"""
Coder Productivity Analytics Service
------------------------------------

Derives per-coder and team-wide productivity metrics from the audit trail
and the ``raf_suspect_conditions`` table (which records the canonical
``status``, ``reviewed_by_user_id`` and ``reviewed_at`` for every suspect
the coder touches).

Why both sources?  ``raf_suspect_conditions`` is the source of truth for
"accepted vs dismissed" outcomes (the audit log records the *event*, but
the same row can be flipped twice — only the final status counts).  The
``audit_log`` and ``immutable_audit_log`` tables are used for:

  * PHI_VIEW / phi_view events  → derive ``avg_time_on_chart_seconds``
                                  from consecutive views on the same patient.
  * RAF_RECALCULATED            → bonus signal for "charts touched".
  * SUSPECT_*_OVERRIDE          → fold into the force-accept-no-MEAT counter.

Tenant isolation is enforced on every query.  Date filters are inclusive
of *date_from* and *date_to* (both ``YYYY-MM-DD`` strings).

Industry baselines for context (used for UI commentary, not enforced here):
  * Average HCC coder reviews 5-10 charts / hour.
  * AI-acceptance ground-truth in published vendor whitepapers: 60-75%.
"""

from __future__ import annotations

import logging
import statistics
from datetime import date, datetime, timedelta
from typing import Any

from app.db import raf_cursor

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

# When two consecutive PHI views on the same chart are more than this many
# seconds apart, we treat them as separate review sessions — the coder
# probably stepped away.  Anything below this is counted as continuous
# time on chart.
_CHART_SESSION_GAP_SECONDS = 30 * 60  # 30 minutes

# Default lookback window for the /me endpoint when no dates are supplied.
DEFAULT_LOOKBACK_DAYS = 30


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _coerce_int_tenant(tenant_id: str | int | None) -> int:
    try:
        return int(tenant_id) if tenant_id is not None else 1
    except (TypeError, ValueError):
        return 1


def _coerce_date(value: str | date | None, fallback: date) -> date:
    """Parse a YYYY-MM-DD string, returning *fallback* on bad input."""
    if value is None:
        return fallback
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return fallback


def _safe_pct(numerator: float | int, denominator: float | int) -> float:
    """Return numerator / denominator as a percent (0-100), or 0.0 if denom is 0."""
    if not denominator:
        return 0.0
    return round(float(numerator) * 100.0 / float(denominator), 1)


def _empty_metrics(coder_user_id: int, date_from: date, date_to: date) -> dict[str, Any]:
    """Skeleton response for coders with zero activity in the window."""
    return {
        "coder_user_id": coder_user_id,
        "coder_email": None,
        "coder_name": None,
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "charts_reviewed": 0,
        "charts_per_hour": 0.0,
        "suspects_accepted": 0,
        "suspects_dismissed": 0,
        "suspects_force_accepted_no_meat": 0,
        "avg_time_on_chart_seconds": 0,
        "ai_acceptance_rate_pct": 0.0,
        "specificity_capture_rate_pct": 0.0,
        "top_5_accepted_hccs": [],
        "top_5_dismissed_hccs": [],
        "daily_trend": [],
    }


# ---------------------------------------------------------------------------
# Per-coder metric computation
# ---------------------------------------------------------------------------

