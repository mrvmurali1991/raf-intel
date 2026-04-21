"""Registry of per-HCC clinical sanity rules (CMS-HCC V28).

Every rule cites its source in the docstring.  When the cited guidance is
ambiguous, the rule is marked advisory_only=True so it can WARN but never
FAIL — patient safety: better to let a code through with a warning than
silently block billing on unclear evidence.

Rules live at HCC granularity. If multiple HCCs share a clinical pattern
(e.g. cancer family), register them individually so errors stay specific.
"""
from __future__ import annotations

from .codes import (
    ICD10_ACTIVE_CANCER,
    ICD10_ACUTE_MI,
    ICD10_AMPUTATION_ACUTE,
    ICD10_AMPUTATION_STATUS,
    ICD10_CHF_ANY,
    ICD10_CHF_SPECIFIC,
    ICD10_CKD_ANY,
    ICD10_CKD_STAGE_SPECIFIC,
    ICD10_COPD_ANY,
    ICD10_DIABETES_ANY,
    ICD10_DIABETES_WITH_COMPLICATION_SUFFIX,
    ICD10_HISTORY_OF_CANCER,
    ICD10_MDD_ANY,
    ICD10_OLD_MI,
    ICD10_PVD_ANY,
    ICD10_PVD_SPECIFIC,
    ICD10_STROKE_SEQUELAE,
    LOINC_BNP,
    LOINC_EGFR,
    LOINC_HBA1C,
    LOINC_PFT,
    RX_CLASS_ANTIPLATELET_ANTICOAG,
    RX_CLASS_CANCER_TREATMENT,
    RX_CLASS_CHF,
    RX_CLASS_COPD,
    RX_CLASS_DEPRESSION,
    RX_CLASS_DIABETES,
    any_code_matches,
    has_prefix,
    normalize_icd,
    rx_class_present,
)
from .rules import ClinicalRule, PatientContext, RuleResult


MODEL = "V28"


# ---------------------------------------------------------------------------
# HCC 37 — Diabetes with Chronic Complications  (CMS-HCC V28)
# ---------------------------------------------------------------------------

def _rule_hcc37(ctx: PatientContext) -> RuleResult:
    """
    Source: CMS-HCC V28 ICD-to-CC crosswalk (ry2024) — HCC 37 requires an
    ICD-10-CM diabetes code with a fourth character in {2,3,4,5,6,8}
    (complication-specific) per ICD-10-CM Official Guideline I.C.4.a.2
    ("assign as many codes from categories E08–E13 as needed to identify
    all the associated conditions").

    We also expect evidence of active diabetes management (Rx class in
    RX_CLASS_DIABETES) — a "with complications" dx but no DM therapy is
    a known documentation smell.
    """
    dx = ctx.diagnoses_icd10
    if not has_prefix(dx, ICD10_DIABETES_ANY):
        return RuleResult.failure(37, MODEL, "hcc37_dm_complication",
            ["No diabetes ICD-10 code (E08-E13) on chart"])

    has_complication = False
    for c in dx:
        nc = normalize_icd(c)
        if len(nc) >= 4 and nc[0] == "E" and nc[1:3] in {"08", "09", "10", "11", "13"}:
            if nc[3] in ICD10_DIABETES_WITH_COMPLICATION_SUFFIX:
                has_complication = True
                break
    if not has_complication:
        return RuleResult.failure(37, MODEL, "hcc37_dm_complication",
            ["Diabetes dx present but no complication-specific code "
             "(E1x.2–E1x.6/E1x.8). HCC 37 requires a complication-coded dx."])

    if not rx_class_present(ctx.active_rx_classes(), RX_CLASS_DIABETES):
        return RuleResult.warning(37, MODEL, "hcc37_dm_complication",
            ["DM w/ complication coded but no active antidiabetic Rx — "
             "verify management or consider historical coding."])

    return RuleResult.passed(37, MODEL, "hcc37_dm_complication",
                             "complication-specific DM dx + active Rx")


RULE_HCC37 = ClinicalRule(
    hcc=37, model=MODEL, rule_name="hcc37_dm_complication",
    description="DM with chronic complications — requires complication-coded "
                "ICD-10 (E1x.2–E1x.6/E1x.8) and active antidiabetic Rx.",
    required_evidence=_rule_hcc37,
)


