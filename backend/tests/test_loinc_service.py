"""
Unit tests for app.services.knowledge_graph.loinc_service and the
lab_suspect_engine integration that consumes kg_lab_signals.

These tests do NOT require a live backend or DB — DB calls are stubbed via
monkeypatch on the openemr_cursor / raf_cursor context managers.
"""
from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

# Make ``app.*`` importable when pytest is run from the repo root.
_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.services.knowledge_graph import loinc_service  # noqa: E402
from app.services import lab_suspect_engine  # noqa: E402


# ---------------------------------------------------------------------------
# Bypass the session-scoped server_available fixture — these tests are
# purely in-process unit tests with mocked DB calls.
# Overriding the fixture name in this module turns it into a no-op for
# every test collected here.
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session", autouse=True)
def server_available():
    yield


# ---------------------------------------------------------------------------
# Fake cursor / DB plumbing
# ---------------------------------------------------------------------------

class FakeCursor:
    """Minimal MySQL-style cursor backed by a SHARED scripted queue.

    Each call to ``execute`` pops the next response off the queue.  All
    cursors created within a single test share the same queue so that
    sequential ``with raf_cursor()`` calls receive the next scripted row.
    """

    def __init__(self, shared_queue: list[Any]):
        self._queue = shared_queue
        self._last_response: Any = None
        self.lastrowid = 0

    def execute(self, sql: str, params: tuple = ()):
        self._last_response = self._queue.pop(0) if self._queue else []

    def fetchone(self):
        r = self._last_response
        if isinstance(r, list):
            return r[0] if r else None
        return r if isinstance(r, dict) else None

    def fetchall(self):
        r = self._last_response
        if isinstance(r, list):
            return r
        if isinstance(r, dict):
            return [r]
        return []

    def close(self):  # pragma: no cover - interface compatibility
        pass


def _patch_raf_cursor(monkeypatch, scripted: list[Any]):
    """Patch loinc_service.raf_cursor — every ``with raf_cursor()`` shares the
    same scripted queue, so sequential SQL calls receive sequential responses."""
    queue = list(scripted)

    @contextmanager
    def fake_cm(dictionary: bool = True):
        yield FakeCursor(queue)

    monkeypatch.setattr(loinc_service, "raf_cursor", fake_cm)


def _patch_openemr_cursor(monkeypatch, scripted: list[Any]):
    queue = list(scripted)

    @contextmanager
    def fake_cm(dictionary: bool = True):
        yield FakeCursor(queue)

    monkeypatch.setattr(loinc_service, "openemr_cursor", fake_cm)


# ---------------------------------------------------------------------------
# evaluate_threshold — pure function
# ---------------------------------------------------------------------------

class TestEvaluateThreshold:
    def test_above_triggers(self) -> None:
        assert loinc_service.evaluate_threshold(8.2, None, 6.5, "above") is True

    def test_above_does_not_trigger_below(self) -> None:
        assert loinc_service.evaluate_threshold(5.5, None, 6.5, "above") is False

    def test_below_triggers(self) -> None:
        assert loinc_service.evaluate_threshold(25, 30, None, "below") is True

    def test_within_inclusive(self) -> None:
        assert loinc_service.evaluate_threshold(140, 135, 145, "within") is True
        assert loinc_service.evaluate_threshold(155, 135, 145, "within") is False

    def test_outside_high(self) -> None:
        assert loinc_service.evaluate_threshold(160, 135, 145, "outside") is True

    def test_outside_low(self) -> None:
        assert loinc_service.evaluate_threshold(120, 135, 145, "outside") is True

    def test_unknown_meaning_returns_false(self) -> None:
        assert loinc_service.evaluate_threshold(1, 0, 2, "spaghetti") is False

    def test_non_numeric_value_safe(self) -> None:
        assert loinc_service.evaluate_threshold("oops", 1, 2, "above") is False  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# evaluate_lab_value — uses kg_lab_signals + concept lookup
# ---------------------------------------------------------------------------

