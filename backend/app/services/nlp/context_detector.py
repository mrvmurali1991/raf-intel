"""
Clinical context detector — Chapman-style ConText / NegEx.

Given a free-text clinical note and the character span of a candidate
concept (e.g. an ICD label match), classify the concept along five
independent axes:

    * negated       — "no evidence of CHF", "denies chest pain", "ruled out MI"
    * uncertain     — "possible sepsis", "r/o pneumonia", "suspected CKD"
    * historical    — "history of PE 2018", "PMH significant for MI"
    * hypothetical  — "if worsens", "consider pneumonia", "return precautions"
    * family        — "mother with DM", "family history of CAD"

Experiencer is returned separately as "patient" | "family" | "other".

Why custom instead of medspacy
------------------------------
medspacy depends on spaCy + scispacy + model downloads (>500 MB), does
not type-check cleanly under mypy strict, and is far heavier than this
codebase needs.  A Chapman-style NegEx with trigger / pseudo-trigger /
termination-term lists (Chapman 2001, Harkema 2009 ConText) covers every
RADV-relevant case in the suspect/MEAT pipelines with zero extra deps.

This module is the single source of truth for clinical-context trigger
lists — do not copy these constants elsewhere, import them.

Algorithm
---------
1. Operate on a WINDOW around the candidate span: ``WINDOW_BEFORE`` chars
   before the span start and ``WINDOW_AFTER`` chars after the span end.
2. Truncate the window at any ``TERMINATION_TERMS`` occurrence between
   the trigger and the target (e.g. "but", "however", "except").
3. Look for triggers:
     * Backward-looking triggers (most NegEx triggers) fire when they
       appear in the text BEFORE the span within the untruncated window.
     * Forward-looking triggers (e.g. "unlikely", "was ruled out") fire
       when they appear AFTER the span.
4. Exclude matches that fall inside any ``PSEUDO_NEGATION_TRIGGERS``
   phrase ("no change", "not necessarily", "gram negative") — these look
   like negations but are not.

Public API
----------
detect_context(text, span_start, span_end) -> ContextResult
"""
from __future__ import annotations

import re
from typing import Final, TypedDict

# ---------------------------------------------------------------------------
# Tunable window size (in characters)
# ---------------------------------------------------------------------------
WINDOW_BEFORE: Final[int] = 80
WINDOW_AFTER: Final[int] = 60


# ---------------------------------------------------------------------------
# Trigger lists
#
# Each list is the SINGLE SOURCE OF TRUTH for its category.  Callers that
# need these phrases must import from this module rather than re-declare
# them (per repo policy on copy-paste constants).
# ---------------------------------------------------------------------------

# Pseudo-negation phrases.  If a candidate negation trigger sits inside
# one of these phrases it is suppressed.  Matched case-insensitively.
PSEUDO_NEGATION_TRIGGERS: Final[tuple[str, ...]] = (
    "no change",
    "no increase",
    "no decrease",
    "not only",
    "not necessarily",
    "not certain whether",
    "not certain if",
    "gram negative",
    "gram-negative",
    "without difficulty",
    "not extend",
    "not cause",
    "no further",
)

# Backward-looking negation triggers.  Fire when they appear in the
# window BEFORE the candidate span.
NEGATION_TRIGGERS_PRE: Final[tuple[str, ...]] = (
    "denies",
    "deny",
    "denied",
    "no evidence of",
    "no signs of",
    "no sign of",
    "no indication of",
    "no suggestion of",
    "no symptoms of",
    "no history of",
    "no hx of",
    "no known",
    "negative for",
    "not consistent with",
    "without evidence of",
    "without signs of",
    "without indication of",
    "without",
    "absence of",
    "absent",
    "cannot see",
    "cannot find",
    "ruled out",
    "rule out",
    "ruling out",
    "r/o",
    "rules out",
    "never had",
    "never developed",
    "free of",
    "resolved",
    "patient was not",
    "pt was not",
    "no",
)

# Forward-looking negation triggers.  Fire when they appear AFTER the span.
NEGATION_TRIGGERS_POST: Final[tuple[str, ...]] = (
    "unlikely",
    "was ruled out",
    "is ruled out",
    "has been ruled out",
    "have been ruled out",
    "not seen",
    "not observed",
    "not present",
    "is negative",
    "are negative",
    "was negative",
    "were negative",
)

# Public union (pre + post).
NEGATION_TRIGGERS: Final[tuple[str, ...]] = NEGATION_TRIGGERS_PRE + NEGATION_TRIGGERS_POST

# Uncertainty / hedging.  Matched backward-looking.
UNCERTAINTY_TRIGGERS: Final[tuple[str, ...]] = (
    "possible",
    "possibly",
    "probable",
    "probably",
    "likely",
    "suspected",
    "suspicious for",
    "consistent with",
    "concerning for",
    "concern for",
    "questionable",
    "question of",
    "cannot rule out",
    "can't rule out",
    "unable to rule out",
    "cannot exclude",
    "differential includes",
    "ddx includes",
    "may have",
    "might have",
    "could be",
    "could represent",
    "appears to be",
    "appears",
    "seems",
    "workup for",
    "evaluation for",
    "rule out",
    "r/o",
    "rule-out",
)

