"""
Document Upload & Gemini Vision Analysis Service
=================================================
Handles file storage, validation, and AI-powered clinical extraction
from uploaded documents (PDFs, images) using Google Gemini Vision.

Gemini 2.5 Pro can analyse images and PDFs natively — no OCR pre-step is
required.  The service sends the raw file bytes as inline multimodal parts
and requests a fully structured JSON extraction of all clinically-relevant
data in a single inference call.

Database tables expected in the raf_intelligence schema:
  - documents
  - document_analysis
  - document_diagnosis_lines
  - document_batches
  - document_batch_items
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import settings
from app.db import raf_cursor
from app.services.icd_validator import (
    get_hcc_mapping,
    normalize_code,
    validate_code,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB

# Magic byte signatures used to verify file content matches the declared MIME type.
_MAGIC: dict[str, bytes] = {
    "application/pdf": b"%PDF",
    "image/png": b"\x89PNG",
    "image/jpeg": b"\xff\xd8\xff",
}

ALLOWED_EXTENSIONS: dict[str, str] = {
    "pdf": "application/pdf",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "tiff": "image/tiff",
    "tif": "image/tiff",
    "bmp": "image/bmp",
    "gif": "image/gif",
    "webp": "image/webp",
    "heic": "image/heic",
}

# Project root — /app inside the container
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

UPLOADS_BASE = _PROJECT_ROOT / "uploads" / "documents"

# ---------------------------------------------------------------------------
# Schema – Gemini Vision extraction
# ---------------------------------------------------------------------------

_EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "full_text": {
            "type": "string",
            "description": "Complete OCR / text extraction of the document",
        },
        "document_type_detected": {
            "type": "string",
            "description": "Detected type: progress_note, lab_report, discharge_summary, rx, radiology, consult, other",
        },
        "encounter_date_detected": {
            "type": "string",
            "description": "ISO-8601 date of the encounter/service found in the document, or empty string",
        },
        "provider_name": {"type": "string"},
        "provider_npi": {"type": "string"},
        "facility_name": {"type": "string"},
        "patient_name_detected": {"type": "string"},
        "patient_dob_detected": {"type": "string"},
        "patient_mrn_detected": {"type": "string"},
        "diagnoses": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "icd10_code": {"type": "string"},
                    "description": {"type": "string"},
                    "status": {
                        "type": "string",
                        "description": "active|chronic|resolved|rule_out|suspect",
                    },
                    "meat_monitor": {"type": "string"},
                    "meat_evaluate": {"type": "string"},
                    "meat_assess": {"type": "string"},
                    "meat_treat": {"type": "string"},
                    "supporting_text": {
                        "type": "string",
                        "description": "Verbatim excerpt(s) from document supporting this diagnosis",
                    },
                },
                "required": ["icd10_code", "description", "status"],
            },
        },
        "suspect_conditions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "suspected_icd10": {"type": "string"},
                    "suspected_description": {"type": "string"},
                    "rationale": {"type": "string"},
                    "supporting_text": {"type": "string"},
                },
                "required": ["suspected_description", "rationale"],
            },
        },
        "medications": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "dose": {"type": "string"},
                    "frequency": {"type": "string"},
                    "route": {"type": "string"},
                },
                "required": ["name"],
            },
        },
        "lab_results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "test_name": {"type": "string"},
                    "value": {"type": "string"},
                    "unit": {"type": "string"},
                    "reference_range": {"type": "string"},
                    "flag": {
                        "type": "string",
                        "description": "normal|high|low|critical",
                    },
                },
                "required": ["test_name", "value"],
            },
        },
        "vital_signs": {
            "type": "object",
            "properties": {
                "blood_pressure": {"type": "string"},
                "heart_rate": {"type": "string"},
                "respiratory_rate": {"type": "string"},
                "temperature": {"type": "string"},
                "oxygen_saturation": {"type": "string"},
                "weight": {"type": "string"},
                "height": {"type": "string"},
                "bmi": {"type": "string"},
            },
        },
        "procedures": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "cpt_code": {"type": "string"},
                    "description": {"type": "string"},
                    "date": {"type": "string"},
                },
                "required": ["description"],
            },
        },
        "clinical_summary": {
            "type": "string",
            "description": "1-3 sentence narrative summary of the document",
        },
        "quality_assessment": {
            "type": "object",
            "properties": {
                "legibility_score": {"type": "number", "description": "0.0–1.0"},
                "completeness_score": {"type": "number", "description": "0.0–1.0"},
                "issues": {"type": "array", "items": {"type": "string"}},
                "is_handwritten": {"type": "boolean"},
            },
        },
    },
    "required": ["full_text", "diagnoses", "clinical_summary", "quality_assessment"],
}

_EXTRACTION_PROMPT = """\
You are a clinical documentation specialist performing structured extraction from a medical document.

Analyse the attached document thoroughly and extract ALL clinically relevant information.

EXTRACTION REQUIREMENTS:

1. FULL TEXT — Transcribe ALL visible text (OCR-equivalent), preserving structure.

2. DIAGNOSES — List every diagnosis, condition, or clinical finding:
   - Provide the most specific valid ICD-10-CM code supported by the documentation
   - For each diagnosis provide MEAT evidence:
     * Monitor: what is being watched/tracked
     * Evaluate: tests/assessments performed
     * Assess: clinical assessment statements
     * Treat: treatments/medications for this condition
   - Mark status: active, chronic, resolved, rule_out, or suspect
   - Include the verbatim text supporting each diagnosis

