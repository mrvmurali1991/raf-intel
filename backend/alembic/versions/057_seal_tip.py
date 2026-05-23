"""Seal 056 as the canonical tip so future migrations chain off a single head.

Revision ID: 057_seal_tip
Revises: 056_clean_emr_pid_floats
Create Date: 2026-05-23

After this no-op, `alembic upgrade head` resolves deterministically to 057;
the next real migration sets down_revision = "057_seal_tip". The reviewer
flagged 056 as dangling because nothing pointed AT it; this revision closes
that gap without adding a no-op chain for every future revision (just chain
off whatever the current tip is).
"""
from __future__ import annotations

from typing import Sequence, Union

revision: str = "057_seal_tip"
down_revision: Union[str, Sequence[str], None] = "056_clean_emr_pid_floats"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """No-op sealing revision."""
    pass


def downgrade() -> None:
    """No-op."""
    pass
