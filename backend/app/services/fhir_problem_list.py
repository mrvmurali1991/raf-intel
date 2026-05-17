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

_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
_BROWSER_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


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
# Body builder (pure, so the unit test can assert against it)
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
) -> dict[str, Any]:
    """Return the FHIR ``Condition`` resource body as a dict.

    Parameters mirror :func:`push_problem_list_condition` so callers can
    inspect what *would* be posted without hitting the network.
    """
    if not recorded_date:
        recorded_date = date.today().isoformat()

    source = source or {}
    suspect_id = source.get("suspect_id")
    source_label = source.get("source") or "raf_intelligence"

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
                    "code": verification_status,
                    "display": verification_status.title(),
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

    body = build_condition_body(
        str(patient_emr_pid),
        icd10_code,
        hcc_label,
        clinical_status=clinical_status,
        verification_status=verification_status,
        recorded_date=recorded_date,
        source=source,
    )

    url = f"{adapter.base_url}/Condition"

    @_fhir_post_retry
    def _do_post(headers: dict[str, str]) -> httpx.Response:
        with httpx.Client(timeout=_TIMEOUT, verify=True) as client:
            resp = client.post(url, headers=headers, json=body)
            if resp.status_code in _RETRYABLE_STATUS:
                resp.raise_for_status()
            return resp

    headers = {**adapter._auth_headers(), "Content-Type": "application/fhir+json"}
    resp = _do_post(headers)

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
