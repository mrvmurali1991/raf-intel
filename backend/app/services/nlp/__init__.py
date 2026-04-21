"""NLP sub-package: deterministic, rule-based clinical text utilities.

Contains the Chapman-style ConText / NegEx context detector used by
non-LLM pipelines (suspect_engine, stage1_extraction) to avoid firing
on negated, uncertain, hypothetical, historical or family-history mentions.
"""
from app.services.nlp.context_detector import (
    ContextResult,
    NEGATION_TRIGGERS,
    UNCERTAINTY_TRIGGERS,
    HYPOTHETICAL_TRIGGERS,
    HISTORICAL_TRIGGERS,
    FAMILY_TRIGGERS,
    PSEUDO_NEGATION_TRIGGERS,
    TERMINATION_TERMS,
    detect_context,
)

__all__ = [
    "ContextResult",
    "NEGATION_TRIGGERS",
    "UNCERTAINTY_TRIGGERS",
    "HYPOTHETICAL_TRIGGERS",
    "HISTORICAL_TRIGGERS",
    "FAMILY_TRIGGERS",
    "PSEUDO_NEGATION_TRIGGERS",
    "TERMINATION_TERMS",
    "detect_context",
]
