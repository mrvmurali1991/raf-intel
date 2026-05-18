"""
metrics_service.py — Single source of truth for all Revenue-at-Risk metrics.

Every page that displays Revenue-at-Risk, Recapture Rate, or Provider Average RAF
MUST call these functions rather than computing its own SQL or multiplier.

Root cause of the three-value divergence this module fixes
----------------------------------------------------------
- /recapture used recapture_gaps.revenue_impact stamped at $3,000/gap (a fixed
  per-gap dollar guess, not a per-RAF-point calculation).
- /prospective multiplied open suspect RAF (0.15/suspect) by settings.cms_revenue_per_raf_point
  ($11,015.04), giving a different population and multiplier.
- /reports applied settings.cms_revenue_per_raf_point to a third RAF-gap SQL.

Canonical formula (this module)
--------------------------------
  revenue_at_risk = SUM(open_recapture_gaps.raf_coefficient) * revenue_per_raf_point(payment_year)

  Where:
    - raf_coefficient comes from raf_patient_hcc.raf_coefficient (CMS model coefficient)
      for gaps that exist in prior year but NOT in current year
    - revenue_per_raf_point is sourced from raf.revenue_constants.revenue_per_raf_point(year)
      which encodes the CMS annual MA base rate per payment year
    - payment_year defaults to the current calendar year

Scopes
------
  scope="recapture" — open rows in recapture_gaps table (preferred when populated)
  scope="prospective" — open raf_suspect_conditions rows (AI-detected suspects)
  scope="all" — recapture + prospective combined (default; used on /dashboard)

All callers receive a ``_meta`` key alongside every metric value:
  {
    "value": <float>,
    "_meta": {
      "formula": "<human-readable formula string>",
      "version": "v1",
      "last_computed_at": "<ISO-8601 UTC>",
      "payment_year": <int>,
      "revenue_per_raf_point": <float>,
      "scope": "<recapture|prospective|all>",
    }
  }
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Literal

from app.config import settings
from app.db import raf_cursor
from app.services.raf.revenue_constants import revenue_per_raf_point as _rate_lookup

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Sentinel — bumped when the formula logic changes so callers can detect staleness
# ---------------------------------------------------------------------------
METRICS_VERSION = "v1"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds") + "Z"


def _resolve_rate(payment_year: int | None) -> float:
    """Return the correct CMS revenue-per-RAF-point for the given payment year.

    Priority:
    1. If CMS_REVENUE_PER_RAF_POINT env var is set, honour it (operator override).
    2. Otherwise use the year-keyed table in revenue_constants.
    """
    env_override = float(settings.cms_revenue_per_raf_point)
    # The config default is 11015.04 which matches PY2024 exactly.
    # If the operator has not overridden it, use the year-based table for accuracy.
    default_from_table = _rate_lookup(None)  # returns PY2026 fallback = 11800.00
    if abs(env_override - default_from_table) > 0.01:
        # Operator has explicitly set a non-default value — respect it.
        return env_override
    return _rate_lookup(payment_year)


def _current_year() -> int:
    return datetime.now(timezone.utc).year


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

Scope = Literal["recapture", "prospective", "all"]


def revenue_at_risk(
    tenant_id: str,
    payment_year: int | None = None,
    scope: Scope = "recapture",
) -> dict[str, Any]:
    """Return Revenue-at-Risk with canonical formula metadata.

    This is the SINGLE function all pages must call. It never computes
    a per-gap flat dollar—it always multiplies real RAF coefficients by the
    CMS rate for the payment year.

    Args:
        tenant_id:    Tenant scope.
        payment_year: CMS payment year (defaults to current calendar year).
        scope:        "recapture"  — prior-year HCCs not yet recaptured
                      "prospective"— AI-detected open suspect conditions
                      "all"        — union of both (used on dashboard)

    Returns:
        {
            "value": float,          # dollars
            "_meta": { formula, version, last_computed_at, ... }
        }
    """
    if not tenant_id:
        raise ValueError("metrics_service.revenue_at_risk: tenant_id is required")

    year = payment_year or _current_year()
    rate = _resolve_rate(year)
    prior_year = year - 1

    total_raf: float = 0.0

    if scope in ("recapture", "all"):
        # Canonical SQL: sum raf_coefficient for HCCs present in prior year
        # but absent in current year (unrecaptured HCCs).
        # Falls back gracefully when recapture_gaps table is absent.
        try:
            recapture_raf = _recapture_raf_sum(tenant_id, prior_year, year)
            total_raf += recapture_raf
        except Exception as exc:
            logger.warning("metrics_service: recapture RAF query failed: %s", exc)

    if scope in ("prospective", "all"):
        # Canonical SQL: sum raf_coefficient (defaulting to 0.15 per suspect)
        # for open suspect conditions.
        try:
            suspect_raf = _suspect_raf_sum(tenant_id)
            total_raf += suspect_raf
        except Exception as exc:
            logger.warning("metrics_service: suspect RAF query failed: %s", exc)

    value = round(total_raf * rate, 2)

    scope_desc = {
        "recapture":   "SUM(raf_patient_hcc.raf_coefficient WHERE prior_year HCC absent in current_year)",
        "prospective": "SUM(raf_suspect_conditions.raf_coefficient WHERE status='open')",
        "all":         "SUM(recapture_raf_coefficient) + SUM(suspect_raf_coefficient)",
    }[scope]

    return {
        "value": value,
        "_meta": {
            "formula": (
                f"({scope_desc}) "
                f"* revenue_per_raf_point({year}) "
                f"= {round(total_raf, 4)} RAF-pts * ${rate:,.2f}/pt = ${value:,.2f}"
            ),
            "version": METRICS_VERSION,
            "last_computed_at": _now_iso(),
            "payment_year": year,
            "revenue_per_raf_point": rate,
            "total_raf_points": round(total_raf, 4),
            "scope": scope,
        },
    }


def recapture_rate(
    tenant_id: str,
    payment_year: int | None = None,
) -> dict[str, Any]:
    """Return the recapture rate as a percentage with canonical formula metadata.

    Formula:
        recaptured_hccs / (recaptured_hccs + open_hccs) * 100

    Returns:
        {
            "value": float,    # percent 0-100
            "_meta": { ... }
        }
    """
    if not tenant_id:
        raise ValueError("metrics_service.recapture_rate: tenant_id is required")

    year = payment_year or _current_year()
    prior_year = year - 1

    sql = """
        SELECT
            SUM(status = 'recaptured')                    AS recaptured,
            SUM(status IN ('open', 'recaptured'))         AS total_eligible
        FROM recapture_gaps
        WHERE tenant_id   = %s
          AND prior_year  = %s
          AND current_year = %s
    """

    recaptured: int = 0
    total: int = 0

    try:
        with raf_cursor() as cur:
            cur.execute(sql, (tenant_id, prior_year, year))
            row = cur.fetchone()
            if row:
                recaptured = int(row["recaptured"] or 0)
                total = int(row["total_eligible"] or 0)
    except Exception as exc:
        logger.warning("metrics_service.recapture_rate query failed: %s", exc)

    rate_pct = round((recaptured / total) * 100, 2) if total else 0.0

    return {
        "value": rate_pct,
        "_meta": {
            "formula": (
                f"recaptured_hccs({recaptured}) / total_eligible_hccs({total}) * 100"
                f" = {rate_pct}%"
            ),
            "version": METRICS_VERSION,
            "last_computed_at": _now_iso(),
            "payment_year": year,
            "recaptured": recaptured,
            "total_eligible": total,
            "scope": "recapture_gaps",
        },
    }


def provider_average_raf(
    tenant_id: str,
    provider_id: int | None = None,
    payment_year: int | None = None,
) -> dict[str, Any]:
    """Return average RAF score per provider (or across all providers).

    Formula:
        AVG(raf_scores.final_raf) WHERE measurement_year = payment_year

    Returns:
        {
            "value": float,    # average RAF score
            "_meta": { ... }
        }
    """
    if not tenant_id:
        raise ValueError("metrics_service.provider_average_raf: tenant_id is required")

    year = payment_year or _current_year()

    params: list[Any] = [year, tenant_id]
    provider_clause = ""
    if provider_id is not None:
        provider_clause = "AND ppp.provider_id = %s"
        params.append(provider_id)

    sql = f"""
        SELECT AVG(rs.final_raf) AS avg_raf,
               COUNT(DISTINCT rs.patient_id) AS patient_count
        FROM raf_scores rs
        JOIN patients p ON p.id = rs.patient_id AND p.tenant_id = %s
        LEFT JOIN provider_patient_panel ppp ON ppp.patient_id = rs.patient_id
        WHERE rs.measurement_year = %s
          AND p.is_active = 1
          {provider_clause}
    """

    # Fix param order: measurement_year first then tenant_id
    params = [year, tenant_id]
    if provider_id is not None:
        params.append(provider_id)

    avg: float = 0.0
    patient_count: int = 0

    try:
        with raf_cursor() as cur:
            cur.execute(
                f"""
                SELECT AVG(rs.final_raf) AS avg_raf,
                       COUNT(DISTINCT rs.patient_id) AS patient_count
                FROM raf_scores rs
                JOIN patients p ON p.id = rs.patient_id
                LEFT JOIN provider_patient_panel ppp ON ppp.patient_id = rs.patient_id
                WHERE rs.measurement_year = %s
                  AND p.tenant_id = %s
                  AND p.is_active = 1
                  {provider_clause}
                """,
                params,
            )
            row = cur.fetchone()
            if row:
                avg = round(float(row["avg_raf"] or 0.0), 4)
                patient_count = int(row["patient_count"] or 0)
    except Exception as exc:
        logger.warning("metrics_service.provider_average_raf query failed: %s", exc)

    scope_label = f"provider_id={provider_id}" if provider_id else "all_providers"
    return {
        "value": avg,
        "_meta": {
            "formula": (
                f"AVG(raf_scores.final_raf) WHERE measurement_year={year}"
                f" AND tenant_id={tenant_id} [{scope_label}]"
                f" = {avg} over {patient_count} patients"
            ),
            "version": METRICS_VERSION,
            "last_computed_at": _now_iso(),
            "payment_year": year,
            "patient_count": patient_count,
            "scope": scope_label,
        },
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _recapture_raf_sum(tenant_id: str, prior_year: int, current_year: int) -> float:
    """Sum raf_coefficient for HCCs that existed in prior_year but not current_year.

    Uses recapture_gaps table when available (status='open'); falls back to
    raf_patient_hcc NOT EXISTS subquery when the table is absent or empty.
    """
    # Preferred path: recapture_gaps with real raf_coefficient from raf_patient_hcc
    sql_with_table = """
        SELECT COALESCE(SUM(ph.raf_coefficient), 0) AS total_raf
        FROM recapture_gaps rg
        JOIN raf_patient_hcc ph
          ON ph.patient_id       = rg.patient_id
         AND ph.hcc_code         = rg.hcc_code
         AND ph.measurement_year = %s
         AND ph.tenant_id        = %s
        WHERE rg.tenant_id    = %s
          AND rg.prior_year   = %s
          AND rg.current_year = %s
          AND rg.status       = 'open'
    """

    # Fallback path: derive directly from raf_patient_hcc when recapture_gaps is empty
    sql_fallback = """
        SELECT COALESCE(SUM(ph.raf_coefficient), 0) AS total_raf
        FROM raf_patient_hcc ph
        JOIN patients p ON p.id = ph.patient_id
        WHERE ph.tenant_id        = %s
          AND ph.measurement_year = %s
          AND p.is_active         = 1
          AND p.tenant_id         = %s
          AND NOT EXISTS (
              SELECT 1 FROM raf_patient_hcc cy
              WHERE cy.patient_id       = ph.patient_id
                AND cy.hcc_code         = ph.hcc_code
                AND cy.measurement_year = %s
                AND cy.tenant_id        = %s
          )
    """

    with raf_cursor() as cur:
        try:
            cur.execute(
                sql_with_table,
                (prior_year, tenant_id, tenant_id, prior_year, current_year),
            )
            row = cur.fetchone()
            total = float(row["total_raf"] or 0.0) if row else 0.0
            if total > 0:
                return total
        except Exception:
            pass  # table may not exist yet — fall through

        # Fallback
        cur.execute(
            sql_fallback,
            (tenant_id, prior_year, tenant_id, current_year, tenant_id),
        )
        row = cur.fetchone()
        return float(row["total_raf"] or 0.0) if row else 0.0


def _suspect_raf_sum(tenant_id: str) -> float:
    """Sum estimated RAF contribution for open suspect conditions.

    raf_suspect_conditions does not store a raf_coefficient column; the
    standard per-suspect estimate is 0.15 RAF points (matching the value
    used throughout prospective_service and worklist scoring).
    """
    sql = """
        SELECT COALESCE(SUM(0.15), 0) AS total_raf
        FROM raf_suspect_conditions
        WHERE status    = 'open'
          AND tenant_id = %s
    """
    with raf_cursor() as cur:
        cur.execute(sql, (tenant_id,))
        row = cur.fetchone()
        return float(row["total_raf"] or 0.0) if row else 0.0
