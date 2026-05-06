"""
Recapture Audit Defense PDF builder.

Generates a tenant-scoped PDF that surfaces every dual-signed recaptured HCC
along with its MEAT evidence, source link, and primary/secondary coder
signatures.  Designed to be the package a coding director hands to a CMS
RADV auditor.

Mirrors the structure of ``app/services/radv/packet_builder.py`` (Jinja +
WeasyPrint, lazy import) so deployments that lack the WeasyPrint native
stack still import this module cleanly.

Public API
----------
build_audit_pdf(tenant_id, year=None) -> bytes
    Returns the rendered PDF bytes.

render_audit_html(tenant_id, year=None) -> str
    Returns the rendered HTML — useful for tests that want to assert on
    content without paying the WeasyPrint cost.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.services.meat_audit_service import (
    compute_audit_readiness,
    get_approved_gaps_for_pdf,
)

logger = logging.getLogger(__name__)


_TEMPLATE_DIR = Path(__file__).resolve().parent / "recapture_audit_pdf_templates"

_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
    trim_blocks=True,
    lstrip_blocks=True,
)


def _build_context(tenant_id: str, year: int | None) -> dict[str, Any]:
    gaps = get_approved_gaps_for_pdf(tenant_id=tenant_id, year=year)
    readiness = compute_audit_readiness(tenant_id=tenant_id)
    return {
        "tenant_id":   tenant_id,
        "year":        year,
        "gaps":        gaps,
        "readiness":   readiness,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }


def render_audit_html(tenant_id: str, year: int | None = None) -> str:
    """Render the Jinja HTML for the audit PDF (separated for testability)."""
    context = _build_context(tenant_id, year)
    tmpl = _env.get_template("audit.html")
    return tmpl.render(**context)


def _render_pdf(html: str) -> bytes:
    """Render HTML to PDF using WeasyPrint. Imported lazily."""
    try:
        from weasyprint import HTML  # type: ignore
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "WeasyPrint is not installed or its native dependencies are missing. "
            "Install weasyprint and system packages libpango, libcairo, libgdk-pixbuf."
        ) from exc

    return HTML(string=html).write_pdf()


def build_audit_pdf(tenant_id: str, year: int | None = None) -> bytes:
    """Build the recapture audit defense PDF for the given tenant.

    Parameters
    ----------
    tenant_id:
        Tenant scope (string, matches recapture_gaps.tenant_id storage).
    year:
        Optional measurement-year filter (recapture_gaps.current_year).

    Returns
    -------
    bytes
        Raw PDF bytes (starts with ``%PDF-``).
    """
    logger.info(
        "recapture_audit_pdf.build start tenant=%s year=%s",
        tenant_id, year,
    )
    html = render_audit_html(tenant_id, year)
    pdf_bytes = _render_pdf(html)
    logger.info(
        "recapture_audit_pdf.build done tenant=%s size_bytes=%d",
        tenant_id, len(pdf_bytes),
    )
    return pdf_bytes
