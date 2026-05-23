"""
Unit tests for app.services.feature_flag_service.

These tests do NOT hit the live backend or the live MySQL.  ``raf_cursor`` is
patched with an in-memory fake so the merging / set / reset logic can be
verified deterministically.

Run with::

    pytest backend/tests/test_feature_flag_service.py
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# In-memory cursor fake
# ---------------------------------------------------------------------------

class _FakeCursor:
    """
    Tiny SQL-shaped stub.  Recognises just the three statements used by the
    feature flag service: SELECT, INSERT ... ON DUPLICATE KEY UPDATE, DELETE.
    """

    def __init__(self, store: dict[tuple[int, str], int]):
        self._store = store
        self._last_select: list[dict[str, Any]] = []
        self.rowcount = 0

    def execute(self, sql: str, params: tuple = ()):  # noqa: D401 — mimic API
        sql_norm = " ".join(sql.split()).upper()
        if sql_norm.startswith("SELECT"):
            user_id = int(params[0])
            self._last_select = [
                {"flag_key": k, "enabled": v}
                for (uid, k), v in self._store.items()
                if uid == user_id
            ]
            self.rowcount = len(self._last_select)
        elif sql_norm.startswith("INSERT INTO USER_FEATURE_FLAGS"):
            user_id, key, enabled = int(params[0]), params[1], int(params[2])
            self._store[(user_id, key)] = enabled
            self.rowcount = 1
        elif sql_norm.startswith("DELETE FROM USER_FEATURE_FLAGS"):
            user_id = int(params[0])
            keys = [k for k in self._store if k[0] == user_id]
            for k in keys:
                del self._store[k]
            self.rowcount = len(keys)
        else:  # pragma: no cover — guard against unexpected SQL
            raise AssertionError(f"Unexpected SQL in test fake: {sql!r}")

    def fetchall(self):
        return list(self._last_select)


@contextmanager
def _fake_raf_cursor_factory(store):
    @contextmanager
    def _cm(dictionary: bool = True):  # signature matches db.raf_cursor
        yield _FakeCursor(store)

    yield _cm


@pytest.fixture
def fake_db():
    """Yield a fresh in-memory store + a patched ``raf_cursor`` for one test."""
    store: dict[tuple[int, str], int] = {}
    with _fake_raf_cursor_factory(store) as cm:
        with patch("app.services.feature_flag_service.raf_cursor", cm):
            yield store


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_registry_contains_all_nine_provider_flags() -> None:
    """The 9 keys other agents will reference must be present and stable."""
    from app.services.feature_flag_service import FEATURE_REGISTRY

    expected = {
        "provider_peer_percentile",
        "provider_top_hcc_opportunities",
        "provider_yoy_trend",
        "provider_meat_audit_risk",
        "provider_revenue_breakdown",
        "provider_hcc_gap_drilldown",
        "provider_suspect_hotlist",
        "provider_previsit_briefing",
        "provider_pdf_report",
    }
    assert expected.issubset(FEATURE_REGISTRY.keys())


def test_list_flags_returns_registry_defaults_when_no_overrides(fake_db) -> None:
    """With no DB rows, every flag falls back to its default_enabled value."""
    from app.services.feature_flag_service import FEATURE_REGISTRY, list_flags

    items = list_flags(user_id=42)

    assert len(items) == len(FEATURE_REGISTRY)
    for item in items:
        registry_flag = FEATURE_REGISTRY[item["key"]]
        assert item["enabled"] == registry_flag.default_enabled
        # Schema sanity — every key the frontend reads must be present
        for k in ("key", "name", "description", "category", "default_enabled", "scope"):
            assert k in item


def test_set_flag_persists_override(fake_db) -> None:
    """set_flag should upsert a row and the next list_flags should reflect it."""
    from app.services.feature_flag_service import list_flags, set_flag

    set_flag(user_id=7, key="provider_pdf_report", enabled=False)

    items = {f["key"]: f for f in list_flags(user_id=7)}
    assert items["provider_pdf_report"]["enabled"] is False
    # Other flags untouched
    assert items["provider_peer_percentile"]["enabled"] is True


def test_set_flag_overwrites_existing_override(fake_db) -> None:
    """set_flag is idempotent — re-applying changes the stored value."""
    from app.services.feature_flag_service import list_flags, set_flag

    set_flag(user_id=7, key="provider_yoy_trend", enabled=False)
    set_flag(user_id=7, key="provider_yoy_trend", enabled=True)

    items = {f["key"]: f for f in list_flags(user_id=7)}
    assert items["provider_yoy_trend"]["enabled"] is True


def test_set_flag_rejects_unknown_key(fake_db) -> None:
    """Unknown flag keys must raise — we refuse to persist typos."""
    from app.services.feature_flag_service import set_flag

    with pytest.raises(KeyError):
        set_flag(user_id=7, key="not_a_real_flag", enabled=True)


def test_reset_user_flags_removes_only_that_users_overrides(fake_db) -> None:
    """Resetting user A must not affect user B's overrides."""
    from app.services.feature_flag_service import (
        list_flags,
        reset_user_flags,
        set_flag,
    )

    set_flag(user_id=1, key="provider_pdf_report", enabled=False)
    set_flag(user_id=2, key="provider_pdf_report", enabled=False)

    deleted = reset_user_flags(user_id=1)
    assert deleted == 1

    items_1 = {f["key"]: f for f in list_flags(user_id=1)}
    items_2 = {f["key"]: f for f in list_flags(user_id=2)}

    # User 1 — back to default (true)
    assert items_1["provider_pdf_report"]["enabled"] is True
    # User 2 — override still applied (false)
    assert items_2["provider_pdf_report"]["enabled"] is False


def test_list_flags_requires_user_id(fake_db) -> None:
    """user_id is mandatory; passing None must error rather than silently default."""
    from app.services.feature_flag_service import list_flags

    with pytest.raises(ValueError):
        list_flags(user_id=None)  # type: ignore[arg-type]


def test_list_flags_preserves_registry_order(fake_db) -> None:
    """Registry insertion order is the rendering order — keep it stable."""
    from app.services.feature_flag_service import FEATURE_REGISTRY, list_flags

    keys_returned = [item["key"] for item in list_flags(user_id=99)]
    assert keys_returned == list(FEATURE_REGISTRY.keys())
