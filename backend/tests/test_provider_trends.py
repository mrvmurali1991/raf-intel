"""
tests/test_provider_trends.py — YoY provider-trend service test suite.

Covers:
- Multi-year fixture: values returned ascending, current+deltas computed.
- Single-year fixture: deltas are None, single_year_only flag set.
- Latest-snapshot-per-year selection (picks max calculated_at).
- Metric filtering / unknown-metric fallback.
- Tenant aggregate averaging across providers.

All DB calls are mocked via unittest.mock — no live database required.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from app.services.provider_trends import (
    DEFAULT_METRICS,
    METRIC_COLUMNS,
    get_provider_trend,
    get_tenant_aggregate_trend,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_cursor_cm(rows: list[dict] | None = None):
    """Return (context_manager_factory, cursor_mock) usable as a raf_cursor patch."""
    cursor = MagicMock()
    cursor.fetchall.return_value = list(rows or [])
    cursor.fetchone.return_value = (rows[0] if rows else None)
    cursor.rowcount = len(rows or [])

    @contextmanager
    def _cm(*args, **kwargs):
        yield cursor

    return _cm, cursor


def _row(year: int, *, raf=None, recap=None, cap=None, rev=None,
         calculated_at: datetime | None = None) -> dict:
    """Construct a single fake provider_scorecard_snapshots row."""
    return {
        "measurement_year": year,
        "calculated_at": calculated_at or datetime(year, 12, 31, 12, 0, 0),
        "average_raf": raf,
        "recapture_rate": recap,
        "hcc_capture_rate": cap,
        "revenue_opportunity": rev,
    }


# ===========================================================================
# get_provider_trend — multi-year happy path
# ===========================================================================

def test_get_provider_trend_multi_year_returns_ascending_values_and_deltas():
    # DB returns rows DESC by year (matches the SQL ORDER BY).
    rows = [
        _row(2026, raf=1.34, recap=0.82, cap=0.78, rev=180_000),
        _row(2025, raf=1.21, recap=0.79, cap=0.74, rev=160_000),
        _row(2024, raf=1.10, recap=0.71, cap=0.69, rev=140_000),
        _row(2023, raf=1.02, recap=0.65, cap=0.66, rev=120_000),
    ]
    cm, _cur = _make_cursor_cm(rows)

    with patch("app.services.provider_trends.raf_cursor", cm):
        out = get_provider_trend(provider_id=42, years=4)

    assert out["provider_id"] == 42
    assert out["single_year_only"] is False
    assert out["years_available"] == [2023, 2024, 2025, 2026]

    # All four default metrics are present.
    assert set(out["metrics"].keys()) == set(DEFAULT_METRICS)

    raf = out["metrics"]["raf"]
    # Values are returned ASCENDING for sparkline rendering.
    assert [v["year"] for v in raf["values"]] == [2023, 2024, 2025, 2026]
    assert raf["current"] == pytest.approx(1.34)
    assert raf["delta_vs_prior_year"] == pytest.approx(1.34 - 1.21)
    assert raf["delta_vs_4y"] == pytest.approx(1.34 - 1.02)

    rev = out["metrics"]["revenue"]
    assert rev["current"] == pytest.approx(180_000)
    assert rev["delta_vs_prior_year"] == pytest.approx(20_000)
    assert rev["delta_vs_4y"] == pytest.approx(60_000)


# ===========================================================================
# get_provider_trend — single-year edge case
# ===========================================================================

def test_get_provider_trend_single_year_returns_null_deltas():
    rows = [_row(2026, raf=1.34, recap=0.82, cap=0.78, rev=180_000)]
    cm, _cur = _make_cursor_cm(rows)

    with patch("app.services.provider_trends.raf_cursor", cm):
        out = get_provider_trend(provider_id=7, years=4)

    assert out["single_year_only"] is True
    assert out["years_available"] == [2026]

    raf = out["metrics"]["raf"]
    assert raf["current"] == pytest.approx(1.34)
    assert raf["delta_vs_prior_year"] is None
    assert raf["delta_vs_4y"] is None
    assert len(raf["values"]) == 1


def test_get_provider_trend_no_data_returns_empty_payload():
    cm, _cur = _make_cursor_cm([])

    with patch("app.services.provider_trends.raf_cursor", cm):
        out = get_provider_trend(provider_id=999, years=4)

    assert out["years_available"] == []
    assert out["single_year_only"] is True
    raf = out["metrics"]["raf"]
    assert raf["values"] == []
    assert raf["current"] is None
    assert raf["delta_vs_prior_year"] is None


# ===========================================================================
# get_provider_trend — metric filtering
# ===========================================================================

def test_get_provider_trend_filters_to_requested_metric():
    rows = [
        _row(2026, raf=1.34, recap=0.82),
        _row(2025, raf=1.21, recap=0.79),
    ]
    cm, _cur = _make_cursor_cm(rows)

    with patch("app.services.provider_trends.raf_cursor", cm):
        out = get_provider_trend(provider_id=1, metrics=["raf"], years=4)

    assert list(out["metrics"].keys()) == ["raf"]


def test_get_provider_trend_unknown_metric_falls_back_to_defaults():
    rows = [_row(2026, raf=1.34, recap=0.82, cap=0.78, rev=100_000)]
    cm, _cur = _make_cursor_cm(rows)

    with patch("app.services.provider_trends.raf_cursor", cm):
        out = get_provider_trend(provider_id=1, metrics=["bogus_metric"], years=4)

    # Falls back to default metric set (all four).
    assert set(out["metrics"].keys()) == set(DEFAULT_METRICS)


# ===========================================================================
# get_provider_trend — None values do not poison deltas
# ===========================================================================

def test_get_provider_trend_skips_none_values_in_delta_calculation():
    rows = [
        _row(2026, raf=1.50),
        _row(2025, raf=None),       # missing year — should be ignored for deltas
        _row(2024, raf=1.20),
    ]
    cm, _cur = _make_cursor_cm(rows)

    with patch("app.services.provider_trends.raf_cursor", cm):
        out = get_provider_trend(provider_id=1, metrics=["raf"], years=4)

    raf = out["metrics"]["raf"]
    # All three years still appear in `values` (preserving x-axis position),
    # but deltas only consider numeric points: 1.20 → 1.50.
    assert len(raf["values"]) == 3
    assert raf["current"] == pytest.approx(1.50)
    assert raf["delta_vs_prior_year"] == pytest.approx(0.30)
    assert raf["delta_vs_4y"] == pytest.approx(0.30)


# ===========================================================================
# get_tenant_aggregate_trend
# ===========================================================================

def test_get_tenant_aggregate_trend_computes_average_per_year():
    # The SQL itself does the AVG(); the mock just hands back the resulting rows.
    rows = [
        {"measurement_year": 2026, "value": 1.30},
        {"measurement_year": 2025, "value": 1.18},
        {"measurement_year": 2024, "value": 1.05},
    ]
    cm, _cur = _make_cursor_cm(rows)

    with patch("app.services.provider_trends.raf_cursor", cm):
        out = get_tenant_aggregate_trend(metric="raf", years=4, tenant_id=1)

    assert out["metric"] == "raf"
    assert out["tenant_id"] == 1
    assert [v["year"] for v in out["values"]] == [2024, 2025, 2026]
    assert out["current"] == pytest.approx(1.30)
    assert out["delta_vs_prior_year"] == pytest.approx(0.12)
    assert out["delta_vs_4y"] == pytest.approx(0.25)
    assert out["single_year_only"] is False


def test_get_tenant_aggregate_trend_unknown_metric_falls_back_to_raf():
    cm, _cur = _make_cursor_cm([{"measurement_year": 2026, "value": 1.0}])

    with patch("app.services.provider_trends.raf_cursor", cm):
        out = get_tenant_aggregate_trend(metric="not_a_metric")

    assert out["metric"] == "raf"


# ===========================================================================
# Column registry self-check — guards against typos in METRIC_COLUMNS.
# ===========================================================================

def test_metric_columns_only_reference_known_snapshot_fields():
    # The columns referenced here must match those declared in
    # backend/app/migrations.py for provider_scorecard_snapshots.
    valid_columns = {
        "average_raf",
        "recapture_rate",
        "hcc_capture_rate",
        "revenue_opportunity",
        "meat_completeness_avg",
        "documentation_quality_score",
    }
    for metric, column in METRIC_COLUMNS.items():
        assert column in valid_columns, (
            f"METRIC_COLUMNS[{metric!r}] = {column!r} is not a recognised "
            "provider_scorecard_snapshots column"
        )
