"""
Immutable Audit Log — cryptographic hash-chain audit trail.

Dual-writes to:
  1. ``logs/immutable_audit.jsonl`` — append-only JSON Lines file (primary)
  2. ``immutable_audit_log`` MySQL table — created by migration 021

Each entry includes a SHA-256 hash chaining to the previous entry, making any
tampering or deletion detectable via ``verify_audit_chain()``.

This satisfies HIPAA §164.312(b) audit-controls by providing a durable,
tamper-evident log independent of the MySQL audit_log table.

Public API:
    emit_audit_event(event_type, *, tenant_id, actor_user_id, subject_type,
                     subject_id, payload) -> None   # canonical name
    append_audit_entry(...)                          # legacy alias
    verify_audit_chain() -> (bool, list[str])

Usage:
    from app.services.immutable_audit import emit_audit_event, verify_audit_chain

    emit_audit_event(
        "phi_access",
        tenant_id="1",
        actor_user_id=42,
        subject_type="patient",
        subject_id="123",
        payload={"action": "view"},
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


def _db_insert(entry: dict) -> None:
    """Insert an audit entry into the ``immutable_audit_log`` MySQL table.

    Maps the JSONL entry fields to the columns defined by migration 021:
    ``(id, event_ts, event_type, actor_user_id, actor_email, tenant_id,
      patient_id, resource, action, payload_json, hash_prev, hash_self)``

    Caller must NOT hold ``_write_lock`` — this function acquires no locks.
    Any exception is caught by the caller which logs ERROR and continues.
    """
    from app.db import raf_cursor  # local import to avoid circular deps at module load

    details = entry.get("details") or {}
    payload_json = json.dumps(details, default=str) if details else None

    with raf_cursor() as cur:
        cur.execute(
            """
            INSERT INTO immutable_audit_log
                (event_ts, event_type, actor_user_id, actor_email,
                 tenant_id, patient_id, resource, action,
                 payload_json, hash_prev, hash_self)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                entry.get("timestamp"),
                entry.get("event_type"),
                entry.get("user_id"),
                details.get("actor_email") if details else None,
                entry.get("tenant_id"),
                details.get("patient_id") if details else None,
                entry.get("resource_type") or None,
                entry.get("action") or None,
                payload_json,
                entry.get("previous_hash"),
                entry.get("current_hash"),
            ),
        )


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
    """Append a tamper-evident entry to the immutable audit log (JSONL + DB).

    Returns the written entry dict (including hashes).

    DB insert failures are non-fatal: the JSONL write is always attempted
    first and serves as the durable record.  If the DB is down the event is
    not lost — it is preserved in the JSONL file and will be detected by the
    nightly ``verify_audit_chain`` task.
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
            logger.error("Failed to write immutable audit entry to JSONL", exc_info=True)
            raise

        _last_hash = current_hash

    # DB write is outside the _write_lock to minimise lock hold time.
    # JSONL is already committed at this point — DB failure is non-fatal.
    try:
        _db_insert(entry)
    except Exception:
        logger.error(
            "immutable_audit: DB insert failed for event_type=%s — "
            "event preserved in JSONL, DB out-of-sync until next verify run",
            event_type,
            exc_info=True,
        )

    return entry


# ---------------------------------------------------------------------------
# Public canonical API
# ---------------------------------------------------------------------------


def emit_audit_event(
    event_type: str,
    *,
    tenant_id: int | str | None = None,
    actor_user_id: int | str | None = None,
    subject_type: str | None = None,
    subject_id: str | int | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    """Emit a tamper-evident audit event to both JSONL and DB.

    This is the canonical public function.  All new callers should use this
    rather than ``append_audit_entry`` directly.

    Args:
        event_type:    Uppercase snake_case event name, e.g. ``"PHI_ACCESS"``.
        tenant_id:     Tenant identifier (string or int).
        actor_user_id: ID of the user performing the action.
        subject_type:  Type of the affected resource, e.g. ``"patient"``.
        subject_id:    ID of the affected resource.
        payload:       Arbitrary additional metadata (must be JSON-serialisable).
    """
    details: dict[str, Any] = {}
    if payload:
        details.update(payload)
    if subject_id is not None:
        details.setdefault("subject_id", str(subject_id))

    append_audit_entry(
        event_type=event_type,
        user_id=actor_user_id,
        tenant_id=tenant_id,
        resource_type=subject_type or "",
        resource_id=str(subject_id) if subject_id is not None else None,
        action=event_type,
        details=details or None,
    )


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
