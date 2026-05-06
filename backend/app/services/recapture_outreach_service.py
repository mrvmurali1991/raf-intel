"""
Recapture Outreach Service.

Tracks the workflow + analytics for member outreach campaigns that surround
recapture gaps.  We don't actually send messages from this service — it
records template definitions and per-gap outreach events so leadership can
measure conversion rate, channel effectiveness, and revenue recovered via
member-direct outreach (SMS, portal nudge, phone callback, email, letter).

Tables (see ``database/migrations/add_recapture_outreach.sql``):
    * recapture_outreach_templates
    * recapture_outreach_events

Lifecycle of an event::

    queued -> sent -> delivered -> responded
                                 \\-> opted_out
                                 \\-> failed

A "conversion" is an event where ``resulted_in_closure = 1``.  The fixed
revenue assumption for closure is shared with ``recapture_gap_service`` —
$3,000 per closed gap.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from app.db import raf_cursor

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Per-closure revenue assumption — keep in sync with recapture_gap_service.
_REVENUE_PER_CLOSURE: float = 3000.00

VALID_CHANNELS: set[str] = {"sms", "portal", "phone", "email", "letter"}
VALID_STATUSES: set[str] = {
    "queued",
    "sent",
    "delivered",
    "responded",
    "failed",
    "opted_out",
}

# Status -> the timestamp column that should be filled when transitioning into it.
_STATUS_TIMESTAMP: dict[str, str | None] = {
    "queued": None,
    "sent": "sent_at",
    "delivered": "delivered_at",
    "responded": "responded_at",
    "failed": None,
    "opted_out": None,
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _dump_json(value: Any) -> str | None:
    """Serialise dict/list to JSON string for storage (None passthrough)."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, separators=(",", ":"), default=str)


def _load_json(value: Any) -> Any:
    """Best-effort JSON load — returns None for empty, value as-is on failure."""
    if value is None or value == "":
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return value


