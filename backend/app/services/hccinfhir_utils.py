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

import logging
import re

from hccinfhir import HCCInFHIR
from hccinfhir.datamodels import ModelName
from hccinfhir.defaults import (
    coefficients_default,
    dx_to_cc_default,
    is_chronic_default,
    labels_default,
)
from hccinfhir.model_calculate import calculate_raf
from hccinfhir.model_coefficients import get_coefficent_prefix
from hccinfhir.model_demographics import categorize_demographics

logger = logging.getLogger(__name__)

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


# ---------------------------------------------------------------------------
# FHIR EOB-based RAF calculation
# ---------------------------------------------------------------------------

# Module-level cache so callers that process many patients do not rebuild the
# HCCInFHIR processor (which loads several CSV files) on every call.
_hccinfhir_processors: dict[ModelName, HCCInFHIR] = {}


def _get_processor(model: ModelName) -> HCCInFHIR:
    """Return a cached HCCInFHIR processor for the given model."""
    if model not in _hccinfhir_processors:
        _hccinfhir_processors[model] = HCCInFHIR(model_name=model)
    return _hccinfhir_processors[model]


def _extract_icd10_from_eobs(eob_resources: list[dict]) -> list[str]:
    """Extract unique ICD-10 diagnosis codes from a list of raw EOB dicts.

    Follows the FHIR R4 ExplanationOfBenefit structure:
      eob.diagnosis[*].diagnosisCodeableConcept.coding[0].code

    Args:
        eob_resources: List of raw FHIR EOB resource dicts.

    Returns:
        Deduplicated list of uppercase ICD-10-CM codes.
    """
    codes: set[str] = set()
    for eob in eob_resources:
        for dx in eob.get("diagnosis", []):
            coding_list = dx.get("diagnosisCodeableConcept", {}).get("coding", [])
            for coding in coding_list:
                code = coding.get("code")
                if code:
                    codes.add(code.strip().upper())
    return sorted(codes)


def calculate_raf_from_fhir_eob(
    eob_resources: list[dict],
    age: int,
    sex: str,
    model: ModelName = DEFAULT_MODEL,
    prefix_override: str | None = "CNA_",
    maci: float = 0.059,
    norm_factor: float = 1.050,
) -> dict:
    """Calculate RAF score directly from FHIR ExplanationOfBenefit resources.

    Uses hccinfhir's built-in FHIR parser (HCCInFHIR.run) instead of manual
    ICD-10 extraction.  This is the preferred method when EOB resources are
    available from CMS Blue Button 2.0 or BCDA APIs.

    HCCInFHIR.run applies CMS claim-filtering rules (eligible CPT/HCPCS codes)
    before scoring, which is more accurate than extracting diagnosis codes
    directly from EOBs without filtering.  If the primary path fails for any
    reason (e.g. an unexpected EOB schema variant), the function falls back to
    manual ICD-10 extraction followed by calculate_full_raf().

    Args:
        eob_resources: List of raw FHIR R4 ExplanationOfBenefit resource dicts.
                       Accepts both single-resource dicts and a Bundle entry list.
        age: Patient age in years.
        sex: "M" or "F".
        model: HCC model name.  Defaults to "CMS-HCC Model V28".
        prefix_override: CMS demographic segment prefix, e.g. "CNA_"
                         (Community Non-Dual Aged — the default).  Pass None
                         to let hccinfhir auto-detect the prefix from the
                         demographics object.
        maci: Medicare Advantage coding intensity adjustment (default 0.059,
              the 2026 CMS value).
        norm_factor: CMS normalization factor (default 1.050, the 2026 CMS value).

    Returns:
        dict with the same keys as calculate_full_raf() plus:
          risk_score              – total RAF score (float)
          risk_score_demographics – demographic component only (float)
          risk_score_hcc          – HCC component only (float)
          risk_score_chronic_only – chronic HCC component only (float)
          risk_score_payment      – payment-adjusted score (float)
          hcc_list                – active HCC codes after hierarchies (list[str])
          hcc_details             – list of dicts per active HCC:
                                      hcc_code, label, is_chronic, coefficient
          coefficients            – all applied coefficient name→value pairs (dict)
          interactions            – disease interaction variables applied (dict)
          demographic_category    – age/sex band string, e.g. "F70_74" (str)
          diagnosis_codes         – diagnosis codes used in scoring (list[str])
          model                   – model name used (str)
          source                  – "fhir_eob_parser" or "fallback_icd10" (str)
    """
    demographics_dict: dict = {"age": age, "sex": sex}

    # --- Primary path: HCCInFHIR.run() with built-in FHIR filtering ---
    try:
        processor = _get_processor(model)

        # prefix_override must be one of the PrefixOverride literals or None.
        # Pass it through directly; hccinfhir will validate.
        result = processor.run(
            eob_list=eob_resources,
            demographics=demographics_dict,
            prefix_override=prefix_override,
            maci=maci,
            norm_factor=norm_factor,
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
            "source": "fhir_eob_parser",
        }

    except Exception:
        # --- Fallback path: manual ICD-10 extraction from EOB dicts ---
        icd_codes = _extract_icd10_from_eobs(eob_resources)
        fallback = calculate_full_raf(
            icd_codes=icd_codes,
            age=age,
            sex=sex,
            model=model,
            norm_factor=norm_factor,
            maci=maci,
        )
        fallback["source"] = "fallback_icd10"
        return fallback


