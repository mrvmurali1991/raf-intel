"""
Recapture Campaign Service
==========================

Bulk-campaign workflow for recapture gaps.  Mirrors the campaign abstraction
used by Edifecs / Episource:

    1. A coder lead defines a *filter* (e.g. ``hcc_codes=['18','19']``) that
       selects open ``recapture_gaps`` rows.
    2. The matched gaps are assigned in bulk to one or more coders, using a
       ``round_robin`` or ``by_specialty`` distribution.
    3. Coders work the kanban-style queue (assigned → in_progress → closed /
       dismissed).  Closed assignments roll up into campaign closure-rate and
       $-recaptured aggregates.

Tables: see ``database/migrations/add_recapture_campaigns.sql``.

All public functions accept and return plain dicts/lists so they can be
JSON-serialised by FastAPI without extra boilerplate.  Datetimes are
normalised to ISO-8601 strings on the way out.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from typing import Any, Iterable

from app.db import raf_cursor

logger = logging.getLogger(__name__)

# Allowed values are kept here (single source of truth) so the router and the
# service agree without importing each other's enums.
CAMPAIGN_STATUSES = {"draft", "active", "paused", "completed", "archived"}
ASSIGNMENT_STATUSES = {"assigned", "in_progress", "closed", "dismissed", "reassigned"}
DISTRIBUTION_STRATEGIES = {"round_robin", "by_specialty"}

# Closed assignment statuses that count toward closure-rate / recaptured $.
_CLOSED_STATUSES = {"closed"}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _isoformat(value: Any) -> Any:
    """Normalise datetimes/dates to ISO-8601 strings; pass through otherwise."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _row_to_dict(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {k: _isoformat(v) for k, v in row.items()}


def _parse_filter_criteria(raw: Any) -> dict[str, Any]:
    """JSON-decode a stored ``filter_criteria`` blob.  Empty / malformed → {}."""
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8")
    if isinstance(raw, str) and raw.strip():
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("filter_criteria not valid JSON: %r", raw[:80])
    return {}


def _build_filter_clause(criteria: dict[str, Any]) -> tuple[str, list[Any]]:
    """Translate a filter_criteria dict into a SQL fragment + params.

    Supported keys:
      - ``hcc_codes``: list[str]              → ``rg.hcc_code IN (...)``
      - ``min_revenue``: number               → ``rg.revenue_impact >= ?``
      - ``max_revenue``: number               → ``rg.revenue_impact <= ?``
      - ``max_age_days``: int                 → ``rg.created_at >= NOW() - INTERVAL ? DAY``
      - ``min_age_days``: int                 → ``rg.created_at <= NOW() - INTERVAL ? DAY``
      - ``provider_npis``: list[str]          → ``rg.provider_npi IN (...)``
      - ``patient_ids``: list[str|int]        → ``rg.patient_id IN (...)``
      - ``prior_year`` / ``current_year``: int

    Unknown keys are silently ignored — the dict is forward-compatible by design.
    """
    fragments: list[str] = []
    params: list[Any] = []

    hcc_codes = criteria.get("hcc_codes")
    if isinstance(hcc_codes, list) and hcc_codes:
        placeholders = ", ".join(["%s"] * len(hcc_codes))
        fragments.append(f"rg.hcc_code IN ({placeholders})")
        params.extend(str(c) for c in hcc_codes)

    min_revenue = criteria.get("min_revenue")
    if isinstance(min_revenue, (int, float)):
        fragments.append("rg.revenue_impact >= %s")
        params.append(float(min_revenue))

    max_revenue = criteria.get("max_revenue")
    if isinstance(max_revenue, (int, float)):
        fragments.append("rg.revenue_impact <= %s")
        params.append(float(max_revenue))

    max_age_days = criteria.get("max_age_days")
    if isinstance(max_age_days, int) and max_age_days >= 0:
        # Gap was created within the last N days.
        fragments.append("rg.created_at >= (NOW() - INTERVAL %s DAY)")
        params.append(max_age_days)

    min_age_days = criteria.get("min_age_days")
    if isinstance(min_age_days, int) and min_age_days >= 0:
        fragments.append("rg.created_at <= (NOW() - INTERVAL %s DAY)")
        params.append(min_age_days)

    provider_npis = criteria.get("provider_npis")
    if isinstance(provider_npis, list) and provider_npis:
        placeholders = ", ".join(["%s"] * len(provider_npis))
        fragments.append(f"rg.provider_npi IN ({placeholders})")
        params.extend(str(p) for p in provider_npis)

    patient_ids = criteria.get("patient_ids")
    if isinstance(patient_ids, list) and patient_ids:
        placeholders = ", ".join(["%s"] * len(patient_ids))
        fragments.append(f"rg.patient_id IN ({placeholders})")
        params.extend(str(p) for p in patient_ids)

    prior_year = criteria.get("prior_year")
    if isinstance(prior_year, int):
        fragments.append("rg.prior_year = %s")
        params.append(prior_year)

    current_year = criteria.get("current_year")
    if isinstance(current_year, int):
        fragments.append("rg.current_year = %s")
        params.append(current_year)

    where = (" AND " + " AND ".join(fragments)) if fragments else ""
    return where, params


