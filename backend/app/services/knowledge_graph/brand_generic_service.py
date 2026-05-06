"""
Brand-name to generic-ingredient mapping service.

Resolves US trade names (e.g. "Ozempic", "Eliquis", "Lipitor") to their
generic ingredient (semaglutide, apixaban, atorvastatin) and, when seeded,
the corresponding ATC code.  This is the bridge that lets every downstream
KG layer (ATC -> indication -> HCC) work on a clinician-typed brand name
without having to seed every brand into ``kg_rxnorm_to_atc``.

Source: ``kg_brand_to_generic`` table (curated in
``backend/scripts/seed_brand_to_generic.py`` from the FDA Orange Book and
DailyMed labels).

Public API
----------
- :func:`brand_to_generic`   — exact + fuzzy match brand -> generic dict.
- :func:`generic_to_brands`  — reverse lookup, returns all brand variants.
- :func:`bulk_resolve`       — resolve a mixed list of brand/generic names.
"""
from __future__ import annotations

import difflib
import logging
from typing import Any

from app.db import raf_cursor

logger = logging.getLogger(__name__)


# Same cutoff convention as atc_service: tight enough to catch common typos
# (``ozempick`` -> ``ozempic``) but loose enough to not collapse different
# drugs that share long suffixes.
_FUZZY_CUTOFF = 0.85
_FUZZY_TOP_N = 5


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _normalize(value: str | None) -> str:
    return (value or "").strip().lower()


def _row_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "brand_name": row.get("brand_name"),
        "generic_name": row.get("generic_name"),
        "rxcui_brand": row.get("rxcui_brand"),
        "rxcui_generic": row.get("rxcui_generic"),
        "atc_code": row.get("atc_code"),
        "manufacturer": row.get("manufacturer"),
        "notes": row.get("notes"),
        "is_active": bool(row.get("is_active", 1)),
    }


