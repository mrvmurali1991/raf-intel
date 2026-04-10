"""
Care Gap Closure Workflow service.

Handles:
- CRUD for care_gap_tasks with multi-dimensional filtering
- Status transition validation and lifecycle management
- Task assignment (single and bulk) with history recording
- Comment management
- Dashboard / summary statistics by provider and tenant
- Auto-generation of gap tasks from raf_suspect_conditions

Tables used (raf_intelligence DB):
  care_gap_tasks, care_gap_comments, care_gap_history

Read-only join sources:
  raf_suspect_conditions (gap auto-generation)
  providers              (validation / display names)
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

from app.db import raf_cursor

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Active EMR patient filter
# ---------------------------------------------------------------------------

from app.services.emr_manager import ACTIVE_PATIENTS_SUBQUERY  # noqa: E402

# ---------------------------------------------------------------------------
# Valid status transition graph
# ---------------------------------------------------------------------------

# Maps each status to the set of statuses that may follow it.
_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "open": {"in_progress", "scheduled", "rejected"},
    "in_progress": {"scheduled", "completed", "rejected", "open"},
    "scheduled": {"in_progress", "completed", "rejected", "open"},
    "completed": set(),  # terminal — no further transitions
    "rejected": {"open"},  # can be re-opened
}

# Statuses that represent a terminal/closed state
_CLOSED_STATUSES = {"completed", "rejected"}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _record_history(
    cur,
    task_id: int,
    action: str,
    user_id: int,
    old_status: str | None = None,
    new_status: str | None = None,
    note: str | None = None,
) -> None:
    """Insert one row into care_gap_history.  Must be called within an open cursor."""
    cur.execute(
        """
        INSERT INTO care_gap_history
            (task_id, action, old_status, new_status, user_id, note)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (task_id, action, old_status, new_status, user_id, note),
    )


def _fetch_task(cur, task_id: int) -> dict[str, Any] | None:
    """Return a single task row as a dict, or None if not found."""
    cur.execute(
        "SELECT * FROM care_gap_tasks WHERE id = %s",
        (task_id,),
    )
    return cur.fetchone()


# ---------------------------------------------------------------------------
# CRUD — tasks
# ---------------------------------------------------------------------------


def list_gap_tasks(
    *,
    provider_id: int | None = None,
    assigned_to: int | None = None,
    patient_id: int | None = None,
    status: str | None = None,
    priority: str | None = None,
    gap_type: str | None = None,
    due_before: date | None = None,
    due_after: date | None = None,
    tenant_id: str = "default",
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Return care gap tasks filtered by the supplied criteria."""
    conditions: list[str] = ["tenant_id = %s", ACTIVE_PATIENTS_SUBQUERY]
    params: list[Any] = [tenant_id]

    if provider_id is not None:
        conditions.append("provider_id = %s")
        params.append(provider_id)
    if assigned_to is not None:
        conditions.append("assigned_to = %s")
        params.append(assigned_to)
    if patient_id is not None:
        conditions.append("patient_id = %s")
        params.append(patient_id)
    if status is not None:
        conditions.append("status = %s")
        params.append(status)
    if priority is not None:
        conditions.append("priority = %s")
        params.append(priority)
    if gap_type is not None:
        conditions.append("gap_type = %s")
        params.append(gap_type)
    if due_before is not None:
        conditions.append("due_date <= %s")
        params.append(due_before)
    if due_after is not None:
        conditions.append("due_date >= %s")
        params.append(due_after)

    where = " AND ".join(conditions)
    params.extend([limit, offset])

    with raf_cursor() as cur:
        cur.execute(
            f"""
            SELECT * FROM care_gap_tasks
            WHERE {where}
            ORDER BY
                FIELD(priority, 'critical', 'high', 'medium', 'low'),
                due_date ASC,
                created_at DESC
            LIMIT %s OFFSET %s
            """,
            params,
        )
        return cur.fetchall() or []


def get_gap_task(task_id: int) -> dict[str, Any] | None:
    """Return a single gap task by primary key, or None."""
    with raf_cursor() as cur:
        return _fetch_task(cur, task_id)


def create_gap_task(
    *,
    patient_id: int,
    provider_id: int,
    hcc_code: str,
    hcc_description: str = "",
    gap_type: str = "suspect",
    priority: str = "medium",
    due_date: date | None = None,
    notes: str | None = None,
    evidence_summary: str | None = None,
    assigned_to: int | None = None,
    suspect_condition_id: int | None = None,
    created_by: int | None = None,
    tenant_id: str = "default",
) -> dict[str, Any]:
    """Create a new care gap task and record the creation event in history."""
    with raf_cursor() as cur:
        cur.execute(
            """
            INSERT INTO care_gap_tasks
                (patient_id, provider_id, hcc_code, hcc_description, gap_type,
                 priority, due_date, notes, evidence_summary, assigned_to,
                 suspect_condition_id, created_by, tenant_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                patient_id,
                provider_id,
                hcc_code,
                hcc_description,
                gap_type,
                priority,
                due_date,
                notes,
                evidence_summary,
                assigned_to,
                suspect_condition_id,
                created_by,
                tenant_id,
            ),
        )
        task_id: int = cur.lastrowid

        _record_history(
            cur,
            task_id,
            "created",
            user_id=created_by or 0,
            new_status="open",
        )

        task = _fetch_task(cur, task_id)

    logger.info(
        "care_gap: created task id=%s patient=%s hcc=%s", task_id, patient_id, hcc_code
    )
    return task


