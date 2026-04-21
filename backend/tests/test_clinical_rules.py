"""Unit tests for per-HCC clinical sanity rules (V28).

These tests are **pure unit tests** — no DB, no network.  They exercise the
rule functions directly with hand-built PatientContext objects covering:

    * happy path            — required evidence present → PASS
    * missing-evidence path — required dx/Rx absent     → FAIL (or WARN for
                              advisory_only rules)
    * insufficient-specificity path — non-specific dx   → WARN

All 10+ rules in registry.py are covered.

Any failure here is a regression in the clinical-rule engine; do NOT
relax tests without a clinical coder signoff.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.services.raf.clinical_rules import (
    BilledHCC,
    Encounter,
    LabResult,
    Medication,
    PatientContext,
    RuleStatus,
    validate_billed_hccs,
)
from app.services.raf.clinical_rules.codes import (
    LOINC_BNP,
    LOINC_EGFR,
    LOINC_HBA1C,
    LOINC_PFT,
)
from app.services.raf.clinical_rules.registry import (
    RULE_ACTIVE_CANCER,
    RULE_HCC37,
    RULE_HCC38,
    RULE_HCC155_MDD,
    RULE_HCC226,
    RULE_HCC228_MI,
    RULE_HCC262_PVD,
    RULE_HCC280,
    RULE_HCC409_AMP,
    RULE_HCC_CKD,
    RULE_HCC_STROKE,
)


DOS = date(2026, 6, 1)


def _ctx(**kwargs) -> PatientContext:
    """Build a PatientContext with sensible defaults."""
    defaults = dict(
        patient_id=1,
        date_of_service=DOS,
        age=72,
        sex="F",
        diagnoses_icd10=[],
        medications=[],
        labs=[],
        procedures=[],
        encounters=[],
    )
    defaults.update(kwargs)
    return PatientContext(**defaults)


def _lab(loinc: str) -> LabResult:
    return LabResult(loinc=next(iter(loinc)) if isinstance(loinc, set) else loinc,
                     value=1.0, observed_at=DOS - timedelta(days=30))


def _one(loinc_set) -> LabResult:
    """Return a lab with one LOINC from a set."""
    code = next(iter(loinc_set))
    return LabResult(loinc=code, value=1.0, observed_at=DOS - timedelta(days=30))


# ===========================================================================
# HCC 37 — DM with complications
# ===========================================================================

class TestHCC37:
    def test_happy_path_dm_complication_plus_rx(self):
        ctx = _ctx(
            diagnoses_icd10=["E11.22"],   # nephropathy complication
            medications=[Medication(rx_class="metformin")],
        )
        assert RULE_HCC37.evaluate(ctx).status == RuleStatus.PASS

    def test_missing_evidence_no_dm_at_all(self):
        ctx = _ctx(diagnoses_icd10=["I10"])
        assert RULE_HCC37.evaluate(ctx).status == RuleStatus.FAIL

    def test_insufficient_specificity_dm_without_complication(self):
        ctx = _ctx(
            diagnoses_icd10=["E11.9"],    # uncomplicated
            medications=[Medication(rx_class="insulin")],
        )
        r = RULE_HCC37.evaluate(ctx)
        assert r.status == RuleStatus.FAIL
        assert any("complication" in msg.lower() for msg in r.reasons)

    def test_warn_when_complication_but_no_rx(self):
        ctx = _ctx(diagnoses_icd10=["E11.22"], medications=[])
        assert RULE_HCC37.evaluate(ctx).status == RuleStatus.WARN


# ===========================================================================
# HCC 38 — DM without complication (advisory — WARN only)
# ===========================================================================

class TestHCC38:
    def test_happy_path_dm_plus_a1c(self):
        ctx = _ctx(
            diagnoses_icd10=["E11.9"],
            labs=[_one(LOINC_HBA1C)],
        )
        assert RULE_HCC38.evaluate(ctx).status == RuleStatus.PASS

    def test_missing_dm_fails(self):
        ctx = _ctx(diagnoses_icd10=["I10"])
        assert RULE_HCC38.evaluate(ctx).status == RuleStatus.FAIL

    def test_no_rx_no_a1c_warns(self):
        ctx = _ctx(diagnoses_icd10=["E11.9"])
        assert RULE_HCC38.evaluate(ctx).status == RuleStatus.WARN


# ===========================================================================
# HCC CKD stage-specificity
# ===========================================================================

class TestHCC_CKD:
    def test_happy_path_stage_coded_plus_egfr(self):
        ctx = _ctx(
            diagnoses_icd10=["N18.4"],
            labs=[_one(LOINC_EGFR)],
        )
        assert RULE_HCC_CKD.evaluate(ctx).status == RuleStatus.PASS

    def test_unspecified_ckd_fails(self):
        ctx = _ctx(
            diagnoses_icd10=["N18.9"],
            labs=[_one(LOINC_EGFR)],
        )
        r = RULE_HCC_CKD.evaluate(ctx)
        assert r.status == RuleStatus.FAIL
        assert any("N18.9" in msg or "unspecified" in msg.lower() for msg in r.reasons)

    def test_stage_coded_but_no_egfr_warns(self):
        ctx = _ctx(diagnoses_icd10=["N18.4"])
        assert RULE_HCC_CKD.evaluate(ctx).status == RuleStatus.WARN

    def test_no_ckd_at_all_fails(self):
        ctx = _ctx(diagnoses_icd10=["I10"])
        assert RULE_HCC_CKD.evaluate(ctx).status == RuleStatus.FAIL


# ===========================================================================
# HCC 226 — CHF
# ===========================================================================

class TestHCC226:
    def test_happy_path_specific_chf_plus_rx(self):
        ctx = _ctx(
            diagnoses_icd10=["I50.22"],
            medications=[Medication(rx_class="beta blocker")],
        )
        assert RULE_HCC226.evaluate(ctx).status == RuleStatus.PASS

    def test_no_chf_fails(self):
        ctx = _ctx(diagnoses_icd10=["E11.9"])
        assert RULE_HCC226.evaluate(ctx).status == RuleStatus.FAIL

    def test_unspecified_chf_warns(self):
        ctx = _ctx(
            diagnoses_icd10=["I50.9"],
            medications=[Medication(rx_class="beta blocker")],
        )
        r = RULE_HCC226.evaluate(ctx)
        assert r.status == RuleStatus.WARN
        assert any("I50.9" in msg or "unspecified" in msg.lower() for msg in r.reasons)

    def test_specific_but_no_rx_no_bnp_warns(self):
        ctx = _ctx(diagnoses_icd10=["I50.22"])
        assert RULE_HCC226.evaluate(ctx).status == RuleStatus.WARN


# ===========================================================================
# HCC 280 — COPD
# ===========================================================================

class TestHCC280:
    def test_happy_path_copd_plus_pft(self):
        ctx = _ctx(
            diagnoses_icd10=["J44.9"],
            labs=[_one(LOINC_PFT)],
        )
        assert RULE_HCC280.evaluate(ctx).status == RuleStatus.PASS

    def test_happy_path_copd_plus_inhaler(self):
        ctx = _ctx(
            diagnoses_icd10=["J44.9"],
            medications=[Medication(rx_class="LAMA")],
        )
        assert RULE_HCC280.evaluate(ctx).status == RuleStatus.PASS

    def test_no_copd_fails(self):
        ctx = _ctx(diagnoses_icd10=["E11.9"])
        assert RULE_HCC280.evaluate(ctx).status == RuleStatus.FAIL

    def test_copd_no_pft_no_rx_warns(self):
        ctx = _ctx(diagnoses_icd10=["J44.9"])
        assert RULE_HCC280.evaluate(ctx).status == RuleStatus.WARN


# ===========================================================================
# HCC 155 — MDD (advisory_only — FAILs get demoted to WARN)
# ===========================================================================

class TestHCC155_MDD:
    def test_happy_path_specific_mdd_plus_rx(self):
        ctx = _ctx(
            diagnoses_icd10=["F33.1"],
            medications=[Medication(rx_class="SSRI")],
        )
        assert RULE_HCC155_MDD.evaluate(ctx).status == RuleStatus.PASS

    def test_no_mdd_gets_demoted_to_warn(self):
        """advisory_only=True: FAIL is demoted to WARN."""
        ctx = _ctx(diagnoses_icd10=["I10"])
        r = RULE_HCC155_MDD.evaluate(ctx)
        assert r.status == RuleStatus.WARN
        assert any("advisory" in msg.lower() for msg in r.reasons)

    def test_unspecified_mdd_warns(self):
        ctx = _ctx(
            diagnoses_icd10=["F32.9"],
            medications=[Medication(rx_class="SSRI")],
        )
        assert RULE_HCC155_MDD.evaluate(ctx).status == RuleStatus.WARN


# ===========================================================================
# Active cancer family
# ===========================================================================

class TestActiveCancer:
    def test_happy_path_cancer_plus_chemo(self):
        ctx = _ctx(
            diagnoses_icd10=["C50.911"],
            medications=[Medication(rx_class="chemotherapy")],
        )
        assert RULE_ACTIVE_CANCER.evaluate(ctx).status == RuleStatus.PASS

    def test_happy_path_cancer_plus_oncology_encounter(self):
        ctx = _ctx(
            diagnoses_icd10=["C50.911"],
            encounters=[Encounter(
                encounter_id=1, encounter_date=DOS,
                provider_specialty="oncology",
            )],
        )
        assert RULE_ACTIVE_CANCER.evaluate(ctx).status == RuleStatus.PASS

    def test_only_history_of_cancer_fails(self):
        ctx = _ctx(diagnoses_icd10=["Z85.3"])
        r = RULE_ACTIVE_CANCER.evaluate(ctx)
        assert r.status == RuleStatus.FAIL
        assert any("Z85" in msg for msg in r.reasons)

    def test_cancer_coded_but_no_treatment_warns(self):
        ctx = _ctx(diagnoses_icd10=["C50.911"])
        assert RULE_ACTIVE_CANCER.evaluate(ctx).status == RuleStatus.WARN


# ===========================================================================
# Stroke (advisory_only)
# ===========================================================================

class TestStroke:
    def test_happy_path(self):
        ctx = _ctx(
            diagnoses_icd10=["I69.320"],
            medications=[Medication(rx_class="aspirin")],
        )
        assert RULE_HCC_STROKE.evaluate(ctx).status == RuleStatus.PASS

    def test_no_stroke_fails_demoted_to_warn(self):
        ctx = _ctx(diagnoses_icd10=["I10"])
        assert RULE_HCC_STROKE.evaluate(ctx).status == RuleStatus.WARN

    def test_stroke_no_rx_warns(self):
        ctx = _ctx(diagnoses_icd10=["I69.320"])
        assert RULE_HCC_STROKE.evaluate(ctx).status == RuleStatus.WARN


# ===========================================================================
# Acute MI
# ===========================================================================

class TestAcuteMI:
    def test_happy_path(self):
        ctx = _ctx(
            diagnoses_icd10=["I21.01"],
            encounters=[Encounter(
                encounter_id=1, encounter_date=DOS,
                provider_specialty="cardiology",
            )],
        )
        assert RULE_HCC228_MI.evaluate(ctx).status == RuleStatus.PASS

    def test_only_old_mi_fails(self):
        ctx = _ctx(diagnoses_icd10=["I25.2"])
        r = RULE_HCC228_MI.evaluate(ctx)
        assert r.status == RuleStatus.FAIL
        assert any("I25.2" in msg or "old" in msg.lower() for msg in r.reasons)

    def test_acute_mi_no_cardiology_warns(self):
        ctx = _ctx(diagnoses_icd10=["I21.01"])
        assert RULE_HCC228_MI.evaluate(ctx).status == RuleStatus.WARN


# ===========================================================================
# PVD (advisory)
# ===========================================================================

class TestPVD:
    def test_happy_path_specific_pvd(self):
        ctx = _ctx(diagnoses_icd10=["I70.213"])
        assert RULE_HCC262_PVD.evaluate(ctx).status == RuleStatus.PASS

    def test_unspecified_pvd_warns(self):
        ctx = _ctx(diagnoses_icd10=["I73.9"])
        assert RULE_HCC262_PVD.evaluate(ctx).status == RuleStatus.WARN

    def test_no_pvd_demoted_to_warn(self):
        ctx = _ctx(diagnoses_icd10=["I10"])
        # advisory_only demotes FAIL to WARN
        assert RULE_HCC262_PVD.evaluate(ctx).status == RuleStatus.WARN


# ===========================================================================
# Amputation Status
# ===========================================================================

class TestAmputation:
    def test_happy_path_z_code(self):
        ctx = _ctx(diagnoses_icd10=["Z89.511"])
        assert RULE_HCC409_AMP.evaluate(ctx).status == RuleStatus.PASS

    def test_happy_path_acute_trauma(self):
        ctx = _ctx(diagnoses_icd10=["S78.111A"])
        assert RULE_HCC409_AMP.evaluate(ctx).status == RuleStatus.PASS

    def test_missing_fails(self):
        ctx = _ctx(diagnoses_icd10=["I10"])
        assert RULE_HCC409_AMP.evaluate(ctx).status == RuleStatus.FAIL


# ===========================================================================
# Integration: validate_billed_hccs + ValidationReport
# ===========================================================================

class TestValidatorIntegration:

    def test_single_pass(self):
        ctx = _ctx(
            diagnoses_icd10=["E11.22"],
            medications=[Medication(rx_class="metformin")],
        )
        rep = validate_billed_hccs([BilledHCC(hcc=37)], ctx)
        assert rep.overall_status == RuleStatus.PASS
        assert rep.failed() == []

    def test_single_fail_blocks_hcc(self):
        ctx = _ctx(diagnoses_icd10=["N18.9"], labs=[_one(LOINC_EGFR)])
        rep = validate_billed_hccs([BilledHCC(hcc=327)], ctx)
        assert rep.overall_status == RuleStatus.FAIL
        assert [o.hcc for o in rep.failed()] == [327]

    def test_multi_hcc_mixed(self):
        ctx = _ctx(
            diagnoses_icd10=["E11.22", "I50.9"],
            medications=[Medication(rx_class="metformin")],
        )
        rep = validate_billed_hccs(
            [BilledHCC(hcc=37), BilledHCC(hcc=226)], ctx,
        )
        # HCC 37 PASS; HCC 226 WARN (I50.9 unspec + no CHF Rx)
        assert rep.overall_status == RuleStatus.WARN
        assert [o.hcc for o in rep.warnings()] == [226]

    def test_unknown_hcc_passes_automatically(self):
        """HCCs without a registered rule must not be blocked."""
        ctx = _ctx()
        rep = validate_billed_hccs([BilledHCC(hcc=99999)], ctx)
        assert rep.overall_status == RuleStatus.PASS

    def test_cancer_family_lookup(self):
        """HCC 18 (a cancer family HCC) should inherit the active-cancer rule."""
        ctx = _ctx(diagnoses_icd10=["Z85.3"])   # only history-of
        rep = validate_billed_hccs([BilledHCC(hcc=18)], ctx)
        assert rep.overall_status == RuleStatus.FAIL

    def test_ckd_family_lookup(self):
        """HCC 326 and 328 should inherit the CKD stage-specificity rule."""
        ctx = _ctx(diagnoses_icd10=["N18.9"])
        rep = validate_billed_hccs([BilledHCC(hcc=326)], ctx)
        assert rep.overall_status == RuleStatus.FAIL

    def test_report_to_dict_shape(self):
        ctx = _ctx(diagnoses_icd10=["E11.22"],
                   medications=[Medication(rx_class="metformin")])
        rep = validate_billed_hccs([BilledHCC(hcc=37)], ctx)
        data = rep.to_dict()
        assert data["overall_status"] == "pass"
        assert "outcomes" in data
        assert data["outcomes"][0]["hcc"] == 37


# ===========================================================================
# Registry completeness — ensure we have rules for 10+ high-billed HCCs
# ===========================================================================

def test_registry_has_minimum_rules():
    from app.services.raf.clinical_rules.registry import ALL_RULES
    assert len(ALL_RULES) >= 10, (
        f"Registry must contain >=10 rules (target: DM/CKD/CHF/COPD/MDD/"
        f"cancer/stroke/MI/PVD/amputation). Got {len(ALL_RULES)}."
    )
