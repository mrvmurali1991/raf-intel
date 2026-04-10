"""
MySQL connection pools for OpenEMR and RAF Intelligence databases.

Both pools use mysql-connector-python's built-in pooling so connections
are reused across requests without holding a persistent socket open.

Dynamic pools (see ``dynamic_db_cursor``) support arbitrary external EMR
databases discovered at runtime.  They are cached in ``_dynamic_pools`` up
to ``_MAX_DYNAMIC_POOLS`` entries; the oldest entry is evicted when the
cache is full.
"""
from __future__ import annotations

import hashlib
import logging
import os
import ssl
import threading
import time
from contextlib import contextmanager
from typing import Generator

import mysql.connector
from mysql.connector.pooling import MySQLConnectionPool

from app.config import settings

logger = logging.getLogger(__name__)

_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "20"))

# ---------------------------------------------------------------------------
# Pool singletons – created once, protected by a lock for thread safety
# ---------------------------------------------------------------------------

_openemr_pool: MySQLConnectionPool | None = None
_raf_pool: MySQLConnectionPool | None = None
_pool_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Dynamic pool cache — keyed by a hash of (host, port, database, user)
# ---------------------------------------------------------------------------

_dynamic_pools: dict[str, MySQLConnectionPool] = {}
_dynamic_pool_lock = threading.Lock()
# Ordered insertion is guaranteed in Python 3.7+ dicts; we rely on this for
# oldest-first eviction.
_MAX_DYNAMIC_POOLS = 20


def _build_ssl_context() -> ssl.SSLContext | None:
    """Build an SSL context for MySQL connections.

    Returns ``None`` when ``DB_SSL_ENABLED`` is not set, which keeps the
    existing behaviour for local/development environments.

    When a CA certificate path is provided via ``DB_SSL_CA`` the server
    certificate is verified against that CA.  Without a CA cert the context
    still enforces TLS but skips certificate verification – acceptable for
    self-signed setups where confidentiality is the goal rather than server
    identity.
    """
    if not settings.db_ssl_enabled:
        return None

    ssl_ctx = ssl.create_default_context()

    ca_cert = settings.db_ssl_ca
    if ca_cert:
        ssl_ctx.load_verify_locations(ca_cert)
    else:
        # No CA provided.
        if settings.app_env != "development":
            raise RuntimeError(
                "FATAL: DB_SSL_ENABLED is set but DB_SSL_CA is not provided. "
                "Refusing to connect without certificate verification in production. "
                "Set DB_SSL_CA to the path of your CA certificate, or disable SSL "
                "with DB_SSL_ENABLED=false (not recommended for production)."
            )
        # Development only: encrypt the channel but skip certificate verification.
        # This allows self-signed certificates in local environments.
        logger.warning(
            "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!\n"
            "WARNING: DB_SSL_CA is not set – connecting with ssl.CERT_NONE.\n"
            "Server certificate will NOT be verified. This is only acceptable\n"
            "in development. Set DB_SSL_CA before deploying to production.\n"
            "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
        )
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE

    return ssl_ctx


def _build_openemr_pool() -> MySQLConnectionPool:
    ssl_ctx = _build_ssl_context()
    kwargs: dict = dict(
        pool_name="openemr_pool",
        pool_size=_POOL_SIZE,
        pool_reset_session=True,
        host=settings.openemr_db_host,
        port=settings.openemr_db_port,
        user=settings.openemr_db_user,
        password=settings.openemr_db_password,
        database=settings.openemr_db_name,
        charset="utf8mb4",
        collation="utf8mb4_unicode_ci",
        connect_timeout=10,
    )
    if ssl_ctx:
        kwargs["ssl_context"] = ssl_ctx
    return MySQLConnectionPool(**kwargs)


def _build_raf_pool() -> MySQLConnectionPool:
    ssl_ctx = _build_ssl_context()
    kwargs: dict = dict(
        pool_name="raf_pool",
        pool_size=_POOL_SIZE,
        pool_reset_session=True,
        host=settings.raf_db_host,
        port=settings.raf_db_port,
        user=settings.raf_db_user,
        password=settings.raf_db_password,
        database=settings.raf_db_name,
        charset="utf8mb4",
        collation="utf8mb4_unicode_ci",
        connect_timeout=10,
    )
    if ssl_ctx:
        kwargs["ssl_context"] = ssl_ctx
    return MySQLConnectionPool(**kwargs)


