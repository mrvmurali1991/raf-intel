"""
Immutable Audit Log — cryptographic hash-chain audit trail.

Writes append-only JSON Lines to ``logs/immutable_audit.jsonl``.  Each entry
includes a SHA-256 hash that chains to the previous entry, making any
tampering or deletion detectable via ``verify_audit_chain()``.

This satisfies HIPAA §164.312(b) audit-controls by providing a durable,
tamper-evident log independent of the MySQL audit_log table.

Usage:
    from app.services.immutable_audit import append_audit_entry, verify_audit_chain

    append_audit_entry(
        event_type="phi_access",
        user_id=42,
        tenant_id="1",
        resource_type="patient",
        resource_id="123",
        action="view",
    )

    ok, errors = verify_audit_chain()
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_AUDIT_DIR = Path(os.getenv("IMMUTABLE_AUDIT_DIR", "logs"))
_AUDIT_FILE = _AUDIT_DIR / "immutable_audit.jsonl"

# Serialize writes so the hash chain is never interleaved.
_write_lock = threading.Lock()

# In-memory cache of the last hash for fast chaining.  Populated lazily
# from the last line of the file on first write.
_last_hash: str | None = None
_last_hash_loaded = False

_GENESIS_HASH = "0" * 64  # SHA-256 of "nothing" — anchor for the first entry


def _ensure_dir() -> None:
    _AUDIT_DIR.mkdir(parents=True, exist_ok=True)


def _compute_hash(entry: dict) -> str:
    """Deterministic SHA-256 of the entry (excluding ``current_hash``)."""
    canonical = json.dumps(entry, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _load_last_hash() -> str:
    """Read the last line of the audit file and return its ``current_hash``."""
    if not _AUDIT_FILE.exists():
        return _GENESIS_HASH
    try:
        # Read last non-empty line efficiently
        with open(_AUDIT_FILE, "rb") as f:
            f.seek(0, 2)  # end
            size = f.tell()
            if size == 0:
                return _GENESIS_HASH
            # Read last 4 KB — enough for one JSON line
            f.seek(max(0, size - 4096))
            lines = f.read().decode("utf-8", errors="replace").strip().splitlines()
        if not lines:
            return _GENESIS_HASH
        last = json.loads(lines[-1])
        return last.get("current_hash", _GENESIS_HASH)
    except Exception:
        logger.warning("Could not read last audit hash; starting new chain segment")
        return _GENESIS_HASH


def append_audit_entry(
    *,
    event_type: str,
    user_id: int | str | None = None,
    tenant_id: int | str | None = None,
    resource_type: str = "",
    resource_id: str | None = None,
    action: str = "",
    details: dict[str, Any] | None = None,
) -> dict:
    """Append a tamper-evident entry to the immutable audit log.

    Returns the written entry dict (including hashes).
    """
    global _last_hash, _last_hash_loaded

    with _write_lock:
        if not _last_hash_loaded:
            _last_hash = _load_last_hash()
            _last_hash_loaded = True

        previous_hash = _last_hash or _GENESIS_HASH

        entry = {
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "event_type": event_type,
            "user_id": str(user_id) if user_id is not None else None,
            "tenant_id": str(tenant_id) if tenant_id is not None else None,
            "resource_type": resource_type,
            "resource_id": str(resource_id) if resource_id is not None else None,
            "action": action,
            "details": details,
            "previous_hash": previous_hash,
        }

        current_hash = _compute_hash(entry)
        entry["current_hash"] = current_hash

        _ensure_dir()
        try:
            with open(_AUDIT_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, default=str) + "\n")
                f.flush()
                os.fsync(f.fileno())
        except Exception:
            logger.error("Failed to write immutable audit entry", exc_info=True)
            raise

        _last_hash = current_hash
        return entry


def verify_audit_chain(path: str | Path | None = None) -> tuple[bool, list[str]]:
    """Verify the integrity of the immutable audit log.

    Returns ``(True, [])`` if the chain is intact, or ``(False, errors)``
    with a list of human-readable error descriptions.
    """
    filepath = Path(path) if path else _AUDIT_FILE
    if not filepath.exists():
        return True, []  # No log yet — trivially valid

    errors: list[str] = []
    expected_prev = _GENESIS_HASH
    line_num = 0

    with open(filepath, encoding="utf-8") as f:
        for raw_line in f:
            line_num += 1
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                entry = json.loads(raw_line)
            except json.JSONDecodeError as exc:
                errors.append(f"Line {line_num}: invalid JSON — {exc}")
                continue

            # Check chain link
            if entry.get("previous_hash") != expected_prev:
                errors.append(
                    f"Line {line_num}: chain break — expected previous_hash "
                    f"{expected_prev[:16]}... but got {entry.get('previous_hash', 'MISSING')[:16]}..."
                )

            # Recompute hash
            stored_hash = entry.pop("current_hash", None)
            recomputed = _compute_hash(entry)
            entry["current_hash"] = stored_hash  # restore

            if stored_hash != recomputed:
                errors.append(
                    f"Line {line_num}: hash mismatch — stored {stored_hash[:16]}... "
                    f"vs computed {recomputed[:16]}..."
                )

            expected_prev = stored_hash or recomputed

    return len(errors) == 0, errors
