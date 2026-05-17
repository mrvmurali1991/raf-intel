"""MEAT evidence sentence-offset columns + source_encounter_id.

Revision ID: 030_meat_evidence_offsets
Revises: 029_edps_per_hcc_reject_reasons
Create Date: 2026-05-17

Adds per-letter sentence-offset columns and a source-encounter pointer to
``raf_meat_evidence`` so the LLM evidence extractor (Gap #12 — MEAT
evidence-snippet auto-extraction) can store the {start, end} character
offsets of the proving sentence for each M/E/A/T letter alongside the
verbatim text.

Columns added (all nullable, additive):

  * ``meat_m_offsets`` JSON     — ``[start, end]`` offsets in source note
  * ``meat_e_offsets`` JSON     — ``[start, end]`` offsets
  * ``meat_a_offsets`` JSON     — ``[start, end]`` offsets
  * ``meat_t_offsets`` JSON     — ``[start, end]`` offsets
  * ``source_encounter_id`` INT — encounter the snippets came from
                                  (separate from ``encounter_id`` which
                                  may have been set by an attestation
                                  workflow).

Downgrade drops the same columns (IF EXISTS guards).
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "030_meat_evidence_offsets"
down_revision: Union[str, None] = "029_edps_per_hcc_reject_reasons"
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
    if not _table_exists("raf_meat_evidence"):
        # Defensive: nothing to do until the parent table has been created
        # by an earlier migration / bootstrap.
        return

    for col in ("meat_m_offsets", "meat_e_offsets", "meat_a_offsets", "meat_t_offsets"):
        if not _column_exists("raf_meat_evidence", col):
            _x(
                f"ALTER TABLE `raf_meat_evidence` "
                f"ADD COLUMN `{col}` JSON NULL "
                f"COMMENT '[start, end] character offsets of the proving sentence in source note'"
            )

    if not _column_exists("raf_meat_evidence", "source_encounter_id"):
        _x(
            "ALTER TABLE `raf_meat_evidence` "
            "ADD COLUMN `source_encounter_id` INT NULL "
            "COMMENT 'Encounter ID the MEAT snippets were extracted from (Gap #12 extractor)'"
        )


# ---------------------------------------------------------------------------
# downgrade
# ---------------------------------------------------------------------------

def downgrade() -> None:
    drop_cols = [
        "ALTER TABLE raf_meat_evidence DROP COLUMN IF EXISTS source_encounter_id",
        "ALTER TABLE raf_meat_evidence DROP COLUMN IF EXISTS meat_t_offsets",
        "ALTER TABLE raf_meat_evidence DROP COLUMN IF EXISTS meat_a_offsets",
        "ALTER TABLE raf_meat_evidence DROP COLUMN IF EXISTS meat_e_offsets",
        "ALTER TABLE raf_meat_evidence DROP COLUMN IF EXISTS meat_m_offsets",
    ]
    for stmt in drop_cols:
        try:
            op.execute(sa.text(stmt))
        except Exception:
            pass
