"""Unit tests for the literature-backed evidence rules engine.

These tests do NOT require a running backend; they exercise the in-process
engine directly.  The override in tests/knowledge_graph/conftest.py is
*not* applied here because this file lives at tests/ root.  We therefore
rely on `server_available` being autouse — but since we don't import any
network fixture and we explicitly mark the module to skip the network
requirement, we simply override `server_available` locally.
"""
from __future__ import annotations

import pytest

from app.services.knowledge_graph.evidence_rules_engine import (
    CURATED_RULES,
    _check_trigger,
    evaluate_evidence,
    get_rule,
    get_rules_by_hcc,
    get_rules_by_source,
    list_rules,
)


# ---------------------------------------------------------------------------
# Override the parent server_available autouse fixture for this file only.
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session", autouse=True)
def server_available():  # type: ignore[override]
    """No-op override so engine unit tests run without a live backend."""
    yield


# ---------------------------------------------------------------------------
# 1. Rule catalogue integrity
# ---------------------------------------------------------------------------

def test_catalogue_has_at_least_50_rules():
    assert len(CURATED_RULES) >= 50, "Need at least 50 curated rules"


def test_every_rule_has_source_attribution():
    """No ad-hoc rules: every rule must cite source_type AND source_citation."""
    for r in CURATED_RULES:
        assert r.get("source_type"), f"missing source_type: {r['rule_name']}"
        assert r.get("source_citation"), f"missing source_citation: {r['rule_name']}"
        assert isinstance(r["source_citation"], str)
        assert len(r["source_citation"]) > 20


def test_unique_rule_names():
    names = [r["rule_name"] for r in CURATED_RULES]
    assert len(names) == len(set(names)), "rule_name must be unique"


# ---------------------------------------------------------------------------
# 2. Trigger AND/OR semantics
# ---------------------------------------------------------------------------

def test_trigger_all_requires_every_condition():
    cond = [
        {"kind": "icd10", "prefix": "E11"},
        {"kind": "loinc_threshold", "code": "4548-4", "op": ">", "value": 9.0},
    ]
    # Only ICD met → AND fails
    ev = {"icd10": ["E11.9"]}
    assert _check_trigger(cond, ev, logic="all") is False
    # Both met → AND succeeds
    ev = {"icd10": ["E11.9"], "loinc": [{"code": "4548-4", "value": 9.5}]}
    assert _check_trigger(cond, ev, logic="all") is True


def test_trigger_any_succeeds_with_one_condition():
    cond = [
        {"kind": "icd10", "code": "I50.21"},
        {"kind": "icd10", "code": "I50.23"},
    ]
    ev = {"icd10": ["I50.23"]}
    assert _check_trigger(cond, ev, logic="any") is True
    ev = {"icd10": ["I50.30"]}
    assert _check_trigger(cond, ev, logic="any") is False


# ---------------------------------------------------------------------------
# 3. Threshold operators
# ---------------------------------------------------------------------------

def test_loinc_threshold_lt_op():
    cond = [{"kind": "loinc_threshold", "code": "62238-1", "op": "<", "value": 30.0}]
    assert _check_trigger(cond, {"loinc": [{"code": "62238-1", "value": 14.0}]}, "all") is True
    assert _check_trigger(cond, {"loinc": [{"code": "62238-1", "value": 30.0}]}, "all") is False


def test_loinc_threshold_gt_op():
    cond = [{"kind": "loinc_threshold", "code": "4548-4", "op": ">", "value": 9.0}]
    assert _check_trigger(cond, {"loinc": [{"code": "4548-4", "value": 9.1}]}, "all") is True
    assert _check_trigger(cond, {"loinc": [{"code": "4548-4", "value": 9.0}]}, "all") is False


def test_loinc_threshold_eq_op():
    cond = [{"kind": "loinc_threshold", "code": "X", "op": "=", "value": 5.0}]
    assert _check_trigger(cond, {"loinc": [{"code": "X", "value": 5.0}]}, "all") is True
    assert _check_trigger(cond, {"loinc": [{"code": "X", "value": 5.5}]}, "all") is False


# ---------------------------------------------------------------------------
# 4. Marquee rule happy paths
# ---------------------------------------------------------------------------

def test_marquee_dm_uncontrolled_hba1c():
    """ADA: DM + HbA1c >9 → HCC 18 uncontrolled."""
    matches = evaluate_evidence(
        {
            "icd10": ["E11.9", "H35.022"],
            "loinc": [{"code": "4548-4", "value": 9.2}],
        }
    )
    rule_names = {m["rule_name"] for m in matches}
    assert "ada_dm_uncontrolled_hba1c_gt9" in rule_names
    target = next(m for m in matches if m["rule_name"] == "ada_dm_uncontrolled_hba1c_gt9")
    assert target["output_hcc"] == "18"
    assert "ADA" in target["source_citation"] or "Diabetes" in target["source_citation"]


