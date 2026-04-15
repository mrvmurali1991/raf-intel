"""
RAF router — hccinfhir-based CMS-HCC V24/V28 blended endpoints + multi-model.

POST /api/raf/calculate/{pid}                 - Calculate RAF for a single patient
POST /api/raf/calculate-all                   - Batch calculate for all patients
GET  /api/raf/scores/{pid}                    - Stored RAF score for a patient
GET  /api/raf/scores/{pid}/breakdown          - Detailed HCC breakdown with MEAT status
GET  /api/raf/scores/{pid}/model-comparison   - V24 vs V28 side-by-side comparison
GET  /api/raf/population-summary              - Population-level stats
GET  /api/raf/scores/{pid}/history            - All years calculated for a patient

Multi-Model Endpoints:
GET  /api/raf/models                          - List all available RAF models with descriptions
POST /api/raf/calculate-multi/{pid}           - Calculate RAF across CMS-HCC, RxHCC, HHS-HCC simultaneously
GET  /api/raf/scores/{pid}/multi-model        - Compare stored CMS-HCC scores + run RxHCC/HHS-HCC on live data

CMS Blend Schedule:
  PY2024: 67% V24 + 33% V28
  PY2025: 33% V24 + 67% V28
  PY2026+: 100% V28
"""
# Removed: from __future__ import annotations (breaks FastAPI schema generation)

import logging
import statistics
from collections import Counter
from datetime import date
from typing import Any, Literal

from fastapi import Body, Depends, APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.services.raf_calculator import (
    calculate_raf_score,
    calculate_raf_score_multi_model,
    get_raf_breakdown,
    _BLEND_WEIGHTS,
    _get_patient,
    _get_icd_codes,
    _calculate_age,
    _sex_code,
)
from app.services.multi_model_calculator import (
    calculate_multi_model,
    AVAILABLE_MODELS,
)
from app.services.openemr_connector import (
    get_patient_count,
)
from app.db import raf_cursor, run_in_db_executor
from app.auth import get_current_user, get_tenant_id, require_permission
from app.rate_limit import limiter
from app.services.emr_manager import active_patients_subquery
from app.services.audit_logger import log_phi_access

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/raf", tags=["raf"])

# ---------------------------------------------------------------------------
# HCC label lookup
# ---------------------------------------------------------------------------

from hccinfhir.defaults import labels_default as _labels_default

_V28_MODEL = "CMS-HCC Model V28"
_V24_MODEL = "CMS-HCC Model V24"


