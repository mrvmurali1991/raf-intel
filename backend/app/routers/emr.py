"""
EMR Connection Management Router.

Endpoints for managing EMR (Electronic Medical Record) connections across
multiple vendor types and connection strategies, with field mapping support
and sync history tracking.

GET    /api/emr/vendors                             - List all vendor presets
GET    /api/emr/vendors/{vendor}                    - Get one vendor preset with defaults

POST   /api/emr/connections                         - Create a new EMR connection
GET    /api/emr/connections                         - List all connections (credentials masked)
GET    /api/emr/connections/{id}                    - Get one connection (credentials masked)
PUT    /api/emr/connections/{id}                    - Update connection
DELETE /api/emr/connections/{id}                    - Delete connection

POST   /api/emr/connections/{id}/test               - Test connectivity
POST   /api/emr/connections/{id}/sync               - Trigger a sync
GET    /api/emr/connections/{id}/sync/history       - Get sync history

GET    /api/emr/connections/{id}/mappings           - Get field mappings
PUT    /api/emr/connections/{id}/mappings           - Update field mappings
"""
# Note: do NOT use 'from __future__ import annotations' here —
# it breaks FastAPI/Pydantic schema generation (ForwardRef errors in /openapi.json).

import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, field_validator

from app.auth import get_current_user, get_tenant_id, require_role
from app.rate_limit import limiter
from app.services.audit_logger import log_phi_access

import app.services.emr_manager as emr_mgr
import app.services.patient_matcher as patient_matcher

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/emr", tags=["emr"])

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ConnectionType = Literal["fhir_r4", "rest_api"]

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class CreateConnectionRequest(BaseModel):
    """
    Payload for creating a new EMR connection.

    Validation rules per connection_type:
    - fhir_r4:   requires fhir_base_url
    - rest_api:  requires api_base_url
    All types require: name, vendor, connection_type
    """

    name: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Human-readable label for this connection",
    )
    vendor: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="EMR vendor identifier, e.g. 'openemr', 'epic', 'cerner'",
    )
    connection_type: ConnectionType = Field(
        ..., description="Transport mechanism for this connection"
    )
    is_active: bool = Field(True, description="Whether this connection is enabled")

    # fhir_r4 fields
    fhir_base_url: str | None = Field(
        None, description="FHIR R4 base URL (required for fhir_r4)"
    )
    fhir_auth_type: Literal["none", "oauth2", "api_key"] | None = Field(
        None, description="FHIR auth mechanism"
    )
    fhir_token_url: str | None = Field(
        None, description="OAuth2 token endpoint (fhir_r4 + oauth2)"
    )
    fhir_client_id: str | None = Field(
        None, description="OAuth2 client_id (fhir_r4 + oauth2)"
    )
    fhir_client_secret: str | None = Field(
        None, description="OAuth2 client_secret (fhir_r4 + oauth2)"
    )
    fhir_api_key: str | None = Field(None, description="API key (fhir_r4 + api_key)")

    # rest_api fields
    api_base_url: str | None = Field(
        None, description="REST API base URL (required for rest_api)"
    )
    api_auth_type: Literal["none", "basic", "bearer", "api_key"] | None = Field(
        None, description="REST API auth mechanism"
    )
    api_username: str | None = Field(
        None, description="Basic auth username (rest_api + basic)"
    )
    api_password: str | None = Field(
        None, description="Basic auth password (rest_api + basic)"
    )
    api_token: str | None = Field(
        None, description="Bearer token or API key (rest_api + bearer/api_key)"
    )
    api_key_header: str | None = Field(
        None,
        description="Header name for API key, e.g. 'X-Api-Key' (rest_api + api_key)",
    )

    @field_validator("fhir_base_url", "api_base_url")
    @classmethod
    def strip_trailing_slash(cls, v: str | None) -> str | None:
        return v.rstrip("/") if v else v

    def model_post_init(self, __context: Any) -> None:
        """Cross-field validation based on connection_type."""
        ct = self.connection_type

        if ct == "fhir_r4":
            if not self.fhir_base_url:
                raise ValueError("connection_type 'fhir_r4' requires fhir_base_url")

        elif ct == "rest_api":
            if not self.api_base_url:
                raise ValueError("connection_type 'rest_api' requires api_base_url")


class UpdateConnectionRequest(BaseModel):
    """Payload for updating an existing EMR connection. All fields are optional."""

    name: str | None = Field(None, min_length=1, max_length=200)
    vendor: str | None = Field(None, min_length=1, max_length=100)
    connection_type: ConnectionType | None = None
    is_active: bool | None = None

    # fhir_r4 fields
    fhir_base_url: str | None = None
    fhir_auth_type: Literal["none", "oauth2", "api_key"] | None = None
    fhir_token_url: str | None = None
    fhir_client_id: str | None = None
    fhir_client_secret: str | None = None
    fhir_api_key: str | None = None

    # OAuth2 scope override
    scope: str | None = None

    # sync fields
    sync_enabled: bool | None = None
    sync_interval_minutes: int | None = Field(None, ge=5, le=1440)

    # rest_api fields
    api_base_url: str | None = None
    api_auth_type: Literal["none", "basic", "bearer", "api_key"] | None = None
    api_username: str | None = None
    api_password: str | None = None
    api_token: str | None = None
    api_key_header: str | None = None

    @field_validator("fhir_base_url", "api_base_url")
    @classmethod
    def strip_trailing_slash(cls, v: str | None) -> str | None:
        return v.rstrip("/") if v else v


class ConnectionResponse(BaseModel):
    """EMR connection representation with credentials masked."""

    id: int
    name: str
    vendor: str
    connection_type: str
    is_active: bool

    # fhir_r4 — secrets masked
    fhir_base_url: str | None = None
    fhir_auth_type: str | None = None
    fhir_token_url: str | None = None
    fhir_client_id: str | None = None
    fhir_client_secret: str | None = Field(
        None, description="Always masked in responses"
    )
    fhir_api_key: str | None = Field(None, description="Always masked in responses")

    # rest_api — credentials masked
    api_base_url: str | None = None
    api_auth_type: str | None = None
    api_username: str | None = None
    api_password: str | None = Field(None, description="Always masked in responses")
    api_token: str | None = Field(None, description="Always masked in responses")
    api_key_header: str | None = None