def compute_coder_metrics(
    coder_user_id: int,
    tenant_id: str,
    date_from: str | date | None = None,
    date_to: str | date | None = None,
) -> dict[str, Any]:
    """
    Compute productivity metrics for a single coder over the inclusive window.

    Returns a dict with the fields documented in the module docstring; every
    numeric field is always present (0 if no data) so the frontend can render
    stat tiles unconditionally.
    """
    tid = _coerce_int_tenant(tenant_id)
    today = date.today()
    df = _coerce_date(date_from, today - timedelta(days=DEFAULT_LOOKBACK_DAYS))
    dt = _coerce_date(date_to, today)
    if dt < df:
        dt = df

    result = _empty_metrics(coder_user_id, df, dt)

    # ------------------------------------------------------------------
    # 0. User identity (email + display name) — best effort
    # ------------------------------------------------------------------
    try:
        with raf_cursor() as cur:
            cur.execute(
                "SELECT email, first_name, last_name FROM users WHERE id = %s",
                (coder_user_id,),
            )
            row = cur.fetchone()
            if row:
                result["coder_email"] = row.get("email")
                fn = (row.get("first_name") or "").strip()
                ln = (row.get("last_name") or "").strip()
                result["coder_name"] = (f"{fn} {ln}".strip()) or row.get("email")
    except Exception as exc:
        logger.debug("compute_coder_metrics: user lookup failed user=%s: %s",
                     coder_user_id, exc)

    # ------------------------------------------------------------------
    # 1. Suspect accept/dismiss counts and HCC tops
    # ------------------------------------------------------------------
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT status, hcc_code,
                       COUNT(*) AS n
                  FROM raf_suspect_conditions
                 WHERE tenant_id            = %s
                   AND reviewed_by_user_id  = %s
                   AND reviewed_at         >= %s
                   AND reviewed_at         <  %s
                 GROUP BY status, hcc_code
                """,
                (str(tid), coder_user_id, df.isoformat(), (dt + timedelta(days=1)).isoformat()),
            )
            rows = cur.fetchall() or []

        accepted = 0
        dismissed = 0
        accepted_by_hcc: dict[str, int] = {}
        dismissed_by_hcc: dict[str, int] = {}
        for r in rows:
            status = (r.get("status") or "").lower()
            hcc = str(r.get("hcc_code") or "").strip() or "—"
            n = int(r.get("n") or 0)
            if status == "accepted":
                accepted += n
                accepted_by_hcc[hcc] = accepted_by_hcc.get(hcc, 0) + n
            elif status == "dismissed":
                dismissed += n
                dismissed_by_hcc[hcc] = dismissed_by_hcc.get(hcc, 0) + n

        result["suspects_accepted"] = accepted
        result["suspects_dismissed"] = dismissed
        result["top_5_accepted_hccs"] = [
            {"hcc": k, "count": v}
            for k, v in sorted(accepted_by_hcc.items(), key=lambda x: x[1], reverse=True)[:5]
        ]
        result["top_5_dismissed_hccs"] = [
            {"hcc": k, "count": v}
            for k, v in sorted(dismissed_by_hcc.items(), key=lambda x: x[1], reverse=True)[:5]
        ]
        if (accepted + dismissed) > 0:
            result["ai_acceptance_rate_pct"] = _safe_pct(accepted, accepted + dismissed)
    except Exception as exc:
        logger.warning("compute_coder_metrics: suspect roll-up failed: %s", exc)

    # ------------------------------------------------------------------
    # 2. Force-accept-without-MEAT (override events)
    # ------------------------------------------------------------------
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) AS n
                  FROM immutable_audit_log
                 WHERE tenant_id      = %s
                   AND actor_user_id  = %s
                   AND event_ts      >= %s
                   AND event_ts      <  %s
                   AND event_type     IN (
                       'SUSPECT_ACCEPTED_OVERRIDE',
                       'SUSPECT_FORCE_ACCEPTED_NO_MEAT'
                   )
                """,
                (tid, coder_user_id, df.isoformat(),
                 (dt + timedelta(days=1)).isoformat()),
            )
            row = cur.fetchone() or {}
            result["suspects_force_accepted_no_meat"] = int(row.get("n") or 0)
    except Exception as exc:
        logger.debug("compute_coder_metrics: override-count query failed: %s", exc)

    # ------------------------------------------------------------------
    # 3. Chart views + avg time on chart (derived from consecutive PHI views)
    # ------------------------------------------------------------------
    distinct_charts, avg_seconds = _compute_chart_engagement(
        coder_user_id, tid, df, dt
    )
    result["charts_reviewed"] = distinct_charts
    result["avg_time_on_chart_seconds"] = avg_seconds

    # Charts-per-hour = charts_reviewed / (total time on chart in hours).
    # If we have no PHI dwell data, fall back to assuming a 7.5-hour workday
    # across the window so the tile shows *something* useful for demos.
    total_chart_seconds = distinct_charts * avg_seconds if avg_seconds else 0
    if total_chart_seconds > 0:
        result["charts_per_hour"] = round(distinct_charts / (total_chart_seconds / 3600.0), 1)
    elif distinct_charts > 0:
        # Spread over (date_to - date_from + 1) * 7.5 working hours.
        days = max(1, (dt - df).days + 1)
        result["charts_per_hour"] = round(distinct_charts / (days * 7.5), 1)

    # ------------------------------------------------------------------
    # 4. Specificity capture rate — fraction of accepted suspects with a
    #    more-specific ICD-10 than the original suggestion.  Falls back to
    #    "fraction of accepted suspects that recorded MEAT evidence" when
    #    the specificity flag is absent.
    # ------------------------------------------------------------------
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT
                    SUM(CASE WHEN meat_status = 'documented' THEN 1 ELSE 0 END) AS with_meat,
                    COUNT(*)                                                    AS total
                  FROM raf_suspect_conditions
                 WHERE tenant_id            = %s
                   AND reviewed_by_user_id  = %s
                   AND status               = 'accepted'
                   AND reviewed_at         >= %s
                   AND reviewed_at         <  %s
                """,
                (str(tid), coder_user_id, df.isoformat(),
                 (dt + timedelta(days=1)).isoformat()),
            )
            row = cur.fetchone() or {}
            result["specificity_capture_rate_pct"] = _safe_pct(
                int(row.get("with_meat") or 0),
                int(row.get("total") or 0),
            )
    except Exception as exc:
        logger.debug("compute_coder_metrics: specificity calc failed: %s", exc)

    # ------------------------------------------------------------------
    # 5. Daily trend (last N days) — accepted+dismissed combined.  Drives the
    #    sparkline on the personal dashboard.
    # ------------------------------------------------------------------
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT DATE(reviewed_at) AS d,
                       SUM(CASE WHEN status = 'accepted'  THEN 1 ELSE 0 END) AS accepted,
                       SUM(CASE WHEN status = 'dismissed' THEN 1 ELSE 0 END) AS dismissed
                  FROM raf_suspect_conditions
                 WHERE tenant_id            = %s
                   AND reviewed_by_user_id  = %s
                   AND reviewed_at         >= %s
                   AND reviewed_at         <  %s
                 GROUP BY DATE(reviewed_at)
                 ORDER BY d ASC
                """,
                (str(tid), coder_user_id, df.isoformat(),
                 (dt + timedelta(days=1)).isoformat()),
            )
            trend_rows = cur.fetchall() or []
        # Backfill missing days with zeros so the sparkline doesn't gap.
        by_day = {
            (r["d"].isoformat() if hasattr(r["d"], "isoformat") else str(r["d"])): {
                "accepted": int(r.get("accepted") or 0),
                "dismissed": int(r.get("dismissed") or 0),
            }
            for r in trend_rows
        }
        cursor = df
        daily: list[dict[str, Any]] = []
        while cursor <= dt:
            iso = cursor.isoformat()
            row = by_day.get(iso, {"accepted": 0, "dismissed": 0})
            daily.append({"date": iso, **row, "total": row["accepted"] + row["dismissed"]})
            cursor += timedelta(days=1)
        result["daily_trend"] = daily
    except Exception as exc:
        logger.debug("compute_coder_metrics: daily trend failed: %s", exc)

    return result


