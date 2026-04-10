"""
hccinfhir_utils.py

Single interface layer between application code and the hccinfhir library.

All other modules in this codebase should import HCC/RAF utilities from here
rather than directly from hccinfhir. This isolates hccinfhir API details to
one place and keeps call sites clean.

Key internal facts about hccinfhir (V28, 2026 data files):
  - Coefficient keys are stored as lowercase strings, e.g. "cna_hcc37", "cna_f70_74".
    The prefix is determined by dual status + age + institutional/new-enrollee flags.
  - Demographic category strings follow the pattern F65_69 / M65_69 (non-enrollee)
    or NEF65 / NEM65 (new enrollee), determined by model_demographics.categorize_demographics.
  - dx_to_cc_default maps (icd10, model_name) -> Set[str] of CC numbers (as strings, no "HCC" prefix).
  - labels_default maps (cc_number_str, model_name) -> human-readable label.
  - coefficients_default maps (lowercase_key, model_name) -> float.
  - calculate_raf returns coefficient keys WITHOUT the prefix: e.g. "37" for HCC 37,
    "F70_74" for the age-sex demographic category.
"""

from __future__ import annotations

from typing import Optional

from hccinfhir.model_calculate import calculate_raf
from hccinfhir.model_coefficients import get_coefficent_prefix
from hccinfhir.model_demographics import categorize_demographics
from hccinfhir.defaults import (
    dx_to_cc_default,
    coefficients_default,
    labels_default,
    is_chronic_default,
)
from hccinfhir.datamodels import ModelName

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

DEFAULT_MODEL: ModelName = "CMS-HCC Model V28"

# ---------------------------------------------------------------------------
# ICD-10 → HCC lookup
# ---------------------------------------------------------------------------

def lookup_hcc(icd10_code: str, model: ModelName = DEFAULT_MODEL) -> dict:
    """Return HCC mapping details for a single ICD-10 code.

    Looks up the code against the 2026 V28 dx-to-CC mapping and enriches
    each mapped CC with its label, chronic flag, and a representative
    coefficient drawn from the CNA_ (Community Non-Dual Aged) prefix —
    the most common community segment and a reliable reference value.

    Args:
        icd10_code: ICD-10-CM code, e.g. "E1169".  Case-sensitive; use
                    uppercase as CMS publishes codes.
        model: HCC model name.  Defaults to "CMS-HCC Model V28".

    Returns:
        dict with keys:
          icd10_code    – the input code (str)
          model         – model name used (str)
          maps_to_hcc   – True if any CC mapping exists (bool)
          hcc_codes     – list of CC number strings, e.g. ["37"] (list[str])
          hcc_details   – list of dicts, one per CC:
                            hcc_code  (str)
                            label     (str | None)
                            is_chronic (bool)
                            reference_coefficient (float | None)
    """
    code = icd10_code.strip().upper()
    cc_set: set[str] = dx_to_cc_default.get((code, model), set())

    details = []
    for cc in sorted(cc_set):
        label = labels_default.get((cc, model))
        is_chronic = is_chronic_default.get((cc, model), False)
        # CNA_ prefix = Community Non-Dual Aged, the standard reference segment
        coeff_key = (f"cna_hcc{cc}", model)
        ref_coeff = coefficients_default.get(coeff_key)
        details.append(
            {
                "hcc_code": cc,
                "label": label,
                "is_chronic": is_chronic,
                "reference_coefficient": ref_coeff,
            }
        )

    return {
        "icd10_code": code,
        "model": model,
        "maps_to_hcc": bool(cc_set),
        "hcc_codes": sorted(cc_set),
        "hcc_details": details,
    }


def lookup_hcc_batch(
    icd10_codes: list[str], model: ModelName = DEFAULT_MODEL
) -> list[dict]:
    """Return HCC mapping details for a list of ICD-10 codes.

    Args:
        icd10_codes: List of ICD-10-CM codes.
        model: HCC model name.  Defaults to "CMS-HCC Model V28".

    Returns:
        List of dicts in the same format as lookup_hcc(), one entry per
        input code, preserving input order.
    """
    return [lookup_hcc(code, model=model) for code in icd10_codes]


# ---------------------------------------------------------------------------
# HCC metadata
# ---------------------------------------------------------------------------