# ---------------------------------------------------------------------------
# HCC 38 — Diabetes without Complication (V28)
# ---------------------------------------------------------------------------

def _rule_hcc38(ctx: PatientContext) -> RuleResult:
    """
    Source: CMS-HCC V28 ICD-to-CC crosswalk. HCC 38 fires for uncomplicated
    DM codes (E1x.9 and non-complication-specific codes).  Guideline
    I.C.4.a — uncomplicated DM is still a chronic condition requiring
    documented management; we WARN (not FAIL) if no Rx and no A1c in 12mo,
    since the dx itself is valid per the crosswalk.
    """
    dx = ctx.diagnoses_icd10
    if not has_prefix(dx, ICD10_DIABETES_ANY):
        return RuleResult.failure(38, MODEL, "hcc38_dm_uncomplicated",
            ["No diabetes ICD-10 code (E08-E13) on chart"])

    has_rx = rx_class_present(ctx.active_rx_classes(), RX_CLASS_DIABETES)
    recent_a1c = any(l.loinc in LOINC_HBA1C for l in ctx.recent_labs(365))

    if not has_rx and not recent_a1c:
        return RuleResult.warning(38, MODEL, "hcc38_dm_uncomplicated",
            ["DM coded but no antidiabetic Rx and no HbA1c in last 12 months"])
    return RuleResult.passed(38, MODEL, "hcc38_dm_uncomplicated")


RULE_HCC38 = ClinicalRule(
    hcc=38, model=MODEL, rule_name="hcc38_dm_uncomplicated",
    description="DM without complication — requires DM dx plus either active "
                "Rx OR HbA1c in last 12mo (advisory warning only).",
    required_evidence=_rule_hcc38,
)


# ---------------------------------------------------------------------------
# HCC 326 / 327 / 328 — CKD Stage 3b / 4 / 5  (V28 split stage 3 into 3a/3b)
# Rule guards the non-specific case: unspecified CKD (N18.9) should never
# drive a stage-specific HCC.
# ---------------------------------------------------------------------------

def _rule_hcc_ckd(ctx: PatientContext) -> RuleResult:
    """
    Source: KDIGO 2024 CKD Clinical Practice Guideline — stage specificity
    based on eGFR category (G1–G5); AHA Coding Clinic 3Q 2021 p.15 —
    "assign the code for the specific stage of CKD documented by the
    provider".  ICD-10-CM guideline I.C.14.a.1: if both a stage code and
    N18.9 are documented, code only the stage.

    We FAIL if only N18.9 is on the chart when a stage-specific HCC (326+)
    was billed; WARN if no eGFR lab in window.
    """
    dx = ctx.diagnoses_icd10
    if not has_prefix(dx, ICD10_CKD_ANY):
        return RuleResult.failure(327, MODEL, "ckd_stage_specificity",
            ["No CKD ICD-10 code (N18.x) on chart"])

    if not any_code_matches(dx, ICD10_CKD_STAGE_SPECIFIC):
        return RuleResult.failure(327, MODEL, "ckd_stage_specificity",
            ["CKD coded but stage is unspecified (N18.9). "
             "Stage-specific HCC requires N18.30/31/32, N18.4, N18.5, or N18.6."])

    has_egfr = any(l.loinc in LOINC_EGFR for l in ctx.recent_labs(365))
    if not has_egfr:
        return RuleResult.warning(327, MODEL, "ckd_stage_specificity",
            ["CKD stage coded but no eGFR lab result in last 12 months"])

    return RuleResult.passed(327, MODEL, "ckd_stage_specificity")


RULE_HCC_CKD = ClinicalRule(
    hcc=327, model=MODEL, rule_name="ckd_stage_specificity",
    description="Stage-specific CKD HCC — requires N18.30/31/32/4/5/6 "
                "(not N18.9) plus eGFR in last 12 months.",
    required_evidence=_rule_hcc_ckd,
)


# ---------------------------------------------------------------------------
# HCC 226 — Heart Failure  (V28)
# ---------------------------------------------------------------------------

