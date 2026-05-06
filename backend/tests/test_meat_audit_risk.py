"""
Tests for app.services.meat_audit_risk.

Covers:
  * tier classification (ready / at_risk / audit_risk thresholds)
  * insufficient-data path (< 3 coded HCCs)
  * top-weak HCC ordering and the < 0.75 threshold
  * empty-panel short-circuit
  * components_missing labelling

DB calls are mocked via unittest.mock — no live DB required.
"""
from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from app.services.meat_audit_risk import (
    _classify_tier,
    _missing_components,
    assess_provider_audit_risk,
    get_meat_evidence_for_hcc,
)


# ---------------------------------------------------------------------------
# Pure helpers — no DB
# ---------------------------------------------------------------------------


class TestClassifyTier:
    """The risk-tier classification rules are the load-bearing logic of this
    feature; if these slip every CMO-facing badge is wrong."""

    def test_ready_at_threshold(self):
        assert _classify_tier(0.80, 5) == "ready"

    def test_ready_above_threshold(self):
        assert _classify_tier(0.95, 10) == "ready"

    def test_at_risk_at_threshold(self):
        assert _classify_tier(0.60, 5) == "at_risk"

    def test_at_risk_in_band(self):
        assert _classify_tier(0.79, 5) == "at_risk"

    def test_audit_risk_below_threshold(self):
        assert _classify_tier(0.59, 5) == "audit_risk"

    def test_audit_risk_zero(self):
        assert _classify_tier(0.0, 5) == "audit_risk"

    def test_insufficient_when_too_few_hccs(self):
        # Even with perfect MEAT, < 3 HCCs is not statistically defensible.
        assert _classify_tier(1.0, 2) == "insufficient"

    def test_insufficient_at_zero_hccs(self):
        assert _classify_tier(0.0, 0) == "insufficient"

    def test_three_hccs_is_minimum(self):
        # The boundary: 3 HCCs is enough to render a verdict.
        assert _classify_tier(0.85, 3) == "ready"


class TestMissingComponents:
    def test_all_present(self):
        assert _missing_components(True, True, True, True) == []

    def test_all_missing(self):
        assert _missing_components(False, False, False, False) == [
            "Monitor",
            "Evaluate",
            "Assess",
            "Treat",
        ]

    def test_mixed(self):
        assert _missing_components(True, False, True, False) == ["Evaluate", "Treat"]


# ---------------------------------------------------------------------------
# Mock-based tests for assess_provider_audit_risk
# ---------------------------------------------------------------------------


def _cursor_with_responses(responses: list):
    """Return a (context-manager, cursor-mock) pair that yields the given
    fetchall() responses in order. fetchone() peels the first row off each."""
    cursor = MagicMock()
    cursor.fetchall.side_effect = responses
    cursor.fetchone.side_effect = [
        (rows[0] if rows else None) for rows in responses
    ]

    @contextmanager
    def _cm(*args, **kwargs):
        yield cursor

    return _cm, cursor


