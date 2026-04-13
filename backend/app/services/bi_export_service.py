"""
BI Export Service
=================
Provides data extraction, formatting, and push capabilities for external
Business Intelligence tools: Tableau, PowerBI, Looker, Metabase, and any
generic ODBC/API consumer.

Key responsibilities
--------------------
- Pre-built dataset definitions for the six core analytics views.
- Data export to CSV, JSON, Excel (xlsx via openpyxl when available), and
  a JSON structure compatible with PowerBI REST API push datasets.
- Tableau Web Data Connector (WDC) metadata and data endpoint helpers.
- OData v4 feed generation for PowerBI "Get Data → OData Feed".
- PowerBI REST API push (when connection config provides a push URL and token).
- Optional PHI-strip / anonymisation pass before any export leaves the system.
- Parameterised custom SQL query builder with safe placeholder binding.
- Celery-compatible refresh task helpers.
- Connection CRUD with AES-256-GCM key encryption mirroring the pattern used
  by direct_messaging_service.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import secrets
import time
from base64 import b64decode, b64encode
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional dependency: openpyxl for Excel export
# ---------------------------------------------------------------------------
try:
    import openpyxl
    from openpyxl.styles import Font, PatternFill

    _OPENPYXL_AVAILABLE = True
except ImportError:
    _OPENPYXL_AVAILABLE = False
    logger.info("openpyxl not installed — Excel export falls back to CSV")

# ---------------------------------------------------------------------------
# Optional dependency: requests for outbound HTTP push
# ---------------------------------------------------------------------------
try:
    import requests as _requests

    _REQUESTS_AVAILABLE = True
except ImportError:
    _requests = None  # type: ignore[assignment]
    _REQUESTS_AVAILABLE = False

from app.db import raf_cursor

# ---------------------------------------------------------------------------
# Encryption helpers (reuses JWT_SECRET like direct_messaging_service)
# ---------------------------------------------------------------------------


def _derive_key() -> bytes:
    """Derive a 32-byte AES key from JWT_SECRET."""
    import hashlib

    secret = os.getenv("JWT_SECRET")
    if not secret:
        raise RuntimeError(
            "JWT_SECRET environment variable must be set for BI export encryption"
        )
    return hashlib.sha256(secret.encode()).digest()


def _encrypt_value(plaintext: str) -> str:
    """AES-256-GCM encrypt and return a base64-encoded payload."""
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        key = _derive_key()
        nonce = secrets.token_bytes(12)
        ct = AESGCM(key).encrypt(nonce, plaintext.encode(), None)
        return b64encode(nonce + ct).decode()
    except Exception as exc:
        logger.error("Encryption failed: %s", exc)
        raise


def _decrypt_value(encoded: str) -> str:
    """Decrypt a value produced by _encrypt_value."""
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        raw = b64decode(encoded)
        nonce, ct = raw[:12], raw[12:]
        return AESGCM(_derive_key()).decrypt(nonce, ct, None).decode()
    except Exception as exc:
        logger.error("Decryption failed: %s", exc)
        raise


# ---------------------------------------------------------------------------
# Pre-built dataset definitions
# ---------------------------------------------------------------------------

#: Each entry maps to a dataset_type and carries the canonical SQL template
#: and column schema.  :tenant_id is always injected at query time.
PREBUILT_DATASETS: dict[str, dict[str, Any]] = {
    "raf_scores": {
        "name": "RAF Scores with Demographics",
        "description": (
            "Patient-level CMS-HCC RAF scores joined with demographics. "
            "Includes model version, payment year, and score components."
        ),
        "query_template": """
            SELECT
                rs.patient_id,
                rs.payment_year,
                rs.model_version,
                rs.final_raf,
                rs.demographic_raf,
                rs.disease_raf,
                rs.hcc_count,
                rs.calculated_at,
                rs.tenant_id
            FROM raf_scores rs
            WHERE rs.tenant_id = :tenant_id
            ORDER BY rs.patient_id, rs.payment_year DESC
        """,
        "columns_config": [
            {
                "name": "patient_id",
                "type": "integer",
                "description": "Internal patient identifier",
                "phi": True,
            },
            {
                "name": "payment_year",
                "type": "integer",
                "description": "CMS payment year",
                "phi": False,
            },
            {
                "name": "model_version",
                "type": "string",
                "description": "HCC model (V24/V28/RxHCC)",
                "phi": False,
            },
            {
                "name": "final_raf",
                "type": "decimal",
                "description": "Total RAF score",
                "phi": False,
            },
            {
                "name": "demographic_raf",
                "type": "decimal",
                "description": "Demographic component",
                "phi": False,
            },
            {
                "name": "disease_raf",
                "type": "decimal",
                "description": "Disease component",
                "phi": False,
            },
            {
                "name": "hcc_count",
                "type": "integer",
                "description": "Number of mapped HCCs",
                "phi": False,
            },
            {
                "name": "calculated_at",
                "type": "datetime",
                "description": "Score calculation timestamp",
                "phi": False,
            },
            {
                "name": "tenant_id",
                "type": "string",
                "description": "Tenant discriminator",
                "phi": False,
            },
        ],
    },
    "hcc_gaps": {
        "name": "HCC Gap Analysis",
        "description": (
            "Open and closed HCC gaps with revenue impact estimates. "
            "Sourced from suspect conditions and attestation workflow."
        ),
        "query_template": """
            SELECT
                sc.id                   AS gap_id,
                sc.patient_id,
                sc.icd10_code,
                sc.hcc_code,
                sc.status,
                sc.revenue_impact,
                sc.confidence_score,
                sc.source,
                sc.created_at,
                sc.resolved_at,
                sc.tenant_id
            FROM suspect_conditions sc
            WHERE sc.tenant_id = :tenant_id
            ORDER BY sc.revenue_impact DESC, sc.created_at DESC
        """,
        "columns_config": [
            {
                "name": "gap_id",
                "type": "integer",
                "description": "Gap record identifier",
                "phi": False,
            },
            {
                "name": "patient_id",
                "type": "integer",
                "description": "Patient identifier",
                "phi": True,
            },
            {
                "name": "icd10_code",
                "type": "string",
                "description": "ICD-10-CM code",
                "phi": False,
            },
            {
                "name": "hcc_code",
                "type": "string",
                "description": "Mapped HCC category",
                "phi": False,
            },
            {
                "name": "status",
                "type": "string",
                "description": "open/closed/rejected",
                "phi": False,
            },
            {
                "name": "revenue_impact",
                "type": "decimal",
                "description": "Estimated annual $ impact",
                "phi": False,
            },
            {
                "name": "confidence_score",
                "type": "decimal",
                "description": "ML confidence (0-1)",
                "phi": False,
            },
            {
                "name": "source",
                "type": "string",
                "description": "Detection source",
                "phi": False,
            },
            {
                "name": "created_at",
                "type": "datetime",
                "description": "Gap identified timestamp",
                "phi": False,
            },
            {
                "name": "resolved_at",
                "type": "datetime",
                "description": "Gap resolution timestamp",
                "phi": False,
            },
            {
                "name": "tenant_id",
                "type": "string",
                "description": "Tenant discriminator",
                "phi": False,
            },
        ],
    },
    "provider_performance": {
        "name": "Provider Performance Metrics",
        "description": (
            "Per-provider RAF capture rates, HCC gap closure rates, and "
            "panel statistics. Useful for network management dashboards."
        ),
        "query_template": """
            SELECT
                p.id                    AS provider_id,
                p.name                  AS provider_name,
                p.npi,
                p.specialty,
                p.raf_capture_rate,
                p.avg_raf_score,
                p.total_patients,
                p.hcc_gaps_identified,
                p.hcc_gaps_closed,
                p.tenant_id
            FROM providers p
            WHERE p.tenant_id = :tenant_id
            ORDER BY p.raf_capture_rate DESC
        """,
        "columns_config": [
            {
                "name": "provider_id",
                "type": "integer",
                "description": "Provider identifier",
                "phi": False,
            },
            {
                "name": "provider_name",
                "type": "string",
                "description": "Provider full name",
                "phi": False,
            },
            {
                "name": "npi",
                "type": "string",
                "description": "NPI number",
                "phi": False,
            },
            {
                "name": "specialty",
                "type": "string",
                "description": "Clinical specialty",
                "phi": False,
            },
            {
                "name": "raf_capture_rate",
                "type": "decimal",
                "description": "RAF capture rate %",
                "phi": False,
            },
            {
                "name": "avg_raf_score",
                "type": "decimal",
                "description": "Panel average RAF",
                "phi": False,
            },
            {
                "name": "total_patients",
                "type": "integer",
                "description": "Active patient panel size",
                "phi": False,
            },
            {
                "name": "hcc_gaps_identified",
                "type": "integer",
                "description": "Open HCC gaps",
                "phi": False,
            },
            {
                "name": "hcc_gaps_closed",
                "type": "integer",
                "description": "Closed HCC gaps YTD",
                "phi": False,
            },
            {
                "name": "tenant_id",
                "type": "string",
                "description": "Tenant discriminator",
                "phi": False,
            },
        ],
    },
    "claims_summary": {
        "name": "Claims Summary with HCC Mapping",
        "description": (
            "Adjudicated claims aggregated by patient and date of service, "
            "annotated with HCC category mappings from the claims pipeline."
        ),
        "query_template": """
            SELECT
                c.id                AS claim_id,
                c.patient_id,
                c.claim_type,
                c.service_date,
                c.icd10_codes,
                c.hcc_codes,
                c.total_charge,
                c.allowed_amount,
                c.paid_amount,
                c.status,
                c.payer_name,
                c.tenant_id
            FROM claims c
            WHERE c.tenant_id = :tenant_id
            ORDER BY c.service_date DESC
        """,
        "columns_config": [
            {
                "name": "claim_id",
                "type": "integer",
                "description": "Claim identifier",
                "phi": False,
            },
            {
                "name": "patient_id",
                "type": "integer",
                "description": "Patient identifier",
                "phi": True,
            },
            {
                "name": "claim_type",
                "type": "string",
                "description": "837P / 837I / encounter",
                "phi": False,
            },
            {
                "name": "service_date",
                "type": "date",
                "description": "Date of service",
                "phi": False,
            },
            {
                "name": "icd10_codes",
                "type": "string",
                "description": "Comma-separated ICD codes",
                "phi": False,
            },
            {
                "name": "hcc_codes",
                "type": "string",
                "description": "Mapped HCC categories",
                "phi": False,
            },
            {
                "name": "total_charge",
                "type": "decimal",
                "description": "Total billed charge",
                "phi": False,
            },
            {
                "name": "allowed_amount",
                "type": "decimal",
                "description": "Payer allowed amount",
                "phi": False,
            },
            {
                "name": "paid_amount",
                "type": "decimal",
                "description": "Paid amount",
                "phi": False,
            },
            {
                "name": "status",
                "type": "string",
                "description": "adjudicated/denied/pending",
                "phi": False,
            },
            {
                "name": "payer_name",
                "type": "string",
                "description": "Insurance payer name",
                "phi": False,
            },
            {
                "name": "tenant_id",
                "type": "string",
                "description": "Tenant discriminator",
                "phi": False,
            },
        ],
    },
    "quality_metrics": {
        "name": "Quality / HEDIS Metrics",
        "description": (
            "HEDIS measure rates and STARS scores by provider and population. "
            "Suitable for quality committee reporting and CMS STAR submissions."
        ),
        "query_template": """
            SELECT
                qm.id               AS metric_id,
                qm.measure_code,
                qm.measure_name,
                qm.numerator,
                qm.denominator,
                qm.rate,
                qm.benchmark_rate,
                qm.performance_year,
                qm.provider_id,
                qm.tenant_id
            FROM quality_measures qm
            WHERE qm.tenant_id = :tenant_id
            ORDER BY qm.performance_year DESC, qm.measure_code
        """,
        "columns_config": [
            {
                "name": "metric_id",
                "type": "integer",
                "description": "Metric record identifier",
                "phi": False,
            },
            {
                "name": "measure_code",
                "type": "string",
                "description": "HEDIS measure identifier",
                "phi": False,
            },
            {
                "name": "measure_name",
                "type": "string",
                "description": "Measure full name",
                "phi": False,
            },
            {
                "name": "numerator",
                "type": "integer",
                "description": "Compliant member count",
                "phi": False,
            },
            {
                "name": "denominator",
                "type": "integer",
                "description": "Eligible member count",
                "phi": False,
            },
            {
                "name": "rate",
                "type": "decimal",
                "description": "Compliance rate (0-1)",
                "phi": False,
            },
            {
                "name": "benchmark_rate",
                "type": "decimal",
                "description": "NCQA benchmark rate",
                "phi": False,
            },
            {
                "name": "performance_year",
                "type": "integer",
                "description": "Measurement year",
                "phi": False,
            },
            {
                "name": "provider_id",
                "type": "integer",
                "description": "Provider identifier",
                "phi": False,
            },
            {
                "name": "tenant_id",
                "type": "string",
                "description": "Tenant discriminator",
                "phi": False,
            },
        ],
    },
    "financial": {
        "name": "Financial Reconciliation",
        "description": (
            "Risk-adjusted revenue, capitation payments, and RAF-driven "
            "reconciliation by payment year and model version."
        ),
        "query_template": """
            SELECT
                rs.payment_year,
                rs.model_version,
                rs.tenant_id,
                COUNT(DISTINCT rs.patient_id)           AS member_count,
                AVG(rs.final_raf)                       AS avg_raf,
                SUM(rs.final_raf)                       AS total_raf,
                SUM(rs.final_raf) * 10000               AS estimated_revenue_usd,
                MAX(rs.calculated_at)                   AS last_calculated
            FROM raf_scores rs
            WHERE rs.tenant_id = :tenant_id
            GROUP BY rs.payment_year, rs.model_version, rs.tenant_id
            ORDER BY rs.payment_year DESC
        """,
        "columns_config": [
            {
                "name": "payment_year",
                "type": "integer",
                "description": "CMS payment year",
                "phi": False,
            },
            {
                "name": "model_version",
                "type": "string",
                "description": "HCC model version",
                "phi": False,
            },
            {
                "name": "tenant_id",
                "type": "string",
                "description": "Tenant discriminator",
                "phi": False,
            },
            {
                "name": "member_count",
                "type": "integer",
                "description": "Unique member count",
                "phi": False,
            },
            {
                "name": "avg_raf",
                "type": "decimal",
                "description": "Average RAF score",
                "phi": False,
            },
            {
                "name": "total_raf",
                "type": "decimal",
                "description": "Sum of all RAF scores",
                "phi": False,
            },
            {
                "name": "estimated_revenue_usd",
                "type": "decimal",
                "description": "Estimated revenue (placeholder)",
                "phi": False,
            },
            {
                "name": "last_calculated",
                "type": "datetime",
                "description": "Most recent score timestamp",
                "phi": False,
            },
        ],
    },
}


# ---------------------------------------------------------------------------
# PHI anonymisation
# ---------------------------------------------------------------------------

_PHI_COLUMNS: set[str] = {
    "patient_id",
    "first_name",
    "last_name",
    "full_name",
    "dob",
    "date_of_birth",
    "ssn",
    "mrn",
    "address",
    "city",
    "state",
    "zip",
    "phone",
    "email",
    "member_id",
    "subscriber_id",
}


def _strip_phi(
    rows: list[dict[str, Any]], columns_config: list[dict]
) -> list[dict[str, Any]]:
    """Replace PHI column values with anonymised tokens."""
    phi_names = {col["name"] for col in columns_config if col.get("phi")}
    phi_names |= _PHI_COLUMNS  # belt-and-suspenders: catch unlisted PHI columns
    result = []
    for i, row in enumerate(rows):
        clean = {}
        for k, v in row.items():
            clean[k] = f"ANON_{i}" if k in phi_names else v
        result.append(clean)
    return result


# ---------------------------------------------------------------------------
# Query execution
# ---------------------------------------------------------------------------


def _run_query(
    sql: str,
    params: dict[str, Any],
    limit: int | None = None,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """
    Execute *sql* against the raf_intelligence DB with named :placeholder
    binding.  Returns a list of row dicts.

    mysql-connector-python uses %(name)s syntax, not :name, so we rewrite
    the placeholders before sending to the driver.
    """
    # Convert :param_name → %(param_name)s
    import re

    def _rewrite(m: re.Match) -> str:
        return f"%({m.group(1)})s"

    rewritten = re.sub(r":([a-zA-Z_][a-zA-Z0-9_]*)", _rewrite, sql.strip())

    if limit is not None:
        rewritten = rewritten.rstrip(";") + f" LIMIT {int(limit)} OFFSET {int(offset)}"

    with raf_cursor() as cur:
        cur.execute(rewritten, params)
        return cur.fetchall()


# ---------------------------------------------------------------------------
# Connection CRUD helpers
# ---------------------------------------------------------------------------


def create_connection(
    name: str,
    bi_tool: str,
    connection_config: dict,
    api_key: str | None,
    refresh_schedule: str | None,
    tenant_id: str,
) -> int:
    """Persist a new BI connection. Returns the new row id."""
    api_key_encrypted = _encrypt_value(api_key) if api_key else None
    with raf_cursor() as cur:
        cur.execute(
            """
            INSERT INTO bi_connections
              (name, bi_tool, connection_config, api_key_encrypted,
               refresh_schedule, tenant_id)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                name,
                bi_tool,
                json.dumps(connection_config) if connection_config else None,
                api_key_encrypted,
                refresh_schedule,
                tenant_id,
            ),
        )
        return cur.lastrowid