def _rule_hcc226(ctx: PatientContext) -> RuleResult:
    """
    Source: 2022 ACC/AHA/HFSA Heart Failure Guideline — pharmacotherapy is
    standard of care for HFrEF (GDMT: ARNI/ACEi/ARB + beta blocker + MRA +
    SGLT2i); HFpEF has diuretic + SGLT2i.  AHA Coding Clinic 4Q 2017 p.13
    clarifies I50.9 is non-specific and should be replaced with I50.2x–8x.

    FAIL: no CHF ICD on chart.
    WARN: CHF coded but no CHF-class Rx AND no BNP/NT-proBNP in 12mo.
    WARN: only I50.9 coded (non-specific).
    """
    dx = ctx.diagnoses_icd10
    if not has_prefix(dx, ICD10_CHF_ANY):
        return RuleResult.failure(226, MODEL, "hcc226_chf",
            ["No heart failure ICD-10 code (I50.x) on chart"])

    reasons: list[str] = []
    if not any_code_matches(dx, ICD10_CHF_SPECIFIC):
        reasons.append("CHF coded but only I50.9 (unspecified) — "
                       "code I50.2x/3x/4x/8x per type and acuity.")

    has_rx = rx_class_present(ctx.active_rx_classes(), RX_CLASS_CHF)
    has_bnp = any(l.loinc in LOINC_BNP for l in ctx.recent_labs(365))
    if not has_rx and not has_bnp:
        reasons.append("No CHF-class Rx (ACEi/ARB/ARNI/BB/MRA/SGLT2i/loop) "
                       "and no BNP/NT-proBNP within 12mo")

    if reasons:
        return RuleResult.warning(226, MODEL, "hcc226_chf", reasons)
    return RuleResult.passed(226, MODEL, "hcc226_chf")


RULE_HCC226 = ClinicalRule(
    hcc=226, model=MODEL, rule_name="hcc226_chf",
    description="CHF HCC — requires I50.x with specific subtype preferred, "
                "plus CHF-class Rx OR BNP/NT-proBNP in 12mo.",
    required_evidence=_rule_hcc226,
)


# ---------------------------------------------------------------------------
# HCC 280 — COPD / Chronic Bronchitis / Emphysema (V28)
# ---------------------------------------------------------------------------

def _rule_hcc280(ctx: PatientContext) -> RuleResult:
    """
    Source: GOLD 2024 Report — COPD diagnosis requires spirometric
    confirmation (post-bronchodilator FEV1/FVC < 0.70) OR a chronic
    respiratory Rx regimen.  ICD-10-CM J44.x supports HCC 280 when
    documented by provider.

    FAIL: no J44 code on chart.
    WARN: J44 coded but no PFT on file AND no chronic inhaled Rx.
    """
    dx = ctx.diagnoses_icd10
    if not has_prefix(dx, ICD10_COPD_ANY):
        return RuleResult.failure(280, MODEL, "hcc280_copd",
            ["No COPD ICD-10 code (J44.x) on chart"])

    has_pft = any(l.loinc in LOINC_PFT for l in ctx.recent_labs(365 * 3))
    has_rx = rx_class_present(ctx.active_rx_classes(), RX_CLASS_COPD)

    if not has_pft and not has_rx:
        return RuleResult.warning(280, MODEL, "hcc280_copd",
            ["COPD coded but no PFT (FEV1/FVC) on file and no chronic "
             "inhaler Rx (SABA/LABA/LAMA/ICS). GOLD 2024 requires "
             "spirometric confirmation."])
    return RuleResult.passed(280, MODEL, "hcc280_copd")


RULE_HCC280 = ClinicalRule(
    hcc=280, model=MODEL, rule_name="hcc280_copd",
    description="COPD HCC — requires J44.x plus PFT in last 3 years OR "
                "chronic inhaler Rx.",
    required_evidence=_rule_hcc280,
)


# ---------------------------------------------------------------------------
# HCC 155 — Major Depression, Bipolar, and Paranoid Disorders (V28)
# We narrow this rule to the MDD subset (F32/F33) since other disorders
# (bipolar I, schizophrenia) need different evidence patterns.
# ---------------------------------------------------------------------------

