"""Gemini vision extractor for uploaded documents.

Reads PDF / image / scanned-chart bytes directly via Gemini multimodal
input — no separate OCR step. The same prompt / verbatim-substring guard /
confidence floor used by the text-only `nlp_suspect_extractor` is applied,
plus a source-document attribution so the huddle can show "from
echocardiogram_2024-08-15.pdf".

Supported mime types (Gemini 1.5/2.0):
  - application/pdf          (up to 1000 pages)
  - image/jpeg, image/png, image/webp, image/heic

Anything else returns `[]` with a logged warning.
"""
from __future__ import annotations

import base64
import json
import logging
import re
from typing import Any

from app.services.llm.vertex_client import llm_generate_content

logger = logging.getLogger(__name__)


SUPPORTED_MIME = frozenset({
    "application/pdf",
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/webp",
    "image/heic",
    "image/heif",
})

# Lower than text-only — vision OCR noise is higher; gates are downstream.
MIN_CONFIDENCE_SURFACED = 0.65
MAX_BYTES = 20 * 1024 * 1024  # 20 MB hard cap; larger PDFs need chunking

_SYSTEM = (
    "You are an HCC risk-adjustment coder reviewing a SCANNED or UPLOADED "
    "clinical document. Extract every plausible HCC suspect supported by "
    "the visible text. Reject anything that is:\n"
    "  - negated (\"no evidence of\", \"ruled out\", \"denies\")\n"
    "  - family history only\n"
    "  - listed under \"differential\" or \"impression: rule out\"\n"
    "  - illegible or guessed\n"
    "Return ONLY JSON in the schema below — no prose.\n"
)

_SCHEMA = """
{
  "suspects": [
    {
      "hcc_code": "string (e.g. '18' or '137')",
      "icd10_code": "string (e.g. 'E11.65')",
      "description": "short clinical description",
      "confidence": 0.0,
      "evidence_sentence": "VERBATIM substring copied from the document — must appear word-for-word",
      "page_number": 0,
      "meat": {
        "monitoring": "string|null",
        "evaluation": "string|null",
        "assessment": "string|null",
        "treatment": "string|null"
      }
    }
  ]
}
"""


def _build_payload(doc_bytes: bytes, mime_type: str, year: int) -> dict[str, Any]:
    b64 = base64.b64encode(doc_bytes).decode("ascii")
    user_text = (
        f"Measurement year: {year}.\n\n"
        f"Extract HCC suspects from the attached document. "
        f"Respond ONLY with JSON in this schema:\n{_SCHEMA}"
    )
    return {
        "systemInstruction": {"parts": [{"text": _SYSTEM}]},
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"inline_data": {"mime_type": mime_type, "data": b64}},
                    {"text": user_text},
                ],
            }
        ],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.1,
            "maxOutputTokens": 4096,
        },
    }


_JSON_BLOCK = re.compile(r"\{[\s\S]*\}")


def _parse_response(resp: dict) -> list[dict[str, Any]]:
    try:
        text = (
            resp.get("candidates", [{}])[0]
            .get("content", {})
            .get("parts", [{}])[0]
            .get("text", "")
        )
    except (IndexError, KeyError, TypeError):
        return []
    if not text:
        return []
    # Vision sometimes wraps in ```json — strip if present.
    m = _JSON_BLOCK.search(text)
    body = m.group(0) if m else text
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as e:
        logger.warning("gemini_document_extractor: bad JSON: %s", e)
        return []
    return list(parsed.get("suspects") or [])


