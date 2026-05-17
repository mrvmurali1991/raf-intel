"""FHIR write-back reversal columns on raf_suspect_conditions.

Revision ID: 031_fhir_writeback_reversal
Revises: 77cd8ea4ca45
Create Date: 2026-05-17

Adds two nullable columns to ``raf_suspect_conditions`` so that a
reversed FHIR write-back (condition marked ``entered-in-error`` in the
EHR) can be tracked alongside the original write-back metadata:

  * ``fhir_writeback_reversed_at``     DATETIME NULL
  * ``fhir_writeback_reversal_reason`` TEXT NULL

down_revision uses the merge head ``77cd8ea4ca45_merge_028_hedis_030_radv_030_meat``
which is the current alembic HEAD that consolidates migration branches 028,
030_radv, and 030_meat_evidence_offsets.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "031_fhir_writeback_reversal"
down_revision: Union[str, None] = "77cd8ea4ca45"
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


def _x(sql: str) -> None:
    op.execute(sa.text(sql))


# ---------------------------------------------------------------------------
# upgrade
# ---------------------------------------------------------------------------


def upgrade() -> None:
    if not _table_exists("raf_suspect_conditions"):
        return

    if not _column_exists("raf_suspect_conditions", "fhir_writeback_reversed_at"):
        _x(
            "ALTER TABLE `raf_suspect_conditions` "
            "ADD COLUMN `fhir_writeback_reversed_at` DATETIME NULL "
            "COMMENT 'Timestamp when the FHIR Condition was marked entered-in-error'"
        )

    if not _column_exists("raf_suspect_conditions", "fhir_writeback_reversal_reason"):
        _x(
            "ALTER TABLE `raf_suspect_conditions` "
            "ADD COLUMN `fhir_writeback_reversal_reason` TEXT NULL "
            "COMMENT 'Clinical/admin reason provided when reversing the FHIR write-back'"
        )


# ---------------------------------------------------------------------------
# downgrade
# ---------------------------------------------------------------------------


def downgrade() -> None:
    stmts = [
        "ALTER TABLE raf_suspect_conditions DROP COLUMN IF EXISTS fhir_writeback_reversal_reason",
        "ALTER TABLE raf_suspect_conditions DROP COLUMN IF EXISTS fhir_writeback_reversed_at",
    ]
    for stmt in stmts:
        try:
            _x(stmt)
        except Exception:
            pass
