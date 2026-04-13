"""Add pipeline_settings table for per-tenant pipeline mode configuration.

Revision ID: 005_pipeline_settings_table
Revises: 004_hcc_icd10_crosswalk
Create Date: 2026-04-13 00:00:00.000000

Stores the pipeline mode toggle (auto_ai / auto_basic / manual) and
individual feature flags per tenant.  One row per tenant; missing rows
are treated as the 'auto_basic' default by the router.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import TINYINT


revision: str = "005_pipeline_settings_table"
down_revision: Union[str, None] = "004_hcc_icd10_crosswalk"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "pipeline_settings" in inspector.get_table_names():
        return

    op.create_table(
        "pipeline_settings",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column(
            "pipeline_mode",
            sa.Enum("auto_ai", "auto_basic", "manual", name="pipeline_mode_enum"),
            nullable=False,
            server_default="auto_basic",
        ),
        sa.Column(
            "ai_analysis_enabled",
            TINYINT(1),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "suspect_scan_enabled",
            TINYINT(1),
            nullable=False,
            server_default="1",
        ),
        sa.Column(
            "gap_generation_enabled",
            TINYINT(1),
            nullable=False,
            server_default="1",
        ),
        sa.Column(
            "hierarchy_enabled",
            TINYINT(1),
            nullable=False,
            server_default="1",
        ),
        sa.Column(
            "webhook_enabled",
            TINYINT(1),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "gemini_max_concurrent",
            sa.Integer,
            nullable=False,
            server_default="5",
        ),
        sa.Column("updated_by", sa.String(100), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )

    op.create_index(
        "uq_pipeline_settings_tenant",
        "pipeline_settings",
        ["tenant_id"],
        unique=True,
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "pipeline_settings" not in inspector.get_table_names():
        return

    op.drop_index("uq_pipeline_settings_tenant", table_name="pipeline_settings")
    op.drop_table("pipeline_settings")

    # Drop the ENUM type (no-op on MySQL; required for PostgreSQL)
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TYPE IF EXISTS pipeline_mode_enum")
