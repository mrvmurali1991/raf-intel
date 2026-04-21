"""Per-HCC clinical sanity rules for CMS-HCC V28.

Public API:
    PatientContext            — evidence container the billing gate populates
    BilledHCC, ValidationReport — validator I/O
    validate_billed_hccs      — main entrypoint
    ALL_RULES, lookup_rules   — registry accessors
"""
from .rules import (
    ClinicalRule,
    Encounter,
    LabResult,
    Medication,
    PatientContext,
    ProcedureRecord,
    RuleResult,
    RuleStatus,
)
from .registry import ALL_RULES, lookup_rules
from .validator import BilledHCC, HCCValidationOutcome, ValidationReport, validate_billed_hccs

__all__ = [
    "ClinicalRule",
    "PatientContext",
    "LabResult",
    "Medication",
    "Encounter",
    "ProcedureRecord",
    "RuleResult",
    "RuleStatus",
    "ALL_RULES",
    "lookup_rules",
    "BilledHCC",
    "HCCValidationOutcome",
    "ValidationReport",
    "validate_billed_hccs",
]
