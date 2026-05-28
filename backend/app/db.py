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

import asyncio
import hashlib
import logging
import os
import ssl
import threading
import time
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from functools import wraps

import mysql.connector
from mysql.connector.pooling import MySQLConnectionPool

from app.config import settings

logger = logging.getLogger(__name__)
_slow_query_logger = logging.getLogger("app.db.slow_queries")

# DB_POOL_SIZE default raised from 20 -> 30 to absorb worker bursts.
# Rationale: the FHIR sync + RAF recompute workers can each open several
# concurrent transactions per patient, and during a multi-tenant resync the
# previous 20-connection cap caused requests to queue behind workers and
# tripped pool-acquisition timeouts.  30 gives ~50% headroom while staying
# well below MySQL's default max_connections=151.  The executor worker count
# (_DB_EXECUTOR_WORKERS below) deliberately mirrors this value so we never
# dispatch more sync DB jobs than the pool can satisfy.
_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "30"))
_SLOW_QUERY_MS = int(os.getenv("SLOW_QUERY_THRESHOLD_MS", "500"))

# ---------------------------------------------------------------------------
# Per-request query counter (thread-local) for N+1 detection
# ---------------------------------------------------------------------------

_query_counter = threading.local()


def reset_query_counter() -> None:
    """Reset the per-request query counter (call at request start)."""
    _query_counter.count = 0
    _query_counter.queries = []


def get_query_count() -> int:
    """Return the number of queries executed in the current request."""
    return getattr(_query_counter, "count", 0)


def get_query_log() -> list[str]:
    """Return truncated SQL for queries in the current request."""
    return getattr(_query_counter, "queries", [])


# ---------------------------------------------------------------------------
# Read-replica and proxy configuration
# ---------------------------------------------------------------------------

# Set DB_READ_HOST to enable a read replica for SELECT-heavy queries.
# If unset, raf_read_cursor() falls back to the primary pool.
_DB_READ_HOST: str | None = os.getenv("DB_READ_HOST")
_DB_READ_PORT: int = int(os.getenv("DB_READ_PORT", "3306"))

# Set DB_PROXY_HOST to route all primary writes through a connection proxy
# (ProxySQL / MySQL Router).  When set, the primary RAF pool will connect
# via the proxy instead of directly to the DB server.
_DB_PROXY_HOST: str | None = os.getenv("DB_PROXY_HOST")
_DB_PROXY_PORT: int = int(os.getenv("DB_PROXY_PORT", "6033"))

# ---------------------------------------------------------------------------
# Pool singletons – created once, protected by a lock for thread safety
# ---------------------------------------------------------------------------

_openemr_pool: MySQLConnectionPool | None = None
_raf_pool: MySQLConnectionPool | None = None
_raf_read_pool: MySQLConnectionPool | None = None
_pool_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Dynamic pool cache — keyed by a hash of (host, port, database, user)
# ---------------------------------------------------------------------------

_dynamic_pools: dict[str, MySQLConnectionPool] = {}
_dynamic_pool_lock = threading.Lock()
# Ordered insertion is guaranteed in Python 3.7+ dicts; we rely on this for
# oldest-first eviction.
_MAX_DYNAMIC_POOLS = 20

# ---------------------------------------------------------------------------
# Async executor — thread pool dedicated to synchronous MySQL I/O
#
# Why this exists:
#   mysql-connector-python is a synchronous library.  FastAPI runs sync
#   ``def`` endpoints in Starlette's default anyio threadpool (40 threads by
#   default), but ALL of those workers share the same pool of DB connections.
#   Under high concurrency, coroutines in the async event loop can block
#   waiting for a free connection while the threadpool is saturated, leading
#   to event-loop stalls and potential deadlocks.
#
#   The dedicated ``_db_executor`` gives us:
#   1. A separate, explicitly-sized threadpool whose workers are labelled
#      "db-N" so they are visible in profiling/tracing tools.
#   2. Explicit control over parallelism: ``DB_EXECUTOR_WORKERS`` env var
#      (default 20) mirrors ``DB_POOL_SIZE`` so we never request more
#      connections than the pool holds.
#   3. A clean shutdown path via ``shutdown_db_executor()``, called from the
#      FastAPI lifespan teardown.
#
# Usage — from an async endpoint or middleware:
#
#     from app.db import run_in_db_executor
#
#     result = await run_in_db_executor(my_sync_service_fn, arg1, arg2)
#
# Or decorate a sync helper to make it directly awaitable:
#
#     from app.db import async_db
#
#     @async_db
#     def fetch_scores(tenant_id: str) -> list[dict]: ...
#
#     scores = await fetch_scores(tenant_id)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# ThreadPoolExecutor — dedicated to synchronous MySQL I/O
#
# DB_MAX_WORKERS overrides the worker count ceiling.  Defaults to
# DB_EXECUTOR_WORKERS (which itself defaults to DB_POOL_SIZE).
# DB_QUEUE_SIZE limits the pending-task queue so a surge of requests
# does not exhaust memory; tasks beyond the limit receive an immediate
# rejection rather than silently queuing forever.
# ---------------------------------------------------------------------------

