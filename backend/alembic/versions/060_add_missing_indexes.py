"""Add critical missing indexes for performance-sensitive query paths.

Revision ID: 060_add_missing_indexes
Revises: 059_previsit_briefing_reviews
Create Date: 2026-05-26

Adds indexes that are absent from earlier migrations but required for
common tenant-scoped, status-filtered, and patient-lookup query patterns:

normalized_diagnoses:
  - (patient_id)  — patient-scoped diagnosis lookups used by RAF pipeline
    and clinical note processors.
  - (encounter_id) — encounter-scoped diagnosis lookups for FHIR encounter
    assembly and charge-capture reconciliation.

audit_log:
  - (user_id, created_at) — user activity timeline queries; the existing
    primary-key index on id is insufficient for per-user history pages.

raf_scores:
  - (tenant_id, measurement_year) — tenant dashboard year-filter queries.
    Migration 006 may have added this; the helper skips gracefully if so.

raf_patient_hcc:
  - (tenant_id, measurement_year) — tenant-scoped HCC year summaries used
    by the RAF summary and dashboard endpoints.

raf_patient_demographics:
  - (tenant_id, measurement_year) — tenant-scoped demographics queries for
    risk stratification and population reports.

raf_suspect_conditions:
  - (tenant_id, status) — tenant worklist filtered by status (open /
    accepted / dismissed / coded).  Complements the (patient_id, status)
    index added in migration 006 with a tenant-first prefix for the admin
    and coder worklist views.

patients (FULLTEXT):
  - FULLTEXT(first_name, last_name, mrn) — fast patient search used by the
    patient-lookup typeahead and admin search bar.  MySQL FULLTEXT requires
    InnoDB (which all RAF tables use) and is created with a separate ALTER
    TABLE statement; the guard queries INFORMATION_SCHEMA directly because
    SQLAlchemy's inspector does not enumerate FULLTEXT indexes.

All regular indexes use _create_index(), which verifies table existence,
column existence, and index non-existence before executing DDL.  The
FULLTEXT index uses a dedicated _has_fulltext_index() guard for the same
idempotency guarantee.
"""
from __future__ import annotations

import logging
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Revision identifiers
# ---------------------------------------------------------------------------

revision: str = "060_add_missing_indexes"
down_revision: Union[str, Sequence[str], None] = "059_previsit_briefing_reviews"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# ---------------------------------------------------------------------------
# Helpers  (mirrors pattern established in migrations 006 and 008)
# ---------------------------------------------------------------------------

_FT_INDEX_NAME = "ft_patient_search"
_FT_COLUMNS = "first_name, last_name, mrn"


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


def _has_fulltext_index(table: str, index_name: str) -> bool:
    """Return True when a FULLTEXT index with the given name exists on table.

    SQLAlchemy's inspector omits FULLTEXT entries from get_indexes(), so we
    query INFORMATION_SCHEMA directly.
    """
    if not _table_exists(table):
        return False
    bind = op.get_bind()
    result = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM INFORMATION_SCHEMA.STATISTICS "
            "WHERE TABLE_SCHEMA = DATABASE() "
            "  AND TABLE_NAME   = :tbl "
            "  AND INDEX_NAME   = :idx "
            "  AND INDEX_TYPE   = 'FULLTEXT'"
        ),
        {"tbl": table, "idx": index_name},
    )
    return (result.scalar() or 0) > 0


