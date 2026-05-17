"""
LOINC + lab signal router.

Endpoints (prefix ``/api/kg/labs``):

    GET  /resolve?test=HbA1c                  fuzzy resolve free-text -> LOINC
    POST /evaluate                            single LOINC value -> triggered signals
    POST /evaluate-patient/{pid}              all triggered signals for a patient
    GET  /signals?hcc=18                      reverse: which labs signal an HCC
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import Depends, APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.knowledge_graph import loinc_service
from app.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/kg/labs", tags=["knowledge_graph", "loinc"], dependencies=[Depends(get_current_user)])


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class EvaluateRequest(BaseModel):
    loinc_code: str = Field(..., min_length=1, description="LOINC code, e.g. 4548-4")
    value: float = Field(..., description="Numeric lab value")
    unit: str | None = Field(default=None, description="Optional unit hint")


class EvaluatePatientRequest(BaseModel):
    since_days: int = Field(default=730, ge=1, le=3650, description="Lookback window")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/resolve", summary="Fuzzy resolve test name to LOINC")
def resolve(
    test: str = Query(..., min_length=1, description="Free-text test name (e.g. 'HbA1c')"),
    limit: int = Query(default=5, ge=1, le=25),
) -> dict[str, Any]:
    matches = loinc_service.resolve_lab_to_loinc(test, limit=limit)
    return {"query": test, "count": len(matches), "matches": matches}


@router.post("/evaluate", summary="Evaluate a single LOINC value against signal rules")
def evaluate(payload: EvaluateRequest) -> dict[str, Any]:
    triggered = loinc_service.evaluate_lab_value(
        payload.loinc_code, payload.value, payload.unit
    )
    return {
        "loinc_code": payload.loinc_code,
        "value": payload.value,
        "unit": payload.unit,
        "triggered": triggered,
        "count": len(triggered),
    }


@router.post("/evaluate-patient/{pid}", summary="Evaluate all of a patient's labs")
def evaluate_patient(
    pid: int,
    payload: EvaluatePatientRequest | None = None,
) -> dict[str, Any]:
    if pid <= 0:
        raise HTTPException(status_code=400, detail="pid must be positive")
    since = payload.since_days if payload else 730
    return loinc_service.bulk_evaluate_patient_labs(pid, since_days=since)


@router.get("/signals", summary="Reverse lookup: labs that signal an HCC")
def signals_for_hcc(
    hcc: str = Query(..., min_length=1, description="HCC code, e.g. '18' or 'HCC18'"),
) -> dict[str, Any]:
    rows = loinc_service.get_loinc_signals_for_hcc(hcc)
    return {"hcc": hcc, "count": len(rows), "signals": rows}