def _safe_fetch(sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    """Run a SELECT and return rows; return [] on any DB error."""
    try:
        with raf_cursor() as cur:
            cur.execute(sql, params)
            return list(cur.fetchall() or [])
    except Exception as exc:                     # pragma: no cover - DB-down path
        logger.warning(
            "brand_generic_service: query failed (%s): %s",
            sql.split()[0:4],
            exc,
        )
        return []


# ---------------------------------------------------------------------------
# 1. brand_to_generic
# ---------------------------------------------------------------------------

def brand_to_generic(brand: str) -> dict[str, Any] | None:
    """Resolve a brand name to its generic ingredient.

    Resolution order:
      1. Exact case-insensitive match on ``brand_name``.
      2. Strip a trailing dose form (``Ozempic 0.5 mg``) and retry exact.
      3. ``difflib`` fuzzy match against active brand names.

    Returns ``None`` when nothing matches.  Includes the raw row plus a
    ``match_type`` and ``confidence`` (1.0 for exact, <1.0 for fuzzy).
    """
    needle = _normalize(brand)
    if not needle:
        return None

    rows = _safe_fetch(
        """
        SELECT * FROM kg_brand_to_generic
         WHERE LOWER(brand_name) = %s AND is_active = 1
         LIMIT 1
        """,
        (needle,),
    )
    if rows:
        return {**_row_to_dict(rows[0]), "match_type": "exact", "confidence": 1.0}

    # Strip trailing dose / form tokens — ``ozempic 0.5 mg`` -> ``ozempic``.
    head_token = needle.split()[0] if " " in needle else needle
    if head_token != needle:
        rows = _safe_fetch(
            """
            SELECT * FROM kg_brand_to_generic
             WHERE LOWER(brand_name) = %s AND is_active = 1
             LIMIT 1
            """,
            (head_token,),
        )
        if rows:
            return {
                **_row_to_dict(rows[0]),
                "match_type": "exact_head_token",
                "confidence": 0.95,
            }

    # Fuzzy fallback over distinct active brand names.
    candidates = _safe_fetch(
        "SELECT DISTINCT brand_name FROM kg_brand_to_generic WHERE is_active = 1",
    )
    names = [r["brand_name"] for r in candidates if r.get("brand_name")]
    name_lower_to_orig = {n.lower(): n for n in names}
    matches = difflib.get_close_matches(
        needle, list(name_lower_to_orig), n=_FUZZY_TOP_N, cutoff=_FUZZY_CUTOFF,
    )
    if not matches:
        return None

    # Take the highest-similarity match (difflib returns sorted best-first).
    best_lower = matches[0]
    best_orig = name_lower_to_orig[best_lower]
    rows = _safe_fetch(
        """
        SELECT * FROM kg_brand_to_generic
         WHERE brand_name = %s AND is_active = 1
         LIMIT 1
        """,
        (best_orig,),
    )
    if not rows:
        return None
    # Compute approximate confidence from SequenceMatcher ratio.
    ratio = difflib.SequenceMatcher(None, needle, best_lower).ratio()
    return {
        **_row_to_dict(rows[0]),
        "match_type": "fuzzy",
        "confidence": round(ratio, 3),
    }


# ---------------------------------------------------------------------------
# 2. generic_to_brands
# ---------------------------------------------------------------------------

def generic_to_brands(generic: str) -> list[dict[str, Any]]:
    """Return every brand variant for *generic*.

    Useful for chart-chase / patient education flows that want to show "the
    generic of Lipitor is atorvastatin; other brands include Atorvaliq".
    """
    needle = _normalize(generic)
    if not needle:
        return []
    rows = _safe_fetch(
        """
        SELECT * FROM kg_brand_to_generic
         WHERE LOWER(generic_name) = %s AND is_active = 1
         ORDER BY brand_name
        """,
        (needle,),
    )
    return [_row_to_dict(r) for r in rows]


# ---------------------------------------------------------------------------
# 3. bulk_resolve
# ---------------------------------------------------------------------------

def bulk_resolve(drug_names: list[str]) -> list[dict[str, Any]]:
    """Resolve a mixed list of drug names — brand, generic, or unknown.

    For each input, tries:
      1. ``brand_to_generic`` — if it hits, classify ``input_kind="brand"``.
      2. Otherwise check whether the name appears in ``generic_name`` —
         classify ``input_kind="generic"`` and emit any associated brands.
      3. Else mark ``input_kind="unknown"``.

    The shape is suitable for med-list ingestion: callers can pull
    ``resolved_generic`` and feed it to ``atc_service.resolve_drug_to_atc``.
    """
    out: list[dict[str, Any]] = []
    if not drug_names:
        return out

    for raw in drug_names:
        original = (raw or "").strip()
        if not original:
            out.append({
                "input": raw,
                "input_kind": "unknown",
                "resolved_generic": None,
                "atc_code": None,
                "brands": [],
                "match_type": "empty",
                "confidence": 0.0,
            })
            continue

        # 1. Try brand-first (covers misspelled brands too via fuzzy).
        hit = brand_to_generic(original)
        if hit:
            brands = generic_to_brands(hit["generic_name"])
            out.append({
                "input": original,
                "input_kind": "brand",
                "resolved_generic": hit.get("generic_name"),
                "rxcui_generic": hit.get("rxcui_generic"),
                "atc_code": hit.get("atc_code"),
                "brands": [b["brand_name"] for b in brands],
                "match_type": hit.get("match_type"),
                "confidence": hit.get("confidence", 1.0),
            })
            continue

        # 2. Try generic-first.
        brands = generic_to_brands(original)
        if brands:
            out.append({
                "input": original,
                "input_kind": "generic",
                "resolved_generic": brands[0].get("generic_name"),
                "rxcui_generic": brands[0].get("rxcui_generic"),
                "atc_code": brands[0].get("atc_code"),
                "brands": [b["brand_name"] for b in brands],
                "match_type": "exact_generic",
                "confidence": 1.0,
            })
            continue

        # 3. Unknown.
        out.append({
            "input": original,
            "input_kind": "unknown",
            "resolved_generic": None,
            "atc_code": None,
            "brands": [],
            "match_type": "no_match",
            "confidence": 0.0,
        })

    return out
