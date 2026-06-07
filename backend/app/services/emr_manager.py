"""
Multi-EMR Connection Manager.

Manages connections to multiple Electronic Medical Record (EMR) systems,
supporting direct database connections, FHIR R4 APIs, REST APIs, and HL7v2
interfaces.  Credentials are encrypted at rest using AES-256-GCM.

Supported connection types
--------------------------
* ``direct_db``  – MySQL or PostgreSQL direct connection
* ``fhir_r4``    – FHIR R4 endpoint (OAuth2 client_credentials)
* ``rest_api``   – Generic REST API with bearer-token or basic-auth
* ``hl7v2``      – HL7 v2 MLLP interface (see hl7v2_service.py)

Tables managed by this module
------------------------------
* ``emr_connections``   – one row per registered EMR integration
* ``emr_sync_log``      – one row per sync run
* ``emr_vendor_presets`` – static vendor configuration hints (seeded once)

Usage::

    from app.services.emr_manager import (
        list_connections, create_connection, test_connection,
        trigger_sync, auto_register_openemr,
    )

    auto_register_openemr()          # call at startup
    conns = list_connections()
    result = test_connection(conn_id)
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx

from app.db import raf_cursor
from app.security.ssrf import _assert_safe_outbound_url
from app.services.encryption_service import decrypt, encrypt
from app.services.hcc_mapping_service import get_hcc_coefficient as _hcc_coefficient
from app.services.hcc_mapping_service import map_icd10_batch
from app.services.vendor_adapters.registry import get_adapter, get_fhir_adapter

# ---------------------------------------------------------------------------
# Pipeline event helpers
# ---------------------------------------------------------------------------

def _emit_sync_completed(
    sync_result: dict,
    tenant_id: str | None,
    connection_id: int,
    sync_type: str,
) -> None:
    """Fire the internal ``emr_sync_completed`` pipeline event (non-blocking).

    Only fires when the sync finished with a non-failure status so the
    normalization chain is not triggered on error results.
    """
    status = sync_result.get("status", "")
    if status in ("failed",):
        return  # do not chain on explicit failures
    try:
        from app.services.event_emitter import emit_internal
        emit_internal(
            "emr_sync_completed",
            {
                "tenant_id": tenant_id or "default",
                "connection_id": connection_id,
                "sync_type": sync_type,
                "sync_id": sync_result.get("sync_id"),
                "status": status,
            },
        )
    except Exception as exc:  # pragma: no cover
        logger.error("emr_manager: failed to emit emr_sync_completed: %s", exc)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_MASKED = "***"
_DEFAULT_TIMEOUT = httpx.Timeout(15.0, connect=5.0)

# ---------------------------------------------------------------------------
# Connection-aware patient filtering
# ---------------------------------------------------------------------------

# Use ``active_patients_subquery(tenant_id)`` for all tenant-scoped active-patient
# filtering.  It returns a ``(sql_fragment, params)`` tuple whose fragment restricts
# the given patient_id column to rows whose patient is active AND belongs to the
# supplied tenant.  Raises ValueError if tenant_id is None.
#
# Usage:
#   frag, params = active_patients_subquery(tenant_id)
#   sql = f"SELECT ... FROM raf_scores WHERE {frag} AND ..."
#   cursor.execute(sql, (*params, ...other params...))


def active_patients_subquery(
    tenant_id: int,
    *,
    patient_id_column: str = "patient_id",
) -> tuple[str, tuple[int, ...]]:
    """Return a tenant-scoped SQL fragment for active-patient filtering.

    Returns a ``(sql_fragment, params)`` tuple. The fragment restricts the
    given ``patient_id_column`` (default ``patient_id`` — override to
    ``pid``/``id`` for OpenEMR tables) to rows whose patient is active AND
    belongs to the supplied tenant. One bound parameter is emitted; the
    caller must include it in the query's params tuple in positional order
    matching the fragment.

    Raises ValueError if tenant_id is None — never falls back to a default,
    as that would silently serve cross-tenant data (HIPAA violation).
    """
    if tenant_id is None:
        raise ValueError(
            "active_patients_subquery: tenant_id is required — "
            "refusing to query across all tenants (HIPAA multi-tenant isolation)"
        )
    tid = int(tenant_id)
    # All patient sources (Direct-DB, OpenEMR, FHIR/REST) now have proper
    # rows in the `patients` table with is_active=1, data_source set, and
    # emr_connection_id linked.  The previous UNION with emr_patient_matches
    # is no longer needed and could cause double-counting when emr_pid
    # values differ from patients.id values.
    frag = (
        f"({patient_id_column} IN ("
        f"  SELECT id FROM patients WHERE is_active = 1 AND tenant_id = %s"
        f"))"
    )
    return frag, (tid,)

_CREDENTIAL_FIELDS = ("db_password", "client_secret", "api_key", "access_token", "refresh_token_emr")

_REQUIRED_FIELDS: dict[str, list[str]] = {
    "direct_db": [
        "display_name",
        "db_host",
        "db_port",
        "db_name",
        "db_user",
        "db_password",
        "db_type",
    ],
    "fhir_r4": ["display_name", "base_url"],
    "rest_api": ["display_name", "api_base_url"],
    "hl7v2": ["display_name"],
}

# Connection types that are valid.
_VALID_CONNECTION_TYPES = frozenset(_REQUIRED_FIELDS.keys())


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _mask_credentials(row: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of *row* with credential fields replaced by ``***``."""
    masked = dict(row)
    for field in _CREDENTIAL_FIELDS:
        if masked.get(field):
            masked[field] = _MASKED
    return masked