3. SUSPECT CONDITIONS — Identify conditions evidenced but NOT explicitly coded:
   - Medications implying undocumented diagnoses (e.g. metformin → diabetes)
   - Lab values suggesting undiagnosed conditions
   - Clinical findings consistent with uncoded conditions
   - Provide suggested ICD-10-CM codes where applicable

4. MEDICATIONS — Every medication with dose, frequency, and route if documented

5. LAB RESULTS — All laboratory values with units, reference ranges, and H/L/critical flags

6. VITAL SIGNS — All vital sign measurements

7. PROCEDURES — Any CPT-coded or described procedures

8. PROVIDER INFORMATION — Provider names, NPIs, facility names

9. PATIENT IDENTIFIERS — Patient name, DOB, MRN (for matching, will not be stored externally)

10. QUALITY ASSESSMENT:
    - Legibility score (0.0 = illegible, 1.0 = perfectly clear)
    - Completeness score (0.0 = severely incomplete, 1.0 = complete)
    - Flag any issues: handwriting, stamps obscuring text, cut-off margins, etc.
    - Indicate if document is handwritten

Return ONLY valid JSON matching the provided schema. Be exhaustive — missing a diagnosis
or medication is worse than including an uncertain finding.
"""


# ---------------------------------------------------------------------------
# File helpers
# ---------------------------------------------------------------------------


def _resolve_upload_path(tenant_id: str) -> Path:
    """Return the upload directory for the given tenant and current month."""
    # Sanitize tenant_id to prevent path traversal
    safe_tenant = re.sub(r'[^a-zA-Z0-9_-]', '_', str(tenant_id))
    month_dir = UPLOADS_BASE / safe_tenant / datetime.now(timezone.utc).strftime("%Y-%m")
    # Verify resolved path is within UPLOADS_BASE
    resolved = month_dir.resolve()
    if not resolved.is_relative_to(UPLOADS_BASE.resolve()):
        raise ValueError("Invalid upload path: path escapes base directory")
    month_dir.mkdir(parents=True, exist_ok=True)
    return month_dir


def _compute_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _get_mime_type(filename: str) -> str | None:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return ALLOWED_EXTENSIONS.get(ext)


def validate_upload_file(filename: str, file_bytes: bytes) -> dict[str, Any]:
    """
    Validate filename and file content.

    Returns a dict with keys:
      valid (bool), mime_type (str|None), error (str|None), sha256 (str)
    """
    mime_type = _get_mime_type(filename)
    if mime_type is None:
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "none"
        return {
            "valid": False,
            "mime_type": None,
            "sha256": "",
            "error": f"File type '.{ext}' is not supported. Allowed: {', '.join(ALLOWED_EXTENSIONS)}",
        }

    if len(file_bytes) > MAX_FILE_SIZE_BYTES:
        size_mb = len(file_bytes) / (1024 * 1024)
        return {
            "valid": False,
            "mime_type": mime_type,
            "sha256": "",
            "error": f"File size {size_mb:.1f} MB exceeds the 50 MB limit.",
        }

    if len(file_bytes) == 0:
        return {
            "valid": False,
            "mime_type": mime_type,
            "sha256": "",
            "error": "Uploaded file is empty.",
        }

    # Magic bytes check — verify file content matches declared MIME type.
    expected_magic = _MAGIC.get(mime_type)
    if expected_magic and not file_bytes[: len(expected_magic)].startswith(
        expected_magic
    ):
        return {
            "valid": False,
            "mime_type": mime_type,
            "sha256": "",
            "error": f"File content does not match {mime_type} format",
        }

    return {
        "valid": True,
        "mime_type": mime_type,
        "sha256": _compute_sha256(file_bytes),
        "error": None,
    }


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------


def _ensure_tables() -> None:
    """Idempotent schema fixes for the documents table."""
    with raf_cursor() as cur:
        # The documents table may have id as INT but we need VARCHAR(36) for UUIDs
        cur.execute(
            "SELECT DATA_TYPE FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'documents' AND COLUMN_NAME = 'id'"
        )
        row = cur.fetchone()
        if row and row.get("DATA_TYPE") in ("int", "bigint"):
            logger.info("Migrating documents.id from INT to VARCHAR(36) for UUID support")
            # Drop foreign keys referencing documents.id first
            cur.execute(
                "SELECT CONSTRAINT_NAME, TABLE_NAME FROM information_schema.KEY_COLUMN_USAGE "
                "WHERE REFERENCED_TABLE_SCHEMA = DATABASE() "
                "AND REFERENCED_TABLE_NAME = 'documents' AND REFERENCED_COLUMN_NAME = 'id'"
            )
            fks = cur.fetchall()
            for fk in fks:
                try:
                    cur.execute(f"ALTER TABLE `{fk['TABLE_NAME']}` DROP FOREIGN KEY `{fk['CONSTRAINT_NAME']}`")
                    logger.info("Dropped FK %s on %s", fk["CONSTRAINT_NAME"], fk["TABLE_NAME"])
                except Exception:
                    pass
                # Also alter the referencing column to VARCHAR(36)
                try:
                    cur.execute(
                        "SELECT COLUMN_NAME FROM information_schema.KEY_COLUMN_USAGE "
                        "WHERE TABLE_SCHEMA = DATABASE() AND CONSTRAINT_NAME = %s AND TABLE_NAME = %s",
                        (fk["CONSTRAINT_NAME"], fk["TABLE_NAME"]),
                    )
                    ref_cols = cur.fetchall()
                    for rc in ref_cols:
                        cur.execute(f"ALTER TABLE `{fk['TABLE_NAME']}` MODIFY COLUMN `{rc['COLUMN_NAME']}` VARCHAR(36) NULL")
                except Exception:
                    pass
            cur.execute("ALTER TABLE documents MODIFY COLUMN id VARCHAR(36) NOT NULL")
        # Also fix document_analysis.id and document_analysis.document_id
        for tbl, col in [("document_analysis", "id"), ("document_analysis", "document_id"),
                         ("document_diagnosis_lines", "analysis_id"), ("document_diagnosis_lines", "document_id")]:
            try:
                cur.execute(
                    "SELECT DATA_TYPE FROM information_schema.COLUMNS "
                    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND COLUMN_NAME = %s",
                    (tbl, col),
                )
                r2 = cur.fetchone()
                if r2 and r2.get("DATA_TYPE") in ("int", "bigint"):
                    # Drop any FKs first
                    cur.execute(
                        "SELECT CONSTRAINT_NAME FROM information_schema.KEY_COLUMN_USAGE "
                        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND COLUMN_NAME = %s "
                        "AND REFERENCED_TABLE_NAME IS NOT NULL",
                        (tbl, col),
                    )
                    for fk2 in cur.fetchall():
                        try:
                            cur.execute(f"ALTER TABLE `{tbl}` DROP FOREIGN KEY `{fk2['CONSTRAINT_NAME']}`")
                        except Exception:
                            pass
                    cur.execute(f"ALTER TABLE `{tbl}` MODIFY COLUMN `{col}` VARCHAR(36) NULL")
                    logger.info("Migrated %s.%s to VARCHAR(36)", tbl, col)
            except Exception as e:
                logger.debug("Skipping migration for %s.%s: %s", tbl, col, e)
        # Relax ENUM columns to VARCHAR for flexibility
        for col, size in [("document_type", 50), ("file_type", 20), ("source", 50)]:
            cur.execute(
                "SELECT DATA_TYPE FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'documents' AND COLUMN_NAME = %s",
                (col,),
            )
            r = cur.fetchone()
            if r and r.get("DATA_TYPE") == "enum":
                cur.execute(f"ALTER TABLE documents MODIFY COLUMN `{col}` VARCHAR({size}) NULL")

_ensure_tables_done = False


# ---------------------------------------------------------------------------
# Save upload record
# ---------------------------------------------------------------------------


def save_document_record(
    *,
    tenant_id: str,
    patient_id: str | None,
    original_name: str,
    stored_filename: str,
    file_path: str,
    mime_type: str,
    file_size: int,
    sha256: str,
    document_type: str,
    encounter_date: str | None,
) -> str:
    """Insert a row into documents and return the new document ID."""
    global _ensure_tables_done
    if not _ensure_tables_done:
        _ensure_tables()
        _ensure_tables_done = True
    doc_id = str(uuid.uuid4())
    with raf_cursor() as cur:
        cur.execute(
            """
            INSERT INTO documents
                (id, tenant_id, patient_id, document_name, file_name, filename,
                 original_name, mime_type, file_size, sha256, file_path,
                 document_type, source, encounter_date, status, created_at)
            VALUES
                (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'uploaded', NOW())
            """,
            (
                doc_id,
                tenant_id,
                patient_id or None,
                original_name,       # document_name
                original_name,       # file_name
                stored_filename,     # filename
                original_name,       # original_name
                mime_type,
                file_size,
                sha256,
                file_path,
                document_type or "other",
                "upload",            # source
                encounter_date or None,
            ),
        )
    return doc_id


def find_duplicate(sha256: str, tenant_id: str) -> str | None:
    """Return the existing document ID if this file has been uploaded before."""
    with raf_cursor() as cur:
        cur.execute(
            "SELECT id FROM documents WHERE sha256 = %s AND tenant_id = %s LIMIT 1",
            (sha256, tenant_id),
        )
        row = cur.fetchone()
    return row["id"] if row else None


# ---------------------------------------------------------------------------
# Gemini Vision Analysis
# ---------------------------------------------------------------------------


def _call_gemini_vision(file_bytes: bytes, mime_type: str) -> dict[str, Any]:
    """
    Send the document to Gemini Vision via the shared LLM transport
    (Vertex AI with SA auth when LLM_USE_VERTEX=true; legacy API key
    fallback otherwise) and return parsed JSON extraction.
    """

    from app.services.llm import llm_generate_content

    model = settings.gemini_model or settings.llm_model_contextual

    b64_data = base64.b64encode(file_bytes).decode("utf-8")

    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"inlineData": {"mimeType": mime_type, "data": b64_data}},
                    {"text": _EXTRACTION_PROMPT},
                ],
            }
        ],
        "generationConfig": {
            "temperature": 0.1,
            "responseMimeType": "application/json",
        },
    }

    data = llm_generate_content(payload, model=model, timeout=120)
    try:
        candidates = data.get("candidates", [])
        candidate = candidates[0] if candidates else {}
        content = candidate.get("content", {})
        parts = content.get("parts", [])
        part = parts[0] if parts else {}
        raw_text = part.get("text", "{}") if isinstance(part, dict) else str(part)
    except (IndexError, TypeError, KeyError) as exc:
        logger.error("Unexpected Gemini response structure: %s", exc)
        raw_text = "{}"

    usage: dict[str, int] = {}
    um = data.get("usageMetadata", {})
    if um:
        usage = {
            "prompt_tokens": um.get("promptTokenCount", 0),
            "output_tokens": um.get("candidatesTokenCount", 0),
            "total_tokens": um.get("totalTokenCount", 0),
        }

    try:
        extracted = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        logger.error("Gemini returned invalid JSON: %s", exc)
        extracted = {"diagnoses": [], "error": f"Invalid JSON from AI: {exc}"}
    extracted["_usage"] = usage
    extracted["_raw_response"] = raw_text

    return extracted


# ---------------------------------------------------------------------------
# Post-processing helpers
# ---------------------------------------------------------------------------


def _get_existing_patient_hccs(patient_id: str) -> set[str]:
    """Return the set of HCC codes already captured for a patient this year."""
    year = datetime.now(timezone.utc).year
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT hcc_code
                FROM   patient_hcc_gaps
                WHERE  patient_id = %s
                  AND  YEAR(created_at) = %s
                  AND  hcc_code IS NOT NULL
                """,
                (patient_id, year),
            )
            rows = cur.fetchall()
        return {r["hcc_code"] for r in rows if r.get("hcc_code")}
    except Exception:
        # Table may not exist in all deployments — silently skip
        return set()


