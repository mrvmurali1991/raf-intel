"""
FHIR R4 Integration Service.

Supports connecting to Epic, Cerner, Athenahealth, and generic FHIR R4 servers.
Handles OAuth2 client_credentials token management, resource fetching, parsing,
patient matching, bulk export, incremental sync, and persistence to fhir_* tables.

All HTTP calls use httpx in async mode.  Sync wrappers are provided where the
router needs to run inside a regular (non-async) FastAPI path function, matching
the synchronous style of the rest of this codebase.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx

from app.db import raf_cursor, openemr_cursor
from app.services.encryption_service import decrypt, encrypt
from app.services.circuit_breaker import fhir_breaker

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ICD10_CM_SYSTEM = "http://hl7.org/fhir/sid/icd-10-cm"
SNOMED_SYSTEM = "http://snomed.info/sct"

_DEFAULT_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
_BULK_POLL_INTERVAL = 5  # seconds between polling bulk export status
_BULK_MAX_POLLS = 120    # give up after ~10 minutes


# ---------------------------------------------------------------------------
# Token cache – keyed by connection_id
# ---------------------------------------------------------------------------

_token_cache: dict[int, dict[str, Any]] = {}


def _token_expired(cache_entry: dict[str, Any]) -> bool:
    """Return True when the cached token has less than 60 s of lifetime left."""
    return time.time() >= cache_entry.get("expires_at", 0) - 60


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _extract_coding(codings: list[dict], system: str) -> list[str]:
    """Pull all codes from a coding array that match *system*."""
    return [
        c["code"]
        for c in codings
        if c.get("system", "").rstrip("/") == system.rstrip("/") and c.get("code")
    ]


def _safe_str(val: Any, max_len: int = 500) -> str:
    if val is None:
        return ""
    return str(val)[:max_len]


def _safe_date(val: Any) -> str | None:
    """Sanitize a FHIR date/dateTime to YYYY-MM-DD or None."""
    if not val:
        return None
    s = str(val)[:10]  # take just YYYY-MM-DD
    if s.startswith("-") or s < "0001":
        return None
    return s if len(s) >= 10 else None


# ---------------------------------------------------------------------------
# OAuth2 token acquisition
# ---------------------------------------------------------------------------

async def _fetch_token_async(connection: dict[str, Any]) -> str:
    """
    Fetch an OAuth2 access token and cache it.
    Supports client_credentials (default) and password grant (OpenEMR).
    """
    conn_id: int = connection["id"]
    token_url: str = connection.get("token_url", "") or ""
    client_id: str = connection.get("client_id", "") or ""
    client_secret: str = connection.get("client_secret", "") or ""
    scope: str = connection.get("scope", "system/*.read") or "system/*.read"
    vendor: str = (connection.get("vendor") or "").lower()

    if not token_url:
        raise ValueError(f"Connection {conn_id} has no token_url configured")

    # OpenEMR uses password grant with client_secret_post auth method
    if vendor == "openemr":
        # Check extra_config JSON for oauth creds (set via UI or DB)
        _extra = connection.get("extra_config") or {}
        if isinstance(_extra, str):
            import json as _json
            try:
                _extra = _json.loads(_extra)
            except Exception:
                _extra = {}
        oauth_username: str = (
            connection.get("oauth_username", "")
            or _extra.get("oauth_username", "")
            or os.environ.get("OPENEMR_USERNAME", "admin")
        )
        oauth_password: str = (
            connection.get("oauth_password", "")
            or _extra.get("oauth_password", "")
            or os.environ.get("OPENEMR_PASSWORD", "")
        )
        post_data = {
            "grant_type": "password",
            "client_id": client_id,
            "client_secret": client_secret,
            "username": oauth_username,
            "password": oauth_password,
            "scope": scope,
            "user_role": "users",
        }
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "RAF-Intelligence/1.0",
        }
    else:
        credentials = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        post_data = {"grant_type": "client_credentials", "scope": scope}
        headers = {
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/x-www-form-urlencoded",
        }

    async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
        resp = await client.post(token_url, headers=headers, data=post_data)
        resp.raise_for_status()
        data = resp.json()

    access_token = data.get("access_token")
    if not access_token:
        raise ValueError(f"OAuth2 response missing access_token from {token_url}")
    expires_in: int = int(data.get("expires_in", 3600))

    _token_cache[conn_id] = {
        "access_token": access_token,
        "expires_at": time.time() + expires_in,
    }
    logger.info("OAuth2 token refreshed for connection %s (expires_in=%s)", conn_id, expires_in)
    return access_token


async def _get_token_async(connection: dict[str, Any]) -> str:
    """Return a valid cached token or fetch a new one."""
    conn_id: int = connection["id"]
    auth_type: str = (connection.get("auth_type") or "none").lower()

    if auth_type not in ("oauth2", "smart_on_fhir"):
        # Check if there's a stored access_token as fallback
        stored = connection.get("access_token")
        if stored:
            return stored
        return ""  # no auth or API-key handled via headers elsewhere

    cached = _token_cache.get(conn_id)
    if cached and not _token_expired(cached):
        return cached["access_token"]

    return await _fetch_token_async(connection)


# ---------------------------------------------------------------------------
# Low-level FHIR HTTP client
# ---------------------------------------------------------------------------

async def _fhir_get(
    connection: dict[str, Any],
    path: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    GET {base_url}/{path} with optional query params.
    Automatically attaches Authorization header when auth_type is oauth2 or api_key.
    """
    base_url: str = connection["base_url"].rstrip("/")
    url = f"{base_url}/{path.lstrip('/')}"

    headers: dict[str, str] = {
        "Accept": "application/fhir+json",
        "Content-Type": "application/fhir+json",
    }

    auth_type: str = (connection.get("auth_type") or "none").lower()
    if auth_type == "oauth2":
        token = await _get_token_async(connection)
        headers["Authorization"] = f"Bearer {token}"
    elif auth_type == "api_key":
        api_key: str = connection.get("api_key", "") or ""
        headers["Authorization"] = f"Bearer {api_key}"

    async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
        resp = await client.get(url, headers=headers, params=params or {})

    if resp.status_code == 404:
        raise ValueError(f"FHIR resource not found: {url}")
    if resp.status_code == 401:
        # Invalidate token cache and raise so caller can decide to retry
        _token_cache.pop(connection.get("id"), None)
        raise PermissionError(f"FHIR 401 Unauthorized: {url}")

    resp.raise_for_status()
    return resp.json()


