"""
MEAT Validation Service
=======================
Rule-based validator for CMS HCC MEAT compliance.

MEAT stands for:
    Monitor  — clinician is tracking the condition (labs, f/u, imaging)
    Evaluate — clinician reviewed / examined / discussed the condition
    Assess   — clinician documented status (stable, controlled, worsened)
    Treat    — clinician prescribed medication, therapy, referral, etc.

CMS risk adjustment (RADV) requires every coded HCC to have documentation
of at least one MEAT element in the clinical note for the date of service.
A fully defensible HCC typically shows all four elements. This module
scores each ICD code against the note text and returns a compliance
status that maps to the `raf_patient_hcc.meat_status` enum
(COMPLETE / PARTIAL / MISSING).

Limitations (rule-based keyword match)
--------------------------------------
* Pure keyword spotting — cannot distinguish negation ("no worsening"),
  history ("mother had diabetes"), or hypothetical ("if worsens, start…").
* Condition matching is naive word-overlap against the HCC label; multi-
  word labels and abbreviations (HTN, CHF) are not normalized.
* Sentence windowing is character-based, not sentence-parsed.
* No temporal reasoning — cannot verify the MEAT evidence is for THIS
  encounter vs. a historical note pasted into HPI.

TODO: Upgrade to an ML / LLM approach:
    * clinical-NER model to link mentions to ICD codes
    * negation detection (NegEx / medspaCy)
    * a small fine-tuned classifier on RADV-audited notes to score
      MEAT elements per (condition, note) pair with calibrated
      confidence. Keep this rule engine as a cheap fallback / sanity
      check layer.
"""
from __future__ import annotations

import logging
import re
from typing import Iterable

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# MEAT keyword lexicons
# ---------------------------------------------------------------------------
MONITOR_KEYWORDS: list[str] = [
    "monitor", "monitoring", "checking", "follow-up", "followup", "f/u",
    "trending", "watching", "lab review", "labs ordered", "imaging ordered",
]

EVALUATE_KEYWORDS: list[str] = [
    "evaluate", "evaluation", "assessed", "exam", "examination",
    "reviewed", "discussed", "tested", "physical exam",
]

ASSESS_KEYWORDS: list[str] = [
    "stable", "unstable", "controlled", "uncontrolled", "improved",
    "worsened", "deteriorating", "exacerbation", "well-controlled",
    "poorly controlled", "a&p", "assessment:",
]

TREAT_KEYWORDS: list[str] = [
    "medication", "prescribed", "rx", "treatment", "therapy", "continue",
    "increased dose", "decreased dose", "started on", "discontinued",
    "referred", "referral",
]

# Character radius around a condition mention to search for MEAT evidence.
CONTEXT_WINDOW_CHARS = 200
MAX_EVIDENCE_SNIPPETS = 3

# Common short / stopword tokens to ignore when matching HCC labels.
_STOPWORDS = {
    "the", "a", "an", "of", "and", "or", "with", "without", "due",
    "to", "in", "on", "for", "by", "at", "from", "as", "is", "be",
    "not", "other", "unspecified", "type", "disease", "disorder",
    "syndrome", "condition", "status", "nos", "nec",
}

_WORD_RE = re.compile(r"[A-Za-z0-9&/\-]+")


def _tokenize_label(label: str) -> list[str]:
    """Return meaningful lowercase tokens from an HCC label."""
    if not label:
        return []
    tokens = [t.lower() for t in _WORD_RE.findall(label)]
    return [t for t in tokens if len(t) > 2 and t not in _STOPWORDS]


def _find_condition_spans(
    note_text: str,
    icd_code: str,
    hcc_label: str | None,
) -> list[tuple[int, int]]:
    """
    Return (start, end) character spans in note_text around every mention
    of the condition. Mentions are found via:
      1. direct occurrences of the ICD code (case-insensitive), or
      2. occurrences of any meaningful label token.
    Spans are widened by CONTEXT_WINDOW_CHARS on each side.
    """
    spans: list[tuple[int, int]] = []
    note_lower = note_text.lower()
    n = len(note_text)

    def _add(start: int, end: int) -> None:
        lo = max(0, start - CONTEXT_WINDOW_CHARS)
        hi = min(n, end + CONTEXT_WINDOW_CHARS)
        spans.append((lo, hi))

    # (1) ICD code literal match
    if icd_code:
        code_lower = icd_code.lower()
        idx = note_lower.find(code_lower)
        while idx != -1:
            _add(idx, idx + len(code_lower))
            idx = note_lower.find(code_lower, idx + 1)

    # (2) HCC label token match
    for token in _tokenize_label(hcc_label or ""):
        pattern = re.compile(r"\b" + re.escape(token) + r"\b", re.IGNORECASE)
        for m in pattern.finditer(note_text):
            _add(m.start(), m.end())

    return _merge_spans(spans)


