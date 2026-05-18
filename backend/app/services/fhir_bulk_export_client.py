"""
SMART Bulk Data v2 client for FHIR $export.

Implements the client side of the HL7 SMART Bulk Data Access v2 specification:
  https://hl7.org/fhir/uv/bulkdata/

Works with any adapter that exposes `_auth_headers()` and `base_url`
(e.g. OpenEMRFhirAdapter).  All network calls use httpx with explicit
timeouts; no call blocks longer than `max_wait_seconds`.
"""
from __future__ import annotations

import io
import json
import logging
import time
from typing import Any, Generator, Iterable
from urllib.parse import urlencode

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_TYPES: tuple[str, ...] = (
    "DocumentReference",
    "Condition",
    "Encounter",
    "Observation",
    "Patient",
)
_KICKOFF_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
_POLL_TIMEOUT = httpx.Timeout(60.0, connect=10.0)
_DOWNLOAD_TIMEOUT = httpx.Timeout(300.0, connect=10.0)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class BulkExportTimeoutError(TimeoutError):
    """Raised when poll_export exceeds max_wait_seconds."""

    def __init__(self, polling_url: str, elapsed: float) -> None:
        self.polling_url = polling_url
        self.elapsed = elapsed
        super().__init__(
            f"Bulk export did not complete after {elapsed:.0f}s: {polling_url}"
        )


class BulkExportKickoffError(RuntimeError):
    """Raised when the $export kickoff request fails."""


class BulkExportDownloadError(RuntimeError):
    """Raised when a manifest output file download fails."""


# ---------------------------------------------------------------------------
# Kickoff helpers
# ---------------------------------------------------------------------------


def _build_export_params(
    since: str | None,
    types: Iterable[str],
) -> dict[str, str]:
    """Build _type / _since query params per the SMART bulk spec."""
    params: dict[str, str] = {}
    type_list = list(types)
    if type_list:
        params["_type"] = ",".join(type_list)
    if since:
        params["_since"] = since
    return params


def kickoff_group_export(
    adapter: Any,
    group_id: str | None = None,
    since: str | None = None,
    types: tuple[str, ...] = DEFAULT_TYPES,
) -> str:
    """POST {base}/Group/{group_id}/$export (SMART Bulk Data v2).

    Args:
        adapter:   Any FHIR adapter with ``_auth_headers()`` and ``base_url``.
        group_id:  FHIR Group resource ID. Falls back to ``"all"`` if None.
        since:     ISO-8601 date-time string for incremental export.
        types:     FHIR resource types to include.

    Returns:
        The polling URL from the ``Content-Location`` response header.

    Raises:
        BulkExportKickoffError on any non-202 response.
    """
    gid = group_id or "all"
    url = f"{adapter.base_url}/Group/{gid}/$export"
    params = _build_export_params(since, types)
    headers = {
        **adapter._auth_headers(),
        "Accept": "application/fhir+json",
        "Prefer": "respond-async",
    }
    logger.info("FHIR bulk export kickoff: %s params=%s", url, params)
    resp = httpx.post(url, headers=headers, params=params, timeout=_KICKOFF_TIMEOUT)
    if resp.status_code != 202:
        raise BulkExportKickoffError(
            f"Group $export kickoff returned {resp.status_code}: {resp.text[:300]}"
        )
    polling_url = resp.headers.get("Content-Location") or ""
    if not polling_url:
        raise BulkExportKickoffError(
            "Group $export kickoff: 202 received but no Content-Location header"
        )
    logger.info("FHIR bulk export polling URL: %s", polling_url)
    return polling_url


def kickoff_patient_export(
    adapter: Any,
    patient_id: str,
    since: str | None = None,
    types: tuple[str, ...] = DEFAULT_TYPES,
) -> str:
    """POST {base}/Patient/{id}/$export.

    Args:
        adapter:    FHIR adapter with ``_auth_headers()`` and ``base_url``.
        patient_id: FHIR Patient resource ID.
        since:      ISO-8601 date-time string for incremental export.
        types:      FHIR resource types to include.

    Returns:
        The polling URL from the ``Content-Location`` response header.

    Raises:
        BulkExportKickoffError on any non-202 response.
    """
    url = f"{adapter.base_url}/Patient/{patient_id}/$export"
    params = _build_export_params(since, types)
    headers = {
        **adapter._auth_headers(),
        "Accept": "application/fhir+json",
        "Prefer": "respond-async",
    }
    logger.info(
        "FHIR patient bulk export kickoff: %s params=%s", url, params
    )
    resp = httpx.post(url, headers=headers, params=params, timeout=_KICKOFF_TIMEOUT)
    if resp.status_code != 202:
        raise BulkExportKickoffError(
            f"Patient $export kickoff returned {resp.status_code}: {resp.text[:300]}"
        )
    polling_url = resp.headers.get("Content-Location") or ""
    if not polling_url:
        raise BulkExportKickoffError(
            "Patient $export kickoff: 202 received but no Content-Location header"
        )
    logger.info("FHIR patient bulk export polling URL: %s", polling_url)
    return polling_url


