"""Diabetes suspect rules (E11.x / HCC 37-38)."""
from __future__ import annotations

from ..suspect_schema import SuspectCandidate, SuspectRule
from ._helpers import (
    evidence_from_labs,
    evidence_from_med,
    has_icd_prefix,
    has_med,
    lab_values_above,
)


def _two_high_a1c(bundle: dict) -> SuspectCandidate | None:
    if has_icd_prefix(bundle, "E11", "E10", "E13"):
        return None
    hits = lab_values_above(bundle, 6.5, "hba1c", "a1c", "hemoglobin a1c", min_count=2)
    if not hits:
        return None
    return SuspectCandidate(
        icd10="E11.9",
        hcc="HCC37",
        reason="Two HbA1c readings >= 6.5% without diabetes on problem list",
        supporting_evidence=evidence_from_labs(hits[:2]),
        confidence=0.85,
    )


def _a1c_plus_antidiabetic(bundle: dict) -> SuspectCandidate | None:
    if has_icd_prefix(bundle, "E11", "E10", "E13"):
        return None
    hits = lab_values_above(bundle, 6.5, "hba1c", "a1c", min_count=1)
    med = has_med(bundle, "metformin", "insulin", "glipizide", "glyburide", "empagliflozin", "semaglutide", "liraglutide")
    if not hits or not med:
        return None
    ev = evidence_from_labs(hits[:1]) + [evidence_from_med(med)]
    return SuspectCandidate(
        icd10="E11.9",
        hcc="HCC37",
        reason="HbA1c >= 6.5% plus antidiabetic medication without diabetes on problem list",
        supporting_evidence=ev,
        confidence=0.9,
    )


RULES = [
    SuspectRule("DM-A1C-TWICE", "Two A1c >= 6.5 without E11/E10/E13", _two_high_a1c),
    SuspectRule("DM-A1C-RX", "A1c >= 6.5 + antidiabetic Rx without E11/E10/E13", _a1c_plus_antidiabetic),
]