async def _fhir_get_all_pages(
    connection: dict[str, Any],
    resource_type: str,
    params: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """
    Fetch all pages of a FHIR Bundle search result and return the list of
    resource entries (not the Bundle wrappers).
    """
    MAX_PAGES = 100

    base_url: str = connection["base_url"].rstrip("/")
    path = f"{resource_type}"
    bundle = await _fhir_get(connection, path, params=params)
    entries: list[dict[str, Any]] = []
    page_count = 0

    while True:
        page_count += 1
        if page_count > MAX_PAGES:
            logger.warning(
                "_fhir_get_all_pages: exceeded MAX_PAGES (%d) for %s — truncating results",
                MAX_PAGES,
                resource_type,
            )
            break
        for entry in bundle.get("entry", []):
            resource = entry.get("resource")
            if resource:
                entries.append(resource)

        # Follow next page if present
        next_url: str | None = None
        for link in bundle.get("link", []):
            if link.get("relation") == "next":
                next_url = link.get("url")
                break

        if not next_url:
            break

        # Fetch next page directly with the full URL
        auth_type: str = (connection.get("auth_type") or "none").lower()
        headers: dict[str, str] = {
            "Accept": "application/fhir+json",
            "Content-Type": "application/fhir+json",
        }
        if auth_type == "oauth2":
            token = await _get_token_async(connection)
            headers["Authorization"] = f"Bearer {token}"
        elif auth_type == "api_key":
            headers["Authorization"] = f"Bearer {connection.get('api_key', '')}"

        async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
            resp = await client.get(next_url, headers=headers)
        resp.raise_for_status()
        bundle = resp.json()

    return entries


# ---------------------------------------------------------------------------
# FHIR resource parsers
# ---------------------------------------------------------------------------

def parse_condition(resource: dict[str, Any]) -> dict[str, Any]:
    """
    Extract structured data from a FHIR R4 Condition resource.

    Returns a flat dict suitable for insertion into fhir_conditions.
    """
    fhir_id: str = resource.get("id", "")

    # ICD-10 codes from primary coding
    icd10_codes: list[str] = []
    primary_code = resource.get("code", {})
    codings: list[dict] = primary_code.get("coding", [])
    icd10_codes = _extract_coding(codings, ICD10_CM_SYSTEM)

    # Fallback: also check SNOMED for display text
    display = ""
    for c in codings:
        if c.get("display"):
            display = c["display"]
            break
    if not display:
        display = primary_code.get("text", "")

    # Clinical status
    clinical_status = ""
    cs = resource.get("clinicalStatus", {})
    for c in cs.get("coding", []):
        if c.get("code"):
            clinical_status = c["code"]
            break

    # Verification status
    verification_status = ""
    vs = resource.get("verificationStatus", {})
    for c in vs.get("coding", []):
        if c.get("code"):
            verification_status = c["code"]
            break

    # Subject (patient reference)
    subject_ref: str = resource.get("subject", {}).get("reference", "")
    fhir_patient_id = subject_ref.split("/")[-1] if "/" in subject_ref else subject_ref

    # Onset
    onset = (
        resource.get("onsetDateTime")
        or resource.get("onsetPeriod", {}).get("start")
        or ""
    )

    # Recorded date
    recorded_date = resource.get("recordedDate", "")

    # Encounter reference
    encounter_ref: str = resource.get("encounter", {}).get("reference", "")
    fhir_encounter_id = encounter_ref.split("/")[-1] if "/" in encounter_ref else ""

    return {
        "fhir_resource_id": fhir_id,
        "fhir_patient_id": fhir_patient_id,
        "fhir_encounter_id": fhir_encounter_id,
        "icd10_codes": json.dumps(icd10_codes),
        "icd10_codes_list": icd10_codes,  # convenience — not stored directly
        "display": _safe_str(display),
        "clinical_status": clinical_status,
        "verification_status": verification_status,
        "onset_date": _safe_date(onset),
        "recorded_date": _safe_date(recorded_date),
        "raw_json": json.dumps(resource),
    }


def parse_encounter(resource: dict[str, Any]) -> dict[str, Any]:
    """
    Extract structured data from a FHIR R4 Encounter resource.
    """
    fhir_id: str = resource.get("id", "")

    # Subject
    subject_ref: str = resource.get("subject", {}).get("reference", "")
    fhir_patient_id = subject_ref.split("/")[-1] if "/" in subject_ref else subject_ref

    # Class (inpatient, outpatient, etc.)
    encounter_class = resource.get("class", {}).get("code", "")
    encounter_class_display = resource.get("class", {}).get("display", "")

    # Status
    status = resource.get("status", "")

    # Type
    type_display = ""
    for t in resource.get("type", []):
        for c in t.get("coding", []):
            if c.get("display"):
                type_display = c["display"]
                break
        if not type_display:
            type_display = t.get("text", "")
        if type_display:
            break

    # Period
    period = resource.get("period", {})
    period_start = period.get("start", "")
    period_end = period.get("end", "")

    # Primary provider / participant
    provider_name = ""
    provider_ref = ""
    for participant in resource.get("participant", []):
        individual = participant.get("individual", {})
        ref = individual.get("reference", "")
        display = individual.get("display", "")
        # Prefer the attending (type coding "ATND")
        p_types = [
            c.get("code", "")
            for t in participant.get("type", [])
            for c in t.get("coding", [])
        ]
        if "ATND" in p_types or not provider_ref:
            provider_ref = ref
            provider_name = display

    # Reason codes
    reason_codes: list[str] = []
    for rc in resource.get("reasonCode", []):
        reason_codes.extend(_extract_coding(rc.get("coding", []), ICD10_CM_SYSTEM))

    # Service provider
    service_provider = resource.get("serviceProvider", {}).get("display", "")

    return {
        "fhir_resource_id": fhir_id,
        "fhir_patient_id": fhir_patient_id,
        "encounter_class": _safe_str(encounter_class, 50),
        "encounter_class_display": _safe_str(encounter_class_display, 100),
        "status": status,
        "type_display": _safe_str(type_display, 200),
        "period_start": _safe_str(period_start, 30) or None,
        "period_end": _safe_str(period_end, 30) or None,
        "provider_name": _safe_str(provider_name, 200),
        "provider_ref": _safe_str(provider_ref, 200),
        "reason_codes": json.dumps(reason_codes),
        "service_provider": _safe_str(service_provider, 200),
        "raw_json": json.dumps(resource),
    }


def parse_medication_request(resource: dict[str, Any]) -> dict[str, Any]:
    """
    Extract structured data from a FHIR R4 MedicationRequest resource.

    Returns a flat dict suitable for insertion into fhir_medications.
    """
    fhir_id: str = resource.get("id", "")

    # Subject (patient reference)
    subject_ref: str = resource.get("subject", {}).get("reference", "")
    fhir_patient_id = subject_ref.split("/")[-1] if "/" in subject_ref else subject_ref

    # Medication code — prefer medicationCodeableConcept, fall back to medicationReference
    medication_code = ""
    medication_display = ""
    med_cc = resource.get("medicationCodeableConcept", {})
    if med_cc:
        codings = med_cc.get("coding", [])
        if codings:
            medication_code = codings[0].get("code", "")
            medication_display = codings[0].get("display", "")
        if not medication_display:
            medication_display = med_cc.get("text", "")
    else:
        med_ref = resource.get("medicationReference", {})
        medication_display = med_ref.get("display", "")
        medication_code = med_ref.get("reference", "").split("/")[-1]

    # Status and intent
    status = resource.get("status", "")
    intent = resource.get("intent", "")

    # Authored date
    authored_on = resource.get("authoredOn", "")

    # Dosage instruction text (first entry only)
    dosage_text = ""
    dosage_instructions = resource.get("dosageInstruction", [])
    if dosage_instructions:
        dosage_text = dosage_instructions[0].get("text", "")

    return {
        "fhir_resource_id": fhir_id,
        "fhir_patient_id": fhir_patient_id,
        "medication_code": _safe_str(medication_code, 50),
        "medication_display": _safe_str(medication_display, 500),
        "status": _safe_str(status, 50),
        "intent": _safe_str(intent, 50),
        "authored_on": _safe_date(authored_on),
        "dosage_text": _safe_str(dosage_text, 1000),
        "raw_json": json.dumps(resource),
    }


def parse_observation(resource: dict[str, Any]) -> dict[str, Any]:
    """
    Extract structured data from a FHIR R4 Observation resource.

    Returns a flat dict suitable for insertion into fhir_observations.
    """
    fhir_id: str = resource.get("id", "")

    # Subject (patient reference)
    subject_ref: str = resource.get("subject", {}).get("reference", "")
    fhir_patient_id = subject_ref.split("/")[-1] if "/" in subject_ref else subject_ref

    # Category (e.g. "vital-signs", "laboratory")
    category = ""
    categories = resource.get("category", [])
    if categories:
        cat_codings = categories[0].get("coding", [])
        if cat_codings:
            category = cat_codings[0].get("code", "")

    # LOINC code and display
    code = ""
    code_display = ""
    code_obj = resource.get("code", {})
    code_codings = code_obj.get("coding", [])
    if code_codings:
        code = code_codings[0].get("code", "")
        code_display = code_codings[0].get("display", "")
    if not code_display:
        code_display = code_obj.get("text", "")

    # Value — numeric, string, or codeable concept text
    value_numeric: float | None = None
    value_string: str = ""
    unit: str = ""
    vq = resource.get("valueQuantity", {})
    if vq:
        raw_val = vq.get("value")
        try:
            value_numeric = float(raw_val) if raw_val is not None else None
        except (TypeError, ValueError):
            value_numeric = None
        unit = vq.get("unit", "")
    elif resource.get("valueString"):
        value_string = resource["valueString"]
    elif resource.get("valueCodeableConcept"):
        vcc = resource["valueCodeableConcept"]
        vcc_codings = vcc.get("coding", [])
        value_string = vcc_codings[0].get("display", "") if vcc_codings else vcc.get("text", "")

    # Effective date
    effective_date = (
        resource.get("effectiveDateTime")
        or resource.get("effectivePeriod", {}).get("start")
        or ""
    )

    # Status
    status = resource.get("status", "")

    return {
        "fhir_resource_id": fhir_id,
        "fhir_patient_id": fhir_patient_id,
        "category": _safe_str(category, 50),
        "code": _safe_str(code, 50),
        "code_display": _safe_str(code_display, 500),
        "value_numeric": value_numeric,
        "value_string": _safe_str(value_string, 500),
        "unit": _safe_str(unit, 50),
        "effective_date": _safe_date(effective_date),
        "status": _safe_str(status, 50),
        "raw_json": json.dumps(resource),
    }


def parse_diagnostic_report(resource: dict[str, Any]) -> dict[str, Any]:
    """
    Extract structured data from a FHIR R4 DiagnosticReport resource.
    """
    fhir_id: str = resource.get("id", "")

    # Subject
    subject_ref: str = resource.get("subject", {}).get("reference", "")
    fhir_patient_id = subject_ref.split("/")[-1] if "/" in subject_ref else subject_ref

    # Status
    status = resource.get("status", "")

    # Category
    category_display = ""
    for cat in resource.get("category", []):
        for c in cat.get("coding", []):
            if c.get("display"):
                category_display = c["display"]
                break
        if not category_display:
            category_display = cat.get("text", "")

    # Code
    code_display = ""
    code_obj = resource.get("code", {})
    for c in code_obj.get("coding", []):
        if c.get("display"):
            code_display = c["display"]
            break
    if not code_display:
        code_display = code_obj.get("text", "")

    # Effective date
    effective_date = (
        resource.get("effectiveDateTime")
        or resource.get("effectivePeriod", {}).get("start")
        or ""
    )

    # Conclusion (narrative text)
    conclusion = resource.get("conclusion", "")

    # Conclusion codes (ICD-10)
    conclusion_codes: list[str] = []
    for cc in resource.get("conclusionCode", []):
        conclusion_codes.extend(_extract_coding(cc.get("coding", []), ICD10_CM_SYSTEM))

    # Observation references
    observation_refs: list[str] = [
        r.get("reference", "")
        for r in resource.get("result", [])
        if r.get("reference")
    ]

    # Encounter reference
    encounter_ref: str = resource.get("encounter", {}).get("reference", "")
    fhir_encounter_id = encounter_ref.split("/")[-1] if "/" in encounter_ref else ""

    return {
        "fhir_resource_id": fhir_id,
        "fhir_patient_id": fhir_patient_id,
        "fhir_encounter_id": fhir_encounter_id,
        "status": status,
        "category_display": _safe_str(category_display, 200),
        "code_display": _safe_str(code_display, 200),
        "effective_date": _safe_str(effective_date, 30),
        "conclusion": _safe_str(conclusion, 2000),
        "conclusion_codes": json.dumps(conclusion_codes),
        "observation_refs": json.dumps(observation_refs),
        "raw_json": json.dumps(resource),
    }


def parse_patient(resource: dict[str, Any]) -> dict[str, Any]:
    """
    Extract identifying fields from a FHIR R4 Patient resource.
    Returns a flat dict suitable for matching and storage.
    """
    fhir_id: str = resource.get("id", "")

    # MRN — look for identifier with 'MR' type code
    mrn = ""
    for ident in resource.get("identifier", []):
        type_codings = ident.get("type", {}).get("coding", [])
        if any(c.get("code") == "MR" for c in type_codings):
            mrn = ident.get("value", "")
            break
    if not mrn:
        # Fall back to first identifier
        identifiers = resource.get("identifier", [])
        if identifiers:
            mrn = identifiers[0].get("value", "")

    # Name
    family = ""
    given = ""
    for name in resource.get("name", []):
        if name.get("use") in ("official", "usual") or not family:
            family = name.get("family", "")
            given_list = name.get("given", [])
            given = given_list[0] if given_list else ""
            if name.get("use") == "official":
                break

    # DOB
    birth_date = resource.get("birthDate", "")

    # Gender
    gender = resource.get("gender", "")

    # Phone / email
    phone = ""
    email = ""
    for telecom in resource.get("telecom", []):
        system = telecom.get("system", "")
        value = telecom.get("value", "")
        if system == "phone" and not phone:
            phone = value
        elif system == "email" and not email:
            email = value

    return {
        "fhir_resource_id": fhir_id,
        "mrn": _safe_str(mrn, 100),
        "family_name": _safe_str(family, 100),
        "given_name": _safe_str(given, 100),
        "birth_date": _safe_str(birth_date, 20),
        "gender": gender,
        "phone": _safe_str(phone, 50),
        "email": _safe_str(email, 200),
        "raw_json": json.dumps(resource),
    }


# ---------------------------------------------------------------------------
# Database helpers — connection management
# ---------------------------------------------------------------------------

def get_connection(connection_id: int) -> dict[str, Any] | None:
    """Fetch a FHIR connection record from the DB.

    The ``client_secret`` column is stored encrypted; it is transparently
    decrypted here so callers receive the plaintext value.
    """
    with raf_cursor() as cur:
        cur.execute(
            "SELECT * FROM fhir_connections WHERE id = %s LIMIT 1",
            (connection_id,),
        )
        row = cur.fetchone()
    if row and row.get("client_secret"):
        try:
            row["client_secret"] = decrypt(row["client_secret"])
        except ValueError:
            # Value is not encrypted (legacy plaintext row) – leave as-is so
            # existing connections keep working until they are next updated.
            pass
    return row


def list_connections() -> list[dict[str, Any]]:
    """Return all FHIR connection records."""
    with raf_cursor() as cur:
        cur.execute(
            "SELECT id, name, vendor, base_url, auth_type, scope, is_active, "
            "last_sync_at, last_sync_status, created_at, updated_at "
            "FROM fhir_connections ORDER BY name"
        )
        return cur.fetchall()


def create_connection(data: dict[str, Any]) -> int:
    """Insert a new FHIR connection and return its id.

    ``client_secret`` is encrypted with AES-256-GCM before being written to
    the database so the column never contains plaintext credentials.
    """
    now = _now_utc()
    raw_secret: str = data.get("client_secret", "") or ""
    stored_secret: str = encrypt(raw_secret) if raw_secret else ""
    with raf_cursor() as cur:
        cur.execute(
            """
            INSERT INTO fhir_connections
                (name, vendor, base_url, auth_type, token_url, client_id,
                 client_secret, api_key, scope, is_active, created_at, updated_at)
            VALUES
                (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                data["name"],
                data.get("vendor", "generic"),
                data["base_url"],
                data.get("auth_type", "none"),
                data.get("token_url", ""),
                data.get("client_id", ""),
                stored_secret,
                data.get("api_key", ""),
                data.get("scope", "system/*.read"),
                data.get("is_active", True),
                now,
                now,
            ),
        )
        return cur.lastrowid


def update_connection(connection_id: int, data: dict[str, Any]) -> None:
    """Update mutable fields of a FHIR connection.

    If ``client_secret`` is present in *data* it is encrypted before the
    UPDATE so the database column never contains a plaintext credential.
    """
    now = _now_utc()
    # Encrypt the secret before building the field list so the modified copy
    # ends up in the SQL values rather than the caller's original dict.
    update_data = dict(data)
    if "client_secret" in update_data:
        raw = update_data["client_secret"] or ""
        update_data["client_secret"] = encrypt(raw) if raw else ""

    fields = []
    values: list[Any] = []
    allowed = [
        "name", "vendor", "base_url", "auth_type", "token_url",
        "client_id", "client_secret", "api_key", "scope", "is_active",
    ]
    for key in allowed:
        if key in update_data:
            fields.append(f"{key} = %s")
            values.append(update_data[key])

    if not fields:
        return

    fields.append("updated_at = %s")
    values.append(now)
    values.append(connection_id)

    with raf_cursor() as cur:
        cur.execute(
            f"UPDATE fhir_connections SET {', '.join(fields)} WHERE id = %s",
            values,
        )


def delete_connection(connection_id: int) -> None:
    """Delete a FHIR connection and its associated data."""
    with raf_cursor() as cur:
        cur.execute("DELETE FROM fhir_connections WHERE id = %s", (connection_id,))


def _update_connection_sync_status(
    connection_id: int,
    status: str,
    message: str = "",
) -> None:
    now = _now_utc()
    with raf_cursor() as cur:
        cur.execute(
            """
            UPDATE fhir_connections
            SET last_sync_at = %s, last_sync_status = %s,
                last_sync_message = %s, updated_at = %s
            WHERE id = %s
            """,
            (now, status, _safe_str(message, 500), now, connection_id),
        )


# ---------------------------------------------------------------------------
# Database helpers — sync log
# ---------------------------------------------------------------------------

def _insert_sync_log(
    connection_id: int,
    sync_type: str,
    status: str,
    message: str = "",
    patients_synced: int = 0,
    conditions_synced: int = 0,
    encounters_synced: int = 0,
    reports_synced: int = 0,
) -> int:
    now = _now_utc()
    with raf_cursor() as cur:
        cur.execute(
            """
            INSERT INTO fhir_sync_logs
                (connection_id, sync_type, status, message,
                 patients_synced, conditions_synced, encounters_synced,
                 reports_synced, started_at, completed_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                connection_id, sync_type, status, _safe_str(message, 500),
                patients_synced, conditions_synced, encounters_synced,
                reports_synced, now, now,
            ),
        )
        return cur.lastrowid


def _update_sync_log(log_id: int, **kwargs: Any) -> None:
    now = _now_utc()
    fields = [f"{k} = %s" for k in kwargs]
    fields.append("completed_at = %s")
    values = list(kwargs.values()) + [now, log_id]
    with raf_cursor() as cur:
        cur.execute(
            f"UPDATE fhir_sync_logs SET {', '.join(fields)} WHERE id = %s",
            values,
        )


def get_sync_history(connection_id: int, limit: int = 20) -> list[dict[str, Any]]:
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT * FROM fhir_sync_logs
            WHERE connection_id = %s
            ORDER BY started_at DESC
            LIMIT %s
            """,
            (connection_id, limit),
        )
        return cur.fetchall()


# ---------------------------------------------------------------------------
# Database helpers — patients
# ---------------------------------------------------------------------------

def _upsert_fhir_patient(connection_id: int, parsed: dict[str, Any]) -> int:
    """
    Insert or update a fhir_patients row.
    Returns the row id.
    """
    now = _now_utc()
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT id FROM fhir_patients
            WHERE connection_id = %s AND fhir_resource_id = %s
            LIMIT 1
            """,
            (connection_id, parsed["fhir_resource_id"]),
        )
        existing = cur.fetchone()

        if existing:
            cur.execute(
                """
                UPDATE fhir_patients
                SET mrn = %s, family_name = %s, given_name = %s,
                    birth_date = %s, gender = %s, phone = %s, email = %s,
                    raw_json = %s, updated_at = %s
                WHERE id = %s
                """,
                (
                    parsed["mrn"], parsed["family_name"], parsed["given_name"],
                    parsed["birth_date"], parsed["gender"], parsed["phone"],
                    parsed["email"], parsed["raw_json"], now, existing["id"],
                ),
            )
            return existing["id"]
        else:
            cur.execute(
                """
                INSERT INTO fhir_patients
                    (connection_id, fhir_resource_id, mrn, family_name, given_name,
                     birth_date, gender, phone, email, raw_json, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    connection_id,
                    parsed["fhir_resource_id"],
                    parsed["mrn"], parsed["family_name"], parsed["given_name"],
                    parsed["birth_date"], parsed["gender"], parsed["phone"],
                    parsed["email"], parsed["raw_json"], now, now,
                ),
            )
            return cur.lastrowid


def list_fhir_patients(
    connection_id: int,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT id, fhir_resource_id, mrn, family_name, given_name,
                   birth_date, gender, openemr_pid, mapping_status, created_at
            FROM fhir_patients
            WHERE connection_id = %s
            ORDER BY family_name, given_name
            LIMIT %s OFFSET %s
            """,
            (connection_id, limit, offset),
        )
        return cur.fetchall()


