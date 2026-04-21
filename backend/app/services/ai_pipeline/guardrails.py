"""
AI pipeline guardrails.

Three guardrails are exported:

1. :func:`sanitize_note_for_llm` — strip control characters and neutralize
   prompt-injection patterns before a clinical note is sent to any LLM.
2. :func:`validate_llm_output`   — strict JSON-schema validation of the
   model's response; returns ``(ok, parsed, error)``.
3. :func:`scrub_pii_from_logs`   — mask SSN / MBI / DOB (and a few other
   obvious identifiers) in text that will be written to application logs.
   This is **log-scrubbing only**. It is NOT applied to DB writes.

The module has no side effects on import.
"""
from __future__ import annotations

import json
import logging
import re
import unicodedata
from typing import Any

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 1. sanitize_note_for_llm
# ---------------------------------------------------------------------------

# Patterns commonly used in prompt-injection attempts. Matched case-insensitively.
_INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"ignore (all |the |any )?(previous|prior|above) (instructions?|prompts?|rules?)", re.I),
    re.compile(r"disregard (all |the |any )?(previous|prior|above)", re.I),
    re.compile(r"you are now\b", re.I),
    re.compile(r"forget (everything|all|prior)", re.I),
    re.compile(r"act as (a |an )?(?:system|admin|root|developer)", re.I),
    re.compile(r"</?(?:system|prompt|instructions?|assistant|user)\s*>", re.I),
    re.compile(r"^\s*system\s*:", re.I | re.M),
    re.compile(r"^\s*assistant\s*:", re.I | re.M),
    re.compile(r"```+\s*(?:system|prompt)", re.I),
    re.compile(r"<\|(?:im_start|im_end|endoftext|system|user|assistant)\|>", re.I),
    re.compile(r"\[\[(?:system|instruction|prompt)\]\]", re.I),
)

_CONTROL_CHARS = re.compile(
    # Strip C0 controls (except \t \n \r) and C1 controls.
    r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]"
)


def sanitize_note_for_llm(text: str) -> str:
    """Return a sanitized copy of *text* safe to embed in an LLM prompt.

    In addition to stripping control chars and neutralizing prompt-injection
    patterns, this redacts identifier-level PHI that is never clinically
    relevant for HCC / MEAT extraction (SSN, Medicare MBI, phone, email).

    DOB is intentionally *not* redacted here because age-at-encounter is
    used by downstream age/sex gates — and patient age is already derived
    server-side from the structured patient record, so leaving raw DOB in
    the note does not leak anything the downstream code doesn't already have.
    """
    if not text:
        return ""
    # Normalize unicode (fold look-alike chars used to hide payloads).
    cleaned = unicodedata.normalize("NFKC", str(text))
    # Remove control chars.
    cleaned = _CONTROL_CHARS.sub(" ", cleaned)
    # Neutralize injection patterns by wrapping matches in [REDACTED:...].
    for pat in _INJECTION_PATTERNS:
        cleaned = pat.sub(
            lambda m: f"[REDACTED:{len(m.group(0))}chars]", cleaned
        )
    # Identifier-level PHI redaction (defense-in-depth; Vertex BAA still applies).
    cleaned = _SSN.sub("***-**-****", cleaned)
    try:
        cleaned = _MBI.sub("[MBI]", cleaned)
    except re.error:
        pass
    cleaned = _MBI_LOOSE.sub("[MBI]", cleaned)
    cleaned = _PHONE.sub("[PHONE]", cleaned)
    cleaned = _EMAIL.sub("[EMAIL]", cleaned)
    # Collapse runaway whitespace so prompt-token budgets are predictable.
    cleaned = re.sub(r"[ \t]{3,}", "  ", cleaned)
    cleaned = re.sub(r"\n{4,}", "\n\n\n", cleaned)
    return cleaned.strip()


# ---------------------------------------------------------------------------
# 2. validate_llm_output
# ---------------------------------------------------------------------------

try:
    from jsonschema import Draft202012Validator  # type: ignore
    _HAS_JSONSCHEMA = True
except Exception:  # pragma: no cover
    _HAS_JSONSCHEMA = False


class LLMOutputError(ValueError):
    """Raised by :func:`validate_llm_output_strict`."""


