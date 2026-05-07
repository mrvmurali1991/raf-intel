"""
Recapture Bonus / Coder Incentive Service.

Plans that bonus EARLY-year recapture closure see meaningfully higher
recapture rates. This module powers the gamification surface:

* per-tenant bonus configuration (flat $ per closure + month multiplier curve)
* per-coder year-to-date earnings + at-risk preview
* tenant leaderboard
* "close THIS gap right now → +$X" preview for individual gaps

Storage
-------
Configuration lives in ``recapture_bonus_config`` (one row per tenant —
see ``database/migrations/add_recapture_bonus_config.sql``). Closure
events are derived from ``recapture_gaps.resolved_at / resolved_by``;
no separate ledger table is required.

Tenant convention
-----------------
``tid = int(tenant_id) if tenant_id is not None else 1`` is used in
caller services; this module accepts the str form everywhere because
``recapture_gaps.tenant_id`` and ``recapture_bonus_config.tenant_id``
are both ``VARCHAR(64)``.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from typing import Any

from app.db import raf_cursor

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Defaults — exported so tests and the API can assert against them.
# ---------------------------------------------------------------------------

#: Flat $ per closed recapture gap before applying the month multiplier.
DEFAULT_BONUS_PER_CLOSURE: float = 25.00

#: Month-of-year multiplier curve. January closures earn 2x, December
#: closures earn 0.3x. The curve is intentionally steep so the UI banner
#: ("close now — drops to 0.9x in 25 days") creates urgency.
DEFAULT_MONTH_MULTIPLIERS: dict[int, float] = {
    1: 2.0,
    2: 1.8,
    3: 1.5,
    4: 1.2,
    5: 1.0,
    6: 1.0,
    7: 0.9,
    8: 0.8,
    9: 0.7,
    10: 0.6,
    11: 0.5,
    12: 0.3,
}

#: Allowed admin-mutable fields on the config row.
_UPDATABLE_FIELDS = {"bonus_per_closure_default", "month_multipliers", "active"}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _normalise_multipliers(raw: Any) -> dict[int, float]:
    """
    Coerce a stored multiplier blob (JSON string, dict with str keys, or
    already-typed dict) into ``{int month: float multiplier}``.

    Falls back to :data:`DEFAULT_MONTH_MULTIPLIERS` on any parse failure
    so a corrupt row never blocks earnings calculation.
    """
    if raw is None or raw == "":
        return dict(DEFAULT_MONTH_MULTIPLIERS)

    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError) as exc:
            logger.warning("recapture_bonus: failed to parse multipliers JSON: %s", exc)
            return dict(DEFAULT_MONTH_MULTIPLIERS)

    if not isinstance(raw, dict):
        return dict(DEFAULT_MONTH_MULTIPLIERS)

    out: dict[int, float] = {}
    for k, v in raw.items():
        try:
            month = int(k)
            mult = float(v)
        except (TypeError, ValueError):
            continue
        if 1 <= month <= 12:
            out[month] = mult

    # Backfill any missing months from defaults so downstream code can
    # safely index out[month] without a KeyError check.
    for month, default_mult in DEFAULT_MONTH_MULTIPLIERS.items():
        out.setdefault(month, default_mult)
    return out


def _row_to_config(row: dict[str, Any]) -> dict[str, Any]:
    """Convert a raw DB row into the API-facing config dict."""
    return {
        "id": int(row["id"]),
        "tenant_id": str(row["tenant_id"]),
        "bonus_per_closure_default": float(row["bonus_per_closure_default"] or 0.0),
        "month_multipliers": _normalise_multipliers(row.get("month_multipliers")),
        "active": bool(int(row.get("active") or 0)),
        "created_at": _iso(row.get("created_at")),
        "updated_at": _iso(row.get("updated_at")),
    }


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


# ---------------------------------------------------------------------------
# 1. Configuration management
# ---------------------------------------------------------------------------

def _ephemeral_config(tenant_id: str) -> dict[str, Any]:
    """Return an in-memory default config when the DB table is unavailable."""
    return {
        "id": 0,
        "tenant_id": str(tenant_id),
        "bonus_per_closure_default": DEFAULT_BONUS_PER_CLOSURE,
        "month_multipliers": dict(DEFAULT_MONTH_MULTIPLIERS),
        "active": True,
        "created_at": None,
        "updated_at": None,
    }


def get_or_create_config(tenant_id: str) -> dict[str, Any]:
    """
    Return the bonus configuration for ``tenant_id``, seeding a default
    row when one does not yet exist.

    Sensible defaults (see :data:`DEFAULT_BONUS_PER_CLOSURE` and
    :data:`DEFAULT_MONTH_MULTIPLIERS`) mean an admin never has to touch
    this table before the UI works for the first time.

    DEFENSIVE: if the ``recapture_bonus_config`` table does not yet exist
    (migration not applied), return an ephemeral in-memory config so the
    leaderboard and other endpoints return 200 with defaults rather than 500.
    """
    select_sql = """
        SELECT id, tenant_id, bonus_per_closure_default, month_multipliers,
               active, created_at, updated_at
        FROM recapture_bonus_config
        WHERE tenant_id = %s
    """
    insert_sql = """
        INSERT INTO recapture_bonus_config
            (tenant_id, bonus_per_closure_default, month_multipliers, active)
        VALUES (%s, %s, %s, 1)
    """

    try:
        with raf_cursor() as cursor:
            cursor.execute(select_sql, (str(tenant_id),))
            row = cursor.fetchone()
            if row:
                return _row_to_config(row)

            # Seed default
            cursor.execute(
                insert_sql,
                (
                    str(tenant_id),
                    DEFAULT_BONUS_PER_CLOSURE,
                    json.dumps({str(k): v for k, v in DEFAULT_MONTH_MULTIPLIERS.items()}),
                ),
            )
            cursor.execute(select_sql, (str(tenant_id),))
            row = cursor.fetchone()
    except Exception as _db_exc:
        logger.error(
            "recapture_bonus: get_or_create_config DB error tenant=%s — "
            "returning ephemeral default; %s",
            tenant_id, _db_exc, exc_info=True,
        )
        return _ephemeral_config(tenant_id)

    if not row:
        # Should not happen but guard against pool weirdness — synthesise
        # an in-memory config so the API still returns something usable.
        logger.error(
            "recapture_bonus: insert+reselect returned no row for tenant=%s — "
            "returning ephemeral default",
            tenant_id,
        )
        return _ephemeral_config(tenant_id)
    return _row_to_config(row)


def update_config(tenant_id: str, **fields: Any) -> dict[str, Any]:
    """
    Patch the per-tenant bonus configuration.

    Accepted keys: ``bonus_per_closure_default``, ``month_multipliers``,
    ``active``. Unknown keys are silently dropped (admin UIs may send
    extra fields). The row is created on demand via
    :func:`get_or_create_config`.

    Returns the updated config dict.
    """
    # Ensure the row exists before we attempt to UPDATE it.
    get_or_create_config(tenant_id)

    sets: list[str] = []
    params: list[Any] = []

    if "bonus_per_closure_default" in fields:
        try:
            v = float(fields["bonus_per_closure_default"])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"bonus_per_closure_default must be numeric: {exc}")
        if v < 0:
            raise ValueError("bonus_per_closure_default must be >= 0")
        sets.append("bonus_per_closure_default = %s")
        params.append(v)

    if "month_multipliers" in fields:
        mults = _normalise_multipliers(fields["month_multipliers"])
        sets.append("month_multipliers = %s")
        params.append(json.dumps({str(k): v for k, v in mults.items()}))

    if "active" in fields:
        sets.append("active = %s")
        params.append(1 if fields["active"] else 0)

    # Reject calls that touch nothing — surfacing this as a no-op rather
    # than silently succeeding makes admin debugging easier.
    unknown = set(fields) - _UPDATABLE_FIELDS
    if unknown:
        logger.info("recapture_bonus.update_config ignored unknown fields: %s", unknown)

    if not sets:
        return get_or_create_config(tenant_id)

    sql = f"UPDATE recapture_bonus_config SET {', '.join(sets)} WHERE tenant_id = %s"
    params.append(str(tenant_id))

    with raf_cursor() as cursor:
        cursor.execute(sql, params)

    return get_or_create_config(tenant_id)


# ---------------------------------------------------------------------------
# 2. Multiplier helpers
# ---------------------------------------------------------------------------

def current_month_multiplier(tenant_id: str, *, today: date | None = None) -> dict[str, Any]:
    """
    Quick lookup for the multiplier banner.

    Returns::

        {
            "month": int,            # 1..12
            "multiplier": float,
            "next_month": int,       # 1..12 (wraps from Dec → Jan)
            "next_multiplier": float,
            "delta": float,          # next - current; negative = "drops"
            "days_until_next_month": int,
        }
    """
    config = get_or_create_config(tenant_id)
    mults = config["month_multipliers"]

    today = today or datetime.now(timezone.utc).date()
    month = today.month
    next_month = 1 if month == 12 else month + 1

    # Days until the 1st of next month (always >= 1, <= 31).
    if next_month == 1:
        next_first = date(today.year + 1, 1, 1)
    else:
        next_first = date(today.year, next_month, 1)
    days_until_next = max(1, (next_first - today).days)

    cur_mult = float(mults.get(month, DEFAULT_MONTH_MULTIPLIERS[month]))
    nxt_mult = float(mults.get(next_month, DEFAULT_MONTH_MULTIPLIERS[next_month]))

    return {
        "month": month,
        "multiplier": cur_mult,
        "next_month": next_month,
        "next_multiplier": nxt_mult,
        "delta": round(nxt_mult - cur_mult, 4),
        "days_until_next_month": days_until_next,
    }


def bonus_for_closing_now(tenant_id: str, gap_id: int) -> dict[str, Any]:
    """
    Return the bonus a coder would earn by closing ``gap_id`` *right now*.

    Returns::

        {
            "gap_id": int,
            "bonus": float,
            "base_bonus": float,
            "month": int,
            "multiplier": float,
            "eligible": bool,         # False when gap is already closed or wrong tenant
            "reason": str | None,
        }
    """
    config = get_or_create_config(tenant_id)
    base = float(config["bonus_per_closure_default"])
    cm = current_month_multiplier(tenant_id)

    sql = "SELECT id, status, tenant_id FROM recapture_gaps WHERE id = %s AND tenant_id = %s"
    with raf_cursor() as cursor:
        cursor.execute(sql, (int(gap_id), str(tenant_id)))
        row = cursor.fetchone()

    if not row:
        return {
            "gap_id": int(gap_id),
            "bonus": 0.0,
            "base_bonus": base,
            "month": cm["month"],
            "multiplier": cm["multiplier"],
            "eligible": False,
            "reason": "gap not found for this tenant",
        }

    status = (row.get("status") or "").lower()
    if status != "open":
        return {
            "gap_id": int(gap_id),
            "bonus": 0.0,
            "base_bonus": base,
            "month": cm["month"],
            "multiplier": cm["multiplier"],
            "eligible": False,
            "reason": f"gap already {status}",
        }

    bonus = round(base * cm["multiplier"], 2)
    return {
        "gap_id": int(gap_id),
        "bonus": bonus,
        "base_bonus": base,
        "month": cm["month"],
        "multiplier": cm["multiplier"],
        "eligible": True,
        "reason": None,
    }


# ---------------------------------------------------------------------------
# 3. Coder earnings
# ---------------------------------------------------------------------------

def _coder_filter(coder_id: int) -> tuple[str, list[Any]]:
    """
    Build the WHERE-clause snippet that matches gaps resolved by this coder.

    ``recapture_gaps.resolved_by`` is a ``VARCHAR`` (we use it for both
    user-id strings and email/usernames depending on caller). To keep the
    coder-id mapping flexible we match the numeric id, the email, and the
    full_name from the ``users`` table.
    """
    return (
        """rg.resolved_by IN (
              SELECT CAST(u.id AS CHAR) FROM users u WHERE u.id = %s
              UNION SELECT u.email     FROM users u WHERE u.id = %s
              UNION SELECT u.full_name FROM users u WHERE u.id = %s
           )""",
        [int(coder_id), int(coder_id), int(coder_id)],
    )


def compute_coder_earnings(
    tenant_id: str,
    coder_id: int,
    year: int,
    *,
    today: date | None = None,
) -> dict[str, Any]:
    """
    Calculate year-to-date earnings + at-risk preview for a single coder.

    The bonus is the SUM over each closed gap of
    ``bonus_per_closure_default × month_multiplier(month_of_resolution)``.

    ``bonus_at_risk`` answers "if every still-open gap on this coder's
    plate were closed *this minute*, how much would they earn?" It is the
    open-gap count × current-month multiplier × base bonus.

    Returns::

        {
            "coder_id": int,
            "name": str,
            "email": str,
            "year": int,
            "ytd_closures": int,
            "ytd_dollars_recaptured": float,
            "bonus_earned": float,
            "bonus_at_risk": float,
            "current_month": int,
            "current_multiplier": float,
            "monthly_breakdown": [{"month": int, "closures": int, "bonus": float}, ...],
        }
    """
    config = get_or_create_config(tenant_id)
    base = float(config["bonus_per_closure_default"])
    mults = config["month_multipliers"]
    cm = current_month_multiplier(tenant_id, today=today)

    # 1. Lookup coder identity
    user_sql = "SELECT id, email, full_name, role FROM users WHERE id = %s"
    with raf_cursor() as cursor:
        cursor.execute(user_sql, (int(coder_id),))
        user = cursor.fetchone() or {}

    name = user.get("full_name") or user.get("email") or f"Coder #{coder_id}"
    email = user.get("email") or ""

    # 2. Closures + revenue (YTD)
    coder_clause, coder_params = _coder_filter(coder_id)

    closures_sql = f"""
        SELECT
            MONTH(rg.resolved_at)            AS month,
            COUNT(*)                          AS closures,
            COALESCE(SUM(rg.revenue_impact), 0) AS dollars_recaptured
        FROM recapture_gaps rg
        WHERE rg.tenant_id = %s
          AND rg.status    = 'recaptured'
          AND rg.resolved_at IS NOT NULL
          AND YEAR(rg.resolved_at) = %s
          AND {coder_clause}
        GROUP BY MONTH(rg.resolved_at)
        ORDER BY month
    """

    open_sql = f"""
        SELECT COUNT(*) AS open_count
        FROM recapture_gaps rg
        WHERE rg.tenant_id = %s
          AND rg.status    = 'open'
          AND {coder_clause}
    """

    try:
        with raf_cursor() as cursor:
            cursor.execute(closures_sql, [str(tenant_id), int(year), *coder_params])
            rows = cursor.fetchall() or []
            cursor.execute(open_sql, [str(tenant_id), *coder_params])
            open_row = cursor.fetchone() or {}
    except Exception as _db_exc:
        logger.error(
            "compute_coder_earnings: DB error tenant=%s coder=%s year=%s; %s",
            tenant_id, coder_id, year, _db_exc, exc_info=True,
        )
        rows = []
        open_row = {}

    monthly_breakdown: list[dict[str, Any]] = []
    ytd_closures = 0
    ytd_dollars = 0.0
    bonus_earned = 0.0

    # Build a 12-row breakdown so the UI can render an empty-month placeholder.
    by_month: dict[int, dict[str, Any]] = {}
    for r in rows:
        m = int(r["month"])
        c = int(r["closures"])
        d = float(r["dollars_recaptured"] or 0.0)
        by_month[m] = {"closures": c, "dollars": d}

    for month in range(1, 13):
        info = by_month.get(month, {"closures": 0, "dollars": 0.0})
        mult = float(mults.get(month, DEFAULT_MONTH_MULTIPLIERS[month]))
        bonus_this_month = round(base * mult * info["closures"], 2)
        ytd_closures += info["closures"]
        ytd_dollars += info["dollars"]
        bonus_earned += bonus_this_month
        monthly_breakdown.append({
            "month": month,
            "closures": info["closures"],
            "multiplier": mult,
            "bonus": bonus_this_month,
        })

    open_count = int(open_row.get("open_count") or 0)
    bonus_at_risk = round(base * cm["multiplier"] * open_count, 2)

    return {
        "coder_id": int(coder_id),
        "name": name,
        "email": email,
        "role": user.get("role") or "",
        "year": int(year),
        "ytd_closures": ytd_closures,
        "ytd_dollars_recaptured": round(ytd_dollars, 2),
        "bonus_earned": round(bonus_earned, 2),
        "bonus_at_risk": bonus_at_risk,
        "open_gaps": open_count,
        "current_month": cm["month"],
        "current_multiplier": cm["multiplier"],
        "next_month": cm["next_month"],
        "next_multiplier": cm["next_multiplier"],
        "monthly_breakdown": monthly_breakdown,
    }


# ---------------------------------------------------------------------------
# 4. Leaderboard
# ---------------------------------------------------------------------------

def compute_leaderboard(
    tenant_id: str,
    year: int,
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """
    Rank coders within a tenant by recapture closures for the given year.

    Returns rows pre-sorted by (ytd_closures DESC, ytd_dollars DESC) with
    a 1-based ``rank`` field. Coders with zero closures are omitted to
    avoid surfacing inactive accounts on the leaderboard.

    Each row::

        {
            "rank": int,
            "coder_id": int | None,    # users.id when a match is found
            "resolved_by": str,         # raw value from the gap row
            "name": str,
            "email": str,
            "ytd_closures": int,
            "ytd_dollars_recaptured": float,
            "bonus_earned": float,
            "win_rate": float,          # closures / (closures + open) on their plate
        }
    """
    config = get_or_create_config(tenant_id)
    base = float(config["bonus_per_closure_default"])
    mults = config["month_multipliers"]

    # Group closures by resolved_by (the raw audit string) and per-month so
    # we can apply the multiplier curve correctly without a Python loop
    # over thousands of rows.
    closed_sql = """
        SELECT
            rg.resolved_by                    AS resolved_by,
            MONTH(rg.resolved_at)             AS month,
            COUNT(*)                          AS closures,
            COALESCE(SUM(rg.revenue_impact), 0) AS dollars
        FROM recapture_gaps rg
        WHERE rg.tenant_id = %s
          AND rg.status    = 'recaptured'
          AND rg.resolved_at IS NOT NULL
          AND YEAR(rg.resolved_at) = %s
          AND rg.resolved_by IS NOT NULL
          AND rg.resolved_by <> ''
          AND rg.resolved_by <> 'system'
        GROUP BY rg.resolved_by, MONTH(rg.resolved_at)
    """

    open_sql = """
        SELECT
            rg.resolved_by AS resolved_by,
            COUNT(*)       AS open_count
        FROM recapture_gaps rg
        WHERE rg.tenant_id = %s
          AND rg.status    = 'open'
          AND rg.resolved_by IS NOT NULL
        GROUP BY rg.resolved_by
    """

    users_sql = "SELECT id, email, full_name FROM users"

    try:
        with raf_cursor() as cursor:
            cursor.execute(closed_sql, (str(tenant_id), int(year)))
            closed_rows = cursor.fetchall() or []
            # NOTE: open_sql intentionally has no resolved_by filter — we only
            # use it to compute win_rate for coders who DID close at least one
            # gap, which is unusual usage but sound: if a coder has open gaps
            # tagged with their id but zero closures, they will not appear on
            # the leaderboard at all (filtered below).
            cursor.execute(open_sql, (str(tenant_id),))
            open_rows = cursor.fetchall() or []
            cursor.execute(users_sql)
            user_rows = cursor.fetchall() or []
    except Exception as _db_exc:
        logger.error(
            "compute_leaderboard: DB error tenant=%s year=%s — returning empty; %s",
            tenant_id, year, _db_exc, exc_info=True,
        )
        return []

    # Index users by id, email, full_name so we can resolve the resolved_by
    # string back to a canonical user record regardless of which form was
    # stamped on the gap row.
    users_by_key: dict[str, dict[str, Any]] = {}
    for u in user_rows:
        for k in (str(u["id"]), (u.get("email") or "").lower(), (u.get("full_name") or "").lower()):
            if k:
                users_by_key.setdefault(k, u)

    open_by_key: dict[str, int] = {
        str(r["resolved_by"]): int(r["open_count"] or 0) for r in open_rows
    }

    # Aggregate per resolved_by
    agg: dict[str, dict[str, Any]] = {}
    for r in closed_rows:
        key = str(r["resolved_by"])
        month = int(r["month"]) if r.get("month") else 1
        closures = int(r["closures"] or 0)
        dollars = float(r["dollars"] or 0.0)
        mult = float(mults.get(month, DEFAULT_MONTH_MULTIPLIERS[month]))

        bucket = agg.setdefault(key, {
            "resolved_by": key,
            "ytd_closures": 0,
            "ytd_dollars_recaptured": 0.0,
            "bonus_earned": 0.0,
        })
        bucket["ytd_closures"] += closures
        bucket["ytd_dollars_recaptured"] += dollars
        bucket["bonus_earned"] += base * mult * closures

    # Materialise + enrich
    out: list[dict[str, Any]] = []
    for key, bucket in agg.items():
        user = (
            users_by_key.get(key)
            or users_by_key.get(key.lower())
            or {}
        )
        coder_id = int(user["id"]) if user.get("id") is not None else None
        name = user.get("full_name") or user.get("email") or key or "Unknown"
        email = user.get("email") or ""
        open_count = open_by_key.get(key, 0)
        # Include rolled-up open count by user id too in case the open
        # row keyed off an alternate identifier.
        if user.get("id") is not None:
            open_count += open_by_key.get(str(user["id"]), 0) if str(user["id"]) != key else 0
        if user.get("email"):
            open_count += open_by_key.get(user["email"], 0) if user["email"] != key else 0

        denom = bucket["ytd_closures"] + open_count
        win_rate = round(bucket["ytd_closures"] / denom, 4) if denom else 1.0

        out.append({
            "coder_id": coder_id,
            "resolved_by": key,
            "name": name,
            "email": email,
            "ytd_closures": int(bucket["ytd_closures"]),
            "ytd_dollars_recaptured": round(bucket["ytd_dollars_recaptured"], 2),
            "bonus_earned": round(bucket["bonus_earned"], 2),
            "open_gaps": open_count,
            "win_rate": win_rate,
        })

    out.sort(
        key=lambda r: (-int(r["ytd_closures"]), -float(r["ytd_dollars_recaptured"])),
    )
    out = out[: max(1, int(limit))]
    for i, row in enumerate(out, start=1):
        row["rank"] = i
    return out
