"""
ai_pipeline/orchestrator.py
===========================

End-to-end Celery orchestrator that chains every AI pipeline stage for a
single patient. Each stage is wrapped in try/except and failures are logged
to ``ai_analysis_runs`` so one agent crashing does not abort the whole run.

Agent 3  -> eligibility.can_run_analysis / record_run_start / record_run_finish
Agent 4  -> context_bundle.assemble_bundle
Agent 5  -> extractor.extract_blind / extract_contextual (per note)
Agent 6  -> meat_extractor.extract_meat_evidence (per candidate, per note)
Agent 7  -> suspect_engine.detect_suspects
Mapper   -> hcc_mapper.map_icd_to_hcc
Agent 9  -> provider_query.generate_query

Tables populated (migration 017): ai_hcc_candidates, ai_suspect_candidates,
ai_meat_evidence.  Provider queries are persisted into ai_provider_queries
if that table exists; otherwise logged.

Beat schedule: ``ai_pipeline.schedule_daily`` runs at 02:00 local to the
Celery worker, fetches eligible patients per tenant, and enqueues one
``ai_pipeline.run_for_patient`` task per patient.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, is_dataclass
from datetime import datetime
from typing import Any, Iterable, Optional

from celery.schedules import crontab

from app.services.job_service import celery_app
from app.services.ai_pipeline import (
    context_bundle,
    eligibility,
    extractor,
    meat_extractor,
    provider_query,
    suspect_engine,
)
from app.services.ai_pipeline.hcc_mapper import map_icd_to_hcc
from app.db import raf_cursor

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _log_run_error(run_id: Optional[int], stage: str, exc: BaseException) -> None:
    logger.exception("ai_pipeline stage %s failed (run=%s)", stage, run_id)
    if run_id is None:
        return
    try:
        with raf_cursor() as cur:
            # MySQL-compatible JSON append: build the new error entry in
            # Python, then JSON_ARRAY_APPEND onto the existing array (coalesced
            # to an empty array when NULL).
            new_entry = {
                "stage": stage,
                "error": str(exc),
                "at": datetime.utcnow().isoformat(),
            }
            cur.execute(
                """
                UPDATE ai_analysis_runs
                   SET errors = JSON_ARRAY_APPEND(
                                    COALESCE(errors, JSON_ARRAY()),
                                    '$',
                                    CAST(%s AS JSON))
                 WHERE id = %s
                """,
                (json.dumps(new_entry), run_id),
            )
    except Exception:
        logger.exception("failed to persist stage error for run=%s", run_id)


def _to_jsonable(obj: Any) -> Any:
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(v) for v in obj]
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "to_dict"):
        try:
            return obj.to_dict()
        except Exception:
            pass
    if is_dataclass(obj):
        return asdict(obj)
    if hasattr(obj, "__dict__"):
        return {k: _to_jsonable(v) for k, v in vars(obj).items() if not k.startswith("_")}
    return str(obj)


# ---------------------------------------------------------------------------
# Main task
# ---------------------------------------------------------------------------

@celery_app.task(
    name="ai_pipeline.run_for_patient",
    bind=True,
    queue="pipeline",
    max_retries=2,
    default_retry_delay=120,
)
def run_for_patient(
    self,
    patient_id: int,
    tenant_id: str,
    trigger_reason: str = "scheduled",
) -> dict[str, Any]:
    """Run the full AI pipeline for a single patient within a tenant."""
    run_id: Optional[int] = None
    summary: dict[str, Any] = {
        "patient_id": patient_id,
        "tenant_id": tenant_id,
        "trigger_reason": trigger_reason,
        "run_id": None,
        "stages": {},
    }

    # --- (a) eligibility / rate limit ----------------------------------
    try:
        if not eligibility.can_run_analysis(str(patient_id), tenant_id):
            summary["stages"]["eligibility"] = "skipped_over_limit"
            return summary
    except Exception as exc:
        _log_run_error(None, "eligibility", exc)
        summary["stages"]["eligibility"] = f"error: {exc}"
        return summary

    # --- (b) record_run_start ------------------------------------------
    try:
        run_id = eligibility.record_run_start(
            patient_id=str(patient_id),
            tenant_id=tenant_id,
            trigger_reason=trigger_reason,
        )
        summary["run_id"] = run_id
    except Exception as exc:
        _log_run_error(None, "record_run_start", exc)
        return summary

    final_status = "success"

    # --- (c) context bundle --------------------------------------------
    bundle = None
    try:
        bundle = context_bundle.assemble_bundle(patient_id)
        summary["stages"]["context_bundle"] = "ok"
    except Exception as exc:
        _log_run_error(run_id, "context_bundle", exc)
        final_status = "failed"

    if bundle is None:
        try:
            eligibility.record_run_finish(run_id=run_id, status="failed")
        except Exception:
            pass
        return summary

    demo = getattr(bundle, "demographics", None)
    age = getattr(demo, "age", None) if demo else None
    sex = getattr(demo, "sex", None) if demo else None
    has_esrd = bool(getattr(demo, "has_esrd", False)) if demo else False
    model_version = getattr(bundle, "hcc_model_version", "V28") or "V28"
    notes = list(getattr(bundle, "clinical_notes", []) or [])

    # Build encounter lookup (by id, and by date) from the bundle so each
    # note's MEAT extraction can receive the REAL encounter_type, not a
    # hardcoded "office visit" default. Unknown encounter_type passes as
    # None => meat_extractor.is_face_to_face_encounter returns False
    # (RADV-safe).
    encounters = list(getattr(bundle, "prior_encounters_this_year", []) or [])
    enc_by_id: dict[str, Any] = {}
    enc_by_date: dict[str, Any] = {}
    for _enc in encounters:
        _eid = getattr(_enc, "encounter_id", None)
        if _eid is not None:
            enc_by_id[str(_eid)] = _enc
        _edate = getattr(_enc, "date", None)
        if _edate and _edate not in enc_by_date:
            enc_by_date[_edate] = _enc

    def _resolve_encounter_for_note(note) -> tuple[Optional[str], Optional[str]]:
        eid = getattr(note, "encounter_id", None)
        ndate = getattr(note, "date", None)
        enc = None
        if eid is not None and str(eid) in enc_by_id:
            enc = enc_by_id[str(eid)]
        elif ndate and ndate in enc_by_date:
            enc = enc_by_date[ndate]
        if enc is None:
            return None, ndate
        return getattr(enc, "type", None), getattr(enc, "date", None) or ndate

    # --- (d) per-note extraction (blind + contextual) ------------------
    all_candidates: list[dict] = []
    for note in notes:
        note_id = getattr(note, "id", None)
        note_text = getattr(note, "text", "") or ""
        if not note_text.strip():
            continue
        enc_type, enc_date = _resolve_encounter_for_note(note)
        try:
            blind = extractor.extract_blind(note_text) or []
            ctx = extractor.extract_contextual(note_text, bundle, blind) or []
            for c in ctx:
                all_candidates.append({
                    "candidate": c,
                    "note_id": note_id,
                    "note_text": note_text,
                    "encounter_type": enc_type,
                    "encounter_date": enc_date,
                    "source": "contextual",
                })
        except Exception as exc:
            _log_run_error(run_id, f"extract:note={note_id}", exc)
    summary["stages"]["extract"] = {"candidates": len(all_candidates)}

    # --- (e) MEAT extraction per candidate -----------------------------
    for entry in all_candidates:
        cand = entry["candidate"]
        try:
            evidence = meat_extractor.extract_meat_evidence(
                cand,
                entry["note_text"],
                context={
                    "encounter_type": entry.get("encounter_type"),
                    "encounter_date": entry.get("encounter_date"),
                },
            )
            entry["meat"] = evidence
        except Exception as exc:
            _log_run_error(run_id, f"meat:{getattr(cand, 'icd10', '?')}", exc)
            entry["meat"] = None

    # --- (f) suspect engine --------------------------------------------
    suspects: list[Any] = []
    try:
        bundle_dict = _to_jsonable(bundle)
        suspects = suspect_engine.detect_suspects(bundle_dict, use_llm=True) or []
        summary["stages"]["suspects"] = len(suspects)
    except Exception as exc:
        _log_run_error(run_id, "suspect_engine", exc)

    # --- (g) map ICD->HCC for any candidate missing hcc ----------------
    mapped_entries: list[dict] = []
    for entry in all_candidates:
        cand = entry["candidate"]
        icd10 = getattr(cand, "icd10", "") or ""
        hcc = getattr(cand, "hcc", "") or ""
        hcc_label = None
        mapper_source = None
        if not hcc and icd10:
            try:
                m = map_icd_to_hcc(icd10, age, sex, model_version, has_esrd=has_esrd)
                if m:
                    hcc = m.hcc
                    hcc_label = m.label
                    mapper_source = m.source
            except Exception as exc:
                _log_run_error(run_id, f"map:{icd10}", exc)
        entry["hcc"] = hcc
        entry["hcc_label"] = hcc_label
        entry["mapper_source"] = mapper_source
        if hcc:
            mapped_entries.append(entry)
    summary["stages"]["mapped"] = len(mapped_entries)

    # --- (h) persist candidates + MEAT + suspects ----------------------
    candidate_id_by_entry: dict[int, int] = {}
    suspect_id_list: list[int] = []
    try:
        candidate_id_by_entry, suspect_id_list = _persist_results(
            run_id, patient_id, model_version, mapped_entries, suspects
        )
        summary["stages"]["persist"] = "ok"
    except Exception as exc:
        _log_run_error(run_id, "persist", exc)
        final_status = "failed"

    # --- (i) provider query generation ---------------------------------
    pq_count = 0
    for entry in mapped_entries:
        cand = entry["candidate"]
        try:
            pq = provider_query.generate_query(cand, bundle)
            _persist_provider_query(run_id, patient_id,
                                    candidate_id_by_entry.get(id(entry)),
                                    None, pq)
            pq_count += 1
        except Exception as exc:
            _log_run_error(run_id, f"provider_query:{getattr(cand, 'icd10', '?')}", exc)
    for sid, susp in zip(suspect_id_list, suspects):
        try:
            pq = provider_query.generate_query(susp, bundle)
            _persist_provider_query(run_id, patient_id, None, sid, pq)
            pq_count += 1
        except Exception as exc:
            _log_run_error(run_id, f"provider_query:suspect:{getattr(susp, 'icd10', '?')}", exc)
    summary["stages"]["provider_queries"] = pq_count

    # --- (j) record_run_finish -----------------------------------------
    try:
        eligibility.record_run_finish(run_id=run_id, status=final_status)
    except Exception as exc:
        _log_run_error(run_id, "record_run_finish", exc)

    return summary


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _persist_results(
    run_id: int,
    patient_id: int,
    model_version: str,
    mapped_entries: list[dict],
    suspects: list[Any],
) -> tuple[dict[int, int], list[int]]:
    """Insert candidates, MEAT evidence, and suspects. Returns
    (candidate_row_id_by_entry_id, suspect_row_ids)."""
    cand_ids: dict[int, int] = {}
    suspect_ids: list[int] = []
    with raf_cursor() as cur:
        for entry in mapped_entries:
            cand = entry["candidate"]
            cur.execute(
                """
                INSERT INTO ai_hcc_candidates
                    (run_id, patient_id, icd10, hcc, hcc_label, model_version,
                     source, mapper_source, confidence, note_id, gate_passed)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,TRUE)
                """,
                (
                    run_id,
                    patient_id,
                    getattr(cand, "icd10", "") or "",
                    entry.get("hcc") or "",
                    entry.get("hcc_label"),
                    model_version,
                    entry.get("source", "contextual"),
                    entry.get("mapper_source"),
                    getattr(cand, "confidence", None),
                    entry.get("note_id"),
                ),
            )
            cand_id = cur.lastrowid
            cand_ids[id(entry)] = cand_id

            meat = entry.get("meat")
            if meat is not None:
                for meat_type, quote in (
                    ("monitor", getattr(meat, "m_quote", None)),
                    ("evaluate", getattr(meat, "e_quote", None)),
                    ("assess", getattr(meat, "a_quote", None)),
                    ("treat", getattr(meat, "t_quote", None)),
                ):
                    if not quote:
                        continue
                    cur.execute(
                        """
                        INSERT INTO ai_meat_evidence
                            (run_id, candidate_id, meat_type, quote, note_id)
                        VALUES (%s,%s,%s,%s,%s)
                        """,
                        (run_id, cand_id, meat_type, quote, entry.get("note_id")),
                    )

        for s in suspects:
            evidence_refs = _to_jsonable(getattr(s, "supporting_evidence", []))
            cur.execute(
                """
                INSERT INTO ai_suspect_candidates
                    (run_id, patient_id, hcc, icd10, rule_id, rationale,
                     confidence, evidence_refs)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    run_id,
                    patient_id,
                    getattr(s, "hcc", None),
                    getattr(s, "icd10", None),
                    getattr(s, "rule_id", None) or getattr(s, "source", None),
                    getattr(s, "reason", None) or getattr(s, "rationale", None),
                    getattr(s, "confidence", None),
                    json.dumps(evidence_refs) if evidence_refs is not None else None,
                ),
            )
            suspect_ids.append(cur.lastrowid)
    return cand_ids, suspect_ids


