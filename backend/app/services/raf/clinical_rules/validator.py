"""Clinical-rule validator for billed HCCs.

A "billed HCC" is one that is about to be promoted to billed status in
raf_patient_hcc (meat_status transition to "complete" or equivalent).
Before that promotion happens, this validator runs every registered rule
for that HCC's code and returns a ValidationReport.

The billing gate consumes the report:
  status == "fail"  → block promotion (with reasons)
  status == "warn"  → allow promotion but surface warning in UI
  status == "pass"  → allow promotion cleanly
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .registry import lookup_rules
from .rules import ClinicalRule, PatientContext, RuleResult, RuleStatus


@dataclass
class BilledHCC:
    """A single HCC proposed for billed status."""
    hcc: int
    model: str = "V28"
    source_icd10_codes: list[str] = field(default_factory=list)


@dataclass
class HCCValidationOutcome:
    """Result of running all rules for a single HCC."""
    hcc: int
    model: str
    status: RuleStatus
    rule_results: list[RuleResult] = field(default_factory=list)

    @property
    def reasons(self) -> list[str]:
        return [r for rr in self.rule_results for r in rr.reasons]


@dataclass
class ValidationReport:
    """Aggregate outcome across all billed HCCs on a patient."""
    patient_id: int
    outcomes: list[HCCValidationOutcome] = field(default_factory=list)

    @property
    def overall_status(self) -> RuleStatus:
        statuses = {o.status for o in self.outcomes}
        if RuleStatus.FAIL in statuses:
            return RuleStatus.FAIL
        if RuleStatus.WARN in statuses:
            return RuleStatus.WARN
        return RuleStatus.PASS

    def failed(self) -> list[HCCValidationOutcome]:
        return [o for o in self.outcomes if o.status == RuleStatus.FAIL]

    def warnings(self) -> list[HCCValidationOutcome]:
        return [o for o in self.outcomes if o.status == RuleStatus.WARN]

    def to_dict(self) -> dict:
        return {
            "patient_id": self.patient_id,
            "overall_status": self.overall_status.value,
            "fail_count": len(self.failed()),
            "warn_count": len(self.warnings()),
            "outcomes": [
                {
                    "hcc": o.hcc,
                    "model": o.model,
                    "status": o.status.value,
                    "reasons": o.reasons,
                    "rules": [
                        {"rule": rr.rule_name, "status": rr.status.value, "reasons": rr.reasons}
                        for rr in o.rule_results
                    ],
                }
                for o in self.outcomes
            ],
        }


def _worst_status(results: list[RuleResult]) -> RuleStatus:
    if any(r.status == RuleStatus.FAIL for r in results):
        return RuleStatus.FAIL
    if any(r.status == RuleStatus.WARN for r in results):
        return RuleStatus.WARN
    return RuleStatus.PASS


def validate_billed_hccs(
    hccs: list[BilledHCC],
    patient_ctx: PatientContext,
) -> ValidationReport:
    """Validate every billed HCC against its registered clinical rules.

    If no rule is registered for a given HCC, that HCC gets an automatic
    PASS — we do not block unknown HCCs, only those with explicit guidance.
    """
    outcomes: list[HCCValidationOutcome] = []
    for billed in hccs:
        rules: list[ClinicalRule] = lookup_rules(billed.hcc, billed.model)
        if not rules:
            outcomes.append(HCCValidationOutcome(
                hcc=billed.hcc, model=billed.model,
                status=RuleStatus.PASS,
                rule_results=[],
            ))
            continue

        results = [r.evaluate(patient_ctx) for r in rules]
        outcomes.append(HCCValidationOutcome(
            hcc=billed.hcc, model=billed.model,
            status=_worst_status(results),
            rule_results=results,
        ))
    return ValidationReport(patient_id=patient_ctx.patient_id, outcomes=outcomes)
