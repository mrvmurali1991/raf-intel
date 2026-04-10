"""Adds tenant isolation columns, FKs, age band CHECK, and missing composite indexes. NOTE: MySQL does not support row-level security policies — tenant filtering MUST be enforced at the application/ORM layer in addition to these columns.

Revision ID: 002_tenant_isolation_and_constraints
Revises: 001_initial_baseline
Create Date: 2026-04-10 00:00:00.000000

This migration is defensive: every DDL operation first inspects the live
database and skips the step if it is already applied.  That makes it safe
to run against environments that may have been partially migrated by hand
or whose baseline was created by ``app/migrations.py``.

Targets (MySQL 8):
    1. Add ``tenant_id BIGINT NOT NULL DEFAULT 1`` to:
           patients, raf_patient_hcc, raf_patient_demographics,
           documents, audit_log
    2. Composite index ``(tenant_id, patient_id)`` on each of the above
       (where a ``patient_id`` column exists).
    3. Cascade-delete FKs from patients.id to:
           raf_patient_demographics.patient_id
           raf_patient_hcc.patient_id
           documents.patient_id
    4. CHECK constraint on ``raf_patient_demographics.age_band``
       restricting it to the canonical CMS bands.
    5. Composite indexes:
           hcc_raf_coefficients (model_year, model_version, hcc_code)
           hcc_icd10_crosswalk  (effective_year, icd10_code)
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "002_tenant_isolation_and_constraints"
down_revision: Union[str, None] = "001_initial_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

TENANT_TABLES: tuple[str, ...] = (
    "patients",
    "raf_patient_hcc",
    "raf_patient_demographics",
    "documents",
    "audit_log",
)

# Tables that get a composite (tenant_id, patient_id) index.  Every table in
# TENANT_TABLES except ``patients`` itself owns a ``patient_id`` FK column.
PATIENT_SCOPED_TABLES: tuple[str, ...] = (
    "raf_patient_hcc",
    "raf_patient_demographics",
    "documents",
    "audit_log",
)

# Child tables that should cascade-delete when a patient row is removed.
PATIENT_FK_CHILDREN: tuple[tuple[str, str], ...] = (
    ("raf_patient_demographics", "fk_raf_patient_demographics_patient"),
    ("raf_patient_hcc",          "fk_raf_patient_hcc_patient"),
    ("documents",                "fk_documents_patient"),
)

AGE_BANDS: tuple[str, ...] = (
    "0-34", "35-44", "45-54", "55-59", "60-64", "65-69",
    "70-74", "75-79", "80-84", "85-89", "90-94", "95+",
)
AGE_BAND_CHECK_NAME = "ck_raf_patient_demographics_age_band"

COMPOSITE_INDEXES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "hcc_raf_coefficients",
        "idx_hcc_raf_coef_year_version_code",
        ("model_year", "model_version", "hcc_code"),
    ),
    (
        "hcc_icd10_crosswalk",
        "idx_hcc_icd10_xwalk_year_code",
        ("effective_year", "icd10_code"),
    ),
)


# ---------------------------------------------------------------------------
# Inspection helpers
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
    return any(i["name"] == index_name for i in _inspector().get_indexes(table))


def _fk_exists(table: str, fk_name: str) -> bool:
    if not _table_exists(table):
        return False
    return any(
        fk.get("name") == fk_name for fk in _inspector().get_foreign_keys(table)
    )


def _check_constraint_exists(table: str, constraint_name: str) -> bool:
    """MySQL-specific CHECK constraint probe via information_schema."""
    if not _table_exists(table):
        return False
    bind = op.get_bind()
    row = bind.execute(
        sa.text(
            """
            SELECT 1
              FROM information_schema.TABLE_CONSTRAINTS
             WHERE TABLE_SCHEMA = DATABASE()
               AND TABLE_NAME   = :t
               AND CONSTRAINT_NAME = :c
               AND CONSTRAINT_TYPE = 'CHECK'
             LIMIT 1
            """
        ),
        {"t": table, "c": constraint_name},
    ).first()
    return row is not None


# ---------------------------------------------------------------------------
# upgrade / downgrade
# ---------------------------------------------------------------------------

def upgrade() -> None:
    # -----------------------------------------------------------------------
    # 1. tenant_id columns
    # -----------------------------------------------------------------------
    for table in TENANT_TABLES:
        if not _table_exists(table):
            # Skip silently — table is not present in this deployment.
            continue
        if _column_exists(table, "tenant_id"):
            continue
        op.add_column(
            table,
            sa.Column(
                "tenant_id",
                sa.BigInteger(),
                nullable=False,
                server_default=sa.text("1"),
            ),
        )

    # -----------------------------------------------------------------------
    # 2. Composite (tenant_id, patient_id) indexes
    # -----------------------------------------------------------------------
    for table in PATIENT_SCOPED_TABLES:
        if not _table_exists(table):
            continue
        if not (_column_exists(table, "tenant_id") and _column_exists(table, "patient_id")):
            continue
        idx_name = f"idx_{table}_tenant_patient"
        if _index_exists(table, idx_name):
            continue
        op.create_index(idx_name, table, ["tenant_id", "patient_id"])

    # -----------------------------------------------------------------------
    # 3. Cascade-delete FKs from patients.id to child.patient_id
    # -----------------------------------------------------------------------
    # Only attempt this if a ``patients`` parent table with an ``id`` PK
    # actually exists.  In deployments where patient identity lives in
    # OpenEMR this block is a no-op.
    if _table_exists("patients") and _column_exists("patients", "id"):
        for child_table, fk_name in PATIENT_FK_CHILDREN:
            if not _table_exists(child_table):
                continue
            if not _column_exists(child_table, "patient_id"):
                continue
            if _fk_exists(child_table, fk_name):
                continue
            op.create_foreign_key(
                fk_name,
                child_table,
                "patients",
                ["patient_id"],
                ["id"],
                ondelete="CASCADE",
                onupdate="CASCADE",
            )

    # -----------------------------------------------------------------------
    # 4. CHECK constraint on age_band
    # -----------------------------------------------------------------------
    if (
        _table_exists("raf_patient_demographics")
        and _column_exists("raf_patient_demographics", "age_band")
        and not _check_constraint_exists(
            "raf_patient_demographics", AGE_BAND_CHECK_NAME
        )
    ):
        allowed = ", ".join(f"'{b}'" for b in AGE_BANDS)
        op.execute(
            f"ALTER TABLE raf_patient_demographics "
            f"ADD CONSTRAINT {AGE_BAND_CHECK_NAME} "
            f"CHECK (age_band IN ({allowed}))"
        )

    # -----------------------------------------------------------------------
    # 5. Missing composite indexes on reference tables
    # -----------------------------------------------------------------------
    for table, idx_name, cols in COMPOSITE_INDEXES:
        if not _table_exists(table):
            continue
        if any(not _column_exists(table, c) for c in cols):
            continue
        if _index_exists(table, idx_name):
            continue
        op.create_index(idx_name, table, list(cols))


def downgrade() -> None:
    # 5. Drop composite reference indexes
    for table, idx_name, _cols in COMPOSITE_INDEXES:
        if _index_exists(table, idx_name):
            op.drop_index(idx_name, table_name=table)

    # 4. Drop age_band CHECK
    if _check_constraint_exists("raf_patient_demographics", AGE_BAND_CHECK_NAME):
        op.execute(
            f"ALTER TABLE raf_patient_demographics "
            f"DROP CONSTRAINT {AGE_BAND_CHECK_NAME}"
        )

    # 3. Drop FKs
    if _table_exists("patients"):
        for child_table, fk_name in PATIENT_FK_CHILDREN:
            if _fk_exists(child_table, fk_name):
                op.drop_constraint(fk_name, child_table, type_="foreignkey")

    # 2. Drop composite (tenant_id, patient_id) indexes
    for table in PATIENT_SCOPED_TABLES:
        idx_name = f"idx_{table}_tenant_patient"
        if _index_exists(table, idx_name):
            op.drop_index(idx_name, table_name=table)

    # 1. Drop tenant_id columns
    for table in TENANT_TABLES:
        if _column_exists(table, "tenant_id"):
            op.drop_column(table, "tenant_id")
