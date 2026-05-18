"""HCC-to-lab evidence mapping for the MD pre-visit huddle.

When a physician looks at a suspected HCC, they need to see the supporting
labs INLINE (not "go check the chart"). This module:

  1. Maps each HCC code to the LOINC labs that clinically support it.
  2. Pulls the patient's most recent lab values for those LOINCs.
  3. Marks each as supporting / borderline / contradictory.
  4. Computes the per-HCC annual revenue impact for the measurement year.

Output is a list of `{label, value, units, date, status, supports}` dicts
ready for direct render in the huddle card.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

from app.db import openemr_cursor, raf_cursor
from app.services.raf.revenue_constants import revenue_per_raf_point

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# HCC → LOINC mapping
# ---------------------------------------------------------------------------
# Codes are the most-common LOINC codes that, when out of range, support the
# corresponding HCC. Each entry: (loinc_code, friendly_label, support_test).
# `support_test` is a callable(value: float) -> "support"/"borderline"/"contradict"

def _a1c_test(v: float) -> str:
    if v >= 8.0:
        return "support"  # uncontrolled — supports E11.65 / HCC 18
    if v >= 7.0:
        return "borderline"
    return "contradict"  # controlled — does NOT support uncontrolled-diabetes HCC


def _egfr_test_ckd_stage4(v: float) -> str:
    # eGFR < 30 supports CKD stage 4 (HCC 137)
    if v < 30:
        return "support"
    if v < 45:
        return "borderline"
    return "contradict"


def _egfr_test_ckd_stage5(v: float) -> str:
    if v < 15:
        return "support"
    if v < 25:
        return "borderline"
    return "contradict"


def _creatinine_test(v: float) -> str:
    # Generic "elevated creatinine" — supports CKD HCCs broadly
    if v > 2.0:
        return "support"
    if v > 1.3:
        return "borderline"
    return "contradict"


def _bnp_test(v: float) -> str:
    # NT-proBNP / BNP supports CHF (HCC 85)
    if v > 400:
        return "support"
    if v > 100:
        return "borderline"
    return "contradict"


def _ldl_test(v: float) -> str:
    # Elevated LDL supports lipid disorder (some hierarchy implications)
    if v > 160:
        return "support"
    if v > 130:
        return "borderline"
    return "contradict"


def _troponin_test(v: float) -> str:
    # Elevated troponin supports MI history (HCC 86)
    if v > 0.04:
        return "support"
    return "contradict"


# HCC code -> list of (loinc, label, test_fn)
HCC_LAB_RULES: dict[str, list[tuple[str, str, Any]]] = {
    # Diabetes with complications
    "17": [
        ("4548-4", "Hemoglobin A1c", _a1c_test),
        ("17856-6", "Hemoglobin A1c (alt LOINC)", _a1c_test),
    ],
    "18": [
        ("4548-4", "Hemoglobin A1c", _a1c_test),
        ("17856-6", "Hemoglobin A1c (alt LOINC)", _a1c_test),
        ("2160-0", "Creatinine, serum", _creatinine_test),
    ],
    "19": [
        ("4548-4", "Hemoglobin A1c", _a1c_test),
    ],
    # CKD stages
    "136": [  # CKD stage 3
        ("33914-3", "eGFR (MDRD)", _egfr_test_ckd_stage4),  # borderline for st4
        ("2160-0", "Creatinine, serum", _creatinine_test),
    ],
    "137": [  # CKD stage 4
        ("33914-3", "eGFR (MDRD)", _egfr_test_ckd_stage4),
        ("2160-0", "Creatinine, serum", _creatinine_test),
    ],
    "138": [  # CKD stage 5 / ESRD
        ("33914-3", "eGFR (MDRD)", _egfr_test_ckd_stage5),
        ("2160-0", "Creatinine, serum", _creatinine_test),
    ],
    # Heart failure
    "85": [
        ("33762-6", "NT-proBNP", _bnp_test),
        ("30934-4", "BNP", _bnp_test),
    ],
    # Specified heart arrhythmias — no single supporting lab
    # Acute MI
    "86": [
        ("10839-9", "Troponin I", _troponin_test),
        ("6598-7", "Troponin T", _troponin_test),
    ],
    # Vascular disease
    "108": [
        ("13457-7", "LDL cholesterol (calc)", _ldl_test),
    ],
}


# ---------------------------------------------------------------------------
# Coefficient lookup — for the per-HCC dollar amount
# ---------------------------------------------------------------------------

def _hcc_coefficient(hcc_code: str, model_year: int) -> float:
    """Return the HCC's V28 RAF coefficient for the model year.

    Falls back to a small default (0.10) when the table doesn't carry it —
    we'd rather show a conservative dollar than fail.
    """
    try:
        with raf_cursor() as cur:
            # The CMS coefficient is segment-dependent — use CNA (community
            # non-dual aged) as the default since most MA enrollees fall in
            # that bucket. Real per-patient lookups would resolve segment.
            cur.execute(
                """SELECT coefficient FROM hcc_raf_coefficients
                   WHERE hcc_code=%s AND model_year=%s
                     AND model_segment='CNA'
                   ORDER BY id DESC
                   LIMIT 1""",
                (str(hcc_code), int(model_year)),
            )
            row = cur.fetchone()
            if not row:
                # Fall back to any segment for the year
                cur.execute(
                    """SELECT coefficient FROM hcc_raf_coefficients
                       WHERE hcc_code=%s AND model_year<=%s
                       ORDER BY model_year DESC, id DESC LIMIT 1""",
                    (str(hcc_code), int(model_year)),
                )
                row = cur.fetchone()
            if row:
                v = row["coefficient"] if isinstance(row, dict) else row[0]
                return float(v) if v is not None else 0.10
    except Exception as exc:
        logger.warning("hcc_coefficient lookup failed for %s/%s: %s",
                       hcc_code, model_year, exc)
    return 0.10  # conservative default


def estimated_annual_revenue(hcc_code: str, year: int | None = None) -> dict[str, Any]:
    """Return `{coefficient, revenue_per_raf_point, annual_revenue_dollars}`."""
    yr = year or date.today().year
    coef = _hcc_coefficient(hcc_code, yr)
    rate = revenue_per_raf_point(yr)
    return {
        "hcc_code": hcc_code,
        "model_year": yr,
        "raf_coefficient": round(coef, 4),
        "revenue_per_raf_point": round(rate, 2),
        "annual_revenue_dollars": round(coef * rate, 2),
    }


# ---------------------------------------------------------------------------
# Lab pull for a patient + HCC
# ---------------------------------------------------------------------------

def _latest_labs(emr_pid: int, loinc_codes: list[str]) -> list[dict[str, Any]]:
    """Return one row per LOINC — the most recent result for that code.

    Each row: {loinc, value (float), units, date, raw}.
    Skips rows that can't be coerced to float (e.g. "Positive", "ND").
    """
    if not loinc_codes:
        return []
    placeholders = ",".join(["%s"] * len(loinc_codes))
    sql = f"""
        SELECT pr.result_code AS loinc, pr.result AS raw,
               pr.units AS units, pr.date AS dt, pr.range AS ref_range,
               pr.abnormal AS abnormal
        FROM procedure_result pr
        JOIN procedure_report  prep ON prep.procedure_report_id = pr.procedure_report_id
        JOIN procedure_order   po   ON po.procedure_order_id   = prep.procedure_order_id
        WHERE po.patient_id = %s AND pr.result_code IN ({placeholders})
        ORDER BY pr.date DESC
    """
    params: tuple = (int(emr_pid), *loinc_codes)
    try:
        with openemr_cursor() as cur:
            cur.execute(sql, params)
            rows = list(cur.fetchall() or [])
    except Exception as exc:
        logger.warning("latest_labs query failed for pid=%s: %s", emr_pid, exc)
        return []

    # Deduplicate to one (most recent) per LOINC
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for r in rows:
        r = dict(r) if isinstance(r, dict) else dict(zip(
            ("loinc", "raw", "units", "dt", "ref_range", "abnormal"), r
        ))
        loinc = str(r.get("loinc") or "")
        if loinc in seen or not loinc:
            continue
        seen.add(loinc)
        raw = str(r.get("raw") or "").strip()
        # Try to coerce to float
        try:
            val = float(raw)
        except (TypeError, ValueError):
            val = None
        if val is None:
            continue
        out.append({
            "loinc": loinc,
            "value": val,
            "units": str(r.get("units") or ""),
            "date": r.get("dt").isoformat() if r.get("dt") else None,
            "reference_range": str(r.get("ref_range") or ""),
            "abnormal_flag": str(r.get("abnormal") or ""),
            "raw": raw,
        })
    return out


def evidence_for_hcc(
    emr_pid: int,
    hcc_code: str,
    year: int | None = None,
) -> dict[str, Any]:
    """Return the doctor-facing evidence pack for one HCC suspect.

    {
      "hcc_code": "18",
      "supporting_labs": [...],
      "borderline_labs": [...],
      "contradictory_labs": [...],
      "estimated_annual_revenue_dollars": 1847.30,
      "raf_coefficient": 0.158,
      "revenue_per_raf_point": 11680.00,
      "model_year": 2026
    }
    """
    rules = HCC_LAB_RULES.get(str(hcc_code), [])
    loinc_codes = [loinc for loinc, _label, _test in rules]
    latest = {row["loinc"]: row for row in _latest_labs(int(emr_pid), loinc_codes)}

    supporting: list[dict[str, Any]] = []
    borderline: list[dict[str, Any]] = []
    contradictory: list[dict[str, Any]] = []

    for loinc, label, test_fn in rules:
        row = latest.get(loinc)
        if not row:
            continue
        status = test_fn(row["value"])
        entry = {
            "label": label,
            "loinc": loinc,
            "value": row["value"],
            "units": row["units"],
            "date": row["date"],
            "reference_range": row["reference_range"],
            "abnormal_flag": row["abnormal_flag"],
            "status": status,
        }
        if status == "support":
            supporting.append(entry)
        elif status == "borderline":
            borderline.append(entry)
        else:
            contradictory.append(entry)

    rev = estimated_annual_revenue(str(hcc_code), year)
    return {
        "hcc_code": str(hcc_code),
        "supporting_labs": supporting,
        "borderline_labs": borderline,
        "contradictory_labs": contradictory,
        "labs_total_count": len(supporting) + len(borderline) + len(contradictory),
        "estimated_annual_revenue_dollars": rev["annual_revenue_dollars"],
        "raf_coefficient": rev["raf_coefficient"],
        "revenue_per_raf_point": rev["revenue_per_raf_point"],
        "model_year": rev["model_year"],
    }


def evidence_for_gaps(
    emr_pid: int,
    gaps: list[dict[str, Any]],
    year: int | None = None,
) -> list[dict[str, Any]]:
    """Decorate a list of HCC-gap dicts with lab evidence + revenue.

    Mutates each gap dict in place AND returns it (so callers can chain).
    """
    for g in gaps:
        hcc = str(g.get("hcc_code") or g.get("hcc") or "")
        if not hcc:
            continue
        pack = evidence_for_hcc(emr_pid, hcc, year)
        g["lab_evidence"] = {
            "supporting": pack["supporting_labs"],
            "borderline": pack["borderline_labs"],
            "contradictory": pack["contradictory_labs"],
        }
        g["estimated_annual_revenue_dollars"] = pack["estimated_annual_revenue_dollars"]
        g["raf_coefficient"] = pack["raf_coefficient"]
    return gaps
