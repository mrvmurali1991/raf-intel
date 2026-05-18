"""
Reveleer bi-directional API client.

Reveleer (post-Curation Health acquisition, Nov 2024) is a top-3 MA
risk-adjustment platform.  This client handles:

  - Pulling retrieved charts from Reveleer for Gemini vision processing.
  - Pushing our HCC suspect findings back to Reveleer's workflow queue.

Environment variables
---------------------
REVELEER_API_BASE      — e.g. https://api.reveleer.com
REVELEER_API_KEY       — bearer token / API key
REVELEER_TENANT_ID     — Reveleer tenant / org identifier

Usage
-----
    client = ReveleerClient.from_env()
    charts = client.list_retrieved_charts(since="2026-05-01T00:00:00Z")
    data, mime = client.download_chart(charts[0]["chart_id"])
    result = client.submit_hcc_suspects("EXT-001", suspects=[...])
"""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_BASE = "https://api.reveleer.com"


class ReveleerClient:
    """Thin HTTP wrapper for the Reveleer v2 REST API.

    All network I/O is performed with ``httpx`` (lazy-imported to avoid
    import-time overhead in processes that do not use Reveleer).
    """

    def __init__(
        self,
        api_base: str,
        api_key: str,
        tenant_id: str,
        timeout: float = 60.0,
    ) -> None:
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self.tenant_id = tenant_id
        self.timeout = timeout

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_env(cls) -> "ReveleerClient":
        """Construct a client from standard environment variables."""
        return cls(
            api_base=os.environ.get("REVELEER_API_BASE", _DEFAULT_BASE),
            api_key=os.environ["REVELEER_API_KEY"],
            tenant_id=os.environ["REVELEER_TENANT_ID"],
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "X-Reveleer-Tenant": self.tenant_id,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        import httpx  # lazy import

        url = f"{self.api_base}{path}"
        logger.debug("ReveleerClient GET %s params=%s", url, params)
        response = httpx.get(
            url, headers=self._headers(), params=params or {}, timeout=self.timeout
        )
        response.raise_for_status()
        return response

    def _post(self, path: str, body: dict[str, Any]) -> Any:
        import httpx  # lazy import

        url = f"{self.api_base}{path}"
        logger.debug("ReveleerClient POST %s", url)
        response = httpx.post(
            url, headers=self._headers(), json=body, timeout=self.timeout
        )
        response.raise_for_status()
        return response

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_retrieved_charts(
        self,
        since: str | None = None,
        status: str = "ready",
    ) -> list[dict]:
        """Return metadata for charts that Reveleer has retrieved.

        Parameters
        ----------
        since:
            ISO-8601 datetime string.  Only charts updated after this
            timestamp are returned (uses ``since`` query parameter).
        status:
            Reveleer chart status filter.  Defaults to ``"ready"``.

        Returns
        -------
        list[dict]
            Each dict contains at minimum:
            ``chart_id``, ``patient_external_id``, ``filename``,
            ``mimetype``, ``size_bytes``, ``retrieved_at``.
        """
        params: dict[str, Any] = {"status": status}
        if since:
            params["since"] = since

        resp = self._get("/api/v2/chart-retrievals", params=params)
        payload = resp.json()
        charts: list[dict] = payload.get("charts", payload) if isinstance(payload, dict) else payload
        logger.info(
            "ReveleerClient.list_retrieved_charts: %d charts (status=%s, since=%s)",
            len(charts),
            status,
            since,
        )
        return charts

    def download_chart(self, chart_id: str) -> tuple[bytes, str]:
        """Download binary chart content.

        Parameters
        ----------
        chart_id:
            Reveleer chart identifier returned by ``list_retrieved_charts``.

        Returns
        -------
        tuple[bytes, str]
            ``(raw_bytes, mimetype)`` — mimetype comes from the
            ``Content-Type`` response header (falls back to
            ``application/octet-stream``).
        """
        import httpx  # lazy import

        url = f"{self.api_base}/api/v2/chart-retrievals/{chart_id}/download"
        logger.debug("ReveleerClient.download_chart: %s", chart_id)
        response = httpx.get(
            url,
            headers={k: v for k, v in self._headers().items() if k != "Accept"},
            timeout=self.timeout,
            follow_redirects=True,
        )
        response.raise_for_status()
        mimetype = response.headers.get("content-type", "application/octet-stream").split(";")[0].strip()
        logger.info(
            "ReveleerClient.download_chart: chart_id=%s size=%d mime=%s",
            chart_id,
            len(response.content),
            mimetype,
        )
        return response.content, mimetype

    def submit_hcc_suspects(
        self,
        patient_external_id: str,
        suspects: list[dict],
    ) -> dict:
        """Push HCC suspects to Reveleer's workflow queue.

        Reveleer rejects suspects with an empty ``evidence_sentence``; callers
        are expected to filter those out before calling this method, but this
        method enforces the constraint as a safety net.

        Parameters
        ----------
        patient_external_id:
            Reveleer's patient identifier.
        suspects:
            Each entry must contain:
            ``hcc``, ``icd10``, ``confidence``, ``evidence_sentence``,
            ``source_document_id``.

        Returns
        -------
        dict
            Reveleer response payload (``response_id``, ``accepted``, etc.).
        """
        valid = [s for s in suspects if s.get("evidence_sentence", "").strip()]
        if len(valid) < len(suspects):
            logger.warning(
                "ReveleerClient.submit_hcc_suspects: dropped %d suspects with empty evidence",
                len(suspects) - len(valid),
            )

        body: dict[str, Any] = {
            "patient_external_id": patient_external_id,
            "suspects": valid,
        }
        resp = self._post("/api/v2/hcc-suspects/bulk", body)
        result: dict = resp.json()
        logger.info(
            "ReveleerClient.submit_hcc_suspects: patient=%s accepted=%s response_id=%s",
            patient_external_id,
            result.get("accepted"),
            result.get("response_id"),
        )
        return result