def _encrypt_credentials(data: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of *data* with credential fields encrypted in place."""
    result = dict(data)
    for field in _CREDENTIAL_FIELDS:
        if result.get(field) and result[field] != _MASKED:
            result[field] = encrypt(result[field])
    return result


def _decrypt_credentials(row: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of *row* with credential fields decrypted."""
    result = dict(row)
    for field in _CREDENTIAL_FIELDS:
        if result.get(field):
            try:
                result[field] = decrypt(result[field])
            except (ValueError, Exception) as exc:
                logger.warning(
                    "Failed to decrypt field '%s' for connection id=%s: %s — using raw value",
                    field,
                    result.get("id"),
                    exc,
                )
                # Password may be plaintext (manual UPDATE) — keep raw value
                pass
    return result


# ---------------------------------------------------------------------------
# Centralized migrations — replaces auto-DDL
# ---------------------------------------------------------------------------

_tables_ensured = False  # kept for backward-compat; no longer used for DDL


def _ensure_tables() -> None:
    """No-op — tables are managed by the centralized migration runner."""
    global _tables_ensured
    _tables_ensured = True


# ---------------------------------------------------------------------------
# Vendor presets seeding
# ---------------------------------------------------------------------------

_VENDOR_PRESETS: list[dict[str, Any]] = [
    {
        "vendor": "openemr",
        "display_name": "OpenEMR",
        "connection_type": "direct_db",
        "default_port": 3306,
        "default_db_name": "openemr",
        "fhir_version": None,
        "notes": "Open-source EHR.  Connect via MySQL/MariaDB direct connection.",
        "default_mappings": json.dumps(
            {
                "patient_id": "pid",
                "first_name": "fname",
                "last_name": "lname",
                "dob": "DOB",
                "gender": "sex",
                "ssn": "ss",
                "icd_codes": "diagnosis.diagnosis_code",
                "encounter_id": "encounter",
            }
        ),
    },
    {
        "vendor": "epic",
        "display_name": "Epic",
        "connection_type": "fhir_r4",
        "default_port": None,
        "default_db_name": None,
        "fhir_version": "R4",
        "notes": "Epic FHIR R4 API.  Requires OAuth2 client_credentials with SMART on FHIR.",
        "default_mappings": json.dumps(
            {
                "patient_id": "id",
                "first_name": "name[0].given[0]",
                "last_name": "name[0].family",
                "dob": "birthDate",
                "gender": "gender",
                "icd_codes": "code.coding[system=http://hl7.org/fhir/sid/icd-10-cm].code",
            }
        ),
    },
    {
        "vendor": "cerner",
        "display_name": "Cerner / Oracle Health",
        "connection_type": "fhir_r4",
        "default_port": None,
        "default_db_name": None,
        "fhir_version": "R4",
        "notes": "Cerner Millennium FHIR R4 API.",
        "default_mappings": json.dumps(
            {
                "patient_id": "id",
                "first_name": "name[0].given[0]",
                "last_name": "name[0].family",
                "dob": "birthDate",
                "gender": "gender",
                "icd_codes": "code.coding[system=http://hl7.org/fhir/sid/icd-10-cm].code",
            }
        ),
    },
    {
        "vendor": "athenahealth",
        "display_name": "athenahealth",
        "connection_type": "fhir_r4",
        "default_port": None,
        "default_db_name": None,
        "fhir_version": "R4",
        "notes": "athenahealth FHIR R4 API.",
        "default_mappings": json.dumps(
            {
                "patient_id": "id",
                "first_name": "name[0].given[0]",
                "last_name": "name[0].family",
                "dob": "birthDate",
                "icd_codes": "code.coding[system=http://hl7.org/fhir/sid/icd-10-cm].code",
            }
        ),
    },
    {
        "vendor": "allscripts",
        "display_name": "Allscripts",
        "connection_type": "rest_api",
        "default_port": None,
        "default_db_name": None,
        "fhir_version": None,
        "notes": "Allscripts REST API integration.",
        "default_mappings": json.dumps({}),
    },
    {
        "vendor": "generic_fhir",
        "display_name": "Generic FHIR R4",
        "connection_type": "fhir_r4",
        "default_port": None,
        "default_db_name": None,
        "fhir_version": "R4",
        "notes": "Any FHIR R4-compliant server.",
        "default_mappings": json.dumps(
            {
                "patient_id": "id",
                "icd_codes": "code.coding[system=http://hl7.org/fhir/sid/icd-10-cm].code",
            }
        ),
    },
    {
        "vendor": "generic_db",
        "display_name": "Generic Database",
        "connection_type": "direct_db",
        "default_port": 3306,
        "default_db_name": None,
        "fhir_version": None,
        "notes": "Generic MySQL or PostgreSQL direct connection.",
        "default_mappings": json.dumps({}),
    },
]


def _seed_vendor_presets() -> None:
    """Insert default vendor presets if the table is empty."""
    with raf_cursor() as cur:
        cur.execute("SELECT COUNT(*) AS cnt FROM emr_vendor_presets")
        row = cur.fetchone()
        count = row["cnt"] if isinstance(row, dict) else row[0]
        if count and count > 0:
            return

        for preset in _VENDOR_PRESETS:
            cur.execute(
                """
                INSERT IGNORE INTO emr_vendor_presets
                    (vendor, display_name, connection_type, default_port,
                     default_db_name, fhir_version, notes, default_mappings)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    preset["vendor"],
                    preset["display_name"],
                    preset["connection_type"],
                    preset.get("default_port"),
                    preset.get("default_db_name"),
                    preset.get("fhir_version"),
                    preset.get("notes"),
                    preset.get("default_mappings"),
                ),
            )
    logger.info("emr_manager: vendor presets seeded (%d rows)", len(_VENDOR_PRESETS))


# ---------------------------------------------------------------------------
# CRUD – emr_connections
# ---------------------------------------------------------------------------


def list_connections(tenant_id: str) -> list[dict]:
    """Return all EMR connections for *tenant_id*, with credentials masked."""
    _ensure_tables()
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT id, tenant_id, display_name, vendor, connection_type,
                   db_type, db_host, db_port, db_name, db_user, db_password,
                   base_url, token_url, client_id, client_secret, scope,
                   api_base_url, api_key, api_auth_type,
                   is_active, field_mappings, extra_config,
                   last_test_at, last_test_success,
                   sync_enabled, sync_interval_minutes, sync_cron, last_sync_at,
                   created_at, updated_at
            FROM emr_connections
            WHERE tenant_id = %s
            ORDER BY display_name
            """,
            (tenant_id,),
        )
        rows = cur.fetchall() or []
    return [_mask_credentials(dict(r)) for r in rows]


def get_connection(connection_id: int, tenant_id: str | None = None) -> dict | None:
    """Return a single EMR connection by ID, with credentials masked.

    When *tenant_id* is supplied the query also filters by tenant so that a
    user from one tenant cannot retrieve a connection owned by another tenant.
    """
    _ensure_tables()
    with raf_cursor() as cur:
        if tenant_id is not None:
            cur.execute(
                """
                SELECT id, tenant_id, display_name, vendor, connection_type,
                       db_type, db_host, db_port, db_name, db_user, db_password,
                       base_url, token_url, client_id, client_secret, scope,
                       api_base_url, api_key, api_auth_type,
                       is_active, field_mappings, extra_config,
                       last_test_at, last_test_success,
                       sync_enabled, sync_interval_minutes, sync_cron, last_sync_at,
                       access_token, refresh_token_emr, token_expires_at,
                       created_at, updated_at
                FROM emr_connections
                WHERE id = %s AND tenant_id = %s
                """,
                (connection_id, tenant_id),
            )
        else:
            cur.execute(
                """
                SELECT id, tenant_id, display_name, vendor, connection_type,
                       db_type, db_host, db_port, db_name, db_user, db_password,
                       base_url, token_url, client_id, client_secret, scope,
                       api_base_url, api_key, api_auth_type,
                       is_active, field_mappings, extra_config,
                       last_test_at, last_test_success,
                       sync_enabled, sync_interval_minutes, sync_cron, last_sync_at,
                       access_token, refresh_token_emr, token_expires_at,
                       created_at, updated_at
                FROM emr_connections
                WHERE id = %s
                """,
                (connection_id,),
            )
        row = cur.fetchone()
    if row is None:
        return None
    return _mask_credentials(dict(row))


def get_connection_with_credentials(
    connection_id: int, tenant_id: str | None = None
) -> dict | None:
    """Internal use only – returns the connection with credentials decrypted.

    When *tenant_id* is supplied the query also filters by tenant to prevent
    cross-tenant credential access.  Never expose the return value through an
    API response.
    """
    _ensure_tables()
    with raf_cursor() as cur:
        if tenant_id is not None:
            cur.execute(
                """
                SELECT id, tenant_id, display_name, vendor, connection_type,
                       db_type, db_host, db_port, db_name, db_user, db_password,
                       base_url, token_url, client_id, client_secret, scope,
                       api_base_url, api_key, api_auth_type,
                       is_active, field_mappings, extra_config,
                       last_test_at, last_test_success,
                       sync_enabled, sync_interval_minutes, sync_cron, last_sync_at,
                       access_token, refresh_token_emr, token_expires_at,
                       created_at, updated_at
                FROM emr_connections
                WHERE id = %s AND tenant_id = %s
                """,
                (connection_id, tenant_id),
            )
        else:
            cur.execute(
                """
                SELECT id, tenant_id, display_name, vendor, connection_type,
                       db_type, db_host, db_port, db_name, db_user, db_password,
                       base_url, token_url, client_id, client_secret, scope,
                       api_base_url, api_key, api_auth_type,
                       is_active, field_mappings, extra_config,
                       last_test_at, last_test_success,
                       sync_enabled, sync_interval_minutes, sync_cron, last_sync_at,
                       access_token, refresh_token_emr, token_expires_at,
                       created_at, updated_at
                FROM emr_connections
                WHERE id = %s
                """,
                (connection_id,),
            )
        row = cur.fetchone()
    if row is None:
        return None
    return _decrypt_credentials(dict(row))


def get_active_direct_db_credentials(tenant_id: str) -> dict | None:
    """Return decrypted credentials for the first active direct_db connection.

    Returns a dict with keys ``db_host``, ``db_port``, ``db_name``,
    ``db_user``, ``db_password``, ``db_type`` — or ``None`` if no active
    direct_db connection exists for *tenant_id*.

    Results are cached for 30 seconds to avoid hitting the database on
    every patient-list request.
    """
    now = time.monotonic()
    cache = getattr(get_active_direct_db_credentials, "_cache", None)
    if cache and cache["tenant"] == tenant_id and now - cache["ts"] < 30:
        return cache["value"]

    _ensure_tables()
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT id, db_type, db_host, db_port, db_name, db_user, db_password
            FROM emr_connections
            WHERE tenant_id = %s
              AND connection_type = 'direct_db'
              AND is_active = 1
            ORDER BY created_at
            LIMIT 1
            """,
            (tenant_id,),
        )
        row = cur.fetchone()

    if not row:
        get_active_direct_db_credentials._cache = {
            "tenant": tenant_id, "ts": now, "value": None,
        }
        return None

    result = _decrypt_credentials(dict(row))
    get_active_direct_db_credentials._cache = {
        "tenant": tenant_id, "ts": now, "value": result,
    }
    return result


def _invalidate_creds_cache() -> None:
    """Clear the TTL cache on get_active_direct_db_credentials."""
    get_active_direct_db_credentials._cache = None


def create_connection(data: dict) -> dict:
    """Validate, encrypt credentials, and INSERT a new EMR connection.

    Returns the newly created connection (credentials masked).
    Raises ``ValueError`` on missing required fields or unknown connection type.
    """
    _ensure_tables()

    connection_type = data.get("connection_type", "")
    if connection_type not in _VALID_CONNECTION_TYPES:
        raise ValueError(
            f"Invalid connection_type '{connection_type}'. "
            f"Must be one of: {', '.join(sorted(_VALID_CONNECTION_TYPES))}"
        )

    required = _REQUIRED_FIELDS[connection_type]
    missing = [f for f in required if not data.get(f)]
    if missing:
        raise ValueError(
            f"Missing required fields for {connection_type}: {', '.join(missing)}"
        )

    encrypted = _encrypt_credentials(data)
    tenant_id = encrypted.get("tenant_id") or ""
    if not tenant_id:
        raise ValueError(
            "register_connection: tenant_id is required — "
            "refusing to register EMR connection without tenant scope (HIPAA multi-tenant isolation)"
        )

    with raf_cursor() as cur:
        cur.execute(
            """
            INSERT INTO emr_connections
                (tenant_id, name, display_name, vendor, connection_type,
                 db_type, db_host, db_port, db_name, db_user, db_password,
                 base_url, token_url, client_id, client_secret, scope,
                 api_base_url, api_key, api_auth_type,
                 is_active, field_mappings, extra_config)
            VALUES
                (%s, %s, %s, %s, %s,
                 %s, %s, %s, %s, %s, %s,
                 %s, %s, %s, %s, %s,
                 %s, %s, %s,
                 %s, %s, %s)
            """,
            (
                tenant_id,
                encrypted.get("name") or encrypted.get("display_name"),
                encrypted.get("display_name"),
                encrypted.get("vendor", "generic"),
                connection_type,
                # direct_db
                encrypted.get("db_type"),
                encrypted.get("db_host"),
                encrypted.get("db_port"),
                encrypted.get("db_name"),
                encrypted.get("db_user"),
                encrypted.get("db_password"),
                # fhir_r4
                encrypted.get("base_url"),
                encrypted.get("token_url"),
                encrypted.get("client_id"),
                encrypted.get("client_secret"),
                encrypted.get("scope"),
                # rest_api
                encrypted.get("api_base_url"),
                encrypted.get("api_key"),
                encrypted.get("api_auth_type") or encrypted.get("auth_type") or "none",
                # shared
                int(encrypted.get("is_active", 1)),
                json.dumps(encrypted.get("field_mappings"))
                if isinstance(encrypted.get("field_mappings"), dict)
                else encrypted.get("field_mappings"),
                json.dumps(encrypted.get("extra_config"))
                if isinstance(encrypted.get("extra_config"), dict)
                else encrypted.get("extra_config"),
            ),
        )
        new_id = cur.lastrowid

    logger.info(
        "emr_manager: created connection id=%s display_name=%s",
        new_id,
        data.get("display_name"),
    )
    _invalidate_creds_cache()
    result = get_connection(new_id)
    if result is None:
        raise RuntimeError("Failed to retrieve newly created connection")
    return result


def update_connection(
    connection_id: int, data: dict, tenant_id: str | None = None
) -> dict:
    """UPDATE an existing EMR connection.

    Only columns present in *data* are updated.  Credential fields are
    re-encrypted when provided (and not already masked as ``***``).
    Returns the updated connection (credentials masked).
    Raises ``KeyError`` if the connection does not exist or does not belong to
    *tenant_id* (when supplied).
    """
    _ensure_tables()

    existing = get_connection(connection_id, tenant_id=tenant_id)
    if existing is None:
        raise KeyError(f"EMR connection id={connection_id} not found")

    # Build SET clause dynamically from the provided keys.
    _UPDATABLE = {
        "display_name",
        "vendor",
        "connection_type",
        "db_type",
        "db_host",
        "db_port",
        "db_name",
        "db_user",
        "db_password",
        "base_url",
        "token_url",
        "client_id",
        "client_secret",
        "scope",
        "api_base_url",
        "api_key",
        "api_auth_type",
        "is_active",
        "field_mappings",
        "extra_config",
        "tenant_id",
        "sync_enabled",
        "sync_interval_minutes",
        "sync_cron",
        "last_sync_at",
    }

    fields: list[str] = []
    params: list[Any] = []

    for key, value in data.items():
        if key not in _UPDATABLE:
            continue
        if key in _CREDENTIAL_FIELDS and value and value != _MASKED:
            value = encrypt(value)
        if key in ("field_mappings", "extra_config") and isinstance(value, dict):
            value = json.dumps(value)
        fields.append(f"{key} = %s")
        params.append(value)

    if not fields:
        return existing

    if tenant_id is not None:
        params.extend([connection_id, tenant_id])
        where_clause = "id = %s AND tenant_id = %s"
    else:
        params.append(connection_id)
        where_clause = "id = %s"

    with raf_cursor() as cur:
        cur.execute(
            f"UPDATE emr_connections SET {', '.join(fields)} WHERE {where_clause}",
            params,
        )

    logger.info(
        "emr_manager: updated connection id=%s fields=%s",
        connection_id,
        list(data.keys()),
    )
    _invalidate_creds_cache()
    result = get_connection(connection_id, tenant_id=tenant_id)
    if result is None:
        raise RuntimeError("Failed to retrieve updated connection")
    return result


def delete_connection(connection_id: int, tenant_id: str | None = None) -> bool:
    """DELETE an EMR connection.  Returns True if a row was removed.

    When *tenant_id* is supplied only the row matching both id and tenant is
    deleted, preventing cross-tenant deletes.
    """
    _ensure_tables()
    with raf_cursor() as cur:
        if tenant_id is not None:
            cur.execute(
                "DELETE FROM emr_connections WHERE id = %s AND tenant_id = %s",
                (connection_id, tenant_id),
            )
        else:
            cur.execute("DELETE FROM emr_connections WHERE id = %s", (connection_id,))
        affected = cur.rowcount
    _invalidate_creds_cache()
    logger.info(
        "emr_manager: deleted connection id=%s (affected=%s)", connection_id, affected
    )
    return affected > 0


# ---------------------------------------------------------------------------
# Vendor presets
# ---------------------------------------------------------------------------


def get_vendor_presets() -> list[dict]:
    """Return all vendor preset rows."""
    _ensure_tables()
    with raf_cursor() as cur:
        cur.execute(
            "SELECT id, vendor, display_name, connection_type, default_port, "
            "default_db_name, fhir_version, notes, default_mappings, created_at "
            "FROM emr_vendor_presets ORDER BY display_name"
        )
        rows = cur.fetchall() or []
    return [dict(r) for r in rows]


def get_vendor_preset(vendor: str) -> dict | None:
    """Return a single vendor preset by *vendor* slug, or None."""
    _ensure_tables()
    with raf_cursor() as cur:
        cur.execute(
            "SELECT id, vendor, display_name, connection_type, default_port, "
            "default_db_name, fhir_version, notes, default_mappings, created_at "
            "FROM emr_vendor_presets WHERE vendor = %s",
            (vendor,),
        )
        row = cur.fetchone()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Connection testing
# ---------------------------------------------------------------------------


def test_connection(connection_id: int, tenant_id: str | None = None) -> dict:
    """Test connectivity for the given EMR connection.

    Returns a dict with keys:
        * ``success``    – bool
        * ``message``    – human-readable result
        * ``latency_ms`` – round-trip time in milliseconds (0 on failure)

    When *tenant_id* is supplied only connections owned by that tenant can be
    tested.  Also updates ``last_test_at`` and ``last_test_success`` in the DB.
    """
    _ensure_tables()

    connection = get_connection_with_credentials(connection_id, tenant_id=tenant_id)
    if connection is None:
        return {
            "success": False,
            "message": f"Connection id={connection_id} not found",
            "latency_ms": 0,
        }

    connection_type: str = connection.get("connection_type", "")

    try:
        if connection_type == "direct_db":
            result = _test_direct_db(connection)
        elif connection_type == "fhir_r4":
            result = _test_fhir_r4(connection)
        elif connection_type == "rest_api":
            result = _test_rest_api(connection)
        elif connection_type == "hl7v2":
            result = _test_hl7v2(connection)
        else:
            result = {
                "success": False,
                "message": f"Unknown connection_type '{connection_type}'",
                "latency_ms": 0,
            }
    except Exception as exc:
        logger.exception(
            "emr_manager: test_connection id=%s unexpected error", connection_id
        )
        result = {
            "success": False,
            "message": f"Unexpected error: {exc}",
            "latency_ms": 0,
        }

    # Persist test result.
    with raf_cursor() as cur:
        cur.execute(
            "UPDATE emr_connections SET last_test_at = %s, last_test_success = %s WHERE id = %s",
            (_now_utc(), int(result["success"]), connection_id),
        )

    return result


def _test_hl7v2(connection: dict) -> dict:
    """Verify HL7v2 connectivity by attempting a TCP connection to the MLLP port.

    The host and port are read from ``extra_config.host`` / ``extra_config.port``
    (or ``db_host`` / ``db_port`` as a fallback for legacy rows).  If neither is
    configured the test fails with a clear message rather than an exception.
    """
    import socket as _socket

    extra: dict = {}
    raw_extra = connection.get("extra_config")
    if isinstance(raw_extra, dict):
        extra = raw_extra
    elif isinstance(raw_extra, str):
        try:
            extra = json.loads(raw_extra)
        except Exception:
            logger.debug("swallowed exception", exc_info=True)
            extra = {}

    host: str = (
        extra.get("host") or extra.get("hl7_host") or connection.get("db_host") or ""
    )
    port_raw = (
        extra.get("port") or extra.get("hl7_port") or connection.get("db_port") or 2575
    )
    try:
        port = int(port_raw)
    except (TypeError, ValueError):
        port = 2575

    if not host:
        return {
            "success": False,
            "message": (
                "HL7v2 connection has no host configured. "
                "Set extra_config.host (and optionally extra_config.port)."
            ),
            "latency_ms": 0,
        }

    start = time.monotonic()
    try:
        with _socket.create_connection((host, port), timeout=10.0):
            pass
        latency_ms = round((time.monotonic() - start) * 1000, 1)
        logger.info(
            "emr_manager: HL7v2 TCP test succeeded %s:%s latency=%.1f ms (connection_id=%s)",
            host,
            port,
            latency_ms,
            connection.get("id"),
        )
        return {
            "success": True,
            "message": f"TCP connection to {host}:{port} succeeded (MLLP port reachable)",
            "latency_ms": latency_ms,
        }
    except TimeoutError:
        latency_ms = round((time.monotonic() - start) * 1000, 1)
        logger.warning(
            "emr_manager: HL7v2 TCP test timed out %s:%s (connection_id=%s)",
            host,
            port,
            connection.get("id"),
        )
        return {
            "success": False,
            "message": f"TCP connection to {host}:{port} timed out after 10 s",
            "latency_ms": latency_ms,
        }
    except ConnectionRefusedError:
        latency_ms = round((time.monotonic() - start) * 1000, 1)
        logger.warning(
            "emr_manager: HL7v2 TCP connection refused %s:%s (connection_id=%s)",
            host,
            port,
            connection.get("id"),
        )
        return {
            "success": False,
            "message": f"TCP connection to {host}:{port} refused — is the MLLP listener running?",
            "latency_ms": latency_ms,
        }
    except OSError as exc:
        latency_ms = round((time.monotonic() - start) * 1000, 1)
        logger.warning(
            "emr_manager: HL7v2 TCP test failed %s:%s: %s (connection_id=%s)",
            host,
            port,
            exc,
            connection.get("id"),
        )
        return {
            "success": False,
            "message": f"TCP connection to {host}:{port} failed: {exc}",
            "latency_ms": latency_ms,
        }


def _test_direct_db(connection: dict) -> dict:
    db_type = (connection.get("db_type") or "mysql").lower()
    host = connection.get("db_host", "")
    port = int(connection.get("db_port") or 3306)
    db_name = connection.get("db_name", "")
    user = connection.get("db_user", "")
    password = connection.get("db_password", "")

    start = time.monotonic()
    try:
        if db_type == "mysql":
            import mysql.connector  # noqa: PLC0415

            conn = mysql.connector.connect(
                host=host,
                port=port,
                database=db_name,
                user=user,
                password=password,
                connect_timeout=10,
            )
            cur = conn.cursor()
            cur.execute("SELECT 1")
            cur.fetchone()
            cur.close()
            conn.close()

        elif db_type == "postgresql":
            import psycopg2  # noqa: PLC0415

            conn = psycopg2.connect(
                host=host,
                port=port,
                dbname=db_name,
                user=user,
                password=password,
                connect_timeout=10,
            )
            cur = conn.cursor()
            cur.execute("SELECT 1")
            cur.fetchone()
            cur.close()
            conn.close()

        else:
            return {
                "success": False,
                "message": f"Unsupported db_type '{db_type}'",
                "latency_ms": 0,
            }

    except Exception as exc:
        latency_ms = int((time.monotonic() - start) * 1000)
        logger.warning(
            "emr_manager: direct_db test failed id=%s: %s", connection.get("id"), exc
        )
        return {"success": False, "message": str(exc), "latency_ms": latency_ms}

    latency_ms = int((time.monotonic() - start) * 1000)
    return {"success": True, "message": "SELECT 1 succeeded", "latency_ms": latency_ms}


def _test_fhir_r4(connection: dict) -> dict:
    # Try the dedicated FHIR adapter first (handles OAuth2)
    fhir_adapter = get_fhir_adapter(connection)
    if fhir_adapter:
        return fhir_adapter.test_connection()

    base_url = (connection.get("base_url") or "").rstrip("/")
    if not base_url:
        return {
            "success": False,
            "message": "base_url is not configured",
            "latency_ms": 0,
        }

    try:
        _assert_safe_outbound_url(base_url)
    except ValueError as exc:
        return {"success": False, "message": str(exc), "latency_ms": 0}

    metadata_url = f"{base_url}/metadata"
    start = time.monotonic()
    try:
        with httpx.Client(timeout=_DEFAULT_TIMEOUT) as client:
            resp = client.get(
                metadata_url,
                headers={"Accept": "application/fhir+json"},
            )
            resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        latency_ms = int((time.monotonic() - start) * 1000)
        return {
            "success": False,
            "message": f"HTTP {exc.response.status_code} from {metadata_url}",
            "latency_ms": latency_ms,
        }
    except Exception as exc:
        latency_ms = int((time.monotonic() - start) * 1000)
        logger.warning(
            "emr_manager: fhir_r4 test failed id=%s: %s", connection.get("id"), exc
        )
        return {"success": False, "message": str(exc), "latency_ms": latency_ms}

    latency_ms = int((time.monotonic() - start) * 1000)
    return {
        "success": True,
        "message": f"CapabilityStatement retrieved from {metadata_url}",
        "latency_ms": latency_ms,
    }


def _test_rest_api(connection: dict) -> dict:
    """Test a REST API connection using the appropriate vendor adapter.

    When the connection has a recognised ``vendor``, the vendor-specific
    adapter is used (proper OAuth2 auth, vendor health endpoint, etc.).
    For unrecognised or missing vendors a generic HTTP probe is performed as
    a fallback.
    """
    vendor: str = (connection.get("vendor") or "").lower().strip()

    # Use the vendor adapter when one is registered.
    if vendor:
        try:
            adapter = get_adapter(connection)
            return adapter.test_connection()
        except ValueError:
            # No adapter for this vendor — fall through to generic probe.
            logger.debug(
                "emr_manager: no vendor adapter for '%s', using generic REST probe",
                vendor,
            )

    # Generic fallback: probe /health then the base URL.
    base_url = (connection.get("api_base_url") or "").rstrip("/")
    if not base_url:
        return {
            "success": False,
            "message": "api_base_url is not configured",
            "latency_ms": 0,
        }

    try:
        _assert_safe_outbound_url(base_url)
    except ValueError as exc:
        return {"success": False, "message": str(exc), "latency_ms": 0}

    api_key = connection.get("api_key", "")
    auth_type = (connection.get("api_auth_type") or "bearer").lower()

    headers: dict[str, str] = {"Accept": "application/json"}
    if api_key and auth_type == "bearer":
        headers["Authorization"] = f"Bearer {api_key}"

    urls_to_try = [f"{base_url}/health", base_url]
    start = time.monotonic()
    last_exc: str = ""
    for url in urls_to_try:
        try:
            with httpx.Client(timeout=_DEFAULT_TIMEOUT) as client:
                resp = client.get(url, headers=headers)
                resp.raise_for_status()
            latency_ms = int((time.monotonic() - start) * 1000)
            return {
                "success": True,
                "message": f"HTTP {resp.status_code} from {url}",
                "latency_ms": latency_ms,
            }
        except httpx.HTTPStatusError as exc:
            last_exc = f"HTTP {exc.response.status_code} from {url}"
        except Exception as exc:
            logger.debug("swallowed exception", exc_info=True)
            last_exc = str(exc)

    latency_ms = int((time.monotonic() - start) * 1000)
    logger.warning(
        "emr_manager: rest_api test failed id=%s: %s", connection.get("id"), last_exc
    )
    return {"success": False, "message": last_exc, "latency_ms": latency_ms}


# ---------------------------------------------------------------------------
# Sync operations
# ---------------------------------------------------------------------------


def trigger_sync(
    connection_id: int, sync_type: str = "incremental", tenant_id: str | None = None
) -> dict:
    """Create a new emr_sync_log entry and run the sync for REST API connections.

    For ``rest_api`` connection types the appropriate vendor adapter is invoked
    synchronously via ``adapter.run_sync()``.  The sync log entry is updated
    with the result before returning.

    For all other connection types a ``'pending'`` log entry is created and the
    actual work is expected to be performed by a background task (existing
    behaviour).

    When *tenant_id* is supplied only connections owned by that tenant can be
    synced.  Raises ``KeyError`` if the connection does not exist.
    """
    _ensure_tables()

    connection = get_connection(connection_id, tenant_id=tenant_id)
    if connection is None:
        raise KeyError(f"EMR connection id={connection_id} not found")

    sync_id = str(uuid.uuid4())
    with raf_cursor() as cur:
        cur.execute(
            """
            INSERT INTO emr_sync_log (sync_id, emr_connection_id, connection_id, sync_type, status, started_at)
            VALUES (%s, %s, %s, %s, 'pending', %s)
            """,
            (sync_id, connection_id, connection_id, sync_type, _now_utc()),
        )

    logger.info(
        "emr_manager: sync triggered sync_id=%s connection_id=%s type=%s",
        sync_id,
        connection_id,
        sync_type,
    )

    connection_type: str = connection.get("connection_type", "")
    if connection_type == "fhir_r4":
        # Run the FHIR adapter sync immediately.
        full_connection = get_connection_with_credentials(connection_id)
        try:
            fhir_adapter = get_fhir_adapter(full_connection)
            if fhir_adapter is None:
                raise ValueError("No FHIR adapter available")
            summary = fhir_adapter.run_sync(sync_type=sync_type)
            patients_synced_f: int = summary.get("patients_synced", 0)
            conditions_found_f: int = summary.get("conditions_found", 0)
            adapter_errors_f: list[str] = summary.get("errors", [])
            status_f = "completed" if not adapter_errors_f else "failed"
            error_msg_f: str | None = "; ".join(adapter_errors_f) if adapter_errors_f else None
            log_sync_result(
                sync_id, status=status_f,
                records_fetched=patients_synced_f,
                records_processed=conditions_found_f,
                records_failed=len(adapter_errors_f),
                error_message=error_msg_f,
            )
            _fhir_result = {
                "sync_id": sync_id, "connection_id": connection_id,
                "sync_type": sync_type, "status": status_f,
                "patients_synced": patients_synced_f,
                "conditions_found": conditions_found_f,
                "errors": adapter_errors_f,
            }
            _emit_sync_completed(_fhir_result, tenant_id, connection_id, sync_type)
            return _fhir_result
        except Exception as exc:
            logger.exception("FHIR sync failed sync_id=%s connection_id=%s", sync_id, connection_id)
            log_sync_result(sync_id, status="failed", records_fetched=0, records_processed=0, records_failed=1, error_message=str(exc))
            return {"sync_id": sync_id, "connection_id": connection_id, "sync_type": sync_type, "status": "failed", "error": str(exc)}

    if connection_type == "rest_api":
        # Run the vendor adapter sync immediately and record results.
        full_connection = get_connection_with_credentials(connection_id)
        vendor: str = (full_connection.get("vendor") or "") if full_connection else ""
        try:
            adapter = get_adapter(full_connection)
            summary = adapter.run_sync(sync_type=sync_type)
            patients_synced: int = summary.get("patients_synced", 0)
            conditions_found: int = summary.get("conditions_found", 0)
            adapter_errors: list[str] = summary.get("errors", [])
            status = "completed" if not adapter_errors else "failed"
            error_msg: str | None = (
                "; ".join(adapter_errors) if adapter_errors else None
            )
            log_sync_result(
                sync_id,
                status=status,
                records_fetched=patients_synced,
                records_processed=conditions_found,
                records_failed=len(adapter_errors),
                error_message=error_msg,
            )
            _rest_result = {
                "sync_id": sync_id,
                "connection_id": connection_id,
                "sync_type": sync_type,
                "status": status,
                "patients_synced": patients_synced,
                "conditions_found": conditions_found,
                "errors": adapter_errors,
            }
            _emit_sync_completed(_rest_result, tenant_id, connection_id, sync_type)
            return _rest_result
        except ValueError as exc:
            # No adapter registered for this vendor; fall back to pending state.
            logger.warning(
                "emr_manager: no REST adapter for vendor '%s' (connection_id=%s): %s",
                vendor,
                connection_id,
                exc,
            )
        except Exception as exc:
            logger.exception(
                "emr_manager: REST adapter sync failed sync_id=%s connection_id=%s",
                sync_id,
                connection_id,
            )
            log_sync_result(
                sync_id,
                status="failed",
                records_fetched=0,
                records_processed=0,
                records_failed=1,
                error_message=str(exc),
            )
            return {
                "sync_id": sync_id,
                "connection_id": connection_id,
                "sync_type": sync_type,
                "status": "failed",
                "error": str(exc),
            }

    if connection_type == "direct_db":
        # Run encounter + diagnosis normalization using the connection's stored db_host/port.
        try:
            result = _sync_direct_db(connection_id, sync_id, sync_type)
            _emit_sync_completed(result, tenant_id, connection_id, sync_type)
            return result
        except Exception as exc:
            logger.exception(
                "emr_manager: direct_db sync failed sync_id=%s connection_id=%s",
                sync_id, connection_id,
            )
            log_sync_result(
                sync_id, status="failed",
                records_fetched=0, records_processed=0, records_failed=1,
                error_message=str(exc),
            )
            return {
                "sync_id": sync_id, "connection_id": connection_id,
                "sync_type": sync_type, "status": "failed", "error": str(exc),
            }

    return {
        "sync_id": sync_id,
        "connection_id": connection_id,
        "sync_type": sync_type,
        "status": "pending",
    }


def _sync_direct_db(connection_id: int, sync_id: str, sync_type: str) -> dict:
    """Pull patients + encounters + diagnoses from OpenEMR via direct DB.

    Uses the host/port/credentials stored in emr_connections (via
    encounter_normalization_service) so the connection always goes to the
    correct host — never falls back to the static env-var pool which may
    point to localhost/127.0.0.1 instead of the Docker service hostname.
    """
    from app.services.encounter_normalization_service import sync_all as _enc_sync_all

    # Resolve tenant_id for this connection.
    with raf_cursor() as _cur:
        _cur.execute("SELECT tenant_id FROM emr_connections WHERE id = %s", (connection_id,))
        _conn_row = _cur.fetchone()
    if not _conn_row:
        raise KeyError(f"_sync_direct_db: emr_connections row not found for id={connection_id}")
    tenant_id: str = str(_conn_row["tenant_id"])

    # sync_all() fetches credentials from emr_connections[connection_id] and
    # uses dynamic_db_cursor(host=db_host, ...) — never touches the static pool.
    result = _enc_sync_all(tenant_id=tenant_id, connection_id=connection_id)

    enc = result.get("encounters", {})
    diag = result.get("diagnoses", {})
    patients_synced: int = enc.get("synced", 0)
    conditions_found: int = diag.get("synced", 0)
    total_errors: int = enc.get("errors", 0) + diag.get("errors", 0)
    sync_status = "completed" if total_errors == 0 else "failed"
    error_msg = f"encounter_errors={enc.get('errors', 0)} diagnosis_errors={diag.get('errors', 0)}" if total_errors else None

    log_sync_result(
        sync_id, status=sync_status,
        records_fetched=patients_synced,
        records_processed=conditions_found,
        records_failed=total_errors,
        error_message=error_msg,
    )

    with raf_cursor() as cur:
        cur.execute(
            "UPDATE emr_connections SET last_sync_at = %s WHERE id = %s",
            (_now_utc(), connection_id),
        )

    logger.info(
        "direct_db sync complete: encounters_synced=%d diagnoses_synced=%d errors=%d",
        patients_synced, conditions_found, total_errors,
    )
    return {
        "sync_id": sync_id, "connection_id": connection_id,
        "sync_type": sync_type, "status": sync_status,
        "patients_synced": patients_synced,
        "conditions_found": conditions_found,
        "errors": [],
        "encounters": enc,
        "diagnoses": diag,
    }


def _cms_age_band(dob_str: str | None) -> str:
    """Derive CMS age band from DOB string (YYYY-MM-DD)."""
    if not dob_str:
        return "65-69"
    from datetime import date as _date
    try:
        dob = _date.fromisoformat(str(dob_str)[:10])
        age = (_date.today() - dob).days // 365
    except (ValueError, TypeError):
        return "65-69"
    if age < 35:
        return "0-34"
    if age < 45:
        return "35-44"
    if age < 55:
        return "45-54"
    if age < 65:
        return "55-64"
    if age < 70:
        return "65-69"
    if age < 75:
        return "70-74"
    if age < 80:
        return "75-79"
    if age < 85:
        return "80-84"
    if age < 90:
        return "85-89"
    if age < 95:
        return "90-94"
    return "95+"


def _upsert_patient_demographics(
    pid: int,
    pt: dict,
    measurement_year: int,
    connection_id: int | None = None,
    tenant_id: str | int | None = None,
) -> None:
    """Insert or update a patient in raf_patient_demographics from OpenEMR data.

    When connection_id and tenant_id are provided, also upserts into the `patients`
    table and `emr_patient_matches` table so the downstream normalization pipeline
    can resolve internal patient IDs from OpenEMR pids.
    """
    sex = (pt.get("sex") or "Male")[0].upper()  # M or F
    if sex not in ("M", "F"):
        sex = "M"
    dob = pt.get("DOB") or pt.get("dob")
    age_band = _cms_age_band(dob)

    with raf_cursor() as cur:
        # --- raf_patient_demographics (original logic) ---
        cur.execute(
            "SELECT id FROM raf_patient_demographics WHERE patient_id = %s AND measurement_year = %s",
            (pid, measurement_year),
        )
        row = cur.fetchone()
        if row:
            cur.execute(
                """UPDATE raf_patient_demographics
                   SET age_band=%s, sex=%s, updated_at=NOW()
                   WHERE patient_id=%s AND measurement_year=%s""",
                (age_band, sex, pid, measurement_year),
            )
        else:
            cur.execute(
                """INSERT INTO raf_patient_demographics
                   (patient_id, measurement_year, age_band, sex, dual_status, disabled, model_segment)
                   VALUES (%s, %s, %s, %s, 0, 0, 'CNA')""",
                (pid, measurement_year, age_band, sex),
            )

        # --- patients table (only when connection context is known) ---
        if connection_id is not None and tenant_id is not None:
            cur.execute(
                """INSERT INTO patients
                       (tenant_id, first_name, last_name, dob, gender,
                        emr_pid, emr_connection_id, data_source, is_active,
                        street, city, state, zip, phone, email,
                        created_at, updated_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, 'direct_db', 1,
                           %s, %s, %s, %s, %s, %s,
                           NOW(), NOW())
                   ON DUPLICATE KEY UPDATE
                       first_name      = VALUES(first_name),
                       last_name       = VALUES(last_name),
                       dob             = VALUES(dob),
                       gender          = VALUES(gender),
                       street          = VALUES(street),
                       city            = VALUES(city),
                       state           = VALUES(state),
                       zip             = VALUES(zip),
                       phone           = VALUES(phone),
                       email           = VALUES(email),
                       updated_at      = NOW()""",
                (
                    tenant_id,
                    pt.get("fname") or pt.get("first_name"),
                    pt.get("lname") or pt.get("last_name"),
                    dob,
                    sex,
                    pid,
                    connection_id,
                    pt.get("street"),
                    pt.get("city"),
                    pt.get("state"),
                    pt.get("postal_code") or pt.get("zip"),
                    pt.get("phone_home") or pt.get("phone"),
                    pt.get("email"),
                ),
            )
            # Retrieve the internal patient.id (whether just inserted or already existing)
            cur.execute(
                """SELECT id FROM patients
                   WHERE emr_pid = %s AND emr_connection_id = %s AND tenant_id = %s
                   LIMIT 1""",
                (pid, connection_id, tenant_id),
            )
            patient_row = cur.fetchone()
            if patient_row:
                internal_patient_id = patient_row["id"]
                # --- emr_patient_matches table ---
                cur.execute(
                    """INSERT INTO emr_patient_matches
                           (patient_id, emr_patient_id, emr_pid, emr_connection_id, tenant_id,
                            match_status, match_method, match_score,
                            created_at, updated_at)
                       VALUES (%s, %s, %s, %s, %s, 'matched', 'exact_sync', 1.0, NOW(), NOW())
                       ON DUPLICATE KEY UPDATE
                           match_status = 'matched',
                           match_method = 'exact_sync',
                           match_score  = 1.0,
                           updated_at   = NOW()""",
                    (
                        internal_patient_id,
                        str(pid),
                        pid,
                        connection_id,
                        tenant_id,
                    ),
                )


def _upsert_patient_hcc(pid: int, icd_codes: list[str], measurement_year: int) -> None:
    """Map ICD-10 codes to HCCs via hccinfhir and upsert into raf_patient_hcc.

    One row per (patient_id, hcc_code, measurement_year) triplet.  ICD-10 codes
    that do not map to any HCC in V28 are stored in a catch-all NULL-hcc_code
    row so they are not silently lost.

    Uses map_icd10_batch (hccinfhir) as the authoritative ICD→HCC engine.
    """
    if not icd_codes:
        return

    # ------------------------------------------------------------------
    # 1. Resolve ICD-10 → HCC mappings in a single batch call.
    # ------------------------------------------------------------------
    try:
        hcc_map = map_icd10_batch(icd_codes, model_version="V28")
    except Exception as exc:
        logger.warning("_upsert_patient_hcc: map_icd10_batch failed — %s", exc)
        hcc_map = {}

    # Group ICD-10 codes by the primary HCC they resolve to.
    # Codes with no mapping are collected under the None key.
    hcc_to_codes: dict[str | None, list[str]] = {}
    for code in icd_codes:
        normalised = code.strip().upper().replace(".", "")
        entry = hcc_map.get(normalised)
        hcc_key: str | None = entry["hcc_code"] if entry else None
        hcc_to_codes.setdefault(hcc_key, []).append(code)

    # ------------------------------------------------------------------
    # 2. Upsert one raf_patient_hcc row per HCC group.
    # ------------------------------------------------------------------
    with raf_cursor() as cur:
        for hcc_code, codes_for_hcc in hcc_to_codes.items():
            # Skip ICD-10 codes that don't map to any HCC — the DB column
            # is NOT NULL so we cannot store them.
            if hcc_code is None:
                continue

            # Retrieve the coefficient from hccinfhir for non-null HCCs.
            raf_coefficient: float = 0.0
            if hcc_code is not None:
                try:
                    raf_coefficient = _hcc_coefficient(int(hcc_code), model_version="V28", segment="CNA")
                except Exception:  # noqa: BLE001 — best-effort guard
                    logger.debug("swallowed exception", exc_info=True)

            cur.execute(
                "SELECT id, icd10_codes FROM raf_patient_hcc "
                "WHERE patient_id = %s AND hcc_code <=> %s AND measurement_year = %s LIMIT 1",
                (pid, hcc_code, measurement_year),
            )
            existing = cur.fetchone()
            if existing:
                try:
                    old_codes = json.loads(existing["icd10_codes"] or "[]")
                except (json.JSONDecodeError, TypeError):
                    old_codes = []
                merged = list(set(old_codes + codes_for_hcc))
                cur.execute(
                    "UPDATE raf_patient_hcc "
                    "SET icd10_codes = %s, raf_coefficient = %s, updated_at = NOW() "
                    "WHERE id = %s",
                    (json.dumps(merged), raf_coefficient, existing["id"]),
                )
            else:
                cur.execute(
                    """INSERT INTO raf_patient_hcc
                       (patient_id, measurement_year, hcc_code, icd10_codes,
                        source_encounter_ids, raf_coefficient, meat_status, is_trumped,
                        model_version)
                       VALUES (%s, %s, %s, %s, '[]', %s, 'pending', 0, 'V28')""",
                    (pid, measurement_year, hcc_code, json.dumps(codes_for_hcc), raf_coefficient),
                )


def log_sync_result(
    sync_id: str,
    status: str,
    records_fetched: int,
    records_processed: int,
    records_failed: int,
    error_message: str | None = None,
) -> None:
    """UPDATE the emr_sync_log row identified by *sync_id* with final results."""
    _ensure_tables()
    with raf_cursor() as cur:
        cur.execute(
            """
            UPDATE emr_sync_log
            SET status = %s,
                records_fetched = %s,
                records_processed = %s,
                records_failed = %s,
                error_message = %s,
                finished_at = %s
            WHERE sync_id = %s
            """,
            (
                status,
                records_fetched,
                records_processed,
                records_failed,
                error_message,
                _now_utc(),
                sync_id,
            ),
        )
    logger.info(
        "emr_manager: sync result logged sync_id=%s status=%s fetched=%s processed=%s failed=%s",
        sync_id,
        status,
        records_fetched,
        records_processed,
        records_failed,
    )


def get_sync_history(
    connection_id: int, limit: int = 20, tenant_id: str | None = None
) -> list[dict]:
    """Return the most recent sync log entries for *connection_id*.

    When *tenant_id* is supplied the query JOINs to ``emr_connections`` to
    verify the connection is owned by that tenant before returning history.
    """
    _ensure_tables()
    with raf_cursor() as cur:
        if tenant_id is not None:
            cur.execute(
                """
                SELECT l.id, l.sync_id, l.connection_id, l.sync_type, l.status,
                       l.records_fetched, l.records_processed, l.records_failed,
                       l.error_message, l.started_at, l.finished_at
                FROM emr_sync_log l
                JOIN emr_connections c ON c.id = l.connection_id
                WHERE l.connection_id = %s AND c.tenant_id = %s
                ORDER BY l.started_at DESC
                LIMIT %s
                """,
                (connection_id, tenant_id, limit),
            )
        else:
            cur.execute(
                """
                SELECT id, sync_id, connection_id, sync_type, status,
                       records_fetched, records_processed, records_failed,
                       error_message, started_at, finished_at
                FROM emr_sync_log
                WHERE connection_id = %s
                ORDER BY started_at DESC
                LIMIT %s
                """,
                (connection_id, limit),
            )
        rows = cur.fetchall() or []
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Field mapping helpers
# ---------------------------------------------------------------------------

_VENDOR_DEFAULT_MAPPINGS: dict[str, dict[str, str]] = {
    "openemr": {
        "patient_id": "pid",
        "first_name": "fname",
        "last_name": "lname",
        "dob": "DOB",
        "gender": "sex",
        "ssn": "ss",
        "icd_codes": "diagnosis.diagnosis_code",
        "encounter_id": "encounter",
    },
    "epic": {
        "patient_id": "id",
        "first_name": "name[0].given[0]",
        "last_name": "name[0].family",
        "dob": "birthDate",
        "gender": "gender",
        "icd_codes": "code.coding[system=http://hl7.org/fhir/sid/icd-10-cm].code",
    },
    "cerner": {
        "patient_id": "id",
        "first_name": "name[0].given[0]",
        "last_name": "name[0].family",
        "dob": "birthDate",
        "gender": "gender",
        "icd_codes": "code.coding[system=http://hl7.org/fhir/sid/icd-10-cm].code",
    },
    "athenahealth": {
        "patient_id": "id",
        "first_name": "name[0].given[0]",
        "last_name": "name[0].family",
        "dob": "birthDate",
        "icd_codes": "code.coding[system=http://hl7.org/fhir/sid/icd-10-cm].code",
    },
    "generic_fhir": {
        "patient_id": "id",
        "icd_codes": "code.coding[system=http://hl7.org/fhir/sid/icd-10-cm].code",
    },
}


def get_default_mappings(vendor: str) -> dict:
    """Return the default field mappings for *vendor*, falling back to an empty dict."""
    return dict(_VENDOR_DEFAULT_MAPPINGS.get(vendor, {}))


def update_mappings(connection_id: int, mappings: dict) -> None:
    """Persist field mappings JSON onto the emr_connections row.

    Raises ``KeyError`` if the connection does not exist.
    """
    _ensure_tables()
    if get_connection(connection_id) is None:
        raise KeyError(f"EMR connection id={connection_id} not found")

    with raf_cursor() as cur:
        cur.execute(
            "UPDATE emr_connections SET field_mappings = %s WHERE id = %s",
            (json.dumps(mappings), connection_id),
        )
    logger.info("emr_manager: mappings updated for connection id=%s", connection_id)


# ---------------------------------------------------------------------------
# Sync schedule management
# ---------------------------------------------------------------------------


def update_sync_schedule(
    connection_id: int,
    sync_enabled: bool,
    sync_interval_minutes: int,
    sync_cron: str | None = None,
) -> dict:
    """Update the sync scheduling fields for an EMR connection.

    Args:
        connection_id:          Row ID in emr_connections.
        sync_enabled:           Whether automatic syncing is active.
        sync_interval_minutes:  How often (in minutes) to run incremental syncs.
        sync_cron:              Optional cron expression (for future Celery beat
                                support).  Pass None to clear.

    Returns:
        The updated connection row (credentials masked).
    Raises:
        KeyError: if the connection does not exist.
        ValueError: if sync_interval_minutes is out of range.
    """
    _ensure_tables()

    if get_connection(connection_id) is None:
        raise KeyError(f"EMR connection id={connection_id} not found")

    if sync_interval_minutes < 1:
        raise ValueError("sync_interval_minutes must be >= 1")

    with raf_cursor() as cur:
        cur.execute(
            """
            UPDATE emr_connections
            SET sync_enabled = %s,
                sync_interval_minutes = %s,
                sync_cron = %s
            WHERE id = %s
            """,
            (int(sync_enabled), sync_interval_minutes, sync_cron, connection_id),
        )

    logger.info(
        "emr_manager: sync schedule updated connection id=%s enabled=%s interval=%sm",
        connection_id,
        sync_enabled,
        sync_interval_minutes,
    )
    result = get_connection(connection_id)
    if result is None:
        raise RuntimeError("Failed to retrieve updated connection")
    return result


# ---------------------------------------------------------------------------
# Auto-registration helpers
# ---------------------------------------------------------------------------


def auto_register_openemr() -> dict | None:
    """Auto-create an OpenEMR connection from environment variables at startup.

    Reads the following env vars (all optional – function is a no-op if
    ``OPENEMR_DB_HOST`` is not set):

    * ``OPENEMR_DB_HOST``
    * ``OPENEMR_DB_PORT``  (default 3306)
    * ``OPENEMR_DB_NAME``  (default ``openemr``)
    * ``OPENEMR_DB_USER``
    * ``OPENEMR_DB_PASSWORD``
    * ``OPENEMR_TENANT_ID`` (default ``default``)

    Returns the connection dict (masked) if a row was created, or None if
    either the env var is not set or a row already exists for vendor='openemr'.
    """
    _ensure_tables()

    db_host = os.getenv("OPENEMR_DB_HOST", "")
    if not db_host:
        logger.debug("emr_manager: OPENEMR_DB_HOST not set – skipping auto-register")
        return None

    tenant_id = os.getenv("OPENEMR_TENANT_ID", "")
    if not tenant_id:
        logger.error(
            "emr_manager: OPENEMR_TENANT_ID env var is not set — "
            "refusing to auto-register OpenEMR connection without tenant scope "
            "(HIPAA multi-tenant isolation)"
        )
        return None

    # Check if an openemr connection already exists for this tenant.
    with raf_cursor() as cur:
        cur.execute(
            "SELECT id FROM emr_connections WHERE vendor = 'openemr' AND tenant_id = %s LIMIT 1",
            (tenant_id,),
        )
        existing = cur.fetchone()

    db_port = int(os.getenv("OPENEMR_DB_PORT", "3306"))
    db_name = os.getenv("OPENEMR_DB_NAME", "openemr")
    db_user = os.getenv("OPENEMR_DB_USER", "")
    db_password = os.getenv("OPENEMR_DB_PASSWORD", "")

    if existing:
        existing_id = existing["id"] if isinstance(existing, dict) else existing[0]
        # If the stored db_host differs from what the current env says (e.g. the
        # row was registered with "localhost" before the Docker env var was set
        # to "mysql"), update it in place so pipeline sync_encounters can reach
        # the correct host.
        with raf_cursor() as cur:
            cur.execute(
                "SELECT db_host FROM emr_connections WHERE id = %s",
                (existing_id,),
            )
            stored = cur.fetchone()
        stored_host = (stored or {}).get("db_host", "") if isinstance(stored, dict) else ""
        if stored_host != db_host:
            with raf_cursor() as cur:
                cur.execute(
                    "UPDATE emr_connections SET db_host = %s WHERE id = %s",
                    (db_host, existing_id),
                )
            logger.info(
                "emr_manager: corrected db_host for OpenEMR connection id=%s: %r → %r",
                existing_id,
                stored_host,
                db_host,
            )
        else:
            logger.debug(
                "emr_manager: OpenEMR connection already exists (id=%s) – skipping auto-register",
                existing_id,
            )
        return None

    openemr_url = os.getenv("OPENEMR_URL")
    if not openemr_url and os.getenv("APP_ENV") == "production":
        raise RuntimeError("OPENEMR_URL is required in production")
    openemr_url = openemr_url or "http://localhost:8080"

    connection_data = {
        "tenant_id": tenant_id,
        "name": "OpenEMR (auto-registered)",
        "display_name": "OpenEMR (auto-registered)",
        "vendor": "openemr",
        "connection_type": "direct_db",
        "db_type": "mysql",
        "db_host": db_host,
        "db_port": db_port,
        "db_name": db_name,
        "db_user": db_user,
        "db_password": db_password,
        "base_url": openemr_url,
        "field_mappings": get_default_mappings("openemr"),
        "is_active": 1,
    }

    try:
        result = create_connection(connection_data)
        logger.info(
            "emr_manager: auto-registered OpenEMR connection id=%s host=%s",
            result.get("id"),
            db_host,
        )
        return result
    except Exception as exc:
        logger.error("emr_manager: failed to auto-register OpenEMR connection: %s", exc)
        return None


# ---------------------------------------------------------------------------
# OAuth2 Authorization Code helpers
# ---------------------------------------------------------------------------


def store_oauth2_state(connection_id: int, state_key: str, code_verifier: str, redirect_uri: str = "") -> None:
    """Store PKCE state for an OAuth2 authorization flow."""
    with raf_cursor() as cur:
        # Clean up stale entries older than 10 minutes
        cur.execute("DELETE FROM emr_oauth2_state WHERE created_at < NOW() - INTERVAL 10 MINUTE")
        # Ensure redirect_uri column exists
        try:
            cur.execute(
                "INSERT INTO emr_oauth2_state (state_key, connection_id, code_verifier, redirect_uri) VALUES (%s, %s, %s, %s)",
                (state_key, connection_id, code_verifier, redirect_uri),
            )
        except Exception:
            logger.debug("swallowed exception", exc_info=True)
            cur.execute(
                "INSERT INTO emr_oauth2_state (state_key, connection_id, code_verifier) VALUES (%s, %s, %s)",
                (state_key, connection_id, code_verifier),
            )


def pop_oauth2_state(state_key: str) -> dict | None:
    """Retrieve and delete OAuth2 state (one-time use)."""
    with raf_cursor() as cur:
        cur.execute(
            "SELECT connection_id, code_verifier, redirect_uri FROM emr_oauth2_state WHERE state_key = %s",
            (state_key,),
        )
        row = cur.fetchone()
        if not row:
            return None
        cur.execute("DELETE FROM emr_oauth2_state WHERE state_key = %s", (state_key,))
        return {
            "connection_id": row["connection_id"],
            "code_verifier": row["code_verifier"],
            "redirect_uri": row.get("redirect_uri") or "",
        }


def store_oauth2_tokens(
    connection_id: int,
    access_token: str,
    refresh_token: str,
    expires_in: int = 3600,
) -> None:
    """Encrypt and store OAuth2 tokens for a connection."""
    enc_access = encrypt(access_token) if access_token else None
    enc_refresh = encrypt(refresh_token) if refresh_token else None
    with raf_cursor() as cur:
        cur.execute(
            """
            UPDATE emr_connections
            SET access_token = %s,
                refresh_token_emr = %s,
                token_expires_at = NOW() + INTERVAL %s SECOND
            WHERE id = %s
            """,
            (enc_access, enc_refresh, expires_in, connection_id),
        )
    logger.info("emr_manager: stored OAuth2 tokens for connection %s (expires in %ss)", connection_id, expires_in)


def deactivate_other_connections(connection_id: int, tenant_id: str) -> None:
    """Atomically deactivate every other connection for *tenant_id* and activate
    the specified one in a single cursor block.

    Previously the deactivation of other rows and the subsequent activation of
    this row were separate cursor (transaction) boundaries.  A concurrent
    request could slip its own activation in between those two statements,
    leaving multiple connections marked active simultaneously.

    The fix uses ``SELECT … FOR UPDATE`` to lock the relevant rows for the
    duration of the transaction, then updates both the target connection
    (``is_active = 1``) and all others (``is_active = 0``) before the lock is
    released on commit.
    """
    with raf_cursor() as cur:
        # Lock all tenant rows for this tenant to prevent concurrent toggles
        # from interleaving between the deactivate and activate writes.
        cur.execute(
            "SELECT id FROM emr_connections WHERE tenant_id = %s FOR UPDATE",
            (tenant_id,),
        )
        cur.fetchall()  # consume result set to avoid "Unread result found"
        cur.execute(
            "UPDATE emr_connections SET is_active = 0 WHERE id != %s AND tenant_id = %s",
            (connection_id, tenant_id),
        )
        cur.execute(
            "UPDATE emr_connections SET is_active = 1 WHERE id = %s AND tenant_id = %s",
            (connection_id, tenant_id),
        )
    logger.info(
        "emr_manager: atomically activated connection %s, deactivated all others for tenant '%s'",
        connection_id,
        tenant_id,
    )
