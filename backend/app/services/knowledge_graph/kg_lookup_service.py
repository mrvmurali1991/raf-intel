"""
Unified Knowledge-Graph Query Service.

This is the single API every other system (suspect engine, frontend, audit,
copilot) calls to get HCC reasoning.  It does **not** duplicate logic that
lives in the eight sub-services in this package — it orchestrates them.

Sub-services orchestrated (each optional — gracefully skipped if missing):

    - snomed_service              text/SNOMED → ICD-10 → HCC
    - loinc_service               LOINC lab → signal → HCC
    - atc_service                 ATC class hierarchy
    - drug_class_reasoner         drug → class → HCC
    - comorbidity_engine          HCC + HCC → upgraded HCC
    - demographic_risk_service    age/sex/dual modulation
    - specialty_priors_service    specialty-calibrated priors
    - evidence_rules_engine       structured rule firing + citations

Caching
-------
- functools.lru_cache for `explain_hcc`, `get_priors_for_specialty`,
  `traverse_path`. TTL controlled via env `KG_CACHE_TTL_SEC` (default 3600).
- Per-request memoization for `patient_full_inference` so repeated sub-service
  calls within the same inference share work.

Telemetry
---------
Every public entry point times itself and writes a row to `kg_query_log` for
observability.  Failures to write telemetry never break the user-visible call.
"""
from __future__ import annotations

import functools
import json
import logging
import os
import re
import time
from collections import deque
from datetime import datetime, timedelta
from threading import RLock
from typing import Any, Callable, Iterable

from app.db import raf_cursor

logger = logging.getLogger(__name__)


def _calibration_service():
    """Lazy import of the KG calibration service.

    Kept lazy so the module's import-time graph stays minimal — the
    service has no third-party dependencies but we follow the same
    pattern as the other sub-service shims for consistency.
    """
    from app.services.knowledge_graph import calibration_service
    return calibration_service


# ---------------------------------------------------------------------------
# Sub-service loader — graceful degradation if a sibling agent hasn't merged
# ---------------------------------------------------------------------------

_SUB_SERVICES: dict[str, Any] = {}
_SUB_SERVICE_NAMES: tuple[str, ...] = (
    "snomed_service",
    "loinc_service",
    "atc_service",
    "comorbidity_engine",
    "demographic_risk_service",
    "specialty_priors_service",
    "evidence_rules_engine",
    "drug_class_reasoner",
)


_ICD10_RE = re.compile(r"^[A-Z]\d{2}(\.?\d{1,4})?$", re.IGNORECASE)


def _looks_like_icd10(text: str) -> bool:
    """True when *text* matches an ICD-10-CM code shape (e.g. E1140, E11.40)."""
    return bool(_ICD10_RE.match(text or ""))


def _load_sub_services() -> None:
    """Try to import each sibling sub-service. Missing ones are recorded as None."""
    for name in _SUB_SERVICE_NAMES:
        if name in _SUB_SERVICES:
            continue
        try:
            module = __import__(
                f"app.services.knowledge_graph.{name}",
                fromlist=[name],
            )
            _SUB_SERVICES[name] = module
        except Exception as exc:  # ImportError or anything else loading the module
            logger.info("kg sub-service unavailable: %s (%s)", name, exc)
            _SUB_SERVICES[name] = None


def _get_sub(name: str) -> Any | None:
    """Return the sub-service module if loaded, else None."""
    if name not in _SUB_SERVICES:
        _load_sub_services()
    return _SUB_SERVICES.get(name)


def reload_sub_services() -> dict[str, bool]:
    """Force a reload of sub-service availability (used by tests)."""
    _SUB_SERVICES.clear()
    _load_sub_services()
    return {name: _SUB_SERVICES.get(name) is not None for name in _SUB_SERVICE_NAMES}


# ---------------------------------------------------------------------------
# Telemetry — kg_query_log
# ---------------------------------------------------------------------------

def _log_query(
    query_type: str,
    params: dict[str, Any] | None,
    duration_ms: int,
    result_count: int,
    cached: bool = False,
) -> None:
    """Write one row to kg_query_log. Never raises — logs and swallows errors."""
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                INSERT INTO kg_query_log
                    (query_type, params_json, duration_ms, result_count, cached)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    query_type,
                    json.dumps(params or {}, default=str),
                    int(duration_ms),
                    int(result_count),
                    1 if cached else 0,
                ),
            )
    except Exception as exc:
        logger.debug("kg_query_log insert failed (non-fatal): %s", exc)


