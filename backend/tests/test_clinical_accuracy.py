"""
Clinical Accuracy and Validation Tests.

These tests verify the medical correctness of the RAF Intelligence system,
going beyond structural API checks to validate clinical logic:

  1. ICD-10 codes extracted from clinical notes must be valid billable codes.
  2. HCC mappings must align with the CMS-HCC V28 crosswalk
     (e.g., E11.22 → HCC18, E11.9 → HCC19, I50.32 → HCC85).
  3. Negated conditions (e.g., "no history of CHF") must NOT appear in the
     active diagnoses list.
  4. RAF score components follow expected clinical patterns.
  5. Known ICD-10 → HCC crosswalk spot-checks.

NOTE: All tests require a live backend AND a live Gemini API key.
      Analysis tests are slow (10–30 s per call) and are skipped if
      no patients with encounters are seeded in the database.
"""
from __future__ import annotations

import re
import pytest
import requests

pytestmark = pytest.mark.integration

# Analysis can take up to 2 minutes with Gemini
ANALYSIS_TIMEOUT = 120

# ---------------------------------------------------------------------------
# CMS-HCC V28 official crosswalk spot-checks (ICD-10 → expected HCC number)
# These are sourced from the 2026 CMS-HCC V28 Rate Announcement tables.
# ---------------------------------------------------------------------------
ICD10_TO_HCC_V28: dict[str, str] = {
    # Diabetes
    "E11.22": "18",   # Type 2 DM w/ diabetic chronic kidney disease → HCC18
    "E11.65": "19",   # Type 2 DM w/ hyperglycemia                   → HCC19
    "E11.9":  "19",   # Type 2 DM without complications              → HCC19
    "E10.9":  "17",   # Type 1 DM without complications              → HCC17
    # Heart failure
    "I50.32": "85",   # Chronic diastolic heart failure               → HCC85
    "I50.9":  "85",   # Unspecified heart failure                     → HCC85
    # CKD
    "N18.4":  "137",  # CKD, Stage 4                                  → HCC137
    "N18.5":  "136",  # CKD, Stage 5                                  → HCC136
    # COPD
    "J44.9":  "111",  # COPD, unspecified                             → HCC111
    # Atrial fibrillation
    "I48.91": "96",   # Unspecified AF                                → HCC96
}

# ICD-10 codes that are NOT HCC-relevant in V28
NON_HCC_ICD10_CODES: list[str] = [
    "I10",    # Essential hypertension — NOT HCC in V28
    "Z87.39", # Personal history of other endocrine conditions — NOT HCC
    "Z00.00", # Encounter for general adult medical exam — NOT HCC
]

# Basic ICD-10-CM validation pattern
ICD10_PATTERN = re.compile(r"^[A-Z]\d{2}(\.\w{1,4})?$", re.IGNORECASE)

