"""CMS MA revenue-per-RAF-point constants by payment year.

Sources
-------
PY2024: CMS 2024 Rate Announcement (national average MA base rate).
PY2025: CMS 2025 Rate Announcement (3.58% effective growth rate).
PY2026: CMS 2026 Rate Announcement + V28 rebenchmarking impact (~3.44% update).
PY2027: Projection based on CMS 10-year actuarial trend (~2.5% annual growth).

These values are used for dollar-delta estimates only.  They are NOT CMS-
validated and should be cross-checked against official CMS plan-specific
payment notices before any contract or budget commitment.
"""
from __future__ import annotations

REVENUE_PER_RAF_POINT_BY_YEAR: dict[int, float] = {
    2024: 11015.04,
    2025: 11407.20,
    2026: 11800.00,  # post-rebenchmarking (PY2026 CMS Rate Announcement)
    2027: 12100.00,  # projected
}

_DEFAULT_YEAR = 2026
_FALLBACK_RATE = REVENUE_PER_RAF_POINT_BY_YEAR[_DEFAULT_YEAR]


def revenue_per_raf_point(year: int | None = None) -> float:
    """Return the estimated CMS revenue per RAF point for *year*.

    Falls back to the PY2026 rate when the year is unknown or not yet
    in the table, matching the expected default for current deployments.

    Parameters
    ----------
    year:
        Payment year (e.g. 2026).  ``None`` returns the default year rate.

    Returns
    -------
    float
        Dollars per RAF point per member per year.
    """
    if year is None:
        return _FALLBACK_RATE
    # Exact match first.
    if year in REVENUE_PER_RAF_POINT_BY_YEAR:
        return REVENUE_PER_RAF_POINT_BY_YEAR[year]
    # For future years not yet in the table, use the nearest known year.
    known_years = sorted(REVENUE_PER_RAF_POINT_BY_YEAR.keys())
    if year < known_years[0]:
        return REVENUE_PER_RAF_POINT_BY_YEAR[known_years[0]]
    return REVENUE_PER_RAF_POINT_BY_YEAR[known_years[-1]]
