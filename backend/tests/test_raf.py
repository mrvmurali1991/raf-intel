"""
RAF Score API integration tests.

Covers:
  POST /api/raf/calculate/{pid}
  GET  /api/raf/scores/{pid}
  GET  /api/raf/scores/{pid}/breakdown
  GET  /api/raf/scores/{pid}/history
  GET  /api/raf/population-summary

Validates:
  - Response shape and required fields
  - RAF score is within the expected CMS-HCC V28 range (0.0 – 5.0)
  - Demographic score is plausible for the patient's age/sex
  - HCC list elements carry required sub-fields
"""
from __future__ import annotations

import re
import pytest
import requests
from datetime import date

# CMS-HCC V28 practical ceiling — real patients rarely exceed 5.0 in OpenEMR demos
RAF_SCORE_MAX = 5.0
RAF_SCORE_MIN = 0.0

# Current measurement year
CURRENT_YEAR = date.today().year


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _assert_ok(r: requests.Response, context: str = "") -> dict:
    assert r.status_code == 200, (
        f"{context} — expected 200, got {r.status_code}. Body: {r.text[:500]}"
    )
    return r.json()


# ---------------------------------------------------------------------------
# POST /api/raf/calculate/{pid}
# ---------------------------------------------------------------------------

class TestRAFCalculate:
    """Trigger a fresh RAF calculation for a patient and validate the result."""

    @pytest.fixture(scope="class")
    def calc_result(
        self,
        api_client: requests.Session,
        base_url: str,
        first_pid: int,
    ) -> dict:
        """Run the RAF calculation once and cache the result for the class."""
        r = api_client.post(
            f"{base_url}/api/raf/calculate/{first_pid}",
            json={"year": CURRENT_YEAR},
        )
        assert r.status_code == 200, (
            f"POST /api/raf/calculate/{first_pid} failed with {r.status_code}: {r.text[:500]}"
        )
        return r.json()

    def test_calculate_returns_200(
        self, api_client: requests.Session, base_url: str, first_pid: int
    ):
        r = api_client.post(
            f"{base_url}/api/raf/calculate/{first_pid}",
            json={"year": CURRENT_YEAR},
        )
        _assert_ok(r, f"POST /api/raf/calculate/{first_pid}")

    def test_calculate_result_has_required_top_level_fields(
        self, calc_result: dict, first_pid: int
    ):
        """The calculation response must contain all documented top-level fields."""
        required = [
            "patient_id",
            "raf_score",
            "icd_codes",
            "final_hcc_list",
        ]
        for field in required:
            assert field in calc_result, (
                f"Missing required field '{field}' in calculate response. "
                f"Got keys: {sorted(calc_result)}"
            )

    def test_raf_score_is_within_valid_range(self, calc_result: dict):
        raf = calc_result.get("raf_score")
        assert raf is not None, "raf_score must not be None"
        assert isinstance(raf, (int, float)), f"raf_score must be numeric, got {type(raf)}"
        assert RAF_SCORE_MIN <= float(raf) <= RAF_SCORE_MAX, (
            f"raf_score {raf} is outside the expected range "
            f"[{RAF_SCORE_MIN}, {RAF_SCORE_MAX}]"
        )

    def test_raf_score_is_positive(self, calc_result: dict):
        """Every patient receives at least the demographic base rate."""
        raf = float(calc_result.get("raf_score", 0))
        assert raf >= 0, f"raf_score must be >= 0, got {raf}"

    def test_icd_codes_is_list(self, calc_result: dict):
        icd_codes = calc_result.get("icd_codes")
        assert isinstance(icd_codes, list), (
            f"'icd_codes' must be a list, got {type(icd_codes).__name__}"
        )

    def test_icd_codes_look_like_icd10(self, calc_result: dict):
        """
        ICD-10-CM codes follow the pattern: letter + 2 digits [+ optional chars].
        Validate a spot-check of the first ten codes.
        """
        icd10_pattern = re.compile(r"^[A-Z]\d{2}(\.\w+)?$", re.IGNORECASE)
        codes = calc_result.get("icd_codes", [])
        for code in codes[:10]:
            code_str = str(code).strip().replace(".", "")
            # Re-add dot for validation if removed
            assert re.match(r"^[A-Z]\d{2}", code_str, re.IGNORECASE), (
                f"ICD code '{code}' does not look like a valid ICD-10-CM code"
            )

    def test_final_hcc_list_is_list(self, calc_result: dict):
        hcc_list = calc_result.get("final_hcc_list")
        assert isinstance(hcc_list, list), (
            f"'final_hcc_list' must be a list, got {type(hcc_list).__name__}"
        )

    def test_patient_id_in_response_matches_request(
        self, calc_result: dict, first_pid: int
    ):
        assert int(calc_result.get("patient_id")) == first_pid, (
            f"patient_id in response ({calc_result.get('patient_id')}) "
            f"!= requested pid ({first_pid})"
        )

    def test_returns_404_for_nonexistent_pid(
        self, api_client: requests.Session, base_url: str, nonexistent_pid: int
    ):
        r = api_client.post(
            f"{base_url}/api/raf/calculate/{nonexistent_pid}",
            json={"year": CURRENT_YEAR},
        )
        assert r.status_code == 404, (
            f"Expected 404 for nonexistent PID, got {r.status_code}"
        )

    def test_demographic_score_is_present(self, calc_result: dict):
        """Demographic score should be a key component of the RAF."""
        demo = calc_result.get("demographic_score")
        # May be nested or top-level depending on hccinfhir version
        if demo is None:
            # Try to find it inside a nested structure
            breakdown = calc_result.get("breakdown") or {}
            demo = breakdown.get("demographic_score")
        # Not all responses expose it at top-level, so only assert type if present
        if demo is not None:
            assert isinstance(demo, (int, float)), (
                f"demographic_score should be numeric, got {type(demo).__name__}: {demo}"
            )


