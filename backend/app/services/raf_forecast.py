"""
RAF Financial Forecast Service.

Translates pending RAF clinical signals into forward-looking revenue
impact ($) so CFOs / VPRA leaders can prioritize coding interventions.

Three scopes:
    * patient   – single-member projection
    * provider  – aggregate of a panel (list of patient_ids)
    * tenant    – org-wide population projection

Math (deterministic — no LLM call):

    suspect_lift_raf       = Σ (coefficient_i × confidence_i)         [open suspects]
    removal_risk_raf       = Σ (coefficient_j × (1 - persistence))    [unrecaptured chronic HCCs]
    net_projected_raf      = current_raf + suspect_lift_raf − removal_risk_raf

    *_revenue              = *_raf × HCC_BASE_RATE

`HCC_BASE_RATE` is imported from `app.config`; never hard-coded.

Persistence assumption: chronic HCCs that were coded in the prior measurement
year carry a 0.85 default re-capture probability (the CMS empirical chronic-
condition recapture rate).  Anything not recaptured is treated as a $ at risk.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

from app.db import raf_cursor
from app.services.provider_service import _HCC_BASE_RATE as HCC_BASE_RATE

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tunable constants
# ---------------------------------------------------------------------------

# Probability that a chronic HCC coded last year *should* be re-captured this
# year.  Anything below this is the "removal risk" — RAF $ in jeopardy.
DEFAULT_CHRONIC_PERSISTENCE: float = 0.85

# CMS-HCC V28 default model segment used when a patient has no demographics
# row yet.  Conservative — community, non-dual, aged.
DEFAULT_MODEL_SEGMENT: str = "CNA"

# CMS V28 coefficient table is curated for model_year 2024 in this DB.
DEFAULT_COEFFICIENT_YEAR: int = 2024


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _current_year() -> int:
    return date.today().year


def _resolve_segment(patient_id: int, year: int) -> str:
    """Best-effort lookup of stored model segment; defaults to CNA."""
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT model_segment
                FROM raf_patient_demographics
                WHERE patient_id = %s AND measurement_year = %s
                LIMIT 1
                """,
                (patient_id, year),
            )
            row = cur.fetchone()
        if row and row.get("model_segment"):
            return row["model_segment"]
    except Exception as exc:
        logger.debug("_resolve_segment pid=%s: %s", patient_id, exc)
    return DEFAULT_MODEL_SEGMENT


def _coefficient_lookup(
    hcc_codes: list[int | str],
    segment: str,
    year: int = DEFAULT_COEFFICIENT_YEAR,
) -> dict[str, float]:
    """
    Bulk fetch RAF coefficients for a list of HCC codes / segment / year.
    Returns a dict keyed by string HCC code.
    """
    if not hcc_codes:
        return {}

    # Normalise to int (table column is SMALLINT) but keep string keys for output
    int_codes: list[int] = []
    for c in hcc_codes:
        try:
            int_codes.append(int(str(c).replace("HCC", "").strip()))
        except (ValueError, TypeError):
            continue

    if not int_codes:
        return {}

    placeholders = ",".join(["%s"] * len(int_codes))
    sql = f"""
        SELECT hcc_code, coefficient
        FROM hcc_raf_coefficients
        WHERE model_segment = %s
          AND model_year    = %s
          AND hcc_code IN ({placeholders})
    """

    try:
        with raf_cursor() as cur:
            cur.execute(sql, (segment, year, *int_codes))
            rows = cur.fetchall()
        return {str(r["hcc_code"]): float(r["coefficient"]) for r in rows}
    except Exception as exc:
        logger.warning(
            "_coefficient_lookup failed segment=%s year=%s codes=%s: %s",
            segment, year, int_codes, exc,
        )
        return {}


def _current_raf(patient_id: int, year: int) -> float:
    """Latest stored final RAF score for a patient/year. 0.0 if missing."""
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT final_raf
                FROM raf_scores
                WHERE patient_id = %s AND measurement_year = %s
                ORDER BY calculated_at DESC
                LIMIT 1
                """,
                (patient_id, year),
            )
            row = cur.fetchone()
        if row and row.get("final_raf") is not None:
            return float(row["final_raf"])
    except Exception as exc:
        logger.debug("_current_raf pid=%s: %s", patient_id, exc)
    return 0.0


def _open_suspects(patient_id: int, year: int) -> list[dict[str, Any]]:
    """
    Open suspects for a patient/year.  Each row carries suspect_hcc,
    confidence_score, suspect_icd10, evidence_type.
    """
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT id, suspect_hcc, suspect_icd10, evidence_type,
                       confidence_score
                FROM raf_suspect_conditions
                WHERE patient_id      = %s
                  AND measurement_year = %s
                  AND status            = 'open'
                """,
                (patient_id, year),
            )
            return list(cur.fetchall() or [])
    except Exception as exc:
        logger.debug("_open_suspects pid=%s: %s", patient_id, exc)
        return []


