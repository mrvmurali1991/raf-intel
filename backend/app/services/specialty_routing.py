"""
specialty_routing.py
====================

Specialty-aware routing for HCC suspect cards (the "ForeSee" pattern).

The clinical reality is that an HCC suspect is only actionable for a clinician
whose specialty owns the underlying organ system. A nephrologist reviewing a
patient should see CKD / kidney-related suspects (HCC 138, 326, 327) bubbled to
the top; a cardiologist should see heart-related suspects (HCC 84-88) first;
and so on. Surfacing every HCC equally to every specialty buries the relevant
opportunities and creates documentation fatigue.

This module is the single source of truth that maps an HCC code to a canonical
specialty bucket. The mapping is intentionally hard-coded for the top ~30
HCCs (which cover the bulk of recapture revenue) — anything outside the table
falls through to ``"general"`` so the UI still has something to render.

Public surface
--------------
specialty_for_hcc(hcc_code: int) -> str
    Return the canonical specialty bucket for the given V28 HCC code.

SPECIALTY_BUCKETS
    Immutable tuple listing all valid bucket names — used by the frontend
    filter-chip row so the two sides agree on the vocabulary.
"""

from __future__ import annotations

from typing import Final


# Canonical specialty bucket names. Anything that isn't in this tuple is not
# a valid return value of :func:`specialty_for_hcc`. The frontend filter row
# enumerates the same set.
SPECIALTY_BUCKETS: Final[tuple[str, ...]] = (
    "cardiology",
    "nephrology",
    "endocrinology",
    "pulmonology",
    "oncology",
    "behavioral",
    "general",
)


# Hard-coded routing table for the top ~30 V28 HCCs. Keep this table compact
# and reviewable — every entry is a clinical decision, not a database lookup.
#
# Endocrinology — diabetes spectrum (HCC 17-19 = DM w/ complications;
#                  HCC 35-38 = thyroid / metabolic disorders).
# Cardiology    — CHF / MI / AMI / ischaemic heart family (HCC 84-88).
# Nephrology    — CKD stages, ESRD, dialysis status (HCC 138, 326, 327).
# Pulmonology   — COPD / asthma / chronic respiratory failure (HCC 111-112).
# Oncology      — solid + haematological malignancies (HCC 7-12).
# Behavioral    — schizophrenia / major affective / substance use (HCC 51-55).
_HCC_TO_SPECIALTY: Final[dict[int, str]] = {
    # Endocrinology
    17: "endocrinology",
    18: "endocrinology",
    19: "endocrinology",
    35: "endocrinology",
    36: "endocrinology",
    37: "endocrinology",
    38: "endocrinology",
    # Cardiology
    84: "cardiology",
    85: "cardiology",
    86: "cardiology",
    87: "cardiology",
    88: "cardiology",
    # Nephrology
    138: "nephrology",
    326: "nephrology",
    327: "nephrology",
    # Pulmonology
    111: "pulmonology",
    112: "pulmonology",
    # Oncology
    7: "oncology",
    8: "oncology",
    9: "oncology",
    10: "oncology",
    11: "oncology",
    12: "oncology",
    # Behavioral health
    51: "behavioral",
    52: "behavioral",
    53: "behavioral",
    54: "behavioral",
    55: "behavioral",
}


def specialty_for_hcc(hcc_code: int) -> str:
    """Return the canonical specialty bucket for *hcc_code*.

    Parameters
    ----------
    hcc_code:
        Numeric V28 HCC code (e.g. ``138`` for CKD Stage 4). Pass ``0`` or any
        unmapped value to receive ``"general"``.

    Returns
    -------
    str
        One of :data:`SPECIALTY_BUCKETS`. Always falls through to
        ``"general"`` rather than raising — the routing table is
        intentionally permissive so the UI never has to handle an
        ``UnknownSpecialty`` error path.
    """
    try:
        key = int(hcc_code)
    except (TypeError, ValueError):
        return "general"
    return _HCC_TO_SPECIALTY.get(key, "general")
