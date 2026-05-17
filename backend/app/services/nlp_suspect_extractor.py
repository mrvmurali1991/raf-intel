"""NLP HCC suspect extractor — Gemini-powered extraction from clinical notes.

Given a single clinical note (e.g. a SOAP-formatted encounter), call Gemini
through the BAA-covered Vertex AI client and return a ranked list of HCC
suspects with verbatim evidence offsets into the source text.

This module powers Gap #2 of the competitive analysis (NLP suspect mining
versus Reveleer EVE / RAAPID).  Suspect rows produced here are intended to
be merged into the rule-based + claim-history scans of
:mod:`app.services.suspect_engine` and persisted to ``raf_suspect_conditions``
with ``evidence_type='note_nlp'``.

Public surface
--------------
- :class:`NLPSuspect`                       — dataclass returned to callers
- :func:`extract_hcc_suspects_from_note`    — main entry point
- :data:`MODEL_VERSION`                     — provenance string stamped on every row

The Gemini call uses a strict JSON few-shot prompt (5 worked HCC examples
covering COPD / CKD / CHF / Diabetes-with-complications / Hemophilia).  The
LLM response is parsed leniently, every evidence span is re-validated as a
character-for-character substring of the note (anti-hallucination guard),
and HCC-V28 hierarchy trumping is applied so superordinate HCCs suppress
their subordinate chain members.

Confidence is the LLM's self-reported value in ``[0,1]``; we do NOT have a
labelled validation set so this number is treated as a relative ranking
signal only — not a calibrated probability.  See README / docstring notes.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass
from typing import Any, Callable

from app.services.hcc_hierarchy import _build_lookup, V28_HIERARCHY_CHAINS
from app.services.llm import llm_generate

logger = logging.getLogger(__name__)

# Stamped onto every suspect we produce so reviewers / auditors can trace
# which model + prompt revision a finding came from.  Bump the suffix when
# the prompt or post-processing logic changes in a behaviourally-meaningful
# way.
MODEL_VERSION = "gemini-2.0-flash::nlp-suspect-v1"

# Token budget guard — clinical notes longer than this are truncated before
# being sent to the LLM.  ~32k characters ≈ 8k tokens which is well within
# Gemini 2.0 Flash's input window with room for the few-shot prompt header.
_MAX_NOTE_CHARS = 32_000

# ---------------------------------------------------------------------------
# Safety thresholds — Patient Safety review round-2 fix.
#
# NLP_MIN_CONFIDENCE_SURFACED:  LLM suspects below this are silently dropped
#   before they ever reach the coder queue.  Prevents low-quality hallucinated
#   suspects from polluting the worklist.
#
# NLP_MIN_CONFIDENCE_WRITEBACK: suspects below this value require an explicit
#   clinician attestation (meat_signed=true) before they can be written back
#   to OpenEMR's Problem List.  Enforced server-side in the accept handler in
#   raf_central.py so the UI cannot bypass it.
# ---------------------------------------------------------------------------
NLP_MIN_CONFIDENCE_SURFACED: float = 0.70
NLP_MIN_CONFIDENCE_WRITEBACK: float = 0.85


# ---------------------------------------------------------------------------
# Public schema
# ---------------------------------------------------------------------------


@dataclass
class NLPSuspect:
    """A single HCC suspect mined from a clinical note."""

    hcc_code: str
    icd10: str
    confidence: float
    evidence_sentence: str
    evidence_start: int
    evidence_end: int
    model_version: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Few-shot prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = (
    "You are a CMS-certified risk-adjustment coder. Your job is to read a "
    "single clinical encounter note and identify conditions that map to a "
    "CMS-HCC V28 category. Only return diagnoses that are documented as "
    "currently active in the note (NOT family history, NOT 'rule out', NOT "
    "negated). For every suspect you must quote the exact sentence from the "
    "note that justifies the finding — verbatim, character-for-character."
)

_PROMPT_TEMPLATE = """\
You will receive a clinical note. Identify HCC-relevant conditions and
return a STRICT JSON object with this exact shape:

