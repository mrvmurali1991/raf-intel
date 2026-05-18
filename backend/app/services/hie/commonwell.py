"""CommonWell Health Alliance FHIR R4 adapter.

API surface used:
  POST {base}/v1/patients/match      — patient demographics query (FHIR R4 Parameters)
  GET  {base}/v1/patients/{id}/DocumentReference — document index
  GET  {base}/v1/Binary/{id}         — binary content fetch

Credentials loaded from:
  HIE_COMMONWELL_CERT_PATH
  HIE_COMMONWELL_KEY_PATH
  HIE_COMMONWELL_TRUST_BUNDLE

Optional:
  HIE_COMMONWELL_BASE_URL            — defaults to CommonWell sandbox
"""
from __future__ import annotations

import base64
import logging
import os
from typing import Any

from .base import (
    HIEAdapter,
    HIENetworkError,
    NetworkNotConfiguredError,
    _parse_fhir_bundle_entries,
)

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "https://api.commonwellalliance.org"


def _extract_confidence(search_match_ext: list[dict] | None) -> float:
    """Parse the CommonWell-specific searchMatch extension for confidence score."""
    if not search_match_ext:
        return 0.0
    for ext in search_match_ext:
        if ext.get("url", "").endswith("confidence") or ext.get("url", "").endswith("score"):
            val = ext.get("valueDecimal") or ext.get("valueInteger")
            if val is not None:
                return float(val)
    return 0.0


def _patient_resource_to_match(resource: dict[str, Any]) -> dict[str, Any]:
    """Map a FHIR Patient resource to our canonical match dict."""
    name_list = resource.get("name") or []
    given = " ".join((name_list[0].get("given") or []) if name_list else [])
    family = (name_list[0].get("family") or "") if name_list else ""
    display_name = f"{given} {family}".strip()

    extensions = resource.get("extension") or []
    confidence = _extract_confidence(extensions)

    return {
        "hie_patient_id": resource.get("id", ""),
        "confidence": confidence,
        "name": display_name,
        "dob": resource.get("birthDate", ""),
        "sex": resource.get("gender", ""),
        "network": "commonwell",
        "_raw": resource,
    }


class CommonWellAdapter(HIEAdapter):
    """FHIR R4 adapter for CommonWell Health Alliance."""

    network_name = "commonwell"

    def __init__(self) -> None:
        super().__init__()
        self._base_url = os.environ.get("HIE_COMMONWELL_BASE_URL", _DEFAULT_BASE_URL).rstrip("/")

    async def discover_patient(
        self,
        first_name: str,
        last_name: str,
        dob: str,
        sex: str,
        mbi: str | None = None,
    ) -> list[dict[str, Any]]:
        """POST /v1/patients/match with FHIR R4 Parameters body.

        Returns list of candidate matches sorted by descending confidence.
        Returns [] (not raises) when the HIE returns 0 matches.
        Raises NetworkNotConfiguredError when certs are absent.
        """
        await self._rate_limited_call()

        params_body: dict[str, Any] = {
            "resourceType": "Parameters",
            "parameter": [
                {"name": "given", "valueString": first_name},
                {"name": "family", "valueString": last_name},
                {"name": "birthdate", "valueDate": dob},
                {"name": "gender", "valueCode": sex},
            ],
        }
        if mbi:
            params_body["parameter"].append(
                {
                    "name": "identifier",
                    "valueIdentifier": {
                        "system": "http://hl7.org/fhir/sid/us-mbi",
                        "value": mbi,
                    },
                }
            )

        async with self._build_httpx_client() as client:
            url = f"{self._base_url}/v1/patients/match"
            try:
                resp = await client.post(url, json=params_body)
                resp.raise_for_status()
            except Exception as exc:
                raise HIENetworkError(
                    f"CommonWell patient match failed: {exc}"
                ) from exc

            bundle = resp.json()

        resources = _parse_fhir_bundle_entries(bundle)
        matches = [_patient_resource_to_match(r) for r in resources if r.get("resourceType") == "Patient"]
        matches.sort(key=lambda m: m["confidence"], reverse=True)
        logger.info(
            "CommonWell discover_patient: %d candidates for %s %s",
            len(matches),
            first_name,
            last_name,
        )
        return matches

    async def list_document_references(
        self,
        hie_patient_id: str,
        since: str | None = None,
    ) -> list[dict[str, Any]]:
        """GET /v1/patients/{id}/DocumentReference."""
        await self._rate_limited_call()

        params: dict[str, str] = {}
        if since:
            params["date"] = f"ge{since}"

        async with self._build_httpx_client() as client:
            url = f"{self._base_url}/v1/patients/{hie_patient_id}/DocumentReference"
            try:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
            except Exception as exc:
                raise HIENetworkError(
                    f"CommonWell DocumentReference list failed: {exc}"
                ) from exc
            bundle = resp.json()

        doc_refs = _parse_fhir_bundle_entries(bundle)
        logger.info(
            "CommonWell list_document_references: %d docs for patient %s",
            len(doc_refs),
            hie_patient_id,
        )
        return doc_refs

    async def fetch_binary(self, binary_ref: str) -> tuple[bytes, str]:
        """Fetch Binary resource content.

        Tries direct GET first; falls back to FHIR Binary JSON with base64
        .data field if the server returns JSON instead of raw bytes.
        """
        await self._rate_limited_call()

        # Build absolute URL
        url = (
            binary_ref
            if binary_ref.startswith("http")
            else f"{self._base_url}/{binary_ref.lstrip('/')}"
        )

        async with self._build_httpx_client() as client:
            try:
                resp = await client.get(url)
                resp.raise_for_status()
            except Exception as exc:
                raise HIENetworkError(
                    f"CommonWell fetch_binary failed for {url}: {exc}"
                ) from exc

            content_type = resp.headers.get("content-type", "application/octet-stream")

            # If server returned FHIR JSON wrapping base64 content
            if "fhir+json" in content_type or "json" in content_type:
                try:
                    fhir_binary = resp.json()
                    b64_data = fhir_binary.get("data", "")
                    raw = base64.b64decode(b64_data)
                    mime = fhir_binary.get("contentType", "application/pdf")
                    return raw, mime
                except Exception as exc:
                    raise HIENetworkError(
                        f"CommonWell fetch_binary JSON parse failed: {exc}"
                    ) from exc

            return resp.content, content_type.split(";")[0].strip()
