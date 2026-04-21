"""Shared dataclasses for the suspect engine (avoids circular imports)."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

Source = Literal["rule", "llm", "both"]
EvidenceType = Literal["lab", "med", "vital", "history"]


@dataclass
class SupportingEvidence:
    type: EvidenceType
    ref_id: str
    value: str


@dataclass
class SuspectCandidate:
    icd10: str
    hcc: str
    reason: str
    supporting_evidence: list[SupportingEvidence] = field(default_factory=list)
    confidence: float = 0.0
    source: Source = "rule"
    requires_provider_query: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def fingerprint(self) -> str:
        return self.icd10.split(".")[0]


@dataclass
class SuspectRule:
    rule_id: str
    description: str
    evaluate: Callable[[dict], SuspectCandidate | None]