# ---------------------------------------------------------------------------
# Polling
# ---------------------------------------------------------------------------


def poll_export(
    adapter: Any,
    polling_url: str,
    max_wait_seconds: int = 600,
) -> dict[str, Any]:
    """Poll ``polling_url`` until the export completes or the timeout expires.

    Back-off strategy:
    - Start at 2 seconds.
    - Exponential back-off, capped at 30 seconds.
    - If the server sends a ``Retry-After`` header, that value is honored
      (but never exceeds the remaining budget).

    Args:
        adapter:           FHIR adapter — used only for auth headers.
        polling_url:       URL returned in ``Content-Location`` from kickoff.
        max_wait_seconds:  Wall-clock budget. Raises ``BulkExportTimeoutError``
                           if exceeded.

    Returns:
        The parsed manifest JSON (dict) when the server responds with 200.

    Raises:
        BulkExportTimeoutError:  Time budget exhausted.
        BulkExportKickoffError:  Server responded with an error status.
    """
    deadline = time.monotonic() + max_wait_seconds
    delay = 2.0
    max_delay = 30.0
    elapsed_start = time.monotonic()

    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise BulkExportTimeoutError(
                polling_url, time.monotonic() - elapsed_start
            )

        headers = {
            **adapter._auth_headers(),
            "Accept": "application/json",
        }
        resp = httpx.get(polling_url, headers=headers, timeout=_POLL_TIMEOUT)

        if resp.status_code == 200:
            logger.info("FHIR bulk export complete: %s", polling_url)
            return resp.json()

        if resp.status_code == 202:
            # Still in progress — compute next sleep from Retry-After or back-off
            retry_after_raw = resp.headers.get("Retry-After") or ""
            try:
                retry_after = float(retry_after_raw)
            except (ValueError, TypeError):
                retry_after = None

            sleep_for = retry_after if retry_after and retry_after > 0 else delay
            sleep_for = min(sleep_for, max_delay, remaining - 0.1)
            if sleep_for <= 0:
                raise BulkExportTimeoutError(
                    polling_url, time.monotonic() - elapsed_start
                )
            logger.debug(
                "FHIR bulk export in progress; sleeping %.1fs (retry-after=%s)",
                sleep_for,
                retry_after_raw or "none",
            )
            time.sleep(sleep_for)
            # Exponential back-off for next iteration
            delay = min(delay * 2, max_delay)
            continue

        # Any other status code is an error
        raise BulkExportKickoffError(
            f"Bulk export poll returned unexpected status {resp.status_code}: "
            f"{resp.text[:300]}"
        )


# ---------------------------------------------------------------------------
# Manifest download
# ---------------------------------------------------------------------------


def download_manifest_files(
    adapter: Any,
    manifest: dict[str, Any],
) -> Generator[tuple[str, dict[str, Any]], None, None]:
    """Yield ``(resource_type, resource_dict)`` for every row in all output files.

    Supports plain NDJSON and gzip-compressed responses (``Content-Encoding:
    gzip`` or ``.ndjson.gz`` file names).  Gzip support is lazy-imported only
    when the first compressed file is encountered.

    Args:
        adapter:   FHIR adapter used for auth headers.
        manifest:  Parsed manifest JSON from ``poll_export``.

    Yields:
        ``(resource_type, line_dict)`` tuples — one per non-empty NDJSON line.

    Raises:
        BulkExportDownloadError:  HTTP error downloading any output file.
    """
    output_files: list[dict[str, Any]] = manifest.get("output") or []
    auth_headers = adapter._auth_headers()

    for file_entry in output_files:
        resource_type: str = file_entry.get("type") or "Unknown"
        output_url: str = file_entry.get("url") or ""
        if not output_url:
            logger.warning("Manifest entry missing url: %s", file_entry)
            continue

        logger.info(
            "Downloading bulk export file: type=%s url=%s", resource_type, output_url
        )
        resp = httpx.get(
            output_url,
            headers={**auth_headers, "Accept": "application/ndjson"},
            timeout=_DOWNLOAD_TIMEOUT,
        )
        if resp.status_code != 200:
            raise BulkExportDownloadError(
                f"Failed to download {output_url}: HTTP {resp.status_code}"
            )

        # Detect gzip: check Content-Encoding or URL suffix
        content_encoding = resp.headers.get("Content-Encoding") or ""
        is_gzip = (
            "gzip" in content_encoding.lower()
            or output_url.endswith(".gz")
        )

        raw_bytes: bytes = resp.content
        if is_gzip:
            import gzip as _gzip  # lazy import — only when needed
            raw_bytes = _gzip.decompress(raw_bytes)

        # Parse NDJSON
        for raw_line in raw_bytes.splitlines():
            line = raw_line.strip() if isinstance(raw_line, bytes) else raw_line.strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError as exc:
                logger.warning(
                    "Skipping malformed NDJSON line (%s): %s",
                    resource_type,
                    exc,
                )
                continue
            yield resource_type, parsed
