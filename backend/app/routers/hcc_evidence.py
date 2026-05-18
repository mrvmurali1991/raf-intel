"""Per-HCC clinical-evidence endpoint for the patient detail page.

Renders the supporting labs + estimated annual revenue for a single HCC
code on a single patient. Used by the patient chart's HCC suspect drawer
so the physician sees the lab justification and the dollar value inline.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth import get_current_user, get_tenant_id, require_permission
from app.db import raf_cursor
from app.services.hcc_lab_evidence import (
    evidence_for_hcc,
    estimated_annual_revenue,
)

router = APIRouter(
    prefix="/api/hcc-evidence",
    tags=["hcc-evidence"],
    dependencies=[Depends(get_current_user)],
)


def _verify_patient_in_tenant(patient_id: int, tenant_id: str) -> None:
    with raf_cursor() as cur:
        cur.execute(
            "SELECT 1 FROM patients WHERE id=%s AND tenant_id=%s AND is_active=1",
            (patient_id, tenant_id),
        )
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="patient not found")


@router.get(
    "/patient/{patient_id}/hcc/{hcc_code}",
    summary="Lab evidence + annual revenue for one HCC on one patient",
)
def patient_hcc_evidence(
    patient_id: int,
    hcc_code: str,
    year: int | None = Query(default=None, description="Measurement year"),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("suspects", "read")),
):
    _verify_patient_in_tenant(patient_id, tenant_id)
    return evidence_for_hcc(int(patient_id), str(hcc_code), year)


@router.get(
    "/hcc/{hcc_code}/revenue",
    summary="Estimated annual revenue for an HCC (no patient required)",
)
def hcc_revenue_only(
    hcc_code: str,
    year: int | None = Query(default=None),
    _user: dict = Depends(get_current_user),
):
    return estimated_annual_revenue(str(hcc_code), year)
