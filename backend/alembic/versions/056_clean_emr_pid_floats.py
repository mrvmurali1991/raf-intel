"""Strip trailing ``.0`` from patients.emr_pid (legacy auto_sync float→str bug).

Revision ID: 056_clean_emr_pid_floats
Revises: 055_widen_permission_enum
Create Date: 2026-05-23

The old auto_sync code stored numeric emr_pid via Python `str(float_val)`,
producing values like ``"35.0"`` instead of ``"35"``. Downstream code
worked around this with `int(float(_raw))` in pipeline_chain and
celery_tasks, but the underlying string-with-dot rows still trip up
joins and previsit_briefing which calls `int(emr_pid)` directly
(ValueError: invalid literal for int()).

This migration normalises the column in-place and is idempotent.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "056_clean_emr_pid_floats"
down_revision: Union[str, Sequence[str], None] = "055_widen_permission_enum"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Strip ``.0`` suffix on all emr_pids — TRIM(TRAILING) is idempotent.
    op.execute(sa.text(
        "UPDATE patients "
        "SET emr_pid = TRIM(TRAILING '.0' FROM emr_pid) "
        "WHERE emr_pid LIKE '%.0'"
    ))


def downgrade() -> None:
    """No-op — re-appending '.0' would re-break the joins."""
    pass
