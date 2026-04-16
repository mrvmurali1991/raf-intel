"""Add system_config table for global/tenant-scoped key-value settings.

Revision ID: 013_system_config_table
Revises: 012_fix_duplicate_patients
Create Date: 2026-04-16 00:00:00.000000

A generic string key/value store for system-wide configuration. Used
initially for AI analysis controls (cutoff date, per-patient daily cap),
but intentionally general so additional flags can be added without new
migrations.

Keys are global when ``tenant_id`` is NULL, or tenant-scoped otherwise.
The ``config_service`` layer handles precedence (tenant > global).
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "013_system_config_table"
down_revision: Union[str, None] = "012_fix_duplicate_patients"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Seed values for AI analysis controls. Read from backend via config_service.
_SEED_ROWS = [
    ("ai_analysis_cutoff_date", "2026-04-15"),
    ("max_analyses_per_patient_per_day", "2"),
]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "system_config" not in inspector.get_table_names():
        # Note: MySQL disallows NULL in PRIMARY KEY columns, so we use a
        # surrogate ``tenant_scope`` column that stores the literal string
        # ``'__global__'`` for global settings. The application layer
        # translates NULL tenant -> '__global__' transparently.
        op.create_table(
            "system_config",
            sa.Column("config_key", sa.String(128), nullable=False),
            sa.Column(
                "tenant_scope",
                sa.String(64),
                nullable=False,
                server_default="__global__",
            ),
            sa.Column("config_value", sa.Text, nullable=True),
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
            sa.PrimaryKeyConstraint(
                "config_key", "tenant_scope", name="pk_system_config"
            ),
            mysql_engine="InnoDB",
            mysql_charset="utf8mb4",
            mysql_collate="utf8mb4_unicode_ci",
        )

    # Seed defaults as global rows. Idempotent — existing values preserved.
    for key, value in _SEED_ROWS:
        op.execute(
            sa.text(
                "INSERT INTO system_config (config_key, tenant_scope, config_value) "
                "VALUES (:k, '__global__', :v) "
                "ON DUPLICATE KEY UPDATE config_value = config_value"
            ).bindparams(k=key, v=value)
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "system_config" in inspector.get_table_names():
        op.drop_table("system_config")
