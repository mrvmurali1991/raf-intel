"""
FHIR-based Problem List write-back.

Gap #4 from COMPETITIVE-GAP-ANALYSIS.md: push accepted suspect HCC codes
back to the EHR via the standard FHIR R4 ``Condition`` endpoint so the
write-back path also works for Epic, Cerner, Athena, etc.

The active OpenEMR connection's OAuth2 token is obtained via the
existing ``OpenEMRFhirAdapter`` so credentials are never duplicated.
If the FHIR POST fails the caller may fall back to the legacy
``openemr_connector.push_medical_problem`` direct-MySQL path.

After a successful POST we run a reconcile step that GETs
``/Condition?subject=Patient/{emr_pid}`` and confirms the ICD-10 code
is present in the returned Bundle, emitting
``SUSPECT_FHIR_RECONCILE_MISMATCH`` when it is not.

Custom RAF Intelligence extension url used on the Condition extension:
``https://raf-intelligence.health/fhir/StructureDefinition/suspect-id``
"""
from __future__ import annotations

import logging
import time
from datetime import date, datetime, timezone
from typing import Any

import httpx
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from app.services.cache_strategy import get_active_connection_id
from app.services.emr_manager import get_connection_with_credentials
from app.services.vendor_adapters.openemr_fhir import OpenEMRFhirAdapter

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ICD10_SYSTEM = "http://hl7.org/fhir/sid/icd-10-cm"
US_CORE_ASSERTED_DATE_URL = (
    "http://hl7.org/fhir/us/core/StructureDefinition/us-core-condition-assertedDate"
)
RAF_SUSPECT_EXT_URL = (
    "https://raf-intelligence.health/fhir/StructureDefinition/suspect-id"
)

CLINICAL_STATUS_SYSTEM = "http://terminology.hl7.org/CodeSystem/condition-clinical"
VERIFICATION_STATUS_SYSTEM = (
    "http://terminology.hl7.org/CodeSystem/condition-ver-status"
)
CATEGORY_SYSTEM = "http://terminology.hl7.org/CodeSystem/condition-category"

import os

_FHIR_TIMEOUT_SECONDS = float(os.getenv("FHIR_TIMEOUT_SECONDS", "5.0"))
_TIMEOUT = httpx.Timeout(_FHIR_TIMEOUT_SECONDS, connect=min(2.0, _FHIR_TIMEOUT_SECONDS))
_BROWSER_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})

# Roles that are considered credentialed for the purposes of "confirmed" status
_CREDENTIALED_ROLES = frozenset({"coder", "admin", "physician"})


def _retryable(exc: BaseException) -> bool:
    if isinstance(exc, (httpx.ConnectError, httpx.ReadTimeout)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _RETRYABLE_STATUS
    return False


_fhir_post_retry = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential_jitter(initial=0.5, max=4),
    retry=retry_if_exception(_retryable),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)


# ---------------------------------------------------------------------------
# MEAT evidence helpers
# ---------------------------------------------------------------------------


