"""
Review Queue router — unified coder workspace for AI-produced work items.

The /review-queue UI consumes these endpoints. It merges three classes
of items under one queue:

* ``hcc_candidate``   — NLP-extracted HCC candidates pending confirmation
* ``suspect``         — suspect-engine-generated suspect conditions
* ``provider_query``  — provider-query items awaiting resolution

Endpoints
---------
GET  /api/review/candidates
POST /api/review/decision
"""
# Deliberately avoid ``from __future__ import annotations`` — FastAPI/Pydantic
# schema generation dislikes it in routers.

import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from app.auth import get_current_user, get_tenant_id
from app.db import raf_cursor
from app.middleware.idempotency import idempotency_key_dependency, store_idempotent_response
from app.services import audit as audit_svc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/review", tags=["review-queue"])


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

ItemKind = Literal["hcc_candidate", "suspect", "provider_query"]
Decision = Literal["accept", "reject", "edit"]


class ReviewItem(BaseModel):
    id: str                       # "<kind>:<numeric-id>"
    kind: ItemKind
    patient_id: int
    patient_name: str | None = None
    hcc: int | None = None
    icd10: str | None = None
    condition: str | None = None
    confidence: float | None = None
    evidence_snippet: str | None = None
    evidence_source_id: int | None = None   # document / note id for deep-link
    evidence_span: tuple[int, int] | None = None
    meat: dict[str, bool] | None = None     # {"monitor": true, "evaluate": ...}
    status: str = "open"
    created_at: str | None = None


class CandidatesResponse(BaseModel):
    items: list[ReviewItem]
    total: int


class DecisionRequest(BaseModel):
    candidate_id: str = Field(..., description="Composite id '<kind>:<numeric>'")
    decision: Decision
    notes: str | None = None
    edited_icd10: str | None = Field(
        default=None,
        description="Required when decision == 'edit'",
    )


class DecisionResponse(BaseModel):
    ok: bool
    audit_id: int | None = None


# ---------------------------------------------------------------------------
# GET /api/review/candidates
# ---------------------------------------------------------------------------

