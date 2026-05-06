"""
tests/test_recapture_cfo_forecast.py — CFO forecasting service test suite.

Covers:
- Linear extrapolation forecast math (YTD ÷ days × days_in_year)
- Variance vs. budget calculation
- Monthly aggregation (12 buckets, dollar totals)
- Top 3 condition / provider rollups
- Audit risk flag heuristic
- CSV export shape (header row + 12 month rows)
- JSON export shape

All DB calls are mocked — no live database is required.
"""

from __future__ import annotations

import csv
import io
import json
from contextlib import contextmanager
from datetime import date, datetime
from unittest.mock import MagicMock, patch

import pytest
from app.services.recapture_cfo_forecast import (
    _CSV_HEADERS,
    export_for_bi,
    get_executive_summary,
    get_year_over_year_trend,
)
from app.services.recapture_gap_service import _REVENUE_IMPACT_PER_GAP


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_cm(rows: list[dict]):
    """Return a context-manager that yields a cursor over *rows*."""
    cursor = MagicMock()
    cursor.fetchall.return_value = list(rows)
    cursor.fetchone.return_value = (rows[0] if rows else None)
    cursor.rowcount = len(rows)

    @contextmanager
    def _cm(*args, **kwargs):
        yield cursor

    return _cm, cursor


def _row(
    *,
    status: str = "open",
    hcc_code: str = "85",
    icd10_code: str = "I50.9",
    revenue_impact: float = 3000.0,
    created_at: datetime | None = None,
    resolved_at: datetime | None = None,
    provider_npi: str = "1234567890",
) -> dict:
    return {
        "id": 1,
        "patient_id": "p1",
        "tenant_id": "1",
        "hcc_code": hcc_code,
        "icd10_code": icd10_code,
        "prior_year": 2025,
        "current_year": 2026,
        "status": status,
        "last_encounter_date": None,
        "provider_npi": provider_npi,
        "revenue_impact": revenue_impact,
        "resolved_at": resolved_at,
        "resolved_by": None,
        "created_at": created_at or datetime(2026, 1, 15, 10, 0, 0),
        "updated_at": datetime(2026, 1, 15, 10, 0, 0),
    }


# ===========================================================================
# 1. get_executive_summary — top-level shape
# ===========================================================================


def test_summary_shape_has_required_keys():
    cm, _ = _make_cm([])
    with patch("app.services.recapture_cfo_forecast.raf_cursor", cm):
        out = get_executive_summary("1", 2026, today=date(2026, 7, 2))

    for key in [
        "year", "generated_at", "total_gaps_open", "total_dollars_at_risk",
        "ytd_dollars_recaptured", "ytd_closures", "ytd_velocity_per_day",
        "budget_dollars", "forecast_ye_dollars", "variance_to_budget",
        "month_breakdown", "quarter_breakdown",
        "top_3_recaptured_conditions", "top_3_at_risk_conditions",
        "top_3_provider_contributors", "audit_risk_flag",
    ]:
        assert key in out, f"missing key: {key}"

    assert out["year"] == 2026
    assert len(out["month_breakdown"]) == 12
    assert len(out["quarter_breakdown"]) == 4


def test_summary_empty_db_yields_zeros():
    cm, _ = _make_cm([])
    with patch("app.services.recapture_cfo_forecast.raf_cursor", cm):
        out = get_executive_summary("1", 2026, today=date(2026, 7, 2))

    assert out["total_gaps_open"] == 0
    assert out["total_dollars_at_risk"] == 0.0
    assert out["ytd_dollars_recaptured"] == 0.0
    assert out["forecast_ye_dollars"] == 0.0
    assert out["variance_to_budget"] == 0.0
    assert out["audit_risk_flag"] is False  # no rows = no flag


# ===========================================================================
# 2. Linear extrapolation forecast math
# ===========================================================================


