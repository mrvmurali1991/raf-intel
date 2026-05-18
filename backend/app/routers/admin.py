"""
Admin router — internal tooling endpoints.

POST /api/admin/openemr-docs/scan
    Fetches unprocessed PDF rows from openemr.documents, sends each through
    the Gemini vision pipeline, and persists suspects + MEAT evidence to the
    RAF Intelligence database.

    Query params:
        limit   int  (default 10, max 100)  — max documents to process per call
        dry_run bool (default false)         — parse only, do not persist

GET /api/admin/openemr-docs/ingest-log
    Returns recent rows from raf_doc_ingest_log ordered by processed_at DESC.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.db import openemr_cursor, raf_cursor

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])

# ---------------------------------------------------------------------------
# Schema note
# ---------------------------------------------------------------------------
# raf_doc_ingest_log (created on first use via CREATE TABLE IF NOT EXISTS):
#   id              INT AUTO_INCREMENT PRIMARY KEY
#   document_id     INT NOT NULL           — openemr.documents.id
#   patient_id      INT NOT NULL
#   filename        VARCHAR(500)
#   status          ENUM('ok','error','skipped')
#   suspects_found  INT DEFAULT 0
#   error_msg       TEXT NULL
#   processed_at    DATETIME DEFAULT NOW()
#   raw_response    MEDIUMTEXT NULL        — Gemini JSON response (truncated at 8000 chars)
# ---------------------------------------------------------------------------

_CREATE_INGEST_LOG = """
CREATE TABLE IF NOT EXISTS raf_doc_ingest_log (
    id             INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    document_id    INT NOT NULL,
    patient_id     INT NOT NULL,
    filename       VARCHAR(500) DEFAULT '',
    status         ENUM('ok','error','skipped') NOT NULL DEFAULT 'ok',
    suspects_found INT NOT NULL DEFAULT 0,
    error_msg      TEXT NULL,
    processed_at   DATETIME NOT NULL DEFAULT NOW(),
    raw_response   MEDIUMTEXT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""

# raf_suspect_conditions schema accepted by _store_suspect_from_vision:
# Uses the same table as the existing suspect_engine, but source = 'gemini_vision'
# and evidence stores evidence_sentence + source_document_id.
_UPSERT_SUSPECT = """
INSERT INTO raf_suspect_conditions (
    patient_id, fingerprint, source,
    suspected_icd, suspected_hcc, description,
    evidence, confidence, status,
    created_at, updated_at
) VALUES (
    %s, %s, 'gemini_vision',
    %s, %s, %s,
    %s, %s, 'open',
    NOW(), NOW()
)
ON DUPLICATE KEY UPDATE
    confidence   = GREATEST(confidence, VALUES(confidence)),
    evidence     = VALUES(evidence),
    updated_at   = NOW()
"""

_INSERT_INGEST_LOG = """
INSERT INTO raf_doc_ingest_log
    (document_id, patient_id, filename, status, suspects_found, error_msg,
     processed_at, raw_response)
VALUES (%s, %s, %s, %s, %s, %s, NOW(), %s)
"""


# ---------------------------------------------------------------------------
# Ensure raf_doc_ingest_log exists
# ---------------------------------------------------------------------------

def _ensure_ingest_log_table() -> None:
    try:
        with raf_cursor() as cur:
            cur.execute(_CREATE_INGEST_LOG)
    except Exception as exc:
        logger.warning("Could not create raf_doc_ingest_log: %s", exc)


# ---------------------------------------------------------------------------
# Fetch unprocessed documents from openemr.documents
# ---------------------------------------------------------------------------

def _fetch_pending_docs(limit: int) -> list[dict[str, Any]]:
    """
    Return up to *limit* PDF documents from openemr.documents that have NOT
    yet been processed (i.e., have no row in raf_doc_ingest_log).
    """
    sql = """
        SELECT
            d.id          AS document_id,
            d.patient_id  AS pid,
            d.url_filepath,
            d.date        AS doc_date
        FROM documents d
        LEFT JOIN raf_intelligence.raf_doc_ingest_log l
               ON l.document_id = d.id
        WHERE d.mimetype = 'application/pdf'
          AND l.id IS NULL
        ORDER BY d.date DESC
        LIMIT %s
    """
    try:
        with openemr_cursor() as cur:
            cur.execute(sql, (limit,))
            return cur.fetchall() or []
    except Exception as exc:
        logger.error("_fetch_pending_docs failed: %s", exc)
        raise


# ---------------------------------------------------------------------------
# Gemini vision extraction
# ---------------------------------------------------------------------------

def _gemini_extract_from_pdf(pdf_path: str) -> dict[str, Any]:
    """
    Upload a PDF to the Gemini Files API and extract clinical suspects.

    Returns a dict with keys:
        suspects  list[dict]  — each has: icd10, hcc, description,
                                evidence_sentence, confidence (0.0–1.0)
        raw_text  str         — full Gemini response text (for logging)
        error     str | None  — error message if extraction failed

    If GEMINI_API_KEY / GOOGLE_API_KEY is not set, returns
        {"suspects": [], "raw_text": "", "error": "no_api_key"}
    """
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY", "")
    if not api_key:
        return {"suspects": [], "raw_text": "", "error": "no_api_key"}

    if not os.path.isfile(pdf_path):
        return {"suspects": [], "raw_text": "", "error": f"file_not_found:{pdf_path}"}

    try:
        from google import genai
        from google.genai import types as gtypes
    except ImportError:
        return {"suspects": [], "raw_text": "", "error": "google_genai_not_installed"}

    prompt = (
        "You are a clinical coding specialist. "
        "Analyze the attached clinical document and identify ALL conditions that "
        "map to CMS-HCC V28 risk-adjustment codes. "
        "For each condition:\n"
        "1. Provide the ICD-10-CM code (most specific applicable).\n"
        "2. Provide the HCC number (e.g. HCC85).\n"
        "3. Provide a brief description of the condition.\n"
        "4. Extract a verbatim sentence from the document that supports this diagnosis "
        "(this is the MEAT evidence sentence).\n"
        "5. Provide a confidence score 0.0–1.0.\n\n"
        "Return ONLY valid JSON in this exact structure:\n"
        '{"suspects": ['
        '{"icd10": "I50.22", "hcc": "HCC85", "description": "Chronic systolic CHF",'
        ' "evidence_sentence": "<verbatim quote>", "confidence": 0.91}'
        "]}"
    )

    try:
        client = genai.Client(api_key=api_key)
        model = os.getenv("GEMINI_MODEL", "gemini-2.5-pro")

        with open(pdf_path, "rb") as fh:
            pdf_bytes = fh.read()

        response = client.models.generate_content(
            model=model,
            contents=[
                gtypes.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf"),
                prompt,
            ],
            config=gtypes.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.1,
            ),
        )

        raw_text = response.text or ""

        # Strip JSON fences if present
        stripped = raw_text.strip()
        if stripped.startswith("```"):
            lines = stripped.splitlines()
            stripped = "\n".join(
                l for l in lines if not l.strip().startswith("```")
            ).strip()

        parsed = json.loads(stripped)
        suspects = parsed.get("suspects", [])

        # Validate and normalise each suspect
        clean: list[dict[str, Any]] = []
        for s in suspects:
            if not isinstance(s, dict):
                continue
            if not s.get("icd10") and not s.get("hcc"):
                continue
            clean.append({
                "icd10":            str(s.get("icd10", "")).strip().upper(),
                "hcc":              str(s.get("hcc", "")).strip().upper(),
                "description":      str(s.get("description", "")).strip(),
                "evidence_sentence": str(s.get("evidence_sentence", "")).strip(),
                "confidence":       float(s.get("confidence", 0.5)),
            })

        return {"suspects": clean, "raw_text": raw_text, "error": None}

    except json.JSONDecodeError as exc:
        logger.warning("Gemini returned non-JSON for %s: %s", pdf_path, exc)
        return {"suspects": [], "raw_text": raw_text if "raw_text" in dir() else "", "error": f"json_parse:{exc}"}
    except Exception as exc:
        logger.error("Gemini extraction failed for %s: %s", pdf_path, exc)
        return {"suspects": [], "raw_text": "", "error": str(exc)}