def list_connections(tenant_id: str) -> list[dict[str, Any]]:
    """Return all connections for a tenant (api_key_encrypted is excluded)."""
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT id, name, bi_tool, connection_config, refresh_schedule,
                   last_sync_at, status, error_message, tenant_id,
                   created_at, updated_at
            FROM bi_connections
            WHERE tenant_id = %s
            ORDER BY name
            """,
            (tenant_id,),
        )
        rows = cur.fetchall()
    result = []
    for row in rows:
        r = dict(row)
        if isinstance(r.get("connection_config"), str):
            try:
                r["connection_config"] = json.loads(r["connection_config"])
            except (json.JSONDecodeError, TypeError):
                pass
        result.append(r)
    return result


def get_connection(connection_id: int, tenant_id: str) -> dict[str, Any] | None:
    """Fetch a single connection record (does not decrypt api_key)."""
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT id, name, bi_tool, connection_config, refresh_schedule,
                   last_sync_at, status, error_message, tenant_id,
                   created_at, updated_at
            FROM bi_connections
            WHERE id = %s AND tenant_id = %s
            """,
            (connection_id, tenant_id),
        )
        row = cur.fetchone()
    if not row:
        return None
    r = dict(row)
    if isinstance(r.get("connection_config"), str):
        try:
            r["connection_config"] = json.loads(r["connection_config"])
        except (json.JSONDecodeError, TypeError):
            pass
    return r