def test_forecast_linear_extrapolation():
    """4 closed gaps × $3000 = $12 000 in 100 days → $43 800 projection."""
    rows = [
        _row(
            status="recaptured",
            revenue_impact=3000.0,
            created_at=datetime(2026, 1, 1, 8, 0, 0),
            resolved_at=datetime(2026, 2, 1, 8, 0, 0),
        )
        for _ in range(4)
    ]
    cm, _ = _make_cm(rows)
    with patch("app.services.recapture_cfo_forecast.raf_cursor", cm):
        out = get_executive_summary("1", 2026, today=date(2026, 4, 10))

    # Day 100 of 2026 (non-leap, 365 days)
    assert out["days_elapsed"] == 100
    assert out["days_in_year"] == 365
    assert out["ytd_dollars_recaptured"] == 12000.0
    expected = round(12000.0 / 100 * 365, 2)
    assert out["forecast_ye_dollars"] == expected  # 43800.0
    assert out["ytd_velocity_per_day"] == 120.0


def test_forecast_zero_days_elapsed_is_safe():
    """Future year (today before Jan 1) must not divide by zero."""
    cm, _ = _make_cm([])
    with patch("app.services.recapture_cfo_forecast.raf_cursor", cm):
        out = get_executive_summary("1", 2030, today=date(2026, 1, 1))
    assert out["forecast_ye_dollars"] == 0.0
    assert out["ytd_velocity_per_day"] == 0.0


# ===========================================================================
# 3. Variance vs. budget
# ===========================================================================


def test_variance_against_budget():
    """Budget = (open + closed) × $3000; variance = forecast − budget."""
    rows = (
        # 5 open gaps
        [_row(status="open", revenue_impact=3000.0) for _ in range(5)]
        + [
            _row(
                status="recaptured",
                revenue_impact=3000.0,
                created_at=datetime(2026, 1, 1),
                resolved_at=datetime(2026, 2, 1),
            )
            for _ in range(2)
        ]
    )
    cm, _ = _make_cm(rows)
    with patch("app.services.recapture_cfo_forecast.raf_cursor", cm):
        out = get_executive_summary("1", 2026, today=date(2026, 4, 10))

    expected_budget = (5 + 2) * float(_REVENUE_IMPACT_PER_GAP)
    assert out["budget_dollars"] == expected_budget  # 21 000
    assert out["variance_to_budget"] == round(
        out["forecast_ye_dollars"] - expected_budget, 2
    )


# ===========================================================================
# 4. Monthly aggregation
# ===========================================================================


def test_month_breakdown_buckets_correctly():
    rows = [
        _row(status="open", revenue_impact=3000.0,
             created_at=datetime(2026, 1, 5)),
        _row(status="open", revenue_impact=3000.0,
             created_at=datetime(2026, 3, 20)),
        _row(
            status="recaptured", revenue_impact=3000.0,
            created_at=datetime(2026, 1, 1),
            resolved_at=datetime(2026, 2, 14),
        ),
    ]
    cm, _ = _make_cm(rows)
    with patch("app.services.recapture_cfo_forecast.raf_cursor", cm):
        out = get_executive_summary("1", 2026, today=date(2026, 4, 10))

    months = {m["month"]: m for m in out["month_breakdown"]}
    assert months[1]["opened"] == 2  # Jan: 1 open + 1 recaptured (created in Jan)
    assert months[1]["remaining_dollars"] == 3000.0  # only the still-open one
    assert months[2]["closed"] == 1
    assert months[2]["recaptured_dollars"] == 3000.0
    assert months[3]["opened"] == 1
    assert months[3]["remaining_dollars"] == 3000.0


def test_quarter_breakdown_sums_months():
    rows = [
        _row(status="open", revenue_impact=3000.0,
             created_at=datetime(2026, 2, 5)),
        _row(status="open", revenue_impact=3000.0,
             created_at=datetime(2026, 5, 5)),
    ]
    cm, _ = _make_cm(rows)
    with patch("app.services.recapture_cfo_forecast.raf_cursor", cm):
        out = get_executive_summary("1", 2026, today=date(2026, 6, 1))

    qs = {q["quarter"]: q for q in out["quarter_breakdown"]}
    assert qs["Q1"]["opened"] == 1
    assert qs["Q2"]["opened"] == 1
    assert qs["Q3"]["opened"] == 0
    assert qs["Q4"]["opened"] == 0


