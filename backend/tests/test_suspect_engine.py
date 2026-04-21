"""Unit tests for the hybrid suspect engine (Agent 8)."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from app.services.ai_pipeline import suspect_engine as se
from app.services.ai_pipeline.rules import (
    cardiac,
    diabetes,
    hematology,
    hepatic,
    lipid,
    renal,
    respiratory,
)
from app.services.ai_pipeline.suspect_schema import SuspectCandidate


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
def _lab(name, value, lab_id="L1", date="2026-01-01", unit=""):
    return {"id": lab_id, "name": name, "value": value, "unit": unit, "date": date}


def _med(name, med_id="M1", cls=""):
    return {"id": med_id, "name": name, "class": cls, "active": True}


# ---------------------------------------------------------------------------
# Diabetes
# ---------------------------------------------------------------------------
def test_diabetes_two_high_a1c_flags_suspect():
    bundle = {
        "labs": [_lab("HbA1c", 7.8, "L1", "2026-01-01"), _lab("HbA1c", 7.2, "L2", "2025-10-01")],
        "medications": [],
        "problem_list": [],
    }
    c = diabetes._two_high_a1c(bundle)
    assert c and c.icd10 == "E11.9" and c.hcc == "HCC37"
    assert len(c.supporting_evidence) == 2


def test_diabetes_already_coded_is_skipped():
    bundle = {
        "labs": [_lab("HbA1c", 7.8), _lab("HbA1c", 7.5)],
        "problem_list": [{"icd10": "E11.9", "active": True}],
    }
    assert diabetes._two_high_a1c(bundle) is None


def test_diabetes_a1c_plus_metformin():
    bundle = {
        "labs": [_lab("HbA1c", 6.8)],
        "medications": [_med("metformin 500 mg")],
        "problem_list": [],
    }
    c = diabetes._a1c_plus_antidiabetic(bundle)
    assert c and c.confidence >= 0.85


# ---------------------------------------------------------------------------
# Renal
# ---------------------------------------------------------------------------
def test_renal_two_low_egfr():
    bundle = {
        "labs": [_lab("eGFR", 42), _lab("eGFR", 38)],
        "problem_list": [],
    }
    c = renal._low_egfr(bundle)
    assert c and c.icd10.startswith("N18")


def test_renal_stage_from_value():
    bundle = {"labs": [_lab("eGFR", 20), _lab("eGFR", 22)], "problem_list": []}
    c = renal._low_egfr(bundle)
    assert c.icd10 == "N18.4"


def test_renal_skipped_if_coded():
    bundle = {"labs": [_lab("eGFR", 40), _lab("eGFR", 38)], "problem_list": [{"icd10": "N18.3"}]}
    assert renal._low_egfr(bundle) is None


# ---------------------------------------------------------------------------
# Cardiac
# ---------------------------------------------------------------------------
def test_chf_bnp_plus_furosemide():
    bundle = {
        "labs": [_lab("BNP", 850)],
        "medications": [_med("furosemide 40 mg")],
        "problem_list": [],
    }
    c = cardiac._chf_bnp_loop(bundle)
    assert c and c.icd10 == "I50.9"


def test_chf_requires_diuretic():
    bundle = {"labs": [_lab("BNP", 850)], "medications": [], "problem_list": []}
    assert cardiac._chf_bnp_loop(bundle) is None


# ---------------------------------------------------------------------------
# Lipid
# ---------------------------------------------------------------------------
def test_lipid_ldl_plus_statin():
    bundle = {
        "labs": [_lab("LDL-C", 160)],
        "medications": [_med("atorvastatin 40 mg")],
        "problem_list": [],
    }
    c = lipid._ldl_plus_statin(bundle)
    assert c and c.icd10 == "E78.5"


# ---------------------------------------------------------------------------
# Respiratory
# ---------------------------------------------------------------------------
def test_copd_lama():
    bundle = {"medications": [_med("tiotropium inhaler")], "problem_list": []}
    c = respiratory._copd_long_acting(bundle)
    assert c and c.icd10 == "J44.9"


# ---------------------------------------------------------------------------
# Hepatic
# ---------------------------------------------------------------------------
def test_cirrhosis_triad():
    bundle = {
        "labs": [_lab("Platelet", 110), _lab("INR", 1.5), _lab("Albumin", 3.0)],
        "problem_list": [],
    }
    c = hepatic._cirrhosis_signals(bundle)
    assert c and c.hcc == "HCC32"


def test_cirrhosis_single_signal_insufficient():
    bundle = {"labs": [_lab("Platelet", 110)], "problem_list": []}
    assert hepatic._cirrhosis_signals(bundle) is None


# ---------------------------------------------------------------------------
# Hematology / endocrine
# ---------------------------------------------------------------------------
def test_anemia_low_hgb():
    bundle = {"labs": [_lab("Hemoglobin", 9.5)], "problem_list": []}
    c = hematology._anemia(bundle)
    assert c and c.icd10 == "D64.9"


def test_hypothyroid_tsh_plus_levothyroxine():
    bundle = {
        "labs": [_lab("TSH", 8.2)],
        "medications": [_med("levothyroxine 50 mcg")],
        "problem_list": [],
    }
    c = hematology._hypothyroid(bundle)
    assert c and c.confidence >= 0.8


def test_morbid_obesity_bmi():
    bundle = {"vitals": [{"id": "V1", "type": "BMI", "value": 42.3}], "problem_list": []}
    c = hematology._morbid_obesity(bundle)
    assert c and c.icd10 == "E66.01"


# ---------------------------------------------------------------------------
# Merge & dedupe
# ---------------------------------------------------------------------------
def test_merge_dedupes_by_family_and_marks_both():
    rule_c = SuspectCandidate(icd10="E11.9", hcc="HCC37", reason="rule", confidence=0.8, source="rule")
    llm_c = SuspectCandidate(icd10="E11.65", hcc="HCC37", reason="llm", confidence=0.6, source="llm")
    merged = se.merge([rule_c], [llm_c])
    assert len(merged) == 1
    assert merged[0].source == "both"
    assert merged[0].icd10 == "E11.9"  # rule wins on specific code
    assert merged[0].confidence > 0.8


def test_every_candidate_requires_provider_query():
    bundle = {
        "labs": [_lab("HbA1c", 8.0), _lab("HbA1c", 7.6)],
        "medications": [_med("metformin")],
        "problem_list": [],
    }
    results = se.run_rules(bundle)
    assert results
    assert all(c.requires_provider_query for c in results)


def test_detect_suspects_rule_only_when_llm_disabled():
    bundle = {
        "labs": [_lab("HbA1c", 8.0), _lab("HbA1c", 7.8)],
        "problem_list": [],
    }
    out = se.detect_suspects(bundle, use_llm=False)
    assert any(c.icd10.startswith("E11") for c in out)
    assert all(c.source == "rule" for c in out)


def test_detect_suspects_merges_llm(monkeypatch):
    bundle = {
        "labs": [_lab("eGFR", 40), _lab("eGFR", 38)],
        "problem_list": [],
    }
    fake_resp = (
        '{"suspects":[{"icd10":"N18.3","hcc":"HCC138","reason":"llm",'
        '"supporting_evidence":[{"type":"lab","ref_id":"L1","value":"eGFR=40"}],'
        '"confidence":0.7}]}'
    )
    with patch.object(se, "llm_generate", return_value=fake_resp):
        out = se.detect_suspects(bundle, use_llm=True)
    assert len(out) == 1
    assert out[0].source == "both"
    assert out[0].requires_provider_query is True


def test_llm_bad_json_returns_empty():
    with patch.object(se, "llm_generate", return_value="not-json"):
        assert se.run_llm({}) == []


def test_rule_inventory_count():
    # Starter inventory: 12 rules across 7 disease families.
    from app.services.ai_pipeline.rules import ALL_RULES
    assert len(ALL_RULES) >= 10


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
