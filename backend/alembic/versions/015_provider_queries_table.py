"""Add provider_queries table for auto-drafted compliant CDI queries.

Revision ID: 015_provider_queries_table
Revises: 014_ai_analysis_runs
Create Date: 2026-04-16 00:00:00.000000

Stores AHIMA/ACDIS-compliant provider queries drafted by the AI pipeline for
suspect / HCC candidates that failed MEAT validation. Every row represents a
single query; the ``citations`` column holds the JSON array of supporting
chart evidence that was used to draft the query (document_id, span, quote).

Status lifecycle:
    draft    -> initial AI draft, pending CDI review
    sent     -> approved and dispatched to provider
    answered -> provider has responded

MySQL-native migration: JSON (not JSONB), TIMESTAMP without TZ,
CURRENT_TIMESTAMP defaults, sa.Enum for the status column.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "015_provider_queries_table"
down_revision: Union[str, None] = "014_ai_analysis_runs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "provider_queries",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("patient_id", sa.Integer, nullable=False, index=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, index=True),
        sa.Column("to_provider_id", sa.String(64), nullable=True, index=True),
        sa.Column("subject", sa.String(512), nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column(
            "status",
            sa.Enum("draft", "sent", "answered", name="provider_query_status"),
            nullable=False,
            server_default="draft",
        ),
        # JSON payload: list of {document_id, span_start, span_end, quote}
        sa.Column("citations", sa.JSON, nullable=False),
        # JSON payload: list of compliance flag codes (empty => clean draft)
        sa.Column("compliance_flags", sa.JSON, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
        ),
        sa.Index("ix_provider_queries_patient_status", "patient_id", "status"),
        sa.Index("ix_provider_queries_tenant_status", "tenant_id", "status"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )


def downgrade() -> None:
    op.drop_table("provider_queries")
