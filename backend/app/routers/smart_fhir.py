"""
SMART on FHIR Router.

Endpoints that implement the SMART on FHIR app-launch specification,
allowing this application to be launched from within an EHR (Epic,
Cerner, athenahealth, or any generic FHIR R4-compliant system).

Launch flows supported:
  - EHR-launch:        GET /api/smart/launch?iss=<fhir_base>&launch=<token>
  - Standalone-launch: GET /api/smart/launch?registration_id=<id>
  - OAuth2 callback:   GET /api/smart/callback?code=<code>&state=<state>

App-registration management (admin-only):
  POST   /api/smart/registrations
  GET    /api/smart/registrations
  PUT    /api/smart/registrations/{id}
  DELETE /api/smart/registrations/{id}

Session and context:
  GET /api/smart/context               — current SMART context for a session
  GET /api/smart/patient               — FHIR Patient resource for the session
  GET /api/smart/sessions              — active/recent SMART sessions
  GET /api/smart/.well-known/smart-configuration — this app's SMART metadata
"""
# Note: do NOT use 'from __future__ import annotations' — breaks Pydantic schema generation.

import logging
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse, JSONResponse
from pydantic import BaseModel, Field, HttpUrl, field_validator

from app.auth import get_current_user, get_tenant_id, require_role
from app.config import settings

import app.services.smart_fhir_service as smart_svc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/smart", tags=["smart_fhir"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class RegistrationCreate(BaseModel):
    """Payload for registering a new SMART app with an EHR."""

    name: str = Field(..., min_length=1, max_length=200, description="Human-readable label")
    ehr_vendor: Literal["epic", "cerner", "athenahealth", "generic"] = Field(
        "generic", description="EHR vendor"
    )
    client_id: str = Field(..., min_length=1, max_length=255, description="OAuth2 client_id from the EHR")
    client_secret: Optional[str] = Field(
        None,
        description="OAuth2 client_secret — omit for public clients. Stored encrypted.",
    )
    redirect_uri: str = Field(..., description="Registered OAuth2 redirect URI, e.g. https://app.example.com/api/smart/callback")
    scopes: str = Field(
        "launch patient/*.read openid fhirUser",
        description="Space-separated SMART/OAuth2 scopes",
    )
    launch_url: Optional[str] = Field(
        None, description="App gallery launch URL registered in the EHR (EHR-launch only)"
    )
    fhir_base_url: str = Field(..., description="FHIR R4 base URL, e.g. https://fhir.epic.example.com/api/FHIR/R4")
    token_endpoint: str = Field(..., description="OAuth2 token endpoint")
    authorize_endpoint: str = Field(..., description="OAuth2 authorization endpoint")
    status: Literal["active", "inactive"] = Field("active", description="Registration status")

    @field_validator("fhir_base_url", "token_endpoint", "authorize_endpoint", "redirect_uri", mode="before")
    @classmethod
    def _strip_trailing_slash(cls, v: str) -> str:
        return v.rstrip("/") if isinstance(v, str) else v


class RegistrationUpdate(BaseModel):
    """Fields that may be updated on an existing registration.  All optional."""

    name: Optional[str] = Field(None, min_length=1, max_length=200)
    ehr_vendor: Optional[Literal["epic", "cerner", "athenahealth", "generic"]] = None
    client_id: Optional[str] = Field(None, min_length=1, max_length=255)
    client_secret: Optional[str] = Field(None, description="New client_secret; stored encrypted.")
    redirect_uri: Optional[str] = None
    scopes: Optional[str] = None
    launch_url: Optional[str] = None
    fhir_base_url: Optional[str] = None
    token_endpoint: Optional[str] = None
    authorize_endpoint: Optional[str] = None
    status: Optional[Literal["active", "inactive"]] = None


class RegistrationResponse(BaseModel):
    """Public view of a SMART app registration (no secrets)."""

    id: int
    name: str
    ehr_vendor: str
    client_id: str
    redirect_uri: str
    scopes: str
    launch_url: Optional[str]
    fhir_base_url: str
    token_endpoint: str
    authorize_endpoint: str
    status: str
    tenant_id: str
    created_at: Any
    updated_at: Any

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# SMART configuration (public — no auth required)
# ---------------------------------------------------------------------------

