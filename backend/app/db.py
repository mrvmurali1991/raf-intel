"""
MySQL connection pools for OpenEMR and RAF Intelligence databases.

Both pools use mysql-connector-python's built-in pooling so connections
are reused across requests without holding a persistent socket open.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Generator

import mysql.connector
from mysql.connector.pooling import MySQLConnectionPool

from app.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pool singletons – created once at import time
# ---------------------------------------------------------------------------

_openemr_pool: MySQLConnectionPool | None = None
_raf_pool: MySQLConnectionPool | None = None


def _build_openemr_pool() -> MySQLConnectionPool:
    return MySQLConnectionPool(
        pool_name="openemr_pool",
        pool_size=10,
        pool_reset_session=True,
        host=settings.openemr_db_host,
        port=settings.openemr_db_port,
        user=settings.openemr_db_user,
        password=settings.openemr_db_password,
        database=settings.openemr_db_name,
        charset="utf8mb4",
        collation="utf8mb4_unicode_ci",
        autocommit=True,
        connect_timeout=10,
    )


def _build_raf_pool() -> MySQLConnectionPool:
    return MySQLConnectionPool(
        pool_name="raf_pool",
        pool_size=10,
        pool_reset_session=True,
        host=settings.raf_db_host,
        port=settings.raf_db_port,
        user=settings.raf_db_user,
        password=settings.raf_db_password,
        database=settings.raf_db_name,
        charset="utf8mb4",
        collation="utf8mb4_unicode_ci",
        autocommit=True,
        connect_timeout=10,
    )


def get_openemr_pool() -> MySQLConnectionPool:
    global _openemr_pool
    if _openemr_pool is None:
        _openemr_pool = _build_openemr_pool()
    return _openemr_pool


def get_raf_pool() -> MySQLConnectionPool:
    global _raf_pool
    if _raf_pool is None:
        _raf_pool = _build_raf_pool()
    return _raf_pool


# ---------------------------------------------------------------------------
# Context-manager helpers used throughout the app
# ---------------------------------------------------------------------------

@contextmanager
def openemr_cursor(dictionary: bool = True) -> Generator:
    """Yield a cursor from the OpenEMR connection pool."""
    pool = get_openemr_pool()
    conn = pool.get_connection()
    try:
        cursor = conn.cursor(dictionary=dictionary)
        yield cursor
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()


@contextmanager
def raf_cursor(dictionary: bool = True) -> Generator:
    """Yield a cursor from the RAF Intelligence connection pool."""
    pool = get_raf_pool()
    conn = pool.get_connection()
    try:
        cursor = conn.cursor(dictionary=dictionary)
        yield cursor
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()


# ---------------------------------------------------------------------------
# Health-check helper
# ---------------------------------------------------------------------------

def check_connections() -> dict[str, bool]:
    """Try to ping both databases and return status dict."""
    status: dict[str, bool] = {}
    for label, pool_fn in [("openemr", get_openemr_pool), ("raf", get_raf_pool)]:
        try:
            pool = pool_fn()
            conn = pool.get_connection()
            conn.ping(reconnect=True)
            conn.close()
            status[label] = True
        except Exception as exc:
            logger.warning("DB health-check failed for %s: %s", label, exc)
            status[label] = False
    return status
