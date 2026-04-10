"""
Patient router.

GET /api/patients                              - paginated patient list from OpenEMR
GET /api/patients/{pid}                        - single patient with latest RAF score
GET /api/patients/{pid}/encounters             - encounter history
GET /api/patients/{pid}/medications            - active prescriptions (includes diagnosis field)
GET /api/patients/{pid}/medication-gaps        - medication-linked diagnoses not billed this year
GET /api/patients/{pid}/diagnoses              - ICD-10 billing codes
GET /api/patients/{pid}/procedures             - CPT procedure codes with condition hints
GET /api/patients/{pid}/lab-suspects           - rule-based lab/vitals suspect conditions
GET /api/patients/{pid}/comprehensive-profile  - aggregated full patient picture for RAF analysis
"""
from __future__ import annotations

import logging
from datetime import date as _date
from datetime import datetime as _datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.services import openemr_connector as emr
from app.services.audit_logger import log_phi_access
from app.services.raf_calculator import get_raf_breakdown

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/patients", tags=["patients"])


# ---------------------------------------------------------------------------
# Patient list
# ---------------------------------------------------------------------------

@router.get("", summary="List all patients")
def list_patients(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    search: str = Query("", description="Search by name or PID"),
) -> dict[str, Any]:
    """
    Return a paginated list of patients from OpenEMR's patient_data table.
    Supports server-side search by name or PID across all 20K+ patients.
    """
    try:
        if search.strip():
            patients, total = emr.search_patients(search.strip(), limit=limit, offset=offset)
        else:
            patients = emr.get_patients(limit=limit, offset=offset)
            total = emr.get_patient_count()
    except Exception as exc:
        logger.error("list_patients error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    log_phi_access(
        action="list",
        resource="patient",
        details=f"limit={limit} offset={offset} search={search!r} returned={len(patients)}",
    )
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "search": search,
        "patients": patients,
    }


# ---------------------------------------------------------------------------
# Patients with encounters (for pipeline demo)
# ---------------------------------------------------------------------------