# Historical mentions: past-tense / PMH context.  Backward-looking.
HISTORICAL_TRIGGERS: Final[tuple[str, ...]] = (
    "history of",
    "hx of",
    "h/o",
    "past medical history",
    "past medical history of",
    "pmh",
    "pmh of",
    "pmhx",
    "past history of",
    "previously diagnosed",
    "previously had",
    "prior history of",
    "prior",
    "status post",
    "s/p",
    "resolved",
    "remote history of",
    "longstanding",
    "years ago",
    "year ago",
    "in the past",
)

# Hypothetical / contingent: if-then, return precautions, consider.
HYPOTHETICAL_TRIGGERS: Final[tuple[str, ...]] = (
    "if",
    "unless",
    "in case of",
    "should",
    "return if",
    "return precautions",
    "would be",
    "would indicate",
    "consider",
    "consideration of",
    "consideration for",
    "rule out",
    "call if",
    "come back if",
    "to rule out",
)

# Family-history experiencer.  Backward-looking.
FAMILY_TRIGGERS: Final[tuple[str, ...]] = (
    "family history of",
    "family hx of",
    "fh of",
    "fhx of",
    "fh:",
    "fhx:",
    "mother with",
    "mother has",
    "mother had",
    "father with",
    "father has",
    "father had",
    "brother with",
    "brother has",
    "brother had",
    "sister with",
    "sister has",
    "sister had",
    "parent with",
    "parent has",
    "parents with",
    "sibling with",
    "sibling has",
    "son with",
    "daughter with",
    "grandmother with",
    "grandmother had",
    "grandfather with",
    "grandfather had",
    "relative with",
    "aunt with",
    "uncle with",
)

# Termination terms — when found between a trigger and the target span
# they cancel the trigger's effect.
TERMINATION_TERMS: Final[tuple[str, ...]] = (
    "but",
    "however",
    "although",
    "though",
    "except",
    "aside from",
    "apart from",
    "nevertheless",
    "yet",
    "still",
    ";",
)


# ---------------------------------------------------------------------------
# Public result type
# ---------------------------------------------------------------------------

class ContextResult(TypedDict):
    """Classification of a candidate concept span along the ConText axes."""
    negated: bool
    uncertain: bool
    historical: bool
    hypothetical: bool
    family: bool
    experiencer: str  # "patient" | "family" | "other"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _compile_phrase(phrase: str) -> re.Pattern[str]:
    """
    Build a word-boundary-aware regex for a trigger phrase.

    Word boundaries use ``\\b`` when the phrase starts/ends with a word
    character and a whitespace / start-of-string lookaround otherwise so
    phrases containing punctuation (e.g. "r/o", "fh:") still match.
    """
    escaped = re.escape(phrase)
    # Replace escaped spaces with flexible whitespace.
    escaped = escaped.replace(r"\ ", r"\s+")

    left = r"\b" if phrase[:1].isalnum() else r"(?:^|\s|[\.,;:!\?\(\)])"
    right = r"\b" if phrase[-1:].isalnum() else r"(?:$|\s|[\.,;:!\?\(\)])"
    return re.compile(f"{left}{escaped}{right}", re.IGNORECASE)


# Pre-compile every trigger list once at import time.
_PSEUDO_NEG_REGEX: Final[list[re.Pattern[str]]] = [
    _compile_phrase(p) for p in PSEUDO_NEGATION_TRIGGERS
]
_NEG_PRE_REGEX: Final[list[re.Pattern[str]]] = [
    _compile_phrase(p) for p in NEGATION_TRIGGERS_PRE
]
_NEG_POST_REGEX: Final[list[re.Pattern[str]]] = [
    _compile_phrase(p) for p in NEGATION_TRIGGERS_POST
]
_UNCERTAIN_REGEX: Final[list[re.Pattern[str]]] = [
    _compile_phrase(p) for p in UNCERTAINTY_TRIGGERS
]
_HISTORICAL_REGEX: Final[list[re.Pattern[str]]] = [
    _compile_phrase(p) for p in HISTORICAL_TRIGGERS
]
_HYPOTHETICAL_REGEX: Final[list[re.Pattern[str]]] = [
    _compile_phrase(p) for p in HYPOTHETICAL_TRIGGERS
]
_FAMILY_REGEX: Final[list[re.Pattern[str]]] = [
    _compile_phrase(p) for p in FAMILY_TRIGGERS
]
_TERMINATION_REGEX: Final[list[re.Pattern[str]]] = [
    _compile_phrase(t) for t in TERMINATION_TERMS
]


