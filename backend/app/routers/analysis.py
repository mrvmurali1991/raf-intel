"""
Clinical note analysis router — full MedCAT → Assertion → Retrieve-Rank → Gemini pipeline.

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
1. MedCAT NER          – medcat_service.extract_entities()
2. Assertion filter    – assertion_service.filter_negated_entities()
3. Retrieve-Rank       – retrieve_rank_service.get_candidates()
4. Gemini analysis     – gemini_service.analyze_clinical_note()
5. Validation          – icd_validator (inside gemini_service)
6. Confidence routing  – confidence_router.route_analysis_result()
7. Persist             – meat_evidence_service.store_analysis_meat()
                         + raf_encounter_analysis table

Fallback behavior
-----------------
If MedCAT or assertion_service raises an exception the pipeline falls back
gracefully to Gemini-only mode (no candidate-code grounding).  The response
``pipeline`` block marks which stages ran.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import date as _date
from datetime import datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException
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
from app.services.meat_evidence_service import store_analysis_meat, update_hcc_meat_status

# Legacy imports — kept for _run_pipeline_legacy fallback
try:
    from app.services._legacy import medcat_service, assertion_service
    from app.services._legacy import retrieve_rank_service
    from app.services._legacy import gemini_service
    from app.services.confidence_router import route_analysis_result
except ImportError:
    medcat_service = None  # type: ignore
    assertion_service = None  # type: ignore
    retrieve_rank_service = None  # type: ignore
    gemini_service = None  # type: ignore
    route_analysis_result = None  # type: ignore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/analysis", tags=["analysis"])

# ---------------------------------------------------------------------------
# In-memory job store (replace with Redis / persistent DB for production)
# ---------------------------------------------------------------------------

_jobs: dict[str, dict[str, Any]] = {}


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


# LEGACY — kept for fallback
def _run_pipeline_legacy(
    note_text: str,
    *,
    patient_age: int | None = None,
    patient_sex: str | None = None,
    existing_hccs: list[str] | None = None,
    medications: list[str] | None = None,
    labs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Execute the full analysis pipeline on *note_text*.

    Returns a dict shaped like the documented response format.  Pipeline
    stage metadata is included under the ``pipeline`` key so the caller can
    see exactly what each stage contributed.

    Raises RuntimeError only if Gemini itself fails (all other stages have
    internal fallbacks).
    """
    pipeline: dict[str, Any] = {
        "medcat_entities": [],
        "after_negation_filter": [],
        "candidate_codes": [],
        "gemini_selected": [],
        "stages_run": [],
        "fallback_mode": False,
    }

    # ------------------------------------------------------------------
    # Stage 1: MedCAT NER
    # ------------------------------------------------------------------
    raw_entities: list[dict[str, Any]] = []
    try:
        raw_entities = medcat_service.extract_entities(note_text)
        pipeline["medcat_entities"] = [
            {
                "text": e.get("text", ""),
                "name": e.get("name", ""),
                "icd10": e.get("icd10", ""),
                "confidence": e.get("confidence", 0),
                "negated": e.get("negated", False),
                "category": e.get("category", ""),
            }
            for e in raw_entities
        ]
        pipeline["stages_run"].append("medcat")
        logger.debug("MedCAT: %d entities extracted", len(raw_entities))
    except Exception as exc:
        logger.warning("MedCAT stage failed, using fallback: %s", exc)
        pipeline["fallback_mode"] = True

    # ------------------------------------------------------------------
    # Stage 2: Assertion / negation filter
    # ------------------------------------------------------------------
    present_entities: list[dict[str, Any]] = []
    try:
        if raw_entities:
            present_entities = assertion_service.filter_negated_entities(
                raw_entities, note_text
            )
            pipeline["after_negation_filter"] = [
                {
                    "text": e.get("text", ""),
                    "name": e.get("name", ""),
                    "icd10": e.get("icd10", ""),
                    "assertion": (e.get("assertion") or {}).get("assertion", "present"),
                }
                for e in present_entities
            ]
            pipeline["stages_run"].append("assertion_filter")
            logger.debug(
                "Assertion filter: %d → %d entities after removing negated/historical",
                len(raw_entities),
                len(present_entities),
            )
    except Exception as exc:
        logger.warning("Assertion stage failed, using all entities: %s", exc)
        present_entities = raw_entities

    # ------------------------------------------------------------------
    # Stage 3: Retrieve-Rank candidate ICD codes
    # ------------------------------------------------------------------
    candidate_codes: list[dict[str, Any]] = []
    try:
        if present_entities:
            # retrieve_and_rank returns entities enriched with candidates
            ranked_entities = retrieve_rank_service.retrieve_and_rank(
                present_entities, clinical_note=note_text
            )
            # Flatten all candidates from all entities
            for ent in ranked_entities:
                for c in ent.get("candidates", []):
                    candidate_codes.append({
                        "icd10_code": c.get("code", ""),
                        "description": c.get("description", ""),
                        "entity_source": ent.get("name", ""),
                        "relevance_score": float(c.get("relevance_score", 0)),
                    })
            pipeline["candidate_codes"] = [
                {
                    "icd10": c.get("icd10_code", c.get("code", "")),
                    "description": c.get("description", ""),
                    "entity": c.get("entity_source", ""),
                    "relevance_score": round(float(c.get("relevance_score", 0)), 3),
                }
                for c in candidate_codes
            ]
            pipeline["stages_run"].append("retrieve_rank")
            logger.debug("Retrieve-Rank: %d candidate codes", len(candidate_codes))
    except Exception as exc:
        logger.warning("Retrieve-Rank stage failed: %s", exc)

    # ------------------------------------------------------------------
    # Stage 4: Gemini analysis (with candidate codes as grounding context)
    # ------------------------------------------------------------------
    # Build the existing_hccs list from candidate codes + caller-supplied
    existing_hcc_list: list[str] = list(existing_hccs or [])
    for c in candidate_codes:
        hcc = c.get("hcc_code", "")
        if hcc and hcc not in existing_hcc_list:
            existing_hcc_list.append(hcc)

    gemini_result = gemini_service.analyze_clinical_note(
        note_text=note_text,
        patient_age=patient_age,
        patient_sex=patient_sex,
        existing_hccs=existing_hcc_list or None,
        medications=medications,
        lab_results=labs,
    )
    pipeline["stages_run"].append("gemini")

    # Stage 5: collect what Gemini selected
    pipeline["gemini_selected"] = [
        {
            "icd10": d.get("icd10", ""),
            "description": d.get("description", ""),
            "confidence": d.get("confidence", 0),
        }
        for d in gemini_result.get("diagnoses", [])
    ]

    # ------------------------------------------------------------------
    # Stage 6: Enrich diagnoses with MEAT score integer and source tag
    # ------------------------------------------------------------------
    diagnoses: list[dict[str, Any]] = []
    negated_conditions: list[dict[str, Any]] = []

    for dx in gemini_result.get("diagnoses", []):
        meat = dx.get("meat") or {}
        # Normalise MEAT keys: Gemini may return M/E/A/T or monitoring/evaluation/…
        normalised_meat = {
            "M": meat.get("M") or meat.get("monitoring", ""),
            "E": meat.get("E") or meat.get("evaluation", ""),
            "A": meat.get("A") or meat.get("assessment", ""),
            "T": meat.get("T") or meat.get("treatment", ""),
        }
        meat_score = sum(1 for v in normalised_meat.values() if v and v.strip())

        # Determine source tag and fill missing ICD-10/description
        icd10 = dx.get("icd10", "") or ""
        description = dx.get("description", "") or ""
        hcc = dx.get("hcc_code") or dx.get("hcc", "") or ""

        # If ICD-10 is empty, try to find it from MedCAT entities matching this HCC
        if not icd10 and hcc:
            # Map HCC to common ICD-10 codes
            hcc_to_icd = {
                "HCC37": ("E11.22", "Type 2 DM with diabetic chronic kidney disease"),
                "HCC38": ("E11.65", "Type 2 DM with hyperglycemia"),
                "HCC85": ("I50.32", "Chronic diastolic heart failure"),
                "HCC226": ("I50.30", "Chronic diastolic heart failure"),
                "HCC329": ("N18.32", "Chronic kidney disease, stage 3b"),
                "HCC328": ("N18.3", "Chronic kidney disease, stage 3"),
                "HCC18": ("E11.22", "Type 2 DM with complications"),
                "HCC19": ("E11.9", "Type 2 DM without complications"),
                "HCC137": ("N18.4", "Chronic kidney disease, stage 4"),
                "HCC111": ("J44.9", "COPD, unspecified"),
                "HCC280": ("J44.9", "COPD, unspecified"),
                "HCC96": ("I48.91", "Atrial fibrillation"),
                "HCC238": ("I48.91", "Atrial fibrillation"),
                "HCC52": ("F03.90", "Dementia, unspecified"),
                "HCC127": ("G30.9", "Alzheimer disease"),
                "HCC155": ("F32.9", "Major depressive disorder"),
                "HCC8": ("C79.9", "Metastatic cancer"),
                "HCC1": ("B20", "HIV disease"),
            }
            hcc_clean = hcc.replace("HCC", "").strip()
            hcc_key = f"HCC{hcc_clean}" if not hcc.startswith("HCC") else hcc
            if hcc_key in hcc_to_icd:
                icd10, description = hcc_to_icd[hcc_key]
            else:
                # Try to match from MedCAT entities
                for ent in present_entities:
                    if ent.get("icd10"):
                        icd10 = ent["icd10"]
                        description = ent.get("name", "")
                        break

        # If description still empty, use MEAT assessment
        if not description:
            description = normalised_meat.get("A", "") or dx.get("condition", "")

        matched_candidate = next(
            (c for c in candidate_codes if c.get("icd10_code") == icd10 or c.get("icd10") == icd10), None
        )
        source = "medcat+gemini" if matched_candidate else "gemini"

        # Override HCC with official CMS-HCC V28 crosswalk lookup
        crosswalk_hcc = ""
        crosswalk_weight = None
        if icd10:
            from app.services.icd_validator import get_hcc_mapping
            mapping = get_hcc_mapping(icd10)
            if mapping:
                crosswalk_hcc = f"HCC{mapping['hcc_code']}"
                crosswalk_weight = mapping.get("raf_weight")
            # If crosswalk says no HCC, clear it (Gemini may have hallucinated)
            # If crosswalk has a different HCC, use the crosswalk
            if crosswalk_hcc:
                if hcc and hcc != crosswalk_hcc:
                    logger.info(
                        "HCC override: %s Gemini=%s → Crosswalk=%s", icd10, hcc, crosswalk_hcc
                    )
                hcc = crosswalk_hcc
            elif not crosswalk_hcc and mapping is None:
                # Code not in crosswalk = not risk-adjusting
                if hcc:
                    logger.info("HCC removed: %s Gemini=%s → NOT in V28 crosswalk", icd10, hcc)
                hcc = ""

        diagnoses.append({
            "icd10": icd10,
            "description": description,
            "hcc": hcc,
            "hcc_weight": crosswalk_weight,
            "confidence": float(dx.get("confidence", 0.0)),
            "meat": normalised_meat,
            "meat_score": meat_score,
            "source": source,
        })

    # ------------------------------------------------------------------
    # Stage 6.5: Deduplicate diagnoses by ICD-10 code
    # ------------------------------------------------------------------
    if diagnoses:
        seen_icd: dict[str, int] = {}
        unique_diagnoses: list[dict[str, Any]] = []
        for dx in diagnoses:
            icd = dx.get("icd10", "").strip()
            if not icd:
                # Keep entries without ICD if they have a description
                if dx.get("description"):
                    unique_diagnoses.append(dx)
                continue
            if icd in seen_icd:
                # Keep the one with higher confidence
                existing_idx = seen_icd[icd]
                if dx.get("confidence", 0) > unique_diagnoses[existing_idx].get("confidence", 0):
                    unique_diagnoses[existing_idx] = dx
            else:
                seen_icd[icd] = len(unique_diagnoses)
                unique_diagnoses.append(dx)

        if len(unique_diagnoses) < len(diagnoses):
            logger.info("Deduplicated diagnoses: %d -> %d", len(diagnoses), len(unique_diagnoses))
        diagnoses = unique_diagnoses

    # Collect negated conditions from Gemini output
    for nc in gemini_result.get("negated_conditions", []):
        if isinstance(nc, str):
            negated_conditions.append({"icd10": "", "description": nc, "reason": "negated"})
        elif isinstance(nc, dict):
            negated_conditions.append({
                "icd10": nc.get("icd10", ""),
                "description": nc.get("description", str(nc)),
                "reason": nc.get("reason", "negated"),
            })
        else:
            negated_conditions.append({"icd10": "", "description": str(nc), "reason": "negated"})

    # Also add assertion-filtered entities as negated_conditions
    negated_entity_icds = {nc.get("icd10", "") for nc in negated_conditions}
    for ent in raw_entities:
        ent_icd = ent.get("icd10", "")
        assertion = (ent.get("assertion") or {}).get("assertion", "present")
        if assertion in ("absent", "historical", "family") and ent_icd not in negated_entity_icds:
            negated_conditions.append({
                "icd10": ent_icd if isinstance(ent_icd, str) else str(ent_icd),
                "description": ent.get("name", ""),
                "reason": assertion,
            })

    suspect_conditions = gemini_result.get("suspect_conditions", [])

    # ------------------------------------------------------------------
    # Stage 7: Confidence routing
    # ------------------------------------------------------------------
    overall_confidence = float(
        gemini_result.get("overall_confidence", 0.0)
        or gemini_result.get("overall_documentation_score", 0.0)
        or (
            sum(d["confidence"] for d in diagnoses) / len(diagnoses)
            if diagnoses else 0.0
        )
    )

    try:
        routing = route_analysis_result(
            medcat_entities=pipeline.get("medcat_entities", []),
            gemini_diagnoses=diagnoses,
            negation_results=pipeline.get("negation_filtered", []),
            candidate_codes=pipeline.get("candidate_codes", []),
        )
    except Exception as exc:
        logger.warning("Confidence routing failed: %s", exc)
        routing = {
            "routing": "human_review",
            "overall_confidence": overall_confidence,
            "reasons": [f"Routing error: {exc}"],
        }
    pipeline["stages_run"].append("confidence_routing")

    return {
        "pipeline": pipeline,
        "diagnoses": diagnoses,
        "suspect_conditions": suspect_conditions,
        "negated_conditions": negated_conditions,
        "routing": routing,
        "overall_confidence": round(overall_confidence, 4),
        "_meta": gemini_result.get("_meta", {}),
    }


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
            (encounter_id, pid, analysis_json, overall_score,
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
        routing = str(analysis.get("routing", "needs_review"))[:50]

        with raf_cursor() as cur:
            cur.execute(sql, (
                encounter_id,
                pid,
                _json.dumps(analysis, default=_default_ser),
                float(overall) if overall else 0,
                len(analysis.get("diagnoses", [])),
                len(analysis.get("suspect_conditions", [])),
                sum(1 for d in analysis.get("diagnoses", []) if d.get("hcc")),
                routing,
            ))
        logger.debug("Saved encounter analysis for encounter_id=%s", encounter_id)
    except Exception as exc:
        logger.warning(
            "Failed to save encounter analysis for encounter %s: %s (type: %s)",
            encounter_id, exc, type(exc).__name__,
        )
        # Retry with aggressive serialization
        try:
            clean_json = _json.loads(_json.dumps(analysis, default=_default_ser))
            with raf_cursor() as cur:
                cur.execute(sql, (
                    encounter_id, pid,
                    _json.dumps(clean_json),
                    float(analysis.get("overall_confidence", 0)),
                    len(analysis.get("diagnoses", [])),
                    len(analysis.get("suspect_conditions", [])),
                    sum(1 for d in analysis.get("diagnoses", []) if d.get("hcc")),
                    str(analysis.get("routing", "needs_review")),
                ))
            logger.info("Saved encounter analysis (retry) for encounter_id=%s", encounter_id)
        except Exception as exc2:
            logger.error("Retry save also failed for encounter %s: %s", encounter_id, exc2)

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
                    "evaluation":  d.get("meat", {}).get("E", ""),
                    "assessment":  d.get("meat", {}).get("A", ""),
                    "treatment":   d.get("meat", {}).get("T", ""),
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
def get_cached_analysis(encounter_id: int) -> dict[str, Any]:
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
                result = _json.loads(row["analysis_json"]) if isinstance(row["analysis_json"], str) else row["analysis_json"]
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
def analyze_encounter(
    encounter_id: int,
    body: EncounterAnalysisRequest = EncounterAnalysisRequest(),
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
                cached = _json.loads(row["analysis_json"]) if isinstance(row["analysis_json"], str) else row["analysis_json"]
                cached["_cached"] = True
                cached["_cached_at"] = str(row["created_at"])
                logger.info("Returning cached analysis for encounter %s", encounter_id)
                return cached
    except Exception:
        pass  # cache miss — run fresh analysis

    # Fetch encounter metadata
    encounter = get_encounter(encounter_id)
    if not encounter:
        raise HTTPException(status_code=404, detail=f"Encounter {encounter_id} not found")

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
        medications = [
            m["drug"] for m in meds if m.get("drug") and m.get("active")
        ][:30]

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
    except Exception as exc:
        logger.error("Pipeline failed for encounter %s: %s", encounter_id, exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"Analysis pipeline failed: {exc}")

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
        if stripped and (stripped.endswith(":") or re.match(r"^[A-Z][A-Za-z /\-]+:", stripped)):
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
def analyze_note(body: NoteAnalysisRequest) -> dict[str, Any]:
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
            len(raw_note), len(note_text), pid,
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
        medications = [m["drug"] for m in meds if m.get("drug") and m.get("active")][:30]
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
        pid, len(note_text), was_truncated, patient_age, patient_sex, demographics_source,
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
    except Exception as exc:
        exc_str = str(exc)
        logger.error(
            "Pipeline failed for patient %s (note endpoint): %s",
            pid, exc_str, exc_info=True,
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
        raise HTTPException(
            status_code=502,
            detail=f"Analysis pipeline failed: {exc_str}",
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
    )
    return result


# ---------------------------------------------------------------------------
# POST /api/analysis/batch/{pid}
# ---------------------------------------------------------------------------

def _run_batch_job(job_id: str, pid: int, save_results: bool) -> None:
    """Background task: analyze all encounters for a patient."""
    _jobs[job_id]["status"] = "running"
    try:
        patient = get_patient(pid)
        if not patient:
            _jobs[job_id].update({"status": "failed", "error": f"Patient {pid} not found"})
            return

        dob = patient.get("DOB") or ""
        patient_sex: str = patient.get("sex", "")

        billing = get_billing_codes(pid)
        existing_hccs = [b["code"] for b in billing if b.get("code")][:50]
        meds = get_medications(pid)
        medications = [m["drug"] for m in meds if m.get("drug") and m.get("active")][:30]
        labs = get_labs(pid)[:20]

        notes = get_all_clinical_notes_for_patient(pid)
        _jobs[job_id]["total"] = len(notes)

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
                        from app.services.suspect_engine import save_suspects_from_analysis
                        save_suspects_from_analysis(pid, enc_id, batch_suspects)
                    except Exception as s_exc:
                        logger.warning("Batch: failed to save suspects: %s", s_exc)

                if save_results and enc_id:
                    result["encounter_date"] = note.get("date", _date.today().isoformat())
                    _save_encounter_analysis(enc_id, pid, result)

            except Exception as exc:
                logger.warning("Batch job %s: note error pid=%s: %s", job_id, pid, exc)
                errors += 1

            _jobs[job_id]["processed"] = len(results)
            _jobs[job_id]["errors"] = errors

        _jobs[job_id]["status"] = "complete"
        _jobs[job_id]["results"] = results

    except Exception as exc:
        _jobs[job_id].update({"status": "failed", "error": str(exc)})
        logger.error("Batch job %s failed: %s", job_id, exc, exc_info=True)


@router.post(
    "/batch/{pid}",
    summary="Queue batch analysis for all encounters of a patient",
)
def batch_analysis(
    pid: int,
    save_results: bool = True,
    background_tasks: BackgroundTasks = BackgroundTasks(),
) -> dict[str, Any]:
    """
    Queue a background job to analyze all clinical notes for *pid*.
    Poll ``GET /api/analysis/jobs/{job_id}`` for status.
    """
    patient = get_patient(pid)
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient {pid} not found")

    job_id = f"analysis-{uuid.uuid4().hex[:8]}"
    _jobs[job_id] = {
        "status": "queued",
        "pid": pid,
        "processed": 0,
        "errors": 0,
        "total": 0,
        "created_at": datetime.utcnow().isoformat(),
        "results": [],
    }
    background_tasks.add_task(_run_batch_job, job_id, pid, save_results)

    log_phi_access(
        action="batch_analyze",
        resource="patient",
        patient_id=pid,
        details=f"job_id={job_id}",
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
def get_job_status(job_id: str) -> dict[str, Any]:
    """Poll the status of a background analysis job."""
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    response = {k: v for k, v in job.items() if k != "results"}
    response["job_id"] = job_id
    if job.get("status") == "complete":
        response["result_count"] = len(job.get("results", []))
    return response


@router.get("/jobs/{job_id}/results", summary="Retrieve completed job results")
def get_job_results(job_id: str) -> dict[str, Any]:
    """Return the full results of a completed analysis job."""
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    if job.get("status") != "complete":
        raise HTTPException(
            status_code=409,
            detail=f"Job {job_id} is not complete (status: {job.get('status')})",
        )
    return {
        "job_id": job_id,
        "pid": job.get("pid"),
        "results": job.get("results", []),
    }