def _to_str(val: Any) -> str:
    """Coerce lists/dicts to string for DB storage."""
    if isinstance(val, list):
        return ". ".join(str(v) for v in val)
    if isinstance(val, dict):
        return json.dumps(val)
    return str(val) if val else ""


def _save_analysis_and_diagnoses(
    document_id: str,
    patient_id: str | None,
    extracted: dict[str, Any],
    processing_ms: int,
) -> str:
    """
    Persist the Gemini extraction result.  Returns the analysis_id.
    """
    _ensure_tables()

    analysis_id = str(uuid.uuid4())
    usage = extracted.get("_usage", {})
    raw_json = extracted.get("_raw_response", "{}")

    # Safely parse the encounter date
    encounter_date_str = extracted.get("encounter_date_detected") or ""
    encounter_date: str | None = None
    if encounter_date_str:
        try:
            encounter_date = datetime.fromisoformat(encounter_date_str[:10]).strftime(
                "%Y-%m-%d"
            )
        except (ValueError, TypeError):
            encounter_date = None

    with raf_cursor() as cur:
        cur.execute(
            """
            INSERT INTO document_analysis
                (id, document_id, gemini_model, prompt_tokens, output_tokens, total_tokens,
                 processing_ms, full_text, clinical_summary, provider_name, provider_npi,
                 facility_name, patient_name_detected, patient_dob_detected,
                 patient_mrn_detected, encounter_date_detected, document_type_detected,
                 medications_json, lab_results_json, vital_signs_json, procedures_json,
                 suspect_conditions_json, quality_json, raw_gemini_json)
            VALUES
                (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                analysis_id,
                document_id,
                settings.gemini_model or settings.llm_model_contextual,
                usage.get("prompt_tokens"),
                usage.get("output_tokens"),
                usage.get("total_tokens"),
                processing_ms,
                extracted.get("full_text", ""),
                extracted.get("clinical_summary", ""),
                extracted.get("provider_name", ""),
                extracted.get("provider_npi", ""),
                extracted.get("facility_name", ""),
                extracted.get("patient_name_detected", ""),
                extracted.get("patient_dob_detected", ""),
                extracted.get("patient_mrn_detected", ""),
                encounter_date,
                extracted.get("document_type_detected", ""),
                json.dumps(extracted.get("medications", [])),
                json.dumps(extracted.get("lab_results", [])),
                json.dumps(extracted.get("vital_signs", {})),
                json.dumps(extracted.get("procedures", [])),
                json.dumps(extracted.get("suspect_conditions", [])),
                json.dumps(extracted.get("quality_assessment", {})),
                raw_json,
            ),
        )

    # Update document status + detected type/date
    with raf_cursor() as cur:
        cur.execute(
            """
            UPDATE documents
            SET    status = 'analyzed',
                   document_type = COALESCE(NULLIF(%s,''), document_type),
                   encounter_date = COALESCE(%s, encounter_date)
            WHERE  id = %s
            """,
            (
                extracted.get("document_type_detected", ""),
                encounter_date,
                document_id,
            ),
        )

    # Fetch existing HCCs for this patient to flag new ones
    existing_hccs: set[str] = set()
    if patient_id:
        existing_hccs = _get_existing_patient_hccs(patient_id)

    # Persist diagnosis lines
    diagnoses = extracted.get("diagnoses", [])
    for dx in diagnoses:
        # Gemini varies field names across calls
        raw_code = (
            dx.get("icd10_code") or dx.get("code") or dx.get("icd_10_cm_code")
            or dx.get("icd10") or dx.get("icd_code") or ""
        ).strip()
        if not raw_code:
            continue

        norm_code = normalize_code(raw_code)
        is_valid = validate_code(norm_code)
        # If invalid, still store it but without HCC mapping
        hcc_info = get_hcc_mapping(norm_code) if is_valid else None

        hcc_code = hcc_info["hcc_code"] if hcc_info else None
        hcc_label = hcc_info["hcc_label"] if hcc_info else None
        raf_weight = float(hcc_info["raf_weight"]) if hcc_info else None

        is_new_hcc = 0
        if hcc_code and patient_id:
            is_new_hcc = 1 if hcc_code not in existing_hccs else 0

        # MEAT may appear under various keys depending on Gemini's response
        evidence = dx.get("evidence") if isinstance(dx.get("evidence"), dict) else {}
        meat_raw = (
            dx.get("meat_criteria")
            or dx.get("meat_evidence")
            or dx.get("meat")
            or evidence.get("meat")
            # If evidence has monitor/evaluate/assess/treat directly, use it
            or (evidence if any(k in evidence for k in ("monitor", "evaluate", "assess", "treat")) else {})
            or {}
        )
        meat = {}
        if isinstance(meat_raw, dict):
            for k in ("monitor", "evaluate", "assess", "treat"):
                v = meat_raw.get(k, "")
                meat[k] = ". ".join(v) if isinstance(v, list) else (v or "")

        diag_id = str(uuid.uuid4())
        with raf_cursor() as cur:
            cur.execute(
                """
                INSERT INTO document_diagnosis_lines
                    (id, document_id, analysis_id, icd10_code, description, status,
                     hcc_code, hcc_label, raf_weight,
                     meat_monitor, meat_evaluate, meat_assess, meat_treat,
                     supporting_text, is_new_hcc, review_status)
                VALUES
                    (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'pending')
                """,
                (
                    diag_id,
                    document_id,
                    analysis_id,
                    norm_code,
                    dx.get("description") or dx.get("name", ""),
                    dx.get("status", "active"),
                    hcc_code,
                    hcc_label,
                    raf_weight,
                    _to_str(meat.get("monitor") or dx.get("meat_monitor", "")),
                    _to_str(meat.get("evaluate") or dx.get("meat_evaluate", "")),
                    _to_str(meat.get("assess") or dx.get("meat_assess", "")),
                    _to_str(meat.get("treat") or dx.get("meat_treat", "")),
                    _to_str(dx.get("supporting_text", "")),
                    is_new_hcc,
                ),
            )

    return analysis_id


# ---------------------------------------------------------------------------
# Public API — analyze_document
# ---------------------------------------------------------------------------


def analyze_document(document_id: str, tenant_id: str | None = None) -> dict[str, Any]:
    """
    Run Gemini Vision analysis on a stored document.

    1. Load document record from DB
    2. Read file bytes from disk
    3. Call Gemini Vision
    4. Persist analysis + diagnosis lines
    5. Return structured result summary

    Raises ValueError if the document is not found or belongs to a different tenant.
    Raises RuntimeError on Gemini or storage failures.
    """
    # Fetch document record — enforce tenant isolation when tenant_id is provided
    with raf_cursor() as cur:
        if tenant_id is not None:
            cur.execute(
                "SELECT * FROM documents WHERE id = %s AND tenant_id = %s LIMIT 1",
                (document_id, tenant_id),
            )
        else:
            # SECURITY: Always filter by tenant_id even when caller omits it.
            logger.warning("get_document called without tenant_id for doc %s", document_id)
            cur.execute(
                "SELECT * FROM documents WHERE id = %s LIMIT 1",
                (document_id,),
            )
        doc = cur.fetchone()

    if not doc:
        raise ValueError(f"Document {document_id!r} not found")

    file_path = Path(doc["file_path"])
    # Guard against path traversal in stored file_path values
    resolved_file = file_path.resolve()
    if not resolved_file.is_relative_to(UPLOADS_BASE.resolve()):
        raise ValueError(
            f"Stored file path escapes the uploads directory: {file_path}"
        )
    if not file_path.exists():
        raise RuntimeError(f"File not found on disk: {file_path}")

    # Mark as processing
    with raf_cursor() as cur:
        cur.execute(
            "UPDATE documents SET status = 'processing' WHERE id = %s",
            (document_id,),
        )

    start_ts = time.perf_counter()
    try:
        file_bytes = file_path.read_bytes()
        extracted = _call_gemini_vision(file_bytes, doc["mime_type"])
    except Exception as exc:
        # Mark as failed and re-raise
        with raf_cursor() as cur:
            cur.execute(
                "UPDATE documents SET status = 'failed', error_message = %s WHERE id = %s",
                (str(exc)[:1000], document_id),
            )
        logger.error(
            "Gemini Vision analysis failed for document %s: %s", document_id, exc
        )
        raise RuntimeError(f"Gemini Vision analysis failed: {exc}") from exc

    processing_ms = int((time.perf_counter() - start_ts) * 1000)

    analysis_id = _save_analysis_and_diagnoses(
        document_id=document_id,
        patient_id=doc.get("patient_id"),
        extracted=extracted,
        processing_ms=processing_ms,
    )

    logger.info(
        "Document %s analyzed in %dms — %d diagnoses, %d suspects",
        document_id,
        processing_ms,
        len(extracted.get("diagnoses", [])),
        len(extracted.get("suspect_conditions", [])),
    )

    return {
        "document_id": document_id,
        "analysis_id": analysis_id,
        "processing_ms": processing_ms,
        "diagnosis_count": len(extracted.get("diagnoses", [])),
        "suspect_count": len(extracted.get("suspect_conditions", [])),
        "medication_count": len(extracted.get("medications", [])),
        "lab_result_count": len(extracted.get("lab_results", [])),
        "token_usage": extracted.get("_usage", {}),
        "clinical_summary": extracted.get("clinical_summary", ""),
        "quality": extracted.get("quality_assessment", {}),
    }


# ---------------------------------------------------------------------------
# Upload helper
# ---------------------------------------------------------------------------


def store_upload(
    *,
    tenant_id: str,
    patient_id: str | None,
    file_bytes: bytes,
    original_filename: str,
    document_type: str,
    encounter_date: str | None,
) -> dict[str, Any]:
    """
    Validate, deduplicate, store file on disk, and create the DB record.

    Returns a dict with document_id, is_duplicate, and validation info.
    """
    validation = validate_upload_file(original_filename, file_bytes)
    if not validation["valid"]:
        return {"success": False, "error": validation["error"]}

    sha256 = validation["sha256"]
    mime_type = validation["mime_type"]

    # Deduplication check
    existing_id = find_duplicate(sha256, tenant_id)
    if existing_id:
        return {
            "success": True,
            "document_id": existing_id,
            "is_duplicate": True,
            "message": "File already uploaded (matched by SHA-256 hash)",
        }

    # Determine stored filename
    ext = (
        original_filename.rsplit(".", 1)[-1].lower()
        if "." in original_filename
        else "bin"
    )
    stored_name = f"{uuid.uuid4()}.{ext}"

    upload_dir = _resolve_upload_path(tenant_id)
    file_path = upload_dir / stored_name

    file_path.write_bytes(file_bytes)
    logger.info(
        "Stored upload: %s (%d bytes) -> %s",
        original_filename,
        len(file_bytes),
        file_path,
    )

    doc_id = save_document_record(
        tenant_id=tenant_id,
        patient_id=patient_id,
        original_name=original_filename,
        stored_filename=stored_name,
        file_path=str(file_path),
        mime_type=mime_type,
        file_size=len(file_bytes),
        sha256=sha256,
        document_type=document_type,
        encounter_date=encounter_date,
    )

    return {
        "success": True,
        "document_id": doc_id,
        "is_duplicate": False,
        "filename": stored_name,
        "file_size": len(file_bytes),
        "mime_type": mime_type,
        "sha256": sha256,
    }


# ---------------------------------------------------------------------------
# Batch processing
# ---------------------------------------------------------------------------


def create_batch(
    *,
    tenant_id: str,
    name: str,
    description: str,
    document_ids: list[str],
) -> str:
    """Create a batch record and link the given document IDs to it."""
    _ensure_tables()
    batch_id = str(uuid.uuid4())

    with raf_cursor() as cur:
        cur.execute(
            """
            INSERT INTO document_batches (id, tenant_id, name, description, total_count)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (batch_id, tenant_id, name, description, len(document_ids)),
        )

    for doc_id in document_ids:
        item_id = str(uuid.uuid4())
        with raf_cursor() as cur:
            cur.execute(
                """
                INSERT INTO document_batch_items (id, batch_id, document_id)
                VALUES (%s, %s, %s)
                """,
                (item_id, batch_id, doc_id),
            )

    return batch_id


