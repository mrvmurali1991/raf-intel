"""
HCC gap drilldown router.

Exposes a single endpoint that backs the per-HCC patient drilldown modal
on the providers detail drawer:

    GET /api/providers/{provider_id}/hcc/{hcc_code}/gap-patients
"""

import logging
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.auth import get_current_user, require_permission
from app.rate_limit import limiter
from app.services.hcc_gap_drilldown import get_gap_patients
from app.services.provider_service import get_provider

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/providers", tags=["providers", "hcc-gap-drilldown"])


@router.get(
    "/{provider_id}/hcc/{hcc_code}/gap-patients",
    summary="Patients in a provider's panel missing the given HCC",
)
@limiter.limit("60/minute")
def gap_patients(
    request: Request,
    provider_id: int,
    hcc_code: str,
    year: int = Query(default=None, description="Measurement year (defaults to current year)"),
    limit: int = Query(default=50, ge=1, le=500),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("providers", "read")),
) -> dict[str, Any]:
    """Return panel patients who are MISSING ``hcc_code`` for ``year``.

    A patient is "missing" the HCC when they have an open suspect for it,
    OR they were coded for it last year but not yet this year. Patients
    who already have the HCC coded for the year are excluded.

    The response includes the list of patients with chart context plus
    a small summary (panel size, total missing) so the frontend can render
    the modal title without a second request.
    """
    provider = get_provider(provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail=f"Provider {provider_id} not found")

    calc_year = year or date.today().year
    tenant_id = current_user.get("tenant_id")

    try:
        patients = get_gap_patients(
            provider_id=provider_id,
            hcc_code=hcc_code,
            year=calc_year,
            tenant_id=tenant_id,
            limit=limit,
        )
    except Exception as exc:
        logger.error(
            "gap_patients error pid=%s hcc=%s year=%s: %s",
            provider_id, hcc_code, calc_year, exc, exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Internal server error")

    # Panel size for context in the modal subtitle.
    try:
        from app.db import raf_cursor
        from app.services.emr_manager import active_patients_subquery

        tid = int(tenant_id) if tenant_id is not None else 1
        sf, sp = active_patients_subquery(tid)
        with raf_cursor() as cur:
            cur.execute(
                f"SELECT COUNT(*) AS n FROM provider_patient_panel WHERE provider_id = %s AND {sf}",
                (provider_id, *sp),
            )
            row = cur.fetchone() or {}
            panel_size = int(row.get("n") or 0)
    except Exception as exc:
        logger.warning("panel-size lookup failed pid=%s: %s", provider_id, exc)
        panel_size = None

    return {
        "provider_id": provider_id,
        "provider_name": (
            f"{provider.get('first_name', '')} {provider.get('last_name', '')}".strip()
        ),
        "hcc_code": str(hcc_code),
        "year": calc_year,
        "panel_size": panel_size,
        "missing_count": len(patients),
        "patients": patients,
    }
