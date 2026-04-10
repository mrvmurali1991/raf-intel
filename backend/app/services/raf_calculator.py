# DISCLAIMER: This module calculates CMS-HCC risk adjustment scores using the
# hccinfhir library, which is a third-party open-source implementation of the
# CMS-HCC model. It is NOT validated or endorsed by CMS. Results should be
# verified against the official CMS SAS software before use in payment
# determinations. This tool is designed for clinical analytics, gap identification,
# and prospective risk assessment — not for payment submission.

"""
CMS-HCC V28 RAF Score Calculation Engine.

Based on CMS-HCC V28 model via hccinfhir library (third-party open-source
implementation). Not CMS-validated. For informational purposes — verify against
official CMS SAS software for payment accuracy.
Handles OpenEMR integration, result persistence, and batch processing.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime
from typing import Any

from hccinfhir import HCCInFHIR, Demographics

from app.db import raf_cursor, openemr_cursor

logger = logging.getLogger(__name__)

# Module-level singleton processor
_processor = HCCInFHIR(model_name="CMS-HCC Model V28")

# CMS normalization factors by payment year.
# Passed directly to hccinfhir's calculate_from_diagnosis(norm_factor=...) so
# risk_score_payment is computed inside the library consistently.
_NORM_FACTORS: dict[int, float] = {
    2024: 1.015,
    2025: 1.045,
    2026: 1.050,  # estimated
}

# Minimum Allowable Coding Intensity (MACI) adjustment by year.
# Passed directly to hccinfhir's calculate_from_diagnosis(maci=...) so
# risk_score_payment is computed inside the library consistently.
_MACI_FACTORS: dict[int, float] = {
    2024: 0.059,  # 5.9%
    2025: 0.059,
    2026: 0.059,  # estimated
}

# Map CMS model segment strings to hccinfhir prefix_override values.
# hccinfhir uses these prefixes to select the correct coefficient table.
_SEGMENT_TO_PREFIX: dict[str, str] = {
    "CNA": "CNA_",
    "CND": "CND_",
    "CFA": "CFA_",
    "CFD": "CFD_",
    "CPA": "CPA_",
    "CPD": "CPD_",
    "INS": "INS_",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _calculate_age(dob: str | date | datetime, as_of_year: int | None = None) -> int:
    """Calculate age as of Feb 1 of measurement year (CMS convention)."""
    if isinstance(dob, str):
        dob = datetime.strptime(dob[:10], "%Y-%m-%d").date()
    elif isinstance(dob, datetime):
        dob = dob.date()
    ref = date(as_of_year or date.today().year, 2, 1)
    age = ref.year - dob.year - ((ref.month, ref.day) < (dob.month, dob.day))
    return max(0, age)


def determine_model_segment(
    age: int,
    is_dual: bool = False,
    dual_type: str = "non_dual",
    is_institutional: bool = False,
    orec: str = "0",
) -> str:
    """
    Determine the correct CMS-HCC model segment for a beneficiary.

    CMS-HCC V28 model segments:
      CNA - Community, Non-dual, Aged (age >= 65, not on Medicaid)
      CND - Community, Non-dual, Disabled (age < 65 with disability, OREC = 1)
      CFA - Community, Full-dual, Aged (age >= 65, full Medicaid)
      CFD - Community, Full-dual, Disabled (age < 65, full Medicaid)
      CPA - Community, Partial-dual, Aged (age >= 65, partial Medicaid buy-in)
      CPD - Community, Partial-dual, Disabled (age < 65, partial Medicaid buy-in)
      INS - Institutional (SNF / long-term nursing facility resident)

    Args:
        age:            Beneficiary age as of Feb 1 of measurement year.
        is_dual:        True if beneficiary has any Medicaid coverage.
        dual_type:      "full", "partial", or "non_dual".
        is_institutional: True if resident of SNF / nursing facility.
        orec:           Original Reason for Entitlement Code (unused here but
                        reserved for future ESRD / disability sub-segments).

    Returns:
        Two- or three-letter model segment string.
    """
    # Institutional takes highest precedence regardless of age or dual status.
    if is_institutional:
        return "INS"

    aged = age >= 65

    # Normalise dual_type to lowercase for comparison.
    dt = (dual_type or "non_dual").lower()

    if dt in ("full", "full_dual"):
        return "CFA" if aged else "CFD"
    if dt in ("partial", "partial_dual"):
        return "CPA" if aged else "CPD"

    # Non-dual (no Medicaid, or is_dual is explicitly False).
    if aged:
        return "CNA"
    return "CND"


def _sex_code(sex_str: str) -> str:
    """Normalize sex to M/F."""
    s = (sex_str or "").strip().upper()
    if s.startswith("F"):
        return "F"
    return "M"


def _get_patient(patient_id: int) -> dict[str, Any] | None:
    """Get patient from OpenEMR."""
    with openemr_cursor() as cur:
        cur.execute("SELECT * FROM patient_data WHERE pid = %s", (patient_id,))
        row = cur.fetchone()
    return row


def _get_icd_codes(patient_id: int) -> list[str]:
    """Get unique ICD-10 codes from OpenEMR billing."""
    with openemr_cursor() as cur:
        cur.execute(
            "SELECT DISTINCT code FROM billing WHERE pid = %s AND code_type = 'ICD10' AND activity = 1",
            (patient_id,),
        )
        rows = cur.fetchall()
    return [r["code"] for r in rows if r.get("code")]


# ---------------------------------------------------------------------------
# Core calculation
# ---------------------------------------------------------------------------

def _get_enrollment_from_raf_db(patient_id: int, measurement_year: int) -> dict[str, Any] | None:
    """
    Look up stored OREC / dual-eligibility from raf_patient_demographics.

    Returns a dict with dual_status, orec, institutional keys, or None if no
    row exists or the table is missing the new columns.
    """
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT dual_type, orec, institutional
                FROM raf_patient_demographics
                WHERE patient_id = %s AND measurement_year = %s
                LIMIT 1
                """,
                (patient_id, measurement_year),
            )
            row = cur.fetchone()
        if row:
            return {
                "dual_status": row.get("dual_type") or "non_dual",
                "orec": str(row.get("orec") or "0"),
                "institutional": bool(row.get("institutional", False)),
                "source": "raf_db",
            }
    except Exception as exc:
        logger.debug("_get_enrollment_from_raf_db pid=%s: %s", patient_id, exc)
    return None


