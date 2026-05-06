"""Evidence-rules router.

Endpoints:
  POST /api/kg/evidence-rules/evaluate
  GET  /api/kg/evidence-rules
  GET  /api/kg/evidence-rules/{rule_id}
  GET  /api/kg/evidence-rules/sources/{source_type}
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.knowledge_graph.evidence_rules_engine import (
    evaluate_evidence,
    get_rule,
    get_rules_by_hcc,
    get_rules_by_source,
    list_rules,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/kg/evidence-rules", tags=["knowledge-graph"])


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class EvaluateRequest(BaseModel):
    """Body for /evaluate."""

    evidence: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Dict containing optional keys: 'icd10' (list of code strings), "
            "'atc' (list of medication ATC codes), 'loinc' (list of "
            "{code,value} dicts), 'notes' (list of free-text strings)."
        ),
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/evaluate", summary="Evaluate evidence against all curated rules")
def post_evaluate(req: EvaluateRequest) -> dict[str, Any]:
    """Run all active literature-backed rules against the supplied evidence.

    Returns the matched rules with full source attribution.
    """
    try:
        matches = evaluate_evidence(req.evidence or {})
    except TypeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "count": len(matches),
        "matches": matches,
    }


@router.get("", summary="List curated evidence rules (optionally filter by HCC)")
def get_rules(
    hcc: Optional[str] = Query(default=None, description="Filter by output HCC code"),
) -> dict[str, Any]:
    if hcc is not None:
        rules = get_rules_by_hcc(hcc)
    else:
        rules = list_rules()
    return {"count": len(rules), "rules": rules}


@router.get("/sources/{source_type}", summary="List rules for a given source_type")
def get_rules_by_source_endpoint(source_type: str) -> dict[str, Any]:
    rules = get_rules_by_source(source_type)
    if not rules:
        raise HTTPException(
            status_code=404,
            detail=f"No rules with source_type={source_type!r}",
        )
    return {"count": len(rules), "rules": rules}


@router.get("/{rule_id}", summary="Get a single curated rule by id")
def get_rule_by_id(rule_id: int) -> dict[str, Any]:
    rule = get_rule(rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail=f"Rule {rule_id} not found")
    return rule
