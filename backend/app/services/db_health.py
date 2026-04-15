"""
Database health monitoring service.

Provides three metrics that are surfaced through the /api/health/db endpoint:

1. Connection pool utilisation
   mysql-connector-python does not expose pool internals directly, so we
   approximate utilisation by attempting a non-blocking connection acquire and
   measuring whether the pool is saturated.

2. Slow query counter
   Queries the MySQL ``information_schema.processlist`` for long-running
   queries (> SLOW_QUERY_THRESHOLD_SEC seconds).  Requires the connecting
   user to have the PROCESS privilege.

3. Replication lag (read replica only)
   When DB_READ_HOST is configured, issues ``SHOW REPLICA STATUS`` (or the
   older ``SHOW SLAVE STATUS`` alias) against the replica and returns
   ``Seconds_Behind_Source`` / ``Seconds_Behind_Master``.

All three checks are intentionally defensive: they log warnings but never
raise so the endpoint always returns a valid JSON body.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)

# Queries running longer than this many seconds are counted as slow.
SLOW_QUERY_THRESHOLD_SEC: int = int(os.getenv("SLOW_QUERY_THRESHOLD_SEC", "5"))

# Replication lag threshold in seconds that causes the replica check to be
# flagged as degraded (not an error, just a warning flag in the response).
REPLICATION_LAG_WARN_SEC: int = int(os.getenv("REPLICATION_LAG_WARN_SEC", "30"))


def _pool_utilisation() -> dict[str, Any]:
    """Approximate utilisation of the primary RAF connection pool.

    mysql-connector-python does not expose free/used connection counts, so
    we attempt to acquire a connection with a zero timeout.  If that raises
    ``PoolError`` the pool is fully utilised.  The absolute count returned is
    therefore either 0 (got a connection) or pool_size (all connections busy).
    """
    from app.db import get_raf_pool, _POOL_SIZE

    result: dict[str, Any] = {
        "pool_size": _POOL_SIZE,
        "status": "ok",
        "note": "",
    }
    conn = None
    try:
        start = time.monotonic()
        pool = get_raf_pool()
        conn = pool.get_connection()
        latency_ms = int((time.monotonic() - start) * 1000)
        result["latency_ms"] = latency_ms
        result["status"] = "ok"
    except Exception as exc:
        result["status"] = "saturated"
        result["note"] = str(exc)[:200]
        logger.warning("db_health: pool utilisation check failed: %s", exc)
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
    return result


def _slow_query_count() -> dict[str, Any]:
    """Count queries running longer than SLOW_QUERY_THRESHOLD_SEC seconds.

    Requires the PROCESS privilege.  Returns count=0 and a warning note
    if the query fails (e.g. insufficient privileges).
    """
    from app.db import raf_cursor

    result: dict[str, Any] = {
        "threshold_sec": SLOW_QUERY_THRESHOLD_SEC,
        "count": 0,
        "status": "ok",
    }
    try:
        with raf_cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS cnt FROM information_schema.PROCESSLIST "
                "WHERE TIME > %s AND COMMAND != 'Sleep'",
                (SLOW_QUERY_THRESHOLD_SEC,),
            )
            row = cur.fetchone()
            count = int(row["cnt"]) if row else 0
        result["count"] = count
        if count > 0:
            result["status"] = "warn"
            logger.warning("db_health: %d slow queries detected (>%ds)", count, SLOW_QUERY_THRESHOLD_SEC)
    except Exception as exc:
        result["status"] = "unavailable"
        result["note"] = str(exc)[:200]
        logger.warning("db_health: slow query check failed: %s", exc)
    return result


def _replication_lag() -> dict[str, Any] | None:
    """Check replica replication lag via SHOW REPLICA STATUS.

    Returns None when no read replica is configured (DB_READ_HOST not set).
    Returns a dict with ``lag_seconds`` and ``status`` otherwise.
    """
    from app.db import _DB_READ_HOST, get_raf_read_pool, get_raf_pool

    if not _DB_READ_HOST:
        return None

    result: dict[str, Any] = {
        "replica_host": _DB_READ_HOST,
        "lag_seconds": None,
        "status": "ok",
    }
    conn = None
    cursor = None
    try:
        pool = get_raf_read_pool()
        conn = pool.get_connection()
        cursor = conn.cursor(dictionary=True)
        # MySQL 8.0.22+ uses SHOW REPLICA STATUS; older versions use SHOW SLAVE STATUS.
        try:
            cursor.execute("SHOW REPLICA STATUS")
        except Exception:
            cursor.execute("SHOW SLAVE STATUS")  # noqa: S603 — legacy alias
        row = cursor.fetchone()
        if row is None:
            result["status"] = "not_a_replica"
            result["note"] = "SHOW REPLICA STATUS returned no rows"
            return result
        # MySQL 8.0.22+ uses Seconds_Behind_Source; older uses Seconds_Behind_Master.
        lag = row.get("Seconds_Behind_Source") or row.get("Seconds_Behind_Master")
        if lag is None:
            result["status"] = "io_thread_stopped"
            result["note"] = "Replica IO thread may be stopped"
        else:
            result["lag_seconds"] = int(lag)
            if int(lag) > REPLICATION_LAG_WARN_SEC:
                result["status"] = "warn"
                logger.warning(
                    "db_health: replication lag %ds exceeds threshold %ds",
                    int(lag),
                    REPLICATION_LAG_WARN_SEC,
                )
    except Exception as exc:
        result["status"] = "unavailable"
        result["note"] = str(exc)[:200]
        logger.warning("db_health: replication lag check failed: %s", exc)
    finally:
        if cursor is not None:
            try:
                cursor.close()
            except Exception:
                pass
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
    return result


def get_db_health() -> dict[str, Any]:
    """Aggregate all DB health metrics into a single response dict.

    Always returns a valid dict — individual check failures are captured as
    error fields inside each sub-key so the endpoint never returns 500.

    Returns:
        {
            "status":      "ok" | "warn" | "degraded",
            "pool":        { ... },
            "slow_queries": { ... },
            "replication": { ... } | null,
            "checked_at":  "<iso8601>",
        }
    """
    from datetime import datetime, timezone

    pool_info = _pool_utilisation()
    slow_info = _slow_query_count()
    repl_info = _replication_lag()

    # Derive overall status from sub-checks.
    statuses = [pool_info.get("status"), slow_info.get("status")]
    if repl_info:
        statuses.append(repl_info.get("status"))

    if "saturated" in statuses or "unavailable" in statuses or "io_thread_stopped" in statuses:
        overall = "degraded"
    elif "warn" in statuses:
        overall = "warn"
    else:
        overall = "ok"

    return {
        "status": overall,
        "pool": pool_info,
        "slow_queries": slow_info,
        "replication": repl_info,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
