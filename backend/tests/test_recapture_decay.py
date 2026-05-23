"""
tests/test_recapture_decay.py — Decay curve + velocity KPI test suite.

All DB calls are mocked via ``unittest.mock.patch`` on the ``raf_cursor``
context manager. No database is required.

Coverage:
    * get_decay_curve — cohort grouping, monthly counts, cumulative pct math
    * get_velocity_kpis — avg/median days, YTD $, year-end projection,
                          target-30 / Q1 / Q4 ratios
    * get_top_slow_movers — ranking by avg days, $-tiebreak, no-closures-first
    * Internal helpers — _safe_month / _coerce_dt / _median / _is_leap
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime
from unittest.mock import MagicMock, patch

import pytest

from app.services.recapture_decay import (
    _coerce_dt,
    _is_leap,
    _median,
    _safe_month,
    get_decay_curve,
    get_top_slow_movers,
    get_velocity_kpis,
)

# ---------------------------------------------------------------------------
# Cursor context-manager helper
# ---------------------------------------------------------------------------

def _cursor_cm(rows: list[dict]):
    """Return a context-manager-compatible factory yielding a cursor that
    fetches `rows`."""
    @contextmanager
    def _cm(*args, **kwargs):
        cur = MagicMock()
        cur.fetchall.return_value = list(rows)
        yield cur
    return _cm


def _gap(
    *,
    current_year: int,
    status: str = "recaptured",
    resolved_at: datetime | None = None,
    created_at: datetime | None = None,
    revenue_impact: float = 3000.0,
    hcc_code: str = "85",
) -> dict:
    return {
        "current_year": current_year,
        "status": status,
        "resolved_at": resolved_at,
        "created_at": created_at or datetime(current_year, 1, 1),
        "revenue_impact": revenue_impact,
        "hcc_code": hcc_code,
    }


# ===========================================================================
# 1. get_decay_curve
# ===========================================================================

class TestDecayCurve:
    def test_cohort_grouping_three_years(self) -> None:
        rows = [
            _gap(current_year=2024, resolved_at=datetime(2024, 2, 15)),
            _gap(current_year=2025, resolved_at=datetime(2025, 3, 10)),
            _gap(current_year=2026, resolved_at=datetime(2026, 1, 20)),
        ]
        with patch("app.services.recapture_decay.raf_cursor", _cursor_cm(rows)):
            res = get_decay_curve(tenant_id="1", current_year=2026, lookback_years=3)

        assert res["current_year"] == 2026
        assert res["lookback_years"] == 3
        years = [c["cohort_year"] for c in res["cohorts"]]
        assert years == [2024, 2025, 2026]
        for c in res["cohorts"]:
            assert c["total_gaps"] == 1
            assert c["closed_gaps"] == 1
            # 12 months emitted
            assert [p["month_of_year"] for p in c["points"]] == list(range(1, 13))

    def test_cumulative_percentages_reach_one(self) -> None:
        # 4 gaps in cohort 2026, all resolved across different months
        rows = [
            _gap(current_year=2026, resolved_at=datetime(2026, 1, 5)),
            _gap(current_year=2026, resolved_at=datetime(2026, 1, 20)),
            _gap(current_year=2026, resolved_at=datetime(2026, 6, 10)),
            _gap(current_year=2026, resolved_at=datetime(2026, 12, 1)),
        ]
        with patch("app.services.recapture_decay.raf_cursor", _cursor_cm(rows)):
            res = get_decay_curve(tenant_id="1", current_year=2026, lookback_years=1)

        cohort = res["cohorts"][0]
        pts = cohort["points"]
        # By Jan: 2/4 = 0.5
        assert pts[0]["cumulative_closed_pct"] == pytest.approx(0.5)
        # By June (idx 5): 3/4
        assert pts[5]["cumulative_closed_pct"] == pytest.approx(0.75)
        # By December: 4/4
        assert pts[11]["cumulative_closed_pct"] == pytest.approx(1.0)
        # $ recaptured cumulative ≈ 4 × 3000 = 12000 by Dec
        assert pts[11]["cumulative_$_recaptured"] == pytest.approx(12000.0)

    def test_open_gaps_count_in_total_but_not_closed(self) -> None:
        rows = [
            _gap(current_year=2026, status="open", resolved_at=None),
            _gap(current_year=2026, status="recaptured", resolved_at=datetime(2026, 4, 10)),
        ]
        with patch("app.services.recapture_decay.raf_cursor", _cursor_cm(rows)):
            res = get_decay_curve(tenant_id="1", current_year=2026, lookback_years=1)
        c = res["cohorts"][0]
        assert c["total_gaps"] == 2
        assert c["closed_gaps"] == 1
        # April closure ⇒ cumulative pct hits 0.5 there
        assert c["points"][3]["cumulative_closed_pct"] == pytest.approx(0.5)
        # And stays at 0.5 for the rest of the year
        assert c["points"][11]["cumulative_closed_pct"] == pytest.approx(0.5)

    def test_empty_cohort_emits_zeros(self) -> None:
        with patch("app.services.recapture_decay.raf_cursor", _cursor_cm([])):
            res = get_decay_curve(tenant_id="1", current_year=2026, lookback_years=2)
        assert len(res["cohorts"]) == 2
        for c in res["cohorts"]:
            assert c["total_gaps"] == 0
            for p in c["points"]:
                assert p["closure_rate"] == 0.0
                assert p["cumulative_closed_pct"] == 0.0

    def test_lookback_clamped_to_one(self) -> None:
        with patch("app.services.recapture_decay.raf_cursor", _cursor_cm([])):
            res = get_decay_curve(tenant_id="1", current_year=2026, lookback_years=0)
        # Clamped to 1 → only 2026 cohort in result
        assert len(res["cohorts"]) == 1
        assert res["cohorts"][0]["cohort_year"] == 2026

    def test_dollars_summed_per_month(self) -> None:
        rows = [
            _gap(current_year=2026, resolved_at=datetime(2026, 3, 5), revenue_impact=1000),
            _gap(current_year=2026, resolved_at=datetime(2026, 3, 20), revenue_impact=2000),
            _gap(current_year=2026, resolved_at=datetime(2026, 7, 1), revenue_impact=4000),
        ]
        with patch("app.services.recapture_decay.raf_cursor", _cursor_cm(rows)):
            res = get_decay_curve(tenant_id="1", current_year=2026, lookback_years=1)
        pts = res["cohorts"][0]["points"]
        assert pts[2]["$_recaptured"] == pytest.approx(3000.0)
        assert pts[6]["$_recaptured"] == pytest.approx(4000.0)


# ===========================================================================
# 2. get_velocity_kpis
# ===========================================================================

class TestVelocityKpis:
    def test_avg_and_median_days_to_close(self) -> None:
        # Two gaps closed in 10 and 20 days → avg=15, median=15
        rows = [
            _gap(current_year=2026,
                 created_at=datetime(2026, 1, 1),
                 resolved_at=datetime(2026, 1, 11),
                 revenue_impact=3000),
            _gap(current_year=2026,
                 created_at=datetime(2026, 1, 1),
                 resolved_at=datetime(2026, 1, 21),
                 revenue_impact=3000),
        ]
        with patch("app.services.recapture_decay.raf_cursor", _cursor_cm(rows)):
            kpis = get_velocity_kpis(tenant_id="1", year=2026, today=date(2026, 6, 30))

        assert kpis["avg_days_to_close"] == pytest.approx(15.0)
        assert kpis["median_days_to_close"] == pytest.approx(15.0)
        assert kpis["closed_cohort_gaps"] == 2
        assert kpis["ytd_$_recaptured"] == pytest.approx(6000.0)

    def test_year_end_projection_linear_extrapolation(self) -> None:
        # Closed $4000 by day 100 of a 365-day year → projected ≈ 4000 * 365/100
        rows = [
            _gap(current_year=2026,
                 created_at=datetime(2026, 1, 1),
                 resolved_at=datetime(2026, 1, 15),
                 revenue_impact=4000),
        ]
        with patch("app.services.recapture_decay.raf_cursor", _cursor_cm(rows)):
            kpis = get_velocity_kpis(tenant_id="1", year=2026, today=date(2026, 4, 10))
        # Day-of-year for Apr 10 = 100
        expected = 4000 * (365 / 100)
        assert kpis["ye_projected_$"] == pytest.approx(expected, rel=0.01)

    def test_target_30_days_ratio(self) -> None:
        # 1 of 2 closed within 30 days → 0.5
        rows = [
            _gap(current_year=2026,
                 created_at=datetime(2026, 1, 1),
                 resolved_at=datetime(2026, 1, 20)),  # 19 days
            _gap(current_year=2026,
                 created_at=datetime(2026, 1, 1),
                 resolved_at=datetime(2026, 4, 1)),   # 90 days
        ]
        with patch("app.services.recapture_decay.raf_cursor", _cursor_cm(rows)):
            kpis = get_velocity_kpis(tenant_id="1", year=2026, today=date(2026, 6, 30))
        assert kpis["days_to_close_target_30"] == pytest.approx(0.5)

    def test_q1_q4_ratios(self) -> None:
        rows = [
            _gap(current_year=2026, resolved_at=datetime(2026, 2, 10),
                 created_at=datetime(2026, 1, 1)),   # Q1
            _gap(current_year=2026, resolved_at=datetime(2026, 3, 5),
                 created_at=datetime(2026, 1, 1)),   # Q1
            _gap(current_year=2026, resolved_at=datetime(2026, 11, 5),
                 created_at=datetime(2026, 1, 1)),   # Q4
            _gap(current_year=2026, resolved_at=datetime(2026, 7, 5),
                 created_at=datetime(2026, 1, 1)),   # Other
        ]
        with patch("app.services.recapture_decay.raf_cursor", _cursor_cm(rows)):
            kpis = get_velocity_kpis(tenant_id="1", year=2026, today=date(2026, 12, 31))
        assert kpis["early_recapture_rate"] == pytest.approx(2 / 4)
        assert kpis["late_recapture_rate"] == pytest.approx(1 / 4)

    def test_no_data_returns_zeros(self) -> None:
        with patch("app.services.recapture_decay.raf_cursor", _cursor_cm([])):
            kpis = get_velocity_kpis(tenant_id="1", year=2026, today=date(2026, 6, 30))
        assert kpis["avg_days_to_close"] == 0.0
        assert kpis["median_days_to_close"] == 0.0
        assert kpis["ytd_$_recaptured"] == 0.0
        assert kpis["ye_projected_$"] == 0.0
        assert kpis["closed_cohort_gaps"] == 0
        assert kpis["open_cohort_gaps"] == 0

    def test_open_count_excludes_closed(self) -> None:
        rows = [
            _gap(current_year=2026, status="open", resolved_at=None),
            _gap(current_year=2026, status="open", resolved_at=None),
            _gap(current_year=2026, status="recaptured",
                 created_at=datetime(2026, 1, 1),
                 resolved_at=datetime(2026, 2, 1)),
        ]
        with patch("app.services.recapture_decay.raf_cursor", _cursor_cm(rows)):
            kpis = get_velocity_kpis(tenant_id="1", year=2026, today=date(2026, 6, 30))
        assert kpis["open_cohort_gaps"] == 2
        assert kpis["closed_cohort_gaps"] == 1
        assert kpis["total_cohort_gaps"] == 3


# ===========================================================================
# 3. get_top_slow_movers
# ===========================================================================

class TestSlowMovers:
    def test_ranking_by_avg_days_to_close(self) -> None:
        rows = [
            # HCC 85 closed in 10 days
            _gap(current_year=2026, hcc_code="85",
                 created_at=datetime(2026, 1, 1),
                 resolved_at=datetime(2026, 1, 11)),
            # HCC 111 closed in 100 days
            _gap(current_year=2026, hcc_code="111",
                 created_at=datetime(2026, 1, 1),
                 resolved_at=datetime(2026, 4, 11)),
            # HCC 18 closed in 50 days
            _gap(current_year=2026, hcc_code="18",
                 created_at=datetime(2026, 1, 1),
                 resolved_at=datetime(2026, 2, 20)),
        ]
        with patch("app.services.recapture_decay.raf_cursor", _cursor_cm(rows)):
            res = get_top_slow_movers(tenant_id="1", year=2026, limit=10)
        codes = [r["hcc_code"] for r in res]
        assert codes == ["111", "18", "85"]
        assert res[0]["avg_days_to_close"] == pytest.approx(100.0)

    def test_no_closures_ranked_first(self) -> None:
        # HCC 85 has 100-day avg; HCC 999 has only open gaps (no avg)
        rows = [
            _gap(current_year=2026, hcc_code="85",
                 created_at=datetime(2026, 1, 1),
                 resolved_at=datetime(2026, 4, 11)),
            _gap(current_year=2026, hcc_code="999", status="open",
                 resolved_at=None, revenue_impact=3000),
            _gap(current_year=2026, hcc_code="999", status="open",
                 resolved_at=None, revenue_impact=3000),
        ]
        with patch("app.services.recapture_decay.raf_cursor", _cursor_cm(rows)):
            res = get_top_slow_movers(tenant_id="1", year=2026, limit=10)
        assert res[0]["hcc_code"] == "999"
        assert res[0]["avg_days_to_close"] is None
        assert res[0]["$_at_risk"] == pytest.approx(6000.0)
        assert res[0]["open_count"] == 2

    def test_limit_clamps_results(self) -> None:
        # 5 distinct HCCs, all with same speed → limit to 2
        rows = [
            _gap(current_year=2026, hcc_code=str(c),
                 created_at=datetime(2026, 1, 1),
                 resolved_at=datetime(2026, 2, 1))
            for c in [10, 11, 12, 13, 14]
        ]
        with patch("app.services.recapture_decay.raf_cursor", _cursor_cm(rows)):
            res = get_top_slow_movers(tenant_id="1", year=2026, limit=2)
        assert len(res) == 2

    def test_at_risk_only_counts_open(self) -> None:
        # One closed (3000) + one open (3000) for HCC 85 → at_risk = 3000
        rows = [
            _gap(current_year=2026, hcc_code="85", status="open",
                 resolved_at=None, revenue_impact=3000),
            _gap(current_year=2026, hcc_code="85",
                 created_at=datetime(2026, 1, 1),
                 resolved_at=datetime(2026, 2, 1),
                 revenue_impact=3000),
        ]
        with patch("app.services.recapture_decay.raf_cursor", _cursor_cm(rows)):
            res = get_top_slow_movers(tenant_id="1", year=2026, limit=10)
        row = next(r for r in res if r["hcc_code"] == "85")
        assert row["$_at_risk"] == pytest.approx(3000.0)
        assert row["open_count"] == 1
        assert row["closed_count"] == 1


# ===========================================================================
# 4. Internal helpers
# ===========================================================================

class TestHelpers:
    def test_safe_month_datetime(self) -> None:
        assert _safe_month(datetime(2026, 7, 15)) == 7

    def test_safe_month_iso_string(self) -> None:
        assert _safe_month("2026-07-15T10:00:00Z") == 7

    def test_safe_month_unparseable_falls_back_to_december(self) -> None:
        assert _safe_month("not a date") == 12
        assert _safe_month(None) == 12

    def test_coerce_dt_strips_tzinfo(self) -> None:
        dt = _coerce_dt("2026-01-15T10:00:00Z")
        assert dt is not None
        assert dt.tzinfo is None
        assert dt.month == 1

    def test_coerce_dt_handles_date(self) -> None:
        d = _coerce_dt(date(2026, 5, 1))
        assert d == datetime(2026, 5, 1)

    def test_median_odd(self) -> None:
        assert _median([1, 2, 3]) == 2

    def test_median_even(self) -> None:
        assert _median([1, 2, 3, 4]) == 2.5

    def test_median_empty(self) -> None:
        assert _median([]) == 0.0

    def test_is_leap_year(self) -> None:
        assert _is_leap(2024) is True
        assert _is_leap(2025) is False
        assert _is_leap(2000) is True
        assert _is_leap(1900) is False
