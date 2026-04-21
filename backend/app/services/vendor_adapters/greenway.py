"""
Greenway Health REST API adapter.

Authentication
--------------
API key authentication via ``X-Api-Key`` request header.  The key is stored
in the ``api_key`` field on the connection row.

Optional OAuth2 bearer token auth is also supported when ``api_auth_type`` is
set to ``oauth2`` in ``extra_config.auth_mode`` and ``client_id`` /
``client_secret`` are populated.

Required connection fields
--------------------------
* ``api_base_url``  – e.g. https://api.greenwayhealth.com/v1
* ``api_key``       – Greenway API key

Optional
--------
* ``extra_config.auth_mode``   – ``apikey`` (default) or ``oauth2``
* ``extra_config.token_url``   – OAuth2 token endpoint (oauth2 mode only)
* ``client_id``                – OAuth2 client id
* ``client_secret``            – OAuth2 client secret

Pagination
----------
Greenway uses ``page`` / ``pageSize`` query parameters.  The adapter iterates
until fewer items than ``pageSize`` are returned or an empty page is received.

Rate limiting
-------------
The base class ``_request`` helper handles 429 + ``Retry-After``.
"""
from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from .base import BaseVendorAdapter

logger = logging.getLogger(__name__)

_PAGE_SIZE = 100
_AUTH_APIKEY = "apikey"
_AUTH_OAUTH2 = "oauth2"


