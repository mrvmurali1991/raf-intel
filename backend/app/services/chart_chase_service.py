"""
Chart Chase Service
===================
Business logic for managing chart chase requests — outreach campaigns that
track retrieval of missing or incomplete medical records.

Key responsibilities:
  - Full CRUD for ``chart_chase_requests``
  - Attempt logging with auto-escalation after 3 failed attempts
  - Linking received documents to chase requests
  - Dashboard aggregates: open chases, aging buckets, completion rates
  - Bulk chase generation from a list of suspect conditions
  - Template management for fax / email / letter outreach

Database tables used (all in raf_intelligence schema):
  chart_chase_requests, chart_chase_attempts, chart_chase_templates

The service never raises HTTP exceptions — callers (routers) are responsible
for translating ValueError / RuntimeError into appropriate HTTP responses.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from typing import Any

from app.db import raf_cursor

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Number of failed attempts before a chase is automatically escalated
_ESCALATION_THRESHOLD = 3


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _row_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    """Normalise MySQL row types for JSON serialisation.

    mysql-connector returns DATE columns as ``datetime.date`` objects and
    DATETIME columns as ``datetime.datetime`` objects.  JSON serialisation
    requires strings; this helper converts them in-place.
    """
    for key, value in row.items():
        if isinstance(value, (date, datetime)):
            row[key] = value.isoformat()
    return row


def _fetch_chase(chase_id: int) -> dict[str, Any]:
    """Return a single chase request row or raise ValueError if not found."""
    with raf_cursor() as cur:
        cur.execute(
            "SELECT * FROM chart_chase_requests WHERE id = %s",
            (chase_id,),
        )
        row = cur.fetchone()
    if not row:
        raise ValueError(f"Chart chase {chase_id} not found")
    return _row_to_dict(row)


# ---------------------------------------------------------------------------
# Chase Request CRUD
# ---------------------------------------------------------------------------

def list_chases(
    *,
    tenant_id: str = "default",
    status: str | None = None,
    priority: str | None = None,
    patient_id: int | None = None,
    provider_npi: str | None = None,
    reason: str | None = None,
    due_before: date | None = None,
    limit: int = 200,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Return chart chase requests with optional filters.

    All filters are ANDed together.  Results are ordered by priority
    (critical → high → medium → low) then due_date ascending so the most
    urgent overdue chases surface first.
    """
    conditions = ["tenant_id = %s"]
    params: list[Any] = [tenant_id]

    if status:
        conditions.append("status = %s")
        params.append(status)
    if priority:
        conditions.append("priority = %s")
        params.append(priority)
    if patient_id is not None:
        conditions.append("patient_id = %s")
        params.append(patient_id)
    if provider_npi:
        conditions.append("provider_npi = %s")
        params.append(provider_npi)
    if reason:
        conditions.append("reason = %s")
        params.append(reason)
    if due_before:
        conditions.append("due_date <= %s")
        params.append(due_before)

    where = " AND ".join(conditions)
    # Priority ordering via FIELD() ensures deterministic sort across MySQL versions
    sql = f"""
        SELECT * FROM chart_chase_requests
        WHERE {where}
        ORDER BY
            FIELD(priority, 'critical', 'high', 'medium', 'low'),
            due_date ASC
        LIMIT %s OFFSET %s
    """
    params += [limit, offset]

    with raf_cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    return [_row_to_dict(r) for r in rows]