@router.get("/with-encounters", summary="Patients that have encounter data")
def patients_with_encounters(
    limit: int = Query(200, ge=1, le=500),
) -> dict[str, Any]:
    """Return only patients that have at least one encounter."""
    try:
        patients = emr.get_patients_with_encounters(limit=limit)
    except Exception as exc:
        logger.error("patients_with_encounters error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    return {"total": len(patients), "patients": patients}


# ---------------------------------------------------------------------------
# Single patient
# ---------------------------------------------------------------------------

@router.get("/{pid}", summary="Get patient details with RAF score")
def get_patient(pid: int) -> dict[str, Any]:
    """
    Return demographic data for *pid* plus their most recent RAF score.
    """
    patient = emr.get_patient(pid)
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient {pid} not found")

    # Attach latest RAF score if available (check current year first, then prior)
    from datetime import date as _date
    raf_data: dict = {}
    for yr in [_date.today().year, _date.today().year - 1]:
        raf_data = get_raf_breakdown(pid, yr)
        if raf_data:
            break
    patient["raf_score"] = raf_data.get("raf_score")
    patient["raf_score_date"] = raf_data.get("calculated_at")
    patient["raf_score_year"] = raf_data.get("measurement_year")

    log_phi_access(action="view", resource="patient", patient_id=pid)
    return patient


# ---------------------------------------------------------------------------
# Clinical Notes
# ---------------------------------------------------------------------------

@router.get("/{pid}/clinical-notes/{encounter_id}", summary="Get clinical notes for encounter")
def get_clinical_notes_for_encounter(pid: int, encounter_id: int) -> dict[str, Any]:
    """Return clinical notes text for a specific encounter."""
    try:
        notes = emr.get_clinical_notes(encounter_id)
    except Exception as exc:
        logger.error("get_clinical_notes error enc=%s: %s", encounter_id, exc)
        raise HTTPException(status_code=500, detail=str(exc))

    log_phi_access(
        action="view",
        resource="clinical_note",
        patient_id=pid,
        encounter_id=encounter_id,
        details=f"notes_returned={len(notes)}",
    )
    return {
        "pid": pid,
        "encounter_id": encounter_id,
        "count": len(notes),
        "notes": notes,
    }


# ---------------------------------------------------------------------------
# Encounters
# ---------------------------------------------------------------------------

@router.get("/{pid}/encounters", summary="Get patient encounters")
def get_encounters(pid: int) -> dict[str, Any]:
    """
    Return all encounters for *pid* from form_encounter.
    """
    patient = emr.get_patient(pid)
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient {pid} not found")

    try:
        encounters = emr.get_encounters(pid)
    except Exception as exc:
        logger.error("get_encounters error pid=%s: %s", pid, exc)
        raise HTTPException(status_code=500, detail=str(exc))

    log_phi_access(
        action="view",
        resource="encounter",
        patient_id=pid,
        details=f"encounters_returned={len(encounters)}",
    )
    return {
        "pid": pid,
        "count": len(encounters),
        "encounters": encounters,
    }


# ---------------------------------------------------------------------------
# Medications
# ---------------------------------------------------------------------------

@router.get("/{pid}/medications", summary="Get patient medications")
def get_medications(pid: int) -> dict[str, Any]:
    """
    Return all prescriptions for *pid* from the prescriptions table.
    """
    patient = emr.get_patient(pid)
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient {pid} not found")

    try:
        medications = emr.get_medications(pid)
    except Exception as exc:
        logger.error("get_medications error pid=%s: %s", pid, exc)
        raise HTTPException(status_code=500, detail=str(exc))

    return {
        "pid": pid,
        "count": len(medications),
        "medications": medications,
    }


# ---------------------------------------------------------------------------
# Medication-diagnosis gaps
# ---------------------------------------------------------------------------

@router.get("/{pid}/medication-gaps", summary="Medication-linked diagnoses not billed this year")
def get_medication_gaps(
    pid: int,
    year: int = Query(0, ge=0, description="Calendar year to check (defaults to current year)"),
) -> dict[str, Any]:
    """
    Return active medications whose linked ICD-10 diagnosis has not been
    billed in *year* (defaults to the current calendar year).

    Each prescription in OpenEMR carries a ``diagnosis`` field containing the
    ICD-10 code(s) the medication was prescribed for.  This endpoint surfaces
    cases where an active medication implies an ongoing condition that has not
    yet been substantiated by a claim in the target year — a direct RAF
    recapture opportunity.

    The ``diagnosis`` field is parsed robustly: single codes, semicolon-
    separated lists, codes embedded in free text, and prefixed values (e.g.
    ``ICD10:E11.9``) are all handled.

    Response shape
    --------------
    ``gaps``     - list of gap items, each with:
                     icd_code   - the ICD-10 code from the prescription
                     drug       - the medication name
                     active     - always 1 (only active Rx are considered)
                     description - human-readable ICD-10 description (if known)
                     valid_icd10 - whether the code passes ICD-10-CM validation
    ``year``     - the calendar year checked
    ``gap_count``- number of distinct (icd_code, drug) pairs returned
    """
    from datetime import date as _date

    from app.services.icd_validator import get_description, validate_code

    if year == 0:
        year = _date.today().year

    patient = emr.get_patient(pid)
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient {pid} not found")

    try:
        gaps = emr.get_medication_diagnosis_gaps(pid, year)
    except Exception as exc:
        logger.error("get_medication_gaps error pid=%s year=%s: %s", pid, year, exc)
        raise HTTPException(status_code=500, detail=str(exc))

    # Enrich each gap with a human-readable ICD-10 description.
    for gap in gaps:
        code = gap.get("icd_code", "")
        if code:
            gap["description"] = get_description(code) or ""
            gap["valid_icd10"] = validate_code(code)

    return {
        "pid": pid,
        "year": year,
        "gap_count": len(gaps),
        "gaps": gaps,
    }


# ---------------------------------------------------------------------------
# Diagnoses (billing ICD-10 codes)
# ---------------------------------------------------------------------------

@router.get("/{pid}/diagnoses", summary="Get patient billing ICD-10 codes")
def get_diagnoses(pid: int) -> dict[str, Any]:
    """
    Return all ICD-10 billing codes for *pid* from the billing table,
    enriched with code descriptions via the ICD-10-CM index.
    """
    from app.services.icd_validator import get_description, validate_code

    patient = emr.get_patient(pid)
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient {pid} not found")

    try:
        codes = emr.get_billing_codes(pid)
    except Exception as exc:
        logger.error("get_diagnoses error pid=%s: %s", pid, exc)
        raise HTTPException(status_code=500, detail=str(exc))

    # Enrich with ICD-10-CM descriptions
    for row in codes:
        code = row.get("code", "")
        if code:
            row["description"] = get_description(code) or row.get("code_text", "")
            row["valid_icd10"] = validate_code(code)

    log_phi_access(
        action="view",
        resource="diagnosis",
        patient_id=pid,
        details=f"codes_returned={len(codes)}",
    )
    return {
        "pid": pid,
        "count": len(codes),
        "diagnoses": codes,
    }


# ---------------------------------------------------------------------------
# Procedures (CPT codes with condition hints)
# ---------------------------------------------------------------------------

@router.get("/{pid}/procedures", summary="Get patient CPT procedure codes with condition hints")
def get_procedures(pid: int) -> dict[str, Any]:
    """
    Return all active CPT4 procedure codes for *pid* from the billing table.

    Each row is enriched with a ``condition_hint`` block when the CPT code
    appears in CPT_CONDITION_HINTS.  The hint carries:
      - condition  : plain-English condition name
      - icd10      : representative ICD-10 code (None when ambiguous)
      - hcc        : primary HCC category (None when ambiguous)

    Codes without a hint entry are returned as-is with ``condition_hint: null``
    so callers can distinguish known-hint vs unknown without filtering.

    Example response
    ----------------
    {
      "pid": 42,
      "count": 3,
      "procedures": [
        {
          "code": "93306",
          "code_text": "Echo transthorcic",
          "date": "2025-11-01",
          "encounter": "1001",
          "modifier": null,
          "units": 1,
          "fee": 250.0,
          "condition_hint": {
            "condition": "Heart Disease",
            "icd10": "I50.9",
            "hcc": "HCC226"
          }
        },
        ...
      ]
    }
    """
    patient = emr.get_patient(pid)
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient {pid} not found")

    try:
        cpt_rows = emr.get_cpt_codes(pid)
    except Exception as exc:
        logger.error("get_procedures error pid=%s: %s", pid, exc)
        raise HTTPException(status_code=500, detail=str(exc))

    hints = emr.CPT_CONDITION_HINTS
    for row in cpt_rows:
        code = str(row.get("code") or "").strip()
        row["condition_hint"] = hints.get(code)  # None when not in dict

    return {
        "pid": pid,
        "count": len(cpt_rows),
        "procedures": cpt_rows,
    }


# ---------------------------------------------------------------------------
# Problem List
# ---------------------------------------------------------------------------

@router.get("/{pid}/problem-list", summary="Get patient active problem list")
def get_problem_list(pid: int) -> dict[str, Any]:
    """
    Return all active medical problems for *pid* from OpenEMR's lists table.

    Each problem includes:
    - id, title        — row PK and free-text problem name entered by clinician
    - diagnosis        — raw ICD code (may be NULL/empty for title-only entries)
    - begdate/enddate  — onset and resolution dates
    - occurrence       — how often the condition recurs (OpenEMR lookup value)
    - outcome          — clinical outcome code
    - activity         — always 1 (active) for records returned here

    Entries where diagnosis is empty are still returned; the caller should
    treat them as unstructured problems that cannot be matched to HCC codes
    without manual review.
    """
    patient = emr.get_patient(pid)
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient {pid} not found")

    try:
        problems = emr.get_problem_list(pid)
    except Exception as exc:
        logger.error("get_problem_list error pid=%s: %s", pid, exc)
        raise HTTPException(status_code=500, detail=str(exc))

    # Annotate each problem with whether it has a structured ICD code
    for p in problems:
        p["has_icd_code"] = bool(p.get("diagnosis"))

    return {
        "pid": pid,
        "count": len(problems),
        "problems": problems,
    }


# ---------------------------------------------------------------------------
# Recapture Gaps
# ---------------------------------------------------------------------------

@router.get("/{pid}/recapture-gaps", summary="Active problems not billed this year")
def get_recapture_gaps(
    pid: int,
    year: int = Query(
        default=0,
        ge=2000,
        le=2100,
        description="Calendar year to check billing against. Defaults to current year.",
    ),
) -> dict[str, Any]:
    """
    Return active medical problems from the problem list that have NOT been
    substantiated by an ICD-10 billing claim in *year*.

    These represent RAF recapture opportunities: chronic conditions already
    documented in OpenEMR but not re-coded in the current payment year.
    CMS requires annual documentation of HCC-mapped diagnoses for them to
    contribute to the patient's risk score.

    Only problems with a populated diagnosis code are evaluated; title-only
    entries are excluded because they cannot be matched to billing rows.

    Query parameter:
    - year (int, optional): defaults to the current calendar year.
    """
    from datetime import date as _date

    if year == 0:
        year = _date.today().year

    patient = emr.get_patient(pid)
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient {pid} not found")

    try:
        gaps = emr.get_recapture_gaps(pid, year)
    except Exception as exc:
        logger.error("get_recapture_gaps error pid=%s year=%s: %s", pid, year, exc)
        raise HTTPException(status_code=500, detail=str(exc))

    return {
        "pid": pid,
        "year": year,
        "count": len(gaps),
        "recapture_gaps": gaps,
    }


# ---------------------------------------------------------------------------
# Vitals Suspects — rule-based suspect conditions derived from form_vitals
# ---------------------------------------------------------------------------

@router.get("/{pid}/vitals-suspects", summary="Vitals-based suspect conditions")
def get_vitals_suspects(pid: int) -> dict[str, Any]:
    """
    Evaluate the most recent vitals recorded in form_vitals for *pid* against
    a set of clinical threshold rules and return conditions that appear suspect
    but are not already present in the patient's billing or problem-list records.

    Rules applied
    -------------
    - BMI >= 40                  → Morbid Obesity (E66.01 / HCC48)
    - BMI 35-39.9                → Severe Obesity (E66.01 / HCC48)
    - Oxygen saturation < 88 %   → Chronic Respiratory Failure (J96.11 / HCC213)
    - Systolic BP >= 180 mmHg    → Hypertensive Crisis (I16.0)
    - Weight loss >= 10 % trend  → Malnutrition/Cachexia (R63.4)

    Existing diagnoses are sourced from ``get_all_patient_diagnoses``, which
    unions the billing table and active problem list.  A suspect is suppressed
    when its ICD-10 code (dot-stripped) already appears in that union.

    Each returned suspect includes:
        field           — vital field that triggered the rule
        measured_value  — the numeric value observed
        condition       — human-readable condition name
        icd10           — suggested ICD-10 code
        hcc             — HCC category or null
        confidence      — float 0-1
        evidence        — short narrative for display
        vitals_date     — date of the vitals reading used
    """
    patient = emr.get_patient(pid)
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient {pid} not found")

    try:
        all_diagnoses = emr.get_all_patient_diagnoses(pid)
        existing_codes = [d.get("icd_code", "") for d in all_diagnoses]
    except Exception as exc:
        logger.warning("get_vitals_suspects: could not fetch diagnoses pid=%s: %s", pid, exc)
        existing_codes = []

    try:
        suspects = emr.detect_vitals_suspects(pid, existing_diagnoses=existing_codes)
    except Exception as exc:
        logger.error("get_vitals_suspects error pid=%s: %s", pid, exc)
        raise HTTPException(status_code=500, detail=str(exc))

    patient_name = (
        f"{patient.get('fname', '')} {patient.get('lname', '')}".strip()
        or f"Patient {pid}"
    )

    # Sort by confidence descending so highest-confidence suspects appear first
    suspects.sort(key=lambda s: s.get("confidence", 0), reverse=True)

    return {
        "pid": pid,
        "patient_name": patient_name,
        "count": len(suspects),
        "vitals_suspects": suspects,
    }


# ---------------------------------------------------------------------------
# Lab & Vitals Suspects — rule-based, no LLM required
# ---------------------------------------------------------------------------

@router.get("/{pid}/lab-suspects", summary="Rule-based lab/vitals suspect conditions")
def get_lab_suspects(pid: int) -> dict[str, Any]:
    """
    Return suspect HCC conditions derived purely from lab values and vitals
    embedded in clinical notes and structured form_vitals rows.

    This endpoint is SUPPLEMENTARY to the Gemini pipeline.  It runs a
    deterministic regex + threshold engine (``lab_suspect_engine``) and
    returns results immediately without any LLM call, making it fast and
    available even when the full pipeline has not been run for this patient.

    Each suspect includes:
    - ``lab``               – the measurement that triggered the rule (e.g. "HbA1c")
    - ``value``             – extracted numeric value
    - ``threshold``         – the clinical threshold that was breached
    - ``operator``          – comparison direction (">=", "<", etc.)
    - ``condition``         – plain-English condition name
    - ``icd10``             – suggested ICD-10-CM code
    - ``hcc``               – HCC category label (null if not HCC-relevant)
    - ``source``            – "clinical_note" | "vitals"
    - ``confidence_score``  – heuristic 0.0–1.0 score
    - ``evidence_detail``   – dict with raw match context

    Suspects already present in the patient's billing record (matched by
    ICD-10 category prefix) are automatically excluded.

    Example response
    ----------------
    ::

        {
          "pid": 42,
          "notes_scanned": 7,
          "vitals_rows_checked": 3,
          "existing_diagnosis_count": 12,
          "note_suspects_count": 2,
          "vitals_suspects_count": 1,
          "total_suspects": 3,
          "suspects": [
            {
              "lab": "HbA1c",
              "value": 7.2,
              "threshold": 6.5,
              "operator": ">=",
              "condition": "Type 2 Diabetes",
              "icd10": "E11.65",
              "hcc": "HCC37",
              "source": "clinical_note",
              "confidence_score": 0.8212,
              "evidence_detail": { ... }
            },
            ...
          ]
        }
    """
    patient = emr.get_patient(pid)
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient {pid} not found")

    from app.services.lab_suspect_engine import run_lab_suspect_scan

    try:
        result = run_lab_suspect_scan(pid)
    except Exception as exc:
        logger.error("get_lab_suspects error pid=%s: %s", pid, exc)
        raise HTTPException(status_code=500, detail=f"Lab suspect scan failed: {exc}")

    patient_name = (
        f"{patient.get('fname', '')} {patient.get('lname', '')}".strip()
        or f"Patient {pid}"
    )

    return {
        "pid": pid,
        "patient_name": patient_name,
        "notes_scanned": result["notes_scanned"],
        "vitals_rows_checked": result["vitals_rows_checked"],
        "existing_diagnosis_count": result["existing_diagnosis_count"],
        "note_suspects_count": len(result["note_suspects"]),
        "vitals_suspects_count": len(result["vitals_suspects"]),
        "total_suspects": len(result["all_suspects"]),
        "suspects": result["all_suspects"],
    }


# ---------------------------------------------------------------------------
# Comprehensive Profile — aggregated multi-source patient view for RAF analysis
# ---------------------------------------------------------------------------

def _calculate_age(dob_raw: str | None) -> int | None:
    """
    Return the patient's current age in years, or None when DOB is absent/unparseable.

    Age is computed relative to today's calendar date, NOT the CMS Feb-1 convention
    used by the RAF calculator.  This value is purely for display purposes in the
    profile view.
    """
    if not dob_raw:
        return None
    try:
        dob = _datetime.strptime(str(dob_raw)[:10], "%Y-%m-%d").date()
        today = _date.today()
        return (
            today.year - dob.year
            - ((today.month, today.day) < (dob.month, dob.day))
        )
    except (ValueError, TypeError):
        return None


def _safe_call(label: str, fn, *args, default=None, **kwargs):
    """
    Call *fn* with *args*/*kwargs* and return the result.

    On any exception, log a warning and return *default* so a single broken
    data source never aborts the whole profile assembly.
    """
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        logger.warning("comprehensive-profile [%s] failed: %s", label, exc)
        return default


@router.get(
    "/{pid}/comprehensive-profile",
    summary="Complete patient profile for RAF analysis",
)
def get_comprehensive_profile(pid: int) -> dict[str, Any]:
    """
    Aggregate ALL available OpenEMR data sources into a single response.

    Used by the frontend to show the complete patient picture before and after
    RAF analysis.  Every sub-call is individually wrapped so that a failure in
    one data source (e.g. a table that does not exist yet in the target database,
    or a service being developed by another agent) never breaks the response.
    Missing data sources return empty lists / None and are reflected in the
    ``data_completeness`` block so the UI can surface meaningful warnings.

    Data sources aggregated
    -----------------------
    - Patient demographics (DOB, sex, race, ethnicity)
    - Billing: ICD-10 codes + CPT procedure codes
    - Problem list (OpenEMR lists table, ~990 K rows)
    - Recapture gaps: active problems not yet billed in the current year
    - Medications (active prescriptions) + medication-diagnosis gaps
    - Encounters (full history with provider info)
    - Vitals: latest structured reading + rule-based vitals suspects
    - Labs: rule-based lab suspects from clinical notes and procedure_result
    - Immunizations (``immunizations`` table)
    - Enrollment info (OREC + dual-eligibility derived from insurance_data)
    - HEDIS compliance indicators
    - Family history (``lists`` type=family_history)
    - Allergies (``lists`` type=allergy)
    - Referrals (``referrals`` table)
    - RAF: current score + HCC breakdown from raf_scores / raf_patient_hcc

    All timestamps / Decimal values are pre-serialised to JSON-safe types by the
    individual service functions before reaching this layer.
    """
    # ------------------------------------------------------------------
    # 1. Resolve patient — hard 404 if not found; no fallback.
    # ------------------------------------------------------------------
    patient = emr.get_patient(pid)
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient {pid} not found")

    current_year = _date.today().year

    # ------------------------------------------------------------------
    # 2. Collect every data source independently.
    # ------------------------------------------------------------------

    # --- Billing -------------------------------------------------------
    icd10_codes = _safe_call("billing.icd10", emr.get_billing_codes, pid, default=[])
    cpt_codes = _safe_call("billing.cpt", emr.get_cpt_codes, pid, default=[])

    # Attach condition hints to CPT codes (local dict, never fails)
    hints = emr.CPT_CONDITION_HINTS
    for row in cpt_codes:
        code = str(row.get("code") or "").strip()
        row.setdefault("condition_hint", hints.get(code))

    # --- Problem list --------------------------------------------------
    problem_list = _safe_call("problem_list", emr.get_problem_list, pid, default=[])
    for p in problem_list:
        p["has_icd_code"] = bool(p.get("diagnosis"))

    # --- Recapture gaps ------------------------------------------------
    recapture_gaps = _safe_call(
        "recapture_gaps", emr.get_recapture_gaps, pid, current_year, default=[]
    )

    # --- Medications ---------------------------------------------------
    medications = _safe_call("medications", emr.get_medications, pid, default=[])

    # get_medication_diagnosis_gaps may not exist yet (added by another agent)
    medication_diagnosis_gaps = _safe_call(
        "medication_diagnosis_gaps",
        emr.get_medication_diagnosis_gaps,  # type: ignore[attr-defined]
        pid,
        current_year,
        default=[],
    )

    # --- Encounters ----------------------------------------------------
    encounters = _safe_call("encounters", emr.get_encounters, pid, default=[])

    # --- Vitals --------------------------------------------------------
    # get_latest_vitals may not exist yet; fall back to get_vitals and take first row
    latest_vitals = _safe_call(
        "vitals.latest",
        emr.get_latest_vitals,  # type: ignore[attr-defined]
        pid,
        default=None,
    )
    if latest_vitals is None:
        all_vitals = _safe_call("vitals.all", emr.get_vitals, pid, default=[])
        latest_vitals = all_vitals[0] if all_vitals else None

    # Vitals-based suspects from the rule-based lab suspect engine
    vitals_suspects: list[dict[str, Any]] = []
    try:
        from app.services.lab_suspect_engine import run_lab_suspect_scan  # type: ignore

        lab_scan = run_lab_suspect_scan(pid)
        vitals_suspects = lab_scan.get("vitals_suspects", [])
        lab_suspects_list = lab_scan.get("all_suspects", [])
    except Exception as exc:
        logger.warning("comprehensive-profile [lab_suspect_engine] failed: %s", exc)
        lab_suspects_list = []

    # --- Immunizations -------------------------------------------------
    immunizations = _safe_call(
        "immunizations",
        emr.get_immunizations,  # type: ignore[attr-defined]
        pid,
        default=[],
    )

    # --- Enrollment info -----------------------------------------------
    enrollment = _safe_call(
        "enrollment",
        emr.get_patient_enrollment_info,
        pid,
        default={
            "dual_status": "non_dual",
            "orec": "0",
            "institutional": False,
            "source": "unavailable",
        },
    )

    # --- HEDIS compliance ----------------------------------------------
    # get_hedis_compliance may not exist yet (added by another agent)
    hedis: dict[str, Any] = _safe_call(
        "hedis",
        emr.get_hedis_compliance,  # type: ignore[attr-defined]
        pid,
        current_year,
        default={},
    )

    # --- Family history ------------------------------------------------
    family_history = _safe_call(
        "family_history",
        emr.get_family_history,  # type: ignore[attr-defined]
        pid,
        default=[],
    )

    # --- Allergies -----------------------------------------------------
    allergies = _safe_call(
        "allergies",
        emr.get_allergies,  # type: ignore[attr-defined]
        pid,
        default=[],
    )

    # --- Referrals -----------------------------------------------------
    referrals = _safe_call(
        "referrals",
        emr.get_referrals,  # type: ignore[attr-defined]
        pid,
        default=[],
    )

    # --- RAF score + breakdown ----------------------------------------
    raf_current_score: float | None = None
    raf_breakdown: dict[str, Any] | None = None

    for yr in [current_year, current_year - 1]:
        raf_data = _safe_call("raf_breakdown", get_raf_breakdown, pid, yr, default={})
        if raf_data:
            raf_current_score = raf_data.get("raf_score")
            raf_breakdown = raf_data
            break

    # --- Clinical notes existence check (for completeness only) --------
    # We check encounter-level has_notes flags rather than fetching all note text.
    has_clinical_notes = any(
        bool(enc.get("has_notes")) for enc in encounters
    )

    # --- Insurance / coverage existence check --------------------------
    has_insurance = enrollment.get("source") not in (None, "default", "unavailable")

    # ------------------------------------------------------------------
    # 3. Compute data completeness score (0–100 %).
    # ------------------------------------------------------------------
    completeness_flags: dict[str, bool] = {
        "has_billing":       bool(icd10_codes),
        "has_problems":      bool(problem_list),
        "has_clinical_notes": has_clinical_notes,
        "has_vitals":        latest_vitals is not None,
        "has_labs":          bool(lab_suspects_list),
        "has_immunizations": bool(immunizations),
        "has_insurance":     has_insurance,
    }
    completeness_pct = round(
        sum(completeness_flags.values()) / len(completeness_flags) * 100
    )

    # ------------------------------------------------------------------
    # 4. Assemble final response.
    # ------------------------------------------------------------------
    log_phi_access(
        action="view",
        resource="profile",
        patient_id=pid,
        details=f"completeness_pct={completeness_pct}",
    )
    return {
        "pid": pid,
        "patient": patient,
        "demographics": {
            "age": _calculate_age(patient.get("DOB")),
            "sex": patient.get("sex"),
            "race": patient.get("race"),
            "ethnicity": patient.get("ethnicity"),
        },
        "billing": {
            "icd10_codes": icd10_codes,
            "cpt_codes": cpt_codes,
        },
        "problem_list": problem_list,
        "recapture_gaps": recapture_gaps,
        "medications": {
            "active": medications,
            "diagnosis_gaps": medication_diagnosis_gaps,
        },
        "encounters": encounters,
        "vitals": {
            "latest": latest_vitals,
            "suspects": vitals_suspects,
        },
        "labs": {
            "suspects": lab_suspects_list,
        },
        "immunizations": immunizations,
        "enrollment": enrollment,
        "hedis": hedis,
        "family_history": family_history,
        "allergies": allergies,
        "referrals": referrals,
        "raf": {
            "current_score": raf_current_score,
            "breakdown": raf_breakdown,
        },
        "data_completeness": {
            **completeness_flags,
            "completeness_pct": completeness_pct,
        },
    }


# ---------------------------------------------------------------------------
# Family History
# ---------------------------------------------------------------------------

@router.get("/{pid}/family-history", summary="Get patient family history")
def get_family_history(pid: int) -> dict[str, Any]:
    """
    Return the most recent family-history record for *pid* from
    OpenEMR's history_data table.

    The response includes only columns that describe relatives' diagnoses
    (relatives_cancer, relatives_diabetes, relatives_heart_disease, etc.).
    An empty ``family_history`` dict is returned when the table does not
    exist in this OpenEMR deployment or the patient has no record.

    This data enriches the risk-stratification pipeline: a positive family
    history of diabetes or cardiovascular disease, for example, can support
    suspect-condition recommendations when the patient's own diagnoses are
    incomplete.
    """
    patient = emr.get_patient(pid)
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient {pid} not found")

    family_history = emr.get_family_history(pid)

    return {
        "pid": pid,
        "family_history": family_history,
    }


# ---------------------------------------------------------------------------
# SDOH
# ---------------------------------------------------------------------------

@router.get("/{pid}/sdoh", summary="Get Social Determinants of Health data")
def get_sdoh(pid: int) -> dict[str, Any]:
    """
    Return Social Determinants of Health (SDOH) data for *pid*.

    The response combines two sources:

    1. ``sdoh_form`` — the raw row from form_history_sdoh (OpenEMR >= 6.x).
       ``null`` when the table is absent or no record exists.

    2. ``billed_z_codes`` — ICD-10 Z-codes already present on the patient's
       claims (Z5x through Z9x range), each with the most recent billing date.
       Empty list when none exist.

    3. ``billable_highlights`` — reference map of the six highest-value SDOH
       Z-codes that CMS accepts for risk adjustment:
           Z59.0  Homelessness
           Z59.1  Inadequate housing
           Z56.0  Unemployment
           Z63.0  Relationship problems
           Z60.2  Living alone
           Z91.120 Food insecurity

    These codes are billable and can contribute to quality measures and
    Enhanced Medication Adherence scores.  Practices that document SDOH but
    do not bill the corresponding Z-codes leave value on the table.
    """
    patient = emr.get_patient(pid)
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient {pid} not found")

    sdoh = emr.get_sdoh_data(pid)

    return sdoh


# ---------------------------------------------------------------------------
# Allergies
# ---------------------------------------------------------------------------

@router.get("/{pid}/allergies", summary="Get patient active allergies")
def get_allergies(pid: int) -> dict[str, Any]:
    """
    Return all active allergy records for *pid* from OpenEMR's lists table.

    Each record includes:
    - ``title``     — free-text allergen name (e.g. "Penicillin", "Peanuts")
    - ``diagnosis`` — structured reaction code (ICD/SNOMED) when available;
                      may be empty for free-text-only entries
    - ``begdate``   — date the allergy was first recorded

    Allergies are relevant to the RAF pipeline because certain drug allergies
    constrain medication options for chronic conditions (e.g. ACE inhibitor
    allergy in a CHF patient) and may indicate underlying diagnoses.

    An empty list is returned when no active allergies exist or the table is
    inaccessible.
    """
    patient = emr.get_patient(pid)
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient {pid} not found")

    allergies = emr.get_allergies(pid)

    return {
        "pid": pid,
        "count": len(allergies),
        "allergies": allergies,
    }


# ---------------------------------------------------------------------------
# Referrals
# ---------------------------------------------------------------------------

@router.get("/{pid}/referrals", summary="Get patient referral transactions")
def get_referrals(pid: int) -> dict[str, Any]:
    """
    Return all referral transactions for *pid* from OpenEMR's transactions
    table (rows with title='Referral'), ordered newest first.

    Each record includes:
    - ``id``          — transaction PK
    - ``date``        — date referral was created
    - ``body``        — free-text referral notes / clinical summary
    - ``refer_to``    — specialist or facility being referred to
    - ``refer_from``  — referring provider
    - ``reason``      — structured reason for referral
    - ``reply_date``  — date consultation reply was received (null if pending)

    Referrals surface care-coordination context useful for identifying
    specialty conditions (e.g. referral to cardiology may indicate undiagnosed
    HF) and for closing care gaps when a reply has not been received.

    An empty list is returned when the transactions table is absent or no
    referrals exist for the patient.
    """
    patient = emr.get_patient(pid)
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient {pid} not found")

    referrals = emr.get_referrals(pid)

    return {
        "pid": pid,
        "count": len(referrals),
        "referrals": referrals,
    }


# ---------------------------------------------------------------------------
# Immunizations
# ---------------------------------------------------------------------------

@router.get("/{pid}/immunizations", summary="Get patient immunization history")
def get_immunizations(pid: int) -> dict[str, Any]:
    """
    Return the complete immunization history for *pid* from the OpenEMR
    immunizations table.

    Each record includes:
    - id, administered_date, cvx_code, manufacturer, lot_number
    - administered_by, education_date, note

    Records flagged as added_erroneously in OpenEMR are excluded.
    CVX codes are the CDC standard vaccine identifiers -- use them for any
    downstream matching, not free-text descriptions.
    """
    patient = emr.get_patient(pid)
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient {pid} not found")

    try:
        immunizations = emr.get_immunizations(pid)
    except Exception as exc:
        logger.error("get_immunizations error pid=%s: %s", pid, exc)
        raise HTTPException(status_code=500, detail=str(exc))

    return {
        "pid": pid,
        "count": len(immunizations),
        "immunizations": immunizations,
    }


# ---------------------------------------------------------------------------
# HEDIS / Stars quality measures
# ---------------------------------------------------------------------------

@router.get("/{pid}/hedis", summary="HEDIS/Stars quality measure compliance")
def get_hedis_compliance(
    pid: int,
    year: int = Query(
        default=0,
        ge=2000,
        le=2100,
        description="Measurement year.  Defaults to the current calendar year.",
    ),
) -> dict[str, Any]:
    """
    Return HEDIS/Stars quality measure compliance for *pid*.

    Each measure in the response contains:
    - measure      : human-readable measure name
    - due          : whether the measure applies to this patient (age/sex-gated)
    - compliant    : whether the patient currently meets the measure
    - last_date    : ISO date of the most recent qualifying event, or null

    Measures currently evaluated
    ----------------------------
    flu_vaccine     -- Annual influenza vaccination (all ages)
    pneumococcal    -- Pneumococcal vaccination series (age >= 65)
    zoster          -- Shingles vaccination series (age >= 50)

    Compliance is determined using CDC CVX vaccine codes sourced from the
    OpenEMR immunizations table.  Free-text note matching is used only as a
    secondary fallback for influenza when no CVX code is recorded.
    """
    from datetime import date as _date

    if year == 0:
        year = _date.today().year

    patient = emr.get_patient(pid)
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient {pid} not found")

    try:
        measures = emr.get_hedis_compliance(pid, year)
    except Exception as exc:
        logger.error("get_hedis_compliance error pid=%s year=%s: %s", pid, year, exc)
        raise HTTPException(status_code=500, detail=str(exc))

    due_count = sum(1 for m in measures.values() if m.get("due"))
    compliant_count = sum(1 for m in measures.values() if m.get("due") and m.get("compliant"))

    return {
        "pid": pid,
        "year": year,
        "summary": {
            "measures_due": due_count,
            "measures_compliant": compliant_count,
            "compliance_rate": round(compliant_count / due_count, 2) if due_count else None,
        },
        "measures": measures,
    }


# ---------------------------------------------------------------------------
# Enrollment / Insurance Info
# ---------------------------------------------------------------------------

@router.get("/{pid}/enrollment", summary="Get patient enrollment and insurance/dual status")
def get_patient_enrollment(pid: int) -> dict[str, Any]:
    """
    Return enrollment and insurance metadata for *pid* derived from OpenEMR
    insurance_data, insurance_companies, and form_encounter tables.

    Response fields
    ---------------
    dual_status         -- "non_dual" | "partial_dual" | "full_dual"
    primary_insurance   -- display name of the primary insurer, or null
    secondary_insurance -- display name of the secondary insurer, or null
    orec                -- "0" (aged) | "1" (disabled).  CMS Original Reason
                           for Entitlement Code derived from patient age.
                           ESRD (OREC 2/3) cannot be detected from OpenEMR.
    institutional       -- true when any recent encounter has a facility-based
                           POS code (SNF=31, Nursing Facility=32, etc.)
    pos_codes           -- list of distinct POS codes from recent encounters
    source              -- how the data was derived:
                             "openemr_insurance"   -- matched insurance records
                             "openemr_age_heuristic" -- age only, no insurance data
                             "default"              -- no usable data; CNA assumed
    confidence          -- "high" | "medium" | "low"

    This endpoint never returns a 500 — if data is unavailable it falls back
    gracefully to CNA defaults (non_dual, aged, not institutional).
    """
    patient = emr.get_patient(pid)
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient {pid} not found")

    enrollment = emr.get_patient_enrollment_info(pid)

    return {
        "pid": pid,
        "enrollment": enrollment,
    }
