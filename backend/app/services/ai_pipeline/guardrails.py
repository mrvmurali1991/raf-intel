"""
AI pipeline guardrails.

Three guardrails are exported:

1. :func:`sanitize_note_for_llm` — strip control characters and neutralize
   prompt-injection patterns before a clinical note is sent to any LLM.
   Also redacts HIPAA Safe Harbor identifiers: SSN, MBI, phone, email,
   patient names (when supplied), DOB, street addresses, ZIP codes, and
   MRN-style identifiers.
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


def sanitize_note_for_llm(
    text: str,
    known_names: list[str] | None = None,
) -> str:
    """Return a sanitized copy of *text* safe to embed in an LLM prompt.

    In addition to stripping control chars and neutralizing prompt-injection
    patterns, this redacts HIPAA Safe Harbor identifiers (defence-in-depth;
    Vertex BAA still applies):

    * SSN, Medicare MBI
    * Phone, email
    * Patient names — when ``known_names`` is supplied (e.g.
      ``[patient.first_name, patient.last_name]``), each token is replaced
      with ``[NAME]``.  Matching is case-insensitive and word-boundary-aware;
      longer names are matched before shorter ones to avoid partial clobbers.
    * Dates-of-birth (static birthdates for people aged 18-100) replaced with
      ``[DOB]``.  Clinical dates such as procedure/encounter dates are NOT
      redacted — only patterns that carry a 4-digit birth year whose computed
      age falls within 18-100.
    * Street addresses replaced with ``[ADDRESS]``.
    * ZIP codes (standalone or following a state abbreviation) replaced with
      ``[ZIP]``.
    * MRN-style identifiers (6-12 digit numbers labelled with MRN /
      "Medical Record Number") replaced with ``[MRN]``.
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
    # --- HIPAA Safe Harbor identifier redaction ----------------------------
    # Apply labelled / structured identifiers FIRST so that the later
    # broad digit-sequence rules (SSN, phone) do not clobber them.

    # MBI — structured alpha-numeric; apply before SSN digit sweep
    try:
        cleaned = _MBI.sub("[MBI]", cleaned)
    except re.error:
        pass
    cleaned = _MBI_LOOSE.sub("[MBI]", cleaned)

    # MRN — labelled numeric; apply before SSN so the digits are gone
    cleaned = _MRN.sub(r"\1[MRN]", cleaned)

    # ZIP — apply before SSN so ZIP+4 (d{5}-d{4}) is not mis-matched as SSN
    cleaned = _ZIP_PREFIXED.sub(r"\1[ZIP]", cleaned)

    # DOB — apply before SSN so date separators don't confuse the SSN sweep
    cleaned = _redact_dob(cleaned)

    # SSN — broad digit pattern; runs after the more-specific rules above
    cleaned = _SSN.sub("***-**-****", cleaned)

    # Phone, email
    cleaned = _PHONE.sub("[PHONE]", cleaned)
    cleaned = _EMAIL.sub("[EMAIL]", cleaned)

    # Street addresses (no digit-collision risk, but keep near end for clarity)
    cleaned = _STREET_ADDRESS.sub("[ADDRESS]", cleaned)
    # Patient names — longest token first to avoid partial matches
    if known_names:
        # Filter to non-empty strings; sort longest first
        tokens = sorted(
            (n.strip() for n in known_names if n and n.strip()),
            key=len,
            reverse=True,
        )
        for token in tokens:
            if not token:
                continue
            pattern = re.compile(
                r"\b" + re.escape(token) + r"\b", re.IGNORECASE
            )
            cleaned = pattern.sub("[NAME]", cleaned)
    # Collapse runaway whitespace so prompt-token budgets are predictable.
    cleaned = re.sub(r"[ \t]{3,}", "  ", cleaned)
    cleaned = re.sub(r"\n{4,}", "\n\n\n", cleaned)
    return cleaned.strip()


# ---------------------------------------------------------------------------
# 1b. Additional HIPAA Safe Harbor patterns (used by sanitize_note_for_llm)
# ---------------------------------------------------------------------------

# MRN: 6-12 digit number preceded by "MRN", "MRN#", "Medical Record Number",
# or "Medical Record #".  We capture the label in group 1 so we can keep it
# in the replacement (readable context) and only blank the number itself.
_MRN = re.compile(
    r"(\bMRN\s*[:#]?\s*|\bMedical\s+Record(?:\s+Number)?\s*[:#]?\s*)"
    r"\d{6,12}\b",
    re.IGNORECASE,
)