def test_marquee_ckd_stage4():
    """KDIGO: N18.4 + eGFR <30 → HCC 137."""
    matches = evaluate_evidence(
        {
            "icd10": ["N18.4"],
            "loinc": [{"code": "62238-1", "value": 22.0}],
        }
    )
    rules = {m["rule_name"]: m for m in matches}
    assert "kdigo_ckd_stage4_egfr_15_30" in rules
    assert rules["kdigo_ckd_stage4_egfr_15_30"]["output_hcc"] == "137"


def test_marquee_hfref():
    """ACC/AHA: I50.x + LVEF <40 → HFrEF HCC 224."""
    matches = evaluate_evidence(
        {
            "icd10": ["I50.22"],
            "loinc": [{"code": "10230-1", "value": 35.0}],
        }
    )
    names = {m["rule_name"] for m in matches}
    assert "accaha_hfref_lvef_lt40" in names


def test_marquee_copd_exacerbation():
    """GOLD: J44.1 → acute COPD exacerbation HCC 279."""
    matches = evaluate_evidence({"icd10": ["J44.1"]})
    names = {m["rule_name"] for m in matches}
    assert "gold_copd_acute_exacerbation" in names


def test_marquee_mdd_severe():
    """DSM-5: F33.2 severe recurrent MDD → HCC 155."""
    matches = evaluate_evidence({"icd10": ["F33.2"]})
    names = {m["rule_name"] for m in matches}
    assert "dsm5_mdd_five_of_nine_criteria" in names


# ---------------------------------------------------------------------------
# 5. Negative paths
# ---------------------------------------------------------------------------

def test_negative_no_evidence_returns_no_matches():
    assert evaluate_evidence({}) == []


def test_negative_unrelated_codes():
    matches = evaluate_evidence({"icd10": ["Z00.00", "Z23"]})
    # Allow USPSTF screening rules to NOT match (they require Z87.891 / I71.x)
    names = {m["rule_name"] for m in matches}
    assert "ada_dm_uncontrolled_hba1c_gt9" not in names
    assert "accaha_hfref_lvef_lt40" not in names


# ---------------------------------------------------------------------------
# 6. Source citation present in every output
# ---------------------------------------------------------------------------

def test_source_citation_in_every_output():
    matches = evaluate_evidence(
        {
            "icd10": ["E11.9", "I50.22", "J44.1", "N18.4", "F33.2"],
            "loinc": [
                {"code": "4548-4", "value": 9.5},
                {"code": "10230-1", "value": 30.0},
                {"code": "62238-1", "value": 22.0},
            ],
        }
    )
    assert matches, "Expected several matches"
    for m in matches:
        assert m["source_citation"], f"missing citation: {m}"
        assert m["source_type"], f"missing source_type: {m}"


# ---------------------------------------------------------------------------
# 7. Lookup helpers
# ---------------------------------------------------------------------------

def test_get_rule_by_id():
    rule = get_rule(1)
    assert rule is not None
    assert rule["id"] == 1
    assert get_rule(99999) is None


def test_get_rules_by_hcc_filters():
    rules = get_rules_by_hcc("18")
    assert len(rules) >= 1
    assert all(r["output_hcc"] == "18" for r in rules)
    # Tolerant of "HCC18" prefix as well.
    assert get_rules_by_hcc("HCC18")


def test_get_rules_by_source_filters():
    ada = get_rules_by_source("ADA-guideline")
    assert len(ada) >= 4
    assert all(r["source_type"] == "ADA-guideline" for r in ada)


def test_list_rules_assigns_ids():
    rules = list_rules()
    ids = [r["id"] for r in rules]
    assert ids == list(range(1, len(rules) + 1))


# ---------------------------------------------------------------------------
# 8. Acceptance test from the brief
# ---------------------------------------------------------------------------

def test_acceptance_dm_uncontrolled_with_retinopathy():
    """Exact acceptance fixture from the brief."""
    matches = evaluate_evidence(
        {
            "icd10": ["E11.9", "H35.022"],
            "loinc": [{"code": "4548-4", "value": 9.2}],
        }
    )
    names = {m["rule_name"] for m in matches}
    assert "ada_dm_uncontrolled_hba1c_gt9" in names
    # Per AHA Coding Clinic combination-coding rule (note pattern not present
    # but DM+retinopathy ICD prefix triggers the AHA rule via E11 + ADA-side
    # retinopathy mapping handles HCC 18)
    assert "ada_dm_with_retinopathy" in names
