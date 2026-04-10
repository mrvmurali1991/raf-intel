"""
Audit router — RADV-ready PDF audit packages.

Routes
------
POST /api/audit/generate/{pid}   Generate a PDF audit package for a patient
GET  /api/audit/packages         List previously generated packages
GET  /api/audit/download/{fname} Download a PDF by filename
"""
from __future__ import annotations

import io
import logging
import os
import textwrap
from datetime import date, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from app.db import raf_cursor
from app.services import openemr_connector as emr
from app.services.raf_calculator import get_raf_breakdown, calculate_raf_score
from app.services.suspect_engine import get_suspects_for_patient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/audit", tags=["audit"])

AUDIT_DIR = Path(os.getenv("AUDIT_DIR", "/tmp/raf-audits"))
AUDIT_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class GenerateAuditRequest(BaseModel):
    year: int | None = None
    model_segment: str = "CNA"
    include_suspects: bool = True
    recalculate: bool = False


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/generate/{pid}", summary="Generate RADV audit package PDF")
def generate_audit(
    pid: int,
    body: GenerateAuditRequest = GenerateAuditRequest(),
) -> dict[str, Any]:
    """
    Build a comprehensive RADV-ready PDF audit package for *pid*.

    The PDF contains:
    - Cover page with patient demographics and RAF score
    - RAF score summary (demographic + disease + interaction breakdowns)
    - HCC code table with ICD-10 sources and MEAT status
    - Per-HCC MEAT evidence pages with quoted clinical text
    - Suspect conditions report
    - Provider attestation page
    - Table of contents
    """
    patient = emr.get_patient(pid)
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient {pid} not found")

    calc_year = body.year or date.today().year

    if body.recalculate:
        calculate_raf_score(
            patient_id=pid,
            year=calc_year,
            model_segment=body.model_segment,
        )

    raf_data = get_raf_breakdown(pid, calc_year)
    suspects = get_suspects_for_patient(patient_id=pid) if body.include_suspects else []
    encounters = emr.get_encounters(pid)
    medications = emr.get_medications(pid)
    diagnoses = emr.get_billing_codes(pid)

    try:
        pdf_bytes = _build_audit_pdf(
            patient=patient,
            raf_data=raf_data,
            suspects=suspects,
            encounters=encounters,
            medications=medications,
            diagnoses=diagnoses,
            year=calc_year,
        )
    except Exception as exc:
        logger.exception("PDF generation failed pid=%s", pid)
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {exc}") from exc

    ts = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    filename = f"audit_pid{pid}_{calc_year}_{ts}.pdf"
    filepath = AUDIT_DIR / filename
    filepath.write_bytes(pdf_bytes)

    package_id = _save_package_record(pid, calc_year, str(filepath), len(pdf_bytes))

    return {
        "pid": pid,
        "year": calc_year,
        "package_id": package_id,
        "filename": filename,
        "size_bytes": len(pdf_bytes),
        "download_url": f"/api/audit/download/{filename}",
    }


