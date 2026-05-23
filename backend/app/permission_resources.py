"""Canonical list of permission resource names used by `require_permission()`.

Every value here must:
  - be a valid value in the `role_default_permissions.resource` ENUM
  - appear in at least one `require_permission(...)` call site in app/routers/

The startup health check (see `app/main.py`) verifies both directions, so any
drift between the routers, this module, and the DB ENUM raises at boot time
instead of silently 403'ing in production.

When adding a new resource:
  1. Add the string here.
  2. Add a row to `role_default_permissions` for every role that needs it
     (via Alembic migration).
  3. Reference it in the relevant router's `require_permission(...)` call.
"""
from __future__ import annotations

from typing import Final, Literal

ResourceName = Literal[
    "admin",
    "adt",
    "attestations",
    "audit",
    "care_gaps",
    "chart_chase",
    "claims",
    "cohorts",
    "documents",
    "encounters",
    "fhir",
    "jobs",
    "meat",
    "patients",
    "pipeline",
    "providers",
    "qa_review",
    "radv",
    "raf",
    "raf_scores",
    "recapture",
    "reports",
    "submissions",
    "suspects",
    "webhooks",
    "worklist",
    # Resources used by friendly UI names — kept in sync with the ENUM widening
    # in migration 055_widen_permission_enum.py
    "dashboard",
    "huddle",
    "qa",
    "v28",
    "pre_submission",
    "quality",
    "goals",
    "settings",
    "users",
]

# Plain set for runtime membership checks (Literal types are not iterable).
RESOURCE_NAMES: Final[frozenset[str]] = frozenset({
    "admin", "adt", "attestations", "audit", "care_gaps", "chart_chase",
    "claims", "cohorts", "documents", "encounters", "fhir", "jobs", "meat",
    "patients", "pipeline", "providers", "qa_review", "radv", "raf",
    "raf_scores", "recapture", "reports", "submissions", "suspects",
    "webhooks", "worklist", "dashboard", "huddle", "qa", "v28",
    "pre_submission", "quality", "goals", "settings", "users",
})

ACTIONS: Final[frozenset[str]] = frozenset({
    "read", "write", "delete", "export", "admin", "manage",
})