def map_patient_to_openemr(
    connection_id: int,
    fhir_patient_id_or_row_id: int | str,
    openemr_pid: int,
) -> None:
    """Associate a fhir_patients row with an OpenEMR pid."""
    now = _now_utc()
    with raf_cursor() as cur:
        cur.execute(
            """
            UPDATE fhir_patients
            SET openemr_pid = %s, mapping_status = 'mapped', updated_at = %s
            WHERE id = %s AND connection_id = %s
            """,
            (openemr_pid, now, fhir_patient_id_or_row_id, connection_id),
        )


# ---------------------------------------------------------------------------
# Database helpers — conditions
# ---------------------------------------------------------------------------

def _upsert_fhir_condition(connection_id: int, parsed: dict[str, Any]) -> int:
    now = _now_utc()
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT id FROM fhir_conditions
            WHERE connection_id = %s AND fhir_resource_id = %s
            LIMIT 1
            """,
            (connection_id, parsed["fhir_resource_id"]),
        )
        existing = cur.fetchone()

        if existing:
            cur.execute(
                """
                UPDATE fhir_conditions
                SET icd10_codes = %s, display = %s, clinical_status = %s,
                    verification_status = %s, onset_date = %s, recorded_date = %s,
                    fhir_encounter_id = %s, raw_json = %s, updated_at = %s
                WHERE id = %s
                """,
                (
                    parsed["icd10_codes"], parsed["display"],
                    parsed["clinical_status"], parsed["verification_status"],
                    parsed["onset_date"], parsed["recorded_date"],
                    parsed["fhir_encounter_id"], parsed["raw_json"],
                    now, existing["id"],
                ),
            )
            return existing["id"]
        else:
            cur.execute(
                """
                INSERT INTO fhir_conditions
                    (connection_id, fhir_resource_id, fhir_patient_id, fhir_encounter_id,
                     icd10_codes, display, clinical_status, verification_status,
                     onset_date, recorded_date, raw_json, hcc_mapped, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 0, %s, %s)
                """,
                (
                    connection_id,
                    parsed["fhir_resource_id"],
                    parsed["fhir_patient_id"],
                    parsed["fhir_encounter_id"],
                    parsed["icd10_codes"],
                    parsed["display"],
                    parsed["clinical_status"],
                    parsed["verification_status"],
                    parsed["onset_date"],
                    parsed["recorded_date"],
                    parsed["raw_json"],
                    now, now,
                ),
            )
            return cur.lastrowid


def list_fhir_conditions(
    connection_id: int,
    limit: int = 200,
    offset: int = 0,
) -> list[dict[str, Any]]:
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT id, fhir_resource_id, fhir_patient_id, icd10_codes,
                   display, clinical_status, verification_status,
                   onset_date, recorded_date, hcc_mapped, created_at
            FROM fhir_conditions
            WHERE connection_id = %s
            ORDER BY recorded_date DESC, id DESC
            LIMIT %s OFFSET %s
            """,
            (connection_id, limit, offset),
        )
        return cur.fetchall()