def _hcc_label(hcc_code: str, model: str = _V28_MODEL) -> str:
    """Look up HCC label from hccinfhir for the specified model."""
    code = str(hcc_code).replace("HCC", "").strip()
    label = _labels_default.get((code, model))
    if label:
        return label
    # Fallback to V28 label if V24-specific not found
    if model != _V28_MODEL:
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
        dual_status:   "non_dual" | "partial_dual" | "full_dual"
        orec:          "0" (aged) | "1" (disabled) | "2" (ESRD) | "3" (disabled+ESRD)
        institutional: True if patient is a SNF / nursing-facility resident.
    """

    dual_status: str = "non_dual"
    orec: str = "0"
    institutional: bool = False


class ADLDataModel(BaseModel):
    """
    Activities of Daily Living (ADL) impairment data for PACE/FIDE-SNP frailty adjustment.

    The CMS frailty adjustment applies a payment addend to PACE and FIDE-SNP plans
    based on the number of ADL impairments (0-6 scale). At least 3 impairments
    triggers frailty designation.
    """

    bathing: bool = Field(
        default=False, description="Impaired ability to bathe independently"
    )
    dressing: bool = Field(
        default=False, description="Impaired ability to dress independently"
    )
    eating: bool = Field(
        default=False, description="Impaired ability to eat independently"
    )
    toileting: bool = Field(
        default=False, description="Impaired ability to use toilet independently"
    )
    transferring: bool = Field(
        default=False, description="Impaired ability to transfer (e.g., bed to chair)"
    )
    continence: bool = Field(default=False, description="Impaired continence")


class CalculateRequest(BaseModel):
    year: int | None = Field(
        default=None, description="Payment/measurement year. Defaults to current year."
    )
    enrollment_info: EnrollmentInfoModel | None = None
    model_version: Literal["v24", "v28", "blended", "auto"] = Field(
        default="auto",
        description=(
            "Model version to use. 'auto' applies CMS transition blend rules: "
            "PY2024=67%V24+33%V28, PY2025=33%V24+67%V28, PY2026+=100%V28."
        ),
    )
    # ── New Enrollee Model ────────────────────────────────────────────────────
    enrollment_months: int = Field(
        default=12,
        ge=1,
        le=12,
        description=(
            "Months of Part B coverage in the measurement year. "
            "Patients with <12 months use the New Enrollee (NE) demographic-only model, "
            "bypassing HCC coding per CMS methodology."
        ),
    )
    # ── CMS Sweep Period ──────────────────────────────────────────────────────
    sweep_period: Literal["initial", "midyear", "final", "none"] | None = Field(
        default=None,
        description=(
            "CMS sweep period for date-of-service filtering. "
            "'initial'=Jan-Mar, 'midyear'=Jan-Jun, 'final'=full year. "
            "'none' or null bypasses date filtering."
        ),
    )
    # ── PACE / FIDE-SNP Frailty ───────────────────────────────────────────────
    plan_type: str = Field(
        default="MA",
        description=(
            "CMS plan type for frailty adjustment eligibility. "
            "'PACE' and 'FIDE_SNP' plans receive a frailty addend when ≥3 ADLs impaired. "
            "Other values: 'MA', 'SNP', 'MAPD'."
        ),
    )
    adl_data: ADLDataModel | None = Field(
        default=None,
        description=(
            "ADL impairment data for PACE/FIDE-SNP frailty adjustment. "
            "Omit for non-PACE/FIDE-SNP plans—frailty adjustment will not be applied."
        ),
    )


# ---------------------------------------------------------------------------
# POST /calculate/{pid}
# ---------------------------------------------------------------------------


@router.post("/calculate/{pid}", summary="Calculate RAF score for a patient")
@limiter.limit("10/minute")
async def calculate_raf(
    request: Request,
    pid: int,
    body: CalculateRequest = CalculateRequest(),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("raf_scores", "write")),
) -> dict[str, Any]:
    """
    Run the CMS-HCC RAF calculation for *pid*.

    **Model version** (`model_version`):
    - **auto** (default): CMS transition schedule
      - 2024: 67% V24 + 33% V28 | 2025: 33% V24 + 67% V28 | 2026+: 100% V28
    - **v28** / **v24** / **blended**: explicit override

    **New Enrollee model** (`enrollment_months < 12`):
    - Patients with < 12 months Part B coverage use the NE demographic-only model.
    - HCC codes are ignored; only age/sex/dual status demographic factors apply.

    **Sweep period** (`sweep_period`):
    - Filters ICD-10 codes by CMS date-of-service window:
      initial=Q1, midyear=H1, final=full year.

    **Frailty adjustment** (`plan_type` + `adl_data`):
    - PACE and FIDE-SNP plans with ≥ 3 ADL impairments receive a CMS frailty addend.
    - Provide `adl_data` fields to trigger this calculation.

    Response includes `blend_weights`, `v24_score`, `v28_score`, `new_enrollee`,
    `frailty_addend`, `sweep_period`, and all standard fields.

    Converted to ``async def`` — ``calculate_raf_score`` does multiple
    synchronous MySQL round-trips (patient fetch, ICD-10 lookup, score persist).
    Dispatching via ``run_in_db_executor`` keeps the event loop responsive under
    concurrent calculation requests.
    """
    patient = await run_in_db_executor(_get_patient, pid, tenant_id)
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient {pid} not found")

    logger.debug("calculate_raf pid=%s tenant=%s user=%s", pid, tenant_id, current_user.get("id"))
    calc_year = body.year or date.today().year
    enrollment_override = (
        body.enrollment_info.model_dump() if body.enrollment_info else None
    )

    # Build ADL dict for frailty service
    adl_data: dict | None = None
    if body.adl_data is not None:
        adl_data = body.adl_data.model_dump()

    # Normalise sweep_period: 'none' → None
    sweep = (
        body.sweep_period if body.sweep_period and body.sweep_period != "none" else None
    )

    def _run_calculation() -> dict:
        return calculate_raf_score(
            patient_id=pid,
            measurement_year=calc_year,
            enrollment_override=enrollment_override,
            model_version=body.model_version,
            enrollment_months=body.enrollment_months,
            sweep_period=sweep,
            adl_data=adl_data,
            plan_type=body.plan_type,
            tenant_id=tenant_id,
        )

    try:
        result = await run_in_db_executor(_run_calculation)
    except Exception as exc:
        logger.error("calculate_raf error pid=%s: %s", pid, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

    return result


# ---------------------------------------------------------------------------
# POST /calculate-all
# ---------------------------------------------------------------------------


@router.post("/calculate-all", summary="Batch calculate RAF for all patients")
@limiter.limit("2/minute")
def calculate_all(
    request: Request,
    year: int | None = Query(default=None),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("raf_scores", "write")),
) -> dict[str, Any]:
    """
    Dispatch an async background job to calculate RAF for every patient in
    OpenEMR.  Returns immediately with a job_id for polling via
    GET /api/jobs/{job_id}.

    The job runs via Celery so it never blocks the API process regardless of
    population size.  Poll GET /api/jobs/{job_id} for progress and results.
    """
    from app.services.job_service import dispatch_calculate_raf_batch

    calc_year = year or date.today().year

    # Collect all patient IDs upfront so the Celery task has an explicit list
    # (allows per-patient progress tracking in the job row).
    # For FHIR/REST connections, pull IDs from emr_patient_matches instead of
    # querying the local OpenEMR database directly.
    _conn_type = None
    try:
        with raf_cursor() as _ct_cur:
            _ct_cur.execute("SELECT connection_type FROM emr_connections WHERE is_active = 1 LIMIT 1")
            _ct_r = _ct_cur.fetchone()
            _conn_type = _ct_r["connection_type"] if _ct_r else None
    except Exception:
        pass

    if _conn_type in ("fhir_r4", "rest_api"):
        try:
            with raf_cursor() as cur:
                cur.execute(
                    "SELECT epm.id AS pid "
                    "FROM emr_patient_matches epm "
                    "JOIN emr_connections ec ON ec.id = epm.connection_id "
                    "WHERE ec.is_active = 1 ORDER BY pid"
                )
                rows = cur.fetchall() or []
            patient_ids = [int(r["pid"]) for r in rows]
            patient_count = len(patient_ids)
        except Exception as exc:
            logger.error("calculate_all: failed to fetch FHIR patient IDs: %s", exc, exc_info=True)
            raise HTTPException(status_code=500, detail="Failed to fetch patient list")
    else:
        try:
            patient_count = get_patient_count()
        except Exception as exc:
            logger.error("calculate_all: failed to count patients: %s", exc, exc_info=True)
            raise HTTPException(status_code=500, detail="Failed to query patient count")

        try:
            with raf_cursor() as cur:
                cur.execute(
                    "SELECT id FROM patients WHERE is_active = 1 AND tenant_id = %s ORDER BY id",
                    (tenant_id,),
                )
                rows = cur.fetchall() or []
            patient_ids = [int(r["id"]) for r in rows]
        except Exception as exc:
            logger.error("calculate_all: failed to fetch patient IDs: %s", exc, exc_info=True)
            raise HTTPException(status_code=500, detail="Failed to fetch patient list")

    if patient_count == 0:
        raise HTTPException(status_code=400, detail="No patients found")

    # Convert tenant_id to int (required by job_service)
    try:
        tenant_id_int: int | None = int(tenant_id) if tenant_id else None
    except (TypeError, ValueError):
        tenant_id_int = None

    submitted_by: int | None = None
    try:
        submitted_by = int(current_user.get("id", 0)) or None
    except (TypeError, ValueError):
        pass

    try:
        job_id = dispatch_calculate_raf_batch(
            patient_ids=patient_ids,
            year=calc_year,
            tenant_id=tenant_id_int,
            submitted_by=submitted_by,
        )
    except Exception as exc:
        logger.error("calculate_all: dispatch failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to dispatch batch job")

    logger.info(
        "calculate_all dispatched job=%s patients=%d year=%d tenant=%s user=%s",
        job_id,
        len(patient_ids),
        calc_year,
        tenant_id,
        current_user.get("id"),
    )

    return {
        "status": "dispatched",
        "job_id": job_id,
        "message": f"RAF calculation queued for {len(patient_ids)} patients (year {calc_year})",
        "patient_count": len(patient_ids),
        "measurement_year": calc_year,
        "poll_url": f"/api/jobs/{job_id}",
    }


# ---------------------------------------------------------------------------
# GET /scores/{pid}
# ---------------------------------------------------------------------------


@router.get("/scores/{pid}", summary="Get stored RAF score for a patient")
async def get_scores(
    pid: int,
    year: int | None = Query(default=None),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("raf_scores", "read")),
) -> dict[str, Any]:
    """
    Return the most recent stored RAF score for *pid*.

    If *year* is omitted, defaults to the current year. Use
    GET /api/raf/scores/{pid}/history for scores across all years.

    Converted to ``async def`` — the patient existence check and the
    ``raf_scores`` SELECT are both dispatched to the dedicated DB thread pool
    so neither blocks the event loop.
    """
    patient = await run_in_db_executor(_get_patient, pid, tenant_id)
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient {pid} not found")

    calc_year = year or date.today().year
    _tid = int(tenant_id)

    _sf, _sp = active_patients_subquery(_tid)

    def _fetch_score() -> dict | None:
        with raf_cursor() as cur:
            cur.execute(
                f"""
                SELECT
                    patient_id, measurement_year, score_type, model_segment,
                    demographic_score, disease_score, interaction_score,
                    total_raw, final_raf, hcc_count, calculated_at
                FROM raf_scores
                WHERE patient_id = %s AND measurement_year = %s
                  AND {_sf}
                  AND raf_scores.tenant_id = %s
                ORDER BY calculated_at DESC
                LIMIT 1
                """,
                (pid, calc_year, *_sp, _tid),
            )
            return cur.fetchone()

    try:
        row = await run_in_db_executor(_fetch_score)
    except Exception as exc:
        logger.error("get_scores db error pid=%s: %s", pid, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

    if not row:
        raise HTTPException(
            status_code=404,
            detail=f"No RAF score found for patient {pid} in year {calc_year}. "
            "Use POST /api/raf/calculate/{pid} to calculate.",
        )

    v24_w, v28_w = _BLEND_WEIGHTS.get(calc_year, (0.0, 1.0))

    log_phi_access(
        action="view_raf_scores",
        resource="raf_scores",
        patient_id=pid,
        details=f"year={calc_year}",
        tenant_id=tenant_id,
    )
    return {
        "patient_id": pid,
        "patient_name": f"{patient.get('fname', '')} {patient.get('lname', '')}".strip(),
        "measurement_year": row["measurement_year"],
        "model_segment": row.get("model_segment", "CNA"),
        "score_type": row.get("score_type", "v28"),
        "raf_score": float(row["final_raf"]),
        "demographic_score": float(row.get("demographic_score") or 0),
        "disease_score": float(row.get("disease_score") or 0),
        "interaction_score": float(row.get("interaction_score") or 0),
        "hcc_count": row.get("hcc_count", 0),
        "blend_weights": {"v24": round(v24_w, 4), "v28": round(v28_w, 4)},
        "calculated_at": str(row.get("calculated_at", "")),
    }


# ---------------------------------------------------------------------------
# GET /scores/{pid}/breakdown
# ---------------------------------------------------------------------------


@router.get(
    "/scores/{pid}/breakdown", summary="Detailed HCC breakdown with MEAT status"
)
async def get_breakdown(
    pid: int,
    year: int | None = Query(default=None),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("raf_scores", "read")),
) -> dict[str, Any]:
    """
    Return the full stored RAF breakdown for *pid* / *year* including:
      - Score components (demographic, disease, interaction)
      - Per-HCC contributions with ICD-10 codes
      - MEAT documentation status for each HCC
      - Model version and blend info for the stored score

    Converted to ``async def`` — patient lookup and ``get_raf_breakdown``
    both touch MySQL; dispatching them to the DB executor prevents event-loop
    stalls on the highest-traffic HCC detail endpoint.
    """
    patient = await run_in_db_executor(_get_patient, pid, tenant_id)
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient {pid} not found")

    logger.debug("get_breakdown pid=%s tenant=%s user=%s", pid, tenant_id, current_user.get("id"))
    calc_year = year or date.today().year
    try:
        breakdown = await run_in_db_executor(get_raf_breakdown, pid, calc_year, tenant_id=tenant_id)
    except Exception as exc:
        logger.error("get_breakdown error pid=%s: %s", pid, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

    if not breakdown:
        raise HTTPException(
            status_code=404,
            detail=f"No RAF score found for patient {pid} / year {calc_year}",
        )

    hcc_details = breakdown.get("hcc_details", [])

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
        meat_completeness: dict[str, Any] = meat_completeness_report.get(hcc_code, {})

        raw_codes = hcc.get("icd10_codes", [])
        clean_codes: list[str] = []
        for c in raw_codes:
            s = str(c).strip()
            if s.startswith("{") and s.endswith("}"):
                inner = s[1:-1]
                for part in inner.split(","):
                    code = part.strip().strip("'\"")
                    if code:
                        if len(code) > 3 and "." not in code and code[0].isalpha():
                            code = code[:3] + "." + code[3:]
                        clean_codes.append(code)
            else:
                if len(s) > 3 and "." not in s and s[0].isalpha():
                    s = s[:3] + "." + s[3:]
                clean_codes.append(s)

        annotated_hccs.append(
            {
                "hcc_code": hcc_code,
                "hcc_label": _hcc_label(hcc_code),
                "coefficient": hcc.get("coefficient", 0.0),
                "icd10_codes": clean_codes,
                "meat_status": meat_status,
                "meat_completeness": meat_completeness,
            }
        )

    v24_w, v28_w = _BLEND_WEIGHTS.get(calc_year, (0.0, 1.0))

    result = {
        "patient_id": pid,
        "patient_name": f"{patient.get('fname', '')} {patient.get('lname', '')}".strip(),
        "measurement_year": calc_year,
        "raf_score": breakdown.get("raf_score", 0.0),
        "final_raf": breakdown.get("final_raf", breakdown.get("raf_score", 0.0)),
        "demographic_score": breakdown.get("demographic_score", 0.0),
        "disease_score": breakdown.get("disease_score", 0.0),
        "interaction_score": breakdown.get("interaction_score", 0.0),
        "hcc_count": breakdown.get("hcc_count", 0),
        "model_segment": breakdown.get("model_segment", "CNA"),
        "score_type": breakdown.get("score_type", "v28"),
        "blend_weights": {"v24": round(v24_w, 4), "v28": round(v28_w, 4)},
        "calculated_at": breakdown.get("calculated_at", ""),
        "hcc_details": annotated_hccs,
    }
    # Pass through engine_input/engine_output for the Calculation Pipeline UI
    if breakdown.get("engine_input"):
        result["engine_input"] = breakdown["engine_input"]
    if breakdown.get("engine_output"):
        result["engine_output"] = breakdown["engine_output"]

    log_phi_access(
        action="view_raf_breakdown",
        resource="raf_scores",
        patient_id=pid,
        details=f"year={calc_year} hcc_count={len(annotated_hccs)}",
        tenant_id=tenant_id,
    )
    return result


# ---------------------------------------------------------------------------
# GET /scores/{pid}/model-comparison  (NEW)
# ---------------------------------------------------------------------------


@router.get(
    "/scores/{pid}/model-comparison",
    summary="Side-by-side V24 vs V28 RAF comparison for a patient",
)
def get_model_comparison(
    pid: int,
    year: int | None = Query(default=None),
    enrollment_override_dual: str = Query(
        default=None,
        alias="dual_status",
        description="Override dual status: non_dual | partial_dual | full_dual",
    ),
    enrollment_override_orec: str = Query(
        default=None,
        alias="orec",
        description="Override OREC: 0 | 1 | 2 | 3",
    ),
    enrollment_override_inst: bool = Query(
        default=False,
        alias="institutional",
        description="Override institutional flag",
    ),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("raf_scores", "read")),
) -> dict[str, Any]:
    """
    Run both CMS-HCC V24 and V28 models for *pid* and return a detailed
    side-by-side comparison.

    Response includes:
    - **v24**: full single-model result (raw score, HCCs, coefficients, interactions)
    - **v28**: full single-model result
    - **blended**: blended raw score and payment RAF using CMS transition weights
    - **hcc_comparison**: HCCs unique to V24, unique to V28, and present in both
    - **blend_weights**: the CMS-mandated weights for the given payment year

    This endpoint always runs both models regardless of the payment year blend
    schedule, making it useful for prospective analysis in any year.

    Note: this endpoint does NOT persist scores; use POST /api/raf/calculate/{pid}
    for that purpose.
    """
    patient = _get_patient(pid, tenant_id=tenant_id)
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient {pid} not found")

    calc_year = year or date.today().year

    enrollment_override: dict[str, Any] | None = None
    if any(
        [enrollment_override_dual, enrollment_override_orec, enrollment_override_inst]
    ):
        enrollment_override = {
            "dual_status": enrollment_override_dual or "non_dual",
            "orec": enrollment_override_orec or "0",
            "institutional": enrollment_override_inst,
        }

    try:
        comparison = calculate_raf_score_multi_model(
            patient_id=pid,
            measurement_year=calc_year,
            enrollment_override=enrollment_override,
            tenant_id=tenant_id,
        )
    except ValueError as exc:
        logger.warning("model_comparison not found pid=%s: %s", pid, exc)
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("model_comparison error pid=%s: %s", pid, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

    # Annotate HCC labels on the comparison output
    def _annotate_hcc_list(codes: list[str], model: str) -> list[dict[str, str]]:
        return [{"hcc_code": c, "label": _hcc_label(c, model)} for c in codes]

    hcc_comp = comparison.get("hcc_comparison", {})
    comparison["hcc_comparison"]["v24_only_annotated"] = _annotate_hcc_list(
        hcc_comp.get("v24_only", []), _V24_MODEL
    )
    comparison["hcc_comparison"]["v28_only_annotated"] = _annotate_hcc_list(
        hcc_comp.get("v28_only", []), _V28_MODEL
    )
    comparison["hcc_comparison"]["in_both_annotated"] = _annotate_hcc_list(
        hcc_comp.get("in_both", []), _V28_MODEL
    )

    comparison["patient_name"] = (
        f"{patient.get('fname', '')} {patient.get('lname', '')}".strip()
    )

    log_phi_access(
        action="view_model_comparison",
        resource="raf_scores",
        patient_id=pid,
        details=f"year={calc_year}",
        tenant_id=tenant_id,
    )
    return comparison


# ---------------------------------------------------------------------------
# GET /population-summary
# ---------------------------------------------------------------------------

_RAF_RANGES = [
    ("0.0-0.5", 0.0, 0.5),
    ("0.5-1.0", 0.5, 1.0),
    ("1.0-1.5", 1.0, 1.5),
    ("1.5-2.0", 1.5, 2.0),
    ("2.0+", 2.0, float("inf")),
]


@router.get("/population-summary", summary="Population-level RAF statistics")
def population_summary(
    year: int | None = Query(default=None),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("raf_scores", "read")),
) -> dict[str, Any]:
    """
    Return aggregate RAF statistics for the current patient population.

    Includes average/median RAF, distribution buckets, the most frequently
    occurring HCCs, and the blend weights applied for the given year.
    """
    calc_year = year or date.today().year

    # Check if any EMR connection is active before querying OpenEMR
    has_active = False
    _conn_type: str | None = None
    try:
        with raf_cursor() as _cur:
            _cur.execute(
                "SELECT COUNT(*) AS cnt, MAX(connection_type) AS ct "
                "FROM emr_connections WHERE is_active = 1 AND tenant_id = %s",
                (int(tenant_id),),
            )
            _row = _cur.fetchone()
            has_active = bool(_row and _row["cnt"] > 0)
            _conn_type = _row["ct"] if _row else None
    except Exception:
        pass

    if has_active:
        try:
            if _conn_type in ("fhir_r4", "rest_api"):
                with raf_cursor() as _cur3:
                    _cur3.execute(
                        "SELECT COUNT(DISTINCT epm.id) AS cnt "
                        "FROM emr_patient_matches epm "
                        "JOIN emr_connections ec ON ec.id = epm.connection_id "
                        "WHERE ec.is_active = 1 AND ec.tenant_id = %s",
                        (int(tenant_id),),
                    )
                    total_patients = _cur3.fetchone()["cnt"]
            else:
                # Direct-DB: count tenant-scoped active patients inline
                with raf_cursor() as _cur_db:
                    _cur_db.execute(
                        "SELECT COUNT(*) AS cnt FROM patients WHERE is_active = 1 AND tenant_id = %s",
                        (int(tenant_id),),
                    )
                    total_patients = _cur_db.fetchone()["cnt"]
        except Exception as exc:
            logger.error("population_summary patient count error: %s", exc)
            total_patients = 0
    else:
        # Check for uploaded patients when EMR is off
        try:
            with raf_cursor() as _cur_up:
                _cur_up.execute(
                    "SELECT COUNT(*) AS cnt FROM patients WHERE is_active = 1 AND data_source = 'upload' AND tenant_id = %s",
                    (int(tenant_id),),
                )
                total_patients = _cur_up.fetchone()["cnt"]
        except Exception:
            total_patients = 0

    # Scope RAF scores to the correct patient set based on connection type.
    # For FHIR/REST: use emr_patient_matches to find patient IDs.
    # For direct_db or upload: use the patients table via active_patients_subquery.
    if _conn_type in ("fhir_r4", "rest_api"):
        _pop_score_filter = (
            "patient_id IN ("
            "SELECT epm.id "
            "FROM emr_patient_matches epm "
            "JOIN emr_connections ec ON ec.id = epm.connection_id "
            "WHERE ec.is_active = 1 AND ec.tenant_id = %s"
            ")"
        )
        _pop_score_params: tuple = (int(tenant_id),)
    else:
        _pop_score_filter, _pop_score_params = active_patients_subquery(int(tenant_id))
    try:
        with raf_cursor() as cur:
            # Use a subquery to get the best (highest) score per patient,
            # then filter by active-patient tenant scope.
            cur.execute(
                f"""
                SELECT patient_id, final_raf, score_type
                FROM (
                    SELECT patient_id, final_raf, score_type,
                           ROW_NUMBER() OVER (PARTITION BY patient_id ORDER BY final_raf DESC) AS rn
                    FROM raf_scores
                    WHERE measurement_year = %s
                      AND tenant_id = %s
                ) ranked
                WHERE rn = 1
                  AND {_pop_score_filter}
                ORDER BY final_raf DESC
                """,
                (calc_year, int(tenant_id), *_pop_score_params),
            )
            score_rows = cur.fetchall()
    except Exception as exc:
        logger.error("population_summary scores error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

    seen: set[int] = set()
    scores: list[float] = []
    score_type_counts: Counter = Counter()
    for row in score_rows:
        p = row["patient_id"]
        if p not in seen:
            seen.add(p)
            scores.append(float(row["final_raf"]))
            score_type_counts[row.get("score_type", "v28")] += 1

    patients_with_scores = len(scores)
    average_raf = round(statistics.mean(scores), 4) if scores else 0.0
    median_raf = round(statistics.median(scores), 4) if scores else 0.0

    raf_distribution = []
    for label, lo, hi in _RAF_RANGES:
        if hi == float("inf"):
            count = sum(1 for s in scores if s >= lo)
        else:
            count = sum(1 for s in scores if lo <= s < hi)
        raf_distribution.append({"range": label, "count": count})

    try:
        # Reuse the same patient-scoping filter already built for score queries.
        with raf_cursor() as cur:
            cur.execute(
                f"""
                SELECT hcc_code, COUNT(DISTINCT patient_id) AS patient_count
                FROM raf_patient_hcc
                WHERE measurement_year = %s
                  AND tenant_id = %s
                  AND {_pop_score_filter}
                GROUP BY hcc_code
                ORDER BY patient_count DESC
                LIMIT 10
                """,
                (calc_year, int(tenant_id), *_pop_score_params),
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

    v24_w, v28_w = _BLEND_WEIGHTS.get(calc_year, (0.0, 1.0))

    # patients_with_gaps & hcc_capture_rate for frontend
    patients_with_gaps = 0
    hcc_capture_rate = 0.0
    try:
        with raf_cursor() as cur:
            cur.execute(
                "SELECT COUNT(DISTINCT patient_id) AS cnt FROM care_gap_tasks WHERE tenant_id = %s AND status NOT IN ('completed', 'rejected')",
                (tenant_id,),
            )
            patients_with_gaps = cur.fetchone()["cnt"]
            if total_patients:
                hcc_capture_rate = round(patients_with_scores / total_patients * 100, 1)
    except Exception:
        pass

    return {
        "year": calc_year,
        "total_patients": total_patients,
        "patients_with_scores": patients_with_scores,
        "average_raf_score": average_raf,
        "median_raf_score": median_raf,
        "patients_with_gaps": patients_with_gaps,
        "hcc_capture_rate": hcc_capture_rate,
        "total_revenue_opportunity": round(sum(scores) * 12614, 2) if scores else 0,
        "raf_distribution": raf_distribution,
        "top_hccs": top_hccs,
        "blend_weights": {"v24": round(v24_w, 4), "v28": round(v28_w, 4)},
        "score_type_breakdown": dict(score_type_counts),
    }


# ---------------------------------------------------------------------------
# GET /scores/{pid}/history
# ---------------------------------------------------------------------------


@router.get(
    "/scores/{pid}/history", summary="RAF score history for a patient (all years)"
)
def get_score_history(
    pid: int,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("raf_scores", "read")),
) -> dict[str, Any]:
    """
    Return all RAF scores ever calculated for *pid*, one entry per year,
    ordered newest-first. Includes `score_type` and `blend_weights` per year.
    """
    patient = _get_patient(pid, tenant_id=tenant_id)
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient {pid} not found")

    _sf, _sp = active_patients_subquery(int(tenant_id))
    try:
        with raf_cursor() as cur:
            cur.execute(
                f"""
                SELECT
                    measurement_year,
                    score_type,
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
                  AND {_sf}
                  AND raf_scores.tenant_id = %s
                ORDER BY
                    measurement_year DESC,
                    calculated_at DESC
                """,
                (pid, *_sp, int(tenant_id)),
            )
            rows = cur.fetchall()
    except Exception as exc:
        logger.error("get_score_history db error pid=%s: %s", pid, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

    seen_years: set[int] = set()
    history: list[dict[str, Any]] = []
    for row in rows:
        yr = row["measurement_year"]
        if yr in seen_years:
            continue
        seen_years.add(yr)
        v24_w, v28_w = _BLEND_WEIGHTS.get(yr, (0.0, 1.0))
        history.append(
            {
                "measurement_year": yr,
                "score_type": row.get("score_type", "v28"),
                "blend_weights": {"v24": round(v24_w, 4), "v28": round(v28_w, 4)},
                "model_segment": row.get("model_segment", "CNA"),
                "raf_score": float(row["final_raf"]),
                "demographic_score": float(row.get("demographic_score") or 0),
                "disease_score": float(row.get("disease_score") or 0),
                "interaction_score": float(row.get("interaction_score") or 0),
                "hcc_count": row.get("hcc_count", 0),
                "calculated_at": str(row.get("calculated_at", "")),
            }
        )

    log_phi_access(
        action="view_raf_history",
        resource="raf_scores",
        patient_id=pid,
        details=f"years_returned={len(history)}",
        tenant_id=tenant_id,
    )
    return {
        "patient_id": pid,
        "patient_name": f"{patient.get('fname', '')} {patient.get('lname', '')}".strip(),
        "years_calculated": len(history),
        "history": history,
    }


# ---------------------------------------------------------------------------
# GET /models
# ---------------------------------------------------------------------------


@router.get("/models", summary="List all available RAF models with descriptions")
def list_models(
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Return metadata for every RAF model supported by this system.

    Models:
    - **cms_hcc_v24**: CMS-HCC Version 24 — Medicare Advantage medical (phase-out)
    - **cms_hcc_v28**: CMS-HCC Version 28 — Medicare Advantage medical (current)
    - **rxhcc**: RxHCC — Medicare Part D prescription drug risk adjustment
    - **hhs_hcc**: HHS-HCC — ACA/Exchange marketplace concurrent risk adjustment

    Key model differences are highlighted to guide which model to apply
    for a given population and program type.
    """
    return {
        "total_models": len(AVAILABLE_MODELS),
        "models": AVAILABLE_MODELS,
        "quick_reference": {
            "medicare_advantage_ma": {
                "models": ["cms_hcc_v28", "cms_hcc_v24"],
                "note": "Use CMS-HCC V28 for MA plans. V24/V28 blend applies through PY2025.",
            },
            "medicare_part_d_mapd": {
                "models": ["rxhcc"],
                "note": "Use RxHCC for Part D drug cost risk adjustment.",
            },
            "aca_exchange_marketplace": {
                "models": ["hhs_hcc"],
                "note": "Use HHS-HCC for ACA/Exchange risk transfer calculations.",
            },
        },
        "cms_blend_schedule": {
            "PY2024": "67% V24 + 33% V28",
            "PY2025": "33% V24 + 67% V28",
            "PY2026+": "100% V28",
        },
    }


