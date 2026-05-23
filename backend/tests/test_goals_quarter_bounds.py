"""Boundary tests for goals._quarter_bounds (round-16 suggestion S-1).

The Q4 path is non-obvious — end_month = 12 makes
`next_y = year + 1` and `next_m = (12 % 12) + 1 = 1`, then we subtract
a day to get 31-Dec of the original year. These tests pin the math so a
future refactor can't silently regress the year-rollover case.
"""
from __future__ import annotations

from datetime import date


def test_q1_bounds() -> None:
    from app.routers.goals import _quarter_bounds
    start, end = _quarter_bounds("2026-Q1")
    assert start == date(2026, 1, 1)
    assert end == date(2026, 3, 31)


def test_q2_bounds() -> None:
    from app.routers.goals import _quarter_bounds
    start, end = _quarter_bounds("2026-Q2")
    assert start == date(2026, 4, 1)
    assert end == date(2026, 6, 30)


def test_q3_bounds() -> None:
    from app.routers.goals import _quarter_bounds
    start, end = _quarter_bounds("2026-Q3")
    assert start == date(2026, 7, 1)
    assert end == date(2026, 9, 30)


def test_q4_bounds_rolls_into_next_year_correctly() -> None:
    from app.routers.goals import _quarter_bounds
    start, end = _quarter_bounds("2026-Q4")
    assert start == date(2026, 10, 1)
    # Critical: end must be 31-Dec of the SAME year, not 31-Dec of next year.
    assert end == date(2026, 12, 31)