def update_gap_task(
    task_id: int,
    updates: dict[str, Any],
    user_id: int,
) -> dict[str, Any] | None:
    """
    Partial update of a gap task.  Only the fields present in *updates* are
    written.  Status and assignment changes should use the dedicated functions;
    this function rejects them to keep audit trails clean.
    """
    # Disallow direct status/assignment changes via generic update
    updates.pop("status", None)
    updates.pop("assigned_to", None)
    updates.pop("id", None)
    updates.pop("created_at", None)
    updates.pop("tenant_id", None)

    if not updates:
        with raf_cursor() as cur:
            return _fetch_task(cur, task_id)

    set_clause = ", ".join(f"{col} = %s" for col in updates)
    params = list(updates.values()) + [task_id]

    with raf_cursor() as cur:
        cur.execute(
            f"UPDATE care_gap_tasks SET {set_clause} WHERE id = %s",
            params,
        )
        _record_history(cur, task_id, "updated", user_id=user_id)
        return _fetch_task(cur, task_id)


# ---------------------------------------------------------------------------
# Assignment
# ---------------------------------------------------------------------------


def assign_gap_task(
    task_id: int,
    assigned_to: int,
    user_id: int,
    note: str | None = None,
) -> dict[str, Any] | None:
    """Assign (or re-assign) a gap task to a user."""
    with raf_cursor() as cur:
        task = _fetch_task(cur, task_id)
        if not task:
            return None

        cur.execute(
            "UPDATE care_gap_tasks SET assigned_to = %s WHERE id = %s",
            (assigned_to, task_id),
        )
        _record_history(
            cur,
            task_id,
            "assigned",
            user_id=user_id,
            old_status=task["status"],
            new_status=task["status"],
            note=note or f"assigned to user {assigned_to}",
        )
        return _fetch_task(cur, task_id)


def bulk_assign_gap_tasks(
    task_ids: list[int],
    assigned_to: int,
    user_id: int,
) -> dict[str, Any]:
    """Assign multiple gap tasks to the same user in a single transaction."""
    succeeded: list[int] = []
    failed: list[dict[str, Any]] = []

    with raf_cursor() as cur:
        for tid in task_ids:
            try:
                task = _fetch_task(cur, tid)
                if not task:
                    failed.append({"task_id": tid, "error": "not found"})
                    continue
                cur.execute(
                    "UPDATE care_gap_tasks SET assigned_to = %s WHERE id = %s",
                    (assigned_to, tid),
                )
                _record_history(
                    cur,
                    tid,
                    "bulk_assigned",
                    user_id=user_id,
                    note=f"bulk assigned to user {assigned_to}",
                )
                succeeded.append(tid)
            except Exception as exc:
                logger.warning("bulk_assign: task_id=%s failed: %s", tid, exc)
                failed.append({"task_id": tid, "error": str(exc)})

    return {
        "assigned_to": assigned_to,
        "requested": len(task_ids),
        "succeeded": len(succeeded),
        "failed": len(failed),
        "succeeded_ids": succeeded,
        "errors": failed,
    }


# ---------------------------------------------------------------------------
# Status transitions
# ---------------------------------------------------------------------------


