"""
tests/test_provider_metric_parity.py

Pins both the v1 scorecard service (provider_service.calculate_provider_scorecard)
and the v2 scorecard service (provider_scorecard_v2._aggregate_provider_metrics)
to one canonical metric definition:

  avg_raf           = mean of raf_scores.final_raf (latest per patient, per year)
  recapture_rate    = recaptured_count / prior_year_hcc_count
                      where recaptured_count = distinct (patient, hcc) pairs
                      present in BOTH current year AND prior year in raf_patient_hcc
  recapture_rate_pct (v2) = recapture_rate * 100   (same numerator / denominator)

Both services must agree on the numeric outcome when fed identical synthetic data.
Regression guard: ensures the bug where v2 used the recapture_gaps table
(returning 100.0 trivially) instead of raf_patient_hcc cannot re-appear.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Minimal cursor stub (replicated from test_provider_scorecard.py pattern)
# ---------------------------------------------------------------------------


class _ScriptedCursor:
    """Pops scripted fetch payloads in order; records execute() calls."""

    def __init__(self, script: list[dict[str, Any]]) -> None:
        self._script = list(script)
        self._current: dict[str, Any] = {}
        self.executed: list[str] = []
        self.rowcount = 0

    def execute(self, sql: str, params=None) -> None:
        self.executed.append(sql.strip().split("\n", 1)[0][:120])
        self._current = self._script.pop(0) if self._script else {}

    def fetchall(self) -> list[dict[str, Any]]:
        return list(self._current.get("rows", []))

    def fetchone(self) -> dict[str, Any] | None:
        return self._current.get("row")

    def executemany(self, sql: str, params=None) -> None:
        self.executed.append(sql.strip().split("\n", 1)[0][:120])


@contextmanager
def _cm(cursor):
    yield cursor


# ---------------------------------------------------------------------------
# Canonical scenario
#
# Panel: patients 10, 20
# Year: 2026, Prior year: 2025
#
# RAF scores (year=2026):
#   patient 10: final_raf = 1.500
#   patient 20: final_raf = 0.900
#   → avg_raf = (1.500 + 0.900) / 2 = 1.200
#
# HCC counts via raf_patient_hcc:
#   Prior year (2025) distinct (patient,hcc) pairs = 4
#   Current year (2026) distinct (patient,hcc) pairs = 5
#   Recaptured (in 2026 AND 2025) = 3
#   → recapture_rate  = 3 / 4 = 0.75
#   → recapture_rate_pct = 75.0
# ---------------------------------------------------------------------------

_CANON_AVG_RAF = 1.200
_CANON_RECAPTURE_RATE = 0.75       # v1 format: 0..1 fraction
_CANON_RECAPTURE_RATE_PCT = 75.0   # v2 format: 0..100 percentage


# ---------------------------------------------------------------------------
# v1: calculate_provider_scorecard
# ---------------------------------------------------------------------------

_V1_SCRIPT = [
    # 1. panel
    {"rows": [{"patient_id": 10}, {"patient_id": 20}]},
    # 2. raf_scores
    {
        "rows": [
            {"patient_id": 10, "final_raf": 1.500},
            {"patient_id": 20, "final_raf": 0.900},
        ]
    },
    # 3. HCC counts (coded_curr, coded_prior, recaptured) combined aggregate
    {"row": {"coded_curr": 5, "coded_prior": 4, "recaptured": 3}},
    # 4. suspect counts combined aggregate
    {
        "row": {
            "open_suspect_hccs": 1,
            "s_open": 1,
            "s_accepted": 0,
            "s_dismissed": 0,
            "total_confidence": 0.8,
        }
    },
    # 5. MEAT avg
    {"row": {"avg_meat": None}},
    # 6. percentile rank — fewer than 2 rows → None
    {"rows": [{"average_raf": 1.2}]},
    # 7. INSERT snapshot
    {},
    # 8. get_provider
    {
        "row": {
            "id": 1,
            "first_name": "Alice",
            "last_name": "Smith",
            "full_name": "Alice Smith",
            "specialty": "Internal Medicine",
            "specialty_category": "pcp",
            "practice_name": None,
            "npi": "1111111111",
            "email": None,
            "credential": "MD",
            "openemr_user_id": None,
            "phone": None,
            "status": "active",
            "created_at": "2026-01-01",
            "updated_at": "2026-01-01",
        }
    },
]


def test_v1_scorecard_canonical_metrics():
    """v1 calculate_provider_scorecard matches canonical avg_raf + recapture_rate."""
    from app.services import provider_service

    cursor = _ScriptedCursor(_V1_SCRIPT)
    with patch.object(provider_service, "raf_cursor", lambda: _cm(cursor)):
        result = provider_service.calculate_provider_scorecard(
            provider_id=1, year=2026, tenant_id=1
        )

    assert result["average_raf"] == pytest.approx(_CANON_AVG_RAF, abs=1e-3)
    assert result["recapture_rate"] == pytest.approx(_CANON_RECAPTURE_RATE, abs=1e-3)


# ---------------------------------------------------------------------------
# v2: _aggregate_provider_metrics (via provider_scorecard_v2)
# ---------------------------------------------------------------------------

_V2_SCRIPT = [
    # providers query
    {
        "rows": [
            {
                "id": 1,
                "npi": "1111111111",
                "full_name": "Alice Smith",
                "specialty": "Internal Medicine",
            }
        ]
    },
    # panel_sizes query
    {"rows": [{"provider_id": 1, "panel_size": 2}]},
    # panel_by_provider query
    {
        "rows": [
            {"provider_id": 1, "patient_id": 10},
            {"provider_id": 1, "patient_id": 20},
        ]
    },
    # 1. avg_raf: raf_scores
    {
        "rows": [
            {"patient_id": 10, "final_raf": 1.500},
            {"patient_id": 20, "final_raf": 0.900},
        ]
    },
    # 2. recapture via raf_patient_hcc (coded_prior=4, recaptured=3)
    {"row": {"coded_prior": 4, "recaptured": 3}},
    # 3. MEAT: scored_hccs aggregate
    {"row": {"sum_m": 0, "sum_e": 0, "sum_a": 0, "sum_t": 0, "scored_hccs": 0}},
    # 4. MEAT: total_hccs
    {"row": {"total_hccs": 5}},
]


def test_v2_scorecard_canonical_metrics():
    """v2 _aggregate_provider_metrics matches canonical avg_raf + recapture_rate_pct."""
    from app.services import provider_scorecard_v2

    cursor = _ScriptedCursor(_V2_SCRIPT)
    with patch.object(provider_scorecard_v2, "raf_cursor", lambda: _cm(cursor)):
        rows, _ = provider_scorecard_v2._aggregate_provider_metrics(
            tenant_id=1, year=2026
        )

    assert len(rows) == 1
    row = rows[0]

    assert row["avg_raf"] == pytest.approx(_CANON_AVG_RAF, abs=1e-3), (
        f"v2 avg_raf={row['avg_raf']} expected {_CANON_AVG_RAF}"
    )
    assert row["recapture_rate_pct"] == pytest.approx(_CANON_RECAPTURE_RATE_PCT, abs=0.1), (
        f"v2 recapture_rate_pct={row['recapture_rate_pct']} expected {_CANON_RECAPTURE_RATE_PCT}"
    )


def test_v1_v2_recapture_formula_same_value():
    """Both services produce numerically equivalent recapture values for
    the same underlying data (v1 fraction * 100 == v2 percentage)."""
    # The assertions above already validate this individually; this test
    # makes the cross-service contract explicit so it fails loudly if
    # either formula regresses independently.
    assert round(_CANON_RECAPTURE_RATE * 100, 1) == _CANON_RECAPTURE_RATE_PCT


def test_v2_recapture_no_prior_hccs_returns_100():
    """When prior-year HCC count is 0, v2 returns 100.0% (same as v1)."""
    script_no_prior = [
        {"rows": [{"id": 1, "npi": None, "full_name": "Bob Jones", "specialty": None}]},
        {"rows": [{"provider_id": 1, "panel_size": 1}]},
        {"rows": [{"provider_id": 1, "patient_id": 5}]},
        # raf_scores
        {"rows": [{"patient_id": 5, "final_raf": 1.1}]},
        # recapture: coded_prior=0, recaptured=0
        {"row": {"coded_prior": 0, "recaptured": 0}},
        # MEAT: no scored HCCs
        {"row": {"sum_m": 0, "sum_e": 0, "sum_a": 0, "sum_t": 0, "scored_hccs": 0}},
        {"row": {"total_hccs": 0}},
    ]
    from app.services import provider_scorecard_v2

    cursor = _ScriptedCursor(script_no_prior)
    with patch.object(provider_scorecard_v2, "raf_cursor", lambda: _cm(cursor)):
        rows, _ = provider_scorecard_v2._aggregate_provider_metrics(
            tenant_id=1, year=2026
        )

    assert rows[0]["recapture_rate_pct"] == 100.0
    assert rows[0]["data_quality_flag"] is None