def get_hcc_label(hcc_code: str, model: ModelName = DEFAULT_MODEL) -> str:
    """Return the human-readable label for an HCC code.

    Args:
        hcc_code: CC number as a string, e.g. "37" or "HCC37".
                  The "HCC" prefix is stripped automatically.
        model: HCC model name.  Defaults to "CMS-HCC Model V28".

    Returns:
        Label string, or an empty string if the code is not found.
    """
    cc = hcc_code.upper()
    if cc.startswith("HCC"):
        cc = cc[3:]
    # labels_default stores keys without leading zeros (e.g. "37" not "037")
    cc_norm = cc.lstrip("0") or cc
    return labels_default.get((cc_norm, model), "")


def get_hcc_coefficient(
    hcc_code: str,
    model: ModelName = DEFAULT_MODEL,
    prefix: str = "CNA_",
) -> float:
    """Return the coefficient for an HCC code under a given demographic prefix.

    Args:
        hcc_code: CC number as a string, e.g. "37" or "HCC37".
        model: HCC model name.  Defaults to "CMS-HCC Model V28".
        prefix: CMS demographic segment prefix, e.g. "CNA_" (Community
                Non-Dual Aged — the default), "CFA_" (Full Dual Aged),
                "INS_" (Institutional), etc.  See hccinfhir.datamodels.PrefixOverride
                for the full set of valid prefixes.

    Returns:
        Coefficient as a float, or 0.0 if the code/prefix combo is not found.
    """
    cc = hcc_code.upper().replace("HCC", "").lstrip("0") or hcc_code
    key = (f"{prefix.lower()}hcc{cc}", model)
    return coefficients_default.get(key, 0.0)


# ---------------------------------------------------------------------------
# Quick risk-adjusting check
# ---------------------------------------------------------------------------

def is_risk_adjusting(icd10_code: str, model: ModelName = DEFAULT_MODEL) -> bool:
    """Return True if the ICD-10 code maps to at least one HCC in the model.

    Args:
        icd10_code: ICD-10-CM code, e.g. "E1169".
        model: HCC model name.  Defaults to "CMS-HCC Model V28".

    Returns:
        True if the code maps to one or more condition categories, else False.
    """
    code = icd10_code.strip().upper()
    return bool(dx_to_cc_default.get((code, model)))


# ---------------------------------------------------------------------------
# Full HCC catalogue
# ---------------------------------------------------------------------------

def get_all_v28_hccs() -> dict[str, dict]:
    """Return all HCC codes for the V28 model with labels and CNA_ coefficients.

    Iterates the labels table (which is the authoritative list of valid HCC
    codes for a model) and attaches chronic flag and reference coefficient.

    Returns:
        dict keyed by HCC code string (e.g. "37"), each value a dict:
          label                 (str | None)
          is_chronic            (bool)
          reference_coefficient (float | None)  – CNA_ segment coefficient
    """
    model = DEFAULT_MODEL
    result: dict[str, dict] = {}

    for (cc, mdl), label in labels_default.items():
        if mdl != model:
            continue
        is_chronic = is_chronic_default.get((cc, model), False)
        coeff_key = (f"cna_hcc{cc}", model)
        ref_coeff = coefficients_default.get(coeff_key)
        result[cc] = {
            "label": label,
            "is_chronic": is_chronic,
            "reference_coefficient": ref_coeff,
        }

    return result


# ---------------------------------------------------------------------------
# Demographic coefficient
# ---------------------------------------------------------------------------

def get_demographic_coefficient(
    age: int,
    sex: str,
    dual_elgbl_cd: str = "NA",
    orec: str = "0",
    new_enrollee: bool = False,
    lti: bool = False,
    model: ModelName = DEFAULT_MODEL,
) -> tuple[str, float]:
    """Return the age/sex band label and its demographic coefficient.

    Uses the same demographic categorization logic as the CMS model to
    derive the correct age/sex category string (e.g. "F70_74") and then
    looks up its coefficient under the appropriate demographic prefix.

    Args:
        age: Patient age in years.
        sex: "M" or "F".
        dual_elgbl_cd: CMS dual eligibility code.  Default "NA" (non-dual).
        orec: Original reason for entitlement code.  Default "0" (aged).
        new_enrollee: True if patient is a new Medicare enrollee.
        lti: True if patient is long-term institutionalized.
        model: HCC model name.  Defaults to "CMS-HCC Model V28".

    Returns:
        (category, coefficient) tuple where:
          category    – age/sex band string, e.g. "F70_74" (str)
          coefficient – demographic coefficient for this segment (float),
                        or 0.0 if not found.
    """
    demographics = categorize_demographics(
        age=age,
        sex=sex,
        dual_elgbl_cd=dual_elgbl_cd,
        orec=orec,
        new_enrollee=new_enrollee,
        lti=lti,
    )
    category: str = demographics.category or ""
    prefix = get_coefficent_prefix(demographics, model)
    coeff_key = (f"{prefix}{category}".lower(), model)
    coefficient = coefficients_default.get(coeff_key, 0.0)
    return category, coefficient


