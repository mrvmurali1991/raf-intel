"""Add reviewed_by_user_id (BIGINT) to suspect/HCC/attestation tables for RBAC audit filtering.

Revision ID: 023_reviewed_by_fk
Revises: 022_meat_document_provenance
Create Date: 2026-04-22

Changes (all additive, idempotent via IF NOT EXISTS):

A.  Three new nullable integer columns so admins can filter audit by reviewer:
        raf_suspect_conditions.reviewed_by_user_id   BIGINT NULL
        raf_patient_hcc.reviewed_by_user_id          BIGINT NULL
        provider_attestations.attested_by_user_id    BIGINT NULL
    No FK constraint — avoids table-level locking on large production tables.

B.  Composite indexes for fast admin/auditor queries:
        idx_rsc_reviewer  (tenant_id, reviewed_by_user_id)
        idx_rph_reviewer  (tenant_id, reviewed_by_user_id)
        idx_pa_attester   (tenant_id, attested_by_user_id)
    All created with IF NOT EXISTS (MySQL 8.0+).

C.  Backfill from the existing free-text reviewed_by column using
    REGEXP_SUBSTR to extract the numeric user-id embedded in strings like
    "user:123 (email@domain)".  Rows already having a non-NULL
    reviewed_by_user_id are skipped.

Downgrade: drops columns and indexes (IF EXISTS guards).
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "023_reviewed_by_fk"
down_revision: Union[str, None] = "022_meat_document_provenance"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ---------------------------------------------------------------------------
# Helpers (inlined — do not import across migration files)
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


def _x(sql: str) -> None:
    op.execute(sa.text(sql))


# ---------------------------------------------------------------------------
# upgrade
# ---------------------------------------------------------------------------

def upgrade() -> None:
    # ------------------------------------------------------------------
    # A. Add reviewed_by_user_id / attested_by_user_id columns
    # ------------------------------------------------------------------
    if not _column_exists("raf_suspect_conditions", "reviewed_by_user_id"):
        _x(
            "ALTER TABLE `raf_suspect_conditions` "
            "ADD COLUMN `reviewed_by_user_id` BIGINT NULL "
            "COMMENT 'Numeric user.id of the reviewer — structured FK for audit filters'"
        )

    if not _column_exists("raf_patient_hcc", "reviewed_by_user_id"):
        _x(
            "ALTER TABLE `raf_patient_hcc` "
            "ADD COLUMN `reviewed_by_user_id` BIGINT NULL "
            "COMMENT 'Numeric user.id of the reviewer — structured FK for audit filters'"
        )

    # provider_attestations already has provider_user_id (the attestor).
    # We add attested_by_user_id as the canonical reviewer-identity column
    # to match the pattern on the other two tables.
    if not _column_exists("provider_attestations", "attested_by_user_id"):
        _x(
            "ALTER TABLE `provider_attestations` "
            "ADD COLUMN `attested_by_user_id` BIGINT NULL "
            "COMMENT 'Numeric user.id of the attestor — structured FK for audit filters'"
        )

    # ------------------------------------------------------------------
    # B. Composite indexes
    # ------------------------------------------------------------------
    if (
        not _index_exists("raf_suspect_conditions", "idx_rsc_reviewer")
        and _column_exists("raf_suspect_conditions", "reviewed_by_user_id")
    ):
        _x(
            "CREATE INDEX `idx_rsc_reviewer` "
            "ON `raf_suspect_conditions` (`tenant_id`, `reviewed_by_user_id`)"
        )

    if (
        not _index_exists("raf_patient_hcc", "idx_rph_reviewer")
        and _column_exists("raf_patient_hcc", "reviewed_by_user_id")
    ):
        _x(
            "CREATE INDEX `idx_rph_reviewer` "
            "ON `raf_patient_hcc` (`tenant_id`, `reviewed_by_user_id`)"
        )

    if (
        not _index_exists("provider_attestations", "idx_pa_attester")
        and _column_exists("provider_attestations", "attested_by_user_id")
    ):
        _x(
            "CREATE INDEX `idx_pa_attester` "
            "ON `provider_attestations` (`tenant_id`, `attested_by_user_id`)"
        )

    # ------------------------------------------------------------------
    # C. Backfill from free-text reviewed_by strings ("user:123 (...)").
    #    REGEXP_SUBSTR is MySQL 8.0+.  Guarded so a re-run skips already-
    #    populated rows and skips entirely if the column wasn't just added.
    # ------------------------------------------------------------------
    if _column_exists("raf_suspect_conditions", "reviewed_by_user_id"):
        _x(
            "UPDATE `raf_suspect_conditions` "
            "SET reviewed_by_user_id = CAST(REGEXP_SUBSTR(reviewed_by, '[0-9]+') AS UNSIGNED) "
            "WHERE reviewed_by REGEXP '^user:[0-9]+' "
            "  AND reviewed_by_user_id IS NULL"
        )

    if _column_exists("raf_patient_hcc", "reviewed_by_user_id"):
        _x(
            "UPDATE `raf_patient_hcc` "
            "SET reviewed_by_user_id = CAST(REGEXP_SUBSTR(reviewed_by, '[0-9]+') AS UNSIGNED) "
            "WHERE reviewed_by REGEXP '^user:[0-9]+' "
            "  AND reviewed_by_user_id IS NULL"
        )

    # provider_attestations uses provider_user_id for the numeric id already;
    # copy it into attested_by_user_id for rows that pre-date this migration.
    if _column_exists("provider_attestations", "attested_by_user_id"):
        _x(
            "UPDATE `provider_attestations` "
            "SET attested_by_user_id = provider_user_id "
            "WHERE provider_user_id IS NOT NULL "
            "  AND attested_by_user_id IS NULL"
        )


# ---------------------------------------------------------------------------
# downgrade
# ---------------------------------------------------------------------------

def downgrade() -> None:
    drop_idx = [
        "DROP INDEX IF EXISTS idx_rsc_reviewer ON raf_suspect_conditions",
        "DROP INDEX IF EXISTS idx_rph_reviewer ON raf_patient_hcc",
        "DROP INDEX IF EXISTS idx_pa_attester  ON provider_attestations",
    ]
    for stmt in drop_idx:
        try:
            op.execute(sa.text(stmt))
        except Exception:
            pass

    drop_cols = [
        "ALTER TABLE raf_suspect_conditions  DROP COLUMN IF EXISTS reviewed_by_user_id",
        "ALTER TABLE raf_patient_hcc         DROP COLUMN IF EXISTS reviewed_by_user_id",
        "ALTER TABLE provider_attestations   DROP COLUMN IF EXISTS attested_by_user_id",
    ]
    for stmt in drop_cols:
        op.execute(sa.text(stmt))