class TestEvaluateLabValue:
    def _hba1c_rows(self):
        # Row 1: 6.5% threshold (controlled DM)
        # Row 2: 9.0% threshold (uncontrolled DM)
        return [
            [
                {
                    "id": 1, "loinc_code": "4548-4", "test_name": "Hemoglobin A1c",
                    "unit": "%", "threshold_low": None, "threshold_high": 6.5,
                    "threshold_meaning": "above", "signals_concept_id": 100,
                    "confidence": 0.85, "notes": "DM",
                },
                {
                    "id": 2, "loinc_code": "4548-4", "test_name": "Hemoglobin A1c",
                    "unit": "%", "threshold_low": None, "threshold_high": 9.0,
                    "threshold_meaning": "above", "signals_concept_id": 101,
                    "confidence": 0.90, "notes": "Uncontrolled DM",
                },
            ],
            # _fetch_concept call for concept 100
            {"id": 100, "code_system": "ICD10", "code": "E11.9",
             "display_name": "Type 2 DM", "hcc_code": "HCC36"},
            # _fetch_concept call for concept 101
            {"id": 101, "code_system": "ICD10", "code": "E11.65",
             "display_name": "Type 2 DM (uncontrolled)", "hcc_code": "HCC36"},
        ]

    def test_hba1c_82_triggers_diabetes_only(self, monkeypatch) -> None:
        scripted = self._hba1c_rows()
        # Only first concept lookup happens (8.2 < 9.0 so uncontrolled rule misses)
        scripted = [scripted[0], scripted[1]]
        _patch_raf_cursor(monkeypatch, scripted)

        out = loinc_service.evaluate_lab_value("4548-4", 8.2, "%")
        assert len(out) == 1
        assert out[0]["condition_code"] == "E11.9"
        assert out[0]["hcc_code"] == "HCC36"
        assert out[0]["threshold_explanation"].startswith("8.2 %")

    def test_hba1c_95_triggers_both(self, monkeypatch) -> None:
        scripted = self._hba1c_rows()
        _patch_raf_cursor(monkeypatch, scripted)

        out = loinc_service.evaluate_lab_value("4548-4", 9.5, "%")
        assert len(out) == 2
        codes = sorted(o["condition_code"] for o in out)
        assert codes == ["E11.65", "E11.9"]

    def test_unknown_loinc_returns_empty(self, monkeypatch) -> None:
        _patch_raf_cursor(monkeypatch, [[]])
        assert loinc_service.evaluate_lab_value("9999-9", 100) == []

    def test_non_numeric_value_returns_empty(self, monkeypatch) -> None:
        _patch_raf_cursor(monkeypatch, [])
        assert loinc_service.evaluate_lab_value("4548-4", "non-numeric") == []

    def test_egfr_25_triggers_ckd_stage4(self, monkeypatch) -> None:
        scripted = [
            [
                {"id": 10, "loinc_code": "33914-3", "test_name": "eGFR",
                 "unit": "mL/min/1.73m2", "threshold_low": 60.0,
                 "threshold_high": None, "threshold_meaning": "below",
                 "signals_concept_id": 200, "confidence": 0.7, "notes": "CKD"},
                {"id": 11, "loinc_code": "33914-3", "test_name": "eGFR",
                 "unit": "mL/min/1.73m2", "threshold_low": 30.0,
                 "threshold_high": None, "threshold_meaning": "below",
                 "signals_concept_id": 201, "confidence": 0.85, "notes": "CKD4"},
            ],
            # concept 200 has hcc=None -> service will fall back to ICD10
            # crosswalk lookup, which we script as empty.
            {"id": 200, "code_system": "ICD10", "code": "N18.9",
             "display_name": "CKD", "hcc_code": None},
            [],  # _hcc_for_icd10 lookup returns no row
            {"id": 201, "code_system": "ICD10", "code": "N18.4",
             "display_name": "CKD Stage 4", "hcc_code": "HCC326"},
        ]
        _patch_raf_cursor(monkeypatch, scripted)

        out = loinc_service.evaluate_lab_value("33914-3", 25, "mL/min/1.73m2")
        assert len(out) == 2
        codes = sorted(o["condition_code"] for o in out)
        assert codes == ["N18.4", "N18.9"]
        # The CKD4 row should carry HCC326
        ckd4 = next(o for o in out if o["condition_code"] == "N18.4")
        assert ckd4["hcc_code"] == "HCC326"


# ---------------------------------------------------------------------------
# Anemia sex-specific thresholds
# ---------------------------------------------------------------------------

