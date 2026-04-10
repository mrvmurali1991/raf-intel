"""
ICD-10-CM validation and lookup utilities.

Wraps the simple_icd_10_cm library and exposes a clean public API used
throughout the RAF Intelligence platform.  All functions are synchronous;
the ICD-10-CM index is loaded once at import time by simple_icd_10_cm and
cached in memory for the lifetime of the process.

Public surface
--------------
validate_icd10_code(code)              -> bool
get_code_info(code)                    -> dict[str, Any]
search_codes(query, max_results)       -> list[dict[str, Any]]
get_hcc_mapping(icd10_code)            -> dict[str, Any] | None  (hccinfhir V28)
get_children_with_descriptions(code)   -> list[dict[str, Any]]
get_leaf_descendants(code)             -> list[str]
normalize_code(code)                   -> str
enrich_codes(codes)                    -> list[dict[str, Any]]
check_excludes1(code1, code2)          -> bool
validate_code_set(codes)               -> list[dict[str, Any]]

Legacy aliases (kept for backwards-compat with existing router code)
--------------------------------------------------------------------
validate_code(code)       -> bool          (alias for validate_icd10_code)
code_exists(code)         -> bool
get_description(code)     -> str
get_code_description(code) -> dict[str, Any]
get_children(code)        -> list[str]
get_ancestors(code)       -> list[str]
get_parent(code)          -> str
"""
from __future__ import annotations

import logging
from typing import Any

import simple_icd_10_cm as cm

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal normalisation helper
# ---------------------------------------------------------------------------

def _norm(code: str) -> str:
    """Upper-case and strip; keep whatever dot/no-dot form was passed in."""
    return code.strip().upper() if code else ""


def normalize_code(code: str) -> str:
    """Return *code* in standard dot-notation if it is a valid ICD-10-CM item.

    Attempts three forms in order:
      1. The code as given (already may have a dot).
      2. With a dot inserted after character 3.
      3. Without any dot.

    Returns the first form that is valid, or the uppercased original if none
    of the above succeeds.
    """
    if not code:
        return code
    upper = _norm(code)
    if cm.is_valid_item(upper):
        return upper
    # Try inserting dot after char 3
    if len(upper) > 3 and "." not in upper:
        candidate = upper[:3] + "." + upper[3:]
        if cm.is_valid_item(candidate):
            return candidate
    # Try removing dot
    no_dot = upper.replace(".", "")
    if cm.is_valid_item(no_dot):
        return no_dot
    return upper


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_icd10_code(code: str) -> bool:
    """Return True only when *code* is a valid, assignable (leaf) ICD-10-CM code.

    Non-leaf codes (categories, blocks, chapters) are not valid for claim
    billing and return False.  Dot notation is optional.
    """
    if not code or not isinstance(code, str):
        return False
    norm = normalize_code(code)
    try:
        return cm.is_valid_item(norm) and cm.is_leaf(norm)
    except Exception:
        return False


# Legacy alias
validate_code = validate_icd10_code


def code_exists(code: str) -> bool:
    """Return True if *code* exists anywhere in the ICD-10-CM hierarchy
    (including non-leaf category and block codes).
    """
    if not code:
        return False
    try:
        return cm.is_valid_item(normalize_code(code))
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Descriptions
# ---------------------------------------------------------------------------

def get_description(code: str) -> str:
    """Return the human-readable description for *code*, or ``""`` if unknown."""
    if not code:
        return ""
    try:
        return cm.get_description(normalize_code(code)) or ""
    except Exception:
        return ""