@router.get(
    "/.well-known/smart-configuration",
    summary="SMART app configuration",
    tags=["smart_fhir"],
    include_in_schema=True,
)
def smart_configuration(request: Request) -> dict[str, Any]:
    """
    Advertise this application's SMART on FHIR capabilities.

    This endpoint is intentionally unauthenticated so EHR systems can
    discover it during app registration and launch validation.
    """
    base_url = str(request.base_url).rstrip("/")
    return {
        "issuer": base_url,
        "jwks_uri": f"{base_url}/api/auth/.well-known/jwks",
        "authorization_endpoint": f"{base_url}/api/smart/launch",
        "token_endpoint": f"{base_url}/api/auth/token",
        "token_endpoint_auth_methods_supported": ["client_secret_basic", "client_secret_post", "private_key_jwt"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "registration_endpoint": f"{base_url}/api/smart/registrations",
        "scopes_supported": [
            "openid", "fhirUser", "launch", "launch/patient",
            "patient/*.read", "user/*.read", "offline_access",
        ],
        "response_types_supported": ["code"],
        "management_endpoint": f"{base_url}/api/smart/sessions",
        "introspection_endpoint": f"{base_url}/api/auth/introspect",
        "capabilities": [
            "launch-ehr",
            "launch-standalone",
            "client-public",
            "client-confidential-symmetric",
            "context-ehr-patient",
            "context-ehr-encounter",
            "context-standalone-patient",
            "permission-patient",
            "permission-user",
            "sso-openid-connect",
            "authorize-post",
        ],
        "code_challenge_methods_supported": ["S256"],
    }


# ---------------------------------------------------------------------------
# EHR / standalone launch initiation
# ---------------------------------------------------------------------------

@router.get(
    "/launch",
    summary="Initiate SMART on FHIR EHR launch",
    response_class=RedirectResponse,
    status_code=302,
)
def smart_launch(
    registration_id: int = Query(..., description="ID of the SMART app registration to use"),
    iss: Optional[str] = Query(
        None,
        description="FHIR base URL supplied by the EHR on EHR-launch (the `iss` parameter)",
    ),
    launch: Optional[str] = Query(
        None,
        description="Opaque launch token supplied by the EHR on EHR-launch",
    ),
    tenant_id: str = Depends(get_tenant_id),
    current_user: dict = Depends(get_current_user),
) -> RedirectResponse:
    """
    Initiate a SMART on FHIR app launch.

    For **EHR-launch**: the EHR supplies `iss` and `launch` query parameters
    when opening the app.  The app redirects the user's browser to the EHR
    authorization endpoint.

    For **standalone-launch**: omit `launch`; the user selects the patient
    inside the EHR authorization dialog.
    """
    try:
        result = smart_svc.initiate_launch(
            registration_id=registration_id,
            tenant_id=tenant_id,
            launch_token=launch,
            iss=iss,
        )
    except ValueError as exc:
        logger.error("Unexpected error: %s", exc)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Bad request")
    except Exception as exc:
        logger.error("SMART launch initiation error: %s", exc, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Launch initiation failed")

    return RedirectResponse(url=result["redirect_url"], status_code=302)


# ---------------------------------------------------------------------------
# OAuth2 callback
# ---------------------------------------------------------------------------

@router.get(
    "/callback",
    summary="SMART on FHIR OAuth2 callback",
)
def smart_callback(
    code: str = Query(..., description="Authorization code returned by the EHR"),
    state: str = Query(..., description="CSRF state parameter echoed from the launch"),
    error: Optional[str] = Query(None, description="OAuth2 error code if authorization failed"),
    error_description: Optional[str] = Query(None),
    tenant_id: str = Depends(get_tenant_id),
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Handle the OAuth2 authorization callback from the EHR.

    Exchanges the authorization code for access/refresh tokens, extracts
    the SMART launch context, and returns the session ID that must be
    supplied to subsequent `/api/smart/context` and `/api/smart/patient`
    calls.
    """
    if error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"EHR authorization error: {error} — {error_description or ''}",
        )

    try:
        result = smart_svc.handle_callback(
            state=state,
            code=code,
            tenant_id=tenant_id,
        )
    except ValueError as exc:
        logger.error("Unexpected error: %s", exc)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Bad request")
    except Exception as exc:
        logger.error("SMART callback error: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="OAuth2 callback processing failed",
        )

    return result


# ---------------------------------------------------------------------------
# Session context and patient data
# ---------------------------------------------------------------------------

@router.get(
    "/context",
    summary="Get SMART launch context",
)
def get_context(
    session_id: int = Query(..., description="SMART session ID returned by the callback endpoint"),
    tenant_id: str = Depends(get_tenant_id),
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Return the SMART launch context for the given session.

    Contains the FHIR IDs of the patient, practitioner, and encounter
    that were supplied by the EHR at launch time.
    """
    try:
        return smart_svc.get_launch_context(session_id=session_id, tenant_id=tenant_id)
    except ValueError as exc:
        logger.error("Unexpected error: %s", exc)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found")
    except Exception as exc:
        logger.error("SMART context fetch error: %s", exc, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Context retrieval failed")


@router.get(
    "/patient",
    summary="Get FHIR Patient for the current SMART session",
)
def get_patient(
    session_id: int = Query(..., description="SMART session ID"),
    tenant_id: str = Depends(get_tenant_id),
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Fetch the FHIR Patient resource for the patient in scope for this session.

    The access token is used to call the EHR's FHIR API.  Results are
    cached in `smart_context_cache` for the lifetime of the session.
    Returns the raw FHIR Patient plus a mapped `internal_patient_id`
    if a match can be found in the local OpenEMR database.
    """
    try:
        return smart_svc.get_patient_data(session_id=session_id, tenant_id=tenant_id)
    except ValueError as exc:
        logger.error("Unexpected error: %s", exc)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Bad request")
    except Exception as exc:
        logger.error("SMART patient fetch error: %s", exc, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Patient data retrieval failed")


# ---------------------------------------------------------------------------
# Active session listing
# ---------------------------------------------------------------------------

@router.get(
    "/sessions",
    summary="List SMART launch sessions",
)
def list_sessions(
    session_status: Optional[str] = Query(
        None,
        alias="status",
        description="Filter by session status: initiated | authorized | active | expired | error",
    ),
    tenant_id: str = Depends(get_tenant_id),
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """
    List recent SMART launch sessions for this tenant.

    Returns up to 200 sessions, newest first.  Use `?status=active` to
    see only sessions with a valid access token.
    """
    try:
        sessions = smart_svc.list_sessions(tenant_id=tenant_id, status=session_status)
        return {"count": len(sessions), "sessions": sessions}
    except Exception as exc:
        logger.error("SMART session list error: %s", exc, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Session listing failed")


# ---------------------------------------------------------------------------
# App registration management  (admin-only)
# ---------------------------------------------------------------------------

@router.post(
    "/registrations",
    summary="Register a SMART app with an EHR",
    status_code=status.HTTP_201_CREATED,
)
def create_registration(
    body: RegistrationCreate,
    tenant_id: str = Depends(get_tenant_id),
    current_user: dict = Depends(require_role("admin", "superadmin")),
) -> dict[str, Any]:
    """
    Register this application as a SMART app with an EHR system.

    Stores the OAuth2 credentials (client_id, client_secret), endpoint
    URLs, and supported scopes.  The client_secret is encrypted at rest
    using AES-256-GCM.

    Requires the `admin` or `superadmin` role.
    """
    try:
        reg = smart_svc.create_registration(data=body.model_dump(), tenant_id=tenant_id)
        return {"registration": reg}
    except Exception as exc:
        logger.error("SMART registration create error: %s", exc, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Registration creation failed")


@router.get(
    "/registrations",
    summary="List SMART app registrations",
)
def list_registrations(
    tenant_id: str = Depends(get_tenant_id),
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Return all SMART app registrations for this tenant.  Secrets are never returned."""
    try:
        regs = smart_svc.list_registrations(tenant_id=tenant_id)
        return {"count": len(regs), "registrations": regs}
    except Exception as exc:
        logger.error("SMART registration list error: %s", exc, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Registration listing failed")


@router.put(
    "/registrations/{registration_id}",
    summary="Update a SMART app registration",
)
def update_registration(
    registration_id: int,
    body: RegistrationUpdate,
    tenant_id: str = Depends(get_tenant_id),
    current_user: dict = Depends(require_role("admin", "superadmin")),
) -> dict[str, Any]:
    """
    Update fields on an existing SMART app registration.

    All fields are optional — only supplied fields are written.
    To rotate the client_secret, include the new plaintext value;
    it will be encrypted before storage.

    Requires the `admin` or `superadmin` role.
    """
    try:
        reg = smart_svc.update_registration(
            registration_id=registration_id,
            data=body.model_dump(exclude_none=True),
            tenant_id=tenant_id,
        )
        if not reg:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Registration {registration_id} not found",
            )
        return {"registration": reg}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("SMART registration update error: %s", exc, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Registration update failed")


@router.delete(
    "/registrations/{registration_id}",
    summary="Delete a SMART app registration",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_registration(
    registration_id: int,
    tenant_id: str = Depends(get_tenant_id),
    current_user: dict = Depends(require_role("admin", "superadmin")),
) -> None:
    """
    Permanently remove a SMART app registration and all associated sessions.

    This action is irreversible.  Active sessions linked to this registration
    will be cascade-deleted by the database FK constraint.

    Requires the `admin` or `superadmin` role.
    """
    try:
        deleted = smart_svc.delete_registration(
            registration_id=registration_id, tenant_id=tenant_id
        )
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Registration {registration_id} not found",
            )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("SMART registration delete error: %s", exc, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Registration deletion failed")