class VendorPresetResponse(BaseModel):
    """Vendor preset configuration with default values."""

    model_config = {"extra": "allow"}

    vendor: str
    display_name: str
    connection_type: str | None = None
    notes: str | None = None


class SyncHistoryResponse(BaseModel):
    """One entry in the sync history log."""

    id: int
    connection_id: int
    sync_type: str
    status: Literal["pending", "running", "completed", "failed"]
    started_at: str | None = None
    completed_at: str | None = None
    records_synced: int | None = None
    error_message: str | None = None


class FieldMappingsRequest(BaseModel):
    """Payload for updating field mappings on a connection."""

    mappings: dict[str, Any] = Field(
        ...,
        description="Key/value mapping of source field names to destination field names or transformation specs",
    )


class UpdateSyncScheduleRequest(BaseModel):
    """Payload for enabling/disabling automatic sync and configuring its interval."""

    sync_enabled: bool = Field(
        ..., description="Whether automatic syncing is active for this connection"
    )
    sync_interval_minutes: int = Field(
        60,
        ge=1,
        le=10080,  # max 1 week
        description="How often (in minutes) to run incremental syncs when sync_enabled=True",
    )
    sync_cron: str | None = Field(
        None,
        max_length=100,
        description="Optional cron expression for advanced scheduling (informational; used by Celery beat in prod)",
    )


class ManualMatchRequest(BaseModel):
    """Payload for manually linking an unmatched patient to an internal pid."""

    unmatched_id: int = Field(..., description="emr_unmatched_patients.id to resolve")
    internal_pid: int = Field(..., description="OpenEMR patient_data.pid to link to")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_CREDENTIAL_FIELDS = frozenset(
    {
        "fhir_client_secret",
        "fhir_api_key",
        "api_password",
        "api_token",
    }
)


def _require_connection(
    connection_id: int, tenant_id: str | None = None
) -> dict[str, Any]:
    """Fetch connection by ID (scoped to tenant when supplied) or raise HTTP 404."""
    conn = emr_mgr.get_connection(connection_id, tenant_id=tenant_id)
    if not conn:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"EMR connection {connection_id} not found",
        )
    return conn


def _flip_patient_cohort(connection_id: int, tenant_id: str) -> int:
    """Deactivate all patients for *tenant_id*, then reactivate those belonging
    to *connection_id*.

    Uses ``emr_connection_id`` — the correct FK column on the ``patients``
    table — to identify the cohort to restore.

    Returns the number of patients reactivated (``rowcount`` of the second
    UPDATE).
    """
    from app.db import raf_cursor

    with raf_cursor() as cur:
        cur.execute(
            "UPDATE patients SET is_active = 0 WHERE is_active = 1 AND tenant_id = %s",
            (tenant_id,),
        )
        cur.execute(
            "UPDATE patients SET is_active = 1"
            " WHERE emr_connection_id = %s AND tenant_id = %s",
            (connection_id, tenant_id),
        )
        restored = cur.rowcount or 0
    logger.info(
        "emr: flipped patient cohort for connection %s — %d patients reactivated",
        connection_id,
        restored,
    )
    return restored


