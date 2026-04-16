"""Add ai_analysis_runs table for per-patient pipeline run tracking.

Revision ID: 014_ai_analysis_runs
Revises: 013_system_config_table
Create Date: 2026-04-16 00:10:00.000000

One row per full AI analysis pipeline run. Used by
``app.services.ai_pipeline.eligibility`` to enforce a per-patient daily
cap (default 2 runs/day) and to record trigger reasons for audit.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "014_ai_analysis_runs"
down_revision: Union[str, None] = "013_system_config_table"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # NOTE: We do not use ``sa.inspect(bind)`` here because that breaks
    # ``alembic upgrade head --sql`` (offline / no live DB connection).
    # Idempotency is enforced at the SQL level via a raw CREATE TABLE IF
    # NOT EXISTS executed through ``op.execute`` — but because we want the
    # full SQLAlchemy-rendered DDL (charset, engine, indexes) we rely on
    # Alembic's normal ``create_table`` and accept that re-running will
    # error if the table already exists. Operators should ``alembic stamp``
    # past this revision if the table was created manually.
    op.create_table(
        "ai_analysis_runs",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("patient_id", sa.Integer, nullable=False),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("finished_at", sa.DateTime, nullable=True),
        # status: "running" | "success" | "failed"
        sa.Column("status", sa.String(32), nullable=False, server_default="running"),
        sa.Column("trigger_reason", sa.String(128), nullable=True),
        sa.Index(
            "ix_ai_runs_patient_started",
            "tenant_id",
            "patient_id",
            "started_at",
        ),
        sa.Index("ix_ai_runs_tenant_started", "tenant_id", "started_at"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )


def downgrade() -> None:
    op.drop_table("ai_analysis_runs")