def _get_connection_api_key(connection_id: int, tenant_id: str) -> str | None:
    """Internal: fetch and decrypt the api_key for a connection."""
    with raf_cursor() as cur:
        cur.execute(
            "SELECT api_key_encrypted FROM bi_connections WHERE id = %s AND tenant_id = %s",
            (connection_id, tenant_id),
        )
        row = cur.fetchone()
    if not row or not row["api_key_encrypted"]:
        return None
    try:
        return _decrypt_value(row["api_key_encrypted"])
    except Exception:
        return None


def _update_connection_status(
    connection_id: int,
    status: str,
    error_message: str | None = None,
    last_sync_at: datetime | None = None,
) -> None:
    with raf_cursor() as cur:
        cur.execute(
            """
            UPDATE bi_connections
            SET status = %s,
                error_message = %s,
                last_sync_at = COALESCE(%s, last_sync_at)
            WHERE id = %s
            """,
            (status, error_message, last_sync_at, connection_id),
        )


# ---------------------------------------------------------------------------
# Dataset CRUD helpers
# ---------------------------------------------------------------------------


def list_datasets(tenant_id: str) -> list[dict[str, Any]]:
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT id, name, description, dataset_type, columns_config,
                   row_count, last_refreshed_at, refresh_frequency,
                   format, status, tenant_id, created_at, updated_at
            FROM bi_datasets
            WHERE tenant_id = %s
            ORDER BY dataset_type, name
            """,
            (tenant_id,),
        )
        rows = cur.fetchall()
    result = []
    for row in rows:
        r = dict(row)
        if isinstance(r.get("columns_config"), str):
            try:
                r["columns_config"] = json.loads(r["columns_config"])
            except (json.JSONDecodeError, TypeError):
                pass
        result.append(r)
    return result


def get_dataset(dataset_id: int, tenant_id: str) -> dict[str, Any] | None:
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT id, name, description, dataset_type, query_template,
                   columns_config, row_count, last_refreshed_at,
                   refresh_frequency, file_path, format, status,
                   error_message, tenant_id, created_at, updated_at
            FROM bi_datasets
            WHERE id = %s AND tenant_id = %s
            """,
            (dataset_id, tenant_id),
        )
        row = cur.fetchone()
    if not row:
        return None
    r = dict(row)
    for field in ("columns_config",):
        if isinstance(r.get(field), str):
            try:
                r[field] = json.loads(r[field])
            except (json.JSONDecodeError, TypeError):
                pass
    return r


