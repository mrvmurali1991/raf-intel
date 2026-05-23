"""
SMART on FHIR Service.

Implements the full SMART on FHIR (v1 + v2) app-launch lifecycle:

  EHR-launch flow:
    1. EHR calls /api/smart/launch?iss=<fhir_base>&launch=<token>
    2. App redirects the browser to the EHR's authorization endpoint
       (with PKCE code_challenge + state + launch parameter).
    3. EHR redirects back to /api/smart/callback?code=<auth_code>&state=<state>
    4. App exchanges the code for tokens and extracts launch context.

  Standalone-launch flow:
    Same as above but without the `launch` scope / token; the patient
    is selected by the user inside the EHR authorization dialog.

Both flows produce a smart_launch_sessions row that the rest of the
application can use to make authorized FHIR API calls on behalf of the
EHR context.

All token values are stored encrypted using the project-wide AES-256-GCM
encryption service.  PKCE uses S256 (SHA-256 code challenge method).
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import secrets
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

import httpx

from app.db import raf_cursor
from app.services.encryption_service import decrypt, encrypt

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = httpx.Timeout(30.0, connect=10.0)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _generate_pkce_pair() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) using S256 method."""
    verifier = secrets.token_urlsafe(64)  # 86-char URL-safe string
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def _generate_state() -> str:
    return secrets.token_urlsafe(32)


def _expires_at_from_seconds(expires_in: int | None) -> str | None:
    """Convert expires_in (seconds from now) to a UTC datetime string."""
    if not expires_in:
        return None
    ts = time.time() + int(expires_in)
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------------------
# Registration CRUD
# ---------------------------------------------------------------------------