def _mask_credentials(conn: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of the connection dict with sensitive fields masked
    and normalized field names for the frontend."""
    out = {k: ("***" if k in _CREDENTIAL_FIELDS and v else v) for k, v in conn.items()}
    # Mask private keys in extra_config
    if out.get("extra_config") and "private_key" in str(out["extra_config"]):
        import json as _json

        try:
            ec = (
                _json.loads(out["extra_config"])
                if isinstance(out["extra_config"], str)
                else out["extra_config"]
            )
            for key in list(ec):
                if "private" in key.lower() or "secret" in key.lower():
                    ec[key] = "***"
            out["extra_config"] = ec
        except Exception:
            out["extra_config"] = "***"
    # Add frontend-friendly aliases
    if "display_name" in out:
        out.setdefault("name", out["display_name"])
    if "base_url" in out:
        out.setdefault("fhir_base_url", out["base_url"])
    return out


# ---------------------------------------------------------------------------
# EMR Status & Demo Connect
# ---------------------------------------------------------------------------


@router.get("/status", summary="Check if any EMR connection is active")
@limiter.limit("60/minute")
def emr_status(
    request: Request,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> dict[str, Any]:
    """Return whether at least one active EMR connection exists, plus vendor metadata."""
    vendor: str | None = None
    is_demo: bool = False
    display_name: str | None = None
    connection_count: int = 0
    connected = False

    try:
        conns = emr_mgr.list_connections(tenant_id=tenant_id)
        connection_count = len(conns)
        for c in conns:
            if c.get("is_active"):
                connected = True
                vendor = c.get("vendor")
                display_name = c.get("display_name") or c.get("name")
                is_demo = vendor == "demo"
                break
    except Exception as exc:
        logger.warning("emr_status: could not retrieve connection list: %s", exc)

    return {
        "connected": connected,
        "vendor": vendor,
        "is_demo": is_demo,
        "connection_count": connection_count,
        "display_name": display_name,
    }


@router.post("/demo-connect", summary="Connect to the bundled OpenEMR instance")
@limiter.limit("30/minute")
def demo_connect(
    request: Request,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> dict[str, Any]:
    """Connect to the bundled OpenEMR demo instance.

    Activates the first available OpenEMR connection (FHIR or direct DB).
    If no connection exists, attempts auto-registration from environment variables.
    """
    import os

    # Check if already connected — return any active OpenEMR connection
    try:
        conns = emr_mgr.list_connections(tenant_id=tenant_id)
        for c in conns:
            if c.get("is_active"):
                return {
                    "success": True,
                    "message": "OpenEMR already connected",
                    "connection": _mask_credentials(c),
                }
    except Exception as exc:
        logger.warning("auto_connect_openemr failed: %s", exc)

    # Try to activate an existing inactive OpenEMR connection
    try:
        conns = emr_mgr.list_connections(tenant_id=tenant_id)
        for c in conns:
            vendor = (c.get("vendor") or "").lower()
            if "openemr" in vendor or "fhir" in vendor:
                conn_id = c["id"]
                # deactivate_other_connections now atomically activates this
                # connection and deactivates all others in one transaction.
                emr_mgr.deactivate_other_connections(conn_id, tenant_id=tenant_id)
                updated = emr_mgr.get_connection(conn_id, tenant_id=tenant_id)
                return {
                    "success": True,
                    "message": "OpenEMR connected successfully",
                    "connection": _mask_credentials(updated),
                }
    except Exception as exc:
        logger.warning("auto_connect_openemr failed: %s", exc)

    # Fallback: auto-register from env vars (direct DB)
    openemr_host = os.getenv("OPENEMR_DB_HOST", "")
    if not openemr_host:
        raise HTTPException(
            status_code=400,
            detail="No OpenEMR connection configured. Go to Integrations to add one.",
        )

    try:
        result = emr_mgr.auto_register_openemr()
        if result is None:
            raise HTTPException(
                status_code=500,
                detail="Failed to register OpenEMR connection.",
            )
        return {
            "success": True,
            "message": "OpenEMR connected successfully",
            "connection": _mask_credentials(result),
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("demo_connect: OpenEMR registration failed: %s", exc)
        raise HTTPException(
            status_code=500,
            detail="Internal server error",
        )


# ---------------------------------------------------------------------------
# Vendor Presets (read-only, any authenticated user)
# ---------------------------------------------------------------------------


@router.get(
    "/vendors",
    summary="List all EMR vendor presets",
    response_model=list[VendorPresetResponse],
)
@limiter.limit("60/minute")
def list_vendors(
    request: Request,
    current_user: dict = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """
    Return the full catalogue of supported EMR vendor presets.

    Each preset contains the vendor's supported connection types and sensible
    defaults (e.g. default port, auth type) that are pre-filled when creating
    a new connection.  Read-only; available to any authenticated user.
    """
    try:
        vendors = emr_mgr.get_vendor_presets()
    except Exception as exc:
        logger.error("list_vendors error: %s", exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    return vendors


@router.get(
    "/vendors/{vendor}",
    summary="Get a single EMR vendor preset with defaults",
    response_model=VendorPresetResponse,
)
@limiter.limit("60/minute")
def get_vendor(
    request: Request,
    vendor: str,
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Return the preset for a specific EMR vendor including all default field
    values to pre-populate a connection creation form.

    Returns HTTP 404 when the vendor identifier is not recognised.
    """
    try:
        preset = emr_mgr.get_vendor_preset(vendor)
    except Exception as exc:
        logger.error("get_vendor %s error: %s", vendor, exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    if not preset:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Vendor preset '{vendor}' not found",
        )

    return preset


# ---------------------------------------------------------------------------
# Connection CRUD (admin or manager only for writes)
# ---------------------------------------------------------------------------


@router.post(
    "/connections",
    summary="Create a new EMR connection",
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("30/minute")
def create_connection(
    request: Request,
    body: CreateConnectionRequest,
    tenant_id: str = Depends(get_tenant_id),
    current_user: dict = Depends(require_role("admin", "manager")),
) -> dict[str, Any]:
    """
    Register a new EMR connection.

    The ``connection_type`` field determines which additional fields are
    required:
    - ``fhir_r4``: supply ``fhir_base_url`` and optional auth fields.
    - ``rest_api``: supply ``api_base_url`` and optional auth fields.

    Credential fields (``fhir_client_secret``,
    ``fhir_api_key``, ``api_password``, ``api_token``) are stored but never
    returned in plain text — they are masked as ``"***"`` in all subsequent
    GET responses.
    """
    try:
        data = body.model_dump(exclude_none=False)
        data["tenant_id"] = tenant_id
        # Map router field names to emr_manager expected names
        if "name" in data and "display_name" not in data:
            data["display_name"] = data.pop("name")
        if "fhir_base_url" in data and "base_url" not in data:
            data["base_url"] = data.get("fhir_base_url")
        if "fhir_client_id" in data and "client_id" not in data:
            data["client_id"] = data.pop("fhir_client_id")
        if "fhir_client_secret" in data and "client_secret" not in data:
            data["client_secret"] = data.pop("fhir_client_secret")
        if "fhir_token_url" in data and "token_url" not in data:
            data["token_url"] = data.pop("fhir_token_url")
        if "fhir_auth_type" in data and "auth_type" not in data:
            data["auth_type"] = data.pop("fhir_auth_type")
        new_id = emr_mgr.create_connection(data)
    except ValueError as exc:
        logger.error("Unexpected error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid input"
        )
    except Exception as exc:
        logger.error("create_connection error: %s", exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    # create_connection returns the full connection dict
    conn = (
        new_id
        if isinstance(new_id, dict)
        else (emr_mgr.get_connection(new_id, tenant_id=tenant_id) or {})
    )
    conn_id = conn.get("id", new_id) if isinstance(conn, dict) else new_id
    return {
        "id": conn_id,
        "message": "EMR connection created",
        "connection": _mask_credentials(conn),
    }


@router.get(
    "/connections",
    summary="List all EMR connections",
)
@limiter.limit("60/minute")
def list_connections(
    request: Request,
    tenant_id: str = Depends(get_tenant_id),
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Return all registered EMR connections.

    Credential fields are masked in the response.  Available to any
    authenticated user; use the write endpoints to mutate connections.
    """
    try:
        rows = emr_mgr.list_connections(tenant_id)
    except Exception as exc:
        logger.error("list_connections error: %s", exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    return {
        "count": len(rows),
        "connections": [_mask_credentials(r) for r in rows],
    }


@router.get(
    "/connections/{connection_id}",
    summary="Get an EMR connection by ID",
)
@limiter.limit("60/minute")
def get_connection(
    request: Request,
    connection_id: int,
    tenant_id: str = Depends(get_tenant_id),
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Return a single EMR connection record with credentials masked.

    Raises HTTP 404 when the connection ID does not exist.
    """
    conn = _require_connection(connection_id, tenant_id)
    return _mask_credentials(conn)


@router.put(
    "/connections/{connection_id}",
    summary="Update an EMR connection",
)
@limiter.limit("30/minute")
def update_connection(
    request: Request,
    connection_id: int,
    body: UpdateConnectionRequest,
    tenant_id: str = Depends(get_tenant_id),
    current_user: dict = Depends(require_role("admin", "manager")),
) -> dict[str, Any]:
    """
    Update mutable fields on an existing EMR connection.

    Only fields explicitly included in the request body are changed; omitted
    fields retain their current values.  Credential fields submitted in the
    body will overwrite stored values.
    """
    _require_connection(connection_id, tenant_id)

    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No fields provided for update",
        )

    # Enforce one-active-at-a-time: deactivate all other connections for this
    # tenant whenever this connection is being set to active.
    _activating = updates.get("is_active") is True or updates.get("is_active") == 1
    if _activating:
        emr_mgr.deactivate_other_connections(connection_id, tenant_id=tenant_id)
        try:
            _flip_patient_cohort(connection_id, tenant_id)
        except Exception as exc:
            logger.error(
                "Failed to flip patient activation for connection %s: %s",
                connection_id,
                exc,
            )
        # Invalidate ALL caches so stale data from previous connection isn't served
        from app.services.cache_strategy import invalidate_all_for_tenant
        from app.cache import cache_delete_pattern
        try:
            invalidate_all_for_tenant(tenant_id)
            cache_delete_pattern("report:*")
            cache_delete_pattern("analytics:*")
        except Exception:
            pass
        # Auto-trigger sync + RAF calc pipeline
        try:
            from app.services.celery_tasks import task_emr_activate_pipeline
            task_emr_activate_pipeline.delay(connection_id, tenant_id)
        except Exception as exc:
            logger.warning("update_connection: failed to trigger auto-pipeline: %s", exc)

    # Map router field names to emr_manager expected names
    if "name" in updates and "display_name" not in updates:
        updates["display_name"] = updates.pop("name")
    if "fhir_base_url" in updates and "base_url" not in updates:
        updates["base_url"] = updates.get("fhir_base_url")
    if "fhir_client_id" in updates and "client_id" not in updates:
        updates["client_id"] = updates.pop("fhir_client_id")
    if "fhir_client_secret" in updates and "client_secret" not in updates:
        updates["client_secret"] = updates.pop("fhir_client_secret")
    if "fhir_token_url" in updates and "token_url" not in updates:
        updates["token_url"] = updates.pop("fhir_token_url")
    if "fhir_auth_type" in updates and "auth_type" not in updates:
        updates["auth_type"] = updates.pop("fhir_auth_type")
    try:
        emr_mgr.update_connection(connection_id, updates, tenant_id=tenant_id)
    except ValueError as exc:
        logger.error("Unexpected error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid input"
        )
    except Exception as exc:
        logger.error("update_connection %s error: %s", connection_id, exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    conn = emr_mgr.get_connection(connection_id, tenant_id=tenant_id)
    return {
        "message": "Connection updated",
        "connection": _mask_credentials(conn),
    }


@router.delete(
    "/connections/{connection_id}",
    summary="Delete an EMR connection",
)
@limiter.limit("30/minute")
def delete_connection(
    request: Request,
    connection_id: int,
    tenant_id: str = Depends(get_tenant_id),
    current_user: dict = Depends(require_role("admin", "manager")),
) -> dict[str, Any]:
    """
    Permanently remove an EMR connection record.

    Associated sync history and field mapping rows are removed via cascade
    constraints on the database foreign keys.
    """
    _require_connection(connection_id, tenant_id)

    try:
        emr_mgr.delete_connection(connection_id, tenant_id=tenant_id)
    except Exception as exc:
        logger.error("delete_connection %s error: %s", connection_id, exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    return {"message": f"EMR connection {connection_id} deleted"}


@router.post(
    "/connections/{connection_id}/reactivate",
    summary="Reactivate an EMR connection and restore its patient cohort",
)
@limiter.limit("30/minute")
def reactivate_connection(
    request: Request,
    connection_id: int,
    tenant_id: str = Depends(get_tenant_id),
    current_user: dict = Depends(require_role("admin", "manager")),
) -> dict[str, Any]:
    """
    Reactivate a previously deactivated EMR connection.

    This is the inverse of a CSV "Replace" import: CSV uploads deactivate
    (rather than delete) the existing EMR-sourced patients so the original
    cohort can be restored at any time. Calling this endpoint:

    1. Marks the connection ``is_active = 1`` (and deactivates other connections).
    2. Deactivates every patient currently flagged active.
    3. Re-activates patients whose ``emr_connection_id`` matches this connection.
    """
    _require_connection(connection_id, tenant_id)

    # deactivate_other_connections atomically sets is_active=0 on all other
    # connections for this tenant and is_active=1 on this one — no separate
    # update_connection call is needed.
    try:
        emr_mgr.deactivate_other_connections(connection_id, tenant_id=tenant_id)
    except Exception as exc:
        logger.error("reactivate_connection %s error: %s", connection_id, exc)
        raise HTTPException(status_code=500, detail="Failed to reactivate connection")

    try:
        restored = _flip_patient_cohort(connection_id, tenant_id)
    except Exception as exc:
        logger.error(
            "reactivate_connection: failed to flip patients for %s: %s",
            connection_id,
            exc,
        )
        raise HTTPException(status_code=500, detail="Failed to restore patient cohort")

    # Invalidate ALL caches so stale data from previous connection isn't served
    from app.services.cache_strategy import invalidate_all_for_tenant
    from app.cache import cache_delete_pattern
    try:
        invalidate_all_for_tenant(tenant_id)
        cache_delete_pattern("report:*")
        cache_delete_pattern("analytics:*")
    except Exception:
        pass

    # P1: Auto-trigger sync + RAF calc in background after activation
    sync_triggered = False
    try:
        from app.services.celery_tasks import task_emr_activate_pipeline
        task_emr_activate_pipeline.delay(connection_id, tenant_id)
        sync_triggered = True
    except Exception as exc:
        logger.warning("reactivate_connection: failed to trigger auto-pipeline: %s", exc)

    return {
        "message": "Connection reactivated",
        "connection_id": connection_id,
        "patients_restored": restored,
        "pipeline_triggered": sync_triggered,
    }


# ---------------------------------------------------------------------------
# Connection Operations
# ---------------------------------------------------------------------------


@router.post(
    "/connections/{connection_id}/test",
    summary="Test EMR connection connectivity",
)
@limiter.limit("30/minute")
def test_connection(
    request: Request,
    connection_id: int,
    tenant_id: str = Depends(get_tenant_id),
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Attempt to establish a connection to the remote EMR system and return
    the result.

    Response includes:
    - ``success``: boolean indicating whether connectivity was confirmed
    - ``message``: human-readable description of the outcome
    - ``latency_ms``: round-trip latency in milliseconds (None on failure)

    Returns HTTP 502 when the remote system is unreachable or returns an error.
    """
    conn = _require_connection(connection_id, tenant_id)

    try:
        result = emr_mgr.test_connection(connection_id, tenant_id=tenant_id)
    except Exception as exc:
        logger.error("test_connection %s error: %s", connection_id, exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    if not result.get("success"):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=result.get("message", "Connection test failed"),
        )

    return result


# ---------------------------------------------------------------------------
# OAuth2 Authorization Code + PKCE
# ---------------------------------------------------------------------------

import hashlib
import base64
import secrets as _secrets
from urllib.parse import urlencode as _urlencode


class OAuth2CallbackBody(BaseModel):
    code: str
    state: str


def _build_client_assertion_jwt(
    client_id: str, token_url: str, private_key_pem: str
) -> str:
    """Build a signed JWT for private_key_jwt client authentication (RFC 7523)."""
    import jwt as _pyjwt
    import time as _time

    now = int(_time.time())
    payload = {
        "iss": client_id,
        "sub": client_id,
        "aud": token_url,
        "iat": now,
        "exp": now + 300,
        "jti": _secrets.token_hex(16),
    }
    return _pyjwt.encode(
        payload, private_key_pem, algorithm="RS384", headers={"kid": "ovXW4xFVHBo"}
    )


@router.get(
    "/connections/{connection_id}/oauth2/authorize",
    summary="Get OAuth2 authorization URL",
)
@limiter.limit("60/minute")
def oauth2_authorize(
    connection_id: int,
    request: Request,
    tenant_id: str = Depends(get_tenant_id),
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Generate an OAuth2 authorization URL with PKCE for the given EMR connection.
    The frontend should redirect the user's browser to the returned URL."""
    conn = _require_connection(connection_id, tenant_id)
    full_conn = emr_mgr.get_connection_with_credentials(
        connection_id, tenant_id=tenant_id
    )

    # PKCE: generate code_verifier and code_challenge
    code_verifier = _secrets.token_urlsafe(64)
    code_challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    state = _secrets.token_urlsafe(32)

    # Build authorize URL
    authorize_url = conn.get("authorize_url") or ""
    if not authorize_url:
        # Derive from base_url: extract scheme+host, append /oauth2/default/authorize
        base = (conn.get("base_url") or "").rstrip("/")
        from urllib.parse import urlparse as _urlparse

        parsed = _urlparse(base)
        authorize_url = f"{parsed.scheme}://{parsed.netloc}/oauth2/default/authorize"

    if not authorize_url:
        raise HTTPException(
            400, "Cannot determine authorize URL. Set it in the connection config."
        )

    # Build redirect_uri from Origin/Referer header or fallback
    origin = request.headers.get("origin") or request.headers.get("referer") or ""
    if origin:
        origin = origin.split("/emr-config")[0].split("/api/")[0].rstrip("/")
    redirect_uri = (
        f"{origin}/emr-config/callback"
        if origin
        else "http://localhost:3444/emr-config/callback"
    )

    # Store state for callback verification (redirect_uri stored so callback uses the same one)
    emr_mgr.store_oauth2_state(connection_id, state, code_verifier, redirect_uri)
    scope = (
        conn.get("scope")
        or full_conn.get("scope")
        or "openid api:fhir user/Patient.read user/Condition.read user/Encounter.read"
    )
    client_id = full_conn.get("client_id") or conn.get("client_id") or ""

    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": scope,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }

    return {"authorize_url": f"{authorize_url}?{_urlencode(params)}"}


@router.post(
    "/connections/oauth2/callback",
    summary="Exchange OAuth2 authorization code for tokens",
)
@limiter.limit("30/minute")
def oauth2_callback(
    request: Request,
    body: OAuth2CallbackBody,
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Exchange an authorization code for access and refresh tokens.
    Called by the frontend after the user authorizes in the EMR."""
    # Look up and consume the state (one-time use)
    state_data = emr_mgr.pop_oauth2_state(body.state)
    if not state_data:
        raise HTTPException(
            400, "Invalid or expired state parameter. Please try authorizing again."
        )

    connection_id = state_data["connection_id"]
    code_verifier = state_data["code_verifier"]
    redirect_uri = (
        state_data.get("redirect_uri") or "http://localhost:3444/emr-config/callback"
    )

    conn = emr_mgr.get_connection_with_credentials(connection_id)
    if not conn:
        raise HTTPException(404, "Connection not found")

    token_url = conn.get("token_url") or ""
    if not token_url:
        raise HTTPException(400, "No token_url configured for this connection")

    # Exchange code for tokens
    import httpx as _httpx

    client_id = conn.get("client_id") or ""
    client_secret = conn.get("client_secret") or ""

    token_data = {
        "grant_type": "authorization_code",
        "code": body.code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "code_verifier": code_verifier,
    }

    # For confidential clients using private_key_jwt auth, create a signed JWT assertion
    extra_config = conn.get("extra_config") or {}
    if isinstance(extra_config, str):
        import json as _json

        try:
            extra_config = _json.loads(extra_config)
        except Exception:
            extra_config = {}
    jwks_private_key_pem = extra_config.get("jwks_private_key_pem") or ""

    if jwks_private_key_pem:
        # Generate client_assertion JWT
        try:
            client_assertion = _build_client_assertion_jwt(
                client_id, token_url, jwks_private_key_pem
            )
            token_data["client_assertion_type"] = (
                "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
            )
            token_data["client_assertion"] = client_assertion
            logger.info("Using private_key_jwt authentication for token exchange")
        except Exception as exc:
            logger.warning(
                "Failed to build client assertion, falling back to client_secret: %s",
                exc,
            )
            if client_secret:
                token_data["client_secret"] = client_secret
    elif client_secret:
        token_data["client_secret"] = client_secret

    try:
        with _httpx.Client(timeout=30, verify=True) as client:
            resp = client.post(
                token_url,
                data=token_data,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
                },
            )
    except Exception as exc:
        logger.error("OAuth2 token exchange network error: %s", exc)
        raise HTTPException(502, "Failed to reach token endpoint")

    if resp.status_code != 200:
        logger.error(
            "OAuth2 token exchange failed (%s): %s", resp.status_code, resp.text[:300]
        )
        raise HTTPException(502, "Token exchange failed")

    tokens = resp.json()
    logger.info(
        "OAuth2 token response keys: %s, token_type: %s",
        list(tokens.keys()),
        tokens.get("token_type", "N/A"),
    )
    access_token = tokens.get("access_token", "")
    refresh_token = tokens.get("refresh_token", "")
    expires_in = tokens.get("expires_in", 3600)

    if not access_token:
        raise HTTPException(502, "No access_token in token response")

    # Store encrypted tokens
    emr_mgr.store_oauth2_tokens(connection_id, access_token, refresh_token, expires_in)

    return {
        "success": True,
        "connection_id": connection_id,
        "message": "Authorization successful. Tokens stored.",
        "expires_in": expires_in,
    }


@router.post(
    "/connections/{connection_id}/sync",
    summary="Trigger an EMR data sync",
    status_code=status.HTTP_202_ACCEPTED,
)
@limiter.limit("30/minute")
def trigger_sync(
    request: Request,
    connection_id: int,
    sync_type: Literal["full", "incremental"] = Query(
        "incremental",
        description="'full' re-syncs all records; 'incremental' syncs only changes since the last run",
    ),
    tenant_id: str = Depends(get_tenant_id),
    current_user: dict = Depends(require_role("admin", "manager")),
) -> dict[str, Any]:
    """
    Kick off a data sync for the specified EMR connection.

    The sync runs asynchronously; this endpoint returns HTTP 202 immediately
    with a ``sync_id`` you can use to track progress via the sync history
    endpoint.

    **sync_type** (query parameter):
    - ``incremental`` (default) — only fetch records changed since the last
      successful sync.
    - ``full`` — re-fetch all records regardless of last-sync timestamp.
    """
    conn = _require_connection(connection_id, tenant_id)

    if not conn.get("is_active"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"EMR connection {connection_id} is disabled. Enable it before syncing.",
        )

    try:
        result = emr_mgr.trigger_sync(
            connection_id, sync_type=sync_type, tenant_id=tenant_id
        )
    except ValueError as exc:
        logger.error("Unexpected error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Bad request"
        )
    except Exception as exc:
        logger.error("trigger_sync %s error: %s", connection_id, exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    log_phi_access(
        action="trigger_emr_sync",
        resource="emr_patients",
        patient_id=None,
        details=f"connection_id={connection_id} sync_type={sync_type}",
        tenant_id=tenant_id,
    )
    return {
        "message": "Sync started",
        "connection_id": connection_id,
        "sync_type": sync_type,
        "poll_url": f"/api/emr/connections/{connection_id}/sync/history",
        **result,
    }


@router.get(
    "/connections/{connection_id}/sync/history",
    summary="Get sync history for an EMR connection",
)
@limiter.limit("60/minute")
def get_sync_history(
    request: Request,
    connection_id: int,
    limit: int = Query(
        20, ge=1, le=100, description="Maximum number of history entries to return"
    ),
    tenant_id: str = Depends(get_tenant_id),
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Return recent sync history for the connection, most recent first.

    Each entry shows the sync type, status (pending / running / completed /
    failed), record counts, start/end timestamps, and any error message.
    """
    _require_connection(connection_id, tenant_id)

    try:
        history = emr_mgr.get_sync_history(
            connection_id, limit=limit, tenant_id=tenant_id
        )
    except Exception as exc:
        logger.error("get_sync_history %s error: %s", connection_id, exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    latest_status = history[0]["status"] if history else "never_synced"

    return {
        "connection_id": connection_id,
        "latest_status": latest_status,
        "total_returned": len(history),
        "history": history,
    }


# ---------------------------------------------------------------------------
# Sync Schedule Management
# ---------------------------------------------------------------------------


@router.put(
    "/connections/{connection_id}/schedule",
    summary="Update the automatic sync schedule for an EMR connection",
)
@limiter.limit("30/minute")
def update_sync_schedule(
    request: Request,
    connection_id: int,
    body: UpdateSyncScheduleRequest,
    current_user: dict = Depends(require_role("admin", "manager")),
) -> dict[str, Any]:
    """
    Enable or disable automatic syncing and configure the sync interval for
    the specified EMR connection.

    When sync_enabled is True, the background scheduler will
    automatically trigger an incremental sync every sync_interval_minutes
    minutes.  Set sync_enabled to False to pause automatic syncing
    without losing the interval configuration.

    The sync_cron field is informational for the simple-compose scheduler
    and is used by Celery beat in production deployments.
    """
    _require_connection(connection_id)

    try:
        updated = emr_mgr.update_sync_schedule(
            connection_id,
            sync_enabled=body.sync_enabled,
            sync_interval_minutes=body.sync_interval_minutes,
            sync_cron=body.sync_cron,
        )
    except ValueError as exc:
        logger.error("Unexpected error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid input"
        )
    except Exception as exc:
        logger.error("update_sync_schedule %s error: %s", connection_id, exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    return {
        "message": "Sync schedule updated",
        "connection_id": connection_id,
        "sync_enabled": body.sync_enabled,
        "sync_interval_minutes": body.sync_interval_minutes,
        "sync_cron": body.sync_cron,
        "connection": _mask_credentials(updated),
    }


# ---------------------------------------------------------------------------
# Field Mappings
# ---------------------------------------------------------------------------


@router.get(
    "/connections/{connection_id}/mappings",
    summary="Get field mappings for an EMR connection",
)
@limiter.limit("60/minute")
def get_field_mappings(
    request: Request,
    connection_id: int,
    tenant_id: str = Depends(get_tenant_id),
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Return the configured field mappings for this connection.

    Field mappings define how source EMR fields are translated to the
    canonical RAF Intelligence schema.  An empty ``mappings`` dict indicates
    that the vendor defaults are in use.
    """
    conn = _require_connection(connection_id, tenant_id)

    try:
        # Return stored field_mappings if present, otherwise vendor defaults
        stored = conn.get("field_mappings")
        if stored:
            mappings = stored if isinstance(stored, dict) else {}
        else:
            mappings = emr_mgr.get_default_mappings(conn.get("vendor", ""))
    except Exception as exc:
        logger.error("get_field_mappings %s error: %s", connection_id, exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    return {
        "connection_id": connection_id,
        "mappings": mappings,
    }


@router.put(
    "/connections/{connection_id}/mappings",
    summary="Update field mappings for an EMR connection",
)
@limiter.limit("30/minute")
def update_field_mappings(
    request: Request,
    connection_id: int,
    body: FieldMappingsRequest,
    tenant_id: str = Depends(get_tenant_id),
    current_user: dict = Depends(require_role("admin", "manager")),
) -> dict[str, Any]:
    """
    Replace the field mappings for this connection with the supplied
    ``mappings`` dict.

    The entire mappings object is replaced on each PUT.  To clear all custom
    mappings and revert to vendor defaults, send an empty dict: ``{}``.
    """
    _require_connection(connection_id, tenant_id)

    try:
        emr_mgr.update_mappings(connection_id, body.mappings)
    except ValueError as exc:
        logger.error("Unexpected error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid input"
        )
    except Exception as exc:
        logger.error("update_field_mappings %s error: %s", connection_id, exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    return {
        "message": "Field mappings updated",
        "connection_id": connection_id,
        "mappings": body.mappings,
    }


# ---------------------------------------------------------------------------
# Patient Matching
# ---------------------------------------------------------------------------


@router.get(
    "/connections/{connection_id}/patients/unmatched",
    summary="List unmatched patients pending manual review",
)
@limiter.limit("60/minute")
def list_unmatched_patients(
    request: Request,
    connection_id: int,
    limit: int = Query(50, ge=1, le=200, description="Max records to return"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    patient_status: Literal["pending", "matched", "rejected", "all"] = Query(
        "pending",
        alias="status",
        description="Filter by match status",
    ),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> dict[str, Any]:
    """
    Return patient records from this EMR connection that could not be
    automatically matched to an internal OpenEMR patient.

    Use the ``status`` query parameter to filter by review state:
    - ``pending``  (default) — awaiting human review
    - ``matched``  — already resolved via manual_match
    - ``rejected`` — explicitly dismissed
    - ``all``      — no filter

    Response includes a ``suggested_pid`` and ``suggested_confidence`` when a
    near-match candidate was identified but fell below the auto-link threshold.
    """
    _require_connection(connection_id)

    try:
        result = patient_matcher.get_unmatched_patients(
            connection_id,
            limit=limit,
            offset=offset,
            status=patient_status,
        )
    except Exception as exc:
        logger.error("list_unmatched_patients %s error: %s", connection_id, exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    log_phi_access(
        action="view_unmatched_patients",
        resource="emr_patients",
        patient_id=None,
        details=f"connection_id={connection_id} status={patient_status} limit={limit} offset={offset}",
        tenant_id=tenant_id,
    )
    return {"connection_id": connection_id, **result}


@router.post(
    "/connections/{connection_id}/patients/match",
    summary="Manually link an unmatched patient to an internal OpenEMR patient",
    status_code=status.HTTP_200_OK,
)
@limiter.limit("30/minute")
def manual_match_patient(
    request: Request,
    connection_id: int,
    body: ManualMatchRequest,
    current_user: dict = Depends(require_role("admin", "manager")),
) -> dict[str, Any]:
    """
    Confirm a manual patient identity match.

    Sets the ``emr_unmatched_patients`` record to status ``matched`` and
    creates a row in ``emr_patient_matches`` attributed to the requesting
    user.

    Raises HTTP 404 when the connection does not exist, HTTP 422 when the
    unmatched record is not in ``pending`` state or the target pid is not
    found in OpenEMR.
    """
    _require_connection(connection_id)

    reviewer = current_user.get("username") or current_user.get("email") or "unknown"

    try:
        match = patient_matcher.manual_match(
            unmatched_id=body.unmatched_id,
            internal_pid=body.internal_pid,
            matched_by=reviewer,
        )
    except ValueError as exc:
        logger.error("Unexpected error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid input"
        )
    except Exception as exc:
        logger.error("manual_match_patient %s error: %s", connection_id, exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    return {
        "message": "Patient matched successfully",
        "connection_id": connection_id,
        "match": match,
    }


@router.get(
    "/connections/{connection_id}/patients/match-stats",
    summary="Get patient match statistics for an EMR connection",
)
@limiter.limit("60/minute")
def get_match_stats(
    request: Request,
    connection_id: int,
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Return aggregate patient matching statistics for this connection.

    Response fields:
    - ``total_matched``   — confirmed matches (auto + manual)
    - ``auto_matched``    — matched automatically above confidence threshold
    - ``manual_matched``  — confirmed by a human reviewer
    - ``unmatched``       — records still pending review
    - ``rejected``        — records explicitly dismissed
    - ``match_rate``      — total_matched / (total_matched + unmatched), 0–1
    """
    _require_connection(connection_id)

    try:
        stats = patient_matcher.get_match_stats(connection_id)
    except Exception as exc:
        logger.error("get_match_stats %s error: %s", connection_id, exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    return stats


# ---------------------------------------------------------------------------
# HL7v2 / MLLP listener management
# ---------------------------------------------------------------------------

from app.services.hl7v2_service import (  # noqa: E402 — placed here to avoid circular imports at module level
    MLLPListener,
    HL7Message,
    HL7ParseError,
    get_listener,
    parse_hl7_message,
    register_listener,
    unregister_listener,
    extract_diagnoses,
    extract_observations,
    extract_patient,
)


class HL7ListenerStartRequest(BaseModel):
    """Optional parameters for starting an MLLP listener."""

    host: str = Field(
        "0.0.0.0",
        description="IP address to bind the MLLP listener to",
    )
    port: int = Field(
        2575,
        ge=1,
        le=65535,
        description="TCP port to listen on (HL7v2 standard port is 2575)",
    )


class HL7ParseRequest(BaseModel):
    """Raw HL7v2 message for parsing/debugging."""

    raw: str = Field(
        ...,
        min_length=4,
        description=(
            "Raw HL7v2 message text.  Segment separator may be \\r, \\n, or \\r\\n. "
            "Do not include MLLP framing bytes."
        ),
    )


@router.post(
    "/connections/{connection_id}/hl7/start",
    summary="Start the MLLP listener for an HL7v2 connection",
    status_code=status.HTTP_200_OK,
)
@limiter.limit("30/minute")
def start_hl7_listener(
    request: Request,
    connection_id: int,
    body: HL7ListenerStartRequest = HL7ListenerStartRequest(),
    current_user: dict = Depends(require_role("admin", "manager")),
) -> dict[str, Any]:
    """
    Start a TCP/MLLP listener for the specified HL7v2 EMR connection.

    The listener runs in a background daemon thread and will accept inbound
    HL7v2 messages framed with MLLP (Minimum Lower Layer Protocol).  Each
    received message is parsed and logged; extend the handler in
    ``hl7v2_service.py`` to persist messages or trigger RAF score updates.

    Returns HTTP 400 when:
    - The connection is not of type ``hl7v2``
    - A listener is already running for this connection

    Returns HTTP 409 when the requested port is already bound.
    """
    conn = _require_connection(connection_id)

    if conn.get("connection_type") != "hl7v2":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Connection {connection_id} is type '{conn.get('connection_type')}', "
                "not 'hl7v2'.  MLLP listener can only be started for hl7v2 connections."
            ),
        )

    existing = get_listener(connection_id)
    if existing and existing.is_running:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"MLLP listener for connection {connection_id} is already running "
                f"on {existing.host}:{existing.port}"
            ),
        )

    listener = MLLPListener(
        host=body.host,
        port=body.port,
        connection_id=connection_id,
    )

    try:
        listener.start()
    except OSError as exc:
        logger.error(
            "start_hl7_listener: cannot bind port %s:%s for connection %s: %s",
            body.host,
            body.port,
            connection_id,
            exc,
        )
        logger.error("Unexpected error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Conflict",
        )
    except RuntimeError as exc:
        logger.error("Unexpected error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Bad request",
        )

    register_listener(connection_id, listener)

    logger.info(
        "start_hl7_listener: started MLLP listener connection_id=%s %s:%s by user=%s",
        connection_id,
        body.host,
        body.port,
        current_user.get("username", current_user.get("sub", "unknown")),
    )

    return {
        "message": f"MLLP listener started for connection {connection_id}",
        "connection_id": connection_id,
        **listener.status(),
    }


@router.post(
    "/connections/{connection_id}/hl7/stop",
    summary="Stop the MLLP listener for an HL7v2 connection",
    status_code=status.HTTP_200_OK,
)
@limiter.limit("30/minute")
def stop_hl7_listener(
    request: Request,
    connection_id: int,
    current_user: dict = Depends(require_role("admin", "manager")),
) -> dict[str, Any]:
    """
    Stop the running MLLP listener for the specified HL7v2 connection.

    Returns HTTP 404 when no listener is running for this connection.
    The listener thread is gracefully shut down and the server socket is closed.
    """
    _require_connection(connection_id)

    listener = get_listener(connection_id)
    if not listener or not listener.is_running:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No running MLLP listener found for connection {connection_id}",
        )

    try:
        listener.stop()
    except Exception as exc:
        logger.error(
            "stop_hl7_listener: error stopping listener for connection %s: %s",
            connection_id,
            exc,
        )
        logger.error("Unexpected error: %s", exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    unregister_listener(connection_id)

    logger.info(
        "stop_hl7_listener: stopped MLLP listener connection_id=%s by user=%s",
        connection_id,
        current_user.get("username", current_user.get("sub", "unknown")),
    )

    return {
        "message": f"MLLP listener stopped for connection {connection_id}",
        "connection_id": connection_id,
    }


@router.get(
    "/connections/{connection_id}/hl7/status",
    summary="Get the MLLP listener status for an HL7v2 connection",
)
@limiter.limit("60/minute")
def get_hl7_listener_status(
    request: Request,
    connection_id: int,
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Return the current status of the MLLP listener for the specified connection.

    The response includes:
    - ``running``:            whether the listener is currently accepting connections
    - ``host`` / ``port``:    the bound address
    - ``started_at``:         ISO-8601 timestamp when the listener was started
    - ``messages_received``:  total HL7 messages successfully processed
    - ``messages_errored``:   total messages that caused handler or parse errors

    Returns HTTP 404 when the connection does not exist.
    When no listener has been started, ``running`` will be ``false`` and all
    counters will be ``null``.
    """
    _require_connection(connection_id)

    listener = get_listener(connection_id)
    if not listener:
        return {
            "connection_id": connection_id,
            "running": False,
            "host": None,
            "port": None,
            "started_at": None,
            "messages_received": None,
            "messages_errored": None,
        }

    return {
        "connection_id": connection_id,
        **listener.status(),
    }


@router.post(
    "/hl7/parse",
    summary="Parse a raw HL7v2 message (testing / debugging)",
)
@limiter.limit("30/minute")
def parse_hl7(
    request: Request,
    body: HL7ParseRequest,
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Parse a raw HL7v2 message and return the extracted structured data.

    This endpoint is intended for testing, debugging, and integration
    validation.  It does **not** persist any data or trigger any workflows.

    The response includes:
    - ``message_type``:   e.g. ``ADT^A01``, ``ORU^R01``, ``DFT^P03``
    - ``patient``:        normalised patient demographics (from PID segment)
    - ``diagnoses``:      list of ICD-10 coded diagnoses (from DG1 segments)
    - ``observations``:   list of lab/vital results (from OBX segments)
    - ``segments``:       list of all segment type identifiers present
    - ``raw_preview``:    first 500 characters of the raw input (for confirmation)

    Returns HTTP 422 when the message cannot be parsed (bad framing, missing
    MSH segment, etc.).
    """
    try:
        msg: HL7Message = parse_hl7_message(body.raw)
    except HL7ParseError as exc:
        logger.error("Unexpected error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid input",
        )
    except Exception as exc:
        logger.error("parse_hl7: unexpected error: %s", exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    try:
        patient = extract_patient(msg)
        diagnoses = extract_diagnoses(msg)
        observations = extract_observations(msg)
    except Exception as exc:
        logger.error("parse_hl7: extraction error: %s", exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    return {
        "message_type": msg.message_type,
        "message_control_id": msg.message_control_id,
        "sending_application": msg.sending_application,
        "sending_facility": msg.sending_facility,
        "message_datetime": msg.message_datetime,
        "patient": patient,
        "diagnoses": diagnoses,
        "observations": observations,
        "segments": list(msg.segments.keys()),
        "raw_preview": body.raw[:500],
    }
