"""Two-pass LLM HCC candidate extractor.

PASS 1 (blind): note text -> list[BlindCandidate]
PASS 2 (contextual): note + PatientContextBundle + Pass1 -> list[HCCCandidate]

Uses Vertex AI via llm_generate() from
backend/app/services/llm/vertex_client.py (owned by Agent 1).
Consumes PatientContextBundle from Agent 4.
"""
from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Vertex client import (Agent 1). Fall back to stub if not yet present so that
# this module is importable and unit-testable in isolation.
# ---------------------------------------------------------------------------
try:
    # TODO: confirm final symbol name once Agent 1 lands vertex_client.py.
    from app.services.llm.vertex_client import llm_generate  # type: ignore
except Exception:  # pragma: no cover - exercised when Agent 1 not yet merged
    log.warning(
        "vertex_client.llm_generate not found; using stub. "
        "Agent 1 must land backend/app/services/llm/vertex_client.py."
    )

    def llm_generate(  # type: ignore[no-redef]
        prompt: str,
        *,
        model: str = "gemini-2.5-pro",
        temperature: float = 0.1,
        max_output_tokens: int = 4096,
        **_: Any,
    ) -> str:
        raise RuntimeError(
            "llm_generate stub invoked; Vertex client not available."
        )


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
@dataclass
class BlindCandidate:
    icd10_guess: str
    condition_text: str
    evidence_span_start: int
    evidence_span_end: int
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MEATStatus:
    monitor: bool = False
    evaluate: bool = False
    assess: bool = False
    treat: bool = False

    @property
    def any(self) -> bool:
        return self.monitor or self.evaluate or self.assess or self.treat

    def to_dict(self) -> dict[str, bool]:
        return asdict(self)


@dataclass
class HCCCandidate:
    icd10: str
    hcc: str
    meat_status: MEATStatus
    recapture_vs_new: str  # "recapture" | "new"
    confidence: float
    evidence_span: str
    rationale: str

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["meat_status"] = self.meat_status.to_dict()
        return d


# ---------------------------------------------------------------------------
# Prompt loading
# ---------------------------------------------------------------------------
_PROMPT_DIR = Path(__file__).parent / "prompts"


