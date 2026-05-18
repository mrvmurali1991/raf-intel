"""OCR fallback pipeline — Tesseract and AWS Textract engines.

Used when Gemini Vision is unavailable or explicitly disabled for a document
class (e.g. 42 CFR Part 2 behavioral-health notes).

Supported formats
-----------------
- PDF     → convert pages to images via pypdfium2, OCR each page
- TIFF    → split multi-page TIFF via Pillow, OCR each page
- JPEG / PNG → single-page OCR

Return value
------------
::

    {
        "full_text": str,
        "pages": [{"page": int, "text": str, "confidence": float}],
        "engine": str,  # "tesseract" | "aws_textract"
    }

All heavy imports (pytesseract, pypdfium2, Pillow, boto3) are lazy so that the
module stays importable in test environments that lack those binaries.
"""
from __future__ import annotations

import io
import logging
import os
from typing import Literal

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_LARGE_DOC_BYTES = 50 * 1024 * 1024  # 50 MB

_GEMINI_MIMETYPES: frozenset[str] = frozenset(
    {
        "application/pdf",
        "image/jpeg",
        "image/png",
        "image/webp",
        "image/heic",
    }
)


# ---------------------------------------------------------------------------
# Low-level OCR helpers
# ---------------------------------------------------------------------------


def tesseract_ocr(image_bytes: bytes) -> tuple[str, float]:
    """Run Tesseract on *image_bytes* (any Pillow-readable format).

    Returns ``(text, mean_confidence)`` where *mean_confidence* is the average
    word-level confidence score (0–100), normalised to 0–1.
    """
    try:
        import pytesseract  # lazy import
        from PIL import Image  # lazy import
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "pytesseract and/or Pillow not installed. "
            "Add them to requirements.txt to use the Tesseract OCR engine."
        ) from exc

    img = Image.open(io.BytesIO(image_bytes))
    data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)

    words: list[str] = []
    confidences: list[float] = []
    for word, conf in zip(data["text"], data["conf"]):
        if str(conf) == "-1" or word.strip() == "":
            continue
        words.append(word)
        confidences.append(float(conf))

    text = " ".join(words)
    mean_conf = (sum(confidences) / len(confidences) / 100.0) if confidences else 0.0
    return text, mean_conf


def aws_textract_ocr(doc_bytes: bytes, mimetype: str) -> tuple[str, float]:
    """Call AWS Textract AnalyzeDocument on *doc_bytes*.

    Required environment variable: ``AWS_REGION``.

    Returns ``(text, mean_confidence)`` where *mean_confidence* is the average
    LINE-block confidence normalised to 0–1.
    """
    try:
        import boto3  # lazy import
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "boto3 not installed. Add it to requirements.txt to use AWS Textract."
        ) from exc

    region = os.environ.get("AWS_REGION", "us-east-1")
    client = boto3.client("textract", region_name=region)

    # Textract AnalyzeDocument accepts raw bytes for single-page docs.
    response = client.analyze_document(
        Document={"Bytes": doc_bytes},
        FeatureTypes=[],  # plain text only — no Queries / Forms / Tables
    )

    blocks = response.get("Blocks", [])
    lines: list[str] = []
    confidences: list[float] = []
    for block in blocks:
        if block.get("BlockType") == "LINE":
            lines.append(block.get("Text", ""))
            conf = block.get("Confidence", 0.0)
            confidences.append(float(conf))

    text = "\n".join(lines)
    mean_conf = (sum(confidences) / len(confidences) / 100.0) if confidences else 0.0
    return text, mean_conf


# ---------------------------------------------------------------------------
# Engine selection
# ---------------------------------------------------------------------------


