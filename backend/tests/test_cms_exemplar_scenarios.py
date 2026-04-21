"""CMS-pattern exemplar beneficiary reconciliation.

Each scenario is a named, well-labelled beneficiary profile chosen to
exercise a specific, publicly-documented V28 behaviour (demographic
floor, dual-status premium, disease interaction, origin-of-entry
disabled track, multi-HCC stacking, negative-control exclusions).

Unlike the bulk reconciliation harness, every exemplar here has a
human-readable label and a ``cms_pattern`` attribution string that a
reviewer can trace back to the CMS Rate Announcement technical notes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("hccinfhir")

from hccinfhir import Demographics, HCCInFHIR  # noqa: E402

_FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "cms_exemplar_scenarios_v28.json"
)


@pytest.fixture(scope="module")
def bundle() -> dict:
    return json.loads(_FIXTURE.read_text())


@pytest.fixture(scope="module")
def processor() -> HCCInFHIR:
    return HCCInFHIR(model_name="CMS-HCC Model V28")


def _all_scenarios() -> list[dict]:
    return json.loads(_FIXTURE.read_text())["scenarios"]


@pytest.mark.parametrize(
    "scenario", _all_scenarios(), ids=lambda s: s["id"]
)
def test_exemplar_score_matches_locked_value(
    scenario: dict, bundle: dict, processor: HCCInFHIR
) -> None:
    demo = Demographics(
        age=scenario["age"],
        sex=scenario["sex"],
        dual_elgbl_cd=scenario["dual_elgbl_cd"],
        orec=scenario["orec"],
        new_enrollee=scenario["new_enrollee"],
    )
    result = processor.calculate_from_diagnosis(
        diagnosis_codes=scenario["diagnoses"],
        demographics=demo,
    )
    tol = bundle["absolute_tolerance"]
    assert result.risk_score == pytest.approx(
        scenario["expected_risk_score"], abs=tol
    ), (
        f"{scenario['id']}: drifted — label='{scenario['label']}', "
        f"pattern='{scenario['cms_pattern']}', "
        f"expected={scenario['expected_risk_score']}, got={result.risk_score}"
    )


class TestBundleMetadata:
    def test_bundle_has_required_metadata(self, bundle: dict) -> None:
        assert bundle["model_name"] == "CMS-HCC Model V28"
        assert bundle["payment_year"] == 2026
        assert bundle["coefficient_source"].startswith("hccinfhir==")
        assert bundle["cms_reference"]

    def test_every_scenario_has_label_and_pattern(self, bundle: dict) -> None:
        for s in bundle["scenarios"]:
            assert s.get("label"), f"{s['id']} missing label"
            assert s.get("cms_pattern"), f"{s['id']} missing cms_pattern"

    def test_scenario_ids_are_unique(self, bundle: dict) -> None:
        ids = [s["id"] for s in bundle["scenarios"]]
        assert len(ids) == len(set(ids)), f"duplicate ids: {ids}"


class TestStructuralInvariants:
    """Invariants that any CMS-compliant V28 table must satisfy."""

    def test_dual_status_increases_score_for_aged(self, bundle: dict) -> None:
        """Full-dual aged beneficiaries must score ≥ non-dual aged peers
        at the same age / sex / diagnoses."""
        by_key = {s["id"]: s for s in bundle["scenarios"]}
        pairs = [
            ("CNA_female_72_no_dx", "CFA_female_72_full_dual_no_dx"),
            ("CNA_male_72_no_dx", "CFA_male_72_full_dual_no_dx"),
            ("CNA_female_80_multi_hcc", "CFA_female_80_multi_hcc"),
        ]
        for cna_id, cfa_id in pairs:
            cna = by_key[cna_id]["expected_risk_score"]
            cfa = by_key[cfa_id]["expected_risk_score"]
            assert cfa + 1e-6 >= cna, (
                f"{cfa_id} ({cfa}) must be >= {cna_id} ({cna}) — "
                f"CMS dual-status premium invariant violated"
            )

    def test_adding_disease_never_decreases_score(self, bundle: dict) -> None:
        """Any CNA profile + 1+ disease diagnoses must score ≥ the
        demographic floor for the same age/sex — a V28 monotonicity rule."""
        by_key = {s["id"]: s for s in bundle["scenarios"]}
        floor = by_key["CNA_female_72_no_dx"]["expected_risk_score"]
        disease_profiles = [
            "CNA_female_72_dm_uncomplicated",
            "CNA_female_72_chf_only",
            "CNA_female_72_dm_plus_chf",
            "CNA_female_72_copd",
        ]
        for pid in disease_profiles:
            assert by_key[pid]["expected_risk_score"] >= floor, (
                f"{pid} ({by_key[pid]['expected_risk_score']}) < "
                f"CNA floor ({floor}) — disease must never decrease RAF"
            )

    def test_ckd_stage3_is_excluded(self, bundle: dict) -> None:
        """N18.3 (CKD stage 3) has no V28 HCC — negative control.

        The exemplar must show score == demographic floor, proving the
        hccinfhir mapping does NOT silently add a phantom HCC.
        """
        by_key = {s["id"]: s for s in bundle["scenarios"]}
        floor = by_key["CNA_female_72_no_dx"]["expected_risk_score"]
        ckd3 = by_key["CNA_female_72_ckd_stage3"]["expected_risk_score"]
        assert ckd3 == pytest.approx(floor, abs=1e-6), (
            f"CKD stage 3 must be excluded from V28 — expected floor={floor}, "
            f"got {ckd3}"
        )

    def test_multi_hcc_stacks_additively(self, bundle: dict) -> None:
        """The multi-HCC profile must score ≥ any single-HCC profile
        from the same age/sex/segment."""
        by_key = {s["id"]: s for s in bundle["scenarios"]}
        multi = by_key["CNA_female_80_multi_hcc"]["expected_risk_score"]
        # 80-year-old floor is higher than 72-year-old; still check multi >= the
        # largest single 72-year-old disease score for sanity.
        singles = [
            by_key["CNA_female_72_dm_uncomplicated"]["expected_risk_score"],
            by_key["CNA_female_72_chf_only"]["expected_risk_score"],
            by_key["CNA_female_72_copd"]["expected_risk_score"],
        ]
        assert multi > max(singles), (
            f"Multi-HCC 80yo profile ({multi}) must exceed every single-HCC "
            f"72yo profile ({max(singles)}) — V28 additivity invariant"
        )

    def test_ne_full_dual_exceeds_non_dual(self, bundle: dict) -> None:
        """For New Enrollees at same age/sex, full-dual must >= non-dual."""
        by_key = {s["id"]: s for s in bundle["scenarios"]}
        non_dual = by_key["NE_female_65_entry"]["expected_risk_score"]
        full_dual = by_key["NE_female_65_full_dual_entry"]["expected_risk_score"]
        assert full_dual > non_dual, (
            f"NE full-dual ({full_dual}) must exceed NE non-dual ({non_dual})"
        )
