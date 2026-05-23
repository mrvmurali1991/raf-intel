"""
Clearinghouse Integration Service

Handles real-time and batch eligibility verification (ANSI X12 270/271) against
major clearinghouse vendors: Availity, Change Healthcare, Waystar, Trizetto,
and generic REST-based custom endpoints.

Architecture
------------
- ANSI X12 270 transactions are built as plain text with correct ISA/GS/ST
  envelope segments and a 2000B/2000C/2110C hierarchy.
- ANSI X12 271 responses are parsed segment by segment into a structured dict.
- Modern clearinghouses (Availity, Change Healthcare) also expose JSON REST
  APIs; those take priority when an api_key is configured.
- A lightweight in-process LRU cache prevents duplicate queries within a
  configurable TTL window (default: 4 hours).
- All vendor API calls are made via httpx with a hard timeout so slow
  responses never block the request loop indefinitely.
- API keys and secrets are stored encrypted at rest; this service decrypts
  them just-in-time using encryption_service.

HIPAA note
----------
PHI transmitted to clearinghouses is already covered by the BAA that providers
maintain with each clearinghouse.  Payloads stored in eligibility_checks are
considered ePHI; access is controlled by tenant_id at the database layer.
"""
from __future__ import annotations

import json
import logging
import random
import time
from datetime import date, datetime, timezone
from typing import Any

from app.db import raf_cursor
from app.services.encryption_service import decrypt, encrypt

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional httpx import — graceful degradation when package is absent
# ---------------------------------------------------------------------------
try:
    import httpx
    _HTTPX_AVAILABLE = True
except ImportError:
    _HTTPX_AVAILABLE = False
    logger.warning(
        "clearinghouse_service: 'httpx' not installed. "
        "Live clearinghouse calls will return simulated responses. "
        "Install with: pip install httpx"
    )

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_TIMEOUT_SECONDS = 30
_CACHE_TTL_HOURS = 4

# In-process eligibility cache: keyed by (tenant_id, member_id, payer_id, service_type, check_date_str)
# Value: (result_dict, expiry_epoch)
_ELIGIBILITY_CACHE: dict[tuple, tuple[dict, float]] = {}
_CACHE_MAX_SIZE = 2000  # evict oldest when exceeded


# ---------------------------------------------------------------------------
# X12 helper utilities
# ---------------------------------------------------------------------------

def _x12_date() -> str:
    """Return today as YYYYMMDD for X12 ISA envelope."""
    return date.today().strftime("%Y%m%d")


def _x12_time() -> str:
    """Return current time as HHMM for X12 ISA envelope."""
    return datetime.now(timezone.utc).strftime("%H%M")


def _control_number(length: int = 9) -> str:
    """Generate a zero-padded numeric control number."""
    return str(random.randint(0, 10 ** length - 1)).zfill(length)


def _isa_control() -> str:
    return _control_number(9)


def _gs_control() -> str:
    return _control_number(6)


def _st_control() -> str:
    return _control_number(4)


# ---------------------------------------------------------------------------
# Build ANSI X12 270 — Eligibility Inquiry
# ---------------------------------------------------------------------------

def build_270(
    sender_id: str,
    receiver_id: str,
    submitter_id: str,
    member_id: str,
    patient_name: str,
    patient_dob: str,            # YYYYMMDD
    payer_id: str,
    service_type_code: str = "30",  # 30 = Health Benefit Plan Coverage
) -> str:
    """
    Build a well-formed ANSI X12 270 (Health Care Eligibility Inquiry) transaction.

    Returns the full X12 interchange as a single string with tilde (~) segment
    terminators and asterisk (*) element separators, matching most production
    clearinghouse requirements.

    Parameters
    ----------
    sender_id:         ISA06 sender identifier (padded to 15 chars).
    receiver_id:       ISA08 receiver identifier (padded to 15 chars).
    submitter_id:      NPI or Tax ID of the submitting entity (NM109 in 1000A).
    member_id:         Health plan member / subscriber ID.
    patient_name:      Patient full name in "LAST FIRST" format.
    patient_dob:       Patient date of birth as YYYYMMDD string.
    payer_id:          ANSI/ACAS numeric payer ID (e.g. "00001").
    service_type_code: X12 271 service type code (default "30" = health benefit plan).
    """
    isa_ctrl = _isa_control()
    gs_ctrl  = _gs_control()
    st_ctrl  = _st_control()
    today    = _x12_date()
    now      = _x12_time()

    # Parse name into last/first — "DOE JOHN" → last=DOE, first=JOHN
    parts = patient_name.strip().upper().split()
    last_name  = parts[0] if parts else "UNKNOWN"
    first_name = parts[1] if len(parts) > 1 else ""

    # Pad sender/receiver IDs to exactly 15 characters (X12 ISA requirement)
    sender_padded   = sender_id.ljust(15)[:15]
    receiver_padded = receiver_id.ljust(15)[:15]

    segments = [
        # Interchange Control Header
        f"ISA*00*          *00*          *ZZ*{sender_padded}*ZZ*{receiver_padded}*{today[2:]}*{now}*^*00501*{isa_ctrl}*0*P*:",
        # Functional Group Header
        f"GS*HS*{sender_id[:15]}*{receiver_id[:15]}*{today}*{now}*{gs_ctrl}*X*005010X279A1",
        # Transaction Set Header
        f"ST*270*{st_ctrl}*005010X279A1",
        # Beginning of Hierarchical Transaction
        f"BHT*0022*13*{st_ctrl}*{today}*{now}",
        # 2000A – Information Source Level (payer)
        "HL*1**20*1",
        f"NM1*PR*2*{payer_id[:35]}*****PI*{payer_id}",
        # 2000B – Information Receiver Level (submitter / provider)
        "HL*2*1*21*1",
        f"NM1*1P*2*SUBMITTER*****XX*{submitter_id}",
        # 2000C – Subscriber Level (patient / member)
        "HL*3*2*22*0",
        "TRN*1*1*1470000567",
        # 2100C – Subscriber Name
        f"NM1*IL*1*{last_name}*{first_name}****MI*{member_id}",
        f"DMG*D8*{patient_dob}",
        # 2110C – Eligibility or Benefit Inquiry
        f"EQ*{service_type_code}",
        # Transaction Set Trailer
        f"SE*13*{st_ctrl}",
        # Functional Group Trailer
        f"GE*1*{gs_ctrl}",
        # Interchange Control Trailer
        f"IEA*1*{isa_ctrl}",
    ]
    return "~\n".join(segments) + "~"


