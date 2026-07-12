"""Admin endpoints for HIE (CommonWell + Carequality) patient sync.

Routes:
  POST /api/admin/hie/sync-patient/{raf_patient_id}
       Body: {"network": "commonwell"|"carequality"}
       Triggers a full discover -> document-fetch -> Gemini-extract cycle.

  GET  /api/admin/hie/networks/status
       Connectivity probe: cert presence + last successful query timestamp.

All routes require an authenticated user with admin or manager role.
"""
# Note: do NOT use 'from __future__ import annotations' here --
# it breaks FastAPI/Pydantic schema generation (ForwardRef errors).

import logging
import os
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth import get_current_user
from app.db import raf_cursor

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/admin/hie",
    tags=["admin"],
    dependencies=[Depends(get_current_user)],
)

_NETWORKS = ("commonwell", "carequality")


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class HieSyncRequest(BaseModel):
    network: Literal["commonwell", "carequality"] = Field(
        ...,
        description="HIE network to sync against.",
    )


class HieSyncResponse(BaseModel):
    status: str
    network: str
    raf_patient_id: int
    hie_patient_id: str | None = None
    matches_found: int = 0
    documents_fetched: int = 0
    documents_skipped: int = 0
    suspects_extracted: int = 0
    errors: list[str] = Field(default_factory=list)


class NetworkProbe(BaseModel):
    network: str
    configured: bool
    cert_path: str | None = None
    key_path: str | None = None
    trust_bundle: str | None = None
    last_successful_query_at: str | None = None


class NetworkStatusResponse(BaseModel):
    networks: list[NetworkProbe]


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _require_admin_or_manager(current_user: dict) -> None:
    role = (current_user.get("role") or "").lower()
    if role not in {"admin", "manager"}:
        raise HTTPException(status_code=403, detail="Admin or manager role required")


def _last_successful_query(network: str) -> str | None:
    """Return ISO-8601 timestamp of last successful HIE query for this network."""
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT MAX(queried_at) AS last_ok
                FROM hie_queries_log
                WHERE network = %s AND status = 'success'
                """,
                (network,),
            )
            row = cur.fetchone()
            if row:
                val = row.get("last_ok") if isinstance(row, dict) else row[0]
                if val:
                    return val.isoformat() if hasattr(val, "isoformat") else str(val)
    except Exception:  # noqa: BLE001 — best-effort guard
        logger.debug("swallowed exception", exc_info=True)
    return None


# ---------------------------------------------------------------------------
# POST /api/admin/hie/sync-patient/{raf_patient_id}
# ---------------------------------------------------------------------------


@router.post(
    "/sync-patient/{raf_patient_id}",
    response_model=HieSyncResponse,
    summary="Trigger HIE patient sync",
    description=(
        "Discover the patient in the named HIE network, retrieve all "
        "DocumentReferences, fetch each binary, and route through "
        "Gemini Vision HCC extraction.  Idempotent -- already-processed "
        "documents are skipped."
    ),
)
def sync_patient(
    raf_patient_id: int,
    body: HieSyncRequest,
    current_user: dict = Depends(get_current_user),
) -> Any:
    _require_admin_or_manager(current_user)

    tenant_id: str = current_user.get("tenant_id") or current_user.get("tenantId") or "default"

    try:
        from app.services.hie.sync import sync_patient_from_hie
    except ImportError as exc:
        raise HTTPException(status_code=500, detail="Internal server error") from exc

    try:
        result = sync_patient_from_hie(
            tenant_id=tenant_id,
            raf_patient_id=raf_patient_id,
            network=body.network,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("HIE sync failed for patient %s / network %s", raf_patient_id, body.network)
        raise HTTPException(status_code=500, detail="Internal server error") from exc

    # Map sync service return dict to response model
    result.setdefault("status", "ok")
    result.setdefault("hie_patient_id", None)
    result.setdefault("matches_found", 0)
    result.setdefault("documents_fetched", 0)
    result.setdefault("documents_skipped", 0)
    result.setdefault("suspects_extracted", 0)
    result.setdefault("errors", [])

    return result


# ---------------------------------------------------------------------------
# GET /api/admin/hie/networks/status
# ---------------------------------------------------------------------------


@router.get(
    "/networks/status",
    response_model=NetworkStatusResponse,
    summary="HIE network connectivity status",
    description=(
        "Checks whether mTLS certificate env vars are present for each "
        "network, and returns the timestamp of the last successful query."
    ),
)
def networks_status(current_user: dict = Depends(get_current_user)) -> Any:
    _require_admin_or_manager(current_user)

    probes: list[NetworkProbe] = []

    for network in _NETWORKS:
        n_upper = network.upper()
        cert = os.environ.get(f"HIE_{n_upper}_CERT_PATH")
        key = os.environ.get(f"HIE_{n_upper}_KEY_PATH")
        trust = os.environ.get(f"HIE_{n_upper}_TRUST_BUNDLE")
        configured = all([cert, key, trust])

        probes.append(
            NetworkProbe(
                network=network,
                configured=configured,
                cert_path=cert,
                key_path=key,
                trust_bundle=trust,
                last_successful_query_at=_last_successful_query(network),
            )
        )

    return NetworkStatusResponse(networks=probes)
