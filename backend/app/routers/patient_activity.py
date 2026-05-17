"""
Per-patient activity feed router.

Carry-over from PCP review #8: the chart had no inline "who-did-what-when"
log.  This endpoint surfaces the patient's audit-log timeline so a coder or
clinician can see — without leaving the chart — who created the last
clinical query, who accepted a suspect, who downloaded a RADV packet, etc.

Endpoint
--------
GET /api/patients/{pid}/activity?limit=100&since=...
    Returns a chronological list of audit events touching this patient,
    joined to ``users`` for actor identity. Tenant-scoped — only rows whose
    actor user is in the caller's tenant are returned.

Source tables
-------------
We UNION two complementary audit surfaces so the feed is comprehensive:

1. ``audit_log`` — populated by ``audit_logger.log_phi_access`` (PHI views,
   exports). Has top-level ``patient_id`` and JSON ``details``.
2. ``immutable_audit_log`` — populated by ``immutable_audit.emit_audit_event``
   (clinical-query create, suspect accept/dismiss, audit-package generate).
   Has top-level ``patient_id`` and JSON ``payload_json``.

Filtering rules (per row)
-------------------------
- ``patient_id = pid``                                — primary path
- OR ``resource_id = str(pid)`` (audit_log only)      — legacy rows
- OR ``JSON_EXTRACT(details/payload, '$.patient_id') = pid`` — payload-embedded

This router is read-only — it never writes to ``audit_log`` itself.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.auth import get_current_user, get_tenant_id, require_permission
from app.db import raf_cursor

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/patients", tags=["patient-activity"])


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class ActivityEntry(BaseModel):
    """One row in the per-patient activity feed."""

    id: str = Field(..., description="Stable row id (prefixed with source table)")
    action: str = Field(..., description="Action name, e.g. CLINICAL_QUERY_CREATED")
    actor_email: str | None = Field(default=None, description="Actor's email if known")
    actor_display_name: str | None = Field(
        default=None, description="Actor's full_name, falls back to email-local"
    )
    created_at: str = Field(..., description="ISO-8601 timestamp")
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Free-form payload (JSON-decoded)"
    )
    resource_type: str | None = Field(default=None, description="Resource kind")
    resource_id: str | None = Field(default=None, description="Resource id (string)")


class ActivityResponse(BaseModel):
    """Envelope so the front-end can grow paging metadata without breaking."""

    patient_id: int
    total: int
    items: list[ActivityEntry]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_iso(value: Any) -> str:
    """Render a datetime (or string) as an ISO-8601 string with seconds precision."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            # Assume UTC for naive timestamps coming from MySQL DATETIME.
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat(timespec="seconds")
    return str(value)


def _coerce_metadata(raw: Any) -> dict[str, Any]:
    """Decode the JSON payload column into a plain dict.

    MySQL JSON columns can come back as either a parsed dict (mysql.connector
    with the ``raw=False`` cursor) or a JSON-encoded string (older drivers).
    Both shapes have been observed in prod.
    """
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, (bytes, bytearray)):
        try:
            raw = raw.decode("utf-8", errors="replace")
        except Exception:
            return {}
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {"value": parsed}
        except Exception:
            return {"raw": raw}
    return {}


def _actor_display_name(full_name: str | None, email: str | None) -> str | None:
    """Pick a reasonable display name. Falls back to email-local part."""
    if full_name and full_name.strip():
        return full_name.strip()
    if email and "@" in email:
        return email.split("@", 1)[0]
    return email or None