def get_chase(chase_id: int) -> dict[str, Any]:
    """Return a single chase request with its attempt history."""
    chase = _fetch_chase(chase_id)

    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT * FROM chart_chase_attempts
            WHERE chase_id = %s
            ORDER BY attempt_number ASC
            """,
            (chase_id,),
        )
        attempts = [_row_to_dict(r) for r in cur.fetchall()]

    chase["attempts_history"] = attempts
    return chase


def create_chase(data: dict[str, Any]) -> dict[str, Any]:
    """Insert a new chart chase request.

    ``data`` keys mirror the ``chart_chase_requests`` columns.  ``request_date``
    defaults to today when not provided.  Returns the newly created row.
    """
    request_date = data.get("request_date") or date.today()
    hcc_codes = data.get("hcc_codes")
    if hcc_codes is not None and not isinstance(hcc_codes, str):
        hcc_codes = json.dumps(hcc_codes)

    sql = """
        INSERT INTO chart_chase_requests (
            tenant_id, patient_id, provider_npi, requesting_user_id,
            chase_type, reason, hcc_codes,
            dos_from, dos_to,
            status, priority,
            facility_name, facility_fax, facility_email, facility_phone,
            request_date, due_date, notes
        ) VALUES (
            %s, %s, %s, %s,
            %s, %s, %s,
            %s, %s,
            %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s
        )
    """
    params = (
        data.get("tenant_id", "default"),
        data["patient_id"],
        data.get("provider_npi"),
        data["requesting_user_id"],
        data.get("chase_type", "initial"),
        data["reason"],
        hcc_codes,
        data.get("dos_from"),
        data.get("dos_to"),
        data.get("status", "pending"),
        data.get("priority", "medium"),
        data.get("facility_name"),
        data.get("facility_fax"),
        data.get("facility_email"),
        data.get("facility_phone"),
        request_date,
        data.get("due_date"),
        data.get("notes"),
    )

    with raf_cursor() as cur:
        cur.execute(sql, params)
        new_id: int = cur.lastrowid

    logger.info("Created chart chase id=%s patient_id=%s", new_id, data["patient_id"])
    return _fetch_chase(new_id)


def update_chase(chase_id: int, data: dict[str, Any]) -> dict[str, Any]:
    """Update mutable fields on an existing chase request.

    Only the keys present in ``data`` are updated; absent keys are left
    unchanged.  Raises ValueError when the chase does not exist.
    """
    _fetch_chase(chase_id)  # Existence check

    allowed = {
        "chase_type", "reason", "hcc_codes", "dos_from", "dos_to",
        "status", "priority", "facility_name", "facility_fax",
        "facility_email", "facility_phone", "due_date", "notes",
        "provider_npi",
    }
    updates = {k: v for k, v in data.items() if k in allowed}
    if not updates:
        return _fetch_chase(chase_id)

    if "hcc_codes" in updates and updates["hcc_codes"] is not None:
        if not isinstance(updates["hcc_codes"], str):
            updates["hcc_codes"] = json.dumps(updates["hcc_codes"])

    set_clause = ", ".join(f"{col} = %s" for col in updates)
    params = list(updates.values()) + [chase_id]

    with raf_cursor() as cur:
        cur.execute(
            f"UPDATE chart_chase_requests SET {set_clause} WHERE id = %s",
            params,
        )

    logger.info("Updated chart chase id=%s fields=%s", chase_id, list(updates.keys()))
    return _fetch_chase(chase_id)


def cancel_chase(chase_id: int, *, notes: str | None = None) -> dict[str, Any]:
    """Set status to 'cancelled'.  Raises ValueError if chase not found."""
    _fetch_chase(chase_id)
    with raf_cursor() as cur:
        if notes:
            cur.execute(
                "UPDATE chart_chase_requests SET status = 'cancelled', notes = %s WHERE id = %s",
                (notes, chase_id),
            )
        else:
            cur.execute(
                "UPDATE chart_chase_requests SET status = 'cancelled' WHERE id = %s",
                (chase_id,),
            )
    logger.info("Cancelled chart chase id=%s", chase_id)
    return _fetch_chase(chase_id)


# ---------------------------------------------------------------------------
# Attempt Logging & Auto-Escalation
# ---------------------------------------------------------------------------

def log_attempt(
    chase_id: int,
    *,
    method: str,
    sent_by: str,
    response: str | None = None,
    responded_at: datetime | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """Record a new outreach attempt and apply escalation logic if warranted.

    After each attempt the parent chase's ``attempts`` counter and
    ``last_attempt_date`` are refreshed.  When ``attempts`` reaches
    ``_ESCALATION_THRESHOLD`` and the chase is not yet completed or cancelled
    the ``chase_type`` is promoted to ``'escalation'`` automatically.

    Returns the updated chase row (with attempts_history).
    """
    chase = _fetch_chase(chase_id)

    if chase["status"] in ("completed", "cancelled"):
        raise ValueError(
            f"Cannot log an attempt on a {chase['status']} chase (id={chase_id})"
        )

    # Determine next attempt_number
    with raf_cursor() as cur:
        cur.execute(
            "SELECT COALESCE(MAX(attempt_number), 0) AS max_n FROM chart_chase_attempts WHERE chase_id = %s",
            (chase_id,),
        )
        row = cur.fetchone()
    next_attempt_number = int(row["max_n"]) + 1

    # Insert the attempt row
    with raf_cursor() as cur:
        cur.execute(
            """
            INSERT INTO chart_chase_attempts
                (chase_id, attempt_number, method, sent_at, sent_by, response, responded_at, notes)
            VALUES (%s, %s, %s, NOW(), %s, %s, %s, %s)
            """,
            (chase_id, next_attempt_number, method, sent_by, response, responded_at, notes),
        )

    # Update attempt counter and last_attempt_date on the request
    new_attempts = int(chase.get("attempts") or 0) + 1
    new_status = chase["status"]
    new_chase_type = chase["chase_type"]

    # Auto-escalate: if we have hit the threshold and the chase is still in
    # an active pre-escalation state, bump chase_type to 'escalation'
    if (
        new_attempts >= _ESCALATION_THRESHOLD
        and new_chase_type != "escalation"
        and new_status not in ("received", "partial", "completed", "cancelled")
    ):
        new_chase_type = "escalation"
        logger.info(
            "Auto-escalating chase id=%s after %s attempts", chase_id, new_attempts
        )

    # Flip status to 'sent' when logging the first attempt against a pending chase
    if new_status == "pending":
        new_status = "sent"

    with raf_cursor() as cur:
        cur.execute(
            """
            UPDATE chart_chase_requests
            SET attempts = %s,
                last_attempt_date = CURDATE(),
                chase_type = %s,
                status = %s
            WHERE id = %s
            """,
            (new_attempts, new_chase_type, new_status, chase_id),
        )

    return get_chase(chase_id)


# ---------------------------------------------------------------------------
# Document Receipt
# ---------------------------------------------------------------------------

def receive_chase(
    chase_id: int,
    *,
    document_id: int | None = None,
    partial: bool = False,
    received_date: date | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """Mark a chase as received (or partially received) and link a document.

    ``partial=True`` sets status to 'partial'; the chase remains open so
    further follow-up can be logged.  ``partial=False`` (default) sets status
    to 'received'.

    Raises ValueError if the chase does not exist or is already completed /
    cancelled.
    """
    chase = _fetch_chase(chase_id)

    if chase["status"] in ("completed", "cancelled"):
        raise ValueError(
            f"Cannot receive on a {chase['status']} chase (id={chase_id})"
        )

    new_status = "partial" if partial else "received"
    effective_received_date = received_date or date.today()

    with raf_cursor() as cur:
        cur.execute(
            """
            UPDATE chart_chase_requests
            SET status = %s,
                received_date = %s,
                document_id = COALESCE(%s, document_id),
                notes = COALESCE(%s, notes)
            WHERE id = %s
            """,
            (new_status, effective_received_date, document_id, notes, chase_id),
        )

    logger.info(
        "Chase id=%s marked %s; document_id=%s", chase_id, new_status, document_id
    )
    return get_chase(chase_id)


# ---------------------------------------------------------------------------
# Dashboard & Reporting
# ---------------------------------------------------------------------------

def get_dashboard(tenant_id: str = "default") -> dict[str, Any]:
    """Return aggregate statistics for the chart chase dashboard.

    Includes:
    - Open chase counts by status and priority
    - Aging buckets (0-7, 8-14, 15-30, 30+ days since request_date)
    - Completion rate over the last 30 days
    - Average days to receipt for completed chases
    """
    with raf_cursor() as cur:
        # Total open (non-terminal) chases
        cur.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM chart_chase_requests
            WHERE tenant_id = %s AND status NOT IN ('completed', 'cancelled')
            """,
            (tenant_id,),
        )
        open_count = cur.fetchone()["cnt"]

        # Breakdown by status
        cur.execute(
            """
            SELECT status, COUNT(*) AS cnt
            FROM chart_chase_requests
            WHERE tenant_id = %s AND status NOT IN ('completed', 'cancelled')
            GROUP BY status
            """,
            (tenant_id,),
        )
        by_status = {r["status"]: r["cnt"] for r in cur.fetchall()}

        # Breakdown by priority (open only)
        cur.execute(
            """
            SELECT priority, COUNT(*) AS cnt
            FROM chart_chase_requests
            WHERE tenant_id = %s AND status NOT IN ('completed', 'cancelled')
            GROUP BY priority
            """,
            (tenant_id,),
        )
        by_priority = {r["priority"]: r["cnt"] for r in cur.fetchall()}

        # Aging buckets based on days since request_date
        cur.execute(
            """
            SELECT
                SUM(CASE WHEN DATEDIFF(CURDATE(), request_date) BETWEEN 0  AND 7  THEN 1 ELSE 0 END) AS bucket_0_7,
                SUM(CASE WHEN DATEDIFF(CURDATE(), request_date) BETWEEN 8  AND 14 THEN 1 ELSE 0 END) AS bucket_8_14,
                SUM(CASE WHEN DATEDIFF(CURDATE(), request_date) BETWEEN 15 AND 30 THEN 1 ELSE 0 END) AS bucket_15_30,
                SUM(CASE WHEN DATEDIFF(CURDATE(), request_date)  > 30             THEN 1 ELSE 0 END) AS bucket_30_plus
            FROM chart_chase_requests
            WHERE tenant_id = %s AND status NOT IN ('completed', 'cancelled')
            """,
            (tenant_id,),
        )
        aging_row = cur.fetchone()
        aging = {
            "0_7_days":   int(aging_row["bucket_0_7"]    or 0),
            "8_14_days":  int(aging_row["bucket_8_14"]   or 0),
            "15_30_days": int(aging_row["bucket_15_30"]  or 0),
            "over_30_days": int(aging_row["bucket_30_plus"] or 0),
        }

        # Completion rate: completed / (completed + cancelled + open) in last 30 days
        cur.execute(
            """
            SELECT
                SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed,
                COUNT(*) AS total
            FROM chart_chase_requests
            WHERE tenant_id = %s AND request_date >= CURDATE() - INTERVAL 30 DAY
            """,
            (tenant_id,),
        )
        comp_row = cur.fetchone()
        completed_30d = int(comp_row["completed"] or 0)
        total_30d = int(comp_row["total"] or 0)
        completion_rate = round(completed_30d / total_30d * 100, 1) if total_30d else 0.0

        # Average days to receipt for completed chases (all time)
        cur.execute(
            """
            SELECT AVG(DATEDIFF(received_date, request_date)) AS avg_days
            FROM chart_chase_requests
            WHERE tenant_id = %s
              AND status IN ('received', 'completed')
              AND received_date IS NOT NULL
            """,
            (tenant_id,),
        )
        avg_row = cur.fetchone()
        avg_days_to_receipt = (
            round(float(avg_row["avg_days"]), 1) if avg_row["avg_days"] else None
        )

        # Overdue: due_date in the past and not terminal
        cur.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM chart_chase_requests
            WHERE tenant_id = %s
              AND due_date < CURDATE()
              AND status NOT IN ('completed', 'cancelled', 'received')
            """,
            (tenant_id,),
        )
        overdue_count = cur.fetchone()["cnt"]

    return {
        "open_chases": open_count,
        "overdue_chases": overdue_count,
        "by_status": by_status,
        "by_priority": by_priority,
        "aging": aging,
        "completion_rate_30d_pct": completion_rate,
        "completed_last_30d": completed_30d,
        "avg_days_to_receipt": avg_days_to_receipt,
    }


# ---------------------------------------------------------------------------
# Bulk Chase Generation
# ---------------------------------------------------------------------------

def bulk_create_chases(
    items: list[dict[str, Any]],
    *,
    requesting_user_id: int,
    tenant_id: str = "default",
    default_priority: str = "medium",
    default_due_days: int = 30,
) -> dict[str, Any]:
    """Create multiple chase requests in a single call.

    Each item in ``items`` must include at minimum ``patient_id`` and
    ``reason``.  Optional per-item fields follow the same schema as
    ``create_chase``.

    Returns a summary dict with ``created``, ``failed``, and ``errors``.
    """
    created: list[int] = []
    errors: list[dict[str, Any]] = []

    for idx, item in enumerate(items):
        try:
            if "patient_id" not in item:
                raise ValueError("patient_id is required")
            if "reason" not in item:
                raise ValueError("reason is required")

            item.setdefault("tenant_id", tenant_id)
            item.setdefault("requesting_user_id", requesting_user_id)
            item.setdefault("priority", default_priority)
            item.setdefault("chase_type", "initial")
            if "due_date" not in item:
                item["due_date"] = (date.today() + timedelta(days=default_due_days)).isoformat()

            row = create_chase(item)
            created.append(row["id"])
        except Exception as exc:
            logger.warning("bulk_create_chases: item[%s] failed: %s", idx, exc)
            errors.append({"index": idx, "item": item, "error": str(exc)})

    return {
        "requested": len(items),
        "created": len(created),
        "failed": len(errors),
        "created_ids": created,
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# Template Management
# ---------------------------------------------------------------------------

def list_templates(tenant_id: str = "default") -> list[dict[str, Any]]:
    """Return all templates for a tenant, ordered by type then name."""
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT * FROM chart_chase_templates
            WHERE tenant_id = %s
            ORDER BY type, name
            """,
            (tenant_id,),
        )
        rows = cur.fetchall()
    return [_row_to_dict(r) for r in rows]


def create_template(data: dict[str, Any]) -> dict[str, Any]:
    """Insert a new outreach template.  Returns the created row."""
    sql = """
        INSERT INTO chart_chase_templates (tenant_id, name, type, subject, body)
        VALUES (%s, %s, %s, %s, %s)
    """
    params = (
        data.get("tenant_id", "default"),
        data["name"],
        data["type"],
        data.get("subject"),
        data["body"],
    )

    with raf_cursor() as cur:
        cur.execute(sql, params)
        new_id: int = cur.lastrowid

    with raf_cursor() as cur:
        cur.execute("SELECT * FROM chart_chase_templates WHERE id = %s", (new_id,))
        row = cur.fetchone()

    logger.info("Created chart chase template id=%s name=%s", new_id, data["name"])
    return _row_to_dict(row)


def get_template(template_id: int) -> dict[str, Any]:
    """Return a single template or raise ValueError if not found."""
    with raf_cursor() as cur:
        cur.execute(
            "SELECT * FROM chart_chase_templates WHERE id = %s", (template_id,)
        )
        row = cur.fetchone()
    if not row:
        raise ValueError(f"Template {template_id} not found")
    return _row_to_dict(row)
