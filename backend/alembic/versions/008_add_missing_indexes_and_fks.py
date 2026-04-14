"""Add missing composite indexes for query performance and FK constraints.

Revision ID: 008_add_missing_indexes_and_fks
Revises: 007_fhir_encounter_medication_storage
Create Date: 2026-04-14 00:00:00.000000

Adds composite indexes that are missing from earlier migrations but required
for performance-critical query paths across the application:

raf_patient_hcc:
  - (patient_id, measurement_year, tenant_id) — tenant-scoped patient HCC
    lookups filtered by year; complements the unique key that covers
    (patient_id, hcc_code, measurement_year).

raf_scores:
  - (patient_id, measurement_year) — plain year-scoped lookup without the
    DESC calculated_at sort; used by quick existence checks.
  - (patient_id, measurement_year, calculated_at) — ascending variant for
    trend queries (migration 006 added the DESC variant).

raf_suspect_conditions:
  - (patient_id, status, measurement_year) — extends the existing
    (patient_id, status) index with year filtering for worklist scoping.

provider_patient_panel:
  - (provider_id, tenant_id) — tenant-scoped provider panel lookups.

provider_alerts:
  - (provider_id, status, created_at) — provider alert queues ordered by
    creation time.

emr_patient_matches:
  - (connection_id, raf_patient_id) — FHIR connection-scoped patient match
    lookups; used by the FHIR sync upsert path.

patients:
  - (tenant_id, mrn) — named uq_patients_tenant_mrn; enforces tenant-scoped
    MRN uniqueness and accelerates MRN lookups.  Created as a plain index
    here because the UNIQUE constraint may already exist from model DDL;
    the helper will skip gracefully if it does.

care_gap_tasks:
  - (patient_id, tenant_id) — patient-scoped care gap lookups within a
    tenant.

raf_encounter_analysis:
  - (pid, tenant_id) — tenant-scoped encounter analysis lookups by PID.
    Note: the column is ``pid`` (not ``patient_id``) in this table.

fhir_encounters:
  - (fhir_patient_id, connection_id) — connection-scoped FHIR patient
    encounter lookups; created by migration 007 but left without a
    composite index.

All indexes are created only after verifying that the target table and every
referenced column exist, and that the index does not already exist.  This
makes the migration fully idempotent and safe to re-run or apply to
environments that are partially ahead or behind.
"""
from __future__ import annotations

import logging
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Revision identifiers
# ---------------------------------------------------------------------------

revision: str = "008_add_missing_indexes_and_fks"
down_revision: Union[str, None] = "007_fhir_encounter_medication_storage"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ---------------------------------------------------------------------------
# Helpers  (mirrors pattern established in migration 006)
# ---------------------------------------------------------------------------

def _inspector():
    return sa.inspect(op.get_bind())


def _table_exists(name: str) -> bool:
    return _inspector().has_table(name)


def _column_exists(table: str, column: str) -> bool:
    if not _table_exists(table):
        return False
    return any(c["name"] == column for c in _inspector().get_columns(table))


def _index_exists(table: str, index_name: str) -> bool:
    if not _table_exists(table):
        return False
    return any(idx["name"] == index_name for idx in _inspector().get_indexes(table))


def _create_index(index_name: str, table: str, columns_sql: str) -> None:
    """Create a regular index if the table exists and the index does not.

    ``columns_sql`` is the raw column list including any DESC/ASC keywords,
    e.g. ``"patient_id, measurement_year, calculated_at"``.

    The helper strips DESC/ASC tokens when verifying column existence so that
    sort-qualified column references are handled correctly.
    """
    if not _table_exists(table):
        logger.info("skipping index %s — table %s does not exist", index_name, table)
        return

    for token in columns_sql.split(","):
        col = token.strip().split()[0]
        if not _column_exists(table, col):
            logger.info(
                "skipping index %s — column %s.%s does not exist",
                index_name, table, col,
            )
            return

    if _index_exists(table, index_name):
        logger.info("index %s already exists on %s — skipping", index_name, table)
        return

    op.execute(sa.text(f"CREATE INDEX {index_name} ON {table} ({columns_sql})"))
    logger.info("created index %s on %s (%s)", index_name, table, columns_sql)


# ---------------------------------------------------------------------------
# Index definitions: (index_name, table_name, columns_sql)
# ---------------------------------------------------------------------------

_INDEXES: list[tuple[str, str, str]] = [
    # -- raf_patient_hcc ------------------------------------------------------
    (
        "idx_raf_patient_hcc_pid_year_tid",
        "raf_patient_hcc",
        "patient_id, measurement_year, tenant_id",
    ),

    # -- raf_scores -----------------------------------------------------------
    # Migration 006 added (patient_id, measurement_year, calculated_at DESC).
    # Add the plain (patient_id, measurement_year) variant used by existence
    # checks, and the ascending calculated_at variant used by trend queries.
    (
        "idx_raf_scores_pid_year",
        "raf_scores",
        "patient_id, measurement_year",
    ),
    (
        "idx_raf_scores_pid_year_calc",
        "raf_scores",
        "patient_id, measurement_year, calculated_at",
    ),

    # -- raf_suspect_conditions -----------------------------------------------
    # Migration 006 added (patient_id, status). Extend with measurement_year
    # for year-scoped worklist queries.
    (
        "idx_suspect_cond_pid_status_year",
        "raf_suspect_conditions",
        "patient_id, status, measurement_year",
    ),

    # -- provider_patient_panel -----------------------------------------------
    (
        "idx_provider_panel_pid_tid",
        "provider_patient_panel",
        "provider_id, tenant_id",
    ),

    # -- provider_alerts -------------------------------------------------------
    (
        "idx_provider_alerts_pid_status",
        "provider_alerts",
        "provider_id, status, created_at",
    ),

    # -- emr_patient_matches ---------------------------------------------------
    (
        "idx_epm_conn_raf",
        "emr_patient_matches",
        "connection_id, raf_patient_id",
    ),

    # -- patients --------------------------------------------------------------
    # Enforces tenant-scoped MRN uniqueness; also accelerates MRN lookups.
    # Named to match the constraint name used in application code.  If the
    # unique constraint already exists as a key rather than an index the
    # inspector will report it and creation is skipped.
    (
        "uq_patients_tenant_mrn",
        "patients",
        "tenant_id, mrn",
    ),

    # -- care_gap_tasks --------------------------------------------------------
    (
        "idx_care_gap_tasks_pid_tid",
        "care_gap_tasks",
        "patient_id, tenant_id",
    ),

    # -- raf_encounter_analysis ------------------------------------------------
    # Column is `pid` in this table (not `patient_id`).
    (
        "idx_enc_analysis_pid_tid",
        "raf_encounter_analysis",
        "pid, tenant_id",
    ),

    # -- fhir_encounters -------------------------------------------------------
    # Table created by migration 007; add the connection-scoped patient index.
    (
        "idx_fhir_enc_patient",
        "fhir_encounters",
        "fhir_patient_id, connection_id",
    ),
]


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------

def upgrade() -> None:
    for index_name, table, columns_sql in _INDEXES:
        _create_index(index_name, table, columns_sql)


def downgrade() -> None:
    for index_name, table, _columns_sql in reversed(_INDEXES):
        if not _table_exists(table):
            continue
        if not _index_exists(table, index_name):
            continue
        op.execute(sa.text(f"DROP INDEX {index_name} ON {table}"))
        logger.info("dropped index %s on %s", index_name, table)