def _fetch_meat_notes(suspect_id: int | str) -> list[dict[str, Any]]:
    """Return FHIR note entries built from raf_meat_evidence rows for suspect_id.

    Each note entry: ``{authorString, time, text}``

    Returns an empty list when there is no MEAT evidence or the DB query fails.
    This function never raises — callers must not be blocked by missing MEAT data.
    """
    try:
        from app.db import raf_cursor

        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT meat_m, meat_e, meat_a, meat_t,
                       meat_m_text, meat_e_text, meat_a_text, meat_t_text,
                       created_at, reviewed_by
                FROM   raf_meat_evidence
                WHERE  suspect_id = %s
                ORDER  BY created_at DESC
                LIMIT  1
                """,
                (int(suspect_id),),
            )
            row = cur.fetchone()
    except Exception as exc:
        logger.warning(
            "_fetch_meat_notes: DB query failed for suspect_id=%s: %s",
            suspect_id, exc,
        )
        return []

    if not row:
        return []

    notes: list[dict[str, Any]] = []
    letter_map = [
        ("M", "meat_m", "meat_m_text"),
        ("E", "meat_e", "meat_e_text"),
        ("A", "meat_a", "meat_a_text"),
        ("T", "meat_t", "meat_t_text"),
    ]
    ts = (row.get("created_at") or datetime.now(tz=timezone.utc))
    ts_str = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
    author = row.get("reviewed_by") or "raf_intelligence"

    for letter, flag_col, text_col in letter_map:
        flag = row.get(flag_col)
        text = (row.get(text_col) or "").strip()
        if flag or text:
            label = {"M": "Monitoring", "E": "Evaluation", "A": "Assessment", "T": "Treatment"}[letter]
            body_text = text if text else f"{label} evidence present (no verbatim snippet)"
            notes.append({
                "authorString": author,
                "time": ts_str,
                "text": f"[{letter}] {label}: {body_text}",
            })

    return notes


def _fetch_user_npi(user_id: int | None) -> str | None:
    """Return the NPI string for user_id from users.npi, or None if absent."""
    if user_id is None:
        return None
    try:
        from app.db import raf_cursor

        with raf_cursor() as cur:
            cur.execute("SELECT npi FROM users WHERE id = %s", (user_id,))
            row = cur.fetchone()
        if row:
            npi = (row.get("npi") or "").strip()
            return npi if npi else None
    except Exception as exc:
        logger.warning(
            "_fetch_user_npi: DB query failed for user_id=%s: %s", user_id, exc
        )
    return None


# ---------------------------------------------------------------------------
# Body builder (pure-ish — DB lookups are isolated to helper functions above)
# ---------------------------------------------------------------------------


def build_condition_body(
    patient_emr_pid: str,
    icd10_code: str,
    hcc_label: str,
    *,
    clinical_status: str = "active",
    verification_status: str = "confirmed",
    recorded_date: str | None = None,
    source: dict | None = None,
    # Safety-gate kwargs — default to backward-compatible behaviour
    meat_signed: bool = False,
    force_accepted: bool = False,
    user_role: str | None = None,
    user_npi: str | None = None,
    meat_notes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return the FHIR ``Condition`` resource body as a dict.

    Parameters mirror :func:`push_problem_list_condition` so callers can
    inspect what *would* be posted without hitting the network.

    Safety logic (CMS RADV + Patient Safety review round-2):

    * ``verification_status`` is automatically downgraded to ``"provisional"``
      when MEAT is absent OR the accepting user is not credentialed
      (role not in coder/admin/physician).  Pass ``verification_status``
      explicitly only if you want to override the computed value.

    * ``note[]`` is populated from MEAT evidence sentences when ``meat_notes``
      is provided.  Pull these via :func:`_fetch_meat_notes`.

    * ``evidence[]`` points to the source clinical encounter when
      ``source.source_encounter_id`` is set.

    * ``recorder`` is set to ``Practitioner/{user_npi}`` when ``user_npi``
      is non-null.
    """
    if not recorded_date:
        recorded_date = date.today().isoformat()

    source = source or {}
    suspect_id = source.get("suspect_id")
    source_label = source.get("source") or "raf_intelligence"
    source_encounter_id = source.get("source_encounter_id")

    # ------------------------------------------------------------------
    # Compute verification_status from safety signals (round-2 fix)
    # ------------------------------------------------------------------
    credentialed = (user_role or "").lower() in _CREDENTIALED_ROLES
    if meat_signed and credentialed:
        resolved_verification_status = "confirmed"
    else:
        # NLP-suggested, force-accepted-without-MEAT, or non-credentialed user
        resolved_verification_status = "provisional"

    # Allow callers that explicitly pass a non-default value to keep it
    # (backward-compat for direct callers that set verification_status='active'
    # or similar intentional override).  The default "confirmed" is the only
    # value we replace — it was the unsafe default.
    if verification_status != "confirmed":
        resolved_verification_status = verification_status

    extensions: list[dict[str, Any]] = [
        {
            "url": US_CORE_ASSERTED_DATE_URL,
            "valueDateTime": recorded_date,
        }
    ]
    if suspect_id is not None:
        extensions.append(
            {
                "url": RAF_SUSPECT_EXT_URL,
                "valueString": (
                    f"suspect_id={suspect_id};source={source_label}"
                ),
            }
        )

    body: dict[str, Any] = {
        "resourceType": "Condition",
        "clinicalStatus": {
            "coding": [
                {
                    "system": CLINICAL_STATUS_SYSTEM,
                    "code": clinical_status,
                    "display": clinical_status.title(),
                }
            ]
        },
        "verificationStatus": {
            "coding": [
                {
                    "system": VERIFICATION_STATUS_SYSTEM,
                    "code": resolved_verification_status,
                    "display": resolved_verification_status.replace("-", " ").title(),
                }
            ]
        },
        "category": [
            {
                "coding": [
                    {
                        "system": CATEGORY_SYSTEM,
                        "code": "problem-list-item",
                        "display": "Problem List Item",
                    }
                ]
            }
        ],
        "code": {
            "coding": [
                {
                    "system": ICD10_SYSTEM,
                    "code": icd10_code,
                    "display": hcc_label,
                }
            ],
            "text": hcc_label,
        },
        "subject": {"reference": f"Patient/{patient_emr_pid}"},
        "recordedDate": recorded_date,
        "extension": extensions,
    }

    # ------------------------------------------------------------------
    # note[] — MEAT evidence sentences (RADV audit requirement)
    # ------------------------------------------------------------------
    if meat_notes:
        body["note"] = [
            {
                "authorString": n.get("authorString", "raf_intelligence"),
                "time": n.get("time", recorded_date),
                "text": n.get("text", ""),
            }
            for n in meat_notes
            if n.get("text")
        ]

    # ------------------------------------------------------------------
    # evidence[] — source clinical encounter reference
    # ------------------------------------------------------------------
    if source_encounter_id:
        body["evidence"] = [
            {
                "detail": [
                    {"reference": f"DocumentReference/{source_encounter_id}"}
                ]
            }
        ]

    # ------------------------------------------------------------------
    # recorder — credentialed user's NPI (FHIR R4 Practitioner reference)
    # ------------------------------------------------------------------
    if user_npi:
        body["recorder"] = {"reference": f"Practitioner/{user_npi}"}

    return body