def _create_index(index_name: str, table: str, columns_sql: str) -> None:
    """Create a regular index if the table exists and the index does not.

    ``columns_sql`` is the raw column list including any DESC/ASC keywords,
    e.g. ``"tenant_id, measurement_year"``.  DESC/ASC tokens are stripped
    when verifying column existence.
    """
    if not _table_exists(table):
        logger.info("skipping index %s — table %s does not exist", index_name, table)
        return

    for token in columns_sql.split(","):
        col = token.strip().split()[0]
        if not _column_exists(table, col):
            logger.info(
                "skipping index %s — column %s.%s does not exist",
                index_name,
                table,
                col,
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
    # -- normalized_diagnoses --------------------------------------------------
    # Used by RAF pipeline to fetch all diagnoses for a patient / encounter.
    (
        "idx_nd_patient",
        "normalized_diagnoses",
        "patient_id",
    ),
    (
        "idx_nd_encounter",
        "normalized_diagnoses",
        "encounter_id",
    ),

    # -- audit_log -------------------------------------------------------------
    # Composite (user_id, created_at) supports per-user activity history pages
    # and compliance export queries that filter by user then sort by time.
    (
        "idx_audit_log_user_created",
        "audit_log",
        "user_id, created_at",
    ),

    # -- raf_scores ------------------------------------------------------------
    # Tenant-year composite for dashboard and report queries.
    # Migration 006 may already have this; _create_index() skips if present.
    (
        "idx_rs_tenant_year",
        "raf_scores",
        "tenant_id, measurement_year",
    ),

    # -- raf_patient_hcc -------------------------------------------------------
    # Tenant-year composite for HCC summary and gap analysis endpoints.
    (
        "idx_rph_tenant_year",
        "raf_patient_hcc",
        "tenant_id, measurement_year",
    ),

    # -- raf_patient_demographics ----------------------------------------------
    # Tenant-year composite for population risk stratification reports.
    (
        "idx_rpd_tenant_year",
        "raf_patient_demographics",
        "tenant_id, measurement_year",
    ),

    # -- raf_suspect_conditions ------------------------------------------------
    # Tenant-status composite for admin and coder worklist views.
    # Complements (patient_id, status) from migration 006 and
    # (patient_id, status, measurement_year) from migration 008.
    (
        "idx_rsc_tenant_status",
        "raf_suspect_conditions",
        "tenant_id, status",
    ),
]


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------

def upgrade() -> None:
    for index_name, table, columns_sql in _INDEXES:
        _create_index(index_name, table, columns_sql)

    # FULLTEXT index on patients(first_name, last_name, mrn).
    # Uses a dedicated guard because SQLAlchemy inspector does not enumerate
    # FULLTEXT indexes.
    if not _table_exists("patients"):
        logger.info("skipping %s — table patients does not exist", _FT_INDEX_NAME)
    elif _has_fulltext_index("patients", _FT_INDEX_NAME):
        logger.info("FULLTEXT index %s already exists on patients — skipping", _FT_INDEX_NAME)
    else:
        # Verify all three columns exist before attempting the ALTER.
        all_cols_present = all(
            _column_exists("patients", col.strip())
            for col in _FT_COLUMNS.split(",")
        )
        if not all_cols_present:
            logger.info(
                "skipping FULLTEXT index %s — one or more columns (%s) missing on patients",
                _FT_INDEX_NAME,
                _FT_COLUMNS,
            )
        else:
            op.execute(
                sa.text(
                    f"ALTER TABLE patients "
                    f"ADD FULLTEXT INDEX {_FT_INDEX_NAME} ({_FT_COLUMNS})"
                )
            )
            logger.info("created FULLTEXT index %s on patients (%s)", _FT_INDEX_NAME, _FT_COLUMNS)


def downgrade() -> None:
    # Drop FULLTEXT index first (reverse of upgrade order).
    if _table_exists("patients") and _has_fulltext_index("patients", _FT_INDEX_NAME):
        op.execute(sa.text(f"ALTER TABLE patients DROP INDEX {_FT_INDEX_NAME}"))
        logger.info("dropped FULLTEXT index %s on patients", _FT_INDEX_NAME)

    for index_name, table, _columns_sql in reversed(_INDEXES):
        if not _table_exists(table):
            continue
        if not _index_exists(table, index_name):
            continue
        op.execute(sa.text(f"DROP INDEX {index_name} ON {table}"))
        logger.info("dropped index %s on %s", index_name, table)
