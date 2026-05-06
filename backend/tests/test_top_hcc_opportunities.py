"""
tests/test_top_hcc_opportunities.py — Top HCC Opportunities ranking tests.

Verifies the deterministic scoring math, ordering, the "missing" filter, peer
context, and the limit. All DB calls are mocked via unittest.mock — no
database is required.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.services import top_hcc_opportunities as svc
from app.services.provider_service import _HCC_BASE_RATE


# ---------------------------------------------------------------------------
# Fake DB harness — each call to raf_cursor() pops the next prepared response
# ---------------------------------------------------------------------------

class _FakeDB:
    """Sequenced cursor stub: each cursor block returns the next planned rows."""

    def __init__(self, plans: list[list[dict[str, Any]] | dict[str, Any] | None]):
        # plans entries: list[dict] for fetchall responses;
        #                 dict   for fetchone responses;
        #                 None  for empty
        self._plans = list(plans)
        self.calls: list[tuple[str, tuple]] = []

    def cursor_cm(self):
        plans = self._plans
        calls = self.calls

        @contextmanager
        def _cm(*args, **kwargs):
            cur = MagicMock()

            if not plans:
                next_plan: Any = []
            else:
                next_plan = plans.pop(0)

            def _exec(sql, params=()):
                calls.append((sql, tuple(params) if not isinstance(params, tuple) else params))

            cur.execute.side_effect = _exec

            if isinstance(next_plan, list):
                cur.fetchall.return_value = next_plan
                cur.fetchone.return_value = next_plan[0] if next_plan else None
            elif isinstance(next_plan, dict):
                cur.fetchone.return_value = next_plan
                cur.fetchall.return_value = [next_plan]
            else:
                cur.fetchall.return_value = []
                cur.fetchone.return_value = None

            yield cur

        return _cm


def _patch_active_subquery() -> Any:
    """Stub active_patients_subquery so it doesn't try to talk to OpenEMR."""
    return patch.object(
        svc,
        "active_patients_subquery",
        lambda tid: ("1=1", ()),
    )


# ===========================================================================
# 1. Empty / no-panel cases
# ===========================================================================

class TestEmptyCases:
    def test_no_panel_returns_empty(self):
        # Single cursor call (panel lookup) → empty list
        db = _FakeDB([[]])
        with _patch_active_subquery(), patch.object(svc, "raf_cursor", db.cursor_cm()):
            result = svc.compute_top_hccs(provider_id=1, year=2026)
        assert result == []

    def test_panel_with_no_open_suspects_returns_empty(self):
        # 1) panel ids   2) open suspects aggregated → empty
        db = _FakeDB([
            [{"patient_id": 100}, {"patient_id": 101}],
            [],  # _open_suspects_aggregated
        ])
        with _patch_active_subquery(), patch.object(svc, "raf_cursor", db.cursor_cm()):
            result = svc.compute_top_hccs(provider_id=1, year=2026)
        assert result == []


# ===========================================================================
# 2. Scoring math — deterministic verification
# ===========================================================================

class TestScoring:
    def test_expected_lift_formula(self):
        """expected_lift = patient_count * coefficient * BASE_RATE * avg_confidence"""
        # plan order — see compute_top_hccs body:
        #   1. _provider_panel
        #   2. _open_suspects_aggregated
        #   3. _coded_hccs_for_panel
        #   4. _coefficient_lookup
        #   5. peer: provider specialty fetch
        #   6. peer: peer ids list (empty so peer rate = None)
        plans = [
            [{"patient_id": 100}, {"patient_id": 101}, {"patient_id": 102}],
            [
                {"hcc_code": "108", "patient_count": 2, "avg_confidence": 0.80},
            ],
            [],  # no coded HCCs
            [{"hcc_code": 108, "coefficient": 0.300}],
            {"specialty": "Internal Medicine"},
            [],  # no peers
        ]
        db = _FakeDB(plans)
        with _patch_active_subquery(), patch.object(svc, "raf_cursor", db.cursor_cm()):
            result = svc.compute_top_hccs(provider_id=1, year=2026, limit=5)

        assert len(result) == 1
        row = result[0]
        assert row["hcc_code"] == "108"
        assert row["patient_count_missing"] == 2
        assert row["avg_confidence"] == 0.80
        assert row["raf_coefficient"] == 0.3
        # 2 * 0.3 * 12_000.0 * 0.80 = 5_760.00
        expected = 2 * 0.300 * _HCC_BASE_RATE * 0.80
        assert row["expected_lift"] == round(expected, 2)
        assert row["peer_capture_rate"] is None  # no peers

    def test_already_coded_hcc_excluded(self):
        """An HCC that's already coded for the panel must NOT be returned."""
        plans = [
            [{"patient_id": 100}, {"patient_id": 101}],
            [
                {"hcc_code": "108", "patient_count": 1, "avg_confidence": 0.9},
                {"hcc_code": "111", "patient_count": 2, "avg_confidence": 0.7},
            ],
            [{"hcc_code": "108"}],            # already coded
            [{"hcc_code": 111, "coefficient": 0.250}],
            {"specialty": "Cardiology"},
            [],
        ]
        db = _FakeDB(plans)
        with _patch_active_subquery(), patch.object(svc, "raf_cursor", db.cursor_cm()):
            result = svc.compute_top_hccs(provider_id=1, year=2026, limit=5)

        codes = [r["hcc_code"] for r in result]
        assert "108" not in codes
        assert "111" in codes

    def test_hcc_without_coefficient_is_dropped(self):
        """Unknown coefficient → score is zero; the row must be omitted."""
        plans = [
            [{"patient_id": 100}],
            [
                {"hcc_code": "999", "patient_count": 1, "avg_confidence": 0.95},
            ],
            [],
            [],  # no coefficient row returned for 999
            {"specialty": "Family Medicine"},
            [],
        ]
        db = _FakeDB(plans)
        with _patch_active_subquery(), patch.object(svc, "raf_cursor", db.cursor_cm()):
            result = svc.compute_top_hccs(provider_id=1, year=2026, limit=5)

        # All scored items dropped → empty list (peer fetch is also skipped
        # when the top is empty).
        assert result == []


