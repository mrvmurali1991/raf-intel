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

import base64
import hashlib
import json
import logging
import os
import secrets
from typing import Any, Literal
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field, field_validator

import app.services.smart_fhir_service as smart_svc
from app.auth import get_current_user, get_tenant_id, require_role
from app.cache import _get_redis

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/smart", tags=["smart_fhir"])

# ---------------------------------------------------------------------------
# Public (no /api prefix) router for the SMART 2.0 launch sequence.
# Mounted alongside the tenant-aware /api/smart router from router_registry.
# ---------------------------------------------------------------------------
public_router = APIRouter(prefix="/smart", tags=["smart_fhir"])


# ---------------------------------------------------------------------------
# PKCE + auth-code storage (Redis-backed, in-memory fallback for dev/tests)
# ---------------------------------------------------------------------------

_AUTHCODE_TTL_SEC = 300
_PKCE_KEY_PREFIX = "smart:authcode:"

# In-memory fallback used when Redis is unavailable.
_pkce_mem: dict[str, dict[str, Any]] = {}


def _pkce_store(code: str, payload: dict[str, Any]) -> None:
    """Persist auth-code → PKCE challenge metadata with a 5-minute TTL."""
    key = f"{_PKCE_KEY_PREFIX}{code}"
    r = _get_redis()
    if r:
        try:
            r.setex(key, _AUTHCODE_TTL_SEC, json.dumps(payload))
            return
        except Exception as exc:  # noqa: BLE001
            logger.warning("PKCE redis store failed: %s — using memory", exc)
    _pkce_mem[key] = payload


def _pkce_load(code: str) -> dict[str, Any] | None:
    key = f"{_PKCE_KEY_PREFIX}{code}"
    r = _get_redis()
    if r:
        try:
            raw = r.get(key)
            if raw:
                return json.loads(raw)
        except Exception as exc:  # noqa: BLE001
            logger.warning("PKCE redis load failed: %s — using memory", exc)
    return _pkce_mem.get(key)


def _pkce_delete(code: str) -> None:
    key = f"{_PKCE_KEY_PREFIX}{code}"
    r = _get_redis()
    if r:
        try:
            r.delete(key)
        except Exception:  # noqa: BLE001 — best-effort guard
            logger.debug("swallowed exception", exc_info=True)
    _pkce_mem.pop(key, None)


