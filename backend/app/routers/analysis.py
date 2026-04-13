"""
Clinical note analysis router.

Endpoints
---------
POST /api/analysis/encounter/{encounter_id}
    Fetch SOAP note from OpenEMR, run the full pipeline, store and return results.

POST /api/analysis/note
    Run the full pipeline on user-supplied note text (no OpenEMR fetch required).

GET  /api/analysis/jobs/{job_id}
    Poll the status of an async batch-analysis job.

GET  /api/analysis/jobs/{job_id}/results
    Retrieve the full results of a completed batch job.

POST /api/analysis/batch/{pid}
    Queue a background job that analyzes every encounter for a patient.

Pipeline stages
---------------
1. Stage 1 extraction  – pipeline_orchestrator / stage1_extraction
2. Gemini analysis     – skill_pipeline / stage2 Gemini
3. Verification        – stage3_verification
4. Confidence routing  – confidence_router.route_analysis_result()
5. Persist             – meat_evidence_service.store_analysis_meat()
                         + raf_encounter_analysis table
"""
# Removed: from __future__ import annotations (breaks FastAPI schema generation)

import json
import logging
import re
import uuid
from datetime import date as _date
from datetime import datetime
from typing import Any

from fastapi import Depends, APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel

from app.db import raf_cursor
from app.services.openemr_connector import (
    get_patient,
    get_encounters,
    get_soap_notes,
    get_medications,
    get_billing_codes,
    get_all_clinical_text,
    get_encounter,
    get_clinical_notes,
    get_labs,
    get_all_clinical_notes_for_patient,
    get_problem_list,
    get_recapture_gaps,
    get_latest_vitals,
    get_medication_diagnoses,
)
from app.services.audit_logger import log_phi_access
from app.services.raf_calculator import calculate_raf_score, _calculate_age
from app.services.meat_evidence_service import (
    store_analysis_meat,
    update_hcc_meat_status,
)
from app.auth import get_current_user, get_tenant_id, require_permission
from app.rate_limit import limiter
from app.services.circuit_breaker import CircuitBreakerError

from app.services.confidence_router import route_analysis_result

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/analysis", tags=["analysis"])

# ---------------------------------------------------------------------------
# DB-backed job store (replaces the former in-memory _jobs dict).
# Jobs are persisted to raf_jobs so they survive restarts and scale across
# multiple workers.  The job_service module provides the persistence layer.
# ---------------------------------------------------------------------------

from app.services.job_service import _upsert_job, _get_job

# Tables are created by the centralized migration runner (app/migrations.py)
# at application startup. No per-module DDL calls are needed.


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class EncounterAnalysisRequest(BaseModel):
    include_context: bool = True
    save_results: bool = True


class NoteAnalysisRequest(BaseModel):
    patient_id: int
    note_text: str
    save_results: bool = False


# ---------------------------------------------------------------------------
# Core pipeline
# ---------------------------------------------------------------------------