# ---------------------------------------------------------------------------
# Full RAF calculation
# ---------------------------------------------------------------------------

def calculate_full_raf(
    icd_codes: list[str],
    age: int,
    sex: str,
    dual_status: str = "NA",
    orec: str = "0",
    institutional: bool = False,
    new_enrollee: bool = False,
    snp: bool = False,
    low_income: bool = False,
    model: ModelName = DEFAULT_MODEL,
    norm_factor: float = 1.0,
    maci: float = 0.0,
    frailty_score: float = 0.0,
) -> dict:
    """Calculate a complete RAF score from ICD codes and demographics.

    Thin wrapper around hccinfhir.model_calculate.calculate_raf that
    returns a plain dict instead of a RAFResult Pydantic model.

    Args:
        icd_codes: List of ICD-10-CM diagnosis codes.
        age: Patient age in years.
        sex: "M" or "F".
        dual_status: CMS dual eligibility code (default "NA").
                     Values: "NA", "00"–"10".  See hccinfhir.datamodels.Demographics.
        orec: Original reason for entitlement code (default "0" = aged).
              Values: "0" aged, "1" disability, "2" ESRD, "3" disability+ESRD.
        institutional: True if patient is long-term institutionalized (LTI).
        new_enrollee: True if patient is a new Medicare enrollee.
        snp: True if patient is enrolled in a Special Needs Plan.
        low_income: True if patient has low-income subsidy (RxHCC models).
        model: HCC model name.  Defaults to "CMS-HCC Model V28".
        norm_factor: CMS normalization factor (default 1.0).
        maci: Medicare Advantage coding intensity adjustment (0.0–1.0, default 0.0).
        frailty_score: Frailty adjustment added to payment score (default 0.0).

    Returns:
        dict with keys:
          risk_score             – total RAF score (float)
          risk_score_demographics – demographic component only (float)
          risk_score_hcc         – HCC component only (float)
          risk_score_chronic_only – chronic HCC component only (float)
          risk_score_payment     – payment-adjusted score (float)
          hcc_list               – active HCC codes after hierarchies (list[str])
          hcc_details            – list of dicts per active HCC:
                                     hcc_code, label, is_chronic, coefficient
          coefficients           – all applied coefficient name→value pairs (dict)
          interactions           – disease interaction variables applied (dict)
          demographic_category   – age/sex band string, e.g. "F70_74" (str)
          diagnosis_codes        – deduplicated input codes used (list[str])
          model                  – model name used (str)
    """
    result = calculate_raf(
        diagnosis_codes=icd_codes,
        model_name=model,
        age=age,
        sex=sex,
        dual_elgbl_cd=dual_status,
        orec=orec,
        lti=institutional,
        new_enrollee=new_enrollee,
        snp=snp,
        low_income=low_income,
        norm_factor=norm_factor,
        maci=maci,
        frailty_score=frailty_score,
    )

    hcc_details = [
        {
            "hcc_code": d.hcc,
            "label": d.label,
            "is_chronic": d.is_chronic,
            "coefficient": d.coefficient,
        }
        for d in result.hcc_details
    ]

    return {
        "risk_score": result.risk_score,
        "risk_score_demographics": result.risk_score_demographics,
        "risk_score_hcc": result.risk_score_hcc,
        "risk_score_chronic_only": result.risk_score_chronic_only,
        "risk_score_payment": result.risk_score_payment,
        "hcc_list": result.hcc_list,
        "hcc_details": hcc_details,
        "coefficients": result.coefficients,
        "interactions": result.interactions,
        "demographic_category": result.demographics.category,
        "diagnosis_codes": result.diagnosis_codes,
        "model": result.model_name,
    }
