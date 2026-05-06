"""
Knowledge-Graph lookup service used by the accuracy benchmark.

This module implements a deterministic, side-effect-free version of the
"KG layer" that the production suspect engine consults when reasoning
about a chart.  It does NOT touch the database — every rule is encoded
as a Python literal so the benchmark is fully reproducible and runnable
in CI.

Three rule families:

    medication signals     drug name pattern -> implied ICD-10
    lab signals            (analyte, op, threshold) -> implied ICD-10
    problem-list rules     prior diagnoses + complications -> upgraded ICD-10

Output: deduplicated list of {icd10, hcc, source, confidence} candidates
suitable for direct comparison against the chart's gold-standard label.

The HCC mapping is derived from `hccinfhir_utils.lookup_hcc` so the
codes returned are CMS-V28 authoritative and stay in sync with the rest
of the platform.
"""
from __future__ import annotations

from typing import Any, Iterable

from app.services.hccinfhir_utils import lookup_hcc


# ---------------------------------------------------------------------------
# Rule tables
# ---------------------------------------------------------------------------
#
# These tables intentionally cover the top-20 most prevalent HCCs in
# Medicare Advantage populations.  They are NOT exhaustive — the goal is
# evaluation reproducibility, not production coverage.  The production
# suspect engine pulls richer signal sets from the database.

MEDICATION_SIGNALS: list[dict[str, Any]] = [
    {"pattern": "metformin",      "icd10": "E119",  "confidence": 0.85, "label": "type 2 diabetes (metformin)"},
    {"pattern": "insulin",        "icd10": "E119",  "confidence": 0.80, "label": "diabetes on insulin"},
    {"pattern": "glipizide",      "icd10": "E119",  "confidence": 0.85, "label": "type 2 diabetes (sulfonylurea)"},
    {"pattern": "empagliflozin",  "icd10": "E119",  "confidence": 0.85, "label": "type 2 diabetes (SGLT2)"},
    {"pattern": "warfarin",       "icd10": "I4891", "confidence": 0.75, "label": "atrial fibrillation (anticoag)"},
    {"pattern": "apixaban",       "icd10": "I4891", "confidence": 0.75, "label": "atrial fibrillation (DOAC)"},
    {"pattern": "rivaroxaban",    "icd10": "I4891", "confidence": 0.70, "label": "atrial fibrillation (DOAC)"},
    {"pattern": "donepezil",      "icd10": "G309",  "confidence": 0.90, "label": "dementia (cholinesterase inh.)"},
    {"pattern": "memantine",      "icd10": "G309",  "confidence": 0.85, "label": "dementia (NMDA antagonist)"},
    {"pattern": "furosemide",     "icd10": "I5032", "confidence": 0.55, "label": "heart failure (loop diuretic)"},
    {"pattern": "spironolactone", "icd10": "I5032", "confidence": 0.55, "label": "heart failure (mineralocorticoid)"},
    {"pattern": "sacubitril",     "icd10": "I5022", "confidence": 0.90, "label": "heart failure with reduced EF"},
    {"pattern": "tiotropium",     "icd10": "J449",  "confidence": 0.85, "label": "COPD (LAMA)"},
    {"pattern": "fluticasone",    "icd10": "J449",  "confidence": 0.45, "label": "COPD/asthma (ICS)"},
    {"pattern": "lithium",        "icd10": "F319",  "confidence": 0.85, "label": "bipolar disorder"},
    {"pattern": "haloperidol",    "icd10": "F209",  "confidence": 0.75, "label": "schizophrenia spectrum"},
    {"pattern": "risperidone",    "icd10": "F209",  "confidence": 0.55, "label": "psychotic disorder"},
    {"pattern": "buprenorphine",  "icd10": "F1120", "confidence": 0.90, "label": "opioid use disorder, in remission"},
    {"pattern": "methadone",      "icd10": "F1120", "confidence": 0.85, "label": "opioid use disorder"},
    {"pattern": "lenalidomide",   "icd10": "C9000", "confidence": 0.90, "label": "multiple myeloma"},
]

# Lab signals: (LOINC-ish code OR name substring, operator, threshold, icd10)
# Only signals whose target ICD-10 maps to a V28 HCC are kept.
LAB_SIGNALS: list[dict[str, Any]] = [
    {"name": "hba1c",        "op": ">=", "threshold": 6.5,  "icd10": "E119",   "confidence": 0.90, "label": "diabetes (HbA1c >= 6.5)"},
    {"name": "hba1c",        "op": ">=", "threshold": 9.0,  "icd10": "E1165",  "confidence": 0.95, "label": "diabetes with hyperglycemia"},
    {"name": "egfr",         "op": "<",  "threshold": 30.0, "icd10": "N184",   "confidence": 0.95, "label": "CKD stage 4"},
    {"name": "egfr",         "op": "<",  "threshold": 15.0, "icd10": "N185",   "confidence": 0.97, "label": "CKD stage 5"},
    {"name": "bnp",          "op": ">",  "threshold": 400.0,"icd10": "I5032",  "confidence": 0.85, "label": "heart failure (BNP elevated)"},
    {"name": "spo2",         "op": "<",  "threshold": 90.0, "icd10": "J449",   "confidence": 0.70, "label": "chronic hypoxemia / COPD"},
    {"name": "ef",           "op": "<",  "threshold": 40.0, "icd10": "I5022",  "confidence": 0.90, "label": "HFrEF (EF<40)"},
]

