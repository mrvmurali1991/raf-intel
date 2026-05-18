"""HIE patient sync orchestrator.

Entry point: sync_patient_from_hie(tenant_id, raf_patient_id, network)

Flow:
  1. Resolve patient demographics from the RAF DB.
  2. Run discover_patient against the named HIE network.
  3. Persist/update hie_patient_matches rows (best confidence match).
  4. list_document_references for the best-match HIE patient ID.
  5. For each document, fetch_binary -> route through Gemini vision extractor.
  6. Insert suspects into raf_suspect_conditions via existing pipeline logic.
  7. Log every query into hie_queries_log (latency, doc count, errors).

Idempotency: skip any document whose fhir_document_id already exists in
fhir_documents_processed (unique constraint on that column).

Rate limiting is enforced inside each HIEAdapter._rate_limited_call().
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

from app.db import raf_cursor
from app.services.gemini_document_extractor import extract_from_document

logger = logging.getLogger(__name__)

_SUPPORTED_NETWORKS = ("commonwell", "carequality")


def _get_adapter(network: str):
    """Lazy-import and instantiate the correct adapter."""
    if network == "commonwell":
        from app.services.hie.commonwell import CommonWellAdapter
        return CommonWellAdapter()
    if network == "carequality":
        from app.services.hie.carequality import CarequalityAdapter
        return CarequalityAdapter()
    raise ValueError(f"Unsupported HIE network: {network!r}")


def _fetch_patient_demographics(raf_patient_id: int, tenant_id: str) -> dict[str, Any] | None:
    """Return basic demographics needed for HIE patient matching."""
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT first_name, last_name, date_of_birth, sex, mbi
            FROM patients
            WHERE id = %s AND tenant_id = %s
            LIMIT 1
            """,
            (raf_patient_id, tenant_id),
        )
        row = cur.fetchone()
    if not row:
        return None
    return {
        "first_name": row.get("first_name") or row[0],
        "last_name": row.get("last_name") or row[1],
        "dob": str(row.get("date_of_birth") or row[2] or ""),
        "sex": row.get("sex") or row[3] or "unknown",
        "mbi": row.get("mbi") or (row[4] if len(row) > 4 else None),
    }


def _upsert_hie_match(
    tenant_id: str,
    raf_patient_id: int,
    network: str,
    match: dict[str, Any],
    doc_count: int,
) -> None:
    with raf_cursor() as cur:
        cur.execute(
            """
            INSERT INTO hie_patient_matches
              (tenant_id, raf_patient_id, network, hie_patient_id,
               confidence, matched_at, last_queried_at, document_count)
            VALUES (%s, %s, %s, %s, %s, NOW(), NOW(), %s)
            ON DUPLICATE KEY UPDATE
              confidence        = VALUES(confidence),
              last_queried_at   = NOW(),
              document_count    = VALUES(document_count)
            """,
            (
                tenant_id,
                raf_patient_id,
                network,
                match["hie_patient_id"],
                match["confidence"],
                doc_count,
            ),
        )


def _log_hie_query(
    tenant_id: str,
    network: str,
    raf_patient_id: int,
    query_type: str,
    status: str,
    latency_ms: int,
    documents_returned: int = 0,
    error_text: str | None = None,
) -> None:
    with raf_cursor() as cur:
        cur.execute(
            """
            INSERT INTO hie_queries_log
              (tenant_id, network, raf_patient_id, query_type, status,
               latency_ms, documents_returned, error_text, queried_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
            """,
            (
                tenant_id,
                network,
                raf_patient_id,
                query_type,
                status,
                latency_ms,
                documents_returned,
                error_text,
            ),
        )


