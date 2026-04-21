"""
Coder Worklist Service — business logic for the coder review queue.

Responsibilities
----------------
- Retrieve a coder's personalized queue (filtered, priority-sorted).
- Claim the next available item atomically (prevents double-assignment).
- Transition item lifecycle: start → complete / escalate / return.
- Persist coding decisions and QA quality scores.
- Roll-up daily productivity metrics into coder_productivity.
- Auto-queue items from NLP analysis results and claims processing.
- Load-balanced (round-robin) assignment across available coders.

All DB access goes through the ``raf_cursor`` context manager from app.db,
which commits on success and rolls back on exception.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from typing import Any

from app.db import raf_cursor
from app.services.cache_strategy import TTL_WORKLIST, tenant_cached

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Active EMR patient filter
# ---------------------------------------------------------------------------

from app.services.emr_manager import active_patients_subquery  # noqa: E402

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _record_action(
    worklist_id: int,
    user_id: int,
    action: str,
    details: dict[str, Any] | None = None,
) -> None:
    """Append a row to coder_worklist_actions (called inside an open cursor block)."""
    with raf_cursor() as cur:
        cur.execute(
            """
            INSERT INTO coder_worklist_actions (worklist_id, user_id, action, details)
            VALUES (%s, %s, %s, %s)
            """,
            (worklist_id, user_id, action, json.dumps(details) if details else None),
        )


def _fetch_item(worklist_id: int) -> dict[str, Any] | None:
    """Return a single worklist row as a dict, or None if not found."""
    with raf_cursor() as cur:
        cur.execute(
            "SELECT * FROM coder_worklist WHERE id = %s",
            (worklist_id,),
        )
        return cur.fetchone()


# ---------------------------------------------------------------------------
# Queue retrieval
# ---------------------------------------------------------------------------

@tenant_cached("coder_worklist", ttl=TTL_WORKLIST)
def get_worklist(
    coder_user_id: int,
    tenant_id: str,
    status: str | None = None,
    review_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """
    Return the coder's queue, sorted by priority ASC then due_date ASC
    (NULLs last) so the most urgent work surfaces first.

    Parameters
    ----------
    coder_user_id:
        ID of the authenticated coder.
    tenant_id:
        Tenant scope.
    status:
        Optional single-status filter (queued | in_progress | completed |
        returned | escalated).  Pass None for all active items
        (queued + in_progress).
    review_type:
        Optional filter for initial_coding | suspect_review |
        audit_response | recapture.
    limit / offset:
        Pagination.
    """
    _sf, _sp = active_patients_subquery(int(tenant_id))
    conditions: list[str] = ["coder_user_id = %s", "tenant_id = %s", _sf]
    params: list[Any] = [coder_user_id, tenant_id, *_sp]

    if status:
        conditions.append("status = %s")
        params.append(status)
    else:
        # Default: show actionable items only
        conditions.append("status IN ('queued', 'in_progress')")

    if review_type:
        conditions.append("review_type = %s")
        params.append(review_type)

    where = " AND ".join(conditions)

    with raf_cursor() as cur:
        cur.execute(f"SELECT COUNT(*) AS total FROM coder_worklist WHERE {where}", params)
        total = cur.fetchone()["total"]

        cur.execute(
            f"""
            SELECT *
            FROM   coder_worklist
            WHERE  {where}
            ORDER BY
                   priority ASC,
                   due_date IS NULL ASC,
                   due_date ASC,
                   assigned_at ASC
            LIMIT  %s OFFSET %s
            """,
            params + [limit, offset],
        )
        items = cur.fetchall()

    # Deserialise JSON fields for callers
    for item in items:
        if item.get("hcc_codes") and isinstance(item["hcc_codes"], str):
            item["hcc_codes"] = json.loads(item["hcc_codes"])

    return {
        "coder_user_id": coder_user_id,
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": items,
    }


# ---------------------------------------------------------------------------
# Claim next item
# ---------------------------------------------------------------------------

def claim_next(
    coder_user_id: int,
    tenant_id: str,
    review_type: str | None = None,
) -> dict[str, Any] | None:
    """
    Atomically claim the highest-priority queued item for a coder.

    Uses SELECT … FOR UPDATE to prevent race conditions when multiple
    coders refresh their queues simultaneously.

    Returns the claimed worklist item dict, or None when the queue is empty.
    """
    if tenant_id is None:
        raise ValueError(
            "coder_worklist_service.claim_next: tenant_id is required — "
            "refusing to operate without tenant scope (HIPAA multi-tenant isolation)"
        )
    _active_patients_frag, _ap = active_patients_subquery(int(tenant_id))
    with raf_cursor() as cur:
        sql = f"""
            SELECT id
            FROM   coder_worklist
            WHERE  coder_user_id = %s
              AND  tenant_id     = %s
              AND  status        = 'queued'
              AND  {_active_patients_frag}
        """
        params: list[Any] = [coder_user_id, tenant_id, *_ap]

        if review_type:
            sql += " AND review_type = %s"
            params.append(review_type)

        sql += """
            ORDER BY priority ASC,
                     due_date IS NULL ASC,
                     due_date ASC,
                     assigned_at ASC
            LIMIT 1
            FOR UPDATE
        """
        cur.execute(sql, params)
        row = cur.fetchone()
        if not row:
            return None

        item_id = row["id"]
        now = _now()

        cur.execute(
            """
            UPDATE coder_worklist
            SET    status      = 'in_progress',
                   started_at  = %s,
                   updated_at  = %s
            WHERE  id          = %s
            """,
            (now, now, item_id),
        )
        cur.execute("SELECT * FROM coder_worklist WHERE id = %s", (item_id,))
        item = cur.fetchone()

    _record_action(item_id, coder_user_id, "claimed")

    if item and item.get("hcc_codes") and isinstance(item["hcc_codes"], str):
        item["hcc_codes"] = json.loads(item["hcc_codes"])

    return item


# ---------------------------------------------------------------------------
# Start review
# ---------------------------------------------------------------------------

def start_review(
    worklist_id: int,
    coder_user_id: int,
) -> dict[str, Any]:
    """
    Transition a queued item to in_progress and stamp started_at.

    Raises ValueError when the item does not exist, does not belong to
    this coder, or is not in a startable state.
    """
    item = _fetch_item(worklist_id)
    if not item:
        raise ValueError(f"Worklist item {worklist_id} not found")
    if item["coder_user_id"] != coder_user_id:
        raise ValueError(
            f"Worklist item {worklist_id} is not assigned to coder {coder_user_id}"
        )
    if item["status"] not in ("queued", "returned"):
        raise ValueError(
            f"Cannot start item {worklist_id} in status '{item['status']}'"
        )

    now = _now()
    with raf_cursor() as cur:
        cur.execute(
            """
            UPDATE coder_worklist
            SET    status     = 'in_progress',
                   started_at = COALESCE(started_at, %s),
                   updated_at = %s
            WHERE  id         = %s
            """,
            (now, now, worklist_id),
        )

    _record_action(worklist_id, coder_user_id, "started")
    return _fetch_item(worklist_id)


# ---------------------------------------------------------------------------
# Complete review
# ---------------------------------------------------------------------------

def complete_review(
    worklist_id: int,
    coder_user_id: int,
    coding_decisions: list[dict[str, Any]],
    notes: str | None = None,
) -> dict[str, Any]:
    """
    Mark a worklist item as completed and persist the coder's coding decisions.

    Parameters
    ----------
    worklist_id:
        Item to complete.
    coder_user_id:
        Must match coder_worklist.coder_user_id.
    coding_decisions:
        List of decision objects, e.g.:
        [{"hcc": 85, "icd10": "I50.9", "action": "confirm", "rationale": "…"}]
    notes:
        Optional free-text coder notes appended to the item.
    """
    item = _fetch_item(worklist_id)
    if not item:
        raise ValueError(f"Worklist item {worklist_id} not found")
    if item["coder_user_id"] != coder_user_id:
        raise ValueError(
            f"Worklist item {worklist_id} is not assigned to coder {coder_user_id}"
        )
    if item["status"] != "in_progress":
        raise ValueError(
            f"Cannot complete item {worklist_id} in status '{item['status']}' — "
            "item must be in_progress first"
        )

    now = _now()

    with raf_cursor() as cur:
        cur.execute(
            """
            UPDATE coder_worklist
            SET    status       = 'completed',
                   completed_at = %s,
                   updated_at   = %s,
                   notes        = CASE WHEN %s IS NOT NULL THEN %s ELSE notes END
            WHERE  id           = %s
            """,
            (now, now, notes, notes, worklist_id),
        )

    _record_action(
        worklist_id,
        coder_user_id,
        "completed",
        details={"coding_decisions": coding_decisions, "notes": notes},
    )

    # Update daily productivity roll-up
    _update_productivity(coder_user_id, item)

    return _fetch_item(worklist_id)


# ---------------------------------------------------------------------------
# Escalate
# ---------------------------------------------------------------------------

def escalate_item(
    worklist_id: int,
    coder_user_id: int,
    reason: str,
) -> dict[str, Any]:
    """
    Escalate a worklist item to a supervisor.

    Any in_progress or queued item may be escalated.  The status is set to
    'escalated' and a supervisor must re-assign or resolve it.

    Parameters
    ----------
    reason:
        Mandatory text explaining why the item requires supervisor attention.
    """
    item = _fetch_item(worklist_id)
    if not item:
        raise ValueError(f"Worklist item {worklist_id} not found")
    if item["coder_user_id"] != coder_user_id:
        raise ValueError(
            f"Worklist item {worklist_id} is not assigned to coder {coder_user_id}"
        )
    if item["status"] not in ("queued", "in_progress"):
        raise ValueError(
            f"Cannot escalate item {worklist_id} in status '{item['status']}'"
        )
    if not reason or not reason.strip():
        raise ValueError("An escalation reason is required")

    now = _now()
    with raf_cursor() as cur:
        cur.execute(
            """
            UPDATE coder_worklist
            SET    status     = 'escalated',
                   updated_at = %s
            WHERE  id         = %s
            """,
            (now, worklist_id),
        )

    _record_action(
        worklist_id,
        coder_user_id,
        "escalated",
        details={"reason": reason},
    )
    return _fetch_item(worklist_id)


# ---------------------------------------------------------------------------
# Return for additional info
# ---------------------------------------------------------------------------

def return_item(
    worklist_id: int,
    coder_user_id: int,
    reason: str,
) -> dict[str, Any]:
    """
    Return a worklist item because additional clinical information is needed
    before coding can be completed.

    The item reverts to 'returned' status.  A manager can then supply the
    missing information and transition it back to 'queued'.

    Parameters
    ----------
    reason:
        Mandatory text describing what additional information is required.
    """
    item = _fetch_item(worklist_id)
    if not item:
        raise ValueError(f"Worklist item {worklist_id} not found")
    if item["coder_user_id"] != coder_user_id:
        raise ValueError(
            f"Worklist item {worklist_id} is not assigned to coder {coder_user_id}"
        )
    if item["status"] not in ("queued", "in_progress"):
        raise ValueError(
            f"Cannot return item {worklist_id} in status '{item['status']}'"
        )
    if not reason or not reason.strip():
        raise ValueError("A return reason is required")

    now = _now()
    with raf_cursor() as cur:
        cur.execute(
            """
            UPDATE coder_worklist
            SET    status     = 'returned',
                   updated_at = %s
            WHERE  id         = %s
            """,
            (now, worklist_id),
        )

    _record_action(
        worklist_id,
        coder_user_id,
        "returned",
        details={"reason": reason},
    )
    return _fetch_item(worklist_id)


# ---------------------------------------------------------------------------
# Manual assignment (manager)
# ---------------------------------------------------------------------------

def assign_item(
    patient_id: int,
    coder_user_id: int,
    assigning_user_id: int,
    review_type: str = "suspect_review",
    encounter_id: int | None = None,
    priority: int = 3,
    due_date: date | None = None,
    hcc_codes: list[int] | None = None,
    notes: str | None = None,
    tenant_id: str = "",  # Required — empty string will raise below
    source: str = "manual",
) -> dict[str, Any]:
    """
    Create a new worklist item and assign it to a specific coder.

    Called by managers when manually routing work.  Also used internally
    by auto-queue functions.

    Returns the newly created worklist row.
    """
    if not tenant_id:
        raise ValueError(
            "assign_item: tenant_id is required — "
            "refusing to create worklist item without tenant scope (HIPAA multi-tenant isolation)"
        )
    now = _now()
    with raf_cursor() as cur:
        # Validate that the target user exists and has the coder role
        cur.execute(
            "SELECT role FROM users WHERE id = %s AND is_active = 1",
            (coder_user_id,),
        )
        target = cur.fetchone()
        if not target:
            raise ValueError(f"User {coder_user_id} not found or inactive")
        if target["role"] not in ("coder", "admin", "manager"):
            raise ValueError(f"User {coder_user_id} has role '{target['role']}' — only coders, admins, and managers can receive worklist items")

        cur.execute(
            """
            INSERT INTO coder_worklist (
                tenant_id, coder_user_id, patient_id, encounter_id,
                review_type, source, priority, status,
                assigned_at, due_date, hcc_codes, notes,
                created_at, updated_at
            ) VALUES (
                %s, %s, %s, %s,
                %s, %s, %s, 'queued',
                %s, %s, %s, %s,
                %s, %s
            )
            """,
            (
                tenant_id,
                coder_user_id,
                patient_id,
                encounter_id,
                review_type,
                source,
                priority,
                now,
                due_date,
                json.dumps(hcc_codes) if hcc_codes else None,
                notes,
                now,
                now,
            ),
        )
        new_id = cur.lastrowid

    _record_action(
        new_id,
        assigning_user_id,
        "assigned",
        details={
            "patient_id": patient_id,
            "encounter_id": encounter_id,
            "review_type": review_type,
            "priority": priority,
        },
    )
    logger.info(
        "assign_item: created worklist id=%s patient=%s coder=%s type=%s",
        new_id, patient_id, coder_user_id, review_type,
    )
    return _fetch_item(new_id)


# ---------------------------------------------------------------------------
# Auto-queue from NLP / claims
# ---------------------------------------------------------------------------

def auto_queue_from_nlp(
    nlp_results: list[dict[str, Any]],
    assigning_user_id: int,
    tenant_id: str,
) -> dict[str, Any]:
    """
    Feed NLP analysis results into the worklist using round-robin assignment.

    Each entry in *nlp_results* should contain at minimum:
        patient_id   int
        encounter_id int  (optional)
        hcc_codes    list[int]
        priority     int  (optional, default 3)
        due_date     str  ISO-8601 date (optional)

    Coders are selected using :func:`_round_robin_coder`.

    Returns a summary of how many items were queued and any per-item errors.
    """
    queued: list[int] = []
    errors: list[dict[str, Any]] = []

    for entry in nlp_results:
        try:
            patient_id: int = int(entry["patient_id"])
            encounter_id: int | None = (
                int(entry["encounter_id"]) if entry.get("encounter_id") else None
            )
            hcc_codes: list[int] = entry.get("hcc_codes", [])
            priority: int = int(entry.get("priority", 3))
            due_date_raw: str | None = entry.get("due_date")
            due_date: date | None = (
                date.fromisoformat(due_date_raw) if due_date_raw else None
            )

            coder_id = _round_robin_coder(tenant_id)
            if coder_id is None:
                raise RuntimeError("No active coders available for assignment")

            item = assign_item(
                patient_id=patient_id,
                coder_user_id=coder_id,
                assigning_user_id=assigning_user_id,
                review_type="suspect_review",
                encounter_id=encounter_id,
                priority=priority,
                due_date=due_date,
                hcc_codes=hcc_codes,
                source="nlp",
                tenant_id=tenant_id,
            )
            queued.append(item["id"])
        except Exception as exc:
            logger.warning("auto_queue_from_nlp: entry failed: %s — %s", entry, exc)
            errors.append({"entry": entry, "error": str(exc)})

    logger.info(
        "auto_queue_from_nlp: queued=%d errors=%d tenant=%s",
        len(queued), len(errors), tenant_id,
    )
    return {"queued": len(queued), "queued_ids": queued, "errors": errors}


def auto_queue_from_claims(
    claims_results: list[dict[str, Any]],
    assigning_user_id: int,
    tenant_id: str,
) -> dict[str, Any]:
    """
    Feed claims analysis results into the worklist using round-robin assignment.

    Each entry in *claims_results* should contain:
        patient_id   int
        encounter_id int  (optional)
        hcc_codes    list[int]
        priority     int  (optional, default 2 — claims gaps tend to be urgent)
        due_date     str  ISO-8601 date (optional)
    """
    queued: list[int] = []
    errors: list[dict[str, Any]] = []

    for entry in claims_results:
        try:
            patient_id = int(entry["patient_id"])
            encounter_id = (
                int(entry["encounter_id"]) if entry.get("encounter_id") else None
            )
            hcc_codes = entry.get("hcc_codes", [])
            priority = int(entry.get("priority", 2))
            due_date_raw = entry.get("due_date")
            due_date = (
                date.fromisoformat(due_date_raw) if due_date_raw else None
            )

            coder_id = _round_robin_coder(tenant_id)
            if coder_id is None:
                raise RuntimeError("No active coders available for assignment")

            item = assign_item(
                patient_id=patient_id,
                coder_user_id=coder_id,
                assigning_user_id=assigning_user_id,
                review_type="recapture",
                encounter_id=encounter_id,
                priority=priority,
                due_date=due_date,
                hcc_codes=hcc_codes,
                source="claims",
                tenant_id=tenant_id,
            )
            queued.append(item["id"])
        except Exception as exc:
            logger.warning("auto_queue_from_claims: entry failed: %s — %s", entry, exc)
            errors.append({"entry": entry, "error": str(exc)})

    logger.info(
        "auto_queue_from_claims: queued=%d errors=%d tenant=%s",
        len(queued), len(errors), tenant_id,
    )
    return {"queued": len(queued), "queued_ids": queued, "errors": errors}


# ---------------------------------------------------------------------------
# Round-robin / load-balanced coder selection
# ---------------------------------------------------------------------------

def _round_robin_coder(tenant_id: str) -> int | None:
    """
    Select the active coder with the fewest open (queued + in_progress) items.

    This is a load-balanced assignment rather than strict round-robin.
    Returns None if no coders with the 'coder' role are found for the tenant.

    The users table is expected to carry a ``role`` column (see migration 005).
    """
    if tenant_id is None:
        raise ValueError(
            "coder_worklist_service._round_robin_coder: tenant_id is required — "
            "refusing to operate without tenant scope (HIPAA multi-tenant isolation)"
        )
    _active_patients_frag, _ap = active_patients_subquery(
        int(tenant_id), patient_id_column="w.patient_id"
    )
    with raf_cursor() as cur:
        cur.execute(
            f"""
            SELECT u.id,
                   COUNT(w.id) AS open_count
            FROM   users u
            LEFT JOIN coder_worklist w
                   ON w.coder_user_id = u.id
                  AND w.tenant_id     = %s
                  AND w.status        IN ('queued', 'in_progress')
                  AND {_active_patients_frag}
            WHERE  u.role      = 'coder'
              AND  u.is_active = 1
            GROUP BY u.id
            ORDER BY open_count ASC
            LIMIT  1
            """,
            (tenant_id, *_ap),
        )
        row = cur.fetchone()
    return row["id"] if row else None


# ---------------------------------------------------------------------------
# Productivity metrics
# ---------------------------------------------------------------------------

def get_productivity_stats(
    coder_user_id: int,
    tenant_id: str,
    days: int = 30,
) -> dict[str, Any]:
    """
    Return productivity metrics for a coder over the last *days* calendar days.

    Includes:
    - Daily roll-up rows from coder_productivity.
    - Aggregate totals: total_completed, avg_daily_completed, avg_accuracy.
    - Current queue depth (open items).
    """
    with raf_cursor() as cur:
        # Daily history from the pre-aggregated table
        cur.execute(
            """
            SELECT date, reviews_completed, avg_time_minutes, accuracy_rate
            FROM   coder_productivity
            WHERE  coder_user_id = %s
              AND  tenant_id     = %s
              AND  date          >= DATE_SUB(CURDATE(), INTERVAL %s DAY)
            ORDER BY date DESC
            """,
            (coder_user_id, tenant_id, days),
        )
        daily = cur.fetchall()

        # Aggregate totals
        cur.execute(
            """
            SELECT
                COALESCE(SUM(reviews_completed), 0)    AS total_completed,
                COALESCE(AVG(avg_time_minutes),  NULL) AS avg_time_minutes,
                COALESCE(AVG(accuracy_rate),     NULL) AS avg_accuracy_rate
            FROM   coder_productivity
            WHERE  coder_user_id = %s
              AND  tenant_id     = %s
              AND  date          >= DATE_SUB(CURDATE(), INTERVAL %s DAY)
            """,
            (coder_user_id, tenant_id, days),
        )
        agg = cur.fetchone()

        # Current queue depth
        if tenant_id is None:
            raise ValueError(
                "coder_worklist_service.get_productivity_stats: tenant_id is required — "
                "refusing to operate without tenant scope (HIPAA multi-tenant isolation)"
            )
        _active_patients_frag, _ap = active_patients_subquery(int(tenant_id))
        cur.execute(
            f"""
            SELECT COUNT(*) AS open_count
            FROM   coder_worklist
            WHERE  coder_user_id = %s
              AND  tenant_id     = %s
              AND  status        IN ('queued', 'in_progress')
              AND  {_active_patients_frag}
            """,
            (coder_user_id, tenant_id, *_ap),
        )
        queue_depth = cur.fetchone()["open_count"]

    return {
        "coder_user_id": coder_user_id,
        "period_days": days,
        "queue_depth": queue_depth,
        "total_completed": int(agg["total_completed"]),
        "avg_time_minutes": (
            float(agg["avg_time_minutes"]) if agg["avg_time_minutes"] else None
        ),
        "avg_accuracy_rate": (
            float(agg["avg_accuracy_rate"]) if agg["avg_accuracy_rate"] else None
        ),
        "daily": daily,
    }


# ---------------------------------------------------------------------------
# Internal: update daily productivity roll-up after completion
# ---------------------------------------------------------------------------

def _update_productivity(
    coder_user_id: int,
    completed_item: dict[str, Any],
) -> None:
    """
    Upsert a row in coder_productivity for today after an item is completed.

    Recalculates avg_time_minutes from the started_at / completed_at of the
    item just completed.  accuracy_rate is left as-is (updated separately by
    the QA reviewer workflow).
    """
    today = date.today()
    tenant_id: str | None = completed_item.get("tenant_id")
    if not tenant_id:
        raise ValueError(
            "_update_productivity: completed_item has no tenant_id — "
            "refusing to update productivity without tenant scope (HIPAA multi-tenant isolation)"
        )

    started_at = completed_item.get("started_at")
    completed_at = completed_item.get("completed_at") or _now()
    time_minutes: float | None = None
    if started_at:
        if isinstance(started_at, str):
            started_at = datetime.fromisoformat(started_at)
        delta = (
            completed_at - started_at
            if isinstance(completed_at, datetime)
            else datetime.combine(today, datetime.min.time()) - started_at
        )
        time_minutes = delta.total_seconds() / 60.0

    with raf_cursor() as cur:
        # Upsert: increment reviews_completed, recalculate avg_time_minutes
        cur.execute(
            """
            INSERT INTO coder_productivity
                (coder_user_id, tenant_id, date, reviews_completed, avg_time_minutes, created_at, updated_at)
            VALUES
                (%s, %s, %s, 1, %s, NOW(), NOW())
            ON DUPLICATE KEY UPDATE
                reviews_completed = reviews_completed + 1,
                avg_time_minutes  = CASE
                    WHEN %s IS NOT NULL
                    THEN (COALESCE(avg_time_minutes, 0) * reviews_completed + %s)
                         / (reviews_completed + 1)
                    ELSE avg_time_minutes
                END,
                updated_at = NOW()
            """,
            (
                coder_user_id, tenant_id, today,
                time_minutes,
                # ON DUPLICATE KEY params
                time_minutes, time_minutes,
            ),
        )