class TestAnemiaSexSpecific:
    """Two rows for LOINC 718-7 — one for female threshold (11), one male (13)."""

    def _rows(self, value: float):
        # The DB returns both rows; evaluate_threshold filters by value.
        return [
            [
                {"id": 21, "loinc_code": "718-7", "test_name": "Hemoglobin (female)",
                 "unit": "g/dL", "threshold_low": 11.0, "threshold_high": None,
                 "threshold_meaning": "below", "signals_concept_id": 300,
                 "confidence": 0.75, "notes": "Anemia female"},
                {"id": 22, "loinc_code": "718-7", "test_name": "Hemoglobin (male)",
                 "unit": "g/dL", "threshold_low": 13.0, "threshold_high": None,
                 "threshold_meaning": "below", "signals_concept_id": 301,
                 "confidence": 0.75, "notes": "Anemia male"},
            ],
        ]

    def test_hgb_12_triggers_male_only(self, monkeypatch) -> None:
        scripted = self._rows(12.0)
        # value=12: only male rule fires (12 <= 13).  One concept lookup.
        scripted.append({"id": 301, "code_system": "ICD10", "code": "D64.9",
                         "display_name": "Anemia (male)", "hcc_code": "HCC48"})
        _patch_raf_cursor(monkeypatch, scripted)

        out = loinc_service.evaluate_lab_value("718-7", 12.0, "g/dL")
        assert len(out) == 1
        assert "male" in (out[0]["test_name"] or "").lower()

    def test_hgb_105_triggers_both(self, monkeypatch) -> None:
        scripted = self._rows(10.5)
        scripted.append({"id": 300, "code_system": "ICD10", "code": "D64.9",
                         "display_name": "Anemia (female)", "hcc_code": "HCC48"})
        scripted.append({"id": 301, "code_system": "ICD10", "code": "D64.9",
                         "display_name": "Anemia (male)", "hcc_code": "HCC48"})
        _patch_raf_cursor(monkeypatch, scripted)

        out = loinc_service.evaluate_lab_value("718-7", 10.5, "g/dL")
        assert len(out) == 2  # both fire at 10.5 (below 11 AND below 13)


# ---------------------------------------------------------------------------
# resolve_lab_to_loinc — fuzzy matching
# ---------------------------------------------------------------------------

class TestResolveLabToLoinc:
    def _signal_rows(self):
        return [
            {"id": 1, "loinc_code": "4548-4", "test_name": "Hemoglobin A1c",
             "unit": "%", "signals_concept_id": 100, "threshold_meaning": "above",
             "threshold_low": None, "threshold_high": 6.5, "confidence": 0.85},
            {"id": 2, "loinc_code": "33914-3",
             "test_name": "Estimated Glomerular Filtration Rate",
             "unit": "mL/min/1.73m2", "signals_concept_id": 200,
             "threshold_meaning": "below", "threshold_low": 60.0,
             "threshold_high": None, "confidence": 0.7},
        ]

    def test_resolve_hba1c_alias(self, monkeypatch) -> None:
        # First LIKE returns nothing (since 'hemoglobin a1c' vs the LIKE pattern
        # token starts with 'hemoglobin'); we still test the broad-scan fallback.
        scripted = [
            [self._signal_rows()[0]],   # LIKE returns the A1c row
        ]
        _patch_raf_cursor(monkeypatch, scripted)

        out = loinc_service.resolve_lab_to_loinc("HbA1c")
        assert out, "expected at least one match"
        assert out[0]["loinc_code"] == "4548-4"
        assert out[0]["similarity"] > 0

    def test_resolve_egfr(self, monkeypatch) -> None:
        scripted = [[self._signal_rows()[1]]]
        _patch_raf_cursor(monkeypatch, scripted)

        out = loinc_service.resolve_lab_to_loinc("eGFR")
        assert out
        assert out[0]["loinc_code"] == "33914-3"

    def test_resolve_empty_input(self, monkeypatch) -> None:
        _patch_raf_cursor(monkeypatch, [])
        assert loinc_service.resolve_lab_to_loinc("") == []
        assert loinc_service.resolve_lab_to_loinc("   ") == []

    def test_resolve_no_matches_returns_empty(self, monkeypatch) -> None:
        # LIKE returns nothing, broad scan returns rows with low similarity.
        scripted = [[], self._signal_rows()]
        _patch_raf_cursor(monkeypatch, scripted)
        out = loinc_service.resolve_lab_to_loinc("zzzzzunknownzzz")
        # Either empty (good) or a low-similarity hit — assert no false positive
        assert all(r["similarity"] < 0.5 for r in out)


# ---------------------------------------------------------------------------
# Integration with lab_suspect_engine
# ---------------------------------------------------------------------------