def create_registration(data: dict[str, Any], tenant_id: str) -> dict[str, Any]:
    """Persist a new SMART app registration.  Returns the created row."""
    secret_plain = data.get("client_secret")
    secret_enc = encrypt(secret_plain) if secret_plain else None

    with raf_cursor() as cur:
        cur.execute(
            """
            INSERT INTO smart_app_registrations
              (name, ehr_vendor, client_id, client_secret_encrypted,
               redirect_uri, scopes, launch_url, fhir_base_url,
               token_endpoint, authorize_endpoint, status, tenant_id)
            VALUES
              (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                data["name"],
                data.get("ehr_vendor", "generic"),
                data["client_id"],
                secret_enc,
                data["redirect_uri"],
                data["scopes"],
                data.get("launch_url"),
                data["fhir_base_url"],
                data["token_endpoint"],
                data["authorize_endpoint"],
                data.get("status", "active"),
                tenant_id,
            ),
        )
        new_id = cur.lastrowid

    return get_registration(new_id, tenant_id)


def get_registration(registration_id: int, tenant_id: str) -> dict[str, Any] | None:
    with raf_cursor() as cur:
        cur.execute(
            "SELECT * FROM smart_app_registrations WHERE id = %s AND tenant_id = %s",
            (registration_id, tenant_id),
        )
        row = cur.fetchone()
    if not row:
        return None
    row.pop("client_secret_encrypted", None)
    return dict(row)


def list_registrations(tenant_id: str) -> list[dict[str, Any]]:
    with raf_cursor() as cur:
        cur.execute(
            "SELECT * FROM smart_app_registrations WHERE tenant_id = %s ORDER BY created_at DESC",
            (tenant_id,),
        )
        rows = cur.fetchall()
    result = []
    for row in rows:
        row.pop("client_secret_encrypted", None)
        result.append(dict(row))
    return result


def update_registration(
    registration_id: int, data: dict[str, Any], tenant_id: str
) -> dict[str, Any] | None:
    # Build dynamic SET clause for only supplied fields.
    allowed = {
        "name", "ehr_vendor", "client_id", "redirect_uri", "scopes",
        "launch_url", "fhir_base_url", "token_endpoint", "authorize_endpoint", "status",
    }
    updates: list[tuple[str, Any]] = []
    for field in allowed:
        if field in data:
            updates.append((field, data[field]))

    if "client_secret" in data and data["client_secret"]:
        updates.append(("client_secret_encrypted", encrypt(data["client_secret"])))

    if not updates:
        return get_registration(registration_id, tenant_id)

    set_clause = ", ".join(f"{col} = %s" for col, _ in updates)
    values = [v for _, v in updates] + [registration_id, tenant_id]

    with raf_cursor() as cur:
        cur.execute(
            f"UPDATE smart_app_registrations SET {set_clause} WHERE id = %s AND tenant_id = %s",
            values,
        )

    return get_registration(registration_id, tenant_id)


def delete_registration(registration_id: int, tenant_id: str) -> bool:
    with raf_cursor() as cur:
        cur.execute(
            "DELETE FROM smart_app_registrations WHERE id = %s AND tenant_id = %s",
            (registration_id, tenant_id),
        )
        return cur.rowcount > 0


# ---------------------------------------------------------------------------
# SMART discovery — fetch /.well-known/smart-configuration from FHIR server
# ---------------------------------------------------------------------------

def fetch_smart_configuration(fhir_base_url: str) -> dict[str, Any]:
    """
    Retrieve the SMART configuration document from the FHIR server.

    Tries the SMART v2 well-known URI first, then the FHIR conformance
    statement (CapabilityStatement) as a fallback.
    """
    base = fhir_base_url.rstrip("/")
    well_known_url = f"{base}/.well-known/smart-configuration"

    try:
        with httpx.Client(timeout=_DEFAULT_TIMEOUT) as client:
            resp = client.get(well_known_url, headers={"Accept": "application/json"})
            if resp.status_code == 200:
                return resp.json()
    except Exception as exc:
        logger.warning("SMART well-known fetch failed for %s: %s", base, exc)

    # Fallback: parse CapabilityStatement security extension
    try:
        with httpx.Client(timeout=_DEFAULT_TIMEOUT) as client:
            resp = client.get(
                f"{base}/metadata",
                headers={"Accept": "application/fhir+json"},
            )
            resp.raise_for_status()
            cs = resp.json()
            return _parse_capability_statement(cs)
    except Exception as exc:
        logger.error("CapabilityStatement fetch failed for %s: %s", base, exc)
        raise ValueError(f"Could not retrieve SMART configuration from {base}") from exc


def _parse_capability_statement(cs: dict[str, Any]) -> dict[str, Any]:
    """Extract authorization / token URLs from a FHIR CapabilityStatement."""
    auth_url = None
    token_url = None
    try:
        for rest in cs.get("rest", []):
            for ext in rest.get("security", {}).get("extension", []):
                if "oauth-uris" in ext.get("url", ""):
                    for sub in ext.get("extension", []):
                        if sub.get("url") == "authorize":
                            auth_url = sub.get("valueUri")
                        elif sub.get("url") == "token":
                            token_url = sub.get("valueUri")
    except Exception:  # noqa: BLE001 — best-effort guard
        logger.debug("swallowed exception", exc_info=True)
    return {
        "authorization_endpoint": auth_url,
        "token_endpoint": token_url,
        "capabilities": [],
    }


# ---------------------------------------------------------------------------
# Launch initiation — build authorization redirect URL
# ---------------------------------------------------------------------------

def initiate_launch(
    registration_id: int,
    tenant_id: str,
    launch_token: str | None = None,
    iss: str | None = None,
) -> dict[str, Any]:
    """
    Start an EHR-launch or standalone-launch flow.

    Returns a dict with:
      - redirect_url: the URL to which the user agent must be redirected
      - session_id:   the newly created smart_launch_sessions row id
      - state:        the CSRF state parameter (echoed for convenience)
    """
    reg = _load_registration_full(registration_id, tenant_id)
    if not reg:
        raise ValueError(f"SMART registration {registration_id} not found")
    if reg["status"] != "active":
        raise ValueError(f"SMART registration {registration_id} is inactive")

    code_verifier, code_challenge = _generate_pkce_pair()
    state = _generate_state()

    # Persist session before redirecting so we can match state on callback
    with raf_cursor() as cur:
        cur.execute(
            """
            INSERT INTO smart_launch_sessions
              (registration_id, launch_token, state_param, code_verifier, status, tenant_id)
            VALUES (%s, %s, %s, %s, 'initiated', %s)
            """,
            (registration_id, launch_token, state, code_verifier, tenant_id),
        )
        session_id = cur.lastrowid

    # Build the authorization URL
    scopes = reg["scopes"]
    if launch_token and "launch" not in scopes:
        scopes = f"launch {scopes}"

    params: dict[str, str] = {
        "response_type": "code",
        "client_id": reg["client_id"],
        "redirect_uri": reg["redirect_uri"],
        "scope": scopes,
        "state": state,
        "aud": iss or reg["fhir_base_url"],
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    if launch_token:
        params["launch"] = launch_token

    redirect_url = reg["authorize_endpoint"] + "?" + urlencode(params)

    logger.info(
        "SMART launch initiated: session_id=%s, registration_id=%s, tenant=%s, ehr_launch=%s",
        session_id, registration_id, tenant_id, bool(launch_token),
    )

    return {"redirect_url": redirect_url, "session_id": session_id, "state": state}


# ---------------------------------------------------------------------------
# OAuth2 callback — exchange auth code for tokens
# ---------------------------------------------------------------------------

def handle_callback(
    state: str,
    code: str,
    tenant_id: str,
) -> dict[str, Any]:
    """
    Process the OAuth2 authorization callback.

    1. Look up the session by state (CSRF check).
    2. Exchange the authorization code for access + refresh tokens.
    3. Extract launch context (patient, practitioner, encounter) from
       the token response or id_token claims.
    4. Persist encrypted tokens to the session row.
    5. Return the sanitized session context.

    Raises ValueError on any error (state mismatch, token exchange failure).
    """
    session = _load_session_by_state(state, tenant_id)
    if not session:
        raise ValueError("Invalid or expired SMART state parameter")
    if session["status"] != "initiated":
        raise ValueError(f"SMART session already in state '{session['status']}'")

    reg = _load_registration_full(session["registration_id"], tenant_id)
    if not reg:
        raise ValueError("Associated SMART registration not found")

    # Retrieve and use the PKCE code_verifier stored in the session
    code_verifier = session["code_verifier"]

    token_data = _exchange_code(
        token_endpoint=reg["token_endpoint"],
        client_id=reg["client_id"],
        client_secret=reg.get("_client_secret_plain"),
        redirect_uri=reg["redirect_uri"],
        code=code,
        code_verifier=code_verifier,
    )

    access_token = token_data.get("access_token")
    if not access_token:
        _mark_session_error(session["id"], "Token exchange returned no access_token")
        raise ValueError("Token exchange failed: no access_token returned")

    refresh_token = token_data.get("refresh_token")
    expires_in = token_data.get("expires_in")
    expires_at = _expires_at_from_seconds(expires_in)

    # Extract SMART context
    patient_id = token_data.get("patient")
    practitioner_id = token_data.get("practitioner") or token_data.get("fhirUser", "").split("/")[-1] or None
    encounter_id = token_data.get("encounter")

    # Try to extract from id_token if context fields are missing.
    # SECURITY NOTE: _decode_id_token_claims() decodes WITHOUT signature
    # verification.  The values below are used only for SMART launch-context
    # display (patient/practitioner/encounter IDs shown in the UI).  They do
    # NOT grant any access rights — authorization is enforced via the
    # access_token checked against the FHIR server on every resource request.
    if not patient_id:
        id_token = token_data.get("id_token")
        if id_token:
            claims = _decode_id_token_claims(id_token)
            patient_id = patient_id or claims.get("patient")
            practitioner_id = practitioner_id or claims.get("fhirUser", "").split("/")[-1] or None
            encounter_id = encounter_id or claims.get("encounter")

    with raf_cursor() as cur:
        cur.execute(
            """
            UPDATE smart_launch_sessions SET
              access_token_encrypted  = %s,
              refresh_token_encrypted = %s,
              patient_fhir_id         = %s,
              practitioner_fhir_id    = %s,
              encounter_fhir_id       = %s,
              token_expires_at        = %s,
              status                  = 'active',
              updated_at              = %s
            WHERE id = %s
            """,
            (
                encrypt(access_token),
                encrypt(refresh_token) if refresh_token else None,
                patient_id,
                practitioner_id or None,
                encounter_id,
                expires_at,
                _now_utc(),
                session["id"],
            ),
        )

    logger.info(
        "SMART callback success: session_id=%s, patient=%s, encounter=%s",
        session["id"], patient_id, encounter_id,
    )

    return {
        "session_id": session["id"],
        "patient_fhir_id": patient_id,
        "practitioner_fhir_id": practitioner_id,
        "encounter_fhir_id": encounter_id,
        "token_expires_at": expires_at,
        "status": "active",
    }


def _exchange_code(
    token_endpoint: str,
    client_id: str,
    client_secret: str | None,
    redirect_uri: str,
    code: str,
    code_verifier: str,
) -> dict[str, Any]:
    """POST to the token endpoint and return the parsed JSON response."""
    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "code_verifier": code_verifier,
    }

    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    auth = None
    if client_secret:
        # Confidential client: use HTTP Basic auth
        auth = (client_id, client_secret)
        payload.pop("client_id", None)  # not needed in body when using Basic auth

    try:
        with httpx.Client(timeout=_DEFAULT_TIMEOUT) as client:
            resp = client.post(token_endpoint, data=payload, headers=headers, auth=auth)
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPStatusError as exc:
        body = exc.response.text[:500]
        raise ValueError(f"Token exchange HTTP {exc.response.status_code}: {body}") from exc
    except Exception as exc:
        raise ValueError(f"Token exchange request failed: {exc}") from exc


def _decode_id_token_claims(id_token: str) -> dict[str, Any]:
    """Extract claims from a JWT id_token WITHOUT signature verification.

    WARNING: These claims are NOT cryptographically verified and MUST NOT be
    used for authorization decisions.  Use only for display/logging purposes
    (e.g. pre-populating SMART launch context fields for UI convenience).
    For authorization, rely exclusively on the access_token validated against
    the FHIR authorization server.
    """
    try:
        parts = id_token.split(".")
        if len(parts) < 2:
            return {}
        # Add padding for base64 decoding
        padded = parts[1] + "=" * (-len(parts[1]) % 4)
        return json.loads(base64.urlsafe_b64decode(padded))
    except Exception:  # noqa: BLE001 — best-effort guard
        logger.debug("swallowed exception", exc_info=True)
        return {}


# ---------------------------------------------------------------------------
# Context retrieval
# ---------------------------------------------------------------------------

def get_launch_context(session_id: int, tenant_id: str) -> dict[str, Any]:
    """Return the SMART context (patient, practitioner, encounter) for a session."""
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT s.id, s.patient_fhir_id, s.practitioner_fhir_id,
                   s.encounter_fhir_id, s.token_expires_at, s.status,
                   s.registration_id, r.fhir_base_url, r.ehr_vendor
            FROM smart_launch_sessions s
            JOIN smart_app_registrations r ON r.id = s.registration_id
            WHERE s.id = %s AND s.tenant_id = %s
            """,
            (session_id, tenant_id),
        )
        row = cur.fetchone()
    if not row:
        raise ValueError(f"SMART session {session_id} not found")

    _check_session_active(row)
    return {
        "session_id": row["id"],
        "patient_fhir_id": row["patient_fhir_id"],
        "practitioner_fhir_id": row["practitioner_fhir_id"],
        "encounter_fhir_id": row["encounter_fhir_id"],
        "token_expires_at": str(row["token_expires_at"]) if row["token_expires_at"] else None,
        "status": row["status"],
        "fhir_base_url": row["fhir_base_url"],
        "ehr_vendor": row["ehr_vendor"],
    }


