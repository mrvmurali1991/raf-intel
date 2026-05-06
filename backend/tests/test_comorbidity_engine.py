"""
Unit tests for the HCC comorbidity-patterns engine.

These tests are PURE: no database, no live backend.  They exercise
``_pattern_matches`` and ``evaluate_evidence_set`` against the seed catalog
loaded from ``backend.scripts.seed_comorbidity_patterns``.

Coverage
--------
* AND-semantics across required_evidence buckets
* ICD/HCC/ATC prefix matching + LOINC threshold operators
* Each marquee clinical example (DM→18, CKD staging, CHF severity, COPD,
  cancer staging, mental health, HIV, vascular) gets a happy-path test +
  a "missing one piece of evidence" negative test.
* Upgrade chains (HCC 19 → HCC 18 once retinopathy is added).
"""
from __future__ import annotations

import importlib.util
import os
import sys
import types
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Module loading — stub out app.db so the seed script can be imported without
# a live MySQL pool.  The pure engine functions still work because they only
# touch the DB when explicitly asked (and we never call those code paths).
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND   = REPO_ROOT / "backend"
sys.path.insert(0, str(BACKEND))

# Stub the openemr_connector + db modules BEFORE importing the engine, so its
# top-level imports succeed without a live MySQL.
if "app" not in sys.modules:
    fake_app = types.ModuleType("app")
    fake_app.__path__ = [str(BACKEND / "app")]  # type: ignore[attr-defined]
    sys.modules["app"] = fake_app

if "app.db" not in sys.modules:
    fake_db = types.ModuleType("app.db")

    def _raf_cursor(*_a, **_kw):  # pragma: no cover - tests do not hit DB
        raise RuntimeError("DB not available in unit tests")

    fake_db.raf_cursor = _raf_cursor  # type: ignore[attr-defined]
    sys.modules["app.db"] = fake_db

if "app.services" not in sys.modules:
    fake_services = types.ModuleType("app.services")
    fake_services.__path__ = [str(BACKEND / "app/services")]  # type: ignore[attr-defined]
    sys.modules["app.services"] = fake_services

if "app.services.openemr_connector" not in sys.modules:
    fake_emr = types.ModuleType("app.services.openemr_connector")
    fake_emr.get_billing_codes = lambda pid: []      # type: ignore[attr-defined]
    fake_emr.get_medications  = lambda pid: []       # type: ignore[attr-defined]
    fake_emr.get_labs         = lambda pid: []       # type: ignore[attr-defined]
    sys.modules["app.services.openemr_connector"] = fake_emr

# Now import the engine + the seed module.
from app.services.knowledge_graph import comorbidity_engine as engine  # noqa: E402

SEED_PATH = BACKEND / "scripts" / "seed_comorbidity_patterns.py"
_seed_spec = importlib.util.spec_from_file_location("seed_module", SEED_PATH)
seed_module = importlib.util.module_from_spec(_seed_spec)  # type: ignore[arg-type]
_seed_spec.loader.exec_module(seed_module)                # type: ignore[union-attr]
SEED_PATTERNS: list[dict] = seed_module.PATTERNS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get(name: str) -> dict:
    """Fetch a seeded pattern by name."""
    for p in SEED_PATTERNS:
        if p["pattern_name"] == name:
            return p
    raise AssertionError(f"seed pattern not found: {name}")


def _evaluate(evidence: dict, patterns: list[dict] | None = None) -> list[dict]:
    """Run the engine against in-memory patterns."""
    return engine.evaluate_evidence_set(evidence, patterns=patterns or SEED_PATTERNS)


# ===========================================================================
# 0. Catalog meta-tests
# ===========================================================================

def test_catalog_has_at_least_100_patterns():
    assert len(SEED_PATTERNS) >= 100, f"only {len(SEED_PATTERNS)} patterns seeded"


def test_every_pattern_has_a_source():
    bad = [p["pattern_name"] for p in SEED_PATTERNS if not p.get("source")]
    assert not bad, f"patterns missing source: {bad}"


def test_every_pattern_has_required_evidence():
    bad = [p["pattern_name"] for p in SEED_PATTERNS if not p.get("required_evidence")]
    assert not bad, f"patterns missing required_evidence: {bad}"