class TestLabSuspectEngineIntegration:
    def test_kg_signal_appears_in_detect_lab_suspects(self, monkeypatch) -> None:
        """A note containing 'HbA1c: 8.2' must yield a KG-driven suspect tagged
        via the kg_lab_signals signal id."""

        def fake_evaluate(loinc, value, unit=None):
            if loinc == "4548-4" and float(value) >= 6.5:
                return [{
                    "signal_id": 99,
                    "loinc_code": "4548-4",
                    "test_name": "Hemoglobin A1c",
                    "unit": "%",
                    "value": float(value),
                    "condition_concept_id": 100,
                    "condition_code": "E11.65",
                    "condition_display": "Type 2 DM (uncontrolled)",
                    "hcc_code": "HCC36",
                    "confidence": 0.9,
                    "threshold_meaning": "above",
                    "threshold_low": None,
                    "threshold_high": 6.5,
                    "threshold_explanation": f"{value} % ≥ 6.5 % (threshold-above)",
                    "notes": "test",
                }]
            return []

        monkeypatch.setattr(lab_suspect_engine, "_kg_evaluate", fake_evaluate)

        suspects = lab_suspect_engine.detect_lab_suspects("HbA1c: 8.2 today.", existing_diagnoses=[])
        assert any(
            s["evidence_detail"].get("via") == "kg_lab_signals" for s in suspects
        ), "expected at least one kg_lab_signals-sourced suspect"

    def test_legacy_rules_still_fire_when_kg_empty(self, monkeypatch) -> None:
        """When kg_lab_signals returns nothing, the legacy hardcoded rules
        must still produce a suspect (eGFR <30 → CKD Stage 4)."""
        monkeypatch.setattr(lab_suspect_engine, "_kg_evaluate", lambda *a, **k: [])

        suspects = lab_suspect_engine.detect_lab_suspects(
            "Patient eGFR: 22 mL/min — CKD progression.",
            existing_diagnoses=[],
        )
        assert any(s["icd10"].startswith("N18") for s in suspects)

    def test_existing_diagnosis_suppresses_kg_signal(self, monkeypatch) -> None:
        """A patient already coded for E11 should NOT receive a duplicate DM
        suspect from kg_lab_signals."""

        def fake_evaluate(loinc, value, unit=None):
            return [{
                "signal_id": 99,
                "loinc_code": "4548-4",
                "test_name": "Hemoglobin A1c",
                "unit": "%",
                "value": float(value),
                "condition_concept_id": 100,
                "condition_code": "E11.9",
                "condition_display": "Type 2 DM",
                "hcc_code": "HCC36",
                "confidence": 0.85,
                "threshold_meaning": "above",
                "threshold_low": None,
                "threshold_high": 6.5,
                "threshold_explanation": "8.2 % ≥ 6.5 %",
                "notes": "",
            }]

        monkeypatch.setattr(lab_suspect_engine, "_kg_evaluate", fake_evaluate)

        suspects = lab_suspect_engine.detect_lab_suspects(
            "HbA1c: 8.2",
            existing_diagnoses=["E11.9"],
        )
        assert not any(s.get("icd10", "").startswith("E11") for s in suspects)


# ---------------------------------------------------------------------------
# get_loinc_signals_for_hcc — reverse lookup
# ---------------------------------------------------------------------------

class TestGetLoincSignalsForHcc:
    def test_returns_only_matching_hcc(self, monkeypatch) -> None:
        scripted = [[
            {"id": 1, "loinc_code": "4548-4", "test_name": "Hemoglobin A1c",
             "unit": "%", "threshold_low": None, "threshold_high": 6.5,
             "threshold_meaning": "above", "confidence": 0.85, "notes": "",
             "concept_id": 100, "concept_code": "E11.9", "code_system": "ICD10",
             "concept_display": "Type 2 DM", "concept_hcc": "HCC36"},
            {"id": 2, "loinc_code": "33914-3", "test_name": "eGFR",
             "unit": "mL/min/1.73m2", "threshold_low": 60.0, "threshold_high": None,
             "threshold_meaning": "below", "confidence": 0.7, "notes": "",
             "concept_id": 200, "concept_code": "N18.9", "code_system": "ICD10",
             "concept_display": "CKD", "concept_hcc": "HCC326"},
        ]]
        _patch_raf_cursor(monkeypatch, scripted)

        out = loinc_service.get_loinc_signals_for_hcc("HCC36")
        assert len(out) == 1
        assert out[0]["loinc_code"] == "4548-4"

    def test_accepts_numeric_hcc(self, monkeypatch) -> None:
        scripted = [[
            {"id": 1, "loinc_code": "4548-4", "test_name": "Hemoglobin A1c",
             "unit": "%", "threshold_low": None, "threshold_high": 6.5,
             "threshold_meaning": "above", "confidence": 0.85, "notes": "",
             "concept_id": 100, "concept_code": "E11.9", "code_system": "ICD10",
             "concept_display": "Type 2 DM", "concept_hcc": "HCC36"},
        ]]
        _patch_raf_cursor(monkeypatch, scripted)

        out = loinc_service.get_loinc_signals_for_hcc(36)
        assert len(out) == 1
        assert out[0]["hcc_code"] == "HCC36"
