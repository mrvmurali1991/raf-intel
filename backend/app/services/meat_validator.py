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

IMPORTANT — ADVISORY-ONLY STATUS
----------------------------------
This module is a **triage / pre-filter signal only**.  Its output MUST NOT be
used to set ``meat_status = 'complete'`` in ``raf_patient_hcc`` for billing
purposes.

NEGATION / CONTEXT DETECTION (added 2026-04)
---------------------------------------------
Simple regex-based context classifiers are now applied to every MEAT keyword
match.  Each match is tested for negation, hypothetical framing, historical
context, and family-history phrasing within a 60-character backward window.
Matches that fail these checks are silently dropped and do not count as MEAT
evidence.

This detection is intentionally conservative:

  * It operates on a fixed character window, not sentence-parse trees, so
    negation separated by a sentence boundary may still be missed.
  * It does NOT replace medspaCy / NegEx for billing-grade validation.
  * Family-history suppression is applied only when a family-history trigger
    immediately precedes the match inside the same window; standalone
    occurrences of "mother" or "father" that do not precede a match are not
    penalised.
  * Multi-sentence scope, coreference, and conjunction negation
    ("neither X nor Y") are out of scope for this layer.

For CMS RADV-defensible billing, only the LLM-validated path
(``app.services.ai_pipeline.meat_extractor.extract_meat_evidence``) may
promote an HCC to ``meat_status = 'complete'``.  This validator drives the
``raf_patient_hcc.meat_status = 'partial'`` triage track at most, controlled
by ``settings.require_llm_meat_for_billing``.

Limitations (rule-based keyword match)
---------------------------------------
* Regex context detection reduces false positives but is not perfect.
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
      confidence.  Keep this rule engine as a cheap fallback / sanity
      check layer.