# ---------------------------------------------------------------------------
# Request model for multi-model calculation
# ---------------------------------------------------------------------------


class MultiModelRequest(BaseModel):
    """Request body for POST /calculate-multi/{pid}."""

    models: list[str] = Field(
        default=["cms_hcc_v28", "rxhcc", "hhs_hcc"],
        description=(
            "List of models to run. Options: cms_hcc_v24, cms_hcc_v28, rxhcc, hhs_hcc. "
            "Default runs V28 + RxHCC + HHS-HCC."
        ),
    )
    year: int | None = Field(
        default=None,
        description="Payment/plan year. Defaults to current year.",
    )
    low_income_subsidy: bool = Field(
        default=False,
        description="RxHCC: True if patient has LIS/Extra Help (Part D Low Income Subsidy).",
    )
    metal_level: str = Field(
        default="silver",
        description="HHS-HCC: ACA plan metal tier (bronze/silver/gold/platinum).",
    )
    enrollment_info: EnrollmentInfoModel | None = Field(
        default=None,
        description="Optional override for CMS-HCC enrollment data (dual status, OREC, institutional).",
    )
    include_cms_hcc: bool = Field(
        default=True,
        description=(
            "If True and cms_hcc_v28 (or v24) is in the models list, also run the "
            "CMS-HCC calculation inline and include it in the multi-model response."
        ),
    )


