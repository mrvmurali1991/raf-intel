# Note: do NOT use 'from __future__ import annotations' here —
# it breaks FastAPI/Pydantic schema generation (ForwardRef errors in /openapi.json).

"""Admin endpoints for per-tenant document-processing policy.

Controls whether Gemini Vision LLM extraction is disabled for a tenant (e.g.
for 42 CFR Part 2 / HIPAA-sensitive document classes) and which OCR fallback
engine to use.

Route prefix: /api/admin/tenant
Tags: admin, ocr-policy
"""

import logging
from datetime import datetime, timezone
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.auth import get_current_user, require_role
from app.db import raf_cursor

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/admin/tenant",
    tags=["admin", "ocr-policy"],
    dependencies=[Depends(get_current_user)],
)

# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

_VALID_ENGINES = {"tesseract", "aws_textract"}


class DocPolicyResponse(BaseModel):
    tenant_id: str
    disable_llm_documents: bool
    llm_blocked_categories: List[str]
    fallback_engine: str
    updated_at: Optional[datetime] = None
    updated_by_user_id: Optional[int] = None


class DocPolicyUpdate(BaseModel):
    disable_llm_documents: bool = Field(
        default=False,
        description="When true, all documents bypass Gemini and use the OCR fallback engine.",
    )
    llm_blocked_categories: List[str] = Field(
        default_factory=list,
        description=(
            "Document categories that must use OCR fallback regardless of the global flag. "
            "e.g. ['behavioral_health', 'substance_abuse']"
        ),
    )
    fallback_engine: str = Field(
        default="tesseract",
        description="OCR engine to use when LLM is bypassed. One of: tesseract, aws_textract.",
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_tenant_id_for_user(current_user: dict) -> str:
    tenant_id = current_user.get("tenant_id") or current_user.get("active_tenant_id")
    if not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No tenant_id associated with this user.",
        )
    return str(tenant_id)


# ---------------------------------------------------------------------------
# GET /api/admin/tenant/doc-policy
# ---------------------------------------------------------------------------


@router.get(
    "/doc-policy",
    summary="Get tenant document-processing policy",
    response_model=DocPolicyResponse,
)
def get_doc_policy(
    current_user: dict = Depends(require_role("admin")),
) -> Any:
    """Return the current document-processing policy for the caller's tenant.

    If no policy row exists the default permissive policy is returned
    (LLM enabled, tesseract fallback engine).
    """
    tenant_id = _get_tenant_id_for_user(current_user)

    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT tenant_id, disable_llm_documents, llm_blocked_categories,
                   fallback_engine, updated_at, updated_by_user_id
            FROM tenant_document_policy
            WHERE tenant_id = %s
            LIMIT 1
            """,
            (tenant_id,),
        )
        row = cur.fetchone()

    if row is None:
        return DocPolicyResponse(
            tenant_id=tenant_id,
            disable_llm_documents=False,
            llm_blocked_categories=[],
            fallback_engine="tesseract",
        )

    import json

    raw_categories = row.get("llm_blocked_categories") or "[]"
    if isinstance(raw_categories, str):
        categories = json.loads(raw_categories)
    else:
        categories = raw_categories or []

    return DocPolicyResponse(
        tenant_id=row["tenant_id"],
        disable_llm_documents=bool(row["disable_llm_documents"]),
        llm_blocked_categories=categories,
        fallback_engine=row["fallback_engine"] or "tesseract",
        updated_at=row.get("updated_at"),
        updated_by_user_id=row.get("updated_by_user_id"),
    )


# ---------------------------------------------------------------------------
# PUT /api/admin/tenant/doc-policy
# ---------------------------------------------------------------------------


@router.put(
    "/doc-policy",
    summary="Update tenant document-processing policy",
    response_model=DocPolicyResponse,
)
def update_doc_policy(
    body: DocPolicyUpdate,
    current_user: dict = Depends(require_role("admin")),
) -> Any:
    """Create or replace the document-processing policy for the caller's tenant.

    Only ``admin`` role users may call this endpoint.
    """
    tenant_id = _get_tenant_id_for_user(current_user)

    if body.fallback_engine not in _VALID_ENGINES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid fallback_engine. Must be one of: {sorted(_VALID_ENGINES)}.",
        )

    user_id: Optional[int] = current_user.get("user_id") or current_user.get("id")
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    import json

    categories_json = json.dumps(body.llm_blocked_categories)

    with raf_cursor() as cur:
        cur.execute(
            """
            INSERT INTO tenant_document_policy
                (tenant_id, disable_llm_documents, llm_blocked_categories,
                 fallback_engine, updated_at, updated_by_user_id)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                disable_llm_documents  = VALUES(disable_llm_documents),
                llm_blocked_categories = VALUES(llm_blocked_categories),
                fallback_engine        = VALUES(fallback_engine),
                updated_at             = VALUES(updated_at),
                updated_by_user_id     = VALUES(updated_by_user_id)
            """,
            (
                tenant_id,
                int(body.disable_llm_documents),
                categories_json,
                body.fallback_engine,
                now,
                user_id,
            ),
        )

    logger.info(
        "tenant_doc_policy updated: tenant=%s disable_llm=%s engine=%s by user=%s",
        tenant_id,
        body.disable_llm_documents,
        body.fallback_engine,
        user_id,
    )

    return DocPolicyResponse(
        tenant_id=tenant_id,
        disable_llm_documents=body.disable_llm_documents,
        llm_blocked_categories=body.llm_blocked_categories,
        fallback_engine=body.fallback_engine,
        updated_at=now,
        updated_by_user_id=user_id,
    )
