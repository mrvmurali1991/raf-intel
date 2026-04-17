"""raf_recompute_inbox: per-patient dirty-marker table driving async RAF recompute.

Revision ID: 018_raf_recompute_inbox
Revises: 017_ai_pipeline_tables
Create Date: 2026-04-17

Introduces the "inbox" pattern replacing the in-process RAF calculation phase
of pipeline_chain.py.

When anything mutates a patient's scoring inputs — EMR sync, encounter
analysis, suspect accept/dismiss, sweep-period change, manual edit — we
simply INSERT IGNORE a row here keyed on (pid, tenant_id, status='pending').
The worker (``task_drain_raf_inbox``, Celery Beat every 15 s) atomically
claims each pending row, runs ``calculate_raf_score``, marks done/failed.

Benefits over the previous in-process chain:
  * Natural debouncing — 50 encounters in 5 s coalesce into one recompute.
  * Idempotent — worker crashes don't lose work; the row stays pending.
  * Single code path regardless of trigger source.
  * Observable — ``SELECT count(*) FROM raf_recompute_pending WHERE status='pending'``.

Schema notes
------------
  * Unique key on (pid, tenant_id, status) prevents duplicate pending/
    processing rows for the same patient. Completed/failed rows may coexist.
  * ``reason`` is free-form but conventionally one of:
        sync | analysis | suspect | sweep_change | manual | backfill
  * ``status`` state machine: pending → processing → (done | failed)
    - done rows can be purged by a retention sweep; kept for observability.
    - failed rows can be requeued by the admin endpoint.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "018_raf_recompute_inbox"
down_revision: Union[str, None] = "2431d3f065b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "raf_recompute_pending",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("pid", sa.Integer, nullable=False),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("reason", sa.String(32), nullable=False),
        sa.Column(
            "status",
            sa.Enum("pending", "processing", "done", "failed", name="raf_inbox_status"),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("attempts", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("last_error", sa.Text, nullable=True),
        sa.Column(
            "queued_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("claimed_at", sa.DateTime, nullable=True),
        sa.Column("completed_at", sa.DateTime, nullable=True),
        # Natural debouncing: at most one (pid, tenant_id) row per active status.
        # Completed and failed rows can coexist with pending (for history).
        sa.UniqueConstraint(
            "pid", "tenant_id", "status", name="uk_raf_inbox_active"
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index(
        "idx_raf_inbox_status_queued",
        "raf_recompute_pending",
        ["status", "queued_at"],
    )
    op.create_index(
        "idx_raf_inbox_tenant",
        "raf_recompute_pending",
        ["tenant_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("idx_raf_inbox_tenant", table_name="raf_recompute_pending")
    op.drop_index("idx_raf_inbox_status_queued", table_name="raf_recompute_pending")
    op.drop_table("raf_recompute_pending")
