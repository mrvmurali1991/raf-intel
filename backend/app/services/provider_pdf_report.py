"""Single-page provider scorecard PDF report.

Generates a CMO-friendly, print-optimized 1-page PDF artifact for network-
leadership meetings.  The pattern mirrors ``app.services.radv.packet_builder``:
Jinja2 HTML template + WeasyPrint, with a lazy import of WeasyPrint so the
module is importable in environments without the native GObject/Pango/Cairo
stack.

Public API
----------
generate_provider_pdf(provider_id, year, *, tenant_id=None) -> bytes
    Return the rendered PDF bytes.  The router layer is responsible for IDOR
    / tenant scoping; this service accepts ``tenant_id`` and forwards it to
    the underlying scorecard service so the metrics shown match the user's
    tenant.

Layout (single page, US Letter)
-------------------------------
- Provider header: name, credential, NPI, specialty, panel size.
- 4 KPI cards: RAF, Capture %, Recapture %, MEAT %.
- Revenue opportunity strip (currency formatted).
- Top 5 HCC opportunities table (by missed revenue).
- Audit risk badge (HIGH / MEDIUM / LOW), derived from documentation
  quality + open suspect counts.
- Footer watermark: "RAF Intelligence — Generated {date} — Confidential".
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Template environment — sibling directory keeps the namespace clear and
# avoids a module/package name clash with provider_pdf_report.py itself.
# ---------------------------------------------------------------------------

_TEMPLATE_DIR = (
    Path(__file__).resolve().parent / "provider_pdf_report_templates"
)

_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
    trim_blocks=True,
    lstrip_blocks=True,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pct(value: Any) -> str:
    """Format a 0..1 ratio (or None) as a 'NN%' string."""
    try:
        if value is None:
            return "—"
        return f"{round(float(value) * 100)}%"
    except (TypeError, ValueError):
        return "—"


def _num(value: Any, digits: int = 2) -> str:
    try:
        if value is None:
            return "—"
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "—"


def _money(value: Any) -> str:
    try:
        if value is None:
            return "$0"
        v = float(value)
        return f"${v:,.0f}"
    except (TypeError, ValueError):
        return "$0"


def _audit_risk(scorecard: dict[str, Any]) -> tuple[str, str]:
    """Derive an audit-risk band + tone from the scorecard.

    Heuristic (deterministic so the report is reproducible):
        HIGH   – documentation_quality_score < 0.50  OR
                 meat_completeness_avg       < 0.50  OR
                 suspects_open               > 25
        MEDIUM – documentation_quality_score < 0.70  OR
                 meat_completeness_avg       < 0.70  OR
                 suspects_open               > 10
        LOW    – otherwise
    """
    doc_q = scorecard.get("documentation_quality_score") or 0.0
    meat = scorecard.get("meat_completeness_avg") or 0.0
    open_susp = int(scorecard.get("suspects_open") or 0)

    try:
        doc_q = float(doc_q)
        meat = float(meat)
    except (TypeError, ValueError):
        doc_q = meat = 0.0

    if doc_q < 0.50 or meat < 0.50 or open_susp > 25:
        return "HIGH", "high"
    if doc_q < 0.70 or meat < 0.70 or open_susp > 10:
        return "MEDIUM", "medium"
    return "LOW", "low"


# ---------------------------------------------------------------------------
# Data assembly
# ---------------------------------------------------------------------------


def _build_context(
    provider_id: int,
    year: int,
    tenant_id: int | str | None,
) -> dict[str, Any]:
    """Assemble the Jinja context for the scorecard PDF.

    Reuses ``provider_service`` so the numbers match what the UI shows.
    Imports are local to this function so that importing this module does
    not pull in the full provider_service stack at module-load time.
    """
    from app.services.provider_service import (
        calculate_hcc_performance,
        calculate_provider_scorecard,
        get_latest_scorecard,
        get_provider,
    )

    provider = get_provider(provider_id) or {}

    # Prefer the cached snapshot when fresh; fall back to a live calc so the
    # PDF works on first-ever click for a provider.
    tid: int | None
    try:
        tid = int(tenant_id) if tenant_id is not None else None
    except (TypeError, ValueError):
        tid = None

    scorecard: dict[str, Any] | None = None
    try:
        scorecard = get_latest_scorecard(provider_id, year)
    except Exception as exc:  # noqa: BLE001
        logger.debug("provider_pdf: scorecard lookup failed pid=%s: %s", provider_id, exc)

    if not scorecard:
        try:
            scorecard = calculate_provider_scorecard(
                provider_id, year, tenant_id=tid
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "provider_pdf: scorecard calc failed pid=%s year=%s: %s",
                provider_id, year, exc,
            )
            scorecard = {}

    try:
        hcc_perf = calculate_hcc_performance(provider_id, year, tenant_id=tid)
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "provider_pdf: hcc-performance failed pid=%s: %s", provider_id, exc
        )
        hcc_perf = []

    # Top-5 HCC opportunities sorted by revenue impact (calculate_hcc_performance
    # already sorts desc, but we re-sort defensively in case the service changes).
    top_hcc = sorted(
        hcc_perf,
        key=lambda h: float(h.get("revenue_impact") or 0),
        reverse=True,
    )[:5]

    risk_band, risk_tone = _audit_risk(scorecard)

    full_name = (
        f"{provider.get('first_name','') or ''} "
        f"{provider.get('last_name','') or ''}"
    ).strip() or f"Provider {provider_id}"

    kpis = [
        {
            "label": "Avg RAF",
            "value": _num(scorecard.get("average_raf"), 3),
            "tone": "blue",
        },
        {
            "label": "Capture",
            "value": _pct(scorecard.get("hcc_capture_rate")),
            "tone": "emerald",
        },
        {
            "label": "Recapture",
            "value": _pct(scorecard.get("recapture_rate")),
            "tone": "violet",
        },
        {
            "label": "MEAT",
            "value": _pct(scorecard.get("meat_completeness_avg")),
            "tone": "slate",
        },
    ]

    return {
        "provider": {
            "id": provider_id,
            "full_name": full_name,
            "first_name": provider.get("first_name") or "",
            "last_name": provider.get("last_name") or "",
            "credential": provider.get("credential") or "",
            "specialty": provider.get("specialty") or "—",
            "specialty_category": provider.get("specialty_category") or "",
            "npi": provider.get("npi") or "—",
            "practice_name": provider.get("practice_name") or "",
        },
        "year": year,
        "panel_size": int(scorecard.get("total_patients") or 0),
        "kpis": kpis,
        "revenue_opportunity": _money(scorecard.get("revenue_opportunity")),
        "revenue_opportunity_raw": float(
            scorecard.get("revenue_opportunity") or 0
        ),
        "doc_quality_pct": _pct(scorecard.get("documentation_quality_score")),
        "percentile_rank": _num(scorecard.get("percentile_rank"), 0),
        "suspects_open": int(scorecard.get("suspects_open") or 0),
        "suspects_accepted": int(scorecard.get("suspects_accepted") or 0),
        "top_hcc": [
            {
                "code": str(h.get("hcc_code", "")),
                "label": h.get("hcc_label") or h.get("description") or "",
                "coded": int(h.get("coded_patients") or 0),
                "open": int(h.get("open_suspects") or 0),
                "capture": _pct(h.get("capture_rate")),
                "revenue_impact": _money(h.get("revenue_impact")),
            }
            for h in top_hcc
        ],
        "risk_band": risk_band,
        "risk_tone": risk_tone,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "generated_date": datetime.now(timezone.utc).strftime("%B %d, %Y"),
        "footer_watermark": (
            f"RAF Intelligence — Generated "
            f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')} — Confidential"
        ),
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def render_html(context: dict[str, Any]) -> str:
    """Render the Jinja HTML for the report (separate step keeps tests fast)."""
    tmpl = _env.get_template("template.html")
    return tmpl.render(**context)


def _render_pdf(html: str) -> bytes:
    """Render HTML to PDF using WeasyPrint. Imported lazily."""
    try:
        from weasyprint import CSS, HTML  # type: ignore
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "WeasyPrint is not installed or its native dependencies are missing. "
            "Install weasyprint and system packages libpango, libcairo, libgdk-pixbuf."
        ) from exc

    css_path = _TEMPLATE_DIR / "style.css"
    stylesheets = [CSS(filename=str(css_path))] if css_path.exists() else []
    return HTML(string=html).write_pdf(stylesheets=stylesheets)


def generate_provider_pdf(
    provider_id: int,
    year: int,
    *,
    tenant_id: int | str | None = None,
) -> bytes:
    """Build the single-page provider scorecard PDF.

    Parameters
    ----------
    provider_id:
        Primary key of the provider row.  The router has already done IDOR /
        tenant verification before calling.
    year:
        Measurement year (e.g. 2026).  Maps to ``provider_scorecard_snapshots
        .measurement_year``.
    tenant_id:
        Optional tenant scope; forwarded to the scorecard service for panel /
        HCC performance queries.

    Returns
    -------
    bytes
        Raw PDF bytes (starts with ``%PDF-``).
    """
    logger.info(
        "provider_pdf.build start provider_id=%d year=%d tenant=%s",
        provider_id, year, tenant_id,
    )
    context = _build_context(provider_id, year, tenant_id)
    html = render_html(context)
    pdf_bytes = _render_pdf(html)
    logger.info(
        "provider_pdf.build done provider_id=%d size_bytes=%d",
        provider_id, len(pdf_bytes),
    )
    return pdf_bytes
