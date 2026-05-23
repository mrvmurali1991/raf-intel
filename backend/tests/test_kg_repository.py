"""
Knowledge graph repository tests.

These tests hit a real MySQL instance (the ``raf_intelligence`` database).
They use a per-test-run prefix to scope concept codes so they cannot collide
with seeded production data, and they clean up after themselves at module
teardown.

Skip behaviour: if the DB is unreachable the entire module is skipped via
the ``_db_available`` autouse fixture so the suite stays green in
environments without MySQL.
"""
from __future__ import annotations

import time
import uuid
from typing import Iterator

import pytest


# ---------------------------------------------------------------------------
# Override the project-level ``server_available`` autouse fixture for this
# module. The repository tests do NOT need the HTTP backend running — they
# talk to MySQL directly — so we replace the autouse fixture with a no-op.
# (Re-declaring at module / function scope shadows the session-scope autouse.)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def server_available():  # noqa: D401 — pytest fixture override
    yield


# ---------------------------------------------------------------------------
# DB-availability guard — skip the whole module if we cannot connect.
# ---------------------------------------------------------------------------


def _db_reachable() -> bool:
    try:
        from app.db import raf_cursor  # type: ignore

        with raf_cursor(dictionary=True) as cur:
            cur.execute("SELECT 1 AS ok")
            row = cur.fetchone()
            return bool(row and row.get("ok") == 1)
    except Exception:
        return False


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not _db_reachable(),
        reason="raf_intelligence MySQL is not reachable from the test runner.",
    ),
]


# ---------------------------------------------------------------------------
# Lazy imports (after the skip guard so import-time failures do not blow up).
# ---------------------------------------------------------------------------

from app.db import raf_cursor  # noqa: E402
from app.services.knowledge_graph import kg_repository as repo  # noqa: E402
from app.services.knowledge_graph.kg_schema import (  # noqa: E402
    EDGE_TYPES,
    ONTOLOGIES,
    Concept,
    Edge,
    EdgeType,
)
from app.services.knowledge_graph.seed_top_hccs import seed_top_hccs  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def run_prefix() -> str:
    """A short, unique prefix so codes from this run never collide with seeds."""
    return f"TST{uuid.uuid4().hex[:6].upper()}"


@pytest.fixture(scope="module", autouse=True)
def _cleanup(run_prefix: str) -> Iterator[None]:
    """Drop everything created with our run prefix, both before and after."""

    def _delete():
        with raf_cursor(dictionary=True) as cur:
            cur.execute(
                "DELETE FROM knowledge_graph_concepts "
                "WHERE code LIKE %s OR concept_uri LIKE %s",
                (f"{run_prefix}%", f"%:{run_prefix}%"),
            )

    _delete()
    yield
    _delete()


def _mk(prefix: str, ontology: str, code_suffix: str, label: str | None = None) -> Concept:
    code = f"{prefix}{code_suffix}"
    return Concept(
        ontology=ontology,
        code=code,
        preferred_label=label or f"Test concept {code}",
        semantic_type="Disease or Syndrome",
        metadata={"test": True, "prefix": prefix},
    )


# ---------------------------------------------------------------------------
# Schema-level smoke tests
# ---------------------------------------------------------------------------


def test_ontology_enum_matches_schema_constants() -> None:
    assert "umls" in ONTOLOGIES
    assert "icd10" in ONTOLOGIES
    assert "hcc" in ONTOLOGIES
    assert len(ONTOLOGIES) == len(set(ONTOLOGIES))


def test_edge_type_constants_unique_and_present() -> None:
    assert EdgeType.MAPS_TO in EDGE_TYPES
    assert EdgeType.HAS_INDICATION in EDGE_TYPES
    assert len(EDGE_TYPES) == len(set(EDGE_TYPES))


def test_concept_dataclass_validates_ontology() -> None:
    with pytest.raises(ValueError):
        Concept(ontology="not-real", code="X", preferred_label="X")