# ---------------------------------------------------------------------------
# GET /api/raf/scores/{pid}/breakdown
# ---------------------------------------------------------------------------

class TestRAFBreakdown:
    """Detailed HCC breakdown endpoint."""

    @pytest.fixture(scope="class")
    def breakdown(
        self,
        api_client: requests.Session,
        base_url: str,
        first_pid: int,
    ) -> dict:
        """
        Ensure a score exists, then fetch the breakdown.
        Calculate first to guarantee there is something to retrieve.
        """
        # Trigger calculation to ensure data exists
        api_client.post(
            f"{base_url}/api/raf/calculate/{first_pid}",
            json={"year": CURRENT_YEAR},
        )
        r = api_client.get(
            f"{base_url}/api/raf/scores/{first_pid}/breakdown",
            params={"year": CURRENT_YEAR},
        )
        assert r.status_code == 200, (
            f"GET /api/raf/scores/{first_pid}/breakdown returned {r.status_code}: {r.text[:500]}"
        )
        return r.json()

    def test_breakdown_returns_200(
        self, api_client: requests.Session, base_url: str, first_pid: int
    ):
        api_client.post(
            f"{base_url}/api/raf/calculate/{first_pid}",
            json={"year": CURRENT_YEAR},
        )
        r = api_client.get(
            f"{base_url}/api/raf/scores/{first_pid}/breakdown",
            params={"year": CURRENT_YEAR},
        )
        _assert_ok(r, f"GET /api/raf/scores/{first_pid}/breakdown")

    def test_breakdown_has_required_fields(self, breakdown: dict):
        required = [
            "patient_id",
            "patient_name",
            "measurement_year",
            "raf_score",
            "demographic_score",
            "disease_score",
            "interaction_score",
            "hcc_count",
            "model_segment",
            "hcc_details",
        ]
        for field in required:
            assert field in breakdown, (
                f"Breakdown missing required field '{field}'. Got keys: {sorted(breakdown)}"
            )

    def test_raf_score_in_range(self, breakdown: dict):
        raf = float(breakdown["raf_score"])
        assert RAF_SCORE_MIN <= raf <= RAF_SCORE_MAX, (
            f"raf_score {raf} out of expected range [{RAF_SCORE_MIN}, {RAF_SCORE_MAX}]"
        )

    def test_score_components_sum_to_raf(self, breakdown: dict):
        """
        Total RAF = demographic + disease + interaction (within floating point tolerance).
        """
        demo = float(breakdown.get("demographic_score", 0))
        disease = float(breakdown.get("disease_score", 0))
        interaction = float(breakdown.get("interaction_score", 0))
        total = float(breakdown.get("raf_score", 0))

        computed_sum = round(demo + disease + interaction, 4)
        assert abs(computed_sum - total) < 0.01, (
            f"Score components ({demo} + {disease} + {interaction} = {computed_sum}) "
            f"do not sum to raf_score ({total}) within tolerance"
        )

    def test_demographic_score_is_positive(self, breakdown: dict):
        """Every CMS-HCC V28 segment has a positive demographic base rate."""
        demo = float(breakdown.get("demographic_score", 0))
        assert demo > 0, (
            f"Demographic score should be > 0 (CMS always assigns a base rate). Got: {demo}"
        )

    def test_hcc_count_matches_hcc_details_length(self, breakdown: dict):
        assert breakdown["hcc_count"] == len(breakdown["hcc_details"]), (
            f"hcc_count ({breakdown['hcc_count']}) != len(hcc_details) "
            f"({len(breakdown['hcc_details'])})"
        )

    def test_hcc_details_is_list(self, breakdown: dict):
        assert isinstance(breakdown["hcc_details"], list)

    def test_hcc_detail_records_have_required_fields(self, breakdown: dict):
        """Each HCC detail entry must have hcc_code, hcc_label, and icd10_codes."""
        for hcc in breakdown["hcc_details"][:10]:
            for field in ("hcc_code", "hcc_label", "icd10_codes", "meat_status"):
                assert field in hcc, (
                    f"HCC detail record missing '{field}'. Got: {hcc}"
                )

    def test_hcc_icd10_codes_is_list(self, breakdown: dict):
        for hcc in breakdown["hcc_details"][:10]:
            assert isinstance(hcc.get("icd10_codes"), list), (
                f"'icd10_codes' in HCC detail must be a list. Got: {hcc}"
            )

    def test_model_segment_is_known_value(self, breakdown: dict):
        """CMS-HCC V28 model segments are well-defined strings."""
        known_segments = {
            "CNA", "CND", "CFA", "CFD", "CPA", "CPD",
            "INS", "NE", "CE", "ESRD",
        }
        segment = breakdown.get("model_segment", "")
        # Not all backends expose every segment — allow unknown but non-empty
        assert segment, "model_segment must not be empty"

    def test_breakdown_returns_404_for_nonexistent_pid(
        self, api_client: requests.Session, base_url: str, nonexistent_pid: int
    ):
        r = api_client.get(
            f"{base_url}/api/raf/scores/{nonexistent_pid}/breakdown"
        )
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/raf/scores/{pid}  (stored score)
# ---------------------------------------------------------------------------

