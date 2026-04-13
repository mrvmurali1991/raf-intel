"""
FHIR R4 Integration Router.

Endpoints for managing FHIR server connections, triggering syncs, and
processing synced clinical data into HCC/RAF pipelines.

POST   /api/fhir/connections                        - Register a new FHIR server
GET    /api/fhir/connections                        - List all connections
GET    /api/fhir/connections/{id}                   - Get one connection
PUT    /api/fhir/connections/{id}                   - Update connection
DELETE /api/fhir/connections/{id}                   - Remove connection
POST   /api/fhir/connections/{id}/test              - Test connectivity
POST   /api/fhir/sync/{connection_id}               - Trigger sync
GET    /api/fhir/sync/{connection_id}/status        - Sync history
GET    /api/fhir/patients/{connection_id}           - List synced patients
POST   /api/fhir/patients/{connection_id}/map       - Map FHIR patient → OpenEMR pid
GET    /api/fhir/conditions/{connection_id}         - List synced conditions
GET    /api/fhir/conditions/{connection_id}/unmapped - Conditions not yet HCC-mapped
POST   /api/fhir/conditions/{connection_id}/process - Process conditions → HCC → RAF
"""
# Removed: from __future__ import annotations (breaks FastAPI schema generation)

import logging
import threading
from typing import Any, Literal

from fastapi import Depends, APIRouter, HTTPException, Query, BackgroundTasks
from app.auth import get_current_user, require_permission
from pydantic import BaseModel, Field, HttpUrl, field_validator

import app.services.fhir_service as fhir_svc
from app.services.circuit_breaker import CircuitBreakerError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/fhir", tags=["fhir"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class FHIRConnectionCreate(BaseModel):
    """Payload for registering a new FHIR server connection."""
    name: str = Field(..., min_length=1, max_length=200, description="Human-readable label")
    vendor: Literal["epic", "cerner", "athenahealth", "generic"] = Field(
        "generic",
        description="EHR vendor — controls any vendor-specific behaviour",
    )
    base_url: str = Field(..., description="FHIR R4 base URL, e.g. https://ehr.example.com/fhir/r4")
    auth_type: Literal["none", "oauth2", "api_key"] = Field(
        "none",
        description="Authentication mechanism",
    )
    token_url: str | None = Field(
        None,
        description="OAuth2 token endpoint (required when auth_type=oauth2)",
    )
    client_id: str | None = Field(None, description="OAuth2 client_id")
    client_secret: str | None = Field(None, description="OAuth2 client_secret")
    api_key: str | None = Field(None, description="API key (used when auth_type=api_key)")
    scope: str = Field(
        "system/*.read",
        description="OAuth2 scope(s) to request",
    )
    is_active: bool = Field(True, description="Whether this connection is enabled")

    @field_validator("base_url")
    @classmethod
    def strip_trailing_slash(cls, v: str) -> str:
        return v.rstrip("/")


class FHIRConnectionUpdate(BaseModel):
    """Payload for updating an existing FHIR server connection.  All fields optional."""
    name: str | None = Field(None, min_length=1, max_length=200)
    vendor: Literal["epic", "cerner", "athenahealth", "generic"] | None = None
    base_url: str | None = None
    auth_type: Literal["none", "oauth2", "api_key"] | None = None
    token_url: str | None = None
    client_id: str | None = None
    client_secret: str | None = None
    api_key: str | None = None
    scope: str | None = None
    is_active: bool | None = None

    @field_validator("base_url")
    @classmethod
    def strip_trailing_slash(cls, v: str | None) -> str | None:
        return v.rstrip("/") if v else v