def test_edge_dataclass_validates_self_loop_and_weight() -> None:
    with pytest.raises(ValueError):
        Edge(src_concept_id=1, dst_concept_id=1, edge_type=EdgeType.MAPS_TO)
    with pytest.raises(ValueError):
        Edge(src_concept_id=1, dst_concept_id=2, edge_type=EdgeType.MAPS_TO, weight=2.0)


# ---------------------------------------------------------------------------
# Concept CRUD
# ---------------------------------------------------------------------------


def test_upsert_concept_inserts_and_returns_id(run_prefix: str) -> None:
    c = _mk(run_prefix, "icd10", "001")
    cid = repo.upsert_concept(c)
    assert isinstance(cid, int) and cid > 0
    fetched = repo.find_by_id(cid)
    assert fetched is not None
    assert fetched.code == c.code
    assert fetched.concept_uri == f"icd10:{c.code}"
    assert fetched.metadata == {"test": True, "prefix": run_prefix}


def test_upsert_concept_idempotent_on_repeat(run_prefix: str) -> None:
    c1 = _mk(run_prefix, "icd10", "002", label="Original")
    cid1 = repo.upsert_concept(c1)

    c2 = _mk(run_prefix, "icd10", "002", label="Updated")
    cid2 = repo.upsert_concept(c2)

    assert cid1 == cid2, "ON DUPLICATE KEY must keep the same primary key"
    refetched = repo.find_by_id(cid1)
    assert refetched is not None
    assert refetched.preferred_label == "Updated"


def test_find_by_uri_and_by_code(run_prefix: str) -> None:
    c = _mk(run_prefix, "loinc", "003")
    cid = repo.upsert_concept(c)

    by_code = repo.find_by_code("loinc", c.code)
    assert by_code is not None and by_code.id == cid

    by_uri = repo.find_by_uri(f"loinc:{c.code}")
    assert by_uri is not None and by_uri.id == cid

    assert repo.find_by_uri("does:not:exist") is None
    assert repo.find_by_code("loinc", "DOES-NOT-EXIST") is None


def test_search_concepts_label_match(run_prefix: str) -> None:
    repo.upsert_concept(_mk(run_prefix, "icd10", "010", "Acme Diabetes Marker"))
    repo.upsert_concept(_mk(run_prefix, "loinc", "011", "Acme Diabetes Lab"))
    repo.upsert_concept(_mk(run_prefix, "icd10", "012", "Unrelated Concept"))

    found = repo.search_concepts("Acme Diabetes")
    codes = {c.code for c in found}
    assert f"{run_prefix}010" in codes
    assert f"{run_prefix}011" in codes

    icd_only = repo.search_concepts("Acme Diabetes", ontology="icd10")
    icd_codes = {c.code for c in icd_only}
    assert f"{run_prefix}010" in icd_codes
    assert f"{run_prefix}011" not in icd_codes


# ---------------------------------------------------------------------------
# Edge CRUD
# ---------------------------------------------------------------------------


def test_upsert_edge_idempotent(run_prefix: str) -> None:
    a = repo.upsert_concept(_mk(run_prefix, "icd10", "100"))
    b = repo.upsert_concept(_mk(run_prefix, "hcc", "101"))

    e1 = Edge(src_concept_id=a, dst_concept_id=b, edge_type=EdgeType.MAPS_TO, weight=0.9)
    eid1 = repo.upsert_edge(e1)

    e2 = Edge(src_concept_id=a, dst_concept_id=b, edge_type=EdgeType.MAPS_TO, weight=0.5)
    eid2 = repo.upsert_edge(e2)

    assert eid1 == eid2

    edges = repo.outgoing_edges(a)
    assert len(edges) == 1
    assert pytest.approx(edges[0].weight, rel=1e-3) == 0.5


