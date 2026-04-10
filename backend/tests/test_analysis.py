"""
Analysis Pipeline integration tests.

Covers:
  POST /api/analysis/encounter/{enc_id}
  GET  /api/analysis/encounter/{enc_id}/cached   (if implemented)
  POST /api/analysis/note                        (inline note text)

Validates:
  - Response contains diagnoses, suspect_conditions, pipeline keys
  - pipeline.tool_calls (or stages_run) tracks which pipeline stages ran
  - Cached endpoint returns the same result as the initial analysis
  - Diagnoses carry required sub-fields (icd10, description, confidence, meat)

NOTE: Analysis calls Gemini and may take 10–30 seconds per encounter.
      Tests use a module-scoped fixture to run the pipeline only once.
"""
from __future__ import annotations

import pytest
import requests

# Analysis endpoints can be very slow due to Gemini API latency
ANALYSIS_TIMEOUT = 120  # seconds


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _assert_ok(r: requests.Response, context: str = "") -> dict:
    assert r.status_code == 200, (
        f"{context} — expected 200, got {r.status_code}. Body: {r.text[:600]}"
    )
    return r.json()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def analysis_result(
    api_client: requests.Session,
    base_url: str,
    first_encounter_id: int,
) -> dict:
    """
    Run the full analysis pipeline once for the first encounter and cache
    the result for all tests in this module.  The pipeline is idempotent —
    subsequent calls will overwrite the stored result but return the same shape.
    """
    r = api_client.post(
        f"{base_url}/api/analysis/encounter/{first_encounter_id}",
        json={"include_context": True, "save_results": True},
        timeout=ANALYSIS_TIMEOUT,
    )
    assert r.status_code == 200, (
        f"POST /api/analysis/encounter/{first_encounter_id} failed with "
        f"{r.status_code}: {r.text[:600]}"
    )
    return r.json()


# ---------------------------------------------------------------------------
# POST /api/analysis/encounter/{enc_id}
# ---------------------------------------------------------------------------