# Problem-list upgrade chains.  Each rule fires when the listed prior
# code is present together with one of the trigger findings — and emits
# the upgraded code that better captures the patient's true severity.
PROBLEM_LIST_RULES: list[dict[str, Any]] = [
    # Diabetes complication chains
    {"requires_any": ["E119"], "triggers_any": ["polyneuropathy", "neuropathy"],   "icd10": "E1142",   "confidence": 0.85, "label": "DM with polyneuropathy"},
    {"requires_any": ["E119"], "triggers_any": ["ckd", "n184", "n185"],            "icd10": "E1122",   "confidence": 0.90, "label": "DM with CKD"},
    {"requires_any": ["E119"], "triggers_any": ["foot ulcer", "diabetic ulcer"],   "icd10": "E11621",  "confidence": 0.90, "label": "DM with foot ulcer"},
    # CKD upgrade chains (only V28-mapping codes)
    {"requires_any": ["N184"], "triggers_any": ["egfr<15", "stage 5", "dialysis"], "icd10": "N185",    "confidence": 0.90, "label": "CKD upgrade to stage 5"},
    # HF chains
    {"requires_any": ["I509", "I5032"], "triggers_any": ["ef<40", "reduced ef", "hfref"], "icd10": "I5022", "confidence": 0.85, "label": "HFrEF"},
    {"requires_any": ["I509", "I5022", "I5032"], "triggers_any": ["acute on chronic", "decompensated"], "icd10": "I5023", "confidence": 0.85, "label": "Acute on chronic systolic HF"},
    # Hypertensive CKD
    {"requires_any": ["N184", "N185"], "triggers_any": ["hypertension", "i10"], "icd10": "I120", "confidence": 0.75, "label": "Hypertensive CKD"},
    # Cancer recurrence
    {"requires_any": ["Z853"], "triggers_any": ["mets", "metastatic"], "icd10": "C7989", "confidence": 0.80, "label": "Recurrent/metastatic disease"},
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _norm_code(code: str | None) -> str:
    if not code:
        return ""
    return code.replace(".", "").strip().upper()


def _enrich_with_hcc(icd10: str) -> dict[str, Any]:
    """Resolve an ICD-10 code to its V28 HCC (or empty result)."""
    info = lookup_hcc(icd10)
    hccs = info.get("hcc_codes") or []
    return {
        "icd10": icd10,
        "hcc": hccs[0] if hccs else "",
        "hcc_label": (info.get("hcc_details") or [{}])[0].get("label", "") if hccs else "",
        "raf_weight": (info.get("hcc_details") or [{}])[0].get("reference_coefficient") if hccs else None,
    }


def _operator_matches(value: float, op: str, threshold: float) -> bool:
    return {
        ">":  value >  threshold,
        ">=": value >= threshold,
        "<":  value <  threshold,
        "<=": value <= threshold,
        "=":  value == threshold,
    }.get(op, lambda v, t: False)(value, threshold) if False else (
        (op == ">"  and value >  threshold) or
        (op == ">=" and value >= threshold) or
        (op == "<"  and value <  threshold) or
        (op == "<=" and value <= threshold) or
        (op == "="  and value == threshold)
    )


# ---------------------------------------------------------------------------
# Per-source inference
# ---------------------------------------------------------------------------

def infer_from_medications(medications: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for med in medications or []:
        name = (med.get("drug") or med.get("name") or "").lower().strip()
        if not name:
            continue
        for sig in MEDICATION_SIGNALS:
            if sig["pattern"] in name:
                rec = _enrich_with_hcc(sig["icd10"])
                rec.update({
                    "source": "medication",
                    "evidence_type": "medication",
                    "confidence": sig["confidence"],
                    "evidence": {"drug": med.get("drug") or med.get("name"), "rule": sig["label"]},
                })
                out.append(rec)
    return out


def infer_from_labs(labs: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for lab in labs or []:
        analyte = (lab.get("name") or lab.get("analyte") or "").lower().strip()
        try:
            value = float(lab.get("value"))
        except (TypeError, ValueError):
            continue
        for sig in LAB_SIGNALS:
            if sig["name"] not in analyte:
                continue
            if not _operator_matches(value, sig["op"], sig["threshold"]):
                continue
            rec = _enrich_with_hcc(sig["icd10"])
            rec.update({
                "source": "lab",
                "evidence_type": "lab",
                "confidence": sig["confidence"],
                "evidence": {
                    "analyte": analyte, "value": value,
                    "op": sig["op"], "threshold": sig["threshold"],
                    "rule": sig["label"],
                },
            })
            out.append(rec)
    return out


def infer_from_problem_list(
    problem_list: Iterable[dict[str, Any]] | None,
    findings_text: str | None = None,
) -> list[dict[str, Any]]:
    """Apply 'upgrade chain' rules.

    A problem entry is dict with keys diagnosis (ICD-10) and optional notes.
    findings_text is a free-text bag-of-words drawn from clinical note,
    vitals, labs etc. used to detect the trigger phrase for each rule.
    """
    coded = {_norm_code(p.get("diagnosis")) for p in (problem_list or []) if p.get("diagnosis")}
    bag = (findings_text or "").lower()
    # Add the problem-list titles into the bag of triggers so prior
    # diagnosis lists with no codes still surface.
    for p in (problem_list or []):
        if p.get("title"):
            bag += " " + str(p["title"]).lower()

    out: list[dict[str, Any]] = []
    for rule in PROBLEM_LIST_RULES:
        if not any(_norm_code(c) in coded for c in rule["requires_any"]):
            continue
        if not any(t.lower() in bag for t in rule["triggers_any"]):
            continue
        rec = _enrich_with_hcc(rule["icd10"])
        rec.update({
            "source": "problem_list",
            "evidence_type": "problem_list_chain",
            "confidence": rule["confidence"],
            "evidence": {"rule": rule["label"]},
        })
        out.append(rec)
    return out


def infer_recapture_gaps(prior_year_hccs: Iterable[str], current_hccs: Iterable[str]) -> list[dict[str, Any]]:
    """Flag HCCs that were billed last year but not yet captured this year."""
    prior = {h.strip().upper() for h in (prior_year_hccs or []) if h}
    current = {h.strip().upper() for h in (current_hccs or []) if h}
    out: list[dict[str, Any]] = []
    for hcc in sorted(prior - current):
        out.append({
            "icd10": "",
            "hcc": hcc,
            "hcc_label": "",
            "raf_weight": None,
            "source": "recapture",
            "evidence_type": "historical_hcc_gap",
            "confidence": 0.80,
            "evidence": {"prior_year_billed": True, "current_year_captured": False},
        })
    return out


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def patient_full_inference(chart: dict[str, Any]) -> dict[str, Any]:
    """Run KG inference over a fixture-style chart and return predictions.

    The expected chart shape:
        {
          "id": str,
          "demographics": {...},          (passthrough)
          "medications": [{"drug": ...}, ...],
          "labs": [{"name": ..., "value": ...}, ...],
          "problem_list": [{"diagnosis": "E119", "title": ...}, ...],
          "prior_year_hccs": ["18", "85", ...],
          "current_year_hccs": ["18", ...],
          "note_text": "..."              (free-text snippet for triggers)
        }

    Returns:
        {
          "predictions": [ {icd10, hcc, source, confidence, evidence_type, ...} ],
          "by_source": {medication: int, lab: int, ...},
          "predicted_hccs": [str, ...]   (deduplicated, sorted)
        }
    """
    findings_bag = " ".join(filter(None, [
        chart.get("note_text") or "",
        " ".join(str(v) for v in (chart.get("vitals") or {}).values()),
    ]))

    raw: list[dict[str, Any]] = []
    raw += infer_from_medications(chart.get("medications") or [])
    raw += infer_from_labs(chart.get("labs") or [])
    raw += infer_from_problem_list(chart.get("problem_list") or [], findings_bag)
    raw += infer_recapture_gaps(
        chart.get("prior_year_hccs") or [],
        chart.get("current_year_hccs") or [],
    )

    # Deduplicate by HCC, keeping the highest confidence and merging
    # evidence sources so per_evidence_type accounting still works.
    # Predictions without a V28 HCC mapping are dropped because the
    # benchmark scores at the HCC level.
    by_hcc: dict[str, dict[str, Any]] = {}
    for rec in raw:
        hcc = rec.get("hcc")
        if not hcc:
            continue
        existing = by_hcc.get(hcc)
        if existing is None or rec["confidence"] > existing["confidence"]:
            rec = dict(rec)
            rec["evidence_types"] = [rec["evidence_type"]] if not existing else \
                sorted(set(existing["evidence_types"] + [rec["evidence_type"]]))
            by_hcc[hcc] = rec
        else:
            existing["evidence_types"] = sorted(
                set(existing.get("evidence_types", [existing["evidence_type"]]) + [rec["evidence_type"]])
            )

    preds = list(by_hcc.values())
    by_source: dict[str, int] = {}
    for p in preds:
        by_source[p["source"]] = by_source.get(p["source"], 0) + 1

    return {
        "predictions": preds,
        "by_source": by_source,
        "predicted_hccs": sorted(by_hcc.keys()),
    }