def list_unmapped_conditions(
    connection_id: int,
    limit: int = 200,
) -> list[dict[str, Any]]:
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT fc.*, fp.openemr_pid, fp.family_name, fp.given_name
            FROM fhir_conditions fc
            LEFT JOIN fhir_patients fp
                ON fp.connection_id = fc.connection_id
                AND fp.fhir_resource_id = fc.fhir_patient_id
            WHERE fc.connection_id = %s
              AND fc.hcc_mapped = 0
              AND fc.clinical_status IN ('active', 'recurrence', 'relapse', '')
            ORDER BY fc.recorded_date DESC
            LIMIT %s
            """,
            (connection_id, limit),
        )
        return cur.fetchall()


# ---------------------------------------------------------------------------
# Database helpers — encounters
# ---------------------------------------------------------------------------

def _upsert_fhir_encounter(connection_id: int, parsed: dict[str, Any]) -> int:
    now = _now_utc()
    with raf_cursor() as cur:
        cur.execute(
            "SELECT id FROM fhir_encounters WHERE connection_id = %s AND fhir_resource_id = %s LIMIT 1",
            (connection_id, parsed["fhir_resource_id"]),
        )
        existing = cur.fetchone()

        if existing:
            cur.execute(
                """
                UPDATE fhir_encounters
                SET status = %s, encounter_class = %s, encounter_class_display = %s,
                    type_display = %s, period_start = %s, period_end = %s,
                    provider_name = %s, provider_ref = %s, reason_codes = %s,
                    service_provider = %s, raw_json = %s, updated_at = %s
                WHERE id = %s
                """,
                (
                    parsed["status"], parsed["encounter_class"],
                    parsed["encounter_class_display"], parsed["type_display"],
                    parsed["period_start"], parsed["period_end"],
                    parsed["provider_name"], parsed["provider_ref"],
                    parsed["reason_codes"], parsed["service_provider"],
                    parsed["raw_json"], now, existing["id"],
                ),
            )
            return existing["id"]
        else:
            cur.execute(
                """
                INSERT INTO fhir_encounters
                    (connection_id, fhir_resource_id, fhir_patient_id,
                     status, encounter_class, encounter_class_display,
                     type_display, period_start, period_end,
                     provider_name, provider_ref, reason_codes,
                     service_provider, raw_json, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    connection_id,
                    parsed["fhir_resource_id"],
                    parsed["fhir_patient_id"],
                    parsed["status"],
                    parsed["encounter_class"],
                    parsed["encounter_class_display"],
                    parsed["type_display"],
                    parsed["period_start"],
                    parsed["period_end"],
                    parsed["provider_name"],
                    parsed["provider_ref"],
                    parsed["reason_codes"],
                    parsed["service_provider"],
                    parsed["raw_json"],
                    now, now,
                ),
            )
            return cur.lastrowid