def _merge_spans(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Merge overlapping / adjacent (start, end) spans."""
    if not spans:
        return []
    spans = sorted(spans)
    merged: list[tuple[int, int]] = [spans[0]]
    for start, end in spans[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged


def _any_keyword(text_lower: str, keywords: Iterable[str]) -> bool:
    return any(kw in text_lower for kw in keywords)


def validate_meat(
    note_text: str,
    icd_code: str,
    hcc_label: str | None = None,
) -> dict:
    """
    Validate MEAT evidence for a single ICD code within a clinical note.

    Parameters
    ----------
    note_text : full clinical note text (plain text)
    icd_code  : ICD-10-CM code being validated (e.g. "E11.9")
    hcc_label : optional human-readable label (e.g. "Diabetes without
                complications") used to locate condition mentions when
                the raw ICD code is not present verbatim in the note.

    Returns
    -------
    dict with per-element booleans, element count, status, and up to
    MAX_EVIDENCE_SNIPPETS evidence snippets.
    """
    result: dict = {
        "icd_code": icd_code,
        "monitor": False,
        "evaluate": False,
        "assess": False,
        "treat": False,
        "elements_found": 0,
        "status": "MISSING",
        "evidence_snippets": [],
    }

    if not note_text or not note_text.strip():
        logger.debug("validate_meat: empty note for %s", icd_code)
        return result

    spans = _find_condition_spans(note_text, icd_code, hcc_label)
    if not spans:
        logger.debug(
            "validate_meat: no condition mention for %s (%s)",
            icd_code, hcc_label,
        )
        return result

    snippets: list[str] = []
    for start, end in spans:
        snippet = note_text[start:end].strip()
        snippet_lower = snippet.lower()

        if not result["monitor"] and _any_keyword(snippet_lower, MONITOR_KEYWORDS):
            result["monitor"] = True
        if not result["evaluate"] and _any_keyword(snippet_lower, EVALUATE_KEYWORDS):
            result["evaluate"] = True
        if not result["assess"] and _any_keyword(snippet_lower, ASSESS_KEYWORDS):
            result["assess"] = True
        if not result["treat"] and _any_keyword(snippet_lower, TREAT_KEYWORDS):
            result["treat"] = True

        if len(snippets) < MAX_EVIDENCE_SNIPPETS:
            snippets.append(snippet)

    elements_found = sum(
        1 for k in ("monitor", "evaluate", "assess", "treat") if result[k]
    )
    result["elements_found"] = elements_found
    result["evidence_snippets"] = snippets

    if elements_found == 4:
        result["status"] = "COMPLETE"
    elif elements_found >= 1:
        result["status"] = "PARTIAL"
    else:
        result["status"] = "MISSING"

    logger.debug(
        "validate_meat: %s -> %s (%d/4)",
        icd_code, result["status"], elements_found,
    )
    return result


def validate_meat_batch(
    note_text: str,
    icd_codes: list[str],
) -> list[dict]:
    """Convenience wrapper: run validate_meat over a list of ICD codes."""
    return [validate_meat(note_text, code) for code in icd_codes]


# ---------------------------------------------------------------------------
# Sanity tests
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)

    note_complete = """
    CC: Diabetes follow-up.
    HPI: 58 y/o M with type 2 diabetes mellitus (E11.9). Patient reports
    compliance with metformin. Labs ordered including A1C; f/u in 3 months.
    Physical exam unremarkable. A&P: Diabetes well-controlled on current
    therapy. Continue metformin 1000 mg BID. Referred to diabetic educator.
    """

    note_partial = """
    CHF patient seen today. Heart failure appears stable on exam.
    No medication changes at this time.
    """

    note_missing = """
    Patient came in for a wellness visit. No acute complaints. Reviewed
    family history of cancer. Routine vaccinations up to date.
    """

    cases = [
        ("COMPLETE-ish", note_complete, "E11.9", "Diabetes mellitus without complications"),
        ("PARTIAL", note_partial, "I50.9", "Congestive heart failure"),
        ("MISSING", note_missing, "E11.9", "Diabetes mellitus"),
    ]

    for name, note, code, label in cases:
        r = validate_meat(note, code, label)
        print(f"\n=== {name} | {code} ===")
        print(f"  status={r['status']} elements={r['elements_found']}/4")
        print(f"  M={r['monitor']} E={r['evaluate']} A={r['assess']} T={r['treat']}")
        for s in r["evidence_snippets"]:
            print(f"  >>> {s[:120]}...")

    batch = validate_meat_batch(note_complete, ["E11.9", "I50.9"])
    print("\nbatch:", [(b["icd_code"], b["status"]) for b in batch])
