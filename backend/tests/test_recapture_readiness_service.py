"""
Unit tests for app.services.recapture_readiness_service.

Covers:
- Pure scoring math at threshold boundaries
- MEAT component math (0/4, 4/4, capped at MEAT_MAX_SCORE)
- ICD normalisation against ``ICD10:E11.9`` style problem-list rows
- Recency window for problem-list and encounters
- compute_gap_readiness end-to-end with mocked DB readers
- bulk_compute_readiness + compute_readiness_summary aggregation

All DB calls are patched at the module level — no live database required.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from unittest.mock import patch

import pytest

from app.services import recapture_readiness_service as svc
from app.services.recapture_readiness_service import (
    MAX_SCORE,
    MEAT_MAX_SCORE,
    RECENCY_WINDOW_DAYS,
    SCORE_PER_MEAT,
    SCORE_PROBLEM_LIST,
    SCORE_PROBLEM_LIST_RECENT,
    SCORE_RECENT_ENCOUNTER,
    TIER_MODERATE_MIN,
    TIER_STRONG_MIN,
    _icd_matches,
    _is_recent,
    _normalize_icd,
    _recommended_actions,
    _score_components,
    _tier,
    bulk_compute_readiness,
    compute_gap_readiness,
    compute_readiness_summary,
)


# ===========================================================================
# Pure helpers — no DB
# ===========================================================================


class TestIcdNormalisation:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("E11.9", "E119"),
            ("e11.9", "E119"),
            (" E11.9 ", "E119"),
            ("E119", "E119"),
            ("", ""),
            (None, ""),
        ],
    )
    def test_normalize(self, raw, expected) -> None:
        assert _normalize_icd(raw) == expected

    @pytest.mark.parametrize(
        "stored,target,match",
        [
            ("ICD10:E11.9", "E119", True),
            ("E11.9", "E119", True),
            ("e11.9", "E119", True),
            ("ICD10:I50.9", "E119", False),
            ("", "E119", False),
            (None, "E119", False),
            ("ICD10:E11.9", "", False),
        ],
    )
    def test_icd_matches(self, stored, target, match) -> None:
        assert _icd_matches(stored, target) is match


class TestRecency:
    def test_value_inside_window(self) -> None:
        today = date(2026, 5, 5)
        recent = today - timedelta(days=10)
        assert _is_recent(recent, today=today) is True

    def test_value_at_exact_cutoff(self) -> None:
        today = date(2026, 5, 5)
        cutoff = today - timedelta(days=RECENCY_WINDOW_DAYS)
        # cutoff is inclusive
        assert _is_recent(cutoff, today=today) is True

    def test_value_outside_window(self) -> None:
        today = date(2026, 5, 5)
        old = today - timedelta(days=RECENCY_WINDOW_DAYS + 1)
        assert _is_recent(old, today=today) is False

    def test_none(self) -> None:
        assert _is_recent(None) is False

    def test_iso_string(self) -> None:
        today = date(2026, 5, 5)
        recent_iso = (today - timedelta(days=5)).isoformat()
        assert _is_recent(recent_iso, today=today) is True

    def test_datetime(self) -> None:
        today = date(2026, 5, 5)
        recent = datetime(2026, 5, 1, 9, 0, 0)
        assert _is_recent(recent, today=today) is True

    def test_garbage_value(self) -> None:
        assert _is_recent("not-a-date") is False


# ===========================================================================
# Score formula — boundaries
# ===========================================================================


class TestScoreFormula:
    def test_zero_components_zero_score(self) -> None:
        score, breakdown = _score_components(
            icd_on_problem_list=False,
            problem_list_recent=False,
            recent_encounter=False,
            meat={"m": 0, "e": 0, "a": 0, "t": 0},
        )
        assert score == 0
        assert breakdown == {
            "problem_list": 0,
            "problem_list_recent": 0,
            "recent_encounter": 0,
            "meat": 0,
        }
        assert _tier(score) == "weak"

    def test_problem_list_only(self) -> None:
        score, breakdown = _score_components(
            icd_on_problem_list=True,
            problem_list_recent=False,
            recent_encounter=False,
            meat={"m": 0, "e": 0, "a": 0, "t": 0},
        )
        assert score == SCORE_PROBLEM_LIST  # 30
        assert breakdown["problem_list"] == 30
        assert _tier(score) == "weak"  # 30 < 40

    def test_moderate_threshold_at_40(self) -> None:
        # problem_list (30) + 1 MEAT (10) = 40 → moderate
        score, _ = _score_components(
            icd_on_problem_list=True,
            problem_list_recent=False,
            recent_encounter=False,
            meat={"m": 1, "e": 0, "a": 0, "t": 0},
        )
        assert score == TIER_MODERATE_MIN
        assert _tier(score) == "moderate"

    def test_just_below_moderate_is_weak(self) -> None:
        # 30 problem_list + 0 = 30 → weak
        score, _ = _score_components(
            icd_on_problem_list=True,
            problem_list_recent=False,
            recent_encounter=False,
            meat={"m": 0, "e": 0, "a": 0, "t": 0},
        )
        assert score == 30
        assert _tier(score) == "weak"

    def test_strong_threshold_at_70(self) -> None:
        # 30 + 20 + 20 = 70 → strong
        score, _ = _score_components(
            icd_on_problem_list=True,
            problem_list_recent=True,
            recent_encounter=True,
            meat={"m": 0, "e": 0, "a": 0, "t": 0},
        )
        assert score == TIER_STRONG_MIN
        assert _tier(score) == "strong"

    def test_all_components_max_100(self) -> None:
        score, breakdown = _score_components(
            icd_on_problem_list=True,
            problem_list_recent=True,
            recent_encounter=True,
            meat={"m": 1, "e": 1, "a": 1, "t": 1},
        )
        assert score == MAX_SCORE  # 100
        assert breakdown["meat"] == MEAT_MAX_SCORE
        assert _tier(score) == "strong"

    def test_meat_capped_at_30(self) -> None:
        # All four MEAT elements = 4 * SCORE_PER_MEAT = 40 raw, must cap to 30
        _, breakdown = _score_components(
            icd_on_problem_list=False,
            problem_list_recent=False,
            recent_encounter=False,
            meat={"m": 1, "e": 1, "a": 1, "t": 1},
        )
        assert breakdown["meat"] == MEAT_MAX_SCORE
        assert MEAT_MAX_SCORE < 4 * SCORE_PER_MEAT

    @pytest.mark.parametrize(
        "meat,expected_meat_pts",
        [
            ({"m": 0, "e": 0, "a": 0, "t": 0}, 0),
            ({"m": 1, "e": 0, "a": 0, "t": 0}, 10),
            ({"m": 1, "e": 1, "a": 0, "t": 0}, 20),
            ({"m": 1, "e": 1, "a": 1, "t": 0}, 30),
            ({"m": 1, "e": 1, "a": 1, "t": 1}, 30),  # capped
        ],
    )
    def test_meat_progression(self, meat, expected_meat_pts) -> None:
        _, breakdown = _score_components(
            icd_on_problem_list=False,
            problem_list_recent=False,
            recent_encounter=False,
            meat=meat,
        )
        assert breakdown["meat"] == expected_meat_pts


class TestTier:
    @pytest.mark.parametrize(
        "score,expected",
        [
            (0, "weak"),
            (39, "weak"),
            (40, "moderate"),
            (69, "moderate"),
            (70, "strong"),
            (100, "strong"),
        ],
    )
    def test_tier_boundaries(self, score, expected) -> None:
        assert _tier(score) == expected


class TestRecommendedActions:
    def test_no_problem_list_action_first(self) -> None:
        actions = _recommended_actions(
            icd_on_problem_list=False,
            problem_list_recent=False,
            recent_encounter=True,
            meat={"m": 1, "e": 1, "a": 1, "t": 1},
        )
        assert any("problem list" in a.lower() for a in actions)

    def test_stale_problem_list_suggests_refresh(self) -> None:
        actions = _recommended_actions(
            icd_on_problem_list=True,
            problem_list_recent=False,
            recent_encounter=True,
            meat={"m": 1, "e": 1, "a": 1, "t": 1},
        )
        assert any("reaffirm" in a.lower() or "refresh" in a.lower() for a in actions)

    def test_no_visit_suggests_scheduling(self) -> None:
        actions = _recommended_actions(
            icd_on_problem_list=True,
            problem_list_recent=True,
            recent_encounter=False,
            meat={"m": 1, "e": 1, "a": 1, "t": 1},
        )
        assert any("schedule" in a.lower() and "visit" in a.lower() for a in actions)

    def test_missing_meat_listed(self) -> None:
        actions = _recommended_actions(
            icd_on_problem_list=True,
            problem_list_recent=True,
            recent_encounter=True,
            meat={"m": 1, "e": 0, "a": 0, "t": 1},
        )
        meat_action = next((a for a in actions if "MEAT" in a), None)
        assert meat_action is not None
        assert "E" in meat_action and "A" in meat_action

    def test_full_strong_no_actions(self) -> None:
        actions = _recommended_actions(
            icd_on_problem_list=True,
            problem_list_recent=True,
            recent_encounter=True,
            meat={"m": 1, "e": 1, "a": 1, "t": 1},
        )
        assert actions == []


# ===========================================================================
# compute_gap_readiness — end-to-end with mocked DB readers
# ===========================================================================


_FIXED_TODAY = date(2026, 5, 5)


def _gap_row(gap_id: int = 1, **overrides):
    base = {
        "id": gap_id,
        "patient_id": "42",
        "tenant_id": "1",
        "hcc_code": "85",
        "icd10_code": "I50.9",
        "prior_year": 2025,
        "current_year": 2026,
        "status": "open",
        "last_encounter_date": None,
        "provider_npi": "1234567890",
        "revenue_impact": 3000.00,
    }
    base.update(overrides)
    return base


class TestComputeGapReadiness:
    def test_strong_gap_full_evidence(self) -> None:
        with (
            patch.object(svc, "_load_gap", return_value=_gap_row()),
            patch.object(
                svc, "_fetch_problem_list",
                return_value=[{
                    "diagnosis": "I509",
                    "raw_diagnosis": "ICD10:I50.9",
                    "title": "CHF",
                    "begdate": _FIXED_TODAY - timedelta(days=10),
                    "date_added": _FIXED_TODAY - timedelta(days=10),
                    "date_modified": _FIXED_TODAY - timedelta(days=5),
                }],
            ),
            patch.object(
                svc, "_fetch_recent_encounters",
                return_value={"count": 2, "last_date": "2026-04-30"},
            ),
            patch.object(
                svc, "_fetch_meat_status",
                return_value={"m": 1, "e": 1, "a": 1, "t": 1},
            ),
        ):
            payload = compute_gap_readiness(gap_id=1, tenant_id="1", today=_FIXED_TODAY)

        assert payload["score"] == 100
        assert payload["defensibility_tier"] == "strong"
        assert payload["components"]["problem_list"] is True
        assert payload["components"]["problem_list_recent"] is True
        assert payload["components"]["recent_encounter"] is True
        assert payload["recommended_actions"] == []
        assert payload["last_encounter_in_window"] == "2026-04-30"

    def test_weak_gap_no_evidence(self) -> None:
        with (
            patch.object(svc, "_load_gap", return_value=_gap_row()),
            patch.object(svc, "_fetch_problem_list", return_value=[]),
            patch.object(
                svc, "_fetch_recent_encounters",
                return_value={"count": 0, "last_date": None},
            ),
            patch.object(
                svc, "_fetch_meat_status",
                return_value={"m": 0, "e": 0, "a": 0, "t": 0},
            ),
        ):
            payload = compute_gap_readiness(gap_id=1, tenant_id="1", today=_FIXED_TODAY)

        assert payload["score"] == 0
        assert payload["defensibility_tier"] == "weak"
        assert "Add condition to active problem list" in payload["recommended_actions"]
        assert any("Schedule" in a for a in payload["recommended_actions"])

    def test_moderate_gap_problem_list_but_stale_no_encounter(self) -> None:
        # Problem list match, but begdate > 90 days, no encounter, no MEAT
        # → 30 only → weak
        with (
            patch.object(svc, "_load_gap", return_value=_gap_row()),
            patch.object(
                svc, "_fetch_problem_list",
                return_value=[{
                    "diagnosis": "I509",
                    "raw_diagnosis": "ICD10:I50.9",
                    "title": "CHF",
                    "begdate": _FIXED_TODAY - timedelta(days=400),
                    "date_added": _FIXED_TODAY - timedelta(days=400),
                    "date_modified": _FIXED_TODAY - timedelta(days=400),
                }],
            ),
            patch.object(
                svc, "_fetch_recent_encounters",
                return_value={"count": 0, "last_date": None},
            ),
            patch.object(
                svc, "_fetch_meat_status",
                return_value={"m": 0, "e": 0, "a": 0, "t": 0},
            ),
        ):
            payload = compute_gap_readiness(gap_id=1, tenant_id="1", today=_FIXED_TODAY)

        assert payload["score"] == SCORE_PROBLEM_LIST
        assert payload["defensibility_tier"] == "weak"
        assert payload["components"]["problem_list"] is True
        assert payload["components"]["problem_list_recent"] is False

    def test_unknown_gap_raises_lookup(self) -> None:
        with patch.object(svc, "_load_gap", return_value=None):
            with pytest.raises(LookupError):
                compute_gap_readiness(gap_id=999, tenant_id="1")

    def test_problem_list_match_handles_dotted_icd(self) -> None:
        # Problem list stores 'ICD10:I50.9', gap stores 'I50.9' — must match
        with (
            patch.object(svc, "_load_gap", return_value=_gap_row(icd10_code="I50.9")),
            patch.object(
                svc, "_fetch_problem_list",
                return_value=[{
                    "diagnosis": "I509",
                    "raw_diagnosis": "ICD10:I50.9",
                    "title": "CHF",
                    "begdate": _FIXED_TODAY - timedelta(days=400),
                    "date_added": None,
                    "date_modified": None,
                }],
            ),
            patch.object(
                svc, "_fetch_recent_encounters",
                return_value={"count": 0, "last_date": None},
            ),
            patch.object(
                svc, "_fetch_meat_status",
                return_value={"m": 0, "e": 0, "a": 0, "t": 0},
            ),
        ):
            payload = compute_gap_readiness(gap_id=1, tenant_id="1", today=_FIXED_TODAY)

        assert payload["components"]["problem_list"] is True


# ===========================================================================
# bulk_compute_readiness + compute_readiness_summary
# ===========================================================================


class TestBulkAndSummary:
    def _patches_for_two_gaps(self):
        gaps = [
            _gap_row(gap_id=1, hcc_code="85", icd10_code="I50.9"),
            _gap_row(gap_id=2, hcc_code="111", icd10_code="J44.1", patient_id="43"),
        ]

        def fake_problem(pid):
            if str(pid) == "42":
                return [{
                    "diagnosis": "I509",
                    "raw_diagnosis": "ICD10:I50.9",
                    "title": "CHF",
                    "begdate": _FIXED_TODAY - timedelta(days=10),
                    "date_added": _FIXED_TODAY - timedelta(days=10),
                    "date_modified": _FIXED_TODAY - timedelta(days=10),
                }]
            return []

        def fake_enc(pid, **kw):
            if str(pid) == "42":
                return {"count": 1, "last_date": "2026-04-30"}
            return {"count": 0, "last_date": None}

        def fake_meat(pid, hcc, year):
            if str(pid) == "42":
                return {"m": 1, "e": 1, "a": 1, "t": 1}
            return {"m": 0, "e": 0, "a": 0, "t": 0}

        return gaps, fake_problem, fake_enc, fake_meat

    def test_bulk_returns_per_gap_payload(self) -> None:
        gaps, fake_problem, fake_enc, fake_meat = self._patches_for_two_gaps()

        with (
            patch.object(svc, "_load_gaps_for_year", return_value=gaps),
            patch.object(svc, "_fetch_problem_list", side_effect=fake_problem),
            patch.object(svc, "_fetch_recent_encounters", side_effect=fake_enc),
            patch.object(svc, "_fetch_meat_status", side_effect=fake_meat),
        ):
            items = bulk_compute_readiness(tenant_id="1", year=2026, today=_FIXED_TODAY)

        assert len(items) == 2
        # Patient 42 has full evidence → 100, strong
        assert items[0]["score"] == 100
        assert items[0]["defensibility_tier"] == "strong"
        # Patient 43 has nothing → 0, weak
        assert items[1]["score"] == 0
        assert items[1]["defensibility_tier"] == "weak"

    def test_summary_aggregates_distribution(self) -> None:
        gaps, fake_problem, fake_enc, fake_meat = self._patches_for_two_gaps()

        with (
            patch.object(svc, "_load_gaps_for_year", return_value=gaps),
            patch.object(svc, "_fetch_problem_list", side_effect=fake_problem),
            patch.object(svc, "_fetch_recent_encounters", side_effect=fake_enc),
            patch.object(svc, "_fetch_meat_status", side_effect=fake_meat),
        ):
            summary = compute_readiness_summary(tenant_id="1", year=2026, today=_FIXED_TODAY)

        assert summary["year"] == 2026
        assert summary["total_open_gaps"] == 2
        assert summary["average_score"] == 50.0
        assert summary["defensibility_distribution"] == {
            "strong": 1, "moderate": 0, "weak": 1,
        }
        # Only the weak gap has actions
        assert summary["actionable_gaps"] == 1

    def test_summary_no_gaps(self) -> None:
        with patch.object(svc, "_load_gaps_for_year", return_value=[]):
            summary = compute_readiness_summary(tenant_id="1", year=2026)

        assert summary["total_open_gaps"] == 0
        assert summary["average_score"] == 0.0
        assert summary["defensibility_distribution"] == {
            "strong": 0, "moderate": 0, "weak": 0,
        }
        assert summary["actionable_gaps"] == 0


# ===========================================================================
# Missing-data resilience
# ===========================================================================


class TestMissingData:
    def test_problem_list_db_failure_returns_empty(self) -> None:
        # When openemr_cursor raises, _fetch_problem_list must return []
        with patch(
            "app.services.recapture_readiness_service.openemr_cursor",
            side_effect=Exception("connection refused"),
        ):
            assert svc._fetch_problem_list(42) == []

    def test_meat_db_failure_returns_zeros(self) -> None:
        with patch(
            "app.services.recapture_readiness_service.raf_cursor",
            side_effect=Exception("boom"),
        ):
            assert svc._fetch_meat_status("42", "85", 2026) == {
                "m": 0, "e": 0, "a": 0, "t": 0,
            }

    def test_encounter_db_failure_returns_zero_count(self) -> None:
        with patch(
            "app.services.recapture_readiness_service.openemr_cursor",
            side_effect=Exception("boom"),
        ):
            out = svc._fetch_recent_encounters(42)
            assert out == {"count": 0, "last_date": None}

    def test_invalid_patient_id(self) -> None:
        # Non-numeric pid must not raise
        assert svc._fetch_problem_list("not-a-number") == []
        assert svc._fetch_recent_encounters("not-a-number") == {
            "count": 0, "last_date": None,
        }
