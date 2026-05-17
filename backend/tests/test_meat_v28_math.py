"""Tests for MEAT extractor math fixes and V28 calculator corrections.

Covers:
1. MEAT confidence averaging — only present letters count in denominator.
2. Encounter-id strict-mode — notes with encounter=0 are skipped.
3. Span offset disambiguation — closest occurrence wins, not first .find().
4. V28 hierarchy trump before set-diff — trumped HCCs don't appear as dropped.
5. revenue_per_raf_point(2026) returns 11800.0.
"""
from __future__ import annotations

import re
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# 1. MEAT confidence average — only present letters
# ---------------------------------------------------------------------------

def test_mean_present_confidences_partial():
    """Only M and E present — avg should be (0.9 + 0.8) / 2, not / 4."""
    from app.services.meat_evidence_extractor import _mean_present_confidences

    conf = {"m": 0.9, "e": 0.8, "a": -1.0, "t": -1.0}
    result = _mean_present_confidences(conf)
    assert abs(result - 0.85) < 1e-6, f"Expected 0.85, got {result}"


def test_mean_present_confidences_all_present():
    """All four letters present — avg of all four."""
    from app.services.meat_evidence_extractor import _mean_present_confidences

    conf = {"m": 1.0, "e": 0.8, "a": 0.6, "t": 0.4}
    result = _mean_present_confidences(conf)
    assert abs(result - 0.7) < 1e-6, f"Expected 0.7, got {result}"


def test_mean_present_confidences_none_present():
    """No present letters — should return 0.0 without ZeroDivisionError."""
    from app.services.meat_evidence_extractor import _mean_present_confidences

    conf = {"m": -1.0, "e": -1.0, "a": -1.0, "t": -1.0}
    result = _mean_present_confidences(conf)
    assert result == 0.0


# ---------------------------------------------------------------------------
# 2. Encounter-id strict mode — notes with encounter=0 skipped
# ---------------------------------------------------------------------------

def test_fetch_year_notes_skips_zero_encounter_strict():
    """A note with encounter=0 that cannot be resolved should be skipped
    when strict_encounter_attribution=True (the default)."""
    from app.services import meat_evidence_extractor as mod

    fake_notes = [
        {
            "note_text": "Patient has diabetes mellitus.",
            "date": "2025-03-15",
            "encounter": 0,
        }
    ]

    with (
        patch.object(mod, "_fetch_year_notes", wraps=mod._fetch_year_notes),
        patch(
            "app.services.openemr_connector.get_all_clinical_notes_for_patient",
            return_value=fake_notes,
        ),
        patch.object(
            mod,
            "_resolve_encounter_id",
            return_value=None,  # Simulate failed secondary lookup
        ),
    ):
        result = mod._fetch_year_notes(
            patient_id=1,
            year=2025,
            strict_encounter_attribution=True,
        )

    assert result == [], f"Expected empty list, got {result}"


def test_fetch_year_notes_includes_zero_encounter_nonstrict():
    """A note with encounter=0 should be included when
    strict_encounter_attribution=False."""
    from app.services import meat_evidence_extractor as mod

    fake_notes = [
        {
            "note_text": "Patient has diabetes mellitus.",
            "date": "2025-03-15",
            "encounter": 0,
        }
    ]

    with (
        patch(
            "app.services.openemr_connector.get_all_clinical_notes_for_patient",
            return_value=fake_notes,
        ),
        patch.object(
            mod,
            "_resolve_encounter_id",
            return_value=None,
        ),
    ):
        result = mod._fetch_year_notes(
            patient_id=1,
            year=2025,
            strict_encounter_attribution=False,
        )

    assert len(result) == 1
    assert result[0]["encounter_id"] is None


# ---------------------------------------------------------------------------
# 3. Span offset disambiguation — closest to LLM hint wins
# ---------------------------------------------------------------------------

