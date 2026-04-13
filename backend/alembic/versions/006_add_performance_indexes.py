"""Add composite performance indexes for common query patterns.

Revision ID: 006_add_performance_indexes
Revises: 005_pipeline_settings_table
Create Date: 2026-04-13 00:00:00.000000

Adds composite indexes targeting the most common query patterns identified
across the application.  Each index is checked before creation so this
migration is fully idempotent and safe to run multiple times.

Index rationale
---------------
raf_scores:
  - (patient_id, measurement_year, calculated_at DESC) — patient RAF history
    queries that ORDER BY calculated_at DESC; covers the common lookup of
    "latest RAF score for patient X in year Y".
  - (tenant_id, measurement_year) — tenant-scoped dashboards filtering by year.
    Note: tenant_id was added by migration 002; if it does not exist the index
    is silently skipped.

raf_patient_hcc:
  - (patient_id, measurement_year, hcc_code) — already covered by the UNIQUE
    KEY uq_patient_hcc_year; no additional index needed.
  - (tenant_id, patient_id) — tenant-scoped patient HCC lookups.  Mirrors the
    pattern from migration 002 but for raf_patient_hcc (which 002 already
    handles).  Skipped if it already exists.

raf_encounter_analysis:
  - (patient_id, analyzed_at DESC) — patient encounter timeline queries.
  - (encounter_id) — already has idx via UNIQUE KEY; no action needed.

normalized_encounters:
  - (tenant_id, patient_id, encounter_date) — tenant-scoped patient encounter
    lookups with date range filtering.

raf_suspect_conditions:
  - (patient_id, status) — patient-scoped suspect condition filtering by
    status (open/accepted/dismissed/coded).
  - (status, confidence_score DESC) — worklist queries: "all open suspects
    ordered by confidence".

care_gap_tasks:
  - (tenant_id, status, priority) — already exists as
    idx_care_gap_tenant_status from migrations.py composite indexes.
  - (patient_id, status) — already exists as idx_care_gap_patient_status.
  - (tenant_id, status, due_date) — tenant worklist sorted by due date.

patients:
  - (tenant_id, is_active) — active patient lists per tenant.

provider_scorecard_snapshots:
  - (provider_id, measurement_year, calculated_at DESC) — latest scorecard
    per provider per year.

provider_attestations:
  - (patient_id, status, created_at DESC) — patient attestation history.
  - (tenant_id, status, created_at DESC) — tenant attestation worklist.

coder_worklist:
  - (tenant_id, status, priority, created_at) — coder queue ordering.
"""
from __future__ import annotations

import logging
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
revision: str = "006_add_performance_indexes"
down_revision: Union[str, None] = "005_pipeline_settings_table"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ---------------------------------------------------------------------------
# Helpers
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
    """Create an index if the table exists and the index does not.

    ``columns_sql`` is the raw column list including any DESC keywords,
    e.g. ``"patient_id, measurement_year, calculated_at DESC"``.
    """
    if not _table_exists(table):
        logger.info("skipping index %s — table %s does not exist", index_name, table)
        return

    # Verify all referenced columns exist (strip DESC/ASC keywords)
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

    ddl = f"CREATE INDEX {index_name} ON {table} ({columns_sql})"
    op.execute(sa.text(ddl))
    logger.info("created index %s on %s", index_name, table)


# ---------------------------------------------------------------------------
# Index definitions: (index_name, table_name, columns_sql)
# ---------------------------------------------------------------------------

_INDEXES: list[tuple[str, str, str]] = [
    # -- raf_scores ----------------------------------------------------------
    (
        "idx_raf_scores_pid_year_calcdt",
        "raf_scores",
        "patient_id, measurement_year, calculated_at DESC",
    ),
    (
        "idx_raf_scores_tenant_year",
        "raf_scores",
        "tenant_id, measurement_year",
    ),

    # -- raf_patient_hcc -----------------------------------------------------
    # uq_patient_hcc_year already covers (patient_id, hcc_code, measurement_year)
    # Add tenant-scoped lookup only if tenant_id column is present.
    (
        "idx_raf_phcc_tenant_pid",
        "raf_patient_hcc",
        "tenant_id, patient_id",
    ),

    # -- raf_encounter_analysis ----------------------------------------------
    (
        "idx_raf_ea_pid_analyzed",
        "raf_encounter_analysis",
        "patient_id, analyzed_at DESC",
    ),

    # -- normalized_encounters -----------------------------------------------
    (
        "idx_ne_tenant_pid_date",
        "normalized_encounters",
        "tenant_id, patient_id, encounter_date",
    ),

    # -- raf_suspect_conditions ----------------------------------------------
    (
        "idx_rsc_pid_status",
        "raf_suspect_conditions",
        "patient_id, status",
    ),
    (
        "idx_rsc_status_confidence",
        "raf_suspect_conditions",
        "status, confidence_score DESC",
    ),

    # -- care_gap_tasks ------------------------------------------------------
    # idx_care_gap_tenant_status (tenant_id, status, priority) already exists.
    # idx_care_gap_patient_status (patient_id, status) already exists.
    # Add due-date ordering for tenant worklist if due_date column exists.
    (
        "idx_cgt_tenant_status_due",
        "care_gap_tasks",
        "tenant_id, status, due_date",
    ),

    # -- patients ------------------------------------------------------------
    (
        "idx_patients_tenant_active",
        "patients",
        "tenant_id, is_active",
    ),

    # -- provider_scorecard_snapshots ----------------------------------------
    (
        "idx_pss_provider_year_calc",
        "provider_scorecard_snapshots",
        "provider_id, measurement_year, calculated_at DESC",
    ),

    # -- provider_attestations -----------------------------------------------
    (
        "idx_pa_pid_status_created",
        "provider_attestations",
        "patient_id, status, created_at DESC",
    ),
    (
        "idx_pa_tenant_status_created",
        "provider_attestations",
        "tenant_id, status, created_at DESC",
    ),

    # -- coder_worklist ------------------------------------------------------
    (
        "idx_cw_tenant_status_pri_created",
        "coder_worklist",
        "tenant_id, status, priority, created_at",
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