def get_openemr_pool() -> MySQLConnectionPool:
    global _openemr_pool
    if _openemr_pool is None:
        with _pool_lock:
            if _openemr_pool is None:
                _openemr_pool = _build_openemr_pool()
    return _openemr_pool


def get_raf_pool() -> MySQLConnectionPool:
    global _raf_pool
    if _raf_pool is None:
        with _pool_lock:
            if _raf_pool is None:
                _raf_pool = _build_raf_pool()
    return _raf_pool


# ---------------------------------------------------------------------------
# Context-manager helpers used throughout the app
# ---------------------------------------------------------------------------

@contextmanager
def _db_cursor(pool_fn, dictionary: bool = True) -> Generator:
    """Shared implementation — acquire a connection from *pool_fn*, yield a
    cursor, commit on success, rollback on exception, and always close both
    the cursor and the connection."""
    pool = pool_fn()
    conn = pool.get_connection()
    cursor = None
    try:
        cursor = conn.cursor(dictionary=dictionary)
        yield cursor
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        if cursor is not None:
            cursor.close()
        conn.close()


class NoActiveEMRConnection(Exception):
    """Raised when no active direct_db EMR connection is configured."""


@contextmanager
def openemr_cursor(dictionary: bool = True) -> Generator:
    """Yield a cursor from the active EMR connection configured via the UI.

    Checks the ``emr_connections`` table for an active ``direct_db`` row.
    If none exists, falls back to the direct OpenEMR pool configured via
    environment variables (OPENEMR_DB_*).  This ensures the dashboard and
    reports work out-of-the-box while the UI still shows a 'No EMR Connected'
    banner encouraging explicit configuration.
    """
    # Lazy import to avoid circular dependency at module load
    from app.services.emr_manager import get_active_direct_db_credentials

    creds = get_active_direct_db_credentials()
    if creds is None:
        # Fallback to the direct OpenEMR pool configured via env vars.
        # This keeps the app functional before the user configures an
        # EMR connection through the UI.
        logger.debug(
            "No UI-configured EMR connection found — falling back to "
            "direct OpenEMR pool (env vars)."
        )
        with _db_cursor(get_openemr_pool, dictionary=dictionary) as cursor:
            yield cursor
        return
    with dynamic_db_cursor(
        host=creds["db_host"],
        port=int(creds.get("db_port") or 3306),
        database=creds["db_name"],
        user=creds["db_user"],
        password=creds.get("db_password") or "",
        db_type=creds.get("db_type", "mysql"),
        dictionary=dictionary,
    ) as cursor:
        yield cursor


@contextmanager
def raf_cursor(dictionary: bool = True) -> Generator:
    """Yield a cursor from the RAF Intelligence connection pool."""
    with _db_cursor(get_raf_pool, dictionary=dictionary) as cursor:
        yield cursor


# ---------------------------------------------------------------------------
# Health-check helper
# ---------------------------------------------------------------------------

def check_connections() -> dict[str, bool]:
    """Try to ping both databases and return status dict."""
    status: dict[str, bool] = {}
    for label, pool_fn in [("openemr", get_openemr_pool), ("raf", get_raf_pool)]:
        conn = None
        try:
            pool = pool_fn()
            conn = pool.get_connection()
            conn.ping(reconnect=True)
            status[label] = True
        except Exception as exc:
            logger.warning("DB health-check failed for %s: %s", label, exc)
            status[label] = False
        finally:
            if conn is not None:
                conn.close()
    return status


# ---------------------------------------------------------------------------
# Dynamic pool helpers for multi-EMR support
# ---------------------------------------------------------------------------

