"""AI pipeline package: context assembly, two-pass LLM HCC extraction,
MEAT evidence, suspect detection, HCC mapping, provider queries,
guardrails, eligibility, and orchestration."""

from .context_bundle import (
    PatientContextBundle,
    assemble_bundle,
    to_llm_payload,
)
from .eligibility import (
    can_run_analysis,
    get_eligible_patients,
    record_run_finish,
    record_run_start,
)
from .extractor import (
    BlindCandidate,
    HCCCandidate,
    MEATStatus,
    extract_blind,
    extract_contextual,
    sanitize_note,
)
from .guardrails import (
    sanitize_note_for_llm,
    scrub_pii_from_logs,
    validate_llm_output,
)
from .hcc_mapper import HCCMapping, map_icd_to_hcc
from .meat_extractor import (
    MEATEvidence,
    extract_meat_evidence,
    is_face_to_face_encounter,
    validate_quote_in_source,
)
from .orchestrator import run_for_patient, schedule_daily
from .provider_query import (
    LEADING_PATTERNS,
    ProviderQuery,
    SupportingCitation,
    generate_query,
    lint,
)
from .ai_suspect_pipeline import SuspectCandidate, detect_suspects
from .suspect_schema import SupportingEvidence, SuspectRule

# Back-compat alias: some callers may expect `extract_meat`.
extract_meat = extract_meat_evidence

__all__ = [
    # extractor
    "BlindCandidate",
    "HCCCandidate",
    "MEATStatus",
    "extract_blind",
    "extract_contextual",
    "sanitize_note",
    # meat_extractor
    "MEATEvidence",
    "extract_meat_evidence",
    "extract_meat",
    "is_face_to_face_encounter",
    "validate_quote_in_source",
    # context_bundle
    "PatientContextBundle",
    "assemble_bundle",
    "to_llm_payload",
    # suspect_engine
    "SuspectCandidate",
    "detect_suspects",
    # suspect_schema
    "SupportingEvidence",
    "SuspectRule",
    # hcc_mapper
    "HCCMapping",
    "map_icd_to_hcc",
    # provider_query
    "LEADING_PATTERNS",
    "ProviderQuery",
    "SupportingCitation",
    "generate_query",
    "lint",
    # orchestrator
    "run_for_patient",
    "schedule_daily",
    # guardrails
    "sanitize_note_for_llm",
    "scrub_pii_from_logs",
    "validate_llm_output",
    # eligibility
    "can_run_analysis",
    "get_eligible_patients",
    "record_run_finish",
    "record_run_start",
]