@router.get("/candidates", response_model=CandidatesResponse)
def list_candidates(
    kind: ItemKind | None = Query(default=None),
    status: str = Query(default="open"),
    limit: int = Query(default=200, ge=1, le=1000),
    sort_by: str | None = Query(default=None, description="Ignored — reserved for future use"),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> CandidatesResponse:
    items: list[ReviewItem] = []
    with raf_cursor() as cur:
        # --- suspects --------------------------------------------------------
        # form_suspects has no tenant_id column; scope via patients subquery.
        # Wrapped in try/except so a missing table doesn't fail the whole call.
        if kind in (None, "suspect"):
            try:
                # Join the patient name from raf_intelligence.patients (where
                # auto_sync mirrors first_name/last_name from OpenEMR) instead
                # of cross-DB joining openemr.patient_data — the latter
                # silently returns NULL when the MySQL user lacks cross-schema
                # SELECT grants.
                cur.execute(
                    """
                    SELECT s.id, s.patient_id, s.suspect_hcc AS hcc,
                           s.suspect_icd10 AS icd10,
                           s.suspected_condition AS `condition`,
                           s.confidence_score AS confidence,
                           s.trigger_value AS evidence_snippet,
                           s.status, s.created_at,
                           CONCAT_WS(' ', p.first_name, p.last_name) AS patient_name
                      FROM form_suspects s
                      LEFT JOIN patients p ON p.id = s.patient_id
                     WHERE (%s IS NULL OR s.status = %s)
                       AND s.patient_id IN (
                           SELECT id FROM patients WHERE is_active = 1 AND tenant_id = %s
                       )
                     ORDER BY s.confidence_score IS NULL, s.confidence_score DESC, s.id DESC
                     LIMIT %s
                    """,
                    (status or None, status, tenant_id, limit),
                )
                for r in cur.fetchall() or []:
                    items.append(ReviewItem(
                        id=f"suspect:{r['id']}",
                        kind="suspect",
                        patient_id=r["patient_id"],
                        patient_name=r.get("patient_name"),
                        hcc=r.get("hcc"),
                        icd10=r.get("icd10"),
                        condition=r.get("condition"),
                        confidence=r.get("confidence"),
                        evidence_snippet=r.get("evidence_snippet"),
                        status=r.get("status") or "open",
                        created_at=str(r.get("created_at")) if r.get("created_at") else None,
                    ))
            except Exception:
                # Table may not yet exist in all environments — don't fail the call.
                logger.debug("form_suspects query skipped", exc_info=True)

        # --- HCC candidates (from NLP extractions) --------------------------
        # ai_hcc_candidates has no tenant_id column; scope via patients subquery
        if kind in (None, "hcc_candidate"):
            try:
                # See note above on suspect query — same cross-DB hazard.
                cur.execute(
                    """
                    SELECT c.id, c.patient_id, c.hcc, c.icd10,
                           c.condition_label AS `condition`,
                           c.confidence, c.evidence_snippet,
                           c.source_document_id AS evidence_source_id,
                           c.span_start, c.span_end,
                           c.meat_monitor, c.meat_evaluate,
                           c.meat_assess, c.meat_treat,
                           c.status, c.created_at,
                           CONCAT_WS(' ', p.first_name, p.last_name) AS patient_name
                      FROM ai_hcc_candidates c
                      LEFT JOIN patients p ON p.id = c.patient_id
                     WHERE (%s IS NULL OR c.status = %s)
                       AND c.patient_id IN (
                           SELECT id FROM patients WHERE is_active = 1 AND tenant_id = %s
                       )
                     ORDER BY c.confidence IS NULL, c.confidence DESC, c.id DESC
                     LIMIT %s
                    """,
                    (status or None, status, tenant_id, limit),
                )
                for r in cur.fetchall() or []:
                    span = None
                    if r.get("span_start") is not None and r.get("span_end") is not None:
                        span = (int(r["span_start"]), int(r["span_end"]))
                    items.append(ReviewItem(
                        id=f"hcc_candidate:{r['id']}",
                        kind="hcc_candidate",
                        patient_id=r["patient_id"],
                        patient_name=r.get("patient_name"),
                        hcc=r.get("hcc"),
                        icd10=r.get("icd10"),
                        condition=r.get("condition"),
                        confidence=r.get("confidence"),
                        evidence_snippet=r.get("evidence_snippet"),
                        evidence_source_id=r.get("evidence_source_id"),
                        evidence_span=span,
                        meat={
                            "monitor":  bool(r.get("meat_monitor")),
                            "evaluate": bool(r.get("meat_evaluate")),
                            "assess":   bool(r.get("meat_assess")),
                            "treat":    bool(r.get("meat_treat")),
                        },
                        status=r.get("status") or "open",
                        created_at=str(r.get("created_at")) if r.get("created_at") else None,
                    ))
            except Exception:
                # Table may not yet exist in all environments — don't fail the call.
                logger.debug("ai_hcc_candidates query skipped", exc_info=True)

        # --- provider queries ------------------------------------------------
        if kind in (None, "provider_query"):
            try:
                cur.execute(
                    """
                    SELECT q.id, q.patient_id, q.hcc, q.icd10,
                           q.question AS `condition`,
                           q.confidence, q.context_snippet AS evidence_snippet,
                           q.status, q.created_at,
                           CONCAT_WS(' ', p.fname, p.lname) AS patient_name
                      FROM provider_queries q
                      LEFT JOIN patient_data p ON p.pid = q.patient_id
                     WHERE (%s IS NULL OR q.status = %s)
                       AND q.tenant_id = %s
                     ORDER BY q.created_at DESC
                     LIMIT %s
                    """,
                    (status or None, status, tenant_id, limit),
                )
                for r in cur.fetchall() or []:
                    items.append(ReviewItem(
                        id=f"provider_query:{r['id']}",
                        kind="provider_query",
                        patient_id=r["patient_id"],
                        patient_name=r.get("patient_name"),
                        hcc=r.get("hcc"),
                        icd10=r.get("icd10"),
                        condition=r.get("condition"),
                        confidence=r.get("confidence"),
                        evidence_snippet=r.get("evidence_snippet"),
                        status=r.get("status") or "open",
                        created_at=str(r.get("created_at")) if r.get("created_at") else None,
                    ))
            except Exception:
                logger.debug("provider_queries query skipped", exc_info=True)

    return CandidatesResponse(items=items, total=len(items))


# ---------------------------------------------------------------------------
# POST /api/review/decision
# ---------------------------------------------------------------------------

def _split_id(composite: str) -> tuple[ItemKind, int]:
    try:
        kind, raw = composite.split(":", 1)
        if kind not in ("hcc_candidate", "suspect", "provider_query"):
            raise ValueError
        return kind, int(raw)  # type: ignore[return-value]
    except Exception as e:
        raise HTTPException(400, f"invalid candidate_id '{composite}'") from e


_TABLE = {
    "suspect": "form_suspects",
    "hcc_candidate": "ai_hcc_candidates",
    "provider_query": "provider_queries",
}
_ICD_COL = {
    "suspect": "suspect_icd10",
    "hcc_candidate": "icd10",
    "provider_query": "icd10",
}


@router.post("/decision", response_model=DecisionResponse)
def post_decision(
    request: Request,
    response: Response,
    body: DecisionRequest,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _idem: None = Depends(idempotency_key_dependency()),
) -> DecisionResponse:
    kind, numeric_id = _split_id(body.candidate_id)
    if body.decision == "edit" and not body.edited_icd10:
        raise HTTPException(400, "edited_icd10 required for edit decision")

    table = _TABLE[kind]
    icd_col = _ICD_COL[kind]
    new_status = {"accept": "accepted", "reject": "dismissed", "edit": "accepted"}[
        body.decision
    ]

    before: dict[str, Any] = {}
    after: dict[str, Any] = {"status": new_status}

    # provider_queries has tenant_id; form_suspects and ai_hcc_candidates do not —
    # for those, scope via patient subquery to enforce tenant isolation.
    if kind == "provider_query":
        _tenant_select_clause = " AND tenant_id = %s"
        _tenant_select_params: tuple = (numeric_id, tenant_id)
        _tenant_update_clause = " AND tenant_id = %s"
    else:
        _tenant_select_clause = (
            " AND patient_id IN (SELECT id FROM patients WHERE is_active = 1 AND tenant_id = %s)"
        )
        _tenant_select_params = (numeric_id, tenant_id)
        _tenant_update_clause = (
            " AND patient_id IN (SELECT id FROM patients WHERE is_active = 1 AND tenant_id = %s)"
        )

    with raf_cursor() as cur:
        # fetch before-state for audit
        try:
            cur.execute(
                f"SELECT status, {icd_col} AS icd10 FROM {table} WHERE id=%s{_tenant_select_clause}",
                _tenant_select_params,
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "review item not found")
            before = {"status": row.get("status"), "icd10": row.get("icd10")}
        except HTTPException:
            raise
        except Exception as e:
            logger.exception("review decision lookup failed")
            raise HTTPException(500, "review item lookup failed") from e

        reviewer = str(current_user.get("username") or
                       current_user.get("email") or
                       current_user.get("sub"))
        # update
        if body.decision == "edit":
            cur.execute(
                f"UPDATE {table} SET status=%s, {icd_col}=%s, "
                f"reviewed_at=NOW(), reviewed_by=%s WHERE id=%s{_tenant_update_clause}",
                (new_status, body.edited_icd10, reviewer, numeric_id, tenant_id),
            )
            after["icd10"] = body.edited_icd10
        else:
            cur.execute(
                f"UPDATE {table} SET status=%s, reviewed_at=NOW(), "
                f"reviewed_by=%s WHERE id=%s{_tenant_update_clause}",
                (new_status, reviewer, numeric_id, tenant_id),
            )

    action = {
        "accept": audit_svc.CODER_ACCEPT,
        "reject": audit_svc.CODER_REJECT,
        "edit":   audit_svc.CODER_EDIT,
    }[body.decision]

    audit_id = audit_svc.log_event(
        tenant_id=tenant_id,
        action=action,
        actor_type="user",
        actor_id=str(current_user.get("sub") or current_user.get("email") or
                     current_user.get("username") or "unknown"),
        target_type=kind,
        target_id=numeric_id,
        before=before,
        after={**after, "notes": body.notes} if body.notes else after,
    )
    result = DecisionResponse(ok=True, audit_id=audit_id)
    store_idempotent_response(request, response, result.model_dump())
    return result
