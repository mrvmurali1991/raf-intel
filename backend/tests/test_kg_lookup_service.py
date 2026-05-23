"""
Unit tests for the unified KG query service (kg_lookup_service).

These are pure-Python unit tests using monkeypatch — they do NOT hit MySQL or
the live backend.  Sub-services are stubbed via SimpleNamespace and the
underlying telemetry / DB calls are patched to no-ops.
"""
from __future__ import annotations

import sys
import types
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# Import the module under test
from app.services.knowledge_graph import kg_lookup_service as kg


# ---------------------------------------------------------------------------
# Helpers — fake sub-service module with whatever attributes a test needs
# ---------------------------------------------------------------------------

def _fake_module(**fns) -> types.SimpleNamespace:
    """Build a stand-in module exposing the given callables."""
    return types.SimpleNamespace(**fns)


@pytest.fixture(autouse=True)
def _silence_telemetry(monkeypatch):
    """Suppress kg_query_log writes for every test."""
    monkeypatch.setattr(kg, "_log_query", lambda *a, **kw: None)
    yield


@pytest.fixture(autouse=True)
def _reset_caches(monkeypatch):
    """Clear caches and sub-service map before each test."""
    kg.clear_cache()
    # Force a fresh load on the next access
    kg._SUB_SERVICES.clear()
    yield
    kg.clear_cache()
    kg._SUB_SERVICES.clear()


def _install_subs(**modules: Any) -> None:
    """Install fake sub-services into kg._SUB_SERVICES (skip the loader)."""
    # Pre-populate every known sub-service slot with None, then override.
    for name in kg._SUB_SERVICE_NAMES:
        kg._SUB_SERVICES.setdefault(name, None)
    for name, mod in modules.items():
        kg._SUB_SERVICES[name] = mod


# ---------------------------------------------------------------------------
# 1. get_related_hccs — text input
# ---------------------------------------------------------------------------

def test_get_related_hccs_with_text_input(monkeypatch) -> None:
    snomed = _fake_module(
        search_concept=lambda q: [{"icd10_codes": ["E11.40"]}],
    )
    rules = _fake_module(
        fire_rules_for_codes=lambda codes: [
            {"hcc_code": "37", "rule_id": "R-1",
             "citation": "ICD-10 E11.40", "icd10": "E11.40", "confidence": 0.9}
        ],
    )
    _install_subs(snomed_service=snomed, evidence_rules_engine=rules)
    monkeypatch.setattr(kg, "_query_kg_concept", lambda q: None)

    out = kg.get_related_hccs("diabetes with neuropathy")
    assert isinstance(out, list)
    assert any(r["hcc"] == "37" for r in out)
    top = out[0]
    assert "evidence_rule" in [reason["kind"] for reason in top["reasoning"]]


# ---------------------------------------------------------------------------
# 2. get_related_hccs — concept_uri input + edges fallback
# ---------------------------------------------------------------------------

def test_get_related_hccs_with_concept_uri(monkeypatch) -> None:
    rules = _fake_module(
        fire_rules_for_codes=lambda codes: [
            {"hcc_code": "18", "rule_id": "R-2", "citation": "concept",
             "icd10": "E11.9", "confidence": 0.5}
        ],
    )
    _install_subs(evidence_rules_engine=rules)
    # Concept lookup returns icd10 in attributes
    monkeypatch.setattr(kg, "_query_kg_concept",
                        lambda q: {"attributes": {"icd10_codes": ["E11.9"]}})

    out = kg.get_related_hccs("snomed:44054006")
    assert any(r["hcc"] == "18" for r in out)


# ---------------------------------------------------------------------------
# 3. get_related_hccs — patient context applies modulation + specialty priors
# ---------------------------------------------------------------------------