def transition_status(
    task_id: int,
    new_status: str,
    user_id: int,
    note: str | None = None,
) -> dict[str, Any]:
    """
    Move a gap task to *new_status* after validating the transition is allowed.

    Raises ValueError for invalid transitions or missing tasks.
    """
    with raf_cursor() as cur:
        task = _fetch_task(cur, task_id)
        if not task:
            raise ValueError(f"Care gap task {task_id} not found")

        old_status: str = task["status"]

        allowed = _ALLOWED_TRANSITIONS.get(old_status, set())
        if new_status not in allowed:
            raise ValueError(
                f"Transition from '{old_status}' to '{new_status}' is not allowed. "
                f"Allowed next states: {sorted(allowed) or 'none (terminal state)'}"
            )

        completed_at_clause = ""
        extra_params: list[Any] = []
        if new_status in _CLOSED_STATUSES:
            completed_at_clause = ", completed_at = NOW()"
        elif old_status in _CLOSED_STATUSES:
            # Re-opening a closed task clears the completed_at
            completed_at_clause = ", completed_at = NULL"

        cur.execute(
            f"UPDATE care_gap_tasks SET status = %s {completed_at_clause} WHERE id = %s",
            [new_status] + extra_params + [task_id],
        )

        _record_history(
            cur,
            task_id,
            "status_changed",
            user_id=user_id,
            old_status=old_status,
            new_status=new_status,
            note=note,
        )

        updated = _fetch_task(cur, task_id)

    logger.info(
        "care_gap: task=%s status %s -> %s by user=%s",
        task_id,
        old_status,
        new_status,
        user_id,
    )
    return updated


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------


def add_comment(
    task_id: int,
    user_id: int,
    comment: str,
) -> dict[str, Any]:
    """Add a comment to a gap task and return the new comment record."""
    with raf_cursor() as cur:
        # Verify the task exists
        task = _fetch_task(cur, task_id)
        if not task:
            raise ValueError(f"Care gap task {task_id} not found")

        cur.execute(
            "INSERT INTO care_gap_comments (task_id, user_id, comment) VALUES (%s, %s, %s)",
            (task_id, user_id, comment),
        )
        comment_id: int = cur.lastrowid

        _record_history(
            cur,
            task_id,
            "commented",
            user_id=user_id,
            note=f"comment id={comment_id}",
        )

        cur.execute(
            "SELECT * FROM care_gap_comments WHERE id = %s",
            (comment_id,),
        )
        return cur.fetchone()


def get_comments(task_id: int) -> list[dict[str, Any]]:
    """Return all comments for a gap task, oldest first."""
    with raf_cursor() as cur:
        cur.execute(
            "SELECT * FROM care_gap_comments WHERE task_id = %s ORDER BY created_at ASC",
            (task_id,),
        )
        return cur.fetchall() or []


def get_history(task_id: int) -> list[dict[str, Any]]:
    """Return the full audit history for a gap task, newest first."""
    with raf_cursor() as cur:
        cur.execute(
            "SELECT * FROM care_gap_history WHERE task_id = %s ORDER BY created_at DESC",
            (task_id,),
        )
        return cur.fetchall() or []


# ---------------------------------------------------------------------------
# Dashboard statistics
# ---------------------------------------------------------------------------