# ---------------------------------------------------------------------------
# Adapter resolution
# ---------------------------------------------------------------------------


def _get_fhir_adapter(tenant_id: str | None = None) -> OpenEMRFhirAdapter:
    """Resolve the active OpenEMR FHIR connection and return its adapter."""
    conn_id = get_active_connection_id(tenant_id)
    if not conn_id:
        raise RuntimeError(
            "No active EMR connection configured — cannot push FHIR Condition."
        )
    connection = get_connection_with_credentials(conn_id, tenant_id=tenant_id)
    if not connection:
        raise RuntimeError(
            f"EMR connection id={conn_id} not found for tenant={tenant_id}."
        )
    adapter = OpenEMRFhirAdapter(connection)
    if not adapter.base_url:
        raise RuntimeError(
            "Active EMR connection has no FHIR base_url — cannot push Condition."
        )
    return adapter


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def push_problem_list_condition(
    patient_emr_pid: str | int,
    icd10_code: str,
    hcc_label: str,
    *,
    clinical_status: str = "active",
    verification_status: str = "confirmed",
    recorded_date: str | None = None,
    source: dict | None = None,
    tenant_id: str | None = None,
    adapter: OpenEMRFhirAdapter | None = None,
    # Safety-gate kwargs
    meat_signed: bool = False,
    force_accepted: bool = False,
    user_role: str | None = None,
    user_id: int | None = None,
) -> str:
    """POST a FHIR ``Condition`` resource for *patient_emr_pid*.

    Returns the FHIR Condition resource ``id`` from the server response.
    Raises ``RuntimeError`` if the write fails after retries (so the caller
    can decide whether to fall back to the legacy MySQL writer).
    """
    if not icd10_code:
        raise ValueError("icd10_code is required")
    if not patient_emr_pid:
        raise ValueError("patient_emr_pid is required")

    if adapter is None:
        adapter = _get_fhir_adapter(tenant_id=tenant_id)

    # Pull MEAT notes and user NPI for body enrichment
    suspect_id = (source or {}).get("suspect_id")
    meat_notes: list[dict[str, Any]] = (
        _fetch_meat_notes(suspect_id) if suspect_id is not None else []
    )
    user_npi = _fetch_user_npi(user_id)

    body = build_condition_body(
        str(patient_emr_pid),
        icd10_code,
        hcc_label,
        clinical_status=clinical_status,
        verification_status=verification_status,
        recorded_date=recorded_date,
        source=source,
        meat_signed=meat_signed,
        force_accepted=force_accepted,
        user_role=user_role,
        user_npi=user_npi,
        meat_notes=meat_notes,
    )

    url = f"{adapter.base_url}/Condition"

    # Per-tenant circuit breaker — one open tenant doesn't trip another.
    from app.services.circuit_breaker import (
        CircuitBreakerError,
        get_breaker,
    )
    _cb_key = f"fhir:{tenant_id}:{adapter.base_url}"
    _breaker = get_breaker(_cb_key, failure_threshold=5, recovery_timeout=60.0)

    @_fhir_post_retry
    def _do_post(headers: dict[str, str]) -> httpx.Response:
        with httpx.Client(timeout=_TIMEOUT, verify=True) as client:
            resp = client.post(url, headers=headers, json=body)
            if resp.status_code in _RETRYABLE_STATUS:
                resp.raise_for_status()
            return resp

    headers = {**adapter._auth_headers(), "Content-Type": "application/fhir+json"}
    try:
        resp = _breaker(_do_post)(headers)
    except CircuitBreakerError as cb_err:
        # Circuit open — fail fast without hitting the EHR.
        try:
            from app.services.immutable_audit import append_audit_entry
            append_audit_entry(
                action="FHIR_CIRCUIT_OPEN",
                resource_type="fhir",
                resource_id=str(tenant_id),
                details=f"circuit_open retry_after={cb_err.retry_after:.0f}s",
                tenant_id=str(tenant_id),
            )
        except Exception:  # noqa: BLE001 — best-effort guard
            logger.debug("swallowed exception", exc_info=True)
        raise RuntimeError(
            f"FHIR write-back unavailable (circuit open). Retry in "
            f"{cb_err.retry_after:.0f} seconds."
        ) from cb_err

    # Some OpenEMR builds return 401 with a stale token — refresh and retry once.
    if resp.status_code == 401:
        logger.warning("FHIR POST Condition -> 401, forcing token refresh")
        adapter._force_refresh()
        headers = {
            **adapter._auth_headers(),
            "Content-Type": "application/fhir+json",
        }
        resp = _do_post(headers)

    if resp.status_code not in (200, 201):
        logger.error(
            "FHIR POST Condition failed: %s body=%s",
            resp.status_code,
            resp.text[:400],
        )
        raise RuntimeError(
            f"FHIR Condition write failed: HTTP {resp.status_code} "
            f"body={resp.text[:200]}"
        )

    # 201 typically uses the Location header (Condition/<id>/_history/<v>)
    condition_id = ""
    location = resp.headers.get("Location") or resp.headers.get("location") or ""
    if location:
        # Strip trailing /_history/N if present, then take the last path segment.
        loc = location.split("/_history/")[0].rstrip("/")
        if "/" in loc:
            condition_id = loc.rsplit("/", 1)[-1]
        else:
            condition_id = loc

    if not condition_id:
        try:
            body_json = resp.json()
            condition_id = body_json.get("id", "") if isinstance(body_json, dict) else ""
        except (ValueError, TypeError):
            condition_id = ""

    if not condition_id:
        # Last-resort synthetic id so the caller has *something* auditable.
        condition_id = f"unknown-{int(time.time())}"
        logger.warning(
            "FHIR POST Condition succeeded (HTTP %s) but no id in Location/body",
            resp.status_code,
        )

    logger.info(
        "Pushed FHIR Condition id=%s for Patient/%s icd10=%s",
        condition_id,
        patient_emr_pid,
        icd10_code,
    )
    return condition_id