def _select_engine(
    doc_bytes: bytes,
    explicit_engine: Literal["tesseract", "aws_textract"] | None = None,
) -> Literal["tesseract", "aws_textract"]:
    """Return the engine to use based on env + doc size + explicit override."""
    if explicit_engine:
        return explicit_engine

    env_engine = os.environ.get("OCR_ENGINE", "").lower()
    if env_engine == "aws_textract":
        return "aws_textract"

    if len(doc_bytes) > _LARGE_DOC_BYTES:
        log.info(
            "Document exceeds 50 MB (%d bytes); switching to aws_textract.",
            len(doc_bytes),
        )
        return "aws_textract"

    return "tesseract"


# ---------------------------------------------------------------------------
# Per-page OCR dispatch
# ---------------------------------------------------------------------------


def _ocr_image(image_bytes: bytes, engine: Literal["tesseract", "aws_textract"]) -> tuple[str, float]:
    if engine == "aws_textract":
        return aws_textract_ocr(image_bytes, "image/png")
    return tesseract_ocr(image_bytes)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def ocr_document(
    doc_bytes: bytes,
    mimetype: str,
    engine: Literal["tesseract", "aws_textract"] = "tesseract",
) -> dict:
    """OCR *doc_bytes* and return structured text + page coords.

    Parameters
    ----------
    doc_bytes:
        Raw document bytes.
    mimetype:
        MIME type string, e.g. ``"application/pdf"`` or ``"image/tiff"``.
    engine:
        Preferred engine.  May be overridden by env ``OCR_ENGINE`` or doc
        size heuristic.

    Returns
    -------
    dict
        ``{full_text, pages: [{page, text, confidence}], engine}``
    """
    chosen_engine = _select_engine(doc_bytes, explicit_engine=engine)
    mime = (mimetype or "").lower().strip()

    pages: list[dict] = []

    if mime == "application/pdf":
        pages = _ocr_pdf(doc_bytes, chosen_engine)
    elif mime == "image/tiff":
        pages = _ocr_tiff(doc_bytes, chosen_engine)
    elif mime in ("image/jpeg", "image/png", "image/webp", "image/heic"):
        text, conf = _ocr_image(doc_bytes, chosen_engine)
        pages = [{"page": 1, "text": text, "confidence": conf}]
    else:
        log.warning("ocr_document: unsupported mimetype %r — returning empty result.", mime)
        pages = [{"page": 1, "text": "", "confidence": 0.0}]

    full_text = "\n\n".join(p["text"] for p in pages if p["text"])
    return {"full_text": full_text, "pages": pages, "engine": chosen_engine}


def _ocr_pdf(doc_bytes: bytes, engine: Literal["tesseract", "aws_textract"]) -> list[dict]:
    """Convert PDF pages to images via pypdfium2 then OCR each."""
    try:
        import pypdfium2 as pdfium  # lazy import
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "pypdfium2 not installed. Add it to requirements.txt to OCR PDFs."
        ) from exc

    pdf = pdfium.PdfDocument(doc_bytes)
    results: list[dict] = []
    for page_idx in range(len(pdf)):
        page = pdf[page_idx]
        bitmap = page.render(scale=2.0)  # 150 dpi equivalent
        pil_image = bitmap.to_pil()
        buf = io.BytesIO()
        pil_image.save(buf, format="PNG")
        text, conf = _ocr_image(buf.getvalue(), engine)
        results.append({"page": page_idx + 1, "text": text, "confidence": conf})
    return results


def _ocr_tiff(doc_bytes: bytes, engine: Literal["tesseract", "aws_textract"]) -> list[dict]:
    """Split multi-page TIFF via Pillow then OCR each frame."""
    try:
        from PIL import Image  # lazy import
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "Pillow not installed. Add it to requirements.txt to OCR TIFF files."
        ) from exc

    img = Image.open(io.BytesIO(doc_bytes))
    results: list[dict] = []
    frame_idx = 0
    while True:
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        text, conf = _ocr_image(buf.getvalue(), engine)
        results.append({"page": frame_idx + 1, "text": text, "confidence": conf})
        frame_idx += 1
        try:
            img.seek(frame_idx)
        except EOFError:
            break
    return results
