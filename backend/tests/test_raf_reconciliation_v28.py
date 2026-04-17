"""RAF V28 reconciliation harness.

Reads :file:`tests/fixtures/raf_reconciliation_v28.json` and runs every
scenario through the live ``hccinfhir`` engine, asserting that each expected
value (risk_score, demographic_score, hcc_score, per-HCC coefficients) is
reproduced within the fixture's declared absolute tolerance.

Why this matters
----------------
Without a CMS-certified golden fixture, the RAF engine cannot claim
payment-grade accuracy. This harness is the interim substitute: it locks in
the exact numeric behaviour of the coefficient provider for a curated set of
canonical beneficiaries covering the non-trivial V28 scoring paths
(community/institutional, dual/non-dual, disabled/aged, new-enrollee,
single-HCC/multi-HCC with interactions, constrained-family coefficients).

When CMS publishes its Python reference software (early 2026), regenerate
the expected values from CMS and tighten ``absolute_tolerance`` to ``1e-4``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("hccinfhir", reason="hccinfhir not installed")

from hccinfhir import HCCInFHIR, Demographics  # noqa: E402

_FIXTURE_PATH = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "raf_reconciliation_v28.json"
)


@pytest.fixture(scope="module")
def fixture_bundle() -> dict:
    assert _FIXTURE_PATH.exists(), f"fixture missing: {_FIXTURE_PATH}"
    return json.loads(_FIXTURE_PATH.read_text())


@pytest.fixture(scope="module")
def v28_processor() -> HCCInFHIR:
    return HCCInFHIR(model_name="CMS-HCC Model V28")


def _all_scenarios() -> list[dict]:
    bundle = json.loads(_FIXTURE_PATH.read_text())
    return bundle["scenarios"]


@pytest.mark.parametrize(
    "scenario", _all_scenarios(), ids=lambda s: s["id"]
)
def test_v28_scenario_matches_expected_scores(
    scenario: dict,
    fixture_bundle: dict,
    v28_processor: HCCInFHIR,
) -> None:
    tol = fixture_bundle["absolute_tolerance"]
    demo = Demographics(**scenario["demographics"])
    result = v28_processor.calculate_from_diagnosis(
        diagnosis_codes=scenario["diagnosis_codes"], demographics=demo
    )

    exp = scenario["expected"]
    assert result.risk_score == pytest.approx(exp["risk_score"], abs=tol), (
        f"{scenario['id']}: risk_score drift "
        f"expected={exp['risk_score']}, got={result.risk_score}"
    )
    assert result.risk_score_demographics == pytest.approx(
        exp["demographic_score"], abs=tol
    ), (
        f"{scenario['id']}: demographic_score drift "
        f"expected={exp['demographic_score']}, got={result.risk_score_demographics}"
    )
    assert result.risk_score_hcc == pytest.approx(exp["hcc_score"], abs=tol), (
        f"{scenario['id']}: hcc_score drift "
        f"expected={exp['hcc_score']}, got={result.risk_score_hcc}"
    )


@pytest.mark.parametrize(
    "scenario", _all_scenarios(), ids=lambda s: s["id"]
)
def test_v28_scenario_matches_expected_hcc_list(
    scenario: dict,
    fixture_bundle: dict,
    v28_processor: HCCInFHIR,
) -> None:
    tol = fixture_bundle["absolute_tolerance"]
    demo = Demographics(**scenario["demographics"])
    result = v28_processor.calculate_from_diagnosis(
        diagnosis_codes=scenario["diagnosis_codes"], demographics=demo
    )

    got = {h.hcc: h.coefficient for h in (result.hcc_details or [])}
    expected_list = scenario["expected"]["hcc_list"]
    assert len(got) == len(expected_list), (
        f"{scenario['id']}: HCC count drift "
        f"expected={expected_list}, got={got}"
    )
    for entry in expected_list:
        assert entry["hcc"] in got, (
            f"{scenario['id']}: expected HCC {entry['hcc']} missing from {got}"
        )
        assert got[entry["hcc"]] == pytest.approx(
            entry["coefficient"], abs=tol
        ), (
            f"{scenario['id']}: HCC {entry['hcc']} coefficient drift "
            f"expected={entry['coefficient']}, got={got[entry['hcc']]}"
        )


def test_fixture_bundle_metadata(fixture_bundle: dict) -> None:
    """Guardrails on the fixture itself so it stays self-describing."""
    assert fixture_bundle["model_name"] == "CMS-HCC Model V28"
    assert fixture_bundle["coefficient_source"].startswith("hccinfhir==")
    assert fixture_bundle["absolute_tolerance"] > 0
    assert len(fixture_bundle["scenarios"]) >= 10, (
        "Reconciliation set must cover at least 10 canonical scenarios"
    )
    # Every scenario must hit a distinct segment-or-shape combination.
    ids = [s["id"] for s in fixture_bundle["scenarios"]]
    assert len(ids) == len(set(ids)), f"duplicate scenario ids in fixture: {ids}"
