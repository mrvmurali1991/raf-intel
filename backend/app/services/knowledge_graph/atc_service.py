"""
WHO ATC (Anatomical Therapeutic Chemical) classification service.

Surfaces a small set of high-level helpers that turn drug names / NDCs / RxCUIs
into ATC classes, walk the 5-level hierarchy, and resolve back to indications
(stored as ``knowledge_graph_concepts`` rows linked via ``has_indication`` edges)
and HCC codes.

The functions never raise on missing tables or empty rows — they degrade to an
empty list / ``None`` so callers (e.g. the ``suspect_engine`` fallback path) can
treat ATC inference as best-effort.

Public API
----------
- :func:`resolve_drug_to_atc`     — fuzzy match drug name / NDC / RxCUI → ATC.
- :func:`get_atc_hierarchy`       — full ancestor chain (level 1 → leaf).
- :func:`get_drugs_in_class`      — drugs mapped to an ATC class (and optional
  subclasses).
- :func:`get_indications_for_atc` — concepts treated by this ATC class.
- :func:`drug_to_hcc_chain`       — drug → RxNorm → ATC → indication → HCC
  reasoning chain.
- :func:`unseen_drug_inference`   — falls back through ATC parents when an
  exact RxNorm match is missing.
"""
from __future__ import annotations

import difflib
import json
import logging
from typing import Any

from app.db import raf_cursor

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

# Cutoff for difflib.get_close_matches.  We tune this for typo tolerance
# (``metformiin`` -> ``metformin``) but NOT semantic similarity — drugs in the
# same class often share long suffixes (e.g. ``albiglutide`` is 0.73 similar
# to ``semaglutide``) and we want those to fall through to the ATC class
# inference path instead of being labelled as exact bridge matches.
_FUZZY_CUTOFF = 0.85

# Maximum candidates returned by difflib for a single name lookup.
_FUZZY_TOP_N = 5


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _normalize(value: str | None) -> str:
    return (value or "").strip().lower()


def _row_to_atc(row: dict[str, Any]) -> dict[str, Any]:
    """Coerce a kg_atc_classes row into a serialisable dict."""
    indication_ids: list[int] = []
    raw = row.get("indication_concept_ids")
    if raw:
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8", errors="ignore")
        if isinstance(raw, str):
            try:
                indication_ids = list(json.loads(raw) or [])
            except (TypeError, ValueError):
                indication_ids = []
        elif isinstance(raw, list):
            indication_ids = list(raw)
    return {
        "id": row.get("id"),
        "atc_code": row.get("atc_code"),
        "name": row.get("name"),
        "level": int(row.get("level") or 0),
        "parent_atc_code": row.get("parent_atc_code"),
        "concept_id": row.get("concept_id"),
        "indication_concept_ids": indication_ids,
        "is_active": bool(row.get("is_active", 1)),
    }


def _row_to_concept(row: dict[str, Any]) -> dict[str, Any]:
    """Coerce a knowledge_graph_concepts row into a dict."""
    return {
        "id": row.get("id"),
        "ontology": row.get("ontology"),
        "code": row.get("code"),
        "display_name": row.get("display_name"),
        "description": row.get("description"),
    }


