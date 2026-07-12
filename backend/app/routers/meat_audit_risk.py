"""
MEAT Audit-Risk Router.

Surfaces the per-provider RADV audit-risk badge data + the per-HCC evidence
drill-down used by the front-end MEAT Evidence Modal.

Endpoints
---------
GET /api/providers/{provider_id}/meat-audit-risk?year=2026
    Full risk assessment (tier, MEAT completeness, top-weak HCCs).

GET /api/providers/{provider_id}/meat-evidence/{hcc_code}?year=2026
    Per-patient MEAT evidence rows for a single HCC code in this provider's
    panel.

Both routes are tenant-scoped via the standard `get_current_user` dependency.
"""
# Removed: from __future__ import annotations (breaks FastAPI schema generation)

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth import get_current_user
from app.services.meat_audit_risk import (
    assess_provider_audit_risk,
    get_meat_evidence_for_hcc,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/providers", tags=["providers", "meat-audit-risk"])


@router.get("/{provider_id}/meat-audit-risk")
def provider_meat_audit_risk(
    provider_id: int,
    year: int = Query(2026, ge=2020, le=2099),
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Compute and return the audit-risk assessment for one provider."""
    tenant_id = current_user.get("tenant_id")
    try:
        return assess_provider_audit_risk(
            provider_id=provider_id, year=year, tenant_id=tenant_id
        )
    except Exception as exc:  # pragma: no cover — defensive
        logger.exception("meat-audit-risk failed for provider %s", provider_id)
        raise HTTPException(
            status_code=500, detail="Internal server error"
        )


@router.get("/{provider_id}/meat-evidence/{hcc_code}")
def provider_meat_evidence(
    provider_id: int,
    hcc_code: str,
    year: int = Query(2026, ge=2020, le=2099),
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Per-patient MEAT evidence for one HCC code in this provider's panel."""
    tenant_id = current_user.get("tenant_id")
    try:
        rows = get_meat_evidence_for_hcc(
            provider_id=provider_id,
            hcc_code=hcc_code,
            year=year,
            tenant_id=tenant_id,
        )
    except Exception as exc:  # pragma: no cover — defensive
        logger.exception(
            "meat-evidence lookup failed for provider %s hcc=%s", provider_id, hcc_code
        )
        raise HTTPException(
            status_code=500, detail="Internal server error"
        )

    return {
        "provider_id": provider_id,
        "hcc_code": str(hcc_code),
        "year": year,
        "evidence": rows,
        "count": len(rows),
    }