def get_dashboard_stats(
    *,
    provider_id: int | None = None,
    tenant_id: str = "default",
) -> dict[str, Any]:
    """
    Return summary counts for the care gap dashboard.

    When *provider_id* is supplied the statistics are scoped to that provider's
    tasks.  Otherwise aggregate statistics across all providers are returned.

    Includes:
    - Total tasks by status (open / in_progress / scheduled / completed / rejected)
    - Overdue count (due_date < today AND status not closed)
    - Breakdown by priority
    - Breakdown by gap_type
    - Top 10 providers by open task count (aggregate view only)
    """
    base_conditions = ["tenant_id = %s", ACTIVE_PATIENTS_SUBQUERY]
    base_params: list[Any] = [tenant_id]
    if provider_id is not None:
        base_conditions.append("provider_id = %s")
        base_params.append(provider_id)
    where = " AND ".join(base_conditions)

    with raf_cursor() as cur:
        # Status breakdown
        cur.execute(
            f"""
            SELECT status, COUNT(*) AS cnt
            FROM care_gap_tasks
            WHERE {where}
            GROUP BY status
            """,
            base_params,
        )
        status_rows = cur.fetchall() or []
        by_status: dict[str, int] = {r["status"]: r["cnt"] for r in status_rows}

        # Priority breakdown (open + in_progress only)
        cur.execute(
            f"""
            SELECT priority, COUNT(*) AS cnt
            FROM care_gap_tasks
            WHERE {where} AND status IN ('open','in_progress','scheduled')
            GROUP BY priority
            """,
            base_params,
        )
        priority_rows = cur.fetchall() or []
        by_priority: dict[str, int] = {r["priority"]: r["cnt"] for r in priority_rows}

        # Gap type breakdown
        cur.execute(
            f"""
            SELECT gap_type, COUNT(*) AS cnt
            FROM care_gap_tasks
            WHERE {where}
            GROUP BY gap_type
            """,
            base_params,
        )
        type_rows = cur.fetchall() or []
        by_gap_type: dict[str, int] = {r["gap_type"]: r["cnt"] for r in type_rows}

        # Overdue (past due_date, not yet closed)
        today = date.today().isoformat()
        cur.execute(
            f"""
            SELECT COUNT(*) AS cnt
            FROM care_gap_tasks
            WHERE {where}
              AND due_date < %s
              AND status NOT IN ('completed','rejected')
            """,
            base_params + [today],
        )
        overdue: int = (cur.fetchone() or {}).get("cnt", 0)

        # Top providers by open tasks (aggregate view only)
        top_providers: list[dict[str, Any]] = []
        if provider_id is None:
            cur.execute(
                f"""
                SELECT provider_id, COUNT(*) AS open_tasks
                FROM care_gap_tasks
                WHERE tenant_id = %s AND {ACTIVE_PATIENTS_SUBQUERY} AND status IN ('open','in_progress','scheduled')
                GROUP BY provider_id
                ORDER BY open_tasks DESC
                LIMIT 10
                """,
                [tenant_id],
            )
            top_providers = cur.fetchall() or []

    total = sum(by_status.values())
    open_count = by_status.get("open", 0)
    in_progress_count = by_status.get("in_progress", 0)
    scheduled_count = by_status.get("scheduled", 0)
    completed_count = by_status.get("completed", 0)
    rejected_count = by_status.get("rejected", 0)

    result: dict[str, Any] = {
        "total": total,
        "open": open_count,
        "in_progress": in_progress_count,
        "scheduled": scheduled_count,
        "completed": completed_count,
        "rejected": rejected_count,
        "overdue": overdue,
        "active": open_count + in_progress_count + scheduled_count,
        "closure_rate": (
            round(
                completed_count
                / (
                    completed_count
                    + rejected_count
                    + open_count
                    + in_progress_count
                    + scheduled_count
                ),
                4,
            )
            if total > 0
            else 0.0
        ),
        "by_priority": by_priority,
        "by_gap_type": by_gap_type,
    }
    if provider_id is None:
        result["top_providers_by_open_tasks"] = top_providers

    return result


# ---------------------------------------------------------------------------
# Auto-generate gap tasks from raf_suspect_conditions
# ---------------------------------------------------------------------------


