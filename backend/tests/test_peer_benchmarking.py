"""
tests/test_peer_benchmarking.py — Peer percentile + specialty benchmark tests.

All DB calls are mocked via unittest.mock — no DB or server required.
Coverage:
  * percentile math (correctness, sorting, ties)
  * cohort_summary (min/median/max, even/odd lengths)
  * insufficient_peers handling when cohort_size < 3
  * compute_percentiles end-to-end with mocked DB
  * specialty_benchmarks end-to-end shape
"""
from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from app.services import peer_benchmarking as pb


# ---------------------------------------------------------------------------
# Cursor mock helper
# ---------------------------------------------------------------------------

def _make_cursor_cm(fetch_sequence):
    """
    Returns (cm, cursor) where each cur.execute() call advances which
    fetchall() result is returned next.

    `fetch_sequence` is a list — one entry consumed per execute() call.
    """
    cursor = MagicMock()
    seq = list(fetch_sequence)
    state = {"i": 0}

    def _execute(*args, **kwargs):
        # nothing to do; fetchall picks the next batch
        pass

    def _fetchall():
        if state["i"] >= len(seq):
            return []
        rows = seq[state["i"]]
        state["i"] += 1
        return list(rows)

    def _fetchone():
        if state["i"] >= len(seq):
            return None
        rows = seq[state["i"]]
        state["i"] += 1
        return rows[0] if rows else None

    cursor.execute.side_effect = _execute
    cursor.fetchall.side_effect = _fetchall
    cursor.fetchone.side_effect = _fetchone

    @contextmanager
    def _cm(*args, **kwargs):
        yield cursor

    return _cm, cursor


# ---------------------------------------------------------------------------
# _percentile_rank — pure math
# ---------------------------------------------------------------------------

class TestPercentileRank:
    def test_top_value_yields_100(self):
        # value at top of cohort
        assert pb._percentile_rank(10.0, [1.0, 5.0, 7.0, 10.0]) == 100.0

    def test_bottom_value_yields_position(self):
        # value at bottom — only itself ≤ value out of 4 → 25
        assert pb._percentile_rank(1.0, [1.0, 5.0, 7.0, 10.0]) == 25.0

    def test_middle_value(self):
        # value 7 → rows ≤7: [1,5,7] = 3 of 4 → 75.0
        assert pb._percentile_rank(7.0, [1.0, 5.0, 7.0, 10.0]) == 75.0

    def test_empty_cohort_returns_zero(self):
        assert pb._percentile_rank(5.0, []) == 0.0

    def test_filters_none_values(self):
        # None peers shouldn't blow up
        assert pb._percentile_rank(5.0, [None, 5.0, None, 1.0]) == 100.0

    def test_handles_ties(self):
        # value 5 with two ties — both count as ≤
        assert pb._percentile_rank(5.0, [5.0, 5.0, 1.0, 9.0]) == 75.0


# ---------------------------------------------------------------------------
# _summary_stats
# ---------------------------------------------------------------------------

class TestSummaryStats:
    def test_empty(self):
        assert pb._summary_stats([]) == {
            "min": None, "median": None, "max": None,
        }

    def test_odd_length(self):
        s = pb._summary_stats([1.0, 3.0, 5.0])
        assert s == {"min": 1.0, "median": 3.0, "max": 5.0}

    def test_even_length(self):
        s = pb._summary_stats([1.0, 2.0, 3.0, 4.0])
        # median = (2+3)/2 = 2.5
        assert s == {"min": 1.0, "median": 2.5, "max": 4.0}

    def test_unsorted_input(self):
        s = pb._summary_stats([7.0, 1.0, 4.0])
        assert s == {"min": 1.0, "median": 4.0, "max": 7.0}


# ---------------------------------------------------------------------------
# compute_percentiles — integrated, with mocked DB
# ---------------------------------------------------------------------------

def _scorecard_row(provider_id, **overrides):
    base = {
        "provider_id": provider_id,
        "first_name": f"F{provider_id}",
        "last_name": f"L{provider_id}",
        "full_name": f"F{provider_id} L{provider_id}",
        "specialty": "Internal Medicine",
        "average_raf": 1.0,
        "hcc_capture_rate": 0.5,
        "recapture_rate": 0.5,
        "meat_completeness_avg": 0.5,
        "revenue_opportunity": 1000.0,
        "documentation_quality_score": 0.5,
        "percentile_rank": None,
        "total_patients": 100,
        "patients_with_scores": 80,
        "calculated_at": "2026-01-01T00:00:00",
    }
    base.update(overrides)
    return base