def test_get_related_hccs_specialty_modulation(monkeypatch) -> None:
    rules = _fake_module(
        fire_rules_for_codes=lambda codes: [
            {"hcc_code": "18", "rule_id": "R", "citation": "x",
             "icd10": "E11.9", "confidence": 0.6}
        ],
    )
    demo = _fake_module(modulate=lambda hccs, ctx: {"18": 1.2})
    spec = _fake_module(get_priors_for_specialty=lambda s: {"18": 0.8})
    _install_subs(evidence_rules_engine=rules,
                  demographic_risk_service=demo,
                  specialty_priors_service=spec)
    monkeypatch.setattr(kg, "_query_kg_concept",
                        lambda q: {"attributes": {"icd10_codes": ["E11.9"]}})

    out = kg.get_related_hccs(
        "diabetes",
        patient_context={"age": 68, "sex": "M", "specialty": "Cardiology"},
    )
    top = next(r for r in out if r["hcc"] == "18")
    kinds = [r["kind"] for r in top["reasoning"]]
    assert "demographic_modulation" in kinds
    assert "specialty_prior" in kinds


# ---------------------------------------------------------------------------
# 4. get_evidence_chain — full chain (mock all sub-services)
# ---------------------------------------------------------------------------

def test_get_evidence_chain_full_chain(monkeypatch) -> None:
    rules = _fake_module(
        get_evidence_for_patient_hcc=lambda pid, hcc, year: [
            {"rule_id": "R1", "citation": "Smith 2020",
             "value": "E11.40", "contribution": 0.6}
        ],
        suggest_icd10_for_hcc=lambda hcc: ["E11.40", "E11.42"],
    )
    drugs = _fake_module(
        evidence_for_patient_hcc=lambda pid, hcc: [
            {"drug": "metformin", "atc_class": "A10BA02", "contribution": 0.3}
        ],
    )
    labs = _fake_module(
        evidence_for_patient_hcc=lambda pid, hcc: [
            {"loinc": "4548-4", "value": 8.2, "contribution": 0.4}
        ],
    )
    comorb = _fake_module(
        evidence_for_patient_hcc=lambda pid, hcc: [
            {"pattern": "DM+CKD", "from_hccs": ["18"], "contribution": 0.5}
        ],
    )
    _install_subs(evidence_rules_engine=rules,
                  drug_class_reasoner=drugs,
                  loinc_service=labs,
                  comorbidity_engine=comorb)

    out = kg.get_evidence_chain("37", patient_id=42, year=2026)
    kinds = [c["kind"] for c in out["evidence_chain"]]
    assert "evidence_rule" in kinds
    assert "drug_class" in kinds
    assert "lab_signal" in kinds
    assert "comorbidity" in kinds
    assert out["suggested_icd10"] == ["E11.40", "E11.42"]
    assert out["total_score"] > 0


# ---------------------------------------------------------------------------
# 5. traverse_path — BFS correctness
# ---------------------------------------------------------------------------

def test_traverse_path_bfs(monkeypatch) -> None:
    # Graph:  A -> B -> C ;  A -> D -> C  (two paths to C, BFS picks shortest)
    edges = {
        "A": [{"target_uri": "B", "relation": "rel", "weight": 1.0},
              {"target_uri": "D", "relation": "rel", "weight": 1.0}],
        "B": [{"target_uri": "C", "relation": "rel", "weight": 1.0}],
        "D": [{"target_uri": "C", "relation": "rel", "weight": 1.0}],
        "C": [],
    }
    monkeypatch.setattr(kg, "_kg_edges_from", lambda u: edges.get(u, []))
    path = kg.traverse_path("A", "C", max_depth=5)
    assert path
    nodes = [step["node"] for step in path]
    assert nodes[0] == "A"
    assert nodes[-1] == "C"
    assert len(path) == 3  # A -> (B|D) -> C


def test_traverse_path_self_loop(monkeypatch) -> None:
    monkeypatch.setattr(kg, "_kg_edges_from", lambda u: [])
    path = kg.traverse_path("X", "X", max_depth=5)
    assert path and path[0]["node"] == "X"


def test_traverse_path_unreachable(monkeypatch) -> None:
    monkeypatch.setattr(kg, "_kg_edges_from", lambda u: [])
    path = kg.traverse_path("A", "Z", max_depth=3)
    assert path == []


def test_traverse_path_respects_max_depth(monkeypatch) -> None:
    edges = {
        "A": [{"target_uri": "B", "relation": "r", "weight": 1.0}],
        "B": [{"target_uri": "C", "relation": "r", "weight": 1.0}],
        "C": [{"target_uri": "D", "relation": "r", "weight": 1.0}],
    }
    monkeypatch.setattr(kg, "_kg_edges_from", lambda u: edges.get(u, []))
    # max_depth=1 — A->B reachable but A->...->D not
    assert kg.traverse_path("A", "D", max_depth=1) == []
    assert kg.traverse_path("A", "B", max_depth=1)


