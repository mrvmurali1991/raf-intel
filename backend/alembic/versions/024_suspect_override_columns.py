"""Add accept_override_reason, accept_defense_basis, accept_risk_factors_json to raf_suspect_conditions.

Revision ID: 024_suspect_override_columns
Revises: 023_reviewed_by_fk
Create Date: 2026-04-22

Changes (all additive, idempotent via IF NOT EXISTS):

A.  Three new nullable columns on raf_suspect_conditions:
        accept_override_reason   VARCHAR(500) NULL  — clinician-supplied rationale when
                                                       accepting a risky suspect (low confidence /
                                                       incomplete MEAT / failed clinical rule).
        accept_defense_basis     VARCHAR(100) NULL  — short category tag supplied by frontend
                                                       (e.g. "clinical_judgement", "documentation_pending").
        accept_risk_factors_json TEXT         NULL  — JSON array of risk-factor strings that
                                                       triggered the override gate, persisted for audit.

B.  No index added — these columns are write-once audit fields, not filter columns.

Downgrade: drops the three columns (IF EXISTS guards).
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "024_suspect_override_columns"
down_revision: Union[str, None] = "023_reviewed_by_fk"
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


def _x(sql: str) -> None:
    op.execute(sa.text(sql))


# ---------------------------------------------------------------------------
# upgrade
# ---------------------------------------------------------------------------

def upgrade() -> None:
    if not _column_exists("raf_suspect_conditions", "accept_override_reason"):
        _x(
            "ALTER TABLE `raf_suspect_conditions` "
            "ADD COLUMN `accept_override_reason` VARCHAR(500) NULL "
            "COMMENT 'Clinician rationale when accepting a low-confidence / incomplete-MEAT suspect'"
        )

    if not _column_exists("raf_suspect_conditions", "accept_defense_basis"):
        _x(
            "ALTER TABLE `raf_suspect_conditions` "
            "ADD COLUMN `accept_defense_basis` VARCHAR(100) NULL "
            "COMMENT 'Short category tag for the override (e.g. clinical_judgement, documentation_pending)'"
        )

    if not _column_exists("raf_suspect_conditions", "accept_risk_factors_json"):
        _x(
            "ALTER TABLE `raf_suspect_conditions` "
            "ADD COLUMN `accept_risk_factors_json` TEXT NULL "
            "COMMENT 'JSON array of risk-factor labels that triggered the override gate'"
        )


# ---------------------------------------------------------------------------
# downgrade
# ---------------------------------------------------------------------------

def downgrade() -> None:
    drop_cols = [
        "ALTER TABLE raf_suspect_conditions DROP COLUMN IF EXISTS accept_override_reason",
        "ALTER TABLE raf_suspect_conditions DROP COLUMN IF EXISTS accept_defense_basis",
        "ALTER TABLE raf_suspect_conditions DROP COLUMN IF EXISTS accept_risk_factors_json",
    ]
    for stmt in drop_cols:
        op.execute(sa.text(stmt))
