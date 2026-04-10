# DISCLAIMER: This module implements RxHCC and HHS-HCC risk adjustment models
# using hardcoded coefficient tables derived from publicly available CMS and HHS
# Rate Notice documentation. Coefficients are representative and intended for
# analytics, gap identification, and prospective modeling ONLY. They are NOT
# validated by CMS or HHS and MUST NOT be used for actual payment submissions.
# Always verify against official CMS/HHS software for payment determinations.

"""
Multi-Model RAF Calculation Engine.

=======================================================================
WARNING — RxHCC IMPLEMENTATION IS INCOMPLETE
=======================================================================
The RxHCC calculator in this module currently scores patients using ONLY
their diagnosis (ICD-10) codes. A real RxHCC calculation ALSO requires a
patient's pharmacy / medications data (NDC fills, drug class indicators,
therapy flags) which we do not yet persist. Until a medications / pharmacy
table is added and integrated:

  * RxHCC scores produced here are INVALID for any payment, submission,
    forecasting, or financial reporting use case.
  * They are suitable only as a rough diagnosis-driven proxy for internal
    gap identification and UI prototyping.
  * Coefficient and crosswalk tables live in
    `backend/app/model_constants.py` as PLACEHOLDER values and
    must be replaced with the official CMS / HHS crosswalks before any
    production use.
=======================================================================

Supports four risk adjustment models simultaneously:
  - CMS-HCC V24   — Medicare Advantage medical (prospective, prior-year dx)
  - CMS-HCC V28   — Medicare Advantage medical (prospective, prior-year dx, expanded)
  - RxHCC         — Medicare Part D / MAPD prescription drug costs
  - HHS-HCC       — ACA/Exchange marketplace (concurrent, includes pharmacy)

Key model differences:
  CMS-HCC: Prospective (prior year diagnoses predict next year costs). Pure medical.
  RxHCC:   Prospective (prior year dx). Drug-cost focused for Part D payment.
  HHS-HCC: Concurrent (same year dx). Includes pharmacy + medical. ACA/Exchange only.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

from app.model_constants import (
    HHSHCC_COEFFICIENTS as _HHSHCC_COEFFICIENTS,
    HHSHCC_DEMO_SCORES as _HHSHCC_DEMO_SCORES,
    HHSHCC_ICD_MAP as _HHSHCC_ICD_MAP,
    RXHCC_COEFFICIENTS as _RXHCC_COEFFICIENTS,
    RXHCC_DEMO_SCORES as _RXHCC_DEMO_SCORES,
    RXHCC_ICD_MAP as _RXHCC_ICD_MAP,
    get_age_band,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Model metadata registry
# ---------------------------------------------------------------------------

AVAILABLE_MODELS: dict[str, dict[str, Any]] = {
    "cms_hcc_v24": {
        "name": "CMS-HCC Model V24",
        "description": (
            "CMS Medicare Advantage risk adjustment model Version 24. "
            "Prospective model using prior-year diagnoses to predict current-year "
            "medical costs. Used for MA plan payment. Being phased out per CMS "
            "transition schedule (100% V28 by PY2026)."
        ),
        "use_case": "Medicare Advantage (MA) medical cost prediction",
        "population": "Medicare beneficiaries age 65+, disabled under 65",
        "model_type": "Prospective",
        "includes_pharmacy": False,
        "hcc_count": 86,
        "year_introduced": 2004,
        "status": "Phase-out (CMS transition to V28)",
    },
    "cms_hcc_v28": {
        "name": "CMS-HCC Model V28",
        "description": (
            "CMS Medicare Advantage risk adjustment model Version 28. "
            "Current production model for MA payment. Expands HCC categories "
            "to 115, improves chronic condition capture, and is the sole model "
            "for PY2026 and beyond."
        ),
        "use_case": "Medicare Advantage (MA) medical cost prediction",
        "population": "Medicare beneficiaries age 65+, disabled under 65",
        "model_type": "Prospective",
        "includes_pharmacy": False,
        "hcc_count": 115,
        "year_introduced": 2024,
        "status": "Current production (100% weight from PY2026)",
    },
    "rxhcc": {
        "name": "RxHCC Model (CMS Part D)",
        "description": (
            "CMS Prescription Drug HCC model for Medicare Part D risk adjustment. "
            "Prospective model that maps diagnoses to drug-cost-focused HCC categories. "
            "Used to calculate Part D risk scores for MAPD and PDP plans. "
            "Focuses on conditions that drive high prescription drug utilization "
            "such as HIV/AIDS, multiple sclerosis, cystic fibrosis, and oncology."
        ),
        "use_case": "Medicare Part D / MAPD prescription drug cost prediction",
        "population": "Medicare Part D enrollees",
        "model_type": "Prospective",
        "includes_pharmacy": True,
        "hcc_count": 83,
        "year_introduced": 2006,
        "status": "Current production",
        "key_differences": [
            "Drug-cost focused (not medical cost focused like CMS-HCC)",
            "Different HCC hierarchy — drug categories dominate",
            "Separate coefficients for Low Income Subsidy (LIS) vs non-LIS enrollees",
            "HIV/AIDS, MS, Cystic Fibrosis carry the highest coefficients",
            "Hypertension and common chronic conditions have very low coefficients",
        ],
    },
    "hhs_hcc": {
        "name": "HHS-HCC Model (ACA/Exchange)",
        "description": (
            "HHS risk adjustment model for ACA Marketplace / Exchange health plans "
            "under 45 CFR 153. Concurrent model using current-year diagnoses. "
            "Includes 127 HCC categories with three age-specific sub-models: "
            "Infant (age 0), Child (age 1-20), and Adult (age 21+). "
            "Calculates plan liability risk scores used for risk transfer payments "
            "between Exchange plans. Heavy focus on pregnancy and maternity conditions."
        ),
        "use_case": "ACA Exchange / Marketplace risk transfer between plans",
        "population": "ACA Marketplace enrollees (all ages, non-Medicare/Medicaid)",
        "model_type": "Concurrent",
        "includes_pharmacy": True,
        "hcc_count": 127,
        "year_introduced": 2014,
        "status": "Current production",
        "key_differences": [
            "Concurrent model — uses CURRENT year diagnoses (vs prior year for CMS-HCC)",
            "Three age sub-models: Infant, Child, Adult",
            "Heavy pregnancy/maternity focus (656 related codes)",
            "Includes pharmacy costs in the model",
            "Risk transfer formula: calculates dollar transfers between plans",
            "Age-sex curve differs significantly from CMS-HCC",
            "No dual-eligibility or OREC adjustments (ACA population is non-Medicare)",
        ],
    },
}


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def _normalize_icd(code: str) -> str:
    """Normalize ICD-10 code: strip whitespace, upper-case, remove dots."""
    return code.strip().upper().replace(".", "")


def _age_band_rxhcc(age: int) -> str:
    """Map age to RxHCC demographic age band (delegates to shared helper)."""
    return get_age_band(age, "rxhcc")


def _age_band_hhs(age: int) -> str:
    """Map age to HHS-HCC demographic age band (delegates to shared helper)."""
    return get_age_band(age, "hhs_hcc")


def _sex_normalized(sex: str) -> str:
    """Return 'F' or 'M'."""
    s = (sex or "").strip().upper()
    return "F" if s.startswith("F") else "M"


def _hhs_age_category(age: int) -> str:
    """Return HHS sub-model category: infant, child, or adult."""
    if age < 1:    return "infant"
    if age <= 20:  return "child"
    return "adult"


def _map_icd_to_rxhcc(icd_codes: list[str]) -> dict[int, list[str]]:
    """
    Map a list of ICD-10 codes to RxHCC categories.
    Returns {rxhcc_number: [icd_codes_that_mapped]}.
    Uses prefix matching — longer prefixes take priority.
    """
    hcc_to_codes: dict[int, list[str]] = {}

    for raw_code in icd_codes:
        code = _normalize_icd(raw_code)
        matched_rxhcc: int | None = None

        # Try progressively shorter prefixes (longest match first)
        for prefix_len in (7, 6, 5, 4, 3, 2):
            prefix = code[:prefix_len]
            if prefix in _RXHCC_ICD_MAP:
                matched_rxhcc = _RXHCC_ICD_MAP[prefix]
                break

        if matched_rxhcc is not None:
            hcc_to_codes.setdefault(matched_rxhcc, []).append(raw_code)

    return hcc_to_codes


def _map_icd_to_hhshcc(icd_codes: list[str]) -> dict[int, list[str]]:
    """
    Map a list of ICD-10 codes to HHS-HCC categories.
    Returns {hhs_hcc_number: [icd_codes_that_mapped]}.
    Uses prefix matching — longer prefixes take priority.
    """
    hcc_to_codes: dict[int, list[str]] = {}

    for raw_code in icd_codes:
        code = _normalize_icd(raw_code)
        matched_hcc: int | None = None

        for prefix_len in (7, 6, 5, 4, 3, 2):
            prefix = code[:prefix_len]
            if prefix in _HHSHCC_ICD_MAP:
                matched_hcc = _HHSHCC_ICD_MAP[prefix]
                break

        if matched_hcc is not None:
            hcc_to_codes.setdefault(matched_hcc, []).append(raw_code)

    return hcc_to_codes


# ---------------------------------------------------------------------------
# RxHCC Model Calculator
# ---------------------------------------------------------------------------

def calculate_rxhcc(
    icd_codes: list[str],
    age: int,
    sex: str,
    low_income_subsidy: bool = False,
    payment_year: int = 2026,
) -> dict[str, Any]:
    """
    Calculate RxHCC risk score for a Medicare Part D enrollee.

    Parameters
    ----------
    icd_codes:          ICD-10 codes (prior year diagnoses).
    age:                Patient age as of February 1 of the payment year.
    sex:                'M' or 'F'.
    low_income_subsidy: True if patient receives Low Income Subsidy (LIS).
    payment_year:       CMS payment year.

    Returns a structured dict with:
    - rx_raf_score:   Final RxHCC risk score
    - demographic_score: Age/sex/LIS base score
    - disease_score:  Sum of RxHCC coefficients
    - rxhcc_list:     Active RxHCC categories (numbers)
    - rxhcc_details:  Per-category breakdowns
    - hcc_to_codes:   Which ICD-10 codes triggered each RxHCC
    """
    sex_norm = _sex_normalized(sex)
    lis_key = "LI" if low_income_subsidy else "NLI"
    age_band = _age_band_rxhcc(age)
    coeff_key = f"{lis_key}_{sex_norm}"  # e.g. "NLI_F"

    # Demographic base score
    demo_score = _RXHCC_DEMO_SCORES.get((age_band, sex_norm, lis_key), 0.250)

    # Map ICD codes to RxHCC categories
    hcc_to_codes = _map_icd_to_rxhcc(icd_codes)

    # Accumulate disease score
    rxhcc_details: list[dict[str, Any]] = []
    disease_score = 0.0

    for rxhcc_num in sorted(hcc_to_codes.keys()):
        coeff_entry = _RXHCC_COEFFICIENTS.get(rxhcc_num)
        if not coeff_entry:
            continue

        coefficient = coeff_entry.get(coeff_key, 0.0)
        disease_score += coefficient

        rxhcc_details.append({
            "rxhcc_code": rxhcc_num,
            "rxhcc_label": coeff_entry["description"],
            "coefficient": round(coefficient, 4),
            "icd10_codes": hcc_to_codes[rxhcc_num],
            "lis_segment": lis_key,
        })

    total_score = round(demo_score + disease_score, 4)

    return {
        "model": "rxhcc",
        "model_name": "RxHCC (Medicare Part D)",
        "payment_year": payment_year,
        "rx_raf_score": total_score,
        "demographic_score": round(demo_score, 4),
        "disease_score": round(disease_score, 4),
        "rxhcc_list": sorted(hcc_to_codes.keys()),
        "rxhcc_count": len(rxhcc_details),
        "rxhcc_details": rxhcc_details,
        "hcc_to_codes": {str(k): v for k, v in hcc_to_codes.items()},
        "patient_demographics": {
            "age": age,
            "sex": sex_norm,
            "age_band": age_band,
            "low_income_subsidy": low_income_subsidy,
            "lis_segment": lis_key,
        },
        "model_notes": [
            "RxHCC is a PROSPECTIVE model — uses prior-year diagnoses",
            "Score predicts prescription drug costs (not total medical costs)",
            "Low Income Subsidy (LIS) status affects coefficients and baseline",
            "Higher scores indicate higher expected drug spending",
        ],
    }


# ---------------------------------------------------------------------------
# HHS-HCC Model Calculator
# ---------------------------------------------------------------------------

def calculate_hhs_hcc(
    icd_codes: list[str],
    age: int,
    sex: str,
    metal_level: str = "silver",
    payment_year: int = 2026,
) -> dict[str, Any]:
    """
    Calculate HHS-HCC risk score for an ACA Exchange enrollee.

    Parameters
    ----------
    icd_codes:    ICD-10 codes (CURRENT year diagnoses — concurrent model).
    age:          Patient age.
    sex:          'M' or 'F'.
    metal_level:  ACA metal tier (bronze/silver/gold/platinum) — affects CSR.
    payment_year: Plan year.

    Returns a structured dict with:
    - hhs_raf_score:    Final HHS-HCC risk score (PLRS — Plan Liability Risk Score)
    - demographic_score: Age/sex base score
    - disease_score:    Sum of HHS-HCC coefficients
    - hhs_hcc_list:     Active HHS-HCC categories
    - hhs_hcc_details:  Per-category breakdowns
    - risk_transfer_indicator: Directional indicator for risk transfer
    """
    sex_norm = _sex_normalized(sex)
    age_band = _age_band_hhs(age)
    age_category = _hhs_age_category(age)

    # Demographic base score (age-sex factor)
    demo_score = _HHSHCC_DEMO_SCORES.get((age_band, sex_norm), 0.400)

    # Map ICD codes to HHS-HCC categories
    hcc_to_codes = _map_icd_to_hhshcc(icd_codes)

    # Accumulate disease score using age-category-appropriate coefficients
    hhs_hcc_details: list[dict[str, Any]] = []
    disease_score = 0.0

    for hhs_hcc_num in sorted(hcc_to_codes.keys()):
        coeff_entry = _HHSHCC_COEFFICIENTS.get(hhs_hcc_num)
        if not coeff_entry:
            continue

        coefficient = coeff_entry.get(age_category, 0.0)
        disease_score += coefficient

        hhs_hcc_details.append({
            "hhs_hcc_code": hhs_hcc_num,
            "hhs_hcc_label": coeff_entry["description"],
            "coefficient": round(coefficient, 4),
            "icd10_codes": hcc_to_codes[hhs_hcc_num],
            "age_model": age_category,
        })

    # HHS applies a Statewide Average Premium (SAP) and induced demand factor.
    # For analytics purposes we approximate the Plan Liability Risk Score (PLRS).
    # Full transfer amount requires state-specific SAP, which is out of scope here.
    plan_liability_risk_score = round(demo_score + disease_score, 4)

    # Directional risk transfer indicator (simplified)
    # Scores > 1.0 indicate plan likely receives risk transfer (high-cost enrollees)
    # Scores < 1.0 indicate plan likely pays into risk pool (lower-cost enrollees)
    if plan_liability_risk_score > 1.2:
        risk_transfer_direction = "RECEIVE"
        risk_transfer_note = "Plan likely receives risk transfer payment (high-risk enrollees)"
    elif plan_liability_risk_score < 0.8:
        risk_transfer_direction = "PAY"
        risk_transfer_note = "Plan likely pays into risk pool (lower-risk enrollees)"
    else:
        risk_transfer_direction = "NEUTRAL"
        risk_transfer_note = "Plan near average risk — minimal net transfer expected"

    # Pregnancy flag
    pregnancy_hccs = [h for h in hcc_to_codes.keys() if h in (160, 161, 162, 163, 164)]
    has_pregnancy = len(pregnancy_hccs) > 0

    return {
        "model": "hhs_hcc",
        "model_name": "HHS-HCC (ACA Exchange)",
        "payment_year": payment_year,
        "hhs_raf_score": plan_liability_risk_score,
        "plan_liability_risk_score": plan_liability_risk_score,
        "demographic_score": round(demo_score, 4),
        "disease_score": round(disease_score, 4),
        "hhs_hcc_list": sorted(hcc_to_codes.keys()),
        "hhs_hcc_count": len(hhs_hcc_details),
        "hhs_hcc_details": hhs_hcc_details,
        "hcc_to_codes": {str(k): v for k, v in hcc_to_codes.items()},
        "risk_transfer": {
            "direction": risk_transfer_direction,
            "note": risk_transfer_note,
            "approximate_score": plan_liability_risk_score,
            "caveat": "Full transfer amount requires state SAP — not available here",
        },
        "pregnancy_detected": has_pregnancy,
        "pregnancy_hccs": pregnancy_hccs,
        "patient_demographics": {
            "age": age,
            "sex": sex_norm,
            "age_band": age_band,
            "age_model_category": age_category,
            "metal_level": metal_level,
        },
        "model_notes": [
            "HHS-HCC is a CONCURRENT model — uses CURRENT year diagnoses",
            "Includes medical AND pharmacy costs (unlike CMS-HCC which is medical-only)",
            "Three sub-models: Infant (age <1), Child (age 1-20), Adult (age 21+)",
            "Score is used for risk transfer between ACA Exchange plans — NOT for Medicare",
            "Pregnancy conditions are a major driver in this model",
        ],
    }


# ---------------------------------------------------------------------------
# HCC Overlap Analysis
# ---------------------------------------------------------------------------

def _analyze_hcc_overlap(
    icd_codes: list[str],
    cms_hcc_list: list[str],
    rxhcc_map: dict[int, list[str]],
    hhshcc_map: dict[int, list[str]],
) -> dict[str, Any]:
    """
    Analyze which ICD-10 codes map to HCCs across models and identify overlaps.
    """
    cms_hcc_set = set(str(h).replace("HCC", "").strip() for h in cms_hcc_list)
    rxhcc_set = set(str(h) for h in rxhcc_map.keys())
    hhshcc_set = set(str(h) for h in hhshcc_map.keys())

    # Per-code model coverage
    code_coverage: list[dict[str, Any]] = []
    rxhcc_coded_icds = set(
        code for codes in rxhcc_map.values() for code in codes
    )
    hhshcc_coded_icds = set(
        code for codes in hhshcc_map.values() for code in codes
    )

    for code in icd_codes:
        in_rxhcc = code in rxhcc_coded_icds
        in_hhshcc = code in hhshcc_coded_icds

        # CMS-HCC mapping is handled by hccinfhir — approximate with code presence
        coverage: list[str] = []
        if len(cms_hcc_list) > 0:
            coverage.append("cms_hcc")  # CMS-HCC was run with these codes
        if in_rxhcc:
            coverage.append("rxhcc")
        if in_hhshcc:
            coverage.append("hhs_hcc")

        if in_rxhcc or in_hhshcc:
            code_coverage.append({
                "icd_code": code,
                "in_rxhcc": in_rxhcc,
                "in_hhs_hcc": in_hhshcc,
                "models_covered": coverage,
            })

    return {
        "total_icd_codes": len(icd_codes),
        "cms_hcc_count": len(cms_hcc_set),
        "rxhcc_count": len(rxhcc_set),
        "hhs_hcc_count": len(hhshcc_set),
        "codes_mapped_in_rxhcc": len(rxhcc_coded_icds),
        "codes_mapped_in_hhs_hcc": len(hhshcc_coded_icds),
        "codes_in_both_rxhcc_and_hhs": len(rxhcc_coded_icds & hhshcc_coded_icds),
        "per_code_coverage": code_coverage,
        "note": (
            "CMS-HCC mapping is via hccinfhir (see cms_hcc result). "
            "RxHCC and HHS-HCC mappings are from internal coefficient tables."
        ),
    }


# ---------------------------------------------------------------------------
# Revenue Impact Comparison
# ---------------------------------------------------------------------------

_MEDICARE_MONTHLY_RATE: float = 1_100.0   # Approximate CY2026 MA monthly rate per member
_PART_D_MONTHLY_RATE: float   = 120.0     # Approximate CY2026 Part D monthly rate per member
_ACA_MONTHLY_PREMIUM: float   = 480.0     # National average ACA Silver premium (2024)


def _build_revenue_comparison(
    cms_hcc_score: float | None,
    rxhcc_score: float | None,
    hhs_score: float | None,
    payment_year: int,
) -> dict[str, Any]:
    """
    Build a simplified revenue impact comparison across models.

    Note: These are ILLUSTRATIVE estimates. Actual plan payment involves
    county-level benchmark rates, normalization, and other CMS adjustments.
    """
    comparison: list[dict[str, Any]] = []

    if cms_hcc_score is not None:
        annual_ma = round(cms_hcc_score * _MEDICARE_MONTHLY_RATE * 12, 2)
        comparison.append({
            "model": "CMS-HCC (MA Medical)",
            "risk_score": round(cms_hcc_score, 4),
            "estimated_monthly_revenue": round(cms_hcc_score * _MEDICARE_MONTHLY_RATE, 2),
            "estimated_annual_revenue": annual_ma,
            "rate_basis": f"~${_MEDICARE_MONTHLY_RATE}/mo national average (illustrative)",
        })

    if rxhcc_score is not None:
        annual_partd = round(rxhcc_score * _PART_D_MONTHLY_RATE * 12, 2)
        comparison.append({
            "model": "RxHCC (Part D Drug)",
            "risk_score": round(rxhcc_score, 4),
            "estimated_monthly_revenue": round(rxhcc_score * _PART_D_MONTHLY_RATE, 2),
            "estimated_annual_revenue": annual_partd,
            "rate_basis": f"~${_PART_D_MONTHLY_RATE}/mo Part D base rate (illustrative)",
        })

    if hhs_score is not None:
        annual_aca = round(hhs_score * _ACA_MONTHLY_PREMIUM * 12, 2)
        comparison.append({
            "model": "HHS-HCC (ACA Exchange)",
            "risk_score": round(hhs_score, 4),
            "estimated_monthly_revenue": round(hhs_score * _ACA_MONTHLY_PREMIUM, 2),
            "estimated_annual_revenue": annual_aca,
            "rate_basis": f"~${_ACA_MONTHLY_PREMIUM}/mo national avg Silver premium (illustrative)",
        })

    return {
        "payment_year": payment_year,
        "revenue_estimates": comparison,
        "disclaimer": (
            "Revenue estimates are ILLUSTRATIVE only. Actual MA, Part D, and ACA payments "
            "depend on county benchmarks, blend weights, normalization, risk corridors, "
            "and many other plan-specific and market-specific factors. "
            "Do not use for actual payment calculations or forecasting."
        ),
    }


# ---------------------------------------------------------------------------
# Recommended Actions per Model
# ---------------------------------------------------------------------------

def _build_recommendations(
    cms_hcc_score: float | None,
    cms_hcc_details: list[dict[str, Any]],
    rxhcc_details: list[dict[str, Any]],
    hhs_hcc_details: list[dict[str, Any]],
    icd_codes: list[str],
) -> list[dict[str, Any]]:
    """
    Generate actionable recommendations based on multi-model findings.
    """
    recs: list[dict[str, Any]] = []

    # CMS-HCC opportunities
    if cms_hcc_score is not None and cms_hcc_score < 1.0:
        recs.append({
            "priority": "HIGH",
            "model": "CMS-HCC",
            "action": "Risk Score Improvement",
            "detail": (
                f"CMS-HCC score of {round(cms_hcc_score, 3)} is below the population average (1.0). "
                "Review chronic conditions for documentation completeness. "
                "Ensure MEAT criteria are met for all coded HCCs."
            ),
        })

    # High-value RxHCC opportunities
    high_value_rxhcc = [
        r for r in rxhcc_details
        if r["coefficient"] >= 1.0
    ]
    if high_value_rxhcc:
        hv_names = ", ".join(r["rxhcc_label"] for r in high_value_rxhcc[:3])
        recs.append({
            "priority": "HIGH",
            "model": "RxHCC",
            "action": "High-Cost Drug Conditions Identified",
            "detail": (
                f"Patient has {len(high_value_rxhcc)} high-cost RxHCC condition(s): {hv_names}. "
                "Verify adherence to specialty drug regimens. "
                "Medication therapy management (MTM) eligibility should be evaluated."
            ),
        })

    # Pregnancy flag for HHS-HCC
    pregnancy_hccs = [
        h for h in hhs_hcc_details
        if h["hhs_hcc_code"] in (160, 161, 162, 163, 164)
    ]
    if pregnancy_hccs:
        recs.append({
            "priority": "HIGH",
            "model": "HHS-HCC",
            "action": "Pregnancy Conditions Detected",
            "detail": (
                "Pregnancy-related HHS-HCC categories are active. "
                "Ensure complete prenatal care documentation and maternity management enrollment. "
                "High-risk pregnancy conditions significantly increase plan liability score."
            ),
        })

    # General coding quality
    if len(icd_codes) > 0 and len(rxhcc_details) == 0 and len(hhs_hcc_details) == 0:
        recs.append({
            "priority": "MEDIUM",
            "model": "ALL",
            "action": "Diagnosis Codes Not Mapped to Risk HCCs",
            "detail": (
                f"None of the {len(icd_codes)} ICD-10 codes mapped to RxHCC or HHS-HCC categories. "
                "Review coding completeness. Many codes may be for acute/non-chronic conditions "
                "that do not affect risk scores."
            ),
        })

    if not recs:
        recs.append({
            "priority": "LOW",
            "model": "ALL",
            "action": "No Immediate Actions Required",
            "detail": "Multi-model analysis complete. No high-priority gaps identified at this time.",
        })

    return recs


# ---------------------------------------------------------------------------
# Multi-Model Calculator — main entry point
# ---------------------------------------------------------------------------

def calculate_multi_model(
    patient_id: int,
    icd_codes: list[str],
    age: int,
    sex: str,
    models: list[str] | None = None,
    payment_year: int = 2026,
    # RxHCC-specific
    low_income_subsidy: bool = False,
    # HHS-HCC-specific
    metal_level: str = "silver",
    # CMS-HCC passthrough (optional pre-computed result)
    cms_hcc_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Run multiple RAF models simultaneously and return comparative results.

    Parameters
    ----------
    patient_id:        Patient identifier (for labeling; no DB lookup here).
    icd_codes:         ICD-10 diagnosis codes (list of strings, dots optional).
    age:               Patient age (CMS convention: as of Feb 1 of payment year).
    sex:               'M' or 'F' (or 'Male'/'Female').
    models:            Subset of models to run. Default: all four models.
                       Options: 'cms_hcc_v24', 'cms_hcc_v28', 'rxhcc', 'hhs_hcc'.
    payment_year:      Payment/plan year.
    low_income_subsidy: RxHCC — True if patient has LIS/Extra Help for Part D.
    metal_level:       HHS-HCC — ACA plan metal tier (bronze/silver/gold/platinum).
    cms_hcc_result:    Optional pre-computed CMS-HCC result dict (from raf_calculator).
                       If not provided and 'cms_hcc_v28' is in models, the CMS-HCC
                       section will be empty (run via the existing /calculate endpoint first).

    Returns
    -------
    dict with:
    - patient_id, models_run, payment_year
    - per_model_scores: {model_key: full result dict}
    - score_summary: quick comparison table
    - hcc_overlap_analysis: which codes map to which models
    - revenue_impact_comparison: estimated payment impact per model
    - recommended_actions: prioritized action list
    - model_descriptions: human-readable model explanations
    """
    if models is None:
        models = ["cms_hcc_v28", "rxhcc", "hhs_hcc"]

    # Validate model selection
    valid_models = set(AVAILABLE_MODELS.keys())
    invalid = [m for m in models if m not in valid_models]
    if invalid:
        raise ValueError(
            f"Unknown model(s): {invalid}. Valid options: {sorted(valid_models)}"
        )

    results: dict[str, Any] = {}
    errors: dict[str, str] = {}

    # --- CMS-HCC V24 / V28 ---
    # These are handled by the existing hccinfhir-based calculator.
    # If a pre-computed result is passed in, include it; otherwise note the gap.
    if "cms_hcc_v24" in models or "cms_hcc_v28" in models:
        if cms_hcc_result is not None:
            cms_model_key = cms_hcc_result.get("model_version", "cms_hcc_v28")
            normalized_key = f"cms_hcc_{cms_model_key}" if not cms_model_key.startswith("cms") else cms_model_key
            results["cms_hcc"] = cms_hcc_result
        else:
            # Provide a placeholder so the caller knows CMS-HCC wasn't computed here
            results["cms_hcc"] = {
                "model": "cms_hcc",
                "model_status": "not_computed",
                "note": (
                    "CMS-HCC calculation is handled by the hccinfhir-based engine. "
                    "Call POST /api/raf/calculate/{pid} or GET /api/raf/scores/{pid}/model-comparison "
                    "for CMS-HCC V24/V28 scores, then pass cms_hcc_result to multi-model."
                ),
                "cms_hcc_score": None,
                "hcc_list": [],
            }

    # --- RxHCC ---
    if "rxhcc" in models:
        try:
            results["rxhcc"] = calculate_rxhcc(
                icd_codes=icd_codes,
                age=age,
                sex=sex,
                low_income_subsidy=low_income_subsidy,
                payment_year=payment_year,
            )
        except Exception as exc:
            logger.error("RxHCC calculation error pid=%s: %s", patient_id, exc, exc_info=True)
            errors["rxhcc"] = str(exc)

    # --- HHS-HCC ---
    if "hhs_hcc" in models:
        try:
            results["hhs_hcc"] = calculate_hhs_hcc(
                icd_codes=icd_codes,
                age=age,
                sex=sex,
                metal_level=metal_level,
                payment_year=payment_year,
            )
        except Exception as exc:
            logger.error("HHS-HCC calculation error pid=%s: %s", patient_id, exc, exc_info=True)
            errors["hhs_hcc"] = str(exc)

    # --- Score Summary ---
    cms_score = None
    if "cms_hcc" in results and results["cms_hcc"].get("cms_hcc_score") is not None:
        cms_score = float(results["cms_hcc"]["cms_hcc_score"])
    elif "cms_hcc" in results and results["cms_hcc"].get("raf_score") is not None:
        cms_score = float(results["cms_hcc"]["raf_score"])

    rxhcc_score = None
    if "rxhcc" in results:
        rxhcc_score = results["rxhcc"].get("rx_raf_score")

    hhs_score = None
    if "hhs_hcc" in results:
        hhs_score = results["hhs_hcc"].get("hhs_raf_score")

    score_summary: list[dict[str, Any]] = []
    if cms_score is not None:
        score_summary.append({
            "model": "CMS-HCC",
            "model_key": "cms_hcc",
            "risk_score": round(cms_score, 4),
            "above_average": cms_score > 1.0,
            "use_case": "Medicare Advantage medical payment",
        })
    if rxhcc_score is not None:
        score_summary.append({
            "model": "RxHCC",
            "model_key": "rxhcc",
            "risk_score": round(rxhcc_score, 4),
            "above_average": rxhcc_score > 1.0,
            "use_case": "Medicare Part D drug payment",
        })
    if hhs_score is not None:
        score_summary.append({
            "model": "HHS-HCC",
            "model_key": "hhs_hcc",
            "risk_score": round(hhs_score, 4),
            "above_average": hhs_score > 1.0,
            "use_case": "ACA Exchange risk transfer",
        })

    # --- HCC Overlap Analysis ---
    cms_hcc_list = []
    if "cms_hcc" in results:
        cms_hcc_list = (
            results["cms_hcc"].get("final_hcc_list")
            or results["cms_hcc"].get("v28_hcc_list")
            or results["cms_hcc"].get("hcc_list")
            or []
        )

    rxhcc_map = _map_icd_to_rxhcc(icd_codes)
    hhshcc_map = _map_icd_to_hhshcc(icd_codes)
    overlap_analysis = _analyze_hcc_overlap(icd_codes, cms_hcc_list, rxhcc_map, hhshcc_map)

    # --- Revenue Impact ---
    revenue_comparison = _build_revenue_comparison(
        cms_hcc_score=cms_score,
        rxhcc_score=rxhcc_score,
        hhs_score=hhs_score,
        payment_year=payment_year,
    )

    # --- Recommendations ---
    rxhcc_details_for_recs = results.get("rxhcc", {}).get("rxhcc_details", [])
    hhs_details_for_recs = results.get("hhs_hcc", {}).get("hhs_hcc_details", [])
    recommendations = _build_recommendations(
        cms_hcc_score=cms_score,
        cms_hcc_details=[],
        rxhcc_details=rxhcc_details_for_recs,
        hhs_hcc_details=hhs_details_for_recs,
        icd_codes=icd_codes,
    )

    # --- Model Descriptions for this run ---
    model_descriptions = {
        m: AVAILABLE_MODELS.get(m, {"name": m, "description": "Unknown model"})
        for m in models
    }

    # Explicit per-model completeness / validity status so the frontend
    # can surface warnings instead of relying on free-form "note" strings.
    model_status: dict[str, dict[str, Any]] = {}
    if "cms_hcc_v24" in models or "cms_hcc_v28" in models:
        if cms_hcc_result is not None:
            model_status["cms_hcc"] = {
                "complete": True,
                "valid_for_payment": False,
                "message": "CMS-HCC score supplied by hccinfhir engine (analytics use only).",
            }
        else:
            model_status["cms_hcc"] = {
                "complete": False,
                "valid_for_payment": False,
                "message": (
                    "CMS-HCC not computed in this call. Invoke the hccinfhir-based "
                    "endpoint and pass cms_hcc_result to populate this field."
                ),
            }
    if "rxhcc" in models:
        model_status["rxhcc"] = {
            "complete": False,
            "valid_for_payment": False,
            "message": (
                "RxHCC is currently scored from ICD diagnoses only. A real RxHCC "
                "calculation also requires pharmacy / medications data (NDC fills, "
                "drug class indicators), which is not yet persisted. Treat results "
                "as a diagnosis-driven proxy only."
            ),
        }
    if "hhs_hcc" in models:
        model_status["hhs_hcc"] = {
            "complete": False,
            "valid_for_payment": False,
            "message": (
                "HHS-HCC uses PLACEHOLDER coefficient and crosswalk tables from "
                "backend/app/model_constants.py. Replace with the official "
                "HHS crosswalk before any production use."
            ),
        }

    return {
        "patient_id": patient_id,
        "payment_year": payment_year,
        "models_requested": models,
        "models_run": [m for m in models if m in results or m.startswith("cms")],
        "calculation_errors": errors,
        "model_status": model_status,
        "per_model_scores": results,
        "score_summary": score_summary,
        "hcc_overlap_analysis": overlap_analysis,
        "revenue_impact_comparison": revenue_comparison,
        "recommended_actions": recommendations,
        "model_descriptions": model_descriptions,
        "input_summary": {
            "icd_code_count": len(icd_codes),
            "icd_codes": icd_codes,
            "age": age,
            "sex": _sex_normalized(sex),
            "low_income_subsidy": low_income_subsidy,
            "metal_level": metal_level,
        },
        "disclaimer": (
            "Multi-model RAF results are for analytics and gap identification only. "
            "CMS-HCC uses hccinfhir (third-party, not CMS-validated). "
            "RxHCC and HHS-HCC use representative hardcoded coefficients "
            "and MUST NOT be used for actual payment submissions. "
            "Verify all results against official CMS/HHS software."
        ),
    }
