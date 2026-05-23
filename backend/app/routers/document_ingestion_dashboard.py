"""
Document Ingestion Dashboard router.

GET  /api/admin/document-ingestion/dashboard?hours=24
     Aggregates activity from all 8 ingestion-path tables into a unified view.

GET  /api/admin/document-ingestion/document/{source}/{document_id}
     Returns full detail for a single document (for the drawer).

The 8 source tables queried:
    openemr_document_ingest_log     (source: openemr)
    fhir_documents_processed        (source: fhir-docref / fhir-bulk)
    hl7v2_messages_received         (source: hl7v2-mdm)
    direct_inbound_messages         (source: direct-ccda)
    hie_queries_log                 (source: hie)
    datavant_documents_received     (source: datavant)
    inovalon_patient_pulls          (source: inovalon)
    reveleer_charts_pulled          (source: reveleer)

All tables may not exist yet; the router degrades gracefully per source.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth import get_current_user, require_permission
from app.db import raf_cursor
from app.services.redis_cache import cached as redis_cached

# Module-level identifier guard — see _safe_ident below. Pre-compiled so the
# regex is built once per process, not per query.
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Allowlist for the optional sub-filter column on shared ingestion tables.
# Today the values originate from the in-process SOURCES dict, but this
# frozenset is the single source of truth so future config-driven sources
# can never become an injection vector. Used by both the aggregate query
# and the row-fetch query in _query_source.
_ALLOWED_FILTER_COLS: frozenset[str] = frozenset({"export_type"})


def _safe_ident(value: str, field_name: str) -> str:
    """Reject anything that isn't a bare SQL identifier before string-
    interpolating it into a query. Today the values come from the in-process
    SOURCES dict, but this guard makes injection impossible if SOURCES ever
    becomes DB- or YAML-driven."""
    if not isinstance(value, str) or not _IDENT_RE.fullmatch(value):
        raise ValueError(
            f"document_ingestion_dashboard: refusing non-identifier "
            f"{field_name}={value!r}"
        )
    return value

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/admin/document-ingestion",
    tags=["admin", "document-ingestion"],
)

# ---------------------------------------------------------------------------
# Source configuration
# ---------------------------------------------------------------------------

SOURCES = [
    {
        "id": "fhir-bulk",
        "name": "FHIR Bulk Export",
        "table": "fhir_documents_processed",
        "ts_col": "processed_at",
        "doc_col": "document_id",
        "patient_col": "patient_id",
        "filename_col": "filename",
        "mime_col": "mimetype",
        "status_col": "status",
        "suspects_col": "suspects_extracted",
        "size_col": "file_size_bytes",
        "engine_col": "processing_engine",
        "config_path": "/admin/fhir/bulk-export",
        "source_filter": "bulk",
        "source_filter_col": "export_type",
    },
    {
        "id": "fhir-docref",
        "name": "FHIR DocRef",
        "table": "fhir_documents_processed",
        "ts_col": "processed_at",
        "doc_col": "document_id",
        "patient_col": "patient_id",
        "filename_col": "filename",
        "mime_col": "mimetype",
        "status_col": "status",
        "suspects_col": "suspects_extracted",
        "size_col": "file_size_bytes",
        "engine_col": "processing_engine",
        "config_path": "/admin/fhir/bulk-export",
        "source_filter": "docref",
        "source_filter_col": "export_type",
    },
    {
        "id": "hl7v2-mdm",
        "name": "HL7 v2 MDM",
        "table": "hl7v2_messages_received",
        "ts_col": "received_at",
        "doc_col": "message_id",
        "patient_col": "patient_id",
        "filename_col": "message_type",
        "mime_col": "content_type",
        "status_col": "status",
        "suspects_col": "suspects_extracted",
        "size_col": "message_size_bytes",
        "engine_col": "processing_engine",
        "config_path": "/admin/hl7v2-sources",
        "source_filter": None,
        "source_filter_col": None,
    },
    {
        "id": "direct-ccda",
        "name": "Direct / CCDA",
        "table": "direct_inbound_messages",
        "ts_col": "received_at",
        "doc_col": "message_id",
        "patient_col": "patient_id",
        "filename_col": "filename",
        "mime_col": "mimetype",
        "status_col": "status",
        "suspects_col": "suspects_extracted",
        "size_col": "file_size_bytes",
        "engine_col": "processing_engine",
        "config_path": "/admin/direct-anchors",
        "source_filter": None,
        "source_filter_col": None,
    },
    {
        "id": "hie",
        "name": "HIE",
        "table": "hie_queries_log",
        "ts_col": "queried_at",
        "doc_col": "query_id",
        "patient_col": "patient_id",
        "filename_col": "document_name",
        "mime_col": "mimetype",
        "status_col": "status",
        "suspects_col": "suspects_extracted",
        "size_col": "document_size_bytes",
        "engine_col": "processing_engine",
        "config_path": "/admin/hie",
        "source_filter": None,
        "source_filter_col": None,
    },
    {
        "id": "datavant",
        "name": "Datavant",
        "table": "datavant_documents_received",
        "ts_col": "received_at",
        "doc_col": "document_id",
        "patient_col": "patient_id",
        "filename_col": "filename",
        "mime_col": "mimetype",
        "status_col": "status",
        "suspects_col": "suspects_extracted",
        "size_col": "file_size_bytes",
        "engine_col": "processing_engine",
        "config_path": "/admin/datavant",
        "source_filter": None,
        "source_filter_col": None,
    },
    {
        "id": "inovalon",
        "name": "Inovalon",
        "table": "inovalon_patient_pulls",
        "ts_col": "pulled_at",
        "doc_col": "pull_id",
        "patient_col": "patient_id",
        "filename_col": "document_name",
        "mime_col": "mimetype",
        "status_col": "status",
        "suspects_col": "suspects_extracted",
        "size_col": "document_size_bytes",
        "engine_col": "processing_engine",
        "config_path": "/admin/inovalon",
        "source_filter": None,
        "source_filter_col": None,
    },
    {
        "id": "reveleer",
        "name": "Reveleer",
        "table": "reveleer_charts_pulled",
        "ts_col": "pulled_at",
        "doc_col": "chart_id",
        "patient_col": "patient_id",
        "filename_col": "chart_filename",
        "mime_col": "mimetype",
        "status_col": "status",
        "suspects_col": "suspects_extracted",
        "size_col": "file_size_bytes",
        "engine_col": "processing_engine",
        "config_path": "/admin/reveleer",
        "source_filter": None,
        "source_filter_col": None,
    },
    {
        "id": "openemr",
        "name": "OpenEMR Docs",
        "table": "openemr_document_ingest_log",
        "ts_col": "ingested_at",
        "doc_col": "log_id",
        "patient_col": "patient_id",
        "filename_col": "filename",
        "mime_col": "mimetype",
        "status_col": "status",
        "suspects_col": "suspects_extracted",
        "size_col": "file_size_bytes",
        "engine_col": "processing_engine",
        "config_path": "/admin/openemr-docs",
        "source_filter": None,
        "source_filter_col": None,
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _table_exists(cursor, table_name: str) -> bool:
    """Return True if *table_name* exists in the RAF database."""
    try:
        cursor.execute(
            "SELECT COUNT(*) AS cnt FROM information_schema.tables "
            "WHERE table_schema = DATABASE() AND table_name = %s",
            (table_name,),
        )
        row = cursor.fetchone()
        return bool(row and row["cnt"])
    except Exception:
        # Permission denied / connection drop should be visible in logs even
        # though the caller treats False as "skip this source".
        logger.debug(
            "_table_exists check failed for %s", table_name, exc_info=True,
        )
        return False


def _query_source(
    cursor,
    src: dict,
    since: datetime,
) -> dict[str, Any]:
    """
    Query a single source table using the provided dict cursor.
    Returns a dict with docs_24h, suspects_24h, last_activity, status,
    and recent_rows (up to 200 most-recent rows).
    """
    # _safe_ident is module-level (defined at top of file) so the regex is
    # compiled once per process, not per query. The guard exists so that if
    # SOURCES ever becomes DB- or YAML-driven the value cannot become an
    # injection vector.
    table = _safe_ident(src["table"], "table")
    ts = _safe_ident(src["ts_col"], "ts_col")
    doc = _safe_ident(src["doc_col"], "doc_col")
    patient = _safe_ident(src["patient_col"], "patient_col")
    filename = _safe_ident(src["filename_col"], "filename_col")
    mime = _safe_ident(src["mime_col"], "mime_col")
    status_col = _safe_ident(src["status_col"], "status_col")
    suspects_col = _safe_ident(src["suspects_col"], "suspects_col")
    source_id = src["id"]

    if not _table_exists(cursor, table):
        return {
            "docs_24h": 0,
            "suspects_24h": 0,
            "last_activity": None,
            "status": "not_configured",
            "recent_rows": [],
        }

    # Optional sub-filter for tables shared between two logical sources.
    # Uses module-level _ALLOWED_FILTER_COLS so the constant is built once,
    # not per request, and so the same allowlist applies to every query path
    # in this function (the aggregate + the rows fetch below).
    filter_clause = ""
    filter_params: list[Any] = [since]
    col = src.get("source_filter_col")
    if src.get("source_filter") and col:
        if col not in _ALLOWED_FILTER_COLS:
            logger.warning(
                "document_ingestion_dashboard: rejected non-allowlisted "
                "filter column %r", col,
            )
        else:
            filter_clause = f" AND {col} = %s"
            filter_params.append(src["source_filter"])

    try:
        cursor.execute(
            f"""
            SELECT
                COUNT(*)                        AS docs_24h,
                COALESCE(SUM({suspects_col}),0) AS suspects_24h,
                MAX({ts})                       AS last_activity
            FROM {table}
            WHERE {ts} >= %s{filter_clause}
            """,
            filter_params,
        )
        agg = cursor.fetchone()

        docs_24h = int(agg["docs_24h"]) if agg else 0
        suspects_24h = int(agg["suspects_24h"]) if agg else 0
        last_activity_dt = agg["last_activity"] if agg else None
        last_activity = last_activity_dt.isoformat() if last_activity_dt else None

        # Determine status
        if docs_24h > 0:
            status = "active"
        else:
            cursor.execute(f"SELECT 1 FROM {table} LIMIT 1")
            any_row = cursor.fetchone()
            status = "idle" if any_row else "not_configured"

        # Recent rows for the activity table
        rows_params: list[Any] = [since]
        if src.get("source_filter") and src.get("source_filter_col"):
            rows_params.append(src["source_filter"])

        cursor.execute(
            f"""
            SELECT
                {ts}           AS ts,
                {doc}          AS document_id,
                {patient}      AS patient_id,
                {filename}     AS filename,
                {mime}         AS mimetype,
                {suspects_col} AS suspects,
                {status_col}   AS status
            FROM {table}
            WHERE {ts} >= %s{filter_clause}
            ORDER BY {ts} DESC
            LIMIT 200
            """,
            rows_params,
        )
        raw_rows = cursor.fetchall()

        recent_rows = [
            {
                "source": source_id,
                "timestamp": row["ts"].isoformat() if row["ts"] else None,
                "document_id": str(row["document_id"]) if row["document_id"] else None,
                "patient_id": str(row["patient_id"]) if row["patient_id"] else None,
                "filename": row["filename"],
                "mimetype": row["mimetype"],
                "suspects": int(row["suspects"]) if row["suspects"] else 0,
                "status": row["status"],
            }
            for row in raw_rows
        ]

        return {
            "docs_24h": docs_24h,
            "suspects_24h": suspects_24h,
            "last_activity": last_activity,
            "status": status,
            "recent_rows": recent_rows,
        }

    except Exception:
        # Per-source isolation: a failure on one of the 9 source tables must
        # not blank the whole dashboard. exc_info=True preserves the
        # traceback so ops can diagnose schema drift / connection drops.
        logger.warning(
            "document_ingestion_dashboard: failed to query %s",
            table, exc_info=True,
        )
        return {
            "docs_24h": 0,
            "suspects_24h": 0,
            "last_activity": None,
            "status": "not_configured",
            "recent_rows": [],
        }


# ---------------------------------------------------------------------------
# Dashboard endpoint
# ---------------------------------------------------------------------------

@redis_cached(
    key_builder=lambda tenant_id, hours: (
        f"raf:doc_dashboard:{tenant_id}:{hours}"
    ),
    ttl_seconds=60,
    tenant_aware=True,
)
def _cached_doc_dashboard(tenant_id: str, hours: int) -> dict[str, Any]:
    """Heavy 8-source aggregation memoised for 60 s."""
    return _build_doc_dashboard(hours)


@router.get("/dashboard", summary="Document ingestion unified dashboard")
def get_dashboard(
    hours: int = Query(24, ge=1, le=168, description="Look-back window in hours"),
    force_refresh: bool = Query(
        False, description="Bypass Redis cache (admin debug)."
    ),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("admin", "read")),
) -> dict[str, Any]:
    """
    Returns a unified view across all 8 ingestion paths:
      - sources  : per-source card data (status, counts, last activity)
      - recent_documents : merged chronological list of recent docs
      - kpis     : aggregate KPIs for the requested window
    """
    tenant_id = str((current_user or {}).get("tenant_id") or "global")
    return _cached_doc_dashboard(tenant_id, hours, force_refresh=force_refresh)


def _build_doc_dashboard(hours: int) -> dict[str, Any]:
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    source_cards = []
    all_recent: list[dict] = []
    total_docs = 0
    total_suspects = 0
    success_count = 0
    processed_count = 0
    active_sources = 0

    with raf_cursor() as cursor:
        for src in SOURCES:
            result = _query_source(cursor, src, since)

            total_docs += result["docs_24h"]
            total_suspects += result["suspects_24h"]
            if result["status"] == "active":
                active_sources += 1

            for row in result["recent_rows"]:
                if row["status"] in ("success", "completed", "processed"):
                    success_count += 1
                if row["status"] not in (None, ""):
                    processed_count += 1

            all_recent.extend(result["recent_rows"])

            source_cards.append(
                {
                    "id": src["id"],
                    "name": src["name"],
                    "status": result["status"],
                    "docs_24h": result["docs_24h"],
                    "suspects_24h": result["suspects_24h"],
                    "last_activity": result["last_activity"],
                    "config_path": src["config_path"],
                }
            )

    # Sort recent documents by timestamp desc, cap at 500 for the response.
    # Timestamps are produced via datetime.isoformat() at line 354 — so they
    # always look like "2026-05-23T14:32:11.123456" or "...+00:00". ISO-8601
    # is lexicographically sortable as long as all values share the same
    # timezone-format flavour, which they do here (the upstream column is
    # always UTC-naive datetime). Empty string sorts last under reverse=True
    # which is the desired behaviour for missing timestamps.
    all_recent.sort(key=lambda r: r["timestamp"] or "", reverse=True)
    all_recent = all_recent[:500]

    success_rate = (
        round(success_count / processed_count * 100, 1) if processed_count > 0 else None
    )

    kpis = {
        "total_docs_24h": total_docs,
        "total_suspects_24h": total_suspects,
        "success_rate_pct": success_rate,
        "active_sources": active_sources,
        "window_hours": hours,
    }

    return {
        "sources": source_cards,
        "recent_documents": all_recent,
        "kpis": kpis,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Document detail endpoint
# ---------------------------------------------------------------------------

@router.get(
    "/document/{source_id}/{document_id}",
    summary="Fetch full detail for a single ingested document",
)
def get_document_detail(
    source_id: str,
    document_id: str,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("admin", "read")),
) -> dict[str, Any]:
    """
    Used by the frontend drawer.  Returns full document record plus suspects table.
    Auth: requires admin:read; previously this endpoint was completely open
    and would return SELECT * from any ingestion table to any network-
    reachable caller.
    """
    src = next((s for s in SOURCES if s["id"] == source_id), None)
    if src is None:
        raise HTTPException(status_code=404, detail=f"Unknown source: {source_id}")

    # Apply the same identifier guard the aggregate query uses so an
    # externally-driven SOURCES dict cannot become an injection vector.
    table = _safe_ident(src["table"], "table")
    doc_col = _safe_ident(src["doc_col"], "doc_col")

    row: dict | None = None
    suspects: list[dict] = []

    with raf_cursor() as cursor:
        if not _table_exists(cursor, table):
            raise HTTPException(
                status_code=404,
                detail=f"Source table {table!r} does not exist yet",
            )

        try:
            cursor.execute(
                f"SELECT * FROM {table} WHERE {doc_col} = %s LIMIT 1",
                (document_id,),
            )
            raw = cursor.fetchone()
        except Exception as exc:
            # Don't leak raw MySQL error text (which can include schema info)
            # to the HTTP response. Log the original cause for ops.
            logger.exception(
                "document_ingestion_dashboard.get_document_detail "
                "query failed for source=%s document=%s",
                source_id, document_id,
            )
            raise HTTPException(
                status_code=500,
                detail="Internal error querying document source",
            ) from exc

        if raw is None:
            raise HTTPException(
                status_code=404,
                detail=f"Document {document_id!r} not found in {source_id}",
            )
        row = dict(raw)

        # Attempt to fetch suspects linked to this document
        try:
            cursor.execute(
                """
                SELECT hcc_code, icd10_code, confidence_score, evidence_sentence
                FROM document_suspects
                WHERE source = %s AND document_id = %s
                ORDER BY confidence_score DESC
                """,
                (source_id, document_id),
            )
            suspects = [dict(r) for r in cursor.fetchall()]
        except Exception:
            # form_suspects may not exist yet in this env — log at debug
            # so the empty list is explained instead of silently dropped.
            logger.debug(
                "document_ingestion_dashboard: form_suspects query skipped "
                "for source=%s document=%s",
                source_id, document_id, exc_info=True,
            )

    # Convert datetime objects to ISO strings for JSON serialisation
    for key, val in row.items():
        if isinstance(val, datetime):
            row[key] = val.isoformat()

    return {
        "source": source_id,
        "document_id": document_id,
        "record": row,
        "suspects": suspects,
    }
