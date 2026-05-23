"""Unit tests for ``app.services.knowledge_graph.atc_service``.

These tests do not require a live database — they patch the internal
``_safe_fetch`` helper with a small in-memory fixture that mimics the
``kg_atc_classes``, ``kg_rxnorm_to_atc``, ``knowledge_graph_concepts`` and
``knowledge_graph_edges`` tables.
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from app.services.knowledge_graph import atc_service


# ---------------------------------------------------------------------------
# In-memory fixture (mirrors what the seed script populates).
# ---------------------------------------------------------------------------

_ATC_CLASSES = [
    {"id": 1,  "atc_code": "A",        "name": "Alimentary tract and metabolism",
     "level": 1, "parent_atc_code": None,    "concept_id": 100,
     "indication_concept_ids": None, "is_active": 1},
    {"id": 2,  "atc_code": "A10",      "name": "Drugs used in diabetes",
     "level": 2, "parent_atc_code": "A",     "concept_id": 101,
     "indication_concept_ids": json.dumps([200]), "is_active": 1},
    {"id": 3,  "atc_code": "A10B",     "name": "Blood glucose lowering drugs, excl. insulins",
     "level": 3, "parent_atc_code": "A10",   "concept_id": 102,
     "indication_concept_ids": json.dumps([200]), "is_active": 1},
    {"id": 4,  "atc_code": "A10BA",    "name": "Biguanides",
     "level": 4, "parent_atc_code": "A10B",  "concept_id": 103,
     "indication_concept_ids": json.dumps([200]), "is_active": 1},
    {"id": 5,  "atc_code": "A10BA02",  "name": "Metformin",
     "level": 5, "parent_atc_code": "A10BA", "concept_id": 104,
     "indication_concept_ids": None, "is_active": 1},
    {"id": 6,  "atc_code": "A10BJ",    "name": "Glucagon-like peptide-1 (GLP-1) analogues",
     "level": 4, "parent_atc_code": "A10B",  "concept_id": 105,
     "indication_concept_ids": json.dumps([200]), "is_active": 1},
    {"id": 7,  "atc_code": "C09AA",    "name": "ACE inhibitors, plain (substances)",
     "level": 4, "parent_atc_code": "C09A", "concept_id": 106,
     "indication_concept_ids": json.dumps([201, 202]), "is_active": 1},
    {"id": 8,  "atc_code": "C09A",     "name": "ACE inhibitors, plain",
     "level": 3, "parent_atc_code": "C09",  "concept_id": 107,
     "indication_concept_ids": None, "is_active": 1},
    {"id": 9,  "atc_code": "C09",      "name": "Agents acting on the renin-angiotensin system",
     "level": 2, "parent_atc_code": "C",    "concept_id": 108,
     "indication_concept_ids": None, "is_active": 1},
    {"id": 10, "atc_code": "C",        "name": "Cardiovascular system",
     "level": 1, "parent_atc_code": None,   "concept_id": 109,
     "indication_concept_ids": None, "is_active": 1},
]

_RXNORM_BRIDGE = [
    {"id": 1, "rxcui": "6809",    "drug_name": "metformin",   "ndc": None, "atc_code": "A10BA02",
     "is_brand": 0, "is_generic": 1},
    {"id": 2, "rxcui": "1991302", "drug_name": "semaglutide", "ndc": None, "atc_code": "A10BJ",
     "is_brand": 0, "is_generic": 1},
    {"id": 3, "rxcui": "1992368", "drug_name": "ozempic",     "ndc": None, "atc_code": "A10BJ",
     "is_brand": 1, "is_generic": 0},
    {"id": 4, "rxcui": "29046",   "drug_name": "lisinopril",  "ndc": "00071022223",
     "atc_code": "C09AA", "is_brand": 0, "is_generic": 1},
]

_CONCEPTS = {
    100: {"id": 100, "ontology": "atc",   "code": "A",       "display_name": "ATC: A"},
    104: {"id": 104, "ontology": "atc",   "code": "A10BA02", "display_name": "Metformin"},
    200: {"id": 200, "ontology": "icd10", "code": "E11",     "display_name": "Type 2 diabetes mellitus"},
    201: {"id": 201, "ontology": "icd10", "code": "I10",     "display_name": "Essential hypertension"},
    202: {"id": 202, "ontology": "icd10", "code": "I50",     "display_name": "Congestive heart failure"},
    300: {"id": 300, "ontology": "hcc",   "code": "18",      "display_name": "Diabetes with chronic complications"},
    301: {"id": 301, "ontology": "hcc",   "code": "19",      "display_name": "Diabetes without complication"},
    302: {"id": 302, "ontology": "hcc",   "code": "85",      "display_name": "Congestive heart failure"},
}

_EDGES = [
    # ATC -> indication
    {"source_concept_id": 102, "target_concept_id": 200, "relation": "has_indication"},
    {"source_concept_id": 105, "target_concept_id": 200, "relation": "has_indication"},
    {"source_concept_id": 106, "target_concept_id": 201, "relation": "has_indication"},
    {"source_concept_id": 106, "target_concept_id": 202, "relation": "has_indication"},
    # indication -> HCC
    {"source_concept_id": 200, "target_concept_id": 300, "relation": "maps_to_hcc"},
    {"source_concept_id": 200, "target_concept_id": 301, "relation": "maps_to_hcc"},
    {"source_concept_id": 202, "target_concept_id": 302, "relation": "maps_to_hcc"},
]


def _fake_fetch(sql: str, params: tuple = ()) -> list[dict]:
    """Tiny SQL interpreter — handles every shape the service issues."""
    s = " ".join(sql.split()).lower()
    p = list(params or ())

    # NDC + REPLACE lookup
    if "from kg_rxnorm_to_atc" in s and "ndc" in s and "replace" in s:
        ndc, ndc_clean = p[0], p[1]
        return [r for r in _RXNORM_BRIDGE
                if r.get("ndc") == ndc
                or (r.get("ndc") and r["ndc"].replace("-", "") == ndc_clean)]
    # RxCUI lookup
    if "from kg_rxnorm_to_atc" in s and "rxcui = %s" in s and "ndc" not in s:
        return [r for r in _RXNORM_BRIDGE if r.get("rxcui") == p[0]]
    # Drug-name exact
    if "from kg_rxnorm_to_atc" in s and "lower(drug_name) = %s" in s:
        return [r for r in _RXNORM_BRIDGE if r["drug_name"].lower() == p[0]]
    # Distinct drug names
    if "select distinct drug_name from kg_rxnorm_to_atc" in s:
        seen = set()
        out = []
        for r in _RXNORM_BRIDGE:
            if r["drug_name"] not in seen:
                seen.add(r["drug_name"])
                out.append({"drug_name": r["drug_name"]})
        return out
    # Drug-name IN (...)
    if "from kg_rxnorm_to_atc" in s and "drug_name in" in s:
        return [r for r in _RXNORM_BRIDGE if r["drug_name"] in set(p)]
    # ATC class IN (...) — only used by resolve_drug_to_atc to enrich
    if "from kg_atc_classes" in s and "atc_code in" in s:
        return [c for c in _ATC_CLASSES if c["atc_code"] in set(p)]
    # ATC class single
    if "from kg_atc_classes" in s and "where atc_code = %s" in s:
        return [c for c in _ATC_CLASSES if c["atc_code"] == p[0]]
    # ATC class active list
    if "from kg_atc_classes" in s and "is_active = 1" in s:
        return [{"atc_code": c["atc_code"], "name": c["name"]}
                for c in _ATC_CLASSES if c["is_active"]]
    # drugs in class with join
    if "from kg_rxnorm_to_atc b" in s:
        if "or b.atc_code like" in s:
            code, prefix = p[0], p[1]
            base_prefix = prefix.rstrip("%")
            out = []
            for r in _RXNORM_BRIDGE:
                if r["atc_code"] == code or r["atc_code"].startswith(base_prefix):
                    cls = next((c for c in _ATC_CLASSES if c["atc_code"] == r["atc_code"]), {})
                    out.append({**r, "atc_name": cls.get("name"), "atc_level": cls.get("level")})
            return sorted(out, key=lambda x: x["drug_name"])
        else:
            code = p[0]
            out = []
            for r in _RXNORM_BRIDGE:
                if r["atc_code"] == code:
                    cls = next((c for c in _ATC_CLASSES if c["atc_code"] == r["atc_code"]), {})
                    out.append({**r, "atc_name": cls.get("name"), "atc_level": cls.get("level")})
            return sorted(out, key=lambda x: x["drug_name"])
    # Edges: has_indication from a single source concept_id
    if "from knowledge_graph_edges" in s and "source_concept_id = %s" in s:
        return [
            {"target_concept_id": e["target_concept_id"]}
            for e in _EDGES
            if e["source_concept_id"] == p[0] and e["relation"] == "has_indication"
        ]
    # Edges: maps_to_hcc from indication ids IN (...)
    if "from knowledge_graph_edges" in s and "source_concept_id in" in s:
        return [
            {"target_concept_id": e["target_concept_id"]}
            for e in _EDGES
            if e["source_concept_id"] in set(p) and e["relation"] == "maps_to_hcc"
        ]
    # Concepts WHERE id IN (...)
    if "from knowledge_graph_concepts" in s and "id in" in s:
        if "ontology = 'hcc'" in s:
            return [c for cid, c in _CONCEPTS.items()
                    if cid in set(p) and c["ontology"] == "hcc"]
        return [c for cid, c in _CONCEPTS.items() if cid in set(p)]
    return []


@pytest.fixture(autouse=True)
def _patch_fetch():
    with patch.object(atc_service, "_safe_fetch", side_effect=_fake_fetch):
        yield


# ---------------------------------------------------------------------------
# resolve_drug_to_atc
# ---------------------------------------------------------------------------

def test_resolve_known_drug_exact_name() -> None:
    matches = atc_service.resolve_drug_to_atc("metformin")
    assert len(matches) == 1
    assert matches[0]["atc_code"] == "A10BA02"
    assert matches[0]["is_generic"] is True
    assert matches[0]["atc_class"]["name"] == "Metformin"


def test_resolve_known_drug_case_insensitive() -> None:
    matches = atc_service.resolve_drug_to_atc("Metformin")
    assert len(matches) == 1
    assert matches[0]["drug_name"] == "metformin"


def test_resolve_by_rxcui() -> None:
    matches = atc_service.resolve_drug_to_atc("6809")
    assert matches and matches[0]["drug_name"] == "metformin"


def test_resolve_by_ndc() -> None:
    matches = atc_service.resolve_drug_to_atc("00071022223")
    assert matches and matches[0]["atc_code"] == "C09AA"


def test_resolve_unknown_drug_returns_empty() -> None:
    assert atc_service.resolve_drug_to_atc("definitely-not-a-real-drug") == []


def test_resolve_empty_input() -> None:
    assert atc_service.resolve_drug_to_atc("") == []
    assert atc_service.resolve_drug_to_atc("   ") == []


# ---------------------------------------------------------------------------
# get_atc_hierarchy
# ---------------------------------------------------------------------------

def test_hierarchy_metformin_full_chain() -> None:
    chain = atc_service.get_atc_hierarchy("A10BA02")
    codes = [n["atc_code"] for n in chain]
    assert codes == ["A", "A10", "A10B", "A10BA", "A10BA02"]
    assert chain[0]["level"] == 1
    assert chain[-1]["level"] == 5


def test_hierarchy_unknown_code_returns_empty() -> None:
    assert atc_service.get_atc_hierarchy("Z99ZZ99") == []


def test_hierarchy_handles_orphan_root() -> None:
    chain = atc_service.get_atc_hierarchy("A")
    assert len(chain) == 1
    assert chain[0]["parent_atc_code"] is None


# ---------------------------------------------------------------------------
# get_drugs_in_class
# ---------------------------------------------------------------------------

def test_get_drugs_in_class_with_subclasses() -> None:
    drugs = atc_service.get_drugs_in_class("A10B", include_subclasses=True)
    names = sorted(d["drug_name"] for d in drugs)
    assert "metformin" in names
    assert "semaglutide" in names
    assert "ozempic" in names


def test_get_drugs_in_class_strict() -> None:
    # No drugs are mapped directly to A10B (only to A10BA02 / A10BJ).
    drugs = atc_service.get_drugs_in_class("A10B", include_subclasses=False)
    assert drugs == []


def test_get_drugs_in_leaf_class() -> None:
    drugs = atc_service.get_drugs_in_class("A10BA02", include_subclasses=False)
    assert len(drugs) == 1
    assert drugs[0]["drug_name"] == "metformin"


# ---------------------------------------------------------------------------
# get_indications_for_atc
# ---------------------------------------------------------------------------

def test_indications_at_class_level() -> None:
    inds = atc_service.get_indications_for_atc("A10BJ")
    codes = [c["code"] for c in inds]
    assert "E11" in codes


def test_indications_walk_up_for_leaf() -> None:
    # Metformin (level-5) has no indications; should bubble up to A10BA.
    inds = atc_service.get_indications_for_atc("A10BA02")
    codes = [c["code"] for c in inds]
    assert "E11" in codes


def test_indications_acei_two_concepts() -> None:
    inds = atc_service.get_indications_for_atc("C09AA")
    codes = sorted(c["code"] for c in inds)
    assert codes == ["I10", "I50"]


# ---------------------------------------------------------------------------
# drug_to_hcc_chain
# ---------------------------------------------------------------------------

def test_metformin_full_hcc_chain() -> None:
    chain = atc_service.drug_to_hcc_chain("metformin")
    assert chain["atc_code"] == "A10BA02"
    assert chain["matched_drug"] == "metformin"
    # Hierarchy reaches the top.
    assert chain["hierarchy"][0]["atc_code"] == "A"
    assert chain["hierarchy"][-1]["atc_code"] == "A10BA02"
    # Indications resolve via parent walk.
    indication_codes = {c["code"] for c in chain["indications"]}
    assert "E11" in indication_codes
    # HCCs come from the indication->HCC edges.
    hcc_codes = sorted(h["code"] for h in chain["hccs"])
    assert hcc_codes == ["18", "19"]


def test_brand_drug_resolves_to_class() -> None:
    chain = atc_service.drug_to_hcc_chain("ozempic")
    assert chain["atc_code"] == "A10BJ"
    assert any(h["code"] in ("18", "19") for h in chain["hccs"])


def test_unknown_drug_empty_chain() -> None:
    chain = atc_service.drug_to_hcc_chain("flarbazon")
    assert chain["atc_code"] is None
    assert chain["hccs"] == []


# ---------------------------------------------------------------------------
# unseen_drug_inference
# ---------------------------------------------------------------------------

def test_unseen_drug_stem_glutide() -> None:
    # albiglutide is not in our bridge; stem "-glutide" -> A10BJ (GLP-1).
    chain = atc_service.unseen_drug_inference("albiglutide")
    assert chain["inferred"] is True
    assert chain["atc_code"] == "A10BJ"
    assert chain["inference_path"].startswith("stem:")
    assert any(h["code"] in ("18", "19") for h in chain["hccs"])


def test_unseen_drug_stem_gliflozin() -> None:
    # ertugliflozin not in our bridge; stem "-gliflozin" -> A10BK (SGLT-2).
    chain = atc_service.unseen_drug_inference("ertugliflozin")
    # We didn't fixture A10BK, so the chain will return atc_code=A10BK with
    # empty hierarchy / indications.  That is still useful information.
    assert chain["inferred"] is True
    assert chain["atc_code"] == "A10BK"


def test_unseen_drug_stem_pril() -> None:
    chain = atc_service.unseen_drug_inference("benazepril")
    assert chain["inferred"] is True
    assert chain["atc_code"] == "C09AA"


def test_unseen_drug_exact_match_marked_not_inferred() -> None:
    chain = atc_service.unseen_drug_inference("metformin")
    assert chain["inferred"] is False
    assert chain["inference_path"] == "exact_bridge"


def test_unseen_drug_no_match() -> None:
    chain = atc_service.unseen_drug_inference("xyzzy123")
    assert chain["atc_code"] is None
    assert chain["inferred"] is False


# ---------------------------------------------------------------------------
# Integration: suspect_engine fallback uses ATC service
# ---------------------------------------------------------------------------

def test_suspect_engine_atc_fallback_calls_unseen_inference() -> None:
    """The new helper in suspect_engine should fall back to ATC inference
    when no medication signal matches.
    """
    from app.services import suspect_engine

    suspects = suspect_engine._atc_inferred_suspects(
        patient_id=42,
        med={"drug": "albiglutide", "rxnorm_drugcode": None,
             "start_date": "2026-01-01", "id": 7},
        year=2026,
        coded_icds=set(),
        coded_hccs=set(),
    )
    # Should infer A10BJ via stem and emit at least one suspect tied to a
    # diabetes HCC (18 or 19).
    assert suspects, "expected at least one ATC-inferred suspect"
    hccs = {s["suspected_hcc"] for s in suspects}
    assert hccs & {"18", "19"}
    for s in suspects:
        assert s["source"] == "medication_atc"
        assert s["evidence"]["atc_code"] == "A10BJ"
        assert s["evidence"]["atc_inferred"] is True
        # Confidence stays below typical hand-tuned rule weights (>=0.6).
        assert 0.0 < s["confidence"] < 0.6


def test_suspect_engine_atc_fallback_skips_already_coded_hccs() -> None:
    from app.services import suspect_engine
    suspects = suspect_engine._atc_inferred_suspects(
        patient_id=42,
        med={"drug": "albiglutide", "rxnorm_drugcode": None,
             "start_date": "2026-01-01", "id": 7},
        year=2026,
        coded_icds=set(),
        coded_hccs={"18", "19"},     # both diabetes HCCs already coded
    )
    assert suspects == []
