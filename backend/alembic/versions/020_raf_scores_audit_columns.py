"""Add audit-defensibility columns to raf_scores.

Revision ID: 020_raf_scores_audit_columns
Revises: 019_clinical_notes_table
Create Date: 2026-04-17

Each ``raf_scores`` row must be forensically traceable for RADV defense:

* ``model_version``          — the CMS-HCC model that produced the score
                                 (``V28``, ``V24``, ``V22``, or ``BLEND``).
* ``coefficient_source``     — opaque identifier of the coefficient provider
                                 (e.g. ``hccinfhir==0.3.0`` or
                                 ``cms_py2026_midyear``).
* ``coefficient_manifest_hash`` — SHA-256 of
                                 ``coefficients_manifest.json`` at the time
                                 this row was written.  Any drift is
                                 immediately visible.
* ``calculator_commit_sha``  — git commit SHA of the backend image that
                                 produced the score.  Lets auditors replay
                                 the exact code path.

All columns are nullable so historical rows (written before the migration)
remain valid.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "020_raf_scores_audit_columns"
down_revision: Union[str, None] = "019_clinical_notes_table"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _inspector():
    return sa.inspect(op.get_bind())


def _table_exists(name: str) -> bool:
    return _inspector().has_table(name)


def _column_exists(table: str, column: str) -> bool:
    if not _table_exists(table):
        return False
    return any(c["name"] == column for c in _inspector().get_columns(table))


_NEW_COLUMNS: tuple[tuple[str, str, str], ...] = (
    # (column_name, column_type, after_column)
    ("model_version",             "VARCHAR(16)  DEFAULT NULL", "v28_hcc_count"),
    ("coefficient_source",        "VARCHAR(64)  DEFAULT NULL", "model_version"),
    ("coefficient_manifest_hash", "CHAR(64)     DEFAULT NULL", "coefficient_source"),
    ("calculator_commit_sha",     "VARCHAR(40)  DEFAULT NULL", "coefficient_manifest_hash"),
)


def upgrade() -> None:
    if not _table_exists("raf_scores"):
        return

    dialect = op.get_bind().dialect.name

    for col_name, col_ddl, after_col in _NEW_COLUMNS:
        if _column_exists("raf_scores", col_name):
            continue

        after_clause = f" AFTER {after_col}" if dialect == "mysql" else ""
        op.execute(
            sa.text(
                f"ALTER TABLE raf_scores ADD COLUMN {col_name} {col_ddl}{after_clause}"
            )
        )


def downgrade() -> None:
    if not _table_exists("raf_scores"):
        return

    for col_name, _col_ddl, _after_col in _NEW_COLUMNS:
        if not _column_exists("raf_scores", col_name):
            continue

        op.execute(sa.text(f"ALTER TABLE raf_scores DROP COLUMN {col_name}"))
