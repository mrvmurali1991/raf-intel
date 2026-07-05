# DISCLAIMER: This module is part of the CMS-HCC RAF calculation engine.
# Not CMS-validated. For informational purposes only.
"""
Blend weight tables and factor lookup helpers for V24/V28 CMS transition.

CMS phased transition schedule (MA/Part D):
  PY2024: 67% V24 + 33% V28
  PY2025: 33% V24 + 67% V28
  PY2026: 100% V28  (transition complete)
  PY2027+: 100% V28 (stable)

Years not present in _BLEND_WEIGHTS default to (0.0, 1.0) — pure V28.

PACE organizations follow a separate, slower transition schedule.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Blend weights by payment year: (v24_weight, v28_weight)
# Years not in dict default to (0.0, 1.0) — pure V28.
# ---------------------------------------------------------------------------

_BLEND_WEIGHTS: dict[int, tuple[float, float]] = {
    2024: (0.67, 0.33),
    2025: (0.33, 0.67),
    2026: (0.0,  1.0),   # PY2026: transition complete — pure V28
    2027: (0.0,  1.0),   # PY2027+: stable pure V28 (explicit entry)
}
# Years not in this dict also default to (0.0, 1.0) in the lookup code.

# PACE organizations follow a separate, slower transition schedule.
# CMS uses the 2017 CMS-HCC model (not V24) as the legacy side for PACE.
# Weights here are (legacy_2017_weight, v28_weight).
# CY2026: 90% legacy 2017 + 10% V28  (per CY2026 Advance Notice)
# CY2027: 50% legacy 2017 + 50% V28  (proposed)
# CY2028+: 100% V28 (projected)
_PACE_BLEND_WEIGHTS: dict[int, tuple[float, float]] = {
    2024: (1.0, 0.0),   # PACE not yet transitioning — 100% legacy 2017 model
    2025: (1.0, 0.0),   # PACE not yet transitioning — 100% legacy 2017 model
    2026: (0.90, 0.10),  # 90% legacy 2017 + 10% V28
    2027: (0.50, 0.50),  # proposed 50/50
}

# ---------------------------------------------------------------------------
# Normalization factors by payment year
# Source: CMS 2026 Rate Announcement (and prior year Rate Announcements)
# ---------------------------------------------------------------------------

# V28 normalization factors
_NORM_FACTORS_V28: dict[int, float] = {
    2024: 1.045,
    2025: 1.045,
    2026: 1.067,
}

# Backward-compat alias
_NORM_FACTORS = _NORM_FACTORS_V28

# V24 normalization factors — remained constant across the transition years
# per CMS 2026 Rate Announcement
_NORM_FACTORS_V24: dict[int, float] = {
    2024: 1.153,
    2025: 1.153,
    2026: 1.153,
}

# V22 (legacy 2017 model) normalization factors — used for the PACE legacy side
# per CMS 2026 Rate Announcement
_NORM_FACTORS_V22: dict[int, float] = {
    2024: 1.187,
    2025: 1.187,
    2026: 1.187,
}

# ---------------------------------------------------------------------------
# MACI (Minimum Allowable Coding Intensity) factors by year
# ---------------------------------------------------------------------------

_MACI_FACTORS_V28: dict[int, float] = {
    2024: 0.059,
    2025: 0.059,
    2026: 0.059,  # finalized per CMS 2026 Rate Announcement (Apr 2025)
}

# Backward-compat alias
_MACI_FACTORS = _MACI_FACTORS_V28

_MACI_FACTORS_V24: dict[int, float] = {
    2024: 0.059,
    2025: 0.059,
    2026: 0.059,
}


# ---------------------------------------------------------------------------
# Factor lookup helpers
# ---------------------------------------------------------------------------


def _get_norm_factor(factors: dict[int, float], year: int) -> float:
    """Return the normalization factor for *year*.

    If *year* is not in *factors*, logs a WARNING and returns the factor for
    the latest year present in the dict instead of silently defaulting to 1.0
    (which would produce an unnormalized score with no indication of the error).
    """
    if year in factors:
        return factors[year]
    latest = max(factors.keys())
    logger.warning(
        "No normalization factor for year %s, using %s factor (%.3f)",
        year,
        latest,
        factors[latest],
    )
    return factors[latest]


def _get_maci_factor(factors: dict[int, float], year: int) -> float:
    """Return the MACI factor for *year*.

    If *year* is not in *factors*, logs a WARNING and returns the factor for
    the latest year present in the dict instead of silently defaulting to 0.0.
    """
    if year in factors:
        return factors[year]
    latest = max(factors.keys())
    logger.warning(
        "No MACI factor for year %s, using %s factor (%.3f)",
        year,
        latest,
        factors[latest],
    )
    return factors[latest]
