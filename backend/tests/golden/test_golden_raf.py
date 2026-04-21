"""Golden regression tests for CMS-HCC V28 RAF scoring.

Every YAML under tests/golden/cases/ is loaded and executed against the real
hccinfhir-backed scoring engine used by app.services.raf_calculator.  Any case
with a non-null `expected` block is asserted to within its declared tolerance
(default 0.0001).  Cases with `expected: null` are skipped with their reason.

These fixtures are a regression trip-wire.  If they fail, the scoring engine
has changed behavior and somebody needs to confirm that is intentional BEFORE
merging.  Source citations for every expected number live in the YAML itself.

No database, no network — these tests exercise hccinfhir's pure-python entry
point directly so they run in CI regardless of OpenEMR/MySQL state.
"""
from __future__ import annotations

import pathlib
from typing import Any

import pytest
import yaml


GOLDEN_DIR = pathlib.Path(__file__).parent / "cases"


# ---------------------------------------------------------------------------
# Case discovery
# ---------------------------------------------------------------------------

def _load_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for path in sorted(GOLDEN_DIR.glob("*.yaml")):
        with path.open("r") as fh:
            data = yaml.safe_load(fh)
        data["_path"] = str(path)
        cases.append(data)
    return cases


_ALL_CASES = _load_cases()


def _case_id(case: dict[str, Any]) -> str:
    return case.get("id") or pathlib.Path(case["_path"]).stem


# ---------------------------------------------------------------------------
# Scoring harness — calls the exact same library that raf_calculator uses.
# We do not import raf_calculator directly here because that module pulls in
# MySQL connectors; the golden tests must remain DB-free.  raf_calculator
# delegates scoring to hccinfhir unchanged, so this is a faithful regression
# harness of the scoring math path.
# ---------------------------------------------------------------------------

# Map the segment string used in YAML to hccinfhir's prefix_override — MUST
# stay in sync with app.services.raf_calculator._SEGMENT_TO_PREFIX.
try:
    from app.services.raf_calculator import _SEGMENT_TO_PREFIX  # noqa: F401
    SEGMENT_TO_PREFIX = dict(_SEGMENT_TO_PREFIX)
except Exception:  # pragma: no cover — fallback if import path unavailable in CI
    SEGMENT_TO_PREFIX = {
        "CNA": "CNA_",
        "CND": "CND_",
        "CFA": "CFA_",
        "CFD": "CFD_",
        "CPA": "CPA_",
        "CPD": "CPD_",
        "INS": "INS_",
    }


def _score(case_inputs: dict[str, Any]) -> Any:
    """Run hccinfhir with the given inputs and return the raw result object."""
    from hccinfhir import HCCInFHIR

    segment = case_inputs["model_segment"]
    prefix = SEGMENT_TO_PREFIX.get(segment)
    if prefix is None:
        pytest.skip(f"segment {segment!r} not mapped by raf_calculator")

    processor = HCCInFHIR(model_name="CMS-HCC Model V28")
    return processor.calculate_from_diagnosis(
        list(case_inputs.get("icd10_codes") or []),
        age=int(case_inputs["age"]),
        sex=str(case_inputs["sex"]),
        prefix_override=prefix,
    )


# ---------------------------------------------------------------------------
# Parametrized regression test
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("case", _ALL_CASES, ids=[_case_id(c) for c in _ALL_CASES])
def test_golden_raf_case(case: dict[str, Any]) -> None:
    """Execute a single golden fixture against hccinfhir and assert outputs."""
    expected = case.get("expected")
    if expected is None:
        pytest.skip(
            f"Case {_case_id(case)!r}: {case.get('skip_reason', 'no expected block')}"
        )

    tol = float(case.get("tolerance", 0.0001))
    result = _score(case["inputs"])

    # --- total_raf (always required) ----------------------------------------
    exp_total = expected.get("total_raf")
    assert exp_total is not None, (
        f"{case['id']}: fixture has expected but no total_raf — "
        "either remove the expected block or populate total_raf."
    )
    got_total = float(result.risk_score)
    assert abs(got_total - float(exp_total)) <= tol, (
        f"{case['id']}: total_raf mismatch. "
        f"expected={exp_total} got={got_total} tol={tol}"
    )

    # --- demographic_score (optional) ---------------------------------------
    if "demographic_score" in expected:
        got_demo = float(result.risk_score_demographics)
        assert abs(got_demo - float(expected["demographic_score"])) <= tol, (
            f"{case['id']}: demographic_score mismatch. "
            f"expected={expected['demographic_score']} got={got_demo}"
        )

    # --- disease_score (optional) -------------------------------------------
    if "disease_score" in expected:
        got_disease = float(sum(h.coefficient for h in (result.hcc_details or [])))
        assert abs(got_disease - float(expected["disease_score"])) <= tol, (
            f"{case['id']}: disease_score mismatch. "
            f"expected={expected['disease_score']} got={got_disease}"
        )

    got_hccs = [str(h) for h in (result.hcc_list or [])]

    # --- hcc_list (ordered) -------------------------------------------------
    if "hcc_list" in expected:
        exp_list = [str(h) for h in expected["hcc_list"]]
        assert got_hccs == exp_list, (
            f"{case['id']}: hcc_list mismatch. expected={exp_list} got={got_hccs}"
        )

    # --- hcc_list_unordered -------------------------------------------------
    if "hcc_list_unordered" in expected:
        exp_set = {str(h) for h in expected["hcc_list_unordered"]}
        assert set(got_hccs) == exp_set, (
            f"{case['id']}: hcc_list (unordered) mismatch. "
            f"expected={sorted(exp_set)} got={sorted(got_hccs)}"
        )

    # --- hcc_list_must_not_contain (hierarchy guard) ------------------------
    if "hcc_list_must_not_contain" in expected:
        bad = set(str(h) for h in expected["hcc_list_must_not_contain"])
        leaked = bad.intersection(got_hccs)
        assert not leaked, (
            f"{case['id']}: HCC hierarchy collapse failed. "
            f"These HCCs should have been suppressed: {sorted(leaked)}"
        )

    # --- per-HCC coefficients ----------------------------------------------
    if "hcc_coefficients" in expected:
        got_coeffs = {str(h.hcc): float(h.coefficient) for h in (result.hcc_details or [])}
        for hcc_code, exp_coeff in expected["hcc_coefficients"].items():
            assert str(hcc_code) in got_coeffs, (
                f"{case['id']}: expected HCC {hcc_code} coefficient but HCC not scored"
            )
            assert abs(got_coeffs[str(hcc_code)] - float(exp_coeff)) <= tol, (
                f"{case['id']}: HCC {hcc_code} coefficient mismatch. "
                f"expected={exp_coeff} got={got_coeffs[str(hcc_code)]}"
            )

    # --- interactions -------------------------------------------------------
    if "interactions_fired" in expected:
        fired = {k for k, v in (result.interactions or {}).items() if v}
        missing = set(expected["interactions_fired"]) - fired
        assert not missing, (
            f"{case['id']}: expected interactions did not fire: {sorted(missing)}. "
            f"Got: {sorted(fired)}"
        )


def test_golden_case_count_sanity() -> None:
    """Smoke test: we should have at least 8 cases and a majority with expected values."""
    assert len(_ALL_CASES) >= 8, f"Expected >=8 golden cases, got {len(_ALL_CASES)}"
    with_expected = [c for c in _ALL_CASES if c.get("expected")]
    assert len(with_expected) >= 8, (
        "At least 8 golden cases must have populated `expected:` blocks; "
        f"only {len(with_expected)} do."
    )
