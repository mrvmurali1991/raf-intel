"""MD-facing pre-visit huddle router.

Endpoints
---------
GET  /api/md/today                       Today's schedule + top HCC gaps for the authenticated MD
POST /api/md/today/reviewed/{patient_id} Mark this patient's huddle as reviewed

Surfaces the existing previsit_briefing service through a clinician-friendly
shape: one card per visit, ranked HCC gaps, light envelope so a tablet/phone
client can render fast.
"""
from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth import get_current_user, get_tenant_id, require_permission
from app.db import raf_cursor
from app.services.audit_logger import log_phi_access
from app.services.previsit_briefing import get_upcoming_briefings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/md", tags=["md"])


def _resolve_provider_id(current_user: dict, override: int | None) -> int:
    """Resolve which provider's schedule to fetch.

    Why: NEVER fall back to a hard-coded provider_id. Doing so silently leaks
    another provider's PHI to any caller without a provider mapping (e.g.
    admin users with no clinical role). Either the caller has a mapping or
    they don't — no implicit defaults.
    """
    role = (current_user.get("role") or "").lower()
    if override is not None:
        if role not in {"admin", "manager"}:
            raise HTTPException(
                status_code=403,
                detail="Only admin/manager may view another provider's huddle",
            )
        return int(override)
    pid = current_user.get("provider_id")
    if pid:
        return int(pid)
    raise HTTPException(
        status_code=403,
        detail=(
            "No provider_id mapping for this user. Ask an admin to link your "
            "account to a clinical provider (admin/manager can pass "
            "?provider_id= explicitly)."
        ),
    )


@router.get(
    "/today",
    summary="Today's MD huddle — top HCC gaps per scheduled visit",
)
def md_today(
    provider_id: int | None = Query(
        default=None,
        description="Admin/manager override; defaults to the caller's provider.",
    ),
    days: int = Query(default=1, ge=0, le=7),
    limit_per_patient: int = Query(default=3, ge=1, le=10),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("huddle", "read")),
) -> dict:
    pid = _resolve_provider_id(current_user, provider_id)

    try:
        briefings = get_upcoming_briefings(
            provider_id=pid,
            days_ahead=days,
            limit_per_patient=limit_per_patient,
            tenant_id=tenant_id,
        )
    except Exception as exc:
        logger.error("md_today provider=%s: %s", pid, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to load huddle")

    reviewed_pids: set[int] = set()
    try:
        with raf_cursor() as cur:
            cur.execute(
                """SELECT patient_id FROM previsit_briefing_reviews
                   WHERE tenant_id = %s
                     AND provider_id = %s
                     AND reviewed_date = %s""",
                (tenant_id, pid, date.today()),
            )
            reviewed_pids = {int(r[0]) for r in cur.fetchall() or []}
    except Exception:
        logger.debug("swallowed exception", exc_info=True)
        reviewed_pids = set()

    for b in briefings:
        b["reviewed"] = int(b.get("patient_id") or 0) in reviewed_pids

    # Decorate every HCC gap with supporting labs + per-HCC dollar value.
    # The huddle is most useful when the doctor sees both at a glance.
    from app.services.hcc_lab_evidence import evidence_for_gaps
    total_revenue_at_stake = 0.0
    total_supporting_labs = 0
    for b in briefings:
        emr_pid = int(b.get("patient_id") or b.get("emr_pid") or 0)
        gaps = b.get("hcc_gaps") or b.get("top_gaps") or []
        if emr_pid and gaps:
            try:
                evidence_for_gaps(emr_pid, gaps)
                for g in gaps:
                    total_revenue_at_stake += float(
                        g.get("estimated_annual_revenue_dollars") or 0
                    )
                    le = g.get("lab_evidence") or {}
                    total_supporting_labs += len(le.get("supporting") or [])
            except Exception as exc:  # never block the huddle on enrichment
                logger.warning("lab evidence enrichment failed pid=%s: %s",
                               emr_pid, exc)

    open_hcc_total = sum(len(b.get("hcc_gaps") or []) for b in briefings)
    reviewed_count = sum(1 for b in briefings if b.get("reviewed"))

    return {
        "provider_id": pid,
        "date": date.today().isoformat(),
        "briefings": briefings,
        "summary": {
            "total_visits": len(briefings),
            "total_open_hcc_gaps": open_hcc_total,
            "reviewed_count": reviewed_count,
            "review_progress_pct": (
                round(100 * reviewed_count / len(briefings)) if briefings else 0
            ),
            "total_revenue_at_stake_dollars": round(total_revenue_at_stake, 2),
            "total_supporting_labs": total_supporting_labs,
        },
    }


@router.post(
    "/today/reviewed/{patient_id}",
    summary="Mark this patient's huddle as reviewed for today",
)
def md_today_mark_reviewed(
    patient_id: int,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("huddle", "write")),
) -> dict:
    pid = _resolve_provider_id(current_user, None)
    user_id = int(current_user.get("id") or current_user.get("user_id") or 0)

    with raf_cursor() as cur:
        cur.execute(
            """INSERT INTO previsit_briefing_reviews
                 (tenant_id, provider_id, patient_id, reviewed_date,
                  reviewed_by_user_id)
               VALUES (%s, %s, %s, %s, %s)
               ON DUPLICATE KEY UPDATE reviewed_by_user_id = VALUES(reviewed_by_user_id)""",
            (tenant_id, pid, patient_id, date.today(), user_id),
        )

    log_phi_access(
        action="MD_HUDDLE_REVIEWED",
        resource="previsit_briefing",
        patient_id=patient_id,
        user=str(user_id),
    )
    return {"patient_id": patient_id, "reviewed": True}