def test_validate_offsets_picks_closest_to_llm_hint():
    """When 'diabetes' appears twice, pick the one nearest the LLM offset."""
    from app.services.meat_evidence_extractor import _validate_offsets

    # Construct a note where "diabetes" appears at two different positions.
    note = "Patient has diabetes in history. Assessment: diabetes well controlled."
    # First occurrence at position 12, second at position 51.
    first_pos = note.index("diabetes")
    second_pos = note.index("diabetes", first_pos + 1)

    sentence = "diabetes"

    # LLM hint near the second occurrence.
    result = _validate_offsets(note, sentence, second_pos - 2, second_pos + len(sentence))
    assert result is not None
    assert result[0] == second_pos, (
        f"Expected offset {second_pos} (near LLM hint), got {result[0]}"
    )


def test_validate_offsets_picks_last_when_no_hint():
    """When no valid LLM hint is given, pick the LAST occurrence."""
    from app.services.meat_evidence_extractor import _validate_offsets

    note = "diabetes history noted. Plan: diabetes management ongoing."
    sentence = "diabetes"
    first_pos = note.index("diabetes")
    last_pos = note.rindex("diabetes")

    result = _validate_offsets(note, sentence, None, None)
    assert result is not None
    assert result[0] == last_pos, (
        f"Expected last occurrence at {last_pos}, got {result[0]}"
    )


def test_validate_offsets_returns_none_for_hallucinated_sentence():
    """A sentence not present in the note at all returns None."""
    from app.services.meat_evidence_extractor import _validate_offsets

    note = "Normal physical exam findings."
    result = _validate_offsets(note, "severe acute respiratory distress", None, None)
    assert result is None


# ---------------------------------------------------------------------------
# 4. V28 hierarchy trump before set-diff
# ---------------------------------------------------------------------------

def test_filter_hierarchy_removes_trumped_hcc():
    """HCC 18 must be removed when HCC 17 is present (V24 diabetes chain)."""
    from app.services.v28_transition_calculator import _filter_hierarchy

    result = _filter_hierarchy(["17", "18", "19"], "V24")
    assert "17" in result
    assert "18" not in result, "HCC 18 should be trumped by HCC 17 in V24"
    assert "19" not in result, "HCC 19 should be trumped by HCC 17 in V24"


def test_score_delta_dropped_hccs_excludes_trumped():
    """When V24 has [HCC18, HCC17] and V28 has [HCC17], dropped_hccs should
    be empty — HCC 18 was already trumped on the V24 side, not lost in V28."""
    from app.services import v28_transition_calculator as mod

    fake_multi = {
        "v24": {"payment_raf": 1.5},
        "v28": {"payment_raf": 1.4},
        "hcc_comparison": {
            "v24_only": ["18"],   # Engine reports HCC18 as V24-only
            "v28_only": [],
            "in_both":  ["17"],   # HCC17 present in both
        },
        "icd_codes": ["E119"],
        "model_segment": "CN",
    }

    with (
        patch.object(mod, "_run_multi_model", return_value=fake_multi),
        patch.object(mod, "cache_get", return_value=None),
        patch.object(mod, "cache_set"),
    ):
        result = mod.score_delta_v24_to_v28(
            patient_id=1,
            year=2026,
            tenant_id="test-tenant",
            use_cache=False,
        )

    assert result["dropped_hccs"] == [], (
        f"HCC 18 was trumped by HCC 17 on the V24 side — should not appear "
        f"in dropped_hccs. Got: {result['dropped_hccs']}"
    )


# ---------------------------------------------------------------------------
# 5. Revenue constants — PY2026 rate
# ---------------------------------------------------------------------------

def test_revenue_per_raf_point_2026():
    from app.services.raf.revenue_constants import revenue_per_raf_point

    assert revenue_per_raf_point(2026) == 11800.0


def test_revenue_per_raf_point_2024():
    from app.services.raf.revenue_constants import revenue_per_raf_point

    assert revenue_per_raf_point(2024) == 11015.04


def test_revenue_per_raf_point_default():
    """No year argument returns the 2026 default."""
    from app.services.raf.revenue_constants import revenue_per_raf_point

    assert revenue_per_raf_point() == 11800.0
