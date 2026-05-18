# Note: do NOT use 'from __future__ import annotations' here —
# it breaks FastAPI/Pydantic schema generation (ForwardRef errors in /openapi.json).

"""
Inovalon Electronic Record On Demand — admin endpoints.

Provides a thin operational surface for triggering, listing, and
health-checking Inovalon EROND pulls.

Route prefix: /api/admin/inovalon
Tags: admin
"""

import logging
import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth import get_current_user, require_role
from app.db import raf_cursor

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/admin/inovalon",
    tags=["admin"],
    dependencies=[Depends(require_role("admin"))],
)


# ---------------------------------------------------------------------------
# POST /api/admin/inovalon/pull/{raf_patient_id}
# ---------------------------------------------------------------------------


@router.post(
    "/pull/{raf_patient_id}",
    summary="Trigger Inovalon EROND pull for a patient",
)
def trigger_pull(
    raf_patient_id: int,
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Submit an Inovalon Electronic Record On Demand pull for *raf_patient_id*.

    Returns a pull summary dict with ``pull_id``, ``status``,
    ``suspects_created``, ``docs_routed``, and ``observations_stored``.
    """
    from app.services.partners.inovalon_ingest import (  # noqa: PLC0415
        ingest_patient_from_inovalon,
    )

    tenant_id: str = current_user.get("tenant_id") or ""
    if not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="tenant_id missing from session",
        )

    result = ingest_patient_from_inovalon(
        tenant_id=tenant_id,
        raf_patient_id=raf_patient_id,
    )

    if result.get("status") == "error":
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=result.get("error") or "Inovalon pull failed",
        )

    return result


# ---------------------------------------------------------------------------
# GET /api/admin/inovalon/pulls
# ---------------------------------------------------------------------------


@router.get(
    "/pulls",
    summary="List Inovalon pull records",
)
def list_pulls(
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=500),
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Return recent ``inovalon_patient_pulls`` rows for the caller's tenant.

    Args:
        status: Optional filter by pull status (submitted, processing,
            completed, failed).
        limit: Maximum rows to return (1-500, default 50).
    """
    tenant_id: str = current_user.get("tenant_id") or ""
    if not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="tenant_id missing from session",
        )

    with raf_cursor() as cur:
        if status_filter:
            cur.execute(
                """SELECT id, tenant_id, raf_patient_id, inovalon_pull_id,
                          submitted_at, completed_at, status,
                          resources_returned, bundle_size_bytes, error_text
                   FROM   inovalon_patient_pulls
                   WHERE  tenant_id = %s AND status = %s
                   ORDER  BY submitted_at DESC
                   LIMIT  %s""",
                (tenant_id, status_filter, limit),
            )
        else:
            cur.execute(
                """SELECT id, tenant_id, raf_patient_id, inovalon_pull_id,
                          submitted_at, completed_at, status,
                          resources_returned, bundle_size_bytes, error_text
                   FROM   inovalon_patient_pulls
                   WHERE  tenant_id = %s
                   ORDER  BY submitted_at DESC
                   LIMIT  %s""",
                (tenant_id, limit),
            )
        rows = cur.fetchall() or []

    pulls = []
    for row in rows:
        if isinstance(row, dict):
            r = dict(row)
        else:
            cols = [
                "id", "tenant_id", "raf_patient_id", "inovalon_pull_id",
                "submitted_at", "completed_at", "status",
                "resources_returned", "bundle_size_bytes", "error_text",
                "created_at",
            ]
            r = dict(zip(cols, row))
        # Datetime fields are not JSON-serialisable by default
        for field in ("submitted_at", "completed_at", "created_at"):
            if r.get(field) is not None:
                r[field] = str(r[field])
        pulls.append(r)

    return {"pulls": pulls, "total": len(pulls)}


# ---------------------------------------------------------------------------
# GET /api/admin/inovalon/credentials/check
# ---------------------------------------------------------------------------


@router.get(
    "/credentials/check",
    summary="Verify Inovalon credentials are configured",
)
def credentials_check(
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Return ``{configured: true}`` when all three Inovalon env vars are set.

    Does NOT attempt a live OAuth2 token fetch — safe to call at any time.
    """
    from app.services.partners.inovalon import InovalonClient  # noqa: PLC0415

    client = InovalonClient()
    configured = client.is_configured
    return {
        "configured": configured,
        "api_base_set": bool(os.getenv("INOVALON_API_BASE")),
        "client_id_set": bool(os.getenv("INOVALON_CLIENT_ID")),
        "client_secret_set": bool(os.getenv("INOVALON_CLIENT_SECRET")),
    }