def test_pattern_names_unique():
    names = [p["pattern_name"] for p in SEED_PATTERNS]
    assert len(names) == len(set(names)), "duplicate pattern_name in seed"


# ===========================================================================
# 1. _pattern_matches — pure rule semantics
# ===========================================================================

def test_pattern_matches_and_semantics_all_present():
    p = {"required_evidence": {"hccs": ["19"], "icds": ["E11"]}, "pattern_name": "x"}
    ok, chain = engine._pattern_matches(p, {"hccs": ["19"], "icds": ["E11.9"]})
    assert ok
    assert any(c["type"] == "hcc" for c in chain)
    assert any(c["type"] == "icd" for c in chain)


def test_pattern_matches_and_semantics_one_missing():
    p = {"required_evidence": {"hccs": ["19"], "icds": ["E11", "H35"]}, "pattern_name": "x"}
    ok, chain = engine._pattern_matches(p, {"hccs": ["19"], "icds": ["E11.9"]})
    assert not ok
    assert chain == []


def test_pattern_matches_icd_prefix():
    p = {"required_evidence": {"icds": ["H35"]}, "pattern_name": "x"}
    # H35.31 (prolif retinopathy) should satisfy the H35 rule
    ok, _ = engine._pattern_matches(p, {"icds": ["H35.31"]})
    assert ok


def test_pattern_matches_atc_prefix():
    p = {"required_evidence": {"atc_codes": ["L04AB"]}, "pattern_name": "x"}
    # adalimumab is L04AB04
    ok, _ = engine._pattern_matches(p, {"atc_codes": ["L04AB04"]})
    assert ok


def test_pattern_matches_loinc_threshold_lt():
    p = {
        "required_evidence": {
            "icds": ["N18"],
            "loinc_with_threshold": [{"loinc": "33914-3", "op": "<", "value": 30}],
        },
        "pattern_name": "x",
    }
    ok, _ = engine._pattern_matches(
        p,
        {"icds": ["N18.4"], "labs": [{"loinc": "33914-3", "value": 22}]},
    )
    assert ok
    # Negative — eGFR 35 should not satisfy <30
    ok2, _ = engine._pattern_matches(
        p,
        {"icds": ["N18.4"], "labs": [{"loinc": "33914-3", "value": 35}]},
    )
    assert not ok2


def test_pattern_matches_loinc_threshold_gt():
    p = {
        "required_evidence": {
            "icds": ["E11"],
            "loinc_with_threshold": [{"loinc": "4548-4", "op": ">", "value": 9.0}],
        },
        "pattern_name": "x",
    }
    ok, _ = engine._pattern_matches(p, {"icds": ["E11.9"], "labs": [{"loinc": "4548-4", "value": 10.5}]})
    assert ok
    ok2, _ = engine._pattern_matches(p, {"icds": ["E11.9"], "labs": [{"loinc": "4548-4", "value": 8.0}]})
    assert not ok2


def test_pattern_matches_loinc_unknown_op_fails():
    p = {
        "required_evidence": {"loinc_with_threshold": [{"loinc": "X", "op": "NEAR", "value": 10}]},
        "pattern_name": "x",
    }
    ok, _ = engine._pattern_matches(p, {"labs": [{"loinc": "X", "value": 10}]})
    assert not ok


def test_pattern_matches_empty_evidence_fails():
    p = {"required_evidence": {"icds": ["E11"]}, "pattern_name": "x"}
    ok, _ = engine._pattern_matches(p, {})
    assert not ok


# ===========================================================================
# 2. Diabetes upgrades (HCC 19 → HCC 18)
# ===========================================================================

def test_dm_with_retinopathy_upgrades_to_hcc18():
    matches = _evaluate({"hccs": ["19"], "icds": ["E11.9", "H35.31"]})
    names = {m["pattern_name"] for m in matches}
    assert "dm_with_retinopathy_to_hcc18" in names
    upgrade = next(m for m in matches if m["pattern_name"] == "dm_with_retinopathy_to_hcc18")
    assert upgrade["output_hcc"] == "18"
    assert upgrade["upgrades_from"] == "19"
    # Evidence chain should reference HCC 19 + an ICD
    types_ = {c["type"] for c in upgrade["evidence_chain"]}
    assert {"hcc", "icd"}.issubset(types_)


