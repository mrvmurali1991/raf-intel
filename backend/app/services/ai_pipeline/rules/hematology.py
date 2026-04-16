"""Hematology + endocrine suspect rules (D63 anemia, E66 obesity, E03 hypothyroid)."""
from __future__ import annotations

from ..suspect_schema import SuspectCandidate, SuspectRule
from ._helpers import (
    evidence_from_labs,
    evidence_from_med,
    has_icd_prefix,
    has_med,
    lab_values_above,
    lab_values_below,
)


def _anemia(bundle: dict) -> SuspectCandidate | None:
    if has_icd_prefix(bundle, "D50", "D51", "D52", "D53", "D63", "D64"):
        return None
    hits = lab_values_below(bundle, 11.0, "hemoglobin", "hgb", "hb")
    if not hits:
        return None
    return SuspectCandidate(
        icd10="D64.9",
        hcc="",
        reason="Hemoglobin < 11 g/dL without anemia on problem list",
        supporting_evidence=evidence_from_labs(hits[:1]),
        confidence=0.75,
    )


def _hypothyroid(bundle: dict) -> SuspectCandidate | None:
    if has_icd_prefix(bundle, "E03", "E02", "E00"):
        return None
    tsh = lab_values_above(bundle, 5.0, "tsh")
    med = has_med(bundle, "levothyroxine", "synthroid", "liothyronine")
    if not tsh and not med:
        return None
    ev = evidence_from_labs(tsh[:1])
    if med:
        ev.append(evidence_from_med(med))
    return SuspectCandidate(
        icd10="E03.9",
        hcc="",
        reason="Elevated TSH or levothyroxine therapy without hypothyroidism on problem list",
        supporting_evidence=ev,
        confidence=0.8 if (tsh and med) else 0.65,
    )


def _morbid_obesity(bundle: dict) -> SuspectCandidate | None:
    if has_icd_prefix(bundle, "E66"):
        return None
    for v in bundle.get("vitals") or []:
        if str(v.get("type", "")).lower() != "bmi":
            continue
        try:
            bmi = float(v.get("value"))
        except (TypeError, ValueError):
            continue
        if bmi >= 40:
            from ..suspect_schema import SupportingEvidence
            return SuspectCandidate(
                icd10="E66.01",
                hcc="HCC48",
                reason=f"BMI {bmi} >= 40 (morbid obesity) without E66 coded",
                supporting_evidence=[SupportingEvidence(type="vital", ref_id=str(v.get("id", "")), value=f"BMI={bmi}")],
                confidence=0.9,
            )
    return None


RULES = [
    SuspectRule("ANEMIA-HGB-LOW", "Hgb < 11 without D50-D64", _anemia),
    SuspectRule("HYPOTHYROID-TSH-RX", "High TSH or levothyroxine without E03", _hypothyroid),
    SuspectRule("OBESITY-MORBID-BMI", "BMI >= 40 without E66", _morbid_obesity),
]