def _dynamic_pool_key(host: str, port: int, database: str, user: str) -> str:
    """Return a stable, opaque cache key for the given connection identity.

    The password is intentionally excluded so the key is safe to log.
    """
    raw = f"{host}:{port}:{database}:{user}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _get_or_create_dynamic_pool(
    host: str,
    port: int,
    database: str,
    user: str,
    password: str,
    ssl_enabled: bool = False,
) -> MySQLConnectionPool:
    """Return a cached pool, creating one if necessary.

    Must be called with ``_dynamic_pool_lock`` already held.
    """
    key = _dynamic_pool_key(host, port, database, user)

    if key in _dynamic_pools:
        return _dynamic_pools[key]

    # Evict the oldest entry when the cache is full.
    if len(_dynamic_pools) >= _MAX_DYNAMIC_POOLS:
        oldest_key = next(iter(_dynamic_pools))
        evicted = _dynamic_pools.pop(oldest_key)
        logger.warning(
            "Dynamic pool cache full (%d/%d) — evicted oldest pool: %s",
            len(_dynamic_pools) + 1,
            _MAX_DYNAMIC_POOLS,
            oldest_key[:12],
        )
        # mysql-connector pools do not expose a formal shutdown method, but
        # removing our reference allows GC to reclaim it.
        del evicted

    ssl_ctx: ssl.SSLContext | None = None
    if ssl_enabled:
        ssl_ctx = ssl.create_default_context()
        from app.config import settings  # local import to avoid circular deps

        if settings.app_env == "production":
            # In production require at minimum CERT_OPTIONAL so the TLS
            # handshake still completes against self-signed certs that lack a
            # trusted CA, but hostname verification is enforced when a CA bundle
            # is present.  If settings.db_ssl_ca is set, full CERT_REQUIRED is
            # used instead.
            if settings.db_ssl_ca:
                ssl_ctx.load_verify_locations(cafile=settings.db_ssl_ca)
                ssl_ctx.verify_mode = ssl.CERT_REQUIRED
                ssl_ctx.check_hostname = True
                logger.info(
                    "Dynamic pool for %s:%s/%s created with CERT_REQUIRED "
                    "(CA: %s).",
                    host,
                    port,
                    database,
                    settings.db_ssl_ca,
                )
            else:
                ssl_ctx.check_hostname = False
                ssl_ctx.verify_mode = ssl.CERT_OPTIONAL
                logger.warning(
                    "Dynamic pool for %s:%s/%s created with CERT_OPTIONAL. "
                    "Set DB_SSL_CA to enable full certificate verification.",
                    host,
                    port,
                    database,
                )
        else:
            # Development/staging: CERT_NONE is acceptable for local or
            # self-signed instances, but log a clear warning so this never
            # goes unnoticed if the environment variable is misconfigured.
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl.CERT_NONE
            logger.warning(
                "Dynamic pool for %s:%s/%s created with ssl.CERT_NONE "
                "(env=%s). Certificate verification is DISABLED — "
                "do not use this configuration in production.",
                host,
                port,
                database,
                settings.app_env,
            )

    # Use a short, deterministic pool name derived from the key so that
    # mysql-connector's internal registry stays collision-free.
    pool_name = f"dyn_{key[:12]}"

    kwargs: dict = dict(
        pool_name=pool_name,
        pool_size=5,  # Smaller than main pools — dynamic connections are transient.
        pool_reset_session=True,
        host=host,
        port=port,
        user=user,
        password=password,
        database=database,
        charset="utf8mb4",
        collation="utf8mb4_unicode_ci",
        connect_timeout=10,
    )
    if ssl_ctx:
        kwargs["ssl_context"] = ssl_ctx

    pool = MySQLConnectionPool(**kwargs)
    _dynamic_pools[key] = pool
    logger.debug(
        "Created dynamic pool '%s' for %s:%s/%s (cache size: %d)",
        pool_name,
        host,
        port,
        database,
        len(_dynamic_pools),
    )
    return pool


@contextmanager
def dynamic_db_cursor(
    host: str,
    port: int,
    database: str,
    user: str,
    password: str,
    db_type: str = "mysql",
    ssl_enabled: bool = False,
    dictionary: bool = True,
) -> Generator:
    """Yield a cursor connected to an arbitrary external database.

    Pools are cached by (host, port, database, user) so repeated calls for
    the same connection details reuse an existing pool rather than creating a
    new one on every request.

    The commit/rollback/close lifecycle mirrors ``_db_cursor``.

    Args:
        host: Database server hostname or IP address.
        port: TCP port the server is listening on.
        database: Schema/database name to connect to.
        user: Database username.
        password: Database password.
        db_type: Database engine; currently only ``"mysql"`` is supported.
            ``"postgresql"`` is planned — see TODO(multi-db) below.
        ssl_enabled: When ``True``, wrap the connection in TLS.  Certificate
            verification is skipped for dynamic connections (see
            ``_get_or_create_dynamic_pool``).
        dictionary: When ``True`` (default), rows are returned as dicts.
    """
    if db_type == "postgresql":
        # TODO(multi-db): Add psycopg2 (or psycopg3) support for PostgreSQL
        #   dynamic connections. Use psycopg2.pool.ThreadedConnectionPool with
        #   the same cache/eviction strategy as MySQL pools. Maintain a separate
        #   ``_dynamic_pg_pools`` dict to avoid mixing connector types. Requires
        #   adding psycopg2-binary to dependencies.
        raise NotImplementedError(
            "PostgreSQL dynamic connections are not yet supported. "
            "psycopg2 support is planned in a future release."
        )

    if db_type != "mysql":
        raise ValueError(f"Unsupported db_type: {db_type!r}. Only 'mysql' is supported.")

    with _dynamic_pool_lock:
        pool = _get_or_create_dynamic_pool(
            host=host,
            port=port,
            database=database,
            user=user,
            password=password,
            ssl_enabled=ssl_enabled,
        )

    conn = None
    cursor = None
    try:
        conn = pool.get_connection()
        cursor = conn.cursor(dictionary=dictionary)
        yield cursor
        conn.commit()
    except Exception:
        if conn is not None:
            conn.rollback()
        raise
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


