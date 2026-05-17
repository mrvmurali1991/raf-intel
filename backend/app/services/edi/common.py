"""
Shared primitives for X12 5010 EDI generation.

This module is intentionally dependency-free (stdlib only) so the segment
builders are easy to unit-test in isolation.  Higher-level orchestration that
needs the database lives in `x12_837.py` / `x12_834.py`.

Delimiters
----------
We use the canonical X12 set:
    Segment terminator: ~
    Element separator:  *
    Sub-element sep.:   :
    Repetition sep.:    ^   (ISA11 in 5010)

ISA segment is fixed-width (per spec); other segments are variable-length and
terminated with ~.  Each segment is followed by a newline for human-readability;
the newline is NOT part of the segment per X12 — most parsers ignore it.
"""

from __future__ import annotations

import random
import re
from datetime import date, datetime, timezone
from typing import Iterable

SEG_TERM = "~"
ELEM_SEP = "*"
SUB_SEP = ":"
REPETITION_SEP = "^"
NEWLINE = "\n"


# ---------------------------------------------------------------------------
# Sanitisation
# ---------------------------------------------------------------------------

_BAD_CHAR_RE = re.compile(r"[*~:^\r\n]")


def clean(value: object, max_len: int | None = None) -> str:
    """Return X12-safe text: strip delimiters and trim to max_len.

    None/empty becomes "" — the caller is responsible for deciding whether
    an empty element is acceptable (X12 allows empty elements between *s).
    """
    if value is None:
        return ""
    s = str(value)
    s = _BAD_CHAR_RE.sub(" ", s).strip()
    if max_len is not None:
        s = s[:max_len]
    return s


def upper(value: object, max_len: int | None = None) -> str:
    return clean(value, max_len).upper()


def digits_only(value: object, max_len: int | None = None) -> str:
    if value is None:
        return ""
    s = re.sub(r"\D+", "", str(value))
    if max_len is not None:
        s = s[:max_len]
    return s


# ---------------------------------------------------------------------------
# Control numbers
# ---------------------------------------------------------------------------

def new_isa_control_number() -> str:
    """ISA13 — 9-digit numeric interchange control number."""
    return f"{random.randint(1, 999_999_999):09d}"


def new_gs_control_number() -> str:
    """GS06 — up to 9-digit functional group control number."""
    return f"{random.randint(1, 999_999_999):09d}"


def new_st_control_number(idx: int = 1) -> str:
    """ST02 — 4–9 digit transaction set control number."""
    return f"{idx:09d}"


# ---------------------------------------------------------------------------
# Date/time formatting helpers
# ---------------------------------------------------------------------------

def isa_date(d: datetime | date | None = None) -> str:
    """ISA09 — YYMMDD."""
    d = d or datetime.now(timezone.utc)
    return d.strftime("%y%m%d")


def isa_time(d: datetime | None = None) -> str:
    """ISA10 — HHMM."""
    d = d or datetime.now(timezone.utc)
    return d.strftime("%H%M")


def ccyymmdd(d: date | datetime | str | None) -> str:
    if d is None:
        return ""
    if isinstance(d, str):
        s = d.strip()[:10].replace("-", "")
        return s
    if isinstance(d, (datetime, date)):
        return d.strftime("%Y%m%d")
    return ""


def hhmm(d: datetime | None = None) -> str:
    d = d or datetime.now(timezone.utc)
    return d.strftime("%H%M")


# ---------------------------------------------------------------------------
# Segment builder
# ---------------------------------------------------------------------------

def segment(tag: str, *elements: object) -> str:
    """Build a variable-length segment.

    Trailing empty elements are stripped (per X12 best-practice — minimises
    line length while remaining spec-compliant).  Empty elements *between*
    non-empty elements are preserved.
    """
    parts: list[str] = []
    for e in elements:
        if e is None:
            parts.append("")
        elif isinstance(e, (list, tuple)):
            # composite (sub-element) element
            parts.append(SUB_SEP.join(clean(x) for x in e))
        else:
            parts.append(clean(e))
    while parts and parts[-1] == "":
        parts.pop()
    body = ELEM_SEP.join([tag, *parts]) if parts else tag
    return body + SEG_TERM


# ---------------------------------------------------------------------------
# ISA / IEA — interchange envelope (fixed-width!)
# ---------------------------------------------------------------------------

