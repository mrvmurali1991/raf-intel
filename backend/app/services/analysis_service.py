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

from app.db import raf_cursor
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
        measurement_year = _date.today().year
        hcc_diagnoses = [d for d in analysis.get("diagnoses", []) if d.get("hcc")]
        if hcc_diagnoses:
            with raf_cursor() as cur:
                for dx in hcc_diagnoses:
                    hcc_code = str(dx["hcc"]).strip()
                    icd10 = str(dx.get("icd10", "")).strip()

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
                        cur.execute(
                            """INSERT INTO raf_patient_hcc
                               (patient_id, measurement_year, hcc_code, icd10_codes,
                                source_encounter_ids, raf_coefficient, meat_status, is_trumped)
                               VALUES (%s, %s, %s, %s, %s, 0, 'pending', 0)""",
                            (
                                pid,
                                measurement_year,
                                hcc_code,
                                json.dumps([icd10] if icd10 else []),
                                json.dumps([encounter_id]),
                            ),
                        )
            logger.info(
                "Persisted %d HCC code(s) to raf_patient_hcc for patient_id=%s encounter_id=%s",
                len(hcc_diagnoses),
                pid,
                encounter_id,
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
        update_hcc_meat_status(pid, _date.today().year)
    except Exception as exc:
        logger.warning(
            "Failed to store MEAT evidence for encounter %s: %s", encounter_id, exc
        )