class TestAssessProviderAuditRisk:
    """End-to-end behaviour of the public service, with DB mocked."""

    def _patch_panel_and_query(self, panel_rows, agg_rows, phcc_rows):
        """Mock the three SELECTs that the service issues, in order:
        1) panel patient_ids
        2) aggregated MEAT presence per HCC
        3) per-HCC patient_hcc_ids list
        """
        responses = [panel_rows, agg_rows, phcc_rows]
        cm, _ = _cursor_with_responses(responses)
        # active_patients_subquery returns ('1=1', ()) under the all-active mock
        return (
            patch("app.services.meat_audit_risk.raf_cursor", cm),
            patch(
                "app.services.meat_audit_risk.active_patients_subquery",
                return_value=("1=1", ()),
            ),
            patch(
                "app.services.meat_audit_risk._hcc_label",
                side_effect=lambda c: f"Label-{c}",
            ),
        )

    def test_audit_ready_provider(self):
        """High MEAT (>=0.80), enough HCCs → ready/AUDIT-READY."""
        panel = [{"patient_id": 1}, {"patient_id": 2}, {"patient_id": 3}]
        # 3 HCCs all 4/4 components → completeness = 1.0
        agg = [
            {"hcc_code": 18, "phcc_count": 1, "has_m": 1, "has_e": 1, "has_a": 1, "has_t": 1},
            {"hcc_code": 85, "phcc_count": 1, "has_m": 1, "has_e": 1, "has_a": 1, "has_t": 1},
            {"hcc_code": 96, "phcc_count": 1, "has_m": 1, "has_e": 1, "has_a": 1, "has_t": 1},
        ]
        phcc = [
            {"id": 1, "hcc_code": 18},
            {"id": 2, "hcc_code": 85},
            {"id": 3, "hcc_code": 96},
        ]
        p1, p2, p3 = self._patch_panel_and_query(panel, agg, phcc)
        with p1, p2, p3:
            result = assess_provider_audit_risk(provider_id=1, year=2026, tenant_id=1)

        assert result["risk_tier"] == "ready"
        assert result["risk_label"] == "AUDIT-READY"
        assert result["meat_completeness"] == 1.0
        assert result["hcc_count"] == 3
        # No HCC is below the 0.75 weak threshold
        assert result["top_weak_hccs"] == []

    def test_at_risk_provider(self):
        """Provider in the 0.60–0.80 band shows AT RISK."""
        panel = [{"patient_id": 1}, {"patient_id": 2}, {"patient_id": 3}]
        # 4 HCCs at 0.75, 0.75, 0.75, 0.50 → mean = 0.6875 → at_risk
        agg = [
            {"hcc_code": 18, "phcc_count": 1, "has_m": 1, "has_e": 1, "has_a": 1, "has_t": 0},
            {"hcc_code": 85, "phcc_count": 1, "has_m": 1, "has_e": 1, "has_a": 1, "has_t": 0},
            {"hcc_code": 96, "phcc_count": 1, "has_m": 1, "has_e": 1, "has_a": 1, "has_t": 0},
            {"hcc_code": 22, "phcc_count": 1, "has_m": 1, "has_e": 0, "has_a": 1, "has_t": 0},
        ]
        phcc = [
            {"id": 1, "hcc_code": 18},
            {"id": 2, "hcc_code": 85},
            {"id": 3, "hcc_code": 96},
            {"id": 4, "hcc_code": 22},
        ]
        p1, p2, p3 = self._patch_panel_and_query(panel, agg, phcc)
        with p1, p2, p3:
            result = assess_provider_audit_risk(provider_id=1, year=2026, tenant_id=1)

        assert result["risk_tier"] == "at_risk"
        assert result["risk_label"] == "AT RISK"
        assert result["meat_completeness"] == pytest.approx(0.6875, rel=1e-3)
        assert result["hcc_count"] == 4
        # All 4 HCCs are < 0.75 (the three at 0.75 are NOT < 0.75; only HCC22 at 0.5)
        assert len(result["top_weak_hccs"]) == 1
        assert result["top_weak_hccs"][0]["hcc_code"] == "22"
        assert "Evaluate" in result["top_weak_hccs"][0]["missing_components"]
        assert "Treat" in result["top_weak_hccs"][0]["missing_components"]

    def test_audit_risk_provider(self):
        """Below 0.60 → red audit_risk tier."""
        panel = [{"patient_id": 1}, {"patient_id": 2}, {"patient_id": 3}]
        # 3 HCCs at 0.5, 0.25, 0.5 → mean ≈ 0.42 → audit_risk
        agg = [
            {"hcc_code": 18, "phcc_count": 1, "has_m": 1, "has_e": 0, "has_a": 1, "has_t": 0},
            {"hcc_code": 85, "phcc_count": 1, "has_m": 1, "has_e": 0, "has_a": 0, "has_t": 0},
            {"hcc_code": 96, "phcc_count": 1, "has_m": 1, "has_e": 0, "has_a": 1, "has_t": 0},
        ]
        phcc = [
            {"id": 1, "hcc_code": 18},
            {"id": 2, "hcc_code": 85},
            {"id": 3, "hcc_code": 96},
        ]
        p1, p2, p3 = self._patch_panel_and_query(panel, agg, phcc)
        with p1, p2, p3:
            result = assess_provider_audit_risk(provider_id=1, year=2026, tenant_id=1)

        assert result["risk_tier"] == "audit_risk"
        assert result["risk_label"] == "AUDIT RISK"
        assert result["meat_completeness"] < 0.60

    def test_insufficient_data_below_three_hccs(self):
        """A provider with only 2 coded HCCs returns insufficient,
        regardless of the MEAT score on those two HCCs."""
        panel = [{"patient_id": 1}, {"patient_id": 2}]
        agg = [
            {"hcc_code": 18, "phcc_count": 1, "has_m": 1, "has_e": 1, "has_a": 1, "has_t": 1},
            {"hcc_code": 85, "phcc_count": 1, "has_m": 1, "has_e": 1, "has_a": 1, "has_t": 1},
        ]
        phcc = [{"id": 1, "hcc_code": 18}, {"id": 2, "hcc_code": 85}]
        p1, p2, p3 = self._patch_panel_and_query(panel, agg, phcc)
        with p1, p2, p3:
            result = assess_provider_audit_risk(provider_id=1, year=2026, tenant_id=1)

        assert result["risk_tier"] == "insufficient"
        assert result["risk_label"] == "INSUFFICIENT DATA"
        assert result["hcc_count"] == 2

    def test_empty_panel_short_circuits(self):
        """Provider with no patients in panel → insufficient + zero HCCs.

        We don't even reach the MEAT query, so the cursor only needs to
        return an empty panel result.
        """
        cm, _ = _cursor_with_responses([[]])
        with patch("app.services.meat_audit_risk.raf_cursor", cm), patch(
            "app.services.meat_audit_risk.active_patients_subquery",
            return_value=("1=1", ()),
        ):
            result = assess_provider_audit_risk(provider_id=1, year=2026, tenant_id=1)

        assert result["risk_tier"] == "insufficient"
        assert result["hcc_count"] == 0
        assert result["meat_completeness"] == 0.0
        assert result["top_weak_hccs"] == []

    def test_top_weak_ordering_lowest_first_capped_at_five(self):
        """Top-weak list orders ascending by score and is capped at 5 entries."""
        panel = [{"patient_id": 1}]
        # 8 HCCs with scores 0.0, 0.25, 0.25, 0.5, 0.5, 0.75 (excluded), 1.0, 1.0
        agg = [
            # score 0.0
            {"hcc_code": 1, "phcc_count": 1, "has_m": 0, "has_e": 0, "has_a": 0, "has_t": 0},
            # 0.25 each
            {"hcc_code": 2, "phcc_count": 1, "has_m": 1, "has_e": 0, "has_a": 0, "has_t": 0},
            {"hcc_code": 3, "phcc_count": 1, "has_m": 0, "has_e": 1, "has_a": 0, "has_t": 0},
            # 0.5 each
            {"hcc_code": 4, "phcc_count": 1, "has_m": 1, "has_e": 1, "has_a": 0, "has_t": 0},
            {"hcc_code": 5, "phcc_count": 1, "has_m": 1, "has_e": 0, "has_a": 1, "has_t": 0},
            # 0.75 — NOT below threshold, must NOT appear
            {"hcc_code": 6, "phcc_count": 1, "has_m": 1, "has_e": 1, "has_a": 1, "has_t": 0},
            # 1.0 — must NOT appear
            {"hcc_code": 7, "phcc_count": 1, "has_m": 1, "has_e": 1, "has_a": 1, "has_t": 1},
            {"hcc_code": 8, "phcc_count": 1, "has_m": 1, "has_e": 1, "has_a": 1, "has_t": 1},
        ]
        phcc = [{"id": i, "hcc_code": i} for i in range(1, 9)]
        p1, p2, p3 = self._patch_panel_and_query(panel, agg, phcc)
        with p1, p2, p3:
            result = assess_provider_audit_risk(provider_id=1, year=2026, tenant_id=1)

        weak = result["top_weak_hccs"]
        # 5 weak HCCs are below the < 0.75 cutoff (HCCs 1-5); cap should be 5.
        assert len(weak) == 5
        # Ascending by score: HCC1 (0.0) first, then either of (HCC2, HCC3),
        # then either of (HCC4, HCC5).
        assert weak[0]["hcc_code"] == "1"
        assert weak[0]["meat_score"] == 0.0
        # HCC6 (0.75) and the 1.0 HCCs must NOT be in the list.
        weak_codes = [w["hcc_code"] for w in weak]
        assert "6" not in weak_codes
        assert "7" not in weak_codes
        assert "8" not in weak_codes

    def test_hcc_with_no_meat_evidence_scores_zero(self):
        """HCC coded but no raf_meat_evidence rows → all components missing."""
        panel = [{"patient_id": 1}, {"patient_id": 2}, {"patient_id": 3}]
        # has_m/e/a/t all None (LEFT JOIN miss) → bool() → False
        agg = [
            {"hcc_code": 18, "phcc_count": 1, "has_m": None, "has_e": None, "has_a": None, "has_t": None},
            {"hcc_code": 85, "phcc_count": 1, "has_m": 1, "has_e": 1, "has_a": 1, "has_t": 1},
            {"hcc_code": 96, "phcc_count": 1, "has_m": 1, "has_e": 1, "has_a": 1, "has_t": 1},
        ]
        phcc = [
            {"id": 1, "hcc_code": 18},
            {"id": 2, "hcc_code": 85},
            {"id": 3, "hcc_code": 96},
        ]
        p1, p2, p3 = self._patch_panel_and_query(panel, agg, phcc)
        with p1, p2, p3:
            result = assess_provider_audit_risk(provider_id=1, year=2026, tenant_id=1)

        # Mean of (0.0, 1.0, 1.0) = 0.6667 → at_risk band
        assert result["risk_tier"] == "at_risk"
        # The HCC with no evidence should appear in top_weak_hccs with all components missing
        weak = result["top_weak_hccs"]
        assert len(weak) == 1
        assert weak[0]["hcc_code"] == "18"
        assert weak[0]["meat_score"] == 0.0
        assert set(weak[0]["missing_components"]) == {"Monitor", "Evaluate", "Assess", "Treat"}