def _upsert_patient_demographics(
    patient_id: int,
    measurement_year: int,
    age: int,
    sex: str,
    model_segment: str,
    dual_type: str,
    orec: str,
    institutional: bool,
    enrollment_source: str,
) -> None:
    """Persist (or refresh) enrollment and demographic info in raf_patient_demographics."""
    age_band = _get_age_band_from_age(age)

    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                INSERT INTO raf_patient_demographics
                    (patient_id, measurement_year, age_band, sex,
                     dual_status, dual_type, disabled, orec,
                     institutional, enrollment_source, model_segment)
                VALUES
                    (%s, %s, %s, %s,
                     %s, %s, %s, %s,
                     %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    age_band          = VALUES(age_band),
                    sex               = VALUES(sex),
                    dual_status       = VALUES(dual_status),
                    dual_type         = VALUES(dual_type),
                    disabled          = VALUES(disabled),
                    orec              = VALUES(orec),
                    institutional     = VALUES(institutional),
                    enrollment_source = VALUES(enrollment_source),
                    model_segment     = VALUES(model_segment),
                    updated_at        = NOW()
                """,
                (
                    patient_id,
                    measurement_year,
                    age_band,
                    sex,
                    1 if dual_type != "non_dual" else 0,
                    dual_type,
                    1 if orec == "1" else 0,
                    orec,
                    1 if institutional else 0,
                    enrollment_source,
                    model_segment,
                ),
            )
    except Exception as exc:
        logger.warning(
            "_upsert_patient_demographics pid=%s year=%s: %s",
            patient_id, measurement_year, exc,
        )


def _get_age_band_from_age(age: int) -> str:
    """Return CMS age-band label for a given integer age."""
    if age < 35: return "0-34"
    if age < 45: return "35-44"
    if age < 55: return "45-54"
    if age < 60: return "55-59"
    if age < 65: return "60-64"
    if age < 70: return "65-69"
    if age < 75: return "70-74"
    if age < 80: return "75-79"
    if age < 85: return "80-84"
    if age < 90: return "85-89"
    if age < 95: return "90-94"
    return "95+"


def calculate_raf_score(
    patient_id: int,
    measurement_year: int = 2026,
    dual_status: str | None = None,
    institutional: bool = False,
    *,
    encounter_year: int | None = None,
    enrollment_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Calculate RAF score for a patient using hccinfhir (third-party open-source
    CMS-HCC V28 implementation). Results are estimates — not CMS-validated.
    Verify against official CMS SAS software for payment determinations.

    Steps:
        1. Load patient demographics from OpenEMR
        2. Load ICD-10 codes from OpenEMR billing
        3. Resolve OREC + dual eligibility (override > OpenEMR > RAF DB > CNA default)
        4. Determine the correct CMS-HCC model segment
        5. Run hccinfhir processor (handles ICD→HCC mapping, hierarchy, interactions)
        6. Persist enrollment info to raf_patient_demographics
        7. Store HCCs in raf_patient_hcc
        8. Store result in raf_scores
        9. Return full breakdown

    Args:
        patient_id:          OpenEMR patient PID. Use 0 for paste / anonymous mode.
        measurement_year:    CMS payment year (default 2026).
        dual_status:         Legacy — Medicaid dual status. Prefer enrollment_override.
                             "non_dual", "partial_dual", or "full_dual".
        institutional:       Legacy — True if SNF / nursing-facility resident.
        encounter_year:      Keyword-only. Year used for age calculation only (CMS
                             rule: age as of Feb 1 of encounter year). Defaults to
                             measurement_year.
        enrollment_override: Optional dict from API caller to skip auto-detection.
                             Keys: dual_status, orec, institutional.
    """
    # -----------------------------------------------------------------------
    # Paste / anonymous mode (patient_id == 0)
    # -----------------------------------------------------------------------
    if patient_id == 0:
        logger.info(
            "RAF calc pid=0 (paste mode) — defaulting to CNA (non_dual, aged, OREC=0)"
        )
        # The analysis router handles its own ICD/demographics parsing for paste mode.
        # Return a minimal sentinel so callers know the segment that will be used.
        return {
            "patient_id": 0,
            "measurement_year": measurement_year,
            "model_segment": "CNA",
            "enrollment_info": {
                "dual_status": "non_dual",
                "orec": "0",
                "institutional": False,
                "source": "paste_mode_default",
            },
            "note": (
                "Paste mode: enrollment defaults to CNA (non_dual, aged). "
                "Pass enrollment_override via the API to change."
            ),
        }

    # 1. Get patient
    patient = _get_patient(patient_id)
    if not patient:
        raise ValueError(f"Patient {patient_id} not found in OpenEMR")

    dob = patient.get("DOB") or patient.get("dob") or "1950-01-01"
    sex = _sex_code(patient.get("sex", "M"))
    # Age is always calculated as of Feb 1 of the encounter year (CMS rule).
    age_year = encounter_year if encounter_year is not None else measurement_year
    age = _calculate_age(dob, age_year)

    # 2. Get ICD-10 codes
    icd_codes = _get_icd_codes(patient_id)

    # 3. Resolve enrollment info
    # Priority: enrollment_override > legacy dual_status param > OpenEMR derived
    #           > RAF DB stored > CNA/CND default
    if enrollment_override:
        _dual_type = enrollment_override.get("dual_status") or "non_dual"
        _orec = str(enrollment_override.get("orec", "0"))
        _institutional = bool(enrollment_override.get("institutional", False))
        enrollment_source = "api_override"
        logger.info(
            "RAF calc pid=%s — API enrollment override: dual=%s orec=%s inst=%s",
            patient_id, _dual_type, _orec, _institutional,
        )
    elif dual_status is not None:
        # Legacy caller passed dual_status directly; derive OREC from age.
        _dual_type = dual_status
        _orec = "1" if age < 65 else "0"
        _institutional = institutional
        enrollment_source = "api_override"
    else:
        # Auto-detect from OpenEMR insurance_data + age heuristic
        openemr_info: dict[str, Any] | None = None
        try:
            from app.services.openemr_connector import get_patient_enrollment_info
            openemr_info = get_patient_enrollment_info(patient_id)
        except Exception as exc:
            logger.warning(
                "RAF calc pid=%s — get_patient_enrollment_info failed (%s), "
                "will check RAF DB",
                patient_id, exc,
            )

        if openemr_info and openemr_info.get("source") not in (None, "default"):
            _dual_type = openemr_info["dual_status"]
            _orec = openemr_info["orec"]
            _institutional = openemr_info["institutional"]
            enrollment_source = "openemr_derived"
        else:
            # Try RAF DB for a previously stored value
            raf_db_info = _get_enrollment_from_raf_db(patient_id, measurement_year)
            if raf_db_info:
                _dual_type = raf_db_info["dual_status"]
                _orec = raf_db_info["orec"]
                _institutional = raf_db_info["institutional"]
                enrollment_source = "raf_db"
                logger.debug(
                    "RAF calc pid=%s — enrollment loaded from raf_patient_demographics",
                    patient_id,
                )
            else:
                # Final fallback: CNA for aged (>=65), CND for under-65
                _dual_type = "non_dual"
                _orec = "1" if age < 65 else "0"
                _institutional = institutional
                enrollment_source = "default_cna"
                logger.warning(
                    "RAF calc pid=%s — no enrollment data in OpenEMR or RAF DB; "
                    "defaulting to %s (dual=%s orec=%s)",
                    patient_id,
                    "CND" if age < 65 else "CNA",
                    _dual_type,
                    _orec,
                )

    # 4. Determine model segment
    model_segment = determine_model_segment(
        age=age,
        is_dual=_dual_type != "non_dual",
        dual_type=_dual_type,
        is_institutional=_institutional,
        orec=_orec,
    )
    logger.info(
        "RAF calc pid=%s year=%s age=%s sex=%s segment=%s orec=%s dual=%s codes=%s",
        patient_id, measurement_year, age, sex, model_segment, _orec, _dual_type, icd_codes,
    )

    # 4. Run hccinfhir — pass segment prefix, MACI, and normalization factor so
    #    the library selects the correct coefficient table and computes
    #    risk_score_payment correctly without any manual post-processing.
    norm_factor = _NORM_FACTORS.get(measurement_year, 1.0)
    maci = _MACI_FACTORS.get(measurement_year, 0.0)
    prefix = _SEGMENT_TO_PREFIX.get(model_segment, "CNA_")

    result = _processor.calculate_from_diagnosis(
        icd_codes,
        age=age,
        sex=sex,
        prefix_override=prefix,
        maci=maci,
        norm_factor=norm_factor,
    )

    hcc_list = result.hcc_list or []
    all_coefficients = result.coefficients or {}

    # --- Score decomposition via hccinfhir's built-in fields ---
    # risk_score_demographics: the exact demographic (age/sex/disability) subtotal
    # disease_score: sum of individual HCC coefficients from hcc_details
    # interaction_score: what remains after removing both of the above
    demographic_score: float = result.risk_score_demographics
    disease_score: float = sum(h.coefficient for h in result.hcc_details)
    interaction_score: float = result.risk_score - demographic_score - disease_score

    # Rich per-HCC contributions using HCCDetail objects (includes label + is_chronic)
    hcc_contributions = [
        {
            "hcc_code": str(h.hcc),
            "coefficient": h.coefficient,
            "label": h.label,
            "is_chronic": h.is_chronic,
        }
        for h in result.hcc_details
    ]

    # risk_score_payment is the library-computed payment-adjusted score
    # (applies maci and norm_factor that were passed above).
    raw_raf = result.risk_score
    payment_raf = result.risk_score_payment

    # Keep raf_score as the raw score for backward compatibility.
    raf_score = raw_raf
    subtotal = demographic_score + disease_score + interaction_score

    logger.info(
        "RAF score pid=%s → %.4f (demo=%.4f disease=%.4f int=%.4f) HCCs=%s",
        patient_id, raf_score, demographic_score, disease_score, interaction_score, hcc_list,
    )

    # 5. Store HCCs in raf_patient_hcc
    _store_patient_hccs(patient_id, measurement_year, hcc_list, icd_codes, result)

    # 6. Persist enrollment info to raf_patient_demographics (best-effort)
    _upsert_patient_demographics(
        patient_id=patient_id,
        measurement_year=measurement_year,
        age=age,
        sex=sex,
        model_segment=model_segment,
        dual_type=_dual_type,
        orec=_orec,
        institutional=_institutional,
        enrollment_source=enrollment_source,
    )

    # 7. Build result dict
    result_dict = {
        "patient_id": patient_id,
        "measurement_year": measurement_year,
        "model_segment": model_segment,
        "age": age,
        "sex": sex,
        "icd_codes": icd_codes,
        "demographic_score": round(demographic_score, 4),
        "raw_hcc_list": [str(h) for h in hcc_list],
        "final_hcc_list": [str(h) for h in hcc_list],
        "disease_score": round(disease_score, 4),
        "interaction_score": round(interaction_score, 4),
        "subtotal": round(subtotal, 4),
        "raf_score": round(raf_score, 4),           # Raw risk score (backward compatible)
        "payment_raf": round(payment_raf, 4),        # Payment-adjusted score (MACI + normalization)
        "normalization_factor": norm_factor,
        "maci_factor": maci,
        "hcc_contributions": hcc_contributions,
        "all_coefficients": {k: round(v, 4) for k, v in all_coefficients.items()},
        "interactions_fired": {k: v for k, v in (result.interactions or {}).items() if v},
        # Enrollment metadata surfaced for transparency / debugging
        "enrollment_info": {
            "dual_status": _dual_type,
            "orec": _orec,
            "institutional": _institutional,
            "source": enrollment_source,
        },
        "_disclaimer": "RAF scores are estimates based on CMS-HCC V28 model. Not for payment submission.",
    }

    # 8. Persist to raf_scores
    _upsert_raf_score(result_dict)

    return result_dict


def _store_patient_hccs(
    patient_id: int, year: int, hcc_list: list, icd_codes: list[str], result: Any
) -> None:
    """Store active HCCs in raf_patient_hcc table.

    Uses hccinfhir's hcc_details for the per-HCC coefficient and cc_to_dx for
    the exact ICD codes that triggered each HCC.  cc_to_dx values are sets of
    strings (e.g. {'I509', 'E119'}); convert to sorted lists before JSON-encoding.
    """
    try:
        # Build a lookup from HCC string key -> HCCDetail for coefficient access
        hcc_detail_map = {str(h.hcc): h for h in (result.hcc_details or [])}

        # cc_to_dx maps HCC string -> set[str] of triggering ICD codes (no dots)
        cc_to_dx: dict = result.cc_to_dx or {}

        with raf_cursor() as cur:
            # Clear old HCCs for this patient/year
            cur.execute(
                "DELETE FROM raf_patient_hcc WHERE patient_id = %s AND measurement_year = %s",
                (patient_id, year),
            )
            for hcc in hcc_list:
                hcc_str = str(hcc)
                hcc_int = int(hcc_str) if hcc_str.isdigit() else 0

                # ICD codes that triggered this HCC — cc_to_dx values are sets
                raw_icd = cc_to_dx.get(hcc_str, set())
                related_icd: list[str] = sorted(raw_icd) if isinstance(raw_icd, set) else list(raw_icd)

                # Per-HCC coefficient from hcc_details
                coefficient = hcc_detail_map[hcc_str].coefficient if hcc_str in hcc_detail_map else 0.0

                cur.execute(
                    """
                    INSERT INTO raf_patient_hcc
                        (patient_id, measurement_year, hcc_code, icd10_codes,
                         source_encounter_ids, raf_coefficient, meat_status)
                    VALUES (%s, %s, %s, %s, '[]', %s, 'missing')
                    ON DUPLICATE KEY UPDATE
                        icd10_codes     = VALUES(icd10_codes),
                        raf_coefficient = VALUES(raf_coefficient)
                    """,
                    (patient_id, year, hcc_int, json.dumps(related_icd), coefficient),
                )
    except Exception as exc:
        logger.warning("Failed to store HCCs for pid=%s: %s", patient_id, exc)


def _upsert_raf_score(result: dict[str, Any]) -> None:
    """Persist RAF score to raf_scores table."""
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                INSERT INTO raf_scores (
                    patient_id, measurement_year, score_type, model_segment,
                    demographic_score, disease_score, interaction_score,
                    total_raw, normalization_factor, final_raf,
                    hcc_count, calculated_at
                ) VALUES (
                    %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, NOW()
                )
                ON DUPLICATE KEY UPDATE
                    demographic_score   = VALUES(demographic_score),
                    disease_score       = VALUES(disease_score),
                    interaction_score   = VALUES(interaction_score),
                    total_raw           = VALUES(total_raw),
                    normalization_factor = VALUES(normalization_factor),
                    final_raf           = VALUES(final_raf),
                    hcc_count           = VALUES(hcc_count),
                    calculated_at       = NOW()
                """,
                (
                    result["patient_id"],
                    result["measurement_year"],
                    result["model_segment"],
                    result["model_segment"],
                    result["demographic_score"],
                    result["disease_score"],
                    result["interaction_score"],
                    result["subtotal"],
                    # Store the effective combined adjustment applied:
                    # (1 - maci) / norm_factor, so the stored factor reflects
                    # exactly what was multiplied against total_raw to reach final_raf.
                    round((1 - result["maci_factor"]) / result["normalization_factor"], 6),
                    result["payment_raf"],   # payment-adjusted score is the persisted final_raf
                    len(result["final_hcc_list"]),
                ),
            )
    except Exception as exc:
        logger.error("Failed to persist raf_scores for pid=%s: %s", result["patient_id"], exc)


# ---------------------------------------------------------------------------
# Batch + breakdown
# ---------------------------------------------------------------------------

def calculate_raf_for_all_patients(year: int = 2026) -> list[dict[str, Any]]:
    """Calculate RAF for all patients in OpenEMR."""
    with openemr_cursor() as cur:
        cur.execute("SELECT pid FROM patient_data ORDER BY pid")
        patients = cur.fetchall()

    results = []
    for p in patients:
        pid = int(p["pid"])
        try:
            r = calculate_raf_score(pid, year)
            results.append(r)
        except Exception as exc:
            logger.error("RAF calc failed for pid=%s: %s", pid, exc)
            results.append({"patient_id": pid, "error": str(exc)})
    return results


def get_raf_breakdown(patient_id: int, year: int = 2026) -> dict[str, Any]:
    """Get stored RAF score breakdown, or calculate if not exists."""
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT * FROM raf_scores
                WHERE patient_id = %s AND measurement_year = %s
                ORDER BY calculated_at DESC LIMIT 1
                """,
                (patient_id, year),
            )
            row = cur.fetchone()

        if row:
            # Also get HCC details
            with raf_cursor() as cur:
                cur.execute(
                    "SELECT hcc_code, icd10_codes, meat_status FROM raf_patient_hcc WHERE patient_id = %s AND measurement_year = %s",
                    (patient_id, year),
                )
                hccs = cur.fetchall()

            patient = _get_patient(patient_id)
            return {
                "patient_id": patient_id,
                "patient_name": f"{patient.get('fname', '')} {patient.get('lname', '')}" if patient else "",
                "measurement_year": year,
                "raf_score": float(row.get("final_raf", 0)),
                "demographic_score": float(row.get("demographic_score", 0)),
                "disease_score": float(row.get("disease_score", 0)),
                "interaction_score": float(row.get("interaction_score", 0)),
                "hcc_count": row.get("hcc_count", 0),
                "model_segment": row.get("model_segment", "CNA"),
                "calculated_at": str(row.get("calculated_at", "")),
                "hcc_details": [
                    {
                        "hcc_code": str(h["hcc_code"]),
                        "icd10_codes": json.loads(h["icd10_codes"]) if isinstance(h["icd10_codes"], str) else h["icd10_codes"],
                        "meat_status": h.get("meat_status", "missing"),
                    }
                    for h in hccs
                ],
            }
        else:
            # Calculate fresh
            return calculate_raf_score(patient_id, year)
    except Exception as exc:
        logger.error("get_raf_breakdown failed for pid=%s: %s", patient_id, exc)
        return calculate_raf_score(patient_id, year)


# ---------------------------------------------------------------------------
# Convenience aliases used by routers
# ---------------------------------------------------------------------------

def get_age_band(dob: str, year: int = 2026) -> str:
    """Return age band string."""
    age = _calculate_age(dob, year)
    if age < 35: return "0-34"
    if age < 45: return "35-44"
    if age < 55: return "45-54"
    if age < 60: return "55-59"
    if age < 65: return "60-64"
    if age < 70: return "65-69"
    if age < 75: return "70-74"
    if age < 80: return "75-79"
    if age < 85: return "80-84"
    if age < 90: return "85-89"
    if age < 95: return "90-94"
    return "95+"
