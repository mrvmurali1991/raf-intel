"""Hepatic suspect rules (K70/K74 cirrhosis/chronic liver disease)."""
from __future__ import annotations

from ..suspect_schema import SuspectCandidate, SuspectRule
from ._helpers import (
    evidence_from_labs,
    has_icd_prefix,
    lab_values_above,
    lab_values_below,
)


def _cirrhosis_signals(bundle: dict) -> SuspectCandidate | None:
    if has_icd_prefix(bundle, "K70", "K74", "K76"):
        return None
    low_plt = lab_values_below(bundle, 150.0, "platelet")
    high_inr = lab_values_above(bundle, 1.3, "inr")
    low_alb = lab_values_below(bundle, 3.5, "albumin")
    signals = [s for s in (low_plt, high_inr, low_alb) if s]
    if len(signals) < 2:
        return None
    ev = []
    for s in signals:
        ev += evidence_from_labs(s[:1])
    return SuspectCandidate(
        icd10="K74.60",
        hcc="HCC32",
        reason="Multiple cirrhosis signals (low platelets, elevated INR, low albumin) without K70/K74 coded",
        supporting_evidence=ev,
        confidence=0.7,
    )


RULES = [
    SuspectRule("LIVER-CIRRHOSIS-TRIAD", "2+ of low plt / high INR / low albumin without K70/K74", _cirrhosis_signals),
]
