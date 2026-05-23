"""FHIR DocumentReference + Binary ingest → Gemini vision → RAF suspects + MEAT.

Covers 70 % of MA-plan EHRs (Epic, Cerner, Athena native) whose documents
arrive via FHIR DocumentReference rather than the OpenEMR local filesystem.

Idempotent: every processed document is tracked in `fhir_documents_processed`.
A second run on the same (tenant_id, fhir_document_id) returns "already_processed".
"""
from __future__ import annotations

import logging
import time
from datetime import date
from typing import Any

from app.db import raf_cursor

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Dedup helpers
# ---------------------------------------------------------------------------

def _already_processed(tenant_id: str, fhir_document_id: str) -> bool:
    with raf_cursor() as cur:
        cur.execute(
            """SELECT 1 FROM fhir_documents_processed
               WHERE tenant_id=%s AND fhir_document_id=%s LIMIT 1""",
            (tenant_id, fhir_document_id),
        )
        return cur.fetchone() is not None


def _log_processed(
    *,
    tenant_id: str,
    fhir_document_id: str,
    raf_patient_id: int | None,
    fhir_url: str | None,
    filename: str | None,
    mimetype: str | None,
    size_bytes: int | None,
    suspects_extracted: int,
    status: str = "success",
) -> None:
    with raf_cursor() as cur:
        cur.execute(
            """INSERT INTO fhir_documents_processed
                 (tenant_id, fhir_document_id, raf_patient_id, fhir_url,
                  filename, mimetype, size_bytes, suspects_extracted, status,
                  processed_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
               ON DUPLICATE KEY UPDATE
                 suspects_extracted = VALUES(suspects_extracted),
                 status             = VALUES(status),
                 processed_at       = NOW()""",
            (
                tenant_id,
                fhir_document_id[:128],
                raf_patient_id,
                (fhir_url or "")[:500] or None,
                (filename or "")[:255] or None,
                (mimetype or "")[:64] or None,
                size_bytes,
                int(suspects_extracted),
                status,
            ),
        )


# ---------------------------------------------------------------------------
# Single-document pipeline
# ---------------------------------------------------------------------------

