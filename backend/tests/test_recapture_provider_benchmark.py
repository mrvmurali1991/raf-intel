"""
Tests for the provider peer benchmark on recapture rate.

Synthetic 5-provider panel with deterministic gap distributions verifies:
  * Per-provider rate math (closed / (open+closed))
  * Cohort percentile ranking + insufficient_peers (n<3) fallback
  * Sort order on the leaderboard (rate DESC, $-at-risk DESC tiebreak)
  * Quartile statistics (q1/median/q3) per specialty
  * Decay/trend math across multiple measurement years

All DB calls are mocked.  No live cursor required.
"""
from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from app.services import recapture_provider_benchmark as rpb


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cursor_cm(fetch_sequence):
    """Mock raf_cursor() that returns successive fetchall() results."""
    cursor = MagicMock()
    seq = list(fetch_sequence)
    state = {"i": 0}

    def _execute(*args, **kwargs):
        return None

    def _fetchall():
        if state["i"] >= len(seq):
            return []
        rows = seq[state["i"]]
        state["i"] += 1
        return list(rows)

    cursor.execute.side_effect = _execute
    cursor.fetchall.side_effect = _fetchall

    @contextmanager
    def _cm(*args, **kwargs):
        yield cursor

    return _cm, cursor


# ---------------------------------------------------------------------------
# Pure math
# ---------------------------------------------------------------------------


class TestPercentileMath:
    def test_top_value(self):
        assert rpb._percentile_rank(0.9, [0.1, 0.4, 0.6, 0.9]) == 100.0

    def test_bottom_value(self):
        assert rpb._percentile_rank(0.1, [0.1, 0.4, 0.6, 0.9]) == 25.0

    def test_empty_peers(self):
        assert rpb._percentile_rank(0.5, []) == 0.0

    def test_quartiles_basic(self):
        q1, med, q3 = rpb._quartiles([0.1, 0.2, 0.4, 0.6, 0.8])
        assert med == pytest.approx(0.4, abs=1e-3)
        assert q1 < med < q3

    def test_quartiles_single_value(self):
        q1, med, q3 = rpb._quartiles([0.5])
        assert q1 == med == q3 == 0.5


# ---------------------------------------------------------------------------
# compute_provider_rates — synthetic 5-provider panel
# ---------------------------------------------------------------------------


# 5 providers, 3 specialties (PCP has 3, Cards 1, Nephro 1).
PROVIDERS_FIXTURE = [
    {"id": 1, "npi": "1111111111", "full_name": "Dr. A", "specialty": "Family Medicine"},
    {"id": 2, "npi": "2222222222", "full_name": "Dr. B", "specialty": "Family Medicine"},
    {"id": 3, "npi": "3333333333", "full_name": "Dr. C", "specialty": "Family Medicine"},
    {"id": 4, "npi": "4444444444", "full_name": "Dr. D", "specialty": "Cardiology"},
    {"id": 5, "npi": "5555555555", "full_name": "Dr. E", "specialty": "Nephrology"},
]

PANEL_FIXTURE = [
    {"provider_id": 1, "panel_size": 10},
    {"provider_id": 2, "panel_size": 8},
    {"provider_id": 3, "panel_size": 12},
    {"provider_id": 4, "panel_size": 6},
    {"provider_id": 5, "panel_size": 4},
]

# Provider 1: 8 closed / 10 total = 80%
# Provider 2: 4 closed / 10 total = 40%
# Provider 3: 1 closed / 10 total = 10%
# Provider 4: 5 closed / 10 total = 50%
# Provider 5: 0 gaps (no entry)
GAPS_FIXTURE = [
    {"provider_id": 1, "total_gaps": 10, "gaps_open": 2, "gaps_closed": 8,
     "dollars_recaptured": 24000.0, "dollars_at_risk": 6000.0},
    {"provider_id": 2, "total_gaps": 10, "gaps_open": 6, "gaps_closed": 4,
     "dollars_recaptured": 12000.0, "dollars_at_risk": 18000.0},
    {"provider_id": 3, "total_gaps": 10, "gaps_open": 9, "gaps_closed": 1,
     "dollars_recaptured": 3000.0, "dollars_at_risk": 27000.0},
    {"provider_id": 4, "total_gaps": 10, "gaps_open": 5, "gaps_closed": 5,
     "dollars_recaptured": 15000.0, "dollars_at_risk": 15000.0},
]


