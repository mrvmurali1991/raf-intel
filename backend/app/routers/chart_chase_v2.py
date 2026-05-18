"""Chart-chase production router (v2).

Endpoints
---------
POST   /api/chart-chase/requests              Create one
GET    /api/chart-chase/requests              Paginated worklist
GET    /api/chart-chase/requests/{id}         Detail + documents + events
POST   /api/chart-chase/requests/{id}/assign  Assign to vendor/user
POST   /api/chart-chase/requests/{id}/status/{new_status}  State transition
POST   /api/chart-chase/requests/{id}/upload  Upload a document
POST   /api/chart-chase/bulk                  Bulk create from rows
GET    /api/chart-chase/dashboard             Funnel + TAT
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import (
    APIRouter, Body, Depends, File, Form, HTTPException, Path as PathParam,
    Query, UploadFile,
)
from pydantic import BaseModel, Field

from app.auth import get_current_user, get_tenant_id, require_permission
from app.services.chart_chase import orchestrator as orch

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chart-chase/v2", tags=["chart-chase-v2"])

# Storage path for uploaded documents
UPLOAD_ROOT = Path(os.getenv("CC_UPLOAD_ROOT", "/app/uploads/chart_chase"))
try:
    UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
except OSError:
    # Non-fatal in test environments where /app is read-only.
    logger.debug("Could not create UPLOAD_ROOT %s — uploads will fail at runtime.", UPLOAD_ROOT)


# ----------- Models -----------

class CreateRequest(BaseModel):
    patient_id: int
    reason: str = Field(..., min_length=2, max_length=64)
    reason_detail: str = ""
    date_of_service: str | None = None
    icd10_codes: list[str] | None = None
    hcc_codes: list[str] | None = None
    priority: int = Field(default=5, ge=1, le=9)
    assigned_vendor: str | None = None


class AssignRequest(BaseModel):
    vendor: str | None = None
    assigned_to_user_id: int | None = None


class BulkRow(BaseModel):
    patient_id: int
    reason: str = "RADV_sample"
    reason_detail: str = ""
    date_of_service: str | None = None
    icd10_codes: list[str] | None = None
    hcc_codes: list[str] | None = None
    priority: int = 5
    assigned_vendor: str | None = None


class BulkRequest(BaseModel):
    rows: list[BulkRow]


# ----------- Endpoints -----------

@router.post("/requests", summary="Create a chart-chase request")
def create(
    body: CreateRequest,
    tenant_id: str = Depends(get_tenant_id),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("documents", "write")),
):
    user_id = int(current_user.get("id") or current_user.get("user_id") or 0)
    try:
        return orch.create_request(
            tenant_id=tenant_id,
            patient_id=body.patient_id,
            requested_by_user_id=user_id,
            reason=body.reason,
            reason_detail=body.reason_detail,
            date_of_service=body.date_of_service,
            icd10_codes=body.icd10_codes,
            hcc_codes=body.hcc_codes,
            priority=body.priority,
            assigned_vendor=body.assigned_vendor,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/requests", summary="List chart-chase requests")
def list_(
    status: str | None = Query(default=None),
    priority: int | None = Query(default=None, ge=1, le=9),
    assigned_to_user_id: int | None = Query(default=None),
    patient_id: int | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("documents", "read")),
):
    return orch.list_requests(
        tenant_id=tenant_id, status=status, priority=priority,
        assigned_to_user_id=assigned_to_user_id, patient_id=patient_id,
        limit=limit, offset=offset,
    )


@router.get("/requests/{request_id}", summary="Get one request + timeline")
def get_one(
    request_id: int,
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("documents", "read")),
):
    try:
        return orch.get_request_detail(tenant_id, request_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="not found")


@router.post("/requests/{request_id}/assign", summary="Assign request")
def assign(
    request_id: int,
    body: AssignRequest,
    tenant_id: str = Depends(get_tenant_id),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("documents", "write")),
):
    user_id = int(current_user.get("id") or current_user.get("user_id") or 0)
    try:
        return orch.assign(tenant_id, request_id, body.vendor,
                           body.assigned_to_user_id, user_id)
    except (ValueError, LookupError) as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/requests/{request_id}/status/{new_status}",
             summary="Transition state")
def transition(
    request_id: int,
    new_status: str = PathParam(...),
    note: str = Body(default="", embed=True),
    tenant_id: str = Depends(get_tenant_id),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("documents", "write")),
):
    user_id = int(current_user.get("id") or current_user.get("user_id") or 0)
    try:
        return orch.transition(tenant_id, request_id, new_status, user_id, note)
    except (ValueError, LookupError) as e:
        msg = str(e)
        code = 409 if "Illegal transition" in msg else 422
        if "not found" in msg:
            code = 404
        raise HTTPException(status_code=code, detail=msg)


@router.post("/requests/{request_id}/upload", summary="Upload document")
async def upload(
    request_id: int,
    file: UploadFile = File(...),
    tenant_id: str = Depends(get_tenant_id),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("documents", "write")),
):
    user_id = int(current_user.get("id") or current_user.get("user_id") or 0)
    # Persist file
    tdir = UPLOAD_ROOT / tenant_id / str(request_id)
    tdir.mkdir(parents=True, exist_ok=True)
    target = tdir / (file.filename or "upload.bin")
    data = await file.read()
    target.write_bytes(data)

    try:
        return orch.add_document(
            tenant_id=tenant_id,
            request_id=request_id,
            filename=file.filename or "upload.bin",
            mime_type=file.content_type or "application/octet-stream",
            size_bytes=len(data),
            storage_path=str(target),
            actor_user_id=user_id,
        )
    except LookupError:
        target.unlink(missing_ok=True)
        raise HTTPException(status_code=404, detail="request not found")


@router.post("/bulk", summary="Bulk create requests")
def bulk(
    body: BulkRequest,
    tenant_id: str = Depends(get_tenant_id),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("documents", "write")),
):
    user_id = int(current_user.get("id") or current_user.get("user_id") or 0)
    return orch.bulk_create_from_rows(
        tenant_id=tenant_id,
        requested_by_user_id=user_id,
        rows=[r.model_dump() for r in body.rows],
    )


@router.get("/dashboard", summary="Funnel + TAT dashboard")
def dashboard(
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("documents", "read")),
):
    return orch.dashboard(tenant_id)