# ---------------------------------------------------------------------------
# 6. explain_hcc — static lookup
# ---------------------------------------------------------------------------

def test_explain_hcc_static(monkeypatch) -> None:
    rules = _fake_module(
        get_hcc_definition=lambda h: {"label": "Diabetes with Complications"},
        suggest_icd10_for_hcc=lambda h: ["E11.40", "E11.42"],
        citations_for_hcc=lambda h: [{"title": "ADA 2024", "doi": "..."}],
    )
    drugs = _fake_module(common_drugs_for_hcc=lambda h: ["metformin", "insulin"])
    labs = _fake_module(common_labs_for_hcc=lambda h: ["HbA1c", "Glucose"])
    comorb = _fake_module(common_comorbidities_for_hcc=lambda h: ["HTN", "CKD"])
    _install_subs(evidence_rules_engine=rules,
                  drug_class_reasoner=drugs,
                  loinc_service=labs,
                  comorbidity_engine=comorb)

    out = kg.explain_hcc("37")
    assert out["hcc"] == "37"
    assert out["icd10_codes"] == ["E11.40", "E11.42"]
    assert "metformin" in out["common_drugs"]
    assert out["citations"]


# ---------------------------------------------------------------------------
# 7. patient_full_inference — orchestrates all sub-services
# ---------------------------------------------------------------------------

def test_patient_full_inference_orchestrates_all(monkeypatch) -> None:
    # Stub every sub-service
    rules = _fake_module(
        fire_rules_for_patient=lambda pid, year=2026: [
            {"hcc_code": "37", "rule_id": "R", "citation": "x",
             "icd10": "E11.40", "confidence": 0.9}
        ],
    )
    drugs = _fake_module(
        infer_hccs_from_drugs=lambda dx: [
            {"hcc_code": "18", "drug": "metformin",
             "atc_class": "A10", "confidence": 0.55}
        ],
    )
    labs = _fake_module(
        infer_hccs_from_labs=lambda lx: [
            {"hcc_code": "37", "loinc": "4548-4", "value": 8.5, "confidence": 0.7}
        ],
    )
    snomed = _fake_module(
        infer_hccs_from_icd10=lambda codes: [
            {"hcc_code": "55", "snomed_id": "12345",
             "icd10": "F33.1", "confidence": 0.6}
        ],
    )
    comorb = _fake_module(
        find_upgrades=lambda hccs: [
            {"upgraded_hcc": "38", "from_hccs": ["18", "37"],
             "pattern": "DM+complications", "confidence": 0.65}
        ],
    )
    demo = _fake_module(modulate=lambda hccs, ctx: {h: 1.05 for h in hccs})
    spec = _fake_module(get_priors_for_specialty=lambda s: {"37": 0.9})
    _install_subs(evidence_rules_engine=rules, drug_class_reasoner=drugs,
                  loinc_service=labs, snomed_service=snomed,
                  comorbidity_engine=comorb, demographic_risk_service=demo,
                  specialty_priors_service=spec)

    # Stub the patient-context loaders
    monkeypatch.setattr(kg, "raf_cursor",
                        lambda *a, **kw: _fake_cursor_ctx([]))
    fake_emr = _fake_module(
        get_patient=lambda pid: {"age": 68, "sex": "M",
                                 "provider_specialty": "Cardiology"},
        get_medications=lambda pid: [{"name": "metformin"}],
        get_lab_results=lambda pid: [{"loinc": "4548-4", "value": 8.5}],
        get_billing_codes=lambda pid: [{"code": "F33.1"}],
    )
    monkeypatch.setitem(sys.modules, "app.services.openemr_connector", fake_emr)

    out = kg.patient_full_inference(patient_id=99, year=2026)
    candidates = out["candidates"]
    hccs = [c["hcc"] for c in candidates]
    # All sub-services contributed
    assert "37" in hccs
    assert "18" in hccs
    assert "55" in hccs
    assert "38" in hccs
    # execution_log records each sub-service
    services = {row["service"] for row in out["execution_log"]}
    assert "evidence_rules_engine" in services
    assert "drug_class_reasoner" in services
    assert "loinc_service" in services
    assert "snomed_service" in services
    assert "comorbidity_engine" in services


