"""radv_lcb_dollars — add lcb_dollars to raf_radv_audit_runs.

Revision ID: 036_radv_lcb_dollars
Revises: 033_radv_extrapolation_v2, 034_edi_override_signatures, 035_meat_confidence_recompute
Create Date: 2026-05-17

Adds lcb_dollars (Wilson score lower-confidence-bound, 95% one-sided) to
raf_radv_audit_runs so the audit-defense floor pricing computed by
compute_extrapolated_exposure is persisted and queryable.

Column is nullable — NULL means the run has never been through the
simulate endpoint or was created with methodology=legacy_v1 (no LCB).
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "036_radv_lcb_dollars"
down_revision: Union[str, tuple] = (
    "033_radv_extrapolation_v2",
    "034_edi_override_signatures",
    "035_meat_confidence_recompute",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "raf_radv_audit_runs",
        sa.Column("lcb_dollars", sa.Numeric(precision=15, scale=2), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("raf_radv_audit_runs", "lcb_dollars")
