"""
Data Quality router — admin-facing endpoints that expose the nightly
``app.services.data_quality_monitor`` checks over HTTP so operators can
trigger a run on demand from the admin dashboard.

Routes
------
GET /api/data-quality/checks
    Run the full battery of data quality checks for the caller's tenant
    and return a list of structured results plus a severity summary.

GET /api/data-quality/checks/{check_name}
    Run a single named check. Valid names are:
        patients_without_icd
        hccs_missing_meat
        raf_score_outliers
        future_dob
        duplicate_patients
        stale_crosswalk
        orphaned_hccs

TODO
----
- Admin-gating: this router currently relies on ``require_role("admin")``
  where available; confirm the admin role is enforced in all deployments
  before exposing this router publicly.
"""
# Do not use `from __future__ import annotations` — breaks FastAPI schemas.

import logging
from collections.abc import Callable, Generator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth import require_role
from app.db import raf_cursor
from app.services.data_quality_monitor import (
    CHECK_NAMES,
    Cursor,
    check_duplicate_patients,
    check_future_dob,
    check_hccs_missing_meat,
    check_orphaned_hccs,
    check_patients_without_icd,
    check_raf_score_outliers,
    check_stale_crosswalk,
    run_all_checks,
)

logger = logging.getLogger(__name__)

_admin_dep = require_role("admin")


router = APIRouter(prefix="/api/data-quality", tags=["data-quality"])


# ---------------------------------------------------------------------------
# Cursor dependency
# ---------------------------------------------------------------------------


def get_cursor() -> Generator[Cursor, None, None]:
    """FastAPI dependency that yields a dictionary cursor from the RAF pool.

    Uses the same ``raf_cursor()`` context manager as the rest of the app so
    connections are drawn from and returned to the shared pool.
    """
    with raf_cursor(dictionary=True) as cursor:
        yield cursor


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class CheckResult(BaseModel):
    check: str
    severity: str
    count: int
    sample_ids: list[Any] = Field(default_factory=list)
    details: str


class SeveritySummary(BaseModel):
    error: int = 0
    warn: int = 0
    info: int = 0


class ChecksResponse(BaseModel):
    tenant_id: int
    total_checks: int
    summary: SeveritySummary
    results: list[CheckResult]


# ---------------------------------------------------------------------------
# Single-check dispatch table
# ---------------------------------------------------------------------------

# Tenant-scoped checks take (cursor, tenant_id); stale_crosswalk takes (cursor,) only.
_TENANT_CHECK_MAP: dict[str, Callable[[Cursor, int], dict[str, Any]]] = {
    "patients_without_icd": check_patients_without_icd,
    "hccs_missing_meat": check_hccs_missing_meat,
    "raf_score_outliers": check_raf_score_outliers,
    "future_dob": check_future_dob,
    "duplicate_patients": check_duplicate_patients,
    "orphaned_hccs": check_orphaned_hccs,
}

_GLOBAL_CHECK_MAP: dict[str, Callable[[Cursor], dict[str, Any]]] = {
    "stale_crosswalk": check_stale_crosswalk,
}


def _summarize(results: list[dict[str, Any]]) -> SeveritySummary:
    summary = SeveritySummary()
    for r in results:
        sev = r.get("severity", "info")
        if sev == "error":
            summary.error += 1
        elif sev == "warn":
            summary.warn += 1
        else:
            summary.info += 1
    return summary


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get(
    "/checks",
    response_model=ChecksResponse,
    summary="Run all data quality checks for the caller's tenant",
)
def list_all_checks(
    current_user: dict = Depends(_admin_dep),
    cursor: Cursor = Depends(get_cursor),
) -> ChecksResponse:
    """Execute every registered data quality check and return the report.

    TODO(production): persist run results to ``data_quality_reports`` table
    (timestamp, tenant_id, check, severity, count, sample_ids, details) so
    the admin dashboard can chart trends over time rather than only showing
    the most recent on-demand run.  See issue tracker for the follow-up
    ticket — implementation deferred from this refactor.
    """
    # TODO(production): persist run results to data_quality_reports table — see issue tracker
    try:
        tenant_id = int(current_user.get("tenant_id") or 1)
        results = run_all_checks(cursor, tenant_id)
        return ChecksResponse(
            tenant_id=tenant_id,
            total_checks=len(results),
            summary=_summarize(results),
            results=[CheckResult(**r) for r in results],
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("run_all_checks failed")
        raise HTTPException(
            status_code=500, detail="Data quality run failed. Check server logs for details."
        ) from exc


@router.get(
    "/checks/{check_name}",
    response_model=CheckResult,
    summary="Run a single named data quality check",
)
def run_single_check(
    check_name: str,
    current_user: dict = Depends(_admin_dep),
    cursor: Cursor = Depends(get_cursor),
) -> CheckResult:
    """Run one named data quality check and return its structured result.

    Returns 404 when the check name is not recognised. Known names are
    enumerated by ``CHECK_NAMES`` in ``data_quality_monitor``.
    """
    if check_name not in _TENANT_CHECK_MAP and check_name not in _GLOBAL_CHECK_MAP:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Unknown check '{check_name}'. Valid checks: {', '.join(CHECK_NAMES)}"
            ),
        )
    try:
        if check_name in _TENANT_CHECK_MAP:
            tenant_id = int(current_user.get("tenant_id") or 1)
            result = _TENANT_CHECK_MAP[check_name](cursor, tenant_id)
        else:
            result = _GLOBAL_CHECK_MAP[check_name](cursor)
        return CheckResult(**result)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("Data quality check %s failed", check_name)
        raise HTTPException(
            status_code=500, detail=f"Check '{check_name}' failed. Check server logs for details."
        ) from exc