# ---------------------------------------------------------------------------
# FHIR resource fetching with SMART access token
# ---------------------------------------------------------------------------

def get_patient_data(session_id: int, tenant_id: str) -> dict[str, Any]:
    """
    Fetch the FHIR Patient resource for the patient in this session.

    Uses the session's access token (auto-refreshing if expired).
    Caches the result in smart_context_cache.
    Returns the raw FHIR Patient JSON plus a mapped internal patient_id
    if one can be found in the local database.
    """
    ctx = get_launch_context(session_id, tenant_id)
    patient_fhir_id = ctx.get("patient_fhir_id")
    if not patient_fhir_id:
        raise ValueError("No patient in SMART context for this session")

    # Check cache first
    cached = _get_cached_resource(session_id, "Patient", patient_fhir_id)
    if cached:
        resource = cached
    else:
        access_token = _get_access_token(session_id, tenant_id)
        fhir_base = ctx["fhir_base_url"].rstrip("/")
        resource = _fetch_fhir_resource(
            fhir_base, f"Patient/{patient_fhir_id}", access_token
        )
        _cache_resource(session_id, "Patient", patient_fhir_id, resource)

    internal_id = _map_fhir_patient_to_internal(resource)
    return {"fhir_patient": resource, "internal_patient_id": internal_id}


