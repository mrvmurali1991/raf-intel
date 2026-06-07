"""
Shared FastAPI dependencies used across multiple routers.

Import from here rather than defining identical dependencies inline in each
router — keeps a single source of truth and avoids silent drift between copies.
"""
# Do not use ``from __future__ import annotations`` — breaks FastAPI schemas.

from collections.abc import Generator

from app.db import raf_cursor
from app.services.data_quality_monitor import Cursor


def get_cursor() -> Generator[Cursor, None, None]:
    """FastAPI dependency that yields a dictionary cursor from the RAF pool.

    Uses the same ``raf_cursor()`` context manager as the rest of the app so
    connections are drawn from and returned to the shared pool.
    """
    with raf_cursor(dictionary=True) as cursor:
        yield cursor
