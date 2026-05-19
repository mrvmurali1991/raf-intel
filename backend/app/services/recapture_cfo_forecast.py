"""
recapture_cfo_forecast — Executive ($) reporting layer for the recapture program.

This service does NOT modify any underlying recapture detection logic.  It only
*aggregates* the rows persisted by ``recapture_gap_service.detect_and_persist_gaps``
into the shape a CFO cares about:

    - $ at risk by quarter / month
    - YTD $ recaptured + closure velocity
    - Linear projection of YE $ recaptured vs. budget
    - Top 3 conditions (recaptured + at risk) and provider contributors
    - Audit-risk flag (dual-coded share of total)
    - YoY trend across recent measurement years
    - Flat row export for BI tools

Design notes
------------
*   Money figures derive from the persisted ``revenue_impact`` column when
    available; if not (e.g. legacy zero rows), we fall back to
    ``_REVENUE_IMPACT_PER_GAP`` imported from ``recapture_gap_service`` so the
    constant lives in exactly one place per the project rules.
*   Linear forecast is intentionally simple — YTD $ ÷ days_elapsed × days_in_year.
*   ``tenant_id`` is normalised the same way as elsewhere in the codebase
    (``int(tenant_id) if tenant_id is not None else 1``) so this module behaves
    on the single-tenant prod schema as well as multi-tenant fixtures.
"""

from __future__ import annotations

import csv
import io
import json
import logging
from calendar import isleap
from datetime import date, datetime, timezone
from typing import Any

from app.db import raf_cursor
from app.services.recapture_gap_service import _REVENUE_IMPACT_PER_GAP

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _coerce_tenant(tenant_id: int | str | None) -> str:
    """Mirror tenant fallback used by sibling services (``int(tid) or 1``)."""
    tid = int(tenant_id) if tenant_id is not None else 1
    return str(tid)


def _days_in_year(year: int) -> int:
    return 366 if isleap(year) else 365


def _days_elapsed(year: int, today: date | None = None) -> int:
    """Days elapsed from Jan 1 (inclusive) of *year* up to *today*.

    Returns 0 for future years and a full year for past years (so the
    forecast engine yields a sane number even when the table is back-filled).
    """
    today = today or date.today()
    if today.year < year:
        return 0
    if today.year > year:
        return _days_in_year(year)
    # Same year — Jan 1st is day 1, Dec 31st is day 365/366.
    start = date(year, 1, 1)
    return (today - start).days + 1


def _safe_float(v: Any) -> float:
    try:
        return float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _safe_int(v: Any) -> int:
    try:
        return int(v) if v is not None else 0
    except (TypeError, ValueError):
        return 0


def _amount(row: dict[str, Any]) -> float:
    """Pick revenue_impact when populated, else fall back to the per-gap base."""
    raw = row.get("revenue_impact")
    val = _safe_float(raw)
    return val if val > 0 else float(_REVENUE_IMPACT_PER_GAP)


def _hcc_label(hcc_code: str) -> str:
    """Lazy import of ``_hcc_description`` (kept private in sibling module)."""
    try:
        from app.services.recapture_gap_service import _hcc_description
        return _hcc_description(str(hcc_code))
    except Exception:
        return f"HCC {hcc_code}"


# ---------------------------------------------------------------------------
# Core: load all gap rows for a measurement year
# ---------------------------------------------------------------------------


def _fetch_gap_rows(tenant_id: str, year: int) -> list[dict[str, Any]]:
    """Return every recapture_gaps row for *(tenant, current_year=year)*.

    Includes open + recaptured + dismissed; callers filter by status.

    DEFENSIVE: columns current_year, prior_year, revenue_impact, resolved_at,
    resolved_by, provider_npi may not exist on instances running the legacy
    migration schema (add_recapture_ai_suggestions.sql). On any DB error this
    function returns an empty list so callers produce zero-filled dashboards
    rather than 500 errors.
    """
    sql = """
        SELECT
            id,
            patient_id,
            tenant_id,
            hcc_code,
            icd10_code,
            prior_year,
            current_year,
            status,
            last_encounter_date,
            provider_npi,
            revenue_impact,
            resolved_at,
            resolved_by,
            created_at,
            updated_at
        FROM recapture_gaps
        WHERE tenant_id    = %s
          AND current_year = %s
    """
    try:
        with raf_cursor() as cursor:
            cursor.execute(sql, (tenant_id, year))
            return list(cursor.fetchall() or [])
    except Exception as _db_exc:
        logger.error(
            "_fetch_gap_rows: DB error tenant=%s year=%s — returning empty; %s",
            tenant_id, year, _db_exc, exc_info=True,
        )
        return []


# ---------------------------------------------------------------------------
# 1. get_executive_summary
# ---------------------------------------------------------------------------


