"""
Unit tests for the bulk FHIR ingest pipeline.

The full ingest path writes to MySQL (patients, raf_patient_hcc,
normalized_encounters), publishes to Redis, and calls the RAF calculator —
none of which we want to spin up for a unit test.  The cursor is mocked
with the same pattern as ``test_hcc_hierarchy.py`` so we exercise the
NDJSON parsing, batching, and FHIR → row conversion logic in isolation.
"""
from __future__ import annotations

import io
import json
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from app.services import bulk_ingest_service
from app.services.bulk_ingest_service import (
    _condition_icd10,
    _condition_patient_ref,
    _encounter_to_row,
    _patient_to_row,
    generate_synthetic_ndjson,
)


# ---------------------------------------------------------------------------
# Resource → row converters
# ---------------------------------------------------------------------------

def test_patient_to_row_extracts_core_fields() -> None:
    patient = {
        "resourceType": "Patient",
        "id": "p1",
        "name": [{"family": "Smith", "given": ["Jane", "A"]}],
        "gender": "female",
        "birthDate": "1955-06-12",
        "identifier": [
            {"type": {"coding": [{"code": "MR"}]}, "value": "MRN001"},
            {"system": "http://hl7.org/fhir/sid/us-mbi", "value": "1AB2C34D56E"},
        ],
        "address": [{"line": ["1 Main"], "city": "X", "state": "IL", "postalCode": "12345"}],
        "telecom": [{"system": "phone", "value": "555-1212"}],
    }
    row = _patient_to_row(patient)
    assert row is not None
    assert row["first_name"] == "Jane"
    assert row["last_name"] == "Smith"
    assert row["dob"] == "1955-06-12"
    assert row["gender"] == "F"
    assert row["mrn"] == "MRN001"
    assert row["mbi"] == "1AB2C34D56E"
    assert row["fhir_id"] == "p1"
    assert row["state"] == "IL"


def test_patient_to_row_rejects_missing_dob() -> None:
    assert _patient_to_row({"resourceType": "Patient", "name": [{"family": "X", "given": ["Y"]}]}) is None


def test_condition_extractors() -> None:
    condition = {
        "resourceType": "Condition",
        "id": "c1",
        "subject": {"reference": "Patient/p1"},
        "code": {
            "coding": [
                {"system": "http://hl7.org/fhir/sid/icd-10-cm", "code": "E11.9", "display": "Type 2 diabetes"}
            ]
        },
    }
    code, desc = _condition_icd10(condition)
    assert code == "E11.9"
    assert desc == "Type 2 diabetes"
    assert _condition_patient_ref(condition) == "p1"


def test_encounter_to_row() -> None:
    enc = {
        "resourceType": "Encounter",
        "id": "e1",
        "subject": {"reference": "Patient/p1"},
        "class": {"code": "AMB"},
        "period": {"start": "2025-03-10T08:00:00Z"},
    }
    row = _encounter_to_row(enc)
    assert row is not None
    assert row["encounter_date"] == "2025-03-10"
    assert row["encounter_type"] == "AMB"
    assert row["patient_fhir_id"] == "p1"


# ---------------------------------------------------------------------------
# Synthetic generator + end-to-end (mocked DB)
# ---------------------------------------------------------------------------

def test_synthetic_ndjson_shape() -> None:
    blob = generate_synthetic_ndjson(patient_count=10, conditions_per_patient=3)
    lines = blob.decode("utf-8").splitlines()
    # 10 patients + 30 conditions
    assert len(lines) == 40
    parsed = [json.loads(l) for l in lines]
    patients = [r for r in parsed if r["resourceType"] == "Patient"]
    conditions = [r for r in parsed if r["resourceType"] == "Condition"]
    assert len(patients) == 10
    assert len(conditions) == 30
    # Each Condition points back to a Patient that exists in the file
    patient_ids = {p["id"] for p in patients}
    for c in conditions:
        assert c["subject"]["reference"].split("/", 1)[1] in patient_ids


def _cursor_mock(lastrowid_seq: list[int]):
    """Build a mock cursor whose ``lastrowid`` walks through *lastrowid_seq*."""
    cursor = MagicMock()
    cursor.fetchall.return_value = []
    cursor.fetchone.return_value = None
    cursor.rowcount = 0

    idx = {"i": 0}

    def _exec(*_a, **_kw):
        cursor.lastrowid = lastrowid_seq[idx["i"] % len(lastrowid_seq)]
        idx["i"] += 1

    cursor.execute.side_effect = _exec
    return cursor


def test_full_ingest_against_mocked_db(monkeypatch) -> None:
    """Run the streaming ingest against a fully mocked raf_cursor and
    confirm the accumulator counts the right number of resources."""
    # Stub the HCC mapping so every condition maps to HCC "37" — this lets
    # us assert the executemany count without depending on hccinfhir's
    # internal table.
    monkeypatch.setattr(
        "app.services.bulk_ingest_service.map_icd10_batch",
        lambda codes, model_version="V28": {
            c.replace(".", "").upper(): {
                "icd10_code": c.replace(".", "").upper(),
                "hcc_code": "37",
                "hcc_codes": ["37"],
                "model_version": model_version,
                "model": "v28",
            }
            for c in codes
        },
        raising=False,
    )

    # Mock raf_cursor — pretend every patient INSERT auto-assigns ids 1, 2, 3…
    cursor = _cursor_mock(list(range(1, 100)))

    @contextmanager
    def _cm(*_a, **_kw):
        yield cursor

    # Disable the RAF calculator — already covered by its own tests.
    monkeypatch.setattr(
        "app.services.bulk_ingest_service._BatchAccumulator._run_raf_batch",
        lambda self: None,
    )

    # Don't actually hit Redis.
    monkeypatch.setattr(
        bulk_ingest_service, "_publish_progress", lambda *_a, **_kw: None
    )
    monkeypatch.setattr(bulk_ingest_service, "_update_job", lambda *_a, **_kw: None)

    blob = generate_synthetic_ndjson(patient_count=20, conditions_per_patient=4)

    with patch("app.services.bulk_ingest_service.raf_cursor", _cm):
        # Patch the late-bound import inside _flush_conditions too.
        with patch("app.services.hcc_mapping_service.map_icd10_batch") as m:
            m.side_effect = lambda codes, model_version="V28": {
                c.replace(".", "").upper(): {
                    "icd10_code": c.replace(".", "").upper(),
                    "hcc_code": "37",
                    "hcc_codes": ["37"],
                    "model_version": model_version,
                    "model": "v28",
                }
                for c in codes
            }
            acc = bulk_ingest_service._ingest_ndjson_stream(
                io.BytesIO(blob),
                job_id="test-job",
                tenant_id="1",
                resource_types={"Patient", "Condition", "Encounter", "Observation"},
            )

    assert acc.counts["Patient"] == 20
    # Every synthetic ICD-10 was mapped to HCC 37, so all conditions land.
    assert acc.counts["Condition"] == 80
    assert acc.counts["Encounter"] == 0
    assert acc.errors == [] or all("RAF calc" not in e for e in acc.errors)
