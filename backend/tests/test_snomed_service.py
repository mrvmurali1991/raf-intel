"""
test_snomed_service.py — unit tests for the SNOMED CT mapping service.

All DB access is mocked via raf_cursor; no real database needed.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.services.knowledge_graph import snomed_service
from app.services.knowledge_graph.snomed_service import (
    Concept,
    bulk_resolve_problem_list,
    icd10_to_hcc,
    resolve_text_to_snomed,
    snomed_to_icd10,
    text_to_hcc,
)


# ---------------------------------------------------------------------------
# Cursor helpers
# ---------------------------------------------------------------------------


def _make_cursor_cm(query_responses: list[list[dict[str, Any]]]):
    """Return (cm_factory, cursor_mock) where each enter returns a cursor that
    yields the next batch of rows from *query_responses* on fetchall().

    This works for tests that issue several SQL statements per call.
    """
    counter = {"i": 0}

    def _execute(_sql, _params=None):
        # The cursor uses fetchall() after execute(); we cycle responses by call
        return None

    cursor = MagicMock()
    cursor.execute.side_effect = _execute

    def _fetchall():
        idx = counter["i"]
        counter["i"] += 1
        if idx < len(query_responses):
            return query_responses[idx]
        return []

    def _fetchone():
        idx = counter["i"]
        counter["i"] += 1
        if idx < len(query_responses):
            rows = query_responses[idx]
            return rows[0] if rows else None
        return None

    cursor.fetchall.side_effect = _fetchall
    cursor.fetchone.side_effect = _fetchone

    @contextmanager
    def _cm(*_a, **_kw):
        yield cursor

    return _cm, cursor


# ===========================================================================
# 1. resolve_text_to_snomed
# ===========================================================================


class TestResolveTextToSnomed:
    def test_empty_input_returns_empty_list(self):
        assert resolve_text_to_snomed("") == []
        assert resolve_text_to_snomed("   ") == []

    def test_no_candidates_returns_empty_list(self):
        cm, _ = _make_cursor_cm([[]])
        with patch.object(snomed_service, "raf_cursor", cm):
            assert resolve_text_to_snomed("acute lymphoblastic leukemia") == []

    def test_exact_match_high_score(self):
        rows = [
            {
                "id": 1,
                "code": "44054006",
                "preferred_label": "Type 2 diabetes mellitus",
                "semantic_type": "Disorder",
                "concept_uri": "snomed:44054006",
            },
            {
                "id": 2,
                "code": "46635009",
                "preferred_label": "Type 1 diabetes mellitus",
                "semantic_type": "Disorder",
                "concept_uri": "snomed:46635009",
            },
        ]
        cm, _ = _make_cursor_cm([rows])
        with patch.object(snomed_service, "raf_cursor", cm):
            results = resolve_text_to_snomed("Type 2 diabetes mellitus", top_k=5)

        assert len(results) >= 1
        # The exact-label match should win
        assert results[0].code == "44054006"
        assert results[0].score >= 80.0

    def test_fuzzy_match_diabetic_foot_finds_diabetes_complications(self):
        rows = [
            {
                "id": 10,
                "code": "313839005",
                "preferred_label": "Diabetic foot",
                "semantic_type": "Disorder",
                "concept_uri": "snomed:313839005",
            },
            {
                "id": 11,
                "code": "420715001",
                "preferred_label": "Type 2 diabetes mellitus with peripheral angiopathy",
                "semantic_type": "Disorder",
                "concept_uri": "snomed:420715001",
            },
        ]
        cm, _ = _make_cursor_cm([rows])
        with patch.object(snomed_service, "raf_cursor", cm):
            results = resolve_text_to_snomed("diabetic foot ulcer", top_k=5, min_score=30.0)
        assert len(results) >= 1
        assert any(r.code == "313839005" for r in results)

    def test_top_k_limits_results(self):
        rows = [
            {
                "id": i,
                "code": f"COD{i}",
                "preferred_label": f"Type 2 diabetes mellitus variant {i}",
                "semantic_type": "Disorder",
                "concept_uri": f"snomed:COD{i}",
            }
            for i in range(20)
        ]
        cm, _ = _make_cursor_cm([rows])
        with patch.object(snomed_service, "raf_cursor", cm):
            results = resolve_text_to_snomed("type 2 diabetes", top_k=3)
        assert len(results) <= 3

    def test_fallback_similarity_used_when_no_rapidfuzz(self):
        score = snomed_service._fallback_similarity(
            "type 2 diabetes", "Type 2 diabetes mellitus"
        )
        assert score > 30.0


# ===========================================================================
# 2. snomed_to_icd10
# ===========================================================================


class TestSnomedToIcd10:
    def test_returns_codes(self):
        rows = [{"icd10_code": "E119"}, {"icd10_code": "E1140"}]
        cm, _ = _make_cursor_cm([rows])
        with patch.object(snomed_service, "raf_cursor", cm):
            codes = snomed_to_icd10("44054006")
        assert codes == ["E119", "E1140"]

    def test_empty_input(self):
        assert snomed_to_icd10("") == []

    def test_normalizes_codes_no_dot(self):
        rows = [{"icd10_code": "E11.9"}, {"icd10_code": "e1140"}]
        cm, _ = _make_cursor_cm([rows])
        with patch.object(snomed_service, "raf_cursor", cm):
            codes = snomed_to_icd10("44054006")
        assert "E119" in codes
        assert "E1140" in codes

    def test_db_error_returns_empty(self):
        @contextmanager
        def _cm(*_a, **_kw):
            raise RuntimeError("db down")
            yield  # pragma: no cover

        with patch.object(snomed_service, "raf_cursor", _cm):
            assert snomed_to_icd10("44054006") == []


# ===========================================================================
# 3. icd10_to_hcc
# ===========================================================================


class TestIcd10ToHcc:
    def test_uses_crosswalk_table(self):
        crosswalk = [
            {
                "icd10_code": "E1140",
                "hcc_code": 18,
                "hcc_label": "Diabetes with Chronic Complications",
                "model_version": "V28",
                "model_year": 2026,
            }
        ]
        kg_rows: list[dict[str, Any]] = []
        cm, _ = _make_cursor_cm([crosswalk, kg_rows])
        with patch.object(snomed_service, "raf_cursor", cm), patch.object(
            snomed_service, "_get_hcc_coefficient", lambda *_a, **_kw: 0.302
        ):
            rows = icd10_to_hcc("E1140", model_year=2026)

        assert len(rows) == 1
        assert rows[0]["hcc_code"] == 18
        assert rows[0]["model_version"] == "V28"
        assert rows[0]["raf_coefficient"] == pytest.approx(0.302)
        assert rows[0]["source"] == "hcc_icd10_crosswalk"

    def test_unions_kg_edges(self):
        crosswalk: list[dict[str, Any]] = []  # nothing in canonical table
        kg_rows = [
            {"hcc_code": "18", "hcc_label": "Diabetes with Chronic Complications", "source": "CMS-V28"}
        ]
        cm, _ = _make_cursor_cm([crosswalk, kg_rows])
        with patch.object(snomed_service, "raf_cursor", cm), patch.object(
            snomed_service, "_get_hcc_coefficient", lambda *_a, **_kw: 0.302
        ):
            rows = icd10_to_hcc("E1140", model_year=2026)

        assert len(rows) == 1
        assert rows[0]["hcc_code"] == 18
        assert rows[0]["source"] == "kg_edge:CMS-V28"

    def test_picks_v24_for_old_year(self):
        crosswalk = [
            {
                "icd10_code": "E1140",
                "hcc_code": 18,
                "hcc_label": "Diabetes with Chronic Complications",
                "model_version": "V24",
                "model_year": 2024,
            }
        ]
        cm, _ = _make_cursor_cm([crosswalk, []])
        with patch.object(snomed_service, "raf_cursor", cm), patch.object(
            snomed_service, "_get_hcc_coefficient", lambda *_a, **_kw: None
        ):
            rows = icd10_to_hcc("E1140", model_year=2024)
        assert rows[0]["model_version"] == "V24"

    def test_empty_input(self):
        assert icd10_to_hcc("") == []

    def test_normalizes_input_code(self):
        crosswalk = [
            {
                "icd10_code": "E1140",
                "hcc_code": 18,
                "hcc_label": "Diabetes",
                "model_version": "V28",
                "model_year": 2026,
            }
        ]
        cm, cur = _make_cursor_cm([crosswalk, []])
        with patch.object(snomed_service, "raf_cursor", cm), patch.object(
            snomed_service, "_get_hcc_coefficient", lambda *_a, **_kw: None
        ):
            rows = icd10_to_hcc("e11.40", model_year=2026)
        assert rows[0]["icd10_code"] == "E1140"


# ===========================================================================
# 4. text_to_hcc — full pipeline
# ===========================================================================


class TestTextToHcc:
    def test_full_pipeline_diabetes_neuropathy(self):
        # Stage 1: SNOMED candidate fetch returns one match
        snomed_rows = [
            {
                "id": 1,
                "code": "190447002",
                "preferred_label": "Type 2 diabetes mellitus with neuropathy",
                "semantic_type": "Disorder",
                "concept_uri": "snomed:190447002",
            }
        ]
        # Stage 2: SNOMED → ICD-10
        icd10_rows = [{"icd10_code": "E1140"}]
        # Stage 3 (a): ICD-10 → HCC via crosswalk
        crosswalk_rows = [
            {
                "icd10_code": "E1140",
                "hcc_code": 18,
                "hcc_label": "Diabetes with Chronic Complications",
                "model_version": "V28",
                "model_year": 2026,
            }
        ]
        # Stage 3 (b): KG edges (empty)
        kg_rows: list[dict[str, Any]] = []

        responses = [snomed_rows, icd10_rows, crosswalk_rows, kg_rows]
        cm, _ = _make_cursor_cm(responses)
        with patch.object(snomed_service, "raf_cursor", cm), patch.object(
            snomed_service, "_get_hcc_coefficient", lambda *_a, **_kw: 0.302
        ):
            results = text_to_hcc("Type 2 diabetes with neuropathy", model_year=2026)

        assert len(results) >= 1
        top = results[0]
        assert top["hcc_code"] == 18
        assert top["icd10"] == "E1140"
        assert top["snomed_id"] == "190447002"
        assert top["raf_coefficient"] == pytest.approx(0.302)
        assert top["chain_score"] > 0

    def test_pipeline_dedup_by_hcc(self):
        # Two SNOMED concepts both map to the same HCC; keep the higher-scoring chain.
        snomed_rows = [
            {
                "id": 1,
                "code": "44054006",
                "preferred_label": "Type 2 diabetes mellitus",
                "semantic_type": "Disorder",
                "concept_uri": "snomed:44054006",
            },
            {
                "id": 2,
                "code": "190447002",
                "preferred_label": "Type 2 diabetes mellitus with neuropathy",
                "semantic_type": "Disorder",
                "concept_uri": "snomed:190447002",
            },
        ]
        # Each SNOMED returns one ICD-10
        icd10_rows_1 = [{"icd10_code": "E119"}]
        icd10_rows_2 = [{"icd10_code": "E1140"}]
        # Both ICD-10s map to HCC 18 (artificial example for dedup test)
        crosswalk_1 = [
            {"icd10_code": "E119", "hcc_code": 18, "hcc_label": "DM", "model_version": "V28", "model_year": 2026}
        ]
        kg_1: list[dict[str, Any]] = []
        crosswalk_2 = [
            {"icd10_code": "E1140", "hcc_code": 18, "hcc_label": "DM", "model_version": "V28", "model_year": 2026}
        ]
        kg_2: list[dict[str, Any]] = []

        cm, _ = _make_cursor_cm(
            [snomed_rows, icd10_rows_1, crosswalk_1, kg_1, icd10_rows_2, crosswalk_2, kg_2]
        )
        with patch.object(snomed_service, "raf_cursor", cm), patch.object(
            snomed_service, "_get_hcc_coefficient", lambda *_a, **_kw: 0.302
        ):
            results = text_to_hcc("type 2 diabetes")

        # Even though two chains lead to HCC 18, only one row should appear.
        codes = [r["hcc_code"] for r in results]
        assert codes.count(18) == 1

    def test_empty_input(self):
        assert text_to_hcc("") == []

    def test_pipeline_with_no_snomed_match_returns_empty(self):
        cm, _ = _make_cursor_cm([[]])
        with patch.object(snomed_service, "raf_cursor", cm):
            assert text_to_hcc("xyzzy") == []


# ===========================================================================
# 5. bulk_resolve_problem_list
# ===========================================================================


class TestBulkResolve:
    def test_problem_list_aggregates_unique_hccs(self):
        # Build sequenced responses for two problem-list items.
        # Item 1: "Type 2 diabetes" → SNOMED 1 → E119 → HCC 19 (DM w/o complications)
        # Item 2: "CHF" → SNOMED 2 → I509 → HCC 85 (CHF)
        snomed_a = [
            {
                "id": 1,
                "code": "44054006",
                "preferred_label": "Type 2 diabetes mellitus",
                "semantic_type": "Disorder",
                "concept_uri": "snomed:44054006",
            }
        ]
        icd_a = [{"icd10_code": "E119"}]
        cross_a = [
            {"icd10_code": "E119", "hcc_code": 19, "hcc_label": "DM", "model_version": "V28", "model_year": 2026}
        ]
        kg_a: list[dict[str, Any]] = []

        snomed_b = [
            {
                "id": 2,
                "code": "42343007",
                "preferred_label": "Congestive heart failure",
                "semantic_type": "Disorder",
                "concept_uri": "snomed:42343007",
            }
        ]
        icd_b = [{"icd10_code": "I509"}]
        cross_b = [
            {"icd10_code": "I509", "hcc_code": 85, "hcc_label": "CHF", "model_version": "V28", "model_year": 2026}
        ]
        kg_b: list[dict[str, Any]] = []

        cm, _ = _make_cursor_cm(
            [snomed_a, icd_a, cross_a, kg_a, snomed_b, icd_b, cross_b, kg_b]
        )

        coeffs = {19: 0.10, 85: 0.395}
        with patch.object(snomed_service, "raf_cursor", cm), patch.object(
            snomed_service, "_get_hcc_coefficient", lambda code, _: coeffs.get(int(code))
        ):
            result = bulk_resolve_problem_list(["Type 2 diabetes", "Congestive heart failure"])

        assert len(result["items"]) == 2
        assert result["summary"]["unique_hccs"] == 2
        codes = sorted(r["hcc_code"] for r in result["summary"]["by_hcc"])
        assert codes == [19, 85]
        assert result["summary"]["total_raf"] == pytest.approx(0.495, rel=1e-2)

    def test_empty_list(self):
        result = bulk_resolve_problem_list([])
        assert result["items"] == []
        assert result["summary"]["unique_hccs"] == 0
        assert result["summary"]["total_raf"] == 0


# ===========================================================================
# 6. Top-30 HCC coverage smoke test (data-side, doesn't need DB)
# ===========================================================================


class TestSeedDataCoverage:
    """Sanity-check that the seed list covers the top-30 HCC families."""

    def test_seed_list_covers_top_hccs(self):
        from scripts.seed_snomed_top_concepts import _SEED  # type: ignore

        codes = {s.icd10_code.upper() for s in _SEED}
        # Spot-check representative ICD-10 codes for top HCC families
        # Diabetes
        assert any(c.startswith("E11") for c in codes)
        # CHF
        assert "I509" in codes
        # COPD
        assert "J449" in codes
        # CKD
        assert any(c.startswith("N18") for c in codes)
        # Cancer
        assert any(c.startswith("C") for c in codes)
        # Mental health
        assert "F329" in codes
        # Substance use
        assert "F1120" in codes
        # HIV
        assert "B20" in codes

    def test_seed_list_is_comprehensive(self):
        from scripts.seed_snomed_top_concepts import _SEED  # type: ignore

        # Per the agent task, ~150 SNOMED concepts.  Allow some slack.
        assert len(_SEED) >= 130