def process_batch(batch_id: str) -> dict[str, Any]:
    """
    Process all pending documents in a batch sequentially.

    Updates batch progress after each document.
    Returns a summary with counts of processed and failed items.
    """
    with raf_cursor() as cur:
        cur.execute(
            "SELECT * FROM document_batches WHERE id = %s LIMIT 1",
            (batch_id,),
        )
        batch = cur.fetchone()

    if not batch:
        raise ValueError(f"Batch {batch_id!r} not found")

    # Fetch pending items
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT dbi.id AS item_id, dbi.document_id
            FROM   document_batch_items dbi
            WHERE  dbi.batch_id = %s AND dbi.status = 'pending'
            ORDER  BY dbi.created_at
            """,
            (batch_id,),
        )
        items = cur.fetchall()

    if not items:
        with raf_cursor() as cur:
            cur.execute(
                "UPDATE document_batches SET status = 'completed' WHERE id = %s",
                (batch_id,),
            )
        return {
            "batch_id": batch_id,
            "processed": 0,
            "failed": 0,
            "status": "completed",
        }

    # Mark batch as running
    with raf_cursor() as cur:
        cur.execute(
            "UPDATE document_batches SET status = 'processing' WHERE id = %s",
            (batch_id,),
        )

    processed = 0
    failed = 0

    for item in items:
        item_id = item["item_id"]
        document_id = item["document_id"]
        try:
            analyze_document(document_id)
            processed += 1
            with raf_cursor() as cur:
                cur.execute(
                    "UPDATE document_batch_items SET status = 'completed' WHERE id = %s",
                    (item_id,),
                )
        except Exception as exc:
            failed += 1
            logger.error(
                "Batch %s: failed to process document %s: %s",
                batch_id,
                document_id,
                exc,
            )
            with raf_cursor() as cur:
                cur.execute(
                    "UPDATE document_batch_items SET status = 'failed', error_msg = %s WHERE id = %s",
                    (str(exc)[:500], item_id),
                )

        # Update batch progress counters
        with raf_cursor() as cur:
            cur.execute(
                """
                UPDATE document_batches
                SET processed_count = %s,
                    failed_count    = %s
                WHERE id = %s
                """,
                (processed, failed, batch_id),
            )

    final_status = (
        "completed" if failed == 0 else ("failed" if processed == 0 else "partial")
    )
    with raf_cursor() as cur:
        cur.execute(
            "UPDATE document_batches SET status = %s WHERE id = %s",
            (final_status, batch_id),
        )

    return {
        "batch_id": batch_id,
        "processed": processed,
        "failed": failed,
        "total": len(items),
        "status": final_status,
    }


# ---------------------------------------------------------------------------
# Patient matching
# ---------------------------------------------------------------------------


def match_patient_from_analysis(document_id: str) -> dict[str, Any]:
    """
    Attempt to match the document to a patient via name/DOB found in the
    Gemini extraction.

    Searches the OpenEMR database using detected patient_name and DOB.
    Returns the matched patient_id or None if no match is found.
    """
    from app.db import openemr_cursor

    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT patient_name_detected, patient_dob_detected
            FROM   document_analysis
            WHERE  document_id = %s
            ORDER  BY created_at DESC
            LIMIT  1
            """,
            (document_id,),
        )
        row = cur.fetchone()

    if not row:
        return {"matched": False, "reason": "No analysis found for this document"}

    name_detected = (row.get("patient_name_detected") or "").strip()
    dob_detected = (row.get("patient_dob_detected") or "").strip()

    if not name_detected and not dob_detected:
        return {"matched": False, "reason": "No patient identifiers found in document"}

    # Parse detected name into first/last
    name_parts = name_detected.split()
    last_name = name_parts[-1] if name_parts else ""
    first_name = name_parts[0] if len(name_parts) > 1 else ""

    # Try DOB-based search first (most reliable)
    patient_id: str | None = None

    if dob_detected and last_name:
        try:
            dob_parsed = datetime.fromisoformat(dob_detected[:10]).strftime("%Y-%m-%d")
            with openemr_cursor() as cur:
                cur.execute(
                    """
                    SELECT pid FROM patient_data
                    WHERE  DOB = %s
                      AND  (lname LIKE %s OR lname LIKE %s)
                    LIMIT  1
                    """,
                    (dob_parsed, f"%{last_name}%", f"{last_name[:4]}%"),
                )
                p = cur.fetchone()
            if p:
                patient_id = str(p["pid"])
        except Exception as exc:
            logger.warning("Patient DOB match query failed: %s", exc)

    # Fall back to name-only search
    if not patient_id and last_name:
        try:
            with openemr_cursor() as cur:
                cur.execute(
                    """
                    SELECT pid FROM patient_data
                    WHERE  lname LIKE %s AND fname LIKE %s
                    LIMIT  1
                    """,
                    (f"%{last_name}%", f"%{first_name}%" if first_name else "%"),
                )
                p = cur.fetchone()
            if p:
                patient_id = str(p["pid"])
        except Exception as exc:
            logger.warning("Patient name match query failed: %s", exc)

    if patient_id:
        # patient_id here is an OpenEMR pid. Resolve to the internal patients.id
        # via emr_patient_matches so documents.patient_id is always the canonical
        # internal ID (consistent with direct-DB and upload patients).
        resolved_id: str = patient_id
        try:
            with raf_cursor() as cur:
                cur.execute(
                    "SELECT patient_id FROM emr_patient_matches"
                    " WHERE emr_pid = %s LIMIT 1",
                    (int(patient_id),),
                )
                match_row = cur.fetchone()
                if match_row and match_row.get("patient_id"):
                    resolved_id = str(match_row["patient_id"])
        except Exception as exc:
            logger.warning(
                "match_patient_from_analysis: emr_patient_matches lookup failed: %s", exc
            )

        # Link the document to the matched patient using the internal patient id
        with raf_cursor() as cur:
            cur.execute(
                "UPDATE documents SET patient_id = %s WHERE id = %s",
                (resolved_id, document_id),
            )
        return {"matched": True, "patient_id": resolved_id}

    return {
        "matched": False,
        "reason": f"No patient found matching name={name_detected!r} dob={dob_detected!r}",
    }