def get_code_description(code: str) -> dict[str, Any]:
    """Return a dict with ``{code, description, is_leaf, ancestors, parent,
    children, has_children}`` for *code*.  Returns ``{}`` if code is unknown.
    (Legacy alias for ``get_code_info``, kept for backwards compatibility.)
    """
    if not code:
        return {}
    norm = normalize_code(code)
    if not cm.is_valid_item(norm):
        return {}
    try:
        children = cm.get_children(norm) or []
        return {
            "code": norm,
            "description": cm.get_description(norm) or "",
            "is_leaf": cm.is_leaf(norm),
            "ancestors": cm.get_ancestors(norm) or [],
            "parent": cm.get_parent(norm) or None,
            "children": children,
            "has_children": bool(children),
        }
    except Exception as exc:
        logger.debug("get_code_description failed for %s: %s", code, exc)
        return {}


# ---------------------------------------------------------------------------
# Hierarchy navigation
# ---------------------------------------------------------------------------

def get_children(code: str) -> list[str]:
    """Return direct child codes of *code* in the ICD-10-CM hierarchy."""
    if not code:
        return []
    try:
        return cm.get_children(normalize_code(code)) or []
    except Exception:
        return []


def get_ancestors(code: str) -> list[str]:
    """Return all ancestor codes from immediate parent up to the root chapter."""
    if not code:
        return []
    try:
        return cm.get_ancestors(normalize_code(code)) or []
    except Exception:
        return []


def get_parent(code: str) -> str:
    """Return the immediate parent code, or ``""`` if *code* has no parent."""
    if not code:
        return ""
    try:
        return cm.get_parent(normalize_code(code)) or ""
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Rich metadata
# ---------------------------------------------------------------------------

def get_code_info(code: str) -> dict[str, Any]:
    """Return comprehensive metadata for an ICD-10-CM code.

    Returned dict keys:
        code, description, is_valid, is_leaf, parent, children, ancestors,
        use_additional_code, code_first, code_also, excludes1, excludes2,
        includes, inclusion_terms

    If *code* is not in the ICD-10-CM index, ``is_valid`` is False and most
    other fields are empty / None.
    """
    norm = normalize_code(code) if code else ""
    is_valid = bool(norm) and cm.is_valid_item(norm)

    info: dict[str, Any] = {
        "code": norm or (code or "").strip().upper(),
        "description": None,
        "is_valid": is_valid,
        "is_leaf": False,
        "parent": None,
        "children": [],
        "ancestors": [],
        "use_additional_code": None,
        "code_first": None,
        "code_also": None,
        "excludes1": None,
        "excludes2": None,
        "includes": None,
        "inclusion_terms": None,
    }

    if not is_valid:
        return info

    try:
        info["description"] = cm.get_description(norm) or None
        info["is_leaf"] = cm.is_leaf(norm)
        info["parent"] = cm.get_parent(norm) or None
        info["children"] = cm.get_children(norm) or []
        info["ancestors"] = cm.get_ancestors(norm) or []
        info["use_additional_code"] = cm.get_use_additional_code(norm) or None
        info["code_first"] = cm.get_code_first(norm) or None
        info["code_also"] = cm.get_code_also(norm) or None
        info["excludes1"] = cm.get_excludes1(norm) or None
        info["excludes2"] = cm.get_excludes2(norm) or None
        info["includes"] = cm.get_includes(norm) or None
        info["inclusion_terms"] = cm.get_inclusion_term(norm) or None
    except Exception as exc:
        logger.warning("get_code_info error for %s: %s", norm, exc)

    return info


def get_children_with_descriptions(code: str) -> list[dict[str, Any]]:
    """Return immediate children of *code*, each with description and leaf flag.

    Useful when walking the ICD tree to find the correct specific leaf code.
    """
    norm = normalize_code(code) if code else ""
    if not norm or not cm.is_valid_item(norm):
        return []
    out: list[dict[str, Any]] = []
    for child in cm.get_children(norm) or []:
        try:
            desc = cm.get_description(child) or ""
        except Exception:
            desc = ""
        out.append(
            {
                "code": child,
                "description": desc,
                "is_leaf": cm.is_leaf(child),
            }
        )
    return out