@router.get("/packages", summary="List generated audit packages")
def list_packages(
    pid: int | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    """Return metadata for previously generated audit packages."""
    if pid is not None:
        sql = """
            SELECT id, patient_id, measurement_year, file_path,
                   status, file_size_bytes, generated_at, created_at
            FROM raf_audit_packages
            WHERE patient_id = %s
            ORDER BY created_at DESC
            LIMIT %s
        """
        params: tuple[Any, ...] = (pid, limit)
    else:
        sql = """
            SELECT id, patient_id, measurement_year, file_path,
                   status, file_size_bytes, generated_at, created_at
            FROM raf_audit_packages
            ORDER BY created_at DESC
            LIMIT %s
        """
        params = (limit,)

    try:
        with raf_cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        packages = [_serialize(r) for r in rows]
    except Exception as exc:
        logger.warning("list_packages DB error: %s", exc)
        packages = []

    return {"count": len(packages), "packages": packages}


@router.get("/download/{filename}", summary="Download an audit PDF by filename")
def download_package(filename: str) -> FileResponse:
    """Stream the PDF for *filename*."""
    # Prevent path traversal
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    filepath = AUDIT_DIR / filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Audit file not found")

    return FileResponse(
        path=str(filepath),
        media_type="application/pdf",
        filename=filename,
    )


# ---------------------------------------------------------------------------
# PDF builder
# ---------------------------------------------------------------------------

# Color palette (brand)
_BLUE = "#1A56DB"
_BLUE_LIGHT = "#EBF5FF"
_RED = "#C81E1E"
_GREEN_DARK = "#03543F"
_GREEN_LIGHT = "#DEF7EC"
_YELLOW_DARK = "#723B13"
_YELLOW_LIGHT = "#FDF6B2"
_RED_LIGHT = "#FDE8E8"
_GRAY_ROW = "#F9FAFB"
_GRAY_BORDER = "#D1D5DB"
_TEXT_DARK = "#111928"
_TEXT_MUTED = "#6B7280"


def _build_audit_pdf(
    patient: dict[str, Any],
    raf_data: dict[str, Any],
    suspects: list[dict[str, Any]],
    encounters: list[dict[str, Any]],
    medications: list[dict[str, Any]],
    diagnoses: list[dict[str, Any]],
    year: int,
) -> bytes:
    """Assemble the full RADV audit PDF and return its bytes."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        HRFlowable,
        NextPageTemplate,
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )
    from reportlab.platypus.flowables import KeepTogether

    # ---- colour objects ----
    C = colors.HexColor
    blue = C(_BLUE)
    blue_light = C(_BLUE_LIGHT)
    gray_row = C(_GRAY_ROW)
    gray_border = C(_GRAY_BORDER)
    green_dark = C(_GREEN_DARK)
    green_light = C(_GREEN_LIGHT)
    yellow_dark = C(_YELLOW_DARK)
    yellow_light = C(_YELLOW_LIGHT)
    red_dark = C(_RED)
    red_light = C(_RED_LIGHT)
    text_dark = C(_TEXT_DARK)
    text_muted = C(_TEXT_MUTED)

    PAGE_W, PAGE_H = letter
    MARGIN = 0.75 * inch
    CONTENT_W = PAGE_W - 2 * MARGIN

    # ---- styles ----
    base = getSampleStyleSheet()

    def ps(name: str, **kw) -> ParagraphStyle:
        parent = kw.pop("parent", base["Normal"])
        return ParagraphStyle(name, parent=parent, **kw)

    S = {
        "cover_title": ps("cover_title", fontSize=26, textColor=blue,
                          fontName="Helvetica-Bold", spaceAfter=6, alignment=TA_CENTER),
        "cover_sub": ps("cover_sub", fontSize=13, textColor=text_muted,
                        fontName="Helvetica", alignment=TA_CENTER, spaceAfter=4),
        "cover_value": ps("cover_value", fontSize=14, textColor=text_dark,
                          fontName="Helvetica-Bold", alignment=TA_CENTER, spaceAfter=2),
        "section": ps("section", fontSize=13, textColor=blue,
                      fontName="Helvetica-Bold", spaceBefore=14, spaceAfter=6),
        "subsection": ps("subsection", fontSize=10, textColor=text_dark,
                         fontName="Helvetica-Bold", spaceBefore=8, spaceAfter=4),
        "body": ps("body", fontSize=9, textColor=text_dark,
                   fontName="Helvetica", spaceAfter=3, leading=13),
        "body_bold": ps("body_bold", fontSize=9, textColor=text_dark,
                        fontName="Helvetica-Bold", spaceAfter=3),
        "small": ps("small", fontSize=7.5, textColor=text_muted,
                    fontName="Helvetica", leading=11),
        "small_bold": ps("small_bold", fontSize=7.5, textColor=text_dark,
                         fontName="Helvetica-Bold", leading=11),
        "evidence": ps("evidence", fontSize=8, textColor=text_dark,
                       fontName="Courier", leading=11, leftIndent=6,
                       borderPad=3, backColor=C("#F3F4F6")),
        "toc_h1": ps("toc_h1", fontSize=10, textColor=text_dark,
                     fontName="Helvetica-Bold", spaceAfter=2),
        "toc_entry": ps("toc_entry", fontSize=9, textColor=text_dark,
                        fontName="Helvetica", spaceAfter=2, leftIndent=10),
        "footer": ps("footer", fontSize=7.5, textColor=text_muted,
                     fontName="Helvetica", alignment=TA_CENTER),
        "attest_label": ps("attest_label", fontSize=9, textColor=text_muted,
                           fontName="Helvetica"),
        "attest_value": ps("attest_value", fontSize=11, textColor=text_dark,
                           fontName="Helvetica-Bold"),
        "raf_big": ps("raf_big", fontSize=32, textColor=blue,
                      fontName="Helvetica-Bold", alignment=TA_CENTER, spaceAfter=0),
        "raf_label": ps("raf_label", fontSize=9, textColor=text_muted,
                        fontName="Helvetica", alignment=TA_CENTER),
        "header_brand": ps("header_brand", fontSize=8, textColor=text_muted,
                           fontName="Helvetica", alignment=TA_RIGHT),
    }

    # ---- derived data helpers ----
    def _fmt_score(v: Any, decimals: int = 4) -> str:
        try:
            return f"{float(v):.{decimals}f}"
        except (TypeError, ValueError):
            return str(v) if v is not None else "N/A"

    def _trunc(s: str | None, n: int = 60) -> str:
        s = s or ""
        return s[:n] + "…" if len(s) > n else s

    def _wrap(s: str | None, width: int = 70) -> str:
        s = s or ""
        return "\n".join(textwrap.wrap(s, width)) or s

    # ---- patient info ----
    full_name = f"{patient.get('fname', '')} {patient.get('lname', '')}".strip() or "Unknown"
    dob = str(patient.get("DOB") or patient.get("dob") or "N/A")[:10]
    sex = patient.get("sex", "N/A")
    provider_id = str(patient.get("providerID") or patient.get("provider_id") or "N/A")
    gen_ts = datetime.utcnow().strftime("%B %d, %Y at %H:%M UTC")

    # ---- RAF data ----
    raf_score = raf_data.get("raf_score") or raf_data.get("total_raf") or 0.0
    demo_score = raf_data.get("demographic_score", 0.0)
    disease_score = raf_data.get("disease_score", 0.0)
    interaction_score = raf_data.get("interaction_score", 0.0)
    model_segment = raf_data.get("model_segment", "CNA")
    hcc_detail: list[dict[str, Any]] = raf_data.get("hcc_detail") or raf_data.get("hcc_list") or []

    # ---- page-number canvas callback ----
    _page_info: dict[str, int] = {"n": 0}

    def _on_page(canvas, doc):  # noqa: ANN001
        _page_info["n"] += 1
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(text_muted)
        # left footer
        canvas.drawString(MARGIN, 0.45 * inch,
                          "RAF Intelligence — Confidential RADV Audit Package")
        # right footer
        canvas.drawRightString(PAGE_W - MARGIN, 0.45 * inch,
                               f"Page {doc.page}")
        # top rule (skip cover page 1)
        if doc.page > 1:
            canvas.setStrokeColor(gray_border)
            canvas.setLineWidth(0.5)
            canvas.line(MARGIN, PAGE_H - 0.55 * inch,
                        PAGE_W - MARGIN, PAGE_H - 0.55 * inch)
            canvas.setFont("Helvetica", 7.5)
            canvas.setFillColor(text_muted)
            canvas.drawRightString(PAGE_W - MARGIN, PAGE_H - 0.45 * inch,
                                   f"RAF Intelligence — Audit Package  |  PID {patient.get('pid', '')}  |  {year}")
        canvas.restoreState()

    # ---- table style helpers ----
    def _header_ts(header_color=None) -> TableStyle:
        hc = header_color or blue
        return TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), hc),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 8),
            ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 1), (-1, -1), 8),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, gray_row]),
            ("GRID", (0, 0), (-1, -1), 0.4, gray_border),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ])

    def _kv_ts() -> TableStyle:
        return TableStyle([
            ("BACKGROUND", (0, 0), (0, -1), blue_light),
            ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
            ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("GRID", (0, 0), (-1, -1), 0.4, gray_border),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ])

    def _meat_color(status: str) -> tuple[Any, Any]:
        """Return (background_color, text_color) for a MEAT status string."""
        sl = (status or "").lower()
        if sl == "complete":
            return green_light, green_dark
        if sl == "partial":
            return yellow_light, yellow_dark
        return red_light, red_dark

    def _meat_score_bar(score: int) -> str:
        filled = "■" * score
        empty = "□" * (4 - score)
        return f"{filled}{empty}  ({score}/4)"

    def _hr() -> HRFlowable:
        return HRFlowable(width="100%", thickness=0.5, color=gray_border, spaceAfter=6)

    # ====================================================================
    # BUILD STORY
    # ====================================================================
    story: list[Any] = []

    # ----------------------------------------------------------------
    # 1. COVER PAGE
    # ----------------------------------------------------------------
    story.append(Spacer(1, 0.6 * inch))

    # Brand banner
    banner_data = [["RAF Intelligence — RADV Audit Package"]]
    banner = Table(banner_data, colWidths=[CONTENT_W])
    banner.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), blue),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.white),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 18),
        ("ALIGNMENT", (0, 0), (-1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 14),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 14),
    ]))
    story.append(banner)
    story.append(Spacer(1, 0.35 * inch))

    # RAF score hero
    story.append(Paragraph(_fmt_score(raf_score, 4), S["raf_big"]))
    story.append(Paragraph("Final RAF Score", S["raf_label"]))
    story.append(Spacer(1, 0.25 * inch))
    story.append(_hr())
    story.append(Spacer(1, 0.2 * inch))

    # Cover demographics table
    cover_kv = [
        ["Patient Name", full_name],
        ["Patient ID (PID)", str(patient.get("pid", ""))],
        ["Date of Birth", dob],
        ["Sex", sex],
        ["Provider ID", provider_id],
        ["Measurement Year", str(year)],
        ["Model Segment", model_segment],
        ["Document Generated", gen_ts],
    ]
    cover_t = Table(cover_kv, colWidths=[2.2 * inch, CONTENT_W - 2.2 * inch])
    cover_t.setStyle(_kv_ts())
    story.append(cover_t)
    story.append(Spacer(1, 0.35 * inch))

    # Confidentiality notice
    notice_data = [[
        Paragraph(
            "CONFIDENTIAL — This document contains protected health information (PHI) "
            "prepared for RADV audit defense purposes only.  Do not distribute without "
            "authorization.  Generated by RAF Intelligence.",
            S["small"],
        )
    ]]
    notice_t = Table(notice_data, colWidths=[CONTENT_W])
    notice_t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), C("#FEF3C7")),
        ("BOX", (0, 0), (-1, -1), 0.8, C("#F59E0B")),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
    ]))
    story.append(notice_t)

    story.append(PageBreak())

    # ----------------------------------------------------------------
    # 2. TABLE OF CONTENTS
    # ----------------------------------------------------------------
    story.append(Paragraph("Table of Contents", S["section"]))
    story.append(_hr())

    toc_items = [
        ("1", "RAF Score Summary"),
        ("2", "HCC Code Table"),
        ("3", "Per-HCC MEAT Evidence"),
        ("4", "Suspect Conditions Report"),
        ("5", "Active Diagnoses & Encounter Summary"),
        ("6", "Provider Attestation"),
    ]
    toc_rows = [[Paragraph(f"{n}.", S["toc_entry"]),
                 Paragraph(title, S["toc_entry"])]
                for n, title in toc_items]
    toc_t = Table(toc_rows, colWidths=[0.35 * inch, CONTENT_W - 0.35 * inch])
    toc_t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, gray_row]),
    ]))
    story.append(toc_t)
    story.append(PageBreak())

    # ----------------------------------------------------------------
    # 3. RAF SCORE SUMMARY
    # ----------------------------------------------------------------
    story.append(Paragraph("Section 1 — RAF Score Summary", S["section"]))
    story.append(_hr())

    raf_summary_rows = [
        ["Component", "Score", "Notes"],
        ["Demographic Score", _fmt_score(demo_score),
         "Age/sex risk adjustment from CMS model"],
        ["Disease Score", _fmt_score(disease_score),
         "Sum of all HCC coefficients"],
        ["Interaction Score", _fmt_score(interaction_score),
         "Disease interaction terms"],
        ["FINAL RAF SCORE", _fmt_score(raf_score, 4), f"Model: {model_segment}"],
    ]
    raf_t = Table(raf_summary_rows, colWidths=[2.0 * inch, 1.2 * inch, CONTENT_W - 3.2 * inch])
    raf_ts = _header_ts()
    # Bold + larger final row
    raf_ts.add("FONTNAME", (0, 4), (-1, 4), "Helvetica-Bold")
    raf_ts.add("FONTSIZE", (0, 4), (-1, 4), 10)
    raf_ts.add("BACKGROUND", (0, 4), (-1, 4), blue_light)
    raf_ts.add("TEXTCOLOR", (0, 4), (0, 4), blue)
    story.append(raf_t)
    raf_t.setStyle(raf_ts)
    story.append(Spacer(1, 0.15 * inch))

    # HCC count box
    hcc_count = len(hcc_detail)
    stats_rows = [[
        Paragraph(f"<b>{hcc_count}</b><br/>HCCs Captured", S["body"]),
        Paragraph(f"<b>{_fmt_score(raf_score, 4)}</b><br/>Total RAF", S["body"]),
        Paragraph(f"<b>{model_segment}</b><br/>Model Segment", S["body"]),
        Paragraph(f"<b>{year}</b><br/>Measurement Year", S["body"]),
    ]]
    stats_t = Table(stats_rows, colWidths=[CONTENT_W / 4] * 4)
    stats_t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), blue_light),
        ("BOX", (0, 0), (-1, -1), 0.8, blue),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, gray_border),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(stats_t)
    story.append(PageBreak())

    # ----------------------------------------------------------------
    # 4. HCC CODE TABLE
    # ----------------------------------------------------------------
    story.append(Paragraph("Section 2 — HCC Code Table", S["section"]))
    story.append(_hr())
    story.append(Paragraph(
        "Each HCC is listed with its supporting ICD-10 codes, coefficient weight, "
        "and MEAT documentation status.  Green = Complete, Yellow = Partial, Red = Missing.",
        S["body"],
    ))
    story.append(Spacer(1, 0.1 * inch))

    if hcc_detail:
        hcc_table_rows = [["HCC #", "Description", "ICD-10 Codes", "Coeff.", "MEAT Status"]]
        for h in hcc_detail:
            hcc_num = str(h.get("hcc_number") or h.get("hcc") or "")
            hcc_desc = _trunc(h.get("hcc_description") or h.get("description") or "", 55)
            icd_list = h.get("icd10_codes") or h.get("icd_codes") or []
            if isinstance(icd_list, str):
                icd_list = [icd_list]
            icd_str = ", ".join(icd_list) if icd_list else "—"
            coeff = _fmt_score(h.get("coefficient") or h.get("coeff") or 0.0, 4)
            meat_status = h.get("meat_status") or "missing"
            bg, fg = _meat_color(meat_status)
            status_cell = Paragraph(
                f"<b>{meat_status.upper()}</b>", S["small_bold"]
            )
            hcc_table_rows.append([
                Paragraph(f"<b>HCC {hcc_num}</b>", S["small_bold"]),
                Paragraph(hcc_desc, S["small"]),
                Paragraph(icd_str, S["small"]),
                Paragraph(coeff, S["small"]),
                status_cell,
            ])

        hcc_t = Table(
            hcc_table_rows,
            colWidths=[0.7 * inch, 2.8 * inch, 1.4 * inch, 0.6 * inch, 1.0 * inch],
        )
        hcc_ts = _header_ts()
        # Color-code MEAT status column per row
        for row_idx, h in enumerate(hcc_detail, start=1):
            meat_status = h.get("meat_status") or "missing"
            bg, fg = _meat_color(meat_status)
            hcc_ts.add("BACKGROUND", (4, row_idx), (4, row_idx), bg)
            hcc_ts.add("TEXTCOLOR", (4, row_idx), (4, row_idx), fg)
        hcc_t.setStyle(hcc_ts)
        story.append(hcc_t)
    else:
        story.append(Paragraph("No HCC detail available for this patient and year.", S["body"]))

    story.append(PageBreak())

    # ----------------------------------------------------------------
    # 5. PER-HCC MEAT EVIDENCE PAGES
    # ----------------------------------------------------------------
    story.append(Paragraph("Section 3 — Per-HCC MEAT Evidence", S["section"]))
    story.append(_hr())
    story.append(Paragraph(
        "MEAT criteria: Monitoring, Evaluation, Assessment, Treatment.  "
        "Each category requires direct clinical evidence from encounter notes "
        "within the measurement year to satisfy RADV documentation requirements.",
        S["body"],
    ))

    if hcc_detail:
        for idx, h in enumerate(hcc_detail, start=1):
            hcc_num = str(h.get("hcc_number") or h.get("hcc") or "")
            hcc_desc = h.get("hcc_description") or h.get("description") or ""
            icd_list = h.get("icd10_codes") or h.get("icd_codes") or []
            if isinstance(icd_list, str):
                icd_list = [icd_list]
            coeff = _fmt_score(h.get("coefficient") or h.get("coeff") or 0.0, 4)
            meat_status = h.get("meat_status") or "missing"
            meat_score_val = int(h.get("meat_score") or 0)

            bg, fg = _meat_color(meat_status)

            # HCC header block
            hcc_header_data = [[
                Paragraph(f"HCC {hcc_num}  |  {_trunc(hcc_desc, 65)}", S["section"]),
                Paragraph(f"Coefficient: {coeff}", S["body"]),
            ]]
            hcc_header_t = Table(hcc_header_data, colWidths=[CONTENT_W * 0.75, CONTENT_W * 0.25])
            hcc_header_t.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), blue_light),
                ("BOX", (0, 0), (-1, -1), 0.8, blue),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]))

            # MEAT score + status badge
            badge_data = [[
                Paragraph(
                    f"MEAT Score: {_meat_score_bar(meat_score_val)}",
                    S["body_bold"],
                ),
                Paragraph(
                    f"Status: <b>{meat_status.upper()}</b>",
                    S["body_bold"],
                ),
            ]]
            badge_t = Table(badge_data, colWidths=[CONTENT_W * 0.6, CONTENT_W * 0.4])
            badge_t.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), bg),
                ("TEXTCOLOR", (0, 0), (-1, -1), fg),
                ("BOX", (0, 0), (-1, -1), 0.6, fg),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ]))

            # ICD-10 sources
            icd_rows = [["ICD-10 Code", "Description", "Encounter Date", "Encounter ID"]]
            icd_evidence: list[dict[str, Any]] = h.get("icd_evidence") or []
            if icd_evidence:
                for ie in icd_evidence:
                    icd_rows.append([
                        ie.get("code", ""),
                        _trunc(ie.get("description", ""), 45),
                        str(ie.get("encounter_date", ""))[:10],
                        str(ie.get("encounter_id", "")),
                    ])
            else:
                # Fall back to the flat icd list without encounter detail
                for code in icd_list:
                    icd_rows.append([code, "—", "—", "—"])

            icd_t = Table(
                icd_rows,
                colWidths=[0.9 * inch, 2.9 * inch, 1.1 * inch, 1.1 * inch],
            )
            icd_t.setStyle(_header_ts())

            # MEAT categories
            meat_categories = [
                ("monitoring", "Monitoring",
                 "Evidence that the condition is being tracked / watched over time."),
                ("evaluation", "Evaluation",
                 "Clinical assessment, test ordering, or diagnostic workup."),
                ("assessment", "Assessment",
                 "Clinician's stated diagnosis or impression in the note."),
                ("treatment", "Treatment",
                 "Active management: medications, procedures, referrals, orders."),
            ]

            meat_blocks: list[Any] = []
            for key, label, hint in meat_categories:
                evidence_list: list[dict[str, Any]] = h.get(f"{key}_evidence") or []
                evidence_text: str = h.get(f"{key}_text") or ""
                met = bool(evidence_list or evidence_text)
                status_label = "MET" if met else "NOT MET"
                s_bg, s_fg = _meat_color("complete" if met else "missing")

                cat_header_data = [[
                    Paragraph(f"<b>{label}</b>", S["body_bold"]),
                    Paragraph(hint, S["small"]),
                    Paragraph(f"<b>{status_label}</b>", S["small_bold"]),
                ]]
                cat_t = Table(
                    cat_header_data,
                    colWidths=[0.85 * inch, CONTENT_W - 1.85 * inch, 0.7 * inch],
                )
                cat_t.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, -1), s_bg),
                    ("TEXTCOLOR", (0, 0), (-1, -1), s_fg),
                    ("BOX", (0, 0), (-1, -1), 0.4, s_fg),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ]))
                meat_blocks.append(cat_t)

                # Evidence quote rows
                if evidence_list:
                    for ev in evidence_list[:4]:
                        enc_date = str(ev.get("encounter_date") or ev.get("date") or "")[:10]
                        provider = ev.get("provider") or ev.get("provider_name") or ""
                        quote = ev.get("text") or ev.get("quote") or ev.get("note_text") or ""
                        enc_id = str(ev.get("encounter_id") or "")

                        ev_meta = (
                            f"Encounter {enc_id}  |  {enc_date}  |  {provider}"
                            if enc_id else f"{enc_date}  |  {provider}"
                        )
                        meat_blocks.append(
                            Paragraph(ev_meta, S["small"])
                        )
                        if quote:
                            wrapped_quote = _wrap(quote, 100)
                            meat_blocks.append(
                                Paragraph(f'"{wrapped_quote}"', S["evidence"])
                            )
                        meat_blocks.append(Spacer(1, 2))
                elif evidence_text:
                    meat_blocks.append(
                        Paragraph(f'"{_wrap(evidence_text, 100)}"', S["evidence"])
                    )
                else:
                    meat_blocks.append(
                        Paragraph("No evidence found for this category.", S["small"])
                    )
                meat_blocks.append(Spacer(1, 4))

            block = KeepTogether([
                Spacer(1, 0.15 * inch),
                hcc_header_t,
                Spacer(1, 4),
                badge_t,
                Spacer(1, 6),
                Paragraph("ICD-10 Source Codes", S["subsection"]),
                icd_t,
                Spacer(1, 6),
                Paragraph("MEAT Documentation Evidence", S["subsection"]),
            ] + meat_blocks)
            story.append(block)

            if idx < len(hcc_detail):
                story.append(_hr())
    else:
        story.append(Paragraph("No HCC detail available for MEAT analysis.", S["body"]))

    story.append(PageBreak())

    # ----------------------------------------------------------------
    # 6. SUSPECT CONDITIONS REPORT
    # ----------------------------------------------------------------
    story.append(Paragraph("Section 4 — Suspect Conditions Report", S["section"]))
    story.append(_hr())
    story.append(Paragraph(
        "The following conditions were identified as potentially undocumented based on "
        "active medications, laboratory results, or prior-year HCC capture history.  "
        "These represent opportunities for gap closure in the current measurement year.",
        S["body"],
    ))
    story.append(Spacer(1, 0.1 * inch))

    if suspects:
        susp_rows = [["Trigger Type", "Trigger Value", "Suspected Condition",
                      "Suggested ICD-10", "Confidence", "Priority"]]
        for s in suspects[:60]:
            conf = s.get("confidence") or s.get("confidence_score") or 0.0
            try:
                conf_str = f"{float(conf):.0%}"
            except (TypeError, ValueError):
                conf_str = str(conf)
            priority = s.get("priority") or ("HIGH" if float(conf or 0) >= 0.8 else
                                              "MEDIUM" if float(conf or 0) >= 0.5 else "LOW")
            susp_rows.append([
                s.get("trigger_type") or "",
                _trunc(s.get("trigger_value") or "", 35),
                _trunc(s.get("suspected_condition") or "", 40),
                s.get("suggested_icd10") or s.get("icd10") or "—",
                conf_str,
                priority,
            ])

        susp_t = Table(
            susp_rows,
            colWidths=[0.85 * inch, 1.5 * inch, 2.0 * inch, 0.85 * inch, 0.6 * inch, 0.6 * inch],
        )
        susp_ts = _header_ts(header_color=C(_RED))
        # Color priority column
        for row_idx, s in enumerate(suspects[:60], start=1):
            conf = float(s.get("confidence") or s.get("confidence_score") or 0.0)
            p_bg, p_fg = (_GREEN_LIGHT, _GREEN_DARK) if conf >= 0.8 else (
                (_YELLOW_LIGHT, _YELLOW_DARK) if conf >= 0.5 else (_RED_LIGHT, _RED))
            susp_ts.add("BACKGROUND", (5, row_idx), (5, row_idx), C(p_bg))
            susp_ts.add("TEXTCOLOR", (5, row_idx), (5, row_idx), C(p_fg))
            susp_ts.add("FONTNAME", (5, row_idx), (5, row_idx), "Helvetica-Bold")
        susp_t.setStyle(susp_ts)
        story.append(susp_t)
        story.append(Spacer(1, 0.1 * inch))
        story.append(Paragraph(
            f"Total open suspects: {len(suspects)}  "
            f"(showing first 60).  Review with treating provider before next encounter.",
            S["small"],
        ))
    else:
        story.append(Paragraph("No open suspect conditions identified for this patient.", S["body"]))

    story.append(PageBreak())

    # ----------------------------------------------------------------
    # 7. ACTIVE DIAGNOSES & ENCOUNTER SUMMARY
    # ----------------------------------------------------------------
    story.append(Paragraph("Section 5 — Active Diagnoses & Encounter Summary", S["section"]))
    story.append(_hr())

    # Active diagnoses
    story.append(Paragraph("Active ICD-10 Diagnoses", S["subsection"]))
    if diagnoses:
        dx_rows = [["ICD-10 Code", "Description", "Encounter Date"]]
        seen: set[str] = set()
        for d in diagnoses:
            code = d.get("code") or d.get("diagnosis_code") or ""
            if code in seen:
                continue
            seen.add(code)
            dx_rows.append([
                code,
                _trunc(d.get("description") or d.get("code_text") or "", 60),
                str(d.get("date") or d.get("encounter_date") or "")[:10],
            ])
            if len(dx_rows) > 61:  # 60 data + header
                break
        dx_t = Table(dx_rows, colWidths=[0.9 * inch, 4.2 * inch, 1.0 * inch])
        dx_t.setStyle(_header_ts())
        story.append(dx_t)
    else:
        story.append(Paragraph("No active diagnoses on record.", S["body"]))

    story.append(Spacer(1, 0.2 * inch))

    # Encounter summary
    story.append(Paragraph("Encounter History", S["subsection"]))
    if encounters:
        enc_rows = [["Enc. ID", "Date", "Reason / Chief Complaint", "Provider", "Facility"]]
        for enc in encounters[:40]:
            enc_rows.append([
                str(enc.get("encounter_id") or enc.get("id") or ""),
                str(enc.get("date") or enc.get("encounter_date") or "")[:10],
                _trunc(enc.get("reason") or enc.get("reason_description") or "", 40),
                (f"{enc.get('provider_fname', '')} {enc.get('provider_lname', '')}").strip() or "—",
                _trunc(enc.get("facility") or enc.get("facility_name") or "", 25),
            ])
        enc_t = Table(
            enc_rows,
            colWidths=[0.6 * inch, 0.85 * inch, 2.6 * inch, 1.4 * inch, 1.1 * inch],
        )
        enc_t.setStyle(_header_ts())
        story.append(enc_t)
    else:
        story.append(Paragraph("No encounters on record.", S["body"]))

    # Medications
    if medications:
        story.append(Spacer(1, 0.2 * inch))
        story.append(Paragraph("Active Medications", S["subsection"]))
        med_rows = [["Medication", "Dosage", "Frequency", "Start Date"]]
        for m in medications[:30]:
            med_rows.append([
                _trunc(m.get("drug") or m.get("medication_name") or m.get("name") or "", 45),
                m.get("dosage") or m.get("dose") or "—",
                m.get("frequency") or m.get("schedule") or "—",
                str(m.get("start_date") or m.get("dateAdded") or "")[:10],
            ])
        med_t = Table(
            med_rows,
            colWidths=[2.8 * inch, 1.0 * inch, 1.2 * inch, 1.1 * inch],
        )
        med_t.setStyle(_header_ts())
        story.append(med_t)

    story.append(PageBreak())

    # ----------------------------------------------------------------
    # 8. PROVIDER ATTESTATION
    # ----------------------------------------------------------------
    story.append(Paragraph("Section 6 — Provider Attestation", S["section"]))
    story.append(_hr())
    story.append(Paragraph(
        "I, the undersigned treating provider, attest that the diagnoses documented in this "
        "audit package are accurate to the best of my knowledge, were evaluated and/or treated "
        "during the measurement year, and meet CMS RADV documentation requirements.  All "
        "diagnoses are supported by medical record evidence contained herein.",
        S["body"],
    ))
    story.append(Spacer(1, 0.3 * inch))

    attest_rows = [
        ["Patient Name:", full_name, "PID:", str(patient.get("pid", ""))],
        ["Measurement Year:", str(year), "Model Segment:", model_segment],
        ["Final RAF Score:", _fmt_score(raf_score, 4), "HCC Count:", str(hcc_count)],
    ]
    attest_t = Table(
        attest_rows,
        colWidths=[1.5 * inch, 2.0 * inch, 1.2 * inch, 1.4 * inch],
    )
    attest_t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BACKGROUND", (0, 0), (0, -1), blue_light),
        ("BACKGROUND", (2, 0), (2, -1), blue_light),
        ("GRID", (0, 0), (-1, -1), 0.4, gray_border),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(attest_t)
    story.append(Spacer(1, 0.5 * inch))

    # Signature lines
    sig_rows = [
        ["Treating Provider Signature:", "_" * 42, "Date:", "_" * 18],
        ["Provider Name (Print):", "_" * 42, "NPI:", "_" * 18],
        ["Practice / Organization:", "_" * 42, "Phone:", "_" * 18],
    ]
    sig_t = Table(
        sig_rows,
        colWidths=[1.6 * inch, 2.8 * inch, 0.5 * inch, 1.2 * inch],
    )
    sig_t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(sig_t)
    story.append(Spacer(1, 0.4 * inch))
    story.append(_hr())
    story.append(Paragraph(
        f"Audit package generated by RAF Intelligence on {gen_ts}.  "
        "This document is intended solely for RADV audit defense and quality improvement.  "
        "It does not constitute medical advice or legal counsel.",
        S["footer"],
    ))

    # ----------------------------------------------------------------
    # BUILD
    # ----------------------------------------------------------------
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=MARGIN,
        leftMargin=MARGIN,
        topMargin=0.8 * inch,
        bottomMargin=0.7 * inch,
        title=f"RAF Audit Package — PID {patient.get('pid', '')} — {year}",
        author="RAF Intelligence",
        subject="RADV Audit Package",
    )
    doc.build(story, onFirstPage=_on_page, onLaterPages=_on_page)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _save_package_record(pid: int, year: int, filepath: str, size: int) -> int | None:
    sql = """
        INSERT INTO raf_audit_packages
            (patient_id, measurement_year, file_path, status, file_size_bytes, generated_at)
        VALUES (%s, %s, %s, 'completed', %s, NOW())
        RETURNING id
    """
    try:
        with raf_cursor() as cur:
            cur.execute(sql, (pid, year, filepath, size))
            row = cur.fetchone()
            return row["id"] if row else None
    except Exception as exc:
        logger.warning("Failed to save audit package record: %s", exc)
        return None


def _serialize(row: dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        return {}
    result: dict[str, Any] = {}
    for k, v in row.items():
        result[k] = v.isoformat() if hasattr(v, "isoformat") else v
    return result
