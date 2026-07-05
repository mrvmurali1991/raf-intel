"""Add is_chronic column to raf_patient_hcc

Revision ID: 061_add_is_chronic
Revises: 060_add_missing_indexes
Create Date: 2026-07-05

Moves the idempotent ALTER TABLE that was previously executed on every
score-persistence hot path into a proper Alembic migration.
"""
from __future__ import annotations

import logging
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Revision identifiers
# ---------------------------------------------------------------------------

revision: str = "061_add_is_chronic"
down_revision: Union[str, Sequence[str], None] = "060_add_missing_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Guard: skip if column already exists (may have been created by the
    # now-removed hot-path ALTER TABLE).
    insp = sa.inspect(op.get_bind())
    if insp.has_table("raf_patient_hcc"):
        cols = {c["name"] for c in insp.get_columns("raf_patient_hcc")}
        if "is_chronic" in cols:
            logger.info("is_chronic column already exists — skipping")
            return
    op.add_column(
        "raf_patient_hcc",
        sa.Column("is_chronic", sa.Boolean(), server_default="1"),
    )


def downgrade() -> None:
    op.drop_column("raf_patient_hcc", "is_chronic")
