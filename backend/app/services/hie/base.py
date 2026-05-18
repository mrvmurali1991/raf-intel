"""Abstract base class for HIE network adapters.

All adapters share:
  - mTLS credential loading from env vars
  - Per-network asyncio rate-limit (1 patient query / 2 s)
  - Standard FHIR R4 Bundle parsing helpers
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)

# Rate-limit: CommonWell and Carequality specs require no more than
# 1 patient-level query every 2 seconds per originating system.
_RATE_LIMIT_SECS: float = 2.0

# Per-network state: (asyncio.Lock, last_query_wall_time)
_network_rate_state: dict[str, tuple[asyncio.Lock, float]] = {}


def _get_rate_state(network: str) -> tuple[asyncio.Lock, float]:
    if network not in _network_rate_state:
        _network_rate_state[network] = (asyncio.Lock(), 0.0)
    return _network_rate_state[network]


async def _apply_rate_limit(network: str) -> None:
    """Block until the per-network 2-second gate is clear."""
    lock, last = _get_rate_state(network)
    async with lock:
        now = time.monotonic()
        wait = _RATE_LIMIT_SECS - (now - last)
        if wait > 0:
            await asyncio.sleep(wait)
        _network_rate_state[network] = (lock, time.monotonic())


class NetworkNotConfiguredError(Exception):
    """Raised when required mTLS env vars are absent for a network."""


class HIENetworkError(Exception):
    """Raised for non-retryable HTTP or parsing errors from an HIE network."""


def _load_mtls_config(network_upper: str) -> dict[str, str | None]:
    """Load mTLS paths from env vars.

    Expected vars (NETWORK = 'COMMONWELL' or 'CAREQUALITY'):
      HIE_<NETWORK>_CERT_PATH        — path to PEM client certificate
      HIE_<NETWORK>_KEY_PATH         — path to PEM private key
      HIE_<NETWORK>_TRUST_BUNDLE     — path to CA / trust-bundle PEM
    """
    return {
        "cert": os.environ.get(f"HIE_{network_upper}_CERT_PATH"),
        "key": os.environ.get(f"HIE_{network_upper}_KEY_PATH"),
        "ca": os.environ.get(f"HIE_{network_upper}_TRUST_BUNDLE"),
    }


def _assert_configured(cfg: dict[str, str | None], network: str) -> None:
    missing = [k for k, v in cfg.items() if not v]
    if missing:
        raise NetworkNotConfiguredError(
            f"network_not_configured: {network} missing env vars for: "
            + ", ".join(missing)
        )


def _parse_fhir_bundle_entries(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract the 'resource' from each entry in a FHIR Bundle."""
    entries = bundle.get("entry") or []
    return [e["resource"] for e in entries if "resource" in e]


class HIEAdapter(ABC):
    """Abstract interface for FHIR R4-based HIE networks.

    Subclasses implement the three core operations; the base class enforces
    rate-limiting and provides shared mTLS config loading.
    """

    # Subclasses must set these before calling _build_client()
    network_name: str = ""        # 'commonwell' or 'carequality'
    _base_url: str = ""

    def __init__(self) -> None:
        self._cfg = _load_mtls_config(self.network_name.upper())

    def is_configured(self) -> bool:
        """Return True if all required mTLS env vars are present."""
        return all(v for v in self._cfg.values())

    def _build_httpx_client(self) -> Any:
        """Lazy-import httpx and construct an AsyncClient with mTLS."""
        import httpx  # noqa: PLC0415 — intentional lazy import

        _assert_configured(self._cfg, self.network_name)
        return httpx.AsyncClient(
            cert=(self._cfg["cert"], self._cfg["key"]),
            verify=self._cfg["ca"],
            timeout=30.0,
            headers={
                "Accept": "application/fhir+json",
                "Content-Type": "application/fhir+json",
            },
        )

    async def _rate_limited_call(self) -> None:
        await _apply_rate_limit(self.network_name)

    @abstractmethod
    async def discover_patient(
        self,
        first_name: str,
        last_name: str,
        dob: str,
        sex: str,
        mbi: str | None = None,
    ) -> list[dict[str, Any]]:
        """Query the HIE for patient demographic matches.

        Returns a list of candidate dicts, each containing at minimum:
            hie_patient_id: str
            confidence: float  (0.0–1.0)
            name: str
            dob: str
            sex: str
        """

    @abstractmethod
    async def list_document_references(
        self,
        hie_patient_id: str,
        since: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return DocumentReference resources for a known HIE patient.

        Args:
            hie_patient_id: The network-specific patient identifier.
            since: Optional ISO-8601 date string; limits to docs after this date.

        Returns list of FHIR DocumentReference dicts.
        """

    @abstractmethod
    async def fetch_binary(self, binary_ref: str) -> tuple[bytes, str]:
        """Fetch binary content for a DocumentReference.

        Args:
            binary_ref: URL or FHIR reference to a Binary resource.

        Returns (raw_bytes, mime_type).  Falls back to base64-decoded
        FHIR Binary.data if the server does not serve the PDF directly.
        """
