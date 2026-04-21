"""
DrChrono REST API adapter.

Authentication
--------------
OAuth2 client_credentials (or refresh-token) flow.  The token endpoint is:

    POST https://drchrono.com/o/token/

Required connection fields
--------------------------
* ``client_id``      – DrChrono API client id
* ``client_secret``  – DrChrono API client secret
* ``api_base_url``   – defaults to https://app.drchrono.com/api
* ``extra_config.refresh_token`` – optional refresh token for offline access

Pagination
----------
DrChrono returns a ``next`` URL in the response that points to the next page.
This adapter follows ``next`` automatically.

Rate limiting
-------------
The base class ``_request`` helper handles 429 + ``Retry-After``.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from .base import BaseVendorAdapter

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "https://app.drchrono.com/api"
_TOKEN_URL = "https://drchrono.com/o/token/"
_PAGE_SIZE = 100


class DrChronoAdapter(BaseVendorAdapter):
    """Adapter for the DrChrono REST API."""

    vendor_name = "drchrono"

    def __init__(self, connection: dict[str, Any]) -> None:
        super().__init__(connection)
        if not self.base_url:
            self.base_url = _DEFAULT_BASE_URL
        self.refresh_token: str = self._extra.get("refresh_token", "")
        self._token: str = ""
        self._token_expires_at: float = 0.0

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def _fetch_token(self) -> str:
        """Obtain a fresh access token using client_credentials or refresh_token."""
        payload: dict[str, str]
        if self.refresh_token:
            payload = {
                "grant_type": "refresh_token",
                "refresh_token": self.refresh_token,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            }
        else:
            payload = {
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            }

        logger.debug("drchrono: fetching token from %s", _TOKEN_URL)
        resp = self._request(
            "POST",
            _TOKEN_URL,
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        data = resp.json()
        token = data.get("access_token", "")
        expires_in = float(data.get("expires_in", 3600))
        # Store refreshed refresh_token if returned.
        new_refresh = data.get("refresh_token")
        if new_refresh:
            self.refresh_token = new_refresh
        self._token = token
        self._token_expires_at = time.monotonic() + expires_in - 60
        return token

    def authenticate(self) -> dict[str, str]:
        if not self._token or time.monotonic() >= self._token_expires_at:
            self._fetch_token()
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

        test_url = f"{self.base_url}/users/current"
        try:
            resp = self._request("GET", test_url, headers={**auth, "Accept": "application/json"})
            latency_ms = int((time.monotonic() - start) * 1000)
            return {
                "success": True,
                "message": f"HTTP {resp.status_code} from {test_url}",
                "latency_ms": latency_ms,
            }
        except Exception as exc:
            latency_ms = int((time.monotonic() - start) * 1000)
            return {"success": False, "message": str(exc), "latency_ms": latency_ms}

    # ------------------------------------------------------------------
    # Pagination helper
    # ------------------------------------------------------------------

    def _paginate(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        results_key: str | None = None,
    ) -> list[dict[str, Any]]:
        """Follow DrChrono's cursor-based ``next`` URL pagination."""
        auth = self.authenticate()
        headers = {**auth, "Accept": "application/json"}
        base_params: dict[str, Any] = {"page_size": _PAGE_SIZE}
        if params:
            base_params.update(params)

        all_items: list[dict[str, Any]] = []
        next_url: str | None = f"{self.base_url}{path}"

        while next_url:
            # On the first request use base_params; subsequent pages include
            # all state in the URL already.
            if next_url == f"{self.base_url}{path}":
                resp = self._request("GET", next_url, headers=headers, params=base_params)
            else:
                resp = self._request("GET", next_url, headers=headers)

            payload = resp.json()

            if results_key:
                items: list[dict] = payload.get(results_key) or []
            else:
                items = payload.get("results") or []

            all_items.extend(items)
            next_url = payload.get("next")  # None when last page

        return all_items

    # ------------------------------------------------------------------
    # Data fetching
    # ------------------------------------------------------------------

    def fetch_patients(self, since: str | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        if since:
            params["date_of_last_appointment"] = since  # best-effort filter
        raw = self._paginate("/patients", params=params)
        return [self._normalize_patient(p) for p in raw]

    def fetch_encounters(
        self, patient_id: str, since: str | None = None
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"patient": patient_id}
        if since:
            params["date_range"] = since
        raw = self._paginate("/appointments", params=params)
        return [self._normalize_encounter(e, patient_id) for e in raw]

    def fetch_conditions(self, patient_id: str) -> list[dict[str, Any]]:
        raw = self._paginate("/problems", params={"patient": patient_id})
        conditions: list[dict[str, Any]] = []
        for item in raw:
            normalised = self._normalize_condition(item, patient_id)
            if normalised:
                conditions.append(normalised)
        return conditions

    def fetch_medications(self, patient_id: str) -> list[dict[str, Any]]:
        raw = self._paginate("/medications", params={"patient": patient_id})
        return [self._normalize_medication(m, patient_id) for m in raw]

    def fetch_vitals(self, patient_id: str) -> list[dict[str, Any]]:
        raw = self._paginate("/vitals", params={"patient": patient_id})
        return [self._normalize_vital(v, patient_id) for v in raw]

    def fetch_labs(self, patient_id: str) -> list[dict[str, Any]]:
        raw = self._paginate("/lab_results", params={"patient": patient_id})
        return [self._normalize_lab(lab, patient_id) for lab in raw]

    # ------------------------------------------------------------------
    # Normalisation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_patient(raw: dict[str, Any]) -> dict[str, Any]:
        sex_raw = (raw.get("gender") or "U").upper()
        sex_map = {"MALE": "M", "FEMALE": "F", "M": "M", "F": "F"}
        sex = sex_map.get(sex_raw, "U")
        patient_id = str(raw.get("id") or "")
        return {
            "external_id": patient_id,
            "first_name": raw.get("first_name") or "",
            "last_name": raw.get("last_name") or "",
            "date_of_birth": raw.get("date_of_birth") or "",  # already YYYY-MM-DD
            "sex": sex,
            "mrn": raw.get("chart_id") or patient_id,
            "raw": raw,
        }

    @staticmethod
    def _normalize_encounter(raw: dict[str, Any], patient_id: str) -> dict[str, Any]:
        return {
            "external_id": str(raw.get("id") or ""),
            "patient_external_id": patient_id,
            "encounter_date": (raw.get("scheduled_time") or "")[:10],
            "encounter_type": raw.get("appointment_type") or raw.get("visit_reason") or "",
            "provider": str(raw.get("doctor") or raw.get("primary_care_physician") or ""),
            "raw": raw,
        }

    @staticmethod
    def _normalize_condition(raw: dict[str, Any], patient_id: str) -> dict[str, Any] | None:
        # DrChrono problems use icd_code field
        icd10 = (raw.get("icd_code") or raw.get("icd10_code") or "").strip().upper()
        description = raw.get("name") or raw.get("description") or ""
        status_raw = (raw.get("status") or "active").lower()
        status = "inactive" if status_raw in ("resolved", "inactive", "deleted") else "active"
        onset = raw.get("date") or raw.get("onset_date") or ""
        return {
            "icd10_code": icd10,
            "description": description,
            "status": status,
            "onset_date": onset,
            "patient_external_id": patient_id,
            "raw": raw,
        }

    @staticmethod
    def _normalize_medication(raw: dict[str, Any], patient_id: str) -> dict[str, Any]:
        status_raw = (raw.get("status") or "active").lower()
        status = "active" if status_raw in ("active",) else "inactive"
        return {
            "external_id": str(raw.get("id") or ""),
            "patient_external_id": patient_id,
            "drug_name": raw.get("name") or raw.get("drug_name") or "",
            "status": status,
            "start_date": raw.get("date_started_taking") or "",
            "raw": raw,
        }

    @staticmethod
    def _normalize_vital(raw: dict[str, Any], patient_id: str) -> dict[str, Any]:
        return {
            "patient_external_id": patient_id,
            "recorded_date": raw.get("date_taken") or raw.get("date") or "",
            "type": raw.get("vital_type") or raw.get("type") or "",
            "value": str(raw.get("value") or ""),
            "unit": raw.get("units") or raw.get("unit") or "",
            "raw": raw,
        }

    @staticmethod
    def _normalize_lab(raw: dict[str, Any], patient_id: str) -> dict[str, Any]:
        abnormal_raw = str(raw.get("abnormal_flag") or raw.get("abnormal") or "").lower()
        abnormal = abnormal_raw in ("true", "1", "h", "l", "a", "critical", "abnormal")
        return {
            "patient_external_id": patient_id,
            "result_date": raw.get("date_collected") or raw.get("date") or "",
            "test_name": raw.get("test_name") or raw.get("name") or "",
            "value": str(raw.get("value") or ""),
            "unit": raw.get("units") or raw.get("unit") or "",
            "abnormal": abnormal,
            "raw": raw,
        }
