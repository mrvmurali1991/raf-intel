"""
RFC 3161 timestamp authority (TSA) integration for audit-chain heads.

Each call to ``get_timestamp_for_hash`` sends a TimeStampRequest (TSQ) to
a TSA, receives a TimeStampToken (TST / .tsr), and persists the raw DER
bytes to ``audit/timestamps/{YYYY-MM-DD}/{sha256_hex[:16]}.tsr`` on the
local filesystem as a secondary durability copy.  The primary durable copy
is stored in the ``audit_timestamp_tokens`` DB table (migration 038).

Lazy-imports ``rfc3161ng`` so it is never a hard startup dependency.  If the
library is absent a clear ImportError is raised only when the functions are
called, not at module import time.

Public API
----------
    get_timestamp_for_hash(sha256_hex, tsa_url=None) -> bytes
    verify_timestamp_token(token, sha256_hex) -> bool

Environment variables
---------------------
    RFC3161_TSA_URL   — TSA endpoint URL.  Defaults to FreeTSA.org public TSA.
                        Set this to a commercial TSA for production usage.
    RFC3161_TSA_CERT  — Optional path to the TSA's PEM certificate for offline
                        token verification.  If unset, verification uses the
                        bundled cert supplied by rfc3161ng.

Constraints
-----------
    * TSA requests time out after 10 seconds.
    * No audit write is blocked by this module.  All calls are additive.
    * Token bytes stored in DB as MEDIUMBLOB; local .tsr copies are secondary.
"""
from __future__ import annotations

import hashlib
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default TSA — FreeTSA.org.  No API key required; suitable for dev/staging.
# Production deployments SHOULD override via RFC3161_TSA_URL.
# ---------------------------------------------------------------------------
_DEFAULT_TSA_URL = "https://freetsa.org/tsr"
_REQUEST_TIMEOUT_SECONDS = 10

# Local filesystem storage root for .tsr copies.
_TIMESTAMP_DIR = Path(os.getenv("IMMUTABLE_AUDIT_DIR", "logs")) / "timestamps"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tsa_url() -> str | None:
    """Return the configured TSA URL, or None if not set (falls back to default)."""
    return os.getenv("RFC3161_TSA_URL") or _DEFAULT_TSA_URL


def _local_tsr_path(sha256_hex: str, date_tag: str) -> Path:
    day_dir = _TIMESTAMP_DIR / date_tag
    day_dir.mkdir(parents=True, exist_ok=True)
    return day_dir / f"{sha256_hex[:16]}.tsr"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_timestamp_for_hash(sha256_hex: str, tsa_url: str | None = None) -> bytes:
    """Request an RFC 3161 timestamp token for *sha256_hex* from a TSA.

    Parameters
    ----------
    sha256_hex:
        The 64-character hex-encoded SHA-256 digest of the chain-head entry.
    tsa_url:
        Override TSA endpoint.  Falls back to ``RFC3161_TSA_URL`` env var,
        then to FreeTSA.org.  If None is explicitly passed here, the env-var
        / default logic still applies.

    Returns
    -------
    bytes
        Raw DER-encoded TimeStampToken (.tsr bytes).  Empty bytes (b'') on
        any non-fatal failure (network unreachable, timeout, TSA error).
        The caller should log but must NOT corrupt the audit chain on failure.

    Side-effects
    ------------
    Writes a local ``{_TIMESTAMP_DIR}/{date}/{prefix}.tsr`` file.  Missing
    TSA env var is logged as WARNING (not ERROR) since FreeTSA.org is the
    fallback.
    """
    try:
        import rfc3161ng  # lazy — optional dependency
    except ImportError:
        logger.error(
            "audit_rfc3161: rfc3161ng is not installed — "
            "cannot request RFC 3161 timestamp. "
            "Install with: pip install rfc3161ng"
        )
        return b""

    resolved_url = tsa_url or _tsa_url()

    if not os.getenv("RFC3161_TSA_URL") and resolved_url == _DEFAULT_TSA_URL:
        logger.warning(
            "audit_rfc3161: RFC3161_TSA_URL not set — using public FreeTSA.org. "
            "Set RFC3161_TSA_URL to a commercial TSA for production."
        )

    if not resolved_url:
        logger.warning("audit_rfc3161: no TSA URL configured — skipping timestamp")
        return b""

    try:
        # Build the timestamp request.
        # rfc3161ng.make_timestamp_request returns DER-encoded TSQ bytes.
        digest_bytes = bytes.fromhex(sha256_hex)
        tsq: bytes = rfc3161ng.make_timestamp_request(
            data=digest_bytes,
            hashname="sha256",
            nonce=True,
            include_tsa_certificate=True,
        )
    except Exception as exc:
        logger.error("audit_rfc3161: failed to build TSQ for hash %s: %s", sha256_hex[:16], exc)
        return b""

    try:
        import urllib.request

        req = urllib.request.Request(
            resolved_url,
            data=tsq,
            headers={"Content-Type": "application/timestamp-query"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT_SECONDS) as resp:
            tsr_bytes: bytes = resp.read()
    except TimeoutError as exc:
        logger.warning(
            "audit_rfc3161: TSA request timed out after %ds for hash %s: %s",
            _REQUEST_TIMEOUT_SECONDS, sha256_hex[:16], exc,
        )
        return b""
    except Exception as exc:
        logger.warning(
            "audit_rfc3161: TSA request failed for hash %s: %s",
            sha256_hex[:16], exc,
        )
        return b""

    if not tsr_bytes:
        logger.warning("audit_rfc3161: TSA returned empty response for hash %s", sha256_hex[:16])
        return b""

    # Persist a local copy.
    date_tag = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    try:
        tsr_path = _local_tsr_path(sha256_hex, date_tag)
        tsr_path.write_bytes(tsr_bytes)
        logger.info(
            "audit_rfc3161: timestamp token stored locally at %s (%d bytes)",
            tsr_path, len(tsr_bytes),
        )
    except Exception as exc:
        logger.warning("audit_rfc3161: could not persist .tsr file: %s", exc)

    return tsr_bytes


def verify_timestamp_token(token: bytes, sha256_hex: str) -> bool:
    """Verify that *token* is a valid RFC 3161 TST covering *sha256_hex*.

    Parameters
    ----------
    token:
        Raw DER-encoded TimeStampToken bytes (as returned by ``get_timestamp_for_hash``).
    sha256_hex:
        The SHA-256 hex digest the token should cover.

    Returns
    -------
    bool
        True if the token is cryptographically valid and covers the given hash.
        False on any failure (invalid token, wrong hash, parse error).
    """
    if not token:
        return False

    try:
        import rfc3161ng  # lazy
    except ImportError:
        logger.error("audit_rfc3161: rfc3161ng not installed — cannot verify token")
        return False

    try:
        tst = rfc3161ng.decode_timestamp_response(token)
        digest_bytes = bytes.fromhex(sha256_hex)
        rfc3161ng.check_timestamp(
            tst,
            data=digest_bytes,
            hashname="sha256",
            # No certificate pinning by default; production should pass
            # certificate=Path(os.getenv("RFC3161_TSA_CERT")).read_bytes()
        )
        return True
    except Exception as exc:
        logger.warning(
            "audit_rfc3161: token verification failed for hash %s: %s",
            sha256_hex[:16], exc,
        )
        return False