def reconcile_condition(
    patient_emr_pid: str | int,
    icd10_code: str,
    *,
    tenant_id: str | None = None,
    adapter: OpenEMRFhirAdapter | None = None,
) -> bool:
    """Confirm the new ICD-10 code is now present on the patient's Problem List.

    Returns True when found, False otherwise. Network errors are logged
    and treated as a mismatch (returns False) so the caller can emit
    ``SUSPECT_FHIR_RECONCILE_MISMATCH``.
    """
    if adapter is None:
        try:
            adapter = _get_fhir_adapter(tenant_id=tenant_id)
        except Exception as exc:
            logger.warning("reconcile_condition: adapter resolve failed: %s", exc)
            return False

    try:
        bundle = adapter._fhir_get(
            "Condition", params={"subject": f"Patient/{patient_emr_pid}"}
        )
    except Exception as exc:
        logger.warning(
            "reconcile_condition: GET Condition failed for pid=%s: %s",
            patient_emr_pid,
            exc,
        )
        return False

    target = (icd10_code or "").strip().upper()
    if not target:
        return False

    for entry in (bundle or {}).get("entry", []) or []:
        resource = entry.get("resource", {}) if isinstance(entry, dict) else {}
        codings = (
            resource.get("code", {}).get("coding", [])
            if isinstance(resource, dict)
            else []
        )
        for c in codings or []:
            code = str(c.get("code") or "").strip().upper()
            system = str(c.get("system") or "")
            if code == target and "icd-10" in system.lower():
                return True
            # OpenEMR is occasionally lax about the system url
            if code == target:
                return True
    return False


