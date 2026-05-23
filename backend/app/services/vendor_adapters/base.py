"""
Base class for all REST API vendor adapters.

Every concrete adapter inherits from ``BaseVendorAdapter`` and must implement
the abstract methods.  The normalised output shapes are documented here so
that all adapters produce identical structures for downstream consumers
(fhir_service, RAF calculator, etc.).

Normalised shapes
-----------------
Patient::

    {
        "external_id": str,          # vendor's patient ID
        "first_name": str,
        "last_name": str,
        "date_of_birth": str,        # YYYY-MM-DD
        "sex": str,                  # M / F / U
        "mrn": str,                  # medical record number (may equal external_id)
        "raw": dict,                 # original payload – kept for debugging
    }

Condition::

    {
        "icd10_code": str,           # e.g. "E11.9"
        "description": str,
        "status": str,               # active | inactive | resolved
        "onset_date": str,           # YYYY-MM-DD or ""
        "patient_external_id": str,
        "raw": dict,
    }

Encounter::

    {
        "external_id": str,
        "patient_external_id": str,
        "encounter_date": str,       # YYYY-MM-DD
        "encounter_type": str,
        "provider": str,
        "raw": dict,
    }

Medication::

    {
        "external_id": str,
        "patient_external_id": str,
        "drug_name": str,
        "status": str,               # active | inactive
        "start_date": str,
        "raw": dict,
    }

Vital::

    {
        "patient_external_id": str,
        "recorded_date": str,
        "type": str,
        "value": str,
        "unit": str,
        "raw": dict,
    }

Lab::

    {
        "patient_external_id": str,
        "result_date": str,
        "test_name": str,
        "value": str,
        "unit": str,
        "abnormal": bool,
        "raw": dict,
    }
"""
from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Shared timeout used by all adapters for individual requests.
_DEFAULT_TIMEOUT = httpx.Timeout(30.0, connect=10.0)

# Maximum number of 429/503 retries before giving up on a single request.
_MAX_RETRIES = 3