def _persist_provider_query(
    run_id: Optional[int],
    patient_id: int,
    candidate_id: Optional[int],
    suspect_candidate_id: Optional[int],
    pq: Any,
) -> None:
    """Persist a ProviderQuery. Table ``ai_provider_queries`` is optional
    (added in a later migration) — if absent, log instead."""
    if run_id is None:
        return
    payload = {
        "to_provider_id": getattr(pq, "to_provider_id", None),
        "subject": getattr(pq, "subject", ""),
        "body": getattr(pq, "body", ""),
        "supporting_citations": _to_jsonable(getattr(pq, "supporting_citations", [])),
        "compliance_flags": list(getattr(pq, "compliance_flags", []) or []),
    }
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                INSERT INTO ai_provider_queries
                    (run_id, patient_id, candidate_id, suspect_candidate_id,
                     to_provider_id, subject, body, supporting_citations,
                     compliance_flags, requires_human_review)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    run_id,
                    patient_id,
                    candidate_id,
                    suspect_candidate_id,
                    payload["to_provider_id"],
                    payload["subject"],
                    payload["body"],
                    json.dumps(payload["supporting_citations"]),
                    json.dumps(payload["compliance_flags"]),
                    bool(payload["compliance_flags"]),
                ),
            )
    except Exception as exc:
        logger.warning(
            "ai_provider_queries insert skipped (table may not exist yet): %s; payload=%s",
            exc, payload,
        )


