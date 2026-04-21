"""
Unit tests for app.services.raf.dos_rules.

These are pure unit tests — they do NOT require a running backend — so the
session-scoped ``server_available`` fixture in conftest.py is overridden
here to a no-op.  Run with::

    pytest backend/tests/test_dos_rules.py -v

Covers:
  * PY2024 / PY2025 / PY2026 DOS-window acceptance + rejection
  * Exact edge dates (Jan 1, Dec 31, datetimes at 00:00 and 23:59)
  * Eligible vs ineligible encounter-type handling
  * V24 / V28 blend weights per payment year
  * filter_encounters_for_py / partition_encounters_for_py shape
"""
from __future__ import annotations

from datetime import date, datetime

import pytest

from app.services.raf.dos_rules import (
    ELIGIBLE_ENCOUNTER_TYPES,
    PAYMENT_YEARS,
    PaymentYearWindow,
    filter_encounters_for_py,
    get_blend_weights,
    get_payment_year_window,
    is_eligible_encounter,
    partition_encounters_for_py,
)


# ---------------------------------------------------------------------------
# Override the server_available autouse fixture from conftest.py.
# These unit tests must run even when the backend is offline.
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session", autouse=True)
def server_available():  # noqa: D401 — fixture override
    """No-op override; unit tests don't need the live backend."""
    yield


# ---------------------------------------------------------------------------
# Test data: (encounter, payment_year, expected_ok, expected_reason_substring)
# ---------------------------------------------------------------------------

# PY2024 DOS window is 2023-01-01..2023-12-31.
# PY2025 DOS window is 2024-01-01..2024-12-31.
# PY2026 DOS window is 2025-01-01..2025-12-31.

_IN_WINDOW_CASES: list[tuple[dict, int, bool, str]] = [
    # PY2024 in-window edges (Jan 1, Dec 31, mid-year)
    ({"date": "2023-01-01", "encounter_type": "outpatient"}, 2024, True, ""),
    ({"date": "2023-12-31", "encounter_type": "inpatient"},  2024, True, ""),
    ({"date": "2023-06-15", "encounter_type": "professional"}, 2024, True, ""),
    ({"date": "2023-04-20", "encounter_type": "telehealth"}, 2024, True, ""),
    # PY2025 in-window edges
    ({"date": "2024-01-01", "encounter_type": "outpatient"}, 2025, True, ""),
    ({"date": "2024-12-31", "encounter_type": "inpatient"},  2025, True, ""),
    # PY2026 in-window edges
    ({"date": "2025-01-01", "encounter_type": "outpatient"}, 2026, True, ""),
    ({"date": "2025-12-31", "encounter_type": "professional"}, 2026, True, ""),
]

_OUT_OF_WINDOW_CASES: list[tuple[dict, int, str]] = [
    # One day before the window
    ({"date": "2022-12-31", "encounter_type": "outpatient"}, 2024, "outside PY2024 window"),
    # One day after the window
    ({"date": "2024-01-01", "encounter_type": "outpatient"}, 2024, "outside PY2024 window"),
    # PY2025: 2023 DOS is too old
    ({"date": "2023-11-15", "encounter_type": "inpatient"},  2025, "outside PY2025 window"),
    # PY2025: 2025 DOS is too new
    ({"date": "2025-02-01", "encounter_type": "outpatient"}, 2025, "outside PY2025 window"),
    # PY2026: 2024 DOS is too old
    ({"date": "2024-06-30", "encounter_type": "outpatient"}, 2026, "outside PY2026 window"),
    # PY2026: 2026 DOS is too new
    ({"date": "2026-01-15", "encounter_type": "outpatient"}, 2026, "outside PY2026 window"),
]

_INELIGIBLE_TYPE_CASES: list[tuple[dict, int, str]] = [
    ({"date": "2024-05-01", "encounter_type": "lab"},        2025, "not eligible"),
    ({"date": "2024-05-01", "encounter_type": "pharmacy"},   2025, "not eligible"),
    ({"date": "2024-05-01", "encounter_type": "DME"},        2025, "not eligible"),
    ({"date": "2024-05-01", "encounter_type": "ambulance"},  2025, "not eligible"),
    ({"date": "2024-05-01", "encounter_type": "hospice"},    2025, "not eligible"),
    ({"date": "2024-05-01", "encounter_type": "home_health"}, 2025, "not eligible"),
    ({"date": "2024-05-01", "encounter_type": "institutional"}, 2025, "not eligible"),
    ({"date": "2024-05-01"},                                 2025, "encounter_type missing"),
]


