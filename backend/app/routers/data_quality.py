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
- Persist each run into a ``data_quality_reports`` table (timestamp,
  tenant_id, check, severity, count, sample_ids, details) so the admin
  dashboard can chart trends over time rather than only showing the most
  recent on-demand run.
- Admin-gating: this router currently relies on ``require_role("admin")``
  where available; confirm the admin role is enforced in all deployments
  before exposing this router publicly.
"""
# Do not use `from __future__ import annotations` — breaks FastAPI schemas.

import logging
from typing import Any, Callable, Generator

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.auth import get_current_user
from app.config import settings
from app.services.data_quality_monitor import (
    CHECK_NAMES,
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

# Admin-only dependency if available, otherwise fall back to regular auth.
# TODO: enforce admin-gating uniformly once require_role is rolled out to
# every deployment; for now we degrade to authenticated user with a warning.
try:  # pragma: no cover - import guard
    from app.auth import require_role  # type: ignore

    _admin_dep = require_role("admin")
except Exception:  # noqa: BLE001
    logger.warning(
        "require_role('admin') unavailable — falling back to get_current_user. "
        "TODO: admin-gate /api/data-quality routes."
    )
    _admin_dep = get_current_user


router = APIRouter(prefix="/api/data-quality", tags=["data-quality"])


# ---------------------------------------------------------------------------
# SQLAlchemy session dependency
# ---------------------------------------------------------------------------
#
# The rest of the project uses a raw mysql-connector pool (see app.db), but
# data_quality_monitor was written against a SQLAlchemy ``Session``. Rather
# than rewrite the service, we build a small SQLAlchemy engine here on first
# use, pointed at the same RAF Intelligence database described by
# ``app.config.settings``.

_engine: Engine | None = None
_SessionLocal: sessionmaker | None = None


def _get_engine() -> Engine:
    global _engine, _SessionLocal
    if _engine is None:
        url = (
            f"mysql+mysqlconnector://{settings.raf_db_user}:{settings.raf_db_password}"
            f"@{settings.raf_db_host}:{settings.raf_db_port}/{settings.raf_db_name}"
        )
        _engine = create_engine(url, pool_pre_ping=True, pool_recycle=3600)
        _SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False)
    return _engine


def get_db() -> Generator[Session, None, None]:
    _get_engine()
    assert _SessionLocal is not None
    db = _SessionLocal()
    try:
        yield db
    finally:
        db.close()


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

# Tenant-scoped checks take (db, tenant_id); stale_crosswalk takes (db,) only.
_TENANT_CHECK_MAP: dict[str, Callable[[Session, int], dict[str, Any]]] = {
    "patients_without_icd": check_patients_without_icd,
    "hccs_missing_meat": check_hccs_missing_meat,
    "raf_score_outliers": check_raf_score_outliers,
    "future_dob": check_future_dob,
    "duplicate_patients": check_duplicate_patients,
    "orphaned_hccs": check_orphaned_hccs,
}

_GLOBAL_CHECK_MAP: dict[str, Callable[[Session], dict[str, Any]]] = {
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
    db: Session = Depends(get_db),
) -> ChecksResponse:
    """Execute every registered data quality check and return the report.

    TODO: also persist the returned rows into a ``data_quality_reports``
    table so the admin dashboard can show trends over time.
    """
    try:
        tenant_id = int(getattr(current_user, "tenant_id", None) or 1)
        results = run_all_checks(db, tenant_id)
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
            status_code=500, detail=f"Data quality run failed: {exc!s}"
        ) from exc


@router.get(
    "/checks/{check_name}",
    response_model=CheckResult,
    summary="Run a single named data quality check",
)
def run_single_check(
    check_name: str,
    current_user: dict = Depends(_admin_dep),
    db: Session = Depends(get_db),
) -> CheckResult:
    """Run one named data quality check and return its structured result.

    Returns 404 when the check name is not recognised. Known names are
    enumerated by ``CHECK_NAMES`` in ``data_quality_monitor``.
    """
    if check_name not in _TENANT_CHECK_MAP and check_name not in _GLOBAL_CHECK_MAP:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Unknown check '{check_name}'. Valid checks: "
                f"{', '.join(CHECK_NAMES)}"
            ),
        )
    try:
        if check_name in _TENANT_CHECK_MAP:
            tenant_id = int(getattr(current_user, "tenant_id", None) or 1)
            result = _TENANT_CHECK_MAP[check_name](db, tenant_id)
        else:
            result = _GLOBAL_CHECK_MAP[check_name](db)
        return CheckResult(**result)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("Data quality check %s failed", check_name)
        raise HTTPException(
            status_code=500, detail=f"Check '{check_name}' failed: {exc!s}"
        ) from exc