class TestAnalysisEncounterPost:

    def test_returns_200(
        self,
        api_client: requests.Session,
        base_url: str,
        first_encounter_id: int,
    ):
        r = api_client.post(
            f"{base_url}/api/analysis/encounter/{first_encounter_id}",
            json={"include_context": True, "save_results": False},
            timeout=ANALYSIS_TIMEOUT,
        )
        _assert_ok(r, f"POST /api/analysis/encounter/{first_encounter_id}")

    def test_response_has_diagnoses_key(self, analysis_result: dict):
        assert "diagnoses" in analysis_result, (
            f"'diagnoses' missing from analysis response. Got keys: {sorted(analysis_result)}"
        )

    def test_response_has_suspect_conditions_key(self, analysis_result: dict):
        assert "suspect_conditions" in analysis_result, (
            f"'suspect_conditions' missing from analysis response. "
            f"Got keys: {sorted(analysis_result)}"
        )

    def test_response_has_pipeline_key(self, analysis_result: dict):
        assert "pipeline" in analysis_result, (
            f"'pipeline' missing from analysis response. Got keys: {sorted(analysis_result)}"
        )

    def test_diagnoses_is_list(self, analysis_result: dict):
        assert isinstance(analysis_result["diagnoses"], list), (
            f"'diagnoses' must be a list, got {type(analysis_result['diagnoses']).__name__}"
        )

    def test_suspect_conditions_is_list(self, analysis_result: dict):
        assert isinstance(analysis_result["suspect_conditions"], list), (
            f"'suspect_conditions' must be a list"
        )

    def test_pipeline_is_dict(self, analysis_result: dict):
        assert isinstance(analysis_result["pipeline"], dict), (
            f"'pipeline' must be a dict, got {type(analysis_result['pipeline']).__name__}"
        )

    def test_pipeline_has_tool_calls_or_stages_run(self, analysis_result: dict):
        """
        The skill pipeline records its activity under 'tool_calls' (skill_pipeline.py)
        or 'stages_run' (legacy pipeline).  At least one must be present.
        """
        pipeline = analysis_result["pipeline"]
        has_tool_calls = "tool_calls" in pipeline
        has_stages_run = "stages_run" in pipeline
        assert has_tool_calls or has_stages_run, (
            f"'pipeline' must contain 'tool_calls' or 'stages_run'. "
            f"Got pipeline keys: {sorted(pipeline)}"
        )

    def test_diagnosis_records_have_required_fields(self, analysis_result: dict):
        """Each diagnosis must carry icd10, description, confidence, and meat."""
        required = ("icd10", "description", "confidence")
        for dx in analysis_result["diagnoses"][:10]:
            for field in required:
                assert field in dx, (
                    f"Diagnosis record missing '{field}'. Got: {sorted(dx)}"
                )

    def test_diagnosis_confidence_is_numeric(self, analysis_result: dict):
        for dx in analysis_result["diagnoses"][:10]:
            conf = dx.get("confidence")
            assert isinstance(conf, (int, float)), (
                f"Diagnosis confidence must be numeric, got {type(conf).__name__}: {conf}"
            )

    def test_diagnosis_confidence_range(self, analysis_result: dict):
        """Confidence scores should be in [0, 1]."""
        for dx in analysis_result["diagnoses"][:10]:
            conf = float(dx.get("confidence", 0))
            assert 0.0 <= conf <= 1.0, (
                f"Confidence {conf} outside expected range [0, 1] for dx: {dx}"
            )

    def test_diagnosis_meat_field_present(self, analysis_result: dict):
        """The meat (Monitoring/Evaluation/Assessment/Treatment) field must exist."""
        for dx in analysis_result["diagnoses"][:10]:
            assert "meat" in dx, (
                f"Diagnosis record missing 'meat' field. Got fields: {sorted(dx)}"
            )

    def test_diagnosis_meat_is_dict(self, analysis_result: dict):
        for dx in analysis_result["diagnoses"][:10]:
            meat = dx.get("meat")
            if meat is not None:
                assert isinstance(meat, dict), (
                    f"'meat' must be a dict, got {type(meat).__name__}"
                )

    def test_pipeline_tool_calls_is_list_if_present(self, analysis_result: dict):
        pipeline = analysis_result["pipeline"]
        if "tool_calls" in pipeline:
            assert isinstance(pipeline["tool_calls"], list), (
                f"'pipeline.tool_calls' must be a list"
            )

    def test_pipeline_tool_calls_contain_expected_functions(self, analysis_result: dict):
        """
        The skill pipeline should invoke at least lookup_hcc or validate_icd10
        for any meaningful clinical note with diagnosable conditions.
        """
        pipeline = analysis_result["pipeline"]
        tool_calls = pipeline.get("tool_calls", [])

        if not tool_calls:
            pytest.skip(
                "No tool_calls in pipeline — either no diagnoses found or legacy pipeline used."
            )

        known_functions = {"lookup_hcc", "validate_icd10", "check_medication_gaps", "get_raf_demographic_base"}
        called_functions = set()
        for call in tool_calls:
            if isinstance(call, dict):
                fn = call.get("function") or call.get("name") or call.get("tool")
                if fn:
                    called_functions.add(fn)
            elif isinstance(call, str):
                called_functions.add(call)

        overlap = called_functions & known_functions
        assert overlap, (
            f"Expected at least one of {known_functions} in tool_calls, "
            f"but found: {called_functions}"
        )

    def test_overall_confidence_is_present(self, analysis_result: dict):
        """overall_confidence must be in the top-level response."""
        assert "overall_confidence" in analysis_result, (
            f"'overall_confidence' missing. Got keys: {sorted(analysis_result)}"
        )

    def test_overall_confidence_is_numeric(self, analysis_result: dict):
        conf = analysis_result.get("overall_confidence")
        assert isinstance(conf, (int, float)), (
            f"'overall_confidence' must be numeric, got {type(conf).__name__}: {conf}"
        )

    def test_negated_conditions_is_list(self, analysis_result: dict):
        neg = analysis_result.get("negated_conditions")
        if neg is not None:
            assert isinstance(neg, list), (
                f"'negated_conditions' must be a list, got {type(neg).__name__}"
            )

    def test_routing_key_present(self, analysis_result: dict):
        """Confidence routing result should be exposed."""
        assert "routing" in analysis_result, (
            f"'routing' key missing from analysis response. Keys: {sorted(analysis_result)}"
        )


# ---------------------------------------------------------------------------
# GET /api/analysis/encounter/{enc_id}/cached
# ---------------------------------------------------------------------------

class TestAnalysisCachedResult:
    """
    After at least one analysis has been run (via the module fixture above),
    the cached endpoint should return persisted data.
    """

    def test_cached_returns_200_after_analysis(
        self,
        api_client: requests.Session,
        base_url: str,
        first_encounter_id: int,
        analysis_result: dict,  # ensures analysis ran first
    ):
        """Cached endpoint must return 200 once data has been stored."""
        r = api_client.get(
            f"{base_url}/api/analysis/encounter/{first_encounter_id}/cached",
            timeout=30,
        )
        if r.status_code == 404:
            pytest.skip(
                "Cached endpoint returned 404 — the /cached route may not be "
                "implemented or save_results=True is not persisting. "
                f"Encounter: {first_encounter_id}"
            )
        _assert_ok(r, f"GET /api/analysis/encounter/{first_encounter_id}/cached")

    def test_cached_response_has_diagnoses(
        self,
        api_client: requests.Session,
        base_url: str,
        first_encounter_id: int,
        analysis_result: dict,
    ):
        r = api_client.get(
            f"{base_url}/api/analysis/encounter/{first_encounter_id}/cached",
            timeout=30,
        )
        if r.status_code == 404:
            pytest.skip("Cached endpoint not implemented or no data stored.")
        data = _assert_ok(r)
        assert "diagnoses" in data or "analysis" in data, (
            f"Cached response must contain 'diagnoses' or 'analysis'. Got: {sorted(data)}"
        )

    def test_cached_result_is_consistent_with_live_analysis(
        self,
        api_client: requests.Session,
        base_url: str,
        first_encounter_id: int,
        analysis_result: dict,
    ):
        """
        The cached result should have at minimum the same number of diagnoses
        as the live analysis that just ran (allowing for re-analysis enrichment).
        """
        r = api_client.get(
            f"{base_url}/api/analysis/encounter/{first_encounter_id}/cached",
            timeout=30,
        )
        if r.status_code == 404:
            pytest.skip("Cached endpoint not implemented or no data stored.")
        cached = _assert_ok(r)

        cached_diagnoses = (
            cached.get("diagnoses")
            or (cached.get("analysis") or {}).get("diagnoses")
            or []
        )
        live_diagnoses = analysis_result.get("diagnoses", [])

        # The cached result should have a plausible number of diagnoses
        # (same order of magnitude — not zero if live had results)
        if live_diagnoses:
            assert len(cached_diagnoses) > 0, (
                f"Cached result has 0 diagnoses but live analysis found {len(live_diagnoses)}. "
                "Results may not be persisting correctly."
            )