def test_db_connection(
    host: str,
    port: int,
    database: str,
    user: str,
    password: str,
    db_type: str = "mysql",
    ssl_enabled: bool = False,
) -> tuple[bool, str, int]:
    """Verify that a database is reachable and accepting queries.

    Executes ``SELECT 1`` against the target database and measures round-trip
    latency.  This intentionally uses a direct (non-pooled) connection so that
    pool state is not affected by a failed connectivity test.

    Args:
        host: Database server hostname or IP address.
        port: TCP port the server is listening on.
        database: Schema/database name.
        user: Database username.
        password: Database password.
        db_type: Database engine (``"mysql"`` only for now).
        ssl_enabled: Whether to attempt a TLS connection.

    Returns:
        A three-tuple of ``(success, message, latency_ms)`` where:
        - ``success`` is ``True`` when the query completed without error.
        - ``message`` is a human-readable status string.
        - ``latency_ms`` is the round-trip time in milliseconds (0 on failure).
    """
    if db_type == "postgresql":
        # TODO(multi-db): Implement psycopg2-based connectivity test for PostgreSQL.
        #   Mirror the MySQL test below using psycopg2.connect() with a SELECT 1 query.
        return False, "PostgreSQL connectivity test is not yet implemented.", 0

    if db_type != "mysql":
        return False, f"Unsupported db_type: {db_type!r}. Only 'mysql' is supported.", 0

    ssl_ctx: ssl.SSLContext | None = None
    if ssl_enabled:
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE

    conn = None
    cursor = None
    start = time.monotonic()
    try:
        kwargs: dict = dict(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
            charset="utf8mb4",
            collation="utf8mb4_unicode_ci",
            connect_timeout=10,
        )
        if ssl_ctx:
            kwargs["ssl_context"] = ssl_ctx

        conn = mysql.connector.connect(**kwargs)
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        cursor.fetchone()
        latency_ms = int((time.monotonic() - start) * 1000)
        return True, f"Connection successful ({latency_ms} ms)", latency_ms
    except mysql.connector.Error as exc:
        latency_ms = int((time.monotonic() - start) * 1000)
        logger.debug("test_db_connection failed for %s:%s/%s: %s", host, port, database, exc)
        return False, f"Connection failed: {exc.msg}", 0
    except Exception as exc:  # pragma: no cover — unexpected errors
        logger.debug("test_db_connection unexpected error for %s:%s/%s: %s", host, port, database, exc)
        return False, f"Unexpected error: {exc}", 0
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


def close_dynamic_pool(host: str, port: int, database: str, user: str) -> None:
    """Remove a specific dynamic pool from the cache.

    Call this when a saved EMR connection is deleted so that stale pool
    objects are not held in memory indefinitely.  The pool is removed under
    the lock; any in-flight connections that were already acquired from the
    pool will complete normally — only new acquisitions are prevented.

    Args:
        host: Database server hostname or IP address used when the pool was
            created.
        port: TCP port used when the pool was created.
        database: Schema/database name used when the pool was created.
        user: Database username used when the pool was created.
    """
    key = _dynamic_pool_key(host, port, database, user)
    with _dynamic_pool_lock:
        pool = _dynamic_pools.pop(key, None)
    if pool is not None:
        logger.debug(
            "Removed dynamic pool for %s:%s/%s from cache (remaining: %d)",
            host,
            port,
            database,
            len(_dynamic_pools),
        )
    else:
        logger.debug(
            "close_dynamic_pool called for %s:%s/%s but no pool was cached.",
            host,
            port,
            database,
        )