# ---------------------------------------------------------------------------
# POST /calculate-multi/{pid}
# ---------------------------------------------------------------------------


@router.post(
    "/calculate-multi/{pid}",
    summary="Calculate RAF across multiple models simultaneously",
)
def calculate_multi(
    pid: int,
    body: MultiModelRequest = MultiModelRequest(),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("raf_scores", "read")),
) -> dict[str, Any]:
    """
    Run RAF calculations across multiple models for patient *pid* simultaneously
    and return a unified comparative result.

    **Supported models:**
    - `cms_hcc_v28` — CMS-HCC V28 (Medicare Advantage medical, prospective)
    - `cms_hcc_v24` — CMS-HCC V24 (Medicare Advantage medical, being phased out)
    - `rxhcc` — RxHCC (Medicare Part D drug costs, prospective)
    - `hhs_hcc` — HHS-HCC (ACA Exchange concurrent, includes pharmacy)

    **Response includes:**
    - Per-model risk scores with full HCC breakdowns
    - Score summary table comparing all models side-by-side
    - HCC overlap analysis (which ICD-10 codes map to HCCs in which models)
    - Revenue impact comparison (illustrative estimates per model)
    - Prioritized recommended actions
    - Model descriptions explaining each model's purpose and differences

    **Model differences at a glance:**
    - CMS-HCC and RxHCC are PROSPECTIVE (prior-year dx → next year prediction)
    - HHS-HCC is CONCURRENT (same-year dx → current year score)
    - CMS-HCC is medical-cost focused; RxHCC is drug-cost focused
    - HHS-HCC covers ACA populations (under 65, non-Medicare)
    - Only CMS-HCC and RxHCC apply to Medicare beneficiaries

    Note: CMS-HCC calculation uses the hccinfhir engine when `include_cms_hcc=true`.
    RxHCC and HHS-HCC use internal coefficient tables (representative, not CMS-validated).
    """
    emr_patient = _get_patient(pid, tenant_id=tenant_id)
    if not emr_patient:
        raise HTTPException(status_code=404, detail=f"Patient {pid} not found")

    calc_year = body.year or date.today().year

    dob = emr_patient.get("DOB") or emr_patient.get("dob")
    sex_raw = emr_patient.get("sex") or emr_patient.get("gender") or "M"

    try:
        age = _calculate_age(dob, as_of_year=calc_year)
    except Exception:
        age = 65  # Safe fallback; log and continue
        logger.warning("Could not parse DOB for pid=%s, defaulting age=65", pid)

    sex = _sex_code(sex_raw)

    # Gather ICD-10 codes
    try:
        icd_codes = _get_icd_codes(pid)
    except Exception as exc:
        logger.error("multi_model icd fetch error pid=%s: %s", pid, exc)
        icd_codes = []

    # Optionally run CMS-HCC inline
    cms_hcc_result: dict[str, Any] | None = None
    if body.include_cms_hcc and any(
        m in body.models for m in ("cms_hcc_v24", "cms_hcc_v28")
    ):
        try:
            model_version = (
                "v24"
                if "cms_hcc_v24" in body.models and "cms_hcc_v28" not in body.models
                else "auto"
            )
            enrollment_override = (
                body.enrollment_info.model_dump() if body.enrollment_info else None
            )
            cms_hcc_result = calculate_raf_score(
                patient_id=pid,
                measurement_year=calc_year,
                enrollment_override=enrollment_override,
                model_version=model_version,
                tenant_id=tenant_id,
            )
        except Exception as exc:
            logger.error(
                "cms_hcc inline calc error pid=%s: %s", pid, exc, exc_info=True
            )
            cms_hcc_result = {
                "error": "Calculation failed",
                "cms_hcc_score": None,
                "hcc_list": [],
            }

    try:
        multi_result = calculate_multi_model(
            patient_id=pid,
            icd_codes=icd_codes,
            age=age,
            sex=sex,
            models=body.models,
            payment_year=calc_year,
            low_income_subsidy=body.low_income_subsidy,
            metal_level=body.metal_level,
            cms_hcc_result=cms_hcc_result,
        )
    except ValueError as exc:
        logger.error("Unexpected error: %s", exc)
        raise HTTPException(status_code=422, detail="Invalid input")
    except Exception as exc:
        logger.error("calculate_multi error pid=%s: %s", pid, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

    patient_name = f"{patient.get('fname', '')} {patient.get('lname', '')}".strip()
    multi_result["patient_name"] = patient_name
    multi_result["patient_age"] = age
    multi_result["patient_sex"] = sex

    return multi_result


# ---------------------------------------------------------------------------
# GET /scores/{pid}/multi-model
# ---------------------------------------------------------------------------


@router.get(
    "/scores/{pid}/multi-model",
    summary="Compare stored CMS-HCC scores alongside RxHCC and HHS-HCC",
)
def get_multi_model_scores(
    pid: int,
    year: int | None = Query(default=None),
    models: list[str] = Query(
        default=["cms_hcc_v28", "rxhcc", "hhs_hcc"],
        description="Models to include. Options: cms_hcc_v24, cms_hcc_v28, rxhcc, hhs_hcc.",
    ),
    low_income_subsidy: bool = Query(
        default=False,
        description="RxHCC: True if patient has Low Income Subsidy for Part D.",
    ),
    metal_level: str = Query(
        default="silver",
        description="HHS-HCC: ACA plan metal tier.",
    ),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("raf_scores", "read")),
) -> dict[str, Any]:
    """
    Retrieve the stored CMS-HCC score for *pid* / *year* and compute RxHCC
    and HHS-HCC scores from the patient's current ICD-10 codes to produce a
    unified multi-model comparison view.

    This endpoint is read-only and does not persist any scores. It is designed
    for dashboard use where you want to show a patient's risk profile across
    all applicable models simultaneously.

    **CMS-HCC**: pulled from the raf_scores database (requires prior calculation).
    **RxHCC**: calculated live from current ICD-10 codes.
    **HHS-HCC**: calculated live from current ICD-10 codes.

    Returns the same structure as POST /api/raf/calculate-multi/{pid} but uses
    the stored CMS-HCC score rather than recalculating it.
    """
    calc_year = year or date.today().year

    # Get stored CMS-HCC score from DB
    stored_cms: dict[str, Any] | None = None
    _sf2, _sp2 = active_patients_subquery(int(tenant_id))
    try:
        with raf_cursor() as cur:
            cur.execute(
                f"""
                SELECT
                    patient_id, measurement_year, score_type, model_segment,
                    demographic_score, disease_score, interaction_score,
                    total_raw, final_raf, hcc_count, calculated_at
                FROM raf_scores
                WHERE patient_id = %s AND measurement_year = %s
                  AND {_sf2}
                  AND raf_scores.tenant_id = %s
                ORDER BY calculated_at DESC
                LIMIT 1
                """,
                (pid, calc_year, *_sp2, int(tenant_id)),
            )
            row = cur.fetchone()

        if row:
            stored_cms = {
                "model": "cms_hcc",
                "model_version": row.get("score_type", "v28"),
                "raf_score": float(row["final_raf"]),
                "cms_hcc_score": float(row["final_raf"]),
                "demographic_score": float(row.get("demographic_score") or 0),
                "disease_score": float(row.get("disease_score") or 0),
                "interaction_score": float(row.get("interaction_score") or 0),
                "hcc_count": row.get("hcc_count", 0),
                "model_segment": row.get("model_segment", "CNA"),
                "measurement_year": row["measurement_year"],
                "calculated_at": str(row.get("calculated_at", "")),
                "hcc_list": [],  # HCC list not stored at score level — use breakdown endpoint
                "source": "stored_raf_scores",
            }
        else:
            stored_cms = {
                "model": "cms_hcc",
                "cms_hcc_score": None,
                "raf_score": None,
                "hcc_list": [],
                "note": (
                    f"No stored CMS-HCC score for patient {pid} / year {calc_year}. "
                    "Run POST /api/raf/calculate/{pid} first."
                ),
            }
    except Exception as exc:
        logger.error("multi_model db error pid=%s: %s", pid, exc, exc_info=True)
        stored_cms = {
            "model": "cms_hcc",
            "cms_hcc_score": None,
            "raf_score": None,
            "hcc_list": [],
            "error": "Calculation failed",
        }

    # Get patient data and ICD codes for live RxHCC / HHS-HCC calculations
    emr_patient = _get_patient(pid, tenant_id=tenant_id)
    if not emr_patient:
        raise HTTPException(status_code=404, detail=f"Patient {pid} not found")

    dob = emr_patient.get("DOB") or emr_patient.get("dob")
    sex_raw = emr_patient.get("sex") or emr_patient.get("gender") or "M"

    try:
        age = _calculate_age(dob, as_of_year=calc_year)
    except Exception:
        age = 65
        logger.warning("Could not parse DOB for pid=%s, defaulting age=65", pid)

    sex = _sex_code(sex_raw)

    try:
        icd_codes = _get_icd_codes(pid)
    except Exception as exc:
        logger.error("multi_model icd fetch error pid=%s: %s", pid, exc)
        icd_codes = []

    try:
        multi_result = calculate_multi_model(
            patient_id=pid,
            icd_codes=icd_codes,
            age=age,
            sex=sex,
            models=models,
            payment_year=calc_year,
            low_income_subsidy=low_income_subsidy,
            metal_level=metal_level,
            cms_hcc_result=stored_cms,
        )
    except ValueError as exc:
        logger.error("Unexpected error: %s", exc)
        raise HTTPException(status_code=422, detail="Invalid input")
    except Exception as exc:
        logger.error("multi_model calc error pid=%s: %s", pid, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

    patient_name = f"{patient.get('fname', '')} {patient.get('lname', '')}".strip()
    v24_w, v28_w = _BLEND_WEIGHTS.get(calc_year, (0.0, 1.0))

    multi_result["patient_name"] = patient_name
    multi_result["patient_age"] = age
    multi_result["patient_sex"] = sex
    multi_result["cms_blend_weights"] = {"v24": round(v24_w, 4), "v28": round(v28_w, 4)}
    multi_result["cms_hcc_data_source"] = (
        "stored_raf_scores"
        if stored_cms.get("cms_hcc_score") is not None
        else "not_available"
    )

    return multi_result


# ---------------------------------------------------------------------------
# Full RAF calculation (demographic + HCCs + interactions + normalization)
# ---------------------------------------------------------------------------

# CMS MACI (MA Coding Intensity Adjustment) — statutory minimum 5.9%
_CMS_MACI = 0.059
_CMS_BASE_RATE_PER_RAF = 11015.00

# Risk factor label → hccinfhir prefix_override
_RISK_FACTOR_PREFIX = {
    "Community NonDual Aged": "CNA_",
    "Community NonDual Disabled": "CND_",
    "Community FBDual Aged": "CFA_",
    "Community FBDual Disabled": "CFD_",
    "Community PBDual Aged": "CPA_",
    "Community PBDual Disabled": "CPD_",
    "Institutional Not-Disabled": "INS_",
    "Institutional Disabled": "INS_",
}

# model key → (hccinfhir model_name, coefficients_filename, is_new_enrollee, is_snp, norm_factor)
# Norm factors reflect the CMS Rate Announcement for each payment year
_MODEL_CONFIG: dict[str, dict] = {
    # ----- V28 -----
    "v28-ce-2026": {
        "model_name": "CMS-HCC Model V28",
        "coef_file": "ra_coefficients_2026.csv",
        "new_enrollee": False,
        "snp": False,
        "norm_factor": 1.199,
    },
    "v28-ne-2026": {
        "model_name": "CMS-HCC Model V28",
        "coef_file": "ra_coefficients_2026.csv",
        "new_enrollee": True,
        "snp": False,
        "norm_factor": 1.199,
    },
    "v28-csnp-2026": {
        "model_name": "CMS-HCC Model V28",
        "coef_file": "ra_coefficients_2026.csv",
        "new_enrollee": False,
        "snp": True,
        "norm_factor": 1.199,
    },
    "v28-ce-2025": {
        "model_name": "CMS-HCC Model V28",
        "coef_file": "ra_coefficients_2025.csv",
        "new_enrollee": False,
        "snp": False,
        "norm_factor": 1.153,
    },
    "v28-ne-2025": {
        "model_name": "CMS-HCC Model V28",
        "coef_file": "ra_coefficients_2025.csv",
        "new_enrollee": True,
        "snp": False,
        "norm_factor": 1.153,
    },
    "v28-csnp-2025": {
        "model_name": "CMS-HCC Model V28",
        "coef_file": "ra_coefficients_2025.csv",
        "new_enrollee": False,
        "snp": True,
        "norm_factor": 1.153,
    },
    "v28-ce-2027p": {
        "model_name": "CMS-HCC Model V28",
        "coef_file": "ra_proposed_coefficients_2027.csv",
        "new_enrollee": False,
        "snp": False,
        "norm_factor": 1.229,
    },
    # ----- V24 -----
    "v24-ce-2026": {
        "model_name": "CMS-HCC Model V24",
        "coef_file": "ra_coefficients_2026.csv",
        "new_enrollee": False,
        "snp": False,
        "norm_factor": 1.146,
    },
    "v24-ne-2026": {
        "model_name": "CMS-HCC Model V24",
        "coef_file": "ra_coefficients_2026.csv",
        "new_enrollee": True,
        "snp": False,
        "norm_factor": 1.146,
    },
    "v24-csnp-2026": {
        "model_name": "CMS-HCC Model V24",
        "coef_file": "ra_coefficients_2026.csv",
        "new_enrollee": False,
        "snp": True,
        "norm_factor": 1.146,
    },
    "v24-ce-2025": {
        "model_name": "CMS-HCC Model V24",
        "coef_file": "ra_coefficients_2025.csv",
        "new_enrollee": False,
        "snp": False,
        "norm_factor": 1.097,
    },
    "v24-ne-2025": {
        "model_name": "CMS-HCC Model V24",
        "coef_file": "ra_coefficients_2025.csv",
        "new_enrollee": True,
        "snp": False,
        "norm_factor": 1.097,
    },
}

# Legacy aliases so older clients still work
_MODEL_CONFIG["v28-ce"] = _MODEL_CONFIG["v28-ce-2026"]
_MODEL_CONFIG["v28-ne"] = _MODEL_CONFIG["v28-ne-2026"]
_MODEL_CONFIG["v24-ce"] = _MODEL_CONFIG["v24-ce-2026"]


@router.post("/calculate", summary="Full RAF score calculation via hccinfhir")
def calculate_raf_full(
    body: dict = Body(...),
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Full RAF calculation using the hccinfhir library.

    Accepts:
        codes:        list[str]  ICD-10 diagnosis codes
        age:          int
        gender:       "Male" | "Female"
        risk_factor:  one of the CMS risk factor labels
        model:        "v28-ce" | "v24-ce" | "v28-ne"
        norm_factor:  optional float (defaults to CMS 2026 published value)
        maci:         optional float (defaults to 0.059)

    Returns demographic coefficient, HCC details with coefficients,
    disease interactions, grand total, normalized, and MA-CP adjusted.
    """
    codes_raw = body.get("codes") or []
    age = int(body.get("age") or 65)
    gender = str(body.get("gender") or "Male")
    risk_factor = str(body.get("risk_factor") or "Community NonDual Aged")
    model_key = str(body.get("model") or "v28-ce-2026")
    cfg = _MODEL_CONFIG.get(model_key) or _MODEL_CONFIG["v28-ce-2026"]
    model_name = cfg["model_name"]
    coef_file = cfg["coef_file"]
    is_new_enrollee = cfg["new_enrollee"]
    is_snp = cfg["snp"]

    norm_factor = float(body.get("norm_factor") or cfg["norm_factor"])
    maci = float(body.get("maci") or _CMS_MACI)

    codes = [c.strip().upper().replace(".", "") for c in codes_raw if c and str(c).strip()]

    try:
        from hccinfhir.hccinfhir import HCCInFHIR
        from hccinfhir.datamodels import Demographics
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"hccinfhir not available: {exc}")

    sex = "M" if gender.lower().startswith("m") else "F"

    # Map risk factor → Demographics flags so hccinfhir picks the right category
    fbd = "FBDual" in risk_factor
    pbd = "PBDual" in risk_factor
    institutional = "Institutional" in risk_factor
    disabled = "Disabled" in risk_factor and "NonDual" not in risk_factor
    low_income = fbd or pbd

    try:
        demo = Demographics(
            age=age,
            sex=sex,
            dual_elgbl_cd="02" if fbd else ("03" if pbd else "NA"),
            orec="1" if disabled else "0",
            crec="0",
            new_enrollee=is_new_enrollee,
            snp=is_snp,
            low_income=low_income,
            lti=institutional,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid demographics: {exc}")

    try:
        h = HCCInFHIR(model_name=model_name, coefficients_filename=coef_file)
        # For Continuing Enrollee we let the user's risk factor drive the prefix.
        # For New Enrollee / C-SNP the prefix must come from demographics flags,
        # so hccinfhir picks NE_ / SNPNE_ / etc automatically.
        prefix = None
        if not is_new_enrollee and not is_snp:
            prefix = _RISK_FACTOR_PREFIX.get(risk_factor)
        result = h.calculate_from_diagnosis(
            codes or ["__NONE__"],
            demographics=demo,
            prefix_override=prefix,
            maci=maci,
            norm_factor=norm_factor,
        )
        r = result.model_dump()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"RAF calculation failed: {exc}")

    # Separate HCC coefficients from disease interaction coefficients
    all_coefs: dict = r.get("coefficients") or {}
    hcc_codes_set = {str(hcc) for hcc in (r.get("hcc_list") or [])}
    demo_category = (r.get("demographics") or {}).get("category") or ""

    interactions: list[dict] = []
    for key, coef in all_coefs.items():
        if coef == 0:
            continue
        if str(key) in hcc_codes_set:
            continue
        if str(key) == demo_category:
            continue
        interactions.append({"name": str(key), "coefficient": float(coef)})

    # Enrich HCC details with dx codes that triggered each HCC
    cc_to_dx = r.get("cc_to_dx") or {}
    hcc_details = []
    for h_det in (r.get("hcc_details") or []):
        hcc_id = str(h_det.get("hcc"))
        dx_set = cc_to_dx.get(hcc_id) or set()
        if isinstance(dx_set, set):
            dx_set = sorted(dx_set)
        hcc_details.append(
            {
                "hcc": hcc_id,
                "label": h_det.get("label"),
                "coefficient": float(h_det.get("coefficient") or 0),
                "is_chronic": bool(h_det.get("is_chronic")),
                "diagnosis_codes": list(dx_set),
            }
        )

    # Identify which submitted codes did not map to any HCC
    mapped_dxs: set[str] = set()
    for dxs in cc_to_dx.values():
        if isinstance(dxs, (set, list, tuple)):
            mapped_dxs.update(str(d).upper() for d in dxs)
    unmapped = [c for c in codes if c.upper() not in mapped_dxs]

    risk_score = float(r.get("risk_score") or 0)
    risk_score_demographics = float(r.get("risk_score_demographics") or 0)
    risk_score_payment = float(r.get("risk_score_payment") or 0)

    # Derive normalized and MA-CP-adjusted
    normalized = round(risk_score / norm_factor, 4) if norm_factor else risk_score
    ma_cp_adjusted = round(normalized * (1 - maci), 4)

    return {
        "model": model_name,
        "risk_factor": risk_factor,
        "prefix": prefix,
        "age": age,
        "gender": gender,
        "norm_factor": norm_factor,
        "maci": maci,
        "base_rate": _CMS_BASE_RATE_PER_RAF,
        "coefficient_source": coef_file,
        "demographic": {
            "category": demo_category,
            "coefficient": risk_score_demographics,
        },
        "hcc_details": hcc_details,
        "interactions": interactions,
        "unmapped_codes": unmapped,
        "totals": {
            "hcc_sum": round(risk_score - risk_score_demographics, 4),
            "grand_total": round(risk_score, 4),
            "normalized": normalized,
            "ma_cp_adjusted": ma_cp_adjusted,
            "risk_score_payment": risk_score_payment,
        },
    }


# ---------------------------------------------------------------------------
# ICD-10 to HCC Crosswalk Lookup
# ---------------------------------------------------------------------------


@router.post("/crosswalk", summary="ICD-10 to HCC crosswalk lookup")
def icd10_to_hcc_crosswalk(
    body: dict = Body(...),
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Look up HCC mappings for a list of ICD-10 codes using hccinfhir library and DB crosswalk."""
    codes = body.get("codes", [])
    if not codes:
        return {"results": []}

    # Clean codes - strip dots, uppercase
    clean_codes = []
    for c in codes:
        c = c.strip().upper()
        if c:
            clean_codes.append(c)

    if not clean_codes:
        return {"results": []}

    results = []

    # Use hccinfhir apply_mapping for batch V24/V28/RxHCC lookups
    v28_map: dict[str, set[str]] = {}
    v24_map: dict[str, set[str]] = {}
    rx_map: dict[str, set[str]] = {}
    labels: dict = {}
    coefs: dict = {}
    chronic: dict = {}
    try:
        from hccinfhir.defaults import (
            dx_to_cc_default,
            labels_default,
            coefficients_default,
            is_chronic_default,
        )
        from hccinfhir.model_dx_to_cc import apply_mapping

        labels = labels_default
        coefs = coefficients_default
        chronic = is_chronic_default

        nodot_codes = [c.replace(".", "") for c in clean_codes]
        v28_raw = apply_mapping(nodot_codes, "CMS-HCC Model V28", dx_to_cc_default)
        v24_raw = apply_mapping(nodot_codes, "CMS-HCC Model V24", dx_to_cc_default)
        rx_raw = apply_mapping(nodot_codes, "RxHCC Model V08", dx_to_cc_default)
        for hcc, dxs in v28_raw.items():
            for dx in dxs:
                v28_map.setdefault(dx.upper(), set()).add(hcc)
        for hcc, dxs in v24_raw.items():
            for dx in dxs:
                v24_map.setdefault(dx.upper(), set()).add(hcc)
        for hcc, dxs in rx_raw.items():
            for dx in dxs:
                rx_map.setdefault(dx.upper(), set()).add(hcc)
    except Exception:
        pass

    # DB crosswalk for richer ICD descriptions
    db_map: dict[str, dict] = {}
    try:
        all_variants = list(clean_codes)
        for c in clean_codes:
            if len(c) > 3 and "." not in c and c[0].isalpha():
                all_variants.append(c[:3] + "." + c[3:])
        placeholders = ",".join(["%s"] * len(all_variants))
        with raf_cursor() as cur:
            cur.execute(
                f"SELECT icd10_code, icd10_description, hcc_code, hcc_label "
                f"FROM hcc_icd10_crosswalk "
                f"WHERE REPLACE(icd10_code, '.', '') IN ({placeholders}) "
                f"OR icd10_code IN ({placeholders})",
                all_variants + all_variants,
            )
            for row in cur.fetchall():
                key = row["icd10_code"].replace(".", "").upper()
                db_map[key] = {
                    "hcc_v28": row["hcc_code"],
                    "hcc_label": row["hcc_label"],
                    "icd_description": row.get("icd10_description") or "",
                }
    except Exception:
        pass

    def _hcc_detail(hcc_code: str | None, model: str, seg_key: str) -> dict | None:
        """Look up label + CNA coefficient + chronic flag for an HCC code."""
        if not hcc_code:
            return None
        hcc_str = str(hcc_code)
        label = labels.get((hcc_str, model)) if labels else None
        coef = coefs.get((seg_key, model)) if coefs else None
        is_chr = bool(chronic.get((hcc_str, model))) if chronic else False
        return {
            "code": hcc_str,
            "label": label or "",
            "coefficient": float(coef) if coef is not None else None,
            "is_chronic": is_chr,
        }

    for i, code in enumerate(clean_codes):
        code_nodot = code.replace(".", "").upper()
        code_dot = (
            code
            if "." in code
            else (code[:3] + "." + code[3:] if len(code) > 3 and code[0].isalpha() else code)
        )

        v28_hccs = sorted(v28_map.get(code_nodot, set()), key=lambda x: int(x) if x.isdigit() else 9999)
        v24_hccs = sorted(v24_map.get(code_nodot, set()), key=lambda x: int(x) if x.isdigit() else 9999)
        rx_hccs = sorted(rx_map.get(code_nodot, set()), key=lambda x: int(x) if x.isdigit() else 9999)

        v28_hcc = v28_hccs[0] if v28_hccs else None
        v24_hcc = v24_hccs[0] if v24_hccs else None
        rx_hcc = rx_hccs[0] if rx_hccs else None

        description = ""
        db_entry = db_map.get(code_nodot)
        if db_entry:
            description = db_entry.get("icd_description") or db_entry.get("hcc_label") or ""
            if not v28_hcc and db_entry.get("hcc_v28"):
                v28_hcc = str(db_entry["hcc_v28"])

        v28_detail = _hcc_detail(v28_hcc, "CMS-HCC Model V28", f"cna_hcc{v28_hcc}" if v28_hcc else "")
        v24_detail = _hcc_detail(v24_hcc, "CMS-HCC Model V24", f"cna_hcc{v24_hcc}" if v24_hcc else "")
        rx_detail = None
        if rx_hcc:
            rx_label = (
                labels.get((f"RX{rx_hcc}", "RxHCC Model R08"))
                or labels.get((f"RX{rx_hcc}", "RxHCC Model R05"))
                or ""
            )
            rx_coef = coefs.get((f"rx_ce_nolownoaged_rxhcc{rx_hcc}", "RxHCC Model V08"))
            rx_detail = {
                "code": rx_hcc,
                "label": rx_label,
                "coefficient": float(rx_coef) if rx_coef is not None else None,
                "is_chronic": False,
            }

        v28_coef = (v28_detail or {}).get("coefficient") or 0.0
        v24_coef = (v24_detail or {}).get("coefficient") or 0.0
        delta = round(v28_coef - v24_coef, 4)

        results.append({
            "sno": i + 1,
            "icd10_code": code_dot,
            "description": description,
            "cms_hcc_v24": v24_hcc,
            "cms_hcc_v24_label": (v24_detail or {}).get("label", ""),
            "cms_hcc_v24_coefficient": (v24_detail or {}).get("coefficient"),
            "cms_hcc_v28": v28_hcc,
            "cms_hcc_v28_label": (v28_detail or {}).get("label", ""),
            "cms_hcc_v28_coefficient": (v28_detail or {}).get("coefficient"),
            "rxhcc": rx_hcc,
            "rxhcc_label": (rx_detail or {}).get("label", ""),
            "rxhcc_coefficient": (rx_detail or {}).get("coefficient"),
            "is_chronic": (v28_detail or {}).get("is_chronic") or (v24_detail or {}).get("is_chronic") or False,
            "delta_v28_v24": delta,
            "risk_adjusting": bool(v28_hcc or v24_hcc),
        })

    # Summary stats
    total_v24 = round(sum((r["cms_hcc_v24_coefficient"] or 0) for r in results), 4)
    total_v28 = round(sum((r["cms_hcc_v28_coefficient"] or 0) for r in results), 4)
    total_rx = round(sum((r["rxhcc_coefficient"] or 0) for r in results), 4)
    mapped_count = sum(1 for r in results if r["risk_adjusting"])

    return {
        "results": results,
        "summary": {
            "total_codes": len(results),
            "risk_adjusting_count": mapped_count,
            "not_risk_adjusting_count": len(results) - mapped_count,
            "total_v24_coefficient": total_v24,
            "total_v28_coefficient": total_v28,
            "total_rxhcc_coefficient": total_rx,
            "delta_v28_v24": round(total_v28 - total_v24, 4),
        },
    }


# ---------------------------------------------------------------------------
# GET /dashboard  — population-level RAF dashboard summary
# ---------------------------------------------------------------------------


@router.get("/dashboard", summary="RAF dashboard — population-level summary for the current year")
def get_raf_dashboard(
    year: int | None = Query(default=None),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("raf_scores", "read")),
) -> dict[str, Any]:
    """
    Return a combined RAF dashboard payload:

    - ``population``: total patients, scored patients, average/median RAF for the year
    - ``top_hccs``: the 10 most frequently occurring HCCs across all patients
    - ``recent_calculations``: the 10 most recently calculated RAF scores
    - ``blend_weights``: CMS V24/V28 blend weights for the requested year
    - ``measurement_year``: the year used for all calculations
    """
    calc_year = year or date.today().year
    _tid = int(tenant_id)
    _sf, _sp = active_patients_subquery(_tid)

    dashboard: dict[str, Any] = {"measurement_year": calc_year}

    # Blend weights
    dashboard["blend_weights"] = _BLEND_WEIGHTS.get(
        calc_year, _BLEND_WEIGHTS.get(max(_BLEND_WEIGHTS.keys()), {"v24": 0.0, "v28": 1.0})
    )

    # Population totals
    try:
        with raf_cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS cnt FROM patients WHERE is_active = 1 AND tenant_id = %s",
                (_tid,),
            )
            total_patients = (cur.fetchone() or {}).get("cnt", 0)

            cur.execute(
                f"""
                SELECT
                    COUNT(DISTINCT rs.patient_id) AS scored,
                    AVG(rs.final_raf) AS avg_raf,
                    SUM(rs.final_raf) AS sum_raf
                FROM raf_scores rs
                WHERE rs.measurement_year = %s
                  AND {_sf}
                  AND rs.tenant_id = %s
                """,
                (calc_year, *_sp, _tid),
            )
            pop_row = cur.fetchone() or {}
            scored_patients = int(pop_row.get("scored") or 0)
            avg_raf = round(float(pop_row.get("avg_raf") or 0), 4)

        dashboard["population"] = {
            "total_patients": total_patients,
            "scored_patients": scored_patients,
            "unscored_patients": max(0, total_patients - scored_patients),
            "average_raf": avg_raf,
        }
    except Exception as exc:
        logger.error("get_raf_dashboard population error: %s", exc, exc_info=True)
        dashboard["population"] = {"error": "Failed to load population stats"}

    # Top 10 HCCs by frequency — query raf_patient_hcc directly without
    # requiring a matching raf_scores row (the inner join was silently
    # excluding patients whose HCC records exist but whose score rows have
    # a different patient_id due to FHIR/upload ID migration).
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT hcc_code, hcc_description,
                       COUNT(DISTINCT patient_id) AS patient_count,
                       AVG(raf_coefficient) AS avg_coefficient
                FROM raf_patient_hcc
                WHERE measurement_year = %s
                  AND tenant_id = %s
                GROUP BY hcc_code, hcc_description
                ORDER BY patient_count DESC
                LIMIT 10
                """,
                (calc_year, _tid),
            )
            hcc_rows = cur.fetchall() or []
        dashboard["top_hccs"] = [
            {
                "hcc_code": r["hcc_code"],
                "hcc_label": r.get("hcc_description") or "",
                "patient_count": int(r["patient_count"]),
                "avg_coefficient": round(float(r.get("avg_coefficient") or 0), 4),
            }
            for r in hcc_rows
        ]
    except Exception as exc:
        logger.error("get_raf_dashboard top_hccs error: %s", exc, exc_info=True)
        dashboard["top_hccs"] = []

    # 10 most recently calculated scores
    try:
        with raf_cursor() as cur:
            cur.execute(
                f"""
                SELECT rs.patient_id, rs.measurement_year, rs.final_raf,
                       rs.score_type, rs.model_segment, rs.calculated_at,
                       p.first_name, p.last_name
                FROM raf_scores rs
                LEFT JOIN patients p ON p.id = rs.patient_id AND p.tenant_id = rs.tenant_id
                WHERE rs.measurement_year = %s
                  AND {_sf}
                  AND rs.tenant_id = %s
                ORDER BY rs.calculated_at DESC
                LIMIT 10
                """,
                (calc_year, *_sp, _tid),
            )
            recent_rows = cur.fetchall() or []
        dashboard["recent_calculations"] = [
            {
                "patient_id": r["patient_id"],
                "patient_name": f"{r.get('first_name') or ''} {r.get('last_name') or ''}".strip(),
                "measurement_year": r["measurement_year"],
                "final_raf": round(float(r["final_raf"]), 4),
                "score_type": r.get("score_type", "v28"),
                "model_segment": r.get("model_segment", ""),
                "calculated_at": str(r.get("calculated_at", "")),
            }
            for r in recent_rows
        ]
    except Exception as exc:
        logger.error("get_raf_dashboard recent error: %s", exc, exc_info=True)
        dashboard["recent_calculations"] = []

    return dashboard
