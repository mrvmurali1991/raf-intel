"""Add datavant_chart_requests and datavant_documents_received tables.

Revision ID: 045_datavant_requests
Revises: 042_hl7v2_messages
Create Date: 2026-05-18

Supports the Datavant Switchboard chart-retrieval integration.  Two tables
are added:

  datavant_chart_requests
      One row per chart retrieval request submitted to the Switchboard.
      Tracks submission metadata, current status, and a JSON list of
      document identifiers returned by Datavant.

  datavant_documents_received
      One row per document delivered by a Datavant webhook notification.
      Tracks download state, MIME type, size, and whether the AI pipeline
      has extracted suspect HCC codes from the document.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "045_datavant_requests"
down_revision: Union[str, None] = "042_hl7v2_messages"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "datavant_chart_requests",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("raf_patient_id", sa.Integer(), nullable=False),
        sa.Column(
            "datavant_request_id",
            sa.String(255),
            nullable=False,
            unique=True,
            comment="Unique identifier returned by the Datavant Switchboard API",
        ),
        sa.Column(
            "submitted_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "status",
            sa.String(64),
            nullable=False,
            server_default="submitted",
            comment="Lifecycle status: submitted | processing | complete | failed",
        ),
        sa.Column(
            "document_ids",
            sa.JSON(),
            nullable=True,
            comment="JSON array of Datavant document IDs delivered for this request",
        ),
        sa.Column("dos_from", sa.Date(), nullable=True),
        sa.Column("dos_to", sa.Date(), nullable=True),
        sa.Column("reason", sa.String(255), nullable=True),
        sa.Column(
            "cost_estimate_dollars",
            sa.DECIMAL(8, 2),
            nullable=True,
            comment="Estimated cost in USD per Datavant pricing ($15–$50/chart)",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index(
        "ix_datavant_chart_requests_tenant_id",
        "datavant_chart_requests",
        ["tenant_id"],
    )
    op.create_index(
        "ix_datavant_chart_requests_raf_patient_id",
        "datavant_chart_requests",
        ["raf_patient_id"],
    )
    op.create_index(
        "ix_datavant_chart_requests_status",
        "datavant_chart_requests",
        ["status"],
    )

    op.create_table(
        "datavant_documents_received",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "request_id",
            sa.Integer(),
            sa.ForeignKey("datavant_chart_requests.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "datavant_document_id",
            sa.String(255),
            nullable=False,
            unique=True,
            comment="Unique document identifier from the Datavant Switchboard",
        ),
        sa.Column("filename", sa.String(512), nullable=True),
        sa.Column("mimetype", sa.String(128), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column(
            "downloaded_at",
            sa.DateTime(),
            nullable=True,
            comment="Timestamp when the binary was successfully downloaded",
        ),
        sa.Column(
            "processed",
            sa.SmallInteger(),
            nullable=False,
            server_default="0",
            comment="0 = pending AI extraction, 1 = processed",
        ),
        sa.Column(
            "suspects_extracted",
            sa.Integer(),
            nullable=True,
            comment="Number of suspect HCC codes extracted by the AI pipeline",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index(
        "ix_datavant_documents_received_request_id",
        "datavant_documents_received",
        ["request_id"],
    )
    op.create_index(
        "ix_datavant_documents_received_processed",
        "datavant_documents_received",
        ["processed"],
    )


def downgrade() -> None:
    op.drop_table("datavant_documents_received")
    op.drop_table("datavant_chart_requests")
