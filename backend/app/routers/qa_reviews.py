"""
Multi-rater QA review workflow (Reveleer pattern).

Each accepted suspect / HCC can be routed to a secondary QA reviewer who
either confirms or disputes the primary rating. If the two raters disagree
the row is escalated to a tier-2 reviewer for adjudication.

REST surface
------------
POST /api/qa-reviews                     create the primary review
PUT  /api/qa-reviews/{id}/secondary      add the secondary rating
PUT  /api/qa-reviews/{id}/tier2          adjudicate an escalation
GET  /api/qa-reviews?outcome=...         worklist (pending | escalated | accepted | rejected)
GET  /api/qa-reviews/{id}                full review row

Authorization
-------------
All endpoints require an authenticated user and are tenant-scoped.
Mutating endpoints additionally require the ``qa_review`` resource permission
(action "write"). If the permissions table does not yet know about the
``qa_review`` resource ``check_permission`` returns False and the endpoint
returns 403 — admins can grant the permission through the standard RBAC
admin UI without any code changes.

The router never touches existing suspect / accept / dismiss endpoints —
QA review is an additive workflow that records who-said-what alongside the
primary acceptance event.
"""
# Avoid ``from __future__ import annotations`` — FastAPI/Pydantic schema
# generation dislikes it in routers.