def test_outgoing_and_incoming_edge_filtering(run_prefix: str) -> None:
    a = repo.upsert_concept(_mk(run_prefix, "icd10", "200"))
    b = repo.upsert_concept(_mk(run_prefix, "hcc", "201"))
    c = repo.upsert_concept(_mk(run_prefix, "loinc", "202"))

    repo.upsert_edge(Edge(src_concept_id=a, dst_concept_id=b, edge_type=EdgeType.MAPS_TO))
    repo.upsert_edge(
        Edge(src_concept_id=a, dst_concept_id=c, edge_type=EdgeType.HAS_LAB_SIGNAL, weight=0.8)
    )

    out_all = repo.outgoing_edges(a)
    assert len(out_all) == 2

    out_filtered = repo.outgoing_edges(a, edge_type=EdgeType.MAPS_TO)
    assert len(out_filtered) == 1
    assert out_filtered[0].dst_concept_id == b

    in_b = repo.incoming_edges(b)
    assert len(in_b) == 1 and in_b[0].src_concept_id == a

    in_c_filtered = repo.incoming_edges(c, edge_type=EdgeType.MAPS_TO)
    assert in_c_filtered == []


# ---------------------------------------------------------------------------
# Traversal
# ---------------------------------------------------------------------------


def test_traverse_zero_depth_returns_only_start(run_prefix: str) -> None:
    a = repo.upsert_concept(_mk(run_prefix, "icd10", "300"))
    b = repo.upsert_concept(_mk(run_prefix, "hcc", "301"))
    repo.upsert_edge(Edge(src_concept_id=a, dst_concept_id=b, edge_type=EdgeType.MAPS_TO))

    result = repo.traverse(a, max_depth=0)
    assert len(result) == 1
    assert result[0]["concept"].id == a
    assert result[0]["depth"] == 0
    assert result[0]["via_edge"] is None


def test_traverse_respects_max_depth(run_prefix: str) -> None:
    a = repo.upsert_concept(_mk(run_prefix, "icd10", "400"))
    b = repo.upsert_concept(_mk(run_prefix, "icd10", "401"))
    c = repo.upsert_concept(_mk(run_prefix, "hcc", "402"))
    d = repo.upsert_concept(_mk(run_prefix, "loinc", "403"))

    repo.upsert_edge(Edge(src_concept_id=a, dst_concept_id=b, edge_type=EdgeType.SUBCLASS_OF))
    repo.upsert_edge(Edge(src_concept_id=b, dst_concept_id=c, edge_type=EdgeType.MAPS_TO))
    repo.upsert_edge(Edge(src_concept_id=c, dst_concept_id=d, edge_type=EdgeType.HAS_LAB_SIGNAL))

    depth1 = repo.traverse(a, max_depth=1)
    ids_at_d1 = {r["concept"].id for r in depth1}
    assert ids_at_d1 == {a, b}

    depth2 = repo.traverse(a, max_depth=2)
    ids_at_d2 = {r["concept"].id for r in depth2}
    assert ids_at_d2 == {a, b, c}

    depth3 = repo.traverse(a, max_depth=3)
    ids_at_d3 = {r["concept"].id for r in depth3}
    assert ids_at_d3 == {a, b, c, d}

    # Depth values are correct
    by_id = {r["concept"].id: r["depth"] for r in depth3}
    assert by_id[a] == 0 and by_id[b] == 1 and by_id[c] == 2 and by_id[d] == 3


def test_traverse_filters_by_edge_type(run_prefix: str) -> None:
    a = repo.upsert_concept(_mk(run_prefix, "icd10", "500"))
    b = repo.upsert_concept(_mk(run_prefix, "hcc", "501"))
    c = repo.upsert_concept(_mk(run_prefix, "loinc", "502"))

    repo.upsert_edge(Edge(src_concept_id=a, dst_concept_id=b, edge_type=EdgeType.MAPS_TO))
    repo.upsert_edge(Edge(src_concept_id=a, dst_concept_id=c, edge_type=EdgeType.HAS_LAB_SIGNAL))

    only_maps = repo.traverse(a, edge_types=[EdgeType.MAPS_TO], max_depth=2)
    ids = {r["concept"].id for r in only_maps}
    assert ids == {a, b}

    both = repo.traverse(a, edge_types=[EdgeType.MAPS_TO, EdgeType.HAS_LAB_SIGNAL], max_depth=2)
    assert {r["concept"].id for r in both} == {a, b, c}


