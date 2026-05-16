"""Add unique index on patients(tenant_id, emr_pid, emr_connection_id) to
prevent duplicate patients created by FHIR sync.

Revision ID: 012_fix_duplicate_patients
Revises: 011_widen_emr_pid_for_fhir_uuids
Create Date: 2026-04-15 00:00:00.000000

The ON DUPLICATE KEY UPDATE in openemr_fhir._upsert_patient() relied on a
unique constraint that didn't exist, so every sync run inserted a new row
instead of updating the existing one.  This migration:

1. Removes duplicate rows (keeps the most-recently-updated one).
2. Creates the missing unique index.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "012_fix_duplicate_patients"
down_revision: Union[str, None] = "011_widen_emr_pid_for_fhir_uuids"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    # Check if index already exists
    result = bind.execute(
        sa.text(
            "SELECT 1 FROM information_schema.statistics "
            "WHERE table_schema = DATABASE() "
            "AND table_name = 'patients' "
            "AND index_name = 'uq_patients_tenant_emrpid_conn' "
            "LIMIT 1"
        )
    )
    if result.fetchone():
        return  # already applied

    # Step 1: Delete duplicate rows, keeping the one with the highest id
    # (most recent) for each (tenant_id, emr_pid, emr_connection_id) group.
    # Only target rows where emr_pid IS NOT NULL and emr_pid != ''
    bind.execute(
        sa.text(
            """
            DELETE p1 FROM patients p1
            INNER JOIN patients p2
            ON  p1.tenant_id         = p2.tenant_id
            AND p1.emr_pid           = p2.emr_pid
            AND p1.emr_connection_id = p2.emr_connection_id
            AND p1.id < p2.id
            WHERE p1.emr_pid IS NOT NULL
              AND p1.emr_pid != ''
              AND p1.emr_connection_id IS NOT NULL
            """
        )
    )

    # Step 2: Create the unique index.
    # emr_pid can be NULL for manually-created patients, so we use a
    # conditional index approach: only rows with non-null emr_connection_id
    # are FHIR-synced.  MySQL unique indexes allow multiple NULLs, so
    # patients without emr_connection_id won't conflict.
    bind.execute(
        sa.text(
            "CREATE UNIQUE INDEX uq_patients_tenant_emrpid_conn "
            "ON patients (tenant_id, emr_pid, emr_connection_id)"
        )
    )


def downgrade() -> None:
    raise NotImplementedError(
        "DESTRUCTIVE: drops unique index that prevents duplicate patient rows "
        "from FHIR sync. Removing it will re-introduce silent duplicate inserts. "
        "Manual DBA review required. To proceed, delete this guard."
    )
    op.drop_index("uq_patients_tenant_emrpid_conn", table_name="patients")
