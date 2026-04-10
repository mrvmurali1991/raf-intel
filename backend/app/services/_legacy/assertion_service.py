"""
Clinical Assertion & Negation Detection Service.

Detects whether medical conditions mentioned in clinical text are:
- PRESENT  (confirmed diagnosis)
- ABSENT   (negated — "denies", "no evidence of")
- POSSIBLE (uncertain — "may have", "rule out")
- HISTORICAL (past — "history of", "previous")
- FAMILY   (family history — "family history of", "mother had")

Uses HuggingFace bvanaken/clinical-assertion-negation-bert if available,
falls back to a comprehensive rule-based NegEx-style algorithm.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Trigger phrase lists
# ---------------------------------------------------------------------------

PRE_NEGATION_TRIGGERS: list[str] = [
    # Direct negation
    "no", "not", "never", "neither", "nor", "none",
    "without", "absence of", "absent", "lacking",
    # Verb-based denial
    "denies", "denied", "denying", "deny",
    "refuses", "refused", "declining", "declined",
    # Evidential negation
    "negative for", "negative",
    "no evidence of", "no sign of", "no signs of",
    "no symptoms of", "no complaints of",
    "no history of", "no significant", "no known",
    "no acute", "no active", "no new",
    "no definite", "no obvious", "no clear",
    "unremarkable for", "free of",
    # Rule-out phrases
    "rules out", "rule out", "ruled out", "r/o",
    "to rule out", "to exclude",
    # Uncertainty-to-absence
    "unlikely", "not consistent with",
    # Grammatical negation
    "not demonstrate", "fails to reveal", "fails to show",
    "did not", "does not", "do not", "don't", "didn't", "doesn't",
    "has not", "have not", "had not", "hasn't", "haven't", "hadn't",
    "was not", "were not", "wasn't", "weren't",
    "is not", "are not", "isn't", "aren't",
    "cannot", "can't", "could not", "couldn't",
    "will not", "won't", "would not", "wouldn't",
    "should not", "shouldn't",
    # Temporal resolution
    "no longer", "resolved", "resolving", "gone", "cleared",
    "stopped", "discontinued", "discontinued",
    # Procedure context
    "with no", "without any", "without evidence of",
    "no associated", "not associated",
    "no report of", "not reported",
    "not elicited", "not appreciated",
    "not detected", "not visualized",
    "not seen", "not identified", "not found",
    "not present", "not demonstrated", "not observed",
    "not consistent", "not suggestive",
]

POST_NEGATION_TRIGGERS: list[str] = [
    "absent", "negative", "denied",
    "unlikely", "not present",
    "was ruled out", "has been ruled out", "were ruled out",
    "was negative", "were negative", "is negative", "are negative",
    "not found", "not seen", "not present", "not demonstrated",
    "not identified", "not observed", "not detected",
    "not appreciated", "not elicited", "not noted",
    "not reported", "not visualized",
    "has resolved", "have resolved", "resolved",
    "was resolved", "were resolved",
    "has cleared", "have cleared",
    "not confirmed", "unconfirmed",
    "not established",
]

POSSIBLE_TRIGGERS: list[str] = [
    "possible", "possibly",
    "probable", "probably",
    "may have", "might have", "could have",
    "may be", "might be", "could be",
    "suspected", "suspect", "suspicion of",
    "suspicious for", "suspicious of",
    "concerning for", "concern for",
    "suggestive of", "suggests",
    "consistent with",
    "cannot exclude", "cannot rule out",
    "can't exclude", "can't rule out",
    "could not exclude", "could not rule out",
    "questionable", "question of",
    "differential", "in the differential",
    "consider", "consideration of",
    "evaluate for", "evaluation for",
    "appears to", "seems to",
    "likely", "most likely",
    "presumed", "presumptive",
    "working diagnosis",
    "to be determined",
    "uncertain", "equivocal",
    "cannot be excluded",
    "potentially", "potential",
    "possible etiology",
    "rule out" ,  # also possible in some contexts — handled by priority order
]

HISTORICAL_TRIGGERS: list[str] = [
    "history of", "h/o", "hx of", "hx:",
    "previous", "previously",
    "prior", "prior history of",
    "past medical history", "pmh:", "pmh",
    "past history", "past surgical history",
    "former", "formerly",
    "in the past", "years ago", "months ago",
    "remote history", "remote history of",
    "childhood", "childhood history",
    "status post", "s/p",
    "post-operative", "post operative",
    "post", "after",
    "had a", "had an",
    "underwent",
    "treated for",
    "diagnosed with",  # ambiguous — treated as historical when followed by past tense context
    "recovered from",
    "survived",
    "previous episode of",
    "recurrent",
]

FAMILY_TRIGGERS: list[str] = [
    "family history", "family history of",
    "fh:", "fhx:", "fhx",
    "familial", "familial history of",
    "hereditary",
    "runs in the family", "runs in family",
    "family member",
    "father had", "father has", "father with",
    "mother had", "mother has", "mother with",
    "brother had", "brother has",
    "sister had", "sister has",
    "sibling had", "siblings had",
    "son had", "daughter had",
    "grandfather had", "grandmother had",
    "grandparent had", "grandparents had",
    "parent had", "parents had",
    "maternal", "paternal",
    "maternal history", "paternal history",
    "maternal grandfather", "maternal grandmother",
    "paternal grandfather", "paternal grandmother",
    "first-degree relative", "first degree relative",
]

# ---------------------------------------------------------------------------
# Scope terminators — negation/modifier stops at these
# ---------------------------------------------------------------------------

SCOPE_TERMINATORS = re.compile(
    r"\b(but|however|although|except|apart from|other than|"
    r"yet|still|nevertheless|nonetheless|notwithstanding|"
    r"in contrast|on the other hand|conversely|"
    r"and|or|which|who|where|while|whereas)\b",
    re.IGNORECASE,
)

PUNCTUATION_TERMINATOR = re.compile(r"[.!?;:]")

# Tokens that always terminate a negation scope even mid-phrase
HARD_TERMINATORS: set[str] = {
    "but", "however", "although", "except", "yet", "still",
    "nevertheless", "nonetheless",
}

# Window (in words) to look before/after entity for triggers
NEGATION_WINDOW = 8

# ---------------------------------------------------------------------------
# HuggingFace model (lazy-loaded)
# ---------------------------------------------------------------------------

_hf_pipeline: Any | None = None
_hf_available: bool | None = None  # None = not yet tried


def _load_hf_model() -> Any | None:
    """
    Attempt to load the bvanaken/clinical-assertion-negation-bert pipeline.
    Returns the pipeline on success, None on failure (model not cached / no
    network / transformers not installed).
    """
    global _hf_pipeline, _hf_available

    if _hf_available is False:
        return None
    if _hf_pipeline is not None:
        return _hf_pipeline

    try:
        from transformers import pipeline  # type: ignore[import-untyped]

        import os
        _base = os.path.dirname(__file__)
        local_model = None
        for rel in [
            os.path.join(_base, "..", "..", "..", "models", "assertion-bert"),
            os.path.join(_base, "..", "..", "models", "assertion-bert"),
            "/Users/murali/Documents/Projects/raf-intelligence/models/assertion-bert",
        ]:
            if os.path.exists(os.path.abspath(rel)):
                local_model = os.path.abspath(rel)
                break
        model_path = local_model or "bvanaken/clinical-assertion-negation-bert"
        logger.info("Loading assertion-negation-bert from %s…", "LOCAL" if local_model else "HuggingFace")
        _hf_pipeline = pipeline(
            "text-classification",
            model=model_path,
            tokenizer=model_path,
        )
        _hf_available = True
        logger.info("HuggingFace assertion model loaded successfully.")
        return _hf_pipeline
    except Exception as exc:
        logger.info(
            "HuggingFace model unavailable (%s). Using rule-based NegEx.", exc
        )
        _hf_available = False
        return None


# ---------------------------------------------------------------------------
# Label normalisation for HF model output
# ---------------------------------------------------------------------------

_HF_LABEL_MAP: dict[str, str] = {
    # bvanaken model outputs these labels
    "AFFIRMED": "present",
    "NEGATED": "absent",
    "POSSIBLE": "possible",
    # fallback
    "PRESENT": "present",
    "ABSENT": "absent",
    "HISTORICAL": "historical",
    "FAMILY": "family",
}


# ---------------------------------------------------------------------------
# Rule-based NegEx implementation
# ---------------------------------------------------------------------------

def _normalise_text(text: str) -> str:
    """Lower-case and collapse whitespace."""
    return re.sub(r"\s+", " ", text.lower().strip())


def _find_entity_position(text_lower: str, entity_lower: str) -> int:
    """
    Find the character start position of entity_lower in text_lower.
    Returns -1 if not found.  Prefers exact word-boundary match.
    """
    pattern = re.compile(r"\b" + re.escape(entity_lower) + r"\b")
    m = pattern.search(text_lower)
    if m:
        return m.start()
    # Fallback: plain substring
    idx = text_lower.find(entity_lower)
    return idx


def _truncate_at_scope_terminator(phrase: str) -> str:
    """
    Given a phrase (pre or post context), truncate it at the first
    scope-terminating conjunction or punctuation mark so that negation
    from the far side of a conjunction is ignored.
    """
    # Punctuation first
    m = PUNCTUATION_TERMINATOR.search(phrase)
    if m:
        phrase = phrase[: m.start()]

    # Hard conjunction terminators
    m = SCOPE_TERMINATORS.search(phrase)
    if m:
        phrase = phrase[: m.start()]

    return phrase.strip()


def _tokenize(phrase: str) -> list[str]:
    return phrase.split()


def _match_triggers(
    tokens: list[str],
    triggers: list[str],
    window: int,
    from_end: bool = False,
) -> str | None:
    """
    Check whether any trigger from *triggers* appears in *tokens*.

    When from_end=False  we look at the LAST *window* tokens (pre-entity context).
    When from_end=True   we look at the FIRST *window* tokens (post-entity context).

    Returns the matched trigger phrase, or None.
    """
    if from_end:
        window_tokens = tokens[:window]
    else:
        window_tokens = tokens[-window:]

    window_str = " ".join(window_tokens)

    # Sort triggers longest-first so multi-word phrases match before sub-words
    for trigger in sorted(triggers, key=len, reverse=True):
        if re.search(r"\b" + re.escape(trigger) + r"\b", window_str):
            return trigger

    return None


def _rule_based_assertion(
    text: str, entity_text: str, entity_start: int = -1
) -> dict[str, Any]:
    """
    Core rule-based NegEx algorithm.

    Algorithm:
    1. Locate entity in text.
    2. Scope pre-context: text before entity, truncated at scope terminators.
    3. Scope post-context: text after entity, truncated at scope terminators.
    4. Check trigger lists in priority order:
       FAMILY > HISTORICAL > NEGATION (pre) > NEGATION (post) > POSSIBLE > PRESENT
    5. Return assertion dict.
    """
    text_lower = _normalise_text(text)
    entity_lower = _normalise_text(entity_text)

    # Resolve entity position
    if entity_start < 0:
        entity_start = _find_entity_position(text_lower, entity_lower)

    if entity_start < 0:
        # Entity not found in text — default to present
        return {
            "assertion": "present",
            "confidence": 0.5,
            "trigger": None,
            "negated": False,
        }

    entity_end = entity_start + len(entity_lower)

    pre_raw = text_lower[:entity_start]
    post_raw = text_lower[entity_end:]

    # Truncate each side at scope boundaries
    pre_context = _truncate_at_scope_terminator(pre_raw)
    post_context = _truncate_at_scope_terminator(post_raw)

    pre_tokens = _tokenize(pre_context)
    post_tokens = _tokenize(post_context)

    # ------------------------------------------------------------------
    # Priority 1 — FAMILY (check both sides; family phrases often precede)
    # ------------------------------------------------------------------
    trigger = _match_triggers(pre_tokens, FAMILY_TRIGGERS, NEGATION_WINDOW)
    if trigger:
        return {"assertion": "family", "confidence": 0.90, "trigger": trigger, "negated": False}

    trigger = _match_triggers(post_tokens, FAMILY_TRIGGERS, NEGATION_WINDOW, from_end=True)
    if trigger:
        return {"assertion": "family", "confidence": 0.88, "trigger": trigger, "negated": False}

    # ------------------------------------------------------------------
    # Priority 2 — HISTORICAL
    # ------------------------------------------------------------------
    trigger = _match_triggers(pre_tokens, HISTORICAL_TRIGGERS, NEGATION_WINDOW)
    if trigger:
        return {"assertion": "historical", "confidence": 0.88, "trigger": trigger, "negated": False}

    # ------------------------------------------------------------------
    # Priority 3 — PRE-NEGATION
    # ------------------------------------------------------------------
    trigger = _match_triggers(pre_tokens, PRE_NEGATION_TRIGGERS, NEGATION_WINDOW)
    if trigger:
        return {"assertion": "absent", "confidence": 0.92, "trigger": trigger, "negated": True}

    # ------------------------------------------------------------------
    # Priority 4 — POST-NEGATION
    # ------------------------------------------------------------------
    trigger = _match_triggers(post_tokens, POST_NEGATION_TRIGGERS, NEGATION_WINDOW, from_end=True)
    if trigger:
        return {"assertion": "absent", "confidence": 0.88, "trigger": trigger, "negated": True}

    # ------------------------------------------------------------------
    # Priority 5 — POSSIBLE / UNCERTAIN
    # ------------------------------------------------------------------
    trigger = _match_triggers(pre_tokens, POSSIBLE_TRIGGERS, NEGATION_WINDOW)
    if trigger:
        return {"assertion": "possible", "confidence": 0.85, "trigger": trigger, "negated": False}

    trigger = _match_triggers(post_tokens, POSSIBLE_TRIGGERS, NEGATION_WINDOW, from_end=True)
    if trigger:
        return {"assertion": "possible", "confidence": 0.82, "trigger": trigger, "negated": False}

    # ------------------------------------------------------------------
    # Default — PRESENT
    # ------------------------------------------------------------------
    return {
        "assertion": "present",
        "confidence": 0.80,
        "trigger": None,
        "negated": False,
    }


# ---------------------------------------------------------------------------
# HuggingFace-based assertion (uses [entity] tagging convention)
# ---------------------------------------------------------------------------

def _hf_assertion(
    pipeline_fn: Any, text: str, entity_text: str
) -> dict[str, Any] | None:
    """
    Run the HuggingFace clinical assertion model.

    The bvanaken model expects the entity to be wrapped in square brackets,
    e.g. "Patient denies [chest pain]."

    Returns None on any error so the caller can fall back.
    """
    try:
        tagged_text = re.sub(
            r"\b" + re.escape(entity_text) + r"\b",
            f"[{entity_text}]",
            text,
            count=1,
            flags=re.IGNORECASE,
        )
        result = pipeline_fn(tagged_text, truncation=True, max_length=512)
        if not result:
            return None

        label_raw: str = result[0]["label"].upper()
        score: float = float(result[0]["score"])
        assertion = _HF_LABEL_MAP.get(label_raw, "present")

        return {
            "assertion": assertion,
            "confidence": round(score, 4),
            "trigger": f"hf:{label_raw}",
            "negated": assertion in ("absent", "family"),
        }
    except Exception as exc:
        logger.warning("HF assertion inference failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_assertion(
    text: str,
    entity_text: str,
    entity_start: int = -1,
) -> dict[str, Any]:
    """
    Detect assertion status for a medical entity within clinical text.

    Parameters
    ----------
    text:
        The clinical sentence or passage.
    entity_text:
        The medical entity string to evaluate (e.g. "diabetes mellitus").
    entity_start:
        Optional character offset of *entity_text* within *text*.
        Pass -1 (default) to auto-detect.

    Returns
    -------
    dict with keys:
        assertion  : "present" | "absent" | "possible" | "historical" | "family"
        confidence : float  0-1
        trigger    : str | None   — the phrase that drove the classification
        negated    : bool         — True only when assertion == "absent"
    """
    if not text or not entity_text:
        return {
            "assertion": "present",
            "confidence": 0.5,
            "trigger": None,
            "negated": False,
        }

    # Try HuggingFace model first
    pipeline_fn = _load_hf_model()
    if pipeline_fn is not None:
        hf_result = _hf_assertion(pipeline_fn, text, entity_text)
        if hf_result is not None:
            return hf_result

    # Fall back to rule-based NegEx
    return _rule_based_assertion(text, entity_text, entity_start)


def filter_negated_entities(
    entities: list[dict[str, Any]],
    clinical_note: str,
) -> list[dict[str, Any]]:
    """
    Annotate a list of extracted entities with assertion status and return
    only entities that are clinically PRESENT (active, confirmed).

    Parameters
    ----------
    entities:
        List of entity dicts.  Each dict must have at minimum:
            - "text"  : the entity string
        Optional keys used when present:
            - "start" : character offset in *clinical_note*
            - "sentence" : the sentence containing the entity (used in
                          preference to the full note for local context)
    clinical_note:
        The source clinical note text.

    Returns
    -------
    Filtered list of entity dicts, each augmented with an "assertion" key
    containing the full assertion result dict.  Entities with assertion
    "absent", "family", "historical", or "possible" are excluded.
    """
    present_entities: list[dict[str, Any]] = []

    # Batch all entity contexts for assertion detection
    entity_contexts = []
    for entity in entities:
        entity_text = entity.get("text", "")
        if not entity_text:
            continue

        # Get local context window around entity
        context = entity.get("sentence")
        if not context:
            ent_start = entity.get("start", -1)
            if ent_start >= 0 and len(clinical_note) > 1500:
                win_start = max(0, ent_start - 750)
                win_end = min(len(clinical_note), ent_start + len(entity_text) + 750)
                context = clinical_note[win_start:win_end]
            else:
                context = clinical_note

        entity_contexts.append((entity, context, entity_text))

    # Try batch HuggingFace assertion first
    pipeline_fn = _load_hf_model()
    if pipeline_fn is not None and entity_contexts:
        import re as _re
        tagged_texts = []
        for entity, context, entity_text in entity_contexts:
            tagged = _re.sub(
                r"\b" + _re.escape(entity_text) + r"\b",
                f"[{entity_text}]",
                context,
                count=1,
                flags=_re.IGNORECASE,
            )
            tagged_texts.append(tagged)

        try:
            batch_results = pipeline_fn(tagged_texts, truncation=True, max_length=512, batch_size=len(tagged_texts))
            for i, (entity, context, entity_text) in enumerate(entity_contexts):
                result = batch_results[i]
                label = result[0]["label"].upper() if isinstance(result, list) else result["label"].upper()
                score = float(result[0]["score"] if isinstance(result, list) else result["score"])
                assertion = _HF_LABEL_MAP.get(label, "present")
                assertion_result = {
                    "assertion": assertion,
                    "confidence": round(score, 4),
                    "trigger": f"hf_batch:{label}",
                    "negated": assertion in ("absent", "family"),
                }
                annotated = {**entity, "assertion": assertion_result}
                if assertion_result["assertion"] == "present":
                    present_entities.append(annotated)
                else:
                    logger.debug("Filtered entity '%s' — assertion=%s", entity_text, assertion)
            return present_entities
        except Exception as exc:
            logger.warning("Batch assertion failed, falling back to sequential: %s", exc)

    # Fallback: sequential processing (original logic)
    for entity, context, entity_text in entity_contexts:
        start = entity.get("start", -1) if not entity.get("sentence") else -1
        assertion_result = detect_assertion(context, entity_text, start)
        annotated = {**entity, "assertion": assertion_result}
        if assertion_result["assertion"] == "present":
            present_entities.append(annotated)
        else:
            logger.debug("Filtered entity '%s' — assertion=%s", entity_text, assertion_result["assertion"])

    return present_entities


def is_negated(text: str, entity_text: str) -> bool:
    """
    Simple boolean check: is this entity negated (or family history) in this text?

    Parameters
    ----------
    text:
        Clinical sentence or passage.
    entity_text:
        The medical entity to evaluate.

    Returns
    -------
    True if the entity's assertion is "absent" or "family", False otherwise.
    """
    result = detect_assertion(text, entity_text)
    return result["assertion"] in ("absent", "family")


# ---------------------------------------------------------------------------
# Convenience: batch assertion over sentences
# ---------------------------------------------------------------------------

def batch_detect_assertions(
    pairs: list[tuple[str, str]],
) -> list[dict[str, Any]]:
    """
    Run assertion detection over a list of (text, entity_text) tuples.

    Returns a list of assertion result dicts in the same order as *pairs*.
    """
    return [detect_assertion(text, entity) for text, entity in pairs]
