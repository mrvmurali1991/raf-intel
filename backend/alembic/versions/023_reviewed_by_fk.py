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

revision: str = "023_reviewed_by_fk"
down_revision: Union[str, None] = "022_meat_document_provenance"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ADD_COLUMNS: list[str] = [
    # raf_suspect_conditions
    (
        "ALTER TABLE raf_suspect_conditions "
        "ADD COLUMN IF NOT EXISTS reviewed_by_user_id BIGINT NULL "
        "COMMENT 'Numeric user.id of the reviewer — structured FK for audit filters'"
    ),
    # raf_patient_hcc
    (
        "ALTER TABLE raf_patient_hcc "
        "ADD COLUMN IF NOT EXISTS reviewed_by_user_id BIGINT NULL "
        "COMMENT 'Numeric user.id of the reviewer — structured FK for audit filters'"
    ),
    # provider_attestations already has provider_user_id (the attestor).
    # We add attested_by_user_id as the canonical reviewer-identity column
    # to match the pattern on the other two tables.
    (
        "ALTER TABLE provider_attestations "
        "ADD COLUMN IF NOT EXISTS attested_by_user_id BIGINT NULL "
        "COMMENT 'Numeric user.id of the attestor — structured FK for audit filters'"
    ),
]

_ADD_INDEXES: list[str] = [
    "CREATE INDEX IF NOT EXISTS idx_rsc_reviewer ON raf_suspect_conditions (tenant_id, reviewed_by_user_id)",
    "CREATE INDEX IF NOT EXISTS idx_rph_reviewer ON raf_patient_hcc (tenant_id, reviewed_by_user_id)",
    "CREATE INDEX IF NOT EXISTS idx_pa_attester  ON provider_attestations (tenant_id, attested_by_user_id)",
]

# Backfill: parse "user:123 (...)" strings that have not yet been migrated.
# REGEXP_SUBSTR is MySQL 8.0+.  The WHERE guard makes the statement safe to
# replay: already-populated rows are untouched.
_BACKFILL: list[str] = [
    (
        "UPDATE raf_suspect_conditions "
        "SET reviewed_by_user_id = CAST(REGEXP_SUBSTR(reviewed_by, '[0-9]+') AS UNSIGNED) "
        "WHERE reviewed_by REGEXP '^user:[0-9]+' "
        "  AND reviewed_by_user_id IS NULL"
    ),
    (
        "UPDATE raf_patient_hcc "
        "SET reviewed_by_user_id = CAST(REGEXP_SUBSTR(reviewed_by, '[0-9]+') AS UNSIGNED) "
        "WHERE reviewed_by REGEXP '^user:[0-9]+' "
        "  AND reviewed_by_user_id IS NULL"
    ),
    # provider_attestations uses provider_user_id for the numeric id already;
    # copy it into attested_by_user_id for rows that pre-date this migration.
    (
        "UPDATE provider_attestations "
        "SET attested_by_user_id = provider_user_id "
        "WHERE provider_user_id IS NOT NULL "
        "  AND attested_by_user_id IS NULL"
    ),
]

_DROP_INDEXES: list[str] = [
    "DROP INDEX IF EXISTS idx_rsc_reviewer ON raf_suspect_conditions",
    "DROP INDEX IF EXISTS idx_rph_reviewer ON raf_patient_hcc",
    "DROP INDEX IF EXISTS idx_pa_attester  ON provider_attestations",
]

_DROP_COLUMNS: list[str] = [
    "ALTER TABLE raf_suspect_conditions  DROP COLUMN IF EXISTS reviewed_by_user_id",
    "ALTER TABLE raf_patient_hcc         DROP COLUMN IF EXISTS reviewed_by_user_id",
    "ALTER TABLE provider_attestations   DROP COLUMN IF EXISTS attested_by_user_id",
]


# ---------------------------------------------------------------------------
# Upgrade
# ---------------------------------------------------------------------------

def upgrade() -> None:
    for stmt in _ADD_COLUMNS:
        op.execute(stmt)

    for stmt in _ADD_INDEXES:
        try:
            op.execute(stmt)
        except Exception:
            # Silently swallow duplicate-index errors on MySQL < 8.0
            pass

    for stmt in _BACKFILL:
        op.execute(stmt)


# ---------------------------------------------------------------------------
# Downgrade
# ---------------------------------------------------------------------------

def downgrade() -> None:
    for stmt in _DROP_INDEXES:
        try:
            op.execute(stmt)
        except Exception:
            pass

    for stmt in _DROP_COLUMNS:
        op.execute(stmt)
