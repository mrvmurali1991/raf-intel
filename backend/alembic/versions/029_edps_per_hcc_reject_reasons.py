"""Add per-HCC EDPS reject reason storage.

Revision ID: 029_edps_per_hcc_reject_reasons
Revises: 028_add_qa_reviews_table
Create Date: 2026-05-17

Two columns to support the new MAO-004 ingest path that carries per-HCC
reject detail from CMS:

* ``raf_patient_hcc.last_edps_reason VARCHAR(255) NULL`` — populated by
  ``edps_ingest`` when the CSV ships a ``rejected_hcc_details_json`` cell
  for the matching ``(patient_id, measurement_year, hcc_code)``. Lets the
  patient detail UI render CMS's wording without re-joining feedback rows.

* ``raf_edps_feedback.rejected_hcc_details JSON NULL`` — stores the parsed
  per-HCC detail array verbatim so the GET endpoint can return it without
  re-parsing the original CSV.

Both columns are nullable + additive: existing rows continue to work, and
the upload path remains backward compatible when the optional column is
absent from the CSV.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "029_edps_per_hcc_reject_reasons"
down_revision: Union[str, None] = "028_add_qa_reviews_table"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _inspector():
    return sa.inspect(op.get_bind())


def _column_exists(table: str, column: str) -> bool:
    if not _inspector().has_table(table):
        return False
    return any(c["name"] == column for c in _inspector().get_columns(table))


def _x(sql: str) -> None:
    op.execute(sa.text(sql))


def upgrade() -> None:
    if not _column_exists("raf_patient_hcc", "last_edps_reason"):
        _x("ALTER TABLE `raf_patient_hcc` ADD COLUMN `last_edps_reason` VARCHAR(255) NULL")
    if not _column_exists("raf_edps_feedback", "rejected_hcc_details"):
        _x("ALTER TABLE `raf_edps_feedback` ADD COLUMN `rejected_hcc_details` JSON NULL")


def downgrade() -> None:
    if _column_exists("raf_edps_feedback", "rejected_hcc_details"):
        _x("ALTER TABLE `raf_edps_feedback` DROP COLUMN `rejected_hcc_details`")
    if _column_exists("raf_patient_hcc", "last_edps_reason"):
        _x("ALTER TABLE `raf_patient_hcc` DROP COLUMN `last_edps_reason`")
