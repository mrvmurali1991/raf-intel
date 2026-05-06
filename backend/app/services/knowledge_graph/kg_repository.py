"""
Knowledge graph repository — CRUD against ``knowledge_graph_concepts`` and
``knowledge_graph_edges`` in the ``raf_intelligence`` database.

Design goals
------------
* All write operations are idempotent (INSERT ... ON DUPLICATE KEY UPDATE).
* Reads return the dataclasses defined in :mod:`kg_schema` rather than raw
  rows so callers do not have to know the column layout.
* No coupling to FastAPI / Pydantic — this module is usable from CLI tools
  and Celery jobs.
"""
from __future__ import annotations

import json
import logging
from collections import deque
from typing import Any, Iterable

from app.db import raf_cursor
from app.services.knowledge_graph.kg_schema import Concept, Edge

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _row_to_concept(row: dict[str, Any]) -> Concept:
    """Convert a ``knowledge_graph_concepts`` row dict to a :class:`Concept`."""
    md = row.get("metadata")
    if isinstance(md, (bytes, bytearray)):
        md = md.decode("utf-8")
    if isinstance(md, str) and md:
        try:
            md = json.loads(md)
        except json.JSONDecodeError:
            md = None
    return Concept(
        id=row["id"],
        concept_uri=row["concept_uri"],
        ontology=row["ontology"],
        code=row["code"],
        preferred_label=row["preferred_label"],
        definition=row.get("definition"),
        semantic_type=row.get("semantic_type"),
        is_active=bool(row.get("is_active", 1)),
        metadata=md if isinstance(md, dict) else None,
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


def _row_to_edge(row: dict[str, Any]) -> Edge:
    md = row.get("metadata")
    if isinstance(md, (bytes, bytearray)):
        md = md.decode("utf-8")
    if isinstance(md, str) and md:
        try:
            md = json.loads(md)
        except json.JSONDecodeError:
            md = None
    return Edge(
        id=row["id"],
        src_concept_id=row["src_concept_id"],
        dst_concept_id=row["dst_concept_id"],
        edge_type=row["edge_type"],
        weight=float(row["weight"]) if row.get("weight") is not None else 1.0,
        source=row.get("source"),
        evidence_url=row.get("evidence_url"),
        metadata=md if isinstance(md, dict) else None,
        created_at=row.get("created_at"),
    )


def _dump_metadata(metadata: dict[str, Any] | None) -> str | None:
    if metadata is None:
        return None
    return json.dumps(metadata, sort_keys=True, default=str)


# ---------------------------------------------------------------------------
# Concept CRUD
# ---------------------------------------------------------------------------


def upsert_concept(concept: Concept) -> int:
    """
    Idempotent insert/update keyed on the (ontology, code) unique index.

    Returns the concept's primary key.
    """
    metadata_json = _dump_metadata(concept.metadata)
    sql = """
        INSERT INTO knowledge_graph_concepts
            (concept_uri, ontology, code, preferred_label, definition,
             semantic_type, is_active, metadata)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            concept_uri      = VALUES(concept_uri),
            preferred_label  = VALUES(preferred_label),
            definition       = VALUES(definition),
            semantic_type    = VALUES(semantic_type),
            is_active        = VALUES(is_active),
            metadata         = VALUES(metadata),
            id               = LAST_INSERT_ID(id)
    """
    params = (
        concept.concept_uri,
        concept.ontology,
        concept.code,
        concept.preferred_label,
        concept.definition,
        concept.semantic_type,
        1 if concept.is_active else 0,
        metadata_json,
    )
    with raf_cursor(dictionary=True) as cur:
        cur.execute(sql, params)
        cid = cur.lastrowid
    if cid is None:
        # Fall back to a SELECT in the rare event the connector did not give us
        # lastrowid (older MySQL drivers). Should never happen with the
        # LAST_INSERT_ID(id) trick, but kept for safety.
        existing = find_by_code(concept.ontology, concept.code)
        if existing is None or existing.id is None:
            raise RuntimeError("upsert_concept failed to resolve primary key")
        cid = existing.id
    concept.id = cid
    return cid


def bulk_upsert_concepts(concepts: Iterable[Concept]) -> list[int]:
    """Apply :func:`upsert_concept` to many concepts. Returns their ids."""
    return [upsert_concept(c) for c in concepts]


def find_by_id(concept_id: int) -> Concept | None:
    with raf_cursor(dictionary=True) as cur:
        cur.execute(
            "SELECT * FROM knowledge_graph_concepts WHERE id = %s",
            (concept_id,),
        )
        row = cur.fetchone()
    return _row_to_concept(row) if row else None


def find_by_uri(uri: str) -> Concept | None:
    with raf_cursor(dictionary=True) as cur:
        cur.execute(
            "SELECT * FROM knowledge_graph_concepts WHERE concept_uri = %s LIMIT 1",
            (uri,),
        )
        row = cur.fetchone()
    return _row_to_concept(row) if row else None


def find_by_code(ontology: str, code: str) -> Concept | None:
    with raf_cursor(dictionary=True) as cur:
        cur.execute(
            "SELECT * FROM knowledge_graph_concepts "
            "WHERE ontology = %s AND code = %s",
            (ontology, code),
        )
        row = cur.fetchone()
    return _row_to_concept(row) if row else None


def search_concepts(
    query: str,
    ontology: str | None = None,
    limit: int = 50,
) -> list[Concept]:
    """Case-insensitive prefix/substring search over ``preferred_label``."""
    sql = (
        "SELECT * FROM knowledge_graph_concepts "
        "WHERE preferred_label LIKE %s "
    )
    params: list[Any] = [f"%{query}%"]
    if ontology:
        sql += "AND ontology = %s "
        params.append(ontology)
    sql += "ORDER BY preferred_label LIMIT %s"
    params.append(int(limit))
    with raf_cursor(dictionary=True) as cur:
        cur.execute(sql, tuple(params))
        rows = cur.fetchall() or []
    return [_row_to_concept(r) for r in rows]


def delete_concept(concept_id: int) -> bool:
    """Delete a concept (cascades to its edges via FK). Returns True on hit."""
    with raf_cursor(dictionary=True) as cur:
        cur.execute(
            "DELETE FROM knowledge_graph_concepts WHERE id = %s",
            (concept_id,),
        )
        return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Edge CRUD
# ---------------------------------------------------------------------------


def upsert_edge(edge: Edge) -> int:
    """
    Idempotent insert/update keyed on (src_concept_id, dst_concept_id, edge_type).

    Returns the edge's primary key.
    """
    metadata_json = _dump_metadata(edge.metadata)
    sql = """
        INSERT INTO knowledge_graph_edges
            (src_concept_id, dst_concept_id, edge_type, weight,
             source, evidence_url, metadata)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            weight       = VALUES(weight),
            source       = VALUES(source),
            evidence_url = VALUES(evidence_url),
            metadata     = VALUES(metadata),
            id           = LAST_INSERT_ID(id)
    """
    params = (
        int(edge.src_concept_id),
        int(edge.dst_concept_id),
        edge.edge_type,
        float(edge.weight),
        edge.source,
        edge.evidence_url,
        metadata_json,
    )
    with raf_cursor(dictionary=True) as cur:
        cur.execute(sql, params)
        eid = cur.lastrowid
    if eid is None:
        with raf_cursor(dictionary=True) as cur:
            cur.execute(
                "SELECT id FROM knowledge_graph_edges "
                "WHERE src_concept_id = %s AND dst_concept_id = %s "
                "AND edge_type = %s",
                (edge.src_concept_id, edge.dst_concept_id, edge.edge_type),
            )
            row = cur.fetchone()
            eid = row["id"] if row else None
    if eid is None:
        raise RuntimeError("upsert_edge failed to resolve primary key")
    edge.id = eid
    return eid


def bulk_upsert_edges(edges: Iterable[Edge]) -> list[int]:
    return [upsert_edge(e) for e in edges]


def outgoing_edges(
    src_id: int,
    edge_type: str | None = None,
) -> list[Edge]:
    sql = "SELECT * FROM knowledge_graph_edges WHERE src_concept_id = %s "
    params: list[Any] = [src_id]
    if edge_type:
        sql += "AND edge_type = %s "
        params.append(edge_type)
    sql += "ORDER BY id"
    with raf_cursor(dictionary=True) as cur:
        cur.execute(sql, tuple(params))
        rows = cur.fetchall() or []
    return [_row_to_edge(r) for r in rows]


def incoming_edges(
    dst_id: int,
    edge_type: str | None = None,
) -> list[Edge]:
    sql = "SELECT * FROM knowledge_graph_edges WHERE dst_concept_id = %s "
    params: list[Any] = [dst_id]
    if edge_type:
        sql += "AND edge_type = %s "
        params.append(edge_type)
    sql += "ORDER BY id"
    with raf_cursor(dictionary=True) as cur:
        cur.execute(sql, tuple(params))
        rows = cur.fetchall() or []
    return [_row_to_edge(r) for r in rows]


# ---------------------------------------------------------------------------
# Traversal
# ---------------------------------------------------------------------------


def traverse(
    start_id: int,
    edge_types: Iterable[str] | None = None,
    max_depth: int = 2,
) -> list[dict[str, Any]]:
    """
    Breadth-first traversal from ``start_id`` following outgoing edges whose
    ``edge_type`` is in ``edge_types`` (or any type if ``edge_types`` is
    None / empty).

    Returns a list of records of the form::

        {"concept": Concept, "depth": int, "via_edge": Edge | None}

    The starting node is included at depth 0 with ``via_edge=None``. The
    traversal terminates when ``depth > max_depth`` or no new nodes are
    discovered. Each concept appears at most once (the shortest path wins).
    """
    if max_depth < 0:
        raise ValueError("max_depth must be >= 0")

    start = find_by_id(start_id)
    if start is None:
        return []

    types_set: set[str] | None = set(edge_types) if edge_types else None
    visited: dict[int, dict[str, Any]] = {
        start_id: {"concept": start, "depth": 0, "via_edge": None}
    }
    queue: deque[int] = deque([start_id])
    out: list[dict[str, Any]] = [visited[start_id]]

    while queue:
        current_id = queue.popleft()
        current_depth = visited[current_id]["depth"]
        if current_depth >= max_depth:
            continue
        edges = outgoing_edges(current_id)
        for e in edges:
            if types_set is not None and e.edge_type not in types_set:
                continue
            if e.dst_concept_id in visited:
                continue
            dst = find_by_id(e.dst_concept_id)
            if dst is None:
                continue
            record = {
                "concept": dst,
                "depth": current_depth + 1,
                "via_edge": e,
            }
            visited[e.dst_concept_id] = record
            out.append(record)
            queue.append(e.dst_concept_id)
    return out


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


def stats() -> dict[str, Any]:
    """Return high-level counts for /api/kg/stats."""
    with raf_cursor(dictionary=True) as cur:
        cur.execute("SELECT COUNT(*) AS n FROM knowledge_graph_concepts")
        concepts = int((cur.fetchone() or {"n": 0})["n"])

        cur.execute("SELECT COUNT(*) AS n FROM knowledge_graph_edges")
        edges = int((cur.fetchone() or {"n": 0})["n"])

        cur.execute(
            "SELECT ontology, COUNT(*) AS n FROM knowledge_graph_concepts "
            "GROUP BY ontology"
        )
        by_ontology = {r["ontology"]: int(r["n"]) for r in (cur.fetchall() or [])}

        cur.execute(
            "SELECT edge_type, COUNT(*) AS n FROM knowledge_graph_edges "
            "GROUP BY edge_type"
        )
        by_edge_type = {r["edge_type"]: int(r["n"]) for r in (cur.fetchall() or [])}

    return {
        "concepts": concepts,
        "edges": edges,
        "by_ontology": by_ontology,
        "by_edge_type": by_edge_type,
    }
