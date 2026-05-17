"""
Pre-Submission validation router.

Surfaces coding-rule violations for every ``raf_patient_hcc`` row in the
caller's tenant for a given measurement year BEFORE the 837/EDPS file is
generated. Mirrors the Edifecs RAEM workflow: surface the problem, fix it,
then submit.

Routes
------
GET /api/pre-submission/validate?year=2026
    Returns ``{rule_counts, severity_counts, total, items}`` where ``items``
    is the top 200 findings sorted HIGH -> MEDIUM -> LOW.

The endpoint is read-only and never mutates raf_patient_hcc — its only job
is to render the dashboard.
"""
# Do not use ``from __future__ import annotations`` — breaks FastAPI schemas.

import logging
from collections.abc import Generator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.auth import require_permission
from app.db import raf_cursor
from app.services import pre_submission_validator as svc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/pre-submission", tags=["pre-submission"])

# Cap the payload so a fresh tenant with millions of issues doesn't crush
# the browser; the KPI counters still reflect the full totals.
ITEM_LIMIT = 200

# Reuse the same permission used by the rest of the RAF surface — coders
# with raf:read can view the pre-submit dashboard. (raf:write is not
# required because this endpoint never mutates state.)
_perm_dep = require_permission("raf", "read")


# ---------------------------------------------------------------------------
# DB cursor dependency
# ---------------------------------------------------------------------------

def get_cursor() -> Generator[Any, None, None]:
    """Yield a mysql-connector dictionary cursor from the RAF pool."""
    with raf_cursor(dictionary=True) as cursor:
        yield cursor


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class FindingModel(BaseModel):
    rule_id: str = Field(..., description="R1..R5")
    severity: str = Field(..., description="HIGH | MEDIUM | LOW")
    hcc_id: int = Field(..., description="raf_patient_hcc.id")
    hcc_code: int | None = Field(None, description="HCC code (None when unmapped)")
    icd10: str | None = Field(None, description="Offending or representative ICD-10")
    patient_id: int = Field(..., description="OpenEMR pid (or emr_patient_matches.id)")
    message: str = Field(..., description="Human-readable explanation")


class ValidateResponse(BaseModel):
    year: int
    tenant_id: int
    total: int = Field(..., description="Total findings before truncation")
    rule_counts: dict[str, int] = Field(..., description="Count per rule_id (R1..R5)")
    severity_counts: dict[str, int] = Field(..., description="HIGH/MEDIUM/LOW totals")
    rule_descriptions: dict[str, str] = Field(..., description="Static R1..R5 labels")
    items: list[FindingModel] = Field(..., description=f"Top {ITEM_LIMIT} findings, severity desc")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get(
    "/validate",
    response_model=ValidateResponse,
    summary="Run pre-submission coding-rule validation for the caller's tenant",
)
def validate_endpoint(
    year: int = Query(..., ge=2020, le=2035, description="Measurement year"),
    current_user: dict = Depends(_perm_dep),
    cursor: Any = Depends(get_cursor),
) -> ValidateResponse:
    """Run R1..R5 across every ``raf_patient_hcc`` row for the tenant + year.

    Returns aggregate counters plus the top ``ITEM_LIMIT`` failing rows
    ordered by severity (HIGH first). The full set is summarised in
    ``rule_counts`` / ``severity_counts`` even when the payload is truncated.
    """
    tenant_id_raw = current_user.get("tenant_id")
    if tenant_id_raw is None:
        # Defensive — require_permission already verifies the user, but a
        # misconfigured account could still slip through without a tenant.
        raise HTTPException(
            status_code=403,
            detail="No tenant assignment found for this user.",
        )
    try:
        tenant_id = int(tenant_id_raw)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=403,
            detail="Tenant assignment is not a valid integer.",
        ) from exc

    try:
        findings = svc.validate(cursor, tenant_id, year)
    except RuntimeError as exc:
        logger.exception("pre-submission validate failed for tenant=%s year=%s", tenant_id, year)
        raise HTTPException(
            status_code=500,
            detail="Pre-submission validation failed. Check server logs for details.",
        ) from exc

    summary = svc.summarize(findings)
    truncated = findings[:ITEM_LIMIT]

    return ValidateResponse(
        year=year,
        tenant_id=tenant_id,
        total=len(findings),
        rule_counts=summary["rule_counts"],
        severity_counts=summary["severity_counts"],
        rule_descriptions=svc.RULE_DESCRIPTIONS,
        items=[FindingModel(**f) for f in truncated],
    )