# ---------------------------------------------------------------------------
# Database helpers — diagnostic reports
# ---------------------------------------------------------------------------

def _upsert_fhir_diagnostic_report(connection_id: int, parsed: dict[str, Any]) -> int:
    now = _now_utc()
    with raf_cursor() as cur:
        cur.execute(
            "SELECT id FROM fhir_diagnostic_reports WHERE connection_id = %s AND fhir_report_id = %s LIMIT 1",
            (connection_id, parsed["fhir_resource_id"]),
        )
        existing = cur.fetchone()

        if existing:
            cur.execute(
                """
                UPDATE fhir_diagnostic_reports
                SET status = %s, category = %s, report_type = %s,
                    effective_date = %s, conclusion = %s,
                    fhir_resource = %s, updated_at = %s
                WHERE id = %s
                """,
                (
                    parsed["status"], parsed.get("category_display", ""),
                    parsed.get("code_display", ""),
                    parsed["effective_date"], parsed["conclusion"],
                    parsed["raw_json"], now, existing["id"],
                ),
            )
            return existing["id"]
        else:
            cur.execute(
                """
                INSERT INTO fhir_diagnostic_reports
                    (connection_id, fhir_report_id, fhir_patient_id,
                     status, category, report_type, effective_date,
                     conclusion, fhir_resource, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    connection_id,
                    parsed["fhir_resource_id"],
                    parsed["fhir_patient_id"],
                    parsed["status"],
                    parsed.get("category_display", ""),
                    parsed.get("code_display", ""),
                    parsed["effective_date"],
                    parsed["conclusion"],
                    parsed["raw_json"],
                    now, now,
                ),
            )
            return cur.lastrowid


# ---------------------------------------------------------------------------
# Database helpers — medications
# ---------------------------------------------------------------------------

def _upsert_fhir_medication(connection_id: int, parsed: dict[str, Any]) -> int:
    now = _now_utc()
    with raf_cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS fhir_medications (
                id INT AUTO_INCREMENT PRIMARY KEY,
                connection_id INT NOT NULL,
                fhir_resource_id VARCHAR(200) NOT NULL,
                fhir_patient_id VARCHAR(200),
                medication_code VARCHAR(50),
                medication_display VARCHAR(500),
                status VARCHAR(50),
                intent VARCHAR(50),
                authored_on DATE,
                dosage_text TEXT,
                raw_json LONGTEXT,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                UNIQUE KEY uq_conn_fhir_med (connection_id, fhir_resource_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        cur.execute(
            """
            SELECT id FROM fhir_medications
            WHERE connection_id = %s AND fhir_resource_id = %s
            LIMIT 1
            """,
            (connection_id, parsed["fhir_resource_id"]),
        )
        existing = cur.fetchone()

        if existing:
            cur.execute(
                """
                UPDATE fhir_medications
                SET medication_code = %s, medication_display = %s, status = %s,
                    intent = %s, authored_on = %s, dosage_text = %s,
                    raw_json = %s, updated_at = %s
                WHERE id = %s
                """,
                (
                    parsed["medication_code"], parsed["medication_display"],
                    parsed["status"], parsed["intent"], parsed["authored_on"],
                    parsed["dosage_text"], parsed["raw_json"],
                    now, existing["id"],
                ),
            )
            return existing["id"]
        else:
            cur.execute(
                """
                INSERT INTO fhir_medications
                    (connection_id, fhir_resource_id, fhir_patient_id,
                     medication_code, medication_display, status, intent,
                     authored_on, dosage_text, raw_json, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    connection_id,
                    parsed["fhir_resource_id"],
                    parsed["fhir_patient_id"],
                    parsed["medication_code"],
                    parsed["medication_display"],
                    parsed["status"],
                    parsed["intent"],
                    parsed["authored_on"],
                    parsed["dosage_text"],
                    parsed["raw_json"],
                    now, now,
                ),
            )
            return cur.lastrowid


# ---------------------------------------------------------------------------
# Database helpers — observations
# ---------------------------------------------------------------------------

