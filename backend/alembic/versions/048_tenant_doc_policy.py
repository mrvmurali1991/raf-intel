"""Create tenant_document_policy table.

Revision ID: 048_tenant_doc_policy
Revises: 041_fhir_documents_processed
Create Date: 2026-05-18

Stores per-tenant document-processing policy, including whether LLM-based
extraction is disabled (e.g. for 42 CFR Part 2 compliance) and which fallback
OCR engine to use.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "048_tenant_doc_policy"
down_revision: Union[str, None] = "041_fhir_documents_processed"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if insp.has_table("tenant_document_policy"):
        return

    op.create_table(
        "tenant_document_policy",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column(
            "disable_llm_documents",
            sa.SmallInteger,
            nullable=False,
            server_default="0",
            comment="1 = route ALL document OCR through fallback engine, bypass Gemini",
        ),
        sa.Column(
            "llm_blocked_categories",
            sa.JSON,
            nullable=True,
            comment="List of document category strings that must bypass LLM (42 CFR Part 2 etc.)",
        ),
        sa.Column(
            "fallback_engine",
            sa.String(32),
            nullable=False,
            server_default="tesseract",
            comment="tesseract | aws_textract",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime,
            nullable=True,
            server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
        ),
        sa.Column("updated_by_user_id", sa.Integer, nullable=True),
        sa.UniqueConstraint("tenant_id", name="uq_tdp_tenant_id"),
        sa.Index("idx_tdp_tenant", "tenant_id"),
    )


def downgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if insp.has_table("tenant_document_policy"):
        op.drop_table("tenant_document_policy")
