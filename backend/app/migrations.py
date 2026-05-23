"""DELETED: schema management lives in backend/alembic/versions/ exclusively.

This module previously housed ~2,000 lines of `@register` / `_add_column_if_missing`
DDL functions that ran at application startup. The registration decorator was
already neutralized in an earlier refactor (all of those functions became dead
code), so this file shrank to a tombstone.

If you are reading this because grep led you here:
  - Schema changes: add an Alembic revision under backend/alembic/versions/
  - Need to check current head: `alembic current` (from backend/ on a dev box)
  - History: `git log --all -- backend/app/migrations.py`
"""
from __future__ import annotations

import warnings as _warnings

_DEPRECATION_MESSAGE = (
    "app.migrations is deprecated and no longer runs DDL. Add an Alembic "
    "revision under backend/alembic/versions/ instead."
)


def __getattr__(name: str):
    """Any access to the old API now raises clearly instead of failing silently."""
    _warnings.warn(_DEPRECATION_MESSAGE, DeprecationWarning, stacklevel=2)
    raise AttributeError(
        f"app.migrations.{name} no longer exists. {_DEPRECATION_MESSAGE}"
    )