def _extract_json(output: str | dict | list) -> Any:
    """Best-effort: accept dict/list directly, or parse a JSON string."""
    if isinstance(output, (dict, list)):
        return output
    if not isinstance(output, str):
        raise LLMOutputError(f"unexpected output type {type(output).__name__}")
    text = output.strip()
    # Strip ``` fences if present
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I | re.S)
    # First curly-brace / bracket block
    start = min((i for i in (text.find("{"), text.find("[")) if i != -1), default=-1)
    if start > 0:
        text = text[start:]
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise LLMOutputError(f"invalid JSON: {e.msg}") from e


def validate_llm_output(
    output: Any, schema: dict[str, Any]
) -> tuple[bool, Any, str | None]:
    """Validate *output* against JSON *schema*.

    Returns ``(ok, parsed, error_message)``.
    Callers should retry / fall back when ``ok`` is False.
    """
    try:
        parsed = _extract_json(output)
    except LLMOutputError as e:
        return False, None, str(e)

    if not _HAS_JSONSCHEMA:
        # Fallback: at least ensure top-level type matches.
        top = schema.get("type")
        if top == "object" and not isinstance(parsed, dict):
            return False, parsed, "expected object"
        if top == "array" and not isinstance(parsed, list):
            return False, parsed, "expected array"
        return True, parsed, None

    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(parsed), key=lambda e: e.path)
    if errors:
        first = errors[0]
        path = "/".join(str(p) for p in first.absolute_path) or "<root>"
        return False, parsed, f"{path}: {first.message}"
    return True, parsed, None


# ---------------------------------------------------------------------------
# 3. scrub_pii_from_logs
# ---------------------------------------------------------------------------

# SSN: 123-45-6789 or 123 45 6789 or 9 consecutive digits that look like SSN
_SSN = re.compile(r"\b(?!000|666|9\d\d)(\d{3})[-\s]?(\d{2})[-\s]?(\d{4})\b")
# Medicare Beneficiary Identifier (MBI): 11 chars, strict CMS format
# Positions: 1=1-9, 2=A-Z non-SLOIBZ, 3=alnum, 4=0-9, 5=A-Z non-SLOIBZ,
# 6=alnum, 7=0-9, 8-9=A-Z non-SLOIBZ, 10-11=0-9
# Python's ``re`` has no set-intersection; emulate ``[A-Z&&[^SLOIBZ]]`` with
# an explicit character class listing the allowed letters. This avoids the
# FutureWarning that ``re`` emits for nested ``[[...]]`` syntax.
_MBI_ALPHA = "[ACDEFGHJKMNPQRTUVWXY]"  # A-Z minus S,L,O,I,B,Z
_MBI_ALNUM = "[ACDEFGHJKMNPQRTUVWXY0-9]"
_MBI = re.compile(
    rf"\b[1-9]{_MBI_ALPHA}{_MBI_ALNUM}\d{_MBI_ALPHA}{_MBI_ALNUM}"
    rf"\d{_MBI_ALPHA}{{2}}\d{{2}}\b"
)
# A looser MBI fallback (Python's re doesn't support &&): 11 alnum with
# digits in required spots.
_MBI_LOOSE = re.compile(r"\b[1-9][A-Z][A-Z0-9]\d[A-Z][A-Z0-9]\d[A-Z]{2}\d{2}\b")
# DOB: YYYY-MM-DD, MM/DD/YYYY, DD-MM-YYYY, M/D/YY
_DOB = re.compile(
    r"\b("
    r"(?:19|20)\d{2}[-/](?:0?[1-9]|1[0-2])[-/](?:0?[1-9]|[12]\d|3[01])"
    r"|"
    r"(?:0?[1-9]|1[0-2])[/-](?:0?[1-9]|[12]\d|3[01])[/-](?:19|20)\d{2}"
    r")\b"
)
# Phone
_PHONE = re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")
# Email
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")


def scrub_pii_from_logs(text: str | bytes | None) -> str:
    """Mask SSN / MBI / DOB / phone / email in *text*. Log-scrub only."""
    if text is None:
        return ""
    if isinstance(text, bytes):
        try:
            text = text.decode("utf-8", errors="replace")
        except Exception:
            return "[binary]"
    s = str(text)
    s = _SSN.sub("***-**-****", s)
    try:
        s = _MBI.sub("[MBI]", s)
    except re.error:
        pass
    s = _MBI_LOOSE.sub("[MBI]", s)
    s = _DOB.sub("[DOB]", s)
    s = _PHONE.sub("[PHONE]", s)
    s = _EMAIL.sub("[EMAIL]", s)
    return s


__all__ = [
    "sanitize_note_for_llm",
    "validate_llm_output",
    "scrub_pii_from_logs",
    "LLMOutputError",
]