def _fetch_fhir_resource(
    fhir_base: str, path: str, access_token: str
) -> dict[str, Any]:
    url = f"{fhir_base}/{path.lstrip('/')}"
    try:
        with httpx.Client(timeout=_DEFAULT_TIMEOUT) as client:
            resp = client.get(
                url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/fhir+json",
                },
            )
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPStatusError as exc:
        raise ValueError(
            f"FHIR fetch {url} returned HTTP {exc.response.status_code}"
        ) from exc
    except Exception as exc:
        raise ValueError(f"FHIR fetch {url} failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Token refresh
# ---------------------------------------------------------------------------

def refresh_session_token(session_id: int, tenant_id: str) -> dict[str, Any]:
    """
    Use the stored refresh token to obtain a new access token.
    Updates the session row and returns the new expiry.
    """
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT s.*, r.token_endpoint, r.client_id, r.client_secret_encrypted,
                   r.redirect_uri
            FROM smart_launch_sessions s
            JOIN smart_app_registrations r ON r.id = s.registration_id
            WHERE s.id = %s AND s.tenant_id = %s
            """,
            (session_id, tenant_id),
        )
        row = cur.fetchone()
    if not row:
        raise ValueError(f"SMART session {session_id} not found")

    refresh_token_enc = row.get("refresh_token_encrypted")
    if not refresh_token_enc:
        raise ValueError("Session has no refresh token")

    refresh_token = decrypt(refresh_token_enc)
    client_secret = None
    if row.get("client_secret_encrypted"):
        client_secret = decrypt(row["client_secret_encrypted"])

    payload = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": row["client_id"],
    }
    auth = None
    if client_secret:
        auth = (row["client_id"], client_secret)
        payload.pop("client_id", None)

    try:
        with httpx.Client(timeout=_DEFAULT_TIMEOUT) as client:
            resp = client.post(
                row["token_endpoint"],
                data=payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                auth=auth,
            )
            resp.raise_for_status()
            token_data = resp.json()
    except Exception as exc:
        _mark_session_error(session_id, f"Token refresh failed: {exc}")
        raise ValueError(f"Token refresh failed: {exc}") from exc

    new_access = token_data.get("access_token")
    new_refresh = token_data.get("refresh_token", refresh_token)
    expires_in = token_data.get("expires_in")
    expires_at = _expires_at_from_seconds(expires_in)

    with raf_cursor() as cur:
        cur.execute(
            """
            UPDATE smart_launch_sessions
            SET access_token_encrypted = %s,
                refresh_token_encrypted = %s,
                token_expires_at = %s,
                status = 'active',
                updated_at = %s
            WHERE id = %s
            """,
            (
                encrypt(new_access),
                encrypt(new_refresh),
                expires_at,
                _now_utc(),
                session_id,
            ),
        )

    return {"session_id": session_id, "token_expires_at": expires_at, "status": "active"}


# ---------------------------------------------------------------------------
# Session listing
# ---------------------------------------------------------------------------

def list_sessions(tenant_id: str, status: str | None = None) -> list[dict[str, Any]]:
    with raf_cursor() as cur:
        if status:
            cur.execute(
                """
                SELECT s.id, s.registration_id, r.name AS registration_name,
                       s.patient_fhir_id, s.practitioner_fhir_id,
                       s.encounter_fhir_id, s.token_expires_at, s.status,
                       s.created_at, s.updated_at
                FROM smart_launch_sessions s
                JOIN smart_app_registrations r ON r.id = s.registration_id
                WHERE s.tenant_id = %s AND s.status = %s
                ORDER BY s.created_at DESC
                LIMIT 200
                """,
                (tenant_id, status),
            )
        else:
            cur.execute(
                """
                SELECT s.id, s.registration_id, r.name AS registration_name,
                       s.patient_fhir_id, s.practitioner_fhir_id,
                       s.encounter_fhir_id, s.token_expires_at, s.status,
                       s.created_at, s.updated_at
                FROM smart_launch_sessions s
                JOIN smart_app_registrations r ON r.id = s.registration_id
                WHERE s.tenant_id = %s
                ORDER BY s.created_at DESC
                LIMIT 200
                """,
                (tenant_id,),
            )
        rows = cur.fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_registration_full(registration_id: int, tenant_id: str) -> dict[str, Any] | None:
    """Load a registration row including the decrypted client secret."""
    with raf_cursor() as cur:
        cur.execute(
            "SELECT * FROM smart_app_registrations WHERE id = %s AND tenant_id = %s",
            (registration_id, tenant_id),
        )
        row = cur.fetchone()
    if not row:
        return None
    row = dict(row)
    if row.get("client_secret_encrypted"):
        try:
            row["_client_secret_plain"] = decrypt(row["client_secret_encrypted"])
        except Exception:
            logger.debug("swallowed exception", exc_info=True)
            row["_client_secret_plain"] = None
    row.pop("client_secret_encrypted", None)
    return row


def _load_session_by_state(state: str, tenant_id: str) -> dict[str, Any] | None:
    with raf_cursor() as cur:
        cur.execute(
            "SELECT * FROM smart_launch_sessions WHERE state_param = %s AND tenant_id = %s",
            (state, tenant_id),
        )
        row = cur.fetchone()
    return dict(row) if row else None


def _get_access_token(session_id: int, tenant_id: str) -> str:
    """Return a valid access token, refreshing if needed."""
    with raf_cursor() as cur:
        cur.execute(
            "SELECT access_token_encrypted, token_expires_at FROM smart_launch_sessions "
            "WHERE id = %s AND tenant_id = %s",
            (session_id, tenant_id),
        )
        row = cur.fetchone()
    if not row or not row["access_token_encrypted"]:
        raise ValueError("No access token in session")

    # Refresh if token expires within the next 60 seconds
    expires_at = row["token_expires_at"]
    if expires_at:
        expires_ts = expires_at.timestamp() if hasattr(expires_at, "timestamp") else 0
        if time.time() >= expires_ts - 60:
            refresh_session_token(session_id, tenant_id)
            # Re-fetch after refresh
            with raf_cursor() as cur:
                cur.execute(
                    "SELECT access_token_encrypted FROM smart_launch_sessions WHERE id = %s",
                    (session_id,),
                )
                row = cur.fetchone()

    return decrypt(row["access_token_encrypted"])


def _get_cached_resource(
    session_id: int, resource_type: str, resource_id: str
) -> dict[str, Any] | None:
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT resource_data FROM smart_context_cache
            WHERE session_id = %s AND resource_type = %s AND resource_id = %s
            """,
            (session_id, resource_type, resource_id),
        )
        row = cur.fetchone()
    if not row:
        return None
    data = row["resource_data"]
    return json.loads(data) if isinstance(data, str) else data


