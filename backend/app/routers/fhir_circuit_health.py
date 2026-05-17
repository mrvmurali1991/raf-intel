"""Health probe for per-tenant FHIR circuit breakers."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.auth import get_current_user
from app.services.circuit_breaker import all_breakers_status

router = APIRouter(
    prefix="/api/fhir",
    tags=["fhir"],
    dependencies=[Depends(get_current_user)],
)


@router.get("/circuit/status", summary="All per-tenant FHIR circuit-breaker states")
def fhir_circuit_status(current_user: dict = Depends(get_current_user)):
    role = (current_user.get("role") or "").lower()
    if role not in {"admin", "manager"}:
        raise HTTPException(status_code=403, detail="Admin/manager only")
    return {
        "circuits": [c for c in all_breakers_status() if c["key"].startswith("fhir:")]
    }
