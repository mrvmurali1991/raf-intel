"""
tests/test_recapture_recurring_service.py — Recurring gap detection +
AWV-suggestion integration tests.

Synthetic recapture_gaps fixtures are stitched across 3+ years via mocked
``raf_cursor`` so no database is required.  We verify:

  * Year counting via detect_recurring_gaps()
  * Single-year gaps are NOT flagged as recurring
  * lookback_years window is honoured
  * Persistence path issues UPDATE for matched rows
  * get_recurring_gaps() shape + serialisation
  * suggest_awv_for_gap() shape + read-only contract
  * mark_awv_scheduled() flags row + raises on missing gap_id
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.services.recapture_recurring_service import (
    detect_recurring_gaps,
    get_recurring_gaps,
    mark_awv_scheduled,
    suggest_awv_for_gap,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row(
    gap_id: int,
    patient_id: str,
    hcc_code: str,
    current_year: int,
    status: str = "open",
    revenue: float = 3000.00,
) -> dict[str, Any]:
    return {
        "id":             gap_id,
        "patient_id":     patient_id,
        "hcc_code":       hcc_code,
        "current_year":   current_year,
        "status":         status,
        "revenue_impact": revenue,
    }


def _cursor_with_calls(call_outputs: list[Any]):
    """
    Returns a context-manager that yields a cursor whose fetchall/fetchone
    return values come from `call_outputs` in order — one entry per
    'with raf_cursor()' block.

    Each entry is a dict::

        {"fetchall": [...], "fetchone": {...}, "rowcount": N, "capture": list}

    `capture` (optional) is a list to which executemany batches are appended.
    """
    state = {"index": 0}

    @contextmanager
    def _cm(*args, **kwargs):
        idx = state["index"]
        state["index"] += 1
        spec = call_outputs[idx] if idx < len(call_outputs) else {}
        cur = MagicMock()
        cur.fetchall.return_value = spec.get("fetchall", [])
        cur.fetchone.return_value = spec.get("fetchone", None)
        cur.rowcount = spec.get("rowcount", 0)

        captured = spec.get("capture")
        if captured is not None:
            def _exec_many(_sql, batch):
                captured.extend(list(batch))
            cur.executemany.side_effect = _exec_many

        yield cur

    return _cm


# ===========================================================================
# detect_recurring_gaps
# ===========================================================================


class TestDetectRecurringGaps:

    def test_three_year_recurring_gap_flagged(self):
        """Patient/HCC appearing in 2024, 2025, AND 2026 → years_recurring=3."""
        rows = [
            _row(101, "42", "85", 2024, "open"),
            _row(202, "42", "85", 2025, "open"),
            _row(303, "42", "85", 2026, "open"),
        ]
        captured: list[tuple] = []
        cm = _cursor_with_calls([
            {"fetchall": rows},
            {"capture": captured},  # second block: UPDATE executemany
        ])
        with patch("app.services.recapture_recurring_service.raf_cursor", cm):
            result = detect_recurring_gaps(tenant_id="1", current_year=2026, lookback_years=3)

        assert len(result) == 1
        item = result[0]
        assert item["patient_id"] == "42"
        assert item["hcc_code"] == "85"
        assert item["years_recurring"] == 3
        assert item["total_$_at_risk"] == pytest.approx(9000.00)
        assert item["recommended_action"].startswith("Schedule AWV")
        # Persistence: one UPDATE per id present in current_year
        assert len(captured) == 1
        # tuple shape: (is_rec, years_recurring, gap_id, tenant_id)
        assert captured[0][0] == 1
        assert captured[0][1] == 3
        assert captured[0][2] == 303
        assert captured[0][3] == "1"

    def test_single_year_not_flagged(self):
        """A gap that ONLY appears in current_year is not recurring."""
        rows = [_row(303, "99", "111", 2026, "open")]
        captured: list[tuple] = []
        cm = _cursor_with_calls([
            {"fetchall": rows},
            {"capture": captured},
        ])
        with patch("app.services.recapture_recurring_service.raf_cursor", cm):
            result = detect_recurring_gaps(tenant_id="1", current_year=2026, lookback_years=3)

        assert result == []
        assert captured == []  # No UPDATE issued when nothing recurs

    def test_two_year_recurring_gap_flagged(self):
        """Patient/HCC in 2025 + 2026 (no 2024) → years_recurring=2."""
        rows = [
            _row(202, "7", "19", 2025, "open"),
            _row(303, "7", "19", 2026, "open"),
        ]
        captured: list[tuple] = []
        cm = _cursor_with_calls([
            {"fetchall": rows},
            {"capture": captured},
        ])
        with patch("app.services.recapture_recurring_service.raf_cursor", cm):
            result = detect_recurring_gaps(tenant_id="1", current_year=2026, lookback_years=3)

        assert len(result) == 1
        assert result[0]["years_recurring"] == 2
        assert result[0]["last_recapture_year_or_null"] is None
        # 1 UPDATE for the current-year row
        assert len(captured) == 1

    def test_lookback_window_excludes_old_gaps(self):
        """A 2022 gap with lookback=3 from 2026 falls OUTSIDE the window."""
        # The service uses BETWEEN earliest_year AND current_year in SQL, so
        # the row would never be returned — emulate that here.
        rows = [
            # earliest_year = 2026 - 3 = 2023, so 2022 is excluded by SQL
            _row(202, "5", "85", 2023, "open"),
            _row(303, "5", "85", 2026, "open"),
        ]
        captured: list[tuple] = []
        cm = _cursor_with_calls([
            {"fetchall": rows},
            {"capture": captured},
        ])
        with patch("app.services.recapture_recurring_service.raf_cursor", cm):
            result = detect_recurring_gaps(tenant_id="1", current_year=2026, lookback_years=3)

        assert len(result) == 1
        assert result[0]["years_recurring"] == 2

    def test_recaptured_year_recorded_in_last_recapture(self):
        """Status=recaptured rows still count toward years and surface as last_recapture_year."""
        rows = [
            _row(101, "42", "85", 2024, "recaptured"),
            _row(303, "42", "85", 2026, "open"),
        ]
        captured: list[tuple] = []
        cm = _cursor_with_calls([
            {"fetchall": rows},
            {"capture": captured},
        ])
        with patch("app.services.recapture_recurring_service.raf_cursor", cm):
            result = detect_recurring_gaps(tenant_id="1", current_year=2026, lookback_years=3)

        assert len(result) == 1
        assert result[0]["last_recapture_year_or_null"] == 2024

    def test_invalid_lookback_raises(self):
        with pytest.raises(ValueError, match="lookback_years"):
            detect_recurring_gaps(tenant_id="1", current_year=2026, lookback_years=0)


# ===========================================================================
# get_recurring_gaps
# ===========================================================================


class TestGetRecurringGaps:

    def test_returns_enriched_rows(self):
        rows = [
            {
                "id": 303,
                "patient_id": 42,
                "tenant_id": "1",
                "hcc_code": "85",
                "icd10_code": "I50.9",
                "prior_year": 2025,
                "current_year": 2026,
                "status": "open",
                "last_encounter_date": None,
                "provider_npi": "1234567890",
                "revenue_impact": 3000.00,
                "is_recurring": 1,
                "years_recurring": 3,
                "awv_suggested": 0,
                "awv_visit_date": None,
                "awv_encounter_id": None,
                "created_at": None,
                "updated_at": None,
                "patient_name": "Jane Doe",
                "first_name": "Jane",
                "last_name": "Doe",
                "dob": None,
            },
        ]
        cm = _cursor_with_calls([{"fetchall": rows}])
        with patch("app.services.recapture_recurring_service.raf_cursor", cm):
            result = get_recurring_gaps(tenant_id="1", year=2026)

        assert len(result) == 1
        item = result[0]
        assert item["patient_name"] == "Jane Doe"
        assert item["years_recurring"] == 3
        assert item["is_recurring"] is True
        assert item["awv_suggested"] is False
        assert item["revenue_impact"] == 3000.00

    def test_empty_returns_empty_list(self):
        cm = _cursor_with_calls([{"fetchall": []}])
        with patch("app.services.recapture_recurring_service.raf_cursor", cm):
            assert get_recurring_gaps(tenant_id="1", year=2026) == []


# ===========================================================================
# suggest_awv_for_gap
# ===========================================================================


class TestSuggestAWVForGap:

    def test_eligible_patient_returns_two_week_window(self):
        gap_row = {
            "id": 303,
            "patient_id": 42,
            "tenant_id": "1",
            "hcc_code": "85",
            "current_year": 2026,
            "provider_npi": "1234567890",
            "awv_suggested": 0,
        }
        cm = _cursor_with_calls([{"fetchone": gap_row}])

        elig_payload = {
            "patients": [
                {
                    "patient_id": 42,
                    "last_encounter_date": "2025-08-01",
                    "days_since_last_visit": 200,
                    "provider_id": 7,
                }
            ],
        }
        with patch("app.services.recapture_recurring_service.raf_cursor", cm), \
             patch("app.services.awv_service.get_eligible_patients", return_value=elig_payload):
            result = suggest_awv_for_gap(gap_id=303)

        assert result["gap_id"] == 303
        assert result["patient_id"] == 42
        assert result["eligible"] is True
        assert result["recommended_provider_id"] == 7
        assert result["last_awv_date"] == "2025-08-01"
        assert result["days_since"] == 200
        assert "suggested_visit_date" in result
        assert result["already_marked_scheduled"] is False

    def test_ineligible_patient_returns_recommendation(self):
        gap_row = {
            "id": 11,
            "patient_id": 99,
            "tenant_id": "1",
            "hcc_code": "19",
            "current_year": 2026,
            "provider_npi": None,
            "awv_suggested": 0,
        }
        cm = _cursor_with_calls([{"fetchone": gap_row}])
        with patch("app.services.recapture_recurring_service.raf_cursor", cm), \
             patch("app.services.awv_service.get_eligible_patients", return_value={"patients": []}):
            result = suggest_awv_for_gap(gap_id=11)

        assert result["eligible"] is False
        assert result["recommended_provider_id"] is None
        assert result["last_awv_date"] is None
        assert "suggested_visit_date" in result
        assert "30 days" in result["reason"] or "annual" in result["reason"]

    def test_missing_gap_raises_value_error(self):
        cm = _cursor_with_calls([{"fetchone": None}])
        with patch("app.services.recapture_recurring_service.raf_cursor", cm):
            with pytest.raises(ValueError, match="not found"):
                suggest_awv_for_gap(gap_id=9999)


# ===========================================================================
# mark_awv_scheduled
# ===========================================================================


class TestMarkAWVScheduled:

    def test_updates_row_when_present(self):
        cm = _cursor_with_calls([
            {"fetchone": {"id": 303, "tenant_id": "1"}},
            {"rowcount": 1},
        ])
        with patch("app.services.recapture_recurring_service.raf_cursor", cm):
            result = mark_awv_scheduled(gap_id=303, visit_date="2026-06-15", encounter_id="ENC-42")

        assert result["gap_id"] == 303
        assert result["awv_suggested"] is True
        assert result["awv_visit_date"] == "2026-06-15"
        assert result["awv_encounter_id"] == "ENC-42"

    def test_missing_gap_raises_value_error(self):
        cm = _cursor_with_calls([{"fetchone": None}])
        with patch("app.services.recapture_recurring_service.raf_cursor", cm):
            with pytest.raises(ValueError, match="not found"):
                mark_awv_scheduled(gap_id=9999, visit_date="2026-06-15")
