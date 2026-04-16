"""Auto-draft AHIMA/ACDIS-compliant provider queries for suspect / HCC
candidates that failed MEAT validation.

Public API
----------
    generate_query(candidate, bundle) -> ProviderQuery

The generator:
    1. Builds a prompt (``prompts/provider_query.md``) with the candidate,
       patient context bundle, and failed MEAT elements.
    2. Calls the configured LLM (Vertex / Gemini) via the shared client.
    3. Runs the post-generation compliance linter against the draft.
    4. Returns a :class:`ProviderQuery` with ``compliance_flags`` populated.
       Any non-empty ``compliance_flags`` means the draft MUST be reviewed by
       a human CDI specialist before being sent to the provider.

Compliance linter rules (non-exhaustive, conservative — false-positives are
preferable to leading queries reaching providers):

    LEADING_CONFIRM         "please confirm [patient has] X"
    LEADING_SHOULD_BE_CODED "should be coded as", "code this as"
    LEADING_INDICATE_DX     "indicate [specific diagnosis]", "is this X?"
    FINANCIAL_IMPACT        mentions of RAF, HCC, reimbursement, payment
    SINGLE_OPTION           body contains a yes/no question without >=3 options
    NO_EVIDENCE             zero ``supporting_citations``
    UNCITED_CLAIM           clinical fact in body with no matching citation quote
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional, Union

_PROMPT_PATH = Path(__file__).parent / "prompts" / "provider_query.md"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class SupportingCitation:
    document_id: str
    span_start: int = 0
    span_end: int = 0
    quote: str = ""


@dataclass
class ProviderQuery:
    to_provider_id: Optional[str]
    patient_id: str
    subject: str
    body: str
    supporting_citations: List[SupportingCitation] = field(default_factory=list)
    compliance_flags: List[str] = field(default_factory=list)

    @property
    def requires_human_review(self) -> bool:
        return bool(self.compliance_flags)


# ---------------------------------------------------------------------------
# Compliance linter
# ---------------------------------------------------------------------------


# Patterns are case-insensitive. Each tuple: (flag_code, regex, description).
LEADING_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    (
        "LEADING_CONFIRM",
        re.compile(r"\bplease\s+confirm\b.*\b(patient|pt)\b.*\bhas\b", re.I),
        "Leading phrase: 'please confirm patient has ...'",
    ),
    (
        "LEADING_CONFIRM",
        re.compile(r"\bcan\s+you\s+confirm\s+(the\s+)?(dx|diagnosis)\s+of\b", re.I),
        "Leading phrase: 'can you confirm the diagnosis of ...'",
    ),
    (
        "LEADING_SHOULD_BE_CODED",
        re.compile(r"\bshould\s+(this\s+)?be\s+coded\s+as\b", re.I),
        "Leading phrase: 'should be coded as'",
    ),
    (
        "LEADING_SHOULD_BE_CODED",
        re.compile(r"\bcode\s+this\s+as\b", re.I),
        "Leading phrase: 'code this as'",
    ),
    (
        "LEADING_INDICATE_DX",
        re.compile(
            r"\bindicate\b.*\b(diabetes|CHF|COPD|CKD|cancer|MI|stroke|dementia|depression)\b",
            re.I,
        ),
        "Leading phrase: directing provider to indicate a specific diagnosis",
    ),
    (
        "LEADING_INDICATE_DX",
        re.compile(
            r"\bis\s+this\s+(diabetes|CHF|COPD|CKD|cancer|MI|stroke|dementia|AKI|sepsis)\b\??",
            re.I,
        ),
        "Leading phrase: 'is this <specific diagnosis>?'",
    ),
    (
        "FINANCIAL_IMPACT",
        re.compile(r"\b(RAF|HCC|reimbursement|payment|revenue|capture\s+rate)\b", re.I),
        "Financial / coding-incentive language is not permitted in provider queries",
    ),
]


_OPTION_MARKER = re.compile(r"^\s*(?:[a-eA-E]\)|[-*•]|\d+[.)])\s+", re.M)
_QUESTION_MARK = re.compile(r"\?")


def lint(query: "ProviderQuery") -> List[str]:
    """Run all compliance checks. Returns list of flag codes (possibly empty)."""
    flags: list[str] = []
    text = f"{query.subject}\n{query.body}"

    for code, pattern, _desc in LEADING_PATTERNS:
        if pattern.search(text):
            if code not in flags:
                flags.append(code)

    # Must include supporting citations
    if not query.supporting_citations:
        flags.append("NO_EVIDENCE")

    # Multiple-choice rule: if body contains a question, require >=3 options.
    if _QUESTION_MARK.search(query.body):
        options = _OPTION_MARKER.findall(query.body)
        if len(options) < 3:
            flags.append("SINGLE_OPTION")

    # Uncited-claim heuristic: numeric clinical values in body (e.g. "A1c 8.2",
    # "BP 180/95") must appear in at least one citation quote.
    numeric_claims = re.findall(
        r"\b(?:A1c|HbA1c|BP|eGFR|EF|BNP|LDL|creatinine|troponin)\s*[:=]?\s*[\d./]+",
        query.body,
        flags=re.I,
    )
    if numeric_claims:
        joined_quotes = " ".join(c.quote.lower() for c in query.supporting_citations)
        for claim in numeric_claims:
            if claim.lower() not in joined_quotes:
                flags.append("UNCITED_CLAIM")
                break

    return flags


# ---------------------------------------------------------------------------
# Prompt + LLM
# ---------------------------------------------------------------------------


def _load_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


def _render_prompt(candidate: Any, bundle: Any, meat_gaps: list[str]) -> str:
    template = _load_prompt()
    return (
        template.replace("{candidate_json}", json.dumps(_to_jsonable(candidate), default=str))
        .replace("{bundle_json}", json.dumps(_to_jsonable(bundle), default=str))
        .replace("{meat_gaps}", json.dumps(meat_gaps))
    )


def _to_jsonable(obj: Any) -> Any:
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(v) for v in obj]
    if hasattr(obj, "model_dump"):  # pydantic v2
        return obj.model_dump()
    if hasattr(obj, "dict"):  # pydantic v1
        return obj.dict()
    if hasattr(obj, "__dict__"):
        return {k: _to_jsonable(v) for k, v in vars(obj).items() if not k.startswith("_")}
    return str(obj)


def _call_llm(prompt: str) -> dict[str, Any]:
    """Thin indirection so tests can monkeypatch. Real impl lives in
    ``app.services.llm`` (Vertex/Gemini client)."""
    from app.services.llm import generate_json  # type: ignore

    return generate_json(prompt)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def generate_query(
    candidate: Any,
    bundle: Any,
    *,
    meat_gaps: Optional[list[str]] = None,
    llm_fn=None,
) -> ProviderQuery:
    """Draft a compliant provider query for a failed-MEAT candidate.

    ``candidate`` may be a :class:`SuspectCandidate` or :class:`HCCCandidate`.
    ``bundle`` is a :class:`PatientContextBundle`. Both are duck-typed so this
    module stays decoupled from the extractor package.

    The returned :class:`ProviderQuery` always has ``compliance_flags``
    populated by the linter. A non-empty list means human CDI review is
    mandatory before the query may be sent.
    """
    gaps = meat_gaps or list(getattr(candidate, "meat_gaps", []) or [])
    prompt = _render_prompt(candidate, bundle, gaps)
    raw = (llm_fn or _call_llm)(prompt)

    citations = [
        SupportingCitation(
            document_id=str(c.get("document_id", "")),
            span_start=int(c.get("span_start", 0) or 0),
            span_end=int(c.get("span_end", 0) or 0),
            quote=str(c.get("quote", "")),
        )
        for c in (raw.get("supporting_citations") or [])
    ]

    query = ProviderQuery(
        to_provider_id=getattr(candidate, "attending_provider_id", None)
        or getattr(bundle, "primary_provider_id", None),
        patient_id=str(getattr(candidate, "patient_id", None) or getattr(bundle, "patient_id", "")),
        subject=str(raw.get("subject", "") or ""),
        body=str(raw.get("body", "") or ""),
        supporting_citations=citations,
    )
    query.compliance_flags = lint(query)
    return query


__all__ = [
    "ProviderQuery",
    "SupportingCitation",
    "generate_query",
    "lint",
    "LEADING_PATTERNS",
]
