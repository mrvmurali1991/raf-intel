"""
Human Review Queue
Routes diagnoses to human coders based on confidence, warnings, and Stage 3 flags.

Design principles
-----------------
- Auto-accept  : High confidence, no critical/high warnings, confirmed by both
                 Stage 1 (rule-based extraction) AND Stage 2 (LLM). Safe to
                 submit without coder review.
- Needs review : Medium confidence, medium warnings, or code was restored by
                 Stage 3. Coder should verify before submission.
- Reject       : Low confidence, critical warnings, or negation leak detected.
                 Must NOT be submitted without significant coder intervention.

The function is intentionally side-effect free — it reads the output of the
verified pipeline and returns a plain dict that can be serialised directly into
the API response alongside ``verification`` and ``diagnoses``.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Severity / warning code constants (mirrors stage3_verification.py)
# ---------------------------------------------------------------------------

_CRITICAL_WARNING_CODES = frozenset({
    "EXCLUDES1_CONFLICT",
    "NEGATION_LEAK",
    "OVERCODING_LLM_INFERRED",
    "QUALIFIER_CONTRADICTION",
    "INVALID_ICD10_CODE",
})

_HIGH_WARNING_CODES = frozenset({
    "SILENT_DROP_PROBLEM_LIST",
    "SILENT_DROP_EXPLICIT_CODE",
    "PROBLEM_LIST_UNACCOUNTED",
    "NON_BILLABLE_CODE",
    "MISSING_MEAT_FOR_HCC",
})

_MEDIUM_WARNING_CODES = frozenset({
    "SPECIFICITY_IMPROVEMENT",
    "LLM_INFERRED_NO_EVIDENCE",
    "DUPLICATE_HCC",
    "V28_DROPPED_CODE",
})

# Confidence thresholds
_THRESHOLD_AUTO_ACCEPT  = 0.85   # >= this → eligible for auto-accept
_THRESHOLD_REJECT       = 0.60   # <  this → reject

# Estimated minutes to review a single dx that needs coder attention
_REVIEW_MINUTES_PER_DX = 1.5


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_icd(dx: dict) -> str:
    return dx.get("icd10") or dx.get("icd10_code") or dx.get("code") or ""


def _get_confidence(dx: dict) -> float:
    """Return numeric confidence, converting string labels when necessary."""
    conf = dx.get("confidence")
    if isinstance(conf, (int, float)):
        return float(conf)
    if isinstance(conf, str):
        label_map = {"high": 0.87, "medium": 0.70, "low": 0.45, "flagged": 0.50}
        return label_map.get(conf.lower(), 0.50)
    return 0.0


def _warnings_for_code(icd_code: str, warnings: list[dict]) -> list[dict]:
    """Return all verification warnings that reference *icd_code*."""
    if not icd_code:
        return []
    code_norm = icd_code.replace(".", "").upper()
    matched: list[dict] = []
    for w in warnings:
        w_code = (w.get("icd10_code") or "").replace(".", "").upper()
        if w_code == code_norm:
            matched.append(w)
    return matched


def _highest_severity(warning_list: list[dict]) -> str | None:
    """
    Return the highest severity string from a list of warnings,
    or None when the list is empty.

    Order: critical > high > medium > info
    """
    order = {"critical": 0, "high": 1, "medium": 2, "info": 3}
    best: str | None = None
    best_rank = 999
    for w in warning_list:
        sev = w.get("severity", "info")
        rank = order.get(sev, 3)
        if rank < best_rank:
            best_rank = rank
            best = sev
    return best


def _has_warning_of_code(warning_list: list[dict], code_set: frozenset[str]) -> bool:
    return any(w.get("code") in code_set for w in warning_list)


# ---------------------------------------------------------------------------
# Core routing logic
# ---------------------------------------------------------------------------

def _classify_dx(
    dx: dict,
    per_code_warnings: list[dict],
    global_critical_codes: frozenset[str],
    is_stage3_restored: bool,
) -> str:
    """
    Return one of "auto_accept", "needs_review", or "reject" for a single dx.

    Parameters
    ----------
    dx:
        A single diagnosis dict from the verified pipeline output.
    per_code_warnings:
        Warnings whose ``icd10_code`` field matches this dx's ICD-10 code.
    global_critical_codes:
        Set of warning codes (e.g. "NEGATION_LEAK") that apply globally to
        the encounter (not code-specific). If any are present, every dx that
        maps to them is pushed to reject.
    is_stage3_restored:
        True when Stage 3 restored this code after the LLM silently dropped it.
        Restored codes always go to needs_review, not auto_accept.
    """
    confidence = _get_confidence(dx)
    icd = _get_icd(dx)

    # --- Reject conditions ---
    # 1. Confidence below floor
    if confidence < _THRESHOLD_REJECT:
        return "reject"

    # 2. Critical-severity per-code warning
    if _has_warning_of_code(per_code_warnings, _CRITICAL_WARNING_CODES):
        return "reject"

    # 3. Global negation-leak or overcoding warning covers this dx
    if icd and icd.replace(".", "").upper() in global_critical_codes:
        return "reject"

    # --- Needs-review conditions ---
    # 4. Medium confidence band
    if confidence < _THRESHOLD_AUTO_ACCEPT:
        return "needs_review"

    # 5. High-severity (but not critical) per-code warning
    if _has_warning_of_code(per_code_warnings, _HIGH_WARNING_CODES):
        return "needs_review"

    # 6. Medium-severity per-code warning (specificity, inferred, etc.)
    if _has_warning_of_code(per_code_warnings, _MEDIUM_WARNING_CODES):
        return "needs_review"

    # 7. Stage 3 restored this code — the LLM missed it, coder should confirm
    if is_stage3_restored:
        return "needs_review"

    # --- Auto-accept ---
    return "auto_accept"


def _build_dx_entry(dx: dict, routing_decision: str, per_code_warnings: list[dict]) -> dict:
    """Build the enriched dict placed into each routing bucket."""
    return {
        "icd10":              _get_icd(dx),
        "description":        dx.get("description") or "",
        "hcc":                dx.get("hcc") or dx.get("hcc_code") or None,
        "hcc_weight":         dx.get("hcc_weight"),
        "confidence":         round(_get_confidence(dx), 4),
        "confidence_label":   dx.get("confidence_label") or dx.get("confidence_text") or "",
        "stage1_found":       bool(dx.get("stage1_found")),
        "stage2_found":       bool(dx.get("stage2_found", True)),   # default True (LLM produced it)
        "stage3_restored":    bool(dx.get("stage3_restored")),
        "meat_score":         dx.get("meat_score", 0),
        "routing":            routing_decision,
        "review_flags":       [w.get("code") for w in per_code_warnings if w.get("code")],
        "review_notes":       [w.get("message") for w in per_code_warnings if w.get("message")],
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def route_for_review(verified_result: dict) -> dict:
    """
    Analyse the verified pipeline result and create a human review queue.

    Accepts the full top-level response dict from ``pipeline_orchestrator
    .run_verified_pipeline()`` (or ``skill_pipeline.run_pipeline()`` as a
    graceful fallback).

    Returns
    -------
    {
        "auto_accept": [...],     # High confidence, no warnings -> safe to submit
        "needs_review": [...],    # Medium confidence or warnings -> coder review needed
        "reject": [...],          # Low confidence or critical warnings -> do not submit
        "review_summary": {
            "total":                   int,
            "auto_accept_count":       int,
            "needs_review_count":      int,
            "reject_count":            int,
            "estimated_review_time_minutes": float,
            "encounter_quality_score": float | None,
        }
    }
    """
    diagnoses: list[dict] = verified_result.get("diagnoses") or []
    verification: dict = verified_result.get("verification") or {}

    all_warnings: list[dict]   = verification.get("warnings") or []
    restored_codes: list[dict] = verification.get("restored_codes") or []
    excludes1_conflicts: list[dict] = verification.get("excludes1_conflicts") or []
    quality_score: float | None = verification.get("quality_score")

    # Build a set of ICD-10 codes (normalised, no dot) that were restored by Stage 3
    # so _classify_dx can cheaply check membership.
    restored_icd_set: frozenset[str] = frozenset(
        (rc.get("code") or rc.get("icd10") or rc.get("icd10_code") or "").replace(".", "").upper()
        for rc in restored_codes
        if rc.get("code") or rc.get("icd10") or rc.get("icd10_code")
    )

    # Build a set of ICD-10 codes involved in Excludes1 conflicts — treated as
    # globally critical so any dx touching them is routed to reject.
    excludes1_icd_set: frozenset[str] = frozenset(
        (ec.get("icd10_code") or ec.get("code") or "").replace(".", "").upper()
        for ec in excludes1_conflicts
        if ec.get("icd10_code") or ec.get("code")
    )

    # Also collect any global NEGATION_LEAK / OVERCODING warning icd10 codes
    global_critical_icd_set: frozenset[str] = frozenset(
        (w.get("icd10_code") or "").replace(".", "").upper()
        for w in all_warnings
        if w.get("code") in _CRITICAL_WARNING_CODES and w.get("icd10_code")
    ) | excludes1_icd_set

    # Route each diagnosis
    auto_accept: list[dict]  = []
    needs_review: list[dict] = []
    reject: list[dict]       = []

    for dx in diagnoses:
        icd      = _get_icd(dx)
        icd_norm = icd.replace(".", "").upper()

        per_code_warnings    = _warnings_for_code(icd, all_warnings)
        is_stage3_restored   = bool(
            dx.get("stage3_restored")
            or (icd_norm and icd_norm in restored_icd_set)
        )

        decision = _classify_dx(
            dx,
            per_code_warnings,
            global_critical_icd_set,
            is_stage3_restored,
        )

        entry = _build_dx_entry(dx, decision, per_code_warnings)

        if decision == "auto_accept":
            auto_accept.append(entry)
        elif decision == "needs_review":
            needs_review.append(entry)
        else:
            reject.append(entry)

    # Sort each bucket: by HCC presence first (HCC codes surface first), then
    # confidence descending so the most actionable items appear at the top.
    def _sort_key(e: dict):
        has_hcc = 0 if e.get("hcc") else 1   # HCC codes first
        return (has_hcc, -e.get("confidence", 0))

    auto_accept.sort(key=_sort_key)
    needs_review.sort(key=_sort_key)
    reject.sort(key=_sort_key)

    total = len(auto_accept) + len(needs_review) + len(reject)
    review_items = len(needs_review) + len(reject)
    estimated_minutes = round(review_items * _REVIEW_MINUTES_PER_DX, 1)

    logger.info(
        "[ReviewQueue] Routed %d diagnoses: %d auto-accept, %d needs-review, %d reject "
        "(est. review %.1f min)",
        total,
        len(auto_accept),
        len(needs_review),
        len(reject),
        estimated_minutes,
    )

    return {
        "auto_accept":  auto_accept,
        "needs_review": needs_review,
        "reject":       reject,
        "review_summary": {
            "total":                        total,
            "auto_accept_count":            len(auto_accept),
            "needs_review_count":           len(needs_review),
            "reject_count":                 len(reject),
            "estimated_review_time_minutes": estimated_minutes,
            "encounter_quality_score":      quality_score,
        },
    }
