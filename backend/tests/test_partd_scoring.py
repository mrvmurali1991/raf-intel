"""Part D (RxHCC V08) end-to-end scoring tests.

Locks:

- Model resolution by payment year (2024/2025/2026 → V08; legacy = V05).
- 10 reconciliation scenarios (total + demographic + HCC + triggered-HCC list).
- SBOM is attached to every Part D response with plan_type='PART_D'.
- Structural invariants: hcc_score + demographic_score = total,
  multi-HCC ≥ single-HCC, disease never decreases score.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("hccinfhir")

from app.services.raf.partd_scorer import (  # noqa: E402
    _resolve_rx_model,
    calculate_partd_raf,
)

_FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "partd_reconciliation_v08.json"
)


@pytest.fixture(scope="module")
def bundle() -> dict:
    return json.loads(_FIXTURE.read_text())


def _scenarios() -> list[dict]:
    return json.loads(_FIXTURE.read_text())["scenarios"]


# ---------------------------------------------------------------------------
# Model resolution
# ---------------------------------------------------------------------------

class TestModelResolution:
    @pytest.mark.parametrize("year", [2024, 2025, 2026])
    def test_current_years_use_v08(self, year: int) -> None:
        assert _resolve_rx_model(year) == "RxHCC Model V08"

    def test_unknown_future_year_falls_back_to_v08(self) -> None:
        assert _resolve_rx_model(2099) == "RxHCC Model V08"


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("scenario", _scenarios(), ids=lambda s: s["id"])
def test_partd_scenario_matches_locked(scenario: dict, bundle: dict) -> None:
    result = calculate_partd_raf(
        diagnosis_codes=scenario["diagnoses"],
        age=scenario["age"],
        sex=scenario["sex"],
        dual_elgbl_cd=scenario["dual_elgbl_cd"],
        orec=scenario["orec"],
        new_enrollee=scenario["new_enrollee"],
        payment_year=bundle["payment_year"],
    )
    tol = bundle["absolute_tolerance"]
    assert result["risk_score"] == pytest.approx(
        scenario["expected_total"], abs=tol
    )
    assert result["demographic_score"] == pytest.approx(
        scenario["expected_demographic"], abs=tol
    )
    assert result["hcc_score"] == pytest.approx(
        scenario["expected_hcc"], abs=tol
    )
    assert sorted(result["hcc_list"]) == scenario["expected_hcc_list"]


# ---------------------------------------------------------------------------
# SBOM
# ---------------------------------------------------------------------------

class TestPartDSBOM:
    def test_every_response_carries_sbom(self) -> None:
        result = calculate_partd_raf(
            diagnosis_codes=["E119"], age=72, sex="F", payment_year=2026,
        )
        assert "provenance_sbom" in result
        sbom = result["provenance_sbom"]
        assert sbom["plan_type"] == "PART_D"
        assert sbom["payment_year"] == 2026
        assert sbom["models_used"] == ["RxHCC Model V08"]
        assert sbom["frailty_applied"] is False



# ---------------------------------------------------------------------------
# Structural invariants
# ---------------------------------------------------------------------------

class TestInvariants:
    def test_demographic_plus_hcc_equals_total(self, bundle: dict) -> None:
        for s in bundle["scenarios"]:
            total = s["expected_total"]
            subtotal = round(s["expected_demographic"] + s["expected_hcc"], 4)
            assert subtotal == pytest.approx(total, abs=1e-4), (
                f"{s['id']}: demo+hcc={subtotal} != total={total}"
            )

    def test_multi_hcc_exceeds_single_hcc(self, bundle: dict) -> None:
        by_id = {s["id"]: s for s in bundle["scenarios"]}
        single = by_id["partd_72F_dm"]["expected_total"]
        multi = by_id["partd_72F_dm_chf"]["expected_total"]
        assert multi > single, (
            f"Multi-HCC Part D score ({multi}) must exceed single-HCC ({single})"
        )

    def test_disease_never_reduces_part_d_score(self, bundle: dict) -> None:
        by_id = {s["id"]: s for s in bundle["scenarios"]}
        floor = by_id["partd_72F_no_dx"]["expected_total"]
        for sid in ["partd_72F_dm", "partd_72F_copd", "partd_72F_dm_chf"]:
            assert by_id[sid]["expected_total"] >= floor, (
                f"{sid}: Part D score dropped below demographic floor"
            )

    def test_male_differs_from_female_at_baseline(self, bundle: dict) -> None:
        """Sex-specific RxHCC demographic coefficients should differ."""
        by_id = {s["id"]: s for s in bundle["scenarios"]}
        assert by_id["partd_72M_no_dx"]["expected_total"] != by_id[
            "partd_72F_no_dx"
        ]["expected_total"]


class TestFixtureMetadata:
    def test_fixture_metadata_present(self, bundle: dict) -> None:
        assert bundle["model_name"] == "RxHCC Model V08"
        assert bundle["payment_year"] == 2026
        assert bundle["coefficient_source"].startswith("hccinfhir==")
        assert len(bundle["scenarios"]) >= 10

    def test_scenario_ids_unique(self, bundle: dict) -> None:
        ids = [s["id"] for s in bundle["scenarios"]]
        assert len(ids) == len(set(ids))
