"""
Role-based access control: permission checks, RBAC seeding, and per-user overrides.
"""
from __future__ import annotations

import logging
from typing import Any

from app.db import raf_cursor

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Default role permissions (seeded once at startup)
# ---------------------------------------------------------------------------

_DEFAULT_PERMS: list[tuple[str, str, str]] = [
    # admin – full access
    ("admin", "patients", "read"), ("admin", "patients", "write"), ("admin", "patients", "delete"),
    ("admin", "raf", "read"), ("admin", "raf", "write"),
    ("admin", "analysis", "read"), ("admin", "analysis", "write"),
    ("admin", "suspects", "read"), ("admin", "suspects", "write"),
    ("admin", "reports", "read"), ("admin", "reports", "write"),
    ("admin", "audit", "read"), ("admin", "audit", "write"),
    ("admin", "providers", "read"), ("admin", "providers", "write"),
    ("admin", "claims", "read"), ("admin", "claims", "write"),
    ("admin", "fhir", "read"), ("admin", "fhir", "write"),
    ("admin", "submissions", "read"), ("admin", "submissions", "write"),
    ("admin", "jobs", "read"), ("admin", "jobs", "write"),
    ("admin", "webhooks", "read"), ("admin", "webhooks", "write"),
    ("admin", "documents", "read"), ("admin", "documents", "write"),
    ("admin", "worklist", "read"), ("admin", "worklist", "write"), ("admin", "worklist", "manage"),
    ("admin", "users", "read"), ("admin", "users", "write"),
    # manager – no user management
    ("manager", "patients", "read"), ("manager", "patients", "write"),
    ("manager", "raf", "read"), ("manager", "raf", "write"),
    ("manager", "analysis", "read"), ("manager", "analysis", "write"),
    ("manager", "suspects", "read"), ("manager", "suspects", "write"),
    ("manager", "reports", "read"), ("manager", "reports", "write"),
    ("manager", "audit", "read"),
    ("manager", "providers", "read"), ("manager", "providers", "write"),
    ("manager", "claims", "read"), ("manager", "claims", "write"),
    ("manager", "fhir", "read"), ("manager", "fhir", "write"),
    ("manager", "submissions", "read"), ("manager", "submissions", "write"),
    ("manager", "jobs", "read"), ("manager", "jobs", "write"),
    ("manager", "webhooks", "read"), ("manager", "webhooks", "write"),
    ("manager", "documents", "read"), ("manager", "documents", "write"),
    ("manager", "worklist", "read"), ("manager", "worklist", "write"), ("manager", "worklist", "manage"),
    # auditor – read-only + audit access
    ("auditor", "patients", "read"), ("auditor", "raf", "read"),
    ("auditor", "analysis", "read"), ("auditor", "suspects", "read"),
    ("auditor", "reports", "read"), ("auditor", "audit", "read"),
    ("auditor", "providers", "read"), ("auditor", "claims", "read"),
    ("auditor", "fhir", "read"), ("auditor", "submissions", "read"),
    ("auditor", "jobs", "read"), ("auditor", "webhooks", "read"),
    ("auditor", "documents", "read"), ("auditor", "worklist", "read"),
    # coder – worklist access + limited clinical read
    ("coder", "worklist", "read"), ("coder", "worklist", "write"),
    ("coder", "patients", "read"), ("coder", "raf", "read"),
    ("coder", "analysis", "read"), ("coder", "suspects", "read"),
    ("coder", "documents", "read"), ("coder", "documents", "write"),
    ("coder", "claims", "read"), ("coder", "providers", "read"),
    ("coder", "reports", "read"),
    # viewer – read-only clinical data
    ("viewer", "patients", "read"), ("viewer", "raf", "read"),
    ("viewer", "analysis", "read"), ("viewer", "suspects", "read"),
    ("viewer", "reports", "read"), ("viewer", "providers", "read"),
    ("viewer", "claims", "read"), ("viewer", "fhir", "read"),
    ("viewer", "submissions", "read"), ("viewer", "jobs", "read"),
    ("viewer", "webhooks", "read"),
]


def seed_default_permissions() -> None:
    """Insert/backfill default role permissions idempotently."""
    with raf_cursor() as cur:
        cur.executemany(
            "INSERT IGNORE INTO role_default_permissions (role, resource, action) VALUES (%s, %s, %s)",
            _DEFAULT_PERMS,
        )


# ---------------------------------------------------------------------------
# Permission queries
# ---------------------------------------------------------------------------

def get_user_permissions(user_id: int, get_user_fn: Any) -> list[dict[str, Any]]:
    """Return effective permissions for a user: role defaults merged with per-user overrides."""
    user = get_user_fn(user_id)
    if not user:
        return []
    role = user["role"]

    with raf_cursor() as cur:
        cur.execute(
            "SELECT resource, action, 1 AS granted FROM role_default_permissions WHERE role = %s",
            (role,),
        )
        role_perms = {(r["resource"], r["action"]): True for r in cur.fetchall()}

        cur.execute(
            "SELECT resource, action, granted FROM user_permissions WHERE user_id = %s",
            (user_id,),
        )
        for r in cur.fetchall():
            role_perms[(r["resource"], r["action"])] = bool(r["granted"])

    return [
        {"resource": res, "action": act, "granted": granted}
        for (res, act), granted in role_perms.items()
    ]


def check_permission(user_id: int, resource: str, action: str, get_user_fn: Any) -> bool:
    """Return True if user has the given resource+action permission."""
    user = get_user_fn(user_id)
    if not user:
        return False

    if user["role"] == "admin":
        return True

    with raf_cursor() as cur:
        cur.execute(
            "SELECT granted FROM user_permissions WHERE user_id = %s AND resource = %s AND action = %s",
            (user_id, resource, action),
        )
        override = cur.fetchone()
        if override is not None:
            return bool(override["granted"])

        cur.execute(
            """
            SELECT COUNT(*) AS cnt FROM role_default_permissions
            WHERE role = %s AND resource = %s AND action = %s
            """,
            (user["role"], resource, action),
        )
        row = cur.fetchone()
        return bool(row and row["cnt"] > 0)


def set_user_permissions(user_id: int, permissions: list[dict[str, Any]]) -> None:
    """Replace all per-user permission overrides."""
    with raf_cursor() as cur:
        cur.execute("DELETE FROM user_permissions WHERE user_id = %s", (user_id,))
        for perm in permissions:
            cur.execute(
                """
                INSERT INTO user_permissions (user_id, resource, action, granted)
                VALUES (%s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE granted = VALUES(granted)
                """,
                (
                    user_id,
                    perm["resource"],
                    perm["action"],
                    1 if perm.get("granted", True) else 0,
                ),
            )