def generate_gaps_from_suspects(
    *,
    provider_id: int | None = None,
    patient_id: int | None = None,
    min_confidence: float = 0.5,
    priority_threshold: float = 0.8,
    created_by: int | None = None,
    tenant_id: str = "default",
) -> dict[str, Any]:
    """
    Query ``raf_suspect_conditions`` for open suspects and create gap tasks for
    any that do not already have an associated task.

    Rules:
    - Only suspects with ``status = 'open'`` are considered.
    - Suspects with ``confidence_score >= priority_threshold`` get priority
      'high'; others get 'medium'.
    - If ``provider_id`` is supplied, patients not in the provider's panel are
      skipped.
    - Existing tasks for the same (patient_id, suspect_condition_id) are not
      duplicated.

    Returns a summary dict with counts of created and skipped tasks.
    """
    conditions: list[str] = [
        "sc.status = 'open'",
        "sc.confidence_score >= %s",
        ACTIVE_PATIENTS_SUBQUERY.replace("patient_id IN", "sc.patient_id IN"),
    ]
    params: list[Any] = [min_confidence]

    if patient_id is not None:
        conditions.append("sc.patient_id = %s")
        params.append(patient_id)

    if provider_id is not None:
        # Only patients attributed to this provider
        conditions.append(
            "sc.patient_id IN (SELECT patient_id FROM provider_patient_panel WHERE provider_id = %s)"
        )
        params.append(provider_id)

    where = " AND ".join(conditions)

    created_count = 0
    skipped_count = 0
    errors: list[dict[str, Any]] = []

    with raf_cursor() as cur:
        cur.execute(
            f"""
            SELECT sc.id              AS suspect_id,
                   sc.patient_id,
                   sc.suspect_hcc     AS hcc_code,
                   sc.suspect_icd10   AS icd10_code,
                   sc.evidence_type,
                   sc.confidence_score,
                   sc.evidence_detail
            FROM raf_suspect_conditions sc
            WHERE {where}
            ORDER BY sc.confidence_score DESC
            """,
            params,
        )
        suspects: list[dict[str, Any]] = cur.fetchall() or []

        # Build set of already-linked suspect IDs to avoid duplicates
        if suspects:
            suspect_ids = [s["suspect_id"] for s in suspects]
            fmt = ",".join(["%s"] * len(suspect_ids))
            cur.execute(
                f"SELECT suspect_condition_id FROM care_gap_tasks WHERE suspect_condition_id IN ({fmt})",
                suspect_ids,
            )
            existing_ids: set[int] = {
                row["suspect_condition_id"]
                for row in (cur.fetchall() or [])
                if row["suspect_condition_id"]
            }
        else:
            existing_ids = set()

        for suspect in suspects:
            sid: int = suspect["suspect_id"]
            if sid in existing_ids:
                skipped_count += 1
                continue

            # Determine provider: use supplied or look up from panel
            target_provider: int | None = provider_id
            if target_provider is None:
                cur.execute(
                    """
                    SELECT provider_id
                    FROM provider_patient_panel
                    WHERE patient_id = %s
                    ORDER BY assigned_at DESC
                    LIMIT 1
                    """,
                    (suspect["patient_id"],),
                )
                panel_row = cur.fetchone()
                if panel_row:
                    target_provider = panel_row["provider_id"]
                else:
                    # No provider assignment — skip
                    skipped_count += 1
                    logger.debug(
                        "generate_gaps: patient=%s suspect=%s skipped (no provider panel)",
                        suspect["patient_id"],
                        sid,
                    )
                    continue

            priority = (
                "high"
                if float(suspect.get("confidence_score") or 0) >= priority_threshold
                else "medium"
            )

            evidence_detail = suspect.get("evidence_detail") or {}
            evidence_summary = (
                f"Evidence type: {suspect.get('evidence_type', 'unknown')}. "
                f"Confidence: {float(suspect.get('confidence_score') or 0):.1%}. "
                f"ICD-10: {suspect.get('icd10_code', '')}."
            )

            try:
                cur.execute(
                    """
                    INSERT INTO care_gap_tasks
                        (patient_id, provider_id, hcc_code, hcc_description,
                         gap_type, priority, evidence_summary,
                         suspect_condition_id, created_by, tenant_id)
                    VALUES (%s, %s, %s, %s, 'suspect', %s, %s, %s, %s, %s)
                    """,
                    (
                        suspect["patient_id"],
                        target_provider,
                        str(suspect.get("hcc_code") or ""),
                        f"HCC {suspect.get('hcc_code', '')} — auto-generated from suspect",
                        priority,
                        evidence_summary,
                        sid,
                        created_by or 0,
                        tenant_id,
                    ),
                )
                new_task_id: int = cur.lastrowid
                _record_history(
                    cur,
                    new_task_id,
                    "auto_generated",
                    user_id=created_by or 0,
                    new_status="open",
                    note=f"auto-generated from suspect_condition {sid}",
                )
                created_count += 1
                logger.info(
                    "generate_gaps: created task=%s from suspect=%s patient=%s",
                    new_task_id,
                    sid,
                    suspect["patient_id"],
                )
            except Exception as exc:
                logger.warning(
                    "generate_gaps: suspect=%s failed: %s",
                    sid,
                    exc,
                )
                errors.append({"suspect_id": sid, "error": str(exc)})

    return {
        "suspects_evaluated": len(suspects),
        "tasks_created": created_count,
        "skipped_already_exists": skipped_count,
        "errors": errors,
    }