def get_leaf_descendants(code: str) -> list[str]:
    """Return all assignable (leaf) descendant codes of *code*.

    If *code* is itself a leaf, it is returned in a single-element list.
    """
    norm = normalize_code(code) if code else ""
    if not norm or not cm.is_valid_item(norm):
        return []
    if cm.is_leaf(norm):
        return [norm]
    return [c for c in (cm.get_descendants(norm) or []) if cm.is_leaf(c)]


# ---------------------------------------------------------------------------
# Text search
# ---------------------------------------------------------------------------

def search_codes(query: str, max_results: int = 20) -> list[dict[str, Any]]:
    """Search ICD-10-CM codes by description substring (case-insensitive).

    Parameters
    ----------
    query:
        Free-text search string (e.g. ``"diabetic kidney"``).
    max_results:
        Cap on number of results returned (default 20).

    Returns
    -------
    List of ``{code, description, is_leaf}`` dicts ordered by first match.
    """
    if not query or not isinstance(query, str):
        return []
    query_lower = query.strip().lower()
    results: list[dict[str, Any]] = []
    try:
        for code in cm.get_all_codes(with_dots=True):
            try:
                desc = cm.get_description(code) or ""
            except Exception:
                continue
            if query_lower in desc.lower():
                results.append(
                    {
                        "code": code,
                        "description": desc,
                        "is_leaf": cm.is_leaf(code),
                    }
                )
                if len(results) >= max_results:
                    break
    except Exception as exc:
        logger.warning("ICD-10 search error: %s", exc)
    return results


# ---------------------------------------------------------------------------
# HCC mapping — hccinfhir is the single source of truth
# ---------------------------------------------------------------------------

# Loaded once at import time; failures are surfaced at call time via the
# try/except in get_hcc_mapping so the rest of the module stays functional
# even if the optional dependency is absent.
try:
    from hccinfhir.defaults import (
        coefficients_default,
        dx_to_cc_default,
        is_chronic_default,
        labels_default,
    )
    _HCCINFHIR_AVAILABLE = True
except Exception as _hccinfhir_import_err:  # pragma: no cover
    logger.warning("hccinfhir not available — HCC mapping will always return None: %s", _hccinfhir_import_err)
    _HCCINFHIR_AVAILABLE = False


def get_hcc_mapping(icd10_code: str) -> dict[str, Any] | None:
    """Look up the CMS-HCC V28 mapping for an ICD-10-CM code.

    Uses hccinfhir as the single source of truth.  The ``hcc_icd10_crosswalk``
    database table is intentionally NOT queried here; it may exist for
    reference but should not be used for HCC lookups.

    Returns
    -------
    dict with keys ``icd10_code``, ``hcc_code``, ``hcc_label``,
    ``raf_weight``, ``is_chronic``, ``model_version``, ``source``
    — or ``None`` if the code is not mapped in hccinfhir.
    """
    if not icd10_code or not _HCCINFHIR_AVAILABLE:
        return None

    # Try multiple representations of the same code so callers are not forced
    # to normalise before calling this function.
    upper = icd10_code.strip().upper()
    no_dot = upper.replace(".", "")
    code_variants: list[str] = list(dict.fromkeys([
        no_dot,                      # E.g. "E1140"  — most common key in hccinfhir
        upper,                       # E.g. "E11.40" — dot form
        no_dot.rstrip("0") or no_dot, # E.g. "E114"   — trailing-zero stripped
    ]))

    for code in code_variants:
        hcc_set = dx_to_cc_default.get((code, "CMS-HCC Model V28"))
        if not hcc_set:
            continue

        hcc_code = next(iter(hcc_set))  # typically a single HCC per DX code
        label = labels_default.get((hcc_code, "CMS-HCC Model V28")) or f"HCC {hcc_code}"
        coeff_key = f"HCC{hcc_code}"
        raf_weight: float = coefficients_default.get((coeff_key, "CMS-HCC Model V28")) or 0.0
        is_chronic: bool | None = is_chronic_default.get((hcc_code, "CMS-HCC Model V28"))

        return {
            "icd10_code": icd10_code,
            "hcc_code": hcc_code,
            "hcc_label": label,
            "raf_weight": raf_weight,
            "is_chronic": is_chronic,
            "model_version": "V28",
            "source": "hccinfhir",
        }

    return None


