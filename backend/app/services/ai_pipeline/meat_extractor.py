"""MEAT-evidence extractor.

Given an ``HCCCandidate`` and the source clinical note, this module asks
Gemini 2.5 Pro to return verbatim quotes that document Monitoring,
Evaluation, Assessment, or Treatment (MEAT) for the candidate during a
face-to-face encounter.  Every quote the LLM returns is re-validated as a
character-for-character substring of the note; hallucinated quotes trigger
a single retry with a stricter reminder, then are dropped.

Public surface
--------------
- :class:`MEATEvidence`               — schema of the extractor output.
- :func:`validate_quote_in_source`    — verbatim-quote validator.
- :func:`extract_meat_evidence`       — main entry point.

The encounter-type gate uses the context bundle: telephone, lab-only,
administrative, and similar non-face-to-face encounters are rejected
without calling the LLM.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from app.config import settings
from app.services.llm import llm_generate

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).parent / "prompts" / "meat_extract.md"
# Model name read from settings; override via LLM_MODEL_MEAT env var.
_MODEL: str = settings.llm_model_meat

# ---------------------------------------------------------------------------
# Face-to-face gate
# ---------------------------------------------------------------------------

# Lower-cased substrings that disqualify an encounter from RADV MEAT use.
_NON_F2F_TOKENS: tuple[str, ...] = (
    "telephone",
    "phone",
    "lab only",
    "lab-only",
    "laboratory",
    "radiology only",
    "administrative",
    "admin",
    "email",
    "portal message",
    "message",
    "refill",
    "letter",
    "nurse only",
)

# Lower-cased substrings that explicitly qualify an encounter.
_F2F_TOKENS: tuple[str, ...] = (
    "office visit",
    "office",
    "outpatient",
    "in-person",
    "in person",
    "clinic",
    "home visit",
    "telehealth video",
    "video visit",
    "audio-video",
    "audio+video",
    "annual wellness",
    "awv",
    "preventive",
    "hospital outpatient",
)


def is_face_to_face_encounter(encounter_type: str | None) -> bool:
    """Return True iff ``encounter_type`` denotes a face-to-face visit."""
    if not encounter_type:
        return False
    et = encounter_type.strip().lower()
    if not et:
        return False
    for tok in _NON_F2F_TOKENS:
        if tok in et:
            return False
    for tok in _F2F_TOKENS:
        if tok in et:
            return True
    # Unknown type: default to False to be RADV-safe.
    return False


# ---------------------------------------------------------------------------
# Verbatim-quote validator
# ---------------------------------------------------------------------------

_WS_RE = re.compile(r"\s+")


def _normalise_ws(s: str) -> str:
    return _WS_RE.sub(" ", s).strip()


def validate_quote_in_source(quote: str | None, note: str) -> bool:
    """Return True iff ``quote`` is a verbatim substring of ``note``.

    An exact match is preferred.  Because LLMs often normalise internal
    whitespace (e.g. collapsing newlines to single spaces), the check
    falls back to a whitespace-normalised comparison.  Anything else —
    paraphrasing, truncation of content characters, typo correction —
    fails validation.
    """
    if not quote or not isinstance(quote, str):
        return False
    q = quote.strip()
    if not q:
        return False
    if q in note:
        return True
    return _normalise_ws(q) in _normalise_ws(note)


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


@dataclass
class MEATEvidence:
    """Structured MEAT-evidence record for a single HCC candidate."""

    m_quote: str | None = None
    e_quote: str | None = None
    a_quote: str | None = None
    t_quote: str | None = None
    encounter_date: str | None = None
    is_face_to_face: bool = False
    overall_valid: bool = False
    reason_if_invalid: str | None = None
    dropped_quotes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def any_meat(self) -> bool:
        return any([self.m_quote, self.e_quote, self.a_quote, self.t_quote])


# ---------------------------------------------------------------------------
# Prompt + LLM plumbing
# ---------------------------------------------------------------------------


def _load_prompt_template() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


def _render_prompt(
    candidate: Any,
    note: str,
    encounter_type: str | None,
    encounter_date: str | None,
    extra_reminder: str | None = None,
) -> str:
    tmpl = _load_prompt_template()
    icd10 = getattr(candidate, "icd10", None) or getattr(candidate, "code", "")
    description = getattr(candidate, "description", "") or ""
    hcc = getattr(candidate, "hcc", "") or getattr(candidate, "hcc_code", "")
    rendered = (
        tmpl.replace("{icd10}", str(icd10))
        .replace("{description}", str(description))
        .replace("{hcc}", str(hcc))
        .replace("{encounter_type}", str(encounter_type or "unknown"))
        .replace("{encounter_date}", str(encounter_date or "unknown"))
        .replace("{note}", note)
    )
    if extra_reminder:
        rendered = f"{rendered}\n\nIMPORTANT: {extra_reminder}\n"
    return rendered


_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


def _parse_json(text: str) -> dict[str, Any]:
    if not text:
        raise ValueError("empty LLM response")
    stripped = text.strip()
    # Strip ```json fences if present.
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.lower().startswith("json"):
            stripped = stripped[4:]
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        m = _JSON_BLOCK_RE.search(stripped)
        if not m:
            raise
        return json.loads(m.group(0))


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def extract_meat_evidence(
    candidate: Any,
    note: str,
    context: Mapping[str, Any] | None = None,
    *,
    model: str = _MODEL,
    llm: Any = None,
) -> MEATEvidence:
    """Extract MEAT evidence for ``candidate`` from ``note``.

    Parameters
    ----------
    candidate:
        An ``HCCCandidate``-like object exposing ``icd10`` /
        ``description`` / ``hcc`` attributes.
    note:
        Raw clinical-note text that the LLM must quote verbatim.
    context:
        Optional context bundle; read ``encounter_type`` and
        ``encounter_date`` from it.
    model:
        Gemini model name (default ``gemini-2.5-pro``).
    llm:
        Optional callable with the same signature as
        :func:`app.services.llm.llm_generate` — injected in tests.
    """
    if not isinstance(note, str) or not note.strip():
        return MEATEvidence(
            is_face_to_face=False,
            overall_valid=False,
            reason_if_invalid="empty note",
        )

    ctx = dict(context or {})
    encounter_type = ctx.get("encounter_type") or ctx.get("encounterType")
    encounter_date = ctx.get("encounter_date") or ctx.get("encounterDate")

    f2f = is_face_to_face_encounter(encounter_type)
    if not f2f:
        return MEATEvidence(
            encounter_date=encounter_date,
            is_face_to_face=False,
            overall_valid=False,
            reason_if_invalid=(
                f"encounter_type '{encounter_type}' is not face-to-face"
            ),
        )

    llm_call = llm or llm_generate

    prompt = _render_prompt(candidate, note, encounter_type, encounter_date)
    parsed: dict[str, Any] = {}
    last_err: str | None = None
    for attempt in range(2):
        try:
            raw = llm_call(prompt, model=model, temperature=0.0)
            parsed = _parse_json(raw)
            break
        except Exception as exc:  # pragma: no cover — network path
            last_err = str(exc)
            logger.warning("MEAT LLM parse failed (attempt %d): %s", attempt + 1, exc)
            prompt = _render_prompt(
                candidate,
                note,
                encounter_type,
                encounter_date,
                extra_reminder=(
                    "Return ONLY a valid JSON object matching the schema. "
                    "No markdown, no commentary."
                ),
            )
    else:
        return MEATEvidence(
            encounter_date=encounter_date,
            is_face_to_face=True,
            overall_valid=False,
            reason_if_invalid=f"LLM error: {last_err}",
        )

    # Validate every quote against the note.  Any non-verbatim quote is
    # dropped and recorded in dropped_quotes.
    dropped: list[str] = []
    clean: dict[str, str | None] = {}
    for key in ("m_quote", "e_quote", "a_quote", "t_quote"):
        val = parsed.get(key)
        if val in (None, "", "null"):
            clean[key] = None
            continue
        if validate_quote_in_source(val, note):
            clean[key] = val
        else:
            dropped.append(f"{key}:{val}")
            clean[key] = None
            logger.info("Dropping non-verbatim MEAT quote for %s", key)

    # If everything was dropped, try one retry with a stricter reminder.
    if dropped and not any(clean.values()):
        retry_prompt = _render_prompt(
            candidate,
            note,
            encounter_type,
            encounter_date,
            extra_reminder=(
                "Your previous quotes were not exact substrings of the note. "
                "Return quotes that appear character-for-character in the "
                "clinical note. If none exist, return null for that field."
            ),
        )
        try:
            raw = llm_call(retry_prompt, model=model, temperature=0.0)
            parsed2 = _parse_json(raw)
            for key in ("m_quote", "e_quote", "a_quote", "t_quote"):
                val = parsed2.get(key)
                if val in (None, "", "null"):
                    continue
                if validate_quote_in_source(val, note):
                    clean[key] = val
                else:
                    dropped.append(f"retry:{key}:{val}")
        except Exception as exc:  # pragma: no cover
            logger.warning("MEAT retry failed: %s", exc)

    any_meat = any(clean.values())
    overall_valid = bool(any_meat and f2f)
    reason: str | None = None
    if not overall_valid:
        if not any_meat:
            reason = "no verbatim MEAT evidence found in note"
        elif not f2f:
            reason = "encounter is not face-to-face"

    return MEATEvidence(
        m_quote=clean["m_quote"],
        e_quote=clean["e_quote"],
        a_quote=clean["a_quote"],
        t_quote=clean["t_quote"],
        encounter_date=parsed.get("encounter_date") or encounter_date,
        is_face_to_face=f2f,
        overall_valid=overall_valid,
        reason_if_invalid=reason,
        dropped_quotes=dropped,
    )
