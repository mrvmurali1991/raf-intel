"""Renal suspect rules (N18.x / HCC 138)."""
from __future__ import annotations

from ..suspect_schema import SuspectCandidate, SuspectRule
from ._helpers import evidence_from_labs, has_icd_prefix, lab_values_below, lab_values_above


def _low_egfr(bundle: dict) -> SuspectCandidate | None:
    if has_icd_prefix(bundle, "N18"):
        return None
    hits = lab_values_below(bundle, 60.0, "egfr", "gfr", min_count=2)
    if not hits:
        return None
    val = float(hits[0]["value"])
    if val < 15:
        icd = "N18.6"
    elif val < 30:
        icd = "N18.4"
    elif val < 45:
        icd = "N18.32"
    else:
        icd = "N18.31"
    return SuspectCandidate(
        icd10=icd,
        hcc="HCC138",
        reason=f"Two eGFR readings < 60 (latest={val}) without CKD on problem list",
        supporting_evidence=evidence_from_labs(hits[:2]),
        confidence=0.88,
    )


def _high_acr(bundle: dict) -> SuspectCandidate | None:
    if has_icd_prefix(bundle, "N18"):
        return None
    hits = lab_values_above(bundle, 300.0, "albumin/creatinine", "acr", "microalbumin")
    if not hits:
        return None
    return SuspectCandidate(
        icd10="N18.9",
        hcc="HCC138",
        reason="Albumin/creatinine ratio > 300 mg/g suggests CKD",
        supporting_evidence=evidence_from_labs(hits[:1]),
        confidence=0.7,
    )


RULES = [
    SuspectRule("CKD-EGFR-LOW", "Two eGFR < 60 without N18", _low_egfr),
    SuspectRule("CKD-ACR-HIGH", "ACR > 300 without N18", _high_acr),
]
