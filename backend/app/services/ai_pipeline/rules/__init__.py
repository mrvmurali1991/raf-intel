"""Suspect rule registry — one module per disease family."""
from .diabetes import RULES as _DIABETES
from .renal import RULES as _RENAL
from .cardiac import RULES as _CARDIAC
from .lipid import RULES as _LIPID
from .respiratory import RULES as _RESPIRATORY
from .hepatic import RULES as _HEPATIC
from .hematology import RULES as _HEMATOLOGY

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
