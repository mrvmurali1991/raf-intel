"""Core data model for per-HCC clinical sanity rules.

A ClinicalRule is a pure function from PatientContext -> RuleResult.  Rules
are registered in registry.py and executed by validator.py.  No rule may
touch the database or network; all evidence the rule needs must be supplied
on the PatientContext.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Callable, Optional


# ---------------------------------------------------------------------------
# Evidence inputs the rules operate on
# ---------------------------------------------------------------------------

@dataclass
class LabResult:
    """A single lab observation within the evidence window."""
    loinc: str
    value: float | None = None
    unit: str | None = None
    observed_at: date | None = None


@dataclass
class Medication:
    """A medication order or prescription."""
    rx_class: str           # free-text AHFS/ATC class; normalize via codes.normalize_rx_class
    name: str = ""
    active: bool = True
    started_at: date | None = None
    stopped_at: date | None = None


@dataclass
class Encounter:
    """A minimal encounter record — type, date, and optional attending specialty."""
    encounter_id: int
    encounter_date: date
    encounter_type: str = ""        # e.g. "office", "inpatient", "telehealth"
    provider_specialty: str = ""    # e.g. "oncology", "nephrology", "cardiology"


@dataclass
class ProcedureRecord:
    """A procedure or service performed (CPT/HCPCS)."""
    cpt: str
    performed_at: date | None = None


@dataclass
class PatientContext:
    """All the evidence one clinical rule may inspect.

    The billing gate caller is responsible for populating this from the
    patient record.  Rules MUST NOT read from anywhere else.
    """
    patient_id: int
    date_of_service: date
    age: int
    sex: str

    # Active diagnoses on the problem list + this encounter's billed dx
    diagnoses_icd10: list[str] = field(default_factory=list)

    # Active medication orders at DOS (and recent past)
    medications: list[Medication] = field(default_factory=list)

    # Labs within the evidence window (default 12 months back)
    labs: list[LabResult] = field(default_factory=list)

    # Procedures / radiology / PFT within the evidence window
    procedures: list[ProcedureRecord] = field(default_factory=list)

    # All encounters in the evidence window
    encounters: list[Encounter] = field(default_factory=list)

    # Optional pointer to the billed HCC's supporting MEAT evidence
    meat_status: str = "missing"    # one of "complete" | "partial" | "missing"

    # How many months back the caller considers "within window"; rules may
    # tighten this further for specific evidence classes.
    evidence_window_months: int = 12

    # Convenience lookups ------------------------------------------------

    def active_rx_classes(self) -> list[str]:
        return [m.rx_class for m in self.medications if m.active]

    def recent_labs(self, within_days: int = 365) -> list[LabResult]:
        cutoff = self.date_of_service - timedelta(days=within_days)
        return [l for l in self.labs if l.observed_at and l.observed_at >= cutoff]

    def recent_procedures(self, within_days: int = 365) -> list[ProcedureRecord]:
        cutoff = self.date_of_service - timedelta(days=within_days)
        return [p for p in self.procedures if p.performed_at and p.performed_at >= cutoff]

    def recent_encounter_types(self, within_days: int = 365) -> set[str]:
        cutoff = self.date_of_service - timedelta(days=within_days)
        return {
            e.encounter_type.lower()
            for e in self.encounters
            if e.encounter_date and e.encounter_date >= cutoff
        }


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

class RuleStatus(str, Enum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


@dataclass
class RuleResult:
    """Outcome of one rule's evaluation against a PatientContext."""
    hcc: int
    model: str
    rule_name: str
    status: RuleStatus
    reasons: list[str] = field(default_factory=list)
    # If the rule wants the UI to show something extra
    details: dict = field(default_factory=dict)

    @classmethod
    def passed(cls, hcc: int, model: str, rule_name: str, note: str = "") -> "RuleResult":
        return cls(hcc=hcc, model=model, rule_name=rule_name, status=RuleStatus.PASS,
                   reasons=[note] if note else [])

    @classmethod
    def warning(cls, hcc: int, model: str, rule_name: str, reasons: list[str]) -> "RuleResult":
        return cls(hcc=hcc, model=model, rule_name=rule_name, status=RuleStatus.WARN,
                   reasons=list(reasons))

    @classmethod
    def failure(cls, hcc: int, model: str, rule_name: str, reasons: list[str]) -> "RuleResult":
        return cls(hcc=hcc, model=model, rule_name=rule_name, status=RuleStatus.FAIL,
                   reasons=list(reasons))


# ---------------------------------------------------------------------------
# Rule descriptor
# ---------------------------------------------------------------------------

@dataclass
class ClinicalRule:
    """A per-HCC clinical sanity rule.

    Args:
        hcc:               CMS-HCC number this rule guards.
        model:             Model version this rule applies to (e.g. "V28").
        rule_name:         Short mnemonic used in logs and ValidationReport.
        description:       Human-readable description (source-cited).
        required_evidence: Callable that returns RuleResult.
        advisory_only:     If True, rule cannot produce FAIL — only PASS/WARN.
                           Use when the source guidance is ambiguous.
    """
    hcc: int
    model: str
    rule_name: str
    description: str
    required_evidence: Callable[[PatientContext], RuleResult]
    advisory_only: bool = False

    def evaluate(self, ctx: PatientContext) -> RuleResult:
        result = self.required_evidence(ctx)
        if self.advisory_only and result.status == RuleStatus.FAIL:
            # Demote FAIL to WARN for advisory-only rules — we're not confident
            # enough in the source guidance to block a bill.
            result = RuleResult.warning(
                self.hcc, self.model, self.rule_name,
                ["[advisory] " + r for r in result.reasons],
            )
        return result
