"""Respiratory suspect rules (J44 COPD, J45 asthma)."""
from __future__ import annotations

from ..suspect_schema import SuspectCandidate, SuspectRule
from ._helpers import evidence_from_med, has_icd_prefix, has_med


def _copd_long_acting(bundle: dict) -> SuspectCandidate | None:
    if has_icd_prefix(bundle, "J44", "J43"):
        return None
    med = has_med(bundle, "tiotropium", "umeclidinium", "glycopyrrolate inhal", "long-acting muscarinic")
    if not med:
        return None
    return SuspectCandidate(
        icd10="J44.9",
        hcc="HCC280",
        reason="Long-acting muscarinic antagonist (COPD-specific) prescribed; no J44 coded",
        supporting_evidence=[evidence_from_med(med)],
        confidence=0.75,
    )


RULES = [
    SuspectRule("COPD-LAMA", "LAMA inhaler without J44", _copd_long_acting),
]
