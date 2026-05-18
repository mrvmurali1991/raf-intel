"""
Patient API integration tests.

Tests cover the full set of patient endpoints:
  GET /api/patients/with-encounters
  GET /api/patients/{pid}
  GET /api/patients/{pid}/encounters
  GET /api/patients/{pid}/diagnoses
  GET /api/patients/{pid}/medications
  GET /api/patients/{pid}/clinical-notes/{enc_id}

All tests use live patient data fetched from the running server.  If no
patients with encounters are in the database, patient-specific tests are
skipped rather than failing with cryptic errors.
"""
from __future__ import annotations

import pytest
import requests

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _assert_response_ok(r: requests.Response, context: str = "") -> dict:
    """Assert 200 and return parsed JSON, attaching context on failure."""
    assert r.status_code == 200, (
        f"{context} — expected 200, got {r.status_code}. Body: {r.text[:500]}"
    )
    return r.json()


# ---------------------------------------------------------------------------
# GET /api/patients/with-encounters
# ---------------------------------------------------------------------------

class TestPatientsWithEncounters:
    """Patients that have at least one encounter."""

    def test_endpoint_returns_200(self, api_client: requests.Session, base_url: str):
        r = api_client.get(f"{base_url}/api/patients/with-encounters")
        assert r.status_code == 200, f"Got {r.status_code}: {r.text[:300]}"

    def test_response_has_patients_key(self, api_client: requests.Session, base_url: str):
        r = api_client.get(f"{base_url}/api/patients/with-encounters")
        data = r.json()
        assert "patients" in data, f"Missing 'patients' key in response: {data}"

    def test_response_has_total_key(self, api_client: requests.Session, base_url: str):
        r = api_client.get(f"{base_url}/api/patients/with-encounters")
        data = r.json()
        assert "total" in data, f"Missing 'total' key in response: {data}"

    def test_total_matches_patients_length(self, api_client: requests.Session, base_url: str):
        r = api_client.get(f"{base_url}/api/patients/with-encounters")
        data = r.json()
        assert data["total"] == len(data["patients"]), (
            f"'total' ({data['total']}) does not match len(patients) ({len(data['patients'])})"
        )

    def test_patients_is_a_list(self, api_client: requests.Session, base_url: str):
        r = api_client.get(f"{base_url}/api/patients/with-encounters")
        data = r.json()
        assert isinstance(data["patients"], list), "'patients' must be a list"

    def test_patient_records_have_pid(
        self, api_client: requests.Session, base_url: str, sample_patients: list[dict]
    ):
        """Every returned patient must carry a non-null identifier."""
        if not sample_patients:
            pytest.skip("No patients with encounters in the database.")
        for patient in sample_patients[:10]:  # spot-check first ten
            has_id = (
                patient.get("pid") is not None
                or patient.get("id") is not None
                or patient.get("patient_id") is not None
            )
            assert has_id, f"Patient record missing identifier: {patient}"

    def test_limit_query_param_is_respected(self, api_client: requests.Session, base_url: str):
        """Passing limit=1 should return at most one patient."""
        r = api_client.get(
            f"{base_url}/api/patients/with-encounters", params={"limit": 1}
        )
        assert r.status_code == 200
        data = r.json()
        assert len(data.get("patients", [])) <= 1, (
            f"Expected <= 1 patients with limit=1, got {len(data['patients'])}"
        )


# ---------------------------------------------------------------------------
# GET /api/patients/{pid}
# ---------------------------------------------------------------------------

