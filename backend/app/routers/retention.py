# Note: do NOT use 'from __future__ import annotations' here —
# it breaks FastAPI/Pydantic schema generation (ForwardRef errors in /openapi.json).

"""
Admin endpoints for HIPAA data-retention management.

All routes are prefixed with /api/admin/retention and require an
authenticated user.  In a production deployment you should add
role-based access control (e.g. require an "admin" role) before
these endpoints are reachable.
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth import get_current_user, require_role
from app.services.data_retention import (
    DEFAULT_POLICIES,
    get_retention_status,
    run_retention_sweep,
    update_retention_policy,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/retention", tags=["admin"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class RetentionUpdateRequest(BaseModel):
    retention_days: int = Field(
        ...,
        ge=1,
        description="New retention period in days (must be >= 1)",
    )


# ---------------------------------------------------------------------------
# GET /api/admin/retention
# ---------------------------------------------------------------------------


@router.get(
    "",
    summary="Get data-retention status for all tables",
    response_model=dict[str, Any],
)
def get_retention_status_endpoint(
    current_user: dict = Depends(require_role("admin")),
) -> dict[str, Any]:
    """
    Return the current retention status for every configured policy table.

    Each entry includes the retention period, total row count, oldest record
    date, and the number of rows currently eligible for purge.
    """
    try:
        statuses = get_retention_status()
        return {
            "policies": statuses,
            "total_tables": len(statuses),
            "known_tables": [p.table_name for p in DEFAULT_POLICIES],
        }
    except Exception as exc:
        logger.error("Failed to retrieve retention status: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500, detail="Failed to retrieve retention status"
        )


# ---------------------------------------------------------------------------
# POST /api/admin/retention/sweep
# ---------------------------------------------------------------------------


@router.post(
    "/sweep",
    summary="Manually trigger a data-retention sweep",
    response_model=dict[str, Any],
)
def trigger_retention_sweep(
    current_user: dict = Depends(require_role("admin")),
) -> dict[str, Any]:
    """
    Immediately execute a retention sweep across all policy tables.

    Deletes rows older than each table's configured retention period.
    Returns per-table deleted row counts and a grand total.

    This endpoint is idempotent — running it multiple times in succession
    deletes only the rows that exist at the time of each call.
    """
    logger.info(
        "Manual retention sweep triggered by user %s",
        current_user.get("sub") or current_user.get("username", "unknown"),
    )
    try:
        result = run_retention_sweep()
        return result
    except Exception as exc:
        logger.error("Manual retention sweep failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Retention sweep failed")


# ---------------------------------------------------------------------------
# PUT /api/admin/retention/{table}
# ---------------------------------------------------------------------------


@router.put(
    "/{table}",
    summary="Update the retention period for a specific table",
    response_model=dict[str, Any],
)
def update_table_retention(
    table: str,
    body: RetentionUpdateRequest,
    current_user: dict = Depends(require_role("admin")),
) -> dict[str, Any]:
    """
    Override the in-process retention period for *table*.

    The override takes effect immediately for the next scheduled or manual
    sweep.  It does **not** persist across process restarts — set the
    corresponding environment variable for a permanent change:

    | Table                  | Env var                        |
    |------------------------|--------------------------------|
    | audit_log              | RETENTION_AUDIT_LOG_DAYS       |
    | raf_encounter_analysis | RETENTION_ANALYSIS_DAYS        |
    | emr_sync_log           | RETENTION_SYNC_LOG_DAYS        |
    | user_sessions          | RETENTION_SESSIONS_DAYS        |
    | raf_jobs               | RETENTION_JOBS_DAYS            |
    | webhook_deliveries     | RETENTION_WEBHOOK_DAYS         |
    | documents              | RETENTION_DOCUMENTS_DAYS       |
    """
    logger.info(
        "Retention policy update: table='%s', retention_days=%d, user=%s",
        table,
        body.retention_days,
        current_user.get("sub") or current_user.get("username", "unknown"),
    )
    try:
        policy = update_retention_policy(table, body.retention_days)
        return {
            "table_name": policy.table_name,
            "retention_days": policy.retention_days,
            "date_column": policy.date_column,
            "description": policy.description,
            "note": (
                "Override applied for this process lifetime. "
                "Set the environment variable for persistent configuration."
            ),
        }
    except ValueError as exc:
        logger.error("Unexpected error: %s", exc)
        raise HTTPException(status_code=422, detail="Invalid input")
    except Exception as exc:
        logger.error("Failed to update retention policy: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update retention policy")
