"""Round-trip tests for app.services.config_service.

Uses an in-memory dict to stand in for the ``system_config`` table so no
MySQL connection is needed. Verifies:

- set_config -> get_config round trip (global and tenant scopes)
- tenant-scoped value overrides global
- typed accessors return expected types and fall back to DEFAULTS
- DEFAULTS is the single source of truth (no duplicated constants)
"""
from __future__ import annotations

from contextlib import contextmanager

import pytest
from app.services import config_service


class _FakeCursor:
    """Mimics the cursor interface used by config_service."""

    def __init__(self, store: dict[tuple[str, str], str]):
        self._store = store
        self._last: dict | None = None

    def execute(self, sql: str, params: tuple):
        s = sql.strip().upper()
        if s.startswith("SELECT"):
            key, scope = params
            val = self._store.get((key, scope))
            self._last = {"config_value": val} if val is not None else None
        elif s.startswith("INSERT"):
            key, scope, value = params
            self._store[(key, scope)] = value
            self._last = None
        else:
            raise AssertionError(f"Unexpected SQL: {sql}")

    def fetchone(self):
        return self._last


@pytest.fixture
def fake_db(monkeypatch):
    store: dict[tuple[str, str], str] = {}

    @contextmanager
    def fake_cursor():
        yield _FakeCursor(store)

    monkeypatch.setattr(config_service, "raf_cursor", fake_cursor)
    return store


def test_roundtrip_global(fake_db):
    config_service.set_config("ai_analysis_cutoff_date", "2030-01-01")
    assert config_service.get_config("ai_analysis_cutoff_date") == "2030-01-01"


def test_roundtrip_tenant(fake_db):
    config_service.set_config("ai_analysis_cutoff_date", "2030-01-01")  # global
    config_service.set_config("ai_analysis_cutoff_date", "2031-06-15", tenant_id="t1")
    assert (
        config_service.get_ai_analysis_cutoff_date(tenant_id="t1") == "2031-06-15"
    )
    assert (
        config_service.get_ai_analysis_cutoff_date(tenant_id="other") == "2030-01-01"
    )


def test_typed_accessor_int(fake_db):
    config_service.set_config("max_analyses_per_patient_per_day", "5", tenant_id="t1")
    assert config_service.get_max_analyses_per_patient_per_day("t1") == 5


def test_defaults_fallback_when_empty(fake_db):
    # Nothing set — should fall back to DEFAULTS
    assert (
        config_service.get_ai_analysis_cutoff_date()
        == config_service.DEFAULTS["ai_analysis_cutoff_date"]
    )
    assert config_service.get_max_analyses_per_patient_per_day() == int(
        config_service.DEFAULTS["max_analyses_per_patient_per_day"]
    )


def test_defaults_contents():
    # Canonical values the migration also seeds — keep in sync.
    assert config_service.DEFAULTS["ai_analysis_cutoff_date"] == "2026-04-15"
    assert config_service.DEFAULTS["max_analyses_per_patient_per_day"] == "2"
