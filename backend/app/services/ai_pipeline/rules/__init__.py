"""Suspect rule registry — one module per disease family."""
from .cardiac import RULES as _CARDIAC
from .diabetes import RULES as _DIABETES
from .hematology import RULES as _HEMATOLOGY
from .hepatic import RULES as _HEPATIC
from .lipid import RULES as _LIPID
from .renal import RULES as _RENAL
from .respiratory import RULES as _RESPIRATORY

ALL_RULES = [
    *_DIABETES,
    *_RENAL,
    *_CARDIAC,
    *_LIPID,
    *_RESPIRATORY,
    *_HEPATIC,
    *_HEMATOLOGY,
]

__all__ = ["ALL_RULES"]