import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from app.auth import get_current_user, get_tenant_id, require_permission
from app.db import raf_cursor
from app.middleware.idempotency import (
    idempotency_key_dependency,
    store_idempotent_response,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/qa-reviews", tags=["qa-review"])


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

Rating = Literal["accept", "reject", "unclear"]
Outcome = Literal["accepted", "rejected", "escalated", "pending"]


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class CreateReviewPayload(BaseModel):
    suspect_id: int | None = Field(
        default=None, description="form_suspects.id — at least one of suspect_id / raf_patient_hcc_id required"
    )
    raf_patient_hcc_id: int | None = Field(
        default=None, description="raf_patient_hccs.id"
    )
    primary_rating: Rating
    primary_note: str | None = None


class SecondaryReviewPayload(BaseModel):
    secondary_rating: Rating
    secondary_note: str | None = None


class Tier2ReviewPayload(BaseModel):
    tier2_rating: Rating
    tier2_note: str | None = None


class QAReview(BaseModel):
    id: int
    tenant_id: str
    suspect_id: int | None = None
    raf_patient_hcc_id: int | None = None

    primary_rater_user_id: int
    primary_rating: Rating
    primary_note: str | None = None

    secondary_rater_user_id: int | None = None
    secondary_rating: Rating | None = None
    secondary_note: str | None = None

    tier2_rater_user_id: int | None = None
    tier2_rating: Rating | None = None
    tier2_note: str | None = None

    final_outcome: Outcome
    created_at: str | None = None
    updated_at: str | None = None

    # Convenience metadata — included when joinable.
    suspect_label: str | None = None
    patient_id: int | None = None
    patient_name: str | None = None


class ListResponse(BaseModel):
    items: list[QAReview]
    total: int


class CreatedResponse(BaseModel):
    id: int
    final_outcome: Outcome


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


# Map (primary, secondary) ratings to a closed outcome.
# - identical ratings:
#     accept × accept -> accepted
#     reject × reject -> rejected
#     unclear × unclear -> escalated   (two reviewers both unsure → tier2)
# - any disagreement -> escalated
def _resolve_outcome(primary: Rating, secondary: Rating) -> Outcome:
    if primary == secondary:
        if primary == "accept":
            return "accepted"
        if primary == "reject":
            return "rejected"
        # unclear/unclear -> escalate to tier-2 for a definitive call
        return "escalated"
    return "escalated"


# Map a tier-2 rating to a final closed outcome. ``unclear`` from tier-2 stays
# escalated (we never auto-close on tier-2 unclear; an admin can re-route).
def _resolve_tier2_outcome(tier2: Rating) -> Outcome:
    if tier2 == "accept":
        return "accepted"
    if tier2 == "reject":
        return "rejected"
    return "escalated"


def _user_id(current_user: dict) -> int:
    """Best-effort integer user id from the JWT/session record."""
    raw = current_user.get("id") or current_user.get("user_id") or current_user.get("sub")
    if raw is None:
        raise HTTPException(401, "user id missing from session")
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise HTTPException(401, "user id is not an integer") from exc


def _row_to_model(row: dict) -> QAReview:
    return QAReview(
        id=int(row["id"]),
        tenant_id=str(row["tenant_id"]),
        suspect_id=row.get("suspect_id"),
        raf_patient_hcc_id=row.get("raf_patient_hcc_id"),
        primary_rater_user_id=int(row["primary_rater_user_id"]),
        primary_rating=row["primary_rating"],
        primary_note=row.get("primary_note"),
        secondary_rater_user_id=row.get("secondary_rater_user_id"),
        secondary_rating=row.get("secondary_rating"),
        secondary_note=row.get("secondary_note"),
        tier2_rater_user_id=row.get("tier2_rater_user_id"),
        tier2_rating=row.get("tier2_rating"),
        tier2_note=row.get("tier2_note"),
        final_outcome=row["final_outcome"],
        created_at=str(row["created_at"]) if row.get("created_at") else None,
        updated_at=str(row["updated_at"]) if row.get("updated_at") else None,
        suspect_label=row.get("suspect_label"),
        patient_id=row.get("patient_id"),
        patient_name=row.get("patient_name"),
    )


_SELECT_BARE = """
SELECT q.id, q.tenant_id, q.suspect_id, q.raf_patient_hcc_id,
       q.primary_rater_user_id, q.primary_rating, q.primary_note,
       q.secondary_rater_user_id, q.secondary_rating, q.secondary_note,
       q.tier2_rater_user_id, q.tier2_rating, q.tier2_note,
       q.final_outcome, q.created_at, q.updated_at,
       NULL AS patient_id, NULL AS suspect_label, NULL AS patient_name
  FROM raf_qa_reviews q
"""

_SELECT_WITH_SUSPECT = """
SELECT q.id, q.tenant_id, q.suspect_id, q.raf_patient_hcc_id,
       q.primary_rater_user_id, q.primary_rating, q.primary_note,
       q.secondary_rater_user_id, q.secondary_rating, q.secondary_note,
       q.tier2_rater_user_id, q.tier2_rating, q.tier2_note,
       q.final_outcome, q.created_at, q.updated_at,
       s.patient_id,
       CONCAT_WS(' · ', s.suspect_hcc, s.suspect_icd10, s.suspected_condition)
           AS suspect_label,
       CONCAT_WS(' ', p.first_name, p.last_name) AS patient_name
  FROM raf_qa_reviews q
  LEFT JOIN form_suspects s ON s.id = q.suspect_id
  LEFT JOIN patients p ON p.id = s.patient_id
"""


def _select_template(cur) -> str:
    """
    Return the suspect-joined SELECT when form_suspects exists in this DB,
    otherwise a bare SELECT. form_suspects is the OpenEMR-sourced suspect
    table and is not present in every environment (e.g. RAF-only schemas).
    """
    try:
        cur.execute("SHOW TABLES LIKE 'form_suspects'")
        if cur.fetchone():
            return _SELECT_WITH_SUSPECT
    except Exception:
        logger.debug("form_suspects probe failed", exc_info=True)
    return _SELECT_BARE


# ---------------------------------------------------------------------------
# POST /api/qa-reviews
# ---------------------------------------------------------------------------


@router.post("", response_model=CreatedResponse, status_code=201)
def create_review(
    request: Request,
    response: Response,
    body: CreateReviewPayload,
    current_user: dict = Depends(require_permission("qa_review", "write")),
    tenant_id: str = Depends(get_tenant_id),
    _idem: None = Depends(idempotency_key_dependency()),
) -> CreatedResponse:
    if body.suspect_id is None and body.raf_patient_hcc_id is None:
        raise HTTPException(
            400, "either suspect_id or raf_patient_hcc_id is required"
        )

    rater = _user_id(current_user)
    with raf_cursor() as cur:
        cur.execute(
            """
            INSERT INTO raf_qa_reviews (
                tenant_id, suspect_id, raf_patient_hcc_id,
                primary_rater_user_id, primary_rating, primary_note,
                final_outcome
            ) VALUES (%s, %s, %s, %s, %s, %s, 'pending')
            """,
            (
                tenant_id,
                body.suspect_id,
                body.raf_patient_hcc_id,
                rater,
                body.primary_rating,
                body.primary_note,
            ),
        )
        new_id = cur.lastrowid

    result = CreatedResponse(id=int(new_id), final_outcome="pending")
    store_idempotent_response(request, response, result.model_dump())
    return result


# ---------------------------------------------------------------------------
# PUT /api/qa-reviews/{id}/secondary
# ---------------------------------------------------------------------------


@router.put("/{review_id}/secondary", response_model=QAReview)
def add_secondary_rating(
    review_id: int,
    body: SecondaryReviewPayload,
    current_user: dict = Depends(require_permission("qa_review", "write")),
    tenant_id: str = Depends(get_tenant_id),
) -> QAReview:
    rater = _user_id(current_user)
    with raf_cursor() as cur:
        cur.execute(
            "SELECT * FROM raf_qa_reviews WHERE id=%s AND tenant_id=%s",
            (review_id, tenant_id),
        )
        existing = cur.fetchone()
        if not existing:
            raise HTTPException(404, "qa review not found")
        if existing["secondary_rating"] is not None:
            raise HTTPException(409, "secondary rating already recorded")
        if existing["primary_rater_user_id"] == rater:
            # A primary rater cannot also secondary-rate their own row;
            # this is the whole point of multi-rater QA.
            raise HTTPException(
                403, "secondary review must come from a different rater"
            )

        outcome = _resolve_outcome(existing["primary_rating"], body.secondary_rating)

        cur.execute(
            """
            UPDATE raf_qa_reviews
               SET secondary_rater_user_id=%s,
                   secondary_rating=%s,
                   secondary_note=%s,
                   final_outcome=%s
             WHERE id=%s AND tenant_id=%s
            """,
            (rater, body.secondary_rating, body.secondary_note, outcome, review_id, tenant_id),
        )

        cur.execute(_select_template(cur) + " WHERE q.id=%s AND q.tenant_id=%s",
                    (review_id, tenant_id))
        row = cur.fetchone()
    return _row_to_model(row)


# ---------------------------------------------------------------------------
# PUT /api/qa-reviews/{id}/tier2
# ---------------------------------------------------------------------------


@router.put("/{review_id}/tier2", response_model=QAReview)
def adjudicate_tier2(
    review_id: int,
    body: Tier2ReviewPayload,
    current_user: dict = Depends(require_permission("qa_review", "write")),
    tenant_id: str = Depends(get_tenant_id),
) -> QAReview:
    rater = _user_id(current_user)
    with raf_cursor() as cur:
        cur.execute(
            "SELECT * FROM raf_qa_reviews WHERE id=%s AND tenant_id=%s",
            (review_id, tenant_id),
        )
        existing = cur.fetchone()
        if not existing:
            raise HTTPException(404, "qa review not found")
        if existing["final_outcome"] != "escalated":
            raise HTTPException(
                409, "tier2 adjudication only valid for escalated reviews"
            )
        # A tier-2 reviewer must be a third distinct human.
        if rater in (
            existing.get("primary_rater_user_id"),
            existing.get("secondary_rater_user_id"),
        ):
            raise HTTPException(
                403, "tier2 adjudicator must differ from primary and secondary raters"
            )

        outcome = _resolve_tier2_outcome(body.tier2_rating)

        cur.execute(
            """
            UPDATE raf_qa_reviews
               SET tier2_rater_user_id=%s,
                   tier2_rating=%s,
                   tier2_note=%s,
                   final_outcome=%s
             WHERE id=%s AND tenant_id=%s
            """,
            (rater, body.tier2_rating, body.tier2_note, outcome, review_id, tenant_id),
        )

        cur.execute(_select_template(cur) + " WHERE q.id=%s AND q.tenant_id=%s",
                    (review_id, tenant_id))
        row = cur.fetchone()
    return _row_to_model(row)


# ---------------------------------------------------------------------------
# GET /api/qa-reviews
# ---------------------------------------------------------------------------


@router.get("", response_model=ListResponse)
def list_reviews(
    outcome: Outcome | None = Query(
        default=None,
        description="Filter by final_outcome. Omit for all rows.",
    ),
    closed_today: bool = Query(
        default=False,
        description="If true, only accepted/rejected rows updated today (UTC).",
    ),
    limit: int = Query(default=200, ge=1, le=1000),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> ListResponse:
    where = ["q.tenant_id = %s"]
    params: list[Any] = [tenant_id]
    if outcome:
        where.append("q.final_outcome = %s")
        params.append(outcome)
    if closed_today:
        where.append("q.final_outcome IN ('accepted','rejected')")
        where.append("DATE(q.updated_at) = CURDATE()")
    params.append(limit)

    with raf_cursor() as cur:
        sql = (
            _select_template(cur)
            + " WHERE " + " AND ".join(where)
            + " ORDER BY q.updated_at DESC, q.id DESC LIMIT %s"
        )
        cur.execute(sql, tuple(params))
        rows = cur.fetchall() or []
    items = [_row_to_model(r) for r in rows]
    return ListResponse(items=items, total=len(items))


# ---------------------------------------------------------------------------
# GET /api/qa-reviews/{id}
# ---------------------------------------------------------------------------


@router.get("/{review_id}", response_model=QAReview)
def get_review(
    review_id: int,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> QAReview:
    with raf_cursor() as cur:
        cur.execute(
            _select_template(cur) + " WHERE q.id=%s AND q.tenant_id=%s",
            (review_id, tenant_id),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(404, "qa review not found")
    return _row_to_model(row)