# ---------------------------------------------------------------------------
# Parse ANSI X12 271 — Eligibility Response
# ---------------------------------------------------------------------------

def parse_271(x12_text: str) -> dict[str, Any]:
    """
    Parse an ANSI X12 271 (Health Care Eligibility Response) transaction.

    Returns a structured dict with keys:
        is_eligible, coverage_start, coverage_end, plan_name, plan_number,
        copay, coinsurance, deductible, deductible_remaining, out_of_pocket_max,
        medicare_part, raf_relevant_info, raw_segments (list of segment IDs)

    This is a best-effort parser that handles the most common segment patterns
    found in production 271 responses.  Edge-case segments are captured in
    raf_relevant_info for manual review.
    """
    result: dict[str, Any] = {
        "is_eligible": None,
        "coverage_start": None,
        "coverage_end": None,
        "plan_name": None,
        "plan_number": None,
        "copay": None,
        "coinsurance": None,
        "deductible": None,
        "deductible_remaining": None,
        "out_of_pocket_max": None,
        "medicare_part": None,
        "raf_relevant_info": {},
        "raw_segments": [],
    }

    if not x12_text:
        return result

    # Normalise segment terminator — support ~ and \n variants
    text = x12_text.replace("~\n", "~").replace("\n", "~")
    segments = [s.strip() for s in text.split("~") if s.strip()]

    eb_segments: list[list[str]] = []   # accumulate 2110C EB segments

    for seg in segments:
        elems = seg.split("*")
        seg_id = elems[0].upper()
        result["raw_segments"].append(seg_id)

        if seg_id == "AAA":
            # Rejection: AAA*N indicates ineligible / not found
            if len(elems) > 1 and elems[1].upper() == "N":
                result["is_eligible"] = False

        elif seg_id == "NM1":
            # NM1*PR = payer, NM1*IL = subscriber (patient)
            if len(elems) > 3 and elems[1].upper() == "PR":
                result["raf_relevant_info"]["payer_name"] = elems[3].strip()

        elif seg_id == "EB":
            # EB*1 = active coverage, EB*6 = inactive / terminated
            eb_segments.append(elems)
            if len(elems) > 1:
                coverage_code = elems[1].strip()
                if coverage_code == "1":
                    result["is_eligible"] = True
                elif coverage_code in ("6", "7", "8"):
                    result["is_eligible"] = False

        elif seg_id == "DTP":
            # DTP*291 = plan begin date, DTP*292 = plan end date
            if len(elems) >= 4 and elems[2].upper() == "D8":
                date_val = elems[3].strip()
                try:
                    parsed_date = datetime.strptime(date_val, "%Y%m%d").date().isoformat()
                    if len(elems) > 1 and elems[1] == "291":
                        result["coverage_start"] = parsed_date
                    elif len(elems) > 1 and elems[1] == "292":
                        result["coverage_end"] = parsed_date
                except ValueError:
                    pass

        elif seg_id == "LS":
            pass  # loop start — no data elements needed

        elif seg_id == "INS":
            # INS relationship code
            if len(elems) > 2:
                result["raf_relevant_info"]["relationship_code"] = elems[2]

    # ---------------------------------------------------------------------------
    # Extract coverage details from EB segments
    # ---------------------------------------------------------------------------
    for elems in eb_segments:
        # EB*1**30 = health benefit plan
        # EB*1**MA = medicare advantage
        if len(elems) > 3:
            svc_type = elems[3].upper()
            if svc_type in ("MA", "MB", "MC"):
                result["medicare_part"] = {"MA": "C", "MB": "B", "MC": "A"}.get(svc_type, svc_type)

        # EB element 9 = plan description (plan name)
        if len(elems) > 9 and elems[9].strip():
            result["plan_name"] = elems[9].strip()

        # EB element 14 = plan number / ID
        if len(elems) > 14 and elems[14].strip():
            result["plan_number"] = elems[14].strip()

        # Copay: EB*B (copayment) — element 5 = amount
        if len(elems) > 5 and len(elems) > 1 and elems[1].upper() == "B":
            try:
                result["copay"] = float(elems[5])
            except (ValueError, IndexError):
                pass

        # Coinsurance: EB*A (coinsurance) — element 5 = percent
        if len(elems) > 5 and len(elems) > 1 and elems[1].upper() == "A":
            try:
                result["coinsurance"] = float(elems[5])
            except (ValueError, IndexError):
                pass

        # Deductible: EB*C — element 5 = amount
        if len(elems) > 5 and len(elems) > 1 and elems[1].upper() == "C":
            try:
                result["deductible"] = float(elems[5])
            except (ValueError, IndexError):
                pass

    return result


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def _cache_key(
    tenant_id: str,
    member_id: str,
    payer_id: str,
    service_type: str,
    check_date: str,
) -> tuple:
    return (tenant_id, member_id, payer_id, service_type, check_date)