# ---------------------------------------------------------------------------
# In-window acceptance
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("enc,py,expected_ok,_reason", _IN_WINDOW_CASES)
def test_encounter_in_window_accepted(enc, py, expected_ok, _reason):
    ok, reason = is_eligible_encounter(enc, py)
    assert ok is expected_ok, f"Expected in-window accept for {enc} / PY{py}; got ({ok}, {reason!r})"
    assert reason == ""


# ---------------------------------------------------------------------------
# Out-of-window rejection — reason string includes PY + window
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("enc,py,expected_substring", _OUT_OF_WINDOW_CASES)
def test_encounter_out_of_window_rejected(enc, py, expected_substring):
    ok, reason = is_eligible_encounter(enc, py)
    assert ok is False
    assert expected_substring in reason, (
        f"reason={reason!r} does not mention {expected_substring!r}"
    )
    # The reason should always include the DOS itself for traceability.
    assert enc["date"] in reason


# ---------------------------------------------------------------------------
# Ineligible encounter type rejection
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("enc,py,expected_substring", _INELIGIBLE_TYPE_CASES)
def test_encounter_type_ineligible(enc, py, expected_substring):
    ok, reason = is_eligible_encounter(enc, py)
    assert ok is False
    assert expected_substring in reason


# ---------------------------------------------------------------------------
# Edge timestamps — Jan 1 00:00 + Dec 31 23:59 datetimes must be in window
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("py,start_dt,end_dt", [
    (2024, datetime(2023, 1, 1,  0,  0,  0), datetime(2023, 12, 31, 23, 59, 59)),
    (2025, datetime(2024, 1, 1,  0,  0,  0), datetime(2024, 12, 31, 23, 59, 59)),
    (2026, datetime(2025, 1, 1,  0,  0,  0), datetime(2025, 12, 31, 23, 59, 59)),
])
def test_datetime_edges_accepted(py, start_dt, end_dt):
    for dt in (start_dt, end_dt):
        ok, reason = is_eligible_encounter(
            {"date": dt, "encounter_type": "outpatient"}, py,
        )
        assert ok, f"expected {dt.isoformat()} accepted for PY{py}; got reason={reason!r}"


@pytest.mark.parametrize("py,dt", [
    (2024, datetime(2022, 12, 31, 23, 59, 59)),  # last second before PY2024 window
    (2024, datetime(2024,  1,  1,  0,  0,  0)),  # first second after PY2024 window
    (2025, datetime(2023, 12, 31, 23, 59, 59)),
    (2025, datetime(2025,  1,  1,  0,  0,  0)),
    (2026, datetime(2024, 12, 31, 23, 59, 59)),
    (2026, datetime(2026,  1,  1,  0,  0,  0)),
])
def test_datetime_just_outside_rejected(py, dt):
    ok, reason = is_eligible_encounter(
        {"date": dt, "encounter_type": "outpatient"}, py,
    )
    assert ok is False
    assert f"PY{py}" in reason


# ---------------------------------------------------------------------------
# V24 / V28 blend weights per payment year
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("py,expected", [
    (2024, {"V24": 0.67, "V28": 0.33}),
    (2025, {"V24": 0.33, "V28": 0.67}),
    (2026, {"V24": 0.00, "V28": 1.00}),
])
def test_blend_weights(py, expected):
    blend = get_blend_weights(py)
    assert set(blend.keys()) == set(expected.keys())
    for key, value in expected.items():
        assert blend[key] == pytest.approx(value, abs=1e-6), (
            f"PY{py} {key} weight {blend[key]} != expected {value}"
        )
    # All weights must sum to exactly 1.0.
    assert sum(blend.values()) == pytest.approx(1.0, abs=1e-6)


def test_blend_weights_unknown_year_raises():
    with pytest.raises(KeyError):
        get_blend_weights(2099)


# ---------------------------------------------------------------------------
# PaymentYearWindow registry integrity
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("py", [2024, 2025, 2026])
def test_payment_year_window_registered(py):
    win = get_payment_year_window(py)
    assert isinstance(win, PaymentYearWindow)
    assert win.year == py
    # CMS rule: DOS window is the full calendar year before the payment year.
    assert win.dos_start == date(py - 1, 1, 1)
    assert win.dos_end == date(py - 1, 12, 31)


