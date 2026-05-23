"""Merge every dangling alembic head into a single linear tip.

Revision ID: 054_merge_all_heads
Revises: (every head)
Create Date: 2026-05-23

Static analysis of alembic/versions/ showed 11 dangling heads. Running
`alembic upgrade head` on a fresh DB would error with "Multiple head
revisions are present", and `alembic upgrade heads` would silently
produce non-deterministic ordering. This merge collapses all of them.

If a new branch is added in the future, append it to down_revision
rather than chaining off a single existing tip — that keeps history
auditable.
"""
from __future__ import annotations

from typing import Sequence, Union

revision: str = "054_merge_all_heads"
down_revision: Union[str, Sequence[str], None] = (
    "008_add_missing_indexes_and_fks",
    "040_fhir_bulk_exports",
    "043_direct_inbound_tracking",
    "044_hie_queries",
    "045_datavant_requests",
    "046_inovalon_pulls",
    "047_reveleer_sync",
    "051_chart_requests",
    "053_hcc_rejections",
    "2431d3f065b7",
    "77cd8ea4ca45",
    "777f6498bc76",
    "a7dfeec671e1",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """No-op merge — every parent already created its own tables."""
    pass


def downgrade() -> None:
    """No-op — splitting back into many heads would re-introduce the bug."""
    pass
