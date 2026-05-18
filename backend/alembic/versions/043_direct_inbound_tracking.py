"""Add direct_inbound_messages table for Direct Trust inbound tracking.

Revision ID: 043_direct_inbound_tracking
Revises: 039_fhir_writeback_status
Create Date: 2026-05-18

Tracks every Direct Trust MIME message received at POST /api/direct/inbound.
Provides idempotency (UNIQUE tenant_id + message_id), per-message parse
counts, and an error text column for pipeline forensics.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# ---------------------------------------------------------------------------
# Alembic identifiers
# ---------------------------------------------------------------------------

revision: str = "043_direct_inbound_tracking"
down_revision: Union[str, None] = "039_fhir_writeback_status"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ---------------------------------------------------------------------------
# Upgrade
# ---------------------------------------------------------------------------

def upgrade() -> None:
    op.create_table(
        "direct_inbound_messages",
        sa.Column("id",                sa.Integer,     nullable=False, autoincrement=True),
        sa.Column("tenant_id",         sa.String(50),  nullable=False, server_default="default"),
        sa.Column("message_id",        sa.String(255), nullable=False),
        sa.Column("from_address",      sa.String(255), nullable=False),
        sa.Column("to_address",        sa.String(255), nullable=False),
        sa.Column("subject",           sa.String(500), nullable=True),
        sa.Column("received_at",       sa.DateTime,    nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("ccda_parsed",       sa.SmallInteger, nullable=False, server_default="0",
                  comment="Number of C-CDA XML attachments successfully parsed"),
        sa.Column("suspects_extracted", sa.Integer,    nullable=False, server_default="0",
                  comment="Total HCC suspect conditions written to raf_suspect_conditions"),
        sa.Column("status",            sa.String(20),  nullable=False, server_default="processed",
                  comment="processed | error"),
        sa.Column("error_text",        sa.Text,        nullable=True,
                  comment="Non-fatal parse error details"),
        sa.Column("created_at",        sa.DateTime,    nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at",        sa.DateTime,    nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP")),

        # Constraints
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "message_id", name="uq_dim_tenant_message"),
    )

    # Performance indexes
    op.create_index("idx_dim_tenant_id",      "direct_inbound_messages", ["tenant_id"])
    op.create_index("idx_dim_from_address",   "direct_inbound_messages", ["from_address"])
    op.create_index("idx_dim_received_at",    "direct_inbound_messages", ["received_at"])
    op.create_index("idx_dim_status",         "direct_inbound_messages", ["status"])


# ---------------------------------------------------------------------------
# Downgrade
# ---------------------------------------------------------------------------

def downgrade() -> None:
    op.drop_index("idx_dim_status",         table_name="direct_inbound_messages")
    op.drop_index("idx_dim_received_at",    table_name="direct_inbound_messages")
    op.drop_index("idx_dim_from_address",   table_name="direct_inbound_messages")
    op.drop_index("idx_dim_tenant_id",      table_name="direct_inbound_messages")
    op.drop_table("direct_inbound_messages")
