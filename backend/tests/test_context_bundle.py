"""Unit tests for app.services.ai_pipeline.context_bundle.

Uses a FakeCursor that replays canned rowsets per SQL prefix so no real DB
connection is needed.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.services.ai_pipeline.context_bundle import (
    DEFAULT_HCC_MODEL_VERSION,
    assemble_bundle,
    to_llm_payload,
)


class FakeCursor:
    """Minimal dict-cursor that returns canned rows based on SQL keyword match."""

    def __init__(self, fixtures: dict[str, list[dict]]):
        self.fixtures = fixtures
        self._last: list[dict] = []
        self._patient_fetch_idx = 0

    def execute(self, sql: str, params=()):  # noqa: D401
        s = sql.lower()
        if "from patients" in s:
            self._last = list(self.fixtures.get("patients", []))
        elif "from fhir_conditions" in s:
            self._last = list(self.fixtures.get("conditions", []))
        elif "from fhir_encounters" in s:
            self._last = list(self.fixtures.get("encounters", []))
        elif "from encounters" in s and "fhir_" not in s:
            self._last = list(self.fixtures.get("legacy_encounters", []))
        elif "from fhir_observations" in s:
            self._last = list(self.fixtures.get("labs", []))
        elif "from patient_medications" in s:
            self._last = list(self.fixtures.get("meds", []))
        elif "from form_clinical_notes" in s:
            self._last = list(self.fixtures.get("notes", []))
        elif "from encounter_diagnoses" in s:
            self._last = list(self.fixtures.get("legacy_problems", []))
        else:
            self._last = []

    def fetchone(self):
        return self._last[0] if self._last else None

    def fetchall(self):
        return list(self._last)


@pytest.fixture
def fake_patient_fixtures():
    today = date(2026, 4, 16)
    return {
        "patients": [{
            "id": 42,
            "first_name": "Jane",
            "last_name": "Doe",
            "dob": date(1955, 3, 10),
            "sex": "F",
            "mrn": "MRN-42",
            "emr_pid": "fhir-uuid-abc",
            "data_source": "fhir",
        }],
        "conditions": [
            {"icd10_codes": "E11.9", "display": "Type 2 diabetes",
             "onset_date": date(2020, 1, 15), "clinical_status": "active"},
            {"icd10_codes": "I10", "display": "Hypertension",
             "onset_date": date(2019, 6, 1), "clinical_status": "active"},
        ],
        "encounters": [
            {"encounter_date": date(2026, 2, 1), "status": "finished",
             "encounter_type": "AMB", "type_display": "Office visit",
             "provider_name": "Dr. Smith"},
        ],
        "labs": [
            {"code": "2345-7", "code_display": "Glucose",
             "value_numeric": 145.0, "value_string": None, "unit": "mg/dL",
             "effective_date": date(2026, 1, 10), "status": "high"},
            {"code": "4548-4", "code_display": "HbA1c",
             "value_numeric": 5.4, "value_string": None, "unit": "%",
             "effective_date": date(2025, 8, 1), "status": "final"},
        ],
        "meds": [
            {"medication_name": "Metformin 500mg",
             "fhir_id": "rx-1", "start_date": date(2023, 1, 1),
             "status": "active"},
        ],
        "notes": [
            {"id": 101, "pid": "emr-pid", "encounter": 1,
             "date": date(2026, 3, 1), "note_type": "progress",
             "note_text": "Patient reports improved BG control."},
        ],
    }


def test_assemble_bundle_shape(fake_patient_fixtures):
    cur = FakeCursor(fake_patient_fixtures)
    bundle = assemble_bundle(
        patient_id=42,
        cutoff_date=date(2025, 4, 16),
        mode="full",
        measurement_year=2026,
        cursor=cur,
    )
    assert bundle.patient_id == "42"
    assert bundle.measurement_year == 2026
    assert bundle.hcc_model_version == DEFAULT_HCC_MODEL_VERSION
    assert bundle.demographics.sex == "F"
    assert bundle.demographics.age and bundle.demographics.age >= 70
    assert len(bundle.active_problem_list) == 2
    assert bundle.active_problem_list[0].icd10 == "E11.9"
    assert len(bundle.prior_encounters_this_year) == 1
    assert len(bundle.recent_labs_12mo) == 2
    assert len(bundle.active_medications) == 1
    assert len(bundle.clinical_notes) == 1
    assert "form_clinical_notes" in bundle.meta.source_tables


def test_abnormal_only_mode_filters_labs(fake_patient_fixtures):
    cur = FakeCursor(fake_patient_fixtures)
    bundle = assemble_bundle(
        patient_id=42,
        cutoff_date=date(2025, 4, 16),
        mode="abnormal_only",
        measurement_year=2026,
        cursor=cur,
    )
    assert len(bundle.recent_labs_12mo) == 1
    assert bundle.recent_labs_12mo[0].abnormal_flag is True
    assert bundle.recent_labs_12mo[0].code == "2345-7"


def test_to_llm_payload_keys(fake_patient_fixtures):
    cur = FakeCursor(fake_patient_fixtures)
    bundle = assemble_bundle(
        patient_id=42, cutoff_date=date(2025, 4, 16),
        measurement_year=2026, cursor=cur,
    )
    payload = to_llm_payload(bundle)
    assert list(payload.keys())[:5] == [
        "patient_id", "measurement_year", "hcc_model_version",
        "cutoff_date", "mode",
    ]
    assert "demographics" in payload
    assert "clinical_notes" in payload
    assert "meta" in payload


def test_token_budget_trims_notes_and_labs(fake_patient_fixtures):
    # Pump 50 large notes and 50 non-abnormal labs into fixtures.
    big = dict(fake_patient_fixtures)
    big["notes"] = [
        {"id": i, "pid": "emr-pid", "encounter": i,
         "date": date(2025, 6, 1) + timedelta(days=i),
         "note_type": "progress",
         "note_text": "X" * 2000}
        for i in range(50)
    ]
    big["labs"] = [
        {"code": f"L-{i}", "code_display": "Panel",
         "value_numeric": float(i), "value_string": None, "unit": "x",
         "effective_date": date(2025, 6, 1) + timedelta(days=i),
         "status": "final"}
        for i in range(50)
    ]
    cur = FakeCursor(big)
    bundle = assemble_bundle(
        patient_id=42, cutoff_date=date(2025, 1, 1),
        mode="full", measurement_year=2026,
        cursor=cur, token_budget_chars=5_000,
    )
    assert bundle.meta.trimmed_notes > 0 or bundle.meta.trimmed_labs > 0
    assert bundle.meta.char_count <= 5_000 or len(bundle.clinical_notes) == 0


def test_no_fhir_patient_falls_back_to_legacy_problems():
    fx = {
        "patients": [{
            "id": 7, "first_name": "Bob", "last_name": "Legacy",
            "dob": date(1960, 1, 1), "sex": "M", "mrn": "L-7",
            "emr_pid": "999", "data_source": "emr",
        }],
        "legacy_problems": [
            {"icd10": "J44.9", "display": "COPD",
             "onset_date": date(2021, 5, 1)},
        ],
    }
    cur = FakeCursor(fx)
    bundle = assemble_bundle(
        patient_id=7, cutoff_date=date(2025, 1, 1),
        measurement_year=2026, cursor=cur,
    )
    assert len(bundle.active_problem_list) == 1
    assert bundle.active_problem_list[0].icd10 == "J44.9"
    assert bundle.active_problem_list[0].clinical_status == "active"