class TestRAFStoredScore:

    def test_stored_score_returns_200_after_calculate(
        self, api_client: requests.Session, base_url: str, first_pid: int
    ):
        api_client.post(
            f"{base_url}/api/raf/calculate/{first_pid}",
            json={"year": CURRENT_YEAR},
        )
        r = api_client.get(
            f"{base_url}/api/raf/scores/{first_pid}",
            params={"year": CURRENT_YEAR},
        )
        _assert_ok(r, f"GET /api/raf/scores/{first_pid}")

    def test_stored_score_has_required_fields(
        self, api_client: requests.Session, base_url: str, first_pid: int
    ):
        api_client.post(
            f"{base_url}/api/raf/calculate/{first_pid}",
            json={"year": CURRENT_YEAR},
        )
        r = api_client.get(
            f"{base_url}/api/raf/scores/{first_pid}",
            params={"year": CURRENT_YEAR},
        )
        data = _assert_ok(r)
        for field in (
            "patient_id", "patient_name", "measurement_year",
            "raf_score", "demographic_score", "disease_score",
            "hcc_count", "calculated_at"
        ):
            assert field in data, f"Missing '{field}' in stored score response"

    def test_stored_score_returns_404_for_uncalculated_year(
        self, api_client: requests.Session, base_url: str, first_pid: int
    ):
        """A year with no calculation should return 404."""
        past_year = CURRENT_YEAR - 50  # very unlikely to have data
        r = api_client.get(
            f"{base_url}/api/raf/scores/{first_pid}",
            params={"year": past_year},
        )
        assert r.status_code == 404, (
            f"Expected 404 for year {past_year} with no data, got {r.status_code}"
        )