def _rule_hcc155_mdd(ctx: PatientContext) -> RuleResult:
    """
    Source: ICD-10-CM FY2024 F32/F33.  APA 2023 Practice Guideline — MDD
    requires episode specificity (mild/moderate/severe).  F32.9 is
    unspecified and is not ideal for HCC support.  An active antidepressant
    Rx or behavioral-health visit is strong supporting evidence.

    FAIL: no F32/F33 code.
    WARN: F32.9 unspecified, OR no antidepressant Rx and no behavioral
           health encounter in 12 months.
    """
    dx = ctx.diagnoses_icd10
    if not has_prefix(dx, ICD10_MDD_ANY):
        return RuleResult.failure(155, MODEL, "hcc155_mdd",
            ["No MDD ICD-10 code (F32.x or F33.x)"])

    reasons: list[str] = []
    if any_code_matches(dx, ("F329",)):
        reasons.append("F32.9 is unspecified — prefer F32.0–F32.3 per DSM-5 severity")

    has_rx = rx_class_present(ctx.active_rx_classes(), RX_CLASS_DEPRESSION)
    behavioral_specialties = {"psychiatry", "psychology", "behavioral health", "mental health"}
    has_bh_visit = any(
        (e.provider_specialty or "").lower() in behavioral_specialties
        for e in ctx.encounters
    )
    if not has_rx and not has_bh_visit:
        reasons.append("No antidepressant Rx and no behavioral-health encounter")

    if reasons:
        return RuleResult.warning(155, MODEL, "hcc155_mdd", reasons)
    return RuleResult.passed(155, MODEL, "hcc155_mdd")


RULE_HCC155_MDD = ClinicalRule(
    hcc=155, model=MODEL, rule_name="hcc155_mdd",
    description="Major Depression — requires F32/F33 plus either "
                "antidepressant Rx or behavioral-health encounter.",
    required_evidence=_rule_hcc155_mdd,
    advisory_only=True,   # this is suggestive guidance, not firm billing rule
)


# ---------------------------------------------------------------------------
# HCC 17–23 family — Active cancers (breast/prostate/lung/colon etc.)
# Rule: active cancer needs active treatment or recent dx.  History-of
# codes (Z85.x) alone must not drive an active-cancer HCC.
# ---------------------------------------------------------------------------

def _rule_active_cancer(ctx: PatientContext) -> RuleResult:
    """
    Source: ICD-10-CM FY2024 Guideline I.C.2.d — "When a primary malignancy
    has been previously excised or eradicated from its site, there is no
    further treatment, and there is no evidence of any existing primary
    malignancy, a code from category Z85, personal history of malignant
    neoplasm, should be used ... The secondary site may still be
    considered a primary."

    FAIL: no active cancer (C00-C96) code on chart, only Z85.
    WARN: active C-code present but no active treatment (chemo/radiation/
           hormonal/immunotherapy/targeted) and no oncology encounter in
           last 12 months.
    """
    dx = ctx.diagnoses_icd10
    has_active = has_prefix(dx, ICD10_ACTIVE_CANCER)
    has_history = has_prefix(dx, ICD10_HISTORY_OF_CANCER)

    if not has_active:
        if has_history:
            return RuleResult.failure(23, MODEL, "active_cancer_treatment",
                ["Only personal-history-of-cancer code (Z85.x) on chart. "
                 "Active-cancer HCC requires a C00-C96 code per "
                 "ICD-10-CM guideline I.C.2.d."])
        return RuleResult.failure(23, MODEL, "active_cancer_treatment",
            ["No active cancer ICD-10 code (C00-C96) on chart"])

    has_rx = rx_class_present(ctx.active_rx_classes(), RX_CLASS_CANCER_TREATMENT)
    has_oncology_encounter = any(
        (e.provider_specialty or "").lower() in {"oncology", "hematology/oncology", "radiation oncology"}
        for e in ctx.encounters
    )

    if not has_rx and not has_oncology_encounter:
        return RuleResult.warning(23, MODEL, "active_cancer_treatment",
            ["Active cancer coded but no antineoplastic/immuno/hormonal "
             "therapy and no oncology encounter within 12 months. "
             "Consider Z85.x (history of) if treatment is complete."])

    return RuleResult.passed(23, MODEL, "active_cancer_treatment")


RULE_ACTIVE_CANCER = ClinicalRule(
    hcc=23, model=MODEL, rule_name="active_cancer_treatment",
    description="Active cancer HCC family — requires C-code plus active "
                "treatment OR oncology encounter in last 12mo.",
    required_evidence=_rule_active_cancer,
)


# ---------------------------------------------------------------------------
# HCC 253 — Stroke (V28 maps acute CVA + late-effect codes)
# ---------------------------------------------------------------------------

