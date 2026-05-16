"""CMS V28 golden-master regression gate for RAF scoring math.

These tests call hccinfhir's pure-Python scoring engine directly — no database,
no network — using the same entry point that app.services.raf.calculator uses.
Any coefficient change, normalization-factor drift, or HCC-hierarchy regression
that touches the numbers below will cause a test failure and surface the change
for deliberate review before merge.

Source: CMS HHS-HCC V28 Risk Adjustment Model, CY2025 Medicare Advantage Final
Rate Announcement (April 2024), Table VI-2 "Relative Factors for Community and
Institutional Beneficiaries under the 2024 CMS-HCC Model (Version 28)".
https://www.cms.gov/files/document/2025-announcement.pdf
CMS landing page: https://www.cms.gov/medicare/payment/medicare-advantage-rates-statistics/risk-adjustment

Fixture data lives in fixtures/cms_v28_golden_patients.json. Each case
documents its own coefficient source in the `source_note` field.

HOW TO UPDATE: if a CMS coefficient release intentionally changes a value,
update the fixture JSON to match the new published number, add a comment citing
the new document, and create the commit with a clear message. Do NOT silently
update a number to make a test pass.

Inputs use norm_factor=1.0, maci=0.0 so raw hccinfhir risk_score == the sum of
published CMS coefficients without any year-specific normalization adjustment.
This keeps expectations stable across payment-year transitions.
"""
from __future__ import annotations

import json
import pathlib
import sys
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Fixture loading
# ---------------------------------------------------------------------------

_FIXTURE_PATH = pathlib.Path(__file__).parent / "fixtures" / "cms_v28_golden_patients.json"


def _load_fixture() -> list[dict[str, Any]]:
    with _FIXTURE_PATH.open("r") as fh:
        data = json.load(fh)
    return data["cases"]


_ALL_CASES: list[dict[str, Any]] = _load_fixture()


# ---------------------------------------------------------------------------
# Segment → hccinfhir prefix_override mapping
# MUST stay in sync with app.services.raf.enrollment_resolver._SEGMENT_TO_PREFIX
# ---------------------------------------------------------------------------

try:
    from app.services.raf_calculator import _SEGMENT_TO_PREFIX  # noqa: F401
    _SEGMENT_TO_PREFIX_MAP: dict[str, str] = dict(_SEGMENT_TO_PREFIX)
except Exception:
    # Fallback when DB-connected modules are unavailable in CI
    _SEGMENT_TO_PREFIX_MAP = {
        "CNA": "CNA_",
        "CND": "CND_",
        "CFA": "CFA_",
        "CFD": "CFD_",
        "CPA": "CPA_",
        "CPD": "CPD_",
        "INS": "INS_",
    }


# ---------------------------------------------------------------------------
# V28 processor availability check
# ---------------------------------------------------------------------------

def _v28_available() -> bool:
    """Return True if hccinfhir loads the V28 model without error."""
    try:
        from hccinfhir import HCCInFHIR
        p = HCCInFHIR(model_name="CMS-HCC Model V28")
        # A minimal sanity call — if coefficients_mapping is empty the model
        # failed to load and we should skip rather than silently pass with zeros.
        result = p.calculate_from_diagnosis([], age=70, sex="M", prefix_override="CNA_")
        return result.risk_score > 0.0  # must have a demographic score
    except Exception:
        return False


_V28_AVAILABLE = _v28_available()

_SKIP_IF_NO_V28 = pytest.mark.skipif(
    not _V28_AVAILABLE,
    reason=(
        "CMS-HCC V28 coefficient tables not available in this environment "
        "(hccinfhir could not load 'CMS-HCC Model V28'). "
        "Install hccinfhir>=0.3.0 and ensure coefficient data files are present."
    ),
)


# ---------------------------------------------------------------------------
# Scoring harness — pure, no DB
# ---------------------------------------------------------------------------

def _score_case(case: dict[str, Any]) -> Any:
    """Run hccinfhir V28 with the given case inputs. Returns the raw result object."""
    from hccinfhir import HCCInFHIR

    inputs = case["inputs"]
    segment = inputs["model_segment"]
    prefix = _SEGMENT_TO_PREFIX_MAP.get(segment)
    if prefix is None:
        pytest.skip(f"Segment {segment!r} not mapped — skipping case {case['id']!r}")

    processor = HCCInFHIR(model_name="CMS-HCC Model V28")
    return processor.calculate_from_diagnosis(
        list(inputs.get("icd10_codes") or []),
        age=int(inputs["age"]),
        sex=str(inputs["sex"]),
        prefix_override=prefix,
        # norm_factor=1.0, maci=0.0 so raw risk_score == sum of published coefficients
        norm_factor=1.0,
        maci=0.0,
    )


# ---------------------------------------------------------------------------
# Parametrized golden-master tests
# ---------------------------------------------------------------------------