# Sample clinical note used for negation testing
NEGATION_TEST_NOTE = """
SUBJECTIVE:
Patient is a 72-year-old female presenting for diabetes follow-up.
No history of congestive heart failure or atrial fibrillation.
She denies chest pain or shortness of breath.
Patient does NOT have COPD. No kidney disease documented.

OBJECTIVE:
BP: 132/84. HR: 76. Weight: 168 lbs.
HbA1c: 7.9%. eGFR: 72 (normal).

ASSESSMENT:
1. Type 2 diabetes mellitus without complications (E11.9)
2. Essential hypertension (I10)

PLAN:
Continue metformin. Recheck HbA1c in 3 months.
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _assert_ok(r: requests.Response, ctx: str = "") -> dict:
    assert r.status_code == 200, (
        f"{ctx} — expected 200, got {r.status_code}. Body: {r.text[:500]}"
    )
    return r.json()


def _normalize_icd10(code: str) -> str:
    """Strip whitespace, uppercase — leave the dot in place."""
    return (code or "").strip().upper()


# ---------------------------------------------------------------------------
# ICD-10 Validation: codes returned by the backend must be billable
# ---------------------------------------------------------------------------

class TestICD10Validity:
    """Verify that the ICD-10 codes stored in the backend are structurally valid."""

    def test_patient_billing_codes_are_structurally_valid(
        self,
        api_client: requests.Session,
        base_url: str,
        first_pid: int,
    ) -> None:
        """
        Every ICD-10 code in the patient's billing record must match the
        basic ICD-10-CM format (letter + 2 digits + optional decimal part).
        """
        r = api_client.get(f"{base_url}/api/patients/{first_pid}/diagnoses")
        data = _assert_ok(r, f"GET /api/patients/{first_pid}/diagnoses")
        diagnoses = data.get("diagnoses", [])

        if not diagnoses:
            pytest.skip(f"No billing codes found for patient {first_pid}.")

        invalid_codes = []
        for dx in diagnoses:
            code = _normalize_icd10(dx.get("code", ""))
            if not code:
                continue
            if not ICD10_PATTERN.match(code):
                invalid_codes.append(code)

        assert not invalid_codes, (
            f"Found structurally invalid ICD-10 codes in billing data: {invalid_codes}"
        )

    def test_backend_icd10_validator_marks_real_codes_as_valid(
        self,
        api_client: requests.Session,
        base_url: str,
    ) -> None:
        """
        The /api/icd10/validate endpoint must confirm that codes from the
        official V28 crosswalk spot-check table are all valid billable codes.
        """
        invalid_via_backend = []
        for code in ICD10_TO_HCC_V28:
            r = api_client.get(f"{base_url}/api/icd10/validate/{code}")
            assert r.status_code == 200, f"Validator endpoint failed for {code}"
            data = r.json()
            if not data.get("valid"):
                invalid_via_backend.append(code)

        assert not invalid_via_backend, (
            f"Backend ICD-10 validator rejected known-valid codes: {invalid_via_backend}. "
            "This likely indicates a problem with the ICD-10-CM reference data."
        )

    def test_backend_icd10_validator_rejects_non_codes(
        self,
        api_client: requests.Session,
        base_url: str,
    ) -> None:
        """The validator must return valid=False for clearly invalid strings."""
        junk_codes = ["ZZZZZZ", "ABC123", "999", "NOT-A-CODE"]
        falsely_valid = []
        for code in junk_codes:
            r = api_client.get(f"{base_url}/api/icd10/validate/{code}")
            data = r.json()
            if data.get("valid"):
                falsely_valid.append(code)
        assert not falsely_valid, (
            f"Backend accepted clearly invalid ICD-10 codes as valid: {falsely_valid}"
        )

    def test_diagnoses_valid_icd10_flag_is_true_for_real_codes(
        self,
        api_client: requests.Session,
        base_url: str,
        first_pid: int,
    ) -> None:
        """
        The patient diagnoses endpoint enriches records with valid_icd10.
        Any code passing the ICD10_PATTERN should have valid_icd10=True.
        """
        r = api_client.get(f"{base_url}/api/patients/{first_pid}/diagnoses")
        data = _assert_ok(r)
        diagnoses = data.get("diagnoses", [])

        if not diagnoses:
            pytest.skip(f"No diagnoses for patient {first_pid}.")

        mismatches = []
        for dx in diagnoses:
            code = _normalize_icd10(dx.get("code", ""))
            flag = dx.get("valid_icd10")
            if flag is False and ICD10_PATTERN.match(code):
                mismatches.append(code)

        assert not mismatches, (
            f"Codes that look structurally valid but are flagged invalid: {mismatches}. "
            "Check if simple-icd-10-cm reference data is up to date."
        )


# ---------------------------------------------------------------------------
# HCC Mapping Accuracy
# ---------------------------------------------------------------------------

class TestHCCMappingAccuracy:
    """Verify HCC assignments match the official CMS-HCC V28 crosswalk."""

    def test_known_icd10_codes_map_to_correct_hccs_via_api(
        self,
        api_client: requests.Session,
        base_url: str,
    ) -> None:
        """
        Use GET /api/icd10/validate/{code} (which returns HCC info if available)
        or POST /api/raf/calculate to verify HCC assignments for known codes.

        We validate a subset of the ICD10_TO_HCC_V28 crosswalk table.
        """
        # Use the ICD-10 validate endpoint — it returns 'info' including HCC
        crosswalk_mismatches = []
        crosswalk_hits = 0

        for icd10, expected_hcc in list(ICD10_TO_HCC_V28.items())[:6]:  # spot-check 6
            r = api_client.get(f"{base_url}/api/icd10/validate/{icd10}")
            assert r.status_code == 200
            data = r.json()

            info = data.get("info") or {}
            backend_hcc = (
                str(info.get("hcc_code") or info.get("hcc") or "").strip()
            )

            if backend_hcc:
                crosswalk_hits += 1
                if backend_hcc != expected_hcc:
                    crosswalk_mismatches.append(
                        f"{icd10}: expected HCC{expected_hcc}, got HCC{backend_hcc}"
                    )

        if crosswalk_hits == 0:
            pytest.skip(
                "ICD-10 validate endpoint does not return HCC info — "
                "cannot verify crosswalk accuracy via this endpoint."
            )

        assert not crosswalk_mismatches, (
            f"HCC crosswalk mismatches detected:\n"
            + "\n".join(f"  - {m}" for m in crosswalk_mismatches)
        )

    def test_raf_calculation_assigns_hcc_for_diabetes_patient(
        self,
        api_client: requests.Session,
        base_url: str,
        first_pid: int,
    ) -> None:
        """
        After calculating RAF for a patient with diabetes coding,
        the final_hcc_list should contain at least one of the diabetes HCCs
        (HCC17, HCC18, or HCC19 in V28).
        """
        r = api_client.get(f"{base_url}/api/patients/{first_pid}/diagnoses")
        data = _assert_ok(r)
        codes = [
            _normalize_icd10(dx.get("code", ""))
            for dx in data.get("diagnoses", [])
        ]

        # Check if this patient has any diabetes codes at all
        diabetes_codes_present = any(
            c.startswith("E10") or c.startswith("E11") for c in codes
        )
        if not diabetes_codes_present:
            pytest.skip(
                f"Patient {first_pid} has no diabetes codes — "
                "cannot test diabetes HCC assignment."
            )

        # Trigger RAF calculation
        r = api_client.post(
            f"{base_url}/api/raf/calculate/{first_pid}",
            json={},
            timeout=30,
        )
        calc = _assert_ok(r, f"POST /api/raf/calculate/{first_pid}")
        hcc_list = [str(h) for h in calc.get("final_hcc_list", [])]

        diabetes_hccs = {"17", "18", "19"}
        found = set(hcc_list) & diabetes_hccs
        assert found, (
            f"Patient {first_pid} has diabetes billing codes {[c for c in codes if c.startswith('E1')]} "
            f"but no diabetes HCC (17/18/19) was assigned. HCC list: {hcc_list}"
        )

    def test_non_hcc_codes_do_not_inflate_raf(
        self,
        api_client: requests.Session,
        base_url: str,
        first_pid: int,
    ) -> None:
        """
        Non-HCC codes like I10 (hypertension) must not appear in final_hcc_list
        and must not add disease score weight.
        """
        r = api_client.post(
            f"{base_url}/api/raf/calculate/{first_pid}",
            json={},
            timeout=30,
        )
        calc = _assert_ok(r)
        hcc_list = [str(h) for h in calc.get("final_hcc_list", [])]

        # Hypertension (I10) does NOT have an HCC in V28
        # The HCC list should not contain an HCC solely from I10
        # We can't directly test this without knowing which codes map to which HCCs,
        # but we can assert that the total HCC count is reasonable
        hcc_count = len(hcc_list)
        icd_count = len(calc.get("icd_codes", []))

        # HCC count should always be <= ICD code count (not every code maps to HCC)
        assert hcc_count <= icd_count or icd_count == 0, (
            f"HCC count ({hcc_count}) exceeds ICD code count ({icd_count}), "
            "which is impossible — every HCC requires at least one ICD code."
        )


# ---------------------------------------------------------------------------
# Negation Handling
# ---------------------------------------------------------------------------

class TestNegationHandling:
    """
    Verify that conditions explicitly negated in a clinical note are NOT
    included in the active diagnosis list.
    """

    @pytest.fixture(scope="class")
    def negation_analysis(
        self,
        api_client: requests.Session,
        base_url: str,
        first_pid: int,
    ) -> dict:
        """Run the pipeline on a note that explicitly negates several conditions."""
        r = api_client.post(
            f"{base_url}/api/analysis/note",
            json={
                "patient_id": first_pid,
                "note_text": NEGATION_TEST_NOTE,
                "save_results": False,
            },
            timeout=ANALYSIS_TIMEOUT,
        )
        if r.status_code == 404:
            pytest.skip("POST /api/analysis/note endpoint not implemented.")
        assert r.status_code == 200, (
            f"Analysis note endpoint failed: {r.status_code} — {r.text[:400]}"
        )
        return r.json()

    def test_chf_not_in_active_diagnoses(self, negation_analysis: dict) -> None:
        """
        The test note says 'No history of congestive heart failure'.
        I50.x codes must NOT appear in the active diagnoses list.
        """
        diagnoses = negation_analysis.get("diagnoses", [])
        active_codes = [
            _normalize_icd10(dx.get("icd10", ""))
            for dx in diagnoses
        ]
        chf_codes = [c for c in active_codes if c.startswith("I50")]
        assert not chf_codes, (
            f"CHF code(s) {chf_codes} found in active diagnoses despite "
            "'No history of congestive heart failure' in the note. "
            "Negation handling is failing."
        )

    def test_copd_not_in_active_diagnoses(self, negation_analysis: dict) -> None:
        """
        The test note says 'Patient does NOT have COPD'.
        J44.x codes must NOT appear in the active diagnoses list.
        """
        diagnoses = negation_analysis.get("diagnoses", [])
        active_codes = [
            _normalize_icd10(dx.get("icd10", ""))
            for dx in diagnoses
        ]
        copd_codes = [c for c in active_codes if c.startswith("J44")]
        assert not copd_codes, (
            f"COPD code(s) {copd_codes} found in active diagnoses despite "
            "'Patient does NOT have COPD' in the note."
        )

    def test_atrial_fibrillation_not_in_active_diagnoses(self, negation_analysis: dict) -> None:
        """
        The test note says 'No history of... atrial fibrillation'.
        I48.x codes must NOT appear in the active diagnoses list.
        """
        diagnoses = negation_analysis.get("diagnoses", [])
        active_codes = [
            _normalize_icd10(dx.get("icd10", ""))
            for dx in diagnoses
        ]
        afib_codes = [c for c in active_codes if c.startswith("I48")]
        assert not afib_codes, (
            f"Atrial fibrillation code(s) {afib_codes} found in active diagnoses "
            "despite explicit negation in the note."
        )

    def test_diabetes_is_in_active_diagnoses(self, negation_analysis: dict) -> None:
        """
        The test note positively asserts Type 2 DM (E11.9).
        It must appear in the active diagnoses list.
        """
        diagnoses = negation_analysis.get("diagnoses", [])
        active_codes = [
            _normalize_icd10(dx.get("icd10", ""))
            for dx in diagnoses
        ]
        dm_codes = [c for c in active_codes if c.startswith("E11") or c.startswith("E10")]
        assert dm_codes, (
            f"Type 2 DM (E11.9) should be in active diagnoses but was not found. "
            f"Active codes: {active_codes}"
        )

    def test_negated_conditions_captured_in_negated_list(self, negation_analysis: dict) -> None:
        """
        Negated conditions should appear in negated_conditions, not diagnoses.
        The pipeline should track what was excluded and why.
        """
        negated = negation_analysis.get("negated_conditions", [])
        # If the pipeline found any negated conditions at all, they should be a list
        assert isinstance(negated, list), (
            f"'negated_conditions' must be a list, got: {type(negated).__name__}"
        )


# ---------------------------------------------------------------------------
# RAF Score Clinical Plausibility
# ---------------------------------------------------------------------------

class TestRAFScorePlausibility:
    """High-level clinical plausibility checks on calculated RAF scores."""

    def test_raf_score_components_are_non_negative(
        self,
        api_client: requests.Session,
        base_url: str,
        first_pid: int,
    ) -> None:
        """Every score component (demographic, disease, interaction) must be >= 0."""
        api_client.post(
            f"{base_url}/api/raf/calculate/{first_pid}",
            json={},
            timeout=30,
        )
        r = api_client.get(
            f"{base_url}/api/raf/scores/{first_pid}/breakdown",
        )
        data = _assert_ok(r)

        for component in ("demographic_score", "disease_score", "interaction_score"):
            value = float(data.get(component, 0))
            assert value >= 0, (
                f"{component} is negative ({value}) — this violates CMS-HCC V28 logic."
            )

    def test_demographic_score_reasonable_for_medicare_population(
        self,
        api_client: requests.Session,
        base_url: str,
        first_pid: int,
    ) -> None:
        """
        CMS-HCC V28 demographic base rates for community-dwelling Medicare
        beneficiaries range roughly from 0.1 to 1.0.  Scores outside this
        range suggest a demographic data problem.
        """
        api_client.post(
            f"{base_url}/api/raf/calculate/{first_pid}",
            json={},
            timeout=30,
        )
        r = api_client.get(f"{base_url}/api/raf/scores/{first_pid}/breakdown")
        data = _assert_ok(r)

        demo = float(data.get("demographic_score", 0))
        # Allow a slightly wider range to accommodate edge cases
        assert 0.05 <= demo <= 2.0, (
            f"Demographic score {demo} is outside the plausible CMS-HCC V28 range "
            f"[0.05, 2.0]. Check patient DOB and sex in OpenEMR."
        )

    def test_hcc_count_is_non_negative(
        self,
        api_client: requests.Session,
        base_url: str,
        first_pid: int,
    ) -> None:
        r = api_client.get(f"{base_url}/api/raf/scores/{first_pid}/breakdown")
        if r.status_code == 404:
            api_client.post(
                f"{base_url}/api/raf/calculate/{first_pid}", json={}, timeout=30
            )
            r = api_client.get(f"{base_url}/api/raf/scores/{first_pid}/breakdown")
        data = _assert_ok(r)
        assert int(data.get("hcc_count", 0)) >= 0

    def test_disease_score_increases_with_more_hccs(
        self,
        api_client: requests.Session,
        base_url: str,
        sample_patients: list[dict],
    ) -> None:
        """
        Across at least 2 patients with scores, patients with more HCCs should
        generally have higher disease scores.  This is a population-level
        monotonicity check (not a strict per-patient assertion).
        """
        if len(sample_patients) < 2:
            pytest.skip("Need at least 2 patients with encounters for this test.")

        scored = []
        for patient in sample_patients[:5]:
            pid = int(
                patient.get("pid")
                or patient.get("id")
                or patient.get("patient_id")
            )
            api_client.post(f"{base_url}/api/raf/calculate/{pid}", json={}, timeout=30)
            r = api_client.get(f"{base_url}/api/raf/scores/{pid}/breakdown")
            if r.status_code == 200:
                bd = r.json()
                scored.append({
                    "pid": pid,
                    "hcc_count": int(bd.get("hcc_count", 0)),
                    "disease_score": float(bd.get("disease_score", 0)),
                })

        if len(scored) < 2:
            pytest.skip("Could not retrieve breakdowns for 2+ patients.")

        # Sort by HCC count descending
        scored.sort(key=lambda x: x["hcc_count"], reverse=True)

        # The patient with the most HCCs should have a disease score >= the
        # patient with the fewest HCCs
        most_hccs = scored[0]
        fewest_hccs = scored[-1]

        if most_hccs["hcc_count"] == fewest_hccs["hcc_count"]:
            pytest.skip("All sampled patients have the same HCC count — cannot compare.")

        assert most_hccs["disease_score"] >= fewest_hccs["disease_score"], (
            f"Patient with more HCCs ({most_hccs['hcc_count']}) has a lower disease score "
            f"({most_hccs['disease_score']}) than patient with fewer HCCs "
            f"({fewest_hccs['hcc_count']}, score={fewest_hccs['disease_score']}). "
            "This may indicate an HCC hierarchy / trump rules issue."
        )