class TestSinglePatient:
    """Single patient detail endpoint."""

    def test_returns_200_for_valid_pid(
        self, api_client: requests.Session, base_url: str, first_pid: int
    ):
        r = api_client.get(f"{base_url}/api/patients/{first_pid}")
        _assert_response_ok(r, f"GET /api/patients/{first_pid}")

    def test_response_has_demographic_fields(
        self, api_client: requests.Session, base_url: str, first_pid: int
    ):
        """Patient record must expose core demographic fields."""
        r = api_client.get(f"{base_url}/api/patients/{first_pid}")
        data = _assert_response_ok(r)

        required_fields = ["pid", "fname", "lname"]
        for field in required_fields:
            assert field in data, (
                f"Patient {first_pid} response missing '{field}'. Got keys: {list(data)}"
            )

    def test_response_has_raf_score_fields(
        self, api_client: requests.Session, base_url: str, first_pid: int
    ):
        """
        Patient endpoint injects RAF score fields even if no score has been
        calculated yet (values will be None).
        """
        r = api_client.get(f"{base_url}/api/patients/{first_pid}")
        data = _assert_response_ok(r)
        # These keys must be present (value may be None)
        for key in ("raf_score", "raf_score_date", "raf_score_year"):
            assert key in data, (
                f"Patient {first_pid} response missing '{key}'. Got keys: {list(data)}"
            )

    def test_raf_score_is_numeric_or_none(
        self, api_client: requests.Session, base_url: str, first_pid: int
    ):
        r = api_client.get(f"{base_url}/api/patients/{first_pid}")
        data = _assert_response_ok(r)
        raf = data.get("raf_score")
        assert raf is None or isinstance(raf, (int, float)), (
            f"raf_score should be numeric or None, got {type(raf).__name__}: {raf}"
        )

    def test_pid_in_response_matches_request(
        self, api_client: requests.Session, base_url: str, first_pid: int
    ):
        r = api_client.get(f"{base_url}/api/patients/{first_pid}")
        data = _assert_response_ok(r)
        response_pid = data.get("pid") or data.get("id")
        assert int(response_pid) == first_pid, (
            f"Response pid ({response_pid}) does not match requested pid ({first_pid})"
        )

    def test_returns_404_for_nonexistent_pid(
        self, api_client: requests.Session, base_url: str, nonexistent_pid: int
    ):
        r = api_client.get(f"{base_url}/api/patients/{nonexistent_pid}")
        assert r.status_code == 404, (
            f"Expected 404 for nonexistent PID {nonexistent_pid}, got {r.status_code}"
        )

    def test_404_response_has_detail_field(
        self, api_client: requests.Session, base_url: str, nonexistent_pid: int
    ):
        r = api_client.get(f"{base_url}/api/patients/{nonexistent_pid}")
        data = r.json()
        assert "detail" in data, f"404 response should contain 'detail'. Got: {data}"


# ---------------------------------------------------------------------------
# GET /api/patients/{pid}/encounters
# ---------------------------------------------------------------------------

class TestPatientEncounters:

    def test_returns_200(
        self, api_client: requests.Session, base_url: str, first_pid: int
    ):
        r = api_client.get(f"{base_url}/api/patients/{first_pid}/encounters")
        _assert_response_ok(r, f"GET /api/patients/{first_pid}/encounters")

    def test_response_structure(
        self, api_client: requests.Session, base_url: str, first_pid: int
    ):
        r = api_client.get(f"{base_url}/api/patients/{first_pid}/encounters")
        data = _assert_response_ok(r)
        for key in ("pid", "count", "encounters"):
            assert key in data, f"Missing '{key}' in encounters response: {list(data)}"

    def test_pid_matches(
        self, api_client: requests.Session, base_url: str, first_pid: int
    ):
        r = api_client.get(f"{base_url}/api/patients/{first_pid}/encounters")
        data = _assert_response_ok(r)
        assert int(data["pid"]) == first_pid

    def test_count_matches_list_length(
        self, api_client: requests.Session, base_url: str, first_pid: int
    ):
        r = api_client.get(f"{base_url}/api/patients/{first_pid}/encounters")
        data = _assert_response_ok(r)
        assert data["count"] == len(data["encounters"]), (
            f"'count' ({data['count']}) != len(encounters) ({len(data['encounters'])})"
        )

    def test_encounters_is_list(
        self, api_client: requests.Session, base_url: str, first_pid: int
    ):
        r = api_client.get(f"{base_url}/api/patients/{first_pid}/encounters")
        data = _assert_response_ok(r)
        assert isinstance(data["encounters"], list)

    def test_encounter_records_have_id(
        self, api_client: requests.Session, base_url: str, first_pid: int
    ):
        r = api_client.get(f"{base_url}/api/patients/{first_pid}/encounters")
        data = _assert_response_ok(r)
        for enc in data["encounters"][:5]:
            has_id = any(enc.get(k) is not None for k in ("id", "encounter_id", "eid", "encounter"))
            assert has_id, f"Encounter record missing an id field: {enc}"

    def test_returns_404_for_nonexistent_pid(
        self, api_client: requests.Session, base_url: str, nonexistent_pid: int
    ):
        r = api_client.get(f"{base_url}/api/patients/{nonexistent_pid}/encounters")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/patients/{pid}/diagnoses
# ---------------------------------------------------------------------------