def _timed(query_type: str) -> Callable:
    """Decorator: time the call, then log to kg_query_log."""

    def deco(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            start = time.perf_counter()
            cached = False
            try:
                result = fn(*args, **kwargs)
                if isinstance(result, dict) and result.get("_cached"):
                    cached = True
                return result
            finally:
                duration_ms = int((time.perf_counter() - start) * 1000)
                count = _result_count(result if "result" in dir() else None)
                # Capture only safely-serializable params
                safe_params = _safe_params(args, kwargs)
                _log_query(query_type, safe_params, duration_ms, count, cached=cached)

        return wrapper

    return deco


def _result_count(result: Any) -> int:
    if result is None:
        return 0
    if isinstance(result, list):
        return len(result)
    if isinstance(result, dict):
        for key in ("candidates", "evidence_chain", "results", "items"):
            v = result.get(key)
            if isinstance(v, list):
                return len(v)
        return 1
    return 1


def _safe_params(args: tuple, kwargs: dict) -> dict[str, Any]:
    """Return a JSON-safe subset of the call args for logging."""
    out: dict[str, Any] = {}
    for i, a in enumerate(args):
        if isinstance(a, (str, int, float, bool, type(None))):
            out[f"arg{i}"] = a
        elif isinstance(a, dict):
            out[f"arg{i}"] = {k: v for k, v in a.items()
                              if isinstance(v, (str, int, float, bool, type(None)))}
    for k, v in kwargs.items():
        if isinstance(v, (str, int, float, bool, type(None))):
            out[k] = v
        elif isinstance(v, dict):
            out[k] = {kk: vv for kk, vv in v.items()
                      if isinstance(vv, (str, int, float, bool, type(None)))}
    return out


# ---------------------------------------------------------------------------
# TTL LRU cache
# ---------------------------------------------------------------------------

_CACHE_TTL = int(os.getenv("KG_CACHE_TTL_SEC", "3600"))
_cache_lock = RLock()
_cache: dict[str, tuple[float, Any]] = {}


def _cache_get(key: str) -> Any | None:
    with _cache_lock:
        item = _cache.get(key)
        if not item:
            return None
        ts, val = item
        if time.time() - ts > _CACHE_TTL:
            del _cache[key]
            return None
        return val


def _cache_set(key: str, val: Any) -> None:
    with _cache_lock:
        _cache[key] = (time.time(), val)


def clear_cache() -> None:
    """Clear the in-memory KG cache (used by tests / admin)."""
    with _cache_lock:
        _cache.clear()


# ---------------------------------------------------------------------------
# Internal helpers — lookups against existing KG tables
# ---------------------------------------------------------------------------

def _safe_call(sub_name: str, fn_name: str, *args, **kwargs) -> Any:
    """
    Invoke `sub_name.fn_name(*args, **kwargs)`.  Returns the function's result
    on success.  On any error (missing module, missing function, exception)
    returns None and logs.  This is the core of graceful degradation.
    """
    sub = _get_sub(sub_name)
    if sub is None:
        logger.debug("kg sub-service '%s' unavailable; skipping %s", sub_name, fn_name)
        return None
    fn = getattr(sub, fn_name, None)
    if not callable(fn):
        logger.debug("kg sub-service '%s' has no callable '%s'", sub_name, fn_name)
        return None
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        logger.warning("kg sub-service %s.%s failed: %s", sub_name, fn_name, exc)
        return None


def _query_kg_concept(uri_or_text: str) -> dict[str, Any] | None:
    """Resolve a string to a concept row (URI lookup, then text search)."""
    try:
        with raf_cursor() as cur:
            cur.execute(
                "SELECT * FROM knowledge_graph_concepts WHERE concept_uri=%s LIMIT 1",
                (uri_or_text,),
            )
            row = cur.fetchone()
            if row:
                return row
            cur.execute(
                """
                SELECT * FROM knowledge_graph_concepts
                WHERE label LIKE %s OR concept_id = %s
                ORDER BY (label = %s) DESC
                LIMIT 1
                """,
                (f"%{uri_or_text}%", uri_or_text, uri_or_text),
            )
            return cur.fetchone()
    except Exception as exc:
        logger.debug("knowledge_graph_concepts lookup failed: %s", exc)
        return None


def _kg_edges_from(start_uri: str) -> list[dict[str, Any]]:
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT source_uri, target_uri, relation, weight
                FROM knowledge_graph_edges
                WHERE source_uri=%s
                """,
                (start_uri,),
            )
            return cur.fetchall() or []
    except Exception as exc:
        logger.debug("knowledge_graph_edges lookup failed: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Public API: get_related_hccs
# ---------------------------------------------------------------------------

def get_related_hccs(
    concept_uri_or_text: str,
    patient_context: dict[str, Any] | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """
    Single entry point: 'tell me what HCCs are related to this concept for
    THIS patient'.

    Walks: text → SNOMED → ICD-10 → HCC → comorbidity-upgrade →
    demographic-modulation → specialty-prior → evidence-rule attribution.

    Returns ranked list with full reasoning chain per HCC.
    """
    start = time.perf_counter()
    patient_context = patient_context or {}
    candidates: dict[str, dict[str, Any]] = {}

    # 1. Resolve concept (text → SNOMED/ICD-10/concept_uri)
    icd_codes: list[str] = []

    # 1a. If the input already looks like an ICD-10 code or "icd10:..." URI,
    #     short-circuit straight into the ICD list. This is critical because the
    #     SNOMED resolver only does fuzzy text-matching and won't recognise raw
    #     codes.
    raw = (concept_uri_or_text or "").strip()
    if raw.lower().startswith("icd10:"):
        icd_codes.append(raw.split(":", 1)[1].strip())
    elif _looks_like_icd10(raw):
        icd_codes.append(raw)

    if not icd_codes:
        snomed_matches = _safe_call(
            "snomed_service", "resolve_text_to_snomed", concept_uri_or_text
        ) or []
        for m in snomed_matches or []:
            # resolve_text_to_snomed returns Concept objects; pull the SNOMED id
            # then crosswalk to ICD-10 via snomed_to_icd10.
            sid = getattr(m, "code", None) or (m.get("code") if isinstance(m, dict) else None)
            if not sid:
                continue
            mapped = _safe_call("snomed_service", "snomed_to_icd10", sid) or []
            if isinstance(mapped, list):
                icd_codes.extend(str(c) for c in mapped)

    # Fallback: try concept-graph row
    concept_row = _query_kg_concept(concept_uri_or_text)
    if concept_row and not icd_codes:
        # If the concept itself is an ICD-10 row, use its code directly.
        if str(concept_row.get("ontology", "")).lower() == "icd10":
            code = concept_row.get("code")
            if code:
                icd_codes.append(str(code))
        # Some KG concepts carry icd10 in metadata JSON as a list
        attrs = concept_row.get("metadata") or concept_row.get("attributes") or {}
        if isinstance(attrs, str):
            try:
                attrs = json.loads(attrs)
            except Exception:
                attrs = {}
        if isinstance(attrs, dict):
            icd_codes.extend(attrs.get("icd10_codes") or [])

    # 2. Map ICDs → HCCs via evidence-rules engine (preferred — has citations).
    # The engine's public entry point is ``evaluate_evidence(evidence: dict)``,
    # not ``fire_rules_for_codes`` — call the real function, then also fall back
    # to the canonical ICD-10 → HCC crosswalk so plain codes always map.
    if icd_codes:
        rule_hits = _safe_call(
            "evidence_rules_engine",
            "evaluate_evidence",
            {"icd10": [str(c) for c in icd_codes]},
        ) or []
        for hit in rule_hits or []:
            if not isinstance(hit, dict):
                continue
            hcc = str(
                hit.get("output_hcc") or hit.get("hcc_code") or hit.get("hcc") or ""
            ).strip()
            if not hcc:
                continue
            cand = candidates.setdefault(hcc, {
                "hcc": hcc,
                "confidence": 0.0,
                "sources": [],
                "reasoning": [],
            })
            cand["sources"].append("evidence_rules_engine")
            cand["reasoning"].append({
                "kind": "evidence_rule",
                "rule_id": hit.get("rule_id"),
                "citation": hit.get("source_citation") or hit.get("citation"),
                "icd10": hit.get("output_icd10") or hit.get("icd10"),
            })
            cand["confidence"] = max(cand["confidence"], float(hit.get("confidence", 0.6)))

        # 2b. Crosswalk fallback — for every ICD code, snomed_service.icd10_to_hcc
        # consults hcc_icd10_crosswalk + KG edges. This guarantees a result when
        # no curated rule fires.
        for icd in icd_codes:
            xs = _safe_call("snomed_service", "icd10_to_hcc", icd) or []
            for hit in xs or []:
                if not isinstance(hit, dict):
                    continue
                hcc = str(hit.get("hcc_code") or "").strip()
                if not hcc:
                    continue
                cand = candidates.setdefault(hcc, {
                    "hcc": hcc, "confidence": 0.0, "sources": [], "reasoning": [],
                })
                if "hcc_icd10_crosswalk" not in cand["sources"]:
                    cand["sources"].append("hcc_icd10_crosswalk")
                cand["reasoning"].append({
                    "kind": "icd10_crosswalk",
                    "icd10": hit.get("icd10_code") or icd,
                    "hcc_label": hit.get("hcc_label"),
                    "model_version": hit.get("model_version"),
                })
                cand["confidence"] = max(cand["confidence"], 0.5)

    # 3. Drug-class inference (only if patient_context provides drugs)
    drugs = patient_context.get("drugs") or []
    if drugs:
        drug_hits = _safe_call("drug_class_reasoner", "infer_hccs_from_drugs", drugs) or []
        for hit in drug_hits or []:
            if not isinstance(hit, dict):
                continue
            hcc = str(hit.get("hcc_code") or hit.get("hcc") or "").strip()
            if not hcc:
                continue
            cand = candidates.setdefault(hcc, {
                "hcc": hcc, "confidence": 0.0, "sources": [], "reasoning": [],
            })
            cand["sources"].append("drug_class_reasoner")
            cand["reasoning"].append({
                "kind": "drug_class",
                "drug": hit.get("drug"),
                "atc_class": hit.get("atc_class"),
            })
            cand["confidence"] = max(cand["confidence"], float(hit.get("confidence", 0.5)))

    # 4. Lab signals
    labs = patient_context.get("labs") or []
    if labs:
        lab_hits = _safe_call("loinc_service", "infer_hccs_from_labs", labs) or []
        for hit in lab_hits or []:
            if not isinstance(hit, dict):
                continue
            hcc = str(hit.get("hcc_code") or hit.get("hcc") or "").strip()
            if not hcc:
                continue
            cand = candidates.setdefault(hcc, {
                "hcc": hcc, "confidence": 0.0, "sources": [], "reasoning": [],
            })
            cand["sources"].append("loinc_service")
            cand["reasoning"].append({
                "kind": "lab_signal",
                "loinc": hit.get("loinc"),
                "value": hit.get("value"),
                "interpretation": hit.get("interpretation"),
            })
            cand["confidence"] = max(cand["confidence"], float(hit.get("confidence", 0.55)))

    # 5. Comorbidity upgrade — fold in prior_hccs
    prior_hccs = list(candidates.keys()) + list(patient_context.get("prior_hccs") or [])
    if prior_hccs:
        upgrades = _safe_call(
            "comorbidity_engine",
            "find_upgrades",
            prior_hccs,
        ) or []
        for up in upgrades or []:
            if not isinstance(up, dict):
                continue
            hcc = str(up.get("upgraded_hcc") or up.get("hcc") or "").strip()
            if not hcc:
                continue
            cand = candidates.setdefault(hcc, {
                "hcc": hcc, "confidence": 0.0, "sources": [], "reasoning": [],
            })
            cand["sources"].append("comorbidity_engine")
            cand["reasoning"].append({
                "kind": "comorbidity_upgrade",
                "from_hccs": up.get("from_hccs"),
                "pattern": up.get("pattern"),
            })
            cand["confidence"] = max(cand["confidence"], float(up.get("confidence", 0.5)))

    # 6. Demographic modulation
    if patient_context.get("age") is not None or patient_context.get("sex"):
        modulated = _safe_call(
            "demographic_risk_service",
            "modulate",
            list(candidates.keys()),
            patient_context,
        ) or {}
        if isinstance(modulated, dict):
            for hcc, mult in modulated.items():
                if hcc in candidates and isinstance(mult, (int, float)):
                    candidates[hcc]["confidence"] = min(
                        1.0, candidates[hcc]["confidence"] * float(mult)
                    )
                    candidates[hcc]["reasoning"].append({
                        "kind": "demographic_modulation",
                        "multiplier": float(mult),
                    })

    # 7. Specialty priors
    specialty = patient_context.get("specialty")
    if specialty:
        priors = _safe_call(
            "specialty_priors_service",
            "get_priors_for_specialty",
            specialty,
        ) or {}
        if isinstance(priors, dict):
            for hcc, prior in priors.items():
                if hcc in candidates and isinstance(prior, (int, float)):
                    # Calibrate confidence by combining with prior
                    candidates[hcc]["confidence"] = min(
                        1.0, (candidates[hcc]["confidence"] + float(prior)) / 2
                    )
                    candidates[hcc]["reasoning"].append({
                        "kind": "specialty_prior",
                        "specialty": specialty,
                        "prior": float(prior),
                    })

    # 8. Rank
    ranked = sorted(
        candidates.values(),
        key=lambda c: c["confidence"],
        reverse=True,
    )[:limit]

    # Apply Platt-scaling calibration so callers see calibrated probs.
    # See patient_full_inference for the rationale; we surface both raw
    # and calibrated values per candidate.
    a, b = _calibration_service().load_calibration()
    is_identity = _calibration_service().is_identity(a, b)
    for cand in ranked:
        try:
            raw = float(cand.get("confidence") or 0.0)
        except (TypeError, ValueError):
            raw = 0.0
        cand["raw_confidence"] = raw
        if is_identity:
            cand["calibrated_confidence"] = raw
        else:
            cand["calibrated_confidence"] = round(
                _calibration_service().apply_calibration(raw, a, b), 4
            )
            cand["confidence"] = cand["calibrated_confidence"]

    duration_ms = int((time.perf_counter() - start) * 1000)
    _log_query(
        "get_related_hccs",
        {"concept": concept_uri_or_text, "limit": limit},
        duration_ms,
        len(ranked),
    )
    return ranked


# ---------------------------------------------------------------------------
# Public API: get_evidence_chain
# ---------------------------------------------------------------------------

def get_evidence_chain(
    hcc_code: str,
    patient_id: int,
    year: int = 2026,
) -> dict[str, Any]:
    """
    'Why this HCC for this patient' — pulls every piece of evidence from every
    sub-service.

    Returns: {hcc, suggested_icd10, evidence_chain: [{kind, source, citation,
              value, contribution_to_score}], total_score, decision_tree}
    """
    start = time.perf_counter()
    hcc_code = str(hcc_code).replace("HCC", "").strip()
    chain: list[dict[str, Any]] = []
    decision_tree: list[dict[str, Any]] = []

    # Pull evidence from each sub-service
    rules = _safe_call(
        "evidence_rules_engine",
        "get_evidence_for_patient_hcc",
        patient_id, hcc_code, year,
    ) or []
    for r in rules or []:
        if not isinstance(r, dict):
            continue
        chain.append({
            "kind": "evidence_rule",
            "source": "evidence_rules_engine",
            "citation": r.get("citation"),
            "value": r.get("value"),
            "contribution_to_score": r.get("contribution", 0.6),
        })
        decision_tree.append({"step": "rule_match", "rule_id": r.get("rule_id")})

    drug_evidence = _safe_call(
        "drug_class_reasoner",
        "evidence_for_patient_hcc",
        patient_id, hcc_code,
    ) or []
    for r in drug_evidence or []:
        if not isinstance(r, dict):
            continue
        chain.append({
            "kind": "drug_class",
            "source": "drug_class_reasoner",
            "citation": r.get("atc_class"),
            "value": r.get("drug"),
            "contribution_to_score": r.get("contribution", 0.4),
        })
        decision_tree.append({"step": "drug_match", "drug": r.get("drug")})

    lab_evidence = _safe_call(
        "loinc_service",
        "evidence_for_patient_hcc",
        patient_id, hcc_code,
    ) or []
    for r in lab_evidence or []:
        if not isinstance(r, dict):
            continue
        chain.append({
            "kind": "lab_signal",
            "source": "loinc_service",
            "citation": r.get("loinc"),
            "value": r.get("value"),
            "contribution_to_score": r.get("contribution", 0.4),
        })
        decision_tree.append({"step": "lab_signal", "loinc": r.get("loinc")})

    comorb_evidence = _safe_call(
        "comorbidity_engine",
        "evidence_for_patient_hcc",
        patient_id, hcc_code,
    ) or []
    for r in comorb_evidence or []:
        if not isinstance(r, dict):
            continue
        chain.append({
            "kind": "comorbidity",
            "source": "comorbidity_engine",
            "citation": r.get("pattern"),
            "value": r.get("from_hccs"),
            "contribution_to_score": r.get("contribution", 0.5),
        })

    suggested_icd = _safe_call(
        "evidence_rules_engine",
        "suggest_icd10_for_hcc",
        hcc_code,
    )

    total_score = round(sum(item.get("contribution_to_score", 0.0) for item in chain), 3)

    out = {
        "hcc": hcc_code,
        "patient_id": patient_id,
        "year": year,
        "suggested_icd10": suggested_icd or [],
        "evidence_chain": chain,
        "total_score": total_score,
        "decision_tree": decision_tree,
    }

    duration_ms = int((time.perf_counter() - start) * 1000)
    _log_query(
        "get_evidence_chain",
        {"hcc_code": hcc_code, "patient_id": patient_id, "year": year},
        duration_ms,
        len(chain),
    )
    return out


# ---------------------------------------------------------------------------
# Public API: traverse_path  (BFS through knowledge_graph_edges)
# ---------------------------------------------------------------------------

def traverse_path(
    start_uri: str,
    end_uri: str,
    max_depth: int = 5,
) -> list[dict[str, Any]]:
    """BFS through knowledge_graph_edges to find shortest path between two concepts."""
    cache_key = f"traverse:{start_uri}:{end_uri}:{max_depth}"
    cached = _cache_get(cache_key)
    if cached is not None:
        _log_query("traverse_path",
                   {"start": start_uri, "end": end_uri, "max_depth": max_depth},
                   0, len(cached), cached=True)
        return cached

    start = time.perf_counter()
    if start_uri == end_uri:
        path = [{"node": start_uri, "depth": 0}]
        _cache_set(cache_key, path)
        return path

    visited: set[str] = {start_uri}
    queue: deque = deque()
    # Each queue entry is (current_node, path_so_far)
    queue.append((start_uri, [{"node": start_uri, "relation": None, "depth": 0}]))

    found: list[dict[str, Any]] = []
    while queue:
        node, path = queue.popleft()
        if len(path) - 1 >= max_depth:
            continue
        for edge in _kg_edges_from(node):
            tgt = edge.get("target_uri")
            if not tgt or tgt in visited:
                continue
            visited.add(tgt)
            new_path = path + [{
                "node": tgt,
                "relation": edge.get("relation"),
                "depth": len(path),
                "weight": float(edge.get("weight") or 0.0),
            }]
            if tgt == end_uri:
                found = new_path
                queue.clear()
                break
            queue.append((tgt, new_path))
        if found:
            break

    duration_ms = int((time.perf_counter() - start) * 1000)
    _log_query("traverse_path",
               {"start": start_uri, "end": end_uri, "max_depth": max_depth},
               duration_ms, len(found))
    _cache_set(cache_key, found)
    return found


# ---------------------------------------------------------------------------
# Public API: explain_hcc  (static description)
# ---------------------------------------------------------------------------

def explain_hcc(hcc_code: str) -> dict[str, Any]:
    """
    Static explanation for an HCC: definition + ICD codes + common drugs +
    common labs + comorbidities + literature citations.
    """
    hcc_code = str(hcc_code).replace("HCC", "").strip()
    cache_key = f"explain:{hcc_code}"
    cached = _cache_get(cache_key)
    if cached is not None:
        _log_query("explain_hcc", {"hcc_code": hcc_code}, 0, 1, cached=True)
        return cached

    start = time.perf_counter()

    definition = _safe_call("evidence_rules_engine", "get_hcc_definition", hcc_code) or {}
    icd10 = _safe_call("evidence_rules_engine", "suggest_icd10_for_hcc", hcc_code) or []
    drugs = _safe_call("drug_class_reasoner", "common_drugs_for_hcc", hcc_code) or []
    labs = _safe_call("loinc_service", "common_labs_for_hcc", hcc_code) or []
    comorbs = _safe_call("comorbidity_engine", "common_comorbidities_for_hcc", hcc_code) or []
    citations = _safe_call("evidence_rules_engine", "citations_for_hcc", hcc_code) or []

    # Hccinfhir label as a final fallback for definition
    if not definition:
        try:
            from hccinfhir.defaults import labels_default
            label = labels_default.get((hcc_code, "CMS-HCC Model V28"))
            if label:
                definition = {"label": label, "model": "CMS-HCC Model V28"}
        except Exception:
            pass

    out = {
        "hcc": hcc_code,
        "definition": definition,
        "icd10_codes": icd10,
        "common_drugs": drugs,
        "common_labs": labs,
        "common_comorbidities": comorbs,
        "citations": citations,
    }
    _cache_set(cache_key, out)
    duration_ms = int((time.perf_counter() - start) * 1000)
    _log_query("explain_hcc", {"hcc_code": hcc_code}, duration_ms, 1)
    return out


# ---------------------------------------------------------------------------
# Public API: patient_full_inference  (the big-bang call)
# ---------------------------------------------------------------------------

def patient_full_inference(
    patient_id: int,
    year: int = 2026,
    include_modulation: bool = True,
) -> dict[str, Any]:
    """
    The big-bang call: pull patient's drugs, labs, ICD codes, demographics,
    specialty.  Run through every sub-service and return ranked HCC candidates
    with reasoning chains and a per-call execution log.
    """
    start = time.perf_counter()
    execution_log: list[dict[str, Any]] = []

    def _record(service: str, fn: str, ok: bool, latency_ms: int, note: str = "") -> None:
        execution_log.append({
            "service": service,
            "fn": fn,
            "ok": ok,
            "latency_ms": latency_ms,
            "note": note,
        })

    def _timed_call(service: str, fn: str, *a, **kw):
        sub = _get_sub(service)
        if sub is None:
            _record(service, fn, False, 0, "service_unavailable")
            return None
        target = getattr(sub, fn, None)
        if not callable(target):
            _record(service, fn, False, 0, "fn_unavailable")
            return None
        t0 = time.perf_counter()
        try:
            result = target(*a, **kw)
            ok = True
            note = ""
        except Exception as exc:
            result = None
            ok = False
            note = f"error: {exc}"
            logger.warning("kg sub-service %s.%s raised: %s", service, fn, exc)
        latency_ms = int((time.perf_counter() - t0) * 1000)
        _record(service, fn, ok, latency_ms, note)
        return result

    # 1. Pull patient context (best-effort — emr connector may or may not exist)
    patient_context: dict[str, Any] = {"patient_id": patient_id, "year": year}
    drugs: list[Any] = []
    labs: list[Any] = []
    icd_codes: list[str] = []
    prior_hccs: list[str] = []

    try:
        from app.services import openemr_connector as emr  # local import — optional
        try:
            patient = emr.get_patient(patient_id) or {}
            patient_context["age"] = patient.get("age")
            patient_context["sex"] = patient.get("sex")
            patient_context["specialty"] = patient.get("provider_specialty")
        except Exception as exc:
            logger.debug("emr.get_patient failed: %s", exc)
        try:
            drugs = emr.get_medications(patient_id) or []
        except Exception:
            drugs = []
        try:
            labs = emr.get_lab_results(patient_id) or []
        except Exception:
            labs = []
        try:
            billing = emr.get_billing_codes(patient_id) or []
            icd_codes = [str(b.get("code") or "").strip() for b in billing if b.get("code")]
        except Exception:
            icd_codes = []
    except Exception as exc:
        logger.debug("openemr_connector unavailable: %s", exc)

    # Prior HCCs from raf_patient_hcc
    try:
        with raf_cursor() as cur:
            cur.execute(
                "SELECT DISTINCT hcc_code FROM raf_patient_hcc WHERE patient_id=%s",
                (patient_id,),
            )
            prior_hccs = [r["hcc_code"] for r in (cur.fetchall() or []) if r.get("hcc_code")]
    except Exception as exc:
        logger.debug("prior_hccs fetch failed: %s", exc)

    patient_context["drugs"] = drugs
    patient_context["labs"] = labs
    patient_context["icd10_codes"] = icd_codes
    patient_context["prior_hccs"] = prior_hccs

    candidates: dict[str, dict[str, Any]] = {}

    def _bump(hcc: str, *, source: str, reason: dict, conf: float) -> None:
        cand = candidates.setdefault(hcc, {
            "hcc": hcc,
            "confidence": 0.0,
            "sources": [],
            "reasoning": [],
        })
        cand["sources"].append(source)
        cand["reasoning"].append(reason)
        cand["confidence"] = max(cand["confidence"], float(conf))

    # 2. Evidence rules — strongest signal
    rule_hits = _timed_call("evidence_rules_engine", "fire_rules_for_patient",
                            patient_id, year=year) or []
    for hit in rule_hits or []:
        if not isinstance(hit, dict):
            continue
        hcc = str(hit.get("hcc_code") or hit.get("hcc") or "").strip()
        if not hcc:
            continue
        _bump(hcc,
              source="evidence_rules_engine",
              reason={"kind": "evidence_rule",
                      "rule_id": hit.get("rule_id"),
                      "citation": hit.get("citation"),
                      "icd10": hit.get("icd10")},
              conf=float(hit.get("confidence", 0.7)))

    # 3. Drug-class
    if drugs:
        drug_hits = _timed_call("drug_class_reasoner", "infer_hccs_from_drugs", drugs) or []
        for hit in drug_hits or []:
            if not isinstance(hit, dict):
                continue
            hcc = str(hit.get("hcc_code") or hit.get("hcc") or "").strip()
            if not hcc:
                continue
            _bump(hcc,
                  source="drug_class_reasoner",
                  reason={"kind": "drug_class", "drug": hit.get("drug"),
                          "atc_class": hit.get("atc_class")},
                  conf=float(hit.get("confidence", 0.5)))

    # 4. Labs
    if labs:
        lab_hits = _timed_call("loinc_service", "infer_hccs_from_labs", labs) or []
        for hit in lab_hits or []:
            if not isinstance(hit, dict):
                continue
            hcc = str(hit.get("hcc_code") or hit.get("hcc") or "").strip()
            if not hcc:
                continue
            _bump(hcc,
                  source="loinc_service",
                  reason={"kind": "lab_signal", "loinc": hit.get("loinc"),
                          "value": hit.get("value")},
                  conf=float(hit.get("confidence", 0.55)))

    # 5. SNOMED matches from problem list (use patient's problem list / ICDs)
    if icd_codes:
        snomed_hits = _timed_call("snomed_service", "infer_hccs_from_icd10", icd_codes) or []
        for hit in snomed_hits or []:
            if not isinstance(hit, dict):
                continue
            hcc = str(hit.get("hcc_code") or hit.get("hcc") or "").strip()
            if not hcc:
                continue
            _bump(hcc,
                  source="snomed_service",
                  reason={"kind": "snomed_match", "snomed_id": hit.get("snomed_id"),
                          "icd10": hit.get("icd10")},
                  conf=float(hit.get("confidence", 0.6)))

    # 6. Comorbidity upgrade
    all_known_hccs = list(set(list(candidates.keys()) + prior_hccs))
    if all_known_hccs:
        upgrades = _timed_call("comorbidity_engine", "find_upgrades", all_known_hccs) or []
        for up in upgrades or []:
            if not isinstance(up, dict):
                continue
            hcc = str(up.get("upgraded_hcc") or up.get("hcc") or "").strip()
            if not hcc:
                continue
            _bump(hcc,
                  source="comorbidity_engine",
                  reason={"kind": "comorbidity_upgrade",
                          "from_hccs": up.get("from_hccs"),
                          "pattern": up.get("pattern")},
                  conf=float(up.get("confidence", 0.5)))

    # 7. Demographic modulation
    if include_modulation and (patient_context.get("age") is not None or patient_context.get("sex")):
        mod = _timed_call("demographic_risk_service", "modulate",
                          list(candidates.keys()), patient_context) or {}
        if isinstance(mod, dict):
            for hcc, mult in mod.items():
                if hcc in candidates and isinstance(mult, (int, float)):
                    candidates[hcc]["confidence"] = min(
                        1.0, candidates[hcc]["confidence"] * float(mult)
                    )
                    candidates[hcc]["reasoning"].append({
                        "kind": "demographic_modulation",
                        "multiplier": float(mult),
                    })

    # 8. Specialty priors
    specialty = patient_context.get("specialty")
    if include_modulation and specialty:
        priors = _timed_call("specialty_priors_service",
                             "get_priors_for_specialty", specialty) or {}
        if isinstance(priors, dict):
            for hcc, prior in priors.items():
                if hcc in candidates and isinstance(prior, (int, float)):
                    candidates[hcc]["confidence"] = min(
                        1.0, (candidates[hcc]["confidence"] + float(prior)) / 2
                    )
                    candidates[hcc]["reasoning"].append({
                        "kind": "specialty_prior",
                        "specialty": specialty,
                        "prior": float(prior),
                    })

    ranked = sorted(
        candidates.values(),
        key=lambda c: c["confidence"],
        reverse=True,
    )

    # Apply Platt scaling to each candidate confidence so consumers see
    # well-calibrated probabilities.  We surface BOTH raw and calibrated
    # values; ``confidence`` is left as-is for backwards compatibility
    # (matches the legacy raw value when calibration is identity, matches
    # the calibrated value otherwise — see PR description).
    a, b = _calibration_service().load_calibration()
    is_identity = _calibration_service().is_identity(a, b)
    for cand in ranked:
        try:
            raw = float(cand.get("confidence") or 0.0)
        except (TypeError, ValueError):
            raw = 0.0
        cand["raw_confidence"] = raw
        if is_identity:
            cand["calibrated_confidence"] = raw
        else:
            cand["calibrated_confidence"] = round(
                _calibration_service().apply_calibration(raw, a, b), 4
            )
            # Promote the calibrated value into ``confidence`` so existing
            # downstream consumers (orchestrator, frontend) immediately
            # see calibrated numbers.  raw_confidence preserves the
            # original signal for diagnostics / parallel display.
            cand["confidence"] = cand["calibrated_confidence"]

    duration_ms = int((time.perf_counter() - start) * 1000)
    out = {
        "patient_id": patient_id,
        "year": year,
        "candidates": ranked,
        "execution_log": execution_log,
        "duration_ms": duration_ms,
        "calibration": {
            "a": a,
            "b": b,
            "applied": not is_identity,
        },
    }
    _log_query(
        "patient_full_inference",
        {"patient_id": patient_id, "year": year, "include_modulation": include_modulation},
        duration_ms,
        len(ranked),
    )
    return out


# ---------------------------------------------------------------------------
# Stats / observability
# ---------------------------------------------------------------------------

def get_query_stats(since_hours: int = 24) -> dict[str, Any]:
    """Aggregate kg_query_log for observability dashboards."""
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT query_type,
                       COUNT(*)            AS calls,
                       AVG(duration_ms)    AS avg_ms,
                       MAX(duration_ms)    AS max_ms,
                       SUM(cached)         AS cached_calls,
                       AVG(result_count)   AS avg_results
                FROM kg_query_log
                WHERE created_at >= NOW() - INTERVAL %s HOUR
                GROUP BY query_type
                ORDER BY calls DESC
                """,
                (int(since_hours),),
            )
            rows = cur.fetchall() or []
        # Convert decimals to floats
        clean = []
        for r in rows:
            clean.append({
                "query_type": r["query_type"],
                "calls": int(r["calls"] or 0),
                "avg_ms": float(r["avg_ms"] or 0.0),
                "max_ms": int(r["max_ms"] or 0),
                "cached_calls": int(r["cached_calls"] or 0),
                "avg_results": float(r["avg_results"] or 0.0),
            })
        return {"since_hours": since_hours, "by_type": clean}
    except Exception as exc:
        logger.warning("get_query_stats failed: %s", exc)
        return {"since_hours": since_hours, "by_type": [], "error": str(exc)}


def sub_service_status() -> dict[str, bool]:
    """Return availability of each sibling sub-service."""
    _load_sub_services()
    return {name: _SUB_SERVICES.get(name) is not None for name in _SUB_SERVICE_NAMES}


# Eagerly initialize the sub-service map at import time
_load_sub_services()