def _iso(value: Any) -> Any:
    """Convert datetime/date to ISO string for JSON output."""
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _serialise_template(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    out["trigger_rules"] = _load_json(out.get("trigger_rules"))
    out["is_active"] = bool(int(out.get("is_active", 0) or 0))
    out["created_at"] = _iso(out.get("created_at"))
    out["updated_at"] = _iso(out.get("updated_at"))
    return out


def _serialise_event(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    out["metadata"] = _load_json(out.get("metadata"))
    out["resulted_in_visit"] = bool(int(out.get("resulted_in_visit", 0) or 0))
    out["resulted_in_closure"] = bool(int(out.get("resulted_in_closure", 0) or 0))
    for k in ("scheduled_for", "sent_at", "delivered_at", "responded_at",
              "created_at", "updated_at"):
        if k in out:
            out[k] = _iso(out.get(k))
    return out


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

def create_template(
    tenant_id: str,
    channel: str,
    name: str,
    message_text: str,
    trigger_rules: dict[str, Any] | None = None,
    subject: str | None = None,
    is_active: bool = True,
) -> dict[str, Any]:
    """Insert a new outreach template and return the persisted row."""
    if channel not in VALID_CHANNELS:
        raise ValueError(
            f"Invalid channel '{channel}'. Allowed: {sorted(VALID_CHANNELS)}"
        )
    if not name or not name.strip():
        raise ValueError("name is required")
    if not message_text or not message_text.strip():
        raise ValueError("message_text is required")

    insert_sql = """
        INSERT INTO recapture_outreach_templates
            (tenant_id, channel, name, subject, message_text, trigger_rules, is_active)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """
    select_sql = """
        SELECT id, tenant_id, channel, name, subject, message_text,
               trigger_rules, is_active, created_at, updated_at
        FROM recapture_outreach_templates
        WHERE id = %s
    """
    with raf_cursor() as cursor:
        cursor.execute(
            insert_sql,
            (
                tenant_id,
                channel,
                name.strip(),
                subject,
                message_text,
                _dump_json(trigger_rules),
                1 if is_active else 0,
            ),
        )
        new_id = cursor.lastrowid
        cursor.execute(select_sql, (new_id,))
        row = cursor.fetchone()

    logger.info(
        "create_template tenant=%s channel=%s name=%s id=%s",
        tenant_id, channel, name, new_id,
    )
    return _serialise_template(row) if row else {"id": new_id}


def list_templates(
    tenant_id: str,
    channel: str | None = None,
    is_active: bool | None = None,
) -> list[dict[str, Any]]:
    """Return templates for a tenant, optionally filtered by channel / active."""
    params: list[Any] = [tenant_id]
    where: list[str] = ["tenant_id = %s"]
    if channel is not None:
        if channel not in VALID_CHANNELS:
            raise ValueError(f"Invalid channel '{channel}'")
        where.append("channel = %s")
        params.append(channel)
    if is_active is not None:
        where.append("is_active = %s")
        params.append(1 if is_active else 0)

    sql = f"""
        SELECT id, tenant_id, channel, name, subject, message_text,
               trigger_rules, is_active, created_at, updated_at
        FROM recapture_outreach_templates
        WHERE {' AND '.join(where)}
        ORDER BY channel, name
    """
    with raf_cursor() as cursor:
        cursor.execute(sql, params)
        rows = cursor.fetchall()
    return [_serialise_template(r) for r in rows]


# Default templates seeded per tenant on first use.
_DEFAULT_TEMPLATES: list[dict[str, Any]] = [
    {
        "channel": "sms",
        "name": "Annual wellness reminder (SMS)",
        "subject": None,
        "message_text": (
            "Hi {first_name}, this is a reminder from your care team. "
            "It's time to schedule your annual wellness visit so we can "
            "review your chronic conditions. Reply YES to be called, or "
            "call us at {clinic_phone}."
        ),
        "trigger_rules": {"min_days_open": 30, "min_revenue": 1000},
    },
    {
        "channel": "portal",
        "name": "Portal nudge — overdue chronic care visit",
        "subject": "Time for your follow-up",
        "message_text": (
            "Hi {first_name}, our records show you may be due for a "
            "follow-up visit for an ongoing condition. Please log in to "
            "schedule, or message us through your patient portal."
        ),
        "trigger_rules": {"min_days_open": 60, "min_revenue": 0},
    },
    {
        "channel": "phone",
        "name": "Phone callback request",
        "subject": None,
        "message_text": (
            "Outbound call script: confirm patient identity, mention "
            "{condition} follow-up is due, offer 3 appointment windows, "
            "and document outcome in the EHR."
        ),
        "trigger_rules": {"min_days_open": 90, "min_revenue": 2000},
    },
]


def seed_default_templates(tenant_id: str) -> list[dict[str, Any]]:
    """Insert the canonical SMS / portal / phone templates if absent.

    Idempotent: an existing template with the same (tenant_id, channel, name)
    is left in place.  Returns the list of templates that exist for the tenant
    after seeding (newly created ones first, then pre-existing).
    """
    existing = {(t["channel"], t["name"]): t for t in list_templates(tenant_id)}
    created: list[dict[str, Any]] = []
    for spec in _DEFAULT_TEMPLATES:
        key = (spec["channel"], spec["name"])
        if key in existing:
            continue
        tpl = create_template(
            tenant_id=tenant_id,
            channel=spec["channel"],
            name=spec["name"],
            message_text=spec["message_text"],
            trigger_rules=spec.get("trigger_rules"),
            subject=spec.get("subject"),
            is_active=True,
        )
        created.append(tpl)
    return created


# ---------------------------------------------------------------------------
# Events — queue / lifecycle
# ---------------------------------------------------------------------------

def queue_outreach(
    tenant_id: str,
    gap_id: int,
    template_id: int | None = None,
    channel: str | None = None,
    scheduled_for: datetime | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a queued outreach event for a gap.

    Either ``template_id`` (preferred — channel inherited) or ``channel`` must
    be supplied.  The template/gap are validated to belong to ``tenant_id``.
    """
    if template_id is None and channel is None:
        raise ValueError("Either template_id or channel is required")
    if channel is not None and channel not in VALID_CHANNELS:
        raise ValueError(f"Invalid channel '{channel}'")

    with raf_cursor() as cursor:
        # Validate gap ownership and pull patient_id
        cursor.execute(
            "SELECT id, patient_id FROM recapture_gaps "
            "WHERE id = %s AND tenant_id = %s",
            (gap_id, tenant_id),
        )
        gap = cursor.fetchone()
        if not gap:
            raise ValueError(f"Gap {gap_id} not found for tenant {tenant_id}")

        resolved_channel = channel
        if template_id is not None:
            cursor.execute(
                "SELECT id, channel FROM recapture_outreach_templates "
                "WHERE id = %s AND tenant_id = %s",
                (template_id, tenant_id),
            )
            tpl = cursor.fetchone()
            if not tpl:
                raise ValueError(
                    f"Template {template_id} not found for tenant {tenant_id}"
                )
            resolved_channel = tpl["channel"]

        cursor.execute(
            """
            INSERT INTO recapture_outreach_events
                (tenant_id, gap_id, patient_id, template_id, channel,
                 status, scheduled_for, metadata)
            VALUES (%s, %s, %s, %s, %s, 'queued', %s, %s)
            """,
            (
                tenant_id,
                gap_id,
                gap["patient_id"],
                template_id,
                resolved_channel,
                scheduled_for,
                _dump_json(metadata),
            ),
        )
        new_id = cursor.lastrowid

        cursor.execute(
            """
            SELECT id, tenant_id, gap_id, patient_id, template_id, channel,
                   status, scheduled_for, sent_at, delivered_at, responded_at,
                   response_text, resulted_in_visit, resulted_in_closure,
                   metadata, created_at, updated_at
            FROM recapture_outreach_events
            WHERE id = %s
            """,
            (new_id,),
        )
        row = cursor.fetchone()

    logger.info(
        "queue_outreach tenant=%s gap=%d channel=%s event=%s",
        tenant_id, gap_id, resolved_channel, new_id,
    )
    return _serialise_event(row) if row else {"id": new_id}


def _update_event_status(
    event_id: int,
    new_status: str,
    extra_sets: list[tuple[str, Any]] | None = None,
) -> dict[str, Any]:
    if new_status not in VALID_STATUSES:
        raise ValueError(
            f"Invalid status '{new_status}'. Allowed: {sorted(VALID_STATUSES)}"
        )

    sets: list[str] = ["status = %s"]
    params: list[Any] = [new_status]

    ts_col = _STATUS_TIMESTAMP.get(new_status)
    if ts_col:
        sets.append(f"{ts_col} = %s")
        params.append(_now())

    for col, val in extra_sets or []:
        sets.append(f"{col} = %s")
        params.append(val)

    params.append(event_id)
    sql = f"""
        UPDATE recapture_outreach_events
           SET {', '.join(sets)}
         WHERE id = %s
    """
    select_sql = """
        SELECT id, tenant_id, gap_id, patient_id, template_id, channel,
               status, scheduled_for, sent_at, delivered_at, responded_at,
               response_text, resulted_in_visit, resulted_in_closure,
               metadata, created_at, updated_at
        FROM recapture_outreach_events
        WHERE id = %s
    """
    with raf_cursor() as cursor:
        cursor.execute(sql, params)
        if cursor.rowcount == 0:
            raise ValueError(f"Outreach event {event_id} not found")
        cursor.execute(select_sql, (event_id,))
        row = cursor.fetchone()

    logger.info("event %d -> %s", event_id, new_status)
    return _serialise_event(row) if row else {"id": event_id}


def mark_sent(event_id: int) -> dict[str, Any]:
    """Transition queued -> sent (sets ``sent_at = now``)."""
    return _update_event_status(event_id, "sent")


def mark_delivered(event_id: int) -> dict[str, Any]:
    """Transition sent -> delivered (sets ``delivered_at = now``)."""
    return _update_event_status(event_id, "delivered")


def mark_response(
    event_id: int,
    response_text: str | None = None,
    resulted_in_visit: bool = False,
    resulted_in_closure: bool = False,
) -> dict[str, Any]:
    """Record a member response.

    Sets status='responded', responded_at=now, and the boolean outcome flags.
    If ``resulted_in_closure=True`` the linked gap is also marked recaptured.
    """
    extras: list[tuple[str, Any]] = [
        ("response_text", response_text),
        ("resulted_in_visit", 1 if resulted_in_visit else 0),
        ("resulted_in_closure", 1 if resulted_in_closure else 0),
    ]
    updated = _update_event_status(event_id, "responded", extra_sets=extras)

    if resulted_in_closure and updated.get("gap_id"):
        # Best-effort: close the underlying gap.  Don't fail the response
        # recording if the gap is already closed or missing.
        try:
            from app.services.recapture_gap_service import close_gap
            close_gap(gap_id=int(updated["gap_id"]), tenant_id=str(updated["tenant_id"]))
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "mark_response: could not close gap_id=%s: %s",
                updated.get("gap_id"), exc,
            )

    return updated


def mark_failed(event_id: int, reason: str | None = None) -> dict[str, Any]:
    """Transition to failed and capture an optional failure reason."""
    extras = [("response_text", reason)] if reason else None
    return _update_event_status(event_id, "failed", extra_sets=extras)


def mark_opted_out(event_id: int) -> dict[str, Any]:
    """Transition to opted_out — terminal status, no more outreach."""
    return _update_event_status(event_id, "opted_out")


def mark_event(
    event_id: int,
    status: str,
    response_text: str | None = None,
    resulted_in_visit: bool = False,
    resulted_in_closure: bool = False,
) -> dict[str, Any]:
    """Polymorphic mark helper used by the router."""
    if status == "sent":
        return mark_sent(event_id)
    if status == "delivered":
        return mark_delivered(event_id)
    if status == "responded":
        return mark_response(
            event_id,
            response_text=response_text,
            resulted_in_visit=resulted_in_visit,
            resulted_in_closure=resulted_in_closure,
        )
    if status == "failed":
        return mark_failed(event_id, reason=response_text)
    if status == "opted_out":
        return mark_opted_out(event_id)
    raise ValueError(
        f"Status '{status}' is not transitionable via mark_event. "
        f"Allowed: sent | delivered | responded | failed | opted_out"
    )


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------

def _build_year_clause(year: int | None) -> tuple[str, list[Any]]:
    if year is None:
        return "", []
    return " AND YEAR(created_at) = %s", [year]


def outreach_summary(tenant_id: str, year: int | None = None) -> dict[str, Any]:
    """Return aggregate outreach metrics for a tenant.

    Shape::

        {
          "year": 2026 | None,
          "total_sent": int,            # events that left 'queued'
          "total_responded": int,
          "total_closed": int,
          "conversion_rate": float,     # closed / sent  (0..1)
          "avg_days_to_response": float | None,
          "estimated_revenue": float,   # closed * $3,000
          "by_channel": {
             "sms":   {"queued":N,"sent":N,"delivered":N,"responded":N,
                       "closed":N,"visit_rate":0..1,"closure_rate":0..1},
             ...
          }
        }
    """
    yr_clause, yr_params = _build_year_clause(year)

    # Per-channel breakdown.  We also count 'failed' / 'opted_out' as having
    # left 'queued', so they're included in "sent" for the conversion-rate
    # denominator (consistent with the engagement funnel).
    channel_sql = f"""
        SELECT
            channel,
            COUNT(*)                                                      AS total,
            SUM(status = 'queued')                                        AS queued,
            SUM(status <> 'queued')                                       AS sent_or_later,
            SUM(status IN ('delivered','responded'))                      AS delivered,
            SUM(status = 'responded')                                     AS responded,
            SUM(resulted_in_visit = 1)                                    AS visits,
            SUM(resulted_in_closure = 1)                                  AS closed
        FROM recapture_outreach_events
        WHERE tenant_id = %s {yr_clause}
        GROUP BY channel
    """
    overall_sql = f"""
        SELECT
            COUNT(*)                                       AS total,
            SUM(status <> 'queued')                        AS sent_or_later,
            SUM(status = 'responded')                      AS responded,
            SUM(resulted_in_closure = 1)                   AS closed,
            AVG(
                CASE
                    WHEN responded_at IS NOT NULL AND sent_at IS NOT NULL
                    THEN TIMESTAMPDIFF(SECOND, sent_at, responded_at) / 86400.0
                END
            )                                              AS avg_days_to_response
        FROM recapture_outreach_events
        WHERE tenant_id = %s {yr_clause}
    """

    params = [tenant_id, *yr_params]
    by_channel: dict[str, dict[str, Any]] = {}
    with raf_cursor() as cursor:
        cursor.execute(channel_sql, params)
        for r in cursor.fetchall():
            sent = int(r["sent_or_later"] or 0)
            responded = int(r["responded"] or 0)
            visits = int(r["visits"] or 0)
            closed = int(r["closed"] or 0)
            by_channel[str(r["channel"])] = {
                "queued":       int(r["queued"] or 0),
                "sent":         sent,
                "delivered":    int(r["delivered"] or 0),
                "responded":    responded,
                "visits":       visits,
                "closed":       closed,
                "response_rate": (responded / sent) if sent else 0.0,
                "visit_rate":    (visits / sent) if sent else 0.0,
                "closure_rate":  (closed / sent) if sent else 0.0,
            }

        cursor.execute(overall_sql, params)
        ovr = cursor.fetchone() or {}

    total_sent = int(ovr.get("sent_or_later") or 0)
    total_responded = int(ovr.get("responded") or 0)
    total_closed = int(ovr.get("closed") or 0)
    avg_days = ovr.get("avg_days_to_response")
    avg_days_f = float(avg_days) if avg_days is not None else None

    conversion_rate = (total_closed / total_sent) if total_sent else 0.0

    return {
        "year": year,
        "total_sent": total_sent,
        "total_responded": total_responded,
        "total_closed": total_closed,
        "conversion_rate": conversion_rate,
        "avg_days_to_response": avg_days_f,
        "estimated_revenue": total_closed * _REVENUE_PER_CLOSURE,
        "by_channel": by_channel,
    }


def get_outreach_history(gap_id: int, tenant_id: str | None = None) -> list[dict[str, Any]]:
    """Return chronological outreach events for a single gap.

    If ``tenant_id`` is provided the query is scoped to that tenant (so a
    user cannot peek at another tenant's events via an enumerated id).
    """
    params: list[Any] = [gap_id]
    where = ["gap_id = %s"]
    if tenant_id is not None:
        where.append("tenant_id = %s")
        params.append(tenant_id)

    sql = f"""
        SELECT
            e.id, e.tenant_id, e.gap_id, e.patient_id, e.template_id,
            e.channel, e.status, e.scheduled_for, e.sent_at, e.delivered_at,
            e.responded_at, e.response_text, e.resulted_in_visit,
            e.resulted_in_closure, e.metadata, e.created_at, e.updated_at,
            t.name AS template_name
        FROM recapture_outreach_events e
        LEFT JOIN recapture_outreach_templates t ON t.id = e.template_id
        WHERE {' AND '.join(where)}
        ORDER BY e.created_at ASC, e.id ASC
    """
    with raf_cursor() as cursor:
        cursor.execute(sql, params)
        rows = cursor.fetchall()
    return [_serialise_event(r) for r in rows]