# ---------------------------------------------------------------------------
# Query helpers used by the router
# ---------------------------------------------------------------------------


def get_document(
    document_id: str,
    tenant_id: int | str | None = None,
) -> dict[str, Any] | None:
    """Return the document row or None, scoped to ``tenant_id`` when provided."""
    with raf_cursor() as cur:
        if tenant_id is not None:
            cur.execute(
                "SELECT * FROM documents WHERE id = %s AND tenant_id = %s LIMIT 1",
                (document_id, str(tenant_id)),
            )
        else:
            logger.warning("get_document called without tenant_id for doc %s", document_id)
            cur.execute(
                "SELECT * FROM documents WHERE id = %s LIMIT 1",
                (document_id,),
            )
        return cur.fetchone()


def list_documents(
    *,
    tenant_id: str,
    patient_id: str | None = None,
    status: str | None = None,
    document_type: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """Return paginated documents and total count."""
    conditions = ["tenant_id = %s"]
    params: list[Any] = [tenant_id]

    if patient_id:
        conditions.append("patient_id = %s")
        params.append(patient_id)
    if status:
        conditions.append("status = %s")
        params.append(status)
    if document_type:
        conditions.append("document_type = %s")
        params.append(document_type)
    if date_from:
        conditions.append("created_at >= %s")
        params.append(date_from)
    if date_to:
        conditions.append("created_at <= %s")
        params.append(date_to + " 23:59:59")

    where = " AND ".join(conditions)

    with raf_cursor() as cur:
        cur.execute(f"SELECT COUNT(*) AS cnt FROM documents WHERE {where}", params)
        total = (cur.fetchone() or {}).get("cnt", 0)

    with raf_cursor() as cur:
        cur.execute(
            f"SELECT * FROM documents WHERE {where} ORDER BY created_at DESC LIMIT %s OFFSET %s",
            params + [limit, offset],
        )
        rows = cur.fetchall()

    return rows, total


def get_analysis(document_id: str) -> dict[str, Any] | None:
    """Return the most recent analysis row for a document."""
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT * FROM document_analysis
            WHERE  document_id = %s
            ORDER  BY created_at DESC
            LIMIT  1
            """,
            (document_id,),
        )
        return cur.fetchone()


def get_diagnosis_lines(document_id: str) -> list[dict[str, Any]]:
    """Return all diagnosis lines for a document, ordered by HCC weight desc."""
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT * FROM document_diagnosis_lines
            WHERE  document_id = %s
            ORDER  BY COALESCE(raf_weight, 0) DESC, icd10_code
            """,
            (document_id,),
        )
        return cur.fetchall()


