"""
Reveleer integration glue — pull charts, push HCC suspects.

pull_charts_from_reveleer
    Lists charts Reveleer has retrieved → downloads each → runs Gemini
    vision → persists suspects into raf_suspect_conditions → logs into
    reveleer_charts_pulled.

push_suspects_to_reveleer
    Reads open/accepted gemini_vision suspects not yet pushed → submits
    to Reveleer's bulk endpoint → logs each result into
    reveleer_suspects_pushed.

Both functions are idempotent: UNIQUE indexes on reveleer_chart_id /
raf_suspect_id prevent double-processing on retry.
"""
from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any

from app.db import raf_cursor

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal DB helpers
# ---------------------------------------------------------------------------


def _chart_already_pulled(reveleer_chart_id: str) -> bool:
    with raf_cursor() as cur:
        cur.execute(
            "SELECT 1 FROM reveleer_charts_pulled WHERE reveleer_chart_id=%s LIMIT 1",
            (reveleer_chart_id,),
        )
        return cur.fetchone() is not None


def _insert_chart_pulled(
    *,
    tenant_id: str,
    reveleer_chart_id: str,
    raf_patient_id: int | None,
    filename: str,
    mimetype: str,
    size_bytes: int,
    suspects_extracted: int,
    processed: int = 1,
) -> int:
    with raf_cursor() as cur:
        cur.execute(
            """INSERT INTO reveleer_charts_pulled
                 (tenant_id, reveleer_chart_id, raf_patient_id, filename,
                  mimetype, size_bytes, pulled_at, processed, suspects_extracted)
               VALUES (%s, %s, %s, %s, %s, %s, NOW(), %s, %s)
               ON DUPLICATE KEY UPDATE
                 processed=VALUES(processed),
                 suspects_extracted=VALUES(suspects_extracted)""",
            (
                tenant_id,
                reveleer_chart_id,
                raf_patient_id,
                filename[:255],
                mimetype[:64],
                size_bytes,
                processed,
                suspects_extracted,
            ),
        )
        return int(cur.lastrowid or 0)


def _resolve_patient(tenant_id: str, patient_external_id: str) -> int | None:
    """Map Reveleer patient_external_id -> RAF patients.id."""
    with raf_cursor() as cur:
        cur.execute(
            """SELECT id FROM patients
               WHERE tenant_id=%s
                 AND (external_id=%s OR emr_pid=%s)
                 AND is_active=1
               LIMIT 1""",
            (tenant_id, patient_external_id, patient_external_id),
        )
        row = cur.fetchone()
    if not row:
        return None
    return int(row["id"] if isinstance(row, dict) else row[0])


def _persist_suspect(
    *,
    tenant_id: str,
    patient_id: int,
    measurement_year: int,
    s: dict,
    source_document_id: str | None,
) -> int | None:
    hcc = str(s.get("hcc_code") or "").strip()
    icd = str(s.get("icd10_code") or "").strip()
    if not hcc or not icd:
        return None
    conf = float(s.get("confidence") or 0.0)
    evidence_detail = json.dumps({
        "source": "gemini_vision",
        "description": str(s.get("description") or "")[:255],
        "document_id": source_document_id,
        "evidence_sentence": s.get("evidence_sentence"),
        "page": s.get("page_number"),
    })
    with raf_cursor() as cur:
        cur.execute(
            """SELECT id FROM raf_suspect_conditions
               WHERE tenant_id=%s AND patient_id=%s AND measurement_year=%s
                 AND suspect_hcc=%s AND suspect_icd10=%s AND status='open'
               LIMIT 1""",
            (tenant_id, patient_id, measurement_year, int(hcc), icd),
        )
        row = cur.fetchone()
        if row:
            return int(row["id"] if isinstance(row, dict) else row[0])
        cur.execute(
            """INSERT INTO raf_suspect_conditions
                 (tenant_id, patient_id, measurement_year, suspect_hcc,
                  suspect_icd10, evidence_type, evidence_detail,
                  confidence_score, status)
               VALUES (%s,%s,%s,%s,%s,'historical',%s,%s,'open')""",
            (
                tenant_id, patient_id, measurement_year,
                int(hcc), icd, evidence_detail, conf,
            ),
        )
        return int(cur.lastrowid)