# ---------------------------------------------------------------------------
# Coefficient sync — hccinfhir library → MySQL
# ---------------------------------------------------------------------------

# Matches the HCC portion of a coefficient key, e.g. "cna_hcc37" → segment="cna", hcc_code="37"
_HCC_KEY_RE = re.compile(r"^(.+)_hcc(\d+)$")

# Matches demographic age/sex portion, e.g. "cna_f70_74" → segment="cna", sex="f", age_band="70_74"
# Also handles new-enrollee patterns like "cna_nef65" → sex="f", age_band="65"
# and "cna_m95_gt" → sex="m", age_band="95_gt"
_DEMO_KEY_RE = re.compile(r"^(.+?)_(ne)?([mf])(\d[\w]*)$")


def sync_coefficients_to_db(model: ModelName = DEFAULT_MODEL) -> dict:
    """Sync hccinfhir coefficients to MySQL tables.

    Idempotent — safe to call on startup.  Reads ``coefficients_default`` from
    the hccinfhir library (the in-process source of truth) and upserts the HCC
    and demographic rows into ``hcc_raf_coefficients`` and
    ``hcc_demographic_coefficients`` respectively.  Tables are created with
    ``CREATE TABLE IF NOT EXISTS`` so no prior migration is required.

    Interaction-term keys (e.g. ``cna_diabetes_chf``) are intentionally skipped
    because their naming is model-specific and harder to parse generically.

    Args:
        model: HCC model name.  Defaults to ``DEFAULT_MODEL`` ("CMS-HCC Model V28").

    Returns:
        dict with keys:
          hcc_synced         – number of HCC coefficient rows upserted (int)
          demographic_synced – number of demographic coefficient rows upserted (int)
          model              – model name used (str)
    """
    from app.db import raf_cursor  # deferred to avoid circular imports at module load

    _ensure_coefficient_tables()

    # Derive a short model_year tag from the model string, e.g. "V28" from
    # "CMS-HCC Model V28".  Falls back to the full string if unparseable.
    year_match = re.search(r"V\d+", model, re.IGNORECASE)
    model_year: str = year_match.group(0).upper() if year_match else model

    hcc_rows: list[tuple] = []
    demo_rows: list[tuple] = []

    for (key, key_model), coefficient in coefficients_default.items():
        if key_model != model:
            continue

        hcc_match = _HCC_KEY_RE.match(key)
        if hcc_match:
            segment_prefix = hcc_match.group(1).upper()  # e.g. "CNA"
            hcc_code = hcc_match.group(2)                 # e.g. "37"
            hcc_rows.append((hcc_code, segment_prefix, float(coefficient), model_year))
            continue

        demo_match = _DEMO_KEY_RE.match(key)
        if demo_match:
            segment_prefix = demo_match.group(1).upper()  # e.g. "CNA"
            new_enrollee_flag = demo_match.group(2)        # "ne" or None
            sex = demo_match.group(3).upper()              # "M" or "F"
            age_part = demo_match.group(4)                 # e.g. "70_74", "95_gt", "65"
            # Reconstruct the age band label in a consistent format
            if new_enrollee_flag:
                age_band = f"NE_{age_part}"
            else:
                age_band = age_part
            demo_rows.append((segment_prefix, age_band, sex, float(coefficient), model_year))
            continue

        # Anything that matched neither pattern is an interaction term — skip.

    # Upsert in batches using INSERT ... ON DUPLICATE KEY UPDATE
    HCC_UPSERT = """
        INSERT INTO hcc_raf_coefficients
            (hcc_code, model_segment, coefficient, model_year)
        VALUES (%s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            coefficient = VALUES(coefficient)
    """

    DEMO_UPSERT = """
        INSERT INTO hcc_demographic_coefficients
            (model_segment, age_band, sex, coefficient, model_year)
        VALUES (%s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            coefficient = VALUES(coefficient)
    """

    with raf_cursor() as cursor:
        if hcc_rows:
            cursor.executemany(HCC_UPSERT, hcc_rows)
        if demo_rows:
            cursor.executemany(DEMO_UPSERT, demo_rows)

    logger.info(
        "sync_coefficients_to_db: upserted %d HCC and %d demographic rows for model=%s",
        len(hcc_rows),
        len(demo_rows),
        model,
    )
    return {
        "hcc_synced": len(hcc_rows),
        "demographic_synced": len(demo_rows),
        "model": model,
    }