class SyncRequest(BaseModel):
    """Payload for triggering a FHIR sync."""
    sync_type: Literal["full", "incremental"] = Field(
        "incremental",
        description="'full' ignores the last-sync timestamp; 'incremental' uses it",
    )
    resource_types: list[Literal["Patient", "Condition", "Encounter", "DiagnosticReport"]] | None = Field(
        None,
        description="Subset of resource types to sync.  Omit to sync all four.",
    )
    use_bulk: bool = Field(
        False,
        description="Use FHIR $export bulk API instead of per-resource search",
    )
    background: bool = Field(
        True,
        description="Run sync in the background and return immediately",
    )


class PatientMapRequest(BaseModel):
    """Map a fhir_patients row to an OpenEMR patient."""
    fhir_patient_row_id: int = Field(
        ...,
        description="The id column from fhir_patients (not the FHIR resource ID)",
    )
    openemr_pid: int = Field(..., description="OpenEMR patient pid to link to")


class ProcessConditionsRequest(BaseModel):
    """Options for processing FHIR conditions into the HCC/RAF pipeline."""
    openemr_pid: int | None = Field(
        None,
        description="Limit processing to a single OpenEMR patient.  Omit for all mapped patients.",
    )
    limit: int = Field(
        500,
        ge=1,
        le=5000,
        description="Maximum number of conditions to process in one call",
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _require_connection(connection_id: int) -> dict[str, Any]:
    """Fetch connection or raise 404."""
    conn = fhir_svc.get_connection(connection_id)
    if not conn:
        raise HTTPException(
            status_code=404,
            detail=f"FHIR connection {connection_id} not found",
        )
    return conn


def _safe_connection_response(conn: dict[str, Any]) -> dict[str, Any]:
    """Strip sensitive credentials from a connection dict before returning."""
    return {
        k: v
        for k, v in conn.items()
        if k not in ("client_secret", "api_key")
    }


def _run_sync_background(
    connection_id: int,
    sync_type: str,
    resource_types: list[str] | None,
    use_bulk: bool,
) -> None:
    """Thread target — runs sync and swallows exceptions (already logged inside)."""
    try:
        fhir_svc.run_sync(
            connection_id=connection_id,
            sync_type=sync_type,
            resource_types=resource_types,
            use_bulk=use_bulk,
        )
    except Exception as exc:
        logger.error(
            "Background sync failed for connection %s: %s",
            connection_id, exc,
        )


# ---------------------------------------------------------------------------
# Connections CRUD
# ---------------------------------------------------------------------------

@router.post("/connections", summary="Register a new FHIR server connection", status_code=201)
def create_connection(body: FHIRConnectionCreate,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("fhir", "write"))) -> dict[str, Any]:
    """
    Register a FHIR R4 server so the system can sync clinical data from it.

    For oauth2 auth_type the token_url, client_id, and client_secret fields are
    required.  For api_key auth_type supply the api_key field instead.
    Credentials are stored in the RAF Intelligence database; the client_secret
    and api_key are never returned in subsequent GET responses.
    """
    try:
        new_id = fhir_svc.create_connection(body.model_dump(exclude_none=False))
    except Exception as exc:
        logger.error("create_connection error: %s", exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    conn = fhir_svc.get_connection(new_id)
    return {
        "id": new_id,
        "message": "FHIR connection registered",
        "connection": _safe_connection_response(conn),
    }


@router.get("/connections", summary="List all FHIR server connections")
def list_connections(
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("fhir", "read"))) -> dict[str, Any]:
    """
    Return all registered FHIR server connections with their last-sync status.
    Sensitive credential fields (client_secret, api_key) are omitted.
    """
    try:
        rows = fhir_svc.list_connections()
    except Exception as exc:
        logger.error("list_connections error: %s", exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    return {
        "count": len(rows),
        "connections": [_safe_connection_response(r) for r in rows],
    }


@router.get("/connections/{connection_id}", summary="Get a FHIR connection by ID")
def get_connection(connection_id: int,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("fhir", "read"))) -> dict[str, Any]:
    """Return one connection record.  Credentials are stripped."""
    conn = _require_connection(connection_id)
    return _safe_connection_response(conn)