@_SKIP_IF_NO_V28
@pytest.mark.parametrize("case", _ALL_CASES, ids=[c["id"] for c in _ALL_CASES])
def test_cms_v28_golden_patient(case: dict[str, Any]) -> None:
    """Assert that hccinfhir V28 output matches CMS-published fixture values.

    Each case documents its coefficient source in `source_note`. A failure here
    means the scoring math has drifted from the pinned CMS V28 values — this
    MUST be reviewed before merge, not silently fixed.
    """
    if case.get("_skip_total_assert"):
        # Cases where total_raf is intentionally omitted (version-sensitive HCC coeff)
        result = _score_case(case)
        expected = case.get("expected", {})
        got_hccs = [str(h) for h in (result.hcc_list or [])]

        if "hcc_list_unordered" in expected:
            exp_set = {str(h) for h in expected["hcc_list_unordered"]}
            assert set(got_hccs) == exp_set, (
                f"{case['id']}: HCC set mismatch. expected={sorted(exp_set)} got={sorted(got_hccs)}\n"
                f"source_note: {case.get('source_note', 'n/a')}"
            )

        if "demographic_score" in expected:
            tol = float(case.get("tolerance", 0.0001))
            got_demo = float(result.risk_score_demographics)
            assert abs(got_demo - float(expected["demographic_score"])) <= tol, (
                f"{case['id']}: demographic_score mismatch. "
                f"expected={expected['demographic_score']} got={got_demo}"
            )
        return

    expected = case.get("expected", {})
    tol = float(case.get("tolerance", 0.0001))
    result = _score_case(case)

    # --- total_raf -----------------------------------------------------------
    if "total_raf" in expected:
        got_total = float(result.risk_score)
        exp_total = float(expected["total_raf"])
        assert abs(got_total - exp_total) <= tol, (
            f"{case['id']}: total_raf mismatch. "
            f"expected={exp_total} got={got_total} tol={tol}\n"
            f"source_note: {case.get('source_note', 'n/a')}"
        )

    # --- demographic_score ---------------------------------------------------
    if "demographic_score" in expected:
        got_demo = float(result.risk_score_demographics)
        exp_demo = float(expected["demographic_score"])
        assert abs(got_demo - exp_demo) <= tol, (
            f"{case['id']}: demographic_score mismatch. "
            f"expected={exp_demo} got={got_demo}\n"
            f"source_note: {case.get('source_note', 'n/a')}"
        )

    # --- disease_score -------------------------------------------------------
    if "disease_score" in expected:
        got_disease = float(sum(h.coefficient for h in (result.hcc_details or [])))
        exp_disease = float(expected["disease_score"])
        assert abs(got_disease - exp_disease) <= tol, (
            f"{case['id']}: disease_score mismatch. "
            f"expected={exp_disease} got={got_disease}"
        )

    got_hccs = [str(h) for h in (result.hcc_list or [])]

    # --- hcc_list (ordered) --------------------------------------------------
    if "hcc_list" in expected:
        exp_list = [str(h) for h in expected["hcc_list"]]
        assert got_hccs == exp_list, (
            f"{case['id']}: hcc_list mismatch. expected={exp_list} got={got_hccs}"
        )

    # --- hcc_list_unordered --------------------------------------------------
    if "hcc_list_unordered" in expected:
        exp_set = {str(h) for h in expected["hcc_list_unordered"]}
        assert set(got_hccs) == exp_set, (
            f"{case['id']}: HCC set mismatch. "
            f"expected={sorted(exp_set)} got={sorted(got_hccs)}\n"
            f"source_note: {case.get('source_note', 'n/a')}"
        )

    # --- hierarchy guard: must-not-contain -----------------------------------
    if "hcc_list_must_not_contain" in expected:
        bad = {str(h) for h in expected["hcc_list_must_not_contain"]}
        leaked = bad.intersection(set(got_hccs))
        assert not leaked, (
            f"{case['id']}: HCC hierarchy collapse failed — "
            f"suppressed HCCs still present: {sorted(leaked)}\n"
            f"source_note: {case.get('source_note', 'n/a')}"
        )


# ---------------------------------------------------------------------------
# Smoke test: fixture file loads and has expected shape
# ---------------------------------------------------------------------------

def test_cms_v28_fixture_loads_and_has_minimum_cases() -> None:
    """Smoke test: fixture JSON is valid and contains >=8 cases with expected blocks.

    This test does NOT require the V28 model to be loaded — it only validates
    the fixture file structure. CI can run this unconditionally.
    """
    cases = _load_fixture()
    assert len(cases) >= 8, (
        f"Expected >=8 CMS V28 golden cases, got {len(cases)}. "
        "Add more cases to fixtures/cms_v28_golden_patients.json."
    )
    cases_with_expected = [
        c for c in cases
        if c.get("expected") and not c.get("_skip_total_assert")
    ]
    assert len(cases_with_expected) >= 6, (
        f"At least 6 cases must have a fully-asserted `expected` block; "
        f"only {len(cases_with_expected)} do."
    )
    for case in cases:
        assert "id" in case, f"Case missing 'id' field: {case}"
        assert "inputs" in case, f"Case {case.get('id', '?')} missing 'inputs'"
        assert "source_note" in case, (
            f"Case {case['id']}: every golden case must cite its coefficient source "
            "in 'source_note'."
        )


def test_cms_v28_fixture_all_segments_represented() -> None:
    """Verify fixture covers the required segment diversity (CNA, CFA, CND, INS, CPA)."""
    cases = _load_fixture()
    segments_present = {c["inputs"]["model_segment"] for c in cases}
    required = {"CNA", "CFA", "CND", "INS", "CPA"}
    missing = required - segments_present
    assert not missing, (
        f"Golden fixture is missing coverage for segments: {sorted(missing)}. "
        "Add at least one case per required segment."
    )