def isa_segment(
    *,
    sender_id: str,
    receiver_id: str,
    control_number: str,
    test_indicator: str = "T",   # "T" = test, "P" = production
    sender_qualifier: str = "ZZ",
    receiver_qualifier: str = "ZZ",
    interchange_date: datetime | date | None = None,
) -> str:
    """ISA — Interchange Control Header.  5010 mandates 16 elements.

    Every element is fixed-width per the spec.  Failing to pad correctly is
    the #1 cause of clearinghouse rejection.
    """
    sender = clean(sender_id, 15).ljust(15)
    receiver = clean(receiver_id, 15).ljust(15)
    elements = [
        "00",                                 # ISA01 authorization qualifier
        " " * 10,                             # ISA02 authorization info
        "00",                                 # ISA03 security qualifier
        " " * 10,                             # ISA04 security info
        clean(sender_qualifier, 2).ljust(2),  # ISA05
        sender,                               # ISA06
        clean(receiver_qualifier, 2).ljust(2),# ISA07
        receiver,                             # ISA08
        isa_date(interchange_date),           # ISA09
        isa_time(interchange_date) if isinstance(interchange_date, datetime) else isa_time(),
        REPETITION_SEP,                       # ISA11 repetition separator (5010)
        "00501",                              # ISA12 interchange control version
        control_number.zfill(9)[:9],          # ISA13 control number
        "0",                                  # ISA14 ack requested
        clean(test_indicator, 1),             # ISA15
        SUB_SEP,                              # ISA16 component element sep
    ]
    return "ISA" + ELEM_SEP + ELEM_SEP.join(elements) + SEG_TERM


def iea_segment(*, num_functional_groups: int, control_number: str) -> str:
    return segment("IEA", str(num_functional_groups), control_number.zfill(9)[:9])


# ---------------------------------------------------------------------------
# GS / GE — functional group envelope
# ---------------------------------------------------------------------------

_GS_FUNCTIONAL_ID = {
    "837": "HC",   # Health Care Claim
    "834": "BE",   # Benefit Enrollment
}


def gs_segment(
    *,
    transaction: str,           # "837" or "834"
    sender_code: str,
    receiver_code: str,
    control_number: str,
    transaction_date: date | datetime | None = None,
    version: str = "005010X222A1",
) -> str:
    """GS — Functional Group Header.

    GS08 must match the implementation guide identifier:
        005010X222A1 — 837 Professional
        005010X220A1 — 834 Benefit Enrollment
    """
    fn = _GS_FUNCTIONAL_ID.get(transaction)
    if not fn:
        raise ValueError(f"Unsupported transaction for GS: {transaction!r}")
    d = transaction_date or datetime.now(timezone.utc)
    return segment(
        "GS",
        fn,
        clean(sender_code, 15),
        clean(receiver_code, 15),
        ccyymmdd(d),
        hhmm(d if isinstance(d, datetime) else None),
        control_number.lstrip("0") or "1",
        "X",                # GS07 responsible agency
        version,
    )


def ge_segment(*, num_transactions: int, control_number: str) -> str:
    return segment("GE", str(num_transactions), control_number.lstrip("0") or "1")


# ---------------------------------------------------------------------------
# ST / SE — transaction set envelope
# ---------------------------------------------------------------------------

_ST_IMPL_GUIDE = {
    "837": "005010X222A1",
    "834": "005010X220A1",
}


def st_segment(*, transaction: str, control_number: str) -> str:
    impl = _ST_IMPL_GUIDE.get(transaction)
    if not impl:
        raise ValueError(f"Unsupported transaction for ST: {transaction!r}")
    return segment("ST", transaction, control_number.zfill(4), impl)


def se_segment(*, segment_count: int, control_number: str) -> str:
    """SE — Transaction Set Trailer.  segment_count includes both ST and SE."""
    return segment("SE", str(segment_count), control_number.zfill(4))


# ---------------------------------------------------------------------------
# ICD-10 validation
# ---------------------------------------------------------------------------

_ICD10_RE = re.compile(r"^[A-TV-Z][0-9][A-Z0-9](\.?[A-Z0-9]{0,4})?$", re.I)


def normalize_icd10(code: str) -> str:
    """Return ICD-10 code without dot, upper-cased.

    Empty or malformed input returns "" so callers can filter.
    """
    if not code:
        return ""
    c = re.sub(r"[\s.]+", "", str(code)).upper()
    if not _ICD10_RE.match(code.strip().upper()):
        # be lenient — still emit if it's reasonably shaped
        if not re.fullmatch(r"[A-Z][0-9A-Z]{1,6}", c):
            return ""
    return c


# ---------------------------------------------------------------------------
# File assembly
# ---------------------------------------------------------------------------

def join_segments(segments: Iterable[str], *, newlines: bool = True) -> str:
    """Concatenate segments — preserves their trailing ~ and optionally
    inserts newlines between them for readability."""
    sep = NEWLINE if newlines else ""
    return sep.join(s.rstrip(NEWLINE) for s in segments) + (NEWLINE if newlines else "")


def count_segments(text: str) -> int:
    """Count segments in an X12 text blob — used to populate SE01."""
    return text.count(SEG_TERM)