_DB_EXECUTOR_WORKERS = int(os.getenv("DB_MAX_WORKERS", os.getenv("DB_EXECUTOR_WORKERS", str(_POOL_SIZE))))
_DB_QUEUE_SIZE = int(os.getenv("DB_QUEUE_SIZE", str(_DB_EXECUTOR_WORKERS * 4)))
_db_executor = ThreadPoolExecutor(
    max_workers=_DB_EXECUTOR_WORKERS,
    thread_name_prefix="db",
)


async def run_in_db_executor(func, *args, **kwargs):
    """Run a synchronous DB function in the dedicated DB thread pool.

    Prevents blocking the asyncio event loop when calling mysql-connector
    (synchronous) from an ``async def`` endpoint or middleware.

    Example::

        result = await run_in_db_executor(my_sync_fn, arg1, kwarg=val)
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_db_executor, lambda: func(*args, **kwargs))


def async_db(func):
    """Decorator that makes a synchronous DB function directly awaitable.

    Wraps *func* so that awaiting it dispatches execution to the dedicated
    DB thread pool executor, keeping the event loop free.

    Example::

        @async_db
        def get_patient_row(pid: int) -> dict | None:
            with raf_cursor() as cur:
                cur.execute("SELECT * FROM patients WHERE id = %s", (pid,))
                return cur.fetchone()

        # In an async endpoint:
        row = await get_patient_row(pid)
    """
    @wraps(func)
    async def wrapper(*args, **kwargs):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(_db_executor, lambda: func(*args, **kwargs))
    return wrapper


def shutdown_db_executor() -> None:
    """Shut down the DB thread pool executor during application teardown.

    Called from the FastAPI lifespan shutdown hook.  ``wait=False`` avoids
    blocking the event loop during shutdown; in-flight queries will still
    complete because the underlying threads are daemon threads.
    """
    _db_executor.shutdown(wait=False)
    logger.info("DB executor shut down (workers=%d).", _DB_EXECUTOR_WORKERS)


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
    """Build the primary RAF write pool.

    When DB_PROXY_HOST is configured, connections are routed through the
    proxy (ProxySQL / MySQL Router) instead of connecting directly to the
    primary DB server.
    """
    ssl_ctx = _build_ssl_context()
    # Route through proxy when configured; retain original host as fallback.
    host = _DB_PROXY_HOST if _DB_PROXY_HOST else settings.raf_db_host
    port = _DB_PROXY_PORT if _DB_PROXY_HOST else settings.raf_db_port
    if _DB_PROXY_HOST:
        logger.info(
            "RAF primary pool: routing through proxy %s:%s", host, port
        )
    kwargs: dict = dict(
        pool_name="raf_pool",
        pool_size=_POOL_SIZE,
        pool_reset_session=True,
        host=host,
        port=port,
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


def _build_raf_read_pool() -> MySQLConnectionPool:
    """Build a read-only pool pointing at the read replica.

    Called only when DB_READ_HOST is configured.  Uses a slightly smaller
    pool than the primary because reads can be spread across multiple
    replicas in future.
    """
    ssl_ctx = _build_ssl_context()
    read_pool_size = max(5, _POOL_SIZE // 2)
    kwargs: dict = dict(
        pool_name="raf_read_pool",
        pool_size=read_pool_size,
        pool_reset_session=True,
        host=_DB_READ_HOST,
        port=_DB_READ_PORT,
        user=settings.raf_db_user,
        password=settings.raf_db_password,
        database=settings.raf_db_name,
        charset="utf8mb4",
        collation="utf8mb4_unicode_ci",
        connect_timeout=10,
    )
    if ssl_ctx:
        kwargs["ssl_context"] = ssl_ctx
    logger.info(
        "RAF read-replica pool initialised: %s:%s (pool_size=%d)",
        _DB_READ_HOST,
        _DB_READ_PORT,
        read_pool_size,
    )
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


def get_raf_read_pool() -> MySQLConnectionPool:
    """Return the read-replica pool, or the primary pool if no replica is configured."""
    global _raf_read_pool
    if _DB_READ_HOST is None:
        # No replica configured — fall back to primary transparently.
        return get_raf_pool()
    if _raf_read_pool is None:
        with _pool_lock:
            if _raf_read_pool is None:
                try:
                    _raf_read_pool = _build_raf_read_pool()
                except Exception as exc:
                    logger.warning(
                        "Read replica pool creation failed (%s) — falling back to primary.",
                        exc,
                    )
                    return get_raf_pool()
    return _raf_read_pool


def get_openemr_db():
    """Return a raw connection from the OpenEMR pool."""
    return get_openemr_pool().get_connection()


def get_raf_db():
    """Return a raw connection from the RAF pool."""
    return get_raf_pool().get_connection()


# ---------------------------------------------------------------------------
# Context-manager helpers used throughout the app
# ---------------------------------------------------------------------------


class _InstrumentedCursor:
    """Thin wrapper around a MySQL cursor that logs slow queries and counts executions."""

    __slots__ = ("_cursor",)

    def __init__(self, cursor):
        self._cursor = cursor

    def execute(self, query, params=None):
        # Track query count for N+1 detection
        count = getattr(_query_counter, "count", 0)
        _query_counter.count = count + 1
        queries = getattr(_query_counter, "queries", [])
        if len(queries) < 50:  # cap log size
            queries.append(query[:120] if isinstance(query, str) else str(query)[:120])
            _query_counter.queries = queries

        start = time.monotonic()
        try:
            return self._cursor.execute(query, params)
        finally:
            elapsed_ms = (time.monotonic() - start) * 1000
            if elapsed_ms >= _SLOW_QUERY_MS:
                # Redact parameter values before logging to prevent PHI leaking
                # into slow-query logs.  Only the parameter count is recorded so
                # operators can correlate the query structure with latency without
                # exposing patient names, dates of birth, or MRNs.
                param_summary = (
                    f"({len(params)} params redacted)"
                    if params
                    else "None"
                )
                _slow_query_logger.warning(
                    "SLOW QUERY (%.0fms): %s | params=%s",
                    elapsed_ms,
                    query[:500] if isinstance(query, str) else str(query)[:500],
                    param_summary,
                )

    def __getattr__(self, name):
        return getattr(self._cursor, name)

    def __iter__(self):
        return iter(self._cursor)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._cursor.close()


@contextmanager
def _db_cursor(pool_fn, dictionary: bool = True) -> Generator:
    """Shared implementation — acquire a connection from *pool_fn*, yield a
    cursor, commit on success, rollback on exception, and always close both
    the cursor and the connection.

    The cursor is wrapped with _InstrumentedCursor to log slow queries
    (>SLOW_QUERY_THRESHOLD_MS) and count queries per request for N+1 detection.
    """
    pool = pool_fn()
    conn = pool.get_connection()
    cursor = None
    try:
        raw_cursor = conn.cursor(dictionary=dictionary)
        cursor = _InstrumentedCursor(raw_cursor)
        yield cursor
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        if cursor is not None:
            cursor._cursor.close()
        conn.close()


def explain_query(query: str, params: tuple | None = None) -> list[dict]:
    """Run EXPLAIN on a query and return the plan rows.

    Only available when APP_ENV is 'development'. Returns an empty list in
    production to prevent accidental exposure of query internals.

    Only SELECT statements are accepted; any other statement type is rejected
    to prevent misuse of EXPLAIN as a vector for unintended DML execution.
    """
    if settings.app_env != "development":
        return []
    if not query.strip().upper().startswith("SELECT"):
        return []
    with _db_cursor(get_raf_pool) as cur:
        cur.execute(f"EXPLAIN {query}", params)
        return cur.fetchall()


class NoActiveEMRConnection(Exception):
    """Raised when no active direct_db EMR connection is configured."""


@contextmanager
def openemr_cursor(dictionary: bool = True, tenant_id: str | None = None) -> Generator:
    """Yield a cursor from the active EMR connection configured via the UI.

    Checks the ``emr_connections`` table for an active ``direct_db`` row.
    If none exists, falls back to the direct OpenEMR pool configured via
    environment variables (OPENEMR_DB_*).  This ensures the dashboard and
    reports work out-of-the-box while the UI still shows a 'No EMR Connected'
    banner encouraging explicit configuration.

    ``tenant_id`` is required.  Passing ``None`` raises ``ValueError`` to
    prevent silent cross-tenant data leakage from callers that omit the
    argument.
    """
    if tenant_id is None:
        if os.getenv("APP_ENV", "development") == "production":
            raise ValueError("openemr_cursor() requires tenant_id in production")
        # Fallback: use DEFAULT_TENANT_ID for legacy callers that haven't been
        # updated to pass tenant_id yet.  Log a warning so we can track them.
        _default = os.environ.get("DEFAULT_TENANT_ID", "1")
        logger.debug(
            "openemr_cursor() called without tenant_id — defaulting to '%s'. "
            "Caller should be updated to pass tenant_id explicitly.",
            _default,
        )
        tenant_id = _default
    # Lazy import to avoid circular dependency at module load
    from app.services.emr_manager import get_active_direct_db_credentials

    creds = get_active_direct_db_credentials(tenant_id)
    if creds is None or not creds.get("db_host") or not creds.get("db_name"):
        # Fallback to the direct OpenEMR pool configured via env vars.
        # This keeps the app functional before the user configures an
        # EMR connection through the UI, and when the active connection row
        # has NULL host/name (e.g. a placeholder row with no real credentials).
        logger.debug(
            "No UI-configured EMR connection found (or credentials incomplete) — "
            "falling back to direct OpenEMR pool (env vars)."
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
        db_type=creds.get("db_type") or "mysql",
        dictionary=dictionary,
    ) as cursor:
        yield cursor


@contextmanager
def raf_cursor(dictionary: bool = True) -> Generator:
    """Yield a cursor from the RAF Intelligence connection pool."""
    with _db_cursor(get_raf_pool, dictionary=dictionary) as cursor:
        yield cursor


@contextmanager
def raf_read_cursor(dictionary: bool = True) -> Generator:
    """Yield a read-only cursor routed to the read replica (or primary fallback).

    Use this context manager for SELECT-only workloads — patient lists,
    dashboard aggregates, reports — to offload read traffic from the primary
    write instance.

    When DB_READ_HOST is not configured this is identical to ``raf_cursor``.
    When the replica pool fails at pool-acquisition time the cursor silently
    falls back to the primary pool so the request still succeeds.

    IMPORTANT: Never issue INSERT/UPDATE/DELETE through this cursor.  On a true
    read replica those statements will fail with a read-only error from MySQL.
    """
    if not _DB_READ_HOST:
        with _db_cursor(get_raf_pool, dictionary=dictionary) as cursor:
            yield cursor
        return

    # Try to acquire a connection from the read replica pool.  If the pool
    # itself is unreachable we fall back to the primary *before* yielding,
    # avoiding the illegal double-yield that a post-yield fallback would cause.
    try:
        pool = get_raf_read_pool()
    except Exception:
        logger.warning(
            "raf_read_cursor: read replica pool unavailable, falling back to primary."
        )
        pool = get_raf_pool()

    with _db_cursor(lambda: pool, dictionary=dictionary) as cursor:
        yield cursor


# ---------------------------------------------------------------------------
# Health-check helper
# ---------------------------------------------------------------------------


def check_connections() -> dict[str, bool]:
    """Try to ping both databases (and read replica if configured) and return status dict."""
    status: dict[str, bool] = {}
    targets = [("openemr", get_openemr_pool), ("raf", get_raf_pool)]
    if _DB_READ_HOST:
        targets.append(("raf_read", get_raf_read_pool))
    for label, pool_fn in targets:
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
    ssl_enabled: bool = True,
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
                    "Dynamic pool for %s:%s/%s created with CERT_REQUIRED (CA: %s).",
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
    # ssl_context is not supported by all mysql-connector-python versions;
    # skip for internal/private hosts to avoid "Unsupported argument" errors.
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
    ssl_enabled: bool = True,
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
        raise ValueError(
            f"Unsupported db_type: {db_type!r}. Only 'mysql' is supported."
        )

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
    ssl_enabled: bool = True,
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

        try:
            conn = mysql.connector.connect(**kwargs)
        except TypeError:
            kwargs.pop("ssl_context", None)
            conn = mysql.connector.connect(**kwargs)
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        cursor.fetchone()
        latency_ms = int((time.monotonic() - start) * 1000)
        return True, f"Connection successful ({latency_ms} ms)", latency_ms
    except mysql.connector.Error as exc:
        latency_ms = int((time.monotonic() - start) * 1000)
        logger.debug(
            "test_db_connection failed for %s:%s/%s: %s", host, port, database, exc
        )
        return (
            False,
            "Connection failed. Check your credentials and network settings.",
            0,
        )
    except Exception as exc:  # pragma: no cover — unexpected errors
        logger.debug(
            "test_db_connection unexpected error for %s:%s/%s: %s",
            host,
            port,
            database,
            exc,
        )
        return (
            False,
            "Unexpected connection error. Please verify your database settings.",
            0,
        )
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


# ---------------------------------------------------------------------------
# Tenant-scoped query helpers — safety net for multi-tenancy
# ---------------------------------------------------------------------------

import re as _re

TENANT_SCOPED_TABLES = {
    "patients", "raf_scores", "raf_patient_demographics", "raf_patient_hcc",
    "raf_patient_interactions", "suspects", "attestations", "documents",
    "chart_chase", "claims", "care_gaps", "cohorts", "cohort_snapshots",
    "submissions", "providers", "emr_connections", "audit_log",
    "quality_measures", "awv_visits", "notifications", "coder_worklist",
    "encounters", "encounter_diagnoses", "raf_score_components",
}

_TENANT_FILTER_RE = _re.compile(r"\btenant_id\s*=", _re.IGNORECASE)

# Allowlist of tables that tenant_insert() is permitted to write to.
# Derived from TENANT_SCOPED_TABLES above — the two sets must stay in sync.
_TENANT_INSERT_TABLES: frozenset[str] = frozenset(TENANT_SCOPED_TABLES)

# Valid SQL identifier: letter/underscore start, alphanumeric/underscore body,
# max 64 chars (MySQL limit).
_IDENT_RE = _re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")


def tenant_query(cursor, sql: str, params: tuple | list, tenant_id: str):
    """Execute SQL with automatic tenant_id injection if missing.

    Safety net: if the SQL already contains ``tenant_id =``, it runs as-is.
    Otherwise the filter is appended automatically and logged as a warning.
    """
    if not tenant_id:
        raise ValueError("tenant_query() requires a non-empty tenant_id.")
    params = tuple(params) if not isinstance(params, tuple) else params
    if not _TENANT_FILTER_RE.search(sql):
        sql_upper = sql.strip().upper()
        if "WHERE" in sql_upper:
            sql = sql + " AND tenant_id = %s"
        else:
            sql = sql + " WHERE tenant_id = %s"
        params = params + (tenant_id,)
        logger.warning(
            "TENANT SAFETY NET: Injected tenant_id filter. SQL: %.80s", sql[:80],
        )
    cursor.execute(sql, params)
    return cursor


def tenant_insert(cursor, table: str, data: dict, tenant_id: str):
    """Insert a row, auto-adding tenant_id if not already in *data*.

    Both the table name and every column key are validated against an
    allowlist / regex before being interpolated into SQL, preventing
    SQL injection through those otherwise-unparameterised identifiers.
    """
    if table not in _TENANT_INSERT_TABLES:
        raise ValueError(
            f"tenant_insert: table {table!r} is not in the allowed table list."
        )
    for col in data.keys():
        if not _IDENT_RE.fullmatch(col):
            raise ValueError(
                f"tenant_insert: column name {col!r} contains invalid characters."
            )
    if not tenant_id:
        raise ValueError("tenant_insert() requires a non-empty tenant_id.")
    if "tenant_id" not in data:
        data = {**data, "tenant_id": tenant_id}
        logger.warning("TENANT SAFETY NET: Auto-added tenant_id to INSERT into %s.", table)
    columns = ", ".join(data.keys())
    placeholders = ", ".join(["%s"] * len(data))
    sql = f"INSERT INTO {table} ({columns}) VALUES ({placeholders})"
    cursor.execute(sql, tuple(data.values()))
    return cursor


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


# ---------------------------------------------------------------------------
# Compatibility shim — some routers use get_db() as a FastAPI Depends target
# ---------------------------------------------------------------------------


@contextmanager
def get_db(dictionary: bool = True) -> Generator:
    """Alias for ``raf_cursor`` used by FastAPI Depends injection.

    Some routers import ``get_db`` as a SQLAlchemy-style dependency.
    This shim forwards all calls to :func:`raf_cursor` so those routers
    work without a SQLAlchemy session layer.
    """
    with raf_cursor(dictionary=dictionary) as cursor:
        yield cursor
