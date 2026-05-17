"""RADV extrapolation v2 — add FFS Adjuster fields to raf_radv_audit_runs.

Revision ID: 033_radv_extrapolation_v2
Revises: 031_fhir_writeback_reversal, 032_cds_hooks_dismissal_log
Create Date: 2026-05-17

Adds three columns to raf_radv_audit_runs to support CMS FFS Adjuster
extrapolation methodology (Feb 2023 Final Rule):

  members_enrolled           INT NULL
      Total contract enrollment for the audit period.  When populated,
      the run uses FFS Adjuster extrapolation (methodology: ffs_adjuster_v1).
      NULL means the run pre-dates this migration and uses legacy 55x math
      (methodology: legacy_v1).

  ffs_adjuster               DECIMAL(5,4) NULL DEFAULT 0.97
      CMS FFS Adjuster value per the Feb 2023 Final Rule.  Settable
      per contract to reflect CMS-published contract-specific values.

  extrapolation_methodology  VARCHAR(64) DEFAULT 'legacy_v1'
      Indicates which extrapolation formula was applied:
        'ffs_adjuster_v1' — FFS Adjuster with members_enrolled (CMS-grade)
        'legacy_v1'       — deprecated 55x multiplier (backward compat)

Existing rows default to legacy_v1 with NULL members_enrolled so old
audit-run responses retain their previous behavior.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "033_radv_extrapolation_v2"
down_revision: Union[str, tuple] = (
    "031_fhir_writeback_reversal",
    "032_cds_hooks_dismissal_log",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "raf_radv_audit_runs",
        sa.Column("members_enrolled", sa.Integer(), nullable=True),
    )
    op.add_column(
        "raf_radv_audit_runs",
        sa.Column(
            "ffs_adjuster",
            sa.Numeric(precision=5, scale=4),
            nullable=True,
            server_default="0.9700",
        ),
    )
    op.add_column(
        "raf_radv_audit_runs",
        sa.Column(
            "extrapolation_methodology",
            sa.String(64),
            nullable=True,
            server_default="legacy_v1",
        ),
    )


def downgrade() -> None:
    op.drop_column("raf_radv_audit_runs", "extrapolation_methodology")
    op.drop_column("raf_radv_audit_runs", "ffs_adjuster")
    op.drop_column("raf_radv_audit_runs", "members_enrolled")
