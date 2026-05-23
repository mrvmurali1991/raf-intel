"""
snomed_service.py

SNOMED CT mapping service.

Provides the full clinical-text → SNOMED → ICD-10 → HCC traversal pipeline used
by clinical decision support, suspect-detection assistance and pre-visit
briefings.  All public functions are tenant-aware where the underlying tables
are tenant-aware (the knowledge_graph tables are global / read-only).

Public API
----------
resolve_text_to_snomed(text)            free-text → top-N SNOMED concepts
snomed_to_icd10(snomed_id)              SNOMED concept → ICD-10 codes
icd10_to_hcc(icd10_code, model_year)    ICD-10 → HCC + RAF coefficient
text_to_hcc(text)                       full pipeline w/ chain of evidence
bulk_resolve_problem_list(items)        full pipeline over a list of strings

Implementation notes
--------------------
* Uses ``rapidfuzz`` for fuzzy matching when available; falls back to a
  combination of MySQL ``LIKE`` and a simple Python token-overlap score
  when the library is not installed.
* SNOMED → ICD-10 traversal walks ``knowledge_graph_edges`` rows of type
  ``maps_to`` from a SNOMED concept to ICD-10 concepts.
* ICD-10 → HCC traversal **prefers** the existing
  ``hcc_icd10_crosswalk`` table because it is the canonical source for
  ICD-10 → HCC mappings.  It falls back to (and unions with) any
  ``maps_to`` edges in ``knowledge_graph_edges`` where the source is
  ``CMS-V28`` or ``CMS-V24`` so the graph can be augmented with custom
  rules without modifying the canonical crosswalk.
* RAF coefficients are looked up via ``hccinfhir_utils.get_hcc_coefficient``
  which is the canonical scoring engine (single source of truth).
"""

from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

from app.db import raf_cursor

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional dependency: rapidfuzz
# ---------------------------------------------------------------------------

try:  # pragma: no cover - import-only
    from rapidfuzz import fuzz as _rf_fuzz
    from rapidfuzz import process as _rf_process

    _HAS_RAPIDFUZZ = True
except Exception:  # pragma: no cover - covered by tests via monkeypatch
    logger.debug("swallowed exception", exc_info=True)
    _rf_fuzz = None  # type: ignore[assignment]
    _rf_process = None  # type: ignore[assignment]
    _HAS_RAPIDFUZZ = False


# ---------------------------------------------------------------------------
# Optional dependency: hccinfhir (for RAF coefficients)
# ---------------------------------------------------------------------------

try:  # pragma: no cover - import-only
    from app.services.hccinfhir_utils import get_hcc_coefficient as _get_hcc_coefficient
except Exception:  # pragma: no cover
    logger.debug("swallowed exception", exc_info=True)
    _get_hcc_coefficient = None  # type: ignore[assignment]


# ===========================================================================
# Data classes
# ===========================================================================


@dataclass
class Concept:
    """A single SNOMED CT concept match."""

    concept_id: int
    code: str
    preferred_label: str
    semantic_type: str | None = None
    score: float = 0.0
    # Diagnostic fields useful for debugging / UI
    concept_uri: str | None = None
    matched_via: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ===========================================================================
# Internals
# ===========================================================================

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


def _tokens(text: str) -> set[str]:
    """Cheap tokenizer used by the fallback similarity scorer."""
    return {t.lower() for t in _TOKEN_RE.findall(text or "") if len(t) > 1}


def _fallback_similarity(query: str, label: str) -> float:
    """Token-overlap similarity in [0, 100]; mirrors rapidfuzz scale."""
    q_tokens = _tokens(query)
    l_tokens = _tokens(label)
    if not q_tokens or not l_tokens:
        return 0.0
    overlap = len(q_tokens & l_tokens)
    union = len(q_tokens | l_tokens)
    jaccard = overlap / union if union else 0.0
    # Boost when *all* query tokens appear in the label
    contains_bonus = 0.2 if q_tokens.issubset(l_tokens) else 0.0
    return min(100.0, (jaccard + contains_bonus) * 100.0)


def _score(query: str, label: str) -> float:
    """Return a similarity score in [0, 100], using rapidfuzz if available."""
    if _HAS_RAPIDFUZZ and _rf_fuzz is not None:
        # WRatio is robust to word order, partial matches, case; range [0, 100]
        return float(_rf_fuzz.WRatio(query, label))
    return _fallback_similarity(query, label)


