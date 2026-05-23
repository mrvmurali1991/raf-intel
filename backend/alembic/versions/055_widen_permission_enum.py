"""Widen role_default_permissions.resource ENUM to cover every resource
string used by `require_permission()`.

Revision ID: 055_widen_permission_enum
Revises: 054_merge_all_heads
Create Date: 2026-05-23

Background:
  The original ENUM only contained 12 values (patients, encounters,
  raf_scores, suspects, documents, claims, fhir, providers, audit, reports,
  settings, users). But `require_permission(...)` is called with 26+
  distinct resource strings across app/routers/. MySQL silently coerced
  the missing strings to '' (empty string), so any clinician role insert
  for `raf`, `worklist`, `attestations`, etc. landed as ('', 'read') —
  which never matches the runtime check `role_default_permissions WHERE
  resource = 'raf'`. Result: every non-admin user hit 403 on those
  endpoints with no error in any log.

This migration widens the ENUM to match the canonical list in
`app/permission_resources.py` and backfills admin role permissions so the
startup coverage check stops warning.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "055_widen_permission_enum"
down_revision: Union[str, Sequence[str], None] = "054_merge_all_heads"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Keep this list in sync with backend/app/permission_resources.py.
_RESOURCES = (
    "patients", "encounters", "raf_scores", "suspects", "documents",
    "claims", "fhir", "providers", "audit", "reports", "settings", "users",
    "admin", "adt", "attestations", "care_gaps", "chart_chase", "cohorts",
    "jobs", "meat", "pipeline", "qa_review", "radv", "raf", "recapture",
    "submissions", "webhooks", "worklist",
    "dashboard", "huddle", "qa", "v28", "pre_submission", "quality", "goals",
)

_ACTIONS = ("read", "write", "delete", "export", "admin", "manage")


def upgrade() -> None:
    enum_resources = ", ".join(f"'{r}'" for r in _RESOURCES)
    enum_actions = ", ".join(f"'{a}'" for a in _ACTIONS)

    # Widen role_default_permissions.resource + action
    op.execute(sa.text(
        f"ALTER TABLE role_default_permissions "
        f"MODIFY COLUMN resource ENUM({enum_resources}) NOT NULL"
    ))
    op.execute(sa.text(
        f"ALTER TABLE role_default_permissions "
        f"MODIFY COLUMN action ENUM({enum_actions}) NOT NULL"
    ))

    # Same widening on user_permissions if it exists (some installs lack it).
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

    # Clean up stale '' rows left by the old too-narrow ENUM and seed admin
    # role with every resource:read so the startup coverage check passes.
    op.execute(sa.text(
        "DELETE FROM role_default_permissions WHERE resource = ''"
    ))
    for resource in _RESOURCES:
        op.execute(sa.text(
            f"INSERT IGNORE INTO role_default_permissions "
            f"(role, resource, action) VALUES ('admin', '{resource}', 'read')"
        ))


def downgrade() -> None:
    """No-op — narrowing the ENUM back would re-introduce the 403 bug."""
    pass