# Street address: leading house number + street name + type abbreviation.
# Matches addresses like "123 Main Street", "45 N Oak Ave", "6 Elm Blvd Apt 2".
_STREET_ADDRESS = re.compile(
    r"\b\d{1,5}\s+"                          # house number
    r"(?:[NSEW]\s+)?"                         # optional cardinal direction
    r"[A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)?"  # street name (1-2 words)
    r"\s+"
    r"(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Ln|Drive|Dr"
    r"|Way|Place|Pl|Court|Ct|Circle|Cir|Terrace|Ter|Trail|Trl"
    r"|Highway|Hwy|Parkway|Pkwy)"             # street type
    r"(?:\s+(?:Apt|Suite|Ste|Unit|#)\s*[\w-]+)?"  # optional unit
    r"\b",
    re.IGNORECASE,
)

# ZIP: only redact when the 5-digit sequence is clearly a ZIP, not a lab value.
# Strategy: require it to follow a US state abbreviation (2 upper-case letters)
# or the literal words "ZIP" / "zip code" / "postal code", with optional comma
# and space between the state and the number.
_ZIP_PREFIXED = re.compile(
    r"(\b(?:[A-Z]{2}|ZIP(?:\s+code)?|zip(?:\s+code)?|postal\s+code)[,\s]+)"
    r"(\d{5}(?:-\d{4})?)\b",
)

# Months for text-format DOB (Jan-Dec, full or abbreviated)
_MONTHS = (
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?"
    r"|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
)

# Numeric DOB patterns:
#   ISO:        1962-01-15  or 1962/01/15
#   US slash:   01/15/1962  or 1/15/62  (4-digit year → strict; 2-digit → loose)
#   US dash:    01-15-1962
_DOB_ISO = re.compile(
    r"\b((?:19|20)\d{2})[-/](0?[1-9]|1[0-2])[-/](0?[1-9]|[12]\d|3[01])\b"
)
_DOB_US4 = re.compile(
    r"\b(0?[1-9]|1[0-2])[/-](0?[1-9]|[12]\d|3[01])[/-]((?:19|20)\d{2})\b"
)
_DOB_US2 = re.compile(
    r"\b(0?[1-9]|1[0-2])[/-](0?[1-9]|[12]\d|3[01])[/-](\d{2})\b"
)
# Text DOB: "Jan 15, 1962" / "January 15 1962" / "15 Jan 1962"
_DOB_TEXT_MDY = re.compile(
    rf"\b{_MONTHS}\s+(0?[1-9]|[12]\d|3[01]),?\s+((?:19|20)\d{{2}})\b",
    re.IGNORECASE,
)
_DOB_TEXT_DMY = re.compile(
    rf"\b(0?[1-9]|[12]\d|3[01])\s+{_MONTHS},?\s+((?:19|20)\d{{2}})\b",
    re.IGNORECASE,
)

import datetime as _dt

_CURRENT_YEAR = _dt.date.today().year


def _year_looks_like_dob(year_str: str) -> bool:
    """Return True if a 4-digit year string corresponds to age 18-100."""
    try:
        year = int(year_str)
    except (ValueError, TypeError):
        return False
    age = _CURRENT_YEAR - year
    return 18 <= age <= 100


def _year2_looks_like_dob(year2_str: str) -> bool:
    """Expand a 2-digit year and check age 18-100.

    Convention: 00-39 → 2000-2039, 40-99 → 1940-1999.
    """
    try:
        yy = int(year2_str)
    except (ValueError, TypeError):
        return False
    year = 2000 + yy if yy < 40 else 1900 + yy
    age = _CURRENT_YEAR - year
    return 18 <= age <= 100


def _redact_dob(text: str) -> str:
    """Replace date patterns that look like DOBs (age 18-100) with [DOB].

    Clinical encounter dates (recent years or future) are left untouched.
    """
    def _sub_iso(m: re.Match[str]) -> str:
        return "[DOB]" if _year_looks_like_dob(m.group(1)) else m.group(0)

    def _sub_us4(m: re.Match[str]) -> str:
        return "[DOB]" if _year_looks_like_dob(m.group(3)) else m.group(0)

    def _sub_us2(m: re.Match[str]) -> str:
        return "[DOB]" if _year2_looks_like_dob(m.group(3)) else m.group(0)

    def _sub_text_mdy(m: re.Match[str]) -> str:
        # Last group is the 4-digit year
        return "[DOB]" if _year_looks_like_dob(m.group(m.lastindex)) else m.group(0)

    def _sub_text_dmy(m: re.Match[str]) -> str:
        return "[DOB]" if _year_looks_like_dob(m.group(m.lastindex)) else m.group(0)

    text = _DOB_ISO.sub(_sub_iso, text)
    text = _DOB_US4.sub(_sub_us4, text)
    text = _DOB_US2.sub(_sub_us2, text)
    text = _DOB_TEXT_MDY.sub(_sub_text_mdy, text)
    text = _DOB_TEXT_DMY.sub(_sub_text_dmy, text)
    return text


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
        text = text.decode("utf-8", errors="replace")
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