def _select_snomed_candidates(query: str, like_limit: int = 200) -> list[dict[str, Any]]:
    """Pull SNOMED candidate rows from the DB using a permissive LIKE.

    The query is split into tokens and every token >=3 chars is OR'd into the
    WHERE clause, which keeps the candidate pool small even for short text.
    A hard limit caps the candidate set so fuzzy scoring stays cheap.
    """
    tokens = [t for t in _tokens(query) if len(t) >= 3]
    if not tokens:
        return []

    where_clauses = ["ontology = 'snomed'", "is_active = 1"]
    params: list[Any] = []

    like_parts = []
    for t in tokens:
        like_parts.append("preferred_label LIKE %s")
        params.append(f"%{t}%")
    where_clauses.append("(" + " OR ".join(like_parts) + ")")

    sql = (
        "SELECT id, code, preferred_label, semantic_type, concept_uri "
        "FROM knowledge_graph_concepts "
        f"WHERE {' AND '.join(where_clauses)} "
        "LIMIT %s"
    )
    params.append(like_limit)

    try:
        with raf_cursor() as cur:
            cur.execute(sql, tuple(params))
            return list(cur.fetchall())
    except Exception as exc:
        logger.warning("snomed_service: candidate fetch failed: %s", exc)
        return []


# ===========================================================================
# Public API
# ===========================================================================


def resolve_text_to_snomed(text: str, top_k: int = 5, min_score: float = 50.0) -> list[Concept]:
    """Fuzzy-match free clinical text against SNOMED concept labels.

    Returns the top ``top_k`` matches with scores in [0, 100], sorted descending.
    Concepts scoring below ``min_score`` are dropped.  Returns ``[]`` on empty
    input or when the knowledge graph is empty.
    """
    if not text or not text.strip():
        return []

    candidates = _select_snomed_candidates(text)
    if not candidates:
        return []

    scored: list[tuple[float, dict[str, Any]]] = []
    for row in candidates:
        score = _score(text, row.get("preferred_label") or "")
        if score >= min_score:
            scored.append((score, row))

    scored.sort(key=lambda x: x[0], reverse=True)

    matched_via = "rapidfuzz" if _HAS_RAPIDFUZZ else "fallback_jaccard"
    out: list[Concept] = []
    for score, row in scored[:top_k]:
        out.append(
            Concept(
                concept_id=int(row["id"]),
                code=str(row["code"]),
                preferred_label=str(row["preferred_label"]),
                semantic_type=row.get("semantic_type"),
                score=round(score, 2),
                concept_uri=row.get("concept_uri"),
                matched_via=matched_via,
            )
        )
    return out


def snomed_to_icd10(snomed_id: str) -> list[str]:
    """Return all ICD-10 codes reachable from *snomed_id* via maps_to edges.

    *snomed_id* is the SNOMED CT identifier (the ``code`` column on
    knowledge_graph_concepts where ontology = 'snomed').  Codes are returned
    without the decimal dot, matching CMS canonical format and the format
    used in ``hcc_icd10_crosswalk``.
    """
    if not snomed_id:
        return []

    sql = (
        "SELECT DISTINCT dst.code AS icd10_code "
        "FROM knowledge_graph_edges e "
        "JOIN knowledge_graph_concepts src ON src.id = e.src_concept_id "
        "JOIN knowledge_graph_concepts dst ON dst.id = e.dst_concept_id "
        "WHERE src.ontology = 'snomed' "
        "  AND src.code = %s "
        "  AND e.edge_type = 'maps_to' "
        "  AND dst.ontology = 'icd10' "
        "  AND dst.is_active = 1 "
        "ORDER BY dst.code"
    )
    try:
        with raf_cursor() as cur:
            cur.execute(sql, (str(snomed_id),))
            rows = cur.fetchall()
    except Exception as exc:
        logger.warning("snomed_service.snomed_to_icd10(%s): %s", snomed_id, exc)
        return []

    out: list[str] = []
    for row in rows:
        code = (row.get("icd10_code") or "").strip().upper().replace(".", "")
        if code and code not in out:
            out.append(code)
    return out


def _coefficient_for(hcc_code: int, model_version: str) -> float | None:
    """Look up a numeric RAF coefficient via hccinfhir; ``None`` on miss."""
    if _get_hcc_coefficient is None:
        return None
    try:
        return float(_get_hcc_coefficient(int(hcc_code), model_version) or 0.0) or None
    except Exception:  # noqa: BLE001 — best-effort guard
        logger.debug("swallowed exception", exc_info=True)
        return None


def _model_version_for_year(model_year: int) -> str:
    """Map a payment year to the CMS model version string used by the app."""
    # V28 became active in PY 2024 (phased) and is fully active 2026+.
    # The rest of the codebase uses 2026 = V28, 2024/2023 = V24 by convention.
    return "V28" if model_year >= 2025 else "V24"