# ---------------------------------------------------------------------------
# 1. create_campaign
# ---------------------------------------------------------------------------

def create_campaign(
    tenant_id: str,
    name: str,
    filter_criteria: dict[str, Any] | None = None,
    target_close_date: date | str | None = None,
    created_by: str | None = None,
    description: str | None = None,
    status: str = "draft",
) -> dict[str, Any]:
    """Insert a new campaign and return the persisted row.

    Args:
        tenant_id:        Tenant scope.
        name:             Human-readable campaign name.
        filter_criteria:  See ``_build_filter_clause``.
        target_close_date: Optional deadline (date or ISO string).
        created_by:       User id/email of the creator.
        description:      Free-text notes.
        status:           Initial status (default 'draft').

    Returns:
        dict with the inserted row (id, name, status, ...).
    """
    if not name or not name.strip():
        raise ValueError("Campaign name is required.")
    if status not in CAMPAIGN_STATUSES:
        raise ValueError(f"Invalid status '{status}'. Allowed: {sorted(CAMPAIGN_STATUSES)}")

    criteria_json = json.dumps(filter_criteria or {})

    insert_sql = """
        INSERT INTO recapture_campaigns
            (tenant_id, name, description, status, filter_criteria,
             target_close_date, created_by)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """
    select_sql = """
        SELECT id, tenant_id, name, description, status, filter_criteria,
               target_close_date, created_by, created_at, updated_at
          FROM recapture_campaigns
         WHERE id = %s
    """

    with raf_cursor() as cursor:
        cursor.execute(
            insert_sql,
            (
                tenant_id,
                name.strip(),
                description,
                status,
                criteria_json,
                target_close_date,
                created_by,
            ),
        )
        new_id = cursor.lastrowid
        cursor.execute(select_sql, (new_id,))
        row = cursor.fetchone()

    logger.info(
        "create_campaign tenant=%s id=%s name=%r status=%s",
        tenant_id, new_id, name, status,
    )
    out = _row_to_dict(row) or {}
    out["filter_criteria"] = _parse_filter_criteria(out.get("filter_criteria"))
    return out


# ---------------------------------------------------------------------------
# 2. preview_filter
# ---------------------------------------------------------------------------

def preview_filter(
    tenant_id: str,
    filter_criteria: dict[str, Any] | None,
) -> dict[str, Any]:
    """Return how many open recapture gaps match a filter, without persisting.

    Returns::

        {
            "matched_gaps": int,
            "total_revenue_at_risk": float,
            "by_hcc": [{"hcc_code": str, "count": int, "revenue": float}, ...]
        }
    """
    criteria = filter_criteria or {}
    extra_where, params = _build_filter_clause(criteria)

    count_sql = f"""
        SELECT
            COUNT(*)                               AS matched_gaps,
            COALESCE(SUM(rg.revenue_impact), 0)    AS total_revenue_at_risk
          FROM recapture_gaps rg
         WHERE rg.tenant_id = %s
           AND rg.status    = 'open'
           {extra_where}
    """

    by_hcc_sql = f"""
        SELECT
            rg.hcc_code                            AS hcc_code,
            COUNT(*)                               AS gap_count,
            COALESCE(SUM(rg.revenue_impact), 0)    AS revenue
          FROM recapture_gaps rg
         WHERE rg.tenant_id = %s
           AND rg.status    = 'open'
           {extra_where}
         GROUP BY rg.hcc_code
         ORDER BY revenue DESC
         LIMIT 25
    """

    with raf_cursor() as cursor:
        cursor.execute(count_sql, [tenant_id, *params])
        head = cursor.fetchone() or {}

        cursor.execute(by_hcc_sql, [tenant_id, *params])
        by_hcc_rows = cursor.fetchall() or []

    return {
        "matched_gaps": int(head.get("matched_gaps") or 0),
        "total_revenue_at_risk": float(head.get("total_revenue_at_risk") or 0.0),
        "by_hcc": [
            {
                "hcc_code": r["hcc_code"],
                "count": int(r["gap_count"]),
                "revenue": float(r["revenue"]),
            }
            for r in by_hcc_rows
        ],
    }