def _prior_year_chronic_hccs(patient_id: int, year: int) -> list[dict[str, Any]]:
    """
    HCCs coded in (year-1) that are NOT present in (year).  These are the
    "removal risk" — chronic conditions awaiting re-capture.
    """
    prior = year - 1
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT prior.hcc_code, prior.raf_coefficient
                FROM raf_patient_hcc prior
                LEFT JOIN raf_patient_hcc cur
                  ON  cur.patient_id       = prior.patient_id
                  AND cur.hcc_code         = prior.hcc_code
                  AND cur.measurement_year = %s
                WHERE prior.patient_id       = %s
                  AND prior.measurement_year = %s
                  AND cur.id IS NULL
                """,
                (year, patient_id, prior),
            )
            return list(cur.fetchall() or [])
    except Exception as exc:
        logger.debug("_prior_year_chronic_hccs pid=%s: %s", patient_id, exc)
        return []


# ---------------------------------------------------------------------------
# Public: patient forecast
# ---------------------------------------------------------------------------

def calculate_patient_forecast(
    patient_id: int,
    measurement_year: int | None = None,
    *,
    persistence: float = DEFAULT_CHRONIC_PERSISTENCE,
) -> dict[str, Any]:
    """
    Project the financial impact of accepting open suspects + recapturing
    last year's chronic HCCs for a single patient.

    Returns a dict shaped::

        {
          "patient_id": 123,
          "measurement_year": 2026,
          "model_segment": "CNA",
          "base_rate": 12000.0,
          "current_raf": 1.234,
          "current_revenue": 14808.0,
          "suspect_lift_raf": 0.456,
          "suspect_lift_revenue": 5472.0,
          "removal_risk_raf": 0.123,
          "removal_risk_revenue": 1476.0,
          "net_projected_raf": 1.567,
          "net_projected_revenue": 18804.0,
          "by_suspect": [
            {"suspect_id": 9, "hcc": "108", "icd10": "I5022",
             "evidence_type": "medication", "coefficient": 0.323,
             "confidence": 0.85, "lift_raf": 0.2746,
             "lift_revenue": 3295.0},
            ...
          ],
          "open_suspect_count": 4,
          "removal_risk_hcc_count": 2,
        }
    """
    year = measurement_year or _current_year()
    segment = _resolve_segment(patient_id, year)

    # 1. Current state -------------------------------------------------------
    current_raf = _current_raf(patient_id, year)

    # 2. Suspect lift --------------------------------------------------------
    suspects = _open_suspects(patient_id, year)
    suspect_codes = [s["suspect_hcc"] for s in suspects]
    coeffs = _coefficient_lookup(suspect_codes, segment)

    by_suspect: list[dict[str, Any]] = []
    suspect_lift_raf = 0.0
    for s in suspects:
        hcc_str = str(s["suspect_hcc"])
        coeff = coeffs.get(hcc_str, 0.0)
        confidence = float(s.get("confidence_score") or 0.0)
        lift = coeff * confidence
        suspect_lift_raf += lift
        by_suspect.append({
            "suspect_id": int(s["id"]),
            "hcc": hcc_str,
            "icd10": s.get("suspect_icd10") or "",
            "evidence_type": s.get("evidence_type") or "",
            "coefficient": round(coeff, 4),
            "confidence": round(confidence, 4),
            "lift_raf": round(lift, 4),
            "lift_revenue": round(lift * HCC_BASE_RATE, 2),
        })
    by_suspect.sort(key=lambda r: r["lift_revenue"], reverse=True)

    # 3. Removal risk --------------------------------------------------------
    risk_rows = _prior_year_chronic_hccs(patient_id, year)
    removal_risk_raf = 0.0
    risk_factor = max(0.0, 1.0 - persistence)
    for row in risk_rows:
        coeff = float(row.get("raf_coefficient") or 0.0)
        removal_risk_raf += coeff * risk_factor

    # 4. Compose -------------------------------------------------------------
    net_projected_raf = current_raf + suspect_lift_raf - removal_risk_raf

    return {
        "patient_id": patient_id,
        "measurement_year": year,
        "model_segment": segment,
        "base_rate": HCC_BASE_RATE,
        "persistence_assumption": persistence,
        "current_raf": round(current_raf, 4),
        "current_revenue": round(current_raf * HCC_BASE_RATE, 2),
        "suspect_lift_raf": round(suspect_lift_raf, 4),
        "suspect_lift_revenue": round(suspect_lift_raf * HCC_BASE_RATE, 2),
        "removal_risk_raf": round(removal_risk_raf, 4),
        "removal_risk_revenue": round(removal_risk_raf * HCC_BASE_RATE, 2),
        "net_projected_raf": round(net_projected_raf, 4),
        "net_projected_revenue": round(net_projected_raf * HCC_BASE_RATE, 2),
        "by_suspect": by_suspect,
        "open_suspect_count": len(suspects),
        "removal_risk_hcc_count": len(risk_rows),
    }


# ---------------------------------------------------------------------------
# Public: provider forecast (panel of patients)
# ---------------------------------------------------------------------------

def calculate_provider_forecast(
    provider_id: int | str,
    patient_ids: list[int] | None = None,
    measurement_year: int | None = None,
) -> dict[str, Any]:
    """
    Aggregate forecast for a provider's panel.

    The current schema has no `provider_id → patient` mapping table — when
    `patient_ids` is None the function attempts to derive the panel from
    OpenEMR encounters (provider field).  If neither yields any patients
    the result is an empty aggregate.  Pass `patient_ids` explicitly when
    the caller already knows the panel.
    """
    year = measurement_year or _current_year()
    pids = patient_ids or _provider_panel(provider_id)

    per_patient: list[dict[str, Any]] = []
    totals = {
        "current_raf": 0.0,
        "current_revenue": 0.0,
        "suspect_lift_raf": 0.0,
        "suspect_lift_revenue": 0.0,
        "removal_risk_raf": 0.0,
        "removal_risk_revenue": 0.0,
        "net_projected_raf": 0.0,
        "net_projected_revenue": 0.0,
        "open_suspect_count": 0,
        "removal_risk_hcc_count": 0,
    }

    for pid in pids:
        try:
            f = calculate_patient_forecast(pid, year)
        except Exception as exc:
            logger.warning(
                "calculate_provider_forecast pid=%s skipped: %s", pid, exc
            )
            continue

        per_patient.append({
            "patient_id": pid,
            "current_raf": f["current_raf"],
            "suspect_lift_raf": f["suspect_lift_raf"],
            "removal_risk_raf": f["removal_risk_raf"],
            "net_projected_raf": f["net_projected_raf"],
            "suspect_lift_revenue": f["suspect_lift_revenue"],
            "open_suspect_count": f["open_suspect_count"],
        })
        for k in totals:
            totals[k] += f.get(k, 0.0) or 0.0

    panel_size = len(per_patient)
    avg_lift_per_member = (
        round(totals["suspect_lift_revenue"] / panel_size, 2) if panel_size else 0.0
    )

    # Round monetary / RAF totals for transport
    totals_rounded = {
        k: (round(v, 4) if "raf" in k else round(v, 2)) if isinstance(v, float) else v
        for k, v in totals.items()
    }

    return {
        "provider_id": provider_id,
        "measurement_year": year,
        "base_rate": HCC_BASE_RATE,
        "panel_size": panel_size,
        "avg_lift_revenue_per_member": avg_lift_per_member,
        "totals": totals_rounded,
        "by_patient": sorted(
            per_patient, key=lambda r: r["suspect_lift_revenue"], reverse=True
        ),
    }


def _provider_panel(provider_id: int | str) -> list[int]:
    """
    Best-effort: return distinct patient pids assigned to a provider via
    OpenEMR encounters.  Returns [] if the lookup fails.

    NOTE: stub — the RAF DB does not yet model provider→patient assignment.
    Replace with a join against a dedicated `raf_provider_patients` table
    once that exists.
    """
    try:
        from app.db import openemr_cursor
        with openemr_cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT pid
                FROM form_encounter
                WHERE provider_id = %s
                """,
                (provider_id,),
            )
            rows = cur.fetchall() or []
        return [int(r["pid"]) for r in rows if r.get("pid") is not None]
    except Exception as exc:
        logger.debug("_provider_panel provider=%s: %s", provider_id, exc)
        return []