def test_registry_covers_required_years():
    for required in (2024, 2025, 2026):
        assert required in PAYMENT_YEARS, (
            f"PAYMENT_YEARS must declare PY{required} — callers depend on it"
        )


def test_eligible_encounter_types_covers_cms_categories():
    # These four are the only types our filter accepts.  A regression here
    # would silently allow (or silently drop) entire claim categories.
    assert "inpatient" in ELIGIBLE_ENCOUNTER_TYPES
    assert "outpatient" in ELIGIBLE_ENCOUNTER_TYPES
    assert "professional" in ELIGIBLE_ENCOUNTER_TYPES
    assert "telehealth" in ELIGIBLE_ENCOUNTER_TYPES
    # Obviously-not-RAF types must stay out.
    assert "lab" not in ELIGIBLE_ENCOUNTER_TYPES
    assert "dme" not in ELIGIBLE_ENCOUNTER_TYPES


# ---------------------------------------------------------------------------
# filter_encounters_for_py + partition_encounters_for_py
# ---------------------------------------------------------------------------

def test_filter_encounters_keeps_only_eligible():
    encs = [
        {"date": "2024-03-01", "encounter_type": "outpatient"},   # keep
        {"date": "2022-12-31", "encounter_type": "outpatient"},   # drop (DOS)
        {"date": "2024-06-15", "encounter_type": "lab"},          # drop (type)
        {"date": "2024-12-31", "encounter_type": "inpatient"},    # keep
        {"date": "2024-01-01", "encounter_type": "professional"}, # keep
    ]
    kept = filter_encounters_for_py(encs, 2025)
    assert len(kept) == 3
    kept_dates = {e["date"] for e in kept}
    assert kept_dates == {"2024-03-01", "2024-12-31", "2024-01-01"}


def test_partition_encounters_returns_reasons():
    encs = [
        {"date": "2024-03-01", "encounter_type": "outpatient"},
        {"date": "2022-12-31", "encounter_type": "outpatient"},
        {"date": "2024-06-15", "encounter_type": "lab"},
    ]
    kept, excluded = partition_encounters_for_py(encs, 2025)
    assert len(kept) == 1
    assert kept[0]["date"] == "2024-03-01"

    assert len(excluded) == 2
    reasons = {item["reason"] for item in excluded}
    assert any("outside PY2025 window" in r for r in reasons)
    assert any("not eligible" in r for r in reasons)


# ---------------------------------------------------------------------------
# Flexible input shapes (encounter_date / dos / service_date, type vs
# encounter_type, already-coerced date/datetime)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("enc", [
    {"encounter_date": "2024-05-01", "encounter_type": "outpatient"},
    {"dos":            "2024-05-01", "encounter_type": "outpatient"},
    {"service_date":   "2024-05-01", "encounter_type": "outpatient"},
    {"date":           date(2024, 5, 1), "encounter_type": "outpatient"},
    {"date":           datetime(2024, 5, 1, 14, 30), "type": "OUTPATIENT"},
])
def test_alternate_field_names(enc):
    ok, reason = is_eligible_encounter(enc, 2025)
    assert ok, f"expected accept for {enc!r}, got reason={reason!r}"


def test_missing_dos_rejected():
    ok, reason = is_eligible_encounter({"encounter_type": "outpatient"}, 2025)
    assert ok is False
    assert "date-of-service" in reason


def test_unparseable_dos_rejected():
    ok, reason = is_eligible_encounter(
        {"date": "not-a-date", "encounter_type": "outpatient"}, 2025,
    )
    assert ok is False
    assert "date-of-service" in reason


def test_unknown_payment_year_rejected_with_reason():
    ok, reason = is_eligible_encounter(
        {"date": "2024-05-01", "encounter_type": "outpatient"}, 2099,
    )
    assert ok is False
    assert "2099" in reason


# ---------------------------------------------------------------------------
# PaymentYearWindow self-validation (blend sums, date ordering)
# ---------------------------------------------------------------------------

def test_blend_must_sum_to_one():
    with pytest.raises(ValueError):
        PaymentYearWindow(
            year=9999,
            dos_start=date(9998, 1, 1),
            dos_end=date(9998, 12, 31),
            model_blend={"V24": 0.5, "V28": 0.2},  # sums to 0.7
        )


def test_dos_end_must_be_after_start():
    with pytest.raises(ValueError):
        PaymentYearWindow(
            year=9999,
            dos_start=date(9998, 12, 31),
            dos_end=date(9998, 1, 1),
            model_blend={"V28": 1.0},
        )