# ---------------------------------------------------------------------------
# Daily fan-out
# ---------------------------------------------------------------------------

def _all_tenant_ids() -> list[str]:
    """Return tenant_ids that have at least one patient. Best-effort: fall
    back to a single 'default' tenant if the lookup fails."""
    try:
        with raf_cursor() as cur:
            cur.execute("SELECT DISTINCT tenant_id FROM patients WHERE tenant_id IS NOT NULL")
            rows = cur.fetchall() or []
            out = [(r["tenant_id"] if isinstance(r, dict) else r[0]) for r in rows]
            return [t for t in out if t]
    except Exception as exc:
        logger.warning("could not enumerate tenants: %s", exc)
        return ["default"]


@celery_app.task(name="ai_pipeline.schedule_daily", queue="pipeline")
def schedule_daily() -> dict[str, int]:
    """Enqueue run_for_patient for every eligible patient across tenants."""
    enqueued = 0
    for tenant_id in _all_tenant_ids():
        try:
            pids: Iterable[str] = eligibility.get_eligible_patients(tenant_id) or []
        except Exception as exc:
            logger.warning("get_eligible_patients(%s) failed: %s", tenant_id, exc)
            continue
        for pid in pids:
            try:
                run_for_patient.apply_async(
                    kwargs={
                        "patient_id": int(pid),
                        "tenant_id": tenant_id,
                        "trigger_reason": "daily_beat",
                    },
                    queue="pipeline",
                )
                enqueued += 1
            except Exception as exc:
                logger.warning("enqueue failed for %s/%s: %s", tenant_id, pid, exc)
    return {"enqueued": enqueued}


# ---------------------------------------------------------------------------
# Register Beat entry (applied on worker/beat import)
# ---------------------------------------------------------------------------
try:
    celery_app.conf.beat_schedule.setdefault(
        "ai-pipeline-daily-2am",
        {
            "task": "ai_pipeline.schedule_daily",
            "schedule": crontab(hour=2, minute=0),
            "options": {"queue": "pipeline"},
        },
    )
except Exception as exc:  # pragma: no cover
    logger.warning("could not register ai_pipeline beat entry: %s", exc)


__all__ = ["run_for_patient", "schedule_daily"]
