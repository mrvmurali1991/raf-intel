"""
Admin endpoints for encryption key management (KMS BYOK).

POST /api/admin/encryption/rotate-key   — re-encrypt all sensitive rows
GET  /api/admin/encryption/status       — provider info and rotation age
"""
from __future__ import annotations

import base64
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.auth import require_role
from app.db import raf_cursor
from app.services.encryption_service import (
    VERSION_FERNET,
    VERSION_KMS,
    AwsKmsProvider,
    LocalFernetProvider,
    _universal_decrypt,
    get_provider,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/encryption", tags=["admin"])

# ---------------------------------------------------------------------------
# Tables + columns that hold encrypted fields
# ---------------------------------------------------------------------------

_ENCRYPTED_COLUMNS: list[dict[str, Any]] = [
    {"table": "fhir_connections", "pk": "id", "columns": ["client_secret"]},
    {"table": "users", "pk": "id", "columns": ["mfa_secret"]},
]

_BATCH_SIZE = 100


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _blob_version(blob: bytes) -> str:
    if not blob:
        return "empty"
    if blob[:1] == VERSION_FERNET:
        return "fernet"
    if blob[:1] == VERSION_KMS:
        return "kms"
    return "unknown"


def _re_encrypt_row(
    row_id: Any,
    col_value: str,
    active_provider,
) -> str:
    """Decrypt the existing value and re-encrypt with the active provider."""
    raw = base64.urlsafe_b64decode(col_value.encode("ascii"))
    plaintext = _universal_decrypt(raw, active_provider)
    new_blob = active_provider.encrypt(plaintext)
    return base64.urlsafe_b64encode(new_blob).decode("ascii")


# ---------------------------------------------------------------------------
# GET /api/admin/encryption/status
# ---------------------------------------------------------------------------


@router.get("/status", summary="Encryption provider status")
def encryption_status(
    _current_user: dict = Depends(require_role("admin")),
):
    """Return active provider name, optional KMS key ARN, and env metadata."""
    provider = get_provider()
    arn = os.getenv("AWS_KMS_KEY_ARN", "")
    provider_name = "kms" if isinstance(provider, AwsKmsProvider) else "fernet"

    # Approximate rotation age from an env hint (set externally by rotation pipeline)
    rotation_ts_str = os.getenv("ENCRYPTION_LAST_ROTATED_TS", "")
    rotation_age_days: Any = None
    if rotation_ts_str:
        try:
            ts = float(rotation_ts_str)
            age_seconds = time.time() - ts
            rotation_age_days = round(age_seconds / 86400, 1)
        except ValueError:
            rotation_age_days = None

    return {
        "provider": provider_name,
        "key_arn": arn or None,
        "rotation_age_days": rotation_age_days,
        "cache_ttl_seconds": 300,
        "version_byte_fernet": "0x01",
        "version_byte_kms": "0x02",
    }


# ---------------------------------------------------------------------------
# POST /api/admin/encryption/rotate-key
# ---------------------------------------------------------------------------


@router.post("/rotate-key", summary="Re-encrypt all sensitive rows with active provider")
def rotate_key(
    _current_user: dict = Depends(require_role("admin")),
):
    """Batch re-encrypt every sensitive column with the current active provider.

    Returns:
        {"rotated": N, "errors": [{"table": ..., "id": ..., "error": ...}]}
    """
    provider = get_provider()
    total_rotated = 0
    errors: list[dict[str, Any]] = []

    for spec in _ENCRYPTED_COLUMNS:
        table = spec["table"]
        pk = spec["pk"]
        columns: list[str] = spec["columns"]

        for col in columns:
            # Paginate in batches of 100 to avoid large transactions.
            offset = 0
            while True:
                try:
                    with raf_cursor() as cur:
                        cur.execute(
                            f"SELECT `{pk}`, `{col}` FROM `{table}`"
                            f" WHERE `{col}` IS NOT NULL AND `{col}` != ''"
                            f" LIMIT %s OFFSET %s",
                            (_BATCH_SIZE, offset),
                        )
                        rows = cur.fetchall()
                except Exception as exc:
                    logger.error("rotate-key: failed to read %s.%s: %s", table, col, exc)
                    errors.append({"table": table, "column": col, "id": None, "error": str(exc)})
                    break

                if not rows:
                    break

                for row in rows:
                    row_id = row[pk]
                    old_val: str = row[col]
                    if not old_val:
                        continue

                    # Skip rows already on active provider version.
                    try:
                        raw = base64.urlsafe_b64decode(old_val.encode("ascii"))
                    except Exception:
                        raw = b""

                    active_version = VERSION_KMS if isinstance(provider, AwsKmsProvider) else VERSION_FERNET
                    if raw[:1] == active_version:
                        continue  # already correct version, no-op

                    try:
                        new_val = _re_encrypt_row(row_id, old_val, provider)
                    except Exception as exc:
                        logger.warning(
                            "rotate-key: failed to re-encrypt %s id=%s col=%s: %s",
                            table, row_id, col, exc,
                        )
                        errors.append({"table": table, "column": col, "id": row_id, "error": str(exc)})
                        continue

                    try:
                        with raf_cursor() as cur:
                            cur.execute(
                                f"UPDATE `{table}` SET `{col}` = %s WHERE `{pk}` = %s",
                                (new_val, row_id),
                            )
                        total_rotated += 1
                    except Exception as exc:
                        logger.warning(
                            "rotate-key: failed to write %s id=%s col=%s: %s",
                            table, row_id, col, exc,
                        )
                        errors.append({"table": table, "column": col, "id": row_id, "error": str(exc)})

                offset += _BATCH_SIZE
                if len(rows) < _BATCH_SIZE:
                    break

    return {"rotated": total_rotated, "errors": errors}