# ---------------------------------------------------------------------------
# Persist suspects from vision pipeline
# ---------------------------------------------------------------------------

def _fingerprint(patient_id: int, source: str, code: str) -> str:
    import hashlib
    raw = f"{patient_id}|{source}|{code}".lower()
    return hashlib.md5(raw.encode()).hexdigest()


def _store_vision_suspects(
    patient_id: int,
    document_id: int,
    suspects: list[dict[str, Any]],
) -> int:
    """
    Persist Gemini vision suspects into raf_suspect_conditions.
    Returns the number of suspects successfully stored.
    """
    stored = 0
    for s in suspects:
        icd10 = s.get("icd10", "")
        hcc = s.get("hcc", "")
        code_key = icd10 or hcc
        if not code_key:
            continue

        evidence = {
            "source": "gemini_vision",
            "evidence_sentence": s.get("evidence_sentence", ""),
            "source_document_id": document_id,
        }

        fp = _fingerprint(patient_id, "gemini_vision", code_key)
        try:
            with raf_cursor() as cur:
                cur.execute(
                    _UPSERT_SUSPECT,
                    (
                        patient_id,
                        fp,
                        icd10,
                        hcc,
                        s.get("description", ""),
                        json.dumps(evidence),
                        s.get("confidence", 0.5),
                    ),
                )
                stored += 1
        except Exception as exc:
            logger.warning(
                "_store_vision_suspects failed pid=%s code=%s: %s",
                patient_id, code_key, exc,
            )

    return stored