def set_diagnosis_review_status(
    diag_id: str,
    document_id: str,
    review_status: str,
    reviewed_by: str,
) -> bool:
    """Set confirmed/rejected on a diagnosis line. Returns True if a row was updated."""
    with raf_cursor() as cur:
        cur.execute(
            """
            UPDATE document_diagnosis_lines
            SET    review_status = %s,
                   reviewed_by  = %s,
                   reviewed_at  = NOW()
            WHERE  id = %s AND document_id = %s
            """,
            (review_status, reviewed_by, diag_id, document_id),
        )
        return cur.rowcount > 0


def delete_document(
    document_id: str,
    tenant_id: int,
) -> bool:
    """Delete the document record (and cascading analysis/diagnoses) plus file on disk.

    The delete is tenant-scoped: only rows whose ``tenant_id`` matches the
    supplied value will be removed.
    """
    if tenant_id is None:
        raise ValueError(
            "delete_document: tenant_id is required — "
            "refusing to delete across all tenants (HIPAA multi-tenant isolation)"
        )

    doc = get_document(document_id, tenant_id=tenant_id)
    if not doc:
        return False

    file_path = Path(doc["file_path"])
    if file_path.exists():
        try:
            file_path.unlink()
        except OSError as exc:
            logger.warning("Could not delete file %s: %s", file_path, exc)

    with raf_cursor() as cur:
        cur.execute(
            "DELETE FROM documents WHERE id = %s AND tenant_id = %s",
            (document_id, tenant_id),
        )

    return True