@router.put("/connections/{connection_id}", summary="Update a FHIR connection")
def update_connection(connection_id: int, body: FHIRConnectionUpdate,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("fhir", "write"))) -> dict[str, Any]:
    """
    Update mutable fields of an existing FHIR connection.
    Only fields included in the request body are changed.
    """
    _require_connection(connection_id)
    try:
        fhir_svc.update_connection(
            connection_id,
            body.model_dump(exclude_unset=True),
        )
    except Exception as exc:
        logger.error("update_connection %s error: %s", connection_id, exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    conn = fhir_svc.get_connection(connection_id)
    return {
        "message": "Connection updated",
        "connection": _safe_connection_response(conn),
    }


@router.delete("/connections/{connection_id}", summary="Remove a FHIR connection")
def delete_connection(connection_id: int,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("fhir", "write"))) -> dict[str, Any]:
    """
    Delete a FHIR connection record.
    Associated fhir_patients, fhir_conditions, fhir_encounters, and
    fhir_diagnostic_reports rows are cascade-deleted by the foreign key
    constraints defined in the schema.
    """
    _require_connection(connection_id)
    try:
        fhir_svc.delete_connection(connection_id)
    except Exception as exc:
        logger.error("delete_connection %s error: %s", connection_id, exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    return {"message": f"Connection {connection_id} deleted"}


@router.post("/connections/{connection_id}/test", summary="Test FHIR server connectivity")
def test_connection(connection_id: int,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("fhir", "write"))) -> dict[str, Any]:
    """
    Attempt to reach the FHIR server's CapabilityStatement endpoint (GET /metadata).

    Returns success/failure, the HTTP status code, and the server's reported
    FHIR version.  Useful for validating credentials before triggering a sync.
    """
    conn = _require_connection(connection_id)
    try:
        result = fhir_svc.test_connection(conn)
    except CircuitBreakerError as exc:
        logger.warning("FHIR circuit breaker open for connection %s: %s", connection_id, exc)
        raise HTTPException(
            status_code=503,
            detail=f"FHIR service temporarily unavailable. {exc}",
            headers={"Retry-After": str(int(exc.retry_after))},
        ) from exc
    except Exception as exc:
        logger.error("test_connection %s error: %s", connection_id, exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    status_code = 200 if result["success"] else 502
    if status_code != 200:
        raise HTTPException(status_code=status_code, detail=result["message"])

    return result


# ---------------------------------------------------------------------------
# Sync
# ---------------------------------------------------------------------------

@router.post("/sync/{connection_id}", summary="Trigger a FHIR data sync")
def trigger_sync(connection_id: int, body: SyncRequest = SyncRequest(),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("fhir", "write"))) -> dict[str, Any]:
    """
    Kick off a FHIR data sync for the given connection.

    **sync_type**:
    - ``incremental`` (default) — only fetches resources updated since the last
      successful sync using the ``_lastUpdated`` search parameter.
    - ``full`` — fetches all resources regardless of update timestamp.

    **resource_types**: Subset of Patient, Condition, Encounter, DiagnosticReport.
    Omit to sync all four.

    **use_bulk**: When True, the service uses the FHIR $export operation
    (ndjson bulk download) instead of paginated REST search.  Requires the
    server to support the Bulk Data Access IG.

    **background**: When True (default) the sync runs in a background thread
    and the endpoint returns immediately with a log_id you can use to poll
    ``GET /api/fhir/sync/{connection_id}/status``.  Set to False to block
    until completion (suitable for small populations or testing).
    """
    conn = _require_connection(connection_id)
    if not conn.get("is_active"):
        raise HTTPException(
            status_code=400,
            detail=f"Connection {connection_id} is disabled. Enable it before syncing.",
        )

    if body.background:
        t = threading.Thread(
            target=_run_sync_background,
            args=(
                connection_id,
                body.sync_type,
                body.resource_types,
                body.use_bulk,
            ),
            daemon=True,
        )
        t.start()
        return {
            "message": "Sync started in the background",
            "connection_id": connection_id,
            "sync_type": body.sync_type,
            "resource_types": body.resource_types or ["Patient", "Condition", "Encounter", "DiagnosticReport"],
            "use_bulk": body.use_bulk,
            "status": "running",
            "poll_url": f"/api/fhir/sync/{connection_id}/status",
        }

    # Foreground sync
    try:
        result = fhir_svc.run_sync(
            connection_id=connection_id,
            sync_type=body.sync_type,
            resource_types=body.resource_types,
            use_bulk=body.use_bulk,
        )
    except CircuitBreakerError as exc:
        logger.warning("FHIR circuit breaker open for sync %s: %s", connection_id, exc)
        raise HTTPException(
            status_code=503,
            detail=f"FHIR service temporarily unavailable. {exc}",
            headers={"Retry-After": str(int(exc.retry_after))},
        ) from exc
    except ValueError as exc:
        logger.error("Unexpected error: %s", exc)
        raise HTTPException(status_code=400, detail="Bad request")
    except Exception as exc:
        logger.error("trigger_sync %s error: %s", connection_id, exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    return result


@router.get("/sync/{connection_id}/status", summary="Get sync history for a connection")
def get_sync_status(
    connection_id: int,
    limit: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("fhir", "read"))) -> dict[str, Any]:
    """
    Return the sync history for a connection, most recent first.

    Each entry shows the sync type, status (running / completed / failed),
    resource counts, start/end timestamps, and any error message.
    """
    _require_connection(connection_id)
    try:
        history = fhir_svc.get_sync_history(connection_id, limit=limit)
    except Exception as exc:
        logger.error("get_sync_status %s error: %s", connection_id, exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    latest_status = history[0]["status"] if history else "never_synced"

    return {
        "connection_id": connection_id,
        "latest_status": latest_status,
        "total_records": len(history),
        "history": history,
    }


# ---------------------------------------------------------------------------
# Patients
# ---------------------------------------------------------------------------

@router.get("/patients/{connection_id}", summary="List synced FHIR patients")
def list_patients(
    connection_id: int,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("fhir", "read"))) -> dict[str, Any]:
    """
    Return patients pulled from the FHIR server during the most recent sync.

    Each patient record shows the FHIR resource ID, MRN, name, DOB, and
    whether it has been mapped to an OpenEMR pid.  ``mapping_status`` will be
    ``'mapped'`` when a pid link exists or ``NULL``/``''`` when not yet matched.
    """
    _require_connection(connection_id)
    try:
        patients = fhir_svc.list_fhir_patients(connection_id, limit=limit, offset=offset)
    except Exception as exc:
        logger.error("list_patients fhir %s error: %s", connection_id, exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    mapped = sum(1 for p in patients if p.get("openemr_pid"))

    return {
        "connection_id": connection_id,
        "total_returned": len(patients),
        "limit": limit,
        "offset": offset,
        "mapped_count": mapped,
        "unmapped_count": len(patients) - mapped,
        "patients": patients,
    }


@router.post("/patients/{connection_id}/map", summary="Map a FHIR patient to an OpenEMR pid")
def map_patient(connection_id: int, body: PatientMapRequest,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("fhir", "write"))) -> dict[str, Any]:
    """
    Manually link a fhir_patients row to an OpenEMR patient record.

    The system attempts automatic matching by MRN and name+DOB during sync.
    Use this endpoint to resolve patients the auto-matcher could not link.

    ``fhir_patient_row_id`` is the ``id`` primary key from the fhir_patients
    table (returned in the patients list), not the FHIR resource ID string.
    """
    _require_connection(connection_id)
    try:
        fhir_svc.map_patient_to_openemr(
            connection_id,
            body.fhir_patient_row_id,
            body.openemr_pid,
        )
    except Exception as exc:
        logger.error(
            "map_patient connection=%s row=%s pid=%s error: %s",
            connection_id, body.fhir_patient_row_id, body.openemr_pid, exc,
        )
        logger.error("Unexpected error: %s", exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    return {
        "message": "Patient mapped successfully",
        "connection_id": connection_id,
        "fhir_patient_row_id": body.fhir_patient_row_id,
        "openemr_pid": body.openemr_pid,
    }


# ---------------------------------------------------------------------------
# Conditions
# ---------------------------------------------------------------------------

@router.get("/conditions/{connection_id}", summary="List synced FHIR conditions")
def list_conditions(
    connection_id: int,
    limit: int = Query(200, ge=1, le=2000),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("fhir", "read"))) -> dict[str, Any]:
    """
    Return Condition resources synced from the FHIR server.

    Each entry includes the ICD-10 codes extracted from the FHIR coding array
    (system = ``http://hl7.org/fhir/sid/icd-10-cm``), clinical status,
    and whether it has been mapped to CMS-HCC codes.
    """
    _require_connection(connection_id)
    try:
        conditions = fhir_svc.list_fhir_conditions(connection_id, limit=limit, offset=offset)
    except Exception as exc:
        logger.error("list_conditions fhir %s error: %s", connection_id, exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    return {
        "connection_id": connection_id,
        "total_returned": len(conditions),
        "limit": limit,
        "offset": offset,
        "conditions": conditions,
    }


@router.get("/conditions/{connection_id}/unmapped", summary="List conditions not yet HCC-mapped")
def list_unmapped_conditions(
    connection_id: int,
    limit: int = Query(200, ge=1, le=2000),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("fhir", "read"))) -> dict[str, Any]:
    """
    Return active conditions that have ICD-10 codes but have not yet been
    processed through the HCC mapping pipeline.

    Only conditions with ``clinical_status`` of ``active``, ``recurrence``,
    ``relapse``, or blank are included — inactive / resolved conditions are
    excluded because they do not contribute to current-year RAF scores.

    Use ``POST /api/fhir/conditions/{connection_id}/process`` to run the
    HCC mapping and RAF recalculation on these conditions.
    """
    _require_connection(connection_id)
    try:
        conditions = fhir_svc.list_unmapped_conditions(connection_id, limit=limit)
    except Exception as exc:
        logger.error("list_unmapped_conditions fhir %s error: %s", connection_id, exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    return {
        "connection_id": connection_id,
        "count": len(conditions),
        "conditions": conditions,
    }


@router.post("/conditions/{connection_id}/process", summary="Process FHIR conditions → HCC → RAF")
def process_conditions(
    connection_id: int,
    body: ProcessConditionsRequest = ProcessConditionsRequest(),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("fhir", "write"))) -> dict[str, Any]:
    """
    Process unmapped FHIR conditions through the full HCC/RAF pipeline:

    1. For each fhir_condition with ICD-10 codes, find the linked OpenEMR pid.
    2. Map each ICD-10 code to its CMS-HCC V28 hierarchy via hccinfhir_utils.
    3. Persist the HCC codes back to fhir_conditions.hcc_codes.
    4. Trigger a full RAF score recalculation for every affected OpenEMR patient.
    5. Return a summary of how many conditions and patients were updated.

    Conditions without a mapped OpenEMR pid are skipped (see
    ``POST /api/fhir/patients/{connection_id}/map`` to resolve unmapped patients).

    Optionally supply ``openemr_pid`` to scope processing to a single patient.
    """
    _require_connection(connection_id)
    try:
        result = fhir_svc.process_conditions_for_raf(
            connection_id=connection_id,
            openemr_pid=body.openemr_pid,
            limit=body.limit,
        )
    except Exception as exc:
        logger.error("process_conditions fhir %s error: %s", connection_id, exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    return {
        "connection_id": connection_id,
        **result,
    }