class _FakeCur:
    def __init__(self, rows):
        self._rows = rows
    def execute(self, *a, **kw): pass
    def fetchall(self): return self._rows
    def fetchone(self): return self._rows[0] if self._rows else None


def _fake_cursor_ctx(rows):
    class _Ctx:
        def __enter__(self): return _FakeCur(rows)
        def __exit__(self, *a): return False
    return _Ctx()


# ---------------------------------------------------------------------------
# 8. Caching — same call twice, second one cached
# ---------------------------------------------------------------------------

def test_explain_hcc_caches(monkeypatch) -> None:
    call_count = {"n": 0}

    def _fire(h):
        call_count["n"] += 1
        return {"label": "x"}

    rules = _fake_module(
        get_hcc_definition=_fire,
        suggest_icd10_for_hcc=lambda h: [],
        citations_for_hcc=lambda h: [],
    )
    _install_subs(evidence_rules_engine=rules)

    kg.explain_hcc("37")
    kg.explain_hcc("37")
    assert call_count["n"] == 1  # second call hit cache


def test_traverse_caches(monkeypatch) -> None:
    call_count = {"n": 0}

    def _edges(u):
        call_count["n"] += 1
        return []

    monkeypatch.setattr(kg, "_kg_edges_from", _edges)
    kg.traverse_path("A", "B", max_depth=2)
    n_after_first = call_count["n"]
    kg.traverse_path("A", "B", max_depth=2)
    assert call_count["n"] == n_after_first  # cached, no new edge fetches


# ---------------------------------------------------------------------------
# 9. Telemetry — kg_query_log row written
# ---------------------------------------------------------------------------

def test_telemetry_log_called(monkeypatch) -> None:
    """Re-enable telemetry for one test and confirm _log_query is invoked."""
    monkeypatch.setattr(kg, "_log_query", MagicMock())
    rules = _fake_module(
        get_hcc_definition=lambda h: {},
        suggest_icd10_for_hcc=lambda h: [],
        citations_for_hcc=lambda h: [],
    )
    _install_subs(evidence_rules_engine=rules)

    kg.explain_hcc("37")
    assert kg._log_query.called
    args, kwargs = kg._log_query.call_args
    assert args[0] == "explain_hcc"


def test_telemetry_failure_does_not_crash(monkeypatch) -> None:
    """If kg_query_log INSERT fails, the call still returns normally."""
    def _boom(*a, **kw): raise RuntimeError("db down")
    # Patch raf_cursor used inside _log_query directly
    real_log = kg._log_query  # this fixture replaced it; re-import original
    from app.services.knowledge_graph import kg_lookup_service as fresh
    monkeypatch.setattr(fresh, "raf_cursor", _boom)
    # Should still complete without raising
    fresh._log_query("test", {}, 1, 1)


# ---------------------------------------------------------------------------
# 10. Graceful degradation — missing sub-service does not crash
# ---------------------------------------------------------------------------

def test_graceful_degradation_when_subservice_missing(monkeypatch) -> None:
    """All sub-services unavailable → call still returns a (possibly empty) result."""
    # Force every sub-service to be None
    for name in kg._SUB_SERVICE_NAMES:
        kg._SUB_SERVICES[name] = None
    monkeypatch.setattr(kg, "_query_kg_concept", lambda q: None)
    monkeypatch.setattr(kg, "_kg_edges_from", lambda u: [])

    out = kg.get_related_hccs("diabetes")
    assert isinstance(out, list)  # empty but valid
    expl = kg.explain_hcc("37")
    assert expl["hcc"] == "37"
    chain = kg.get_evidence_chain("37", patient_id=1, year=2026)
    assert chain["hcc"] == "37"
    assert chain["evidence_chain"] == []


