"""
Provider Revenue Opportunity Breakdown.

Decomposes the rolled-up ``revenue_opportunity`` figure on
``provider_scorecard_snapshots`` into three actionable buckets so coding /
RA leaders can see where the dollars are coming from:

  1. **Recapture**         – chronic HCCs coded in the prior year that have
                              not yet been recaptured this year.
                              lift = Σ coef × (1 − persistence) × HCC_BASE_RATE
  2. **MEAT improvement**  – HCCs already coded this year whose MEAT
                              completeness score is below 0.75 (likely to be
                              denied on RADV audit).
                              lift = Σ coef × (1 − meat_score) × HCC_BASE_RATE
  3. **New suspects**      – open suspect conditions not yet coded.
                              lift = Σ coef × confidence × HCC_BASE_RATE

Math is fully deterministic — no LLM calls.

The CMS V28 chronic-condition persistence default of 0.85 mirrors the
``raf_forecast`` service and is exposed in the response under
``assumptions.persistence`` so callers can audit the calculation.

The HCC base rate is imported from ``provider_service`` (single source of
truth — never hard-coded here).
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

from app.db import raf_cursor
from app.services.emr_manager import active_patients_subquery
from app.services.meat_evidence_service import calculate_meat_completeness
from app.services.provider_service import _HCC_BASE_RATE

logger = logging.getLogger(__name__)

# CMS empirical chronic-condition recapture rate.  Anything not recaptured
# is the $ at risk and forms the recapture bucket.
DEFAULT_CHRONIC_PERSISTENCE: float = 0.85

# MEAT completeness scores below this threshold are flagged for improvement.
# 0.75 corresponds to "3 of 4 MEAT elements present" — anything weaker is
# considered audit-vulnerable.
MEAT_IMPROVEMENT_THRESHOLD: float = 0.75

# Coefficient table is curated for V28 / CNA / 2024 in this DB (mirrors
# raf_forecast.DEFAULT_COEFFICIENT_YEAR / DEFAULT_MODEL_SEGMENT).
DEFAULT_COEFFICIENT_YEAR: int = 2024
DEFAULT_MODEL_SEGMENT: str = "CNA"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _current_year() -> int:
    return date.today().year


def _provider_panel(provider_id: int, tenant_id: int | None = None) -> list[int]:
    """Return distinct active patient_ids assigned to *provider_id*."""
    tid = int(tenant_id) if tenant_id is not None else 1
    sub_frag, sub_params = active_patients_subquery(tid)
    sql = (
        "SELECT DISTINCT patient_id "
        "FROM provider_patient_panel "
        f"WHERE provider_id = %s AND {sub_frag}"
    )
    try:
        with raf_cursor() as cur:
            cur.execute(sql, (provider_id, *sub_params))
            rows = cur.fetchall() or []
        return [int(r["patient_id"]) for r in rows if r.get("patient_id") is not None]
    except Exception as exc:
        logger.warning("provider_panel provider=%s failed: %s", provider_id, exc)
        return []


def _hcc_label_lookup(hcc_codes: list[int]) -> dict[int, str]:
    """Best-effort label lookup from icd10 crosswalk.  Returns {} on miss."""
    if not hcc_codes:
        return {}
    placeholders = ",".join(["%s"] * len(hcc_codes))
    sql = (
        "SELECT hcc_code, MIN(hcc_label) AS hcc_label "
        "FROM hcc_icd10_crosswalk "
        f"WHERE hcc_code IN ({placeholders}) "
        "GROUP BY hcc_code"
    )
    try:
        with raf_cursor() as cur:
            cur.execute(sql, tuple(hcc_codes))
            rows = cur.fetchall() or []
        out: dict[int, str] = {}
        for r in rows:
            try:
                k = int(str(r["hcc_code"]).strip().upper().replace("HCC", ""))
            except (TypeError, ValueError):
                continue
            out[k] = (r.get("hcc_label") or "")
        return out
    except Exception as exc:
        logger.debug("_hcc_label_lookup failed: %s", exc)
        return {}


def _coefficient_lookup(
    hcc_codes: list[int],
    *,
    segment: str = DEFAULT_MODEL_SEGMENT,
    year: int = DEFAULT_COEFFICIENT_YEAR,
) -> dict[int, float]:
    """Bulk fetch RAF coefficients keyed by integer hcc_code."""
    if not hcc_codes:
        return {}
    uniq = sorted(set(int(c) for c in hcc_codes))
    placeholders = ",".join(["%s"] * len(uniq))
    sql = (
        "SELECT hcc_code, coefficient "
        "FROM hcc_raf_coefficients "
        f"WHERE model_segment = %s AND model_year = %s AND hcc_code IN ({placeholders})"
    )
    try:
        with raf_cursor() as cur:
            cur.execute(sql, (segment, year, *uniq))
            rows = cur.fetchall() or []
        out: dict[int, float] = {}
        for r in rows:
            try:
                k = int(str(r["hcc_code"]).strip().upper().replace("HCC", ""))
            except (TypeError, ValueError):
                continue
            try:
                out[k] = float(r["coefficient"])
            except (TypeError, ValueError):
                continue
        return out
    except Exception as exc:
        logger.warning("_coefficient_lookup failed: %s", exc)
        return {}


def _coded_hccs_this_year(panel: list[int], year: int) -> list[dict[str, Any]]:
    """HCCs coded for the panel in *year*."""
    if not panel:
        return []
    placeholders = ",".join(["%s"] * len(panel))
    sql = (
        "SELECT id, patient_id, hcc_code, raf_coefficient "
        "FROM raf_patient_hcc "
        f"WHERE measurement_year = %s AND patient_id IN ({placeholders}) "
        "  AND COALESCE(is_trumped, 0) = 0"
    )
    try:
        with raf_cursor() as cur:
            cur.execute(sql, (year, *panel))
            return list(cur.fetchall() or [])
    except Exception as exc:
        logger.warning("_coded_hccs_this_year failed: %s", exc)
        return []


def _prior_year_unrecaptured(
    panel: list[int], year: int
) -> list[dict[str, Any]]:
    """
    Prior-year HCCs that are NOT in the current year for any panel patient.
    Each row has (patient_id, hcc_code, raf_coefficient).
    """
    if not panel:
        return []
    placeholders = ",".join(["%s"] * len(panel))
    sql = (
        "SELECT prior.patient_id, prior.hcc_code, prior.raf_coefficient "
        "FROM raf_patient_hcc prior "
        "LEFT JOIN raf_patient_hcc cur "
        "  ON  cur.patient_id       = prior.patient_id "
        "  AND cur.hcc_code         = prior.hcc_code "
        "  AND cur.measurement_year = %s "
        "WHERE prior.measurement_year = %s "
        f"  AND prior.patient_id IN ({placeholders}) "
        "  AND cur.id IS NULL"
    )
    try:
        with raf_cursor() as cur:
            cur.execute(sql, (year, year - 1, *panel))
            return list(cur.fetchall() or [])
    except Exception as exc:
        logger.warning("_prior_year_unrecaptured failed: %s", exc)
        return []


def _open_suspects(panel: list[int], year: int) -> list[dict[str, Any]]:
    """Open suspects for the panel in *year*."""
    if not panel:
        return []
    placeholders = ",".join(["%s"] * len(panel))
    sql = (
        "SELECT id, patient_id, suspect_hcc, confidence_score "
        "FROM raf_suspect_conditions "
        f"WHERE status = 'open' AND measurement_year = %s "
        f"  AND patient_id IN ({placeholders})"
    )
    try:
        with raf_cursor() as cur:
            cur.execute(sql, (year, *panel))
            return list(cur.fetchall() or [])
    except Exception as exc:
        logger.warning("_open_suspects failed: %s", exc)
        return []


def _meat_score_by_phcc(panel: list[int], year: int) -> dict[int, float]:
    """
    Map raf_patient_hcc.id → MEAT completeness fraction (0.0–1.0) using the
    canonical ``calculate_meat_completeness`` service per patient.
    """
    out: dict[int, float] = {}
    for pid in panel:
        try:
            res = calculate_meat_completeness(pid, year)
        except Exception as exc:
            logger.debug("calculate_meat_completeness pid=%s: %s", pid, exc)
            continue
        for entry in res.get("per_hcc", []) or []:
            phcc_id = entry.get("patient_hcc_id")
            score = entry.get("meat_score")
            if phcc_id is None or score is None:
                continue
            # ``meat_score`` in the service is 0–4; normalize to 0.0–1.0.
            out[int(phcc_id)] = round(float(score) / 4.0, 4)
    return out


def _top_n_by_dollars(
    rows: list[dict[str, Any]], n: int = 3
) -> list[dict[str, Any]]:
    """Return the top *n* rows sorted by ``dollars`` desc."""
    return sorted(rows, key=lambda r: r.get("dollars", 0.0), reverse=True)[:n]


def _to_int(v: Any) -> int | None:
    """Coerce hcc_code-like values to int, returning None on empty/garbage."""
    try:
        s = str(v).strip().upper().replace("HCC", "")
        return int(s) if s else None
    except (TypeError, ValueError):
        return None


def _aggregate_hcc(
    rows: list[dict[str, Any]],
    labels: dict[int, str],
) -> list[dict[str, Any]]:
    """
    Collapse a list of per-row dollar contributions to one entry per
    hcc_code so the "top contributors" UI doesn't show the same code 30 times.
    """
    by_code: dict[int, dict[str, Any]] = {}
    for r in rows:
        code = _to_int(r["hcc_code"])
        if code is None:
            continue
        d = float(r.get("dollars", 0.0) or 0.0)
        if code not in by_code:
            by_code[code] = {
                "hcc_code": str(code),
                "hcc_label": labels.get(code, "") or f"HCC {code}",
                "dollars": 0.0,
            }
        by_code[code]["dollars"] += d
    out = list(by_code.values())
    for r in out:
        r["dollars"] = round(r["dollars"], 2)
    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_breakdown(
    provider_id: int,
    year: int | None = None,
    *,
    tenant_id: int | None = None,
    persistence: float = DEFAULT_CHRONIC_PERSISTENCE,
    meat_threshold: float = MEAT_IMPROVEMENT_THRESHOLD,
) -> dict[str, Any]:
    """
    Decompose a provider's revenue opportunity into three buckets.

    Returns
    -------
    dict shaped::

        {
          "provider_id": 1,
          "year": 2026,
          "total": 218400.0,
          "buckets": [
            {
              "name": "Recapture",
              "amount": 90000.0,
              "pct_of_total": 41.21,
              "count": 12,
              "top_3_hccs": [
                {"hcc_code": "108", "hcc_label": "...", "dollars": 25000.0},
                ...
              ]
            },
            ...
          ],
          "assumptions": {"persistence": 0.85, "base_rate": 12000.0,
                          "meat_threshold": 0.75,
                          "model_segment": "CNA",
                          "coefficient_year": 2024}
        }
    """
    yr = int(year) if year is not None else _current_year()
    panel = _provider_panel(provider_id, tenant_id=tenant_id)

    # Empty panel → return zero-shaped response (not an error)
    if not panel:
        return _empty_response(provider_id, yr, persistence, meat_threshold)

    # --- 1. Pull raw rows for each bucket ----------------------------------
    coded = _coded_hccs_this_year(panel, yr)
    prior_unrecap = _prior_year_unrecaptured(panel, yr)
    suspects = _open_suspects(panel, yr)

    # Collect every HCC code we'll need a coefficient or label for.
    def _to_int(v: Any) -> int | None:
        try:
            s = str(v).strip().upper().replace("HCC", "")
            return int(s) if s else None
        except (TypeError, ValueError):
            return None

    all_codes: set[int] = set()
    for r in coded:
        v = _to_int(r["hcc_code"])
        if v is not None:
            all_codes.add(v)
    for r in prior_unrecap:
        v = _to_int(r["hcc_code"])
        if v is not None:
            all_codes.add(v)
    for r in suspects:
        v = _to_int(r["suspect_hcc"])
        if v is not None:
            all_codes.add(v)
    coeffs = _coefficient_lookup(list(all_codes))
    labels = _hcc_label_lookup(list(all_codes))

    # --- 2. Recapture bucket ----------------------------------------------
    risk_factor = max(0.0, 1.0 - float(persistence))
    recapture_rows: list[dict[str, Any]] = []
    for r in prior_unrecap:
        code = _to_int(r["hcc_code"])
        if code is None:
            continue
        # Prefer the coefficient stored on the prior-year row (already
        # segment-resolved at coding time); fall back to the lookup.
        coef = float(r.get("raf_coefficient") or 0.0) or coeffs.get(code, 0.0)
        dollars = coef * risk_factor * _HCC_BASE_RATE
        if dollars <= 0:
            continue
        recapture_rows.append({"hcc_code": code, "dollars": dollars})
    recapture_amt = sum(r["dollars"] for r in recapture_rows)

    # --- 3. MEAT improvement bucket ---------------------------------------
    meat_scores = _meat_score_by_phcc(panel, yr)
    meat_rows: list[dict[str, Any]] = []
    for r in coded:
        code = _to_int(r["hcc_code"])
        if code is None:
            continue
        phcc_id = int(r["id"])
        meat = float(meat_scores.get(phcc_id, 0.0))
        if meat >= meat_threshold:
            continue
        coef = float(r.get("raf_coefficient") or 0.0) or coeffs.get(code, 0.0)
        dollars = coef * (1.0 - meat) * _HCC_BASE_RATE
        if dollars <= 0:
            continue
        meat_rows.append({"hcc_code": code, "dollars": dollars})
    meat_amt = sum(r["dollars"] for r in meat_rows)

    # --- 4. New suspects bucket -------------------------------------------
    suspect_rows: list[dict[str, Any]] = []
    for s in suspects:
        code = int(s["suspect_hcc"])
        coef = coeffs.get(code, 0.0)
        confidence = float(s.get("confidence_score") or 0.0)
        dollars = coef * confidence * _HCC_BASE_RATE
        if dollars <= 0:
            continue
        suspect_rows.append({"hcc_code": code, "dollars": dollars})
    suspect_amt = sum(r["dollars"] for r in suspect_rows)

    total = recapture_amt + meat_amt + suspect_amt

    def pct(x: float) -> float:
        return round((x / total) * 100.0, 2) if total > 0 else 0.0

    buckets = [
        {
            "name": "Recapture",
            "amount": round(recapture_amt, 2),
            "pct_of_total": pct(recapture_amt),
            "count": len(recapture_rows),
            "top_3_hccs": _top_n_by_dollars(_aggregate_hcc(recapture_rows, labels)),
        },
        {
            "name": "MEAT improvement",
            "amount": round(meat_amt, 2),
            "pct_of_total": pct(meat_amt),
            "count": len(meat_rows),
            "top_3_hccs": _top_n_by_dollars(_aggregate_hcc(meat_rows, labels)),
        },
        {
            "name": "New suspects",
            "amount": round(suspect_amt, 2),
            "pct_of_total": pct(suspect_amt),
            "count": len(suspect_rows),
            "top_3_hccs": _top_n_by_dollars(_aggregate_hcc(suspect_rows, labels)),
        },
    ]

    return {
        "provider_id": int(provider_id),
        "year": yr,
        "total": round(total, 2),
        "buckets": buckets,
        "assumptions": {
            "persistence": float(persistence),
            "base_rate": float(_HCC_BASE_RATE),
            "meat_threshold": float(meat_threshold),
            "model_segment": DEFAULT_MODEL_SEGMENT,
            "coefficient_year": DEFAULT_COEFFICIENT_YEAR,
        },
        "panel_size": len(panel),
    }


def _empty_response(
    provider_id: int,
    year: int,
    persistence: float,
    meat_threshold: float,
) -> dict[str, Any]:
    """Zero-shaped breakdown so the UI can render an empty-state card."""
    return {
        "provider_id": int(provider_id),
        "year": int(year),
        "total": 0.0,
        "buckets": [
            {"name": "Recapture", "amount": 0.0, "pct_of_total": 0.0,
             "count": 0, "top_3_hccs": []},
            {"name": "MEAT improvement", "amount": 0.0, "pct_of_total": 0.0,
             "count": 0, "top_3_hccs": []},
            {"name": "New suspects", "amount": 0.0, "pct_of_total": 0.0,
             "count": 0, "top_3_hccs": []},
        ],
        "assumptions": {
            "persistence": float(persistence),
            "base_rate": float(_HCC_BASE_RATE),
            "meat_threshold": float(meat_threshold),
            "model_segment": DEFAULT_MODEL_SEGMENT,
            "coefficient_year": DEFAULT_COEFFICIENT_YEAR,
        },
        "panel_size": 0,
    }
