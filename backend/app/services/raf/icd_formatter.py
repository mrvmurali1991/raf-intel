# DISCLAIMER: This module is part of the CMS-HCC RAF calculation engine.
# Not CMS-validated. For informational purposes only.
"""ICD-10 code formatting, normalization, and ESRD indicator sets."""

from __future__ import annotations

# ---------------------------------------------------------------------------
# ICD-10 code formatting helpers
# ---------------------------------------------------------------------------


def _format_icd10(code: str) -> str:
    """Add dot to ICD-10 code if missing: 'E1165' -> 'E11.65'."""
    code = str(code).strip().upper()
    if "." in code or len(code) <= 3:
        return code
    return f"{code[:3]}.{code[3:]}"


# ---------------------------------------------------------------------------
# ICD-10 code sets that drive ESRD segment detection
# ---------------------------------------------------------------------------

# ICD-10 codes that indicate ESRD Functioning Graft status (post-transplant)
_ESRD_FUNCTIONING_GRAFT_CODES: frozenset[str] = frozenset(
    {
        "Z94.0",
        "Z940",  # Kidney transplant status
        "T86.10",
        "T8610",  # Kidney transplant rejection, unspecified
        "T86.11",
        "T8611",  # Kidney transplant rejection
        "T86.12",
        "T8612",  # Kidney transplant failure
        "T86.13",
        "T8613",  # Kidney transplant infection
        "T86.19",
        "T8619",  # Other kidney transplant complication
    }
)

# ICD-10 codes that indicate active ESRD Dialysis
_ESRD_DIALYSIS_CODES: frozenset[str] = frozenset(
    {
        "Z99.2",
        "Z992",  # Dependence on renal dialysis
        "N18.6",
        "N186",  # End stage renal disease
        "Z49.01",
        "Z4901",  # Encounter for fitting and adjustment of hemodialysis
        "Z49.02",
        "Z4902",  # Peritoneal dialysis
        "Z49.31",
        "Z4931",  # Encounter for adequacy testing for hemodialysis
        "Z49.32",
        "Z4932",  # Encounter for adequacy testing for peritoneal dialysis
    }
)
