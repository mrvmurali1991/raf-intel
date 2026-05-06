"""
Unit tests for the provider revenue opportunity breakdown service.

Verifies the deterministic 3-bucket math (Recapture / MEAT improvement /
New suspects) with synthetic suspects + prior-year HCCs + MEAT scores.

Run with:
    cd backend && python -m pytest tests/test_provider_revenue_breakdown.py -v
"""
from __future__ import annotations

import os
import sys
from unittest.mock import patch

import pytest

# Make app importable without installing
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ---------------------------------------------------------------------------
# Helpers — patch every DB-touching helper so the test runs offline
# ---------------------------------------------------------------------------

def _run_with_fixtures(
    *,
    panel: list[int],
    coded: list[dict],
    prior_unrecap: list[dict],
    suspects: list[dict],
    coeffs: dict[int, float],
    meat_scores: dict[int, float],
    labels: dict[int, str] | None = None,
    persistence: float = 0.85,
    meat_threshold: float = 0.75,
    year: int = 2026,
    provider_id: int = 99,
):
    """Run compute_breakdown with all data layers mocked."""
    import app.services.provider_revenue_breakdown as svc

    with patch.object(svc, "_provider_panel", return_value=panel), \
         patch.object(svc, "_coded_hccs_this_year", return_value=coded), \
         patch.object(svc, "_prior_year_unrecaptured", return_value=prior_unrecap), \
         patch.object(svc, "_open_suspects", return_value=suspects), \
         patch.object(svc, "_coefficient_lookup", return_value=coeffs), \
         patch.object(svc, "_hcc_label_lookup", return_value=labels or {}), \
         patch.object(
             svc,
             "_meat_score_by_phcc",
             return_value=meat_scores,
         ):
        return svc.compute_breakdown(
            provider_id,
            year,
            persistence=persistence,
            meat_threshold=meat_threshold,
        )


# ---------------------------------------------------------------------------
# 1. Empty panel → all-zero response (UI safe)
# ---------------------------------------------------------------------------

class TestEmptyPanel:
    def test_empty_panel_returns_zero_total(self):
        out = _run_with_fixtures(
            panel=[],
            coded=[],
            prior_unrecap=[],
            suspects=[],
            coeffs={},
            meat_scores={},
        )
        assert out["total"] == 0.0
        assert out["panel_size"] == 0
        names = [b["name"] for b in out["buckets"]]
        assert names == ["Recapture", "MEAT improvement", "New suspects"]
        assert all(b["amount"] == 0.0 for b in out["buckets"])
        assert all(b["count"] == 0 for b in out["buckets"])
        assert out["assumptions"]["base_rate"] == 12000.0


# ---------------------------------------------------------------------------
# 2. Recapture bucket math
#    Σ coef × (1 − persistence) × HCC_BASE_RATE
# ---------------------------------------------------------------------------

class TestRecaptureBucket:
    def test_single_unrecaptured_hcc(self):
        # coef 0.5, persistence 0.85 → risk_factor = 0.15
        # 0.5 × 0.15 × 12000 = 900
        out = _run_with_fixtures(
            panel=[1],
            coded=[],
            prior_unrecap=[{"patient_id": 1, "hcc_code": 108, "raf_coefficient": 0.5}],
            suspects=[],
            coeffs={108: 0.5},
            meat_scores={},
            persistence=0.85,
        )
        recap = next(b for b in out["buckets"] if b["name"] == "Recapture")
        assert recap["amount"] == pytest.approx(900.0, rel=1e-4)
        assert recap["count"] == 1
        assert out["total"] == pytest.approx(900.0, rel=1e-4)

    def test_multi_recapture_sums(self):
        out = _run_with_fixtures(
            panel=[1, 2],
            coded=[],
            prior_unrecap=[
                {"patient_id": 1, "hcc_code": 108, "raf_coefficient": 0.5},
                {"patient_id": 2, "hcc_code": 88, "raf_coefficient": 0.3},
            ],
            suspects=[],
            coeffs={108: 0.5, 88: 0.3},
            meat_scores={},
            persistence=0.85,
        )
        # (0.5 + 0.3) × 0.15 × 12000 = 1440
        recap = next(b for b in out["buckets"] if b["name"] == "Recapture")
        assert recap["amount"] == pytest.approx(1440.0, rel=1e-4)
        assert recap["count"] == 2

    def test_persistence_one_zeros_recapture(self):
        out = _run_with_fixtures(
            panel=[1],
            coded=[],
            prior_unrecap=[{"patient_id": 1, "hcc_code": 108, "raf_coefficient": 0.5}],
            suspects=[],
            coeffs={108: 0.5},
            meat_scores={},
            persistence=1.0,
        )
        recap = next(b for b in out["buckets"] if b["name"] == "Recapture")
        # risk_factor = 0 → bucket is 0 (and the row is skipped due to <=0 guard)
        assert recap["amount"] == 0.0
        assert recap["count"] == 0