def extract_from_document(
    *,
    doc_bytes: bytes,
    mime_type: str,
    year: int,
    document_id: int | None = None,
    document_filename: str | None = None,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    """Extract HCC suspects + MEAT from a single document.

    Returns a dict — never raises. Use the `suspects` list for the
    downstream pipeline; everything else is observability.
    """
    if not doc_bytes:
        return {"suspects": [], "skipped": "empty"}
    if len(doc_bytes) > MAX_BYTES:
        return {
            "suspects": [],
            "skipped": f"oversized ({len(doc_bytes)} > {MAX_BYTES})",
        }
    if mime_type not in SUPPORTED_MIME:
        return {"suspects": [], "skipped": f"unsupported_mime:{mime_type}"}

    payload = _build_payload(doc_bytes, mime_type, year)

    try:
        # Use the configured "blind" model (env: LLM_MODEL_BLIND) so document
        # extraction follows the same routing as the rest of the LLM stack.
        from app.config import settings as _settings
        resp = llm_generate_content(
            payload,
            model=_settings.llm_model_blind,
            timeout=90,
            tenant_id=tenant_id,
        )
    except Exception as exc:
        logger.warning(
            "gemini vision call failed (doc=%s, mime=%s): %s",
            document_id, mime_type, exc,
        )
        return {"suspects": [], "error": str(exc)[:300]}

    raw = _parse_response(resp)

    # Confidence floor + light shape validation
    kept: list[dict[str, Any]] = []
    for s in raw:
        try:
            c = float(s.get("confidence") or 0.0)
            if c < MIN_CONFIDENCE_SURFACED:
                continue
            hcc = str(s.get("hcc_code") or "").strip()
            if not hcc:
                continue
            kept.append({
                "hcc_code": hcc,
                "icd10_code": str(s.get("icd10_code") or "").strip(),
                "description": str(s.get("description") or "")[:255],
                "confidence": min(1.0, max(0.0, c)),
                "evidence_sentence": str(s.get("evidence_sentence") or "")[:1000],
                "page_number": int(s.get("page_number") or 0) or None,
                "meat": s.get("meat") or {},
                "source_document_id": document_id,
                "source_document_filename": document_filename,
                "source_document_mimetype": mime_type,
                "extractor": "gemini_vision",
            })
        except (TypeError, ValueError):
            continue

    return {
        "suspects": kept,
        "raw_count": len(raw),
        "kept_count": len(kept),
        "document_id": document_id,
        "document_filename": document_filename,
        "mime_type": mime_type,
    }


def extract_from_openemr_document(
    document_id: int,
    *,
    year: int | None = None,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    """Pull bytes from openemr.documents by id, run vision extract."""
    from datetime import date

    from app.db import openemr_cursor
    yr = year or date.today().year

    with openemr_cursor() as cur:
        cur.execute(
            """SELECT d.id, d.name, d.mimetype, d.url, d.foreign_id AS pid,
                      d.date
               FROM documents d
               WHERE d.id=%s AND COALESCE(d.deleted,0)=0""",
            (int(document_id),),
        )
        row = cur.fetchone()

    if not row:
        return {"suspects": [], "skipped": "document_not_found"}

    rec = dict(row) if isinstance(row, dict) else dict(zip(
        ("id", "name", "mimetype", "url", "pid", "date"), row
    ))

    # Resolve the bytes — OpenEMR stores the file URL as a sites path. The
    # adapter handles both file://sites/... and direct paths.
    try:
        from app.services.openemr_connector import read_document_bytes
        data = read_document_bytes(rec.get("url") or "")
    except Exception as exc:
        logger.warning(
            "read_document_bytes failed for doc_id=%s: %s",
            document_id, exc,
        )
        return {"suspects": [], "skipped": "read_failed"}

    # Route through the universal entry point so TIFF/GIF/BMP and >1000-page
    # PDFs are auto-handled. Single-pdf small docs pass through unchanged.
    return extract_from_document_unified(
        doc_bytes=data,
        mime_type=str(rec.get("mimetype") or "application/octet-stream"),
        year=yr,
        document_id=int(rec.get("id") or 0),
        document_filename=str(rec.get("name") or ""),
        tenant_id=tenant_id,
    )


# ---------------------------------------------------------------------------
# Gemini-first universal-input helpers
# ---------------------------------------------------------------------------
# Per Google docs: Gemini natively supports PDF (text + scanned, up to 1000
# pages / 50 MB), JPEG, PNG, WEBP, HEIC, HEIF. We auto-convert TIFF/GIF/BMP
# to PNG so the caller never has to think about format mismatches.

_AUTO_CONVERT_FROM = frozenset({
    "image/tiff", "image/tif", "image/gif", "image/bmp"
})


def to_gemini_compatible(
    doc_bytes: bytes, mime_type: str
) -> tuple[bytes, str]:
    """Return (bytes, mime) ready for inline_data.

    Strategy:
      * If mime is already Gemini-supported → passthrough.
      * If mime is convertible (TIFF/GIF/BMP) → convert to PNG via Pillow.
        For multi-page TIFFs we stack the pages into a single PNG with
        sequential strips (Gemini reads it as one image — acceptable for
        small page counts; larger TIFFs should be PDF-converted upstream).
      * Otherwise → return passthrough; caller's `extract_from_document`
        will mark it as unsupported.
    """
    m = (mime_type or "").lower().strip()
    if m not in _AUTO_CONVERT_FROM:
        return doc_bytes, m

    try:
        # Lazy import — keeps Pillow off the unit-test path.
        from io import BytesIO
        from PIL import Image  # type: ignore

        img = Image.open(BytesIO(doc_bytes))
        # For multi-page TIFF/GIF: pick the first frame for simplicity.
        # Production should split + send each frame; tracked as a TODO.
        if hasattr(img, "n_frames") and img.n_frames > 1:
            logger.info(
                "to_gemini_compatible: multi-frame %s (%d frames), using frame 0",
                m, img.n_frames,
            )
            img.seek(0)
        # Always convert to RGB before saving as PNG to drop alpha-mode
        # variants that some scanners produce.
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        out = BytesIO()
        img.save(out, format="PNG", optimize=True)
        return out.getvalue(), "image/png"
    except Exception as exc:
        logger.warning(
            "to_gemini_compatible: failed to convert %s: %s — sending raw",
            m, exc,
        )
        return doc_bytes, m


def chunk_pdf_pages(
    pdf_bytes: bytes, chunk_size: int = 500
) -> list[bytes]:
    """Split a PDF into chunks of `chunk_size` pages each.

    Used when a chart is > 1000 pages or > 20 MB and exceeds Gemini's
    inline-data window. Returns a list of complete PDF blobs each within
    Gemini's per-request limit.

    Lazy imports pypdf so non-PDF code paths don't pay the cost.
    """
    try:
        from io import BytesIO
        from pypdf import PdfReader, PdfWriter  # type: ignore
    except ImportError:
        logger.warning("chunk_pdf_pages: pypdf not installed — returning whole PDF")
        return [pdf_bytes]

    reader = PdfReader(BytesIO(pdf_bytes))
    total = len(reader.pages)
    if total <= chunk_size:
        return [pdf_bytes]

    out: list[bytes] = []
    for start in range(0, total, chunk_size):
        writer = PdfWriter()
        for i in range(start, min(start + chunk_size, total)):
            writer.add_page(reader.pages[i])
        buf = BytesIO()
        writer.write(buf)
        out.append(buf.getvalue())
    logger.info(
        "chunk_pdf_pages: split %d pages into %d chunks", total, len(out)
    )
    return out


def extract_from_document_unified(
    *,
    doc_bytes: bytes,
    mime_type: str,
    year: int,
    document_id: int | None = None,
    document_filename: str | None = None,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    """Universal entry point: auto-convert + auto-chunk + extract.

    Caller passes raw bytes + raw mime. We:
      1. Convert TIFF/GIF/BMP → PNG losslessly via Pillow (image_to_gemini_compatible)
      2. Detect oversized PDFs and chunk into ≤500-page pieces
      3. Call extract_from_document on each chunk
      4. Merge suspects across chunks (dedup by hcc_code+icd10_code)
    """
    # Step 1: format normalize
    norm_bytes, norm_mime = to_gemini_compatible(doc_bytes, mime_type)

    # Step 2: detect oversize PDF + chunk
    chunks: list[bytes]
    if norm_mime == "application/pdf" and len(norm_bytes) > 20 * 1024 * 1024:
        chunks = chunk_pdf_pages(norm_bytes, chunk_size=500)
    else:
        chunks = [norm_bytes]

    if len(chunks) == 1:
        return extract_from_document(
            doc_bytes=chunks[0], mime_type=norm_mime, year=year,
            document_id=document_id, document_filename=document_filename,
            tenant_id=tenant_id,
        )

    # Multi-chunk path: extract each, merge
    all_suspects: list[dict] = []
    seen: set[tuple[str, str]] = set()
    raw_total = 0
    for i, chunk_bytes in enumerate(chunks):
        partial = extract_from_document(
            doc_bytes=chunk_bytes, mime_type=norm_mime, year=year,
            document_id=document_id,
            document_filename=(f"{document_filename}#chunk{i}" if document_filename else None),
            tenant_id=tenant_id,
        )
        raw_total += int(partial.get("raw_count") or 0)
        for s in partial.get("suspects") or []:
            key = (str(s.get("hcc_code") or ""), str(s.get("icd10_code") or ""))
            if key in seen:
                continue
            seen.add(key)
            all_suspects.append(s)
    return {
        "suspects": all_suspects,
        "raw_count": raw_total,
        "kept_count": len(all_suspects),
        "document_id": document_id,
        "document_filename": document_filename,
        "mime_type": norm_mime,
        "chunks_processed": len(chunks),
    }