def _is_document_processed(fhir_document_id: str) -> bool:
    """Return True if this document has already been extracted (idempotency guard)."""
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT 1 FROM fhir_documents_processed
            WHERE fhir_document_id = %s
            LIMIT 1
            """,
            (fhir_document_id,),
        )
        return cur.fetchone() is not None


def _mark_document_processed(
    fhir_document_id: str,
    tenant_id: str,
    raf_patient_id: int,
    network: str,
) -> None:
    with raf_cursor() as cur:
        cur.execute(
            """
            INSERT IGNORE INTO fhir_documents_processed
              (fhir_document_id, tenant_id, raf_patient_id, source, processed_at)
            VALUES (%s, %s, %s, %s, NOW())
            """,
            (fhir_document_id, tenant_id, raf_patient_id, f"hie_{network}"),
        )


def _extract_binary_url(doc_ref: dict[str, Any]) -> tuple[str | None, str]:
    """Return (binary_url, mime_type) from a FHIR DocumentReference."""
    for content_item in doc_ref.get("content") or []:
        attachment = content_item.get("attachment") or {}
        url = attachment.get("url")
        mime = attachment.get("contentType", "application/pdf")
        if url:
            return url, mime
    return None, "application/pdf"


def sync_patient_from_hie(
    tenant_id: str,
    raf_patient_id: int,
    network: str,
) -> dict[str, Any]:
    """Discover a patient in the HIE, fetch documents, extract HCC suspects.

    Returns a summary dict with keys:
      network, raf_patient_id, hie_patient_id, matches_found,
      documents_fetched, documents_skipped, suspects_extracted, errors
    """
    import asyncio

    if network not in _SUPPORTED_NETWORKS:
        raise ValueError(f"Unsupported network: {network!r}. Choose from {_SUPPORTED_NETWORKS}")

    adapter = _get_adapter(network)

    if not adapter.is_configured():
        return {
            "status": "network_not_configured",
            "network": network,
            "raf_patient_id": raf_patient_id,
        }

    summary: dict[str, Any] = {
        "network": network,
        "raf_patient_id": raf_patient_id,
        "hie_patient_id": None,
        "matches_found": 0,
        "documents_fetched": 0,
        "documents_skipped": 0,
        "suspects_extracted": 0,
        "errors": [],
    }

    # Step 1: Resolve patient demographics
    demo = _fetch_patient_demographics(raf_patient_id, tenant_id)
    if not demo:
        summary["errors"].append("patient_not_found")
        return summary

    # Step 2: Discover patient
    t0 = time.monotonic()
    try:
        matches = asyncio.run(
            adapter.discover_patient(
                first_name=demo["first_name"],
                last_name=demo["last_name"],
                dob=demo["dob"],
                sex=demo["sex"],
                mbi=demo.get("mbi"),
            )
        )
        latency = int((time.monotonic() - t0) * 1000)
        _log_hie_query(
            tenant_id, network, raf_patient_id,
            "discover_patient", "success", latency,
        )
    except Exception as exc:
        latency = int((time.monotonic() - t0) * 1000)
        _log_hie_query(
            tenant_id, network, raf_patient_id,
            "discover_patient", "error", latency,
            error_text=str(exc)[:500],
        )
        summary["errors"].append(f"discover_patient: {exc}")
        return summary

    summary["matches_found"] = len(matches)
    if not matches:
        return summary

    best_match = matches[0]
    summary["hie_patient_id"] = best_match["hie_patient_id"]
    hie_patient_id = best_match["hie_patient_id"]

    # Step 3: List document references
    t0 = time.monotonic()
    try:
        doc_refs = asyncio.run(
            adapter.list_document_references(hie_patient_id)
        )
        latency = int((time.monotonic() - t0) * 1000)
        _log_hie_query(
            tenant_id, network, raf_patient_id,
            "list_document_references", "success", latency,
            documents_returned=len(doc_refs),
        )
    except Exception as exc:
        latency = int((time.monotonic() - t0) * 1000)
        _log_hie_query(
            tenant_id, network, raf_patient_id,
            "list_document_references", "error", latency,
            error_text=str(exc)[:500],
        )
        summary["errors"].append(f"list_document_references: {exc}")
        # Still upsert match even if doc listing fails
        _upsert_hie_match(tenant_id, raf_patient_id, network, best_match, 0)
        return summary

    _upsert_hie_match(tenant_id, raf_patient_id, network, best_match, len(doc_refs))

    # Steps 4-6: Fetch binary + Gemini extraction for each document
    from datetime import date
    current_year = date.today().year

    for doc_ref in doc_refs:
        doc_id = doc_ref.get("id", "")
        fhir_document_id = f"{network}:{hie_patient_id}:{doc_id}"

        if _is_document_processed(fhir_document_id):
            summary["documents_skipped"] += 1
            continue

        binary_url, mime_type = _extract_binary_url(doc_ref)
        if not binary_url:
            summary["documents_skipped"] += 1
            continue

        t0 = time.monotonic()
        try:
            raw_bytes, actual_mime = asyncio.run(adapter.fetch_binary(binary_url))
            latency = int((time.monotonic() - t0) * 1000)
            _log_hie_query(
                tenant_id, network, raf_patient_id,
                "fetch_binary", "success", latency, documents_returned=1,
            )
        except Exception as exc:
            latency = int((time.monotonic() - t0) * 1000)
            _log_hie_query(
                tenant_id, network, raf_patient_id,
                "fetch_binary", "error", latency, error_text=str(exc)[:500],
            )
            summary["errors"].append(f"fetch_binary({doc_id}): {exc}")
            continue

        # Step 6: Gemini vision extraction
        extraction = extract_from_document(
            doc_bytes=raw_bytes,
            mime_type=actual_mime or mime_type,
            year=current_year,
            document_filename=f"hie_{network}_{doc_id}",
            tenant_id=tenant_id,
        )
        suspects = extraction.get("suspects") or []
        summary["suspects_extracted"] += len(suspects)
        summary["documents_fetched"] += 1

        # Mark as processed (idempotency)
        _mark_document_processed(fhir_document_id, tenant_id, raf_patient_id, network)

    return summary