def _parse_since(since: str | None) -> datetime | None:
    """Parse an ISO-8601 ``since`` query param. Returns None if absent/invalid.

    Accepts trailing ``Z`` (UTC) which Python's fromisoformat does not in 3.10.
    """
    if not since:
        return None
    s = since.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid 'since' timestamp ({since!r}); use ISO-8601",
        ) from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.get(
    "/{pid}/activity",
    response_model=ActivityResponse,
    summary="Per-patient audit-log timeline",
)
def get_patient_activity(
    pid: int,
    limit: int = Query(default=100, ge=1, le=500),
    since: str | None = Query(
        default=None,
        description="ISO-8601 timestamp; only events strictly after this are returned",
    ),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("patients", "read")),
) -> ActivityResponse:
    """Return the audit-log timeline for *pid*, newest first.

    Tenant isolation: the JOIN against ``users.tenant_id`` ensures rows whose
    actor belongs to another tenant are excluded.  Defence-in-depth: we also
    verify *pid* lives in the caller's tenant before issuing the JOIN, so a
    caller cannot probe other tenants' patient ids via this endpoint.
    """
    # ------------------------------------------------------------------
    # Tenant-scope the patient itself before exposing any timeline rows.
    # ------------------------------------------------------------------
    try:
        with raf_cursor() as cur:
            cur.execute(
                "SELECT id FROM patients WHERE id = %s AND tenant_id = %s AND is_active = 1",
                (pid, tenant_id),
            )
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail=f"Patient {pid} not found")
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("activity tenant check failed pid=%s tenant=%s: %s", pid, tenant_id, exc)
        raise HTTPException(status_code=500, detail="Internal server error") from exc

    since_dt = _parse_since(since)

    pid_str = str(pid)

    # ------------------------------------------------------------------
    # Pull from audit_log (JOIN users — only this tenant's actors).
    #
    # We accept three "this row is about pid" signals:
    #   1. al.patient_id = pid                              (top-level column)
    #   2. al.resource_id = '<pid>'                          (string compare)
    #   3. JSON path al.details.patient_id = pid             (legacy / phi rows)
    #
    # The OR triple is wrapped in parentheses so the tenant filter still
    # applies via the JOIN, regardless of which limb matched.
    # ------------------------------------------------------------------
    audit_log_sql = """
        SELECT
            al.id              AS id,
            al.action          AS action,
            al.resource_type   AS resource_type,
            al.resource_id     AS resource_id,
            al.details         AS details,
            al.created_at      AS created_at,
            u.email            AS actor_email,
            u.full_name        AS actor_full_name
        FROM audit_log al
        LEFT JOIN users u ON u.id = al.user_id
        WHERE u.tenant_id = %s
          AND (
                al.patient_id = %s
             OR al.resource_id = %s
             OR JSON_EXTRACT(al.details, '$.patient_id') = %s
             OR JSON_CONTAINS(al.details, CAST(%s AS JSON), '$.patient_id')
          )
    """
    audit_log_params: list[Any] = [tenant_id, pid, pid_str, pid, pid]
    if since_dt is not None:
        audit_log_sql += " AND al.created_at > %s"
        audit_log_params.append(since_dt)
    audit_log_sql += " ORDER BY al.created_at DESC LIMIT %s"
    audit_log_params.append(limit)

    # ------------------------------------------------------------------
    # Pull from immutable_audit_log — clinical-query and similar events
    # never reach audit_log so we must UNION the two surfaces.
    # ------------------------------------------------------------------
    immutable_sql = """
        SELECT
            ial.id              AS id,
            ial.action          AS action,
            ial.event_type      AS event_type,
            ial.resource        AS resource_type,
            ial.payload_json    AS payload_json,
            ial.event_ts        AS created_at,
            ial.actor_email     AS actor_email,
            ial.actor_user_id   AS actor_user_id,
            u.email             AS user_email,
            u.full_name         AS actor_full_name
        FROM immutable_audit_log ial
        LEFT JOIN users u ON u.id = ial.actor_user_id
        WHERE ial.tenant_id = %s
          AND (
                ial.patient_id = %s
             OR JSON_EXTRACT(ial.payload_json, '$.patient_id') = %s
             OR JSON_CONTAINS(ial.payload_json, CAST(%s AS JSON), '$.patient_id')
          )
    """
    immutable_params: list[Any] = [tenant_id, pid, pid, pid]
    if since_dt is not None:
        immutable_sql += " AND ial.event_ts > %s"
        immutable_params.append(since_dt)
    immutable_sql += " ORDER BY ial.event_ts DESC LIMIT %s"
    immutable_params.append(limit)

    items: list[ActivityEntry] = []

    # audit_log
    try:
        with raf_cursor() as cur:
            cur.execute(audit_log_sql, tuple(audit_log_params))
            for row in cur.fetchall() or []:
                metadata = _coerce_metadata(row.get("details"))
                action = row.get("action") or ""
                items.append(
                    ActivityEntry(
                        id=f"al-{row['id']}",
                        action=action,
                        actor_email=row.get("actor_email"),
                        actor_display_name=_actor_display_name(
                            row.get("actor_full_name"), row.get("actor_email")
                        ),
                        created_at=_to_iso(row.get("created_at")),
                        metadata=metadata,
                        resource_type=row.get("resource_type"),
                        resource_id=str(row["resource_id"]) if row.get("resource_id") is not None else None,
                    )
                )
    except Exception as exc:
        # Don't fail the whole endpoint if audit_log is unavailable — log
        # and continue so the immutable_audit_log half still surfaces.
        logger.warning("audit_log query failed for pid=%s: %s", pid, exc)

    # immutable_audit_log
    try:
        with raf_cursor() as cur:
            cur.execute(immutable_sql, tuple(immutable_params))
            for row in cur.fetchall() or []:
                metadata = _coerce_metadata(row.get("payload_json"))
                # immutable_audit's action column often duplicates event_type
                # (emit_audit_event sets both to the same upper-snake string).
                # Prefer ``action`` when present; fall back to event_type.
                action = row.get("action") or row.get("event_type") or ""
                actor_email = row.get("actor_email") or row.get("user_email")
                items.append(
                    ActivityEntry(
                        id=f"ial-{row['id']}",
                        action=action,
                        actor_email=actor_email,
                        actor_display_name=_actor_display_name(
                            row.get("actor_full_name"), actor_email
                        ),
                        created_at=_to_iso(row.get("created_at")),
                        metadata=metadata,
                        resource_type=row.get("resource_type"),
                        # immutable_audit_log has no resource_id column —
                        # surface the subject_id from the payload if present.
                        resource_id=(
                            str(metadata.get("subject_id"))
                            if metadata.get("subject_id") is not None
                            else None
                        ),
                    )
                )
    except Exception as exc:
        logger.warning("immutable_audit_log query failed for pid=%s: %s", pid, exc)

    # Stable sort newest first, then trim to caller-supplied limit.
    items.sort(key=lambda e: e.created_at, reverse=True)
    items = items[:limit]

    return ActivityResponse(patient_id=pid, total=len(items), items=items)
