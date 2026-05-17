"""merge_round2_heads

Revision ID: a7dfeec671e1
Revises: 033_radv_extrapolation_v2, 034_edi_override_signatures, 035_meat_confidence_recompute
Create Date: 2026-05-17 13:47:36.307697+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7dfeec671e1'
down_revision: Union[str, None] = ('033_radv_extrapolation_v2', '034_edi_override_signatures', '035_meat_confidence_recompute')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