# ---------------------------------------------------------------------------
# 3. assign_gaps_to_coders
# ---------------------------------------------------------------------------

def _round_robin(items: Iterable[Any], buckets: int) -> list[list[Any]]:
    """Distribute *items* into *buckets* lists, alternating one at a time."""
    out: list[list[Any]] = [[] for _ in range(max(buckets, 1))]
    for idx, it in enumerate(items):
        out[idx % buckets].append(it)
    return out


def _select_matching_open_gaps(
    cursor,
    tenant_id: str,
    filter_criteria: dict[str, Any],
) -> list[dict[str, Any]]:
    extra_where, params = _build_filter_clause(filter_criteria or {})
    sql = f"""
        SELECT rg.id, rg.patient_id, rg.hcc_code, rg.icd10_code,
               rg.provider_npi, rg.revenue_impact, rg.created_at
          FROM recapture_gaps rg
         WHERE rg.tenant_id = %s
           AND rg.status    = 'open'
           {extra_where}
         ORDER BY rg.revenue_impact DESC, rg.id ASC
    """
    cursor.execute(sql, [tenant_id, *params])
    return cursor.fetchall() or []


def assign_gaps_to_coders(
    campaign_id: int,
    coder_ids: list[int],
    distribution: str = "round_robin",
    tenant_id: str | None = None,
) -> dict[str, Any]:
    """Bulk-assign matching open gaps to a list of coders.

    The campaign's stored ``filter_criteria`` selects which gaps to assign.
    Already-assigned gaps (same campaign+gap pair) are skipped silently
    thanks to the UNIQUE KEY ``uq_assign``.

    Args:
        campaign_id:  PK of recapture_campaigns row.
        coder_ids:    List of users.id values.  Order is honoured for round-robin.
        distribution: 'round_robin' (default) or 'by_specialty'.
        tenant_id:    Optional explicit tenant scope; if None we look it up.

    Returns:
        {
          "campaign_id": int,
          "assigned": int,                  # rows newly written
          "skipped_existing": int,          # already assigned in this campaign
          "per_coder": [{"coder_id": int, "count": int}, ...],
          "total_matched": int,
        }
    """
    if not coder_ids:
        raise ValueError("At least one coder_id is required.")
    if distribution not in DISTRIBUTION_STRATEGIES:
        raise ValueError(
            f"Invalid distribution '{distribution}'. "
            f"Allowed: {sorted(DISTRIBUTION_STRATEGIES)}"
        )

    fetch_campaign_sql = """
        SELECT id, tenant_id, filter_criteria, status
          FROM recapture_campaigns
         WHERE id = %s
    """

    insert_assignment_sql = """
        INSERT IGNORE INTO recapture_coder_assignments
            (campaign_id, coder_id, gap_id, status)
        VALUES (%s, %s, %s, 'assigned')
    """

    # For by_specialty we need a coder→provider_npi mapping (via users.provider_id)
    coder_specialty_sql = """
        SELECT u.id AS coder_id,
               p.npi AS provider_npi,
               p.specialty AS specialty
          FROM users u
          LEFT JOIN providers p ON p.id = u.provider_id
         WHERE u.id IN ({placeholders})
    """

    with raf_cursor() as cursor:
        cursor.execute(fetch_campaign_sql, (campaign_id,))
        campaign = cursor.fetchone()
        if not campaign:
            raise ValueError(f"Campaign {campaign_id} not found.")
        if tenant_id is None:
            tenant_id = campaign["tenant_id"]
        elif str(campaign["tenant_id"]) != str(tenant_id):
            raise ValueError(
                f"Campaign {campaign_id} does not belong to tenant {tenant_id}"
            )

        criteria = _parse_filter_criteria(campaign.get("filter_criteria"))

        # Activate a draft campaign on first assign for ergonomics.
        if campaign["status"] == "draft":
            cursor.execute(
                "UPDATE recapture_campaigns SET status='active' WHERE id=%s",
                (campaign_id,),
            )

        # 1. Gather all matching open gaps for this campaign.
        gaps = _select_matching_open_gaps(cursor, tenant_id, criteria)
        total_matched = len(gaps)

        # 2. Build the per-coder buckets.
        buckets: dict[int, list[int]] = {cid: [] for cid in coder_ids}

        if distribution == "by_specialty":
            placeholders = ", ".join(["%s"] * len(coder_ids))
            cursor.execute(
                coder_specialty_sql.format(placeholders=placeholders),
                tuple(coder_ids),
            )
            coder_rows = cursor.fetchall() or []

            # NPI → coder, specialty (HCC code-class) → coder
            npi_to_coder: dict[str, int] = {}
            specialty_to_coder: dict[str, int] = {}
            for r in coder_rows:
                cid = int(r["coder_id"])
                if r.get("provider_npi"):
                    npi_to_coder.setdefault(str(r["provider_npi"]), cid)
                if r.get("specialty"):
                    specialty_to_coder.setdefault(str(r["specialty"]).lower(), cid)

            # Walk gaps; route by NPI match first, then fall back to round-robin
            # so we never starve a gap.
            unrouted: list[int] = []
            for g in gaps:
                routed = False
                npi = str(g.get("provider_npi") or "")
                if npi and npi in npi_to_coder:
                    buckets[npi_to_coder[npi]].append(int(g["id"]))
                    routed = True
                if not routed:
                    unrouted.append(int(g["id"]))

            # Round-robin the leftovers across all coders so workload stays
            # roughly balanced.
            rr = _round_robin(unrouted, len(coder_ids))
            for cid, chunk in zip(coder_ids, rr):
                buckets[cid].extend(chunk)
        else:
            # Pure round-robin
            gap_ids = [int(g["id"]) for g in gaps]
            rr = _round_robin(gap_ids, len(coder_ids))
            for cid, chunk in zip(coder_ids, rr):
                buckets[cid] = chunk

        # 3. Persist assignments.
        rows_to_insert: list[tuple] = [
            (campaign_id, cid, gid)
            for cid, gids in buckets.items()
            for gid in gids
        ]

        assigned = 0
        if rows_to_insert:
            cursor.executemany(insert_assignment_sql, rows_to_insert)
            assigned = cursor.rowcount

        attempted = len(rows_to_insert)
        skipped_existing = max(attempted - assigned, 0)

    per_coder = [
        {"coder_id": cid, "count": len(buckets[cid])} for cid in coder_ids
    ]

    logger.info(
        "assign_gaps_to_coders campaign=%s matched=%d attempted=%d new=%d skipped=%d",
        campaign_id, total_matched, attempted, assigned, skipped_existing,
    )

    return {
        "campaign_id": campaign_id,
        "assigned": assigned,
        "skipped_existing": skipped_existing,
        "per_coder": per_coder,
        "total_matched": total_matched,
    }