def _inside_pseudo_negation(window_text: str, match_start: int, match_end: int) -> bool:
    """Return True if [match_start, match_end] overlaps a pseudo-negation phrase."""
    for pat in _PSEUDO_NEG_REGEX:
        for pm in pat.finditer(window_text):
            if pm.start() <= match_start and pm.end() >= match_end:
                return True
    return False


def _earliest_termination(window_text: str, start: int, end: int) -> int | None:
    """
    Return the earliest termination-term position strictly between *start*
    and *end* (both in window coordinates), or None if there is none.
    """
    earliest: int | None = None
    for pat in _TERMINATION_REGEX:
        m = pat.search(window_text, start, end)
        if m is None:
            continue
        pos = m.start()
        if earliest is None or pos < earliest:
            earliest = pos
    return earliest


def _pre_trigger_fires(
    pre_text: str,
    patterns: list[re.Pattern[str]],
) -> bool:
    """
    Scan *pre_text* for any backward-looking trigger.  The trigger fires
    if:

      1. It matches,
      2. It is not inside a pseudo-negation phrase,
      3. There is no termination term between the trigger end and the
         end of pre_text (where the target span begins).
    """
    target_pos = len(pre_text)
    for pat in patterns:
        for m in pat.finditer(pre_text):
            if _inside_pseudo_negation(pre_text, m.start(), m.end()):
                continue
            term = _earliest_termination(pre_text, m.end(), target_pos)
            if term is not None:
                # A termination word cancels this particular trigger hit.
                continue
            return True
    return False


def _post_trigger_fires(
    post_text: str,
    patterns: list[re.Pattern[str]],
) -> bool:
    """
    Scan *post_text* (text AFTER the target span) for any forward-looking
    trigger.  Termination terms between the span end (position 0 of
    post_text) and the trigger cancel the hit.
    """
    for pat in patterns:
        for m in pat.finditer(post_text):
            if _inside_pseudo_negation(post_text, m.start(), m.end()):
                continue
            term = _earliest_termination(post_text, 0, m.start())
            if term is not None:
                continue
            return True
    return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_context(text: str, span_start: int, span_end: int) -> ContextResult:
    """
    Classify the concept at ``text[span_start:span_end]`` along the five
    ConText axes.

    Parameters
    ----------
    text:
        The full clinical text.  May be multiline.
    span_start, span_end:
        Character offsets of the candidate concept.  ``span_end`` is
        exclusive (Python slice convention).

    Returns
    -------
    ContextResult
        Booleans for negated / uncertain / historical / hypothetical /
        family, plus an ``experiencer`` label ("patient" | "family").

    Notes
    -----
    * The function only looks at a window of ``WINDOW_BEFORE`` chars
      before and ``WINDOW_AFTER`` chars after the span, truncated at the
      nearest newline to avoid leaking context across unrelated
      sentences.
    * Pure function — no I/O, no globals mutated.  Safe to call in
      tight loops.
    """
    if not text or span_start < 0 or span_end <= span_start:
        return ContextResult(
            negated=False, uncertain=False, historical=False,
            hypothetical=False, family=False, experiencer="patient",
        )

    # Window bounds.
    win_start = max(0, span_start - WINDOW_BEFORE)
    win_end = min(len(text), span_end + WINDOW_AFTER)

    # Tighten at sentence / line boundaries so context does not bleed.
    pre_raw = text[win_start:span_start]
    post_raw = text[span_end:win_end]

    # Use the LAST newline or sentence terminator in pre_raw as the real
    # window start; anything before it belongs to a different sentence.
    last_break = max(
        pre_raw.rfind("\n"),
        pre_raw.rfind(". "),
        pre_raw.rfind("! "),
        pre_raw.rfind("? "),
    )
    if last_break >= 0:
        pre_raw = pre_raw[last_break + 1:]

    # Similarly, cut post_raw at the first newline or sentence terminator.
    first_break = min(
        (p for p in (
            post_raw.find("\n"),
            post_raw.find(". "),
            post_raw.find("! "),
            post_raw.find("? "),
        ) if p >= 0),
        default=-1,
    )
    if first_break >= 0:
        post_raw = post_raw[:first_break]

    family = _pre_trigger_fires(pre_raw, _FAMILY_REGEX)
    negated = (
        _pre_trigger_fires(pre_raw, _NEG_PRE_REGEX)
        or _post_trigger_fires(post_raw, _NEG_POST_REGEX)
    )
    uncertain = _pre_trigger_fires(pre_raw, _UNCERTAIN_REGEX)
    historical = _pre_trigger_fires(pre_raw, _HISTORICAL_REGEX)
    hypothetical = _pre_trigger_fires(pre_raw, _HYPOTHETICAL_REGEX)

    experiencer = "family" if family else "patient"

    return ContextResult(
        negated=negated,
        uncertain=uncertain,
        historical=historical,
        hypothetical=hypothetical,
        family=family,
        experiencer=experiencer,
    )