def _get_unpushed_suspects(tenant_id: str, raf_patient_id: int) -> list[dict]:
    """Return open gemini_vision suspects not yet pushed to Reveleer."""
    with raf_cursor() as cur:
        cur.execute(
            """SELECT rsc.id, rsc.suspect_hcc, rsc.suspect_icd10,
                      rsc.confidence_score, rsc.evidence_detail
               FROM raf_suspect_conditions rsc
               LEFT JOIN reveleer_suspects_pushed rsp ON rsp.raf_suspect_id = rsc.id
               WHERE rsc.tenant_id=%s
                 AND rsc.patient_id=%s
                 AND rsc.status='open'
                 AND rsc.evidence_type='historical'
                 AND rsp.id IS NULL""",
            (tenant_id, raf_patient_id),
        )
        rows = cur.fetchall()
    result: list[dict] = []
    for row in rows:
        r = dict(row) if isinstance(row, dict) else dict(
            zip(("id", "suspect_hcc", "suspect_icd10", "confidence_score", "evidence_detail"), row)
        )
        try:
            detail = json.loads(r.get("evidence_detail") or "{}")
        except (json.JSONDecodeError, TypeError):
            detail = {}
        if detail.get("source") != "gemini_vision":
            continue
        evidence_sentence = str(detail.get("evidence_sentence") or "").strip()
        if not evidence_sentence:
            continue  # Reveleer rejects empty evidence_sentence
        result.append({
            "id": r["id"],
            "hcc": str(r["suspect_hcc"]),
            "icd10": str(r["suspect_icd10"]),
            "confidence": float(r.get("confidence_score") or 0.0),
            "evidence_sentence": evidence_sentence,
            "source_document_id": str(detail.get("document_id") or ""),
        })
    return result


