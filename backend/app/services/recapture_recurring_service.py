"""
Recapture Recurring Gap Service.

A (patient_id, hcc_code) pair that's been an open recapture gap for 2+
consecutive years is a SYSTEMIC issue — the provider isn't capturing it and
the patient isn't getting visits.  These deserve elevated priority and an
auto-suggested AWV.

This module:
  * Detects recurring gaps by scanning the ``recapture_gaps`` table across a
    rolling lookback window.
  * Persists the recurring flag + ``years_recurring`` count back onto the row.
  * Joins to the ``patients`` view to enrich list responses with name/DOB.
  * Suggests an AWV for a gap by reading the existing AWV service —
    READ-ONLY: this service never schedules an AWV itself.

The companion router lives at ``app/routers/recapture_recurring.py``.

Schema dependencies (added by ``database/migrations/add_recurring_flag.sql``)::

    ALTER TABLE recapture_gaps
      ADD COLUMN is_recurring     TINYINT(1) NOT NULL DEFAULT 0,
      ADD COLUMN years_recurring  SMALLINT NULL,
      ADD COLUMN awv_suggested    TINYINT(1) NOT NULL DEFAULT 0,
      ADD COLUMN awv_visit_date   DATE NULL,
      ADD COLUMN awv_encounter_id VARCHAR(64) NULL;
    CREATE INDEX idx_recurring ON recapture_gaps(is_recurring);
"""
# Do NOT use 'from __future__ import annotations' — keep service callable
# from FastAPI without ForwardRef issues if signatures are reflected.

import logging
from datetime import date, datetime, timedelta
from typing import Any, Optional

from app.db import raf_cursor

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_REVENUE_IMPACT_PER_GAP: float = 3000.00  # mirrors recapture_gap_service
_AWV_RECOMMENDED_INTERVAL_DAYS: int = 365


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_tenant_id(tenant_id: Any) -> str:
    """Return the tenant_id as a string, with the app-wide ``1`` fallback."""
    if tenant_id is None:
        return "1"
    return str(tenant_id)


def _format_date(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value) if value is not None else default
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# 1. detect_recurring_gaps
# ---------------------------------------------------------------------------


def detect_recurring_gaps(
    tenant_id: Any,
    current_year: int,
    lookback_years: int = 3,
) -> list[dict[str, Any]]:
    """
    Find (patient_id, hcc_code) pairs where a gap appears in *current_year* AND
    in at least one of the prior ``lookback_years`` years, and persist the
    ``is_recurring`` / ``years_recurring`` flags.

    A "gap appears in year Y" means a row exists in ``recapture_gaps`` with
    ``current_year = Y`` (regardless of resolution status — historical data is
    informative even when a gap was eventually recaptured the following year).

    Args:
        tenant_id:      Tenant scope (numeric or string accepted).
        current_year:   The model year being evaluated for recurrence.
        lookback_years: How many prior years to scan (default 3 ⇒ also check
                        current_year-1, current_year-2, current_year-3).

    Returns:
        A list of recurrence summaries::

            [
              {
                "patient_id": "42",
                "hcc_code":   "85",
                "years_recurring":         3,
                "total_$_at_risk":         9000.00,
                "last_recapture_year_or_null": 2024,
                "recommended_action":      "Schedule AWV (3-year recurring gap)",
              },
              ...
            ]
    """
    tid = _resolve_tenant_id(tenant_id)
    if lookback_years < 1:
        raise ValueError("lookback_years must be >= 1")

    # Pull every gap row for the tenant within the rolling window so we can
    # compute recurrence purely in Python — much easier to reason about than
    # a self-join across N years and avoids over-fetching unrelated rows.
    earliest_year = current_year - lookback_years
    sql = """
        SELECT
            id,
            patient_id,
            hcc_code,
            current_year,
            status,
            revenue_impact
        FROM recapture_gaps
        WHERE tenant_id    = %s
          AND current_year BETWEEN %s AND %s
    """
    with raf_cursor() as cursor:
        cursor.execute(sql, (tid, earliest_year, current_year))
        rows = cursor.fetchall() or []

    # Group by (patient_id, hcc_code) → set of years a gap appeared in
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (str(row["patient_id"]), str(row["hcc_code"]))
        bucket = grouped.setdefault(
            key,
            {
                "years":             set(),
                "ids_in_current":    [],
                "last_recaptured":   None,
                "revenue_impact":    0.0,
            },
        )
        year = _safe_int(row["current_year"])
        bucket["years"].add(year)
        if year == current_year:
            bucket["ids_in_current"].append(_safe_int(row["id"]))
        if str(row["status"]) == "recaptured":
            existing = bucket["last_recaptured"]
            if existing is None or year > existing:
                bucket["last_recaptured"] = year
        # Use the configured per-gap revenue impact from the row when available
        try:
            ri = float(row["revenue_impact"]) if row["revenue_impact"] is not None else _REVENUE_IMPACT_PER_GAP
        except (TypeError, ValueError):
            ri = _REVENUE_IMPACT_PER_GAP
        # We sum revenue once per year the gap appeared
        bucket["revenue_impact"] = ri

    # A pair is "recurring" when it appears in current_year AND in at least
    # one prior year inside the lookback window.
    recurring_summaries: list[dict[str, Any]] = []
    rows_to_flag: list[tuple[int, int, int]] = []  # (id, years_recurring, is_recurring)

    for (patient_id, hcc_code), bucket in grouped.items():
        years: set[int] = bucket["years"]
        if current_year not in years:
            continue
        # Need at least ONE prior year inside the window to qualify
        prior_in_window = {y for y in years if y < current_year and y >= earliest_year}
        if not prior_in_window:
            continue

        years_recurring = len(years)  # count of distinct years gap was open
        revenue = bucket["revenue_impact"] * years_recurring
        recommended = (
            f"Schedule AWV ({years_recurring}-year recurring gap)"
            if years_recurring >= 2
            else "Review patient outreach plan"
        )
        recurring_summaries.append({
            "patient_id":                  patient_id,
            "hcc_code":                    hcc_code,
            "years_recurring":             years_recurring,
            "total_$_at_risk":             round(revenue, 2),
            "last_recapture_year_or_null": bucket["last_recaptured"],
            "recommended_action":          recommended,
        })
        for gap_id in bucket["ids_in_current"]:
            rows_to_flag.append((gap_id, years_recurring, 1))

    # Persist the is_recurring + years_recurring flags
    if rows_to_flag:
        update_sql = """
            UPDATE recapture_gaps
               SET is_recurring    = %s,
                   years_recurring = %s
             WHERE id              = %s
               AND tenant_id       = %s
        """
        with raf_cursor() as cursor:
            cursor.executemany(
                update_sql,
                [(is_rec, yr, gid, tid) for (gid, yr, is_rec) in rows_to_flag],
            )

    logger.info(
        "detect_recurring_gaps tenant=%s current_year=%s lookback=%s "
        "matches=%d rows_flagged=%d",
        tid, current_year, lookback_years, len(recurring_summaries), len(rows_to_flag),
    )
    return recurring_summaries