def push_and_reconcile(
    patient_emr_pid: str | int,
    icd10_code: str,
    hcc_label: str,
    *,
    clinical_status: str = "active",
    verification_status: str = "confirmed",
    recorded_date: str | None = None,
    source: dict | None = None,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    """Convenience wrapper: push then reconcile in one call.

    Returns a dict::

        {
            "condition_id": str,
            "reconciled": bool,
        }
    """
    adapter = _get_fhir_adapter(tenant_id=tenant_id)
    condition_id = push_problem_list_condition(
        patient_emr_pid,
        icd10_code,
        hcc_label,
        clinical_status=clinical_status,
        verification_status=verification_status,
        recorded_date=recorded_date,
        source=source,
        adapter=adapter,
    )
    reconciled = reconcile_condition(
        patient_emr_pid, icd10_code, tenant_id=tenant_id, adapter=adapter
    )
    return {"condition_id": condition_id, "reconciled": reconciled}


# ---------------------------------------------------------------------------
# Reversal — mark AI-written condition as entered-in-error (Patient Safety fix)
# ---------------------------------------------------------------------------


def reverse_problem_list_condition(
    condition_id: str,
    reversal_reason: str,
    tenant_id: str,
    user_id: int,
    *,
    adapter: OpenEMRFhirAdapter | None = None,
) -> dict[str, Any]:
    """Mark a previously-written FHIR Condition as ``entered-in-error``.

    Steps:
    1. PUT Condition/{condition_id} with verificationStatus="entered-in-error"
       to OpenEMR FHIR.
    2. Emit immutable audit event ``SUSPECT_WRITEBACK_REVERSED``.
    3. Update ``raf_suspect_conditions`` reversal columns.

    Returns ``{"success": True, "condition_id": condition_id}`` or raises
    ``RuntimeError`` on FHIR failure.

    The DB update (step 3) is attempted after the FHIR call.  A DB failure
    is logged as ERROR but does not cause the function to raise — the FHIR
    state is the authoritative record.
    """
    if not condition_id:
        raise ValueError("condition_id is required")
    if not reversal_reason or len(reversal_reason.strip()) < 30:
        raise ValueError("reversal_reason must be at least 30 characters")

    if adapter is None:
        adapter = _get_fhir_adapter(tenant_id=tenant_id)

    # ------------------------------------------------------------------
    # Build minimal update body — entered-in-error
    # ------------------------------------------------------------------
    reversal_body: dict[str, Any] = {
        "resourceType": "Condition",
        "id": condition_id,
        "verificationStatus": {
            "coding": [
                {
                    "system": VERIFICATION_STATUS_SYSTEM,
                    "code": "entered-in-error",
                    "display": "Entered In Error",
                }
            ]
        },
    }

    url = f"{adapter.base_url}/Condition/{condition_id}"

    from app.services.circuit_breaker import (
        CircuitBreakerError,
        get_breaker,
    )
    _cb_key = f"fhir:{tenant_id}:{adapter.base_url}"
    _breaker = get_breaker(_cb_key, failure_threshold=5, recovery_timeout=60.0)

    @_fhir_post_retry
    def _do_put(headers: dict[str, str]) -> httpx.Response:
        with httpx.Client(timeout=_TIMEOUT, verify=True) as client:
            resp = client.put(url, headers=headers, json=reversal_body)
            if resp.status_code in _RETRYABLE_STATUS:
                resp.raise_for_status()
            return resp

    headers = {**adapter._auth_headers(), "Content-Type": "application/fhir+json"}
    try:
        resp = _breaker(_do_put)(headers)
    except CircuitBreakerError as cb_err:
        try:
            from app.services.immutable_audit import append_audit_entry
            append_audit_entry(
                action="FHIR_CIRCUIT_OPEN",
                resource_type="fhir",
                resource_id=str(tenant_id),
                details=f"circuit_open reversal retry_after={cb_err.retry_after:.0f}s",
                tenant_id=str(tenant_id),
            )
        except Exception:  # noqa: BLE001 — best-effort guard
            logger.debug("swallowed exception", exc_info=True)
        raise RuntimeError(
            f"FHIR reversal unavailable (circuit open). Retry in "
            f"{cb_err.retry_after:.0f} seconds."
        ) from cb_err

    if resp.status_code == 401:
        logger.warning("FHIR PUT Condition reversal -> 401, forcing token refresh")
        adapter._force_refresh()
        headers = {**adapter._auth_headers(), "Content-Type": "application/fhir+json"}
        resp = _do_put(headers)

    if resp.status_code not in (200, 201):
        logger.error(
            "FHIR PUT Condition reversal failed: %s body=%s",
            resp.status_code,
            resp.text[:400],
        )
        raise RuntimeError(
            f"FHIR Condition reversal failed: HTTP {resp.status_code} "
            f"body={resp.text[:200]}"
        )

    logger.info(
        "Reversed FHIR Condition id=%s (entered-in-error) user_id=%s",
        condition_id,
        user_id,
    )

    # ------------------------------------------------------------------
    # Immutable audit event
    # ------------------------------------------------------------------
    try:
        from app.services.immutable_audit import emit_audit_event

        emit_audit_event(
            "SUSPECT_WRITEBACK_REVERSED",
            tenant_id=tenant_id,
            actor_user_id=user_id,
            subject_type="condition",
            subject_id=condition_id,
            payload={
                "reversal_reason": reversal_reason.strip(),
                "condition_id": condition_id,
            },
        )
    except Exception as exc:
        logger.error(
            "reverse_problem_list_condition: audit emit failed condition_id=%s: %s",
            condition_id, exc,
        )

    # ------------------------------------------------------------------
    # DB update — graceful degradation if migration 031 not applied yet
    # ------------------------------------------------------------------
    reversed_at = datetime.now(tz=timezone.utc)
    try:
        from app.db import raf_cursor

        with raf_cursor() as cur:
            cur.execute(
                """
                UPDATE raf_suspect_conditions
                SET    fhir_writeback_reversed_at     = %s,
                       fhir_writeback_reversal_reason = %s
                WHERE  fhir_condition_id = %s
                  AND  tenant_id         = %s
                """,
                (
                    reversed_at,
                    reversal_reason.strip()[:2000],
                    condition_id,
                    tenant_id,
                ),
            )
    except Exception as exc:
        logger.error(
            "reverse_problem_list_condition: DB update failed condition_id=%s: %s "
            "(migration 031 may not be applied yet)",
            condition_id, exc,
        )

    return {"success": True, "condition_id": condition_id}