def get_executive_summary(
    tenant_id: int | str | None,
    year: int,
    today: date | None = None,
) -> dict[str, Any]:
    """Build the full CFO-facing dashboard payload for *(tenant, year)*.

    See module docstring for the contract.  ``today`` is overridable to make
    the linear-extrapolation math deterministic in tests.
    """
    tid = _coerce_tenant(tenant_id)
    rows = _fetch_gap_rows(tid, year)
    today = today or date.today()

    # ----- bucket counts --------------------------------------------------
    open_rows: list[dict[str, Any]] = []
    closed_rows: list[dict[str, Any]] = []
    dismissed_rows: list[dict[str, Any]] = []
    for r in rows:
        status = (r.get("status") or "").lower()
        if status == "open":
            open_rows.append(r)
        elif status == "recaptured":
            closed_rows.append(r)
        elif status == "dismissed":
            dismissed_rows.append(r)

    total_open = len(open_rows)
    total_closed = len(closed_rows)
    total_dismissed = len(dismissed_rows)

    total_at_risk = round(sum(_amount(r) for r in open_rows), 2)
    ytd_recaptured = round(sum(_amount(r) for r in closed_rows), 2)

    # ----- velocity / forecast -------------------------------------------
    days_elapsed = _days_elapsed(year, today)
    days_in_year = _days_in_year(year)
    if days_elapsed > 0:
        velocity = ytd_recaptured / days_elapsed
        forecast_ye = round(velocity * days_in_year, 2)
    else:
        velocity = 0.0
        forecast_ye = 0.0
    velocity = round(velocity, 2)

    # Budget = full pipeline value (open + closed) at the standard per-gap rate
    budget = round((total_open + total_closed) * float(_REVENUE_IMPACT_PER_GAP), 2)
    variance = round(forecast_ye - budget, 2)

    # ----- monthly + quarterly breakdown ---------------------------------
    months: list[dict[str, Any]] = [
        {"month": m, "opened": 0, "closed": 0, "recaptured_dollars": 0.0, "remaining_dollars": 0.0}
        for m in range(1, 13)
    ]

    for r in rows:
        amt = _amount(r)
        ca = r.get("created_at")
        if isinstance(ca, datetime) and ca.year == year:
            months[ca.month - 1]["opened"] += 1
            if (r.get("status") or "").lower() == "open":
                months[ca.month - 1]["remaining_dollars"] += amt

        ra = r.get("resolved_at")
        if (
            (r.get("status") or "").lower() == "recaptured"
            and isinstance(ra, datetime)
            and ra.year == year
        ):
            months[ra.month - 1]["closed"] += 1
            months[ra.month - 1]["recaptured_dollars"] += amt

    # round dollars for clean JSON
    for m in months:
        m["recaptured_dollars"] = round(m["recaptured_dollars"], 2)
        m["remaining_dollars"] = round(m["remaining_dollars"], 2)

    quarters: list[dict[str, Any]] = []
    for q_idx in range(4):
        chunk = months[q_idx * 3 : q_idx * 3 + 3]
        quarters.append(
            {
                "quarter": f"Q{q_idx + 1}",
                "opened": sum(m["opened"] for m in chunk),
                "closed": sum(m["closed"] for m in chunk),
                "recaptured_dollars": round(sum(m["recaptured_dollars"] for m in chunk), 2),
                "remaining_dollars": round(sum(m["remaining_dollars"] for m in chunk), 2),
            }
        )

    # ----- top 3 conditions / providers ----------------------------------
    by_hcc_recap: dict[str, dict[str, Any]] = {}
    by_hcc_risk: dict[str, dict[str, Any]] = {}
    by_provider: dict[str, dict[str, Any]] = {}

    for r in closed_rows:
        code = str(r.get("hcc_code") or "")
        slot = by_hcc_recap.setdefault(
            code,
            {"hcc_code": code, "description": _hcc_label(code), "count": 0, "dollars": 0.0},
        )
        slot["count"] += 1
        slot["dollars"] += _amount(r)

        npi = r.get("provider_npi") or "unassigned"
        pslot = by_provider.setdefault(
            npi, {"provider_npi": npi, "recaptured_count": 0, "recaptured_dollars": 0.0}
        )
        pslot["recaptured_count"] += 1
        pslot["recaptured_dollars"] += _amount(r)

    for r in open_rows:
        code = str(r.get("hcc_code") or "")
        slot = by_hcc_risk.setdefault(
            code,
            {"hcc_code": code, "description": _hcc_label(code), "count": 0, "dollars": 0.0},
        )
        slot["count"] += 1
        slot["dollars"] += _amount(r)

    def _top3(d: dict[str, dict[str, Any]], key: str) -> list[dict[str, Any]]:
        items = sorted(d.values(), key=lambda x: x.get(key, 0), reverse=True)[:3]
        for it in items:
            if "dollars" in it:
                it["dollars"] = round(it["dollars"], 2)
            if "recaptured_dollars" in it:
                it["recaptured_dollars"] = round(it["recaptured_dollars"], 2)
        return items

    top_recap = _top3(by_hcc_recap, "dollars")
    top_risk = _top3(by_hcc_risk, "dollars")
    top_providers = _top3(by_provider, "recaptured_dollars")

    # ----- audit risk flag -----------------------------------------------
    # Heuristic: flag when "dual-coded" gaps (i.e. those with both an ICD-10
    # and an HCC code populated) make up < 10 % of the total population.
    # A low share suggests provider documentation is leaning on a single
    # code source which raises RADV-style audit exposure.
    dual_coded = sum(
        1 for r in rows
        if str(r.get("icd10_code") or "").strip()
        and str(r.get("hcc_code") or "").strip()
    )
    total_rows = len(rows)
    audit_risk_flag = False
    if total_rows > 0:
        audit_risk_flag = (dual_coded / total_rows) < 0.10

    return {
        "year": year,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_gaps_open": total_open,
        "total_dollars_at_risk": total_at_risk,
        "ytd_dollars_recaptured": ytd_recaptured,
        "ytd_closures": total_closed,
        "ytd_velocity_per_day": velocity,
        "budget_dollars": budget,
        "forecast_ye_dollars": forecast_ye,
        "variance_to_budget": variance,
        "month_breakdown": months,
        "quarter_breakdown": quarters,
        "top_3_recaptured_conditions": top_recap,
        "top_3_at_risk_conditions": top_risk,
        "top_3_provider_contributors": top_providers,
        "audit_risk_flag": audit_risk_flag,
        "audit_dual_coded_pct": round(
            (dual_coded / total_rows) * 100 if total_rows else 0.0, 2
        ),
        "totals": {
            "rows": total_rows,
            "open": total_open,
            "recaptured": total_closed,
            "dismissed": total_dismissed,
            "dual_coded": dual_coded,
        },
        "days_elapsed": days_elapsed,
        "days_in_year": days_in_year,
    }