# ---------------------------------------------------------------------------
# 2. get_recurring_gaps
# ---------------------------------------------------------------------------


def get_recurring_gaps(tenant_id: Any, year: int) -> list[dict[str, Any]]:
    """
    Return all currently-flagged recurring gaps for *year* with patient context.

    Joins to the ``patients`` compatibility view for first/last name + DOB.

    Args:
        tenant_id: Tenant scope.
        year:      Model year (matches recapture_gaps.current_year).

    Returns:
        List of enriched gap dicts (patient name + DOB + years_recurring etc.)
    """
    tid = _resolve_tenant_id(tenant_id)
    sql = """
        SELECT
            rg.id,
            rg.patient_id,
            rg.tenant_id,
            rg.hcc_code,
            rg.icd10_code,
            rg.prior_year,
            rg.current_year,
            rg.status,
            rg.last_encounter_date,
            rg.provider_npi,
            rg.revenue_impact,
            rg.is_recurring,
            rg.years_recurring,
            rg.awv_suggested,
            rg.awv_visit_date,
            rg.awv_encounter_id,
            rg.created_at,
            rg.updated_at,
            CONCAT(COALESCE(pt.first_name,''), ' ', COALESCE(pt.last_name,'')) AS patient_name,
            pt.first_name,
            pt.last_name,
            pt.dob
        FROM recapture_gaps rg
        LEFT JOIN patients pt
               ON pt.id        = rg.patient_id
              AND pt.tenant_id = rg.tenant_id
        WHERE rg.tenant_id    = %s
          AND rg.current_year = %s
          AND rg.is_recurring = 1
        ORDER BY rg.years_recurring DESC, rg.revenue_impact DESC, rg.id DESC
    """
    with raf_cursor() as cursor:
        cursor.execute(sql, (tid, year))
        rows = cursor.fetchall() or []

    result: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["patient_name"] = (item.get("patient_name") or "").strip() or "Unknown"
        for key in ("last_encounter_date", "dob", "created_at", "updated_at", "awv_visit_date"):
            if key in item:
                item[key] = _format_date(item[key])
        item["is_recurring"] = bool(item.get("is_recurring"))
        item["awv_suggested"] = bool(item.get("awv_suggested"))
        if item.get("revenue_impact") is not None:
            try:
                item["revenue_impact"] = float(item["revenue_impact"])
            except (TypeError, ValueError):
                item["revenue_impact"] = 0.0
        result.append(item)
    return result


# ---------------------------------------------------------------------------
# 3. suggest_awv_for_gap
# ---------------------------------------------------------------------------


