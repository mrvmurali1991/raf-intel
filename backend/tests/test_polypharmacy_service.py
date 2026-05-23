"""Unit tests for the polypharmacy + brand-to-generic KG layer.

These tests do not require a live database — they patch the
``_safe_fetch`` helpers in ``atc_service`` and ``brand_generic_service`` with
small in-memory fixtures that mimic ``kg_atc_classes``, ``kg_rxnorm_to_atc``
and ``kg_brand_to_generic``.
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from app.services.knowledge_graph import (
    atc_service,
    brand_generic_service,
    polypharmacy_service,
)


# ---------------------------------------------------------------------------
# Fixture data — covers every drug + ATC class referenced by the tests.
# ---------------------------------------------------------------------------

_ATC_CLASSES = [
    # CHF / cardiovascular
    {"id": 1,  "atc_code": "C03CA",   "name": "Loop diuretics",
     "level": 4, "parent_atc_code": "C03C", "concept_id": 100,
     "indication_concept_ids": None, "is_active": 1},
    {"id": 2,  "atc_code": "C03DA",   "name": "Aldosterone antagonists",
     "level": 4, "parent_atc_code": "C03D", "concept_id": 101,
     "indication_concept_ids": None, "is_active": 1},
    {"id": 3,  "atc_code": "C07AB",   "name": "Beta blocking agents, selective",
     "level": 4, "parent_atc_code": "C07A", "concept_id": 102,
     "indication_concept_ids": None, "is_active": 1},
    {"id": 4,  "atc_code": "C07AG",   "name": "Alpha and beta blocking agents",
     "level": 4, "parent_atc_code": "C07A", "concept_id": 103,
     "indication_concept_ids": None, "is_active": 1},
    {"id": 5,  "atc_code": "C09AA",   "name": "ACE inhibitors, plain",
     "level": 4, "parent_atc_code": "C09A", "concept_id": 104,
     "indication_concept_ids": None, "is_active": 1},
    {"id": 6,  "atc_code": "C09CA",   "name": "Angiotensin II receptor blockers",
     "level": 4, "parent_atc_code": "C09C", "concept_id": 105,
     "indication_concept_ids": None, "is_active": 1},
    {"id": 7,  "atc_code": "C10AA",   "name": "HMG CoA reductase inhibitors (statins)",
     "level": 4, "parent_atc_code": "C10A", "concept_id": 106,
     "indication_concept_ids": None, "is_active": 1},
    {"id": 8,  "atc_code": "B01AC",   "name": "Platelet aggregation inhibitors",
     "level": 4, "parent_atc_code": "B01A", "concept_id": 107,
     "indication_concept_ids": None, "is_active": 1},
    {"id": 9,  "atc_code": "B01AF",   "name": "Direct factor Xa inhibitors",
     "level": 4, "parent_atc_code": "B01A", "concept_id": 108,
     "indication_concept_ids": None, "is_active": 1},
    {"id": 10, "atc_code": "B01AA",   "name": "Vitamin K antagonists",
     "level": 4, "parent_atc_code": "B01A", "concept_id": 109,
     "indication_concept_ids": None, "is_active": 1},
    # Diabetes
    {"id": 11, "atc_code": "A10AE",   "name": "Long-acting insulins",
     "level": 4, "parent_atc_code": "A10A", "concept_id": 110,
     "indication_concept_ids": None, "is_active": 1},
    {"id": 12, "atc_code": "A10BJ",   "name": "GLP-1 analogues",
     "level": 4, "parent_atc_code": "A10B", "concept_id": 111,
     "indication_concept_ids": None, "is_active": 1},
    {"id": 13, "atc_code": "A10BK",   "name": "SGLT-2 inhibitors",
     "level": 4, "parent_atc_code": "A10B", "concept_id": 112,
     "indication_concept_ids": None, "is_active": 1},
    {"id": 14, "atc_code": "A10BA02", "name": "Metformin",
     "level": 5, "parent_atc_code": "A10BA", "concept_id": 113,
     "indication_concept_ids": None, "is_active": 1},
    {"id": 15, "atc_code": "A10BX",   "name": "Other blood glucose lowering drugs",
     "level": 4, "parent_atc_code": "A10B", "concept_id": 114,
     "indication_concept_ids": None, "is_active": 1},
    # Mental health
    {"id": 16, "atc_code": "N05AH",   "name": "Atypical antipsychotics (diazepines)",
     "level": 4, "parent_atc_code": "N05A", "concept_id": 115,
     "indication_concept_ids": None, "is_active": 1},
    {"id": 17, "atc_code": "N05AX",   "name": "Other antipsychotics",
     "level": 4, "parent_atc_code": "N05A", "concept_id": 116,
     "indication_concept_ids": None, "is_active": 1},
    {"id": 18, "atc_code": "N06DA",   "name": "Anticholinesterases",
     "level": 4, "parent_atc_code": "N06D", "concept_id": 117,
     "indication_concept_ids": None, "is_active": 1},
    {"id": 19, "atc_code": "N06DX",   "name": "Other anti-dementia drugs",
     "level": 4, "parent_atc_code": "N06D", "concept_id": 118,
     "indication_concept_ids": None, "is_active": 1},
    # HIV
    {"id": 20, "atc_code": "J05AR",   "name": "Antivirals for HIV, combinations",
     "level": 4, "parent_atc_code": "J05A", "concept_id": 119,
     "indication_concept_ids": None, "is_active": 1},
    {"id": 21, "atc_code": "J05AF",   "name": "NRTIs",
     "level": 4, "parent_atc_code": "J05A", "concept_id": 120,
     "indication_concept_ids": None, "is_active": 1},
    # Anemia / iron
    {"id": 22, "atc_code": "B03XA",   "name": "Erythropoiesis stimulating agents",
     "level": 4, "parent_atc_code": "B03X", "concept_id": 121,
     "indication_concept_ids": None, "is_active": 1},
    {"id": 23, "atc_code": "B03A",    "name": "Iron preparations",
     "level": 3, "parent_atc_code": "B03", "concept_id": 122,
     "indication_concept_ids": None, "is_active": 1},
    # Lithium (parent class N05AN)
    {"id": 24, "atc_code": "N05AN",   "name": "Lithium",
     "level": 4, "parent_atc_code": "N05A", "concept_id": 123,
     "indication_concept_ids": None, "is_active": 1},
]

_RXNORM_BRIDGE = [
    # CHF GDMT
    {"id": 1,  "rxcui": "4603",  "drug_name": "furosemide",     "ndc": None, "atc_code": "C03CA",   "is_brand": 0, "is_generic": 1},
    {"id": 2,  "rxcui": "9997005", "drug_name": "spironolactone", "ndc": None, "atc_code": "C03DA", "is_brand": 0, "is_generic": 1},
    {"id": 3,  "rxcui": "29046", "drug_name": "lisinopril",     "ndc": None, "atc_code": "C09AA",   "is_brand": 0, "is_generic": 1},
    {"id": 4,  "rxcui": "52175", "drug_name": "losartan",       "ndc": None, "atc_code": "C09CA",   "is_brand": 0, "is_generic": 1},
    {"id": 5,  "rxcui": "6918",  "drug_name": "metoprolol",     "ndc": None, "atc_code": "C07AB",   "is_brand": 0, "is_generic": 1},
    {"id": 6,  "rxcui": "20352", "drug_name": "carvedilol",     "ndc": None, "atc_code": "C07AG",   "is_brand": 0, "is_generic": 1},
    # CAD bundle
    {"id": 7,  "rxcui": "1191",  "drug_name": "aspirin",        "ndc": None, "atc_code": "B01AC",   "is_brand": 0, "is_generic": 1},
    {"id": 8,  "rxcui": "32968", "drug_name": "clopidogrel",    "ndc": None, "atc_code": "B01AC",   "is_brand": 0, "is_generic": 1},
    {"id": 9,  "rxcui": "83367", "drug_name": "atorvastatin",   "ndc": None, "atc_code": "C10AA",   "is_brand": 0, "is_generic": 1},
    # Anticoag
    {"id": 10, "rxcui": "1364430", "drug_name": "apixaban",     "ndc": None, "atc_code": "B01AF",   "is_brand": 0, "is_generic": 1},
    {"id": 11, "rxcui": "11289",   "drug_name": "warfarin",     "ndc": None, "atc_code": "B01AA",   "is_brand": 0, "is_generic": 1},
    # Diabetes
    {"id": 12, "rxcui": "1006406", "drug_name": "insulin glargine", "ndc": None, "atc_code": "A10AE", "is_brand": 0, "is_generic": 1},
    {"id": 13, "rxcui": "1991302", "drug_name": "semaglutide",  "ndc": None, "atc_code": "A10BJ",   "is_brand": 0, "is_generic": 1},
    {"id": 14, "rxcui": "1545653", "drug_name": "empagliflozin","ndc": None, "atc_code": "A10BK",   "is_brand": 0, "is_generic": 1},
    {"id": 15, "rxcui": "6809",    "drug_name": "metformin",    "ndc": None, "atc_code": "A10BA02", "is_brand": 0, "is_generic": 1},
    {"id": 16, "rxcui": "2601723", "drug_name": "tirzepatide",  "ndc": None, "atc_code": "A10BX",   "is_brand": 0, "is_generic": 1},
    # Mental health
    {"id": 17, "rxcui": "61381",  "drug_name": "olanzapine",    "ndc": None, "atc_code": "N05AH",   "is_brand": 0, "is_generic": 1},
    {"id": 18, "rxcui": "352393", "drug_name": "aripiprazole",  "ndc": None, "atc_code": "N05AX",   "is_brand": 0, "is_generic": 1},
    {"id": 19, "rxcui": "135447", "drug_name": "donepezil",     "ndc": None, "atc_code": "N06DA",   "is_brand": 0, "is_generic": 1},
    {"id": 20, "rxcui": "39998",  "drug_name": "memantine",     "ndc": None, "atc_code": "N06DX",   "is_brand": 0, "is_generic": 1},
    # HIV
    {"id": 21, "rxcui": "1747691", "drug_name": "bictegravir/emtricitabine/tenofovir", "ndc": None, "atc_code": "J05AR", "is_brand": 0, "is_generic": 1},
    {"id": 22, "rxcui": "352236",  "drug_name": "emtricitabine","ndc": None, "atc_code": "J05AF",   "is_brand": 0, "is_generic": 1},
    # Anemia
    {"id": 23, "rxcui": "105694", "drug_name": "epoetin alfa",  "ndc": None, "atc_code": "B03XA",   "is_brand": 0, "is_generic": 1},
    {"id": 24, "rxcui": "5489",   "drug_name": "ferrous sulfate","ndc": None, "atc_code": "B03A",    "is_brand": 0, "is_generic": 1},
]


_BRAND_GENERIC_ROWS = [
    {"id": 1,  "brand_name": "Ozempic",   "generic_name": "semaglutide",   "rxcui_brand": "1992368", "rxcui_generic": "1991302", "atc_code": "A10BJ",   "manufacturer": "Novo Nordisk", "notes": None, "is_active": 1},
    {"id": 2,  "brand_name": "Jardiance", "generic_name": "empagliflozin", "rxcui_brand": "1547004", "rxcui_generic": "1545653", "atc_code": "A10BK",   "manufacturer": "BI",          "notes": None, "is_active": 1},
    {"id": 3,  "brand_name": "Mounjaro",  "generic_name": "tirzepatide",   "rxcui_brand": "2601725", "rxcui_generic": "2601723", "atc_code": "A10BX",   "manufacturer": "Lilly",       "notes": None, "is_active": 1},
    {"id": 4,  "brand_name": "Eliquis",   "generic_name": "apixaban",      "rxcui_brand": "1364435", "rxcui_generic": "1364430", "atc_code": "B01AF",   "manufacturer": "BMS",         "notes": None, "is_active": 1},
    {"id": 5,  "brand_name": "Lipitor",   "generic_name": "atorvastatin",  "rxcui_brand": "153165",  "rxcui_generic": "83367",   "atc_code": "C10AA",   "manufacturer": "Pfizer",      "notes": None, "is_active": 1},
    {"id": 6,  "brand_name": "Lithobid",  "generic_name": "lithium",       "rxcui_brand": "858823",  "rxcui_generic": "6448",    "atc_code": "N05AN",   "manufacturer": "Noven",       "notes": None, "is_active": 1},
    {"id": 7,  "brand_name": "Wegovy",    "generic_name": "semaglutide",   "rxcui_brand": "2401358", "rxcui_generic": "1991302", "atc_code": "A10BJ",   "manufacturer": "Novo Nordisk", "notes": None, "is_active": 1},
]


# ---------------------------------------------------------------------------
# Fake-fetch interpreters
# ---------------------------------------------------------------------------

def _fake_atc_fetch(sql: str, params: tuple = ()) -> list[dict]:
    """Tiny SQL interpreter for atc_service._safe_fetch."""
    s = " ".join(sql.split()).lower()
    p = list(params or ())

    # Brand-bridge lookup (added in step 3b)
    if "from kg_brand_to_generic" in s and "lower(brand_name) = %s" in s and "is_active = 1" in s:
        target = p[0]
        return [
            {"generic_name": r["generic_name"], "atc_code": r["atc_code"]}
            for r in _BRAND_GENERIC_ROWS
            if r["brand_name"].lower() == target and r["is_active"]
        ]

    # NDC lookup
    if "from kg_rxnorm_to_atc" in s and "ndc" in s and "replace" in s:
        return []  # we don't fixture NDCs in this suite
    if "from kg_rxnorm_to_atc" in s and "rxcui = %s" in s and "ndc" not in s:
        return [r for r in _RXNORM_BRIDGE if r.get("rxcui") == p[0]]
    if "from kg_rxnorm_to_atc" in s and "lower(drug_name) = %s" in s:
        return [r for r in _RXNORM_BRIDGE if r["drug_name"].lower() == p[0]]
    if "select distinct drug_name from kg_rxnorm_to_atc" in s:
        seen, out = set(), []
        for r in _RXNORM_BRIDGE:
            if r["drug_name"] not in seen:
                seen.add(r["drug_name"])
                out.append({"drug_name": r["drug_name"]})
        return out
    if "from kg_rxnorm_to_atc" in s and "drug_name in" in s:
        return [r for r in _RXNORM_BRIDGE if r["drug_name"] in set(p)]
    if "from kg_atc_classes" in s and "atc_code in" in s:
        return [c for c in _ATC_CLASSES if c["atc_code"] in set(p)]
    if "from kg_atc_classes" in s and "where atc_code = %s" in s:
        return [c for c in _ATC_CLASSES if c["atc_code"] == p[0]]
    if "from kg_atc_classes" in s and "is_active = 1" in s:
        return [{"atc_code": c["atc_code"], "name": c["name"]}
                for c in _ATC_CLASSES if c["is_active"]]
    return []


def _fake_brand_fetch(sql: str, params: tuple = ()) -> list[dict]:
    """Tiny SQL interpreter for brand_generic_service._safe_fetch."""
    s = " ".join(sql.split()).lower()
    p = list(params or ())

    if "from kg_brand_to_generic" in s and "lower(brand_name) = %s" in s:
        return [r for r in _BRAND_GENERIC_ROWS
                if r["brand_name"].lower() == p[0] and r["is_active"]]
    if "from kg_brand_to_generic" in s and "lower(generic_name) = %s" in s:
        return [r for r in _BRAND_GENERIC_ROWS
                if r["generic_name"].lower() == p[0] and r["is_active"]]
    if "select distinct brand_name from kg_brand_to_generic" in s:
        seen, out = set(), []
        for r in _BRAND_GENERIC_ROWS:
            if r["is_active"] and r["brand_name"] not in seen:
                seen.add(r["brand_name"])
                out.append({"brand_name": r["brand_name"]})
        return out
    if "from kg_brand_to_generic" in s and "brand_name = %s" in s:
        return [r for r in _BRAND_GENERIC_ROWS
                if r["brand_name"] == p[0] and r["is_active"]]
    return []


@pytest.fixture(autouse=True)
def _patch_fetches():
    with (
        patch.object(atc_service, "_safe_fetch", side_effect=_fake_atc_fetch),
        patch.object(brand_generic_service, "_safe_fetch", side_effect=_fake_brand_fetch),
    ):
        yield


# ---------------------------------------------------------------------------
# Brand-to-generic exact + fuzzy + reverse + bulk
# ---------------------------------------------------------------------------

def test_brand_to_generic_exact_ozempic() -> None:
    hit = brand_generic_service.brand_to_generic("Ozempic")
    assert hit is not None
    assert hit["generic_name"] == "semaglutide"
    assert hit["atc_code"] == "A10BJ"
    assert hit["match_type"] == "exact"
    assert hit["confidence"] == 1.0


def test_brand_to_generic_case_insensitive() -> None:
    hit = brand_generic_service.brand_to_generic("eliquis")
    assert hit is not None
    assert hit["generic_name"] == "apixaban"


def test_brand_to_generic_with_dose_form_strips_to_head_token() -> None:
    hit = brand_generic_service.brand_to_generic("Ozempic 0.5 mg")
    assert hit is not None
    assert hit["generic_name"] == "semaglutide"
    assert hit["match_type"] in {"exact_head_token", "fuzzy"}


def test_brand_to_generic_fuzzy_typo() -> None:
    hit = brand_generic_service.brand_to_generic("Ozempick")  # common typo
    assert hit is not None
    assert hit["generic_name"] == "semaglutide"
    assert hit["match_type"] == "fuzzy"
    assert 0.85 <= hit["confidence"] < 1.0


def test_brand_to_generic_unknown_returns_none() -> None:
    assert brand_generic_service.brand_to_generic("Florbazonalin") is None


def test_brand_to_generic_empty_input() -> None:
    assert brand_generic_service.brand_to_generic("") is None
    assert brand_generic_service.brand_to_generic("   ") is None


def test_generic_to_brands_returns_all_variants() -> None:
    brands = brand_generic_service.generic_to_brands("semaglutide")
    names = sorted(b["brand_name"] for b in brands)
    assert names == ["Ozempic", "Wegovy"]


def test_bulk_resolve_mixed_brand_generic_unknown() -> None:
    out = brand_generic_service.bulk_resolve(
        ["Ozempic", "metformin", "Florbazonalin", ""],
    )
    assert len(out) == 4
    by_input = {r["input"]: r for r in out if r["input"]}
    assert by_input["Ozempic"]["input_kind"] == "brand"
    assert by_input["Ozempic"]["resolved_generic"] == "semaglutide"
    # ``metformin`` is a generic with no brand row -> input_kind=unknown.
    # That is acceptable behaviour for a pure brand-bridge lookup.
    assert by_input["metformin"]["input_kind"] in {"generic", "unknown"}
    assert by_input["Florbazonalin"]["input_kind"] == "unknown"


# ---------------------------------------------------------------------------
# ATC integration: brand bridge resolves Ozempic
# ---------------------------------------------------------------------------

def test_atc_resolve_via_brand_bridge_ozempic() -> None:
    matches = atc_service.resolve_drug_to_atc("Ozempic")
    assert matches, "Ozempic should resolve via brand bridge"
    # Bridge -> semaglutide row -> A10BJ
    assert any(m["atc_code"] == "A10BJ" for m in matches)


def test_atc_unseen_drug_stem_still_works_after_brand_path() -> None:
    # tirzepatide is in the bridge — exact path.  Stem inference for an
    # unseen drug like "albiglutide" should still hit A10BJ via stem suffix.
    chain = atc_service.unseen_drug_inference("albiglutide")
    assert chain["atc_code"] == "A10BJ"
    assert chain["inference_path"].startswith("stem:")


# ---------------------------------------------------------------------------
# Polypharmacy patterns: 8+ happy-path triggers
# ---------------------------------------------------------------------------

def _ids_of(triggered):
    return {t["pattern_id"] for t in triggered}


def test_chf_gdmt_triggers_with_three_drugs() -> None:
    triggered = polypharmacy_service.evaluate_drug_combination(
        ["furosemide", "lisinopril", "metoprolol"],
    )
    ids = _ids_of(triggered)
    assert "chf_gdmt" in ids
    chf = next(t for t in triggered if t["pattern_id"] == "chf_gdmt")
    assert chf["primary_hcc"] == "226"
    assert "C03CA" in chf["matched_atc_codes"]


def test_chf_gdmt_with_mineralocorticoid_boost() -> None:
    triggered = polypharmacy_service.evaluate_drug_combination(
        ["furosemide", "lisinopril", "metoprolol", "spironolactone"],
    )
    chf = next(t for t in triggered if t["pattern_id"] == "chf_gdmt")
    assert chf["boost_atc_codes"] == ["C03DA"]
    # Boost lifts confidence above the base 0.78.
    assert chf["confidence"] > 0.78


def test_chf_gdmt_promotes_to_hfref_when_ef_low() -> None:
    triggered = polypharmacy_service.evaluate_drug_combination(
        ["furosemide", "lisinopril", "metoprolol"],
        patient_context={"ejection_fraction": 32},
    )
    chf = next(t for t in triggered if t["pattern_id"] == "chf_gdmt")
    assert chf["primary_hcc"] == "224"


def test_chf_gdmt_negative_missing_beta_blocker() -> None:
    triggered = polypharmacy_service.evaluate_drug_combination(
        ["furosemide", "lisinopril"],
    )
    assert "chf_gdmt" not in _ids_of(triggered)


def test_dm_multi_modal_triggers_insulin_plus_glp1() -> None:
    triggered = polypharmacy_service.evaluate_drug_combination(
        ["insulin glargine", "semaglutide"],
    )
    ids = _ids_of(triggered)
    assert "dm_multi_modal" in ids


def test_dm_multi_modal_negative_only_metformin() -> None:
    triggered = polypharmacy_service.evaluate_drug_combination(["metformin"])
    assert "dm_multi_modal" not in _ids_of(triggered)


def test_cad_post_mi_triggers_with_full_quad() -> None:
    triggered = polypharmacy_service.evaluate_drug_combination(
        ["aspirin", "atorvastatin", "metoprolol", "lisinopril"],
    )
    assert "cad_post_mi" in _ids_of(triggered)


def test_cad_post_mi_negative_no_antiplatelet() -> None:
    triggered = polypharmacy_service.evaluate_drug_combination(
        ["atorvastatin", "metoprolol", "lisinopril"],
    )
    assert "cad_post_mi" not in _ids_of(triggered)


def test_dementia_behavioral_triggers() -> None:
    triggered = polypharmacy_service.evaluate_drug_combination(
        ["donepezil", "olanzapine"],
    )
    assert "dementia_behavioral" in _ids_of(triggered)


def test_dementia_behavioral_negative_no_antipsychotic() -> None:
    triggered = polypharmacy_service.evaluate_drug_combination(["donepezil"])
    assert "dementia_behavioral" not in _ids_of(triggered)


def test_hiv_active_triggers_on_combination_tablet() -> None:
    triggered = polypharmacy_service.evaluate_drug_combination(
        ["bictegravir/emtricitabine/tenofovir"],
    )
    ids = _ids_of(triggered)
    assert "hiv_active_art" in ids
    hit = next(t for t in triggered if t["pattern_id"] == "hiv_active_art")
    assert hit["primary_hcc"] == "1"


def test_hiv_active_negative_just_emtricitabine_alone_still_implies_hiv() -> None:
    # NRTI alone is enough — pattern requires only one of [J05AR, J05AF].
    triggered = polypharmacy_service.evaluate_drug_combination(["emtricitabine"])
    assert "hiv_active_art" in _ids_of(triggered)


def test_bipolar_lithium_plus_atypical_triggers_via_brand() -> None:
    # Lithobid is brand-bridged to lithium (ingredient name match).
    triggered = polypharmacy_service.evaluate_drug_combination(
        ["Lithobid", "olanzapine"],
    )
    assert "bipolar_active" in _ids_of(triggered)


def test_bipolar_negative_lithium_alone() -> None:
    triggered = polypharmacy_service.evaluate_drug_combination(["Lithobid"])
    assert "bipolar_active" not in _ids_of(triggered)


def test_ckd_anemia_triggers_on_esa_plus_iron() -> None:
    triggered = polypharmacy_service.evaluate_drug_combination(
        ["epoetin alfa", "ferrous sulfate"],
    )
    ids = _ids_of(triggered)
    assert "ckd_anemia" in ids
    hit = next(t for t in triggered if t["pattern_id"] == "ckd_anemia")
    assert hit["primary_hcc"] == "138"


def test_ckd_anemia_negative_iron_alone() -> None:
    triggered = polypharmacy_service.evaluate_drug_combination(["ferrous sulfate"])
    assert "ckd_anemia" not in _ids_of(triggered)


def test_afib_anticoag_plus_rate_control() -> None:
    triggered = polypharmacy_service.evaluate_drug_combination(
        ["apixaban", "metoprolol"],
    )
    assert "afib_anticoag_rate_control" in _ids_of(triggered)


def test_afib_negative_anticoag_only() -> None:
    triggered = polypharmacy_service.evaluate_drug_combination(["apixaban"])
    assert "afib_anticoag_rate_control" not in _ids_of(triggered)


def test_afib_warfarin_plus_carvedilol() -> None:
    triggered = polypharmacy_service.evaluate_drug_combination(
        ["warfarin", "carvedilol"],
    )
    assert "afib_anticoag_rate_control" in _ids_of(triggered)


# ---------------------------------------------------------------------------
# Pattern catalogue
# ---------------------------------------------------------------------------

def test_list_patterns_returns_all_curated() -> None:
    patterns = polypharmacy_service.list_patterns()
    # 8+ patterns required; current curation has 10.
    assert len(patterns) >= 8
    ids = {p["id"] for p in patterns}
    assert {
        "chf_gdmt", "dm_multi_modal", "cad_post_mi",
        "dementia_behavioral", "hiv_active_art", "bipolar_active",
        "ckd_anemia", "afib_anticoag_rate_control",
    }.issubset(ids)
    for p in patterns:
        assert p["citation"], f"pattern {p['id']} missing citation"


def test_evaluate_returns_empty_for_empty_drug_list() -> None:
    assert polypharmacy_service.evaluate_drug_combination([]) == []


def test_evaluate_returns_reasoning_chain_for_each_trigger() -> None:
    triggered = polypharmacy_service.evaluate_drug_combination(
        ["furosemide", "lisinopril", "metoprolol"],
    )
    for t in triggered:
        assert t["reasoning"]
        assert t["citation"]
        assert isinstance(t["matched_drugs"], list) and t["matched_drugs"]


def test_evaluate_orders_by_confidence_descending() -> None:
    # Combination triggers multiple patterns — verify ordering.
    triggered = polypharmacy_service.evaluate_drug_combination(
        ["furosemide", "lisinopril", "metoprolol", "spironolactone",
         "aspirin", "atorvastatin",  # adds CAD
         "apixaban",                   # adds AFib
         ],
    )
    confidences = [t["confidence"] for t in triggered]
    assert confidences == sorted(confidences, reverse=True)
    assert len(triggered) >= 2
