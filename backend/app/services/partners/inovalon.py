"""
Inovalon Electronic Record On Demand — FHIR pull client.

Inovalon's platform provides unified access to structured + unstructured
clinical data from Epic, Cerner, Athena, eClinicalWorks, NextGen, and
Allscripts via a single FHIR R4 API.  Unlike chart-retrieval brokers
(Datavant, Ciox), Inovalon performs structured-data extraction, so callers
receive FHIR resources (Condition, Observation, DocumentReference, etc.)
rather than raw PDFs.

Configuration (all resolved from environment at instantiation):
    INOVALON_API_BASE       — e.g. https://api.inovalon.com/erond
    INOVALON_CLIENT_ID      — OAuth2 client_credentials client ID
    INOVALON_CLIENT_SECRET  — OAuth2 client_credentials client secret
    INOVALON_TOKEN_URL      — Token endpoint, defaults to
                              {INOVALON_API_BASE}/oauth2/token

All HTTP calls use a 30-second timeout with up to 3 retries on 429/5xx
via tenacity.  httpx is lazily imported so the module loads in test
environments that do not install the dependency.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

_HTTP_TIMEOUT = 30.0
# Refresh a token 60 s before it actually expires to avoid races.
_TOKEN_REFRESH_BUFFER_S = 60

_DEFAULT_SECTIONS = (
    "conditions",
    "medications",
    "observations",
    "encounters",
    "documents",
)


def _is_retryable(exc: BaseException) -> bool:
    """Return True for transient HTTP errors that should be retried."""
    try:
        import httpx  # noqa: PLC0415

        if isinstance(exc, httpx.HTTPStatusError):
            return exc.response.status_code in (429, 500, 502, 503, 504)
        if isinstance(exc, (httpx.ConnectError, httpx.ReadTimeout)):
            return True
    except ImportError:
        pass
    return False


_retry_policy = retry(
    retry=retry_if_exception(_is_retryable),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=16),
    reraise=True,
)


class InovalonClient:
    """REST client for the Inovalon Electronic Record On Demand API.

    Parameters are resolved from environment variables when not supplied
    explicitly, making test injection straightforward.

    Args:
        api_base: Base URL for the Inovalon EROND API.
        client_id: OAuth2 client_credentials client ID.
        client_secret: OAuth2 client_credentials client secret.
        token_url: OAuth2 token endpoint.  Defaults to
            ``{api_base}/oauth2/token``.
    """

    def __init__(
        self,
        api_base: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        token_url: str | None = None,
    ) -> None:
        self.api_base = (api_base or os.getenv("INOVALON_API_BASE", "")).rstrip("/")
        self.client_id = client_id or os.getenv("INOVALON_CLIENT_ID", "")
        self.client_secret = client_secret or os.getenv("INOVALON_CLIENT_SECRET", "")
        self.token_url = (
            token_url
            or os.getenv("INOVALON_TOKEN_URL", "")
            or f"{self.api_base}/oauth2/token"
        )
        # In-process token cache: {"access_token": str, "expires_at": float}
        self._token_cache: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Configuration guard
    # ------------------------------------------------------------------

    def _assert_configured(self) -> None:
        missing = [
            name
            for name, val in [
                ("INOVALON_API_BASE", self.api_base),
                ("INOVALON_CLIENT_ID", self.client_id),
                ("INOVALON_CLIENT_SECRET", self.client_secret),
            ]
            if not val
        ]
        if missing:
            raise RuntimeError(
                f"InovalonClient: missing required config: {', '.join(missing)}"
            )

    @property
    def is_configured(self) -> bool:
        """Return True when all three required env vars are present."""
        return bool(self.api_base and self.client_id and self.client_secret)

    # ------------------------------------------------------------------
    # OAuth2 token management
    # ------------------------------------------------------------------

    def _token_expired(self) -> bool:
        expires_at = self._token_cache.get("expires_at", 0.0)
        return time.time() >= expires_at - _TOKEN_REFRESH_BUFFER_S

    def _token(self) -> str:
        """Return a valid access token, fetching a new one when expired.

        Uses client_credentials grant.  The token is cached in memory for
        its TTL minus a 60-second safety buffer.
        """
        if self._token_cache.get("access_token") and not self._token_expired():
            return self._token_cache["access_token"]  # type: ignore[return-value]

        import httpx  # noqa: PLC0415

        self._assert_configured()
        logger.debug("inovalon: fetching new OAuth2 token")
        with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
            resp = client.post(
                self.token_url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "scope": "fhir.read erond.pull",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            resp.raise_for_status()

        data = resp.json()
        access_token: str = data["access_token"]
        expires_in: int = int(data.get("expires_in", 3600))
        self._token_cache = {
            "access_token": access_token,
            "expires_at": time.time() + expires_in,
        }
        logger.debug("inovalon: token cached, expires_in=%d s", expires_in)
        return access_token

    # ------------------------------------------------------------------
    # Internal HTTP helpers
    # ------------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @_retry_policy
    def pull_patient_record(
        self,
        patient_demographics: dict[str, Any],
        sections: tuple[str, ...] | list[str] = _DEFAULT_SECTIONS,
    ) -> dict[str, Any]:
        """Submit an asynchronous pull request for a patient's FHIR record.

        Args:
            patient_demographics: Dict with keys such as ``first_name``,
                ``last_name``, ``dob`` (YYYY-MM-DD), ``member_id``,
                ``gender``, and optionally ``ssn_last4``.
            sections: FHIR resource categories to include in the pull.
                Defaults to conditions, medications, observations,
                encounters, and documents.

        Returns:
            Dict with ``pull_id``, ``status``, and ``submitted_at``.
        """
        import httpx  # noqa: PLC0415

        self._assert_configured()
        payload: dict[str, Any] = {
            "patient": patient_demographics,
            "sections": list(sections),
        }
        url = f"{self.api_base}/v2/patient-record/pull"
        logger.info(
            "inovalon: submitting pull for patient %s",
            patient_demographics.get("member_id", "<unknown>"),
        )
        with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
            resp = client.post(url, json=payload, headers=self._headers())
            resp.raise_for_status()

        data = resp.json()
        return {
            "pull_id": data["pull_id"],
            "status": data.get("status", "submitted"),
            "submitted_at": data.get("submitted_at", ""),
        }

    @_retry_policy
    def get_pull_status(self, pull_id: str) -> dict[str, Any]:
        """Poll the status of an outstanding pull request.

        Args:
            pull_id: The Inovalon pull ID returned by
                :meth:`pull_patient_record`.

        Returns:
            Dict with ``pull_id``, ``status`` (one of ``submitted``,
            ``processing``, ``completed``, ``failed``), ``resources_returned``
            (dict of resource-type -> count), ``bundle_size_bytes``, and
            ``completed_at``.
        """
        import httpx  # noqa: PLC0415

        self._assert_configured()
        url = f"{self.api_base}/v2/patient-record/pull/{pull_id}"
        logger.debug("inovalon: polling pull status pull_id=%s", pull_id)
        with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
            resp = client.get(url, headers=self._headers())
            resp.raise_for_status()

        data = resp.json()
        return {
            "pull_id": pull_id,
            "status": data.get("status", "unknown"),
            "resources_returned": data.get("resources_returned", {}),
            "bundle_size_bytes": data.get("bundle_size_bytes", 0),
            "completed_at": data.get("completed_at", ""),
        }

    @_retry_policy
    def download_bundle(self, pull_id: str) -> bytes:
        """Download the NDJSON FHIR bundle for a completed pull.

        Args:
            pull_id: The Inovalon pull ID for a *completed* pull request.

        Returns:
            Raw NDJSON bytes (one FHIR resource JSON object per line).
        """
        import httpx  # noqa: PLC0415

        self._assert_configured()
        url = f"{self.api_base}/v2/patient-record/pull/{pull_id}/bundle"
        logger.info("inovalon: downloading bundle pull_id=%s", pull_id)
        with httpx.Client(timeout=120.0) as client:  # larger timeout for bundles
            resp = client.get(
                url,
                headers={**self._headers(), "Accept": "application/x-ndjson"},
            )
            resp.raise_for_status()
        return resp.content

    @_retry_policy
    def fetch_binary(self, binary_url: str) -> tuple[bytes, str]:
        """Fetch a DocumentReference binary attachment from Inovalon.

        Args:
            binary_url: Absolute URL from ``DocumentReference.content
                .attachment.url``.

        Returns:
            Tuple of ``(content_bytes, content_type)``.
        """
        import httpx  # noqa: PLC0415

        self._assert_configured()
        logger.debug("inovalon: fetching binary %s", binary_url)
        with httpx.Client(timeout=120.0) as client:
            resp = client.get(binary_url, headers=self._headers())
            resp.raise_for_status()
        return resp.content, resp.headers.get("content-type", "application/octet-stream")
