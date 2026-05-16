"""
Suspect-feedback router — clinician thumbs-up / thumbs-down on AI suspects.

Endpoint
--------
POST /api/suspects/{suspect_id}/feedback
  Body: { sentiment: 'helpful' | 'incorrect' | 'irrelevant', comment?: str }
  Auth: Bearer token (get_current_user) — tenant_id extracted server-side.
  Rate: 1 feedback per (user, suspect) per calendar day; 409 on duplicate.
  Returns: 201 { id: int }
"""

from __future__ import annotations

import logging
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.auth import get_current_user, get_tenant_id
from app.db import raf_cursor

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/suspects", tags=["suspect-feedback"])

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

SentimentLiteral = Literal["helpful", "incorrect", "irrelevant"]


class FeedbackIn(BaseModel):
    sentiment: SentimentLiteral = Field(
        ..., description="Clinician assessment of the AI suggestion."
    )
    comment: Optional[str] = Field(
        None, max_length=2000, description="Optional free-text elaboration."
    )


class FeedbackOut(BaseModel):
    id: int


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post(
    "/{suspect_id}/feedback",
    response_model=FeedbackOut,
    status_code=status.HTTP_201_CREATED,
    summary="Submit clinician feedback on an AI suspect",
)
def submit_feedback(
    suspect_id: str,
    body: FeedbackIn,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> FeedbackOut:
    """Persist a clinician's sentiment on a suspect condition.

    One feedback row is allowed per user per suspect per UTC calendar day.
    A 409 is returned if the user already submitted feedback today.
    """
    user_id: int = current_user["id"]

    with raf_cursor() as cur:
        # Duplicate check — 1 per (user, suspect) per day.
        cur.execute(
            """
            SELECT id FROM suspect_feedback
            WHERE  tenant_id  = %s
              AND  suspect_id = %s
              AND  user_id    = %s
              AND  DATE(created_at) = CURDATE()
            LIMIT 1
            """,
            (tenant_id, suspect_id, user_id),
        )
        if cur.fetchone():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="You have already submitted feedback for this suspect today.",
            )

        cur.execute(
            """
            INSERT INTO suspect_feedback (suspect_id, tenant_id, user_id, sentiment, comment)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (suspect_id, tenant_id, user_id, body.sentiment, body.comment),
        )
        new_id: int = cur.lastrowid

    logger.info(
        "suspect_feedback created id=%s suspect=%s tenant=%s user=%s sentiment=%s",
        new_id,
        suspect_id,
        tenant_id,
        user_id,
        body.sentiment,
    )
    return FeedbackOut(id=new_id)