def _cache_resource(
    session_id: int, resource_type: str, resource_id: str, data: dict[str, Any]
) -> None:
    serialized = json.dumps(data)
    with raf_cursor() as cur:
        cur.execute(
            """
            INSERT INTO smart_context_cache (session_id, resource_type, resource_id, resource_data)
            VALUES (%s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE resource_data = VALUES(resource_data), fetched_at = NOW()
            """,
            (session_id, resource_type, resource_id, serialized),
        )


def _map_fhir_patient_to_internal(fhir_patient: dict[str, Any]) -> int | None:
    """
    Try to resolve a FHIR Patient resource to a local OpenEMR patient_id.

    Matching strategy (in order of preference):
      1. MRN identifier (system contains 'mrn' or 'medical-record')
      2. First name + last name + date of birth
    """
    # Strategy 1 — MRN identifier
    for ident in fhir_patient.get("identifier", []):
        system = (ident.get("system") or "").lower()
        if "mrn" in system or "medical-record" in system:
            mrn = ident.get("value", "").strip()
            if mrn:
                pid = _lookup_patient_by_mrn(mrn)
                if pid:
                    return pid

    # Strategy 2 — name + DOB
    dob = fhir_patient.get("birthDate")
    names = fhir_patient.get("name", [])
    if names and dob:
        name = names[0]
        given = (name.get("given") or [""])[0]
        family = name.get("family", "")
        if given and family and dob:
            pid = _lookup_patient_by_name_dob(given, family, dob)
            if pid:
                return pid

    return None


