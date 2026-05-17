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

from app.auth import get_current_user
from app.db import raf_cursor
from app.services.audit_logger import log_phi_access
from app.services.previsit_briefing import get_upcoming_briefings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/md", tags=["md"])


def _resolve_provider_id(current_user: dict, override: int | None) -> int:
    """Resolve which provider's schedule to fetch.

    Priority:
      1. Explicit ?provider_id= query param (admin/manager only — physicians
         must view their own schedule).
      2. JWT-derived provider_id when the users table carries one (future).
      3. Demo default = 1 so the page renders for any tenant out of the box.
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
    return 1


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
) -> dict:
    pid = _resolve_provider_id(current_user, provider_id)

    try:
        briefings = get_upcoming_briefings(
            provider_id=pid,
            days_ahead=days,
            limit_per_patient=limit_per_patient,
        )
    except Exception as exc:
        logger.error("md_today provider=%s: %s", pid, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to load huddle")

    reviewed_pids: set[int] = set()
    try:
        with raf_cursor() as cur:
            cur.execute(
                """SELECT patient_id FROM previsit_briefing_reviews
                   WHERE provider_id = %s AND reviewed_date = %s""",
                (pid, date.today()),
            )
            reviewed_pids = {int(r[0]) for r in cur.fetchall() or []}
    except Exception:
        reviewed_pids = set()

    for b in briefings:
        b["reviewed"] = int(b.get("patient_id") or 0) in reviewed_pids

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
        },
    }


@router.post(
    "/today/reviewed/{patient_id}",
    summary="Mark this patient's huddle as reviewed for today",
)
def md_today_mark_reviewed(
    patient_id: int,
    current_user: dict = Depends(get_current_user),
) -> dict:
    pid = _resolve_provider_id(current_user, None)
    user_id = int(current_user.get("id") or current_user.get("user_id") or 0)

    with raf_cursor() as cur:
        cur.execute(
            """INSERT INTO previsit_briefing_reviews
                 (provider_id, patient_id, reviewed_date, reviewed_by_user_id)
               VALUES (%s, %s, %s, %s)
               ON DUPLICATE KEY UPDATE reviewed_by_user_id = VALUES(reviewed_by_user_id)""",
            (pid, patient_id, date.today(), user_id),
        )

    log_phi_access(
        action="MD_HUDDLE_REVIEWED",
        resource="previsit_briefing",
        patient_id=patient_id,
        user=str(user_id),
    )
    return {"patient_id": patient_id, "reviewed": True}