# ---------------------------------------------------------------------------
# Public: tenant (org-wide) forecast
# ---------------------------------------------------------------------------

def calculate_tenant_forecast(
    tenant_id: int | str | None = None,
    measurement_year: int | None = None,
    *,
    patient_limit: int | None = None,
) -> dict[str, Any]:
    """
    Org-wide forecast.  In single-tenant deployments `tenant_id` is ignored
    and every patient with stored RAF or open suspects is included.

    For very large populations pass `patient_limit` for a sampled estimate.
    """
    year = measurement_year or _current_year()
    pids = _all_active_patient_ids(year, limit=patient_limit)

    panel = calculate_provider_forecast(
        provider_id=f"tenant:{tenant_id or 'default'}",
        patient_ids=pids,
        measurement_year=year,
    )
    panel["tenant_id"] = tenant_id or "default"
    panel.pop("provider_id", None)
    return panel


def _all_active_patient_ids(year: int, *, limit: int | None = None) -> list[int]:
    """
    Union of patients with either (a) a stored RAF score for `year`, or
    (b) at least one open suspect for `year`.  These are the patients for
    whom a forecast is meaningful.
    """
    sql = """
        SELECT DISTINCT pid FROM (
            SELECT patient_id AS pid
            FROM raf_scores
            WHERE measurement_year = %s
            UNION
            SELECT patient_id AS pid
            FROM raf_suspect_conditions
            WHERE measurement_year = %s AND status = 'open'
        ) t
        ORDER BY pid
    """
    if limit:
        sql += f" LIMIT {int(limit)}"

    try:
        with raf_cursor() as cur:
            cur.execute(sql, (year, year))
            rows = cur.fetchall() or []
        return [int(r["pid"]) for r in rows if r.get("pid") is not None]
    except Exception as exc:
        logger.warning("_all_active_patient_ids year=%s: %s", year, exc)
        return []