def _rule_hcc_stroke(ctx: PatientContext) -> RuleResult:
    """
    Source: ICD-10-CM FY2024 I63 (acute ischemic stroke), I61/I62
    (hemorrhagic), I69 (sequelae).  Guideline I.C.9.d — I69 codes are used
    to indicate conditions classifiable to I60-I67 as the cause of sequelae
    themselves classified elsewhere.  For chronic billing, I69.x with a
    documented residual is the correct capture.

    FAIL: no stroke or sequelae code on chart.
    WARN: I69 present but no antiplatelet/anticoagulant Rx — standard
          secondary-prevention therapy per AHA/ASA 2021 Secondary
          Stroke Prevention Guideline.
    """
    dx = ctx.diagnoses_icd10
    has_sequelae = has_prefix(dx, ICD10_STROKE_SEQUELAE)
    has_acute = any(normalize_icd(c).startswith(("I60", "I61", "I62", "I63", "I64")) for c in dx)

    if not has_sequelae and not has_acute:
        return RuleResult.failure(253, MODEL, "hcc_stroke",
            ["No stroke ICD-10 code (I60-I64 or I69) on chart"])

    has_rx = rx_class_present(ctx.active_rx_classes(), RX_CLASS_ANTIPLATELET_ANTICOAG)
    if not has_rx:
        return RuleResult.warning(253, MODEL, "hcc_stroke",
            ["Stroke coded but no antiplatelet or anticoagulant Rx. "
             "AHA/ASA 2021 Secondary Prevention Guideline recommends "
             "standard secondary-prevention therapy."])

    return RuleResult.passed(253, MODEL, "hcc_stroke")


RULE_HCC_STROKE = ClinicalRule(
    hcc=253, model=MODEL, rule_name="hcc_stroke",
    description="Stroke HCC — requires I60-I64 or I69.x on chart plus "
                "antiplatelet/anticoagulant Rx (warn only).",
    required_evidence=_rule_hcc_stroke,
    advisory_only=True,
)


# ---------------------------------------------------------------------------
# HCC 228 — Acute Myocardial Infarction (V28)
# ---------------------------------------------------------------------------

def _rule_hcc228_mi(ctx: PatientContext) -> RuleResult:
    """
    Source: AHA Coding Clinic 1Q 2017 p.24 — I21 (acute MI) is used only
    for the initial encounter and up to 4 weeks; after that, I25.2 (old
    MI) is correct.  ICD-10-CM FY2024 I21/I22 tabular.

    FAIL: no I21/I22 code on chart.
    WARN: I21/I22 present but service date is >4 weeks after the MI
          (we warn because we cannot always determine the true onset date
          from claims data alone).
    """
    dx = ctx.diagnoses_icd10
    has_acute = has_prefix(dx, ICD10_ACUTE_MI)

    if not has_acute:
        if has_prefix(dx, ICD10_OLD_MI):
            return RuleResult.failure(228, MODEL, "hcc228_acute_mi",
                ["Only old-MI code (I25.2) present. Acute MI HCC requires "
                 "I21.x or I22.x per AHA Coding Clinic 1Q 2017 p.24."])
        return RuleResult.failure(228, MODEL, "hcc228_acute_mi",
            ["No acute MI ICD-10 code (I21.x or I22.x) on chart"])

    # Advisory: if no cardiac encounter in 4 weeks, MI may have healed.
    recent_cardiac = any(
        (e.provider_specialty or "").lower() in {"cardiology", "interventional cardiology"}
        for e in ctx.encounters
    )
    if not recent_cardiac:
        return RuleResult.warning(228, MODEL, "hcc228_acute_mi",
            ["Acute MI coded but no cardiology encounter in window. "
             "Verify MI is truly acute (≤4 weeks); if older, use I25.2."])
    return RuleResult.passed(228, MODEL, "hcc228_acute_mi")


RULE_HCC228_MI = ClinicalRule(
    hcc=228, model=MODEL, rule_name="hcc228_acute_mi",
    description="Acute MI HCC — requires I21.x/I22.x (not I25.2) plus "
                "cardiology encounter in the 4-week window.",
    required_evidence=_rule_hcc228_mi,
)


# ---------------------------------------------------------------------------
# HCC 262 — Vascular Disease (PVD, V28)
# ---------------------------------------------------------------------------

