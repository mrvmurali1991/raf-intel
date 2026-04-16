"""ai_audit_log table

Revision ID: 016_ai_audit_log
Revises: 015_provider_queries_table
Create Date: 2026-04-16

MySQL-native: JSON (not JSONB), TIMESTAMP without TZ,
CURRENT_TIMESTAMP defaults, named CHECK constraint, sa.Enum for actor_type.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "016_ai_audit_log"
down_revision: Union[str, None] = "015_provider_queries_table"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ai_audit_log",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, index=True),
        sa.Column(
            "actor_type",
            sa.Enum("system", "user", name="ai_audit_actor_type"),
            nullable=False,
        ),
        sa.Column("actor_id", sa.String(128), nullable=True),
        sa.Column("action", sa.String(128), nullable=False, index=True),
        sa.Column("target_type", sa.String(64), nullable=True),
        sa.Column("target_id", sa.String(128), nullable=True),
        sa.Column("before", sa.JSON, nullable=True),
        sa.Column("after", sa.JSON, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            index=True,
        ),
        sa.CheckConstraint(
            "actor_type IN ('system','user')", name="ck_ai_audit_actor_type"
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index(
        "ix_ai_audit_tenant_created",
        "ai_audit_log",
        ["tenant_id", "created_at"],
    )
    op.create_index(
        "ix_ai_audit_target",
        "ai_audit_log",
        ["target_type", "target_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_ai_audit_target", table_name="ai_audit_log")
    op.drop_index("ix_ai_audit_tenant_created", table_name="ai_audit_log")
    op.drop_table("ai_audit_log")