def _store_meat_from_vision(
    patient_id: int,
    document_id: int,
    suspects: list[dict[str, Any]],
) -> None:
    """
    Store simplified MEAT evidence rows derived from Gemini vision extraction.
    Each evidence_sentence is treated as the MEAT Assessment element.
    """
    for s in suspects:
        evidence_sentence = s.get("evidence_sentence", "")
        if not evidence_sentence:
            continue

        hcc_code = s.get("hcc", "")
        if not hcc_code:
            continue

        # Look up the raf_patient_hcc id (best-effort; skip if none)
        try:
            with raf_cursor() as cur:
                cur.execute(
                    """
                    SELECT id FROM raf_patient_hcc
                    WHERE patient_id = %s AND hcc_code = %s
                    ORDER BY measurement_year DESC
                    LIMIT 1
                    """,
                    (patient_id, hcc_code),
                )
                row = cur.fetchone()
                if not row:
                    continue
                patient_hcc_id = row["id"] if isinstance(row, dict) else row[0]

                # Store MEAT with assessment element populated from evidence_sentence
                cur.execute(
                    """
                    INSERT INTO raf_meat_evidence
                        (patient_hcc_id, encounter_id, encounter_date,
                         meat_a, meat_a_present, completeness_score,
                         raw_note_excerpt, created_at, updated_at)
                    VALUES
                        (%s, %s, CURDATE(),
                         %s, 1, 0.2500,
                         %s, NOW(), NOW())
                    ON DUPLICATE KEY UPDATE
                        meat_a         = VALUES(meat_a),
                        meat_a_present = 1,
                        updated_at     = NOW()
                    """,
                    (
                        patient_hcc_id,
                        document_id,
                        evidence_sentence[:500],
                        evidence_sentence[:2000],
                    ),
                )
        except Exception as exc:
            logger.debug(
                "_store_meat_from_vision skipped hcc=%s pid=%s: %s",
                hcc_code, patient_id, exc,
            )


def _log_ingest(
    document_id: int,
    patient_id: int,
    filename: str,
    status: str,
    suspects_found: int,
    error_msg: str | None,
    raw_response: str,
) -> None:
    try:
        with raf_cursor() as cur:
            cur.execute(
                _INSERT_INGEST_LOG,
                (
                    document_id,
                    patient_id,
                    filename,
                    status,
                    suspects_found,
                    error_msg,
                    raw_response[:8000] if raw_response else None,
                ),
            )
    except Exception as exc:
        logger.warning("_log_ingest failed: %s", exc)


# ---------------------------------------------------------------------------
# POST /api/admin/openemr-docs/scan
# ---------------------------------------------------------------------------

