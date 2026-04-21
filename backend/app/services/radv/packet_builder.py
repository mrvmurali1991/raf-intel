"""RADV audit packet builder.

Assembles a per-patient, per-payment-year CMS RADV (Risk Adjustment Data
Validation) evidence packet and renders it to a PDF using Jinja2 + WeasyPrint.

Design notes
------------
- Reads from the existing RAF schema only (``raf_patient_hcc``,
  ``raf_meat_evidence``, ``raf_suspect_conditions``, ``normalized_encounters``,
  ``normalized_diagnoses``, ``ai_meat_evidence``, ``patients``,
  ``raf_patient_demographics``).  Does NOT redesign the MEAT data model.
- One PDF covers all HCCs billed for a patient in the payment year, with
  one evidence block per HCC.
- Always applies a diagonal "PRE-SUBMISSION — INTERNAL AUDIT" watermark so
  the document cannot be mistaken for a finalized CMS response.
- WeasyPrint is imported lazily inside ``build_packet`` so environments
  without the native stack can still import this module (the router's
  HTTP layer surfaces a 500 with a clear message rather than crashing at
  import time).

Public API
----------
build_packet(patient_id, payment_year, db=None, *, tenant_id) -> bytes
    Return the rendered PDF bytes.  ``db`` accepts a SQLAlchemy Session for
    call-site symmetry with the rest of the codebase, but packet assembly
    uses the project's raw-SQL ``raf_cursor()`` context manager like every
    other router.  Pass ``None`` to use the ambient pool.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.db import raf_cursor
from app.services.hccinfhir_utils import (
    DEFAULT_MODEL,
    labels_default,
    lookup_hcc,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Template environment
# ---------------------------------------------------------------------------

_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"

_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
    trim_blocks=True,
    lstrip_blocks=True,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _hcc_label(hcc_code: int | str) -> str:
    """Return the human-readable label for an HCC code, falling back to ``HCC n``."""
    return labels_default.get((str(hcc_code), DEFAULT_MODEL)) or f"HCC {hcc_code}"


def _parse_icd_list(raw: Any) -> list[str]:
    """Normalise ``raf_patient_hcc.icd10_codes`` (JSON string or CSV) to a list."""
    if not raw:
        return []
    if isinstance(raw, (list, tuple)):
        return [str(c).strip() for c in raw if c]
    # Try JSON first (seed data stores JSON arrays)
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(c).strip() for c in parsed if c]
    except (TypeError, ValueError):
        pass
    return [c.strip() for c in str(raw).split(",") if c.strip()]


def _float(val: Any) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


def _fmt_date(val: Any) -> str:
    if not val:
        return ""
    return str(val)[:10]


# ---------------------------------------------------------------------------
# Data assembly
# ---------------------------------------------------------------------------


def _fetch_patient(patient_id: int, tenant_id: str) -> dict[str, Any] | None:
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT
                p.id,
                p.first_name,
                p.last_name,
                p.dob,
                p.gender,
                pd.medicare_beneficiary_id,
                pd.insurance_id
            FROM patients p
            LEFT JOIN raf_patient_demographics pd
                   ON pd.patient_id = p.id
                  AND pd.tenant_id  = p.tenant_id
            WHERE p.id        = %s
              AND p.tenant_id = %s
            LIMIT 1
            """,
            (patient_id, tenant_id),
        )
        return cur.fetchone()