def _upsert_fhir_observation(connection_id: int, parsed: dict[str, Any]) -> int:
    now = _now_utc()
    with raf_cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS fhir_observations (
                id INT AUTO_INCREMENT PRIMARY KEY,
                connection_id INT NOT NULL,
                fhir_resource_id VARCHAR(200) NOT NULL,
                fhir_patient_id VARCHAR(200),
                category VARCHAR(50),
                code VARCHAR(50),
                code_display VARCHAR(500),
                value_numeric DECIMAL(10,4),
                value_string VARCHAR(500),
                unit VARCHAR(50),
                effective_date DATE,
                status VARCHAR(50),
                raw_json LONGTEXT,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                UNIQUE KEY uq_conn_fhir_obs (connection_id, fhir_resource_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        cur.execute(
            """
            SELECT id FROM fhir_observations
            WHERE connection_id = %s AND fhir_resource_id = %s
            LIMIT 1
            """,
            (connection_id, parsed["fhir_resource_id"]),
        )
        existing = cur.fetchone()

        if existing:
            cur.execute(
                """
                UPDATE fhir_observations
                SET category = %s, code = %s, code_display = %s,
                    value_numeric = %s, value_string = %s, unit = %s,
                    effective_date = %s, status = %s,
                    raw_json = %s, updated_at = %s
                WHERE id = %s
                """,
                (
                    parsed["category"], parsed["code"], parsed["code_display"],
                    parsed["value_numeric"], parsed["value_string"], parsed["unit"],
                    parsed["effective_date"], parsed["status"],
                    parsed["raw_json"], now, existing["id"],
                ),
            )
            return existing["id"]
        else:
            cur.execute(
                """
                INSERT INTO fhir_observations
                    (connection_id, fhir_resource_id, fhir_patient_id,
                     category, code, code_display,
                     value_numeric, value_string, unit,
                     effective_date, status, raw_json, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    connection_id,
                    parsed["fhir_resource_id"],
                    parsed["fhir_patient_id"],
                    parsed["category"],
                    parsed["code"],
                    parsed["code_display"],
                    parsed["value_numeric"],
                    parsed["value_string"],
                    parsed["unit"],
                    parsed["effective_date"],
                    parsed["status"],
                    parsed["raw_json"],
                    now, now,
                ),
            )
            return cur.lastrowid


# ---------------------------------------------------------------------------
# AllergyIntolerance — parser, upsert, sync
# ---------------------------------------------------------------------------


def parse_allergy_intolerance(resource: dict[str, Any]) -> dict[str, Any]:
    """Extract structured data from a FHIR R4 AllergyIntolerance resource."""
    fhir_id = resource.get("id", "")
    subject_ref = resource.get("patient", {}).get("reference", "")
    fhir_patient_id = subject_ref.split("/")[-1] if "/" in subject_ref else subject_ref

    # Code
    code_cc = resource.get("code", {})
    codings = code_cc.get("coding", [])
    allergy_code = codings[0].get("code", "") if codings else ""
    allergy_display = codings[0].get("display", "") if codings else ""
    if not allergy_display:
        allergy_display = code_cc.get("text", "")

    clinical_status = ""
    cs = resource.get("clinicalStatus", {})
    cs_codings = cs.get("coding", [])
    if cs_codings:
        clinical_status = cs_codings[0].get("code", "")

    verification_status = ""
    vs = resource.get("verificationStatus", {})
    vs_codings = vs.get("coding", [])
    if vs_codings:
        verification_status = vs_codings[0].get("code", "")

    category = ""
    cats = resource.get("category", [])
    if cats:
        category = cats[0]

    criticality = resource.get("criticality", "")
    allergy_type = resource.get("type", "")
    onset = resource.get("onsetDateTime", "") or resource.get("onsetString", "")
    recorded_date = resource.get("recordedDate", "")

    return {
        "fhir_resource_id": fhir_id,
        "fhir_patient_id": fhir_patient_id,
        "allergy_code": allergy_code[:50],
        "allergy_display": allergy_display[:500],
        "clinical_status": clinical_status[:50],
        "verification_status": verification_status[:50],
        "category": category[:50],
        "criticality": criticality[:50],
        "allergy_type": allergy_type[:50],
        "onset_date": onset[:10] if onset else None,
        "recorded_date": recorded_date[:10] if recorded_date else None,
        "raw_json": json.dumps(resource, default=str),
    }


def _upsert_fhir_allergy(connection_id: int, parsed: dict[str, Any]) -> int:
    now = _now_utc()
    with raf_cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS fhir_allergies (
                id INT AUTO_INCREMENT PRIMARY KEY,
                connection_id INT NOT NULL,
                fhir_resource_id VARCHAR(200) NOT NULL,
                fhir_patient_id VARCHAR(200),
                allergy_code VARCHAR(50),
                allergy_display VARCHAR(500),
                clinical_status VARCHAR(50),
                verification_status VARCHAR(50),
                category VARCHAR(50),
                criticality VARCHAR(50),
                allergy_type VARCHAR(50),
                onset_date DATE,
                recorded_date DATE,
                raw_json LONGTEXT,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                UNIQUE KEY uq_conn_fhir_allergy (connection_id, fhir_resource_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        cur.execute(
            "SELECT id FROM fhir_allergies WHERE connection_id = %s AND fhir_resource_id = %s LIMIT 1",
            (connection_id, parsed["fhir_resource_id"]),
        )
        existing = cur.fetchone()

        if existing:
            cur.execute(
                """
                UPDATE fhir_allergies
                SET allergy_code = %s, allergy_display = %s, clinical_status = %s,
                    verification_status = %s, category = %s, criticality = %s,
                    allergy_type = %s, onset_date = %s, recorded_date = %s,
                    raw_json = %s, updated_at = %s
                WHERE id = %s
                """,
                (
                    parsed["allergy_code"], parsed["allergy_display"],
                    parsed["clinical_status"], parsed["verification_status"],
                    parsed["category"], parsed["criticality"],
                    parsed["allergy_type"], parsed["onset_date"],
                    parsed["recorded_date"], parsed["raw_json"],
                    now, existing["id"],
                ),
            )
            return existing["id"]
        else:
            cur.execute(
                """
                INSERT INTO fhir_allergies
                    (connection_id, fhir_resource_id, fhir_patient_id,
                     allergy_code, allergy_display, clinical_status, verification_status,
                     category, criticality, allergy_type,
                     onset_date, recorded_date, raw_json, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    connection_id,
                    parsed["fhir_resource_id"], parsed["fhir_patient_id"],
                    parsed["allergy_code"], parsed["allergy_display"],
                    parsed["clinical_status"], parsed["verification_status"],
                    parsed["category"], parsed["criticality"],
                    parsed["allergy_type"], parsed["onset_date"],
                    parsed["recorded_date"], parsed["raw_json"],
                    now, now,
                ),
            )
            return cur.lastrowid


async def _sync_allergies_async(
    connection: dict[str, Any],
    last_updated: str | None = None,
) -> int:
    """Fetch and upsert all AllergyIntolerance resources. Returns count synced."""
    params: dict[str, Any] = {"_count": 100}
    if last_updated:
        params["_lastUpdated"] = f"gt{last_updated}"

    resources = await _fhir_get_all_pages(connection, "AllergyIntolerance", params=params)
    count = 0
    for resource in resources:
        parsed = parse_allergy_intolerance(resource)
        _upsert_fhir_allergy(connection["id"], parsed)
        count += 1

    logger.info("Synced %d AllergyIntolerance resources for connection %s", count, connection["id"])
    return count


# ---------------------------------------------------------------------------
# Patient matching — FHIR Patient → OpenEMR pid
# ---------------------------------------------------------------------------

def _find_openemr_pid_by_mrn(mrn: str, tenant_id: str = "1") -> int | None:
    """Search OpenEMR patient_data for a matching MRN."""
    if not mrn:
        return None
    with openemr_cursor(tenant_id=tenant_id) as cur:
        # pubpid and pid are the main identifier columns in OpenEMR
        cur.execute(
            """
            SELECT pid FROM patient_data
            WHERE pubpid = %s OR pid = %s
            LIMIT 1
            """,
            (mrn, mrn),
        )
        row = cur.fetchone()
    return int(row["pid"]) if row else None


def _find_openemr_pid_by_name_dob(
    family: str, given: str, dob: str, tenant_id: str = "1"
) -> int | None:
    """Search OpenEMR patient_data by last name, first name, and date of birth."""
    if not family or not dob:
        return None
    with openemr_cursor(tenant_id=tenant_id) as cur:
        cur.execute(
            """
            SELECT pid FROM patient_data
            WHERE LOWER(lname) = LOWER(%s)
              AND LOWER(fname) = LOWER(%s)
              AND DOB = %s
            LIMIT 1
            """,
            (family, given, dob),
        )
        row = cur.fetchone()
    return int(row["pid"]) if row else None


def attempt_auto_map_patient(connection_id: int, fhir_row_id: int) -> int | None:
    """
    Try to automatically map a fhir_patients row to an OpenEMR pid.
    First tries MRN match, then falls back to name + DOB.
    Updates the DB row when a match is found.
    Returns the matched pid, or None.
    """
    with raf_cursor() as cur:
        cur.execute(
            "SELECT * FROM fhir_patients WHERE id = %s AND connection_id = %s LIMIT 1",
            (fhir_row_id, connection_id),
        )
        row = cur.fetchone()

    if not row:
        return None

    # Resolve tenant_id from the connection for openemr_cursor calls
    conn = get_connection(connection_id)
    _tid = (conn or {}).get("tenant_id", "1") or "1"

    pid = _find_openemr_pid_by_mrn(row["mrn"], tenant_id=_tid)
    if not pid:
        pid = _find_openemr_pid_by_name_dob(
            row["family_name"], row["given_name"], row["birth_date"], tenant_id=_tid
        )

    if pid:
        map_patient_to_openemr(connection_id, fhir_row_id, pid)

    return pid


# ---------------------------------------------------------------------------
# Core connectivity test
# ---------------------------------------------------------------------------

async def test_connection_async(connection: dict[str, Any]) -> dict[str, Any]:
    """
    Attempt to GET the FHIR server's CapabilityStatement (metadata endpoint).
    Returns a result dict with success, status_code, and a message.
    """
    result: dict[str, Any] = {
        "success": False,
        "status_code": None,
        "message": "",
        "server_name": "",
        "fhir_version": "",
    }
    try:
        data = await _fhir_get(connection, "metadata")
        result["success"] = True
        result["status_code"] = 200
        result["server_name"] = data.get("implementation", {}).get("description", "")
        result["fhir_version"] = data.get("fhirVersion", "")
        result["message"] = "Connection successful"
    except httpx.HTTPStatusError as exc:
        result["status_code"] = exc.response.status_code
        result["message"] = f"HTTP {exc.response.status_code}: {exc.response.text[:200]}"
    except PermissionError as exc:
        result["status_code"] = 401
        result["message"] = str(exc)
    except Exception as exc:
        result["message"] = str(exc)

    return result


@fhir_breaker
def test_connection(connection: dict[str, Any]) -> dict[str, Any]:
    """Synchronous wrapper around test_connection_async."""
    return asyncio.run(test_connection_async(connection))


# ---------------------------------------------------------------------------
# Per-resource sync routines
# ---------------------------------------------------------------------------

async def _sync_patients_async(
    connection: dict[str, Any],
    last_updated: str | None = None,
) -> int:
    """Fetch and upsert all Patient resources. Returns count synced."""
    params: dict[str, Any] = {"_count": 100}
    if last_updated:
        params["_lastUpdated"] = f"gt{last_updated}"

    resources = await _fhir_get_all_pages(connection, "Patient", params=params)
    count = 0
    for resource in resources:
        parsed = parse_patient(resource)
        row_id = _upsert_fhir_patient(connection["id"], parsed)
        # Attempt auto-mapping on every upsert
        attempt_auto_map_patient(connection["id"], row_id)
        count += 1

    logger.info("Synced %d Patient resources for connection %s", count, connection["id"])
    return count


async def _sync_conditions_async(
    connection: dict[str, Any],
    last_updated: str | None = None,
) -> int:
    """Fetch and upsert all Condition resources. Returns count synced."""
    params: dict[str, Any] = {"_count": 100}
    if last_updated:
        params["_lastUpdated"] = f"gt{last_updated}"

    resources = await _fhir_get_all_pages(connection, "Condition", params=params)
    count = 0
    for resource in resources:
        parsed = parse_condition(resource)
        _upsert_fhir_condition(connection["id"], parsed)
        count += 1

    logger.info("Synced %d Condition resources for connection %s", count, connection["id"])
    return count


async def _sync_encounters_async(
    connection: dict[str, Any],
    last_updated: str | None = None,
) -> int:
    """Fetch and upsert all Encounter resources. Returns count synced."""
    params: dict[str, Any] = {"_count": 100}
    if last_updated:
        params["_lastUpdated"] = f"gt{last_updated}"

    resources = await _fhir_get_all_pages(connection, "Encounter", params=params)
    count = 0
    for resource in resources:
        parsed = parse_encounter(resource)
        _upsert_fhir_encounter(connection["id"], parsed)
        count += 1

    logger.info("Synced %d Encounter resources for connection %s", count, connection["id"])
    return count


async def _sync_diagnostic_reports_async(
    connection: dict[str, Any],
    last_updated: str | None = None,
) -> int:
    """Fetch and upsert all DiagnosticReport resources. Returns count synced."""
    params: dict[str, Any] = {"_count": 100}
    if last_updated:
        params["_lastUpdated"] = f"gt{last_updated}"

    resources = await _fhir_get_all_pages(connection, "DiagnosticReport", params=params)
    count = 0
    for resource in resources:
        parsed = parse_diagnostic_report(resource)
        _upsert_fhir_diagnostic_report(connection["id"], parsed)
        count += 1

    logger.info("Synced %d DiagnosticReport resources for connection %s", count, connection["id"])
    return count


async def _sync_medications_async(
    connection: dict[str, Any],
    last_updated: str | None = None,
) -> int:
    """Fetch and upsert all MedicationRequest resources. Returns count synced."""
    params: dict[str, Any] = {"_count": 100}
    if last_updated:
        params["_lastUpdated"] = f"gt{last_updated}"

    resources = await _fhir_get_all_pages(connection, "MedicationRequest", params=params)
    count = 0
    for resource in resources:
        parsed = parse_medication_request(resource)
        _upsert_fhir_medication(connection["id"], parsed)
        count += 1

    logger.info("Synced %d MedicationRequest resources for connection %s", count, connection["id"])
    return count


async def _sync_observations_async(
    connection: dict[str, Any],
    last_updated: str | None = None,
) -> int:
    """Fetch and upsert all Observation resources. Returns count synced."""
    params: dict[str, Any] = {"_count": 100}
    if last_updated:
        params["_lastUpdated"] = f"gt{last_updated}"

    resources = await _fhir_get_all_pages(connection, "Observation", params=params)
    count = 0
    for resource in resources:
        parsed = parse_observation(resource)
        _upsert_fhir_observation(connection["id"], parsed)
        count += 1

    logger.info("Synced %d Observation resources for connection %s", count, connection["id"])
    return count


# ---------------------------------------------------------------------------
# Bulk FHIR $export
# ---------------------------------------------------------------------------

async def _bulk_export_async(
    connection: dict[str, Any],
    resource_types: list[str] | None = None,
    since: str | None = None,
) -> dict[str, Any]:
    """
    Kick off a FHIR Bulk Data $export operation and poll until complete.
    Returns {"files": [...], "error": None} or {"files": [], "error": "..."}.
    """
    base_url = connection["base_url"].rstrip("/")
    params: dict[str, Any] = {"_outputFormat": "application/fhir+ndjson"}
    if resource_types:
        params["_type"] = ",".join(resource_types)
    if since:
        params["_since"] = since

    auth_type: str = (connection.get("auth_type") or "none").lower()
    headers: dict[str, str] = {
        "Accept": "application/fhir+json",
        "Prefer": "respond-async",
    }
    if auth_type == "oauth2":
        token = await _get_token_async(connection)
        headers["Authorization"] = f"Bearer {token}"
    elif auth_type == "api_key":
        headers["Authorization"] = f"Bearer {connection.get('api_key', '')}"

    # Kick off export
    async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
        resp = await client.get(
            f"{base_url}/$export",
            headers=headers,
            params=params,
        )

    if resp.status_code not in (200, 202):
        return {"files": [], "error": f"Export initiation failed: {resp.status_code} {resp.text[:200]}"}

    # Spec: 202 with Content-Location header for status polling
    status_url = resp.headers.get("Content-Location")
    if not status_url:
        if resp.status_code == 200:
            # Some servers return the manifest immediately
            return {"files": resp.json().get("output", []), "error": None}
        return {"files": [], "error": "No Content-Location header in export response"}

    # Poll for completion
    for _ in range(_BULK_MAX_POLLS):
        await asyncio.sleep(_BULK_POLL_INTERVAL)
        async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
            poll_resp = await client.get(status_url, headers=headers)

        if poll_resp.status_code == 200:
            manifest = poll_resp.json()
            return {"files": manifest.get("output", []), "error": None}
        if poll_resp.status_code == 202:
            # Still processing — continue polling
            continue
        # Unexpected status
        return {"files": [], "error": f"Unexpected poll status {poll_resp.status_code}"}

    return {"files": [], "error": "Bulk export timed out after polling"}


async def _process_bulk_ndjson(
    connection: dict[str, Any],
    files: list[dict[str, Any]],
) -> dict[str, int]:
    """Download and process NDJSON bulk export files. Returns counts per type."""
    counts: dict[str, int] = {
        "Patient": 0,
        "Condition": 0,
        "Encounter": 0,
        "DiagnosticReport": 0,
        "MedicationRequest": 0,
        "Observation": 0,
    }

    auth_type: str = (connection.get("auth_type") or "none").lower()
    headers: dict[str, str] = {"Accept": "application/fhir+ndjson"}
    if auth_type == "oauth2":
        token = await _get_token_async(connection)
        headers["Authorization"] = f"Bearer {token}"
    elif auth_type == "api_key":
        headers["Authorization"] = f"Bearer {connection.get('api_key', '')}"

    for file_entry in files:
        url = file_entry.get("url", "")
        resource_type = file_entry.get("type", "")
        if not url:
            continue

        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
            resp = await client.get(url, headers=headers)
        resp.raise_for_status()

        for line in resp.text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                resource = json.loads(line)
            except json.JSONDecodeError:
                continue

            rtype = resource.get("resourceType", resource_type)
            if rtype == "Patient":
                parsed = parse_patient(resource)
                row_id = _upsert_fhir_patient(connection["id"], parsed)
                attempt_auto_map_patient(connection["id"], row_id)
                counts["Patient"] += 1
            elif rtype == "Condition":
                _upsert_fhir_condition(connection["id"], parse_condition(resource))
                counts["Condition"] += 1
            elif rtype == "Encounter":
                _upsert_fhir_encounter(connection["id"], parse_encounter(resource))
                counts["Encounter"] += 1
            elif rtype == "DiagnosticReport":
                _upsert_fhir_diagnostic_report(
                    connection["id"], parse_diagnostic_report(resource)
                )
                counts["DiagnosticReport"] += 1
            elif rtype == "MedicationRequest":
                _upsert_fhir_medication(
                    connection["id"], parse_medication_request(resource)
                )
                counts["MedicationRequest"] += 1
            elif rtype == "Observation":
                _upsert_fhir_observation(
                    connection["id"], parse_observation(resource)
                )
                counts["Observation"] += 1

    return counts


# ---------------------------------------------------------------------------
# Full / incremental sync orchestration
# ---------------------------------------------------------------------------

async def run_sync_async(
    connection_id: int,
    sync_type: str = "incremental",
    resource_types: list[str] | None = None,
    use_bulk: bool = False,
) -> dict[str, Any]:
    """
    Orchestrate a FHIR sync (full or incremental) for a connection.

    sync_type: "full" clears the last_updated marker; "incremental" uses it.
    resource_types: subset of ["Patient","Condition","Encounter","DiagnosticReport"].
    use_bulk: attempt $export bulk download instead of per-resource search.

    Returns a summary dict.
    """
    conn = get_connection(connection_id)
    if not conn:
        raise ValueError(f"FHIR connection {connection_id} not found")

    if not conn.get("is_active"):
        raise ValueError(f"FHIR connection {connection_id} is disabled")

    default_resources = ["Patient", "Condition", "Encounter", "DiagnosticReport", "MedicationRequest", "Observation", "AllergyIntolerance"]
    resources_to_sync = resource_types or default_resources

    # Determine last_updated cutoff for incremental
    last_updated: str | None = None
    if sync_type == "incremental":
        last_sync = conn.get("last_sync_at")
        if last_sync:
            last_updated = str(last_sync)[:19].replace(" ", "T") + "Z"

    log_id = _insert_sync_log(connection_id, sync_type, "running")
    _update_connection_sync_status(connection_id, "running")

    counts: dict[str, int] = {
        "Patient": 0,
        "Condition": 0,
        "Encounter": 0,
        "DiagnosticReport": 0,
        "MedicationRequest": 0,
        "Observation": 0,
    }

    try:
        sync_errors = []
        if use_bulk:
            bulk_result = await _bulk_export_async(conn, resources_to_sync, since=last_updated)
            if bulk_result["error"]:
                raise RuntimeError(bulk_result["error"])
            bulk_counts = await _process_bulk_ndjson(conn, bulk_result["files"])
            counts.update(bulk_counts)
        else:
            resource_syncs = [
                ("Patient", lambda: _sync_patients_async(conn, last_updated)),
                ("Condition", lambda: _sync_conditions_async(conn, last_updated)),
                ("Encounter", lambda: _sync_encounters_async(conn, last_updated)),
                ("DiagnosticReport", lambda: _sync_diagnostic_reports_async(conn, last_updated)),
                ("MedicationRequest", lambda: _sync_medications_async(conn, last_updated)),
                ("Observation", lambda: _sync_observations_async(conn, last_updated)),
                ("AllergyIntolerance", lambda: _sync_allergies_async(conn, last_updated)),
            ]
            for res_type, sync_fn in resource_syncs:
                if res_type in resources_to_sync:
                    try:
                        counts[res_type] = await sync_fn()
                    except Exception as e:
                        logger.warning("Sync failed for %s (connection %s): %s", res_type, connection_id, e)
                        sync_errors.append(f"{res_type}: {e}")

        summary = (
            f"Synced: {counts['Patient']} patients, {counts['Condition']} conditions, "
            f"{counts['Encounter']} encounters, {counts['DiagnosticReport']} reports, "
            f"{counts['MedicationRequest']} medications, {counts['Observation']} observations"
        )
        if sync_errors:
            summary += f" | Errors: {'; '.join(sync_errors)}"
        sync_status = "completed" if not sync_errors else "completed_with_errors"
        _update_sync_log(
            log_id,
            status=sync_status,
            message=summary,
            patients_synced=counts["Patient"],
            conditions_synced=counts["Condition"],
            encounters_synced=counts["Encounter"],
            reports_synced=counts["DiagnosticReport"],
        )
        _update_connection_sync_status(connection_id, sync_status, summary)
        logger.info("Sync complete for connection %s: %s", connection_id, summary)

        return {
            "log_id": log_id,
            "status": "completed",
            "sync_type": sync_type,
            "counts": counts,
            "message": summary,
        }

    except Exception as exc:
        error_msg = str(exc)
        logger.error("Sync failed for connection %s: %s", connection_id, error_msg)
        _update_sync_log(log_id, status="failed", message=error_msg[:500])
        _update_connection_sync_status(connection_id, "failed", error_msg)
        raise


@fhir_breaker
def run_sync(
    connection_id: int,
    sync_type: str = "incremental",
    resource_types: list[str] | None = None,
    use_bulk: bool = False,
) -> dict[str, Any]:
    """Synchronous wrapper around run_sync_async."""
    return asyncio.run(
        run_sync_async(connection_id, sync_type, resource_types, use_bulk)
    )


# ---------------------------------------------------------------------------
# Conditions → ICD-10 → HCC mapping → RAF calculation
# ---------------------------------------------------------------------------

def process_conditions_for_raf(
    connection_id: int,
    openemr_pid: int | None = None,
    limit: int = 500,
) -> dict[str, Any]:
    """
    For each unmapped fhir_condition that has ICD-10 codes:
      1. Find the linked OpenEMR pid (via fhir_patients mapping).
      2. Call the RAF calculator to incorporate new codes.
      3. Mark the condition as hcc_mapped.

    Returns a summary of what was processed.

    When openemr_pid is provided, only processes conditions for that patient.
    """
    from app.services.raf_calculator import calculate_raf_score
    from app.services.hccinfhir_utils import lookup_hcc

    with raf_cursor() as cur:
        if openemr_pid:
            cur.execute(
                """
                SELECT fc.*, fp.openemr_pid
                FROM fhir_conditions fc
                JOIN fhir_patients fp
                  ON fp.connection_id = fc.connection_id
                 AND fp.fhir_resource_id = fc.fhir_patient_id
                WHERE fc.connection_id = %s
                  AND fp.openemr_pid = %s
                  AND fc.hcc_mapped = 0
                  AND fc.icd10_codes IS NOT NULL
                  AND fc.icd10_codes != '[]'
                ORDER BY fc.id
                LIMIT %s
                """,
                (connection_id, openemr_pid, limit),
            )
        else:
            cur.execute(
                """
                SELECT fc.*, fp.openemr_pid
                FROM fhir_conditions fc
                JOIN fhir_patients fp
                  ON fp.connection_id = fc.connection_id
                 AND fp.fhir_resource_id = fc.fhir_patient_id
                WHERE fc.connection_id = %s
                  AND fp.openemr_pid IS NOT NULL
                  AND fc.hcc_mapped = 0
                  AND fc.icd10_codes IS NOT NULL
                  AND fc.icd10_codes != '[]'
                ORDER BY fc.id
                LIMIT %s
                """,
                (connection_id, limit),
            )
        rows = cur.fetchall()

    if not rows:
        return {
            "processed": 0,
            "hcc_mapped": 0,
            "raf_recalculated": 0,
            "skipped_no_pid": 0,
            "message": "No unmapped conditions with ICD-10 codes found",
        }

    processed = 0
    hcc_mapped = 0
    raf_recalculated = 0
    skipped_no_pid = 0
    pids_recalculated: set[int] = set()

    now = _now_utc()

    for row in rows:
        pid = row.get("openemr_pid")
        if not pid:
            skipped_no_pid += 1
            continue

        icd10_list: list[str] = []
        try:
            icd10_list = json.loads(row.get("icd10_codes") or "[]")
        except (json.JSONDecodeError, TypeError):
            pass

        hcc_codes: list[str] = []
        for code in icd10_list:
            result = lookup_hcc(code)
            if result.get("maps_to_hcc"):
                hcc_codes.extend(result.get("hcc_codes", []))

        has_hcc = bool(hcc_codes)

        with raf_cursor() as cur:
            cur.execute(
                """
                UPDATE fhir_conditions
                SET hcc_mapped = 1,
                    hcc_codes = %s,
                    hcc_mapped_at = %s,
                    updated_at = %s
                WHERE id = %s
                """,
                (
                    json.dumps(hcc_codes),
                    now,
                    now,
                    row["id"],
                ),
            )

        processed += 1
        if has_hcc:
            hcc_mapped += 1

        # Recalculate RAF for this patient once per batch (not per condition)
        if pid not in pids_recalculated:
            try:
                calculate_raf_score(int(pid))
                pids_recalculated.add(int(pid))
                raf_recalculated += 1
            except Exception as exc:
                logger.warning(
                    "RAF recalculation failed for pid %s after FHIR condition processing: %s",
                    pid, exc,
                )

    return {
        "processed": processed,
        "hcc_mapped": hcc_mapped,
        "raf_recalculated": raf_recalculated,
        "skipped_no_pid": skipped_no_pid,
        "patients_updated": list(pids_recalculated),
        "message": (
            f"Processed {processed} conditions; {hcc_mapped} mapped to HCC codes; "
            f"RAF recalculated for {raf_recalculated} patients"
        ),
    }


def extract_icd10_codes_for_patient(
    connection_id: int,
    fhir_patient_id: str,
) -> list[str]:
    """
    Return a deduplicated list of all ICD-10 codes from active fhir_conditions
    for the given FHIR patient ID.  Used to feed into RAF calculation directly.
    """
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT icd10_codes FROM fhir_conditions
            WHERE connection_id = %s
              AND fhir_patient_id = %s
              AND clinical_status IN ('active', 'recurrence', 'relapse', '')
              AND icd10_codes IS NOT NULL
              AND icd10_codes != '[]'
            """,
            (connection_id, fhir_patient_id),
        )
        rows = cur.fetchall()

    all_codes: list[str] = []
    for row in rows:
        try:
            codes = json.loads(row.get("icd10_codes") or "[]")
            all_codes.extend(codes)
        except (json.JSONDecodeError, TypeError):
            pass

    # Deduplicate while preserving order
    seen: set[str] = set()
    result: list[str] = []
    for code in all_codes:
        if code not in seen:
            seen.add(code)
            result.append(code)

    return result