def _verify_pkce_s256(verifier: str, challenge: str) -> bool:
    """SHA-256(verifier) → base64url-no-pad; constant-time compare to challenge."""
    if not verifier or not challenge:
        return False
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    computed = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return secrets.compare_digest(computed, challenge)


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
    client_secret: str | None = Field(
        None,
        description="OAuth2 client_secret — omit for public clients. Stored encrypted.",
    )
    redirect_uri: str = Field(..., description="Registered OAuth2 redirect URI, e.g. https://app.example.com/api/smart/callback")
    scopes: str = Field(
        "launch patient/*.read openid fhirUser",
        description="Space-separated SMART/OAuth2 scopes",
    )
    launch_url: str | None = Field(
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

    name: str | None = Field(None, min_length=1, max_length=200)
    ehr_vendor: Literal["epic", "cerner", "athenahealth", "generic"] | None = None
    client_id: str | None = Field(None, min_length=1, max_length=255)
    client_secret: str | None = Field(None, description="New client_secret; stored encrypted.")
    redirect_uri: str | None = None
    scopes: str | None = None
    launch_url: str | None = None
    fhir_base_url: str | None = None
    token_endpoint: str | None = None
    authorize_endpoint: str | None = None
    status: Literal["active", "inactive"] | None = None


class RegistrationResponse(BaseModel):
    """Public view of a SMART app registration (no secrets)."""

    id: int
    name: str
    ehr_vendor: str
    client_id: str
    redirect_uri: str
    scopes: str
    launch_url: str | None
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
            "patient/Patient.read",
            "patient/Condition.read",
            "patient/Encounter.read",
            "patient/Observation.read",
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
    iss: str | None = Query(
        None,
        description="FHIR base URL supplied by the EHR on EHR-launch (the `iss` parameter)",
    ),
    launch: str | None = Query(
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
    error: str | None = Query(None, description="OAuth2 error code if authorization failed"),
    error_description: str | None = Query(None),
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
    session_status: str | None = Query(
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


# ===========================================================================
# Public SMART 2.0 launch sequence
# ---------------------------------------------------------------------------
# Mounted at /smart (no /api prefix).  Implements the *issuer-side* SMART 2.0
# contract so that this server can act as a SMART-compatible authorization
# endpoint for downstream tools (Epic CDS Hooks, third-party SMART clients).
# Spec: https://hl7.org/fhir/smart-app-launch/STU2.2/
# ===========================================================================


@public_router.get(
    "/.well-known/smart-configuration",
    summary="SMART 2.0 discovery document (issuer-side)",
)
def smart_configuration_well_known(request: Request) -> JSONResponse:
    """Advertise SMART 2.0 issuer capabilities at the canonical location.

    Conforms to SMART App Launch STU 2.2 (https://hl7.org/fhir/smart-app-launch/STU2.2/).
    Scopes include the Epic read-only connector set required for RAF Intelligence:
    patient/Patient.read, patient/Condition.read, patient/Encounter.read,
    patient/Observation.read.
    """
    base_url = str(request.base_url).rstrip("/")
    body = {
        "issuer": f"{base_url}/smart",
        "jwks_uri": f"{base_url}/api/auth/.well-known/jwks",
        "authorization_endpoint": f"{base_url}/smart/authorize",
        "token_endpoint": f"{base_url}/smart/token",
        "introspection_endpoint": f"{base_url}/api/auth/introspect",
        "revocation_endpoint": f"{base_url}/api/auth/revoke",
        "management_endpoint": f"{base_url}/api/smart/sessions",
        "registration_endpoint": f"{base_url}/api/smart/registrations",
        "token_endpoint_auth_methods_supported": [
            "client_secret_basic",
            "client_secret_post",
            "private_key_jwt",
            "none",
        ],
        "grant_types_supported": ["authorization_code", "client_credentials"],
        "response_types_supported": ["code"],
        "code_challenge_methods_supported": ["S256"],
        "scopes_supported": [
            "openid",
            "fhirUser",
            "launch",
            "launch/patient",
            "patient/Patient.read",
            "patient/Condition.read",
            "patient/Encounter.read",
            "patient/Observation.read",
            "patient/Condition.write",
        ],
        "capabilities": [
            "launch-ehr",
            "launch-standalone",
            "client-public",
            "client-confidential-symmetric",
            "sso-openid-connect",
            "context-banner",
            "context-style",
            "permission-patient",
        ],
    }
    return JSONResponse(content=body, media_type="application/json")


_LAUNCH_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>RAF Intelligence — SMART on FHIR Launch</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body {{ font-family: -apple-system, system-ui, sans-serif; background: #0f172a;
           color: #e2e8f0; display: flex; align-items: center; justify-content: center;
           min-height: 100vh; margin: 0; }}
    .card {{ background: #1e293b; border-radius: 12px; padding: 32px 40px; max-width: 480px;
             box-shadow: 0 10px 30px rgba(0,0,0,.4); text-align: center; }}
    h1 {{ margin-top: 0; font-size: 1.25rem; color: #38bdf8; }}
    code {{ background: #0f172a; padding: 2px 6px; border-radius: 4px; }}
    .spinner {{ border: 3px solid #334155; border-top-color: #38bdf8; border-radius: 50%;
                width: 28px; height: 28px; animation: spin 1s linear infinite; margin: 16px auto; }}
    @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
  </style>
</head>
<body>
  <div class="card">
    <h1>Launching RAF Intelligence in your EHR</h1>
    <div class="spinner" aria-hidden="true"></div>
    <p>Redirecting to <code id="iss"></code> for SMART authorization…</p>
    <noscript><p>JavaScript is required to complete the SMART launch.</p></noscript>
  </div>
  <script>
    (function () {{
      var iss = {iss_json};
      var launch = {launch_json};
      var clientId = {client_id_json};
      var redirectUri = {redirect_uri_json};
      var scope = {scope_json};
      document.getElementById('iss').textContent = iss || '(standalone)';
      function b64url(buf) {{
        return btoa(String.fromCharCode.apply(null, new Uint8Array(buf)))
          .replace(/\\+/g, '-').replace(/\\//g, '_').replace(/=+$/, '');
      }}
      var verifier = b64url(crypto.getRandomValues(new Uint8Array(32)));
      var state = b64url(crypto.getRandomValues(new Uint8Array(16)));
      sessionStorage.setItem('smart_code_verifier', verifier);
      sessionStorage.setItem('smart_state', state);
      sessionStorage.setItem('smart_iss', iss || '');
      crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier)).then(function (h) {{
        var challenge = b64url(h);
        var params = new URLSearchParams({{
          response_type: 'code',
          client_id: clientId,
          redirect_uri: redirectUri,
          scope: scope,
          state: state,
          aud: iss || '',
          code_challenge: challenge,
          code_challenge_method: 'S256'
        }});
        if (launch) params.set('launch', launch);
        var cfgUrl = (iss || '') + '/.well-known/smart-configuration';
        fetch(cfgUrl, {{ credentials: 'omit' }})
          .then(function (r) {{ return r.json(); }})
          .then(function (cfg) {{
            var authzEp = (cfg && cfg.authorization_endpoint) || ((iss || '') + '/authorize');
            window.location = authzEp + '?' + params.toString();
          }})
          .catch(function () {{
            window.location = '/smart/authorize?' + params.toString();
          }});
      }});
    }})();
  </script>
</body>
</html>
"""


@public_router.get(
    "/launch",
    summary="SMART on FHIR EHR-launch landing page",
    response_class=HTMLResponse,
)
def smart_launch_page(
    request: Request,
    iss: str | None = Query(None, description="FHIR base URL supplied by the EHR"),
    launch: str | None = Query(None, description="Opaque launch token from the EHR"),
) -> HTMLResponse:
    """Render the launch HTML.  The page generates a PKCE pair in the
    browser and redirects to the EHR's authorize endpoint (discovered via
    the iss's smart-configuration document)."""
    base = str(request.base_url).rstrip("/")
    client_id = os.environ.get("SMART_DEFAULT_CLIENT_ID", "raf-intelligence")
    redirect_uri = os.environ.get(
        "SMART_DEFAULT_REDIRECT_URI", f"{base}/smart/callback"
    )
    scope = os.environ.get(
        "SMART_DEFAULT_SCOPE",
        "openid fhirUser launch launch/patient patient/Patient.read "
        "patient/Condition.read patient/Encounter.read patient/Observation.read",
    )
    html = _LAUNCH_HTML.format(
        iss_json=json.dumps(iss or ""),
        launch_json=json.dumps(launch or ""),
        client_id_json=json.dumps(client_id),
        redirect_uri_json=json.dumps(redirect_uri),
        scope_json=json.dumps(scope),
    )
    return HTMLResponse(content=html)


@public_router.get(
    "/authorize",
    summary="SMART 2.0 authorization endpoint (PKCE)",
)
def smart_authorize(
    request: Request,
    response_type: str = Query("code"),
    client_id: str = Query(...),
    redirect_uri: str = Query(...),
    scope: str = Query(...),
    state: str = Query(...),
    aud: str | None = Query(None),
    launch: str | None = Query(None),
    code_challenge: str = Query(..., description="PKCE S256 challenge"),
    code_challenge_method: str = Query("S256"),
) -> RedirectResponse:
    """Issue an authorization code for the SMART client.

    The code_challenge is bound to the issued code with a 5 minute TTL.  On
    token exchange the client must present a code_verifier whose SHA-256
    digest matches.

    NOTE: this MVP auto-approves the request — full Epic App Orchard
    certification additionally requires an interactive login + consent
    screen, which is intentionally out of scope for this MVP.
    """
    if response_type != "code":
        raise HTTPException(status_code=400, detail="unsupported_response_type")
    if code_challenge_method != "S256":
        raise HTTPException(
            status_code=400,
            detail="unsupported code_challenge_method (only S256 supported)",
        )

    auth_code = secrets.token_urlsafe(32)
    _pkce_store(
        auth_code,
        {
            "code_challenge": code_challenge,
            "code_challenge_method": code_challenge_method,
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": scope,
            "aud": aud,
            "launch": launch,
        },
    )

    qs = urlencode({"code": auth_code, "state": state})
    return RedirectResponse(url=f"{redirect_uri}?{qs}", status_code=302)


@public_router.post(
    "/token",
    summary="SMART 2.0 token endpoint (authorization_code + client_credentials)",
)
async def smart_token(request: Request) -> dict[str, Any]:
    """Exchange a PKCE authorization code (or client_credentials) for an
    access token.  Verifies the code_verifier against the stored challenge."""
    body: dict[str, Any] = {}
    ctype = (request.headers.get("content-type") or "").lower()
    if "application/x-www-form-urlencoded" in ctype:
        form = await request.form()
        body = {k: v for k, v in form.items()}
    elif "application/json" in ctype:
        body = await request.json()
    else:
        try:
            body = await request.json()
        except Exception:
            logger.debug("swallowed exception", exc_info=True)
            try:
                form = await request.form()
                body = {k: v for k, v in form.items()}
            except Exception:
                logger.debug("swallowed exception", exc_info=True)
                body = {}

    grant_type = body.get("grant_type")
    if grant_type == "client_credentials":
        return {
            "access_token": secrets.token_urlsafe(32),
            "token_type": "Bearer",
            "expires_in": 3600,
            "scope": body.get("scope", ""),
        }

    if grant_type != "authorization_code":
        raise HTTPException(status_code=400, detail="unsupported_grant_type")

    code = body.get("code")
    code_verifier = body.get("code_verifier")
    if not code or not code_verifier:
        raise HTTPException(status_code=400, detail="invalid_request")

    stored = _pkce_load(code)
    if not stored:
        raise HTTPException(status_code=400, detail="invalid_grant (code expired or unknown)")

    if not _verify_pkce_s256(code_verifier, stored["code_challenge"]):
        raise HTTPException(status_code=400, detail="invalid_grant (PKCE verification failed)")

    _pkce_delete(code)

    return {
        "access_token": secrets.token_urlsafe(32),
        "token_type": "Bearer",
        "expires_in": 3600,
        "scope": stored.get("scope", ""),
        "patient": "synthetic-patient-1",
    }


@public_router.get(
    "/callback",
    summary="SMART 2.0 OAuth2 callback (issuer-side test landing)",
    response_class=HTMLResponse,
)
def smart_callback_public(
    code: str | None = Query(None),
    state: str | None = Query(None),
    error: str | None = Query(None),
) -> HTMLResponse:
    """Minimal callback landing — used for local end-to-end testing."""
    if error:
        return HTMLResponse(
            content=f"<h1>SMART error</h1><p>{error}</p>",
            status_code=400,
        )
    return HTMLResponse(
        content=(
            "<!doctype html><html><body>"
            "<h1>SMART callback</h1>"
            f"<p>code: <code>{code}</code></p>"
            f"<p>state: <code>{state}</code></p>"
            "<p>Exchange this code at <code>POST /smart/token</code> with the "
            "matching <code>code_verifier</code> (stored in sessionStorage on /smart/launch).</p>"
            "</body></html>"
        )
    )
