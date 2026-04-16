"""Lipid / metabolic suspect rules (E78.x)."""
from __future__ import annotations

from ..suspect_schema import SuspectCandidate, SuspectRule
from ._helpers import (
    evidence_from_labs,
    evidence_from_med,
    has_icd_prefix,
    has_med,
    lab_values_above,
)


def _ldl_plus_statin(bundle: dict) -> SuspectCandidate | None:
    if has_icd_prefix(bundle, "E78"):
        return None
    ldl = lab_values_above(bundle, 130.0, "ldl", "ldl-c", "ldl cholesterol")
    statin = has_med(bundle, "atorvastatin", "rosuvastatin", "simvastatin", "pravastatin", "statin")
    if not (ldl or statin):
        return None
    ev = evidence_from_labs(ldl[:1])
    if statin:
        ev.append(evidence_from_med(statin))
    reason = "Hyperlipidemia suggested by "
    if ldl and statin:
        reason += "elevated LDL-C plus statin therapy"
        conf = 0.85
    elif statin:
        reason += "statin therapy without hyperlipidemia on problem list"
        conf = 0.65
    else:
        reason += "elevated LDL-C"
        conf = 0.7
    return SuspectCandidate(
        icd10="E78.5",
        hcc="",  # not directly HCC-weighted but billable
        reason=reason,
        supporting_evidence=ev,
        confidence=conf,
    )


def _high_triglycerides(bundle: dict) -> SuspectCandidate | None:
    if has_icd_prefix(bundle, "E78"):
        return None
    tg = lab_values_above(bundle, 500.0, "triglyceride", "triglycerides")
    if not tg:
        return None
    return SuspectCandidate(
        icd10="E78.1",
        hcc="",
        reason="Triglycerides > 500 mg/dL without E78 coded",
        supporting_evidence=evidence_from_labs(tg[:1]),
        confidence=0.75,
    )


RULES = [
    SuspectRule("LIPID-LDL-STATIN", "Elevated LDL or statin without E78", _ldl_plus_statin),
    SuspectRule("LIPID-TG-HIGH", "TG > 500 without E78", _high_triglycerides),
]