def test_dm_with_retinopathy_negative_no_retinopathy():
    matches = _evaluate({"hccs": ["19"], "icds": ["E11.9"]})
    names = {m["pattern_name"] for m in matches}
    assert "dm_with_retinopathy_to_hcc18" not in names


def test_dm_with_nephropathy_upgrades_to_hcc18():
    matches = _evaluate({"hccs": ["19"], "icds": ["E11.9", "N18.3"]})
    names = {m["pattern_name"] for m in matches}
    assert "dm_with_nephropathy_to_hcc18" in names


def test_dm_with_nephropathy_negative_without_n18():
    matches = _evaluate({"hccs": ["19"], "icds": ["E11.9"]})
    names = {m["pattern_name"] for m in matches}
    assert "dm_with_nephropathy_to_hcc18" not in names


def test_dm_e1122_direct_to_hcc18_happy():
    matches = _evaluate({"icds": ["E11.22"]})
    names = {m["pattern_name"] for m in matches}
    assert "dm_e1122_direct_to_hcc18" in names


def test_dm_e1122_direct_negative():
    matches = _evaluate({"icds": ["E11.21"]})  # nephropathy alone, not DM-CKD
    names = {m["pattern_name"] for m in matches}
    assert "dm_e1122_direct_to_hcc18" not in names


def test_dm_with_neuropathy_happy():
    matches = _evaluate({"hccs": ["19"], "icds": ["E11.9", "E11.40"]})
    assert "dm_with_neuropathy_to_hcc18" in {m["pattern_name"] for m in matches}


def test_dm_with_neuropathy_negative():
    matches = _evaluate({"hccs": ["19"], "icds": ["E11.9"]})
    assert "dm_with_neuropathy_to_hcc18" not in {m["pattern_name"] for m in matches}


def test_dm_with_foot_ulcer_happy():
    matches = _evaluate({"hccs": ["19"], "icds": ["E11.621"]})
    assert "dm_with_foot_ulcer_to_hcc18" in {m["pattern_name"] for m in matches}


def test_dm_with_foot_ulcer_compound_negative_without_l97():
    matches = _evaluate({"icds": ["E11.621"]})  # no L97 site code
    assert "dm_with_foot_ulcer_compound_l97" not in {m["pattern_name"] for m in matches}


def test_dm_with_charcot_foot_happy():
    matches = _evaluate({"icds": ["E11.610"]})
    assert "dm_with_charcot_foot" in {m["pattern_name"] for m in matches}


def test_dm_chronic_with_morbid_obesity_compound():
    matches = _evaluate({"hccs": ["18"], "icds": ["E66.01"]})
    assert "dm_chronic_compl_with_morbid_obesity" in {m["pattern_name"] for m in matches}


def test_dm_dka_acute_complication():
    matches = _evaluate({"icds": ["E11.10"]})
    m = next(m for m in matches if m["pattern_name"] == "dm_with_ketoacidosis_acute")
    assert m["output_hcc"] == "17"
    assert m["upgrades_from"] == "19"


# ===========================================================================
# 3. CKD staging
# ===========================================================================

def test_ckd_stage4_egfr_under_30():
    matches = _evaluate({
        "icds": ["N18.9"],
        "labs": [{"loinc": "33914-3", "value": 22}],
    })
    m = next(m for m in matches if m["pattern_name"] == "ckd_stage4_from_egfr")
    assert m["output_hcc"] == "137"
    assert m["upgrades_from"] == "138"


def test_ckd_stage4_negative_egfr_45():
    matches = _evaluate({
        "icds": ["N18.9"],
        "labs": [{"loinc": "33914-3", "value": 45}],
    })
    assert "ckd_stage4_from_egfr" not in {m["pattern_name"] for m in matches}


def test_esrd_dialysis_z992():
    matches = _evaluate({"icds": ["N18.6", "Z99.2"]})
    assert "esrd_dialysis_z992" in {m["pattern_name"] for m in matches}


def test_esrd_negative_no_dialysis_status():
    matches = _evaluate({"icds": ["N18.5"]})
    assert "esrd_dialysis_z992" not in {m["pattern_name"] for m in matches}


def test_esrd_n186_direct():
    matches = _evaluate({"icds": ["N18.6"]})
    assert "esrd_n186_direct" in {m["pattern_name"] for m in matches}


