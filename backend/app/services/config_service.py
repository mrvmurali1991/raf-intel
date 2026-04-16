"""System configuration service — thin DAO over the ``system_config`` table.

All readers across the codebase MUST go through this module rather than
hardcoding config constants. Adding a new configurable value is as simple
as defining a default in :data:`DEFAULTS` and calling :func:`get_config`.

Precedence (highest wins):
    1. tenant-scoped row (tenant_scope = tenant_id)
    2. global row       (tenant_scope = '__global__')
    3. hardcoded default in :data:`DEFAULTS`

The table is created by Alembic migration ``013_system_config_table``.
"""
from __future__ import annotations

import logging
from typing import Any

from app.db import raf_cursor

logger = logging.getLogger(__name__)

# Single source of truth for default values. Never duplicate these elsewhere.
DEFAULTS: dict[str, str] = {
    "ai_analysis_cutoff_date": "2026-04-15",
    "max_analyses_per_patient_per_day": "2",
}

_GLOBAL_SCOPE = "__global__"


def _scope(tenant_id: str | None) -> str:
    return tenant_id if tenant_id else _GLOBAL_SCOPE


def get_config(key: str, default: Any | None = None, tenant_id: str | None = None) -> str | None:
    """Fetch a config value. Falls back tenant -> global -> DEFAULTS -> default.

    Returns the raw string value (or None if unset and no default supplied).
    Callers are responsible for type coercion (e.g. int/date parsing).
    """
    try:
        with raf_cursor() as cur:
            if tenant_id:
                cur.execute(
                    "SELECT config_value FROM system_config "
                    "WHERE config_key = %s AND tenant_scope = %s LIMIT 1",
                    (key, tenant_id),
                )
                row = cur.fetchone()
                if row and row.get("config_value") is not None:
                    return row["config_value"]
            cur.execute(
                "SELECT config_value FROM system_config "
                "WHERE config_key = %s AND tenant_scope = %s LIMIT 1",
                (key, _GLOBAL_SCOPE),
            )
            row = cur.fetchone()
            if row and row.get("config_value") is not None:
                return row["config_value"]
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("config_service: read failed key=%s: %s", key, exc)

    if default is not None:
        return str(default)
    return DEFAULTS.get(key)


def set_config(key: str, value: str, tenant_id: str | None = None) -> None:
    """Upsert a config value. Pass tenant_id=None for a global setting."""
    scope = _scope(tenant_id)
    with raf_cursor() as cur:
        cur.execute(
            """
            INSERT INTO system_config (config_key, tenant_scope, config_value)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE config_value = VALUES(config_value)
            """,
            (key, scope, value),
        )
    logger.info("config_service: set key=%s scope=%s", key, scope)


# Typed convenience accessors --------------------------------------------------


def get_ai_analysis_cutoff_date(tenant_id: str | None = None) -> str:
    """ISO YYYY-MM-DD string. Services filtering clinical data after this
    date should ignore records dated after the cutoff during AI analysis."""
    return get_config("ai_analysis_cutoff_date", tenant_id=tenant_id) or DEFAULTS[
        "ai_analysis_cutoff_date"
    ]


def get_max_analyses_per_patient_per_day(tenant_id: str | None = None) -> int:
    raw = get_config("max_analyses_per_patient_per_day", tenant_id=tenant_id)
    try:
        return int(raw) if raw is not None else int(DEFAULTS["max_analyses_per_patient_per_day"])
    except (TypeError, ValueError):
        return int(DEFAULTS["max_analyses_per_patient_per_day"])