# ---------------------------------------------------------------------------
# Excludes1 checking
# ---------------------------------------------------------------------------

def check_excludes1(code1: str, code2: str) -> bool:
    """Check if two ICD-10-CM codes have an Excludes1 relationship.

    An Excludes1 note means the two conditions cannot be coded together on the
    same claim.  Both directions are checked: code1 excluding code2 AND code2
    excluding code1.  The check is prefix-based so that, for example, an
    Excludes1 entry of "E11" will match any E11.x code passed as *code2*.

    Returns True when a conflict is detected, False otherwise (including when
    either code is not found in the ICD-10-CM index).
    """
    norm1 = normalize_code(code1) if code1 else ""
    norm2 = normalize_code(code2) if code2 else ""
    if not norm1 or not norm2:
        return False

    try:
        # Check code1's Excludes1 list for code2
        excludes1_of_1 = cm.get_excludes1(norm1) or []
        if any(norm2.startswith(exc.strip()) for exc in excludes1_of_1):
            return True
    except Exception:
        pass

    try:
        # Also check code2's Excludes1 list for code1 (relationship is symmetric
        # in practice but ICD-10-CM sometimes only annotates one direction)
        excludes1_of_2 = cm.get_excludes1(norm2) or []
        if any(norm1.startswith(exc.strip()) for exc in excludes1_of_2):
            return True
    except Exception:
        pass

    return False


def validate_code_set(codes: list[str]) -> list[dict[str, Any]]:
    """Check all pairs in *codes* for Excludes1 conflicts.

    This is an advisory check — Excludes1 conflicts are returned as warnings,
    not errors.  Some valid clinical scenarios may trigger apparent conflicts
    (e.g. a code that is Excludes1 at a category level but not at a more
    specific subcategory).  Callers should surface these as informational
    warnings and never use them to block claim submission.

    Parameters
    ----------
    codes:
        List of ICD-10-CM codes to cross-check (duplicates are ignored).

    Returns
    -------
    List of warning dicts, each with keys:
        ``code1``, ``code2``, ``message``, ``severity`` ("warning")

    An empty list means no Excludes1 conflicts were detected.
    """
    if not codes or len(codes) < 2:
        return []

    # Normalise and deduplicate while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for c in codes:
        norm = normalize_code(c) if c else ""
        if norm and norm not in seen:
            seen.add(norm)
            unique.append(norm)

    warnings: list[dict[str, Any]] = []
    for i in range(len(unique)):
        for j in range(i + 1, len(unique)):
            c1, c2 = unique[i], unique[j]
            if check_excludes1(c1, c2):
                desc1 = get_description(c1) or c1
                desc2 = get_description(c2) or c2
                warnings.append({
                    "code1": c1,
                    "code2": c2,
                    "message": (
                        f"Excludes1 conflict: {c1} ({desc1}) and {c2} ({desc2}) "
                        "cannot be coded together per ICD-10-CM Excludes1 rules. "
                        "Verify clinical documentation or use an appropriate "
                        "combination code if one exists."
                    ),
                    "severity": "warning",
                })
    return warnings


# ---------------------------------------------------------------------------
# Batch enrichment
# ---------------------------------------------------------------------------

def enrich_codes(codes: list[str]) -> list[dict[str, Any]]:
    """Return code-info + HCC mapping for each code in *codes*.

    Convenience wrapper consumed by gemini_service to annotate its output.
    """
    enriched: list[dict[str, Any]] = []
    for code in codes:
        info = get_code_info(code)
        info["hcc_mapping"] = get_hcc_mapping(code)
        enriched.append(info)
    return enriched
