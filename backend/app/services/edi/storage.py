"""
Local filesystem storage for generated EDI files.

Files land at:
    <base>/<tenant_id>/<file_id>.edi

Metadata is persisted in the `edi_files` table so it survives restarts.
The table is created lazily on first use to avoid a hard dependency on the
migration runner.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_BASE = "./backend/edi_output"


def _base_dir() -> Path:
    base_env = os.getenv("EDI_OUTPUT_DIR")
    if base_env:
        return Path(base_env)
    try:
        from app.config import settings  # type: ignore

        candidate = getattr(settings, "edi_output_dir", None)
        if candidate:
            return Path(candidate)
    except Exception:
        pass
    return Path(_DEFAULT_BASE)


def _ensure_table() -> None:
    try:
        from app.db import raf_cursor

        with raf_cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS edi_files (
                    id            VARCHAR(64)   NOT NULL PRIMARY KEY,
                    tenant_id     VARCHAR(64)   NOT NULL,
                    transaction   VARCHAR(8)    NOT NULL,
                    file_path     VARCHAR(512)  NOT NULL,
                    file_size     BIGINT        NOT NULL DEFAULT 0,
                    sha256        VARCHAR(64)   NOT NULL,
                    encounter_count INT         NOT NULL DEFAULT 0,
                    metadata      JSON          NULL,
                    created_at    DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_tenant (tenant_id, created_at),
                    INDEX idx_txn (transaction, created_at)
                )
                """
            )
    except Exception as exc:
        # Don't crash file generation just because we couldn't persist metadata.
        logger.warning("edi_files table creation skipped: %s", exc)


def save_edi_file(
    *,
    tenant_id: str | int,
    transaction: str,
    content: str,
    encounter_count: int,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Write *content* to disk and persist a metadata row.

    Returns a dict with id, file_path, file_size, sha256, encounter_count.
    """
    _ensure_table()

    file_id = uuid.uuid4().hex
    base = _base_dir() / str(tenant_id)
    base.mkdir(parents=True, exist_ok=True)
    file_path = base / f"{file_id}.edi"

    data = content.encode("utf-8")
    file_path.write_bytes(data)
    sha256 = hashlib.sha256(data).hexdigest()
    size = len(data)

    try:
        from app.db import raf_cursor

        with raf_cursor() as cur:
            cur.execute(
                """
                INSERT INTO edi_files
                    (id, tenant_id, transaction, file_path, file_size,
                     sha256, encounter_count, metadata, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    file_id,
                    str(tenant_id),
                    transaction,
                    str(file_path),
                    size,
                    sha256,
                    encounter_count,
                    json.dumps(metadata or {}),
                    datetime.now(timezone.utc),
                ),
            )
    except Exception as exc:
        logger.warning("edi_files insert failed for %s: %s", file_id, exc)

    return {
        "id": file_id,
        "file_path": str(file_path),
        "file_size": size,
        "sha256": sha256,
        "encounter_count": encounter_count,
        "transaction": transaction,
    }


def get_edi_file(*, file_id: str, tenant_id: str | int) -> dict[str, Any] | None:
    """Fetch a generated file's metadata.  Returns None when not found or when
    the tenant does not own it."""
    _ensure_table()
    try:
        from app.db import raf_cursor

        with raf_cursor() as cur:
            cur.execute(
                "SELECT * FROM edi_files WHERE id = %s",
                (file_id,),
            )
            row = cur.fetchone()
    except Exception as exc:
        logger.warning("edi_files lookup failed: %s", exc)
        return None
    if not row:
        return None
    if str(row.get("tenant_id")) != str(tenant_id):
        return None
    return row