# ===========================================================================
# 4. CHF severity
# ===========================================================================

def test_chf_acute_systolic_upgrade():
    matches = _evaluate({"icds": ["I50.21"]})
    m = next(m for m in matches if m["pattern_name"] == "chf_acute_on_chronic_systolic")
    assert m["output_hcc"] == "224"
    assert m["upgrades_from"] == "226"


def test_chf_low_ef_upgrade():
    matches = _evaluate({
        "icds": ["I50.9"],
        "labs": [{"loinc": "8806-2", "value": 28}],
    })
    assert "chf_with_low_ef_systolic" in {m["pattern_name"] for m in matches}


def test_chf_low_ef_negative_normal_ef():
    matches = _evaluate({
        "icds": ["I50.9"],
        "labs": [{"loinc": "8806-2", "value": 60}],
    })
    assert "chf_with_low_ef_systolic" not in {m["pattern_name"] for m in matches}


def test_chf_acute_pulm_edema_upgrade():
    matches = _evaluate({"icds": ["I50.1", "J81.0"]})
    assert "chf_with_acute_pulm_edema" in {m["pattern_name"] for m in matches}


def test_chf_acute_pulm_edema_negative():
    matches = _evaluate({"icds": ["I50.1"]})
    assert "chf_with_acute_pulm_edema" not in {m["pattern_name"] for m in matches}


# ===========================================================================
# 5. COPD progression
# ===========================================================================

def test_copd_with_acute_exacerbation():
    matches = _evaluate({"icds": ["J44.1"]})
    assert "copd_with_acute_exacerbation" in {m["pattern_name"] for m in matches}


def test_copd_with_chronic_resp_failure():
    matches = _evaluate({"icds": ["J44.9", "J96.10"]})
    assert "copd_with_chronic_resp_failure" in {m["pattern_name"] for m in matches}


def test_copd_with_chronic_resp_failure_negative():
    matches = _evaluate({"icds": ["J44.9"]})
    assert "copd_with_chronic_resp_failure" not in {m["pattern_name"] for m in matches}


# ===========================================================================
# 6. Cancer staging
# ===========================================================================

def test_active_cancer_breast_with_chemo():
    matches = _evaluate({"icds": ["C50.911", "Z51.11"]})
    assert "active_cancer_breast_with_chemo" in {m["pattern_name"] for m in matches}


def test_active_cancer_breast_without_chemo_negative():
    matches = _evaluate({"icds": ["C50.911"]})
    assert "active_cancer_breast_with_chemo" not in {m["pattern_name"] for m in matches}


def test_metastatic_cancer_secondary_codes():
    matches = _evaluate({"icds": ["C77.9"]})
    m = next(m for m in matches if m["pattern_name"] == "metastatic_cancer_secondary_codes")
    assert m["output_hcc"] == "17"


# ===========================================================================
# 7. Mental health
# ===========================================================================

def test_bipolar_severe_psychotic():
    matches = _evaluate({"icds": ["F31.5"]})
    m = next(m for m in matches if m["pattern_name"] == "bipolar_severe_psychotic")
    assert m["output_hcc"] == "151"
    assert m["upgrades_from"] == "152"


def test_schizophrenia_with_clozapine():
    matches = _evaluate({"icds": ["F20.0"], "atc_codes": ["N05AH02"]})
    assert "schizophrenia_with_clozapine" in {m["pattern_name"] for m in matches}


def test_schizophrenia_with_clozapine_negative_no_drug():
    matches = _evaluate({"icds": ["F20.0"]})
    assert "schizophrenia_with_clozapine" not in {m["pattern_name"] for m in matches}


# ===========================================================================
# 8. HIV / AIDS
# ===========================================================================

def test_hiv_b20_direct():
    matches = _evaluate({"icds": ["B20"]})
    assert "hiv_b20_direct" in {m["pattern_name"] for m in matches}


def test_hiv_with_pcp_pneumonia():
    matches = _evaluate({"icds": ["B20", "B59"]})
    assert "hiv_with_pcp_pneumonia" in {m["pattern_name"] for m in matches}


def test_hiv_with_pcp_negative_no_pcp():
    matches = _evaluate({"icds": ["B20"]})
    assert "hiv_with_pcp_pneumonia" not in {m["pattern_name"] for m in matches}