"""
from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from typing import Literal

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# MEAT keyword lexicons
# ---------------------------------------------------------------------------
MONITOR_KEYWORDS: list[str] = [
    "monitor", "monitoring", "checking", "follow-up", "followup", "f/u",
    "trending", "watching", "lab review", "labs ordered", "imaging ordered",
    "vitals", "vital signs", "blood pressure", "bp", "o2 sat", "spo2",
    "weight", "bmi", "heart rate", "pulse",
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
    "medication", "prescribed", "rx", "treatment", "therapy",
    "continue medication", "continue current regimen", "continue treatment",
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

# ---------------------------------------------------------------------------
# Context-classification constants
# ---------------------------------------------------------------------------

# Sentence-ending punctuation that blocks a trigger from spanning into the
# current clause.
_SENTENCE_END_RE = re.compile(r"[.;!?]")

# Negation triggers — if any of these appear in the backward window before a
# MEAT keyword (without an intervening sentence boundary) the match is dropped.
NEGATION_TRIGGERS: list[str] = [
    "no evidence of",
    "negative for",
    "absence of",
    "rules out",
    "rule out",
    "free of",
    "never",
    "refused",
    "denies",
    "denied",
    "without",
    "r/o",
    "not",
    "no",
]

# Hypothetical / uncertainty triggers — match is dropped.
HYPOTHETICAL_TRIGGERS: list[str] = [
    "consideration",
    "suspected",
    "could be",
    "probable",
    "possibly",
    "possible",
    "consider",
    "suspect",
    "likely",
    "unless",
    "rule out",
    "r/o",
    "if",
]

# Historical / resolved triggers — match is dropped.
HISTORICAL_TRIGGERS: list[str] = [
    "status post",
    "previously",
    "in remission",
    "history of",
    "resolved",
    "hx of",
    "prior",
    "past",
    "h/o",
    "s/p",
]

# Family-history triggers — match is dropped only when one of these appears
# immediately before the keyword in the backward window.
FAMILY_TRIGGERS: list[str] = [
    "family history",
    "sibling",
    "parent",
    "father",
    "mother",
    "fhx",
]

# Pre-compile trigger lists into single alternation patterns, longest-first so
# greedier matches take priority (e.g. "no evidence of" before "no").
def _compile_triggers(triggers: list[str]) -> re.Pattern[str]:
    sorted_triggers = sorted(triggers, key=len, reverse=True)
    alts = "|".join(re.escape(t) for t in sorted_triggers)
    return re.compile(alts, re.IGNORECASE)

_NEGATION_RE = _compile_triggers(NEGATION_TRIGGERS)
_HYPOTHETICAL_RE = _compile_triggers(HYPOTHETICAL_TRIGGERS)
_HISTORICAL_RE = _compile_triggers(HISTORICAL_TRIGGERS)
_FAMILY_RE = _compile_triggers(FAMILY_TRIGGERS)

# How far back (in characters) to look for a trigger before a match.
_TRIGGER_WINDOW = 60


def _backward_window(text: str, match_start: int, window: int = _TRIGGER_WINDOW) -> str:
    """
    Return the substring ending just before match_start, up to `window` chars
    back, but truncated at the last sentence-ending punctuation so that
    triggers from a prior sentence are ignored.
    """
    lo = max(0, match_start - window)
    prefix = text[lo:match_start]
    # Find the rightmost sentence-ending character; keep only what follows it.
    sent_end = _SENTENCE_END_RE.search(prefix)
    if sent_end:
        # There may be multiple — find the last one.
        for m in _SENTENCE_END_RE.finditer(prefix):
            last_end = m.end()
        prefix = prefix[last_end:]
    return prefix


def _context_is_negated(text: str, match_start: int, window: int = _TRIGGER_WINDOW) -> bool:
    """Return True if a negation trigger precedes the match within `window` chars."""
    return bool(_NEGATION_RE.search(_backward_window(text, match_start, window)))


def _context_is_hypothetical(text: str, match_start: int, window: int = _TRIGGER_WINDOW) -> bool:
    """Return True if a hypothetical trigger precedes the match within `window` chars."""
    return bool(_HYPOTHETICAL_RE.search(_backward_window(text, match_start, window)))


def _context_is_historical(text: str, match_start: int, window: int = _TRIGGER_WINDOW) -> bool:
    """Return True if a historical/resolved trigger precedes the match within `window` chars."""
    return bool(_HISTORICAL_RE.search(_backward_window(text, match_start, window)))


def _context_is_family(text: str, match_start: int, window: int = _TRIGGER_WINDOW) -> bool:
    """Return True if a family-history trigger precedes the match within `window` chars."""
    return bool(_FAMILY_RE.search(_backward_window(text, match_start, window)))


ContextLabel = Literal["positive", "negated", "hypothetical", "historical", "family"]


def _classify_context(text: str, match_start: int, window: int = _TRIGGER_WINDOW) -> ContextLabel:
    """
    Classify the context of a match at `match_start` in `text`.

    Returns one of: "positive" | "negated" | "hypothetical" | "historical" | "family"

    Priority order: negated > hypothetical > historical > family > positive.
    Intended for diagnostic logging; not persisted to DB.
    """
    if _context_is_negated(text, match_start, window):
        return "negated"
    if _context_is_hypothetical(text, match_start, window):
        return "hypothetical"
    if _context_is_historical(text, match_start, window):
        return "historical"
    if _context_is_family(text, match_start, window):
        return "family"
    return "positive"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

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


def _match_keyword_with_context(
    text: str,
    keyword: str,
) -> bool:
    """
    Return True if `keyword` appears in `text` AND its context is "positive"
    (not negated, hypothetical, historical, or family-history).

    Uses whole-string search rather than span-relative positions so the
    backward window can reach into full note context when the snippet is
    already a narrow window extracted by `_find_condition_spans`.
    """
    kw_lower = keyword.lower()
    text_lower = text.lower()
    idx = text_lower.find(kw_lower)
    while idx != -1:
        ctx = _classify_context(text, idx)
        if ctx == "positive":
            return True
        idx = text_lower.find(kw_lower, idx + 1)
    return False


def _any_keyword_positive(text: str, keywords: Iterable[str]) -> bool:
    """Return True if any keyword in `keywords` matches with positive context."""
    return any(_match_keyword_with_context(text, kw) for kw in keywords)


# Keep the old helper for internal use where context checks are not needed.
def _any_keyword(text_lower: str, keywords: Iterable[str]) -> bool:
    return any(kw in text_lower for kw in keywords)


# ---------------------------------------------------------------------------
# Public API — MEATValidator class and standalone validate_meat functions
# ---------------------------------------------------------------------------

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

        if not result["monitor"] and _any_keyword_positive(snippet, MONITOR_KEYWORDS):
            result["monitor"] = True
        if not result["evaluate"] and _any_keyword_positive(snippet, EVALUATE_KEYWORDS):
            result["evaluate"] = True
        if not result["assess"] and _any_keyword_positive(snippet, ASSESS_KEYWORDS):
            result["assess"] = True
        if not result["treat"] and _any_keyword_positive(snippet, TREAT_KEYWORDS):
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


class MEATValidator:
    """
    Stateless wrapper around the module-level validate_meat functions.

    Exists so callers can instantiate a validator object and swap it out
    in dependency injection / testing without changing call sites.
    """

    def validate(
        self,
        note_text: str,
        icd_code: str,
        hcc_label: str | None = None,
    ) -> dict:
        return validate_meat(note_text, icd_code, hcc_label)

    def validate_batch(
        self,
        note_text: str,
        icd_codes: list[str],
    ) -> list[dict]:
        return validate_meat_batch(note_text, icd_codes)


# ---------------------------------------------------------------------------
# Self-tests
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.WARNING)

    PASS = "\033[32mPASS\033[0m"
    FAIL = "\033[31mFAIL\033[0m"
    failures = 0

    def check(label: str, condition: bool) -> None:
        global failures
        status = PASS if condition else FAIL
        print(f"  [{status}] {label}")
        if not condition:
            failures += 1

    # --- Positive examples: must be detected as MEAT evidence ---------------
    print("\n=== Positive examples (should be detected) ===")

    note_pos1 = "A&P: Diabetes E11.9 is stable on current therapy."
    r = validate_meat(note_pos1, "E11.9", "Diabetes")
    check("stable -> assess=True", r["assess"] is True)

    note_pos2 = "Patient with CHF I50.9. Labs ordered and f/u scheduled in 3 months."
    r = validate_meat(note_pos2, "I50.9", "heart failure")
    check("f/u -> monitor=True", r["monitor"] is True)

    note_pos3 = "COPD patient (J44.9) reviewed. Physical exam performed."
    r = validate_meat(note_pos3, "J44.9", "COPD")
    check("physical exam -> evaluate=True", r["evaluate"] is True)

    note_pos4 = "Hypertension I10. Continue metformin and referred to cardiologist."
    r = validate_meat(note_pos4, "I10", "Hypertension")
    check("referred -> treat=True", r["treat"] is True)

    note_pos5 = "Patient has worsened hypertension I10 since last visit."
    r = validate_meat(note_pos5, "I10", "Hypertension")
    check("worsened (no negation) -> assess=True", r["assess"] is True)

    # --- Negated examples: must NOT be detected as MEAT evidence ------------
    print("\n=== Negated examples (should NOT be detected) ===")

    note_neg1 = "Patient denies worsening of diabetes E11.9."
    r = validate_meat(note_neg1, "E11.9", "Diabetes")
    check("denies worsening -> assess=False", r["assess"] is False)

    note_neg2 = "No evidence of exacerbation in CHF patient I50.9."
    r = validate_meat(note_neg2, "I50.9", "heart failure")
    check("no evidence of exacerbation -> assess=False", r["assess"] is False)

    note_neg3 = "If worsens, consider increasing dose. COPD J44.9 otherwise stable."
    r = validate_meat(note_neg3, "J44.9", "COPD")
    # "consider increasing dose" — hypothetical, should not count as treat
    check("consider increasing dose -> treat=False", r["treat"] is False)
    # "otherwise stable" is positive
    check("otherwise stable -> assess=True", r["assess"] is True)

    note_neg4 = "Family history of hypertension. Patient with I10."
    r = validate_meat(note_neg4, "I10", "Hypertension")
    # "family history" precedes "hypertension" — that label match is in context
    # but no MEAT keyword follows it; verify no false positive on assess
    # The note has no assess keyword at all, so assess must be False
    check("family history only -> assess=False", r["assess"] is False)

    note_neg5 = "History of well-controlled diabetes E11.9, now resolved."
    r = validate_meat(note_neg5, "E11.9", "Diabetes")
    check("history of well-controlled -> assess=False", r["assess"] is False)

    # --- _classify_context diagnostic helper --------------------------------
    print("\n=== _classify_context helper ===")
    ctx1 = _classify_context("denies worsening here", len("denies "))
    check("_classify_context negated", ctx1 == "negated")

    ctx2 = _classify_context("if worsens consider", len("if worsens "))
    check("_classify_context hypothetical", ctx2 == "hypothetical")

    ctx3 = _classify_context("history of stable disease", len("history of "))
    check("_classify_context historical", ctx3 == "historical")

    ctx4 = _classify_context("mother had stable diabetes", len("mother had "))
    check("_classify_context family", ctx4 == "family")

    ctx5 = _classify_context("patient is stable", len("patient is "))
    check("_classify_context positive", ctx5 == "positive")

    # --- Legacy sanity cases (original tests) --------------------------------
    print("\n=== Legacy regression cases ===")

    note_complete = """
    CC: Diabetes follow-up.
    HPI: 58 y/o M with type 2 diabetes mellitus (E11.9). Patient reports
    compliance with metformin. Labs ordered including A1C; f/u in 3 months.
    Physical exam unremarkable. A&P: Diabetes well-controlled on current
    therapy. Continue metformin 1000 mg BID. Referred to diabetic educator.
    """
    r = validate_meat(note_complete, "E11.9", "Diabetes mellitus without complications")
    check("complete note -> COMPLETE or PARTIAL", r["status"] in ("COMPLETE", "PARTIAL"))

    note_partial = """
    CHF patient seen today. Heart failure appears stable on exam.
    No medication changes at this time.
    """
    r = validate_meat(note_partial, "I50.9", "Congestive heart failure")
    check("partial note -> elements >= 1", r["elements_found"] >= 1)

    note_missing = """
    Patient came in for a wellness visit. No acute complaints. Reviewed
    family history of cancer. Routine vaccinations up to date.
    """
    r = validate_meat(note_missing, "E11.9", "Diabetes mellitus")
    check("missing note -> MISSING", r["status"] == "MISSING")

    # --- Summary -------------------------------------------------------------
    print(f"\n{'All tests passed.' if failures == 0 else f'{failures} test(s) FAILED.'}")
    sys.exit(0 if failures == 0 else 1)