def _fetch_billed_hccs(
    patient_id: int, payment_year: int, tenant_id: str
) -> list[dict[str, Any]]:
    """Return all HCC rows billed for this patient/year/tenant.

    A "billed" HCC is any row in ``raf_patient_hcc`` for the patient/year.
    Suspects that were never accepted do NOT get a row in this table — they
    live in ``raf_suspect_conditions``. The packet intentionally excludes
    those to avoid asserting evidence for a condition that was not coded.
    """
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT
                id,
                hcc_code,
                icd10_codes,
                raf_coefficient,
                meat_status,
                source,
                model_version,
                measurement_year,
                created_at
            FROM raf_patient_hcc
            WHERE patient_id       = %s
              AND measurement_year = %s
              AND tenant_id        = %s
              AND COALESCE(is_trumped, 0) = 0
            ORDER BY hcc_code
            """,
            (patient_id, payment_year, tenant_id),
        )
        return list(cur.fetchall() or [])


def _fetch_encounters_for_icds(
    patient_id: int,
    tenant_id: str,
    payment_year: int,
    icd_codes: list[str],
) -> list[dict[str, Any]]:
    if not icd_codes:
        return []
    placeholders = ", ".join(["%s"] * len(icd_codes))
    with raf_cursor() as cur:
        cur.execute(
            f"""
            SELECT DISTINCT
                ne.encounter_id,
                ne.encounter_date,
                ne.encounter_type,
                ne.facility_name,
                ne.provider_name,
                ne.provider_npi
            FROM normalized_encounters ne
            JOIN normalized_diagnoses nd
              ON nd.encounter_id = ne.encounter_id
            WHERE ne.patient_id = %s
              AND ne.tenant_id  = %s
              AND YEAR(ne.encounter_date) = %s
              AND nd.icd10_code IN ({placeholders})
            ORDER BY ne.encounter_date DESC
            """,
            (patient_id, tenant_id, payment_year, *icd_codes),
        )
        return list(cur.fetchall() or [])


def _fetch_meat_evidence(patient_hcc_id: int) -> list[dict[str, Any]]:
    """Return per-encounter MEAT evidence rows for this billed HCC assignment."""
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT
                id,
                encounter_id,
                encounter_date,
                meat_m,
                meat_e,
                meat_a,
                meat_t,
                meat_m_present,
                meat_e_present,
                meat_a_present,
                meat_t_present,
                completeness_score,
                raw_note_excerpt
            FROM raf_meat_evidence
            WHERE patient_hcc_id = %s
            ORDER BY encounter_date DESC
            """,
            (patient_hcc_id,),
        )
        return list(cur.fetchall() or [])


def _fetch_llm_quotes(
    patient_id: int, payment_year: int, hcc_code: int | str
) -> list[dict[str, Any]]:
    """Return LLM-extracted MEAT quotes with note_id + char offsets.

    Tolerates schema drift: any unexpected column / missing table logs and
    returns an empty list so the packet still builds.
    """
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT
                    ame.meat_type,
                    ame.quote,
                    ame.note_id,
                    ame.note_span_start,
                    ame.note_span_end,
                    ame.strength,
                    ame.created_at
                FROM ai_meat_evidence ame
                JOIN ai_hcc_candidates ahc ON ahc.id = ame.candidate_id
                WHERE ahc.patient_id = %s
                  AND YEAR(ahc.created_at) = %s
                  AND CAST(ahc.hcc_code AS CHAR) = %s
                ORDER BY ame.created_at DESC
                LIMIT 50
                """,
                (patient_id, payment_year, str(hcc_code)),
            )
            return list(cur.fetchall() or [])
    except Exception as exc:  # noqa: BLE001 — tolerate schema drift in dev DBs
        logger.debug(
            "radv.packet: ai_meat_evidence lookup skipped for patient_id=%d hcc=%s: %s",
            patient_id,
            hcc_code,
            exc,
        )
        return []


def _fetch_suspect_trail(
    patient_id: int,
    tenant_id: str,
    payment_year: int,
    hcc_code: int | str,
) -> dict[str, Any] | None:
    """Return suspect→accept audit trail for this HCC code if available."""
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT
                    id,
                    status,
                    reviewed_by,
                    updated_at,
                    created_at,
                    confidence_score,
                    evidence_type
                FROM raf_suspect_conditions
                WHERE patient_id       = %s
                  AND tenant_id        = %s
                  AND measurement_year = %s
                  AND CAST(suspect_hcc AS CHAR) = %s
                ORDER BY (status = 'accepted') DESC, updated_at DESC
                LIMIT 1
                """,
                (patient_id, tenant_id, payment_year, str(hcc_code)),
            )
            row = cur.fetchone()
            return dict(row) if row else None
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "radv.packet: suspect trail lookup skipped for patient_id=%d hcc=%s: %s",
            patient_id,
            hcc_code,
            exc,
        )
        return None


# ---------------------------------------------------------------------------
# Context construction
# ---------------------------------------------------------------------------