def _ensure_coefficient_tables() -> None:
    """Create coefficient tables if they do not already exist.

    Uses ``CREATE TABLE IF NOT EXISTS`` so this is safe to call repeatedly.
    The unique keys drive the ``ON DUPLICATE KEY UPDATE`` upsert logic in
    ``sync_coefficients_to_db``.
    """
    from app.db import raf_cursor  # deferred import

    CREATE_HCC = """
        CREATE TABLE IF NOT EXISTS hcc_raf_coefficients (
            id            INT UNSIGNED NOT NULL AUTO_INCREMENT,
            hcc_code      VARCHAR(20)  NOT NULL COMMENT 'CC number without HCC prefix, e.g. 37',
            model_segment VARCHAR(30)  NOT NULL COMMENT 'Segment prefix, e.g. CNA, CFA, INS',
            coefficient   DOUBLE       NOT NULL,
            model_year    VARCHAR(10)  NOT NULL COMMENT 'e.g. V28',
            created_at    TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at    TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP
                                       ON UPDATE CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            UNIQUE KEY uq_hcc_segment_year (hcc_code, model_segment, model_year)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """

    CREATE_DEMO = """
        CREATE TABLE IF NOT EXISTS hcc_demographic_coefficients (
            id            INT UNSIGNED NOT NULL AUTO_INCREMENT,
            model_segment VARCHAR(30)  NOT NULL COMMENT 'Segment prefix, e.g. CNA, CFA, INS',
            age_band      VARCHAR(20)  NOT NULL COMMENT 'Age range string, e.g. 70_74, NE_65',
            sex           CHAR(1)      NOT NULL COMMENT 'M or F',
            coefficient   DOUBLE       NOT NULL,
            model_year    VARCHAR(10)  NOT NULL COMMENT 'e.g. V28',
            created_at    TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at    TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP
                                       ON UPDATE CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            UNIQUE KEY uq_demo_segment_age_sex_year (model_segment, age_band, sex, model_year)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """

    with raf_cursor() as cursor:
        cursor.execute(CREATE_HCC)
        cursor.execute(CREATE_DEMO)