def _lookup_patient_by_mrn(mrn: str) -> int | None:
    try:
        from app.db import openemr_cursor
        with openemr_cursor() as cur:
            cur.execute(
                "SELECT pid FROM patient_data WHERE pubpid = %s LIMIT 1",
                (mrn,),
            )
            row = cur.fetchone()
        return int(row["pid"]) if row else None
    except Exception as exc:
        logger.warning("MRN patient lookup failed: %s", exc)
        return None


def _lookup_patient_by_name_dob(fname: str, lname: str, dob: str) -> int | None:
    try:
        from app.db import openemr_cursor
        with openemr_cursor() as cur:
            cur.execute(
                "SELECT pid FROM patient_data WHERE fname = %s AND lname = %s AND DOB = %s LIMIT 1",
                (fname, lname, dob),
            )
            row = cur.fetchone()
        return int(row["pid"]) if row else None
    except Exception as exc:
        logger.warning("Name+DOB patient lookup failed: %s", exc)
        return None


def _check_session_active(row: dict[str, Any]) -> None:
    if row["status"] in ("expired", "error"):
        raise ValueError(f"SMART session is {row['status']}")
    if row["status"] == "initiated":
        raise ValueError("SMART session is still in progress (authorization not complete)")
    # Check wall-clock expiry
    expires_at = row.get("token_expires_at")
    if expires_at:
        ts = expires_at.timestamp() if hasattr(expires_at, "timestamp") else 0
        if time.time() >= ts:
            raise ValueError("SMART session access token has expired")


def _mark_session_error(session_id: int, message: str) -> None:
    try:
        with raf_cursor() as cur:
            cur.execute(
                "UPDATE smart_launch_sessions SET status = 'error', error_message = %s, "
                "updated_at = %s WHERE id = %s",
                (message[:1000], _now_utc(), session_id),
            )
    except Exception as exc:
        logger.error("Failed to mark session %s as error: %s", session_id, exc)
