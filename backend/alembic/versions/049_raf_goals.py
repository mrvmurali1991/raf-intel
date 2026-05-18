"""Create raf_goals table for quarterly goal tracking.

Revision ID: 049_raf_goals
Revises: 048_tenant_doc_policy
Create Date: 2026-05-18
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "049_raf_goals"
down_revision: Union[str, None] = "048_tenant_doc_policy"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if insp.has_table("raf_goals"):
        return

    op.create_table(
        "raf_goals",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, index=True),
        sa.Column(
            "period",
            sa.String(8),
            nullable=False,
            comment="YYYY-QN, e.g. 2026-Q2",
        ),
        sa.Column(
            "metric",
            sa.Enum(
                "raf_capture_count",
                "revenue",
                "gaps_closed",
                name="raf_goal_metric",
            ),
            nullable=False,
        ),
        sa.Column("target_value", sa.Numeric(14, 2), nullable=False),
        sa.Column("owner_user_id", sa.Integer, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index(
        "ix_raf_goals_tenant_period",
        "raf_goals",
        ["tenant_id", "period"],
    )


def downgrade() -> None:
    op.drop_index("ix_raf_goals_tenant_period", table_name="raf_goals")
    op.drop_table("raf_goals")
    op.execute("DROP TYPE IF EXISTS raf_goal_metric")