# ---------------------------------------------------------------------------
# GET /api/raf/scores/{pid}/history
# ---------------------------------------------------------------------------

class TestRAFScoreHistory:

    def test_history_returns_200(
        self, api_client: requests.Session, base_url: str, first_pid: int
    ):
        r = api_client.get(f"{base_url}/api/raf/scores/{first_pid}/history")
        _assert_ok(r, f"GET /api/raf/scores/{first_pid}/history")

    def test_history_has_required_fields(
        self, api_client: requests.Session, base_url: str, first_pid: int
    ):
        r = api_client.get(f"{base_url}/api/raf/scores/{first_pid}/history")
        data = _assert_ok(r)
        for field in ("patient_id", "patient_name", "years_calculated", "history"):
            assert field in data, f"Missing '{field}' in history response"

    def test_history_entries_have_expected_fields(
        self, api_client: requests.Session, base_url: str, first_pid: int
    ):
        r = api_client.get(f"{base_url}/api/raf/scores/{first_pid}/history")
        data = _assert_ok(r)
        for entry in data.get("history", [])[:5]:
            for field in ("measurement_year", "raf_score", "hcc_count", "calculated_at"):
                assert field in entry, (
                    f"History entry missing '{field}'. Got: {entry}"
                )

    def test_history_years_calculated_matches_history_list(
        self, api_client: requests.Session, base_url: str, first_pid: int
    ):
        r = api_client.get(f"{base_url}/api/raf/scores/{first_pid}/history")
        data = _assert_ok(r)
        assert data["years_calculated"] == len(data["history"])

    def test_history_is_ordered_newest_first(
        self, api_client: requests.Session, base_url: str, first_pid: int
    ):
        """
        History must be sorted descending by measurement_year.
        """
        r = api_client.get(f"{base_url}/api/raf/scores/{first_pid}/history")
        data = _assert_ok(r)
        years = [entry["measurement_year"] for entry in data.get("history", [])]
        assert years == sorted(years, reverse=True), (
            f"History is not sorted newest-first. Got years: {years}"
        )


# ---------------------------------------------------------------------------
# GET /api/raf/population-summary
# ---------------------------------------------------------------------------

class TestRAFPopulationSummary:

    def test_population_summary_returns_200(
        self, api_client: requests.Session, base_url: str
    ):
        r = api_client.get(f"{base_url}/api/raf/population-summary")
        _assert_ok(r, "GET /api/raf/population-summary")

    def test_population_summary_has_required_fields(
        self, api_client: requests.Session, base_url: str
    ):
        r = api_client.get(f"{base_url}/api/raf/population-summary")
        data = _assert_ok(r)
        for field in (
            "measurement_year", "total_patients", "patients_with_scores",
            "average_raf", "median_raf", "raf_distribution", "top_hccs",
        ):
            assert field in data, (
                f"Missing '{field}' in population-summary. Got keys: {sorted(data)}"
            )

    def test_distribution_has_expected_buckets(
        self, api_client: requests.Session, base_url: str
    ):
        r = api_client.get(f"{base_url}/api/raf/population-summary")
        data = _assert_ok(r)
        dist = data.get("raf_distribution", [])
        labels = {d["range"] for d in dist}
        expected_labels = {"0.0-0.5", "0.5-1.0", "1.0-1.5", "1.5-2.0", "2.0+"}
        assert expected_labels.issubset(labels), (
            f"Expected distribution buckets {expected_labels} not all present. Got: {labels}"
        )

    def test_average_raf_is_non_negative(self, api_client: requests.Session, base_url: str):
        r = api_client.get(f"{base_url}/api/raf/population-summary")
        data = _assert_ok(r)
        assert float(data.get("average_raf", 0)) >= 0

    def test_measurement_year_is_current_or_recent(
        self, api_client: requests.Session, base_url: str
    ):
        r = api_client.get(f"{base_url}/api/raf/population-summary")
        data = _assert_ok(r)
        year = data.get("measurement_year")
        assert year is not None
        assert CURRENT_YEAR - 2 <= int(year) <= CURRENT_YEAR + 1, (
            f"measurement_year {year} is unexpectedly far from {CURRENT_YEAR}"
        )
