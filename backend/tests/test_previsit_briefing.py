"""
tests/test_previsit_briefing.py — Pre-Visit HCC Briefing service tests.

Covers:
- Empty case: provider has no upcoming visits → returns [].
- Suspect-only candidates make it onto the huddle card.
- Recapture and MEAT-weak candidates are mixed and ranked correctly.
- Top-N limit per visit is honoured.
- De-duplication: the same hcc_code from multiple sources surfaces once.
- Date filtering: only encounters in [today, today+days_ahead] are returned.
- Empty patient join (orphan pid) is skipped without crashing.

All DB calls are mocked via unittest.mock — no MySQL or FastAPI required.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from app.services import previsit_briefing as svc


# ---------------------------------------------------------------------------
# Cursor mocking helper
# ---------------------------------------------------------------------------

class FakeCursor:
    """Minimal cursor that returns pre-programmed result sets in order.

    Each call to ``execute`` consumes one element from ``results``.  Each
    element is the rows that ``fetchall()`` should return for that query.
    ``fetchone()`` returns the first row (or None).
    """

    def __init__(self, results: list[list[dict]]):
        self._results = list(results)
        self._current: list[dict] = []

    def execute(self, *_args, **_kwargs):
        if self._results:
            self._current = list(self._results.pop(0))
        else:
            self._current = []

    def fetchall(self):
        return list(self._current)

    def fetchone(self):
        return self._current[0] if self._current else None


def _cursor_cm(results: list[list[dict]]):
    """Return a contextmanager factory yielding a single shared FakeCursor.

    The cursor's queue is shared across nested ``with`` blocks because some
    code paths open multiple short-lived cursors.
    """
    fake = FakeCursor(results)

    @contextmanager
    def _cm(*_args, **_kwargs):
        yield fake

    return _cm, fake


# ---------------------------------------------------------------------------
# 1. Empty case
# ---------------------------------------------------------------------------

class TestEmptyCase:
    def test_no_upcoming_visits_returns_empty_list(self):
        # First openemr_cursor query returns no encounters → service exits early.
        cm_oe, _ = _cursor_cm([[]])  # form_encounter
        cm_raf, _ = _cursor_cm([])

        with patch.object(svc, "openemr_cursor", cm_oe), \
             patch.object(svc, "raf_cursor", cm_raf):
            out = svc.get_upcoming_briefings(provider_id=999, days_ahead=7)

        assert out == []


# ---------------------------------------------------------------------------
# 2. Suspect-only candidates rank to top
# ---------------------------------------------------------------------------

class TestSuspectCandidates:
    def test_open_suspect_appears_with_correct_metadata(self):
        # Set up: 1 visit, 1 open suspect for that patient.
        visit_dt = datetime.combine(date.today() + timedelta(days=2),
                                    datetime.min.time().replace(hour=10, minute=30))
        encounters = [
            {"encounter_id": 1, "pid": 42, "visit_dt": visit_dt,
             "reason": "Annual wellness visit"},
        ]
        patients = [
            {"patient_id": 100, "emr_pid": 42, "first_name": "Jane",
             "last_name": "Doe", "dob": date(1955, 6, 1), "sex": "F",
             "mrn": "MRN42"},
        ]
        suspects = [
            {"id": 11, "suspect_hcc": 108, "suspect_icd10": "I5022",
             "evidence_type": "medication", "confidence_score": 0.85},
        ]

        # openemr_cursor → 1 call (form_encounter)
        cm_oe, _ = _cursor_cm([encounters])
        # raf_cursor calls (in order):
        #   1. patients lookup
        #   2. _resolve_segment (raf_patient_demographics)
        #   3. _suspect_candidates (raf_suspect_conditions)
        #   4. _coefficient_lookup (hcc_raf_coefficients)
        #   5. _recapture_candidates (raf_patient_hcc prior-year)
        #   6. _meat_weak_candidates (raf_patient_hcc partial/missing)
        cm_raf, _ = _cursor_cm([
            patients,                                   # patient join
            [{"model_segment": "CNA"}],                 # segment
            suspects,                                    # open suspects
            [{"hcc_code": 108, "coefficient": 0.323}], # coefficient lookup
            [],                                          # recapture
            [],                                          # meat-weak
        ])

        with patch.object(svc, "openemr_cursor", cm_oe), \
             patch.object(svc, "raf_cursor", cm_raf), \
             patch("app.services.raf_forecast.raf_cursor", cm_raf):
            out = svc.get_upcoming_briefings(provider_id=7, days_ahead=7)

        assert len(out) == 1
        b = out[0]
        assert b["patient_name"] == "Jane Doe"
        assert b["pid"] == 42
        assert b["patient_id"] == 100
        assert b["mrn"] == "MRN42"
        assert b["sex"] == "F"
        assert b["age"] is not None and b["age"] > 60
        assert b["encounter_reason"] == "Annual wellness visit"
        assert b["visit_time"] == "10:30"
        assert len(b["top_hccs"]) == 1
        h = b["top_hccs"][0]
        assert h["hcc_code"] == "108"
        assert h["status"] == "suspect"
        assert h["evidence_type"] == "medication"
        assert h["expected_dollars"] > 0
        assert 0 < h["confidence"] <= 1
        assert b["total_potential_dollars"] > 0


# ---------------------------------------------------------------------------
# 3. Mixed candidates — ranking
# ---------------------------------------------------------------------------

class TestRanking:
    def test_higher_score_ranks_first_and_top_n_enforced(self):
        visit_dt = datetime.combine(
            date.today() + timedelta(days=1),
            datetime.min.time().replace(hour=9),
        )
        encounters = [
            {"encounter_id": 1, "pid": 42, "visit_dt": visit_dt, "reason": "f/u"},
        ]
        patients = [
            {"patient_id": 100, "emr_pid": 42, "first_name": "X",
             "last_name": "Y", "dob": date(1950, 1, 1), "sex": "M",
             "mrn": "M1"},
        ]
        # 4 candidates total — 2 suspects + 1 recapture + 1 meat-weak.
        # Ensure no overlapping HCC codes so de-dupe isn't triggered.
        suspects = [
            {"id": 1, "suspect_hcc": 108, "suspect_icd10": "I5022",
             "evidence_type": "medication", "confidence_score": 0.90},
            {"id": 2, "suspect_hcc": 18,  "suspect_icd10": "E1165",
             "evidence_type": "lab",        "confidence_score": 0.40},
        ]
        recapture = [
            # Prior-year HCC 19 not present this year.
            {"hcc_code": 19, "raf_coefficient": 0.302, "icd10_codes": "[]"},
        ]
        meat_weak = [
            {"patient_hcc_id": 555, "hcc_code": 22,
             "raf_coefficient": 0.300, "meat_status": "partial"},
        ]
        coeff_rows = [
            {"hcc_code": 108, "coefficient": 0.500},
            {"hcc_code": 18,  "coefficient": 0.300},
        ]

        cm_oe, _ = _cursor_cm([encounters])
        cm_raf, _ = _cursor_cm([
            patients,
            [{"model_segment": "CNA"}],
            suspects,
            coeff_rows,
            recapture,
            [],          # fallback coefficient lookup for recapture (none missing)
            meat_weak,
            [{"patient_hcc_id": 555, "avg_score": 0.25}],  # completeness lookup
        ])

        with patch.object(svc, "openemr_cursor", cm_oe), \
             patch.object(svc, "raf_cursor", cm_raf), \
             patch("app.services.raf_forecast.raf_cursor", cm_raf):
            out = svc.get_upcoming_briefings(
                provider_id=7, days_ahead=7, limit_per_patient=3,
            )

        assert len(out) == 1
        top = out[0]["top_hccs"]
        assert len(top) == 3, "limit_per_patient=3 should cap output"

        # The strongest candidate is HCC 108 (coeff 0.5 × confidence 0.9).
        assert top[0]["hcc_code"] == "108"

        # Statuses should reflect mixed sources.
        statuses = {h["status"] for h in top}
        assert statuses & {"suspect", "recapture", "meat_weak"}

    def test_dedupe_keeps_highest_score_when_same_hcc_appears_twice(self):
        visit_dt = datetime.combine(
            date.today() + timedelta(days=1),
            datetime.min.time().replace(hour=9),
        )
        encounters = [
            {"encounter_id": 1, "pid": 42, "visit_dt": visit_dt, "reason": "f/u"},
        ]
        patients = [
            {"patient_id": 100, "emr_pid": 42, "first_name": "X",
             "last_name": "Y", "dob": date(1950, 1, 1), "sex": "M",
             "mrn": "M1"},
        ]
        # HCC 108 appears as a high-confidence suspect AND as a recapture
        # candidate. Only the suspect should survive.
        suspects = [
            {"id": 1, "suspect_hcc": 108, "suspect_icd10": "I5022",
             "evidence_type": "medication", "confidence_score": 0.95},
        ]
        recapture = [
            {"hcc_code": 108, "raf_coefficient": 0.323, "icd10_codes": "[]"},
        ]

        cm_oe, _ = _cursor_cm([encounters])
        cm_raf, _ = _cursor_cm([
            patients,
            [{"model_segment": "CNA"}],
            suspects,
            [{"hcc_code": 108, "coefficient": 0.323}],
            recapture,
            [],          # recapture coefficient fallback
            [],          # meat-weak (none)
        ])

        with patch.object(svc, "openemr_cursor", cm_oe), \
             patch.object(svc, "raf_cursor", cm_raf), \
             patch("app.services.raf_forecast.raf_cursor", cm_raf):
            out = svc.get_upcoming_briefings(provider_id=7, days_ahead=7)

        top = out[0]["top_hccs"]
        codes = [h["hcc_code"] for h in top]
        assert codes.count("108") == 1, "duplicate HCC code should be deduped"
        # The kept entry should be the suspect (higher confidence × $).
        assert top[0]["status"] == "suspect"


# ---------------------------------------------------------------------------
# 4. Date filter passes through to SQL
# ---------------------------------------------------------------------------

class TestDateFiltering:
    def test_days_ahead_passed_into_sql_bind_params(self):
        captured: dict[str, tuple] = {}

        class CapturingCursor(FakeCursor):
            def execute(self, sql, params=()):
                # First call is form_encounter — capture its bind params.
                if "form_encounter" in sql and "params" not in captured:
                    captured["params"] = params
                super().execute(sql, params)

        fake = CapturingCursor([[]])

        @contextmanager
        def _oe_cm(*_a, **_k):
            yield fake

        # raf_cursor never gets called when there are no encounters.
        cm_raf, _ = _cursor_cm([])
        with patch.object(svc, "openemr_cursor", _oe_cm), \
             patch.object(svc, "raf_cursor", cm_raf):
            svc.get_upcoming_briefings(provider_id=7, days_ahead=14)

        assert "params" in captured
        params = captured["params"]
        assert params[0] == 7  # provider id
        # Window is [today, today + 14 + 1) so the upper bound is +15 days.
        today = date.today()
        assert params[1] == today
        assert params[2] == today + timedelta(days=15)


# ---------------------------------------------------------------------------
# 5. Patient with no record in `patients` view is skipped
# ---------------------------------------------------------------------------

class TestOrphanPatientSkipped:
    def test_encounter_with_no_active_patient_record_is_skipped(self):
        visit_dt = datetime.combine(
            date.today() + timedelta(days=1),
            datetime.min.time(),
        )
        encounters = [
            {"encounter_id": 1, "pid": 9999, "visit_dt": visit_dt,
             "reason": "f/u"},
        ]
        cm_oe, _ = _cursor_cm([encounters])
        # Patient lookup returns nothing → encounter is dropped.
        cm_raf, _ = _cursor_cm([[]])

        with patch.object(svc, "openemr_cursor", cm_oe), \
             patch.object(svc, "raf_cursor", cm_raf), \
             patch("app.services.raf_forecast.raf_cursor", cm_raf):
            out = svc.get_upcoming_briefings(provider_id=7, days_ahead=7)

        assert out == []