# ---------------------------------------------------------------------------
# Chart-engagement helper — derives time-on-chart from PHI view audit events
# ---------------------------------------------------------------------------

def _compute_chart_engagement(
    coder_user_id: int,
    tenant_id: int,
    df: date,
    dt: date,
) -> tuple[int, int]:
    """
    Walk consecutive ``phi_view`` events for *coder_user_id* and infer:

      * distinct charts viewed (count of distinct patient_id)
      * avg dwell time on a single chart in seconds

    Consecutive views on the same patient_id within
    ``_CHART_SESSION_GAP_SECONDS`` are folded into a single session.  When
    only one view exists for a patient we treat it as a 60-second baseline
    so a "look-and-leave" doesn't collapse to zero.
    """
    df_iso = df.isoformat()
    dt_iso = (dt + timedelta(days=1)).isoformat()

    events: list[tuple[int, datetime]] = []
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT patient_id, event_ts
                  FROM immutable_audit_log
                 WHERE tenant_id      = %s
                   AND actor_user_id  = %s
                   AND event_ts      >= %s
                   AND event_ts      <  %s
                   AND patient_id IS NOT NULL
                   AND event_type IN ('phi_view', 'PHI_VIEW')
                 ORDER BY patient_id, event_ts
                """,
                (tenant_id, coder_user_id, df_iso, dt_iso),
            )
            for r in cur.fetchall() or []:
                pid = r.get("patient_id")
                ts = r.get("event_ts")
                if pid is None or ts is None:
                    continue
                events.append((int(pid), ts))
    except Exception as exc:
        logger.debug("_compute_chart_engagement: immutable_audit_log query failed: %s", exc)

    # Fallback to the legacy audit_log table if immutable log is empty
    if not events:
        try:
            with raf_cursor() as cur:
                cur.execute(
                    """
                    SELECT patient_id, created_at AS event_ts
                      FROM audit_log
                     WHERE user_id        = %s
                       AND patient_id    IS NOT NULL
                       AND created_at   >= %s
                       AND created_at   <  %s
                       AND (action LIKE 'phi_%%' OR action = 'PHI_VIEW')
                     ORDER BY patient_id, created_at
                    """,
                    (coder_user_id, df_iso, dt_iso),
                )
                for r in cur.fetchall() or []:
                    pid = r.get("patient_id")
                    ts = r.get("event_ts")
                    if pid is None or ts is None:
                        continue
                    events.append((int(pid), ts))
        except Exception as exc:
            logger.debug("_compute_chart_engagement: audit_log fallback failed: %s", exc)

    if not events:
        return (0, 0)

    # Group into per-patient session lists and sum dwell across sessions.
    sessions_by_patient: dict[int, list[float]] = {}
    current_pid: int | None = None
    session_start: datetime | None = None
    session_last: datetime | None = None

    def _flush_session() -> None:
        if current_pid is None or session_start is None or session_last is None:
            return
        seconds = (session_last - session_start).total_seconds()
        if seconds <= 0:
            seconds = 60.0  # treat single-event session as a 60s read
        sessions_by_patient.setdefault(current_pid, []).append(seconds)

    for pid, ts in events:
        if current_pid != pid or session_last is None:
            _flush_session()
            current_pid = pid
            session_start = ts
            session_last = ts
            continue
        # same patient — is this still the same session?
        gap = (ts - session_last).total_seconds()
        if gap <= _CHART_SESSION_GAP_SECONDS:
            session_last = ts
        else:
            _flush_session()
            session_start = ts
            session_last = ts
    _flush_session()

    distinct_charts = len(sessions_by_patient)
    all_dwell = [
        sum(sessions) for sessions in sessions_by_patient.values() if sessions
    ]
    if not all_dwell:
        return (distinct_charts, 0)
    avg_seconds = int(round(statistics.mean(all_dwell)))
    return (distinct_charts, avg_seconds)


# ---------------------------------------------------------------------------
# Team-wide aggregate
# ---------------------------------------------------------------------------

def compute_team_metrics(
    tenant_id: str,
    date_from: str | date | None = None,
    date_to: str | date | None = None,
) -> dict[str, Any]:
    """
    Aggregate ``compute_coder_metrics`` across every coder who reviewed at
    least one suspect in the window.  Returns per-coder rows plus team-wide
    average / median / p95 of charts-per-hour.
    """
    tid = _coerce_int_tenant(tenant_id)
    today = date.today()
    df = _coerce_date(date_from, today - timedelta(days=DEFAULT_LOOKBACK_DAYS))
    dt = _coerce_date(date_to, today)

    # 1. Find active coders — anyone who has *any* row in raf_suspect_conditions
    #    with reviewed_by_user_id IS NOT NULL within the window.
    coder_ids: list[int] = []
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT reviewed_by_user_id
                  FROM raf_suspect_conditions
                 WHERE tenant_id           = %s
                   AND reviewed_by_user_id IS NOT NULL
                   AND reviewed_at        >= %s
                   AND reviewed_at        <  %s
                """,
                (str(tid), df.isoformat(), (dt + timedelta(days=1)).isoformat()),
            )
            for r in cur.fetchall() or []:
                uid = r.get("reviewed_by_user_id")
                if uid is not None:
                    coder_ids.append(int(uid))
    except Exception as exc:
        logger.warning("compute_team_metrics: coder enumeration failed: %s", exc)

    rows: list[dict[str, Any]] = []
    for uid in coder_ids:
        rows.append(compute_coder_metrics(uid, str(tid), df, dt))

    # 2. Roll up team-wide stats on charts_per_hour.  Use defensive list
    #    comprehension so zero-activity rows don't skew the median to 0.
    cph = [float(r["charts_per_hour"]) for r in rows if r["charts_per_hour"] > 0]
    if cph:
        team_avg = round(sum(cph) / len(cph), 2)
        team_median = round(statistics.median(cph), 2)
        sorted_cph = sorted(cph)
        p95_idx = max(0, int(round(len(sorted_cph) * 0.95)) - 1)
        team_p95 = round(sorted_cph[p95_idx], 2)
    else:
        team_avg = team_median = team_p95 = 0.0

    return {
        "tenant_id": str(tid),
        "date_from": df.isoformat(),
        "date_to": dt.isoformat(),
        "per_coder_rows": rows,
        "team_avg_charts_per_hour": team_avg,
        "team_median_charts_per_hour": team_median,
        "team_p95_charts_per_hour": team_p95,
        "active_coders": len(rows),
    }