def suggest_awv_for_gap(gap_id: int) -> dict[str, Any]:
    """
    READ-ONLY AWV recommendation for a recurring gap.

    Looks up the gap's patient, asks the existing AWV service whether the
    patient is currently AWV-eligible, and computes a suggested visit date.
    Does NOT call any scheduling endpoint.

    Args:
        gap_id: Primary key of the recapture_gaps row.

    Returns:
        {
            "gap_id":               int,
            "patient_id":           int,
            "eligible":             bool,
            "last_awv_date":        ISO date | None,
            "days_since":           int | None,
            "recommended_provider_id": int | None,
            "suggested_visit_date":   ISO date,
            "reason":               human-readable explanation,
        }

    Raises:
        ValueError: When the gap_id is not found.
    """
    # Look up the gap row
    with raf_cursor() as cursor:
        cursor.execute(
            """
            SELECT id, patient_id, tenant_id, hcc_code, current_year,
                   provider_npi, awv_suggested
            FROM recapture_gaps
            WHERE id = %s
            """,
            (gap_id,),
        )
        gap = cursor.fetchone()

    if not gap:
        raise ValueError(f"recapture_gaps row id={gap_id} not found")

    tenant_id = str(gap["tenant_id"])
    patient_id = _safe_int(gap["patient_id"])
    schedule_year = _safe_int(gap["current_year"]) or date.today().year

    # Pull AWV-eligible patient list and check for our patient.  We delegate
    # the eligibility logic to the existing service — we never compute it
    # ourselves and we never write any AWV row.
    eligible = False
    last_awv_date: Optional[str] = None
    days_since: Optional[int] = None
    recommended_provider_id: Optional[int] = None

    try:
        from app.services import awv_service

        elig_payload = awv_service.get_eligible_patients(tenant_id=tenant_id, year=schedule_year)
        for entry in elig_payload.get("patients", []) or []:
            if _safe_int(entry.get("patient_id")) == patient_id:
                eligible = True
                last_awv_date = entry.get("last_encounter_date")
                days_since = _safe_int(entry.get("days_since_last_visit"), default=None) \
                    if entry.get("days_since_last_visit") is not None else None
                recommended_provider_id = entry.get("provider_id")
                break
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning("suggest_awv_for_gap: AWV eligibility lookup failed: %s", exc)

    # Suggested visit date: today + 14 days when eligible, else 365 days from
    # last encounter (safe default for non-eligible patients).
    today = date.today()
    if eligible:
        suggested_dt = today + timedelta(days=14)
        reason = "Patient is AWV-eligible — recommend visit within two weeks."
    elif last_awv_date:
        try:
            base = datetime.fromisoformat(str(last_awv_date)).date()
            suggested_dt = base + timedelta(days=_AWV_RECOMMENDED_INTERVAL_DAYS)
            if suggested_dt < today:
                suggested_dt = today + timedelta(days=14)
            reason = "Patient not currently AWV-eligible — suggested date based on annual interval."
        except ValueError:
            suggested_dt = today + timedelta(days=30)
            reason = "Patient eligibility unknown — suggested follow-up in 30 days."
    else:
        suggested_dt = today + timedelta(days=30)
        reason = "No AWV history found — suggest a wellness visit within 30 days."

    return {
        "gap_id":                   gap_id,
        "patient_id":               patient_id,
        "tenant_id":                tenant_id,
        "hcc_code":                 str(gap["hcc_code"]),
        "schedule_year":            schedule_year,
        "eligible":                 eligible,
        "last_awv_date":            last_awv_date,
        "days_since":               days_since,
        "recommended_provider_id":  recommended_provider_id,
        "suggested_visit_date":     suggested_dt.isoformat(),
        "already_marked_scheduled": bool(gap.get("awv_suggested")),
        "reason":                   reason,
    }


# ---------------------------------------------------------------------------
# 4. mark_awv_scheduled — metadata only, never calls AWV scheduling
# ---------------------------------------------------------------------------


def mark_awv_scheduled(
    gap_id: int,
    visit_date: str,
    encounter_id: Optional[str] = None,
) -> dict[str, Any]:
    """
    Record that an AWV has been scheduled for a recurring gap.  Sets
    ``awv_suggested = 1`` plus optional metadata.  Does NOT create an
    awv_schedules row — that is the EHR's job.

    Args:
        gap_id:       recapture_gaps.id
        visit_date:   ISO date the AWV was booked for
        encounter_id: Optional EHR encounter / appointment ID

    Returns:
        Dict with ``gap_id``, ``awv_suggested``, ``awv_visit_date``,
        ``awv_encounter_id`` after the update.

    Raises:
        ValueError: When the gap row does not exist.
    """
    # Validate the gap exists first so we can return a 404-style error from
    # the router.
    with raf_cursor() as cursor:
        cursor.execute(
            "SELECT id, tenant_id FROM recapture_gaps WHERE id = %s",
            (gap_id,),
        )
        row = cursor.fetchone()
    if not row:
        raise ValueError(f"recapture_gaps row id={gap_id} not found")

    update_sql = """
        UPDATE recapture_gaps
           SET awv_suggested    = 1,
               awv_visit_date   = %s,
               awv_encounter_id = %s
         WHERE id = %s
    """
    with raf_cursor() as cursor:
        cursor.execute(update_sql, (visit_date, encounter_id, gap_id))

    logger.info(
        "mark_awv_scheduled: gap_id=%s visit_date=%s encounter_id=%s",
        gap_id, visit_date, encounter_id,
    )
    return {
        "gap_id":           gap_id,
        "awv_suggested":    True,
        "awv_visit_date":   visit_date,
        "awv_encounter_id": encounter_id,
    }