# ---------------------------------------------------------------------------
# 4. mark_assignment
# ---------------------------------------------------------------------------

def mark_assignment(
    assignment_id: int,
    status: str,
    notes: str | None = None,
    coder_id: int | None = None,
) -> dict[str, Any]:
    """Update assignment state (kanban move) and cascade to recapture_gaps.

    When *status* is 'closed' we also mark the underlying gap as 'recaptured'
    so dashboards stay in sync.  When 'dismissed' the gap is marked 'dismissed'.

    Args:
        assignment_id:  PK of recapture_coder_assignments row.
        status:         New status — must be in ASSIGNMENT_STATUSES.
        notes:          Optional free-text note appended to the row.
        coder_id:       Optional ownership check: refuse the update if this
                        assignment belongs to another coder.

    Returns:
        Updated assignment dict + ``campaign`` rollup stats.
    """
    if status not in ASSIGNMENT_STATUSES:
        raise ValueError(
            f"Invalid status '{status}'. Allowed: {sorted(ASSIGNMENT_STATUSES)}"
        )

    fetch_sql = """
        SELECT a.id, a.campaign_id, a.coder_id, a.gap_id, a.status,
               c.tenant_id
          FROM recapture_coder_assignments a
          JOIN recapture_campaigns c ON c.id = a.campaign_id
         WHERE a.id = %s
    """
    update_assignment_sql = """
        UPDATE recapture_coder_assignments
           SET status   = %s,
               notes    = COALESCE(%s, notes),
               closed_at = CASE WHEN %s IN ('closed','dismissed')
                                THEN COALESCE(closed_at, NOW())
                                ELSE NULL END
         WHERE id = %s
    """
    update_gap_recaptured = """
        UPDATE recapture_gaps
           SET status      = 'recaptured',
               resolved_at = NOW(),
               resolved_by = %s
         WHERE id = %s
           AND status = 'open'
    """
    update_gap_dismissed = """
        UPDATE recapture_gaps
           SET status      = 'dismissed',
               resolved_at = NOW(),
               resolved_by = %s
         WHERE id = %s
           AND status = 'open'
    """

    with raf_cursor() as cursor:
        cursor.execute(fetch_sql, (assignment_id,))
        row = cursor.fetchone()
        if not row:
            raise ValueError(f"Assignment {assignment_id} not found.")
        if coder_id is not None and int(row["coder_id"]) != int(coder_id):
            raise PermissionError(
                f"Assignment {assignment_id} is owned by coder "
                f"{row['coder_id']}, not {coder_id}"
            )

        cursor.execute(
            update_assignment_sql,
            (status, notes, status, assignment_id),
        )

        # Cascade gap status only on terminal moves.
        actor = f"coder:{row['coder_id']}"
        if status == "closed":
            cursor.execute(update_gap_recaptured, (actor, row["gap_id"]))
        elif status == "dismissed":
            cursor.execute(update_gap_dismissed, (actor, row["gap_id"]))

        # Refresh and return the updated assignment + campaign rollup.
        cursor.execute(
            """
            SELECT id, campaign_id, coder_id, gap_id, status,
                   closed_at, notes, created_at, updated_at
              FROM recapture_coder_assignments
             WHERE id = %s
            """,
            (assignment_id,),
        )
        updated = cursor.fetchone()

        # Auto-complete the campaign when every assignment is in a terminal
        # state (closed / dismissed).
        cursor.execute(
            """
            SELECT
              SUM(status NOT IN ('closed','dismissed')) AS still_open,
              COUNT(*)                                  AS total
              FROM recapture_coder_assignments
             WHERE campaign_id = %s
            """,
            (row["campaign_id"],),
        )
        rollup = cursor.fetchone() or {}
        if (
            rollup.get("total")
            and not rollup.get("still_open")
        ):
            cursor.execute(
                "UPDATE recapture_campaigns SET status='completed' WHERE id=%s "
                "AND status IN ('active','paused','draft')",
                (row["campaign_id"],),
            )

    out = _row_to_dict(updated) or {}
    out["campaign_id"] = row["campaign_id"]

    # Roll up campaign stats so the UI can update without an extra round-trip.
    out["campaign_stats"] = _compute_campaign_stats(row["campaign_id"])

    logger.info(
        "mark_assignment id=%s status=%s coder=%s",
        assignment_id, status, row["coder_id"],
    )
    return out