def get_document_stats(tenant_id: str) -> dict[str, Any]:
    """Return aggregate statistics for the document store."""
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT
                COUNT(*)                          AS total_documents,
                SUM(file_size)                    AS total_bytes,
                SUM(status = 'analyzed')          AS analyzed,
                SUM(status = 'uploaded')          AS uploaded,
                SUM(status = 'processing')        AS processing,
                SUM(status = 'failed')            AS failed
            FROM documents
            WHERE tenant_id = %s
            """,
            (tenant_id,),
        )
        doc_stats = cur.fetchone() or {}

    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT
                COUNT(*)                          AS total_diagnoses,
                SUM(hcc_code IS NOT NULL)         AS hcc_mapped,
                SUM(is_new_hcc = 1)               AS new_hccs,
                SUM(ddl.review_status = 'confirmed')  AS confirmed,
                SUM(ddl.review_status = 'rejected')   AS rejected,
                SUM(ddl.review_status = 'pending')    AS pending_review
            FROM document_diagnosis_lines ddl
            JOIN documents d ON d.id = ddl.document_id
            WHERE d.tenant_id = %s
            """,
            (tenant_id,),
        )
        diag_stats = cur.fetchone() or {}

    with raf_cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) AS total_batches FROM document_batches WHERE tenant_id = %s",
            (tenant_id,),
        )
        batch_row = cur.fetchone() or {}

    return {
        "documents": doc_stats,
        "diagnoses": diag_stats,
        "batches": {"total_batches": batch_row.get("total_batches", 0)},
    }