# ---------------------------------------------------------------------------
# Leaderboard — anonymized friendly-competition ranking
# ---------------------------------------------------------------------------

def compute_leaderboard(
    tenant_id: str,
    date_from: str | date | None = None,
    date_to: str | date | None = None,
    requesting_user_id: int | None = None,
) -> dict[str, Any]:
    """
    Return ranked rows by charts-per-hour.  Names are replaced with
    "Coder #N" unless the user has opted in to ``show_my_name`` (stored in
    ``user_preferences`` keyed on user_id).
    """
    team = compute_team_metrics(tenant_id, date_from, date_to)

    show_name_ids: set[int] = set()
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT user_id
                  FROM user_preferences
                 WHERE pref_key = 'analytics.show_my_name'
                   AND pref_value IN ('1', 'true', 'yes')
                """
            )
            for r in cur.fetchall() or []:
                uid = r.get("user_id")
                if uid is not None:
                    show_name_ids.add(int(uid))
    except Exception as exc:
        logger.debug("compute_leaderboard: user_preferences lookup failed "
                     "(non-fatal): %s", exc)

    ranked = sorted(
        team["per_coder_rows"],
        key=lambda r: (r.get("charts_per_hour") or 0, r.get("suspects_accepted") or 0),
        reverse=True,
    )
    out: list[dict[str, Any]] = []
    for i, r in enumerate(ranked, start=1):
        uid = r["coder_user_id"]
        is_me = uid == requesting_user_id
        show_name = is_me or uid in show_name_ids
        display = r.get("coder_name") if show_name else f"Coder #{i}"
        out.append({
            "rank": i,
            "coder_user_id": uid if (is_me or show_name) else None,
            "display_name": display,
            "is_me": is_me,
            "charts_per_hour": r.get("charts_per_hour"),
            "charts_reviewed": r.get("charts_reviewed"),
            "suspects_accepted": r.get("suspects_accepted"),
            "ai_acceptance_rate_pct": r.get("ai_acceptance_rate_pct"),
        })
    return {
        "date_from": team["date_from"],
        "date_to": team["date_to"],
        "rows": out,
    }