def _build_hcc_block(
    hcc_row: dict[str, Any],
    patient_id: int,
    payment_year: int,
    tenant_id: str,
) -> dict[str, Any]:
    icd_codes = _parse_icd_list(hcc_row.get("icd10_codes"))
    hcc_code = hcc_row["hcc_code"]
    patient_hcc_id = hcc_row["id"]

    encounters = _fetch_encounters_for_icds(
        patient_id, tenant_id, payment_year, icd_codes
    )

    # Per-ICD hccinfhir enrichment (V24 + V28 mapping where available)
    icd_details: list[dict[str, Any]] = []
    for code in icd_codes:
        try:
            mapping = lookup_hcc(code)
        except Exception as exc:  # noqa: BLE001
            logger.debug("lookup_hcc failed for %s: %s", code, exc)
            mapping = {"maps_to_hcc": False, "hcc_codes": [], "hcc_details": {}}
        icd_details.append(
            {
                "icd10_code": code,
                "hcc_codes": mapping.get("hcc_codes") or [],
                "details": mapping.get("hcc_details") or {},
            }
        )

    meat_rows = _fetch_meat_evidence(patient_hcc_id)

    # Aggregate MEAT letters with best evidence quote + encounter id per letter
    meat_letters: dict[str, dict[str, Any]] = {
        "M": {"letter": "M", "name": "Monitor", "present": False, "quote": None,
               "encounter_id": None, "offset": None},
        "E": {"letter": "E", "name": "Evaluate", "present": False, "quote": None,
               "encounter_id": None, "offset": None},
        "A": {"letter": "A", "name": "Assess", "present": False, "quote": None,
               "encounter_id": None, "offset": None},
        "T": {"letter": "T", "name": "Treat", "present": False, "quote": None,
               "encounter_id": None, "offset": None},
    }
    letter_to_cols = {
        "M": ("meat_m_present", "meat_m"),
        "E": ("meat_e_present", "meat_e"),
        "A": ("meat_a_present", "meat_a"),
        "T": ("meat_t_present", "meat_t"),
    }
    for row in meat_rows:
        for letter, (present_col, text_col) in letter_to_cols.items():
            if row.get(present_col) and not meat_letters[letter]["present"]:
                meat_letters[letter]["present"] = True
                meat_letters[letter]["quote"] = row.get(text_col)
                meat_letters[letter]["encounter_id"] = row.get("encounter_id")

    # LLM-extracted char-offset quotes (provenance)
    llm_quotes = _fetch_llm_quotes(patient_id, payment_year, hcc_code)

    # Attach char-offset to MEAT letters where a matching LLM quote exists
    for q in llm_quotes:
        mtype = str(q.get("meat_type") or "").lower()
        letter_key = {"monitor": "M", "evaluate": "E", "assess": "A", "treat": "T"}.get(mtype)
        if letter_key and meat_letters[letter_key]["offset"] is None:
            meat_letters[letter_key]["offset"] = (
                q.get("note_span_start"),
                q.get("note_span_end"),
            )
            # If the normalized MEAT row had no quote, fall back to the LLM quote.
            if not meat_letters[letter_key]["quote"]:
                meat_letters[letter_key]["quote"] = q.get("quote")
                meat_letters[letter_key]["encounter_id"] = (
                    meat_letters[letter_key]["encounter_id"] or q.get("note_id")
                )

    # Suspect → accept audit trail
    suspect_trail = _fetch_suspect_trail(patient_id, tenant_id, payment_year, hcc_code)

    criteria_met = sum(1 for v in meat_letters.values() if v["present"])
    if criteria_met == 4:
        overall_status = "COMPLETE"
    elif criteria_met > 0:
        overall_status = "PARTIAL"
    else:
        overall_status = "MISSING"

    return {
        "hcc_code": hcc_code,
        "hcc_label": _hcc_label(hcc_code),
        "model_version": hcc_row.get("model_version") or "V28",
        "raf_coefficient": _float(hcc_row.get("raf_coefficient")),
        "source": hcc_row.get("source") or "billed",
        "stored_meat_status": hcc_row.get("meat_status"),
        "icd_codes": icd_codes,
        "icd_details": icd_details,
        "encounters": [
            {
                "encounter_id": e.get("encounter_id"),
                "date": _fmt_date(e.get("encounter_date")),
                "type": e.get("encounter_type"),
                "facility": e.get("facility_name"),
                "provider_name": e.get("provider_name"),
                "provider_npi": e.get("provider_npi"),
            }
            for e in encounters
        ],
        "meat_letters": [meat_letters["M"], meat_letters["E"], meat_letters["A"], meat_letters["T"]],
        "meat_rows": [
            {
                "encounter_id": r.get("encounter_id"),
                "date": _fmt_date(r.get("encounter_date")),
                "completeness": _float(r.get("completeness_score")),
                "raw_excerpt": r.get("raw_note_excerpt"),
            }
            for r in meat_rows
        ],
        "llm_quotes": [
            {
                "meat_type": q.get("meat_type"),
                "quote": q.get("quote"),
                "note_id": q.get("note_id"),
                "span_start": q.get("note_span_start"),
                "span_end": q.get("note_span_end"),
                "strength": _float(q.get("strength")),
            }
            for q in llm_quotes
        ],
        "suspect_trail": (
            {
                "accepted_by": suspect_trail.get("reviewed_by"),
                "accepted_at": _fmt_date(suspect_trail.get("updated_at")),
                "status": suspect_trail.get("status"),
                "confidence": _float(suspect_trail.get("confidence_score")),
                "evidence_type": suspect_trail.get("evidence_type"),
            }
            if suspect_trail
            else None
        ),
        "overall_status": overall_status,
        "criteria_met": criteria_met,
    }