# ---------------------------------------------------------------------------
# 5. Campaign stats / list / detail
# ---------------------------------------------------------------------------

def _compute_campaign_stats(campaign_id: int) -> dict[str, Any]:
    """Return rolled-up totals for a single campaign id."""
    sql = """
        SELECT
          COUNT(*)                                                AS total_gaps,
          SUM(a.status = 'assigned')                              AS assigned_count,
          SUM(a.status = 'in_progress')                           AS in_progress_count,
          SUM(a.status = 'closed')                                AS closed_count,
          SUM(a.status = 'dismissed')                             AS dismissed_count,
          COALESCE(SUM(CASE WHEN a.status = 'closed'
                            THEN rg.revenue_impact END), 0)       AS recaptured_revenue,
          COALESCE(SUM(CASE WHEN a.status NOT IN ('closed','dismissed')
                            THEN rg.revenue_impact END), 0)       AS at_risk_revenue
          FROM recapture_coder_assignments a
          LEFT JOIN recapture_gaps rg ON rg.id = a.gap_id
         WHERE a.campaign_id = %s
    """
    with raf_cursor() as cursor:
        cursor.execute(sql, (campaign_id,))
        row = cursor.fetchone() or {}

    total = int(row.get("total_gaps") or 0)
    closed = int(row.get("closed_count") or 0)
    closure_rate = (closed / total * 100.0) if total else 0.0

    return {
        "total_gaps":          total,
        "assigned":            int(row.get("assigned_count") or 0),
        "in_progress":         int(row.get("in_progress_count") or 0),
        "closed":              closed,
        "dismissed":           int(row.get("dismissed_count") or 0),
        "closure_rate":        round(closure_rate, 2),
        "recaptured_revenue":  float(row.get("recaptured_revenue") or 0.0),
        "at_risk_revenue":     float(row.get("at_risk_revenue") or 0.0),
    }


