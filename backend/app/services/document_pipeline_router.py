"""Document pipeline router — selects the right extractor for each document.

Extraction strategies
---------------------
- ``gemini_vision``  — primary path (Gemini multimodal, handles PDF/JPEG/PNG/WEBP/HEIC)
- ``ocr_fallback``   — deterministic OCR (Tesseract or AWS Textract)
- ``skip``           — document type not supported

42 CFR Part 2 compliance
------------------------
Documents in the ``behavioral_health`` or ``substance_abuse`` categories are
routed to ``ocr_fallback`` by default so no PHI is sent to an LLM provider.
A per-tenant ``disable_llm_documents`` flag enforces the same constraint
across all document classes for tenants that mandate it.
"""
from __future__ import annotations

import dataclasses
import logging
from typing import Any, Literal

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_GEMINI_MIMETYPES: frozenset[str] = frozenset(
    {
        "application/pdf",
        "image/jpeg",
        "image/png",
        "image/webp",
        "image/heic",
    }
)

# Document categories that must bypass LLM processing (42 CFR Part 2 default).
_NO_LLM_CATEGORIES: frozenset[str] = frozenset({"behavioral_health", "substance_abuse"})

ExtractorChoice = Literal["gemini_vision", "ocr_fallback", "skip"]


# ---------------------------------------------------------------------------
# Tenant policy model
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class TenantDocPolicy:
    """Snapshot of a tenant's document-processing policy.

    Populated from the ``tenant_document_policy`` table (migration 048).
    Defaults represent the permissive baseline for tenants that have not
    configured a custom policy.
    """

    tenant_id: str = ""
    disable_llm_documents: bool = False
    llm_blocked_categories: list[str] = dataclasses.field(default_factory=list)
    fallback_engine: str = "tesseract"


# ---------------------------------------------------------------------------
# Routing decision
# ---------------------------------------------------------------------------


def choose_extractor(
    doc_bytes: bytes,
    mimetype: str,
    tenant_policy: TenantDocPolicy,
    document_category: str | None = None,
) -> ExtractorChoice:
    """Decide which extractor to use for a document.

    Decision priority (highest first):

    1. Tenant-level LLM disable flag → ``ocr_fallback``
    2. Per-category tenant block list → ``ocr_fallback``
    3. Globally protected categories (42 CFR Part 2) → ``ocr_fallback``
    4. TIFF (Gemini does not support it) → ``ocr_fallback``
    5. Supported Gemini MIME type → ``gemini_vision``
    6. Everything else → ``skip``
    """
    mime = (mimetype or "").lower().strip()
    category = (document_category or "").lower().strip()

    # 1. Hard tenant-level LLM disable
    if tenant_policy.disable_llm_documents:
        log.debug(
            "choose_extractor: tenant %s has disable_llm_documents=True → ocr_fallback",
            tenant_policy.tenant_id,
        )
        return "ocr_fallback"

    # 2. Per-tenant blocked category list
    if category and category in {c.lower() for c in (tenant_policy.llm_blocked_categories or [])}:
        log.debug(
            "choose_extractor: category %r in tenant blocked list → ocr_fallback",
            category,
        )
        return "ocr_fallback"

    # 3. Globally protected 42 CFR Part 2 categories
    if category in _NO_LLM_CATEGORIES:
        log.debug(
            "choose_extractor: category %r is 42 CFR Part 2 protected → ocr_fallback",
            category,
        )
        return "ocr_fallback"

    # 4. TIFF — not supported by Gemini Vision
    if mime == "image/tiff":
        log.debug("choose_extractor: TIFF detected → ocr_fallback")
        return "ocr_fallback"

    # 5. Gemini-supported format
    if mime in _GEMINI_MIMETYPES:
        return "gemini_vision"

    # 6. Unsupported
    log.warning("choose_extractor: unsupported mimetype %r → skip", mime)
    return "skip"


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def process_document(
    doc_bytes: bytes,
    mimetype: str,
    tenant_id: str,
    raf_patient_id: int,
    document_category: str | None = None,
    tenant_policy: TenantDocPolicy | None = None,
) -> dict[str, Any]:
    """Orchestrate document extraction and route results to the NLP pipeline.

    Returns a dict with keys: ``extractor``, ``result`` (raw extractor output),
    and ``suspects`` (list, populated after NLP processing).

    Notes
    -----
    - Suspect / MEAT persistence is delegated to the existing NLP pipeline via
      the ``ai_pipeline.orchestrator`` module (imported lazily so this module
      remains unit-testable in isolation).
    - If the NLP pipeline is unavailable the raw OCR / Gemini text is returned
      with an empty suspects list and a warning logged.
    """
    if tenant_policy is None:
        tenant_policy = TenantDocPolicy(tenant_id=tenant_id)

    extractor = choose_extractor(doc_bytes, mimetype, tenant_policy, document_category)

    if extractor == "skip":
        log.info(
            "process_document: skipping document for patient %d (mimetype=%r)",
            raf_patient_id,
            mimetype,
        )
        return {"extractor": "skip", "result": None, "suspects": []}

    raw_result: dict[str, Any]

    if extractor == "ocr_fallback":
        from app.services.ocr_fallback import ocr_document  # lazy import

        engine = tenant_policy.fallback_engine or "tesseract"
        raw_result = ocr_document(doc_bytes, mimetype, engine=engine)  # type: ignore[arg-type]
        extracted_text = raw_result.get("full_text", "")

    else:  # gemini_vision
        # Gemini Vision path — defer to existing pipeline; return placeholder
        # so callers can see the routing decision.
        log.debug(
            "process_document: routing to gemini_vision for patient %d", raf_patient_id
        )
        raw_result = {"engine": "gemini_vision", "full_text": None}
        extracted_text = None  # Gemini handles its own text extraction

    # Route extracted text through existing NLP suspect pipeline when we have text.
    suspects: list[dict] = []
    if extracted_text:
        try:
            from app.services.ai_pipeline.orchestrator import run_text_pipeline  # lazy import

            suspects = run_text_pipeline(
                text=extracted_text,
                tenant_id=tenant_id,
                raf_patient_id=raf_patient_id,
            )
        except Exception as exc:  # pragma: no cover
            log.warning(
                "process_document: NLP pipeline unavailable (patient=%d): %s",
                raf_patient_id,
                exc,
            )

    return {"extractor": extractor, "result": raw_result, "suspects": suspects}