def icd10_to_hcc(icd10_code: str, model_year: int = 2026) -> list[dict[str, Any]]:
    """Return HCC mappings for *icd10_code* under the given payment year.

    Result rows look like::

        {
          "icd10_code":      "E1140",
          "hcc_code":        18,
          "hcc_label":       "Diabetes with Chronic Complications",
          "model_version":   "V28",
          "model_year":      2026,
          "raf_coefficient": 0.302,
          "source":          "hcc_icd10_crosswalk"  | "kg_edge:CMS-V28" | ...
        }

    The function unions two sources:
      1. ``hcc_icd10_crosswalk`` — canonical CMS mapping table.
      2. ``knowledge_graph_edges`` of type ``maps_to`` whose source is
         ``CMS-V28`` or ``CMS-V24`` — used for graph-only / custom rules.
    """
    if not icd10_code:
        return []

    code_raw = icd10_code.strip().upper()
    code_no_dot = code_raw.replace(".", "")
    # The on-disk crosswalk historically stores codes WITH dots (e.g. "E11.40"),
    # but callers may pass either form. Match both.
    code_with_dot = code_raw if "." in code_raw else (
        f"{code_raw[:3]}.{code_raw[3:]}" if len(code_raw) > 3 else code_raw
    )
    model_version = _model_version_for_year(model_year)
    seen: set[tuple[int, str]] = set()
    rows: list[dict[str, Any]] = []

    # 1. Canonical crosswalk table -------------------------------------------
    # NOTE: The crosswalk schema uses ``effective_year`` (not ``model_version``)
    # and stores codes WITH dots. We accept both code formats and infer the
    # version from year.
    crosswalk_sql = (
        "SELECT icd10_code, hcc_code, hcc_label, effective_year "
        "FROM hcc_icd10_crosswalk "
        "WHERE icd10_code IN (%s, %s) "
        "  AND effective_year <= %s "
        "ORDER BY effective_year DESC, hcc_code"
    )
    try:
        with raf_cursor() as cur:
            cur.execute(crosswalk_sql, (code_with_dot, code_no_dot, model_year))
            for row in cur.fetchall():
                hcc_code = int(row["hcc_code"])
                key = (hcc_code, model_version)
                if key in seen:
                    continue
                seen.add(key)
                rows.append(
                    {
                        "icd10_code": code_no_dot,
                        "hcc_code": hcc_code,
                        "hcc_label": row.get("hcc_label"),
                        "model_version": model_version,
                        "model_year": int(row.get("effective_year") or model_year),
                        "raf_coefficient": _coefficient_for(hcc_code, model_version),
                        "source": "hcc_icd10_crosswalk",
                    }
                )
    except Exception as exc:
        logger.warning("snomed_service.icd10_to_hcc crosswalk failed: %s", exc)

    # 2. KG edges -------------------------------------------------------------
    kg_source = f"CMS-{model_version}"
    kg_sql = (
        "SELECT dst.code AS hcc_code, dst.preferred_label AS hcc_label, e.source "
        "FROM knowledge_graph_edges e "
        "JOIN knowledge_graph_concepts src ON src.id = e.src_concept_id "
        "JOIN knowledge_graph_concepts dst ON dst.id = e.dst_concept_id "
        "WHERE src.ontology = 'icd10' AND src.code IN (%s, %s) "
        "  AND e.edge_type = 'maps_to' "
        "  AND dst.ontology = 'hcc' "
        "  AND e.source IN ('CMS-V28','CMS-V24') "
        "  AND e.source = %s"
    )
    try:
        with raf_cursor() as cur:
            cur.execute(kg_sql, (code_with_dot, code_no_dot, kg_source))
            for row in cur.fetchall():
                try:
                    hcc_code = int(row["hcc_code"])
                except (TypeError, ValueError):
                    continue
                key = (hcc_code, model_version)
                if key in seen:
                    continue
                seen.add(key)
                rows.append(
                    {
                        "icd10_code": code_no_dot,
                        "hcc_code": hcc_code,
                        "hcc_label": row.get("hcc_label"),
                        "model_version": model_version,
                        "model_year": model_year,
                        "raf_coefficient": _coefficient_for(hcc_code, model_version),
                        "source": f"kg_edge:{row.get('source')}",
                    }
                )
    except Exception as exc:
        logger.warning("snomed_service.icd10_to_hcc kg edges failed: %s", exc)

    return rows


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


