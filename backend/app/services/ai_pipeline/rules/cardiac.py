"""Cardiac suspect rules (I50.x CHF / I48.x AFib)."""
from __future__ import annotations

from ..suspect_schema import SuspectCandidate, SuspectRule
from ._helpers import (
    evidence_from_labs,
    evidence_from_med,
    has_icd_prefix,
    has_med,
    lab_values_above,
)


def _chf_bnp_loop(bundle: dict) -> SuspectCandidate | None:
    if has_icd_prefix(bundle, "I50"):
        return None
    bnp_hits = lab_values_above(bundle, 400.0, "bnp", "nt-probnp", "nt probnp")
    diuretic = has_med(bundle, "furosemide", "bumetanide", "torsemide")
    if not bnp_hits or not diuretic:
        return None
    return SuspectCandidate(
        icd10="I50.9",
        hcc="HCC226",
        reason="Elevated BNP/NT-proBNP with loop diuretic and no CHF on problem list",
        supporting_evidence=evidence_from_labs(bnp_hits[:1]) + [evidence_from_med(diuretic)],
        confidence=0.82,
    )


def _afib_anticoag(bundle: dict) -> SuspectCandidate | None:
    if has_icd_prefix(bundle, "I48"):
        return None
    # Vital-based: look for documented irregular rhythm via vitals or ecg tag
    anticoag = has_med(bundle, "apixaban", "rivaroxaban", "dabigatran", "warfarin")
    if not anticoag:
        return None
    # Anticoag alone is weak — require at least one rhythm cue in notes/vitals
    for v in bundle.get("vitals") or []:
        rhythm = str(v.get("type", "")).lower() + " " + str(v.get("value", "")).lower()
        if "afib" in rhythm or "atrial fib" in rhythm or "irregular" in rhythm:
            from ..suspect_schema import SupportingEvidence
            return SuspectCandidate(
                icd10="I48.91",
                hcc="HCC238",
                reason="Anticoagulant prescribed with documented irregular rhythm; no AFib coded",
                supporting_evidence=[
                    evidence_from_med(anticoag),
                    SupportingEvidence(type="vital", ref_id=str(v.get("id", "")), value=str(v.get("value", ""))),
                ],
                confidence=0.65,
            )
    return None


RULES = [
    SuspectRule("CHF-BNP-LOOP", "BNP elevated + loop diuretic, no I50", _chf_bnp_loop),
    SuspectRule("AFIB-ANTICOAG-RHYTHM", "Anticoag + irregular rhythm, no I48", _afib_anticoag),
]
