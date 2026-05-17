"""034 — edi_override_signatures: co-signer audit table for EDI override gate.

Revision ID: 034_edi_override_signatures
Revises: 030_add_radv_audit_runs
Create Date: 2026-05-17
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "034_edi_override_signatures"
down_revision = "030_add_radv_audit_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "edi_override_signatures",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("edi_file_id", sa.BigInteger(), nullable=True),
        sa.Column("patient_id", sa.Integer(), nullable=False),
        sa.Column("submitter_user_id", sa.Integer(), nullable=True),
        sa.Column("reviewer_user_id", sa.Integer(), nullable=False),
        sa.Column("override_reason", sa.Text(), nullable=False),
        sa.Column("signed_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_edi_override_tenant_file",
        "edi_override_signatures",
        ["tenant_id", "edi_file_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_edi_override_tenant_file", table_name="edi_override_signatures")
    op.drop_table("edi_override_signatures")