def _load_prompt(name: str) -> str:
    return (_PROMPT_DIR / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Prompt-injection guard
# ---------------------------------------------------------------------------
_INJECTION_PATTERNS = [
    re.compile(r"(?i)ignore (all |the )?(previous|prior|above) (instructions|prompt|rules)"),
    re.compile(r"(?i)disregard (all |the )?(previous|prior|above) (instructions|prompt|rules)"),
    re.compile(r"(?i)forget (all |the )?(previous|prior|above) (instructions|prompt|rules)"),
    re.compile(r"(?i)you are now [^\n.]{0,80}"),
    re.compile(r"(?i)system\s*:\s*"),
    re.compile(r"(?i)</?\s*(system|assistant|user)\s*>"),
    re.compile(r"<<<\s*(NOTE|BUNDLE|BLIND)_(START|END)\s*>>>"),
]


def sanitize_note(text: str) -> str:
    """Neutralize prompt-injection attempts embedded in clinical text.

    Replaces matches with a bracketed [redacted] marker rather than deleting,
    so span offsets roughly survive and coders can see something was filtered.
    """
    if not text:
        return ""
    cleaned = text
    for pat in _INJECTION_PATTERNS:
        cleaned = pat.sub("[redacted-directive]", cleaned)
    return cleaned


# ---------------------------------------------------------------------------
# Robust JSON parsing
# ---------------------------------------------------------------------------
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", re.DOTALL)


def _parse_json_lenient(raw: str) -> Any:
    """Try hard to pull a JSON object out of an LLM response."""
    if raw is None:
        raise ValueError("empty LLM response")
    s = raw.strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    m = _JSON_FENCE_RE.search(s)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    # Fall back: slice between first '{' and last '}'.
    start = s.find("{")
    end = s.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(s[start : end + 1])
        except json.JSONDecodeError:
            pass
    raise ValueError(f"Could not parse JSON from LLM output: {raw[:240]!r}")


def _generate_json(
    prompt: str,
    *,
    model: str,
    temperature: float = 0.1,
    max_retries: int = 2,
    _llm: Callable[..., str] | None = None,
) -> Any:
    """Call the LLM and parse JSON, retrying once with a repair nudge."""
    fn = _llm or llm_generate
    last_err: Exception | None = None
    raw: str = ""
    for attempt in range(max_retries + 1):
        current_prompt = prompt
        if attempt > 0:
            current_prompt = (
                prompt
                + "\n\nYour previous response was not valid JSON:\n"
                + raw[:800]
                + "\n\nReturn ONLY valid JSON matching the schema. No prose, no fences."
            )
        raw = fn(current_prompt, model=model, temperature=temperature)
        try:
            return _parse_json_lenient(raw)
        except Exception as e:
            last_err = e
            log.warning("LLM JSON parse failed (attempt %d): %s", attempt + 1, e)
    raise ValueError(f"LLM returned unparseable JSON after {max_retries + 1} attempts: {last_err}")


# ---------------------------------------------------------------------------
# Pass 1: blind extraction
# ---------------------------------------------------------------------------
BLIND_MODEL = "gemini-2.0-flash"
CONTEXTUAL_MODEL = "gemini-2.5-pro"


def extract_blind(
    note_text: str,
    *,
    _llm: Callable[..., str] | None = None,
) -> list[BlindCandidate]:
    """Pass 1: extract candidate conditions from the note with no context."""
    if not note_text or not note_text.strip():
        return []
    safe = sanitize_note(note_text)
    template = _load_prompt("extract_blind.md")
    prompt = template.replace("{note_text}", safe)
    data = _generate_json(prompt, model=BLIND_MODEL, temperature=0.1, _llm=_llm)

    raw_list = data.get("candidates", []) if isinstance(data, dict) else []
    out: list[BlindCandidate] = []
    for item in raw_list:
        try:
            out.append(
                BlindCandidate(
                    icd10_guess=str(item.get("icd10_guess", "")).strip(),
                    condition_text=str(item.get("condition_text", "")).strip(),
                    evidence_span_start=int(item.get("evidence_span_start", 0) or 0),
                    evidence_span_end=int(item.get("evidence_span_end", 0) or 0),
                    confidence=float(item.get("confidence", 0.0) or 0.0),
                )
            )
        except Exception as e:
            log.warning("Skipping malformed blind candidate %r: %s", item, e)
    return out


# ---------------------------------------------------------------------------
# Pass 2: contextual extraction
# ---------------------------------------------------------------------------
def _bundle_to_jsonable(bundle: Any) -> Any:
    """Best-effort coercion of Agent 4's PatientContextBundle to JSON.

    Supports: dict, pydantic BaseModel (v1 or v2), dataclass, or any object
    with .to_dict() / .dict() / .model_dump().
    """
    if bundle is None:
        return {}
    if isinstance(bundle, dict):
        return bundle
    for attr in ("model_dump", "dict", "to_dict"):
        fn = getattr(bundle, attr, None)
        if callable(fn):
            try:
                return fn()
            except (TypeError, ValueError, AttributeError):  # noqa: BLE001
                continue
    try:
        return asdict(bundle)  # dataclass
    except TypeError:  # noqa: BLE001 — not a dataclass; fall through
        pass
    # Last resort: shallow __dict__.
    return getattr(bundle, "__dict__", {}) or {}


def extract_contextual(
    note_text: str,
    bundle: Any,
    blind_candidates: list[BlindCandidate],
    *,
    _llm: Callable[..., str] | None = None,
) -> list[HCCCandidate]:
    """Pass 2: using note + PatientContextBundle + blind candidates, decide
    MEAT compliance and recapture-vs-new for each candidate."""
    if not note_text or not note_text.strip():
        return []
    safe_note = sanitize_note(note_text)
    bundle_json = json.dumps(_bundle_to_jsonable(bundle), default=str, ensure_ascii=False)
    blind_json = json.dumps(
        [c.to_dict() for c in (blind_candidates or [])], ensure_ascii=False
    )

    template = _load_prompt("extract_contextual.md")
    prompt = (
        template.replace("{bundle_json}", bundle_json)
        .replace("{blind_json}", blind_json)
        .replace("{note_text}", safe_note)
    )
    data = _generate_json(prompt, model=CONTEXTUAL_MODEL, temperature=0.1, _llm=_llm)

    raw_list = data.get("candidates", []) if isinstance(data, dict) else []
    out: list[HCCCandidate] = []
    for item in raw_list:
        try:
            meat_raw = item.get("meat_status", {}) or {}
            meat = MEATStatus(
                monitor=bool(meat_raw.get("monitor", False)),
                evaluate=bool(meat_raw.get("evaluate", False)),
                assess=bool(meat_raw.get("assess", False)),
                treat=bool(meat_raw.get("treat", False)),
            )
            recap = str(item.get("recapture_vs_new", "new")).strip().lower()
            if recap not in ("recapture", "new"):
                recap = "new"
            out.append(
                HCCCandidate(
                    icd10=str(item.get("icd10", "")).strip(),
                    hcc=str(item.get("hcc", "")).strip(),
                    meat_status=meat,
                    recapture_vs_new=recap,
                    confidence=float(item.get("confidence", 0.0) or 0.0),
                    evidence_span=str(item.get("evidence_span", "")),
                    rationale=str(item.get("rationale", ""))[:240],
                )
            )
        except Exception as e:
            log.warning("Skipping malformed contextual candidate %r: %s", item, e)
    return out
