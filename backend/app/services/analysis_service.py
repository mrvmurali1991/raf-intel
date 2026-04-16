"""
analysis_service.py

Reusable persistence helpers for AI pipeline analysis results.

Extracted from app/routers/analysis.py so that pipeline automation
(pipeline_chain, celery_tasks) and the router can share a single
canonical implementation without importing from a router module.
"""

import json
import logging
from datetime import date as _date
from typing import Any

from hccinfhir.defaults import is_chronic_default

from app.db import raf_cursor
from app.services.audit_logger import log_phi_access
from app.services.icd_validator import validate_code
from app.services.hccinfhir_utils import lookup_hcc
from app.services.meat_evidence_service import store_analysis_meat, update_hcc_meat_status

logger = logging.getLogger(__name__)


def save_encounter_analysis(
    encounter_id: int,
    pid: int,
    analysis: dict[str, Any],
) -> None:
    """Upsert pipeline results to raf_encounter_analysis and raf_meat_evidence tables.

    This is the canonical persistence function for AI analysis results.
    It is called by:
      - app/routers/analysis.py   (HTTP endpoints)
      - app/services/pipeline_chain.py  (background automation)
      - app/services/celery_tasks.py    (Celery worker tasks)

    Parameters
    ----------
    encounter_id:
        OpenEMR encounter ID (integer).  Used as the primary key in
        raf_encounter_analysis and source_encounter_ids in raf_patient_hcc.
    pid:
        Internal patient ID (integer).  May be from the local patients table
        or an emr_patient_matches.id for FHIR patients — both are valid here.
    analysis:
        Full pipeline result dict as returned by run_verified_pipeline() or
        run_pipeline().
    """
    import json as _json

    # ------------------------------------------------------------------
    # 1. Upsert the encounter-level summary row
    # ------------------------------------------------------------------
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
        """Handle Decimal, datetime, date for JSON serialisation."""
        from decimal import Decimal
        from datetime import datetime as _dt, date as _d

        if isinstance(obj, Decimal):
            return float(obj)
        if isinstance(obj, (_dt, _d)):
            return obj.isoformat()
        return str(obj)

    try:
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
        log_phi_access(
            action="write",
            resource="encounter_analysis",
            patient_id=pid,
            details=f"encounter_id={encounter_id}",
        )
    except Exception as exc:
        logger.warning(
            "Failed to save encounter analysis for encounter %s: %s (type: %s)",
            encounter_id,
            exc,
            type(exc).__name__,
        )
        # Retry with aggressive serialisation to strip any non-JSON-safe objects
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

    # ------------------------------------------------------------------
    # 2. Persist HCC codes discovered by AI into raf_patient_hcc
    # ------------------------------------------------------------------
    try:
        # Derive measurement_year from encounter date when available,
        # falling back to current year only if no date is present.
        _enc_date_str = analysis.get("encounter_date") or analysis.get("date")
        year_defaulted = False
        if _enc_date_str:
            try:
                measurement_year = int(str(_enc_date_str)[:4])
            except (ValueError, TypeError):
                measurement_year = _date.today().year
                year_defaulted = True
                logger.warning(
                    "measurement_year defaulted to %d for encounter_id=%s pid=%s"
                    " — encounter_date missing or unparseable (value=%r)",
                    measurement_year,
                    encounter_id,
                    pid,
                    _enc_date_str,
                )
        else:
            measurement_year = _date.today().year
            year_defaulted = True
            logger.warning(
                "measurement_year defaulted to %d for encounter_id=%s pid=%s"
                " — encounter_date missing or unparseable (value=None)",
                measurement_year,
                encounter_id,
                pid,
            )
        hcc_diagnoses = [d for d in analysis.get("diagnoses", []) if d.get("hcc")]
        if hcc_diagnoses:
            with raf_cursor() as cur:
                for dx in hcc_diagnoses:
                    # Normalize HCC code to plain number string (e.g., "19")
                    hcc_code = str(dx["hcc"]).strip().upper().replace("HCC", "").replace(" ", "").lstrip("0") or "0"
                    icd10 = str(dx.get("icd10", "")).strip()

                    if icd10 and not validate_code(icd10):
                        logger.warning(
                            "Skipping invalid ICD-10 code %s for encounter %s",
                            icd10,
                            encounter_id,
                        )
                        continue

                    # Cross-validate AI HCC mapping against official CMS crosswalk
                    if icd10:
                        official = lookup_hcc(icd10)
                        official_hcc = official.get("hcc_code")
                        if official_hcc and str(official_hcc) != hcc_code:
                            logger.warning(
                                "AI HCC mismatch for %s: AI=%s, CMS crosswalk=%s (encounter %s) — using CMS value",
                                icd10, hcc_code, official_hcc, encounter_id,
                            )
                            hcc_code = str(official_hcc)
                        elif not official_hcc:
                            logger.warning(
                                "ICD-10 %s has no CMS HCC mapping but AI assigned HCC %s (encounter %s) — skipping",
                                icd10, hcc_code, encounter_id,
                            )
                            continue

                    cur.execute(
                        "SELECT id, icd10_codes, source_encounter_ids "
                        "FROM raf_patient_hcc "
                        "WHERE patient_id = %s AND hcc_code = %s AND measurement_year = %s "
                        "LIMIT 1",
                        (pid, hcc_code, measurement_year),
                    )
                    existing = cur.fetchone()
                    if existing:
                        try:
                            old_codes = json.loads(existing["icd10_codes"] or "[]")
                        except (ValueError, TypeError):
                            old_codes = []
                        merged_codes = list(set(old_codes + ([icd10] if icd10 else [])))

                        try:
                            old_enc = json.loads(existing["source_encounter_ids"] or "[]")
                        except (ValueError, TypeError):
                            old_enc = []
                        merged_enc = list(set(old_enc + [encounter_id]))

                        cur.execute(
                            "UPDATE raf_patient_hcc "
                            "SET icd10_codes = %s, source_encounter_ids = %s, updated_at = NOW() "
                            "WHERE id = %s",
                            (
                                json.dumps(merged_codes),
                                json.dumps(merged_enc),
                                existing["id"],
                            ),
                        )
                    else:
                        _is_chronic = (
                            1
                            if is_chronic_default.get(
                                (hcc_code, "CMS-HCC Model V28"), True
                            )
                            else 0
                        )
                        cur.execute(
                            """INSERT INTO raf_patient_hcc
                               (patient_id, measurement_year, hcc_code, icd10_codes,
                                source_encounter_ids, raf_coefficient, meat_status, is_trumped,
                                is_chronic)
                               VALUES (%s, %s, %s, %s, %s, 0, 'pending', 0, %s)""",
                            (
                                pid,
                                measurement_year,
                                hcc_code,
                                json.dumps([icd10] if icd10 else []),
                                json.dumps([encounter_id]),
                                _is_chronic,
                            ),
                        )
            logger.info(
                "Persisted %d HCC code(s) to raf_patient_hcc for patient_id=%s encounter_id=%s",
                len(hcc_diagnoses),
                pid,
                encounter_id,
            )
            log_phi_access(
                action="write",
                resource="hcc_codes",
                patient_id=pid,
                details=f"encounter_id={encounter_id}, count={len(hcc_diagnoses)}",
            )

            # Apply HCC trumping hierarchy so that, e.g., HCC 17 suppresses HCC 18
            # when both are present for the same patient+year.
            try:
                from app.services.hcc_hierarchy import apply_hierarchy_to_patient

                hierarchy_result = apply_hierarchy_to_patient(
                    patient_id=pid,
                    measurement_year=measurement_year,
                    tenant_id="1",
                )
                logger.info(
                    "HCC hierarchy applied for patient_id=%s year=%s: "
                    "total=%d trumped=%d updated=%d errors=%d",
                    pid,
                    measurement_year,
                    hierarchy_result.get("total", 0),
                    hierarchy_result.get("trumped", 0),
                    hierarchy_result.get("updated", 0),
                    hierarchy_result.get("errors", 0),
                )
            except Exception as hierarchy_exc:
                logger.warning(
                    "HCC hierarchy step failed for patient_id=%s encounter_id=%s: %s",
                    pid,
                    encounter_id,
                    hierarchy_exc,
                )

    except Exception as hcc_exc:
        logger.warning(
            "Failed to persist HCC codes to raf_patient_hcc for encounter %s: %s",
            encounter_id,
            hcc_exc,
        )

    # ------------------------------------------------------------------
    # 3. MEAT evidence
    # ------------------------------------------------------------------
    def _extract_meat(d: dict) -> dict:
        """Normalise MEAT keys from AI output.

        The model may return single-letter keys (M/E/A/T) or full-word keys
        (monitoring/evaluation/assessment/treatment) in either case.  Accept
        all variants so the downstream store step always receives the expected
        long-form keys.
        """
        _meat_raw = d.get("meat", {})
        monitoring = _meat_raw.get("M") or _meat_raw.get("monitoring") or _meat_raw.get("Monitoring") or ""
        evaluation = _meat_raw.get("E") or _meat_raw.get("evaluation") or _meat_raw.get("Evaluation") or ""
        assessment = _meat_raw.get("A") or _meat_raw.get("assessment") or _meat_raw.get("Assessment") or ""
        treatment = _meat_raw.get("T") or _meat_raw.get("treatment") or _meat_raw.get("Treatment") or ""
        if d.get("hcc") and not any([monitoring, evaluation, assessment, treatment]):
            logger.warning(
                "All MEAT fields empty for HCC diagnosis icd10=%s hcc=%s — "
                "AI may have returned unexpected keys: %s",
                d.get("icd10", ""),
                d.get("hcc", ""),
                list(_meat_raw.keys()),
            )
        return {
            "monitoring": monitoring,
            "evaluation": evaluation,
            "assessment": assessment,
            "treatment": treatment,
        }

    gemini_compat = {
        "diagnoses": [
            {
                "icd10": d.get("icd10", ""),
                "description": d.get("description", ""),
                "hcc_code": d.get("hcc", ""),
                "confidence": d.get("confidence", 0),
                "negated": False,
                "meat": _extract_meat(d),
                "meat_score": d.get("meat_score", 0),
            }
            for d in analysis.get("diagnoses", [])
        ],
        "_meta": {
            "encounter_id": encounter_id,
            "encounter_date": analysis.get("encounter_date") or analysis.get("date") or _date.today().isoformat(),
        },
    }
    try:
        store_analysis_meat(pid, measurement_year, gemini_compat)
        update_hcc_meat_status(pid, measurement_year)
    except Exception as exc:
        logger.warning(
            "Failed to store MEAT evidence for encounter %s: %s", encounter_id, exc
        )
