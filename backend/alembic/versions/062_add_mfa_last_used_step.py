"""Add mfa_last_used_step column to users table

Revision ID: 062_add_mfa_last_used_step
Revises: 061_add_is_chronic
Create Date: 2026-07-05

Prevents TOTP code replay attacks by tracking the last accepted
time-step index per user.
"""
from __future__ import annotations

import logging
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

logger = logging.getLogger(__name__)

revision: str = "062_add_mfa_last_used_step"
down_revision: Union[str, Sequence[str], None] = "061_add_is_chronic"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if insp.has_table("users"):
        cols = {c["name"] for c in insp.get_columns("users")}
        if "mfa_last_used_step" in cols:
            logger.info("mfa_last_used_step column already exists — skipping")
            return
    op.add_column(
        "users",
        sa.Column("mfa_last_used_step", sa.BigInteger(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "mfa_last_used_step")
