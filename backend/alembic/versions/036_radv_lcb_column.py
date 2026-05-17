"""Add lcb_dollars column to raf_radv_audit_runs for Wilson LCB storage.

Revision ID: 036_radv_lcb_column
Revises: a7dfeec671e1
Create Date: 2026-05-17

References: CMS Feb-2023 Final Rule (90 FR 1944) FFS Adjuster methodology.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "036_radv_lcb_column"
down_revision = "a7dfeec671e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "raf_radv_audit_runs",
        sa.Column(
            "lcb_dollars",
            sa.Numeric(precision=14, scale=2),
            nullable=True,
            comment=(
                "One-sided 99% Wilson score LCB on projected payment error "
                "(CMS Feb-2023 Final Rule, 90 FR 1944). NULL for legacy runs."
            ),
        ),
    )


def downgrade() -> None:
    op.drop_column("raf_radv_audit_runs", "lcb_dollars")