def _safe_fetch(sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    """Run a SELECT and return rows; return [] on any DB error."""
    try:
        with raf_cursor() as cur:
            cur.execute(sql, params)
            return list(cur.fetchall() or [])
    except Exception as exc:                     # pragma: no cover - DB-down path
        logger.warning("atc_service: query failed (%s): %s", sql.split()[0:4], exc)
        return []


def _brand_bridge_lookup(needle: str) -> tuple[str | None, str | None] | None:
    """Look up a brand name in ``kg_brand_to_generic`` and return
    ``(generic_name, atc_code)`` when it hits.

    Returns ``None`` when no row matches.  Both fields in the tuple may be
    independently ``None`` (e.g. some seeds know the generic but not the ATC).
    Implemented inline (no import of ``brand_generic_service``) to keep this
    module's call surface symmetric with the rest of ``_safe_fetch`` queries
    and to avoid a circular import when callers patch ``_safe_fetch`` in
    tests.
    """
    if not needle:
        return None
    rows = _safe_fetch(
        """
        SELECT generic_name, atc_code FROM kg_brand_to_generic
         WHERE LOWER(brand_name) = %s AND is_active = 1
         LIMIT 1
        """,
        (needle,),
    )
    if not rows:
        return None
    return rows[0].get("generic_name"), rows[0].get("atc_code")


# ---------------------------------------------------------------------------
# 1. resolve_drug_to_atc
# ---------------------------------------------------------------------------

def resolve_drug_to_atc(drug_name_or_ndc: str) -> list[dict[str, Any]]:
    """Resolve a drug name, RxCUI, or NDC string to ATC class entries.

    Resolution order:
      1. Exact NDC match.
      2. Exact RxCUI match.
      3. Exact case-insensitive drug-name match.
      4. ``difflib`` fuzzy drug-name match (cutoff = ``_FUZZY_CUTOFF``).

    Returns a list of dicts with keys: ``rxcui``, ``drug_name``, ``ndc``,
    ``atc_code``, ``is_brand``, ``is_generic``, plus the merged ATC class
    metadata (``name``, ``level``, ``parent_atc_code``, ``concept_id``,
    ``indication_concept_ids``).  Empty list when nothing matches.
    """
    needle = _normalize(drug_name_or_ndc)
    if not needle:
        return []

    # 1. NDC exact (NDCs may be stored with or without dashes — try both).
    ndc_clean = needle.replace("-", "")
    rows = _safe_fetch(
        """
        SELECT * FROM kg_rxnorm_to_atc
         WHERE ndc = %s OR REPLACE(ndc, '-', '') = %s
         LIMIT 50
        """,
        (drug_name_or_ndc, ndc_clean),
    )

    # 2. RxCUI exact.
    if not rows and needle.isdigit():
        rows = _safe_fetch(
            "SELECT * FROM kg_rxnorm_to_atc WHERE rxcui = %s LIMIT 50",
            (needle,),
        )

    # 3. Drug name exact.
    if not rows:
        rows = _safe_fetch(
            "SELECT * FROM kg_rxnorm_to_atc WHERE LOWER(drug_name) = %s LIMIT 50",
            (needle,),
        )

    # 3b. Brand-bridge: when the drug name didn't hit kg_rxnorm_to_atc directly,
    # check kg_brand_to_generic before falling through to fuzzy / stem
    # inference.  This makes ``Ozempic`` resolve to its generic ingredient
    # (semaglutide) and reuse whatever bridge row already exists for it.
    if not rows:
        bridged_atc = _brand_bridge_lookup(needle)
        if bridged_atc:
            generic_name, atc_code = bridged_atc
            # Try to surface the bridge row for the generic name first.
            if generic_name:
                rows = _safe_fetch(
                    "SELECT * FROM kg_rxnorm_to_atc WHERE LOWER(drug_name) = %s LIMIT 50",
                    (generic_name.lower(),),
                )
            # Synthesise a minimal pseudo-row when the bridge has no entry for
            # the generic — callers still get a usable ATC + drug_name.
            if not rows and atc_code:
                rows = [{
                    "rxcui": None,
                    "drug_name": generic_name or drug_name_or_ndc,
                    "ndc": None,
                    "atc_code": atc_code,
                    "is_brand": 0,
                    "is_generic": 1,
                }]

    # 4. Fuzzy fallback over distinct drug names.
    if not rows:
        candidates = _safe_fetch(
            "SELECT DISTINCT drug_name FROM kg_rxnorm_to_atc",
        )
        names = [r["drug_name"] for r in candidates if r.get("drug_name")]
        # Also try matching on the longest token in case the input looks like
        # "Glucophage XR 500 mg" — difflib aligns "glucophage" to "metformin"
        # poorly, but tokenizing improves recall.
        name_lower_to_orig: dict[str, str] = {n.lower(): n for n in names}
        matches = difflib.get_close_matches(
            needle, list(name_lower_to_orig), n=_FUZZY_TOP_N, cutoff=_FUZZY_CUTOFF
        )
        if not matches and " " in needle:
            for token in needle.split():
                token_matches = difflib.get_close_matches(
                    token, list(name_lower_to_orig), n=_FUZZY_TOP_N,
                    cutoff=_FUZZY_CUTOFF,
                )
                matches.extend(token_matches)
        if matches:
            originals = [name_lower_to_orig[m] for m in matches]
            placeholders = ",".join(["%s"] * len(originals))
            rows = _safe_fetch(
                f"SELECT * FROM kg_rxnorm_to_atc WHERE drug_name IN ({placeholders})",
                tuple(originals),
            )

    if not rows:
        return []

    # Join in ATC class metadata (single round-trip).
    atc_codes = sorted({r["atc_code"] for r in rows if r.get("atc_code")})
    if not atc_codes:
        return [{**r, "atc_class": None} for r in rows]
    placeholders = ",".join(["%s"] * len(atc_codes))
    classes = _safe_fetch(
        f"SELECT * FROM kg_atc_classes WHERE atc_code IN ({placeholders})",
        tuple(atc_codes),
    )
    by_code = {c["atc_code"]: _row_to_atc(c) for c in classes}

    out: list[dict[str, Any]] = []
    for r in rows:
        atc_meta = by_code.get(r.get("atc_code"))
        out.append(
            {
                "rxcui": r.get("rxcui"),
                "drug_name": r.get("drug_name"),
                "ndc": r.get("ndc"),
                "atc_code": r.get("atc_code"),
                "is_brand": bool(r.get("is_brand", 0)),
                "is_generic": bool(r.get("is_generic", 1)),
                "atc_class": atc_meta,
            }
        )
    return out


# ---------------------------------------------------------------------------
# 2. get_atc_hierarchy
# ---------------------------------------------------------------------------

def get_atc_hierarchy(atc_code: str) -> list[dict[str, Any]]:
    """Return the full hierarchy chain from level 1 to *atc_code*.

    Output is ordered from the anatomical main group (level 1) down to the
    requested code.  The walk follows ``parent_atc_code`` and bails out after
    six steps to defend against accidental cycles.
    """
    if not atc_code:
        return []

    chain: list[dict[str, Any]] = []
    current = atc_code.strip().upper()
    seen: set[str] = set()
    for _ in range(8):                          # hard cap; ATC depth = 5
        if not current or current in seen:
            break
        seen.add(current)
        rows = _safe_fetch(
            "SELECT * FROM kg_atc_classes WHERE atc_code = %s LIMIT 1",
            (current,),
        )
        if not rows:
            break
        node = _row_to_atc(rows[0])
        chain.append(node)
        current = (node.get("parent_atc_code") or "").upper() or ""

    chain.reverse()
    return chain


# ---------------------------------------------------------------------------
# 3. get_drugs_in_class
# ---------------------------------------------------------------------------

def get_drugs_in_class(
    atc_code: str, include_subclasses: bool = True
) -> list[dict[str, Any]]:
    """List RxNorm bridges that map to *atc_code* (and optionally subclasses).

    Subclass expansion is done by string prefix because ATC codes are
    hierarchical by construction (``A10BA02`` is a child of ``A10BA``).
    """
    if not atc_code:
        return []
    code = atc_code.strip().upper()

    if include_subclasses:
        rows = _safe_fetch(
            """
            SELECT b.*, c.name AS atc_name, c.level AS atc_level
              FROM kg_rxnorm_to_atc b
              LEFT JOIN kg_atc_classes c ON c.atc_code = b.atc_code
             WHERE b.atc_code = %s OR b.atc_code LIKE %s
             ORDER BY b.drug_name
            """,
            (code, f"{code}%"),
        )
    else:
        rows = _safe_fetch(
            """
            SELECT b.*, c.name AS atc_name, c.level AS atc_level
              FROM kg_rxnorm_to_atc b
              LEFT JOIN kg_atc_classes c ON c.atc_code = b.atc_code
             WHERE b.atc_code = %s
             ORDER BY b.drug_name
            """,
            (code,),
        )

    return [
        {
            "rxcui": r.get("rxcui"),
            "drug_name": r.get("drug_name"),
            "ndc": r.get("ndc"),
            "atc_code": r.get("atc_code"),
            "atc_name": r.get("atc_name"),
            "atc_level": r.get("atc_level"),
            "is_brand": bool(r.get("is_brand", 0)),
            "is_generic": bool(r.get("is_generic", 1)),
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# 4. get_indications_for_atc
# ---------------------------------------------------------------------------

def get_indications_for_atc(atc_code: str) -> list[dict[str, Any]]:
    """Return the disease concepts treated by *atc_code*.

    Two sources of indication data are merged:

      1. ``kg_atc_classes.indication_concept_ids`` — explicit concept-id JSON
         array set at seed time.
      2. ``knowledge_graph_edges`` rows of relation ``has_indication`` whose
         source is the ATC concept.

    Bubbles up through parent classes when the leaf node has no indications,
    because indications are typically defined at level 4 (e.g. A10BA →
    diabetes) rather than at level 5 (e.g. A10BA02 metformin).
    """
    if not atc_code:
        return []

    visited: set[str] = set()
    code = atc_code.strip().upper()
    while code and code not in visited:
        visited.add(code)
        rows = _safe_fetch(
            "SELECT * FROM kg_atc_classes WHERE atc_code = %s LIMIT 1",
            (code,),
        )
        if not rows:
            return []
        node = _row_to_atc(rows[0])
        concept_ids: list[int] = list(node.get("indication_concept_ids") or [])

        edge_rows = _safe_fetch(
            """
            SELECT target_concept_id FROM knowledge_graph_edges
             WHERE source_concept_id = %s AND relation = 'has_indication'
            """,
            (node["concept_id"],),
        )
        for er in edge_rows:
            tcid = er.get("target_concept_id")
            if tcid and tcid not in concept_ids:
                concept_ids.append(tcid)

        if concept_ids:
            placeholders = ",".join(["%s"] * len(concept_ids))
            concept_rows = _safe_fetch(
                f"SELECT * FROM knowledge_graph_concepts WHERE id IN ({placeholders})",
                tuple(concept_ids),
            )
            return [_row_to_concept(c) for c in concept_rows]

        # Walk up.
        code = (node.get("parent_atc_code") or "").upper()

    return []


# ---------------------------------------------------------------------------
# 5. drug_to_hcc_chain
# ---------------------------------------------------------------------------

def drug_to_hcc_chain(drug_name: str) -> dict[str, Any]:
    """Build the full reasoning chain drug → RxNorm → ATC → indication → HCC.

    Returns a dict with the resolved drug bridge, ATC hierarchy, indication
    concepts and any HCC concepts reachable via ``maps_to_hcc`` edges from
    those indications.  Returns an empty-shaped dict when resolution fails.
    """
    empty: dict[str, Any] = {
        "drug_name": drug_name,
        "matched_drug": None,
        "rxcui": None,
        "ndc": None,
        "atc_code": None,
        "hierarchy": [],
        "indications": [],
        "hccs": [],
    }

    matches = resolve_drug_to_atc(drug_name)
    if not matches:
        return empty

    # Pick the highest-fidelity match: generic > brand, longest atc_code first.
    matches.sort(
        key=lambda m: (
            0 if m.get("is_generic") else 1,
            -len(m.get("atc_code") or ""),
        )
    )
    head = matches[0]
    atc_code = head.get("atc_code") or ""

    hierarchy = get_atc_hierarchy(atc_code)
    indications = get_indications_for_atc(atc_code)

    # Indication → HCC via knowledge_graph_edges (relation='maps_to_hcc').
    hccs: list[dict[str, Any]] = []
    if indications:
        ind_ids = [c["id"] for c in indications if c.get("id")]
        if ind_ids:
            placeholders = ",".join(["%s"] * len(ind_ids))
            edge_rows = _safe_fetch(
                f"""
                SELECT DISTINCT target_concept_id FROM knowledge_graph_edges
                 WHERE source_concept_id IN ({placeholders})
                   AND relation = 'maps_to_hcc'
                """,
                tuple(ind_ids),
            )
            target_ids = [r["target_concept_id"] for r in edge_rows if r.get("target_concept_id")]
            if target_ids:
                placeholders = ",".join(["%s"] * len(target_ids))
                hcc_rows = _safe_fetch(
                    f"""
                    SELECT * FROM knowledge_graph_concepts
                     WHERE id IN ({placeholders}) AND ontology = 'hcc'
                    """,
                    tuple(target_ids),
                )
                hccs = [_row_to_concept(r) for r in hcc_rows]

    return {
        "drug_name": drug_name,
        "matched_drug": head.get("drug_name"),
        "rxcui": head.get("rxcui"),
        "ndc": head.get("ndc"),
        "atc_code": atc_code,
        "hierarchy": hierarchy,
        "indications": indications,
        "hccs": hccs,
    }


# ---------------------------------------------------------------------------
# 6. unseen_drug_inference
# ---------------------------------------------------------------------------

def unseen_drug_inference(drug_name: str) -> dict[str, Any]:
    """Infer a likely class membership for a drug not in the RxNorm bridge.

    Strategy:
      1. If :func:`resolve_drug_to_atc` returns a hit, just emit that chain.
      2. Otherwise, try a fuzzy match against the ATC class display names —
         e.g. ``"tirzepatide"`` may not be in the bridge but the GLP-1 class
         ``A10BJ "Glucagon-like peptide-1 (GLP-1) analogues"`` exists.
      3. As a last resort, try fuzzy-matching against the cached set of
         indication concept names (e.g. "ozempic" → "diabetes" → A10BJ).

    The result always contains ``inferred=True`` when the inference path was
    used (vs an exact bridge match).  Callers should treat ``inferred`` chains
    as lower confidence.
    """
    base = drug_to_hcc_chain(drug_name)
    if base["atc_code"]:
        return {**base, "inferred": False, "inference_path": "exact_bridge"}

    needle = _normalize(drug_name)
    if not needle:
        return {**base, "inferred": False, "inference_path": "no_input"}

    # Step 2: fuzzy class-name match.
    class_rows = _safe_fetch(
        "SELECT atc_code, name FROM kg_atc_classes WHERE is_active = 1"
    )
    name_to_code: dict[str, str] = {
        (r["name"] or "").lower(): r["atc_code"] for r in class_rows if r.get("name")
    }
    fuzzy = difflib.get_close_matches(
        needle, list(name_to_code), n=3, cutoff=0.55,
    )

    # Also try common drug-stem heuristics: "-glutide" → GLP-1, "-gliflozin" → SGLT-2,
    # "-pril" → ACE inhibitors, "-sartan" → ARBs, "-statin" → statins, "-azepam" → BZD.
    stem_hits: list[str] = []
    stem_to_class = {
        "glutide": "A10BJ",     # GLP-1 analogues
        # tirzepatide (GIP/GLP-1 dual agonist) and similar peptides are
        # classified by WHO under "other blood glucose lowering drugs".
        "zepatide": "A10BX",    # GIP/GLP-1 dual agonists
        "gliflozin": "A10BK",   # SGLT-2 inhibitors
        "gliptin": "A10BH",     # DPP-4 inhibitors
        "pril": "C09AA",        # ACE inhibitors
        "sartan": "C09CA",      # ARBs
        "statin": "C10AA",      # HMG-CoA reductase inhibitors
        "olol": "C07AB",        # Beta blockers (selective)
        "xaban": "B01AF",       # Direct factor Xa inhibitors (DOACs)
        "parin": "B01AB",       # Heparin group
        "azepam": "N05BA",      # Benzodiazepines (anxiolytics)
        "azole": "J02AC",       # Triazole antifungals
    }
    for stem, code in stem_to_class.items():
        if stem in needle:
            stem_hits.append(code)

    candidate_code: str | None = None
    inference_path: str = ""
    if stem_hits:
        candidate_code = stem_hits[0]
        inference_path = f"stem:{stem_hits[0]}"
    elif fuzzy:
        candidate_code = name_to_code[fuzzy[0]]
        inference_path = "class_name_fuzzy"

    if not candidate_code:
        return {**base, "inferred": False, "inference_path": "no_match"}

    hierarchy = get_atc_hierarchy(candidate_code)
    indications = get_indications_for_atc(candidate_code)

    # HCCs from indications (mirror drug_to_hcc_chain).
    hccs: list[dict[str, Any]] = []
    if indications:
        ind_ids = [c["id"] for c in indications if c.get("id")]
        if ind_ids:
            placeholders = ",".join(["%s"] * len(ind_ids))
            edge_rows = _safe_fetch(
                f"""
                SELECT DISTINCT target_concept_id FROM knowledge_graph_edges
                 WHERE source_concept_id IN ({placeholders})
                   AND relation = 'maps_to_hcc'
                """,
                tuple(ind_ids),
            )
            target_ids = [r["target_concept_id"] for r in edge_rows if r.get("target_concept_id")]
            if target_ids:
                placeholders = ",".join(["%s"] * len(target_ids))
                hcc_rows = _safe_fetch(
                    f"""
                    SELECT * FROM knowledge_graph_concepts
                     WHERE id IN ({placeholders}) AND ontology = 'hcc'
                    """,
                    tuple(target_ids),
                )
                hccs = [_row_to_concept(r) for r in hcc_rows]

    return {
        "drug_name": drug_name,
        "matched_drug": None,
        "rxcui": None,
        "ndc": None,
        "atc_code": candidate_code,
        "hierarchy": hierarchy,
        "indications": indications,
        "hccs": hccs,
        "inferred": True,
        "inference_path": inference_path,
    }
