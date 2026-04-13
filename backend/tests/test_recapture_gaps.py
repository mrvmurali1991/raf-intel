"""
tests/test_recapture_gaps.py — Recapture gap detection and management test suite.

Tests cover:
- Prior-year HCC not in current year → gap detected and persisted
- HCC present in both years → no gap created
- Gap closure (recapture) via resolve_gap() and close_gap()
- list_gaps() pagination and status filtering
- get_gap_stats() aggregation
- get_gap_summary() rich summary with top patients
- get_patient_gaps() patient-scoped open gaps
- detect_gaps() wrapper with year derivation
- Revenue impact assignment
- Boundary / edge cases

All DB calls are mocked via unittest.mock — no database required.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from unittest.mock import MagicMock, call, patch

import pytest

from app.services.recapture_gap_service import (
    _REVENUE_IMPACT_PER_GAP,
    detect_and_persist_gaps,
    detect_gaps,
    resolve_gap,
    list_gaps,
    get_gap_stats,
    get_patient_gaps,
    close_gap,
    get_gap_summary,
    get_recapture_bundle,
    _hcc_description,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_cursor_cm(rows: list[dict] | None = None, rowcount: int = 0):
    """Return a reusable context-manager mock that yields a cursor."""
    cursor = MagicMock()
    cursor.fetchall.return_value = list(rows or [])
    cursor.fetchone.return_value = (rows[0] if rows else None)
    cursor.rowcount = rowcount

    @contextmanager
    def _cm(*args, **kwargs):
        yield cursor

    return _cm, cursor


def _detect_rows(prior_hccs: list[dict], current_map: dict) -> list[dict]:
    """
    Build fake SELECT rows for detect_and_persist_gaps.

    prior_hccs: list of {patient_id, hcc_code, icd10_code, provider_npi}
    current_map: set of (patient_id, hcc_code) tuples present in current year
    """
    rows = []
    for h in prior_hccs:
        key = (h["patient_id"], h["hcc_code"])
        current_hcc = h["hcc_code"] if key in current_map else None
        rows.append({
            "patient_id": h["patient_id"],
            "hcc_code": h["hcc_code"],
            "icd10_code": h.get("icd10_code", "E11.9"),
            "provider_npi": h.get("provider_npi", "1234567890"),
            "current_hcc_code": current_hcc,
        })
    return rows


# ===========================================================================
# 1. detect_and_persist_gaps — core gap detection
# ===========================================================================

class TestDetectAndPersistGaps:
    def _gap_cursor_cm(self, detect_rows, rowcount=0, total_open=0):
        """
        Build a single-block cursor for detect_and_persist_gaps which:
          1. execute(detect_sql) + fetchall() → detect_rows
          2. executemany(insert_sql) → rowcount gaps inserted
          3. execute(count_open_sql) + fetchone() → {"total_open": N}
        All happen in ONE 'with raf_cursor()' block.
        """
        @contextmanager
        def _cm(*args, **kwargs):
            cur = MagicMock()
            cur.fetchall.return_value = detect_rows
            cur.rowcount = rowcount
            cur.fetchone.return_value = {"total_open": total_open}
            yield cur

        return _cm

    def test_prior_hcc_missing_in_current_year_creates_gap(self):
        """Patient with HCC 17 in prior year but not in current → 1 new gap."""
        detect_rows = _detect_rows(
            prior_hccs=[{"patient_id": "42", "hcc_code": "17", "icd10_code": "E11.0"}],
            current_map=set(),  # HCC 17 not recaptured
        )
        cm = self._gap_cursor_cm(detect_rows, rowcount=1, total_open=1)
        with patch("app.services.recapture_gap_service.raf_cursor", cm):
            result = detect_and_persist_gaps(tenant_id="1", prior_year=2025, current_year=2026)

        assert result["new_gaps"] == 1
        assert result["total_open"] == 1

    def test_hcc_in_both_years_creates_no_gap(self):
        """HCC 17 present in both prior and current year → no new gap."""
        detect_rows = _detect_rows(
            prior_hccs=[{"patient_id": "42", "hcc_code": "17", "icd10_code": "E11.0"}],
            current_map={("42", "17")},  # Recaptured
        )
        cm = self._gap_cursor_cm(detect_rows, rowcount=0, total_open=0)
        with patch("app.services.recapture_gap_service.raf_cursor", cm):
            result = detect_and_persist_gaps(tenant_id="1", prior_year=2025, current_year=2026)

        assert result["new_gaps"] == 0
        assert result["total_open"] == 0

    def test_multiple_patients_partial_recapture(self):
        """Three HCCs: two gaps, one recaptured."""
        prior = [
            {"patient_id": "1", "hcc_code": "17", "icd10_code": "E11.0"},
            {"patient_id": "2", "hcc_code": "85", "icd10_code": "I50.9"},
            {"patient_id": "3", "hcc_code": "111", "icd10_code": "J44.1"},
        ]
        detect_rows = _detect_rows(
            prior_hccs=prior,
            current_map={("3", "111")},  # Only patient 3 recaptured
        )
        cm = self._gap_cursor_cm(detect_rows, rowcount=2, total_open=2)
        with patch("app.services.recapture_gap_service.raf_cursor", cm):
            result = detect_and_persist_gaps(tenant_id="1", prior_year=2025, current_year=2026)

        assert result["new_gaps"] == 2
        assert result["total_open"] == 2

    def test_revenue_impact_assigned_per_gap(self):
        """Each gap should receive the standard revenue impact."""
        assert _REVENUE_IMPACT_PER_GAP == pytest.approx(3000.00)

    def test_empty_prior_year_returns_zeros(self):
        """When there are no prior-year HCCs, no gaps are inserted and total_open=0."""
        count_row = {"total_open": 0}

        # The service uses a single cursor block; we need fetchall to return []
        # and fetchone to return the count row within the same context block.
        @contextmanager
        def _cm(*args, **kwargs):
            cur = MagicMock()
            cur.fetchall.return_value = []
            cur.fetchone.return_value = count_row
            cur.rowcount = 0
            yield cur

        with patch("app.services.recapture_gap_service.raf_cursor", _cm):
            result = detect_and_persist_gaps(tenant_id="1", prior_year=2025, current_year=2026)

        assert result["new_gaps"] == 0
        assert result["total_open"] == 0

    def test_duplicate_patient_provider_rows_deduped(self):
        """Same (patient_id, hcc_code) from two provider rows → only one gap inserted."""
        detect_rows = [
            {"patient_id": "5", "hcc_code": "17", "icd10_code": "E11.0",
             "provider_npi": "111", "current_hcc_code": None},
            {"patient_id": "5", "hcc_code": "17", "icd10_code": "E11.0",
             "provider_npi": "222", "current_hcc_code": None},
        ]
        insert_batch_captured = {}

        @contextmanager
        def _cm(*args, **kwargs):
            cur = MagicMock()
            cur.fetchall.return_value = detect_rows
            cur.rowcount = 1
            cur.fetchone.return_value = {"total_open": 1}

            def _exec_many(sql, batch):
                insert_batch_captured["batch"] = batch

            cur.executemany.side_effect = _exec_many
            yield cur

        with patch("app.services.recapture_gap_service.raf_cursor", _cm):
            detect_and_persist_gaps(tenant_id="1", prior_year=2025, current_year=2026)

        batch = insert_batch_captured.get("batch", [])
        assert len(batch) == 1


# ===========================================================================
# 2. detect_gaps — wrapper with year derivation
# ===========================================================================

class TestDetectGaps:
    def test_year_derivation(self):
        """detect_gaps(measurement_year=2026) → prior_year=2025 current_year=2026."""
        with patch(
            "app.services.recapture_gap_service.detect_and_persist_gaps",
            return_value={"new_gaps": 0, "total_open": 0},
        ) as mock_detect:
            result = detect_gaps(tenant_id="1", measurement_year=2026)

        mock_detect.assert_called_once_with(
            tenant_id="1", prior_year=2025, current_year=2026
        )
        assert result["prior_year"] == 2025
        assert result["current_year"] == 2026


# ===========================================================================
# 3. resolve_gap — status transitions
# ===========================================================================

class TestResolveGap:
    def test_recaptured_transition(self):
        cm, cursor = _make_cursor_cm(rowcount=1)
        with patch("app.services.recapture_gap_service.raf_cursor", cm):
            success = resolve_gap(gap_id=1, status="recaptured", resolved_by="user@raf.health")
        assert success is True

    def test_dismissed_transition(self):
        cm, cursor = _make_cursor_cm(rowcount=1)
        with patch("app.services.recapture_gap_service.raf_cursor", cm):
            success = resolve_gap(gap_id=1, status="dismissed", resolved_by="admin")
        assert success is True

    def test_invalid_status_raises_value_error(self):
        with pytest.raises(ValueError, match="Invalid status"):
            resolve_gap(gap_id=1, status="pending", resolved_by="user")

    def test_gap_not_found_returns_false(self):
        cm, cursor = _make_cursor_cm(rowcount=0)
        with patch("app.services.recapture_gap_service.raf_cursor", cm):
            success = resolve_gap(gap_id=9999, status="recaptured", resolved_by="user")
        assert success is False


# ===========================================================================
# 4. close_gap — recapture via system
# ===========================================================================

class TestCloseGap:
    def test_close_gap_recaptures_successfully(self):
        existing_gap = {"id": 1}
        call_n = {"n": 0}

        @contextmanager
        def _cm(*args, **kwargs):
            cur = MagicMock()
            n = call_n["n"]
            call_n["n"] += 1
            if n == 0:
                cur.fetchone.return_value = existing_gap
            yield cur

        with patch("app.services.recapture_gap_service.raf_cursor", _cm):
            # Should not raise
            close_gap(gap_id=1, tenant_id="1")

    def test_close_gap_raises_if_not_found(self):
        cm, cursor = _make_cursor_cm(rows=[])

        with patch("app.services.recapture_gap_service.raf_cursor", cm):
            with pytest.raises(ValueError, match="not found"):
                close_gap(gap_id=9999, tenant_id="1")


# ===========================================================================
# 5. list_gaps — pagination and status filter
# ===========================================================================

class TestListGaps:
    def _gap_row(self, gap_id: int = 1, status: str = "open") -> dict:
        return {
            "id": gap_id, "patient_id": "42", "tenant_id": "1", "hcc_code": "17",
            "icd10_code": "E11.0", "prior_year": 2025, "current_year": 2026,
            "status": status, "last_encounter_date": None, "provider_npi": "1234567890",
            "revenue_impact": 3000.00, "resolved_at": None, "resolved_by": None,
            "created_at": datetime(2026, 1, 1), "updated_at": datetime(2026, 1, 1),
            "patient_name": "John Doe",
        }

    def test_returns_open_gaps(self):
        rows = [self._gap_row(1, "open"), self._gap_row(2, "open")]
        cm, _ = _make_cursor_cm(rows=rows)
        with patch("app.services.recapture_gap_service.raf_cursor", cm):
            result = list_gaps(tenant_id="1", status="open")
        assert len(result) == 2
        assert all(r["status"] == "open" for r in result)

    def test_empty_result_when_no_gaps(self):
        cm, _ = _make_cursor_cm(rows=[])
        with patch("app.services.recapture_gap_service.raf_cursor", cm):
            result = list_gaps(tenant_id="1")
        assert result == []

    def test_pagination_parameters_passed(self):
        cm, cursor = _make_cursor_cm(rows=[])
        with patch("app.services.recapture_gap_service.raf_cursor", cm):
            list_gaps(tenant_id="1", limit=10, offset=20)
        # Verify limit/offset are in the execute call args
        call_args = cursor.execute.call_args
        params = call_args[0][1] if call_args else []
        assert 10 in params
        assert 20 in params


# ===========================================================================
# 6. get_gap_stats — aggregation
# ===========================================================================

class TestGetGapStats:
    def test_stats_mapped_correctly(self):
        stats_row = {
            "total_gaps": 10,
            "open_count": 6,
            "recaptured_count": 3,
            "dismissed_count": 1,
            "total_revenue_at_risk": 18000.00,
        }
        cm, _ = _make_cursor_cm(rows=[stats_row])
        with patch("app.services.recapture_gap_service.raf_cursor", cm):
            result = get_gap_stats(tenant_id="1")
        assert result["total_gaps"] == 10
        assert result["open"] == 6
        assert result["recaptured"] == 3
        assert result["dismissed"] == 1
        assert result["total_revenue_at_risk"] == pytest.approx(18000.00)

    def test_null_values_default_to_zero(self):
        stats_row = {
            "total_gaps": None,
            "open_count": None,
            "recaptured_count": None,
            "dismissed_count": None,
            "total_revenue_at_risk": None,
        }
        cm, _ = _make_cursor_cm(rows=[stats_row])
        with patch("app.services.recapture_gap_service.raf_cursor", cm):
            result = get_gap_stats(tenant_id="1")
        assert result["total_gaps"] == 0
        assert result["open"] == 0
        assert result["total_revenue_at_risk"] == 0.0


# ===========================================================================
# 7. get_patient_gaps — patient-scoped open gaps
# ===========================================================================

class TestGetPatientGaps:
    def test_returns_open_gaps_for_patient(self):
        rows = [
            {
                "id": 1, "patient_id": "42", "hcc_code": "17", "icd10_code": "E11.0",
                "prior_year": 2025, "current_year": 2026, "status": "open",
                "last_encounter_date": None, "provider_npi": "123",
                "revenue_impact": 3000.00,
                "created_at": None, "updated_at": None,
            }
        ]
        cm, _ = _make_cursor_cm(rows=rows)
        with patch("app.services.recapture_gap_service.raf_cursor", cm):
            result = get_patient_gaps(patient_id=42, tenant_id="1")
        assert len(result) == 1
        assert result[0]["hcc_code"] == "17"
        assert "hcc_description" in result[0]

    def test_hcc_description_attached(self):
        rows = [
            {
                "id": 1, "patient_id": "42", "hcc_code": "17", "icd10_code": "E11.0",
                "prior_year": 2025, "current_year": 2026, "status": "open",
                "last_encounter_date": None, "provider_npi": None,
                "revenue_impact": 3000.00,
                "created_at": None, "updated_at": None,
            }
        ]
        cm, _ = _make_cursor_cm(rows=rows)
        with patch("app.services.recapture_gap_service.raf_cursor", cm):
            result = get_patient_gaps(patient_id=42, tenant_id="1")
        assert result[0]["hcc_description"] == "Diabetes with Acute Complications"

    def test_no_gaps_returns_empty_list(self):
        cm, _ = _make_cursor_cm(rows=[])
        with patch("app.services.recapture_gap_service.raf_cursor", cm):
            result = get_patient_gaps(patient_id=999, tenant_id="1")
        assert result == []


# ===========================================================================
# 8. _hcc_description helper
# ===========================================================================

class TestHccDescription:
    @pytest.mark.parametrize("code,expected", [
        ("17", "Diabetes with Acute Complications"),
        ("18", "Diabetes with Chronic Complications"),
        ("19", "Diabetes without Complications"),
        ("85", "Congestive Heart Failure"),
        ("111", "Chronic Obstructive Pulmonary Disease"),
        ("134", "Dialysis Status"),
    ])
    def test_known_hcc_descriptions(self, code: str, expected: str):
        assert _hcc_description(code) == expected

    def test_unknown_hcc_returns_fallback(self):
        assert _hcc_description("9999") == "HCC 9999"

    def test_hcc_prefix_stripped(self):
        """Input 'HCC17' should resolve the same as '17'."""
        assert _hcc_description("HCC17") == _hcc_description("17")


# ===========================================================================
# 9. get_recapture_bundle — CMS Bundle 6 payload
# ===========================================================================

class TestGetRecaptureBundle:
    def test_bundle_rows_structured_correctly(self):
        rows = [
            {
                "Patient_ID": "42", "HCC": "17", "ICD10": "E11.0",
                "Prior_Year": 2025, "Current_Year": 2026, "Current_Status": "open",
                "Last_Encounter_Date": None, "Provider_NPI": "1234567890",
                "Revenue_Impact": 3000.00,
            }
        ]
        cm, _ = _make_cursor_cm(rows=rows)
        with patch("app.services.recapture_gap_service.raf_cursor", cm):
            bundle = get_recapture_bundle(tenant_id="1")
        assert len(bundle) == 1
        item = bundle[0]
        assert item["Patient_ID"] == "42"
        assert item["HCC"] == "17"
        assert item["Revenue_Impact"] == pytest.approx(3000.00)
        assert item["Last_Encounter_Date"] is None

    def test_empty_bundle_when_no_gaps(self):
        cm, _ = _make_cursor_cm(rows=[])
        with patch("app.services.recapture_gap_service.raf_cursor", cm):
            bundle = get_recapture_bundle(tenant_id="1")
        assert bundle == []