# ---------------------------------------------------------------------------
# 2. get_year_over_year_trend
# ---------------------------------------------------------------------------


def get_year_over_year_trend(
    tenant_id: int | str | None,
    years_back: int = 3,
    today: date | None = None,
) -> dict[str, Any]:
    """Return per-year comparison rows for the trailing *years_back* years."""
    tid = _coerce_tenant(tenant_id)
    today = today or date.today()
    current_year = today.year

    years = list(range(current_year - years_back + 1, current_year + 1))
    series: list[dict[str, Any]] = []

    for y in years:
        rows = _fetch_gap_rows(tid, y)
        opened = len(rows)
        closed = sum(1 for r in rows if (r.get("status") or "").lower() == "recaptured")
        recap_dollars = round(
            sum(_amount(r) for r in rows if (r.get("status") or "").lower() == "recaptured"),
            2,
        )
        risk_dollars = round(
            sum(_amount(r) for r in rows if (r.get("status") or "").lower() == "open"), 2
        )
        rate = round((closed / opened) * 100, 2) if opened else 0.0
        series.append(
            {
                "year": y,
                "opened": opened,
                "closed": closed,
                "recaptured_dollars": recap_dollars,
                "at_risk_dollars": risk_dollars,
                "closure_rate_pct": rate,
            }
        )

    return {"tenant_id": tid, "years_back": years_back, "series": series}


# ---------------------------------------------------------------------------
# 3. export_for_bi
# ---------------------------------------------------------------------------


_CSV_HEADERS = [
    "year",
    "month",
    "opened",
    "closed",
    "recaptured_$",
    "remaining_$",
]


def export_for_bi(
    tenant_id: int | str | None,
    year: int,
    format: str = "csv",
    today: date | None = None,
) -> tuple[str, str]:
    """Flatten the executive summary into a tabular row-per-month export.

    Returns a ``(content, mime_type)`` tuple.  ``format`` accepts ``"csv"``
    (default) or ``"json"``.
    """
    fmt = (format or "csv").lower()
    summary = get_executive_summary(tenant_id, year, today=today)
    rows = [
        {
            "year": year,
            "month": m["month"],
            "opened": m["opened"],
            "closed": m["closed"],
            "recaptured_$": m["recaptured_dollars"],
            "remaining_$": m["remaining_dollars"],
        }
        for m in summary["month_breakdown"]
    ]

    if fmt == "json":
        return json.dumps(rows, separators=(",", ":")), "application/json"

    if fmt != "csv":
        raise ValueError(f"Unsupported export format '{format}'. Use 'csv' or 'json'.")

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=_CSV_HEADERS)
    writer.writeheader()
    for r in rows:
        writer.writerow(r)
    return buf.getvalue(), "text/csv"