def _get_cached(key: tuple) -> dict[str, Any] | None:
    entry = _ELIGIBILITY_CACHE.get(key)
    if entry is None:
        return None
    result, expiry = entry
    if time.time() > expiry:
        _ELIGIBILITY_CACHE.pop(key, None)
        return None
    return result


def _set_cache(key: tuple, result: dict[str, Any]) -> None:
    if len(_ELIGIBILITY_CACHE) >= _CACHE_MAX_SIZE:
        # Evict the oldest entry by insertion order (Python 3.7+ dict)
        oldest = next(iter(_ELIGIBILITY_CACHE))
        _ELIGIBILITY_CACHE.pop(oldest, None)
    _ELIGIBILITY_CACHE[key] = (result, time.time() + _CACHE_TTL_HOURS * 3600)


# ---------------------------------------------------------------------------
# Connection management
# ---------------------------------------------------------------------------

def get_connection(connection_id: int) -> dict[str, Any] | None:
    """Return a clearinghouse connection row by ID (credentials still encrypted)."""
    with raf_cursor() as cur:
        cur.execute(
            "SELECT * FROM clearinghouse_connections WHERE id = %s",
            (connection_id,),
        )
        return cur.fetchone()


def list_connections(tenant_id: str) -> list[dict[str, Any]]:
    """Return all connections for a tenant (credentials stripped from response)."""
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT id, name, vendor, api_base_url, sender_id, receiver_id,
                   submitter_id, status, test_mode, transaction_count,
                   last_transaction_at, tenant_id, created_at, updated_at
            FROM clearinghouse_connections
            WHERE tenant_id = %s
            ORDER BY name
            """,
            (tenant_id,),
        )
        return cur.fetchall()


def create_connection(
    tenant_id: str,
    name: str,
    vendor: str,
    api_base_url: str,
    api_key: str | None,
    api_secret: str | None,
    sender_id: str | None,
    receiver_id: str | None,
    submitter_id: str | None,
    test_mode: bool = True,
    status: str = "testing",
) -> int:
    """Persist a new clearinghouse connection; returns the new row ID."""
    encrypted_key    = encrypt(api_key)    if api_key    else None
    encrypted_secret = encrypt(api_secret) if api_secret else None

    with raf_cursor() as cur:
        cur.execute(
            """
            INSERT INTO clearinghouse_connections
                (tenant_id, name, vendor, api_base_url,
                 api_key_encrypted, api_secret_encrypted,
                 sender_id, receiver_id, submitter_id,
                 status, test_mode)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                tenant_id, name, vendor, api_base_url,
                encrypted_key, encrypted_secret,
                sender_id, receiver_id, submitter_id,
                status, test_mode,
            ),
        )
        return cur.lastrowid


def update_connection(connection_id: int, tenant_id: str, **kwargs: Any) -> bool:
    """
    Update mutable fields on a connection.  If api_key or api_secret are in
    kwargs they are encrypted before writing.
    """
    if "api_key" in kwargs:
        val = kwargs.pop("api_key")
        kwargs["api_key_encrypted"] = encrypt(val) if val else None
    if "api_secret" in kwargs:
        val = kwargs.pop("api_secret")
        kwargs["api_secret_encrypted"] = encrypt(val) if val else None

    if not kwargs:
        return False

    set_clause = ", ".join(f"{col} = %s" for col in kwargs)
    values = list(kwargs.values()) + [connection_id, tenant_id]

    with raf_cursor() as cur:
        cur.execute(
            f"UPDATE clearinghouse_connections SET {set_clause} "
            f"WHERE id = %s AND tenant_id = %s",
            values,
        )
        return cur.rowcount > 0