def _process_one(
    *,
    tenant_id: str,
    raf_patient_id: int,
    fhir_document_id: str,
    attachment_url: str,
    filename: str | None,
    adapter,
    measurement_year: int,
) -> dict[str, Any]:
    """Fetch binary, run vision, persist suspects/MEAT, dedup-log."""
    if _already_processed(tenant_id, fhir_document_id):
        return {
            "fhir_document_id": fhir_document_id,
            "status": "already_processed",
        }

    try:
        raw_bytes, mime_type = adapter.fetch_binary(attachment_url)
    except Exception as exc:
        logger.warning(
            "fetch_binary %s failed: %s", attachment_url, exc
        )
        _log_processed(
            tenant_id=tenant_id,
            fhir_document_id=fhir_document_id,
            raf_patient_id=raf_patient_id,
            fhir_url=attachment_url,
            filename=filename,
            mimetype=None,
            size_bytes=None,
            suspects_extracted=0,
            status="fetch_error",
        )
        return {"fhir_document_id": fhir_document_id, "status": "fetch_error", "error": str(exc)[:300]}

    from app.services.gemini_document_extractor import extract_from_document

    result = extract_from_document(
        doc_bytes=raw_bytes,
        mime_type=mime_type,
        year=measurement_year,
        document_filename=filename,
        tenant_id=tenant_id,
    )
    suspects = result.get("suspects", [])

    from app.services.openemr_document_ingest import _persist_suspect_to_raf, _persist_meat

    persisted = 0
    for s in suspects:
        sid = _persist_suspect_to_raf(
            tenant_id=tenant_id,
            patient_id=raf_patient_id,
            measurement_year=measurement_year,
            s=s,
        )
        if sid is not None:
            persisted += 1
            try:
                _persist_meat(sid, None, s)
            except Exception as exc:
                logger.warning("_persist_meat sid=%s: %s", sid, exc)

    status = "success" if not result.get("skipped") and not result.get("error") else (
        result.get("skipped") or result.get("error") or "skipped"
    )
    _log_processed(
        tenant_id=tenant_id,
        fhir_document_id=fhir_document_id,
        raf_patient_id=raf_patient_id,
        fhir_url=attachment_url,
        filename=filename,
        mimetype=mime_type,
        size_bytes=len(raw_bytes),
        suspects_extracted=persisted,
        status=status,
    )

    return {
        "fhir_document_id": fhir_document_id,
        "status": status,
        "suspects_returned": len(suspects),
        "suspects_persisted": persisted,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def ingest_patient_documents(
    tenant_id: str,
    raf_patient_id: int,
    *,
    since: str | None = None,
    measurement_year: int | None = None,
) -> dict[str, Any]:
    """List DocumentReferences for a patient, fetch each Binary, run vision pipeline.

    Returns a summary dict.  Never raises — errors are captured per-document.
    """
    yr = measurement_year or date.today().year

    # Resolve patient → EMR PID for the FHIR query
    emr_pid: str | None = None
    connection: dict | None = None
    with raf_cursor() as cur:
        cur.execute(
            """SELECT p.emr_pid, ec.id AS conn_id,
                      ec.base_url, ec.token_url, ec.client_id, ec.client_secret,
                      ec.scope, ec.access_token, ec.refresh_token_emr,
                      ec.token_expires_at, ec.extra_config, ec.api_username,
                      ec.api_password
               FROM patients p
               JOIN emr_connections ec ON ec.tenant_id = p.tenant_id
               WHERE p.id = %s AND p.tenant_id = %s AND p.is_active = 1
               LIMIT 1""",
            (raf_patient_id, tenant_id),
        )
        row = cur.fetchone()

    if not row:
        return {
            "tenant_id": tenant_id,
            "raf_patient_id": raf_patient_id,
            "status": "error",
            "error": "patient_not_found_or_no_emr_connection",
            "processed": 0,
        }

    rec = dict(row) if isinstance(row, dict) else dict(zip(
        ("emr_pid", "conn_id", "base_url", "token_url", "client_id",
         "client_secret", "scope", "access_token", "refresh_token_emr",
         "token_expires_at", "extra_config", "api_username", "api_password"),
        row,
    ))
    emr_pid = str(rec["emr_pid"] or "")
    if not emr_pid:
        return {
            "tenant_id": tenant_id,
            "raf_patient_id": raf_patient_id,
            "status": "error",
            "error": "emr_pid_missing",
            "processed": 0,
        }

    connection = {
        "id": rec.get("conn_id"),
        "base_url": rec.get("base_url"),
        "token_url": rec.get("token_url"),
        "client_id": rec.get("client_id"),
        "client_secret": rec.get("client_secret"),
        "scope": rec.get("scope"),
        "access_token": rec.get("access_token"),
        "refresh_token_emr": rec.get("refresh_token_emr"),
        "token_expires_at": rec.get("token_expires_at"),
        "extra_config": rec.get("extra_config"),
        "api_username": rec.get("api_username"),
        "api_password": rec.get("api_password"),
    }

    from app.services.vendor_adapters.openemr_fhir import OpenEMRFhirAdapter

    adapter = OpenEMRFhirAdapter(connection)

    try:
        entries = adapter.list_document_references(
            emr_pid, since=since, _count=50
        )
    except Exception as exc:
        logger.debug("swallowed exception", exc_info=True)
        return {
            "tenant_id": tenant_id,
            "raf_patient_id": raf_patient_id,
            "status": "error",
            "error": f"list_document_references failed: {exc!s:.300}",
            "processed": 0,
        }

    results: list[dict] = []
    for entry in entries:
        resource = entry.get("resource", {})
        doc_id = resource.get("id", "")
        if not doc_id:
            continue

        content_list = resource.get("content") or []
        if not content_list:
            continue
        attachment = content_list[0].get("attachment") or {}
        attach_url = attachment.get("url") or ""
        if not attach_url:
            # Some servers inline base64 data — skip those (handled by fetch_document_references)
            continue

        fname = attachment.get("title") or attachment.get("url", "").split("/")[-1] or None

        try:
            r = _process_one(
                tenant_id=tenant_id,
                raf_patient_id=raf_patient_id,
                fhir_document_id=doc_id,
                attachment_url=attach_url,
                filename=fname,
                adapter=adapter,
                measurement_year=yr,
            )
        except Exception as exc:
            logger.exception("_process_one doc=%s: %s", doc_id, exc)
            r = {"fhir_document_id": doc_id, "status": "error", "error": str(exc)[:300]}

        results.append(r)

    already = sum(1 for r in results if r.get("status") == "already_processed")
    success = sum(1 for r in results if r.get("status") == "success")
    total_suspects = sum(r.get("suspects_persisted", 0) for r in results)

    return {
        "tenant_id": tenant_id,
        "raf_patient_id": raf_patient_id,
        "documents_found": len(entries),
        "documents_processed": len(results),
        "already_processed": already,
        "newly_processed": success,
        "suspects_persisted": total_suspects,
        "results": results,
    }


def ingest_tenant_documents(
    tenant_id: str,
    *,
    since: str | None = None,
    measurement_year: int | None = None,
    rate_limit_sec: float = 1.0,
) -> dict[str, Any]:
    """Iterate all active patients in tenant and ingest their FHIR documents.

    Rate-limited at ``rate_limit_sec`` per patient to be EHR-polite (default 1/s).
    """
    with raf_cursor() as cur:
        cur.execute(
            """SELECT id FROM patients
               WHERE tenant_id = %s AND is_active = 1
               ORDER BY id ASC""",
            (tenant_id,),
        )
        rows = cur.fetchall() or []

    patient_ids = [
        int(r["id"] if isinstance(r, dict) else r[0]) for r in rows
    ]

    all_results: list[dict] = []
    total_suspects = 0

    for pid in patient_ids:
        summary = ingest_patient_documents(
            tenant_id,
            pid,
            since=since,
            measurement_year=measurement_year,
        )
        all_results.append(summary)
        total_suspects += summary.get("suspects_persisted", 0)
        if rate_limit_sec > 0:
            time.sleep(rate_limit_sec)

    return {
        "tenant_id": tenant_id,
        "patients_iterated": len(patient_ids),
        "suspects_persisted": total_suspects,
        "patient_summaries": all_results,
    }