class TestPatientDiagnoses:

    def test_returns_200(
        self, api_client: requests.Session, base_url: str, first_pid: int
    ):
        r = api_client.get(f"{base_url}/api/patients/{first_pid}/diagnoses")
        _assert_response_ok(r, f"GET /api/patients/{first_pid}/diagnoses")

    def test_response_structure(
        self, api_client: requests.Session, base_url: str, first_pid: int
    ):
        r = api_client.get(f"{base_url}/api/patients/{first_pid}/diagnoses")
        data = _assert_response_ok(r)
        for key in ("pid", "count", "diagnoses"):
            assert key in data, f"Missing '{key}' in diagnoses response: {list(data)}"

    def test_diagnoses_is_list(
        self, api_client: requests.Session, base_url: str, first_pid: int
    ):
        r = api_client.get(f"{base_url}/api/patients/{first_pid}/diagnoses")
        data = _assert_response_ok(r)
        assert isinstance(data["diagnoses"], list)

    def test_count_matches_list_length(
        self, api_client: requests.Session, base_url: str, first_pid: int
    ):
        r = api_client.get(f"{base_url}/api/patients/{first_pid}/diagnoses")
        data = _assert_response_ok(r)
        assert data["count"] == len(data["diagnoses"])

    def test_diagnosis_records_have_icd10_validation_flag(
        self, api_client: requests.Session, base_url: str, first_pid: int
    ):
        """Diagnoses endpoint enriches records with valid_icd10 flag."""
        r = api_client.get(f"{base_url}/api/patients/{first_pid}/diagnoses")
        data = _assert_response_ok(r)
        for dx in data["diagnoses"][:5]:
            assert "valid_icd10" in dx, (
                f"Diagnosis record missing 'valid_icd10' enrichment: {dx}"
            )

    def test_returns_404_for_nonexistent_pid(
        self, api_client: requests.Session, base_url: str, nonexistent_pid: int
    ):
        r = api_client.get(f"{base_url}/api/patients/{nonexistent_pid}/diagnoses")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/patients/{pid}/medications
# ---------------------------------------------------------------------------

class TestPatientMedications:

    def test_returns_200(
        self, api_client: requests.Session, base_url: str, first_pid: int
    ):
        r = api_client.get(f"{base_url}/api/patients/{first_pid}/medications")
        _assert_response_ok(r, f"GET /api/patients/{first_pid}/medications")

    def test_response_structure(
        self, api_client: requests.Session, base_url: str, first_pid: int
    ):
        r = api_client.get(f"{base_url}/api/patients/{first_pid}/medications")
        data = _assert_response_ok(r)
        for key in ("pid", "count", "medications"):
            assert key in data, f"Missing '{key}' in medications response: {list(data)}"

    def test_medications_is_list(
        self, api_client: requests.Session, base_url: str, first_pid: int
    ):
        r = api_client.get(f"{base_url}/api/patients/{first_pid}/medications")
        data = _assert_response_ok(r)
        assert isinstance(data["medications"], list)

    def test_count_matches_list_length(
        self, api_client: requests.Session, base_url: str, first_pid: int
    ):
        r = api_client.get(f"{base_url}/api/patients/{first_pid}/medications")
        data = _assert_response_ok(r)
        assert data["count"] == len(data["medications"])

    def test_returns_404_for_nonexistent_pid(
        self, api_client: requests.Session, base_url: str, nonexistent_pid: int
    ):
        r = api_client.get(f"{base_url}/api/patients/{nonexistent_pid}/medications")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/patients/{pid}/clinical-notes/{enc_id}
# ---------------------------------------------------------------------------

class TestPatientClinicalNotes:

    def test_returns_200(
        self,
        api_client: requests.Session,
        base_url: str,
        first_pid: int,
        first_encounter_id: int,
    ):
        r = api_client.get(
            f"{base_url}/api/patients/{first_pid}/clinical-notes/{first_encounter_id}"
        )
        _assert_response_ok(
            r,
            f"GET /api/patients/{first_pid}/clinical-notes/{first_encounter_id}",
        )

    def test_response_structure(
        self,
        api_client: requests.Session,
        base_url: str,
        first_pid: int,
        first_encounter_id: int,
    ):
        r = api_client.get(
            f"{base_url}/api/patients/{first_pid}/clinical-notes/{first_encounter_id}"
        )
        data = _assert_response_ok(r)
        for key in ("pid", "encounter_id", "count", "notes"):
            assert key in data, (
                f"Missing '{key}' in clinical-notes response. Got keys: {list(data)}"
            )

    def test_pids_match(
        self,
        api_client: requests.Session,
        base_url: str,
        first_pid: int,
        first_encounter_id: int,
    ):
        r = api_client.get(
            f"{base_url}/api/patients/{first_pid}/clinical-notes/{first_encounter_id}"
        )
        data = _assert_response_ok(r)
        assert int(data["pid"]) == first_pid
        assert int(data["encounter_id"]) == first_encounter_id

    def test_notes_is_list(
        self,
        api_client: requests.Session,
        base_url: str,
        first_pid: int,
        first_encounter_id: int,
    ):
        r = api_client.get(
            f"{base_url}/api/patients/{first_pid}/clinical-notes/{first_encounter_id}"
        )
        data = _assert_response_ok(r)
        assert isinstance(data["notes"], list)