@dataclass
class _HCCEvidence:
    text: str
    snomed: Concept
    icd10: str
    hcc: dict[str, Any]
    chain_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "snomed_id": self.snomed.code,
            "snomed_label": self.snomed.preferred_label,
            "snomed_score": self.snomed.score,
            "icd10": self.icd10,
            "hcc_code": self.hcc.get("hcc_code"),
            "hcc_label": self.hcc.get("hcc_label"),
            "model_version": self.hcc.get("model_version"),
            "raf_coefficient": self.hcc.get("raf_coefficient"),
            "source": self.hcc.get("source"),
            "chain_score": round(self.chain_score, 2),
        }


def text_to_hcc(
    text: str,
    *,
    top_k_snomed: int = 5,
    top_k_results: int = 10,
    model_year: int = 2026,
) -> list[dict[str, Any]]:
    """Full clinical-text → HCC pipeline.

    Returns a list of HCC candidates each annotated with the chain of evidence
    (SNOMED concept, intermediate ICD-10, RAF coefficient).  Sorted by
    ``chain_score`` descending and de-duplicated by ``hcc_code`` (the highest
    scoring chain for each HCC is retained).
    """
    if not text or not text.strip():
        return []

    snomed_matches = resolve_text_to_snomed(text, top_k=top_k_snomed)
    evidences: list[_HCCEvidence] = []

    for concept in snomed_matches:
        icd10_codes = snomed_to_icd10(concept.code)
        for icd10 in icd10_codes:
            hccs = icd10_to_hcc(icd10, model_year=model_year)
            for hcc in hccs:
                # chain_score is the SNOMED match score, attenuated slightly
                # if no RAF coefficient is known (less actionable).
                base = float(concept.score or 0.0)
                if not hcc.get("raf_coefficient"):
                    base *= 0.9
                evidences.append(
                    _HCCEvidence(
                        text=text,
                        snomed=concept,
                        icd10=icd10,
                        hcc=hcc,
                        chain_score=base,
                    )
                )

    # De-duplicate by HCC, keep highest scoring chain
    best_by_hcc: dict[int, _HCCEvidence] = {}
    for ev in evidences:
        hcc_code = ev.hcc.get("hcc_code")
        if hcc_code is None:
            continue
        prev = best_by_hcc.get(hcc_code)
        if prev is None or ev.chain_score > prev.chain_score:
            best_by_hcc[hcc_code] = ev

    out = sorted(best_by_hcc.values(), key=lambda e: e.chain_score, reverse=True)
    return [ev.to_dict() for ev in out[:top_k_results]]


def bulk_resolve_problem_list(
    problem_list: Iterable[str],
    *,
    model_year: int = 2026,
    top_k_per_item: int = 5,
) -> dict[str, Any]:
    """Run :func:`text_to_hcc` over every problem-list item and aggregate.

    Result shape::

        {
          "items":   [ {"text": "...", "candidates": [...]}, ... ],
          "summary": {
             "unique_hccs":      int,
             "total_raf":        float,    # sum of best chain per HCC
             "by_hcc":           [ {hcc_code, hcc_label, raf_coefficient,
                                   evidence_count, best_chain}, ... ]
          }
        }
    """
    items: list[dict[str, Any]] = []
    aggregated: dict[int, dict[str, Any]] = {}

    for raw in problem_list or []:
        text = (raw or "").strip()
        if not text:
            items.append({"text": raw or "", "candidates": []})
            continue

        candidates = text_to_hcc(
            text,
            top_k_results=top_k_per_item,
            model_year=model_year,
        )
        items.append({"text": text, "candidates": candidates})

        for cand in candidates:
            hcc_code = cand.get("hcc_code")
            if hcc_code is None:
                continue
            existing = aggregated.get(hcc_code)
            if existing is None or cand["chain_score"] > existing["best_chain"]["chain_score"]:
                aggregated[hcc_code] = {
                    "hcc_code": hcc_code,
                    "hcc_label": cand.get("hcc_label"),
                    "raf_coefficient": cand.get("raf_coefficient"),
                    "evidence_count": (existing or {}).get("evidence_count", 0) + 1,
                    "best_chain": cand,
                }
            else:
                existing["evidence_count"] += 1

    by_hcc = sorted(
        aggregated.values(),
        key=lambda r: (r.get("raf_coefficient") or 0.0, r["best_chain"]["chain_score"]),
        reverse=True,
    )
    total_raf = sum((r.get("raf_coefficient") or 0.0) for r in by_hcc)

    return {
        "items": items,
        "summary": {
            "unique_hccs": len(by_hcc),
            "total_raf": round(total_raf, 4),
            "by_hcc": by_hcc,
        },
    }