def _record_push_result(
    *,
    tenant_id: str,
    suspect_id: int,
    reveleer_response_id: str | None,
    status: str,
    error_text: str | None,
) -> None:
    with raf_cursor() as cur:
        cur.execute(
            """INSERT INTO reveleer_suspects_pushed
                 (tenant_id, raf_suspect_id, pushed_at,
                  reveleer_response_id, status, error_text)
               VALUES (%s, %s, NOW(), %s, %s, %s)
               ON DUPLICATE KEY UPDATE
                 pushed_at=NOW(), reveleer_response_id=VALUES(reveleer_response_id),
                 status=VALUES(status), error_text=VALUES(error_text)""",
            (
                tenant_id,
                suspect_id,
                (reveleer_response_id or "")[:128] or None,
                status,
                (error_text or "")[:1000] or None,
            ),
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def pull_charts_from_reveleer(
    tenant_id: str,
    since: str | None = None,
) -> dict[str, Any]:
    """Pull new ready charts from Reveleer, run vision extraction, persist.

    Parameters
    ----------
    tenant_id:
        RAF tenant identifier.
    since:
        ISO-8601 datetime; only charts updated after this are fetched.

    Returns
    -------
    dict
        Summary with ``charts_found``, ``charts_skipped``, ``charts_processed``,
        ``suspects_extracted``.
    """
    from app.services.partners.reveleer import ReveleerClient
    from app.services.gemini_document_extractor import extract_from_document

    client = ReveleerClient.from_env()
    yr = date.today().year

    charts = client.list_retrieved_charts(since=since, status="ready")
    found = len(charts)
    skipped = processed = suspects_total = 0

    for chart in charts:
        chart_id = str(chart.get("chart_id") or "")
        if not chart_id:
            logger.warning("pull_charts_from_reveleer: chart missing chart_id, skipping")
            skipped += 1
            continue

        if _chart_already_pulled(chart_id):
            skipped += 1
            continue

        patient_external_id = str(chart.get("patient_external_id") or "")
        filename = str(chart.get("filename") or chart_id)
        mimetype = str(chart.get("mimetype") or "application/octet-stream")

        try:
            doc_bytes, detected_mime = client.download_chart(chart_id)
        except Exception as exc:
            logger.error(
                "pull_charts_from_reveleer: download failed chart_id=%s: %s", chart_id, exc
            )
            skipped += 1
            continue

        if detected_mime and detected_mime != "application/octet-stream":
            mimetype = detected_mime

        raf_patient_id = _resolve_patient(tenant_id, patient_external_id) if patient_external_id else None

        extraction = extract_from_document(
            doc_bytes=doc_bytes,
            mime_type=mimetype,
            year=yr,
            document_id=None,
            document_filename=filename,
            tenant_id=tenant_id,
        )
        suspects = extraction.get("suspects", [])
        suspects_count = 0

        if raf_patient_id is not None:
            for s in suspects:
                sid = _persist_suspect(
                    tenant_id=tenant_id,
                    patient_id=raf_patient_id,
                    measurement_year=yr,
                    s=s,
                    source_document_id=chart_id,
                )
                if sid is not None:
                    suspects_count += 1

        _insert_chart_pulled(
            tenant_id=tenant_id,
            reveleer_chart_id=chart_id,
            raf_patient_id=raf_patient_id,
            filename=filename,
            mimetype=mimetype,
            size_bytes=len(doc_bytes),
            suspects_extracted=suspects_count,
        )
        processed += 1
        suspects_total += suspects_count

    summary = {
        "charts_found": found,
        "charts_skipped": skipped,
        "charts_processed": processed,
        "suspects_extracted": suspects_total,
    }
    logger.info("pull_charts_from_reveleer tenant=%s summary=%s", tenant_id, summary)
    return summary


def push_suspects_to_reveleer(
    tenant_id: str,
    raf_patient_id: int,
) -> dict[str, Any]:
    """Push open gemini_vision suspects to Reveleer for patient.

    Only suspects with a non-empty ``evidence_sentence`` are submitted
    (Reveleer rejects empty evidence).  Already-pushed suspects are skipped
    via LEFT JOIN on ``reveleer_suspects_pushed``.

    Returns
    -------
    dict
        Summary with ``suspects_found``, ``pushed``, ``failed``, ``skipped``.
    """
    from app.services.partners.reveleer import ReveleerClient

    client = ReveleerClient.from_env()

    # Resolve Reveleer patient external id from RAF patient record
    with raf_cursor() as cur:
        cur.execute(
            "SELECT external_id FROM patients WHERE id=%s AND tenant_id=%s LIMIT 1",
            (raf_patient_id, tenant_id),
        )
        row = cur.fetchone()
    if not row:
        logger.warning(
            "push_suspects_to_reveleer: patient %s not found in tenant %s",
            raf_patient_id, tenant_id,
        )
        return {"suspects_found": 0, "pushed": 0, "failed": 0, "skipped": 0}

    patient_external_id = str(row["external_id"] if isinstance(row, dict) else row[0])
    suspects = _get_unpushed_suspects(tenant_id, raf_patient_id)
    found = len(suspects)

    if not suspects:
        return {"suspects_found": 0, "pushed": 0, "failed": 0, "skipped": 0}

    # Build Reveleer payload shape
    payload_suspects = [
        {
            "hcc": s["hcc"],
            "icd10": s["icd10"],
            "confidence": s["confidence"],
            "evidence_sentence": s["evidence_sentence"],
            "source_document_id": s["source_document_id"],
        }
        for s in suspects
    ]

    pushed = failed = skipped = 0
    try:
        result = client.submit_hcc_suspects(patient_external_id, payload_suspects)
        response_id = str(result.get("response_id") or "")
        # Record each suspect as pushed
        for s in suspects:
            _record_push_result(
                tenant_id=tenant_id,
                suspect_id=int(s["id"]),
                reveleer_response_id=response_id,
                status="success",
                error_text=None,
            )
        pushed = len(suspects)
    except Exception as exc:
        err_text = str(exc)[:1000]
        logger.error(
            "push_suspects_to_reveleer: submit failed patient=%s tenant=%s: %s",
            raf_patient_id, tenant_id, exc,
        )
        for s in suspects:
            _record_push_result(
                tenant_id=tenant_id,
                suspect_id=int(s["id"]),
                reveleer_response_id=None,
                status="failed",
                error_text=err_text,
            )
        failed = len(suspects)

    summary = {
        "suspects_found": found,
        "pushed": pushed,
        "failed": failed,
        "skipped": skipped,
    }
    logger.info(
        "push_suspects_to_reveleer tenant=%s patient=%s summary=%s",
        tenant_id, raf_patient_id, summary,
    )
    return summary