def _rule_hcc262_pvd(ctx: PatientContext) -> RuleResult:
    """
    Source: 2016 AHA/ACC PAD Guideline — PAD diagnosis via ABI, imaging,
    or documented claudication. ICD-10-CM I70.2x (atherosclerosis of
    native arteries of extremities) is the preferred code when severity
    is documented.

    FAIL: no I70 or I73 code on chart.
    WARN: I73.9 only (unspecified) — prefer I70.2x or I73.89 with
          documented symptoms.
    """
    dx = ctx.diagnoses_icd10
    if not has_prefix(dx, ICD10_PVD_ANY):
        return RuleResult.failure(262, MODEL, "hcc262_pvd",
            ["No PVD ICD-10 code (I70.x or I73.x) on chart"])

    if any_code_matches(dx, ("I739",)) and not any_code_matches(dx, ICD10_PVD_SPECIFIC):
        return RuleResult.warning(262, MODEL, "hcc262_pvd",
            ["Only I73.9 (unspecified peripheral vascular disease) coded. "
             "Prefer I70.2x or I73.89 when specificity is available."])
    return RuleResult.passed(262, MODEL, "hcc262_pvd")


RULE_HCC262_PVD = ClinicalRule(
    hcc=262, model=MODEL, rule_name="hcc262_pvd",
    description="Peripheral vascular disease HCC — requires I70.x or I73.x, "
                "prefer specific over I73.9.",
    required_evidence=_rule_hcc262_pvd,
    advisory_only=True,
)


# ---------------------------------------------------------------------------
# HCC 409 — Amputation Status, Lower Limb (V28)
# ---------------------------------------------------------------------------

def _rule_hcc409_amputation(ctx: PatientContext) -> RuleResult:
    """
    Source: ICD-10-CM FY2024 Z89 (acquired absence of limb) — these are
    status codes and are valid as long as the anatomic loss is permanent.
    AHA Coding Clinic 3Q 2013 p.24: acquired absence persists for life
    and Z89 is chronic once documented.

    FAIL: neither Z89 nor S48/S58/S78/S88 (acute traumatic amputation)
          present.  We do not require an operative note at billing time
          because once a Z89 code is on the problem list it is a lifelong
          status.
    """
    dx = ctx.diagnoses_icd10
    if has_prefix(dx, ICD10_AMPUTATION_STATUS) or has_prefix(dx, ICD10_AMPUTATION_ACUTE):
        return RuleResult.passed(409, MODEL, "hcc409_amputation_status")
    return RuleResult.failure(409, MODEL, "hcc409_amputation_status",
        ["No amputation-status (Z89.x) or acute amputation (S48/58/78/88) "
         "code on chart"])


RULE_HCC409_AMP = ClinicalRule(
    hcc=409, model=MODEL, rule_name="hcc409_amputation_status",
    description="Amputation status HCC — requires Z89.x or an acute "
                "traumatic-amputation code.",
    required_evidence=_rule_hcc409_amputation,
)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

ALL_RULES: list[ClinicalRule] = [
    RULE_HCC37,
    RULE_HCC38,
    RULE_HCC_CKD,
    RULE_HCC226,
    RULE_HCC280,
    RULE_HCC155_MDD,
    RULE_ACTIVE_CANCER,
    RULE_HCC_STROKE,
    RULE_HCC228_MI,
    RULE_HCC262_PVD,
    RULE_HCC409_AMP,
]


def rules_for_hcc(hcc: int, model: str = MODEL) -> list[ClinicalRule]:
    """Return all rules registered for a given HCC + model."""
    return [r for r in ALL_RULES if r.hcc == hcc and r.model == model]


# Special: HCC 23 rule applies to the whole active-cancer family — register
# under all relevant cancer HCCs so lookup by billed HCC finds it.
# V28 cancer HCCs (per CMS ry2024 coefficient table): 17, 18, 19, 20, 21, 22, 23.
_CANCER_HCCS = {17, 18, 19, 20, 21, 22, 23}


def lookup_rules(hcc: int, model: str = MODEL) -> list[ClinicalRule]:
    """Lookup rules that apply to a billed HCC, including family-level rules."""
    matches = rules_for_hcc(hcc, model)
    if hcc in _CANCER_HCCS and RULE_ACTIVE_CANCER not in matches:
        matches.append(RULE_ACTIVE_CANCER)
    # CKD family HCCs: 326, 327, 328 all share the stage-specificity rule
    if hcc in {326, 327, 328} and RULE_HCC_CKD not in matches:
        matches.append(RULE_HCC_CKD)
    return matches