class TestComputePercentiles:
    def test_full_cohort_yields_percentiles(self):
        # 4 providers in cohort.  Provider id=2 has middle-ish RAF.
        cohort = [
            _scorecard_row(1, average_raf=2.0, hcc_capture_rate=0.9),
            _scorecard_row(2, average_raf=1.5, hcc_capture_rate=0.7),
            _scorecard_row(3, average_raf=1.0, hcc_capture_rate=0.5),
            _scorecard_row(4, average_raf=0.5, hcc_capture_rate=0.3),
        ]

        # Two execute calls happen: specialty lookup (fetchone), cohort fetchall.
        cm, _ = _make_cursor_cm([
            [{"specialty": "Internal Medicine"}],  # specialty lookup
            cohort,                                # cohort_snapshots
        ])

        with patch("app.services.peer_benchmarking.raf_cursor", cm):
            result = pb.compute_percentiles(provider_id=2, measurement_year=2026)

        assert result["specialty"] == "Internal Medicine"
        assert result["cohort_size"] == 4
        assert result["insufficient_peers"] is False
        # Provider 2 RAF = 1.5 → at-or-below = [1.5, 1.0, 0.5] = 3 of 4 → 75
        assert result["percentiles"]["average_raf"] == 75.0
        # Capture 0.7 → at-or-below = [0.7, 0.5, 0.3] = 3 of 4 → 75
        assert result["percentiles"]["hcc_capture_rate"] == 75.0
        # Cohort summary correctness
        assert result["cohort_summary"]["average_raf"]["min"] == 0.5
        assert result["cohort_summary"]["average_raf"]["max"] == 2.0

    def test_insufficient_cohort_marks_flag(self):
        # only 2 providers → below MIN_COHORT_SIZE
        cohort = [
            _scorecard_row(1, average_raf=2.0),
            _scorecard_row(2, average_raf=1.0),
        ]
        cm, _ = _make_cursor_cm([
            [{"specialty": "Cardiology"}],
            cohort,
        ])

        with patch("app.services.peer_benchmarking.raf_cursor", cm):
            result = pb.compute_percentiles(provider_id=2, measurement_year=2026)

        assert result["cohort_size"] == 2
        assert result["insufficient_peers"] is True
        # All percentile fields should be None
        assert all(v is None for v in result["percentiles"].values())
        # But cohort summary still computed
        assert result["cohort_summary"]["average_raf"]["min"] == 1.0
        assert result["cohort_summary"]["average_raf"]["max"] == 2.0
        # Provider's own KPI snapshot still populated
        assert result["provider_kpis"]["average_raf"] == 1.0

    def test_provider_specialty_unknown(self):
        # specialty lookup returns None → empty result
        cm, _ = _make_cursor_cm([[]])

        with patch("app.services.peer_benchmarking.raf_cursor", cm):
            result = pb.compute_percentiles(provider_id=99, measurement_year=2026)

        assert result["specialty"] is None
        assert result["cohort_size"] == 0
        assert result["insufficient_peers"] is True
        assert all(v is None for v in result["percentiles"].values())

    def test_provider_not_in_cohort(self):
        # Cohort returned but provider's own row missing — defensive path.
        cohort = [
            _scorecard_row(1, average_raf=2.0),
            _scorecard_row(3, average_raf=1.0),
            _scorecard_row(4, average_raf=0.5),
        ]
        cm, _ = _make_cursor_cm([
            [{"specialty": "Internal Medicine"}],
            cohort,
        ])
        with patch("app.services.peer_benchmarking.raf_cursor", cm):
            result = pb.compute_percentiles(provider_id=2, measurement_year=2026)

        assert result["cohort_size"] == 3
        # Provider not found → percentiles stay None even though cohort is large
        assert all(v is None for v in result["percentiles"].values())
        # provider_kpis stays at default None values
        assert result["provider_kpis"]["average_raf"] is None

    def test_handles_null_kpi_values(self):
        cohort = [
            _scorecard_row(1, average_raf=None, hcc_capture_rate=0.9),
            _scorecard_row(2, average_raf=1.5, hcc_capture_rate=None),
            _scorecard_row(3, average_raf=1.0, hcc_capture_rate=0.5),
            _scorecard_row(4, average_raf=0.5, hcc_capture_rate=0.3),
        ]
        cm, _ = _make_cursor_cm([
            [{"specialty": "Internal Medicine"}],
            cohort,
        ])
        with patch("app.services.peer_benchmarking.raf_cursor", cm):
            result = pb.compute_percentiles(provider_id=2, measurement_year=2026)

        # Provider 2 has no hcc_capture_rate → percentile stays None for it.
        assert result["percentiles"]["hcc_capture_rate"] is None
        # average_raf still computable (3 non-null peers incl. self)
        assert result["percentiles"]["average_raf"] is not None