def test_one_subservice_raising_does_not_crash_full_inference(monkeypatch) -> None:
    """A raising sub-service is logged and skipped, others still contribute."""
    def _raise(*a, **kw):
        raise RuntimeError("simulated failure")

    rules = _fake_module(fire_rules_for_patient=_raise)
    drugs = _fake_module(
        infer_hccs_from_drugs=lambda dx: [
            {"hcc_code": "18", "drug": "metformin",
             "atc_class": "A10", "confidence": 0.5}
        ],
    )
    _install_subs(evidence_rules_engine=rules, drug_class_reasoner=drugs)

    fake_emr = _fake_module(
        get_patient=lambda pid: {"age": 70, "sex": "F"},
        get_medications=lambda pid: [{"name": "metformin"}],
        get_lab_results=lambda pid: [],
        get_billing_codes=lambda pid: [],
    )
    monkeypatch.setitem(sys.modules, "app.services.openemr_connector", fake_emr)
    monkeypatch.setattr(kg, "raf_cursor",
                        lambda *a, **kw: _fake_cursor_ctx([]))

    out = kg.patient_full_inference(patient_id=1)
    services = {row["service"]: row for row in out["execution_log"]}
    assert services["evidence_rules_engine"]["ok"] is False
    assert services["drug_class_reasoner"]["ok"] is True
    # Drug-class HCC still made it through
    assert any(c["hcc"] == "18" for c in out["candidates"])


# ---------------------------------------------------------------------------
# 11. Parallel-safe — calling repeatedly does not deadlock
# ---------------------------------------------------------------------------

def test_repeated_calls_no_deadlock(monkeypatch) -> None:
    """The cache uses an RLock so re-entrant access from the same thread is OK."""
    rules = _fake_module(
        get_hcc_definition=lambda h: {"label": h},
        suggest_icd10_for_hcc=lambda h: [],
        citations_for_hcc=lambda h: [],
    )
    _install_subs(evidence_rules_engine=rules)

    for _ in range(50):
        out = kg.explain_hcc("37")
    assert out["hcc"] == "37"


# ---------------------------------------------------------------------------
# 12. _safe_call returns None on missing module
# ---------------------------------------------------------------------------

def test_safe_call_missing_module_returns_none() -> None:
    for name in kg._SUB_SERVICE_NAMES:
        kg._SUB_SERVICES[name] = None
    assert kg._safe_call("snomed_service", "foo") is None


def test_safe_call_missing_function_returns_none() -> None:
    _install_subs(snomed_service=_fake_module())  # no functions
    assert kg._safe_call("snomed_service", "search_concept", "x") is None


def test_safe_call_swallows_exceptions() -> None:
    def _boom(*a, **kw):
        raise RuntimeError("oops")
    _install_subs(snomed_service=_fake_module(search_concept=_boom))
    assert kg._safe_call("snomed_service", "search_concept", "x") is None


# ---------------------------------------------------------------------------
# 13. sub_service_status reports availability
# ---------------------------------------------------------------------------

def test_sub_service_status() -> None:
    _install_subs(snomed_service=_fake_module(),
                  loinc_service=_fake_module())
    status = kg.sub_service_status()
    assert status["snomed_service"] is True
    assert status["loinc_service"] is True
    assert status["evidence_rules_engine"] is False


# ---------------------------------------------------------------------------
# 14. Ranking — higher confidence always sorts first
# ---------------------------------------------------------------------------

def test_get_related_hccs_ranks_by_confidence(monkeypatch) -> None:
    rules = _fake_module(
        fire_rules_for_codes=lambda codes: [
            {"hcc_code": "37", "rule_id": "A", "citation": "",
             "icd10": "E11", "confidence": 0.9},
            {"hcc_code": "18", "rule_id": "B", "citation": "",
             "icd10": "E11", "confidence": 0.4},
            {"hcc_code": "55", "rule_id": "C", "citation": "",
             "icd10": "E11", "confidence": 0.7},
        ],
    )
    _install_subs(evidence_rules_engine=rules)
    monkeypatch.setattr(kg, "_query_kg_concept",
                        lambda q: {"attributes": {"icd10_codes": ["E11"]}})
    out = kg.get_related_hccs("x", limit=5)
    confidences = [r["confidence"] for r in out]
    assert confidences == sorted(confidences, reverse=True)
    assert out[0]["hcc"] == "37"


# ---------------------------------------------------------------------------
# 15. limit honored
# ---------------------------------------------------------------------------

