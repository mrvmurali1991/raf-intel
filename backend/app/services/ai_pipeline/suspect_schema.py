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
    # --- Calibration layer ---
    # ``confidence`` above is treated as the raw score for legacy reasons.
    # ``raw_confidence`` mirrors it and ``calibrated_confidence`` is filled
    # in by the pipeline after ``merge`` (see ai_suspect_pipeline.detect_suspects).
    # When settings.use_calibrated_confidence is False or no calibrator
    # artifact exists, calibrated_confidence == raw_confidence.
    raw_confidence: float = 0.0
    calibrated_confidence: float | None = None

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