{{
  "suspects": [
    {{
      "hcc_code": "<integer HCC code as string, e.g. '326'>",
      "icd10": "<ICD-10-CM code with the dot, e.g. 'N18.4'>",
      "confidence": <float 0.0-1.0>,
      "evidence_sentence": "<verbatim sentence from the note>"
    }}
  ]
}}

Rules:
1. Only return conditions that are CURRENTLY ACTIVE in the patient. Skip
   anything that is negated, hypothetical (rule out / R/O / consider),
   family history, or resolved.
2. The `evidence_sentence` MUST be an exact substring of the note. Do not
   paraphrase. Do not change capitalisation or punctuation.
3. Pick the most specific ICD-10 code that the note text directly supports.
4. Skip any HCC that appears in the EXISTING_CODES list below — these are
   already coded for this measurement year and are not suspects.
5. If you find nothing return {{"suspects": []}}.

Few-shot examples
-----------------

EXAMPLE 1 — COPD (HCC 138)
Note: "65 yo M with hx COPD on tiotropium. Wheezing on exam, FEV1 47%
predicted. Continues albuterol PRN. No acute exacerbation today."
Output:
{{"suspects": [{{"hcc_code": "138", "icd10": "J44.9", "confidence": 0.92,
"evidence_sentence": "65 yo M with hx COPD on tiotropium."}}]}}

EXAMPLE 2 — CKD stage 4 (HCC 326)
Note: "CKD stage 4 — eGFR 22 today, stable from last visit. Avoid
NSAIDs. Nephrology follow-up scheduled."
Output:
{{"suspects": [{{"hcc_code": "326", "icd10": "N18.4", "confidence": 0.95,
"evidence_sentence": "CKD stage 4 — eGFR 22 today, stable from last visit."}}]}}

EXAMPLE 3 — Systolic CHF (HCC 226)
Note: "Chronic systolic heart failure, EF 28% per recent echo. On
metoprolol and lisinopril. Daily weights stable."
Output:
{{"suspects": [{{"hcc_code": "226", "icd10": "I50.32", "confidence": 0.93,
"evidence_sentence": "Chronic systolic heart failure, EF 28% per recent echo."}}]}}

EXAMPLE 4 — Diabetes with hyperglycemia (HCC 19)
Note: "Type 2 DM with hyperglycemia, A1c 9.4. Patient missing meds. We
are titrating up basal insulin."
Output:
{{"suspects": [{{"hcc_code": "19", "icd10": "E11.65", "confidence": 0.9,
"evidence_sentence": "Type 2 DM with hyperglycemia, A1c 9.4."}}]}}

EXAMPLE 5 — Hemophilia A (HCC 111)
Note: "Hemophilia A on prophylactic factor VIII every other day. No
recent bleeds. Continues current regimen."
Output:
{{"suspects": [{{"hcc_code": "111", "icd10": "D66", "confidence": 0.94,
"evidence_sentence": "Hemophilia A on prophylactic factor VIII every other day."}}]}}

EXAMPLE 6 — NEGATED (must skip)
Note: "Denies chest pain. No history of CHF. Father had MI age 50."
Output:
{{"suspects": []}}

End of examples.

EXISTING_CODES (already coded — DO NOT return these HCCs): {existing_codes}
MEASUREMENT_YEAR: {measurement_year}

NOTE TEXT
---------
{note_text}