@router.post("/openemr-docs/scan", summary="Scan pending OpenEMR documents through Gemini vision")
def scan_openemr_docs(
    limit: int = Query(default=10, ge=1, le=100, description="Max documents to process"),
    dry_run: bool = Query(default=False, description="If true, extract but do not persist"),
) -> dict[str, Any]:
    """
    Fetches up to *limit* unprocessed PDF rows from openemr.documents, sends
    each through the Gemini vision pipeline, and persists suspects + MEAT
    evidence.

    Returns a summary with per-document trace entries suitable for CI smoke testing.
    """
    _ensure_ingest_log_table()

    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY", "")
    if not api_key:
        return {
            "status": "skipped",
            "reason": "no_gemini_key",
            "message": "GEMINI_API_KEY (or GOOGLE_API_KEY) is not set; skipping extraction.",
            "processed": 0,
            "documents": [],
        }

    try:
        pending = _fetch_pending_docs(limit)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to fetch pending docs: {exc}")

    if not pending:
        return {
            "status": "ok",
            "message": "No pending documents found.",
            "processed": 0,
            "documents": [],
        }

    trace: list[dict[str, Any]] = []

    for doc in pending:
        doc_id   = doc["document_id"] if isinstance(doc, dict) else doc[0]
        pid      = doc["pid"]         if isinstance(doc, dict) else doc[1]
        filepath = doc["url_filepath"] if isinstance(doc, dict) else doc[2]
        doc_date = str(doc.get("doc_date", ""))

        filename = os.path.basename(filepath) if filepath else f"doc_{doc_id}"
        logger.info("Processing doc_id=%s pid=%s file=%s", doc_id, pid, filename)

        result = _gemini_extract_from_pdf(filepath)

        suspects_found = 0
        if result.get("error"):
            status = "error"
            if not dry_run:
                _log_ingest(doc_id, pid, filename, "error", 0, result["error"], "")
        else:
            suspects = result.get("suspects", [])
            if not dry_run:
                suspects_found = _store_vision_suspects(pid, doc_id, suspects)
                _store_meat_from_vision(pid, doc_id, suspects)
                _log_ingest(
                    doc_id, pid, filename, "ok",
                    suspects_found, None,
                    result.get("raw_text", ""),
                )
            else:
                suspects_found = len(suspects)
            status = "ok"

        trace.append({
            "document_id":     doc_id,
            "patient_id":      pid,
            "filename":        filename,
            "status":          status,
            "suspects_found":  suspects_found,
            "error":           result.get("error"),
            "suspects":        result.get("suspects", []),
            "dry_run":         dry_run,
        })

    patients_with_suspects = len({
        t["patient_id"] for t in trace
        if t["status"] == "ok" and t["suspects_found"] > 0
    })

    return {
        "status": "ok",
        "processed": len(trace),
        "patients_with_suspects": patients_with_suspects,
        "dry_run": dry_run,
        "documents": trace,
    }


# ---------------------------------------------------------------------------
# GET /api/admin/openemr-docs/ingest-log
# ---------------------------------------------------------------------------

@router.get("/openemr-docs/ingest-log", summary="Retrieve recent document ingest log entries")
def get_ingest_log(
    limit: int = Query(default=50, ge=1, le=500),
    patient_id: int | None = Query(default=None),
) -> dict[str, Any]:
    """
    Return recent rows from raf_doc_ingest_log.
    Optionally filter by patient_id.
    """
    _ensure_ingest_log_table()

    try:
        with raf_cursor() as cur:
            if patient_id:
                cur.execute(
                    """
                    SELECT id, document_id, patient_id, filename, status,
                           suspects_found, error_msg, processed_at
                    FROM raf_doc_ingest_log
                    WHERE patient_id = %s
                    ORDER BY processed_at DESC
                    LIMIT %s
                    """,
                    (patient_id, limit),
                )
            else:
                cur.execute(
                    """
                    SELECT id, document_id, patient_id, filename, status,
                           suspects_found, error_msg, processed_at
                    FROM raf_doc_ingest_log
                    ORDER BY processed_at DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
            rows = cur.fetchall() or []
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to query ingest log: {exc}")

    # Serialise datetime objects
    serialised = []
    for row in rows:
        r = dict(row) if isinstance(row, dict) else {
            "id": row[0], "document_id": row[1], "patient_id": row[2],
            "filename": row[3], "status": row[4], "suspects_found": row[5],
            "error_msg": row[6], "processed_at": row[7],
        }
        if isinstance(r.get("processed_at"), datetime):
            r["processed_at"] = r["processed_at"].isoformat()
        serialised.append(r)

    return {"count": len(serialised), "log": serialised}
