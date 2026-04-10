"""
RAF router — hccinfhir-based CMS-HCC V28 endpoints.

POST /api/raf/calculate/{pid}         - Calculate RAF for a single patient
POST /api/raf/calculate-all           - Batch calculate for all patients
GET  /api/raf/scores/{pid}            - Stored RAF score for a patient
GET  /api/raf/scores/{pid}/breakdown  - Detailed HCC breakdown with MEAT status
GET  /api/raf/population-summary      - Population-level stats
GET  /api/raf/scores/{pid}/history    - All years calculated for a patient
"""
from __future__ import annotations

import logging
import statistics
from collections import Counter
from datetime import date
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.services.raf_calculator import (
    calculate_raf_score,
    calculate_raf_for_all_patients,
    get_raf_breakdown,
)
from app.services.openemr_connector import get_patient, get_all_patients, get_patient_count
from app.db import raf_cursor

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/raf", tags=["raf"])

# ---------------------------------------------------------------------------
# Known HCC labels (CMS-HCC V28 subset — most commonly seen)
# ---------------------------------------------------------------------------

from hccinfhir.defaults import labels_default as _labels_default

_V28_MODEL = "CMS-HCC Model V28"


def _hcc_label(hcc_code: str) -> str:
    """Look up HCC label from hccinfhir using V28 model (tuple key)."""
    code = str(hcc_code).replace("HCC", "").strip()
    label = _labels_default.get((code, _V28_MODEL))
    if label:
        return label
    return f"HCC {code}"


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class EnrollmentInfoModel(BaseModel):
    """
    Optional enrollment override for OREC and dual-eligibility.

    When provided, the automatic OpenEMR / RAF DB lookup is skipped and these
    values are used directly for model segment determination.

    Fields:
        dual_status:  "non_dual" | "partial_dual" | "full_dual"
        orec:         "0" (aged) | "1" (disabled) | "2" (ESRD) | "3" (disabled+ESRD)
        institutional: True if patient is a SNF / nursing-facility resident.
    """
    dual_status: str = "non_dual"
    orec: str = "0"
    institutional: bool = False


class CalculateRequest(BaseModel):
    year: int | None = None
    enrollment_info: EnrollmentInfoModel | None = None


# ---------------------------------------------------------------------------
# POST /calculate/{pid}
# ---------------------------------------------------------------------------

@router.post("/calculate/{pid}", summary="Calculate RAF score for a patient")
def calculate_raf(pid: int, body: CalculateRequest = CalculateRequest()) -> dict[str, Any]:
    """
    Run the full CMS-HCC V28 RAF calculation for *pid* using hccinfhir.

    Steps performed:
      1. Pull ICD-10 codes from OpenEMR billing
      2. Resolve OREC + dual eligibility (override > OpenEMR > RAF DB > CNA default)
      3. Map codes to HCCs via hccinfhir (includes hierarchy / trump rules)
      4. Sum demographic + disease + interaction coefficients
      5. Persist enrollment info to raf_patient_demographics
      6. Persist results to raf_scores and raf_patient_hcc
      7. Return full breakdown with all coefficients, HCC list, interactions,
         and enrollment_info metadata showing which segment was selected and why

    Optional ``enrollment_info`` body field lets the frontend supply OREC /
    dual status directly, bypassing auto-detection.  Useful when the EHR data
    is incomplete or when testing alternative segment scenarios.
    """
    patient = get_patient(pid)
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient {pid} not found")

    calc_year = body.year or date.today().year
    enrollment_override = body.enrollment_info.model_dump() if body.enrollment_info else None

    try:
        result = calculate_raf_score(
            patient_id=pid,
            measurement_year=calc_year,
            enrollment_override=enrollment_override,
        )
    except Exception as exc:
        logger.error("calculate_raf error pid=%s: %s", pid, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))

    return result


# ---------------------------------------------------------------------------
# POST /calculate-all
# ---------------------------------------------------------------------------

