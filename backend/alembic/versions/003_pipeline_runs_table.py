"""Add pipeline_runs table for step-by-step pipeline status tracking.

Revision ID: 003_pipeline_runs_table
Revises: 002_tenant_isolation_and_constraints
Create Date: 2026-04-13 00:00:00.000000

Creates the ``pipeline_runs`` table which tracks every auto-chain pipeline
execution (emr_sync_completed → normalization → raf_calculation_completed)
including per-step state, retry counts, and final stats.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import LONGTEXT


revision: str = "003_pipeline_runs_table"
down_revision: Union[str, None] = "002_tenant_isolation_and_constraints"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    if "pipeline_runs" in existing_tables:
        return

    op.create_table(
        "pipeline_runs",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, index=True),
        sa.Column("trigger_event", sa.String(128), nullable=False),
        sa.Column("connection_id", sa.Integer, nullable=True),
        sa.Column("sync_type", sa.String(64), nullable=True),
        # idempotency key: (tenant_id, sync_id) — sync_id is a caller-supplied
        # opaque token (e.g. a Celery job_id or emr_sync row id)
        sa.Column("sync_id", sa.String(255), nullable=True),
        sa.Column(
            "status",
            sa.Enum("pending", "running", "completed", "failed", name="pipeline_status"),
            nullable=False,
            server_default="pending",
        ),
        # JSON array of completed step names, e.g. ["sync_encounters","sync_diagnoses"]
        sa.Column("steps_completed", LONGTEXT, nullable=True),
        sa.Column("current_step", sa.String(128), nullable=True),
        sa.Column("started_at", sa.DateTime, nullable=True),
        sa.Column("finished_at", sa.DateTime, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        # JSON object with arbitrary stats (e.g. {"encounters": 42, "diagnoses": 180})
        sa.Column("stats", LONGTEXT, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )

    # Unique index for idempotency — one active run per (tenant_id, sync_id)
    # when sync_id is provided.  NULL sync_ids are not subject to this constraint
    # (MySQL does not enforce unique over NULLs for multi-column unique keys in the
    # same way as some other RDBMS — this is the desired behaviour here).
    op.create_index(
        "uq_pipeline_runs_tenant_sync",
        "pipeline_runs",
        ["tenant_id", "sync_id"],
        unique=True,
    )

    op.create_index(
        "ix_pipeline_runs_tenant_status",
        "pipeline_runs",
        ["tenant_id", "status"],
    )

    op.create_index(
        "ix_pipeline_runs_created_at",
        "pipeline_runs",
        ["created_at"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    if "pipeline_runs" not in existing_tables:
        return

    op.drop_index("ix_pipeline_runs_created_at", table_name="pipeline_runs")
    op.drop_index("ix_pipeline_runs_tenant_status", table_name="pipeline_runs")
    op.drop_index("uq_pipeline_runs_tenant_sync", table_name="pipeline_runs")
    op.drop_table("pipeline_runs")