# ---------------------------------------------------------------------------
# 3. MEAT improvement bucket math
#    Σ coef × (1 − meat_score) × HCC_BASE_RATE  for meat<threshold
# ---------------------------------------------------------------------------

class TestMeatImprovementBucket:
    def test_below_threshold_counts(self):
        # coef 0.4, meat 0.5, base 12000 → 0.4 × 0.5 × 12000 = 2400
        out = _run_with_fixtures(
            panel=[1],
            coded=[
                {"id": 10, "patient_id": 1, "hcc_code": 108, "raf_coefficient": 0.4},
            ],
            prior_unrecap=[],
            suspects=[],
            coeffs={108: 0.4},
            meat_scores={10: 0.5},
            meat_threshold=0.75,
        )
        meat = next(b for b in out["buckets"] if b["name"] == "MEAT improvement")
        assert meat["amount"] == pytest.approx(2400.0, rel=1e-4)
        assert meat["count"] == 1

    def test_at_or_above_threshold_skipped(self):
        out = _run_with_fixtures(
            panel=[1],
            coded=[
                {"id": 10, "patient_id": 1, "hcc_code": 108, "raf_coefficient": 0.4},
                {"id": 11, "patient_id": 1, "hcc_code": 88, "raf_coefficient": 0.4},
            ],
            prior_unrecap=[],
            suspects=[],
            coeffs={108: 0.4, 88: 0.4},
            meat_scores={10: 1.0, 11: 0.75},
            meat_threshold=0.75,
        )
        meat = next(b for b in out["buckets"] if b["name"] == "MEAT improvement")
        assert meat["amount"] == 0.0
        assert meat["count"] == 0

    def test_no_meat_score_treated_as_zero(self):
        # Missing MEAT row → assumed 0.0 → full coef × 1.0 × base
        out = _run_with_fixtures(
            panel=[1],
            coded=[{"id": 10, "patient_id": 1, "hcc_code": 108, "raf_coefficient": 0.25}],
            prior_unrecap=[],
            suspects=[],
            coeffs={108: 0.25},
            meat_scores={},  # nothing for phcc 10 → defaults to 0
            meat_threshold=0.75,
        )
        meat = next(b for b in out["buckets"] if b["name"] == "MEAT improvement")
        # 0.25 × 1.0 × 12000 = 3000
        assert meat["amount"] == pytest.approx(3000.0, rel=1e-4)
        assert meat["count"] == 1


# ---------------------------------------------------------------------------
# 4. New-suspects bucket math
#    Σ coef × confidence × HCC_BASE_RATE
# ---------------------------------------------------------------------------

class TestNewSuspectBucket:
    def test_confidence_scales_dollars(self):
        # coef 0.6, conf 0.8, base 12000 → 5760
        out = _run_with_fixtures(
            panel=[1],
            coded=[],
            prior_unrecap=[],
            suspects=[{"id": 1, "patient_id": 1, "suspect_hcc": 108, "confidence_score": 0.8}],
            coeffs={108: 0.6},
            meat_scores={},
        )
        sus = next(b for b in out["buckets"] if b["name"] == "New suspects")
        assert sus["amount"] == pytest.approx(5760.0, rel=1e-4)
        assert sus["count"] == 1

    def test_zero_confidence_is_skipped(self):
        out = _run_with_fixtures(
            panel=[1],
            coded=[],
            prior_unrecap=[],
            suspects=[{"id": 1, "patient_id": 1, "suspect_hcc": 108, "confidence_score": 0.0}],
            coeffs={108: 0.6},
            meat_scores={},
        )
        sus = next(b for b in out["buckets"] if b["name"] == "New suspects")
        assert sus["amount"] == 0.0
        assert sus["count"] == 0


# ---------------------------------------------------------------------------
# 5. Combined / total / percentages
# ---------------------------------------------------------------------------

