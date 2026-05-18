"""Admin endpoints for SOC 2 evidence collection."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.auth import get_current_user
from app.services import soc2_evidence as svc

router = APIRouter(
    prefix="/api/admin/soc2",
    tags=["soc2"],
    dependencies=[Depends(get_current_user)],
)


@router.post("/collect", summary="Collect all SOC 2 evidence artifacts now")
def collect_now(current_user: dict = Depends(get_current_user)):
    role = (current_user.get("role") or "").lower()
    if role not in {"admin", "manager"}:
        raise HTTPException(status_code=403, detail="Admin/manager only")
    return svc.collect_all()


@router.get("/latest/{control_id}", summary="Most-recent evidence row for a control")
def latest(control_id: str, current_user: dict = Depends(get_current_user)):
    role = (current_user.get("role") or "").lower()
    if role not in {"admin", "manager", "auditor"}:
        raise HTTPException(status_code=403, detail="Admin/manager/auditor only")
    row = svc.fetch_latest(control_id)
    if not row:
        raise HTTPException(status_code=404, detail="no evidence for control")
    return row


@router.get("/controls", summary="List supported SOC 2 controls")
def list_controls(_user: dict = Depends(get_current_user)):
    return {"controls": list(svc.COLLECTORS.keys())}