class TestComputeProviderRates:
    def test_rates_and_sort_order(self):
        cm, _ = _cursor_cm([PROVIDERS_FIXTURE, PANEL_FIXTURE, GAPS_FIXTURE])
        with patch.object(rpb, "raf_cursor", cm):
            rows = rpb.compute_provider_rates(tenant_id=1, year=2026)

        assert len(rows) == 5
        # Order: rate DESC, at-risk DESC tiebreak
        # 1: 80%, 4: 50%, 2: 40%, 3: 10%, 5: 0%
        assert [r["provider_id"] for r in rows] == [1, 4, 2, 3, 5]

        # Provider 1 math
        p1 = rows[0]
        assert p1["recapture_rate"] == pytest.approx(0.8, abs=1e-4)
        assert p1["gaps_open"] == 2
        assert p1["gaps_closed"] == 8
        assert p1["$_recaptured"] == 24000.0
        assert p1["$_at_risk"] == 6000.0
        assert p1["panel_size"] == 10

        # Zero-gap provider gets a 0% rate, not crash
        p5 = rows[-1]
        assert p5["provider_id"] == 5
        assert p5["recapture_rate"] == 0.0
        assert p5["total_gaps"] == 0
        assert p5["panel_size"] == 4

    def test_rate_zero_when_no_gaps(self):
        # All providers have zero gaps
        cm, _ = _cursor_cm([PROVIDERS_FIXTURE, PANEL_FIXTURE, []])
        with patch.object(rpb, "raf_cursor", cm):
            rows = rpb.compute_provider_rates(tenant_id=1, year=2026)
        for r in rows:
            assert r["recapture_rate"] == 0.0
            assert r["total_gaps"] == 0


class TestComputeSpecialtyCohorts:
    def test_quartiles_within_specialty(self):
        cm, _ = _cursor_cm([
            PROVIDERS_FIXTURE, PANEL_FIXTURE, GAPS_FIXTURE,  # leaderboard call 1 (compute_provider_rates)
        ])
        with patch.object(rpb, "raf_cursor", cm):
            cohorts = rpb.compute_specialty_cohorts(tenant_id=1, year=2026)

        # Family Medicine has providers 1 (80%), 2 (40%), 3 (10%) — n=3
        fm = cohorts["Family Medicine"]
        assert fm["n"] == 3
        # Median rate of [0.10, 0.40, 0.80]
        assert fm["median_rate"] == pytest.approx(0.40, abs=1e-4)
        assert fm["top_provider"]["provider_id"] == 1
        assert fm["top_provider"]["recapture_rate"] == pytest.approx(0.80, abs=1e-4)

        # Cardiology has only provider 4 (50%) — n=1, still emitted
        card = cohorts["Cardiology"]
        assert card["n"] == 1
        assert card["median_rate"] == pytest.approx(0.50, abs=1e-4)

        # Nephrology had no gaps so it should be excluded entirely
        assert "Nephrology" not in cohorts