class TestCombinedBreakdown:
    def test_total_is_sum_of_three_buckets_and_pcts_sum_to_100(self):
        # Recapture: 0.5 × 0.15 × 12000 = 900
        # MEAT:      0.4 × (1-0.5) × 12000 = 2400
        # Suspect:   0.6 × 0.5 × 12000 = 3600
        # Total: 6900
        out = _run_with_fixtures(
            panel=[1],
            coded=[{"id": 10, "patient_id": 1, "hcc_code": 88, "raf_coefficient": 0.4}],
            prior_unrecap=[
                {"patient_id": 1, "hcc_code": 108, "raf_coefficient": 0.5}
            ],
            suspects=[
                {"id": 1, "patient_id": 1, "suspect_hcc": 100, "confidence_score": 0.5}
            ],
            coeffs={88: 0.4, 100: 0.6, 108: 0.5},
            meat_scores={10: 0.5},
            persistence=0.85,
            meat_threshold=0.75,
        )
        amounts = {b["name"]: b["amount"] for b in out["buckets"]}
        assert amounts["Recapture"] == pytest.approx(900.0, rel=1e-4)
        assert amounts["MEAT improvement"] == pytest.approx(2400.0, rel=1e-4)
        assert amounts["New suspects"] == pytest.approx(3600.0, rel=1e-4)
        assert out["total"] == pytest.approx(6900.0, rel=1e-4)
        # percentages should sum to ~100
        pct_sum = sum(b["pct_of_total"] for b in out["buckets"])
        assert pct_sum == pytest.approx(100.0, abs=0.05)


# ---------------------------------------------------------------------------
# 6. top_3_hccs aggregation
# ---------------------------------------------------------------------------

class TestTopContributors:
    def test_top_3_aggregates_same_code(self):
        # Two patients both with HCC 108 prior-year unrecaptured →
        # top_3 should collapse to a single entry for HCC 108.
        out = _run_with_fixtures(
            panel=[1, 2],
            coded=[],
            prior_unrecap=[
                {"patient_id": 1, "hcc_code": 108, "raf_coefficient": 0.5},
                {"patient_id": 2, "hcc_code": 108, "raf_coefficient": 0.5},
                {"patient_id": 1, "hcc_code": 88,  "raf_coefficient": 0.3},
            ],
            suspects=[],
            coeffs={108: 0.5, 88: 0.3},
            meat_scores={},
            labels={108: "Heart failure", 88: "Diabetes"},
        )
        recap = next(b for b in out["buckets"] if b["name"] == "Recapture")
        codes = [t["hcc_code"] for t in recap["top_3_hccs"]]
        # 108 entry collapses two rows; HCC 108 must appear exactly once
        assert codes.count("108") == 1
        # HCC 108 should outrank 88 (1800 vs 540)
        assert recap["top_3_hccs"][0]["hcc_code"] == "108"
        assert recap["top_3_hccs"][0]["dollars"] == pytest.approx(1800.0, rel=1e-4)
        # Labels surface from the lookup
        assert recap["top_3_hccs"][0]["hcc_label"] == "Heart failure"

    def test_top_3_caps_at_three(self):
        rows = [
            {"patient_id": 1, "hcc_code": h, "raf_coefficient": 0.5}
            for h in (1, 2, 3, 4, 5)
        ]
        out = _run_with_fixtures(
            panel=[1],
            coded=[],
            prior_unrecap=rows,
            suspects=[],
            coeffs={1: 0.5, 2: 0.5, 3: 0.5, 4: 0.5, 5: 0.5},
            meat_scores={},
        )
        recap = next(b for b in out["buckets"] if b["name"] == "Recapture")
        assert len(recap["top_3_hccs"]) == 3


# ---------------------------------------------------------------------------
# 7. Assumptions / base rate import
# ---------------------------------------------------------------------------

class TestAssumptions:
    def test_base_rate_imported_from_provider_service(self):
        from app.services.provider_service import _HCC_BASE_RATE
        out = _run_with_fixtures(
            panel=[1],
            coded=[],
            prior_unrecap=[],
            suspects=[{"id": 1, "patient_id": 1, "suspect_hcc": 108,
                       "confidence_score": 1.0}],
            coeffs={108: 1.0},
            meat_scores={},
        )
        # coef 1.0 × confidence 1.0 → bucket amount equals exactly the base rate
        sus = next(b for b in out["buckets"] if b["name"] == "New suspects")
        assert sus["amount"] == pytest.approx(_HCC_BASE_RATE, rel=1e-4)
        assert out["assumptions"]["base_rate"] == _HCC_BASE_RATE
        assert out["assumptions"]["persistence"] == 0.85
        assert out["assumptions"]["meat_threshold"] == 0.75