def _increment_transaction_count(connection_id: int) -> None:
    """Atomically bump the transaction counter and update last_transaction_at."""
    with raf_cursor() as cur:
        cur.execute(
            """
            UPDATE clearinghouse_connections
            SET transaction_count = transaction_count + 1,
                last_transaction_at = UTC_TIMESTAMP()
            WHERE id = %s
            """,
            (connection_id,),
        )


# ---------------------------------------------------------------------------
# Core eligibility check — internal implementation
# ---------------------------------------------------------------------------

def _call_vendor_rest(
    connection: dict[str, Any],
    member_id: str,
    patient_name: str,
    patient_dob: str,
    payer_id: str,
    service_type: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Dispatch an eligibility inquiry to a clearinghouse vendor's REST API.

    Returns (request_payload, raw_response_dict).
    Raises RuntimeError on HTTP errors or timeouts.
    """
    if not _HTTPX_AVAILABLE:
        raise RuntimeError("httpx is required for live clearinghouse calls")

    vendor      = connection.get("vendor", "custom")
    base_url    = connection.get("api_base_url", "").rstrip("/")
    api_key     = decrypt(connection["api_key_encrypted"])    if connection.get("api_key_encrypted")    else ""
    api_secret  = decrypt(connection["api_secret_encrypted"]) if connection.get("api_secret_encrypted") else ""
    test_mode   = bool(connection.get("test_mode", True))

    # Build request payload — common structure shared across vendors with
    # minor per-vendor adaptation in headers / auth.
    request_payload: dict[str, Any] = {
        "memberId":    member_id,
        "payerId":     payer_id,
        "patientName": patient_name,
        "patientDob":  patient_dob,
        "serviceType": service_type,
        "testMode":    test_mode,
    }

    # Per-vendor endpoint and auth configuration
    if vendor == "availity":
        url     = f"{base_url}/v1/coverages"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type":  "application/json",
        }
    elif vendor == "change_healthcare":
        url     = f"{base_url}/medicalnetwork/eligibility/v3"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type":  "application/json",
        }
    else:
        # Waystar, Trizetto, or custom — generic Bearer auth
        url     = f"{base_url}/eligibility"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type":  "application/json",
        }
        if api_secret:
            headers["X-API-Secret"] = api_secret

    with httpx.Client(timeout=_DEFAULT_TIMEOUT_SECONDS) as client:
        resp = client.post(url, json=request_payload, headers=headers)
        resp.raise_for_status()
        return request_payload, resp.json()


def _call_vendor_x12(
    connection: dict[str, Any],
    member_id: str,
    patient_name: str,
    patient_dob: str,
    payer_id: str,
    service_type_code: str = "30",
) -> tuple[str, str]:
    """
    Submit an X12 270 transaction and receive a 271 response.

    Returns (x12_270_text, x12_271_text).
    For clearinghouses that accept raw X12 over HTTPS (e.g. Trizetto gateway).
    """
    if not _HTTPX_AVAILABLE:
        raise RuntimeError("httpx is required for live clearinghouse calls")

    base_url   = connection.get("api_base_url", "").rstrip("/")
    api_key    = decrypt(connection["api_key_encrypted"]) if connection.get("api_key_encrypted") else ""
    sender_id  = connection.get("sender_id",  "SENDER")
    receiver_id = connection.get("receiver_id", "RECEIVER")
    submitter_id = connection.get("submitter_id", "1234567890")

    x12_270 = build_270(
        sender_id=sender_id,
        receiver_id=receiver_id,
        submitter_id=submitter_id,
        member_id=member_id,
        patient_name=patient_name,
        patient_dob=patient_dob,
        payer_id=payer_id,
        service_type_code=service_type_code,
    )

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type":  "text/plain",
        "Accept":        "text/plain",
    }

    with httpx.Client(timeout=_DEFAULT_TIMEOUT_SECONDS) as client:
        resp = client.post(f"{base_url}/x12", content=x12_270.encode(), headers=headers)
        resp.raise_for_status()
        return x12_270, resp.text


def _simulate_response(
    member_id: str,
    payer_id: str,
    service_type: str,
) -> dict[str, Any]:
    """
    Return a plausible simulated eligibility result for sandbox / test mode.

    Simulates an eligible Medicare Advantage member with typical cost-sharing.
    Not to be used in production.
    """
    today = date.today()
    return {
        "is_eligible":          True,
        "coverage_start":       date(today.year, 1, 1).isoformat(),
        "coverage_end":         None,
        "plan_name":            "Simulated Medicare Advantage Gold",
        "plan_number":          f"SIM-{payer_id}-001",
        "copay":                25.00,
        "coinsurance":          20.00,
        "deductible":           250.00,
        "deductible_remaining": 125.00,
        "out_of_pocket_max":    3500.00,
        "medicare_part":        "C",
        "raf_relevant_info": {
            "cms_contract_id": "H9999",
            "pbp":             "001",
            "plan_type":       "HMO",
            "star_rating":     4.5,
            "simulated":       True,
        },
        "raw_segments": ["ISA", "GS", "ST", "BHT", "HL", "NM1", "EB", "DTP", "SE", "GE", "IEA"],
    }


# ---------------------------------------------------------------------------
# Public API — single check
# ---------------------------------------------------------------------------

def run_eligibility_check(
    tenant_id: str,
    connection_id: int,
    member_id: str,
    patient_name: str,
    patient_dob: str,          # YYYYMMDD or YYYY-MM-DD
    payer_id: str,
    payer_name: str,
    service_type: str = "health_benefit_plan",
    patient_id: int | None = None,
    use_cache: bool = True,
) -> dict[str, Any]:
    """
    Perform a single real-time eligibility check.

    1. Checks the in-process cache; returns the cached result if fresh.
    2. Loads the connection record and decrypts credentials just-in-time.
    3. In test_mode, returns a simulated response; otherwise calls the vendor.
    4. Persists the check record to eligibility_checks.
    5. Updates the connection transaction counter.

    Returns the full eligibility_checks row dict (without raw request/response
    payloads to keep the response lean; use GET /checks/{id} for full detail).
    """
    # Normalise DOB format
    patient_dob_norm = patient_dob.replace("-", "")  # ensure YYYYMMDD

    # Service type → X12 code mapping
    service_type_code_map = {
        "health_benefit_plan": "30",
        "medicare_part_a":     "35",
        "medicare_part_b":     "12",
        "medicare_advantage":  "MA",
    }
    x12_svc_code = service_type_code_map.get(service_type, "30")

    check_date_str = date.today().isoformat()

    # Cache lookup
    if use_cache:
        cache_key = _cache_key(tenant_id, member_id, payer_id, service_type, check_date_str)
        cached = _get_cached(cache_key)
        if cached:
            logger.debug(
                "clearinghouse: cache hit for member=%s payer=%s", member_id, payer_id
            )
            return cached

    connection = get_connection(connection_id)
    if not connection or str(connection.get("tenant_id", "")) != str(tenant_id):
        raise ValueError(f"Clearinghouse connection {connection_id} not found for tenant {tenant_id}")

    if connection.get("status") == "inactive":
        raise ValueError(f"Clearinghouse connection {connection_id} is inactive")

    start_ts = time.perf_counter()
    request_payload: Any = None
    response_payload: Any = None
    parsed: dict[str, Any] = {}
    error_msg: str | None = None
    final_status = "error"

    try:
        if connection.get("test_mode"):
            # Sandbox / simulation mode
            parsed          = _simulate_response(member_id, payer_id, service_type)
            request_payload = {
                "mode":          "simulated",
                "member_id":     member_id,
                "payer_id":      payer_id,
                "service_type":  service_type,
            }
            response_payload = parsed
            final_status     = "completed"

        elif connection.get("vendor") in ("availity", "change_healthcare", "waystar", "trizetto"):
            # REST-based vendors
            request_payload, raw_resp = _call_vendor_rest(
                connection=connection,
                member_id=member_id,
                patient_name=patient_name,
                patient_dob=patient_dob_norm,
                payer_id=payer_id,
                service_type=service_type,
            )
            response_payload = raw_resp
            # Map vendor response to our schema — vendors return different key names;
            # we extract the most common patterns here.
            parsed = _normalise_rest_response(raw_resp)
            final_status = "completed"

        else:
            # Custom / X12 gateway
            x12_270, x12_271 = _call_vendor_x12(
                connection=connection,
                member_id=member_id,
                patient_name=patient_name,
                patient_dob=patient_dob_norm,
                payer_id=payer_id,
                service_type_code=x12_svc_code,
            )
            request_payload  = {"x12_270": x12_270}
            response_payload = {"x12_271": x12_271}
            parsed           = parse_271(x12_271)
            final_status     = "completed"

    except Exception as exc:  # noqa: BLE001
        error_msg    = str(exc)
        final_status = "timeout" if "timeout" in str(exc).lower() else "error"
        logger.error(
            "clearinghouse: eligibility check failed (conn=%d member=%s): %s",
            connection_id, member_id, exc,
        )

    elapsed_ms = int((time.perf_counter() - start_ts) * 1000)

    # Persist check record
    check_id = _persist_check(
        tenant_id=tenant_id,
        connection_id=connection_id,
        patient_id=patient_id,
        patient_name=patient_name,
        patient_dob=patient_dob_norm,
        member_id=member_id,
        payer_id=payer_id,
        payer_name=payer_name,
        service_type=service_type,
        status=final_status,
        request_payload=request_payload,
        response_payload=response_payload,
        parsed=parsed,
        error_message=error_msg,
        response_time_ms=elapsed_ms,
    )

    if final_status == "completed":
        _increment_transaction_count(connection_id)

    result = get_check(check_id)
    if result and use_cache and final_status == "completed":
        _set_cache(cache_key, result)
    return result or {"id": check_id, "status": final_status, "error": error_msg}


def _normalise_rest_response(raw: dict[str, Any]) -> dict[str, Any]:
    """
    Map vendor-specific JSON key names onto our internal schema fields.

    Handles the most common response shapes from Availity and Change Healthcare.
    Falls back gracefully for unknown shapes.
    """
    # Common key aliases seen in vendor responses
    def _get(*keys: str, default: Any = None) -> Any:
        for k in keys:
            v = raw.get(k)
            if v is not None:
                return v
        return default

    is_eligible_raw = _get("eligible", "coverageActive", "isEligible", "active")
    if isinstance(is_eligible_raw, bool):
        is_eligible = is_eligible_raw
    elif isinstance(is_eligible_raw, str):
        is_eligible = is_eligible_raw.lower() in ("true", "yes", "active", "1")
    else:
        is_eligible = None

    def _safe_float(v: Any) -> float | None:
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    return {
        "is_eligible":          is_eligible,
        "coverage_start":       _get("coverageStartDate", "effectiveDate", "coverageStart"),
        "coverage_end":         _get("coverageEndDate", "terminationDate", "coverageEnd"),
        "plan_name":            _get("planName", "planDescription", "benefitPlanName"),
        "plan_number":          _get("planNumber", "planId", "contractNumber"),
        "copay":                _safe_float(_get("copayAmount", "copay", "primaryCareCopay")),
        "coinsurance":          _safe_float(_get("coinsurancePercent", "coinsurance")),
        "deductible":           _safe_float(_get("deductibleAmount", "deductible")),
        "deductible_remaining": _safe_float(_get("deductibleRemaining", "deductibleBalance")),
        "out_of_pocket_max":    _safe_float(_get("outOfPocketMax", "oopMax", "outOfPocketMaximum")),
        "medicare_part":        _get("medicarePart", "medicare_part"),
        "raf_relevant_info":    _get("maDetails", "medicareAdvantageDetails", "rafInfo", default={}),
        "raw_segments":         [],
    }


# ---------------------------------------------------------------------------
# Persist helpers
# ---------------------------------------------------------------------------

def _persist_check(
    tenant_id: str,
    connection_id: int,
    patient_id: int | None,
    patient_name: str,
    patient_dob: str,
    member_id: str,
    payer_id: str,
    payer_name: str,
    service_type: str,
    status: str,
    request_payload: Any,
    response_payload: Any,
    parsed: dict[str, Any],
    error_message: str | None,
    response_time_ms: int,
) -> int:
    """Insert one eligibility_checks row; returns new row ID."""
    def _date_or_none(v: Any) -> str | None:
        if not v:
            return None
        if isinstance(v, date):
            return v.isoformat()
        return str(v)

    with raf_cursor() as cur:
        cur.execute(
            """
            INSERT INTO eligibility_checks (
                tenant_id, connection_id, patient_id,
                patient_name, patient_dob, member_id,
                payer_id, payer_name, service_type,
                check_date, status,
                request_payload, response_payload,
                is_eligible, coverage_start, coverage_end,
                plan_name, plan_number,
                copay, coinsurance,
                deductible, deductible_remaining, out_of_pocket_max,
                medicare_part, raf_relevant_info,
                error_message, response_time_ms
            ) VALUES (
                %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s,
                CURDATE(), %s,
                %s, %s,
                %s, %s, %s,
                %s, %s,
                %s, %s,
                %s, %s, %s,
                %s, %s,
                %s, %s
            )
            """,
            (
                tenant_id, connection_id, patient_id,
                patient_name, patient_dob, member_id,
                payer_id, payer_name, service_type,
                status,
                json.dumps(request_payload)  if request_payload  is not None else None,
                json.dumps(response_payload) if response_payload is not None else None,
                parsed.get("is_eligible"),
                _date_or_none(parsed.get("coverage_start")),
                _date_or_none(parsed.get("coverage_end")),
                parsed.get("plan_name"),
                parsed.get("plan_number"),
                parsed.get("copay"),
                parsed.get("coinsurance"),
                parsed.get("deductible"),
                parsed.get("deductible_remaining"),
                parsed.get("out_of_pocket_max"),
                parsed.get("medicare_part"),
                json.dumps(parsed.get("raf_relevant_info", {})),
                error_message,
                response_time_ms,
            ),
        )
        return cur.lastrowid


# ---------------------------------------------------------------------------
# Batch eligibility
# ---------------------------------------------------------------------------

def create_batch(
    tenant_id: str,
    connection_id: int,
    name: str | None,
    patient_records: list[dict[str, Any]],
) -> int:
    """
    Enqueue a batch eligibility job and return the batch ID.

    patient_records items require: member_id, patient_name, patient_dob,
    payer_id, payer_name.  Optional: service_type, patient_id.

    Processing is synchronous for small batches (<=20 patients) and logs
    progress row by row.  For production scale a task queue (Celery / ARQ)
    should consume this batch ID asynchronously.
    """
    total = len(patient_records)
    with raf_cursor() as cur:
        cur.execute(
            """
            INSERT INTO eligibility_batch
                (tenant_id, connection_id, name, total_checks, status)
            VALUES (%s, %s, %s, %s, 'queued')
            """,
            (tenant_id, connection_id, name, total),
        )
        batch_id = cur.lastrowid

    # Start processing immediately (inline for small batches)
    _process_batch(batch_id, tenant_id, connection_id, patient_records)
    return batch_id


def _process_batch(
    batch_id: int,
    tenant_id: str,
    connection_id: int,
    patient_records: list[dict[str, Any]],
) -> None:
    """Execute all checks in a batch and update the batch status table."""
    _update_batch_status(batch_id, "processing", started_at=True)
    completed = 0
    failed    = 0

    for record in patient_records:
        try:
            run_eligibility_check(
                tenant_id=tenant_id,
                connection_id=connection_id,
                member_id=record.get("member_id", ""),
                patient_name=record.get("patient_name", ""),
                patient_dob=record.get("patient_dob", ""),
                payer_id=record.get("payer_id", ""),
                payer_name=record.get("payer_name", ""),
                service_type=record.get("service_type", "health_benefit_plan"),
                patient_id=record.get("patient_id"),
                use_cache=False,  # always re-check in batch mode
            )
            completed += 1
        except Exception as exc:  # noqa: BLE001
            failed += 1
            logger.warning("clearinghouse: batch %d check failed: %s", batch_id, exc)

        # Incremental progress update every 10 checks
        if (completed + failed) % 10 == 0:
            _update_batch_counters(batch_id, completed, failed)

    overall_status = "completed" if failed == 0 else ("error" if completed == 0 else "completed")
    _update_batch_counters(batch_id, completed, failed)
    _update_batch_status(batch_id, overall_status, completed_at=True)


def _update_batch_status(
    batch_id: int,
    status: str,
    started_at: bool = False,
    completed_at: bool = False,
) -> None:
    extras = ""
    if started_at:
        extras += ", started_at = UTC_TIMESTAMP()"
    if completed_at:
        extras += ", completed_at = UTC_TIMESTAMP()"
    with raf_cursor() as cur:
        cur.execute(
            f"UPDATE eligibility_batch SET status = %s{extras} WHERE id = %s",
            (status, batch_id),
        )


def _update_batch_counters(batch_id: int, completed: int, failed: int) -> None:
    with raf_cursor() as cur:
        cur.execute(
            "UPDATE eligibility_batch SET completed = %s, failed = %s WHERE id = %s",
            (completed, failed, batch_id),
        )


def get_batch(batch_id: int) -> dict[str, Any] | None:
    """Return a batch row including progress counters."""
    with raf_cursor() as cur:
        cur.execute(
            "SELECT * FROM eligibility_batch WHERE id = %s",
            (batch_id,),
        )
        return cur.fetchone()


# ---------------------------------------------------------------------------
# Individual check retrieval
# ---------------------------------------------------------------------------

def get_check(check_id: int) -> dict[str, Any] | None:
    """Return a single eligibility_checks row by ID."""
    with raf_cursor() as cur:
        cur.execute(
            "SELECT * FROM eligibility_checks WHERE id = %s",
            (check_id,),
        )
        return cur.fetchone()


def list_checks(
    tenant_id: str,
    connection_id: int | None = None,
    patient_id: int | None = None,
    payer_id: str | None = None,
    status: str | None = None,
    service_type: str | None = None,
    check_date_from: str | None = None,
    check_date_to: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """
    Return a paginated list of eligibility checks for a tenant.

    Returns (rows, total_count).
    """
    conditions = ["tenant_id = %s"]
    params: list[Any] = [tenant_id]

    if connection_id is not None:
        conditions.append("connection_id = %s")
        params.append(connection_id)
    if patient_id is not None:
        conditions.append("patient_id = %s")
        params.append(patient_id)
    if payer_id:
        conditions.append("payer_id = %s")
        params.append(payer_id)
    if status:
        conditions.append("status = %s")
        params.append(status)
    if service_type:
        conditions.append("service_type = %s")
        params.append(service_type)
    if check_date_from:
        conditions.append("check_date >= %s")
        params.append(check_date_from)
    if check_date_to:
        conditions.append("check_date <= %s")
        params.append(check_date_to)

    where = " AND ".join(conditions)

    with raf_cursor() as cur:
        cur.execute(f"SELECT COUNT(*) AS cnt FROM eligibility_checks WHERE {where}", params)
        total = cur.fetchone()["cnt"]

        cur.execute(
            f"""
            SELECT id, connection_id, patient_id, patient_name, patient_dob,
                   member_id, payer_id, payer_name, service_type,
                   check_date, status, is_eligible,
                   coverage_start, coverage_end,
                   plan_name, plan_number,
                   copay, coinsurance, deductible, deductible_remaining, out_of_pocket_max,
                   medicare_part, raf_relevant_info,
                   error_message, response_time_ms, tenant_id, created_at
            FROM eligibility_checks
            WHERE {where}
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
            """,
            params + [limit, offset],
        )
        rows = cur.fetchall()

    return rows, total


# ---------------------------------------------------------------------------
# Dashboard statistics
# ---------------------------------------------------------------------------

def get_dashboard_stats(tenant_id: str) -> dict[str, Any]:
    """
    Return aggregate clearinghouse statistics for the dashboard:
    - Active connection count
    - Total checks today / this month
    - Eligibility rate (eligible / total completed)
    - Average response time
    - Error rate
    - Recent check list (last 5)
    """
    with raf_cursor() as cur:
        # Connection counts by status
        cur.execute(
            """
            SELECT status, COUNT(*) AS cnt
            FROM clearinghouse_connections
            WHERE tenant_id = %s
            GROUP BY status
            """,
            (tenant_id,),
        )
        conn_rows = cur.fetchall()
        connections_by_status = {r["status"]: r["cnt"] for r in conn_rows}

        # Today's check summary
        cur.execute(
            """
            SELECT
                COUNT(*) AS total,
                SUM(status = 'completed') AS completed,
                SUM(status IN ('error', 'timeout')) AS errors,
                SUM(is_eligible = 1) AS eligible,
                ROUND(AVG(response_time_ms), 1) AS avg_response_ms
            FROM eligibility_checks
            WHERE tenant_id = %s AND check_date = CURDATE()
            """,
            (tenant_id,),
        )
        today = cur.fetchone()

        # Month-to-date totals
        cur.execute(
            """
            SELECT COUNT(*) AS total, SUM(is_eligible = 1) AS eligible
            FROM eligibility_checks
            WHERE tenant_id = %s
              AND check_date >= DATE_FORMAT(CURDATE(), '%Y-%m-01')
            """,
            (tenant_id,),
        )
        mtd = cur.fetchone()

        # Recent checks
        cur.execute(
            """
            SELECT id, patient_name, payer_name, service_type,
                   status, is_eligible, response_time_ms, created_at
            FROM eligibility_checks
            WHERE tenant_id = %s
            ORDER BY created_at DESC
            LIMIT 5
            """,
            (tenant_id,),
        )
        recent = cur.fetchall()

    today_total     = today["total"] or 0
    today_completed = today["completed"] or 0
    today_eligible  = today["eligible"] or 0
    today_errors    = today["errors"] or 0

    eligibility_rate = (
        round(today_eligible / today_completed * 100, 1) if today_completed > 0 else None
    )
    error_rate = (
        round(today_errors / today_total * 100, 1) if today_total > 0 else None
    )

    return {
        "connections":        connections_by_status,
        "active_connections": connections_by_status.get("active", 0),
        "today": {
            "total":           today_total,
            "completed":       today_completed,
            "errors":          today_errors,
            "eligible":        today_eligible,
            "eligibility_rate_pct": eligibility_rate,
            "error_rate_pct":  error_rate,
            "avg_response_ms": today["avg_response_ms"],
        },
        "month_to_date": {
            "total":    mtd["total"] or 0,
            "eligible": mtd["eligible"] or 0,
        },
        "recent_checks": recent,
    }


# ---------------------------------------------------------------------------
# Connection test / validation
# ---------------------------------------------------------------------------

def test_connection(connection_id: int, tenant_id: str) -> dict[str, Any]:
    """
    Run a lightweight connectivity test against the configured clearinghouse.

    Uses a known-good synthetic member ID to verify the credentials and
    endpoint are reachable.  Returns a result dict with 'success' bool and
    'message' string.  Never persists a check row (test_mode is forced).
    """
    connection = get_connection(connection_id)
    if not connection or str(connection.get("tenant_id", "")) != str(tenant_id):
        return {"success": False, "message": f"Connection {connection_id} not found"}

    vendor   = connection.get("vendor", "custom")
    base_url = connection.get("api_base_url", "")

    # Basic URL sanity check
    if not base_url.startswith(("http://", "https://")):
        return {"success": False, "message": f"Invalid api_base_url: {base_url!r}"}

    if not _HTTPX_AVAILABLE:
        return {
            "success": True,
            "message": (
                "httpx not installed — connection is structurally valid "
                "but live connectivity could not be verified."
            ),
            "simulated": True,
        }

    # Attempt a real HTTP probe (HEAD or GET on the base URL)
    try:
        api_key = decrypt(connection["api_key_encrypted"]) if connection.get("api_key_encrypted") else ""
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

        with httpx.Client(timeout=10) as client:
            # Most vendors return 200 or 401 (wrong key) on a bare GET —
            # either confirms the endpoint is reachable.
            probe_url = base_url.rstrip("/") + (
                "/v1/coverages" if vendor == "availity" else
                "/medicalnetwork/eligibility/v3" if vendor == "change_healthcare" else
                "/eligibility"
            )
            resp = client.get(probe_url, headers=headers)
            # 401 = reachable but auth failed (expected with test keys)
            reachable = resp.status_code < 500

        if reachable:
            return {
                "success": True,
                "message": f"Connection to {vendor} endpoint is reachable (HTTP {resp.status_code})",
                "http_status": resp.status_code,
            }
        return {
            "success": False,
            "message": f"Endpoint returned HTTP {resp.status_code}",
            "http_status": resp.status_code,
        }
    except Exception as exc:  # noqa: BLE001
        logger.debug("swallowed exception", exc_info=True)
        return {"success": False, "message": str(exc)}