def create_dataset(
    name: str,
    description: str | None,
    dataset_type: str,
    query_template: str | None,
    columns_config: list,
    refresh_frequency: str,
    fmt: str,
    tenant_id: str,
) -> int:
    with raf_cursor() as cur:
        cur.execute(
            """
            INSERT INTO bi_datasets
              (name, description, dataset_type, query_template, columns_config,
               refresh_frequency, format, tenant_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                name,
                description,
                dataset_type,
                query_template,
                json.dumps(columns_config) if columns_config else None,
                refresh_frequency,
                fmt,
                tenant_id,
            ),
        )
        return cur.lastrowid


def update_dataset(dataset_id: int, updates: dict[str, Any], tenant_id: str) -> bool:
    allowed = {
        "name",
        "description",
        "query_template",
        "columns_config",
        "refresh_frequency",
        "format",
    }
    fields = {k: v for k, v in updates.items() if k in allowed}
    if not fields:
        return False
    set_clauses = ", ".join(f"{k} = %s" for k in fields)
    values = list(fields.values())
    # Serialise JSON fields
    for i, k in enumerate(fields):
        if k == "columns_config" and isinstance(values[i], (list, dict)):
            values[i] = json.dumps(values[i])
    with raf_cursor() as cur:
        cur.execute(
            f"UPDATE bi_datasets SET {set_clauses} WHERE id = %s AND tenant_id = %s",
            values + [dataset_id, tenant_id],
        )
        return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Data extraction
# ---------------------------------------------------------------------------


def _resolve_query(dataset: dict[str, Any]) -> tuple[str, list[dict]]:
    """
    Return (sql_template, columns_config) for a dataset record.

    If the dataset has a custom query_template it is used directly.
    Otherwise we fall back to the matching pre-built definition.
    """
    dt = dataset.get("dataset_type", "custom")
    prebuilt = PREBUILT_DATASETS.get(dt, {})

    sql = dataset.get("query_template") or prebuilt.get("query_template", "")
    columns = dataset.get("columns_config") or prebuilt.get("columns_config", [])

    if isinstance(columns, str):
        try:
            columns = json.loads(columns)
        except json.JSONDecodeError:
            columns = []

    return sql, columns


def fetch_dataset_rows(
    dataset: dict[str, Any],
    tenant_id: str,
    limit: int | None = None,
    offset: int = 0,
    extra_params: dict[str, Any] | None = None,
    anonymise: bool = False,
) -> tuple[list[dict[str, Any]], list[dict]]:
    """
    Execute the dataset query and return (rows, columns_config).

    Parameters
    ----------
    dataset:      Dataset record dict from get_dataset().
    tenant_id:    Tenant filter injected as :tenant_id.
    limit:        Optional row cap (used for preview).
    offset:       Pagination offset.
    extra_params: Additional named parameters to bind into the template.
    anonymise:    Strip PHI fields when True.
    """
    sql, columns = _resolve_query(dataset)
    if not sql:
        return [], columns

    params = {"tenant_id": tenant_id}
    if extra_params:
        params.update(extra_params)

    rows = _run_query(sql, params, limit=limit, offset=offset)

    # Convert datetime/date objects to ISO strings for serialisation
    serialised = []
    for row in rows:
        r = {}
        for k, v in row.items():
            if hasattr(v, "isoformat"):
                r[k] = v.isoformat()
            else:
                r[k] = v
        serialised.append(r)

    if anonymise:
        serialised = _strip_phi(serialised, columns)

    return serialised, columns


# ---------------------------------------------------------------------------
# Export formatters
# ---------------------------------------------------------------------------


def export_csv(rows: list[dict[str, Any]], columns: list[dict]) -> bytes:
    """Return UTF-8 encoded CSV bytes."""
    if not rows:
        col_names = [c["name"] for c in columns]
    else:
        col_names = list(rows[0].keys())

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=col_names, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8")


def export_json(rows: list[dict[str, Any]], columns: list[dict]) -> bytes:
    """Return pretty-printed JSON bytes."""
    payload = {
        "columns": columns,
        "row_count": len(rows),
        "rows": rows,
        "exported_at": datetime.now(timezone.utc).isoformat(),
    }
    return json.dumps(payload, default=str, indent=2).encode("utf-8")


def export_excel(
    rows: list[dict[str, Any]], columns: list[dict], sheet_name: str = "Data"
) -> bytes:
    """
    Return Excel (.xlsx) bytes using openpyxl.
    Falls back to CSV content if openpyxl is not installed.
    """
    if not _OPENPYXL_AVAILABLE:
        logger.warning("openpyxl not available — returning CSV instead of XLSX")
        return export_csv(rows, columns)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_name[:31]  # Excel sheet name limit

    header_fill = PatternFill(
        start_color="1F4E79", end_color="1F4E79", fill_type="solid"
    )
    header_font = Font(color="FFFFFF", bold=True)

    col_names = (
        [c["name"] for c in columns]
        if columns
        else (list(rows[0].keys()) if rows else [])
    )

    # Header row
    for col_idx, col_name in enumerate(col_names, start=1):
        cell = ws.cell(row=1, column=col_idx, value=col_name)
        cell.fill = header_fill
        cell.font = header_font

    # Data rows
    for row_idx, row in enumerate(rows, start=2):
        for col_idx, col_name in enumerate(col_names, start=1):
            ws.cell(row=row_idx, column=col_idx, value=row.get(col_name))

    # Auto-width (approximate)
    for col_idx, col_name in enumerate(col_names, start=1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(col_idx)].width = max(
            12, len(col_name) + 2
        )

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def render_export(
    rows: list[dict[str, Any]],
    columns: list[dict],
    fmt: str,
    dataset_name: str = "export",
) -> tuple[bytes, str, str]:
    """
    Dispatch to the correct formatter.

    Returns (content_bytes, media_type, suggested_filename).
    """
    fmt = fmt.lower()
    safe_name = dataset_name.lower().replace(" ", "_")[:60]
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    if fmt == "json":
        return (
            export_json(rows, columns),
            "application/json",
            f"{safe_name}_{ts}.json",
        )
    if fmt in ("xlsx", "excel"):
        content = export_excel(rows, columns, sheet_name=dataset_name[:31])
        ext = "csv" if not _OPENPYXL_AVAILABLE else "xlsx"
        media = (
            "text/csv"
            if not _OPENPYXL_AVAILABLE
            else ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        )
        return content, media, f"{safe_name}_{ts}.{ext}"

    # Default: CSV
    return export_csv(rows, columns), "text/csv", f"{safe_name}_{ts}.csv"


# ---------------------------------------------------------------------------
# Tableau WDC helpers
# ---------------------------------------------------------------------------


def build_tableau_wdc_schema(dataset: dict[str, Any]) -> dict[str, Any]:
    """
    Return the JSON schema object that Tableau WDC connector expects in its
    getSchema() callback.

    Tableau type mapping: string→STRING, integer→INT, decimal→FLOAT,
    date→DATE, datetime→DATETIME, boolean→BOOL.
    """
    type_map = {
        "string": "STRING",
        "integer": "INT",
        "decimal": "FLOAT",
        "date": "DATE",
        "datetime": "DATETIME",
        "boolean": "BOOL",
    }
    _, columns = _resolve_query(dataset)
    cols = [
        {
            "id": col["name"],
            "alias": col.get("description", col["name"]),
            "dataType": type_map.get(col.get("type", "string"), "STRING"),
        }
        for col in columns
    ]
    return {
        "id": f"raf_ds_{dataset.get('id', 0)}",
        "alias": dataset.get("name", "RAF Dataset"),
        "columns": cols,
    }


def build_tableau_wdc_html(api_base_url: str) -> str:
    """
    Generate the minimal HTML/JS page for a Tableau Web Data Connector.

    The WDC fetches schema from /api/bi/datasets/{id}/schema and data from
    /api/bi/datasets/{id}/download?format=json.
    """
    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <title>RAF Intelligence – Tableau WDC</title>
  <script src="https://connectors.tableau.com/libs/tableauwdc-2.3.latest.js" type="text/javascript"></script>
  <script type="text/javascript">
    (function() {{
      var myConnector = tableau.makeConnector();
      myConnector.getSchema = function(schemaCallback) {{
        var dsId = tableau.connectionData ? JSON.parse(tableau.connectionData).dataset_id : null;
        if (!dsId) {{ alert("No dataset_id configured"); return; }}
        var token = tableau.password;
        fetch("{api_base_url}/api/bi/datasets/" + dsId + "/schema", {{
          headers: {{"Authorization": "Bearer " + token}}
        }}).then(r => r.json()).then(function(schema) {{
          schemaCallback([schema]);
        }});
      }};
      myConnector.getData = function(table, doneCallback) {{
        var dsId = JSON.parse(tableau.connectionData).dataset_id;
        var token = tableau.password;
        fetch("{api_base_url}/api/bi/datasets/" + dsId + "/download?format=json", {{
          headers: {{"Authorization": "Bearer " + token}}
        }}).then(r => r.json()).then(function(payload) {{
          table.appendRows(payload.rows);
          doneCallback();
        }});
      }};
      tableau.registerConnector(myConnector);
      document.getElementById("connectBtn").addEventListener("click", function() {{
        var dsId = document.getElementById("datasetId").value;
        var token = document.getElementById("apiToken").value;
        if (!dsId || !token) {{ alert("Dataset ID and API Token are required"); return; }}
        tableau.connectionName = "RAF Intelligence";
        tableau.password = token;
        tableau.connectionData = JSON.stringify({{dataset_id: dsId}});
        tableau.submit();
      }});
    }})();
  </script>
</head>
<body>
  <h2>RAF Intelligence – Tableau Web Data Connector</h2>
  <label>Dataset ID: <input id="datasetId" type="text" placeholder="1" /></label><br/>
  <label>API Token: <input id="apiToken" type="password" placeholder="Bearer token" /></label><br/>
  <button id="connectBtn">Connect</button>
</body>
</html>"""


# ---------------------------------------------------------------------------
# OData v4 feed (PowerBI "Get Data → OData")
# ---------------------------------------------------------------------------

_ODATA_TYPE_MAP = {
    "string": "Edm.String",
    "integer": "Edm.Int32",
    "decimal": "Edm.Decimal",
    "date": "Edm.Date",
    "datetime": "Edm.DateTimeOffset",
    "boolean": "Edm.Boolean",
}


def build_odata_metadata(dataset_name: str, columns: list[dict]) -> str:
    """Return an OData $metadata CSDL XML document."""
    props = "\n".join(
        f'          <Property Name="{c["name"]}" Type="{_ODATA_TYPE_MAP.get(c.get("type", "string"), "Edm.String")}" />'
        for c in columns
    )
    entity_type = dataset_name.replace(" ", "_").replace("-", "_")
    return f"""<?xml version="1.0" encoding="utf-8"?>
<edmx:Edmx Version="4.0" xmlns:edmx="http://docs.oasis-open.org/odata/ns/edmx">
  <edmx:DataServices>
    <Schema Namespace="RAFIntelligence" xmlns="http://docs.oasis-open.org/odata/ns/edm">
      <EntityType Name="{entity_type}">
        <Key><PropertyRef Name="id" /></Key>
{props}
      </EntityType>
      <EntityContainer Name="DefaultContainer">
        <EntitySet Name="{entity_type}" EntityType="RAFIntelligence.{entity_type}" />
      </EntityContainer>
    </Schema>
  </edmx:DataServices>
</edmx:Edmx>"""


def build_odata_response(
    rows: list[dict[str, Any]], dataset_name: str, odata_base: str
) -> dict:
    """Wrap rows in an OData v4 JSON response envelope."""
    return {
        "@odata.context": f"{odata_base}/$metadata#{dataset_name.replace(' ', '_')}",
        "@odata.count": len(rows),
        "value": rows,
    }


# ---------------------------------------------------------------------------
# PowerBI REST API push
# ---------------------------------------------------------------------------


def push_to_powerbi(
    connection: dict[str, Any],
    api_key: str,
    dataset_name: str,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Push rows to a PowerBI streaming or push dataset via the REST API.

    Expected connection_config keys:
        push_url  – full REST API URL (e.g. https://api.powerbi.com/…/rows)

    Returns a result dict with success/error keys.
    """
    if not _REQUESTS_AVAILABLE:
        return {"success": False, "error": "requests library not installed"}

    cfg = connection.get("connection_config") or {}
    if isinstance(cfg, str):
        try:
            cfg = json.loads(cfg)
        except json.JSONDecodeError:
            cfg = {}

    push_url = cfg.get("push_url")
    if not push_url:
        return {
            "success": False,
            "error": "push_url not configured in connection_config",
        }

    payload = {"rows": rows}
    try:
        resp = _requests.post(
            push_url,
            json=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=30,
        )
        resp.raise_for_status()
        return {
            "success": True,
            "status_code": resp.status_code,
            "rows_pushed": len(rows),
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Dataset refresh
# ---------------------------------------------------------------------------


def refresh_dataset(dataset_id: int, tenant_id: str) -> dict[str, Any]:
    """
    Re-execute the dataset query and update metadata.

    This function is designed to be called from a Celery task or directly
    from the router.  Returns a result dict.
    """
    dataset = get_dataset(dataset_id, tenant_id)
    if not dataset:
        return {"success": False, "error": "Dataset not found"}

    # Mark as refreshing
    with raf_cursor() as cur:
        cur.execute(
            "UPDATE bi_datasets SET status = 'refreshing' WHERE id = %s AND tenant_id = %s",
            (dataset_id, tenant_id),
        )

    t0 = time.perf_counter()
    try:
        rows, _ = fetch_dataset_rows(dataset, tenant_id)
        elapsed_ms = int((time.perf_counter() - t0) * 1000)

        with raf_cursor() as cur:
            cur.execute(
                """
                UPDATE bi_datasets
                SET status = 'ready',
                    row_count = %s,
                    last_refreshed_at = %s,
                    error_message = NULL
                WHERE id = %s AND tenant_id = %s
                """,
                (len(rows), datetime.now(timezone.utc), dataset_id, tenant_id),
            )

        return {
            "success": True,
            "row_count": len(rows),
            "duration_ms": elapsed_ms,
        }
    except Exception as exc:
        logger.error(
            "Dataset refresh failed (id=%s): %s", dataset_id, exc, exc_info=True
        )
        with raf_cursor() as cur:
            cur.execute(
                "UPDATE bi_datasets SET status = 'error', error_message = %s WHERE id = %s AND tenant_id = %s",
                (str(exc)[:500], dataset_id, tenant_id),
            )
        return {"success": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Export log helpers
# ---------------------------------------------------------------------------


def log_export(
    export_type: str,
    status: str,
    tenant_id: str,
    dataset_id: int | None = None,
    connection_id: int | None = None,
    row_count: int | None = None,
    file_size: int | None = None,
    duration_ms: int | None = None,
    error_message: str | None = None,
    exported_by: int | None = None,
) -> None:
    """Insert one row into bi_export_log. Best-effort — never raises."""
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                INSERT INTO bi_export_log
                  (dataset_id, connection_id, export_type, row_count, file_size,
                   duration_ms, status, error_message, exported_by, tenant_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    dataset_id,
                    connection_id,
                    export_type,
                    row_count,
                    file_size,
                    duration_ms,
                    status,
                    error_message,
                    exported_by,
                    tenant_id,
                ),
            )
    except Exception as exc:
        logger.error("bi_export_log write failed: %s", exc)


def list_export_log(
    tenant_id: str,
    dataset_id: int | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    sql = """
        SELECT id, dataset_id, connection_id, export_type, row_count,
               file_size, duration_ms, status, error_message,
               exported_by, tenant_id, created_at
        FROM bi_export_log
        WHERE tenant_id = %s
    """
    params: list[Any] = [tenant_id]
    if dataset_id is not None:
        sql += " AND dataset_id = %s"
        params.append(dataset_id)
    sql += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
    params += [limit, offset]

    with raf_cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


# ---------------------------------------------------------------------------
# Seed pre-built datasets for a tenant (called on first access)
# ---------------------------------------------------------------------------


def seed_prebuilt_datasets(tenant_id: str) -> int:
    """
    Insert the six standard dataset definitions for *tenant_id* if they do
    not already exist.  Returns the number of rows inserted.
    """
    inserted = 0
    for dt, defn in PREBUILT_DATASETS.items():
        with raf_cursor() as cur:
            cur.execute(
                "SELECT id FROM bi_datasets WHERE dataset_type = %s AND tenant_id = %s LIMIT 1",
                (dt, tenant_id),
            )
            exists = cur.fetchone()
        if not exists:
            create_dataset(
                name=defn["name"],
                description=defn["description"],
                dataset_type=dt,
                query_template=defn["query_template"],
                columns_config=defn["columns_config"],
                refresh_frequency="daily",
                fmt="csv",
                tenant_id=tenant_id,
            )
            inserted += 1
    return inserted
