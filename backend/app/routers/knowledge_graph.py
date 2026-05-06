"""
Knowledge graph router — read/search/admin-write endpoints over
``knowledge_graph_concepts`` and ``knowledge_graph_edges``.

Routes
------
GET  /api/kg/stats                       Summary counts (concepts, edges, by_ontology, by_edge_type)
GET  /api/kg/concepts/search             Search by label, optionally filtered by ontology
GET  /api/kg/concepts/by-uri/{uri:path}  Fetch by stable concept_uri
GET  /api/kg/concepts/{concept_id}       Fetch by primary key
GET  /api/kg/concepts/{concept_id}/edges Outgoing edges, optionally filtered by edge_type
POST /api/kg/concepts                    Admin upsert (auth: admin only)
POST /api/kg/edges                       Admin upsert (auth: admin only)

Notes
-----
* The auth dependency (`require_admin`) is best-effort: if ``app.auth`` exposes
  ``require_role`` we use it; otherwise we fall back to a no-op stub so this
  router still works in worktree branches that pre-date the auth scaffolding.
  Production deployments are expected to provide ``require_role``.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.knowledge_graph import kg_repository as repo
from app.services.knowledge_graph.kg_schema import (
    EDGE_TYPES,
    ONTOLOGIES,
    Concept,
    Edge,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/kg", tags=["knowledge_graph"])


# ---------------------------------------------------------------------------
# Auth shim — admin only for write endpoints.
# ---------------------------------------------------------------------------


def _resolve_admin_dep() -> Callable[..., Any]:
    """Return a FastAPI dependency that gates on admin role if available."""
    try:
        from app.auth import require_role  # type: ignore[attr-defined]

        return require_role("admin")
    except Exception:  # pragma: no cover — fallback for older worktrees
        async def _noop() -> dict[str, Any]:
            return {"role": "admin", "stub": True}

        return _noop


require_admin = _resolve_admin_dep()


# ---------------------------------------------------------------------------
# Pydantic request / response models
# ---------------------------------------------------------------------------


class ConceptIn(BaseModel):
    ontology: str = Field(..., description=f"One of {ONTOLOGIES}")
    code: str = Field(..., min_length=1, max_length=64)
    preferred_label: str = Field(..., min_length=1, max_length=500)
    concept_uri: str | None = None
    definition: str | None = None
    semantic_type: str | None = Field(default=None, max_length=100)
    is_active: bool = True
    metadata: dict[str, Any] | None = None


class ConceptOut(BaseModel):
    id: int
    concept_uri: str
    ontology: str
    code: str
    preferred_label: str
    definition: str | None = None
    semantic_type: str | None = None
    is_active: bool
    metadata: dict[str, Any] | None = None


class EdgeIn(BaseModel):
    src_concept_id: int
    dst_concept_id: int
    edge_type: str = Field(..., min_length=1, max_length=64)
    weight: float = Field(default=1.0, ge=0.0, le=1.0)
    source: str | None = Field(default=None, max_length=80)
    evidence_url: str | None = Field(default=None, max_length=500)
    metadata: dict[str, Any] | None = None


class EdgeOut(BaseModel):
    id: int
    src_concept_id: int
    dst_concept_id: int
    edge_type: str
    weight: float
    source: str | None = None
    evidence_url: str | None = None
    metadata: dict[str, Any] | None = None


def _concept_to_out(c: Concept) -> ConceptOut:
    if c.id is None:
        raise RuntimeError("Concept is missing primary key")
    return ConceptOut(
        id=c.id,
        concept_uri=c.concept_uri or f"{c.ontology}:{c.code}",
        ontology=c.ontology,
        code=c.code,
        preferred_label=c.preferred_label,
        definition=c.definition,
        semantic_type=c.semantic_type,
        is_active=c.is_active,
        metadata=c.metadata,
    )


def _edge_to_out(e: Edge) -> EdgeOut:
    if e.id is None:
        raise RuntimeError("Edge is missing primary key")
    return EdgeOut(
        id=e.id,
        src_concept_id=e.src_concept_id,
        dst_concept_id=e.dst_concept_id,
        edge_type=e.edge_type,
        weight=float(e.weight),
        source=e.source,
        evidence_url=e.evidence_url,
        metadata=e.metadata,
    )


# ---------------------------------------------------------------------------
# Read endpoints
# ---------------------------------------------------------------------------


@router.get("/stats", summary="Knowledge graph summary counts")
def get_stats() -> dict[str, Any]:
    return repo.stats()


@router.get(
    "/concepts/search",
    response_model=list[ConceptOut],
    summary="Full-text search over concept labels",
)
def search_concepts(
    q: str = Query(..., min_length=1, description="Substring to match against preferred_label"),
    ontology: str | None = Query(default=None, description=f"Filter to one of {ONTOLOGIES}"),
    limit: int = Query(default=50, ge=1, le=500),
) -> list[ConceptOut]:
    if ontology and ontology not in ONTOLOGIES:
        raise HTTPException(status_code=422, detail=f"Unknown ontology {ontology!r}")
    results = repo.search_concepts(query=q, ontology=ontology, limit=limit)
    return [_concept_to_out(c) for c in results]


@router.get(
    "/concepts/by-uri/{uri:path}",
    response_model=ConceptOut,
    summary="Fetch a concept by its stable URI (e.g. icd10:E11.9)",
)
def get_concept_by_uri(uri: str) -> ConceptOut:
    c = repo.find_by_uri(uri)
    if c is None:
        raise HTTPException(status_code=404, detail=f"No concept with URI {uri!r}")
    return _concept_to_out(c)


@router.get(
    "/concepts/{concept_id}",
    response_model=ConceptOut,
    summary="Fetch a concept by primary key",
)
def get_concept(concept_id: int) -> ConceptOut:
    c = repo.find_by_id(concept_id)
    if c is None:
        raise HTTPException(status_code=404, detail=f"No concept with id {concept_id}")
    return _concept_to_out(c)


@router.get(
    "/concepts/{concept_id}/edges",
    response_model=list[EdgeOut],
    summary="Outgoing edges from a concept",
)
def get_concept_edges(
    concept_id: int,
    type: str | None = Query(default=None, description="Filter by edge_type"),
) -> list[EdgeOut]:
    if repo.find_by_id(concept_id) is None:
        raise HTTPException(status_code=404, detail=f"No concept with id {concept_id}")
    edges = repo.outgoing_edges(concept_id, edge_type=type)
    return [_edge_to_out(e) for e in edges]


# ---------------------------------------------------------------------------
# Admin write endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/concepts",
    response_model=ConceptOut,
    summary="Admin: idempotently create or update a concept",
)
def post_concept(
    payload: ConceptIn,
    _admin: Any = Depends(require_admin),
) -> ConceptOut:
    if payload.ontology not in ONTOLOGIES:
        raise HTTPException(status_code=422, detail=f"Unknown ontology {payload.ontology!r}")
    try:
        concept = Concept(**payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    repo.upsert_concept(concept)
    return _concept_to_out(concept)


@router.post(
    "/edges",
    response_model=EdgeOut,
    summary="Admin: idempotently create or update an edge",
)
def post_edge(
    payload: EdgeIn,
    _admin: Any = Depends(require_admin),
) -> EdgeOut:
    if repo.find_by_id(payload.src_concept_id) is None:
        raise HTTPException(
            status_code=422,
            detail=f"src_concept_id {payload.src_concept_id} not found",
        )
    if repo.find_by_id(payload.dst_concept_id) is None:
        raise HTTPException(
            status_code=422,
            detail=f"dst_concept_id {payload.dst_concept_id} not found",
        )
    try:
        edge = Edge(**payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    repo.upsert_edge(edge)
    return _edge_to_out(edge)


# ---------------------------------------------------------------------------
# Vocabulary echo (helps frontend wire up dropdowns without hard-coding)
# ---------------------------------------------------------------------------


@router.get("/vocabulary", summary="Allowed ontologies and bootstrap edge types")
def get_vocabulary() -> dict[str, Any]:
    return {
        "ontologies": list(ONTOLOGIES),
        "edge_types": list(EDGE_TYPES),
    }