def _build_context(
    patient_id: int, payment_year: int, tenant_id: str
) -> dict[str, Any]:
    patient = _fetch_patient(patient_id, tenant_id)
    billed = _fetch_billed_hccs(patient_id, payment_year, tenant_id)

    hcc_blocks = [
        _build_hcc_block(row, patient_id, payment_year, tenant_id) for row in billed
    ]

    total_raf = round(sum(b["raf_coefficient"] for b in hcc_blocks), 4)

    if patient:
        name = f"{patient.get('first_name') or ''} {patient.get('last_name') or ''}".strip()
        patient_block = {
            "patient_id": patient_id,
            "name": name or f"Patient {patient_id}",
            "dob": _fmt_date(patient.get("dob")),
            "gender": patient.get("gender"),
            "mbi": patient.get("medicare_beneficiary_id"),
            "insurance_id": patient.get("insurance_id"),
        }
    else:
        patient_block = {
            "patient_id": patient_id,
            "name": f"Patient {patient_id}",
            "dob": None,
            "gender": None,
            "mbi": None,
            "insurance_id": None,
        }

    return {
        "patient": patient_block,
        "payment_year": payment_year,
        "tenant_id": tenant_id,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "hcc_blocks": hcc_blocks,
        "total_billed_hccs": len(hcc_blocks),
        "total_raf": total_raf,
        "watermark": "PRE-SUBMISSION \u2014 INTERNAL AUDIT",
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def render_html(context: dict[str, Any]) -> str:
    """Render the Jinja HTML for the packet (separate from the PDF step for tests)."""
    tmpl = _env.get_template("packet.html")
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

    css_path = _TEMPLATE_DIR / "packet.css"
    stylesheets = [CSS(filename=str(css_path))] if css_path.exists() else []
    return HTML(string=html).write_pdf(stylesheets=stylesheets)


def build_packet(
    patient_id: int,
    payment_year: int,
    db: Any = None,
    *,
    tenant_id: str,
) -> bytes:
    """Build the RADV audit packet PDF for a patient/payment_year.

    Parameters
    ----------
    patient_id:
        RAF Intelligence patient id (the callers already IDOR-checked this).
    payment_year:
        CMS payment year (e.g. 2025). Maps to ``raf_patient_hcc.measurement_year``.
    db:
        Accepted for SQLAlchemy-style call-site symmetry; unused — the packet
        reads via the project's ``raf_cursor()`` pool.
    tenant_id:
        Tenant scope; all SELECTs filter on this column.

    Returns
    -------
    bytes
        Raw PDF bytes (starts with ``%PDF-``).
    """
    # Avoid logging patient name to comply with "no PHI in logs" rule.
    logger.info(
        "radv.packet.build start patient_id=%d payment_year=%d tenant=%s",
        patient_id,
        payment_year,
        tenant_id,
    )
    context = _build_context(patient_id, payment_year, tenant_id)
    html = render_html(context)
    pdf_bytes = _render_pdf(html)
    logger.info(
        "radv.packet.build done patient_id=%d hcc_count=%d size_bytes=%d",
        patient_id,
        context["total_billed_hccs"],
        len(pdf_bytes),
    )
    return pdf_bytes