# ---------------------------------------------------------------------------
# get_meat_evidence_for_hcc
# ---------------------------------------------------------------------------


class TestGetMeatEvidenceForHcc:
    def test_normalises_hcc_string_prefix(self):
        """'HCC85' and '85' should both query for hcc_code=85."""
        cm, cursor = _cursor_with_responses(
            [
                # panel response
                [{"patient_id": 1}],
                # evidence response
                [],
            ]
        )
        with patch("app.services.meat_audit_risk.raf_cursor", cm), patch(
            "app.services.meat_audit_risk.active_patients_subquery",
            return_value=("1=1", ()),
        ):
            get_meat_evidence_for_hcc(
                provider_id=1, hcc_code="HCC85", year=2026, tenant_id=1
            )

        # Second cursor.execute (the evidence query) should have hcc_int=85 in its params.
        # Inspect the calls on the cursor:
        evidence_call = cursor.execute.call_args_list[1]
        # second call args = (sql, tuple([year, hcc_int] + panel))
        params = evidence_call.args[1]
        assert 85 in params

    def test_invalid_hcc_returns_empty(self):
        cm, cursor = _cursor_with_responses([[{"patient_id": 1}]])
        with patch("app.services.meat_audit_risk.raf_cursor", cm), patch(
            "app.services.meat_audit_risk.active_patients_subquery",
            return_value=("1=1", ()),
        ):
            out = get_meat_evidence_for_hcc(
                provider_id=1, hcc_code="not-a-number", tenant_id=1
            )
        assert out == []

    def test_empty_panel_returns_empty(self):
        cm, _ = _cursor_with_responses([[]])
        with patch("app.services.meat_audit_risk.raf_cursor", cm), patch(
            "app.services.meat_audit_risk.active_patients_subquery",
            return_value=("1=1", ()),
        ):
            out = get_meat_evidence_for_hcc(
                provider_id=1, hcc_code="85", tenant_id=1
            )
        assert out == []

    def test_evidence_row_shape(self):
        from datetime import date

        cm, _ = _cursor_with_responses(
            [
                [{"patient_id": 7}],
                [
                    {
                        "patient_hcc_id": 12,
                        "patient_id": 7,
                        "encounter_id": 100,
                        "encounter_date": date(2026, 3, 14),
                        "has_m": 1,
                        "has_e": 0,
                        "has_a": 1,
                        "has_t": 0,
                        "score": 0.5,
                        "excerpt": "Continue metformin 1000 mg BID. A1c improved.",
                    }
                ],
            ]
        )
        with patch("app.services.meat_audit_risk.raf_cursor", cm), patch(
            "app.services.meat_audit_risk.active_patients_subquery",
            return_value=("1=1", ()),
        ):
            out = get_meat_evidence_for_hcc(
                provider_id=1, hcc_code="18", year=2026, tenant_id=1
            )

        assert len(out) == 1
        row = out[0]
        assert row["patient_id"] == 7
        assert row["patient_hcc_id"] == 12
        assert row["encounter_id"] == 100
        assert row["encounter_date"] == "2026-03-14"
        assert row["components_present"] == ["Monitor", "Assess"]
        assert row["components_missing"] == ["Evaluate", "Treat"]
        assert row["meat_score"] == 0.5
        assert "metformin" in row["evidence_snippet"]
