"""
Polypharmacy pattern recognition.

Curated combinations of drug classes (encoded by ATC prefixes) that imply a
specific clinical condition with high confidence.  E.g. a patient on a loop
diuretic + ACE inhibitor + beta-blocker is on guideline-directed medical
therapy (GDMT) for congestive heart failure regardless of whether the chart
already lists I50 — the prescription bundle alone is sufficient evidence
to flag an HCC 226 (HFrEF) suspect.

Each pattern cites a clinical guideline / payer source so downstream MEAT
audit + chart-chase flows can render the evidence chain.

Public API
----------
- :data:`POLYPHARMACY_PATTERNS` — the curated rule list.
- :func:`evaluate_drug_combination` — match a patient's med list to all
  patterns, returning triggered signals with reasoning.
- :func:`list_patterns` — pattern catalogue (for the UI / API).
"""
from __future__ import annotations

import logging
from typing import Any

from app.services.knowledge_graph import atc_service, brand_generic_service

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pattern definitions
# ---------------------------------------------------------------------------
#
# A pattern fires when EVERY ``required_classes`` group has at least one
# matching ATC prefix in the patient's med list.  Optional ``boost_classes``
# raise the confidence when present but are not required.  ``output_hccs``
# are the V28 HCCs implied; the first entry is the primary, additional
# entries are alternates / co-occurring.
#
# Each pattern carries a ``citation`` string referencing the guideline or
# CMS document that justifies the inference.

