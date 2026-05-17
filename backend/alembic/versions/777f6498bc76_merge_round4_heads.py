"""merge_round4_heads

Revision ID: 777f6498bc76
Revises: 036_radv_lcb_dollars, a7dfeec671e1
Create Date: 2026-05-17 15:31:20.451998+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '777f6498bc76'
down_revision: Union[str, None] = ('036_radv_lcb_dollars', 'a7dfeec671e1')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
