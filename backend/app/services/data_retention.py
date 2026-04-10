"""
HIPAA-compliant data retention and purge service.

Default retention periods (configurable via env vars):
- Audit logs: 6 years (HIPAA minimum)
- Analysis results: 3 years
- Sync logs: 1 year
- Session data: 30 days
- Job records: 90 days
- Uploaded documents: 3 years
- Webhook delivery logs: 90 days
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.db import raf_cursor

# ---------------------------------------------------------------------------
# SQL identifier validation
# ---------------------------------------------------------------------------

_SAFE_IDENTIFIER = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]{0,63}$')


def _safe_id(name: str) -> str:
    """Validate that *name* is a safe SQL identifier (no injection risk)."""
    if not _SAFE_IDENTIFIER.match(name):
        raise ValueError(f"Invalid SQL identifier: {name!r}")
    return name

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Policy dataclass
# ---------------------------------------------------------------------------


@dataclass
class RetentionPolicy:
    """Describes a single table's data retention configuration."""

    table_name: str
    retention_days: int
    date_column: str
    description: str

    def with_override(self, retention_days: int) -> "RetentionPolicy":
        """Return a copy of this policy with an overridden retention period."""
        return RetentionPolicy(
            table_name=self.table_name,
            retention_days=retention_days,
            date_column=self.date_column,
            description=self.description,
        )


# ---------------------------------------------------------------------------
# Default policies
# ---------------------------------------------------------------------------

DEFAULT_POLICIES: list[RetentionPolicy] = [
    RetentionPolicy(
        table_name="audit_log",
        retention_days=int(os.getenv("RETENTION_AUDIT_LOG_DAYS", "2190")),  # 6 years
        date_column="created_at",
        description="HIPAA audit log — minimum 6-year retention required",
    ),
    RetentionPolicy(
        table_name="raf_encounter_analysis",
        retention_days=int(os.getenv("RETENTION_ANALYSIS_DAYS", "1095")),  # 3 years
        date_column="created_at",
        description="RAF encounter analysis results",
    ),
    RetentionPolicy(
        table_name="emr_sync_log",
        retention_days=int(os.getenv("RETENTION_SYNC_LOG_DAYS", "365")),  # 1 year
        date_column="created_at",
        description="EMR synchronisation operation logs",
    ),
    RetentionPolicy(
        table_name="user_sessions",
        retention_days=int(os.getenv("RETENTION_SESSIONS_DAYS", "30")),  # 30 days
        date_column="created_at",
        description="User session tokens (expired / logged-out)",
    ),
    RetentionPolicy(
        table_name="raf_jobs",
        retention_days=int(os.getenv("RETENTION_JOBS_DAYS", "90")),  # 90 days
        date_column="created_at",
        description="Background job records",
    ),
    RetentionPolicy(
        table_name="webhook_deliveries",
        retention_days=int(os.getenv("RETENTION_WEBHOOK_DAYS", "90")),  # 90 days
        date_column="delivered_at",
        description="Webhook delivery attempt logs",
    ),
    RetentionPolicy(
        table_name="documents",
        retention_days=int(os.getenv("RETENTION_DOCUMENTS_DAYS", "1095")),  # 3 years
        date_column="uploaded_at",
        description="Uploaded patient document records",
    ),
]

# ---------------------------------------------------------------------------
# Runtime overrides — populated by update_retention_policy()
# ---------------------------------------------------------------------------

_policy_overrides: dict[str, int] = {}


def _effective_policies() -> list[RetentionPolicy]:
    """Return DEFAULT_POLICIES with any runtime overrides applied."""
    return [
        p.with_override(_policy_overrides[p.table_name])
        if p.table_name in _policy_overrides
        else p
        for p in DEFAULT_POLICIES
    ]


# ---------------------------------------------------------------------------
# Core operations
# ---------------------------------------------------------------------------


def run_retention_sweep() -> dict[str, Any]:
    """
    Iterate every retention policy and DELETE rows older than the configured
    retention period.

    Returns a summary dict with per-table deleted row counts and a grand total.
    Only runs when DATA_RETENTION_ENABLED is truthy (default: true).
    """
    if not _retention_enabled():
        logger.info("Data retention sweep skipped — DATA_RETENTION_ENABLED is false")
        return {"enabled": False, "tables_processed": 0, "total_deleted": 0}

    policies = _effective_policies()
    results: dict[str, int] = {}
    total_deleted = 0
    sweep_start = datetime.now(timezone.utc)

    logger.info("Starting data retention sweep (%d policies)", len(policies))

    for policy in policies:
        deleted = _purge_table(policy)
        results[policy.table_name] = deleted
        total_deleted += deleted

    elapsed_ms = int((datetime.now(timezone.utc) - sweep_start).total_seconds() * 1000)
    logger.info(
        "Retention sweep complete: %d rows deleted across %d tables in %d ms",
        total_deleted,
        len(policies),
        elapsed_ms,
    )

    return {
        "enabled": True,
        "swept_at": sweep_start.isoformat(),
        "elapsed_ms": elapsed_ms,
        "tables_processed": len(policies),
        "total_deleted": total_deleted,
        "by_table": results,
    }


