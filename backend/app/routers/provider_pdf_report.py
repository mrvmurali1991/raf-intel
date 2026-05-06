"""Provider scorecard PDF export router.

Exposes a single authenticated endpoint:

    GET /api/providers/{provider_id}/report.pdf?year=YYYY -> application/pdf

The endpoint streams a one-page CMO-friendly provider scorecard PDF.  See
``app.services.provider_pdf_report.generate_provider_pdf`` for the assembly
logic.

Mounted on the ``providers`` router prefix (``/api/providers``).  Kept in a
separate module so the providers router file stays focused on CRUD /
scorecard JSON, and so importing this module's WeasyPrint dependency stays
lazy.
"""
# Do NOT add 'from __future__ import annotations' — breaks FastAPI schema gen.

import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response

from app.auth import get_current_user, require_permission
from app.rate_limit import limiter
from app.services.provider_pdf_report import generate_provider_pdf
from app.services.provider_service import get_provider

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/providers", tags=["providers"])

_CURRENT_YEAR = date.today().year


def _safe_filename_segment(value: str) -> str:
    """Sanitize a string for use in a Content-Disposition filename.

    Restricts to ASCII alphanumerics + dash so weird characters in last names
    (apostrophes, accented letters, spaces) do not break the header.
    """
    cleaned = "".join(
        c if (c.isalnum() or c in ("-", "_")) else "-" for c in (value or "")
    )
    cleaned = cleaned.strip("-").lower()
    return cleaned or "provider"


@router.get(
    "/{provider_id}/report.pdf",
    summary="Download single-page provider scorecard PDF",
    response_class=Response,
    responses={
        200: {
            "content": {"application/pdf": {}},
            "description": "Rendered single-page scorecard PDF.",
        },
        404: {"description": "Provider not found in caller's tenant."},
        500: {"description": "PDF render failed."},
    },
)
@limiter.limit("20/minute")
def download_provider_report(
    request: Request,
    provider_id: int,
    year: int = Query(
        default=_CURRENT_YEAR,
        ge=2015,
        le=_CURRENT_YEAR + 1,
        description="Measurement year (defaults to current).",
    ),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("providers", "read")),
) -> Response:
    """Return the single-page provider scorecard PDF.

    Auth, tenant scoping and rate-limiting follow the same patterns as the
    JSON ``/{provider_id}/scorecard`` endpoint:

    - JWT auth required (``get_current_user``).
    - ``providers:read`` permission required.
    - Rate-limited to 20 PDFs/min/IP.
    - Uses tenant_id from the authenticated user for scorecard scoping.
    """
    provider = get_provider(provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail=f"Provider {provider_id} not found")

    tenant_id = current_user.get("tenant_id")

    try:
        pdf_bytes: bytes = generate_provider_pdf(
            provider_id=provider_id,
            year=year,
            tenant_id=tenant_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "provider_pdf build failed provider_id=%d year=%d tenant=%s: %s",
            provider_id, year, tenant_id, exc, exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to build provider scorecard PDF. See server logs.",
        )

    last_name = _safe_filename_segment(provider.get("last_name") or "")
    filename = f"provider-{last_name or provider_id}-{year}.pdf"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