# ===========================================================================
# 9. Vascular complexity
# ===========================================================================

def test_pvd_with_amputation_status():
    matches = _evaluate({"icds": ["I70.0", "Z89.511"]})
    assert "pvd_with_amputation_status" in {m["pattern_name"] for m in matches}


def test_dm_pvd_with_amputation_compound():
    matches = _evaluate({"icds": ["E11.9", "I70.219", "Z89.611"]})
    assert "dm_pvd_with_amputation_compound" in {m["pattern_name"] for m in matches}


def test_dm_pvd_with_amputation_negative_no_amp():
    matches = _evaluate({"icds": ["E11.9", "I70.219"]})
    assert "dm_pvd_with_amputation_compound" not in {m["pattern_name"] for m in matches}


# ===========================================================================
# 10. Upgrade-chain ordering and sort
# ===========================================================================

def test_upgrade_chain_dm_19_to_18_with_retinopathy():
    """The marquee acceptance test from the task brief:
    a HCC 19 patient gains retinopathy → engine emits HCC 18 upgrade with
    full evidence chain.
    """
    evidence = {"hccs": ["19"], "icds": ["E11.9", "H35.31"]}
    matches = _evaluate(evidence)
    assert matches, "expected at least one match for DM + retinopathy"
    upgrade = next(m for m in matches if m["pattern_name"] == "dm_with_retinopathy_to_hcc18")
    assert upgrade["output_hcc"] == "18"
    assert upgrade["upgrades_from"] == "19"
    assert upgrade["confidence"] >= 0.8
    assert upgrade["source"] == seed_module.CMS_V28_SPEC
    # Evidence chain must reference the HCC 19 fact AND at least one ICD
    chain_types = [c["type"] for c in upgrade["evidence_chain"]]
    assert "hcc" in chain_types
    assert "icd" in chain_types


def test_evaluate_results_sorted_by_confidence_desc():
    matches = _evaluate({"icds": ["E11.9", "H35.31", "E66.01"], "hccs": ["19", "18"]})
    confs = [m["confidence"] for m in matches]
    assert confs == sorted(confs, reverse=True)


# ===========================================================================
# 11. Code-normalisation regression tests
# ===========================================================================

def test_norm_hcc_strips_prefix_and_zeros():
    assert engine._norm_hcc("HCC 019") == "19"
    assert engine._norm_hcc("hcc18") == "18"
    assert engine._norm_hcc(19) == "19"
    assert engine._norm_hcc(None) == ""


def test_norm_icd_dots_and_case():
    assert engine._norm_icd("e11.22") == "E1122"
    assert engine._norm_icd("E1122") == "E1122"
    assert engine._norm_icd(None) == ""


def test_evaluate_with_no_patterns_returns_empty():
    assert _evaluate({"icds": ["E11.9"]}, patterns=[]) == []


# ===========================================================================
# 12. Round-trip: every seed pattern can be matched by its own required evidence
# ===========================================================================

def test_every_pattern_is_self_satisfiable():
    """For each pattern, build the *minimal* evidence set from its own
    required_evidence and confirm the pattern fires.  Catches typos in either
    the seed catalog or the matcher.
    """
    failures = []
    for p in SEED_PATTERNS:
        req = p["required_evidence"]
        ev: dict[str, list] = {"hccs": [], "icds": [], "atc_codes": [], "labs": []}
        for h in req.get("hccs") or []:
            ev["hccs"].append(h)
        for i in req.get("icds") or []:
            # Build a leaf code by appending '0' so prefix match still works
            ev["icds"].append(str(i) + "0")
        for a in req.get("atc_codes") or []:
            ev["atc_codes"].append(str(a) + "00")
        for r in req.get("loinc_with_threshold") or []:
            op = r.get("op", ">")
            t = float(r.get("value", 0))
            # Choose a value that satisfies the op
            if op in (">", ">="):
                v = t + 1
            elif op in ("<", "<="):
                v = t - 1
            else:
                v = t
            ev["labs"].append({"loinc": r.get("loinc"), "value": v})
        ok, _ = engine._pattern_matches(p, ev)
        if not ok:
            failures.append(p["pattern_name"])
    assert not failures, f"patterns failed self-satisfy: {failures}"