class BaseVendorAdapter(ABC):
    """Abstract base class for all REST API vendor adapters.

    Subclasses must set ``vendor_name`` and implement all abstract methods.
    The ``connection`` dict is the decrypted row from ``emr_connections``
    (returned by ``get_connection_with_credentials``).
    """

    vendor_name: str = "unknown"

    def __init__(self, connection: dict[str, Any]) -> None:
        self.connection = connection
        self.connection_id: int = connection.get("id", 0)
        self.base_url: str = (connection.get("api_base_url") or "").rstrip("/")
        self.auth_type: str = (connection.get("api_auth_type") or "bearer").lower()
        self.api_key: str = connection.get("api_key") or ""
        self.client_id: str = connection.get("client_id") or ""
        self.client_secret: str = connection.get("client_secret") or ""
        # vendor-specific overrides stored as JSON in extra_config
        self._extra: dict[str, Any] = {}
        raw_extra = connection.get("extra_config")
        if isinstance(raw_extra, dict):
            self._extra = raw_extra
        elif isinstance(raw_extra, str):
            import json

            try:
                self._extra = json.loads(raw_extra)
            except Exception:  # noqa: BLE001 — best-effort guard
                logger.debug("swallowed exception", exc_info=True)

    # ------------------------------------------------------------------
    # HTTP helpers shared by all adapters
    # ------------------------------------------------------------------

    def _get_auth_headers(self) -> dict[str, str]:
        """Return authentication headers using ``api_key`` / ``auth_type``."""
        headers: dict[str, str] = {"Accept": "application/json"}
        if self.api_key and self.auth_type == "bearer":
            headers["Authorization"] = f"Bearer {self.api_key}"
        elif self.api_key and self.auth_type == "basic":
            import base64

            token = base64.b64encode(f"{self.client_id}:{self.api_key}".encode()).decode()
            headers["Authorization"] = f"Basic {token}"
        return headers

    def _request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        json: Any = None,
        data: Any = None,
        timeout: httpx.Timeout | None = None,
        client: httpx.Client | None = None,
    ) -> httpx.Response:
        """Execute an HTTP request with automatic 429/Retry-After handling.

        Parameters
        ----------
        client:
            If provided, reuse this ``httpx.Client`` instance (useful for
            keeping alive a session with a pre-set ``Authorization`` header).
            The caller is responsible for closing it.
        """
        effective_timeout = timeout or _DEFAULT_TIMEOUT
        _client_managed_here = client is None
        if _client_managed_here:
            client = httpx.Client(timeout=effective_timeout)

        try:
            for attempt in range(1, _MAX_RETRIES + 1):
                resp = client.request(
                    method,
                    url,
                    headers=headers,
                    params=params,
                    json=json,
                    data=data,
                )
                if resp.status_code == 429:
                    retry_after = float(resp.headers.get("Retry-After", "5"))
                    # Cap at 60 s to avoid hanging indefinitely.
                    sleep_s = min(retry_after, 60.0)
                    logger.warning(
                        "vendor_adapter[%s]: 429 rate-limited on %s, sleeping %.1fs (attempt %d/%d)",
                        self.vendor_name,
                        url,
                        sleep_s,
                        attempt,
                        _MAX_RETRIES,
                    )
                    time.sleep(sleep_s)
                    continue
                resp.raise_for_status()
                return resp
            # Exhausted retries
            raise httpx.HTTPStatusError(
                f"Rate-limited after {_MAX_RETRIES} retries",
                request=resp.request,
                response=resp,
            )
        finally:
            if _client_managed_here:
                client.close()

    # ------------------------------------------------------------------
    # Abstract interface — every adapter must implement these
    # ------------------------------------------------------------------

    @abstractmethod
    def authenticate(self) -> dict[str, str]:
        """Return a dict of HTTP headers that authenticate subsequent requests.

        For OAuth2 flows this typically calls the token endpoint and returns
        ``{"Authorization": "Bearer <token>"}``.  For API-key vendors it may
        simply return ``{"X-Api-Key": "<key>"}``.
        """

    @abstractmethod
    def test_connection(self) -> dict[str, Any]:
        """Verify connectivity and credentials.

        Returns
        -------
        dict with keys:
            ``success``    – bool
            ``message``    – human-readable status
            ``latency_ms`` – round-trip time in milliseconds
        """

    @abstractmethod
    def fetch_patients(self, since: str | None = None) -> list[dict[str, Any]]:
        """Fetch patients, optionally modified since *since* (ISO-8601 date).

        Returns a list of normalised patient dicts (see module docstring).
        """

    @abstractmethod
    def fetch_encounters(
        self, patient_id: str, since: str | None = None
    ) -> list[dict[str, Any]]:
        """Fetch encounters for *patient_id*.

        Returns a list of normalised encounter dicts.
        """

    @abstractmethod
    def fetch_conditions(self, patient_id: str) -> list[dict[str, Any]]:
        """Fetch active diagnoses / problem-list entries for *patient_id*.

        Returns a list of normalised condition dicts.  Each dict contains at
        minimum an ``icd10_code`` field (may be empty string when unmapped).
        """

    @abstractmethod
    def fetch_medications(self, patient_id: str) -> list[dict[str, Any]]:
        """Fetch current medications for *patient_id*."""

    @abstractmethod
    def fetch_vitals(self, patient_id: str) -> list[dict[str, Any]]:
        """Fetch vital signs for *patient_id*."""

    @abstractmethod
    def fetch_labs(self, patient_id: str) -> list[dict[str, Any]]:
        """Fetch lab results for *patient_id*."""

    # ------------------------------------------------------------------
    # Default run_sync — subclasses may override for bulk/batch APIs
    # ------------------------------------------------------------------

    def run_sync(
        self,
        sync_type: str = "incremental",
        since: str | None = None,
    ) -> dict[str, Any]:
        """Full sync orchestration.

        Fetches all patients, then conditions for each patient.  Returns a
        summary dict compatible with ``log_sync_result``.

        Subclasses that support bulk or cursor-based APIs should override this
        method for better performance.

        Returns
        -------
        dict with keys:
            ``patients_synced``   – int
            ``conditions_found``  – int
            ``errors``            – list[str]
        """
        errors: list[str] = []
        patients_synced = 0
        conditions_found = 0

        logger.info(
            "vendor_adapter[%s] run_sync started connection_id=%s sync_type=%s since=%s",
            self.vendor_name,
            self.connection_id,
            sync_type,
            since,
        )

        try:
            auth_headers = self.authenticate()
        except Exception as exc:
            msg = f"Authentication failed: {exc}"
            logger.error("vendor_adapter[%s] %s", self.vendor_name, msg)
            return {"patients_synced": 0, "conditions_found": 0, "errors": [msg]}

        try:
            patients = self.fetch_patients(since=since if sync_type == "incremental" else None)
        except Exception as exc:
            msg = f"fetch_patients failed: {exc}"
            logger.error("vendor_adapter[%s] %s", self.vendor_name, msg)
            return {"patients_synced": 0, "conditions_found": 0, "errors": [msg]}

        for patient in patients:
            pid = patient.get("external_id", "")
            try:
                conditions = self.fetch_conditions(pid)
                conditions_found += len(conditions)
                patients_synced += 1
            except Exception as exc:
                msg = f"fetch_conditions failed for patient {pid}: {exc}"
                logger.warning("vendor_adapter[%s] %s", self.vendor_name, msg)
                errors.append(msg)

        logger.info(
            "vendor_adapter[%s] run_sync finished: patients=%d conditions=%d errors=%d",
            self.vendor_name,
            patients_synced,
            conditions_found,
            len(errors),
        )
        return {
            "patients_synced": patients_synced,
            "conditions_found": conditions_found,
            "errors": errors,
        }
