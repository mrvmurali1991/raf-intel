"""Widen role_default_permissions.resource ENUM with bi_export + forecast.

Revision ID: 058_add_bi_export_forecast_resources
Revises: 057_seal_tip
Create Date: 2026-05-24

Round-14 review surfaced that bi_export.py, bundles.py, forecast.py,
goals.py, edi_generation.py, and dashboard.py endpoints were missing
`require_permission(...)` checks — making PHI-bearing population dumps
and CMS submission generation callable by any authenticated user. The
fix wires those endpoints to existing resource names where possible,
and introduces two new ones ('bi_export', 'forecast') for the cases
that don't fit an existing bucket.

This migration widens the ENUM to include both new resources and seeds
the admin role with read/write rows so the startup coverage check stays
green.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "058_add_bi_export_forecast_resources"
down_revision: Union[str, Sequence[str], None] = "057_seal_tip"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Keep this in sync with backend/app/permission_resources.py.
_RESOURCES = (
    "patients", "encounters", "raf_scores", "suspects", "documents",
    "claims", "fhir", "providers", "audit", "reports", "settings", "users",
    "admin", "adt", "attestations", "care_gaps", "chart_chase", "cohorts",
    "jobs", "meat", "pipeline", "qa_review", "radv", "raf", "recapture",
    "submissions", "webhooks", "worklist",
    "dashboard", "huddle", "qa", "v28", "pre_submission", "quality", "goals",
    "bi_export", "forecast",
)

_ACTIONS = ("read", "write", "delete", "export", "admin", "manage")


def upgrade() -> None:
    enum_resources = ", ".join(f"'{r}'" for r in _RESOURCES)
    enum_actions = ", ".join(f"'{a}'" for a in _ACTIONS)

    op.execute(sa.text(
        f"ALTER TABLE role_default_permissions "
        f"MODIFY COLUMN resource ENUM({enum_resources}) NOT NULL"
    ))
    op.execute(sa.text(
        f"ALTER TABLE role_default_permissions "
        f"MODIFY COLUMN action ENUM({enum_actions}) NOT NULL"
    ))

    insp = sa.inspect(op.get_bind())
    if insp.has_table("user_permissions"):
        op.execute(sa.text(
            f"ALTER TABLE user_permissions "
            f"MODIFY COLUMN resource ENUM({enum_resources}) NOT NULL"
        ))
        op.execute(sa.text(
            f"ALTER TABLE user_permissions "
            f"MODIFY COLUMN action ENUM({enum_actions}) NOT NULL"
        ))

    for resource in ("bi_export", "forecast"):
        for action in ("read", "write"):
            op.execute(sa.text(
                f"INSERT IGNORE INTO role_default_permissions "
                f"(role, resource, action) VALUES "
                f"('admin', '{resource}', '{action}')"
            ))


def downgrade() -> None:
    """No-op — narrowing the ENUM would re-introduce 403s on these endpoints."""
    pass
