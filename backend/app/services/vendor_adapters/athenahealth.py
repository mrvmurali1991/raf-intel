"""
athenahealth REST API adapter.

Authentication
--------------
OAuth2 client_credentials flow.  The token endpoint is:

    POST https://api.platform.athenahealth.com/oauth2/v1/token

Required connection fields
--------------------------
* ``client_id``      – athenahealth API client id
* ``client_secret``  – athenahealth API client secret
* ``api_base_url``   – defaults to https://api.platform.athenahealth.com
* ``extra_config.practice_id`` – athena practice ID (required for patient APIs)

Pagination
----------
athenahealth uses ``offset`` / ``limit`` with a ``totalcount`` field.  This
adapter iterates pages automatically until all records are fetched.

Rate limiting
-------------
The base class ``_request`` helper handles 429 + ``Retry-After``.
"""
from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from .base import BaseVendorAdapter, _DEFAULT_TIMEOUT

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "https://api.platform.athenahealth.com"
_TOKEN_PATH = "/oauth2/v1/token"
_PAGE_SIZE = 100


class AthenahealthAdapter(BaseVendorAdapter):
    """Adapter for the athenahealth REST platform API."""

    vendor_name = "athenahealth"

    def __init__(self, connection: dict[str, Any]) -> None:
        super().__init__(connection)
        if not self.base_url:
            self.base_url = _DEFAULT_BASE_URL
        self.practice_id: str = str(self._extra.get("practice_id", ""))
        self._token: str = ""
        self._token_expires_at: float = 0.0

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def _fetch_token(self) -> str:
        """Obtain a fresh OAuth2 bearer token via client_credentials."""
        token_url = f"{self.base_url}{_TOKEN_PATH}"
        logger.debug("athenahealth: fetching token from %s", token_url)
        resp = self._request(
            "POST",
            token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        payload = resp.json()
        token = payload.get("access_token", "")
        expires_in = float(payload.get("expires_in", 3600))
        self._token = token
        self._token_expires_at = time.monotonic() + expires_in - 60  # 60 s buffer
        return token

    def authenticate(self) -> dict[str, str]:
        """Return Authorization header, refreshing token if necessary."""
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

        # Hit a lightweight endpoint; if practice_id is set use the practice
        # info endpoint, otherwise fall back to the API root.
        if self.practice_id:
            test_url = f"{self.base_url}/v1/{self.practice_id}/practiceinfo"
        else:
            test_url = f"{self.base_url}/v1"

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
    # Internal pagination helper
    # ------------------------------------------------------------------

    def _paginate(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        results_key: str = "results",
    ) -> list[dict[str, Any]]:
        """Fetch all pages from an athenahealth list endpoint.

        athenahealth paginates with ``offset`` / ``limit`` and returns
        ``totalcount`` at the top level.
        """
        auth = self.authenticate()
        headers = {**auth, "Accept": "application/json"}
        base_params: dict[str, Any] = {"limit": _PAGE_SIZE, "offset": 0}
        if params:
            base_params.update(params)

        all_items: list[dict[str, Any]] = []
        url = f"{self.base_url}{path}"

        while True:
            resp = self._request("GET", url, headers=headers, params=base_params)
            payload = resp.json()

            items: list[dict] = payload.get(results_key) or []
            all_items.extend(items)

            total = int(payload.get("totalcount", len(all_items)))
            current_offset = int(base_params["offset"])
            fetched_so_far = current_offset + len(items)

            if fetched_so_far >= total or not items:
                break

            base_params["offset"] = fetched_so_far

        return all_items

    # ------------------------------------------------------------------
    # Data fetching
    # ------------------------------------------------------------------

    def fetch_patients(self, since: str | None = None) -> list[dict[str, Any]]:
        if not self.practice_id:
            raise ValueError("athenahealth: practice_id is required in extra_config")

        params: dict[str, Any] = {}
        if since:
            params["lastmodifiedstartdate"] = since

        raw_patients = self._paginate(
            f"/v1/{self.practice_id}/patients",
            params=params,
            results_key="patients",
        )
        return [self._normalize_patient(p) for p in raw_patients]

    def fetch_encounters(
        self, patient_id: str, since: str | None = None
    ) -> list[dict[str, Any]]:
        if not self.practice_id:
            raise ValueError("athenahealth: practice_id is required in extra_config")

        params: dict[str, Any] = {}
        if since:
            params["startdate"] = since

        raw = self._paginate(
            f"/v1/{self.practice_id}/patients/{patient_id}/encounters",
            params=params,
            results_key="encounters",
        )
        return [self._normalize_encounter(e, patient_id) for e in raw]

    def fetch_conditions(self, patient_id: str) -> list[dict[str, Any]]:
        if not self.practice_id:
            raise ValueError("athenahealth: practice_id is required in extra_config")

        raw = self._paginate(
            f"/v1/{self.practice_id}/chart/{patient_id}/problems",
            results_key="problems",
        )
        conditions: list[dict[str, Any]] = []
        for item in raw:
            normalised = self._normalize_condition(item, patient_id)
            if normalised:
                conditions.append(normalised)
        return conditions

    def fetch_medications(self, patient_id: str) -> list[dict[str, Any]]:
        if not self.practice_id:
            raise ValueError("athenahealth: practice_id is required in extra_config")

        raw = self._paginate(
            f"/v1/{self.practice_id}/chart/{patient_id}/medications",
            results_key="medications",
        )
        return [self._normalize_medication(m, patient_id) for m in raw]

    def fetch_vitals(self, patient_id: str) -> list[dict[str, Any]]:
        if not self.practice_id:
            raise ValueError("athenahealth: practice_id is required in extra_config")

        raw = self._paginate(
            f"/v1/{self.practice_id}/chart/{patient_id}/vitals",
            results_key="vitals",
        )
        return [self._normalize_vital(v, patient_id) for v in raw]

    def fetch_labs(self, patient_id: str) -> list[dict[str, Any]]:
        if not self.practice_id:
            raise ValueError("athenahealth: practice_id is required in extra_config")

        raw = self._paginate(
            f"/v1/{self.practice_id}/chart/{patient_id}/labresults",
            results_key="labresults",
        )
        return [self._normalize_lab(lab, patient_id) for lab in raw]

    # ------------------------------------------------------------------
    # Normalisation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_patient(raw: dict[str, Any]) -> dict[str, Any]:
        dob_raw = raw.get("dob") or raw.get("dateofbirth") or ""
        # athena returns dates as MM/DD/YYYY
        dob = _reformat_mdy(dob_raw)
        sex_raw = (raw.get("sex") or raw.get("gender") or "U").upper()
        sex = sex_raw[0] if sex_raw else "U"
        patient_id = str(raw.get("patientid") or raw.get("patient_id") or "")
        return {
            "external_id": patient_id,
            "first_name": raw.get("firstname") or raw.get("first_name") or "",
            "last_name": raw.get("lastname") or raw.get("last_name") or "",
            "date_of_birth": dob,
            "sex": sex if sex in ("M", "F") else "U",
            "mrn": raw.get("patientid") or patient_id,
            "raw": raw,
        }

    @staticmethod
    def _normalize_encounter(raw: dict[str, Any], patient_id: str) -> dict[str, Any]:
        enc_date = _reformat_mdy(raw.get("encounterdate") or raw.get("startdate") or "")
        return {
            "external_id": str(raw.get("encounterid") or ""),
            "patient_external_id": patient_id,
            "encounter_date": enc_date,
            "encounter_type": raw.get("encountertype") or raw.get("type") or "",
            "provider": raw.get("providerid") or raw.get("provider") or "",
            "raw": raw,
        }

    @staticmethod
    def _normalize_condition(raw: dict[str, Any], patient_id: str) -> dict[str, Any] | None:
        # athena problems may include ICD-10 codes directly or via a code field
        icd10 = (
            raw.get("icd10code")
            or raw.get("icd10")
            or raw.get("icdcode")
            or ""
        ).strip().upper()
        description = raw.get("problemname") or raw.get("name") or ""
        status_raw = (raw.get("status") or "active").lower()
        status = "active" if status_raw in ("active", "acute", "chronic") else status_raw
        onset = _reformat_mdy(raw.get("onsetdate") or raw.get("startdate") or "")
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
        active = str(raw.get("isstopped") or "").lower()
        status = "inactive" if active == "true" else "active"
        start = _reformat_mdy(raw.get("startdate") or raw.get("createddate") or "")
        return {
            "external_id": str(raw.get("medicationid") or ""),
            "patient_external_id": patient_id,
            "drug_name": raw.get("medication") or raw.get("name") or "",
            "status": status,
            "start_date": start,
            "raw": raw,
        }

    @staticmethod
    def _normalize_vital(raw: dict[str, Any], patient_id: str) -> dict[str, Any]:
        recorded = _reformat_mdy(raw.get("recordeddate") or raw.get("vitaldate") or "")
        return {
            "patient_external_id": patient_id,
            "recorded_date": recorded,
            "type": raw.get("vitaltype") or raw.get("type") or "",
            "value": str(raw.get("value") or ""),
            "unit": raw.get("unit") or "",
            "raw": raw,
        }

    @staticmethod
    def _normalize_lab(raw: dict[str, Any], patient_id: str) -> dict[str, Any]:
        result_date = _reformat_mdy(raw.get("resultdate") or raw.get("date") or "")
        abnormal_raw = str(raw.get("resultstatus") or raw.get("abnormal") or "").lower()
        abnormal = abnormal_raw in ("abnormal", "true", "1", "h", "l", "critical")
        return {
            "patient_external_id": patient_id,
            "result_date": result_date,
            "test_name": raw.get("name") or raw.get("testname") or "",
            "value": str(raw.get("value") or ""),
            "unit": raw.get("unit") or "",
            "abnormal": abnormal,
            "raw": raw,
        }


# ---------------------------------------------------------------------------
# Module-level utility
# ---------------------------------------------------------------------------

def _reformat_mdy(date_str: str) -> str:
    """Convert MM/DD/YYYY → YYYY-MM-DD.  Returns original string unchanged if
    it does not match the expected format, so ISO dates pass through intact."""
    if not date_str:
        return ""
    parts = date_str.split("/")
    if len(parts) == 3:
        mm, dd, yyyy = parts
        return f"{yyyy}-{mm.zfill(2)}-{dd.zfill(2)}"
    return date_str