# ---------------------------------------------------------------------------
# specialty_cohort_summary
# ---------------------------------------------------------------------------

class TestSpecialtyCohortSummary:
    def test_summary_shape(self):
        cohort = [
            _scorecard_row(1, average_raf=2.0),
            _scorecard_row(2, average_raf=1.5),
            _scorecard_row(3, average_raf=1.0),
        ]
        cm, _ = _make_cursor_cm([cohort])

        with patch("app.services.peer_benchmarking.raf_cursor", cm):
            result = pb.specialty_cohort_summary("Internal Medicine", 2026)

        assert result["specialty"] == "Internal Medicine"
        assert result["cohort_size"] == 3
        assert result["insufficient_peers"] is False
        assert result["cohort_summary"]["average_raf"]["min"] == 1.0
        assert result["cohort_summary"]["average_raf"]["max"] == 2.0
        assert result["cohort_summary"]["average_raf"]["median"] == 1.5

    def test_small_cohort_flags_insufficient(self):
        cohort = [
            _scorecard_row(1, average_raf=2.0),
            _scorecard_row(2, average_raf=1.5),
        ]
        cm, _ = _make_cursor_cm([cohort])

        with patch("app.services.peer_benchmarking.raf_cursor", cm):
            result = pb.specialty_cohort_summary("Cardiology", 2026)

        assert result["cohort_size"] == 2
        assert result["insufficient_peers"] is True


# ---------------------------------------------------------------------------
# specialty_benchmarks
# ---------------------------------------------------------------------------

class TestSpecialtyBenchmarks:
    def test_groups_specialties(self):
        # First execute returns distinct specialties
        # Then one cohort fetch per specialty
        im_cohort = [
            _scorecard_row(1, specialty="Internal Medicine", average_raf=2.0),
            _scorecard_row(2, specialty="Internal Medicine", average_raf=1.5),
            _scorecard_row(3, specialty="Internal Medicine", average_raf=1.0),
        ]
        cardio_cohort = [
            _scorecard_row(4, specialty="Cardiology", average_raf=3.0),
            _scorecard_row(5, specialty="Cardiology", average_raf=2.5),
        ]

        cm, _ = _make_cursor_cm([
            # _all_specialties
            [{"specialty": "Cardiology"}, {"specialty": "Internal Medicine"}],
            cardio_cohort,    # Cardiology
            im_cohort,        # Internal Medicine
        ])

        with patch("app.services.peer_benchmarking.raf_cursor", cm):
            result = pb.specialty_benchmarks(measurement_year=2026)

        assert result["measurement_year"] == 2026
        specs = {s["specialty"]: s for s in result["specialties"]}
        assert "Cardiology" in specs
        assert "Internal Medicine" in specs

        # Cardiology has only 2 → insufficient_peers
        assert specs["Cardiology"]["insufficient_peers"] is True
        # Cardiology providers should still appear with kpi values, percentiles None
        assert len(specs["Cardiology"]["providers"]) == 2
        assert all(
            p["percentiles"]["average_raf"] is None
            for p in specs["Cardiology"]["providers"]
        )

        # Internal Medicine has 3 → percentiles populated
        assert specs["Internal Medicine"]["insufficient_peers"] is False
        im_providers = {
            p["provider_id"]: p for p in specs["Internal Medicine"]["providers"]
        }
        # provider 1 has top RAF 2.0 → 100
        assert im_providers[1]["percentiles"]["average_raf"] == 100.0
        # provider 3 has bottom RAF 1.0 → 33.3
        assert im_providers[3]["percentiles"]["average_raf"] == pytest.approx(
            33.3, abs=0.1
        )
