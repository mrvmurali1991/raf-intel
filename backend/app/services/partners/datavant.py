"""
Datavant Switchboard API client.

Datavant (merged with Ciox, Oct 2024) operates the largest chart-retrieval
network in Medicare Advantage — a single integration unlocks 140+ health plan
EHRs without per-plan engineering.

Configuration (all read from environment at import time):
    DATAVANT_API_BASE       — e.g. https://api.switchboard.datavant.com
    DATAVANT_API_KEY        — partner API key issued by Datavant
    DATAVANT_CUSTOMER_ID    — your Datavant customer account identifier

All HTTP calls use a 30-second timeout and up to 2 retries on 502/503 via
tenacity.  httpx is lazily imported so the module loads cleanly in test
environments without the dependency installed in the test venv.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Sentinel for "not configured" — checked at call time so tests can set env
# vars before instantiation.
# ---------------------------------------------------------------------------
_UNSET = object()

_HTTP_TIMEOUT = 30.0  # seconds


def _is_retryable(exc: BaseException) -> bool:
    """Return True for 502 / 503 HTTP errors that warrant a retry."""
    try:
        import httpx  # noqa: PLC0415
        if isinstance(exc, httpx.HTTPStatusError):
            return exc.response.status_code in (502, 503)
    except ImportError:
        pass
    return False


class DatavantClient:
    """REST client for the Datavant Switchboard chart-retrieval API.

    Parameters are resolved from environment variables when not supplied
    explicitly, allowing easy injection in tests.

    Args:
        api_base: Base URL of the Switchboard API.
        api_key: Partner API key.
        customer_id: Datavant customer account identifier.
    """

    def __init__(
        self,
        api_base: str | None = None,
        api_key: str | None = None,
        customer_id: str | None = None,
    ) -> None:
        self.api_base = (api_base or os.getenv("DATAVANT_API_BASE", "")).rstrip("/")
        self.api_key = api_key or os.getenv("DATAVANT_API_KEY", "")
        self.customer_id = customer_id or os.getenv("DATAVANT_CUSTOMER_ID", "")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "X-Datavant-Customer-Id": self.customer_id,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _assert_configured(self) -> None:
        missing = [
            name
            for name, val in [
                ("DATAVANT_API_BASE", self.api_base),
                ("DATAVANT_API_KEY", self.api_key),
                ("DATAVANT_CUSTOMER_ID", self.customer_id),
            ]
            if not val
        ]
        if missing:
            raise RuntimeError(
                f"DatavantClient: missing required config: {', '.join(missing)}"
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @retry(
        retry=retry_if_exception(_is_retryable),
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    def submit_chart_request(
        self,
        patient_demographics: dict[str, Any],
        date_of_service_from: str,
        date_of_service_to: str,
        reason: str,
    ) -> dict[str, Any]:
        """Submit a new chart retrieval request to the Switchboard.

        Args:
            patient_demographics: Dict with keys such as ``first_name``,
                ``last_name``, ``dob``, ``member_id``.
            date_of_service_from: ISO-8601 date string (``YYYY-MM-DD``).
            date_of_service_to: ISO-8601 date string (``YYYY-MM-DD``).
            reason: Clinical reason for the request (e.g. "RAF risk adjustment").

        Returns:
            Dict with ``request_id``, ``status``, and
            ``estimated_turnaround_days``.
        """
        import httpx  # noqa: PLC0415

        self._assert_configured()
        payload: dict[str, Any] = {
            "customer_id": self.customer_id,
            "patient": patient_demographics,
            "date_of_service_from": date_of_service_from,
            "date_of_service_to": date_of_service_to,
            "reason": reason,
        }
        url = f"{self.api_base}/api/v1/chart-requests"
        logger.info("datavant: submitting chart request for patient %s", patient_demographics.get("member_id", "<unknown>"))
        with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
            resp = client.post(url, json=payload, headers=self._headers())
            resp.raise_for_status()
        data = resp.json()
        return {
            "request_id": data["request_id"],
            "status": data.get("status", "submitted"),
            "estimated_turnaround_days": data.get("estimated_turnaround_days", 3),
        }

    @retry(
        retry=retry_if_exception(_is_retryable),
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    def get_chart_request_status(self, request_id: str) -> dict[str, Any]:
        """Poll the status of an existing chart request.

        Args:
            request_id: The Datavant request ID returned by
                :meth:`submit_chart_request`.

        Returns:
            Dict with ``status`` and ``documents_available`` (list of dicts
            each containing at least ``document_id`` and ``filename``).
        """
        import httpx  # noqa: PLC0415

        self._assert_configured()
        url = f"{self.api_base}/api/v1/chart-requests/{request_id}"
        logger.info("datavant: polling status for request %s", request_id)
        with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
            resp = client.get(url, headers=self._headers())
            resp.raise_for_status()
        data = resp.json()
        return {
            "status": data.get("status", "unknown"),
            "documents_available": data.get("documents_available", []),
        }

    @retry(
        retry=retry_if_exception(_is_retryable),
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    def download_document(self, document_id: str) -> tuple[bytes, str]:
        """Download the binary content of a retrieved chart document.

        Args:
            document_id: Datavant document identifier (from
                ``documents_available`` in a status response).

        Returns:
            Tuple of ``(content_bytes, mimetype)`` where ``mimetype`` is the
            value from the ``Content-Type`` response header (defaulting to
            ``application/octet-stream``).
        """
        import httpx  # noqa: PLC0415

        self._assert_configured()
        url = f"{self.api_base}/api/v1/documents/{document_id}/download"
        logger.info("datavant: downloading document %s", document_id)
        with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
            resp = client.get(url, headers=self._headers())
            resp.raise_for_status()
        mimetype = resp.headers.get("content-type", "application/octet-stream")
        return resp.content, mimetype