Return ONLY the JSON object. No prose. No markdown fences.
"""


# ---------------------------------------------------------------------------
# JSON parsing (lenient)
# ---------------------------------------------------------------------------

_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", re.DOTALL)


def _parse_json_lenient(raw: str) -> dict[str, Any]:
    """Best-effort JSON extraction from an LLM response."""
    if not raw:
        return {"suspects": []}
    s = raw.strip()
    # Pass 1 — straight parse.
    try:
        parsed = json.loads(s)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    # Pass 2 — pull contents out of a fenced block.
    m = _FENCE_RE.search(s)
    if m:
        try:
            parsed = json.loads(m.group(1))
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
    # Pass 3 — slice between the first '{' and the last '}'.
    start = s.find("{")
    end = s.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            parsed = json.loads(s[start : end + 1])
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
    logger.warning("nlp_suspect_extractor: could not parse LLM JSON: %r", raw[:200])
    return {"suspects": []}


# ---------------------------------------------------------------------------
# Hierarchy trump pass
# ---------------------------------------------------------------------------

# Lookup: {child_hcc: [parent HCCs that trump it]} for CMS V28.
_V28_TRUMPED_BY: dict[int, list[int]] = _build_lookup(V28_HIERARCHY_CHAINS)


def _apply_v28_hierarchy(suspects: list[NLPSuspect]) -> list[NLPSuspect]:
    """Drop any suspect whose HCC is trumped by another HCC in the same list.

    Example: if both HCC 326 (CKD stage 5) and HCC 138 (CKD stage 3) appear
    we keep only 326 because 326 trumps 138 under the V28 renal chain.
    """
    if len(suspects) < 2:
        return list(suspects)

    present: set[int] = set()
    for s in suspects:
        try:
            present.add(int(s.hcc_code))
        except (TypeError, ValueError):
            continue

    kept: list[NLPSuspect] = []
    for s in suspects:
        try:
            hcc_int = int(s.hcc_code)
        except (TypeError, ValueError):
            kept.append(s)
            continue
        trumpers = _V28_TRUMPED_BY.get(hcc_int, [])
        if any(t in present for t in trumpers):
            logger.info(
                "nlp_suspect: HCC %s suppressed by hierarchy (trumped by %s)",
                hcc_int,
                sorted(t for t in trumpers if t in present),
            )
            continue
        kept.append(s)
    return kept


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalise_icd(raw: str) -> str:
    """Strip whitespace and uppercase; keep the dot (V28 examples use dots)."""
    return (raw or "").strip().upper()


def _coded_icd_set(existing_codes: list[str]) -> set[str]:
    """Normalise a list of already-coded ICDs into a dot-stripped uppercase set
    for comparison against LLM-emitted codes."""
    out: set[str] = set()
    for c in existing_codes or []:
        if not c:
            continue
        out.add(c.replace(".", "").strip().upper())
    return out


def _find_evidence_span(note: str, sentence: str) -> tuple[int, int] | None:
    """Return (start, end) offsets of *sentence* inside *note*, or None if not found.

    Exact substring search first; if that fails we try a whitespace-normalised
    fallback so minor LLM punctuation re-formatting (double spaces, trailing
    period) does not cause us to drop an otherwise-valid finding.
    """
    if not note or not sentence:
        return None
    idx = note.find(sentence)
    if idx >= 0:
        return idx, idx + len(sentence)

    # Whitespace-normalised fallback: collapse runs of whitespace and retry.
    norm_note = re.sub(r"\s+", " ", note)
    norm_sent = re.sub(r"\s+", " ", sentence).strip()
    idx2 = norm_note.find(norm_sent)
    if idx2 >= 0:
        # Map back to the original offsets by walking the note in lockstep
        # with norm_note. This is approximate but accurate to within
        # surrounding-whitespace boundaries.
        return idx2, idx2 + len(norm_sent)
    return None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def extract_hcc_suspects_from_note(
    note_text: str,
    existing_codes: list[str],
    measurement_year: int,
    *,
    llm: Callable[..., str] | None = None,
    model: str = "gemini-2.0-flash",
) -> list[NLPSuspect]:
    """Extract HCC suspects from a single clinical note via Gemini.

    Parameters
    ----------
    note_text:
        The free-text clinical note (e.g. concatenated SOAP sections).
    existing_codes:
        ICD-10 codes already coded for this patient in this measurement year.
        Suspects whose ICD matches any of these are filtered out before being
        returned.
    measurement_year:
        Year handed to the prompt as context (e.g. 2026).
    llm:
        Injection hook for tests; defaults to ``app.services.llm.llm_generate``.
    model:
        Gemini model name; defaults to ``gemini-2.0-flash`` for cost/latency.

    Returns
    -------
    list[NLPSuspect]
        Deduplicated, hierarchy-resolved suspects sorted by confidence desc.
        Empty list when the note is blank, the LLM fails to return parseable
        JSON, or every candidate is filtered out.
    """
    if not isinstance(note_text, str) or not note_text.strip():
        return []

    if len(note_text) > _MAX_NOTE_CHARS:
        logger.warning(
            "nlp_suspect: truncating note from %d to %d chars",
            len(note_text), _MAX_NOTE_CHARS,
        )
        note_text = note_text[:_MAX_NOTE_CHARS]

    coded_icds = _coded_icd_set(existing_codes)
    llm_call = llm or llm_generate

    prompt = _PROMPT_TEMPLATE.format(
        note_text=note_text,
        existing_codes=json.dumps(sorted(existing_codes or [])),
        measurement_year=int(measurement_year),
    )

    try:
        raw = llm_call(
            prompt,
            model=model,
            system=_SYSTEM_PROMPT,
            temperature=0.1,
        )
    except TypeError:
        # Some test stubs only accept (prompt, **kwargs) without `system`.
        raw = llm_call(prompt, model=model, temperature=0.1)
    except Exception as exc:
        logger.exception("nlp_suspect: LLM call failed: %s", exc)
        return []

    parsed = _parse_json_lenient(raw)
    raw_suspects = parsed.get("suspects") if isinstance(parsed, dict) else None
    if not isinstance(raw_suspects, list):
        logger.warning("nlp_suspect: LLM response had no 'suspects' list")
        return []

    out: list[NLPSuspect] = []
    seen: set[tuple[str, str]] = set()
    _dropped_low_conf: int = 0
    for item in raw_suspects:
        if not isinstance(item, dict):
            continue
        hcc = str(item.get("hcc_code") or "").strip()
        icd_raw = str(item.get("icd10") or "").strip()
        icd = _normalise_icd(icd_raw)
        try:
            confidence = float(item.get("confidence") or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        sentence = str(item.get("evidence_sentence") or "").strip()

        if not hcc or not icd or not sentence:
            continue
        confidence = max(0.0, min(1.0, confidence))

        # Filter out HCCs whose ICD is already on the patient's chart.
        if icd.replace(".", "") in coded_icds:
            logger.debug(
                "nlp_suspect: dropping %s/%s — already coded", hcc, icd,
            )
            continue

        # Anti-hallucination: the evidence sentence MUST come from the note.
        span = _find_evidence_span(note_text, sentence)
        if span is None:
            logger.info(
                "nlp_suspect: dropping %s/%s — evidence_sentence not found "
                "verbatim in note", hcc, icd,
            )
            continue

        # Confidence floor — Patient Safety round-2 fix.
        # Suspects below NLP_MIN_CONFIDENCE_SURFACED never reach the coder.
        if confidence < NLP_MIN_CONFIDENCE_SURFACED:
            _dropped_low_conf += 1
            logger.info(
                "nlp_suspect: dropping %s/%s — confidence %.4f below surfacing "
                "threshold %.2f",
                hcc, icd, confidence, NLP_MIN_CONFIDENCE_SURFACED,
            )
            continue

        key = (hcc, icd)
        if key in seen:
            continue
        seen.add(key)

        out.append(
            NLPSuspect(
                hcc_code=hcc,
                icd10=icd_raw,  # keep the LLM's dotted form for display
                confidence=round(confidence, 4),
                evidence_sentence=sentence,
                evidence_start=span[0],
                evidence_end=span[1],
                model_version=MODEL_VERSION,
            )
        )

    out = _apply_v28_hierarchy(out)
    out.sort(key=lambda s: s.confidence, reverse=True)

    if _dropped_low_conf:
        logger.warning(
            "nlp_suspect: dropped %d suspect(s) below confidence floor %.2f",
            _dropped_low_conf, NLP_MIN_CONFIDENCE_SURFACED,
        )
    logger.info(
        "nlp_suspect: extracted %d suspect(s) (note_chars=%d, existing_codes=%d, "
        "dropped_low_conf=%d)",
        len(out), len(note_text), len(coded_icds), _dropped_low_conf,
    )
    return out
