"""Add V24/V28 per-model score columns and blend metadata to raf_scores.

Revision ID: 003_raf_scores_blend_columns
Revises: 002_tenant_isolation_and_constraints
Create Date: 2026-04-13 00:00:00.000000

CMS is transitioning from HCC Model V24 to V28 on a phased blend schedule:
  PY2024: 67% V24 + 33% V28
  PY2025: 33% V24 + 67% V28
  PY2026+: 100% V28

To support auditing and analytics on the blend, each raf_scores row now
stores the raw score produced by each model independently, the blend weights
applied, and the blended raw score before payment adjustments.

New columns on raf_scores:
  v24_score         DECIMAL(8,4)  — raw CMS-HCC V24 risk score (NULL when V24 not run)
  v28_score         DECIMAL(8,4)  — raw CMS-HCC V28 risk score (NULL when V28 not run)
  blended_raw_score DECIMAL(8,4)  — weighted blend: (v24_w * v24_score) + (v28_w * v28_score)
  blend_v24_weight  DECIMAL(5,4)  — V24 blend weight for this payment year (e.g. 0.3300)
  blend_v28_weight  DECIMAL(5,4)  — V28 blend weight for this payment year (e.g. 0.6700)
  v24_hcc_count     SMALLINT      — number of HCCs flagged under V24 (NULL when not run)
  v28_hcc_count     SMALLINT      — number of HCCs flagged under V28 (NULL when not run)

All new columns are nullable so that existing rows remain valid and rows
calculated under pure V24 or pure V28 do not need placeholder values.

This migration is fully defensive: each ALTER is skipped if the column
already exists, so it is safe to run more than once.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "003_raf_scores_blend_columns"
down_revision: Union[str, None] = "002_tenant_isolation_and_constraints"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


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


# ---------------------------------------------------------------------------
# New columns to add: (column_name, ddl_type, after_column)
#
# ``after_column`` is a MySQL-specific positional hint so the columns land in
# a logical group next to the existing score columns rather than at the end of
# the table.  On non-MySQL dialects the AFTER clause is omitted gracefully.
# ---------------------------------------------------------------------------

_NEW_COLUMNS: tuple[tuple[str, str, str], ...] = (
    # (column_name, column_type, after_column)
    ("v24_score",          "DECIMAL(8,4)  DEFAULT NULL", "final_raf"),
    ("v28_score",          "DECIMAL(8,4)  DEFAULT NULL", "v24_score"),
    ("blended_raw_score",  "DECIMAL(8,4)  DEFAULT NULL", "v28_score"),
    ("blend_v24_weight",   "DECIMAL(5,4)  DEFAULT NULL", "blended_raw_score"),
    ("blend_v28_weight",   "DECIMAL(5,4)  DEFAULT NULL", "blend_v24_weight"),
    ("v24_hcc_count",      "SMALLINT      DEFAULT NULL", "blend_v28_weight"),
    ("v28_hcc_count",      "SMALLINT      DEFAULT NULL", "v24_hcc_count"),
)


def upgrade() -> None:
    if not _table_exists("raf_scores"):
        # Table hasn't been created yet — nothing to alter.
        return

    bind = op.get_bind()
    dialect = bind.dialect.name  # "mysql" | "sqlite" | "postgresql" …

    for col_name, col_ddl, after_col in _NEW_COLUMNS:
        if _column_exists("raf_scores", col_name):
            continue  # already applied — skip

        if dialect == "mysql":
            after_clause = f" AFTER {after_col}"
        else:
            after_clause = ""

        op.execute(
            sa.text(
                f"ALTER TABLE raf_scores ADD COLUMN {col_name} {col_ddl}{after_clause}"
            )
        )


def downgrade() -> None:
    """Drop the blend columns — reversible for development environments."""
    if not _table_exists("raf_scores"):
        return

    for col_name, _col_ddl, _after_col in _NEW_COLUMNS:
        if not _column_exists("raf_scores", col_name):
            continue

        op.execute(
            sa.text(f"ALTER TABLE raf_scores DROP COLUMN {col_name}")
        )