# ===========================================================================
# 3. Ordering and limit
# ===========================================================================

class TestOrdering:
    def test_sorted_by_lift_desc_and_limited(self):
        # Three candidate HCCs, none coded; check ordering and limit=2
        plans = [
            [{"patient_id": 100}, {"patient_id": 101}, {"patient_id": 102}, {"patient_id": 103}],
            [
                # low score: 1 * 0.10 * 12000 * 0.5 = 600
                {"hcc_code": "10", "patient_count": 1, "avg_confidence": 0.5},
                # mid score: 2 * 0.20 * 12000 * 0.6 = 2880
                {"hcc_code": "20", "patient_count": 2, "avg_confidence": 0.6},
                # high score: 4 * 0.40 * 12000 * 0.9 = 17280
                {"hcc_code": "30", "patient_count": 4, "avg_confidence": 0.9},
            ],
            [],
            [
                {"hcc_code": 10, "coefficient": 0.10},
                {"hcc_code": 20, "coefficient": 0.20},
                {"hcc_code": 30, "coefficient": 0.40},
            ],
            {"specialty": "Cardiology"},
            [],
        ]
        db = _FakeDB(plans)
        with _patch_active_subquery(), patch.object(svc, "raf_cursor", db.cursor_cm()):
            result = svc.compute_top_hccs(provider_id=1, year=2026, limit=2)

        assert len(result) == 2
        assert result[0]["hcc_code"] == "30"
        assert result[1]["hcc_code"] == "20"
        # strictly descending
        assert result[0]["expected_lift"] > result[1]["expected_lift"]


# ===========================================================================
# 4. Peer capture rate
# ===========================================================================

class TestPeerCaptureRate:
    def test_peer_rate_averages_across_peers(self):
        """
        Two peers in same specialty.
          peer A: coded 1, suspect 1 → 0.5
          peer B: coded 3, suspect 1 → 0.75
        Average = 0.625.
        """
        plans = [
            # 1) provider panel
            [{"patient_id": 100}],
            # 2) open suspects aggregated
            [{"hcc_code": "85", "patient_count": 1, "avg_confidence": 1.0}],
            # 3) coded HCCs
            [],
            # 4) coefficient
            [{"hcc_code": 85, "coefficient": 0.300}],
            # 5) provider specialty
            {"specialty": "Cardiology"},
            # 6) peer ids
            [{"id": 2}, {"id": 3}],
            # peer A — panel
            [{"patient_id": 200}, {"patient_id": 201}],
            # peer A — coded counts
            [{"hcc_code": "85", "cnt": 1}],
            # peer A — suspect counts
            [{"hcc_code": "85", "cnt": 1}],
            # peer B — panel
            [{"patient_id": 300}, {"patient_id": 301}, {"patient_id": 302}, {"patient_id": 303}],
            # peer B — coded counts
            [{"hcc_code": "85", "cnt": 3}],
            # peer B — suspect counts
            [{"hcc_code": "85", "cnt": 1}],
        ]
        db = _FakeDB(plans)
        with _patch_active_subquery(), patch.object(svc, "raf_cursor", db.cursor_cm()):
            result = svc.compute_top_hccs(provider_id=1, year=2026, limit=5)

        assert len(result) == 1
        # (0.5 + 0.75) / 2 = 0.625
        assert result[0]["peer_capture_rate"] == pytest.approx(0.625, abs=1e-4)

    def test_peer_rate_none_when_no_signal(self):
        plans = [
            [{"patient_id": 100}],
            [{"hcc_code": "85", "patient_count": 1, "avg_confidence": 1.0}],
            [],
            [{"hcc_code": 85, "coefficient": 0.300}],
            {"specialty": "Cardiology"},
            [{"id": 2}],
            # peer panel
            [{"patient_id": 200}],
            # peer coded — none
            [],
            # peer suspects — none
            [],
        ]
        db = _FakeDB(plans)
        with _patch_active_subquery(), patch.object(svc, "raf_cursor", db.cursor_cm()):
            result = svc.compute_top_hccs(provider_id=1, year=2026, limit=5)

        assert len(result) == 1
        assert result[0]["peer_capture_rate"] is None