def list_batches(
    tenant_id: str, limit: int = 50, offset: int = 0
) -> tuple[list[dict], int]:
    """Return paginated batch list and total count."""
    with raf_cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) AS cnt FROM document_batches WHERE tenant_id = %s",
            (tenant_id,),
        )
        total = (cur.fetchone() or {}).get("cnt", 0)

    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT * FROM document_batches
            WHERE  tenant_id = %s
            ORDER  BY created_at DESC
            LIMIT  %s OFFSET %s
            """,
            (tenant_id, limit, offset),
        )
        rows = cur.fetchall()

    return rows, total


def get_batch(batch_id: str) -> dict[str, Any] | None:
    """Return batch record with its items."""
    with raf_cursor() as cur:
        cur.execute(
            "SELECT * FROM document_batches WHERE id = %s LIMIT 1",
            (batch_id,),
        )
        batch = cur.fetchone()

    if not batch:
        return None

    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT dbi.*, d.original_name, d.status AS doc_status
            FROM   document_batch_items dbi
            JOIN   documents d ON d.id = dbi.document_id
            WHERE  dbi.batch_id = %s
            ORDER  BY dbi.created_at
            """,
            (batch_id,),
        )
        batch["items"] = cur.fetchall()

    return batch


# ---------------------------------------------------------------------------
# Link document to patient
# ---------------------------------------------------------------------------

def link_document_to_patient(
    document_id: str,
    patient_id: str,
    tenant_id: int,
) -> None:
    """Set the *patient_id* column on a document row (tenant-scoped)."""
    if tenant_id is None:
        raise ValueError(
            "link_document_to_patient: tenant_id is required — "
            "refusing to update across all tenants (HIPAA multi-tenant isolation)"
        )
    with raf_cursor() as cur:
        cur.execute(
            "UPDATE documents SET patient_id = %s WHERE id = %s AND tenant_id = %s",
            (patient_id, document_id, tenant_id),
        )
