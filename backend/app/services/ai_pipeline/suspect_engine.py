"""Backward-compatibility shim.

All implementation has moved to :mod:`ai_suspect_pipeline`.
Import from there for new code.
"""
from __future__ import annotations

# Re-export everything callers used to import from this module.
from .ai_suspect_pipeline import (  # noqa: F401
    _bundle_for_llm,
    _load_prompt_template,
    _strip_fences,
    detect_suspects,
    llm_generate,
    merge,
    run_llm,
    run_rules,
)
from .suspect_schema import SupportingEvidence, SuspectCandidate, SuspectRule  # noqa: F401