class TestProviderPercentile:
    def test_percentile_in_specialty(self):
        # First call: compute_provider_rates → 3 fetchall
        cm, _ = _cursor_cm([PROVIDERS_FIXTURE, PANEL_FIXTURE, GAPS_FIXTURE])
        with patch.object(rpb, "raf_cursor", cm):
            res = rpb.provider_percentile(provider_id=1, tenant_id=1, year=2026)

        assert res["provider_id"] == 1
        assert res["recapture_rate"] == pytest.approx(0.80, abs=1e-4)
        # Specialty (Family Medicine) has 3 members with rates 0.80, 0.40, 0.10
        # Provider 1 is at top → 100th percentile
        assert res["insufficient_peers"] is False
        assert res["percentile_in_specialty"] == 100.0
        assert res["ranks_among_n"] == 3
        assert res["specialty_median"] == pytest.approx(0.40, abs=1e-4)
        # Network has 4 active members; provider 1 still at top → 100
        assert res["percentile_in_network"] == 100.0

    def test_insufficient_peers_for_solo_specialty(self):
        cm, _ = _cursor_cm([PROVIDERS_FIXTURE, PANEL_FIXTURE, GAPS_FIXTURE])
        with patch.object(rpb, "raf_cursor", cm):
            res = rpb.provider_percentile(provider_id=4, tenant_id=1, year=2026)
        # Cardiology has n=1 → insufficient_peers
        assert res["insufficient_peers"] is True
        assert res["percentile_in_specialty"] is None
        assert res["specialty_median"] is None
        assert res["ranks_among_n"] == 1
        # Network has n=4, still computes
        assert res["percentile_in_network"] is not None

    def test_unknown_provider_falls_back(self):
        cm, _ = _cursor_cm([PROVIDERS_FIXTURE, PANEL_FIXTURE, GAPS_FIXTURE])
        with patch.object(rpb, "raf_cursor", cm):
            res = rpb.provider_percentile(provider_id=999, tenant_id=1, year=2026)
        assert res["provider_id"] == 999
        assert res["insufficient_peers"] is True
        assert res["percentile_in_specialty"] is None


# ---------------------------------------------------------------------------
# provider_decay
# ---------------------------------------------------------------------------


class TestProviderDecay:
    def test_three_year_lookback(self):
        rows = [
            {"yr": 2024, "gaps_total": 10, "gaps_closed": 4},
            {"yr": 2025, "gaps_total": 10, "gaps_closed": 6},
            {"yr": 2026, "gaps_total": 10, "gaps_closed": 8},
        ]
        cm, _ = _cursor_cm([rows])
        with patch.object(rpb, "raf_cursor", cm):
            res = rpb.provider_decay(provider_id=1, year=2026, lookback=3, tenant_id=1)

        assert res["years"] == [2024, 2025, 2026]
        assert res["rates"] == [0.4, 0.6, 0.8]
        assert res["deltas"] == [None, pytest.approx(0.2, abs=1e-4), pytest.approx(0.2, abs=1e-4)]

    def test_missing_year_zero_filled(self):
        rows = [
            {"yr": 2026, "gaps_total": 10, "gaps_closed": 5},
        ]
        cm, _ = _cursor_cm([rows])
        with patch.object(rpb, "raf_cursor", cm):
            res = rpb.provider_decay(provider_id=1, year=2026, lookback=3, tenant_id=1)
        assert res["years"] == [2024, 2025, 2026]
        assert res["rates"] == [0.0, 0.0, 0.5]


# ---------------------------------------------------------------------------
# provider_unrecaptured_top_hccs
# ---------------------------------------------------------------------------


class TestUnrecapturedTopHccs:
    def test_orders_by_at_risk(self):
        rows = [
            {"hcc_code": "85", "patient_count": 3, "dollars_at_risk": 9000.0},
            {"hcc_code": "18", "patient_count": 2, "dollars_at_risk": 6000.0},
            {"hcc_code": "111", "patient_count": 1, "dollars_at_risk": 3000.0},
        ]
        cm, _ = _cursor_cm([rows])
        with patch.object(rpb, "raf_cursor", cm):
            res = rpb.provider_unrecaptured_top_hccs(
                provider_id=1, tenant_id=1, year=2026, limit=3,
            )
        assert [r["hcc_code"] for r in res] == ["85", "18", "111"]
        assert res[0]["$_at_risk"] == 9000.0
        assert res[0]["count"] == 3