def list_campaigns(
    tenant_id: str,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Return campaigns for a tenant with rolled-up stats."""
    if status is not None and status not in CAMPAIGN_STATUSES:
        raise ValueError(f"Invalid status '{status}'.")

    params: list[Any] = [tenant_id]
    extra = ""
    if status:
        extra = "AND c.status = %s"
        params.append(status)
    params.extend([limit, offset])

    list_sql = f"""
        SELECT c.id, c.tenant_id, c.name, c.description, c.status,
               c.filter_criteria, c.target_close_date, c.created_by,
               c.created_at, c.updated_at,
               COUNT(a.id)                                            AS total_gaps,
               SUM(a.status = 'closed')                               AS closed_count,
               SUM(a.status = 'in_progress')                          AS in_progress_count,
               SUM(a.status = 'dismissed')                            AS dismissed_count,
               COALESCE(SUM(CASE WHEN a.status = 'closed'
                                 THEN rg.revenue_impact END), 0)      AS recaptured_revenue,
               COALESCE(SUM(CASE WHEN a.status NOT IN ('closed','dismissed')
                                 THEN rg.revenue_impact END), 0)      AS at_risk_revenue
          FROM recapture_campaigns c
          LEFT JOIN recapture_coder_assignments a ON a.campaign_id = c.id
          LEFT JOIN recapture_gaps rg              ON rg.id = a.gap_id
         WHERE c.tenant_id = %s
           {extra}
         GROUP BY c.id
         ORDER BY c.created_at DESC
         LIMIT %s OFFSET %s
    """

    with raf_cursor() as cursor:
        cursor.execute(list_sql, params)
        rows = cursor.fetchall() or []

    out: list[dict[str, Any]] = []
    for row in rows:
        item = _row_to_dict(row) or {}
        item["filter_criteria"] = _parse_filter_criteria(item.get("filter_criteria"))
        total = int(item.pop("total_gaps", 0) or 0)
        closed = int(item.pop("closed_count", 0) or 0)
        item["stats"] = {
            "total_gaps": total,
            "in_progress": int(item.pop("in_progress_count", 0) or 0),
            "closed": closed,
            "dismissed": int(item.pop("dismissed_count", 0) or 0),
            "closure_rate": round((closed / total * 100.0) if total else 0.0, 2),
            "recaptured_revenue": float(item.pop("recaptured_revenue", 0.0) or 0.0),
            "at_risk_revenue": float(item.pop("at_risk_revenue", 0.0) or 0.0),
        }
        out.append(item)
    return out


def get_campaign(campaign_id: int, tenant_id: str) -> dict[str, Any] | None:
    """Return a single campaign + rolled-up stats, or None if missing."""
    fetch_sql = """
        SELECT id, tenant_id, name, description, status, filter_criteria,
               target_close_date, created_by, created_at, updated_at
          FROM recapture_campaigns
         WHERE id = %s AND tenant_id = %s
    """
    with raf_cursor() as cursor:
        cursor.execute(fetch_sql, (campaign_id, tenant_id))
        row = cursor.fetchone()
    if not row:
        return None

    item = _row_to_dict(row) or {}
    item["filter_criteria"] = _parse_filter_criteria(item.get("filter_criteria"))
    item["stats"] = _compute_campaign_stats(campaign_id)
    return item


def update_campaign(
    campaign_id: int,
    tenant_id: str,
    *,
    name: str | None = None,
    description: str | None = None,
    status: str | None = None,
    filter_criteria: dict[str, Any] | None = None,
    target_close_date: date | str | None = None,
) -> dict[str, Any] | None:
    """Patch one or more campaign fields.  Returns the refreshed row."""
    if status is not None and status not in CAMPAIGN_STATUSES:
        raise ValueError(f"Invalid status '{status}'.")

    sets: list[str] = []
    params: list[Any] = []
    if name is not None:
        sets.append("name = %s"); params.append(name.strip())
    if description is not None:
        sets.append("description = %s"); params.append(description)
    if status is not None:
        sets.append("status = %s"); params.append(status)
    if filter_criteria is not None:
        sets.append("filter_criteria = %s"); params.append(json.dumps(filter_criteria))
    if target_close_date is not None:
        sets.append("target_close_date = %s"); params.append(target_close_date)

    if not sets:
        return get_campaign(campaign_id, tenant_id)

    sql = f"UPDATE recapture_campaigns SET {', '.join(sets)} WHERE id = %s AND tenant_id = %s"
    params.extend([campaign_id, tenant_id])
    with raf_cursor() as cursor:
        cursor.execute(sql, params)
        affected = cursor.rowcount

    if not affected:
        return None
    return get_campaign(campaign_id, tenant_id)


# ---------------------------------------------------------------------------
# 6. Kanban
# ---------------------------------------------------------------------------

def get_campaign_kanban(campaign_id: int, tenant_id: str) -> dict[str, Any]:
    """Return assignments grouped by kanban bucket.

    Output::

        {
          "campaign_id": int,
          "stats": {...},
          "buckets": {
            "assigned":    [<assignment+gap>...],
            "in_progress": [...],
            "closed":      [...],
            "dismissed":   [...]
          }
        }
    """
    # Confirm the campaign exists and belongs to this tenant.
    campaign = get_campaign(campaign_id, tenant_id)
    if not campaign:
        raise ValueError(f"Campaign {campaign_id} not found for tenant {tenant_id}")

    sql = """
        SELECT a.id              AS assignment_id,
               a.campaign_id,
               a.coder_id,
               a.gap_id,
               a.status           AS assignment_status,
               a.closed_at,
               a.notes,
               a.created_at       AS assigned_at,
               a.updated_at       AS assignment_updated_at,
               rg.patient_id,
               rg.hcc_code,
               rg.icd10_code,
               rg.prior_year,
               rg.current_year,
               rg.revenue_impact,
               rg.last_encounter_date,
               rg.provider_npi,
               rg.status          AS gap_status,
               CONCAT(COALESCE(u.first_name,''),' ',COALESCE(u.last_name,'')) AS coder_name,
               u.email                                                        AS coder_email
          FROM recapture_coder_assignments a
          LEFT JOIN recapture_gaps rg ON rg.id = a.gap_id
          LEFT JOIN users u           ON u.id = a.coder_id
         WHERE a.campaign_id = %s
         ORDER BY rg.revenue_impact DESC, a.id ASC
    """

    with raf_cursor() as cursor:
        cursor.execute(sql, (campaign_id,))
        rows = cursor.fetchall() or []

    buckets: dict[str, list[dict[str, Any]]] = {
        "assigned": [], "in_progress": [], "closed": [], "dismissed": [],
    }
    for r in rows:
        item = _row_to_dict(r) or {}
        # Cast a few numeric fields for the UI
        if item.get("revenue_impact") is not None:
            item["revenue_impact"] = float(item["revenue_impact"])
        if item.get("coder_name"):
            item["coder_name"] = item["coder_name"].strip() or None
        bucket = item.get("assignment_status") or "assigned"
        # 'reassigned' rows fall back into the assigned column
        if bucket == "reassigned":
            bucket = "assigned"
        buckets.setdefault(bucket, []).append(item)

    return {
        "campaign_id": campaign_id,
        "stats": campaign["stats"],
        "buckets": buckets,
    }


# ---------------------------------------------------------------------------
# 7. Coder dashboard
# ---------------------------------------------------------------------------

def list_coders(tenant_id: str) -> list[dict[str, Any]]:
    """Return active users that can receive campaign assignments.

    Includes users with role 'coder', 'admin', or 'manager' so coder leads
    can self-assign or delegate.  Used by the CreateCampaignModal to populate
    the coder picker.
    """
    sql = """
        SELECT id,
               email,
               role,
               TRIM(CONCAT(COALESCE(first_name,''),' ',COALESCE(last_name,''))) AS full_name
          FROM users
         WHERE tenant_id = %s
           AND is_active = 1
           AND role IN ('coder','admin','manager')
         ORDER BY role, full_name
    """
    with raf_cursor() as cursor:
        cursor.execute(sql, (tenant_id,))
        rows = cursor.fetchall() or []
    return [
        {
            "id": int(r["id"]),
            "email": r["email"],
            "role": r["role"],
            "full_name": (r.get("full_name") or "").strip() or r["email"],
        }
        for r in rows
    ]


def get_coder_dashboard(coder_id: int, tenant_id: str | None = None) -> dict[str, Any]:
    """Return a coder-centric summary: my queue, today's closures, weekly velocity.

    Args:
        coder_id:  users.id of the coder.
        tenant_id: Optional scope — when provided we only count assignments
                   whose campaign belongs to this tenant.

    Returns::

        {
          "coder_id": int,
          "my_open_assignments": [...],
          "today_closures": int,
          "week_closures": int,
          "weekly_velocity": [{"day": "YYYY-MM-DD", "closed": int}, ...],  # last 7 days
          "totals": {"open": int, "closed": int, "dismissed": int}
        }
    """
    tenant_filter = ""
    params_open: list[Any] = [coder_id]
    if tenant_id is not None:
        tenant_filter = "AND c.tenant_id = %s"
        params_open.append(tenant_id)

    open_sql = f"""
        SELECT a.id              AS assignment_id,
               a.campaign_id,
               c.name             AS campaign_name,
               a.gap_id,
               a.status,
               a.created_at,
               rg.patient_id,
               rg.hcc_code,
               rg.icd10_code,
               rg.revenue_impact,
               rg.last_encounter_date
          FROM recapture_coder_assignments a
          JOIN recapture_campaigns c ON c.id = a.campaign_id
          LEFT JOIN recapture_gaps rg ON rg.id = a.gap_id
         WHERE a.coder_id = %s
           {tenant_filter}
           AND a.status IN ('assigned','in_progress')
         ORDER BY rg.revenue_impact DESC
         LIMIT 100
    """

    velocity_sql = f"""
        SELECT DATE(a.closed_at)                AS day,
               COUNT(*)                          AS closed
          FROM recapture_coder_assignments a
          JOIN recapture_campaigns c ON c.id = a.campaign_id
         WHERE a.coder_id = %s
           {tenant_filter}
           AND a.status   = 'closed'
           AND a.closed_at >= (CURDATE() - INTERVAL 6 DAY)
         GROUP BY DATE(a.closed_at)
         ORDER BY day ASC
    """

    totals_sql = f"""
        SELECT
          SUM(a.status IN ('assigned','in_progress'))    AS open_count,
          SUM(a.status = 'closed')                       AS closed_count,
          SUM(a.status = 'dismissed')                    AS dismissed_count,
          SUM(a.status = 'closed' AND DATE(a.closed_at) = CURDATE()) AS today_closures,
          SUM(a.status = 'closed' AND a.closed_at >= (CURDATE() - INTERVAL 6 DAY)) AS week_closures
          FROM recapture_coder_assignments a
          JOIN recapture_campaigns c ON c.id = a.campaign_id
         WHERE a.coder_id = %s
           {tenant_filter}
    """

    with raf_cursor() as cursor:
        cursor.execute(open_sql, params_open)
        open_rows = cursor.fetchall() or []

        cursor.execute(velocity_sql, params_open)
        velocity = cursor.fetchall() or []

        cursor.execute(totals_sql, params_open)
        totals_row = cursor.fetchone() or {}

    open_assignments = []
    for r in open_rows:
        item = _row_to_dict(r) or {}
        if item.get("revenue_impact") is not None:
            item["revenue_impact"] = float(item["revenue_impact"])
        open_assignments.append(item)

    return {
        "coder_id": coder_id,
        "my_open_assignments": open_assignments,
        "today_closures": int(totals_row.get("today_closures") or 0),
        "week_closures": int(totals_row.get("week_closures") or 0),
        "weekly_velocity": [
            {
                "day": _isoformat(r["day"]),
                "closed": int(r["closed"]),
            }
            for r in velocity
        ],
        "totals": {
            "open": int(totals_row.get("open_count") or 0),
            "closed": int(totals_row.get("closed_count") or 0),
            "dismissed": int(totals_row.get("dismissed_count") or 0),
        },
    }