def _run_pipeline(
    note_text: str,
    *,
    patient_age: int | None = None,
    patient_sex: str | None = None,
    existing_hccs: list[str] | None = None,
    medications: list[str] | None = None,
    labs: list[dict[str, Any]] | None = None,
    problem_list: list[dict[str, Any]] | None = None,
    recapture_gaps: list[dict[str, Any]] | None = None,
    latest_vitals: dict[str, Any] | None = None,
    med_diagnoses: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Execute the multi-stage verified pipeline (Stage 1 -> 2 -> 3 -> 4).

    Routes through pipeline_orchestrator.run_verified_pipeline(), which adds
    deterministic pre-extraction (Stage 1) and post-LLM reconciliation (Stage 3)
    around the existing Gemini skill_pipeline call (Stage 2).

    Falls back to the single-stage skill_pipeline on any orchestrator error,
    preserving the previous behavior and ensuring the endpoint stays available
    even if the new pipeline stages fail.
    """
    try:
        from app.services.pipeline_orchestrator import run_verified_pipeline

        return run_verified_pipeline(
            clinical_note=note_text,
            patient_age=patient_age,
            patient_sex=patient_sex,
            medications=medications,
            existing_hccs=existing_hccs,
            problem_list=problem_list,
            recapture_gaps=recapture_gaps,
            latest_vitals=latest_vitals,
            med_diagnoses=med_diagnoses,
        )
    except Exception as exc:
        logger.warning(
            "Verified pipeline failed — falling back to single-stage skill pipeline: %s",
            exc,
            exc_info=True,
        )
        from app.services.skill_pipeline import run_pipeline as skill_pipeline

        return skill_pipeline(
            clinical_note=note_text,
            patient_age=patient_age,
            patient_sex=patient_sex,
            medications=medications,
            existing_hccs=existing_hccs,
            problem_list=problem_list,
            recapture_gaps=recapture_gaps,
            latest_vitals=latest_vitals,
            med_diagnoses=med_diagnoses,
        )



# ---------------------------------------------------------------------------
# Persist helpers
# ---------------------------------------------------------------------------


def _save_encounter_analysis(
    encounter_id: int,
    pid: int,
    analysis: dict[str, Any],
) -> None:
    """Upsert to raf_encounter_analysis and raf_meat_evidence tables."""
    import json as _json

    # Encounter-level row
    sql = """
        INSERT INTO raf_encounter_analysis
            (encounter_id, patient_id, analysis_json, overall_score,
             dx_count, suspect_count, hcc_opportunity_count,
             routing, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
        ON DUPLICATE KEY UPDATE
            analysis_json         = VALUES(analysis_json),
            overall_score         = VALUES(overall_score),
            dx_count              = VALUES(dx_count),
            suspect_count         = VALUES(suspect_count),
            hcc_opportunity_count = VALUES(hcc_opportunity_count),
            routing               = VALUES(routing),
            created_at            = NOW()
    """

    def _default_ser(obj):
        """Handle Decimal, datetime, date, etc. for JSON serialization."""
        from decimal import Decimal
        from datetime import datetime as _dt, date as _d

        if isinstance(obj, Decimal):
            return float(obj)
        if isinstance(obj, (_dt, _d)):
            return obj.isoformat()
        return str(obj)

    try:
        # Ensure all values are safe scalar types
        overall = analysis.get("overall_confidence", 0)
        if isinstance(overall, dict):
            overall = overall.get("score", overall.get("confidence", 0))
        routing_raw = analysis.get("routing", {})
        if isinstance(routing_raw, dict):
            routing = str(routing_raw.get("routing", "needs_review"))[:50]
        else:
            routing = str(routing_raw)[:50]

        with raf_cursor() as cur:
            cur.execute(
                sql,
                (
                    encounter_id,
                    pid,
                    _json.dumps(analysis, default=_default_ser),
                    float(overall) if overall else 0,
                    len(analysis.get("diagnoses", [])),
                    len(analysis.get("suspect_conditions", [])),
                    sum(1 for d in analysis.get("diagnoses", []) if d.get("hcc")),
                    routing,
                ),
            )
        logger.debug("Saved encounter analysis for encounter_id=%s", encounter_id)
    except Exception as exc:
        logger.warning(
            "Failed to save encounter analysis for encounter %s: %s (type: %s)",
            encounter_id,
            exc,
            type(exc).__name__,
        )
        # Retry with aggressive serialization
        try:
            clean_json = _json.loads(_json.dumps(analysis, default=_default_ser))
            with raf_cursor() as cur:
                cur.execute(
                    sql,
                    (
                        encounter_id,
                        pid,
                        _json.dumps(clean_json),
                        float(analysis.get("overall_confidence", 0)),
                        len(analysis.get("diagnoses", [])),
                        len(analysis.get("suspect_conditions", [])),
                        sum(1 for d in analysis.get("diagnoses", []) if d.get("hcc")),
                        str(analysis.get("routing", "needs_review")),
                    ),
                )
            logger.info(
                "Saved encounter analysis (retry) for encounter_id=%s", encounter_id
            )
        except Exception as exc2:
            logger.error(
                "Retry save also failed for encounter %s: %s", encounter_id, exc2
            )

    # MEAT evidence — requires raf_patient_hcc rows to already exist;
    # use the existing store_analysis_meat which accepts (patient_id, year, gemini_result).
    # We inject encounter metadata via the _meta block.
    gemini_compat = {
        "diagnoses": [
            {
                "icd10": d.get("icd10", ""),
                "description": d.get("description", ""),
                "hcc_code": d.get("hcc", ""),
                "confidence": d.get("confidence", 0),
                "negated": False,
                "meat": {
                    "monitoring": d.get("meat", {}).get("M", ""),
                    "evaluation": d.get("meat", {}).get("E", ""),
                    "assessment": d.get("meat", {}).get("A", ""),
                    "treatment": d.get("meat", {}).get("T", ""),
                },
                "meat_score": d.get("meat_score", 0),
            }
            for d in analysis.get("diagnoses", [])
        ],
        "_meta": {
            "encounter_id": encounter_id,
            "encounter_date": analysis.get("encounter_date", _date.today().isoformat()),
        },
    }
    try:
        store_analysis_meat(pid, _date.today().year, gemini_compat)
        # Refresh meat_status in raf_patient_hcc based on newly stored evidence
        update_hcc_meat_status(pid, _date.today().year)
    except Exception as exc:
        logger.warning(
            "Failed to store MEAT evidence for encounter %s: %s", encounter_id, exc
        )


# ---------------------------------------------------------------------------
# POST /api/analysis/encounter/{encounter_id}
# ---------------------------------------------------------------------------


@router.get(
    "/encounter/{encounter_id}/cached",
    summary="Get cached analysis results for an encounter",
)
@limiter.limit("60/minute")
def get_cached_analysis(
    request: Request,
    encounter_id: int,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("encounters", "read")),
) -> dict[str, Any]:
    """Return previously saved analysis for this encounter, or 404 if none."""
    import json as _json

    try:
        with raf_cursor() as cur:
            cur.execute(
                "SELECT analysis_json, created_at FROM raf_encounter_analysis WHERE encounter_id = %s",
                (encounter_id,),
            )
            row = cur.fetchone()
            if row and row["analysis_json"]:
                result = (
                    _json.loads(row["analysis_json"])
                    if isinstance(row["analysis_json"], str)
                    else row["analysis_json"]
                )
                result["_cached"] = True
                result["_cached_at"] = str(row["created_at"])
                return result
    except Exception as exc:
        logger.debug("Cache lookup failed for encounter %s: %s", encounter_id, exc)
    raise HTTPException(status_code=404, detail="No cached analysis found")


@router.post(
    "/encounter/{encounter_id}",
    summary="Full-pipeline analysis for an OpenEMR encounter",
)
@limiter.limit("30/minute")
def analyze_encounter(
    request: Request,
    encounter_id: int,
    body: EncounterAnalysisRequest = EncounterAnalysisRequest(),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("encounters", "write")),
) -> dict[str, Any]:
    """
    Retrieve the SOAP / clinical note for *encounter_id* from OpenEMR,
    run the full MedCAT → Assertion → Retrieve-Rank → Gemini pipeline,
    persist the results, and return the structured analysis.
    """
    # Check cache first — return stored result if available
    import json as _json

    try:
        with raf_cursor() as cur:
            cur.execute(
                "SELECT analysis_json, created_at FROM raf_encounter_analysis WHERE encounter_id = %s",
                (encounter_id,),
            )
            row = cur.fetchone()
            if row and row["analysis_json"]:
                cached = (
                    _json.loads(row["analysis_json"])
                    if isinstance(row["analysis_json"], str)
                    else row["analysis_json"]
                )
                cached["_cached"] = True
                cached["_cached_at"] = str(row["created_at"])
                logger.info("Returning cached analysis for encounter %s", encounter_id)
                return cached
    except Exception:
        pass  # cache miss — run fresh analysis

    # Fetch encounter metadata
    encounter = get_encounter(encounter_id)
    if not encounter:
        raise HTTPException(
            status_code=404, detail=f"Encounter {encounter_id} not found"
        )

    pid: int = int(encounter["pid"])

    # Fetch clinical notes
    notes = get_clinical_notes(encounter_id)
    if not notes:
        raise HTTPException(
            status_code=404,
            detail=f"No clinical notes found for encounter {encounter_id}",
        )

    combined_note = "\n\n".join(
        n["note_text"] for n in notes if n.get("note_text")
    ).strip()
    if not combined_note:
        raise HTTPException(
            status_code=422,
            detail="Clinical notes are empty for this encounter",
        )

    # Optional patient context — initialised to safe defaults so the pipeline
    # call below is always valid even when include_context=False.
    patient_age: int | None = None
    patient_sex: str | None = None
    existing_hccs: list[str] = []
    medications: list[str] = []
    labs: list[dict[str, Any]] = []
    problem_list: list[dict[str, Any]] = []
    recapture_gaps: list[dict[str, Any]] = []
    latest_vitals: dict[str, Any] = {}
    med_diagnoses: list[dict[str, Any]] = []
    enc_year: int = _date.today().year

    if body.include_context:
        patient = get_patient(pid)
        if patient:
            dob = patient.get("DOB") or ""
            # CMS rule: age is calculated as of Feb 1 of the encounter service year.
            # Extract year from the encounter date; fall back to today's year if absent.
            enc_date_raw = encounter.get("date") or ""
            try:
                enc_year = int(str(enc_date_raw)[:4])
            except (TypeError, ValueError):
                enc_year = _date.today().year
            try:
                patient_age = _calculate_age(str(dob)[:10], enc_year)
            except Exception:
                patient_age = None
            patient_sex = patient.get("sex", "")

        billing = get_billing_codes(pid)
        existing_hccs = [b["code"] for b in billing if b.get("code")][:50]

        meds = get_medications(pid)
        medications = [m["drug"] for m in meds if m.get("drug") and m.get("active")][
            :30
        ]

        labs = get_labs(pid)[:20]

        # NEW — Problem list (active diagnoses, including those not billed this year)
        try:
            problem_list = get_problem_list(pid)
            recapture_gaps = get_recapture_gaps(pid, enc_year)
        except Exception:
            problem_list, recapture_gaps = [], []

        # NEW — Latest vitals snapshot
        try:
            latest_vitals = get_latest_vitals(pid)
        except Exception:
            latest_vitals = {}

        # NEW — Medications with documented indication notes
        try:
            med_diagnoses = get_medication_diagnoses(pid)
        except Exception:
            med_diagnoses = []

    # Run pipeline
    try:
        result = _run_pipeline(
            combined_note,
            patient_age=patient_age,
            patient_sex=patient_sex,
            existing_hccs=existing_hccs,
            medications=medications,
            labs=labs,
            problem_list=problem_list,
            recapture_gaps=recapture_gaps,
            latest_vitals=latest_vitals,
            med_diagnoses=med_diagnoses,
        )
    except CircuitBreakerError as exc:
        logger.warning("Gemini circuit breaker open for encounter %s: %s", encounter_id, exc)
        raise HTTPException(
            status_code=503,
            detail=f"AI analysis service temporarily unavailable. {exc}",
            headers={"Retry-After": str(int(exc.retry_after))},
        ) from exc
    except Exception as exc:
        logger.error(
            "Pipeline failed for encounter %s: %s", encounter_id, exc, exc_info=True
        )
        raise HTTPException(status_code=502, detail="Bad gateway")

    # Attach encounter context to response
    result["encounter_id"] = encounter_id
    result["patient_id"] = pid
    result["encounter_date"] = encounter.get("date")

    # Save suspect conditions to raf_suspect_conditions table
    suspects = result.get("suspect_conditions", [])
    if suspects and pid:
        try:
            from app.services.suspect_engine import save_suspects_from_analysis

            save_suspects_from_analysis(pid, encounter_id, suspects)
        except Exception as exc:
            logger.warning("Failed to save suspects: %s", exc)

    # Attach human-review routing queue alongside verification data
    try:
        from app.services.review_queue import route_for_review

        result["review_queue"] = route_for_review(result)
    except Exception as exc:
        logger.warning("review_queue generation failed (non-fatal): %s", exc)
        result["review_queue"] = None

    # Persist
    if body.save_results:
        result["encounter_date"] = encounter.get("date", _date.today().isoformat())
        _save_encounter_analysis(encounter_id, pid, result)

    log_phi_access(
        action="analyze",
        resource="encounter",
        patient_id=pid,
        encounter_id=encounter_id,
        details=f"dx_count={len(result.get('diagnoses', []))} saved={body.save_results}",
        tenant_id=tenant_id,
    )
    return result


# ---------------------------------------------------------------------------
# POST /api/analysis/note — helpers
# ---------------------------------------------------------------------------

_NOTE_CHAR_LIMIT = 20_000

# Section headers to keep when the note must be truncated.  The pipeline
# already hard-caps at 15 000 chars, but doing a smart section-aware
# truncation here means the *right* content reaches Gemini rather than a
# blind head-slice that may include verbose procedure/superbill blocks.
_KEEP_SECTIONS = re.compile(
    r"(?i)(chief\s+complaint|cc:|hpi|history\s+of\s+present\s+illness"
    r"|assessment|impression|diagnos|plan|medications?|current\s+meds)",
)
_SKIP_SECTIONS = re.compile(
    r"(?i)(procedure|care\s+plan|superbill|billing\s+codes?|cpt\s+codes?)",
)


def _truncate_note(note: str) -> tuple[str, bool]:
    """
    Return (possibly-truncated note, was_truncated).

    If the note is within the limit it is returned unchanged.  Otherwise we
    walk the note line-by-line, keeping lines that belong to high-value
    sections (Chief Complaint, HPI, Assessment, Medications) and dropping
    lines inside low-value sections (Procedures, Care Plans, Superbill).
    If the filtered result is still over the limit it is hard-truncated at
    the character boundary.
    """
    if len(note) <= _NOTE_CHAR_LIMIT:
        return note, False

    lines = note.splitlines()
    filtered: list[str] = []
    in_skip_section = False

    for line in lines:
        stripped = line.strip()
        # A line that looks like a new section header resets context.
        if stripped and (
            stripped.endswith(":") or re.match(r"^[A-Z][A-Za-z /\-]+:", stripped)
        ):
            if _SKIP_SECTIONS.search(stripped):
                in_skip_section = True
                continue
            if _KEEP_SECTIONS.search(stripped):
                in_skip_section = False
        if not in_skip_section:
            filtered.append(line)

    result = "\n".join(filtered)

    # Hard truncate if still too long.
    if len(result) > _NOTE_CHAR_LIMIT:
        result = result[:_NOTE_CHAR_LIMIT]

    return result, True


# Age: "65-year-old", "65 year old", "Age: 65", "Age 65"
_AGE_RE = re.compile(
    r"(?:(\d{1,3})\s*[-\u2013]?\s*year\s*[-\u2013]?\s*old)"
    r"|(?:age[:\s]+(\d{1,3}))",
    re.IGNORECASE,
)
# Sex: standalone word or after "Gender:"/"Sex:"
_SEX_RE = re.compile(
    r"(?:gender|sex)[:\s]+(male|female)"
    r"|(?<!\w)(male|female)(?!\w)",
    re.IGNORECASE,
)


def _parse_demographics_from_note(note: str) -> tuple[int | None, str | None]:
    """
    Extract (age, sex) from free-text note using lightweight regex.

    Returns (None, None) when either field cannot be reliably determined.
    Only the first clear match for each field is used.
    """
    age: int | None = None
    sex: str | None = None

    age_match = _AGE_RE.search(note)
    if age_match:
        raw_age = age_match.group(1) or age_match.group(2)
        try:
            candidate = int(raw_age)
            if 0 < candidate < 130:
                age = candidate
        except (TypeError, ValueError):
            pass

    sex_match = _SEX_RE.search(note)
    if sex_match:
        # group(1) = labelled match ("Gender: male"), group(2) = bare word
        raw_sex = (sex_match.group(1) or sex_match.group(2) or "").lower()
        if raw_sex in ("male", "female"):
            sex = raw_sex.capitalize()

    return age, sex


# ---------------------------------------------------------------------------
# POST /api/analysis/note
# ---------------------------------------------------------------------------


@router.post(
    "/note",
    summary="Full-pipeline analysis on user-supplied note text",
)
def analyze_note(
    body: NoteAnalysisRequest,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("encounters", "write")),
) -> dict[str, Any]:
    """
    Run the full pipeline on *note_text* without fetching from OpenEMR.

    Useful for testing, demo, or integration with external EHRs.

    Changes vs original:
    - Large notes (>20 000 chars) are section-aware truncated before the
      pipeline sees them so Gemini is not handed a 60-page document.
    - When patient_id=0 (paste/demo mode) age and sex are parsed from the
      note text with a lightweight regex so the RAF demographic base is
      populated even without an OpenEMR patient record.
    - Timeout and Gemini HTTP errors are returned as caller-friendly 504/502
      responses rather than raw exception strings.
    - response always carries pipeline.medcat_entities and
      pipeline.after_negation_filter (defensive backfill if the pipeline
      returned without them for any reason).
    """
    if not body.note_text or not body.note_text.strip():
        raise HTTPException(status_code=422, detail="note_text must not be empty")

    pid = body.patient_id
    raw_note = body.note_text.strip()

    # --- Issue 1: large-note truncation ----------------------------------------
    note_text, was_truncated = _truncate_note(raw_note)
    if was_truncated:
        logger.warning(
            "Note endpoint: note truncated from %d to %d chars for patient_id=%s",
            len(raw_note),
            len(note_text),
            pid,
        )

    patient_age: int | None = None
    patient_sex: str | None = None
    existing_hccs: list[str] = []
    medications: list[str] = []
    labs: list[dict[str, Any]] = []
    demographics_source = "none"

    # Pull context from OpenEMR if the patient exists and is not the
    # anonymous paste-mode sentinel (patient_id=0).
    patient = get_patient(pid) if pid else None
    if patient:
        dob = patient.get("DOB") or ""
        try:
            # Note endpoint has no encounter date, so we use today's year as a
            # prospective default (correct for current-year gap analysis).
            # For historical encounter scoring use the /encounter/{id} endpoint,
            # which passes the encounter service year to _calculate_age.
            patient_age = _calculate_age(str(dob)[:10])
        except Exception:
            pass
        patient_sex = patient.get("sex", "")
        billing = get_billing_codes(pid)
        existing_hccs = [b["code"] for b in billing if b.get("code")][:50]
        meds = get_medications(pid)
        medications = [m["drug"] for m in meds if m.get("drug") and m.get("active")][
            :30
        ]
        labs = get_labs(pid)[:20]
        demographics_source = "openemr"

    # --- Issue 2: parse demographics from note when patient_id=0 ---------------
    if not patient and (patient_age is None or not patient_sex):
        parsed_age, parsed_sex = _parse_demographics_from_note(raw_note)
        if parsed_age is not None and patient_age is None:
            patient_age = parsed_age
        if parsed_sex and not patient_sex:
            patient_sex = parsed_sex
        if parsed_age is not None or parsed_sex:
            demographics_source = "note_text"

    # --- Issue 5: log entry for every call ------------------------------------
    logger.info(
        "Note endpoint called: patient_id=%s note_chars=%d (truncated=%s) "
        "age=%s sex=%s demographics_source=%s",
        pid,
        len(note_text),
        was_truncated,
        patient_age,
        patient_sex,
        demographics_source,
    )

    # --- Issue 3: structured error handling ------------------------------------
    try:
        result = _run_pipeline(
            note_text,
            patient_age=patient_age,
            patient_sex=patient_sex,
            existing_hccs=existing_hccs,
            medications=medications,
            labs=labs,
        )
    except CircuitBreakerError as exc:
        logger.warning("Gemini circuit breaker open for patient %s: %s", pid, exc)
        raise HTTPException(
            status_code=503,
            detail=f"AI analysis service temporarily unavailable. {exc}",
            headers={"Retry-After": str(int(exc.retry_after))},
        ) from exc
    except Exception as exc:
        exc_str = str(exc)
        logger.error(
            "Pipeline failed for patient %s (note endpoint): %s",
            pid,
            exc_str,
            exc_info=True,
        )
        # Distinguish timeout from other Gemini/HTTP errors so the caller
        # can surface a meaningful message in the UI.
        lower = exc_str.lower()
        if "timeout" in lower or "timed out" in lower or "read timeout" in lower:
            raise HTTPException(
                status_code=504,
                detail=(
                    "The analysis pipeline timed out.  The note may be too long "
                    "or the AI service is temporarily slow.  Try again in a moment, "
                    "or shorten the note."
                ),
            )
        if "429" in exc_str or "quota" in lower or "rate limit" in lower:
            raise HTTPException(
                status_code=429,
                detail=(
                    "The AI service is rate-limited.  Please wait 30 seconds and retry."
                ),
            )
        if any(code in exc_str for code in ("500", "503", "502")):
            raise HTTPException(
                status_code=502,
                detail=(
                    "The AI service returned an error.  This is usually transient — "
                    "please retry.  If the problem persists, contact support."
                ),
            )
        logger.error("Unexpected error: %s", exc)
        raise HTTPException(
            status_code=502,
            detail="Bad gateway",
        )

    # --- Issue 4: guarantee pipeline NER fields are always present -------------
    pipeline_block = result.setdefault("pipeline", {})
    pipeline_block.setdefault("medcat_entities", [])
    pipeline_block.setdefault("after_negation_filter", [])

    result["patient_id"] = pid

    # Expose whether note was truncated so the UI can surface a notice.
    result["_note_truncated"] = was_truncated
    result["_note_chars_submitted"] = len(note_text)

    # Save suspect conditions from pipeline
    note_suspects = result.get("suspect_conditions", [])
    if note_suspects and pid:
        try:
            from app.services.suspect_engine import save_suspects_from_analysis

            save_suspects_from_analysis(pid, None, note_suspects)
        except Exception as exc:
            logger.warning("Note endpoint: failed to save suspects: %s", exc)

    # Attach human-review routing queue alongside verification data
    try:
        from app.services.review_queue import route_for_review

        result["review_queue"] = route_for_review(result)
    except Exception as exc:
        logger.warning("review_queue generation failed (non-fatal): %s", exc)
        result["review_queue"] = None

    log_phi_access(
        action="analyze",
        resource="clinical_note",
        patient_id=pid if pid else None,
        details=f"note_chars={len(note_text)} dx_count={len(result.get('diagnoses', []))}",
        tenant_id=tenant_id,
    )
    return result


# ---------------------------------------------------------------------------
# POST /api/analysis/batch/{pid}
# ---------------------------------------------------------------------------


def _run_batch_job(job_id: str, pid: int, save_results: bool) -> None:
    """Background task: analyze all encounters for a patient (DB-backed)."""
    _upsert_job(job_id, status="RUNNING", started_at=datetime.utcnow())
    try:
        patient = get_patient(pid)
        if not patient:
            _upsert_job(
                job_id,
                status="FAILED",
                error_message=f"Patient {pid} not found",
                finished_at=datetime.utcnow(),
            )
            return

        dob = patient.get("DOB") or ""
        patient_sex: str = patient.get("sex", "")

        billing = get_billing_codes(pid)
        existing_hccs = [b["code"] for b in billing if b.get("code")][:50]
        meds = get_medications(pid)
        medications = [m["drug"] for m in meds if m.get("drug") and m.get("active")][
            :30
        ]
        labs = get_labs(pid)[:20]

        notes = get_all_clinical_notes_for_patient(pid)
        _upsert_job(job_id, total=len(notes))

        results: list[dict[str, Any]] = []
        errors = 0

        for note in notes:
            note_text = note.get("note_text", "")
            if not note_text or not note_text.strip():
                continue

            try:
                # CMS rule: age as of Feb 1 of the encounter service year.
                # Recalculate per note so historical notes use their own year.
                note_date_raw = note.get("date") or ""
                try:
                    note_year = int(str(note_date_raw)[:4])
                except (TypeError, ValueError):
                    note_year = _date.today().year
                try:
                    patient_age: int | None = _calculate_age(str(dob)[:10], note_year)
                except Exception:
                    patient_age = None

                result = _run_pipeline(
                    note_text,
                    patient_age=patient_age,
                    patient_sex=patient_sex,
                    existing_hccs=existing_hccs,
                    medications=medications,
                    labs=labs,
                )
                enc_id: int | None = note.get("encounter")
                result["encounter_id"] = enc_id
                result["note_date"] = note.get("date")
                result["note_type"] = note.get("note_type")
                result["patient_id"] = pid
                results.append(result)

                # Save suspect conditions from pipeline
                batch_suspects = result.get("suspect_conditions", [])
                if batch_suspects and pid:
                    try:
                        from app.services.suspect_engine import (
                            save_suspects_from_analysis,
                        )

                        save_suspects_from_analysis(pid, enc_id, batch_suspects)
                    except Exception as s_exc:
                        logger.warning("Batch: failed to save suspects: %s", s_exc)

                if save_results and enc_id:
                    result["encounter_date"] = note.get(
                        "date", _date.today().isoformat()
                    )
                    _save_encounter_analysis(enc_id, pid, result)

            except Exception as exc:
                logger.warning("Batch job %s: note error pid=%s: %s", job_id, pid, exc)
                errors += 1

            _upsert_job(job_id, progress=len(results), total=len(notes))

        import json as _json

        _upsert_job(
            job_id,
            status="SUCCESS",
            progress=len(results),
            result_json=_json.dumps({"results": results}),
            finished_at=datetime.utcnow(),
        )

    except Exception as exc:
        _upsert_job(
            job_id,
            status="FAILED",
            error_message=str(exc),
            finished_at=datetime.utcnow(),
        )
        logger.error("Batch job %s failed: %s", job_id, exc, exc_info=True)


@router.post(
    "/batch/{pid}",
    summary="Queue batch analysis for all encounters of a patient",
)
def batch_analysis(
    pid: int,
    background_tasks: BackgroundTasks,
    save_results: bool = True,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("encounters", "write")),
) -> dict[str, Any]:
    """
    Queue a background job to analyze all clinical notes for *pid*.
    Poll ``GET /api/analysis/jobs/{job_id}`` for status.
    """
    patient = get_patient(pid)
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient {pid} not found")

    job_id = f"analysis-{uuid.uuid4().hex[:8]}"
    _upsert_job(
        job_id,
        task_name="batch_analysis",
        status="QUEUED",
        submitted_by=current_user.get("id"),
        args_json=json.dumps({"pid": pid, "save_results": save_results}),
    )
    background_tasks.add_task(_run_batch_job, job_id, pid, save_results)

    log_phi_access(
        action="batch_analyze",
        resource="patient",
        patient_id=pid,
        details=f"job_id={job_id}",
        tenant_id=tenant_id,
    )
    return {
        "job_id": job_id,
        "status": "queued",
        "message": f"Batch analysis queued for patient {pid}",
    }


# ---------------------------------------------------------------------------
# GET /api/analysis/jobs/{job_id}
# ---------------------------------------------------------------------------


@router.get("/jobs/{job_id}", summary="Check analysis job status")
def get_job_status_endpoint(
    job_id: str,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("encounters", "read")),
) -> dict[str, Any]:
    """Poll the status of a background analysis job."""
    job = _get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    response = {
        "job_id": job_id,
        "status": job.get("status"),
        "progress": job.get("progress", 0),
        "total": job.get("total", 0),
        "started_at": job.get("started_at"),
        "finished_at": job.get("finished_at"),
        "created_at": job.get("created_at"),
        "error_message": job.get("error_message"),
    }
    if job.get("status") == "SUCCESS":
        result_json = job.get("result_json")
        if isinstance(result_json, dict):
            response["result_count"] = len(result_json.get("results", []))
    return response


@router.get("/jobs/{job_id}/results", summary="Retrieve completed job results")
def get_job_results_endpoint(
    job_id: str,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("encounters", "read")),
) -> dict[str, Any]:
    """Return the full results of a completed analysis job."""
    job = _get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    if job.get("status") != "SUCCESS":
        raise HTTPException(
            status_code=409,
            detail=f"Job {job_id} is not complete (status: {job.get('status')})",
        )
    result_json = job.get("result_json")
    results = result_json.get("results", []) if isinstance(result_json, dict) else []
    return {
        "job_id": job_id,
        "results": results,
    }