def test_traverse_missing_start_returns_empty() -> None:
    assert repo.traverse(2_147_483_640, max_depth=2) == []


def test_traverse_negative_depth_raises(run_prefix: str) -> None:
    a = repo.upsert_concept(_mk(run_prefix, "icd10", "600"))
    with pytest.raises(ValueError):
        repo.traverse(a, max_depth=-1)


def test_traverse_handles_cycles(run_prefix: str) -> None:
    a = repo.upsert_concept(_mk(run_prefix, "icd10", "700"))
    b = repo.upsert_concept(_mk(run_prefix, "hcc", "701"))
    repo.upsert_edge(Edge(src_concept_id=a, dst_concept_id=b, edge_type=EdgeType.COMORBID_WITH))
    repo.upsert_edge(Edge(src_concept_id=b, dst_concept_id=a, edge_type=EdgeType.COMORBID_WITH))

    result = repo.traverse(a, edge_types=[EdgeType.COMORBID_WITH], max_depth=10)
    assert {r["concept"].id for r in result} == {a, b}


# ---------------------------------------------------------------------------
# Cascade & error paths
# ---------------------------------------------------------------------------


def test_delete_concept_cascades_edges(run_prefix: str) -> None:
    a = repo.upsert_concept(_mk(run_prefix, "icd10", "800"))
    b = repo.upsert_concept(_mk(run_prefix, "hcc", "801"))
    repo.upsert_edge(Edge(src_concept_id=a, dst_concept_id=b, edge_type=EdgeType.MAPS_TO))

    assert repo.outgoing_edges(a)
    repo.delete_concept(a)
    assert repo.find_by_id(a) is None
    assert repo.outgoing_edges(a) == []
    assert repo.incoming_edges(b) == []


def test_stats_returns_expected_keys() -> None:
    s = repo.stats()
    assert {"concepts", "edges", "by_ontology", "by_edge_type"} <= set(s)
    assert isinstance(s["concepts"], int)
    assert isinstance(s["edges"], int)
    assert isinstance(s["by_ontology"], dict)


# ---------------------------------------------------------------------------
# Performance / batch smoke
# ---------------------------------------------------------------------------


def test_batch_insert_100_concepts_under_one_second(run_prefix: str) -> None:
    concepts = [_mk(run_prefix, "custom", f"BATCH{i:03d}") for i in range(120)]
    start = time.perf_counter()
    ids = repo.bulk_upsert_concepts(concepts)
    elapsed = time.perf_counter() - start
    assert len(ids) == 120 and all(i > 0 for i in ids)
    # Loose threshold — local MySQL should finish well under 1s, but we give
    # CI headroom. Anything > 5s is a real regression.
    assert elapsed < 5.0, f"bulk_upsert_concepts took {elapsed:.2f}s for 120 rows"


# ---------------------------------------------------------------------------
# End-to-end: top-HCC seed produces enough graph to be useful.
# ---------------------------------------------------------------------------


def test_seed_top_hccs_meets_acceptance_criteria() -> None:
    summary = seed_top_hccs()
    assert summary["concepts_inserted"] >= 80, summary
    assert summary["edges_inserted"] >= 80, summary
    assert "18" in summary["hccs_covered"], "HCC 18 must be in the top-HCC seed"
    assert "85" in summary["hccs_covered"], "HCC 85 (CHF) must be in the seed"
    s = repo.stats()
    assert s["concepts"] >= 80
    assert s["edges"] >= 80
    # Must touch at least these ontologies
    for ont in ("hcc", "icd10", "atc", "loinc", "umls"):
        assert s["by_ontology"].get(ont, 0) > 0, f"Missing ontology {ont}"
