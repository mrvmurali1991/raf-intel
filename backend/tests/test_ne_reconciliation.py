"""New Enrollee V28 reconciliation harness.

Previously the main reconciliation covered 2 NE scenarios. New enrollees
(beneficiaries with <12 months of MA enrollment) run a dedicated CMS table
with no disease adjustment — only age, sex, dual status, and Medicaid
eligibility matter. This harness locks the demographic-only table across
every age band × sex × dual combination (54 scenarios).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("hccinfhir")

from hccinfhir import HCCInFHIR, Demographics  # noqa: E402

_FIXTURE = (
    Path(__file__).resolve().parent / "fixtures" / "ne_reconciliation_v28.json"
)


@pytest.fixture(scope="module")
def fixture_bundle() -> dict:
    return json.loads(_FIXTURE.read_text())


@pytest.fixture(scope="module")
def processor() -> HCCInFHIR:
    return HCCInFHIR(model_name="CMS-HCC Model V28")


def _all_scenarios() -> list[dict]:
    return json.loads(_FIXTURE.read_text())["scenarios"]


@pytest.mark.parametrize("scenario", _all_scenarios(), ids=lambda s: s["id"])
def test_new_enrollee_score_matches_snapshot(
    scenario: dict, fixture_bundle: dict, processor: HCCInFHIR
) -> None:
    tol = fixture_bundle["absolute_tolerance"]
    demo = Demographics(
        age=scenario["age"],
        sex=scenario["sex"],
        dual_elgbl_cd=scenario["dual_elgbl_cd"],
        orec="0",
        new_enrollee=True,
    )
    result = processor.calculate_from_diagnosis(
        diagnosis_codes=[], demographics=demo
    )
    assert result.risk_score == pytest.approx(
        scenario["expected_risk_score"], abs=tol
    ), (
        f"{scenario['id']}: risk_score drift "
        f"expected={scenario['expected_risk_score']}, got={result.risk_score}"
    )
    # For NE, the full risk score must equal the demographic score (no HCC).
    assert result.risk_score_hcc == pytest.approx(0.0, abs=tol), (
        f"{scenario['id']}: NE must have zero HCC score, got "
        f"{result.risk_score_hcc}"
    )


def test_ne_fixture_metadata(fixture_bundle: dict) -> None:
    assert fixture_bundle["model_name"] == "CMS-HCC Model V28"
    assert fixture_bundle["coefficient_source"].startswith("hccinfhir==")
    assert len(fixture_bundle["scenarios"]) >= 50, (
        "NE reconciliation must cover at least 50 demographic combinations"
    )
    ids = [s["id"] for s in fixture_bundle["scenarios"]]
    assert len(ids) == len(set(ids)), f"duplicate scenario ids: {ids}"


def test_ne_full_dual_always_gte_non_dual_at_same_demo(
    fixture_bundle: dict,
) -> None:
    """CMS rate rule: for identical (age, sex), CFA NE ≥ CNA NE."""
    by_key = {
        (s["age"], s["sex"], s["dual_elgbl_cd"]): s["expected_risk_score"]
        for s in fixture_bundle["scenarios"]
    }
    for age in {s["age"] for s in fixture_bundle["scenarios"]}:
        for sex in ("M", "F"):
            non_dual = by_key.get((age, sex, "NA"))
            full_dual = by_key.get((age, sex, "02"))
            if non_dual is None or full_dual is None:
                continue
            assert full_dual + 1e-6 >= non_dual, (
                f"NE({age}, {sex}): full_dual={full_dual} < non_dual={non_dual}"
            )