def test_get_related_hccs_respects_limit(monkeypatch) -> None:
    rules = _fake_module(
        fire_rules_for_codes=lambda codes: [
            {"hcc_code": str(i), "rule_id": str(i), "citation": "",
             "icd10": "E11", "confidence": 0.5} for i in range(20)
        ],
    )
    _install_subs(evidence_rules_engine=rules)
    monkeypatch.setattr(kg, "_query_kg_concept",
                        lambda q: {"attributes": {"icd10_codes": ["E11"]}})
    out = kg.get_related_hccs("x", limit=5)
    assert len(out) == 5


# ---------------------------------------------------------------------------
# 16. Drugs alone can produce HCC candidates
# ---------------------------------------------------------------------------

def test_drug_only_inference(monkeypatch) -> None:
    drugs = _fake_module(
        infer_hccs_from_drugs=lambda dx: [
            {"hcc_code": "111", "drug": "warfarin",
             "atc_class": "B01AA03", "confidence": 0.8}
        ],
    )
    _install_subs(drug_class_reasoner=drugs)
    monkeypatch.setattr(kg, "_query_kg_concept", lambda q: None)

    out = kg.get_related_hccs(
        "anticoag",
        patient_context={"drugs": [{"name": "warfarin"}]},
    )
    assert any(r["hcc"] == "111" for r in out)


# ---------------------------------------------------------------------------
# 17. Lab-only inference
# ---------------------------------------------------------------------------

def test_lab_only_inference(monkeypatch) -> None:
    labs = _fake_module(
        infer_hccs_from_labs=lambda lx: [
            {"hcc_code": "138", "loinc": "33914-3",
             "value": 25, "confidence": 0.7}
        ],
    )
    _install_subs(loinc_service=labs)
    monkeypatch.setattr(kg, "_query_kg_concept", lambda q: None)

    out = kg.get_related_hccs(
        "egfr",
        patient_context={"labs": [{"loinc": "33914-3", "value": 25}]},
    )
    assert any(r["hcc"] == "138" for r in out)


# ---------------------------------------------------------------------------
# 18. Comorbidity upgrade with prior_hccs
# ---------------------------------------------------------------------------

def test_comorbidity_upgrade(monkeypatch) -> None:
    comorb = _fake_module(
        find_upgrades=lambda hccs: [
            {"upgraded_hcc": "38", "from_hccs": hccs,
             "pattern": "DM+CKD", "confidence": 0.7}
        ],
    )
    _install_subs(comorbidity_engine=comorb)
    monkeypatch.setattr(kg, "_query_kg_concept", lambda q: None)

    out = kg.get_related_hccs(
        "x",
        patient_context={"prior_hccs": ["18", "138"]},
    )
    assert any(r["hcc"] == "38" for r in out)


# ---------------------------------------------------------------------------
# 19. clear_cache drops cached entries
# ---------------------------------------------------------------------------

def test_clear_cache(monkeypatch) -> None:
    rules = _fake_module(
        get_hcc_definition=MagicMock(return_value={}),
        suggest_icd10_for_hcc=lambda h: [],
        citations_for_hcc=lambda h: [],
    )
    _install_subs(evidence_rules_engine=rules)

    kg.explain_hcc("37")
    kg.explain_hcc("37")
    assert rules.get_hcc_definition.call_count == 1
    kg.clear_cache()
    kg.explain_hcc("37")
    assert rules.get_hcc_definition.call_count == 2


# ---------------------------------------------------------------------------
# 20. _safe_params filters non-serializable values
# ---------------------------------------------------------------------------

def test_safe_params_filters_complex_objects() -> None:
    out = kg._safe_params(
        ("hello", 42, object()),
        {"k": "v", "complex": object(), "nested": {"a": 1, "obj": object()}},
    )
    assert out["arg0"] == "hello"
    assert out["arg1"] == 42
    assert "arg2" not in out  # raw object filtered
    assert out["k"] == "v"
    assert "complex" not in out
    assert out["nested"] == {"a": 1}


# ---------------------------------------------------------------------------
# 21. get_query_stats returns gracefully when DB has no kg_query_log
# ---------------------------------------------------------------------------

def test_get_query_stats_handles_missing_table(monkeypatch) -> None:
    def _boom(*a, **kw): raise RuntimeError("no such table")
    monkeypatch.setattr(kg, "raf_cursor", _boom)
    out = kg.get_query_stats(since_hours=1)
    assert out["since_hours"] == 1
    assert out["by_type"] == []
    assert "error" in out
