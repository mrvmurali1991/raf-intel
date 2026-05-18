"""Admin endpoints for the OpenEMR-document vision ingestion pipeline."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth import get_current_user, get_tenant_id, require_permission
from app.services.openemr_document_ingest import (
    process_document,
    scan_new_documents,
)

router = APIRouter(
    prefix="/api/admin/openemr-docs",
    tags=["openemr-docs"],
    dependencies=[Depends(get_current_user)],
)


@router.post(
    "/process/{document_id}",
    summary="Run Gemini vision on a single OpenEMR document now",
)
def process_one(
    document_id: int,
    year: int | None = Query(default=None),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("documents", "write")),
):
    role = (current_user.get("role") or "").lower()
    if role not in {"admin", "manager", "coder"}:
        raise HTTPException(status_code=403, detail="Coder/manager/admin only")
    return process_document(
        document_id, tenant_id=tenant_id, measurement_year=year,
    )


@router.post(
    "/scan",
    summary="Scan unprocessed OpenEMR documents (vision pipeline)",
)
def scan(
    since_id: int | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("documents", "write")),
):
    role = (current_user.get("role") or "").lower()
    if role not in {"admin", "manager"}:
        raise HTTPException(status_code=403, detail="Admin/manager only")
    return scan_new_documents(tenant_id, since_id=since_id, limit=limit)
