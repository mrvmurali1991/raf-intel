"""Unit tests for app.services.ai_pipeline.eligibility.

Covers:
  - Cutoff filter: patients updated before cutoff excluded, at/after included.
  - Child-table updates: patient eligible if any FHIR child row updated since cutoff.
  - Per-patient rate limit: 1st + 2nd runs allowed, 3rd blocked.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime
from unittest.mock import patch

import pytest
from app.services.ai_pipeline import eligibility as E

# ---------------------------------------------------------------------------
# Helpers: a scripted cursor that returns different rows per SELECT.
# ---------------------------------------------------------------------------


class ScriptedCursor:
    """MagicMock-style cursor that returns rows by matching substrings in SQL."""

    def __init__(self, script: list[tuple[str, list[dict]]], lastrowid: int = 1):
        # script is an ordered list of (sql_substring, rows).
        self._script = list(script)
        self._last_rows: list[dict] = []
        self.lastrowid = lastrowid
        self.executed: list[tuple[str, tuple]] = []

    def execute(self, sql: str, params: tuple | None = None):
        self.executed.append((sql, params or ()))
        for i, (needle, rows) in enumerate(self._script):
            if needle in sql:
                self._last_rows = rows
                # consume first match so subsequent queries get remaining entries
                self._script.pop(i)
                return
        self._last_rows = []

    def fetchall(self):
        return list(self._last_rows)

    def fetchone(self):
        return self._last_rows[0] if self._last_rows else None


def _cursor_cm(cursor):
    @contextmanager
    def _cm(*args, **kwargs):
        yield cursor

    return _cm


# ---------------------------------------------------------------------------
# Cutoff filter tests
# ---------------------------------------------------------------------------


def test_cutoff_filter_includes_only_recent_patients() -> None:
    cutoff = date(2026, 4, 15)
    # OpenEMR: patient_data returns pid=1 (updated after cutoff).
    # form_clinical_notes returns empty.
    emr = ScriptedCursor(
        [
            ("FROM patient_data", [{"pid": 1}]),
            ("FROM form_clinical_notes", []),
        ]
    )
    # RAF: no FHIR child changes.
    raf = ScriptedCursor(
        [
            ("FROM fhir_observations", []),
            ("FROM fhir_conditions", []),
            ("FROM fhir_medications", []),
            ("FROM fhir_encounters", []),
        ]
    )

    with patch.object(E, "openemr_cursor", _cursor_cm(emr)), \
         patch.object(E, "raf_cursor", _cursor_cm(raf)), \
         patch.object(E, "_get_config", return_value=None):
        result = E.get_eligible_patients("tenant-1", cutoff_date=cutoff)

    assert result == ["1"]
    # Confirm cutoff was bound into the SQL params as a datetime for cutoff date.
    pd_call = next(c for c in emr.executed if "patient_data" in c[0])
    bound_dt = pd_call[1][0]
    assert isinstance(bound_dt, datetime)
    assert bound_dt.date() == cutoff


def test_cutoff_filter_excludes_when_nothing_changed() -> None:
    emr = ScriptedCursor(
        [("FROM patient_data", []), ("FROM form_clinical_notes", [])]
    )
    raf = ScriptedCursor(
        [
            ("FROM fhir_observations", []),
            ("FROM fhir_conditions", []),
            ("FROM fhir_medications", []),
            ("FROM fhir_encounters", []),
        ]
    )
    with patch.object(E, "openemr_cursor", _cursor_cm(emr)), \
         patch.object(E, "raf_cursor", _cursor_cm(raf)), \
         patch.object(E, "_get_config", return_value=None):
        assert E.get_eligible_patients("tenant-1") == []


# ---------------------------------------------------------------------------
# Child-table updates test
# ---------------------------------------------------------------------------


def test_child_table_update_makes_patient_eligible() -> None:
    # Patient record itself is stale, but a FHIR observation moved.
    emr = ScriptedCursor(
        [("FROM patient_data", []), ("FROM form_clinical_notes", [])]
    )
    raf = ScriptedCursor(
        [
            ("FROM fhir_observations", [{"fhir_patient_id": "fhir-abc"}]),
            ("FROM fhir_conditions", []),
            ("FROM fhir_medications", []),
            ("FROM fhir_encounters", []),
            # emr_patient_matches lookup → fhir-abc maps to local pid 42
            (
                "FROM emr_patient_matches",
                [{"local_pid": 42, "fhir_patient_id": "fhir-abc"}],
            ),
        ]
    )
    with patch.object(E, "openemr_cursor", _cursor_cm(emr)), \
         patch.object(E, "raf_cursor", _cursor_cm(raf)), \
         patch.object(E, "_get_config", return_value=None):
        result = E.get_eligible_patients("tenant-1", cutoff_date=date(2026, 4, 15))

    assert result == ["42"]


# ---------------------------------------------------------------------------
# Per-patient rate limit tests
# ---------------------------------------------------------------------------


class CountingRafCursor:
    """Cursor simulating ai_analysis_runs INSERT + COUNT behavior."""

    def __init__(self):
        self.rows: list[dict] = []
        self._last: list[dict] = []
        self.lastrowid = 0

    def execute(self, sql: str, params: tuple | None = None):
        sql_l = sql.lower()
        if "insert into ai_analysis_runs" in sql_l:
            self.lastrowid = len(self.rows) + 1
            self.rows.append(
                {
                    "id": self.lastrowid,
                    "patient_id": params[0],
                    "tenant_id": params[1],
                    "started_at": params[2],
                    "status": "running",
                    "trigger_reason": params[3],
                    "finished_at": None,
                }
            )
            self._last = []
        elif "count(*)" in sql_l and "ai_analysis_runs" in sql_l:
            patient_id, tenant_id = params[1], params[0]
            c = sum(
                1
                for r in self.rows
                if r["patient_id"] == patient_id and r["tenant_id"] == tenant_id
            )
            self._last = [{"c": c}]
        elif "update ai_analysis_runs" in sql_l:
            finished_at, status, run_id = params
            for r in self.rows:
                if r["id"] == run_id:
                    r["finished_at"] = finished_at
                    r["status"] = status
            self._last = []
        else:
            self._last = []

    def fetchone(self):
        return self._last[0] if self._last else None

    def fetchall(self):
        return list(self._last)


def test_rate_limit_allows_first_two_blocks_third() -> None:
    cur = CountingRafCursor()
    with patch.object(E, "raf_cursor", _cursor_cm(cur)), \
         patch.object(E, "_get_config", return_value=None):
        # 1st: allowed
        assert E.can_run_analysis("p1", "tenant-1") is True
        rid1 = E.record_run_start("p1", "tenant-1", "scheduled")
        E.record_run_finish(rid1, status="success")

        # 2nd: still allowed
        assert E.can_run_analysis("p1", "tenant-1") is True
        rid2 = E.record_run_start("p1", "tenant-1", "manual")
        E.record_run_finish(rid2, status="success")

        # 3rd: blocked
        assert E.can_run_analysis("p1", "tenant-1") is False

    # Verify rows recorded correctly.
    assert len(cur.rows) == 2
    assert all(r["status"] == "success" for r in cur.rows)
    assert cur.rows[0]["trigger_reason"] == "scheduled"


def test_rate_limit_is_per_patient() -> None:
    cur = CountingRafCursor()
    with patch.object(E, "raf_cursor", _cursor_cm(cur)), \
         patch.object(E, "_get_config", return_value=None):
        E.record_run_start("p1", "tenant-1")
        E.record_run_start("p1", "tenant-1")
        # Different patient: not blocked by p1's cap.
        assert E.can_run_analysis("p2", "tenant-1") is True
        # p1 is now blocked.
        assert E.can_run_analysis("p1", "tenant-1") is False


def test_record_run_finish_rejects_bad_status() -> None:
    cur = CountingRafCursor()
    with patch.object(E, "raf_cursor", _cursor_cm(cur)), pytest.raises(ValueError):
        E.record_run_finish(1, status="bogus")


def test_cutoff_resolves_from_config() -> None:
    emr = ScriptedCursor(
        [("FROM patient_data", []), ("FROM form_clinical_notes", [])]
    )
    raf = ScriptedCursor(
        [
            ("FROM fhir_observations", []),
            ("FROM fhir_conditions", []),
            ("FROM fhir_medications", []),
            ("FROM fhir_encounters", []),
        ]
    )
    with patch.object(E, "openemr_cursor", _cursor_cm(emr)), \
         patch.object(E, "raf_cursor", _cursor_cm(raf)), \
         patch.object(E, "_get_config", side_effect=lambda k, tenant_id=None:
                      "2026-01-01" if k == E._CFG_KEY_CUTOFF else None):
        E.get_eligible_patients("tenant-1")
    # Bound datetime should reflect the configured cutoff.
    bound = next(c for c in emr.executed if "patient_data" in c[0])[1][0]
    assert bound.date() == date(2026, 1, 1)
