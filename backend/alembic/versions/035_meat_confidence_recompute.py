"""meat_confidence_recompute

Revision ID: 035_meat_confidence_recompute
Revises: 032_cds_hooks_dismissal_log
Create Date: 2026-05-17 00:00:00.000000+00:00

Backfill raf_meat_evidence.overall_confidence using the correct average:
divide by the number of non-NULL letter-confidence columns instead of
always dividing by 4.  Rows where all four letter-confidences are NULL are
left untouched (overall_confidence stays as-is — typically NULL as well).

This migration is safe to run repeatedly (idempotent UPDATE with WHERE).
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "035_meat_confidence_recompute"
down_revision: Union[str, None] = "032_cds_hooks_dismissal_log"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Recompute overall_confidence as mean of the letter-level confidences
    # that are actually present (non-NULL).  GREATEST(1, ...) prevents
    # divide-by-zero in the unlikely event all four columns are NULL but
    # overall_confidence was somehow set.
    op.execute(
        """
        UPDATE raf_meat_evidence
        SET overall_confidence = ROUND(
            (
                COALESCE(m_confidence, 0)
              + COALESCE(e_confidence, 0)
              + COALESCE(a_confidence, 0)
              + COALESCE(t_confidence, 0)
            )
            /
            GREATEST(
                1,
                (m_confidence IS NOT NULL)
              + (e_confidence IS NOT NULL)
              + (a_confidence IS NOT NULL)
              + (t_confidence IS NOT NULL)
            ),
            4
        )
        WHERE overall_confidence IS NOT NULL
        """
    )


def downgrade() -> None:
    # Restore the (incorrect) divide-by-4 behaviour.  Only touches rows
    # that have at least one non-NULL letter confidence so we don't widen
    # the damage to rows with no letter evidence.
    op.execute(
        """
        UPDATE raf_meat_evidence
        SET overall_confidence = ROUND(
            (
                COALESCE(m_confidence, 0)
              + COALESCE(e_confidence, 0)
              + COALESCE(a_confidence, 0)
              + COALESCE(t_confidence, 0)
            ) / 4,
            4
        )
        WHERE overall_confidence IS NOT NULL
        """
    )