class GreenwayAdapter(BaseVendorAdapter):
    """Adapter for the Greenway Health REST API."""

    vendor_name = "greenway"

    def __init__(self, connection: dict[str, Any]) -> None:
        super().__init__(connection)
        self._gw_auth: str = (
            self._extra.get("auth_mode") or _AUTH_APIKEY
        ).lower()
        if self.auth_type in ("bearer",) and self._gw_auth == _AUTH_APIKEY and not self.api_key:
            # Fallback: if no api_key, try oauth2
            self._gw_auth = _AUTH_OAUTH2

        self._token: str = ""
        self._token_expires_at: float = 0.0
        self._token_url: str = self._extra.get(
            "token_url", f"{self.base_url.rstrip('/')}/oauth2/token"
        )

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def _fetch_oauth2_token(self) -> str:
        logger.debug("greenway: fetching OAuth2 token from %s", self._token_url)
        resp = self._request(
            "POST",
            self._token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        data = resp.json()
        token = data.get("access_token", "")
        expires_in = float(data.get("expires_in", 3600))
        self._token = token
        self._token_expires_at = time.monotonic() + expires_in - 60
        return token

    def authenticate(self) -> dict[str, str]:
        if self._gw_auth == _AUTH_APIKEY:
            return {
                "X-Api-Key": self.api_key,
                "Accept": "application/json",
            }
        # OAuth2 path
        if not self._token or time.monotonic() >= self._token_expires_at:
            self._fetch_oauth2_token()
        return {"Authorization": f"Bearer {self._token}"}

    # ------------------------------------------------------------------
    # Connection test
    # ------------------------------------------------------------------

    def test_connection(self) -> dict[str, Any]:
        start = time.monotonic()
        try:
            auth = self.authenticate()
        except Exception as exc:
            latency_ms = int((time.monotonic() - start) * 1000)
            return {"success": False, "message": f"Auth failed: {exc}", "latency_ms": latency_ms}

        test_url = f"{self.base_url.rstrip('/')}/health"
        fallback_url = self.base_url.rstrip("/")

        for url in (test_url, fallback_url):
            try:
                resp = self._request(
                    "GET", url, headers={**auth, "Accept": "application/json"}
                )
                latency_ms = int((time.monotonic() - start) * 1000)
                return {
                    "success": True,
                    "message": f"HTTP {resp.status_code} from {url}",
                    "latency_ms": latency_ms,
                }
            except httpx.HTTPStatusError as exc:
                last_exc: str = f"HTTP {exc.response.status_code} from {url}"
            except Exception as exc:
                last_exc = str(exc)

        latency_ms = int((time.monotonic() - start) * 1000)
        return {"success": False, "message": last_exc, "latency_ms": latency_ms}

    # ------------------------------------------------------------------
    # Pagination helper
    # ------------------------------------------------------------------

    def _paginate(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        results_key: str | None = None,
    ) -> list[dict[str, Any]]:
        auth = self.authenticate()
        headers = {**auth, "Accept": "application/json"}
        base_params: dict[str, Any] = {"pageSize": _PAGE_SIZE, "page": 1}
        if params:
            base_params.update(params)

        all_items: list[dict[str, Any]] = []
        url = f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"

        while True:
            resp = self._request("GET", url, headers=headers, params=base_params)
            payload = resp.json()

            if results_key:
                items: list[dict] = payload.get(results_key) or []
            elif isinstance(payload, list):
                items = payload
            else:
                items = (
                    payload.get("data")
                    or payload.get("results")
                    or payload.get("items")
                    or []
                )

            if not items:
                break

            all_items.extend(items)

            if len(items) < _PAGE_SIZE:
                break  # Last page reached

            base_params["page"] = int(base_params["page"]) + 1

        return all_items

    # ------------------------------------------------------------------
    # Data fetching
    # ------------------------------------------------------------------

    def fetch_patients(self, since: str | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        if since:
            params["modifiedSince"] = since
        raw = self._paginate("/patients", params=params)
        return [self._normalize_patient(p) for p in raw]

    def fetch_encounters(
        self, patient_id: str, since: str | None = None
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"patientId": patient_id}
        if since:
            params["startDate"] = since
        raw = self._paginate("/encounters", params=params)
        return [self._normalize_encounter(e, patient_id) for e in raw]

    def fetch_conditions(self, patient_id: str) -> list[dict[str, Any]]:
        raw = self._paginate("/conditions", params={"patientId": patient_id})
        conditions: list[dict[str, Any]] = []
        for item in raw:
            normalised = self._normalize_condition(item, patient_id)
            if normalised:
                conditions.append(normalised)
        return conditions

    def fetch_medications(self, patient_id: str) -> list[dict[str, Any]]:
        raw = self._paginate("/medications", params={"patientId": patient_id})
        return [self._normalize_medication(m, patient_id) for m in raw]

    def fetch_vitals(self, patient_id: str) -> list[dict[str, Any]]:
        raw = self._paginate("/vitals", params={"patientId": patient_id})
        return [self._normalize_vital(v, patient_id) for v in raw]

    def fetch_labs(self, patient_id: str) -> list[dict[str, Any]]:
        raw = self._paginate("/labs", params={"patientId": patient_id})
        return [self._normalize_lab(lab, patient_id) for lab in raw]

    # ------------------------------------------------------------------
    # Normalisation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_patient(raw: dict[str, Any]) -> dict[str, Any]:
        sex_raw = (raw.get("gender") or raw.get("sex") or "U").upper()
        sex_map = {"MALE": "M", "FEMALE": "F", "M": "M", "F": "F"}
        sex = sex_map.get(sex_raw, "U")
        patient_id = str(raw.get("patientId") or raw.get("id") or "")
        dob = raw.get("dateOfBirth") or raw.get("dob") or ""
        return {
            "external_id": patient_id,
            "first_name": raw.get("firstName") or raw.get("first_name") or "",
            "last_name": raw.get("lastName") or raw.get("last_name") or "",
            "date_of_birth": dob[:10] if dob else "",
            "sex": sex,
            "mrn": raw.get("mrn") or patient_id,
            "raw": raw,
        }

    @staticmethod
    def _normalize_encounter(raw: dict[str, Any], patient_id: str) -> dict[str, Any]:
        enc_date = raw.get("encounterDate") or raw.get("startDate") or raw.get("date") or ""
        return {
            "external_id": str(raw.get("encounterId") or raw.get("id") or ""),
            "patient_external_id": patient_id,
            "encounter_date": enc_date[:10] if enc_date else "",
            "encounter_type": raw.get("encounterType") or raw.get("type") or "",
            "provider": str(raw.get("providerId") or raw.get("provider") or ""),
            "raw": raw,
        }

    @staticmethod
    def _normalize_condition(raw: dict[str, Any], patient_id: str) -> dict[str, Any] | None:
        icd10 = (
            raw.get("icd10Code")
            or raw.get("conditionCode")
            or raw.get("diagnosisCode")
            or ""
        ).strip().upper()
        description = raw.get("conditionName") or raw.get("description") or raw.get("name") or ""
        status_raw = (raw.get("status") or "active").lower()
        status = "inactive" if status_raw in ("resolved", "inactive", "deleted") else "active"
        onset = raw.get("onsetDate") or raw.get("startDate") or ""
        return {
            "icd10_code": icd10,
            "description": description,
            "status": status,
            "onset_date": onset[:10] if onset else "",
            "patient_external_id": patient_id,
            "raw": raw,
        }

    @staticmethod
    def _normalize_medication(raw: dict[str, Any], patient_id: str) -> dict[str, Any]:
        status_raw = (raw.get("status") or "active").lower()
        status = "active" if status_raw in ("active", "current") else "inactive"
        start = raw.get("startDate") or raw.get("prescribedDate") or ""
        return {
            "external_id": str(raw.get("medicationId") or raw.get("id") or ""),
            "patient_external_id": patient_id,
            "drug_name": raw.get("medicationName") or raw.get("name") or "",
            "status": status,
            "start_date": start[:10] if start else "",
            "raw": raw,
        }

    @staticmethod
    def _normalize_vital(raw: dict[str, Any], patient_id: str) -> dict[str, Any]:
        recorded = raw.get("recordedDate") or raw.get("date") or ""
        return {
            "patient_external_id": patient_id,
            "recorded_date": recorded[:10] if recorded else "",
            "type": raw.get("vitalType") or raw.get("type") or "",
            "value": str(raw.get("value") or ""),
            "unit": raw.get("unit") or raw.get("units") or "",
            "raw": raw,
        }

    @staticmethod
    def _normalize_lab(raw: dict[str, Any], patient_id: str) -> dict[str, Any]:
        result_date = raw.get("resultDate") or raw.get("date") or ""
        abnormal_raw = str(raw.get("abnormal") or raw.get("abnormalFlag") or "").lower()
        abnormal = abnormal_raw in ("true", "1", "h", "l", "a", "critical", "abnormal")
        return {
            "patient_external_id": patient_id,
            "result_date": result_date[:10] if result_date else "",
            "test_name": raw.get("testName") or raw.get("name") or "",
            "value": str(raw.get("value") or ""),
            "unit": raw.get("unit") or raw.get("units") or "",
            "abnormal": abnormal,
            "raw": raw,
        }
