"""Create fhir_documents_processed dedup/tracking table.

Revision ID: 041_fhir_documents_processed
Revises: 039_fhir_writeback_status
Create Date: 2026-05-18

Tracks every FHIR DocumentReference that has been fetched via the
DocumentReference + Binary ingest pipeline, enabling idempotent re-runs.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "041_fhir_documents_processed"
down_revision: Union[str, None] = "039_fhir_writeback_status"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if insp.has_table("fhir_documents_processed"):
        return

    op.create_table(
        "fhir_documents_processed",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("fhir_document_id", sa.String(128), nullable=False),
        sa.Column("raf_patient_id", sa.Integer, nullable=True),
        sa.Column("fhir_url", sa.String(500), nullable=True),
        sa.Column("filename", sa.String(255), nullable=True),
        sa.Column("mimetype", sa.String(64), nullable=True),
        sa.Column("size_bytes", sa.Integer, nullable=True),
        sa.Column("suspects_extracted", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "status",
            sa.Enum(
                "success",
                "already_processed",
                "fetch_error",
                "skipped",
                "error",
                name="fhir_doc_status",
            ),
            nullable=False,
            server_default="success",
        ),
        sa.Column("processed_at", sa.DateTime, nullable=True),
        sa.UniqueConstraint("tenant_id", "fhir_document_id", name="uq_fhir_doc_tenant"),
        sa.Index("idx_fdp_tenant_patient", "tenant_id", "raf_patient_id"),
        sa.Index("idx_fdp_status", "status"),
    )


def downgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if insp.has_table("fhir_documents_processed"):
        op.drop_table("fhir_documents_processed")
    # Drop the ENUM type for databases that require it (PostgreSQL)
    try:
        op.execute(sa.text("DROP TYPE IF EXISTS fhir_doc_status"))
    except Exception:
        pass