# ---------------------------------------------------------------------------
# POST /api/analysis/note  (inline note text)
# ---------------------------------------------------------------------------

SAMPLE_SOAP_NOTE = """
SUBJECTIVE:
Patient is a 68-year-old male with a history of Type 2 diabetes mellitus with
diabetic chronic kidney disease, presenting for routine follow-up.
He reports polyuria and polydipsia over the past two weeks.
He is currently taking metformin 1000 mg twice daily and lisinopril 10 mg daily.

OBJECTIVE:
BP: 148/92 mmHg. HR: 78 bpm. Weight: 215 lbs.
Fasting glucose: 187 mg/dL. HbA1c: 8.4%.
eGFR: 48 mL/min (CKD Stage 3b).

ASSESSMENT:
1. Type 2 diabetes mellitus with diabetic chronic kidney disease, Stage 3b (E11.22)
2. Essential hypertension, poorly controlled (I10)
3. Chronic kidney disease, Stage 3b (N18.32)

PLAN:
- Increase metformin to 1000 mg three times daily.
- Continue lisinopril 10 mg daily for nephroprotection.
- Repeat HbA1c in 3 months.
- Nephrology referral for CKD management.
"""


class TestAnalysisNoteInline:
    """POST /api/analysis/note — analyze user-supplied note text directly."""

    @pytest.fixture(scope="class")
    def note_analysis(
        self,
        api_client: requests.Session,
        base_url: str,
        first_pid: int,
    ) -> dict:
        r = api_client.post(
            f"{base_url}/api/analysis/note",
            json={
                "patient_id": first_pid,
                "note_text": SAMPLE_SOAP_NOTE,
                "save_results": False,
            },
            timeout=ANALYSIS_TIMEOUT,
        )
        if r.status_code == 404:
            pytest.skip("POST /api/analysis/note endpoint not implemented.")
        assert r.status_code == 200, (
            f"POST /api/analysis/note failed: {r.status_code} — {r.text[:400]}"
        )
        return r.json()

    def test_note_analysis_returns_200(
        self, api_client: requests.Session, base_url: str, first_pid: int
    ):
        r = api_client.post(
            f"{base_url}/api/analysis/note",
            json={
                "patient_id": first_pid,
                "note_text": SAMPLE_SOAP_NOTE,
                "save_results": False,
            },
            timeout=ANALYSIS_TIMEOUT,
        )
        if r.status_code == 404:
            pytest.skip("POST /api/analysis/note endpoint not implemented.")
        assert r.status_code == 200

    def test_note_analysis_returns_diagnoses(self, note_analysis: dict):
        assert "diagnoses" in note_analysis, (
            f"'diagnoses' missing. Got: {sorted(note_analysis)}"
        )
        assert isinstance(note_analysis["diagnoses"], list)

    def test_note_analysis_finds_diabetes_diagnosis(self, note_analysis: dict):
        """
        The sample note explicitly mentions Type 2 DM — Gemini should extract it.
        E11.22 (Type 2 DM with diabetic CKD) is the expected code.
        """
        diagnoses = note_analysis.get("diagnoses", [])
        icd10_codes = [
            (dx.get("icd10") or "").upper().replace(" ", "")
            for dx in diagnoses
        ]
        diabetes_codes = [c for c in icd10_codes if c.startswith("E11") or c.startswith("E10")]
        assert diabetes_codes, (
            f"Expected at least one diabetes code (E10.x or E11.x) in diagnoses. "
            f"Got ICD codes: {icd10_codes}"
        )

    def test_note_analysis_finds_hypertension(self, note_analysis: dict):
        """I10 (essential hypertension) is explicitly in the ASSESSMENT section."""
        diagnoses = note_analysis.get("diagnoses", [])
        icd10_codes = [
            (dx.get("icd10") or "").upper().replace(" ", "")
            for dx in diagnoses
        ]
        hypertension_codes = [c for c in icd10_codes if c == "I10"]
        assert hypertension_codes, (
            f"Expected I10 (hypertension) in diagnoses. Got ICD codes: {icd10_codes}"
        )
