"""merge 003 branch heads

Revision ID: 2431d3f065b7
Revises: 003_pipeline_runs_table, 017_ai_pipeline_tables
Create Date: 2026-04-16 06:47:42.199028+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2431d3f065b7'
down_revision: Union[str, None] = ('003_pipeline_runs_table', '017_ai_pipeline_tables')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