@router.post("/calculate-all", summary="Batch calculate RAF for all patients")
def calculate_all(year: int = Query(default=None)) -> dict[str, Any]:
    """
    Synchronously calculate RAF for every patient in OpenEMR and return a
    summary of results.  For large populations consider running this
    off-hours; typical runtime is ~1-3 seconds per patient.
    """
    calc_year = year or date.today().year
    try:
        results = calculate_raf_for_all_patients(year=calc_year)
    except Exception as exc:
        logger.error("calculate_all error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))

    successes = [r for r in results if "error" not in r]
    errors = [r for r in results if "error" in r]

    scores = [r["raf_score"] for r in successes if isinstance(r.get("raf_score"), (int, float))]
    avg_raf = round(statistics.mean(scores), 4) if scores else 0.0
    median_raf = round(statistics.median(scores), 4) if scores else 0.0

    return {
        "measurement_year": calc_year,
        "total_processed": len(results),
        "succeeded": len(successes),
        "failed": len(errors),
        "average_raf": avg_raf,
        "median_raf": median_raf,
        "errors": [{"patient_id": r["patient_id"], "error": r["error"]} for r in errors],
        "scores": [
            {
                "patient_id": r["patient_id"],
                "raf_score": r.get("raf_score"),
                "hcc_count": len(r.get("final_hcc_list", [])),
            }
            for r in successes
        ],
    }


# ---------------------------------------------------------------------------
# GET /scores/{pid}
# ---------------------------------------------------------------------------

@router.get("/scores/{pid}", summary="Get stored RAF score for a patient")
def get_scores(pid: int, year: int = Query(default=None)) -> dict[str, Any]:
    """
    Return the most recent stored RAF score for *pid*.

    If *year* is omitted, defaults to the current year.  Use
    GET /api/raf/scores/{pid}/history for scores across all years.
    """
    patient = get_patient(pid)
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient {pid} not found")

    calc_year = year or date.today().year
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT
                    patient_id, measurement_year, model_segment,
                    demographic_score, disease_score, interaction_score,
                    total_raw, final_raf, hcc_count, calculated_at
                FROM raf_scores
                WHERE patient_id = %s AND measurement_year = %s
                ORDER BY calculated_at DESC
                LIMIT 1
                """,
                (pid, calc_year),
            )
            row = cur.fetchone()
    except Exception as exc:
        logger.error("get_scores db error pid=%s: %s", pid, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))

    if not row:
        raise HTTPException(
            status_code=404,
            detail=f"No RAF score found for patient {pid} in year {calc_year}. "
                   "Use POST /api/raf/calculate/{pid} to calculate.",
        )

    return {
        "patient_id": pid,
        "patient_name": f"{patient.get('fname', '')} {patient.get('lname', '')}".strip(),
        "measurement_year": row["measurement_year"],
        "model_segment": row.get("model_segment", "CNA"),
        "raf_score": float(row["final_raf"]),
        "demographic_score": float(row.get("demographic_score") or 0),
        "disease_score": float(row.get("disease_score") or 0),
        "interaction_score": float(row.get("interaction_score") or 0),
        "hcc_count": row.get("hcc_count", 0),
        "calculated_at": str(row.get("calculated_at", "")),
    }


# ---------------------------------------------------------------------------
# GET /scores/{pid}/breakdown
# ---------------------------------------------------------------------------

@router.get("/scores/{pid}/breakdown", summary="Detailed HCC breakdown with MEAT status")
def get_breakdown(
    pid: int,
    year: int = Query(default=None),
) -> dict[str, Any]:
    """
    Return the full stored RAF breakdown for *pid* / *year* including:
      - Score components (demographic, disease, interaction)
      - Per-HCC contributions with ICD-10 codes
      - MEAT documentation status for each HCC
    """
    patient = get_patient(pid)
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient {pid} not found")

    calc_year = year or date.today().year
    try:
        breakdown = get_raf_breakdown(pid, calc_year)
    except Exception as exc:
        logger.error("get_breakdown error pid=%s: %s", pid, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))

    if not breakdown:
        raise HTTPException(
            status_code=404,
            detail=f"No RAF score found for patient {pid} / year {calc_year}",
        )

    # Annotate HCC details with human-readable labels and MEAT completeness
    hcc_details = breakdown.get("hcc_details", [])

    # Load per-HCC MEAT completeness once for the whole patient/year
    meat_completeness_report: dict[str, dict[str, Any]] = {}
    try:
        from app.services.meat_evidence_service import calculate_meat_completeness
        report = calculate_meat_completeness(pid, calc_year)
        for entry in report.get("per_hcc", []):
            meat_completeness_report[str(entry["hcc_code"])] = entry
    except ImportError:
        pass
    except Exception as exc:
        logger.debug("MEAT completeness unavailable for pid=%s: %s", pid, exc)

    annotated_hccs = []
    for hcc in hcc_details:
        hcc_code = str(hcc.get("hcc_code", ""))
        meat_status = hcc.get("meat_status", "missing")

        # Use per-HCC completeness data if available
        meat_completeness: dict[str, Any] = meat_completeness_report.get(hcc_code, {})

        # Clean up icd10_codes — may be stringified Python set like "{'E6601', 'Z6841'}"
        raw_codes = hcc.get("icd10_codes", [])
        clean_codes: list[str] = []
        for c in raw_codes:
            s = str(c).strip()
            if s.startswith("{") and s.endswith("}"):
                # Parse stringified set: "{'E6601', 'Z6841'}"
                inner = s[1:-1]
                for part in inner.split(","):
                    code = part.strip().strip("'\"")
                    if code:
                        # Add dots to ICD-10 codes (E6601 → E66.01)
                        if len(code) > 3 and "." not in code and code[0].isalpha():
                            code = code[:3] + "." + code[3:]
                        clean_codes.append(code)
            else:
                if len(s) > 3 and "." not in s and s[0].isalpha():
                    s = s[:3] + "." + s[3:]
                clean_codes.append(s)

        annotated_hccs.append({
            "hcc_code": hcc_code,
            "hcc_label": _hcc_label(hcc_code),
            "icd10_codes": clean_codes,
            "meat_status": meat_status,
            "meat_completeness": meat_completeness,
        })

    return {
        "patient_id": pid,
        "patient_name": f"{patient.get('fname', '')} {patient.get('lname', '')}".strip(),
        "measurement_year": calc_year,
        "raf_score": breakdown.get("raf_score", 0.0),
        "demographic_score": breakdown.get("demographic_score", 0.0),
        "disease_score": breakdown.get("disease_score", 0.0),
        "interaction_score": breakdown.get("interaction_score", 0.0),
        "hcc_count": breakdown.get("hcc_count", 0),
        "model_segment": breakdown.get("model_segment", "CNA"),
        "calculated_at": breakdown.get("calculated_at", ""),
        "hcc_details": annotated_hccs,
    }


# ---------------------------------------------------------------------------
# GET /population-summary
# ---------------------------------------------------------------------------

_RAF_RANGES = [
    ("0.0-0.5", 0.0, 0.5),
    ("0.5-1.0", 0.5, 1.0),
    ("1.0-1.5", 1.0, 1.5),
    ("1.5-2.0", 1.5, 2.0),
    ("2.0+",    2.0, float("inf")),
]


@router.get("/population-summary", summary="Population-level RAF statistics")
def population_summary(year: int = Query(default=None)) -> dict[str, Any]:
    """
    Return aggregate RAF statistics for the current patient population.

    Includes average/median RAF, distribution buckets, and the most
    frequently occurring HCCs across the population.
    """
    calc_year = year or date.today().year

    # --- 1. Total patient count from OpenEMR ---
    try:
        total_patients = get_patient_count()
    except Exception as exc:
        logger.error("population_summary patient count error: %s", exc)
        total_patients = 0

    # --- 2. Scores from raf_scores ---
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT patient_id, final_raf
                FROM raf_scores
                WHERE measurement_year = %s
                ORDER BY calculated_at DESC
                """,
                (calc_year,),
            )
            score_rows = cur.fetchall()
    except Exception as exc:
        logger.error("population_summary scores error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))

    # De-duplicate: keep one score per patient (latest already by ORDER BY)
    seen: set[int] = set()
    scores: list[float] = []
    for row in score_rows:
        pid = row["patient_id"]
        if pid not in seen:
            seen.add(pid)
            scores.append(float(row["final_raf"]))

    patients_with_scores = len(scores)
    average_raf = round(statistics.mean(scores), 4) if scores else 0.0
    median_raf = round(statistics.median(scores), 4) if scores else 0.0

    # Distribution buckets
    raf_distribution = []
    for label, lo, hi in _RAF_RANGES:
        if hi == float("inf"):
            count = sum(1 for s in scores if s >= lo)
        else:
            count = sum(1 for s in scores if lo <= s < hi)
        raf_distribution.append({"range": label, "count": count})

    # --- 3. Top HCCs across population ---
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT hcc_code, COUNT(DISTINCT patient_id) AS patient_count
                FROM raf_patient_hcc
                WHERE measurement_year = %s
                GROUP BY hcc_code
                ORDER BY patient_count DESC
                LIMIT 10
                """,
                (calc_year,),
            )
            hcc_rows = cur.fetchall()
    except Exception as exc:
        logger.warning("population_summary HCC query error: %s", exc)
        hcc_rows = []

    top_hccs = [
        {
            "hcc": str(row["hcc_code"]),
            "label": _hcc_label(str(row["hcc_code"])),
            "count": row["patient_count"],
        }
        for row in hcc_rows
    ]

    return {
        "measurement_year": calc_year,
        "total_patients": total_patients,
        "patients_with_scores": patients_with_scores,
        "average_raf": average_raf,
        "median_raf": median_raf,
        "raf_distribution": raf_distribution,
        "top_hccs": top_hccs,
    }


# ---------------------------------------------------------------------------
# GET /scores/{pid}/history
# ---------------------------------------------------------------------------

@router.get("/scores/{pid}/history", summary="RAF score history for a patient (all years)")
def get_score_history(pid: int) -> dict[str, Any]:
    """
    Return all RAF scores ever calculated for *pid*, one entry per year,
    ordered newest-first.
    """
    patient = get_patient(pid)
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient {pid} not found")

    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT
                    measurement_year,
                    model_segment,
                    demographic_score,
                    disease_score,
                    interaction_score,
                    total_raw,
                    final_raf,
                    hcc_count,
                    calculated_at
                FROM raf_scores
                WHERE patient_id = %s
                ORDER BY measurement_year DESC, calculated_at DESC
                """,
                (pid,),
            )
            rows = cur.fetchall()
    except Exception as exc:
        logger.error("get_score_history db error pid=%s: %s", pid, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))

    # De-duplicate: one row per year (the latest calculation)
    seen_years: set[int] = set()
    history: list[dict[str, Any]] = []
    for row in rows:
        yr = row["measurement_year"]
        if yr in seen_years:
            continue
        seen_years.add(yr)
        history.append({
            "measurement_year": yr,
            "model_segment": row.get("model_segment", "CNA"),
            "raf_score": float(row["final_raf"]),
            "demographic_score": float(row.get("demographic_score") or 0),
            "disease_score": float(row.get("disease_score") or 0),
            "interaction_score": float(row.get("interaction_score") or 0),
            "hcc_count": row.get("hcc_count", 0),
            "calculated_at": str(row.get("calculated_at", "")),
        })

    return {
        "patient_id": pid,
        "patient_name": f"{patient.get('fname', '')} {patient.get('lname', '')}".strip(),
        "years_calculated": len(history),
        "history": history,
    }