def _purge_table(policy: RetentionPolicy) -> int:
    """
    DELETE rows from *policy.table_name* older than *policy.retention_days*.

    Returns the number of deleted rows.  Swallows per-table errors so that a
    missing table (e.g. during initial setup) does not abort the full sweep.
    """
    try:
        with raf_cursor() as cur:
            # Verify the table exists before issuing DELETE to avoid noisy errors
            # on fresh installs where not all tables are present yet.
            cur.execute(
                "SELECT COUNT(*) AS cnt FROM information_schema.tables "
                "WHERE table_schema = DATABASE() AND table_name = %s",
                (policy.table_name,),
            )
            row = cur.fetchone()
            if not row or row["cnt"] == 0:
                logger.debug(
                    "Retention sweep skipping '%s' — table does not exist",
                    policy.table_name,
                )
                return 0

            # Verify the date column exists before attempting purge.
            cur.execute(
                "SELECT COUNT(*) AS cnt FROM information_schema.columns "
                "WHERE table_schema = DATABASE() AND table_name = %s AND column_name = %s",
                (policy.table_name, policy.date_column),
            )
            col_row = cur.fetchone()
            if not col_row or col_row["cnt"] == 0:
                logger.debug(
                    "Retention sweep skipping '%s' — column '%s' does not exist",
                    policy.table_name,
                    policy.date_column,
                )
                return 0

            cur.execute(
                f"DELETE FROM `{_safe_id(policy.table_name)}` "
                f"WHERE `{_safe_id(policy.date_column)}` < NOW() - INTERVAL %s DAY",
                (policy.retention_days,),
            )
            deleted: int = cur.rowcount

        if deleted:
            logger.info(
                "Retention purge: deleted %d rows from '%s' (policy: %d days on '%s')",
                deleted,
                policy.table_name,
                policy.retention_days,
                policy.date_column,
            )
        else:
            logger.debug(
                "Retention purge: no eligible rows in '%s'",
                policy.table_name,
            )
        return deleted

    except Exception as exc:
        logger.error(
            "Retention purge failed for table '%s': %s",
            policy.table_name,
            exc,
            exc_info=True,
        )
        return 0


def get_retention_status() -> list[dict[str, Any]]:
    """
    For every configured policy return a status dict with:
    - table_name
    - retention_days
    - date_column
    - description
    - total_rows         — total rows in table (None if table missing)
    - oldest_record_date — ISO timestamp of the oldest row (None if empty/missing)
    - eligible_for_purge — rows older than retention_days
    - overridden         — True when a runtime override is active
    """
    policies = _effective_policies()
    statuses: list[dict[str, Any]] = []

    for policy in policies:
        status: dict[str, Any] = {
            "table_name": policy.table_name,
            "retention_days": policy.retention_days,
            "date_column": policy.date_column,
            "description": policy.description,
            "overridden": policy.table_name in _policy_overrides,
            "total_rows": None,
            "oldest_record_date": None,
            "eligible_for_purge": None,
        }

        try:
            with raf_cursor() as cur:
                # Check table existence
                cur.execute(
                    "SELECT COUNT(*) AS cnt FROM information_schema.tables "
                    "WHERE table_schema = DATABASE() AND table_name = %s",
                    (policy.table_name,),
                )
                row = cur.fetchone()
                if not row or row["cnt"] == 0:
                    status["total_rows"] = 0
                    status["oldest_record_date"] = None
                    status["eligible_for_purge"] = 0
                    statuses.append(status)
                    continue

                # Total rows
                cur.execute(f"SELECT COUNT(*) AS cnt FROM `{_safe_id(policy.table_name)}`")
                status["total_rows"] = cur.fetchone()["cnt"]

                # Oldest record
                cur.execute(
                    f"SELECT MIN(`{_safe_id(policy.date_column)}`) AS oldest "
                    f"FROM `{_safe_id(policy.table_name)}`"
                )
                oldest = cur.fetchone()["oldest"]
                if oldest:
                    if isinstance(oldest, datetime):
                        status["oldest_record_date"] = oldest.isoformat()
                    else:
                        status["oldest_record_date"] = str(oldest)
                else:
                    status["oldest_record_date"] = None

                # Eligible for purge
                cur.execute(
                    f"SELECT COUNT(*) AS cnt FROM `{_safe_id(policy.table_name)}` "
                    f"WHERE `{_safe_id(policy.date_column)}` < NOW() - INTERVAL %s DAY",
                    (policy.retention_days,),
                )
                status["eligible_for_purge"] = cur.fetchone()["cnt"]

        except Exception as exc:
            logger.error(
                "Failed to get retention status for '%s': %s",
                policy.table_name,
                exc,
            )
            status["error"] = str(exc)

        statuses.append(status)

    return statuses


def update_retention_policy(table_name: str, retention_days: int) -> RetentionPolicy:
    """
    Override the retention period for *table_name* at runtime.

    The new value is stored in-process (_policy_overrides) and takes effect
    immediately for the next sweep.  It does not persist across restarts —
    set the appropriate env var for persistent configuration.

    Args:
        table_name:     Must match a table in DEFAULT_POLICIES.
        retention_days: Must be a positive integer.

    Returns:
        The updated RetentionPolicy.

    Raises:
        ValueError: When table_name is not in DEFAULT_POLICIES or
                    retention_days is not a positive integer.
    """
    known_tables = {p.table_name for p in DEFAULT_POLICIES}
    if table_name not in known_tables:
        raise ValueError(
            f"Unknown table '{table_name}'. "
            f"Known tables: {sorted(known_tables)}"
        )

    if not isinstance(retention_days, int) or retention_days < 1:
        raise ValueError(
            f"retention_days must be a positive integer, got {retention_days!r}"
        )

    _policy_overrides[table_name] = retention_days
    logger.info(
        "Retention policy override set: table='%s', retention_days=%d",
        table_name,
        retention_days,
    )

    # Return the effective policy for this table
    for p in DEFAULT_POLICIES:
        if p.table_name == table_name:
            return p.with_override(retention_days)

    # Unreachable — we validated above — but satisfies type checker
    raise ValueError(f"Table '{table_name}' not found after validation")  # pragma: no cover


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _retention_enabled() -> bool:
    return os.getenv("DATA_RETENTION_ENABLED", "true").lower() not in ("0", "false", "no")
