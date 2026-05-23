"""Tests for ``app.services.hcc_gap_drilldown.get_gap_patients``.

The function is a pure SQL aggregator over four tables:
  - provider_patient_panel  (the panel for the provider)
  - raf_patient_hcc         (coded HCCs for current + prior year)
  - raf_suspect_conditions  (open suspects)
  - patients (VIEW)         (demographics)

We don't have a live MySQL in unit tests, so we mock ``raf_cursor`` /
``openemr_cursor`` to return canned rows that exercise:

  * the union of "open suspect" + "prior-year coded" (the "missing"
    definition), with already-coded-this-year patients excluded
  * sort order: confidence DESC, then prior_year_coded DESC, then
    patient_id ASC
  * limit honoring
  * graceful handling of patients with no demographics
  * the helpers (_hcc_to_int, _calc_age, _evidence_snippet)
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import date, datetime
from unittest.mock import MagicMock, patch

import pytest

from app.services.hcc_gap_drilldown import (
    _calc_age,
    _evidence_snippet,
    _hcc_to_int,
    get_gap_patients,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

class _CursorScript:
    """Sequenced cursor mock — yields a fresh cursor whose ``fetchall``
    returns the next scripted row list each time the context manager is
    entered. Lets us drive multi-step service flows from a single fixture.
    """

    def __init__(self, scripts: list[list[dict]]):
        self._scripts = list(scripts)
        self.calls: list[tuple] = []  # (sql, params)

    @contextmanager
    def __call__(self, *args, **kwargs):
        rows = self._scripts.pop(0) if self._scripts else []
        cur = MagicMock()
        cur.fetchall.return_value = list(rows)
        cur.fetchone.return_value = (rows[0] if rows else None)

        def _execute(sql, params=()):
            self.calls.append((sql, params))

        cur.execute.side_effect = _execute
        yield cur


def _patch_cursors(raf_scripts: list[list[dict]], oe_scripts: list[list[dict]] | None = None):
    """Return a context manager that patches the two cursor factories
    used by the service module, with sequenced fetchall results.
    """
    raf_factory = _CursorScript(raf_scripts)
    oe_factory = _CursorScript(oe_scripts or [[]])

    return patch.multiple(
        "app.services.hcc_gap_drilldown",
        raf_cursor=raf_factory,
        # active_patients_subquery is patched separately below; we only
        # need the cursor here.
    ), patch("app.db.openemr_cursor", oe_factory), raf_factory, oe_factory


# ---------------------------------------------------------------------------
# Helper: full patch fixture
# ---------------------------------------------------------------------------

@contextmanager
def _service_env(
    panel: list[int],
    coded_this_year: list[int],
    suspects: list[dict],
    prior_year_coded: list[int],
    demos: list[dict],
    last_encounters: list[dict] | None = None,
):
    """Set up the cursor scripts and tenant subquery for the service.

    Order of cursor calls inside ``get_gap_patients``:
      1. SELECT panel
      2. SELECT already-coded-this-year
      3. SELECT open suspects
      4. SELECT prior-year coded
      5. SELECT patients (demographics)
      6. SELECT form_encounter (openemr — separate cursor)
    """
    raf_scripts = [
        [{"patient_id": p} for p in panel],
        [{"patient_id": p} for p in coded_this_year],
        suspects,
        [{"patient_id": p} for p in prior_year_coded],
        demos,
    ]
    oe_scripts = [last_encounters or []]

    raf_factory = _CursorScript(raf_scripts)
    oe_factory = _CursorScript(oe_scripts)

    with patch("app.services.hcc_gap_drilldown.raf_cursor", raf_factory), \
         patch("app.services.hcc_gap_drilldown.active_patients_subquery",
               return_value=("(patient_id IN (SELECT id FROM patients WHERE tenant_id=%s))", (1,))), \
         patch("app.db.openemr_cursor", oe_factory):
        yield raf_factory, oe_factory


# ---------------------------------------------------------------------------
# 1. Helpers
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("85", 85),
        ("HCC85", 85),
        ("hcc85", 85),
        (" 85 ", 85),
        (85, 85),
        ("", None),
        (None, None),
        ("abc", None),
    ],
)
def test_hcc_to_int(raw, expected) -> None:
    assert _hcc_to_int(raw) == expected


def test_calc_age_basic() -> None:
    today = date(2026, 5, 5)
    assert _calc_age(date(1980, 1, 1), today) == 46
    # Birthday hasn't happened yet this year
    assert _calc_age(date(1980, 12, 31), today) == 45


def test_calc_age_str_iso() -> None:
    assert _calc_age("1990-06-15", date(2026, 5, 5)) == 35


def test_calc_age_garbage_returns_none() -> None:
    assert _calc_age(None) is None
    assert _calc_age("") is None
    assert _calc_age("not-a-date") is None


def test_evidence_snippet_dict_note_excerpt() -> None:
    payload = json.dumps({"note_excerpt": "A1c 9.1 on 2026-04-12"})
    snippet = _evidence_snippet("lab", payload)
    assert "Lab" in snippet
    assert "A1c 9.1" in snippet


def test_evidence_snippet_handles_none() -> None:
    assert _evidence_snippet(None, None) == ""


def test_evidence_snippet_truncates_long_text() -> None:
    long = "x" * 500
    snippet = _evidence_snippet("medication", {"note_excerpt": long})
    assert len(snippet) <= 240
    assert snippet.endswith("…")


# ---------------------------------------------------------------------------
# 2. Missing definition + ordering
# ---------------------------------------------------------------------------

def test_returns_empty_when_panel_empty() -> None:
    """No panel → no rows. The service should not crash on an empty IN().
    """
    raf_factory = _CursorScript([[]])  # only the panel query is reached
    with patch("app.services.hcc_gap_drilldown.raf_cursor", raf_factory), \
         patch("app.services.hcc_gap_drilldown.active_patients_subquery",
               return_value=("(1=1)", ())):
        out = get_gap_patients(provider_id=1, hcc_code="85", year=2026)
    assert out == []


def test_returns_empty_for_invalid_hcc() -> None:
    out = get_gap_patients(provider_id=1, hcc_code="not-a-hcc", year=2026)
    assert out == []


def test_already_coded_excluded_from_results() -> None:
    """Patient who already has the HCC coded for the year must NOT appear,
    even if they also have an open suspect."""
    panel = [10, 11, 12]
    suspects = [
        {
            "patient_id": 10,
            "confidence_score": 0.9,
            "evidence_type": "lab",
            "evidence_detail": json.dumps({"note_excerpt": "high"}),
            "created_at": datetime(2026, 1, 1),
            "updated_at": datetime(2026, 1, 1),
        },
        {
            "patient_id": 11,
            "confidence_score": 0.7,
            "evidence_type": "medication",
            "evidence_detail": json.dumps({"note_excerpt": "rx"}),
            "created_at": datetime(2026, 1, 1),
            "updated_at": datetime(2026, 1, 1),
        },
    ]
    demos = [
        {"id": 11, "first_name": "Bob", "last_name": "Smith", "dob": date(1970, 1, 1), "sex": "M", "mrn": "B11"},
    ]
    with _service_env(
        panel=panel,
        coded_this_year=[10],   # patient 10 is already coded for hcc 85
        suspects=suspects,
        prior_year_coded=[],
        demos=demos,
    ):
        out = get_gap_patients(provider_id=1, hcc_code="85", year=2026)

    assert [r["patient_id"] for r in out] == [11]
    assert out[0]["confidence"] == 0.7
    assert out[0]["suspect_status"] == "open"
    assert out[0]["prior_year_coded"] is False


def test_prior_year_coded_only_is_a_gap() -> None:
    """A patient with no open suspect, but coded last year, must still
    appear (recapture-due gap). Confidence falls back to 0.0."""
    panel = [42]
    demos = [
        {"id": 42, "first_name": "Alice", "last_name": "Doe", "dob": date(1955, 6, 1), "sex": "F", "mrn": "A42"},
    ]
    with _service_env(
        panel=panel,
        coded_this_year=[],
        suspects=[],
        prior_year_coded=[42],
        demos=demos,
    ):
        out = get_gap_patients(provider_id=1, hcc_code="85", year=2026)

    assert len(out) == 1
    row = out[0]
    assert row["patient_id"] == 42
    assert row["prior_year_coded"] is True
    assert row["suspect_status"] is None
    assert row["confidence"] == 0.0
    assert row["evidence_snippet"] == ""


def test_sort_by_confidence_desc_then_prior_year_desc() -> None:
    """Sort priorities:
       1. confidence DESC
       2. prior_year_coded DESC (True first)
       3. patient_id ASC (stable tiebreak)
    """
    panel = [1, 2, 3, 4]
    suspects = [
        # patient 1 — high confidence, no prior coding
        {
            "patient_id": 1, "confidence_score": 0.95,
            "evidence_type": "lab", "evidence_detail": json.dumps({"summary": "s1"}),
            "created_at": None, "updated_at": None,
        },
        # patient 2 — medium confidence, prior-year coded
        {
            "patient_id": 2, "confidence_score": 0.50,
            "evidence_type": "medication", "evidence_detail": json.dumps({"summary": "s2"}),
            "created_at": None, "updated_at": None,
        },
        # patient 4 — same medium confidence as patient 2, no prior coding
        {
            "patient_id": 4, "confidence_score": 0.50,
            "evidence_type": "imaging", "evidence_detail": json.dumps({"summary": "s4"}),
            "created_at": None, "updated_at": None,
        },
    ]
    # Patient 3 has only prior-year coding (no suspect → 0.0 confidence)
    demos = [
        {"id": 1, "first_name": "P", "last_name": "1", "dob": date(1960, 1, 1), "sex": "M", "mrn": ""},
        {"id": 2, "first_name": "P", "last_name": "2", "dob": date(1960, 1, 1), "sex": "M", "mrn": ""},
        {"id": 3, "first_name": "P", "last_name": "3", "dob": date(1960, 1, 1), "sex": "M", "mrn": ""},
        {"id": 4, "first_name": "P", "last_name": "4", "dob": date(1960, 1, 1), "sex": "M", "mrn": ""},
    ]

    with _service_env(
        panel=panel,
        coded_this_year=[],
        suspects=suspects,
        prior_year_coded=[2, 3],
        demos=demos,
    ):
        out = get_gap_patients(provider_id=1, hcc_code="85", year=2026, limit=10)

    # Expected order:
    #   patient 1: conf 0.95, prior=False
    #   patient 2: conf 0.50, prior=True   (beats patient 4 on prior flag)
    #   patient 4: conf 0.50, prior=False
    #   patient 3: conf 0.00, prior=True
    assert [r["patient_id"] for r in out] == [1, 2, 4, 3]


def test_limit_truncates_results() -> None:
    panel = [1, 2, 3]
    suspects = [
        {"patient_id": pid, "confidence_score": 0.1 * pid,
         "evidence_type": "lab", "evidence_detail": "{}",
         "created_at": None, "updated_at": None}
        for pid in panel
    ]
    demos = [
        {"id": pid, "first_name": "X", "last_name": str(pid), "dob": None, "sex": "M", "mrn": ""}
        for pid in panel
    ]
    with _service_env(
        panel=panel,
        coded_this_year=[],
        suspects=suspects,
        prior_year_coded=[],
        demos=demos,
    ):
        out = get_gap_patients(provider_id=1, hcc_code="85", year=2026, limit=2)

    assert len(out) == 2
    # Highest confidence first → 0.3 (patient 3), 0.2 (patient 2)
    assert out[0]["patient_id"] == 3
    assert out[1]["patient_id"] == 2


def test_missing_demographics_falls_back_to_placeholder_name() -> None:
    panel = [99]
    suspects = [{
        "patient_id": 99, "confidence_score": 0.6,
        "evidence_type": "historical", "evidence_detail": "{}",
        "created_at": None, "updated_at": None,
    }]
    with _service_env(
        panel=panel,
        coded_this_year=[],
        suspects=suspects,
        prior_year_coded=[],
        demos=[],   # no rows in the patients view
    ):
        out = get_gap_patients(provider_id=1, hcc_code="85", year=2026)

    assert len(out) == 1
    assert out[0]["patient_id"] == 99
    assert out[0]["patient_name"] == "Patient 99"
    assert out[0]["age"] is None
    assert out[0]["sex"] == "Unknown"


def test_hcc_code_accepts_hcc_prefix() -> None:
    """Callers may pass either '85' or 'HCC85' — both should work."""
    panel = [1]
    suspects = [{
        "patient_id": 1, "confidence_score": 0.5,
        "evidence_type": "lab", "evidence_detail": "{}",
        "created_at": None, "updated_at": None,
    }]
    demos = [{"id": 1, "first_name": "A", "last_name": "B", "dob": None, "sex": "M", "mrn": ""}]

    with _service_env(panel=panel, coded_this_year=[], suspects=suspects,
                      prior_year_coded=[], demos=demos):
        out = get_gap_patients(provider_id=1, hcc_code="HCC85", year=2026)

    assert len(out) == 1
    assert out[0]["patient_id"] == 1
