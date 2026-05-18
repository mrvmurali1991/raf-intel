"""Carequality QHIN FHIR R4 adapter.

API surface used:
  POST {base}/Patient/$match         — patient demographics query (FHIR R4)
  GET  {base}/DocumentReference      — document index, patient param
  GET  {base}/Binary/{id}            — binary content fetch

Credentials loaded from:
  HIE_CAREQUALITY_CERT_PATH
  HIE_CAREQUALITY_KEY_PATH
  HIE_CAREQUALITY_TRUST_BUNDLE

Optional:
  HIE_CAREQUALITY_BASE_URL           — defaults to Carequality sandbox
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

_DEFAULT_BASE_URL = "https://fhir.carequality.org/r4"


def _extract_match_grade(entry: dict[str, Any]) -> float:
    """Parse Carequality's search.score from a Bundle entry."""
    search = entry.get("search") or {}
    score = search.get("score")
    if score is not None:
        return float(score)
    # Fall back to extension-based confidence
    resource = entry.get("resource") or {}
    for ext in resource.get("extension") or []:
        url = ext.get("url", "")
        if "match-grade" in url or "confidence" in url:
            code = ext.get("valueCode", "")
            if code == "certain":
                return 1.0
            if code == "probable":
                return 0.85
            if code == "possible":
                return 0.65
    return 0.0


def _entry_to_match(entry: dict[str, Any]) -> dict[str, Any]:
    resource = entry.get("resource") or {}
    name_list = resource.get("name") or []
    given = " ".join((name_list[0].get("given") or []) if name_list else [])
    family = (name_list[0].get("family") or "") if name_list else ""
    display_name = f"{given} {family}".strip()

    return {
        "hie_patient_id": resource.get("id", ""),
        "confidence": _extract_match_grade(entry),
        "name": display_name,
        "dob": resource.get("birthDate", ""),
        "sex": resource.get("gender", ""),
        "network": "carequality",
        "_raw": resource,
    }


class CarequalityAdapter(HIEAdapter):
    """FHIR R4 adapter for Carequality QHIN network."""

    network_name = "carequality"

    def __init__(self) -> None:
        super().__init__()
        self._base_url = os.environ.get("HIE_CAREQUALITY_BASE_URL", _DEFAULT_BASE_URL).rstrip("/")

    async def discover_patient(
        self,
        first_name: str,
        last_name: str,
        dob: str,
        sex: str,
        mbi: str | None = None,
    ) -> list[dict[str, Any]]:
        """POST /Patient/$match per FHIR R4 Patient matching spec.

        Returns list of candidate matches sorted by descending confidence.
        Returns [] on zero matches.
        Raises NetworkNotConfiguredError when certs are absent.
        """
        await self._rate_limited_call()

        patient_resource: dict[str, Any] = {
            "resourceType": "Patient",
            "name": [{"family": last_name, "given": [first_name]}],
            "birthDate": dob,
            "gender": sex,
        }
        if mbi:
            patient_resource["identifier"] = [
                {
                    "system": "http://hl7.org/fhir/sid/us-mbi",
                    "value": mbi,
                }
            ]

        params_body = {
            "resourceType": "Parameters",
            "parameter": [
                {"name": "resource", "resource": patient_resource},
                {"name": "onlyCertainMatches", "valueBoolean": False},
            ],
        }

        async with self._build_httpx_client() as client:
            url = f"{self._base_url}/Patient/$match"
            try:
                resp = await client.post(url, json=params_body)
                resp.raise_for_status()
            except Exception as exc:
                raise HIENetworkError(
                    f"Carequality patient match failed: {exc}"
                ) from exc
            bundle = resp.json()

        raw_entries = bundle.get("entry") or []
        matches = [_entry_to_match(e) for e in raw_entries if "resource" in e]
        matches = [m for m in matches if m["hie_patient_id"]]
        matches.sort(key=lambda m: m["confidence"], reverse=True)
        logger.info(
            "Carequality discover_patient: %d candidates for %s %s",
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
        """GET /DocumentReference?patient={hie_patient_id}."""
        await self._rate_limited_call()

        params: dict[str, str] = {"patient": hie_patient_id}
        if since:
            params["date"] = f"ge{since}"

        async with self._build_httpx_client() as client:
            url = f"{self._base_url}/DocumentReference"
            try:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
            except Exception as exc:
                raise HIENetworkError(
                    f"Carequality DocumentReference list failed: {exc}"
                ) from exc
            bundle = resp.json()

        doc_refs = _parse_fhir_bundle_entries(bundle)
        logger.info(
            "Carequality list_document_references: %d docs for patient %s",
            len(doc_refs),
            hie_patient_id,
        )
        return doc_refs

    async def fetch_binary(self, binary_ref: str) -> tuple[bytes, str]:
        """Fetch Binary resource content, with JSON/base64 fallback."""
        await self._rate_limited_call()

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
                    f"Carequality fetch_binary failed for {url}: {exc}"
                ) from exc

            content_type = resp.headers.get("content-type", "application/octet-stream")

            if "fhir+json" in content_type or "json" in content_type:
                try:
                    fhir_binary = resp.json()
                    b64_data = fhir_binary.get("data", "")
                    raw = base64.b64decode(b64_data)
                    mime = fhir_binary.get("contentType", "application/pdf")
                    return raw, mime
                except Exception as exc:
                    raise HIENetworkError(
                        f"Carequality fetch_binary JSON parse failed: {exc}"
                    ) from exc

            return resp.content, content_type.split(";")[0].strip()