# ===========================================================================
# 5. Top conditions / providers
# ===========================================================================


def test_top_3_recaptured_conditions_sorted_by_dollars():
    rows = [
        _row(status="recaptured", hcc_code="85", revenue_impact=3000.0,
             created_at=datetime(2026, 1, 1), resolved_at=datetime(2026, 2, 1)),
        _row(status="recaptured", hcc_code="85", revenue_impact=3000.0,
             created_at=datetime(2026, 1, 1), resolved_at=datetime(2026, 2, 1)),
        _row(status="recaptured", hcc_code="19", revenue_impact=3000.0,
             created_at=datetime(2026, 1, 1), resolved_at=datetime(2026, 2, 1)),
    ]
    cm, _ = _make_cm(rows)
    with patch("app.services.recapture_cfo_forecast.raf_cursor", cm):
        out = get_executive_summary("1", 2026, today=date(2026, 4, 1))

    top = out["top_3_recaptured_conditions"]
    assert len(top) == 2  # only 2 distinct HCCs
    assert top[0]["hcc_code"] == "85"
    assert top[0]["count"] == 2
    assert top[0]["dollars"] == 6000.0


# ===========================================================================
# 6. Audit risk flag heuristic
# ===========================================================================


def test_audit_risk_flag_true_when_low_dual_coding():
    rows = [
        _row(status="open", icd10_code="", hcc_code="85") for _ in range(20)
    ]
    rows.append(_row(status="open", icd10_code="I50.9", hcc_code="85"))  # 1/21 ~4.76%
    cm, _ = _make_cm(rows)
    with patch("app.services.recapture_cfo_forecast.raf_cursor", cm):
        out = get_executive_summary("1", 2026, today=date(2026, 6, 1))

    assert out["audit_risk_flag"] is True
    assert out["audit_dual_coded_pct"] < 10.0


def test_audit_risk_flag_false_when_high_dual_coding():
    rows = [_row(status="open", icd10_code="I50.9", hcc_code="85") for _ in range(10)]
    cm, _ = _make_cm(rows)
    with patch("app.services.recapture_cfo_forecast.raf_cursor", cm):
        out = get_executive_summary("1", 2026, today=date(2026, 6, 1))
    assert out["audit_risk_flag"] is False


# ===========================================================================
# 7. CSV export shape
# ===========================================================================


def test_csv_export_has_correct_header_and_12_rows():
    cm, _ = _make_cm([])
    with patch("app.services.recapture_cfo_forecast.raf_cursor", cm):
        content, mime = export_for_bi("1", 2026, format="csv",
                                      today=date(2026, 4, 1))

    assert mime == "text/csv"
    reader = csv.reader(io.StringIO(content))
    rows = list(reader)
    assert rows[0] == _CSV_HEADERS
    # 1 header + 12 month rows = 13
    assert len(rows) == 13


def test_json_export_returns_list_of_12():
    cm, _ = _make_cm([])
    with patch("app.services.recapture_cfo_forecast.raf_cursor", cm):
        content, mime = export_for_bi("1", 2026, format="json",
                                      today=date(2026, 4, 1))
    assert mime == "application/json"
    parsed = json.loads(content)
    assert isinstance(parsed, list)
    assert len(parsed) == 12
    assert {"year", "month", "opened", "closed",
            "recaptured_$", "remaining_$"} <= set(parsed[0].keys())


def test_export_unknown_format_raises():
    cm, _ = _make_cm([])
    with patch("app.services.recapture_cfo_forecast.raf_cursor", cm):
        with pytest.raises(ValueError):
            export_for_bi("1", 2026, format="xml")


# ===========================================================================
# 8. YoY trend
# ===========================================================================


def test_yoy_returns_requested_year_window():
    cm, _ = _make_cm([])
    with patch("app.services.recapture_cfo_forecast.raf_cursor", cm):
        out = get_year_over_year_trend("1", years_back=3, today=date(2026, 6, 1))
    assert out["years_back"] == 3
    years = [r["year"] for r in out["series"]]
    assert years == [2024, 2025, 2026]