POLYPHARMACY_PATTERNS: list[dict[str, Any]] = [
    {
        "id": "chf_gdmt",
        "name": "CHF guideline-directed medical therapy",
        "description": (
            "Loop diuretic + ACE/ARB/ARNI + beta-blocker is the cornerstone "
            "of GDMT for HFrEF.  Adding a mineralocorticoid antagonist "
            "upgrades the HCC to severe systolic dysfunction (HCC 224)."
        ),
        "required_classes": [
            ["C03CA"],                          # loop diuretic
            ["C09AA", "C09CA", "C09DX"],        # ACE / ARB / ARNI
            ["C07AB", "C07AG"],                 # beta-blocker (selective or alpha+beta)
        ],
        "boost_classes": [
            ["C03DA"],                          # mineralocorticoid antagonist
            ["A10BK"],                          # SGLT2i (Dapagliflozin / Empagliflozin)
        ],
        "output_hccs": ["226", "224"],
        "base_confidence": 0.78,
        "boost_confidence": 0.10,
        "citation": "AHA/ACC/HFSA 2022 HF Guideline (Heidenreich et al., Circulation 2022;145:e895-e1032)",
    },
    {
        "id": "dm_multi_modal",
        "name": "Multi-modal diabetes therapy",
        "description": (
            "Patient on insulin plus a GLP-1 / SGLT2i / DPP-4 / metformin "
            "combination is by definition diabetic with chronic complications "
            "(HCC 18).  Adding insulin to non-insulin agents is the inflection "
            "point that distinguishes 18 from uncomplicated 19."
        ),
        "required_classes": [
            ["A10A", "A10AB", "A10AE"],         # insulin family
            ["A10BJ", "A10BK", "A10BH", "A10BA02", "A10BA"],  # second agent class
        ],
        "boost_classes": [
            ["A10BX"],                          # tirzepatide / pioglitazone
        ],
        "output_hccs": ["18", "17"],
        "base_confidence": 0.80,
        "boost_confidence": 0.05,
        "citation": "ADA Standards of Care in Diabetes-2024 (Diabetes Care 2024;47(Suppl 1)).",
    },
    {
        "id": "cad_post_mi",
        "name": "Post-MI / secondary CAD prevention bundle",
        "description": (
            "Antiplatelet + statin + beta-blocker + ACE/ARB is the standard "
            "post-MI secondary prevention quadruple — strongly implies "
            "established CAD (HCC 217)."
        ),
        "required_classes": [
            ["B01AC"],                          # antiplatelet
            ["C10AA"],                          # statin
            ["C07AB", "C07AG"],                 # beta-blocker
            ["C09AA", "C09CA"],                 # ACE / ARB
        ],
        "output_hccs": ["217", "224"],
        "base_confidence": 0.82,
        "citation": "2023 ACC/AHA Guideline for the Management of Patients With Chronic Coronary Disease (Circulation 2023;148:e9-e119).",
    },
    {
        "id": "dementia_behavioral",
        "name": "Dementia with behavioral disturbance",
        "description": (
            "Cholinesterase inhibitor (or memantine) + atypical antipsychotic "
            "implies advanced dementia with behavioral / psychotic symptoms — "
            "HCC 125 plus a behavioral overlay (HCC 58)."
        ),
        "required_classes": [
            ["N06DA", "N06DX"],                 # cholinesterase inhibitor / memantine
            ["N05AH", "N05AX"],                 # atypical antipsychotic
        ],
        "output_hccs": ["125", "58"],
        "base_confidence": 0.74,
        "citation": "APA Practice Guideline on the Use of Antipsychotics to Treat Agitation or Psychosis in Dementia (2016).",
    },
    {
        "id": "hiv_active_art",
        "name": "Active HIV antiretroviral therapy",
        "description": (
            "Any combination antiretroviral regimen (NRTI + INSTI/NNRTI/PI, "
            "or a fixed-dose combination tablet) is conclusive evidence of "
            "active HIV disease — HCC 1."
        ),
        "required_classes": [
            ["J05AR", "J05AF"],                 # NRTI / FDC ART
        ],
        "output_hccs": ["1"],
        "base_confidence": 0.92,
        "citation": "DHHS Guidelines for the Use of Antiretroviral Agents in Adults and Adolescents with HIV (clinicalinfo.hiv.gov, updated 2024).",
    },
    {
        "id": "bipolar_active",
        "name": "Active bipolar disorder",
        "description": (
            "Lithium plus an atypical antipsychotic is the canonical bipolar-I "
            "maintenance combination — implies active bipolar disorder under "
            "HCC 152 (V28 psychiatric severity tier)."
        ),
        "required_classes": [
            ["N05AN", "lithium"],               # lithium (ATC N05AN; some seeds use ingredient name)
            ["N05AH", "N05AX"],                 # atypical antipsychotic
        ],
        "output_hccs": ["152", "58"],
        "base_confidence": 0.80,
        "citation": "APA Practice Guideline for the Treatment of Patients with Bipolar Disorder, 2nd ed.; CANMAT 2018 update.",
    },
    {
        "id": "ckd_anemia",
        "name": "CKD with anemia",
        "description": (
            "Erythropoiesis-stimulating agent (epoetin / darbepoetin) plus "
            "iron supplementation implies CKD-associated anemia — HCC 138 "
            "(CKD stage 4-5) plus HCC 46 (anemia)."
        ),
        "required_classes": [
            ["B03XA"],                          # ESA
            ["B03A"],                           # iron preparations
        ],
        "output_hccs": ["138", "46"],
        "base_confidence": 0.78,
        "citation": "KDIGO 2012 Clinical Practice Guideline for Anemia in CKD (Kidney Int Suppl. 2012;2:279-335).",
    },
    {
        "id": "afib_anticoag_rate_control",
        "name": "Atrial fibrillation with anticoagulation",
        "description": (
            "DOAC or warfarin plus a rate-control agent (beta-blocker or "
            "non-DHP CCB) is the standard AFib management bundle — HCC 248."
        ),
        "required_classes": [
            ["B01AF", "B01AA", "B01AE"],        # DOAC / warfarin / dabigatran
            ["C07AB", "C07AG", "C07AA", "C08DA", "C08DB"],  # rate control
        ],
        "output_hccs": ["248"],
        "base_confidence": 0.80,
        "citation": "2023 ACC/AHA/ACCP/HRS Guideline for the Diagnosis and Management of Atrial Fibrillation (Circulation 2024;149:e1-e156).",
    },
    {
        "id": "copd_triple_therapy",
        "name": "COPD triple inhaler therapy",
        "description": (
            "ICS + LABA + LAMA (or a combination such as Trelegy) is GOLD "
            "Group E maintenance — implies severe COPD (HCC 111)."
        ),
        "required_classes": [
            ["R03BA", "R03AK"],                 # ICS or ICS-LABA combo
            ["R03AC", "R03AK"],                 # LABA or ICS-LABA combo
            ["R03BB"],                          # LAMA
        ],
        "output_hccs": ["111", "112"],
        "base_confidence": 0.76,
        "citation": "GOLD 2024 Global Strategy for Prevention, Diagnosis and Management of COPD (goldcopd.org).",
    },
    {
        "id": "parkinson_combination",
        "name": "Parkinson disease with adjunct therapy",
        "description": (
            "Levodopa/carbidopa plus a dopamine agonist or MAO-B inhibitor "
            "implies an established Parkinson diagnosis with motor fluctuations "
            "(HCC 78)."
        ),
        "required_classes": [
            ["N04BA"],                          # L-DOPA
            ["N04BC", "N04BD"],                 # dopamine agonist or MAO-B
        ],
        "output_hccs": ["78"],
        "base_confidence": 0.78,
        "citation": "AAN Practice Guideline: Treatment of Parkinson Disease Motor Symptoms (Neurology 2021;97:942-957).",
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _atc_prefix_match(med_atc_codes: list[str], required_prefixes: list[str]) -> str | None:
    """Return the first matching ATC code, or ``None``."""
    if not med_atc_codes or not required_prefixes:
        return None
    upper_codes = [c.upper() for c in med_atc_codes if c]
    upper_prefixes = [p.upper() for p in required_prefixes if p]
    for code in upper_codes:
        for prefix in upper_prefixes:
            if code == prefix or code.startswith(prefix):
                return code
    return None


def _resolve_drug(drug: str) -> dict[str, Any]:
    """Resolve a single drug name to ``{drug, generic, atc_code}`` shape.

    Goes through the brand-bridge first (so "Ozempic" -> A10BJ), then falls
    back to ``atc_service.resolve_drug_to_atc`` (which itself goes through the
    brand bridge in step 3b — duplicating it here lets us record the bridge
    metadata in the reasoning chain).
    """
    if not drug:
        return {"drug": drug, "generic": None, "atc_code": None, "source": "empty"}

    # Brand bridge first.
    bridge = brand_generic_service.brand_to_generic(drug)
    if bridge:
        atc_from_bridge = bridge.get("atc_code")
        generic = bridge.get("generic_name")
        # If the bridge gave us a generic name, prefer the ATC bridge row
        # (more authoritative than the brand row's denormalised atc_code).
        if generic:
            matches = atc_service.resolve_drug_to_atc(generic)
            if matches:
                head = matches[0]
                return {
                    "drug": drug,
                    "generic": generic,
                    "atc_code": head.get("atc_code"),
                    "source": "brand_bridge+atc_bridge",
                }
        if atc_from_bridge:
            return {
                "drug": drug,
                "generic": generic,
                "atc_code": atc_from_bridge,
                "source": "brand_bridge",
            }

    # Direct ATC bridge (handles ingredient names, RxCUIs, NDCs, fuzzy).
    matches = atc_service.resolve_drug_to_atc(drug)
    if matches:
        head = matches[0]
        return {
            "drug": drug,
            "generic": head.get("drug_name"),
            "atc_code": head.get("atc_code"),
            "source": "atc_bridge",
        }

    # Last-resort stem inference (low confidence).
    inferred = atc_service.unseen_drug_inference(drug)
    if inferred.get("atc_code"):
        return {
            "drug": drug,
            "generic": None,
            "atc_code": inferred.get("atc_code"),
            "source": f"stem:{inferred.get('inference_path')}",
        }

    return {"drug": drug, "generic": None, "atc_code": None, "source": "no_match"}


# ---------------------------------------------------------------------------
# Lithium / ingredient-name special handling
# ---------------------------------------------------------------------------
# The bipolar pattern's first required group accepts the ingredient name
# "lithium" because lithium's WHO ATC code (N05AN01) is sometimes seeded under
# the parent N05AN and sometimes elided entirely.  Accepting the literal
# generic name keeps the pattern trigger-able even when the ATC bridge has not
# been seeded with lithium specifically.

def _ingredient_name_match(generics: list[str], required: list[str]) -> str | None:
    if not generics or not required:
        return None
    lower_generics = {(g or "").lower() for g in generics if g}
    for token in required:
        if token.lower() in lower_generics:
            return token.lower()
    return None


# ---------------------------------------------------------------------------
# 1. evaluate_drug_combination
# ---------------------------------------------------------------------------

def evaluate_drug_combination(
    drug_list: list[str],
    patient_context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Match the patient's drug list against every curated polypharmacy pattern.

    Returns a list of triggered patterns ordered by confidence (highest first).
    Each entry includes the matching drugs, ATC codes, output HCCs, confidence
    and a reasoning chain suitable for chart-chase / MEAT audit display.

    ``patient_context`` may carry hints (``ejection_fraction``, ``coded_hccs``,
    ``serum_creatinine`` ...) that nudge confidence and/or the primary HCC
    selected.  The only currently-honoured key is ``ejection_fraction`` —
    when < 40 the CHF GDMT pattern's primary HCC switches to 224 (HFrEF).
    """
    if not drug_list:
        return []

    # Resolve every drug once up front (cheap when the bridge is in memory).
    resolved = [_resolve_drug(d) for d in drug_list if d and d.strip()]
    atc_codes = [r["atc_code"] for r in resolved if r.get("atc_code")]
    generics = [r["generic"] for r in resolved if r.get("generic")]

    triggered: list[dict[str, Any]] = []
    ctx = patient_context or {}

    for pattern in POLYPHARMACY_PATTERNS:
        matched_codes: list[str] = []
        matched_drugs: list[dict[str, Any]] = []
        all_groups_satisfied = True

        for req_group in pattern["required_classes"]:
            # Try ATC prefix match first.
            hit = _atc_prefix_match(atc_codes, req_group)
            if hit:
                matched_codes.append(hit)
                # Find the resolved entry whose atc_code matches.
                for r in resolved:
                    if (r.get("atc_code") or "").upper().startswith(hit.upper()):
                        matched_drugs.append(r)
                        break
                continue
            # Fallback: ingredient-name match (e.g. "lithium").
            ingr_hit = _ingredient_name_match(generics, req_group)
            if ingr_hit:
                matched_codes.append(ingr_hit)
                for r in resolved:
                    if (r.get("generic") or "").lower() == ingr_hit:
                        matched_drugs.append(r)
                        break
                continue
            all_groups_satisfied = False
            break

        if not all_groups_satisfied:
            continue

        # Boost confidence if any boost group hits.
        confidence = pattern["base_confidence"]
        boost_hits: list[str] = []
        for boost_group in pattern.get("boost_classes") or []:
            hit = _atc_prefix_match(atc_codes, boost_group)
            if hit:
                boost_hits.append(hit)
                confidence = min(0.97, confidence + pattern.get("boost_confidence", 0.05))

        # Patient-context tweaks.
        primary_hcc = pattern["output_hccs"][0]
        ef = ctx.get("ejection_fraction")
        if pattern["id"] == "chf_gdmt" and isinstance(ef, (int, float)) and ef < 40:
            # Promote to HFrEF HCC.
            primary_hcc = "224"
            confidence = min(0.97, confidence + 0.05)

        triggered.append({
            "pattern_id": pattern["id"],
            "pattern_name": pattern["name"],
            "description": pattern["description"],
            "primary_hcc": primary_hcc,
            "all_hccs": pattern["output_hccs"],
            "confidence": round(confidence, 3),
            "matched_atc_codes": matched_codes,
            "boost_atc_codes": boost_hits,
            "matched_drugs": [
                {
                    "drug": d.get("drug"),
                    "generic": d.get("generic"),
                    "atc_code": d.get("atc_code"),
                    "source": d.get("source"),
                }
                for d in matched_drugs
            ],
            "reasoning": (
                f"Patient is on {len(matched_drugs)} drug class(es) matching "
                f"{pattern['name']}: "
                f"{', '.join(d.get('drug') or '?' for d in matched_drugs)}. "
                f"This combination implies HCC {primary_hcc} per "
                f"{pattern['citation']}."
            ),
            "citation": pattern["citation"],
        })

    triggered.sort(key=lambda x: x["confidence"], reverse=True)
    return triggered


# ---------------------------------------------------------------------------
# 2. list_patterns
# ---------------------------------------------------------------------------

def list_patterns() -> list[dict[str, Any]]:
    """Return the pattern catalogue (no PHI / no patient state)."""
    return [
        {
            "id": p["id"],
            "name": p["name"],
            "description": p["description"],
            "required_classes": p["required_classes"],
            "boost_classes": p.get("boost_classes") or [],
            "output_hccs": p["output_hccs"],
            "base_confidence": p["base_confidence"],
            "citation": p["citation"],
        }
        for p in POLYPHARMACY_PATTERNS
    ]
