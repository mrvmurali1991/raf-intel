"""
Automated MEAT Extraction
=========================
Runs the rule-based ``meat_validator`` against every clinical note attached
to a patient, for every HCC currently assigned to that patient, and writes
the findings into ``raf_meat_evidence`` via ``meat_evidence_service``.

This is the scheduled / on-demand backfill path that converts free-text
SOAP notes into structured MEAT compliance evidence for CMS RADV defense.

Scope intentionally narrow:
  * Rule-based extraction only (see meat_validator keyword lexicons).
  * No LLM call. Fast, deterministic, cheap enough to run at panel-load time.
  * If an LLM-based MEAT extractor is wired in later, this module becomes
    the cheap fallback path when the LLM is unavailable or rate-limited.

Public API
----------
run_auto_meat_for_patient(patient_id, tenant_id, year=None, max_days_lookback=365)
    Extract MEAT evidence for this patient across their notes. Returns a
    summary dict the API layer can surface to the user.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any

from app.config import settings
from app.db import raf_cursor
from app.services import meat_evidence_service
from app.services.meat_validator import validate_meat
from app.services.openemr_connector import get_all_clinical_notes_for_patient

logger = logging.getLogger(__name__)

try:
    from hccinfhir.defaults import labels_default as _labels_default
except Exception:
    _labels_default = {}

_V28_MODEL = "CMS-HCC Model V28"


def _label_for_hcc(hcc_code: str) -> str:
    code = str(hcc_code).replace("HCC", "").strip()
    return _labels_default.get((code, _V28_MODEL)) or ""


def _coerce_note_date(raw: Any) -> date | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    s = str(raw).strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s[: len(fmt) + 2], fmt).date()
        except ValueError:
            continue
    return None


def _fetch_patient_hccs(patient_id: int, year: int, tenant_id: str) -> list[dict[str, Any]]:
    """Return raf_patient_hcc rows with their ICD codes for this patient/year."""
    sql = """
        SELECT id AS patient_hcc_id,
               hcc_code,
               icd10_codes
        FROM raf_patient_hcc
        WHERE patient_id       = %s
          AND measurement_year = %s
          AND (tenant_id = %s OR %s = '' OR tenant_id IS NULL)
    """
    with raf_cursor() as cur:
        cur.execute(sql, (patient_id, year, tenant_id, tenant_id))
        rows = cur.fetchall() or []

    out: list[dict[str, Any]] = []
    for r in rows:
        raw_icds = r.get("icd10_codes")
        icds: list[str] = []
        if isinstance(raw_icds, list):
            icds = [str(x).strip() for x in raw_icds if x]
        elif isinstance(raw_icds, str):
            s = raw_icds.strip()
            if s.startswith("["):
                import json
                try:
                    parsed = json.loads(s)
                    if isinstance(parsed, list):
                        icds = [str(x).strip() for x in parsed if x]
                except Exception:
                    pass
            if not icds:
                icds = [c.strip() for c in s.split(",") if c.strip()]
        hcc_code = str(r.get("hcc_code") or "")
        out.append(
            {
                "patient_hcc_id": int(r["patient_hcc_id"]),
                "hcc_code": hcc_code,
                "hcc_label": _label_for_hcc(hcc_code),
                "icd10_codes": icds,
            }
        )
    return out


def run_auto_meat_for_patient(
    patient_id: int,
    tenant_id: str = "",
    year: int | None = None,
    max_days_lookback: int = 365,
) -> dict[str, Any]:
    """Run rule-based MEAT extraction for every HCC across every recent note.

    Returns
    -------
    dict with:
        patient_id       : int
        year             : int
        notes_scanned    : int
        hccs_processed   : int
        evidence_written : int
        by_status        : {"COMPLETE": int, "PARTIAL": int, "MISSING": int}
        skipped_no_match : int     HCC/note pairs with no condition mention
    """
    year = year or date.today().year
    summary: dict[str, Any] = {
        "patient_id": patient_id,
        "year": year,
        "notes_scanned": 0,
        "hccs_processed": 0,
        "evidence_written": 0,
        "by_status": {"COMPLETE": 0, "PARTIAL": 0, "MISSING": 0},
        "skipped_no_match": 0,
    }

    hccs = _fetch_patient_hccs(patient_id, year, tenant_id)
    if not hccs:
        logger.info("auto_meat: no HCCs for patient_id=%s year=%s", patient_id, year)
        return summary
    summary["hccs_processed"] = len(hccs)

    try:
        notes = get_all_clinical_notes_for_patient(patient_id) or []
    except Exception as exc:
        logger.warning("auto_meat: note fetch failed for pid=%s: %s", patient_id, exc)
        notes = []

    cutoff = date.today() - timedelta(days=max_days_lookback)
    kept_notes: list[dict[str, Any]] = []
    for n in notes:
        text = (n.get("note_text") or "").strip()
        if not text:
            continue
        nd = _coerce_note_date(n.get("date"))
        if nd is not None and nd < cutoff:
            continue
        kept_notes.append(
            {
                "encounter_id": int(n.get("encounter") or 0) or None,
                "date": nd or date.today(),
                "text": text,
            }
        )
    summary["notes_scanned"] = len(kept_notes)

    if not kept_notes:
        return summary

    for hcc in hccs:
        if not hcc["icd10_codes"]:
            continue
        for note in kept_notes:
            enc_id = note["encounter_id"] or 0
            if not enc_id:
                continue
            best: dict[str, Any] | None = None
            for icd in hcc["icd10_codes"]:
                res = validate_meat(note["text"], icd, hcc["hcc_label"] or None)
                if res["status"] == "MISSING":
                    continue
                if best is None or res["elements_found"] > best["elements_found"]:
                    best = res
                if res["status"] == "COMPLETE":
                    break
            if best is None:
                summary["skipped_no_match"] += 1
                continue

            snips = best.get("evidence_snippets") or []
            excerpt = "\n\n".join(snips)[:4000]
            try:
                meat_evidence_service.store_meat_evidence(
                    patient_hcc_id=hcc["patient_hcc_id"],
                    encounter_id=enc_id,
                    encounter_date=note["date"],
                    meat_monitoring=(snips[0] if best["monitor"] and snips else None),
                    meat_evaluation=(snips[0] if best["evaluate"] and snips else None),
                    meat_assessment=(snips[0] if best["assess"] and snips else None),
                    meat_treatment=(snips[0] if best["treat"] and snips else None),
                    raw_note_excerpt=excerpt,
                    nlp_model="rule-based:meat_validator",
                    confidence=best["elements_found"] / 4.0,
                )
                summary["evidence_written"] += 1
                summary["by_status"][best["status"]] = (
                    summary["by_status"].get(best["status"], 0) + 1
                )
            except Exception as exc:
                logger.warning(
                    "auto_meat: store_meat_evidence failed pid=%s hcc=%s enc=%s: %s",
                    patient_id, hcc["hcc_code"], enc_id, exc,
                )

    # When require_llm_meat_for_billing is True (default), cap the meat_status
    # written by this rule-based pass at 'partial'.  Only the LLM-validated
    # pipeline (task_analyze_encounters_batch → store_analysis_meat) may
    # promote an HCC to 'complete' for RADV-defensible billing.
    _max_status = "partial" if settings.require_llm_meat_for_billing else "complete"
    try:
        meat_evidence_service.update_hcc_meat_status(patient_id, year, max_status=_max_status)
    except Exception as exc:
        logger.warning("auto_meat: update_hcc_meat_status failed pid=%s: %s", patient_id, exc)

    logger.info(
        "auto_meat: pid=%s year=%s notes=%d hccs=%d wrote=%d",
        patient_id, year, summary["notes_scanned"],
        summary["hccs_processed"], summary["evidence_written"],
    )
    return summary
