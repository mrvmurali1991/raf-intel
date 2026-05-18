"""Poll OpenEMR `documents` table, run Gemini vision, persist results.

Closes the gap where uploaded PDFs / scanned charts / faxed reports
sat in OpenEMR untouched by the RAF NLP pipeline.

Idempotent: tracks every document we've processed in
`openemr_document_ingest_log` and skips on repeat.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

from app.db import openemr_cursor, raf_cursor

logger = logging.getLogger(__name__)


def _already_processed(document_id: int) -> bool:
    with raf_cursor() as cur:
        cur.execute(
            "SELECT 1 FROM openemr_document_ingest_log WHERE document_id=%s LIMIT 1",
            (int(document_id),),
        )
        return cur.fetchone() is not None


def _log_processed(
    document_id: int,
    *,
    patient_id: int | None,
    filename: str | None,
    mimetype: str | None,
    size_bytes: int | None,
    suspects_extracted: int,
    status: str = "success",
    skip_reason: str | None = None,
) -> None:
    with raf_cursor() as cur:
        cur.execute(
            """INSERT INTO openemr_document_ingest_log
                 (document_id, patient_id, filename, mimetype, size_bytes,
                  suspects_extracted, status, skip_reason)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
               ON DUPLICATE KEY UPDATE
                 suspects_extracted=VALUES(suspects_extracted),
                 status=VALUES(status), skip_reason=VALUES(skip_reason),
                 extracted_at=NOW()""",
            (
                int(document_id), patient_id,
                (filename or "")[:255], (mimetype or "")[:64], size_bytes,
                int(suspects_extracted), status,
                (skip_reason or "")[:255] or None,
            ),
        )


def _persist_suspect_to_raf(
    *,
    tenant_id: str,
    patient_id: int,
    measurement_year: int,
    s: dict,
) -> int | None:
    """Insert into raf_suspect_conditions (open) if not already present."""
    hcc = str(s.get("hcc_code") or "").strip()
    icd = str(s.get("icd10_code") or "").strip()
    if not hcc or not icd:
        return None
    conf = float(s.get("confidence") or 0.0)
    desc = str(s.get("description") or "")[:255]
    with raf_cursor() as cur:
        # Dedup: same (tenant, patient, year, hcc, icd, open) -> skip
        cur.execute(
            """SELECT id FROM raf_suspect_conditions
               WHERE tenant_id=%s AND patient_id=%s AND measurement_year=%s
                 AND suspect_hcc=%s AND suspect_icd10=%s AND status='open'
               LIMIT 1""",
            (tenant_id, patient_id, measurement_year, int(hcc), icd),
        )
        row = cur.fetchone()
        if row:
            sid = row["id"] if isinstance(row, dict) else row[0]
            return int(sid)
        # Insert new
        cur.execute(
            """INSERT INTO raf_suspect_conditions
                 (tenant_id, patient_id, measurement_year, suspect_hcc,
                  suspect_icd10, evidence_type, evidence_detail,
                  confidence_score, status)
               VALUES (%s,%s,%s,%s,%s,'historical',%s,%s,'open')""",
            (
                tenant_id, patient_id, measurement_year, int(hcc), icd,
                __import__("json").dumps({
                    "source": "gemini_vision",
                    "description": desc,
                    "document_id": s.get("source_document_id"),
                    "document_filename": s.get("source_document_filename"),
                    "page": s.get("page_number"),
                    "evidence_sentence": s.get("evidence_sentence"),
                }),
                conf,
            ),
        )
        return int(cur.lastrowid)


def _persist_meat(
    suspect_id: int,
    patient_hcc_id: int | None,
    s: dict,
) -> None:
    """Record M/E/A/T sentences with document attribution."""
    meat = s.get("meat") or {}
    m = (meat.get("monitoring") or "").strip()
    e = (meat.get("evaluation") or "").strip()
    a = (meat.get("assessment") or "").strip()
    t = (meat.get("treatment") or "").strip()
    if not any([m, e, a, t]):
        return
    completeness = sum(bool(x) for x in (m, e, a, t)) / 4.0
    enc_date = date.today()
    with raf_cursor() as cur:
        cur.execute(
            """INSERT INTO raf_meat_evidence
                 (patient_hcc_id, encounter_id, encounter_date,
                  meat_m, meat_e, meat_a, meat_t,
                  meat_m_present, meat_e_present, meat_a_present, meat_t_present,
                  completeness_score, raw_note_excerpt,
                  source_document_id, source_document_filename,
                  source_document_mimetype, source_document_page, extractor)
               VALUES (%s, 0, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                       %s, %s, %s, %s, 'gemini_vision')""",
            (
                int(patient_hcc_id or 0), enc_date,
                m[:5000] or None, e[:5000] or None,
                a[:5000] or None, t[:5000] or None,
                int(bool(m)), int(bool(e)), int(bool(a)), int(bool(t)),
                completeness,
                (s.get("evidence_sentence") or "")[:1000],
                s.get("source_document_id"),
                (s.get("source_document_filename") or "")[:255] or None,
                (s.get("source_document_mimetype") or "")[:64] or None,
                s.get("page_number"),
            ),
        )


def process_document(
    document_id: int,
    *,
    tenant_id: str,
    measurement_year: int | None = None,
) -> dict[str, Any]:
    """Single-document pipeline: fetch → vision-extract → persist → log.

    Returns a summary dict, never raises.
    """
    if _already_processed(document_id):
        return {"document_id": document_id, "status": "skipped",
                "reason": "already_processed"}

    yr = measurement_year or date.today().year

    from app.services.gemini_document_extractor import (
        extract_from_openemr_document,
    )
    result = extract_from_openemr_document(
        document_id, year=yr, tenant_id=tenant_id,
    )
    suspects = result.get("suspects", [])

    # Need the patient mapping — pull from openemr.documents.foreign_id
    with openemr_cursor() as cur:
        cur.execute(
            "SELECT foreign_id AS pid, mimetype, name FROM documents WHERE id=%s",
            (int(document_id),),
        )
        row = cur.fetchone()
    if not row:
        _log_processed(
            document_id, patient_id=None, filename=None,
            mimetype=None, size_bytes=None, suspects_extracted=0,
            status="error", skip_reason="document_not_in_openemr",
        )
        return {"document_id": document_id, "status": "error",
                "reason": "document_not_in_openemr"}

    rec = dict(row) if isinstance(row, dict) else dict(zip(
        ("pid", "mimetype", "name"), row
    ))
    emr_pid = int(rec.get("pid") or 0) or None

    # Resolve emr_pid -> raf patients.id within tenant
    raf_patient_id: int | None = None
    if emr_pid:
        with raf_cursor() as cur:
            cur.execute(
                """SELECT id FROM patients
                   WHERE emr_pid=%s AND tenant_id=%s AND is_active=1
                   LIMIT 1""",
                (str(emr_pid), tenant_id),
            )
            r = cur.fetchone()
            if r:
                raf_patient_id = int(r["id"] if isinstance(r, dict) else r[0])

    persisted = 0
    if raf_patient_id is not None:
        for s in suspects:
            sid = _persist_suspect_to_raf(
                tenant_id=tenant_id,
                patient_id=raf_patient_id,
                measurement_year=yr,
                s=s,
            )
            if sid is not None:
                persisted += 1
                try:
                    _persist_meat(sid, None, s)
                except Exception as exc:
                    logger.warning(
                        "persist_meat failed sid=%s: %s", sid, exc,
                    )

    _log_processed(
        document_id,
        patient_id=raf_patient_id,
        filename=rec.get("name"),
        mimetype=rec.get("mimetype"),
        size_bytes=None,
        suspects_extracted=persisted,
        status="success" if persisted >= 0 else "error",
        skip_reason=result.get("skipped") or result.get("error"),
    )

    return {
        "document_id": document_id,
        "tenant_id": tenant_id,
        "raf_patient_id": raf_patient_id,
        "suspects_returned_by_vision": len(suspects),
        "suspects_persisted": persisted,
        "status": "success",
    }


def scan_new_documents(
    tenant_id: str,
    *,
    since_id: int | None = None,
    limit: int = 25,
) -> dict[str, Any]:
    """Find OpenEMR documents we haven't processed and run them in sequence."""
    with openemr_cursor() as cur:
        if since_id is not None:
            cur.execute(
                """SELECT id FROM documents
                   WHERE COALESCE(deleted,0)=0 AND id > %s
                   ORDER BY id ASC LIMIT %s""",
                (int(since_id), int(limit)),
            )
        else:
            cur.execute(
                """SELECT id FROM documents
                   WHERE COALESCE(deleted,0)=0
                   ORDER BY id DESC LIMIT %s""",
                (int(limit),),
            )
        ids = [int(r["id"] if isinstance(r, dict) else r[0]) for r in (cur.fetchall() or [])]

    results: list[dict] = []
    for doc_id in ids:
        if _already_processed(doc_id):
            continue
        try:
            results.append(process_document(doc_id, tenant_id=tenant_id))
        except Exception as exc:
            logger.exception("process_document(%s) failed: %s", doc_id, exc)
            results.append({"document_id": doc_id, "status": "error",
                            "error": str(exc)[:300]})

    return {
        "tenant_id": tenant_id,
        "scanned": len(ids),
        "processed": len([r for r in results if r.get("status") == "success"]),
        "results": results,
    }
