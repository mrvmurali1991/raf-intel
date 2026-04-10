"""
Stage 3: Verification & Reconciliation

Cross-checks Stage 1 (rule-based extraction) against Stage 2 (LLM analysis).
Catches silent drops, overcoding, specificity errors, and Excludes1 conflicts.
No LLM calls — deterministic verification only.

Design reference: docs/MULTI_STAGE_PIPELINE_DESIGN.md  §4.3, §5, §8
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

import simple_icd_10_cm as cm
from hccinfhir.defaults import (
    coefficients_default,
    dx_to_cc_default,
    labels_default,
)

from hccinfhir.defaults import dx_to_cc_default

from app.services.icd_validator import (
    get_description,
    get_hcc_mapping,
    normalize_code,
    validate_code_set,
    validate_icd10_code,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Warning severity constants (matches design doc §8)
# ---------------------------------------------------------------------------

SEV_CRITICAL = "critical"
SEV_HIGH = "high"
SEV_MEDIUM = "medium"
SEV_INFO = "info"

# Warning code strings
W_SILENT_DROP_PROBLEM_LIST  = "SILENT_DROP_PROBLEM_LIST"
W_SILENT_DROP_EXPLICIT      = "SILENT_DROP_EXPLICIT_CODE"
W_PROBLEM_LIST_UNACCOUNTED  = "PROBLEM_LIST_UNACCOUNTED"
W_INVALID_ICD10             = "INVALID_ICD10_CODE"
W_NON_BILLABLE              = "NON_BILLABLE_CODE"
W_EXCLUDES1_CONFLICT        = "EXCLUDES1_CONFLICT"
W_LLM_INFERRED_NO_EVIDENCE  = "LLM_INFERRED_NO_EVIDENCE"
W_OVERCODING                = "OVERCODING_LLM_INFERRED"
W_SPECIFICITY               = "SPECIFICITY_IMPROVEMENT"
W_NEGATION_LEAK             = "NEGATION_LEAK"
W_DUPLICATE_HCC             = "DUPLICATE_HCC"
W_MISSING_MEAT              = "MISSING_MEAT_FOR_HCC"
W_QUALIFIER_CONTRADICTION   = "QUALIFIER_CONTRADICTION"
W_V28_DROPPED               = "V28_DROPPED_CODE"


# ---------------------------------------------------------------------------
# Output dataclasses
# ---------------------------------------------------------------------------

@dataclass
class VerificationResult:
    """Top-level output of Stage 3. Feeds directly into Stage 4."""

    # Final verified diagnosis list. These are safe to pass to RAF calculation.
    verified_diagnoses: list[dict]

    # Codes that were dropped by the LLM but restored by Stage 3.
    restored_codes: list[dict]

    # Codes flagged as potentially unsupported (LLM-inferred with no Stage 1 basis).
    downgraded_codes: list[dict]

    # All warnings generated during this pass.
    warnings: list[dict]

    # ICD-10 Excludes1 mutual exclusion conflicts in the verified set.
    excludes1_conflicts: list[dict]

    # Codes that could be coded more specifically.
    specificity_warnings: list[dict]

    # 0.0 – 1.0 composite quality score for this encounter.
    quality_score: float

    # Full before/after comparison for the audit trail.
    reconciliation_report: dict


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _make_warning(
    severity: str,
    code: str,
    message: str,
    icd10_code: str | None = None,
    action_required: str = "",
) -> dict:
    return {
        "severity": severity,
        "code": code,
        "message": message,
        "icd10_code": icd10_code,
        "action_required": action_required,
    }


def _description(icd_code: str) -> str:
    """Return a human-readable description or the code itself if unknown."""
    return get_description(icd_code) or icd_code


def _is_problem_list_code(code: str, stage1_result: dict) -> bool:
    """Return True if *code* was found in the Active Problem List section."""
    return normalize_code(code) in {
        normalize_code(
            _get_icd_code_from_item(c) if isinstance(c, dict) else (c or "")
        )
        for c in (stage1_result.get("problem_list_codes") or [])
    }


def _get_icd_code_from_item(item: dict) -> str:
    """Extract the ICD-10 code string from a diagnosis or negated dict.

    Handles both the Stage 3 contract key ("icd10_code") and the
    skill_pipeline key ("icd10") so Stage 3 is robust to both callers.
    """
    if not isinstance(item, dict):
        return str(item) if item else ""
    return (
        item.get("icd10_code")
        or item.get("icd10")
        or item.get("code")
        or item.get("icd_code")
        or ""
    )


def _extract_stage2_code_set(stage2_result: dict) -> set[str]:
    return {
        normalize_code(_get_icd_code_from_item(d))
        for d in (stage2_result.get("diagnoses") or [])
        if _get_icd_code_from_item(d)
    }


def _extract_stage2_negated_set(stage2_result: dict) -> set[str]:
    return {
        normalize_code(_get_icd_code_from_item(n))
        for n in (stage2_result.get("negated") or [])
        if _get_icd_code_from_item(n)
    }


# ---------------------------------------------------------------------------
# Code-relationship helpers (used by silent-drop logic)
# ---------------------------------------------------------------------------

# N18 stage-specific codes that MUST always be restored alongside combination
# codes such as E11.22 / I12.9.  ICD-10-CM guidelines §I.C.18.a require both
# the combo code and the N18 stage code to be reported together.
_N18_STAGE_CODES: frozenset[str] = frozenset({
    "N1830", "N1831", "N1832", "N184", "N185",
})

# Combination-code subsumption rules keyed by the *less-specific* parent
# (normalised, no dot).  A dropped code that matches a key is considered
# subsumed when the current code set already contains any code whose normalised
# form starts with one of the listed prefixes.
_SUBSUMPTION_RULES: dict[str, list[str]] = {
    # Hypertension alone (I10) is subsumed when a hypertensive disease
    # combination code is already present (I11.x heart, I12.x CKD, I13.x both).
    "I10": ["I11", "I12", "I13"],
    # Hyperlipidaemia unspecified (E78.5) is subsumed by any specific
    # dyslipidaemia category.
    "E785": ["E780", "E781", "E782", "E783", "E784"],
    # CKD unspecified (N18 without stage suffix) is subsumed by combination
    # codes that already encode CKD.  N18 STAGE codes (N18.3x, N18.4, N18.5)
    # are handled separately and are always restored.
    "N18": ["E1122", "E1322", "I12", "I13"],
}


def _is_version_duplicate(code1: str, code2: str) -> bool:
    """Return True when two codes are the same code in different ICD-10 versions.

    K21.0 vs K21.00 is the canonical example: one version uses a 4-character
    code, the other a 5-character code for the same concept.  A prefix
    relationship in either direction is sufficient to flag them as duplicates.
    """
    n1 = normalize_code(code1)
    n2 = normalize_code(code2)
    return bool(n1 and n2 and (n1.startswith(n2) or n2.startswith(n1)))


def _is_subsumed(dropped_code: str, existing_codes: set[str]) -> tuple[bool, str]:
    """Return (True, reason) when *dropped_code* is covered by *existing_codes*.

    A code is considered subsumed under any of three conditions:

    1. An existing code is a *child* of the dropped code — i.e. its normalised
       form starts with the dropped code's normalised form.  That means the
       existing code is more specific, making the dropped parent redundant.
       The reverse (dropped starts with existing) means existing is a less-
       specific ancestor, which does NOT subsume the dropped code.

    2. A combination code in *existing_codes* encodes the dropped code's concept
       per the explicit _SUBSUMPTION_RULES table (e.g. I11.0 subsumes I10).

    3. The ICD-10-CM hierarchy via simple_icd_10_cm.get_ancestors confirms
       that the dropped code is a direct ancestor of an existing code.

    N18 stage-specific codes are unconditionally exempt from all subsumption
    because ICD-10-CM guidelines require them alongside combination codes.

    Returns
    -------
    (subsumed: bool, reason: str)
        *reason* is a human-readable explanation suitable for an INFO warning.
    """
    dropped_norm = normalize_code(dropped_code)
    if not dropped_norm:
        return False, ""

    # N18 stage codes are always kept — never subsumed.
    if dropped_norm in _N18_STAGE_CODES:
        return False, ""

    for existing in existing_codes:
        existing_norm = normalize_code(existing)
        if not existing_norm:
            continue

        # Condition 1a: existing is more specific than the dropped code.
        if existing_norm.startswith(dropped_norm) and existing_norm != dropped_norm:
            return (
                True,
                f"{dropped_code} dropped — subsumed by more-specific {existing} "
                f"({_description(existing)})",
            )

        # Condition 1b: version duplicate — dropped starts with existing
        # (e.g. K21.00 dropped when K21.0 already present).
        if dropped_norm.startswith(existing_norm) and existing_norm != dropped_norm:
            return (
                True,
                f"{dropped_code} dropped — version duplicate of {existing} "
                f"({_description(existing)})",
            )

    # Condition 2: explicit combination-code subsumption table.
    for parent_norm, child_prefixes in _SUBSUMPTION_RULES.items():
        if dropped_norm.startswith(parent_norm):
            for child_prefix in child_prefixes:
                child_norm = normalize_code(child_prefix)
                matched = next(
                    (e for e in existing_codes if normalize_code(e).startswith(child_norm)),
                    None,
                )
                if matched:
                    return (
                        True,
                        f"{dropped_code} dropped — subsumed by combination code "
                        f"{matched} ({_description(matched)})",
                    )

    # Condition 3: ICD-10-CM ancestor check via simple_icd_10_cm.
    for existing in existing_codes:
        existing_norm = normalize_code(existing)
        try:
            ancestors = cm.get_ancestors(existing_norm)
            if dropped_norm in {normalize_code(a) for a in (ancestors or [])}:
                return (
                    True,
                    f"{dropped_code} dropped — is an ancestor of {existing} "
                    f"({_description(existing)}) per ICD-10-CM hierarchy",
                )
        except Exception:
            pass

    return False, ""


# ---------------------------------------------------------------------------
# HCC enrichment via hccinfhir (used for restored codes)
# ---------------------------------------------------------------------------

def _enrich_restored_code(code: str) -> dict:
    """Look up HCC info for a restored code using hccinfhir.

    Returns a dict with keys: hcc, hcc_label, hcc_coefficient.
    hcc is formatted as "HCC{number}" (e.g. "HCC328"), or None when the code
    has no HCC mapping in the CMS-HCC Model V28 table.
    """
    code_no_dot = code.replace(".", "").upper()
    hcc_set = dx_to_cc_default.get((code_no_dot, "CMS-HCC Model V28"))
    if hcc_set:
        hcc_num = next(iter(hcc_set))
        label = labels_default.get((hcc_num, "CMS-HCC Model V28")) or f"HCC {hcc_num}"
        coeff = coefficients_default.get((f"HCC{hcc_num}", "CMS-HCC Model V28")) or 0.0
        return {
            "hcc": f"HCC{hcc_num}",
            "hcc_label": label,
            "hcc_coefficient": coeff,
        }
    return {"hcc": None, "hcc_label": None, "hcc_coefficient": 0.0}


# ---------------------------------------------------------------------------
# 1. Silent-drop detection
# ---------------------------------------------------------------------------

def check_silent_drops(
    stage1_codes: list[str],
    stage2_diagnoses: list[dict],
    stage2_negated: list[dict],
    stage1_result: dict | None = None,
) -> tuple[list[dict], list[dict]]:
    """Detect ICD-10 codes that Stage 1 found but Stage 2 silently dropped.

    A code is a *silent drop* when it appears in Stage 1 but is absent from
    both Stage 2 diagnoses AND Stage 2 negated.  The LLM neither confirmed nor
    explicitly rejected it — it just vanished.  This is the canonical heart-
    failure bug described in the design doc.

    Parameters
    ----------
    stage1_codes:
        All ICD-10 codes found by the rule-based Stage 1 extractor.
    stage2_diagnoses:
        ``diagnoses`` list from the LLM Stage 2 result.
    stage2_negated:
        ``negated`` list from the LLM Stage 2 result.
    stage1_result:
        Full Stage 1 PreExtractionResult dict, used to detect problem-list codes.

    Returns
    -------
    (dropped_entries, warnings)
        dropped_entries — list of dicts describing each dropped code and the
        action taken (restored vs. flagged).
        warnings — list of warning dicts ready for VerificationResult.warnings.
    """
    stage2_code_set = {
        normalize_code(_get_icd_code_from_item(d))
        for d in (stage2_diagnoses or [])
        if _get_icd_code_from_item(d)
    }
    stage2_negated_set = {
        normalize_code(_get_icd_code_from_item(n))
        for n in (stage2_negated or [])
        if _get_icd_code_from_item(n)
    }

    problem_list_codes: set[str] = set()
    if stage1_result:
        problem_list_codes = {
            normalize_code(
                _get_icd_code_from_item(c) if isinstance(c, dict) else (c or "")
            )
            for c in (stage1_result.get("problem_list_codes") or [])
        }

    dropped_entries: list[dict] = []
    warnings: list[dict] = []

    for raw_item in stage1_codes:
        raw_code = _get_icd_code_from_item(raw_item) if isinstance(raw_item, dict) else (raw_item or "")
        code = normalize_code(raw_code)
        if not code:
            continue

        if code in stage2_code_set:
            # Confirmed by both stages — no issue.
            continue

        if code in stage2_negated_set:
            # LLM explicitly documented a reason for exclusion — acceptable.
            dropped_entries.append({
                "icd10_code": code,
                "title": _description(code),
                "source": "stage1_explicit",
                "llm_negated": True,
                "llm_negation_reason": _find_negation_reason(code, stage2_negated or []),
                "disposition": "excluded_with_reason",
                "severity": SEV_INFO,
            })
            continue

        # Silent drop — the worst failure mode.
        is_problem = code in problem_list_codes
        source = "active_problem_list" if is_problem else "stage1_explicit"
        desc = _description(code)

        # Before restoring, check whether the dropped code is already covered by
        # a more-specific or combination code that Stage 2 kept.  Restoring a
        # redundant parent code (e.g. I10 when I11.0 is present) produces
        # overcoding and incorrect RAF scores.  Err on the side of NOT restoring
        # when the relationship is unambiguous.
        subsumed, subsumption_reason = _is_subsumed(code, stage2_code_set)
        if subsumed:
            logger.info(
                "SILENT DROP SUPPRESSED (subsumed) — %s (%s): %s",
                code, desc, subsumption_reason,
            )
            dropped_entries.append({
                "icd10_code": code,
                "title": desc,
                "source": source,
                "llm_negated": False,
                "llm_negation_reason": None,
                "disposition": "suppressed_subsumed",
                "action": "not_restored",
                "severity": SEV_INFO,
                "reason": "subsumed_by_existing_code",
                "subsumption_reason": subsumption_reason,
                "is_problem_list": is_problem,
            })
            warnings.append(_make_warning(
                severity=SEV_INFO,
                code=W_SILENT_DROP_EXPLICIT,
                message=subsumption_reason,
                icd10_code=code,
                action_required="No action required — more-specific code is already present.",
            ))
            continue

        severity = SEV_CRITICAL if is_problem else SEV_HIGH
        warning_code = W_SILENT_DROP_PROBLEM_LIST if is_problem else W_SILENT_DROP_EXPLICIT

        logger.critical(
            "SILENT DROP DETECTED — %s (%s) was found by Stage 1 in %s "
            "but absent from LLM diagnoses AND negated list. Restoring automatically.",
            code, desc, source,
        )

        hcc_info = _enrich_restored_code(code)
        entry = {
            "icd10": code,
            "icd10_code": code,
            "description": desc,
            "title": desc,
            "hcc": hcc_info["hcc"],
            "hcc_label": hcc_info["hcc_label"],
            "hcc_coefficient": hcc_info["hcc_coefficient"],
            "confidence": "flagged",
            "stage3_restored": True,
            "source": source,
            "restoration_reason": f"Found in {source} but not in LLM output",
            "llm_negated": False,
            "llm_negation_reason": None,
            "disposition": "restored",
            "action": "restored",
            "severity": severity,
            "reason": "silent_drop",
            "is_problem_list": is_problem,
        }
        dropped_entries.append(entry)

        action_msg = (
            "Clinician review required — code was in the Active Problem List "
            "but omitted by LLM without documented reason."
            if is_problem
            else "Review whether this code should be included or explicitly excluded."
        )
        warnings.append(_make_warning(
            severity=severity,
            code=warning_code,
            message=(
                f"{code} ({desc}) appears in {source} but was dropped by LLM "
                "analysis without a documented reason. Code restored with flag."
            ),
            icd10_code=code,
            action_required=action_msg,
        ))

    return dropped_entries, warnings


def _find_negation_reason(code: str, negated: list[dict]) -> str | None:
    """Return the negation reason string for *code*, or None."""
    for n in negated:
        if normalize_code(_get_icd_code_from_item(n)) == code:
            return n.get("reason") or n.get("condition_name")
    return None


# ---------------------------------------------------------------------------
# 2. Overcoding detection
# ---------------------------------------------------------------------------

def check_overcoding(
    stage2_diagnoses: list[dict],
    stage1_codes: list[str],
) -> tuple[list[dict], list[dict]]:
    """Find codes the LLM added that have no Stage 1 basis.

    These are not necessarily wrong — the LLM may have inferred a valid
    condition from medication patterns or clinical language — but they should
    be distinguished from codes explicitly stated in the note.

    Returns
    -------
    (inferred_entries, warnings)
    """
    stage1_set = {
        normalize_code(_get_icd_code_from_item(c) if isinstance(c, dict) else (c or ""))
        for c in stage1_codes if c
    }

    inferred_entries: list[dict] = []
    warnings: list[dict] = []

    for diag in (stage2_diagnoses or []):
        raw_code = _get_icd_code_from_item(diag)
        if not raw_code:
            continue
        code = normalize_code(raw_code)
        if code not in stage1_set:
            desc = _description(code)
            source = diag.get("source", "unknown")

            inferred_entries.append({
                "icd10_code": code,
                "title": desc,
                "llm_reasoning": diag.get("reasoning", ""),
                "confidence": diag.get("confidence", "unknown"),
                "source": source,
                "reason": "llm_inferred",
                "severity": SEV_INFO,
                "disposition": "accepted",
            })

            # Only produce a warning when the LLM's source gives no explicit
            # evidence traceable back to the note.
            if source in ("clinical_inference",):
                warnings.append(_make_warning(
                    severity=SEV_MEDIUM,
                    code=W_LLM_INFERRED_NO_EVIDENCE,
                    message=(
                        f"{code} ({desc}) was inferred by the LLM with source "
                        f"'{source}' but has no matching Stage 1 extraction. "
                        "Ensure clinical documentation supports this code."
                    ),
                    icd10_code=code,
                    action_required="Verify supporting documentation before finalizing.",
                ))
            else:
                # Lower-severity informational note for inferences from
                # medications, labs, or other documented clinical patterns.
                warnings.append(_make_warning(
                    severity=SEV_INFO,
                    code=W_OVERCODING,
                    message=(
                        f"{code} ({desc}) was inferred by the LLM (source: {source}) "
                        "with no verbatim ICD-10 code in Stage 1."
                    ),
                    icd10_code=code,
                    action_required="Informational — review if code is clinically supported.",
                ))

    return inferred_entries, warnings


# ---------------------------------------------------------------------------
# 3. Specificity checking
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Under-coding pattern hints (clinical knowledge base)
# ---------------------------------------------------------------------------
# These are SUGGESTIONS only. The coder/clinician must determine whether
# the documentation supports a more specific code. Stage 3 never auto-corrects
# based on these hints — it only surfaces them as informational warnings.
# ---------------------------------------------------------------------------

SPECIFICITY_HINTS: dict[str, dict] = {
    "E11.311": {
        "hint": (
            "E11.311 is 'DM with unspecified retinopathy with macular edema'. "
            "If laser treatment documented, consider E11.3511 (proliferative with "
            "macular edema) or E11.3411 (severe nonproliferative with macular edema)."
        ),
        "severity": SEV_MEDIUM,
        "potential_codes": ["E11.3511", "E11.3411", "E11.3211"],
    },
    "F01.50": {
        "hint": (
            "F01.50 is 'vascular dementia without behavioral disturbance'. "
            "If agitation, wandering, or behavioral symptoms documented, consider "
            "F01.51 (with behavioral disturbance) for higher specificity."
        ),
        "severity": SEV_INFO,
        "potential_codes": ["F01.51"],
    },
    "F33.0": {
        "hint": (
            "F33.0 is 'MDD recurrent, mild'. If prior hospitalization for depression "
            "documented, consider F33.1 (moderate) or F33.2 (severe without psychosis)."
        ),
        "severity": SEV_INFO,
        "potential_codes": ["F33.1", "F33.2"],
    },
    "I50.22": {
        "hint": (
            "I50.22 is 'chronic systolic HF'. If acute decompensation documented at "
            "this visit (worsening symptoms, BNP elevation, hospital admission), "
            "consider I50.21 (acute systolic) or I50.23 (acute on chronic systolic)."
        ),
        "severity": SEV_MEDIUM,
        "potential_codes": ["I50.23", "I50.21"],
    },
    "N18.32": {
        "hint": (
            "N18.32 is 'CKD Stage 3B'. Verify eGFR matches: Stage 3A (45-59), "
            "Stage 3B (30-44), Stage 4 (<30). If eGFR <30, use N18.4."
        ),
        "severity": SEV_MEDIUM,
        "potential_codes": ["N18.4", "N18.31"],
    },
    "J44.9": {
        "hint": (
            "J44.9 is 'COPD unspecified'. If FEV1 or GOLD stage documented, "
            "consider J44.0 (with lower respiratory infection) or J44.1 "
            "(with exacerbation) only if clinically present."
        ),
        "severity": SEV_INFO,
        "potential_codes": ["J44.0", "J44.1"],
    },
}


def check_specificity(stage2_diagnoses: list[dict]) -> list[dict]:
    """Identify diagnoses that could be coded with a more specific child code.

    Two complementary checks are performed for each code:

    1. **Hierarchy check** — Uses simple_icd_10_cm's hierarchy: if
       ``cm.get_children(code)`` returns any entries the code is a category
       (non-leaf) and should be resolved to a more specific leaf.

    2. **Under-coding hint check** — Compares the code against
       ``SPECIFICITY_HINTS``, a curated table of common under-coding patterns
       with clinical context. Matches emit a suggestion-only warning; the
       coder/clinician decides whether the documentation supports the
       alternative code.

    Returns
    -------
    List of specificity-warning dicts.
    """
    specificity_warnings: list[dict] = []

    for diag in (stage2_diagnoses or []):
        raw_code = _get_icd_code_from_item(diag)
        if not raw_code:
            continue
        code = normalize_code(raw_code)
        if not code:
            continue

        # Only check codes that are valid items in the ICD hierarchy.
        if not cm.is_valid_item(code):
            continue

        # ------------------------------------------------------------------
        # Check 1: hierarchy — is this a non-leaf (category) code?
        # ------------------------------------------------------------------
        try:
            children = cm.get_children(code) or []
        except Exception:
            children = []

        if children:
            # Gather up to 5 leaf-level examples to show in the warning message.
            leaf_examples: list[str] = []
            try:
                for child in children[:10]:
                    if cm.is_leaf(child):
                        leaf_examples.append(child)
                    else:
                        # Walk one level deeper for examples.
                        for grandchild in (cm.get_children(child) or [])[:3]:
                            if cm.is_leaf(grandchild):
                                leaf_examples.append(grandchild)
                    if len(leaf_examples) >= 5:
                        break
            except Exception:
                pass

            examples_str = (
                ", ".join(leaf_examples[:5]) if leaf_examples else "(see ICD-10-CM index)"
            )
            desc = _description(code)

            specificity_warnings.append({
                "icd10_code": code,
                "title": desc,
                "more_specific_options": leaf_examples[:5],
                "reason": "non_leaf_code",
                "severity": SEV_MEDIUM,
                "message": (
                    f"{code} ({desc}) is a category code — consider using a more "
                    f"specific child code such as: {examples_str}"
                ),
            })

        # ------------------------------------------------------------------
        # Check 2: curated under-coding patterns
        # These are SUGGESTIONS only — the coder/clinician must verify that
        # documentation supports any alternative code before changing it.
        # ------------------------------------------------------------------
        if code in SPECIFICITY_HINTS:
            hint_entry = SPECIFICITY_HINTS[code]
            desc = _description(code)

            specificity_warnings.append({
                "icd10_code": code,
                "title": desc,
                "more_specific_options": hint_entry["potential_codes"],
                "reason": "under_coding_pattern",
                "severity": hint_entry["severity"],
                # Clearly label this as a suggestion, not a correction.
                "message": (
                    f"[SUGGESTION] {hint_entry['hint']} "
                    f"Potential alternatives: {', '.join(hint_entry['potential_codes'])}. "
                    "Review documentation before changing — do not auto-correct."
                ),
            })

    return specificity_warnings


# ---------------------------------------------------------------------------
# 4. Negation-leak detection
# ---------------------------------------------------------------------------

def check_negation_leaks(
    stage2_diagnoses: list[dict],
    negation_phrases: list[str],
) -> tuple[list[dict], list[dict]]:
    """Detect diagnoses whose condition name appears in a negation phrase.

    E.g., if Stage 1 extracted the phrase "denies chest pain" and Stage 2
    returned I20.9 (Angina Pectoris, Unspecified), that is a likely negation
    leak and should be flagged.

    Parameters
    ----------
    stage2_diagnoses:
        LLM-confirmed diagnoses.
    negation_phrases:
        Free-text phrases identified as negations (e.g., "patient denies
        chest pain", "no history of heart failure").

    Returns
    -------
    (leak_entries, warnings)
    """
    leak_entries: list[dict] = []
    warnings: list[dict] = []

    if not negation_phrases:
        return leak_entries, warnings

    # Build a flat string of all negation phrases for fast substring matching.
    negation_blob = " ".join(p.lower() for p in negation_phrases)

    for diag in (stage2_diagnoses or []):
        raw_code = _get_icd_code_from_item(diag)
        if not raw_code:
            continue
        code = normalize_code(raw_code)
        desc = _description(code).lower()

        # Check whether key terms from the description appear in any negation phrase.
        # Use the first two meaningful words of the description to avoid false positives
        # from overly generic terms like "unspecified".
        desc_words = [
            w for w in desc.split()
            if len(w) > 4 and w not in {"unspecified", "other", "without", "specified"}
        ]
        matched_phrase: str | None = None
        for phrase in negation_phrases:
            phrase_lower = phrase.lower()
            if any(word in phrase_lower for word in desc_words[:3]):
                matched_phrase = phrase
                break

        if matched_phrase:
            entry = {
                "icd10_code": code,
                "title": _description(code),
                "negation_phrase": matched_phrase,
                "severity": SEV_MEDIUM,
                "reason": "possible_negation_leak",
            }
            leak_entries.append(entry)
            warnings.append(_make_warning(
                severity=SEV_MEDIUM,
                code=W_NEGATION_LEAK,
                message=(
                    f"{code} ({_description(code)}) is included as a diagnosis but its "
                    f"condition description matches a negation phrase: \"{matched_phrase}\""
                ),
                icd10_code=code,
                action_required=(
                    "Verify that this diagnosis is active, not negated or historical."
                ),
            ))

    return leak_entries, warnings


# ---------------------------------------------------------------------------
# 5. Duplicate-HCC detection
# ---------------------------------------------------------------------------

def check_duplicate_hccs(stage2_diagnoses: list[dict]) -> tuple[list[dict], list[dict]]:
    """Identify pairs of diagnoses that map to the same HCC.

    CMS hierarchy rules handle redundancy at payment time, but surfacing
    duplicates early allows coders to select the most specific / highest-
    weighted code and avoid confusing output.

    Returns
    -------
    (duplicate_entries, warnings)
    """
    # Build a map: hcc_code -> [icd10_code, ...]
    hcc_map: dict[str, list[str]] = {}

    for diag in (stage2_diagnoses or []):
        raw_code = _get_icd_code_from_item(diag)
        if not raw_code:
            continue
        code = normalize_code(raw_code)
        hcc = get_hcc_mapping(code)
        if hcc and hcc.get("hcc_code"):
            hcc_num = str(hcc["hcc_code"])
            hcc_map.setdefault(hcc_num, []).append(code)

    duplicate_entries: list[dict] = []
    warnings: list[dict] = []

    for hcc_num, codes in hcc_map.items():
        if len(codes) < 2:
            continue
        entry = {
            "codes": codes,
            "shared_hcc": hcc_num,
            "severity": SEV_INFO,
            "reason": "duplicate_hcc_mapping",
        }
        duplicate_entries.append(entry)
        warnings.append(_make_warning(
            severity=SEV_INFO,
            code=W_DUPLICATE_HCC,
            message=(
                f"Multiple codes map to HCC {hcc_num}: {', '.join(codes)}. "
                "CMS hierarchy will suppress duplicates at scoring time, but "
                "only the most specific code is needed on the claim."
            ),
            icd10_code=None,
            action_required="Consider retaining only the most specific code for each HCC.",
        ))

    return duplicate_entries, warnings


# ---------------------------------------------------------------------------
# 5b. V28 dropped-code detection
# ---------------------------------------------------------------------------

def check_v28_dropped_codes(diagnoses: list[dict]) -> list[dict]:
    """Flag codes that were HCC-mapped in V24 but dropped in V28.

    CMS-HCC Model V28 (effective 2024) removed roughly 2,200 ICD-10 codes
    from HCC mapping that were present in V24.  Common clinical examples
    include F33.0 (Major depressive disorder, single episode, mild) and a
    large number of injury/trauma codes.

    These codes are still valid, billable ICD-10-CM codes — they simply no
    longer contribute to risk-adjustment under V28.  This check is purely
    informational: it explains WHY a submitted code has no HCC assignment
    rather than flagging an error.

    Parameters
    ----------
    diagnoses:
        List of diagnosis dicts from Stage 2 (or the verified set).  Each
        entry must contain either an ``icd10`` or ``icd10_code`` key.

    Returns
    -------
    List of info-severity warning dicts, one per code that was present in
    V24 mapping but absent from V28 mapping.
    """
    warnings: list[dict] = []

    for dx in (diagnoses or []):
        raw = (dx.get("icd10") or dx.get("icd10_code") or "").replace(".", "").upper()
        if not raw:
            continue

        v28_hcc = dx_to_cc_default.get((raw, "CMS-HCC Model V28"))
        v24_hcc = dx_to_cc_default.get((raw, "CMS-HCC Model V24"))

        if v24_hcc and not v28_hcc:
            # Retrieve just the first HCC number from the set returned by the lookup.
            v24_hcc_num = next(iter(v24_hcc))
            display_code = dx.get("icd10") or dx.get("icd10_code") or raw
            warnings.append({
                "severity": SEV_INFO,
                "code": W_V28_DROPPED,
                "icd10_code": display_code,
                "message": (
                    f"{display_code} was HCC-mapped in V24 (HCC{v24_hcc_num}) "
                    "but is NOT mapped in V28. This code does not contribute to "
                    "RAF under the current model year."
                ),
                "action_required": (
                    "No action required. V28 mapping is correct. "
                    "This notice explains why no HCC or RAF weight is shown for this code."
                ),
                "v24_hcc": f"HCC{v24_hcc_num}",
                "v28_status": "not_mapped",
            })

    return warnings


# ---------------------------------------------------------------------------
# 6. Excludes1 conflicts (delegates to icd_validator.validate_code_set)
# ---------------------------------------------------------------------------

def check_excludes1(stage2_diagnoses: list[dict]) -> tuple[list[dict], list[dict]]:
    """Run Excludes1 mutual-exclusion check on the full diagnosis set.

    Delegates to ``validate_code_set`` from icd_validator.py which performs
    pairwise bidirectional Excludes1 checking.

    Returns
    -------
    (conflict_entries, warnings)
    """
    codes = [
        normalize_code(_get_icd_code_from_item(d))
        for d in (stage2_diagnoses or [])
        if _get_icd_code_from_item(d)
    ]
    raw_conflicts = validate_code_set(codes)

    conflict_entries: list[dict] = []
    warnings: list[dict] = []

    for conflict in raw_conflicts:
        entry = {
            "code1": conflict["code1"],
            "code2": conflict["code2"],
            "severity": SEV_HIGH,
            "reason": "excludes1_conflict",
            "message": conflict.get("message", ""),
        }
        conflict_entries.append(entry)
        warnings.append(_make_warning(
            severity=SEV_HIGH,
            code=W_EXCLUDES1_CONFLICT,
            message=conflict.get(
                "message",
                f"Excludes1 conflict between {conflict['code1']} and {conflict['code2']}.",
            ),
            icd10_code=conflict["code1"],
            action_required=(
                "Review whether both codes should be on this claim. "
                "An Excludes1 note means these conditions cannot be coded together. "
                "Use a combination code if one exists."
            ),
        ))

    return conflict_entries, warnings


# ---------------------------------------------------------------------------
# 7. Computed confidence score (replaces LLM self-reported confidence)
# ---------------------------------------------------------------------------

def compute_confidence(
    diagnosis: dict,
    stage1_codes: set,
    problem_list_codes: set,
    assessment_codes: set,
    warnings_for_code: list,
) -> float:
    """Compute a numeric confidence score (0.0 – 0.99) for a single diagnosis.

    This replaces the LLM's self-reported "high"/"medium"/"low" string with a
    deterministic score derived from objective signals.

    Scoring breakdown
    -----------------
    Base                        0.50
    Written explicitly in note  +0.15  (Stage 1 found it)
    On active problem list      +0.10
    In Assessment section       +0.10
    No Stage 3 warnings         +0.10
    MEAT evidence               +0.025 per component (max +0.10)

    Maximum                     0.99

    Parameters
    ----------
    diagnosis:
        The diagnosis dict (from Stage 2 or restored by Stage 3).
    stage1_codes:
        Set of normalised ICD-10 codes found by Stage 1 pre-extraction.
    problem_list_codes:
        Set of normalised codes present on the active problem list.
    assessment_codes:
        Set of normalised codes found in the Assessment & Plan section.
    warnings_for_code:
        List of all Stage 3 warning dicts relevant to this code.
    """
    base = 0.50

    code = _get_icd_code_from_item(diagnosis)
    code_norm = normalize_code(code) if code else ""

    # Stage 1 found (written in the note)
    if code_norm in stage1_codes:
        base += 0.15

    # On active problem list
    if code_norm in problem_list_codes:
        base += 0.10

    # In assessment section
    if code_norm in assessment_codes:
        base += 0.10

    # No Stage 3 warnings for this code
    code_warnings = [
        w for w in warnings_for_code
        if w.get("code") == code or code in str(w.get("message", ""))
    ]
    if not code_warnings:
        base += 0.10

    # MEAT evidence count
    meat = diagnosis.get("meat") or diagnosis.get("meat_evidence") or {}
    if isinstance(meat, dict):
        meat_count = sum(
            1 for k in ["M", "E", "A", "T", "monitor", "evaluate", "assess", "treat"]
            if meat.get(k)
        )
        base += min(meat_count * 0.025, 0.10)

    return min(round(base, 2), 0.99)


def confidence_label(score: float) -> str:
    """Convert a numeric confidence score to a human-readable label."""
    if score >= 0.90:
        return "high"
    if score >= 0.75:
        return "good"
    if score >= 0.60:
        return "medium"
    if score >= 0.40:
        return "low"
    return "very_low"


# ---------------------------------------------------------------------------
# 8. Quality score
# ---------------------------------------------------------------------------

def compute_quality_score(
    warnings: list[dict],
    restored_count: int,
    total_diagnoses: int,
    restored_codes: list[dict] | None = None,
) -> float:
    """Compute a 0.0 – 1.0 quality score for this encounter.

    Deduction schedule
    ------------------
    CRITICAL warning                      -0.15 each
    HIGH / MEDIUM warning                 -0.05 each
    INFO warning                          -0.02 each
    Restored code with HCC mapping        -0.10 each  (revenue at risk)

    Restored codes that carry an HCC mapping receive an extra -0.10 penalty
    on top of any warnings already generated, because a silently dropped
    HCC-mapped code represents a direct RAF / revenue risk.

    The score can never go below 0.0.

    Parameters
    ----------
    warnings:
        All warnings produced by Stage 3.
    restored_count:
        Number of codes that were silently dropped and had to be restored.
    total_diagnoses:
        Total count of diagnoses in the final verified set.
    restored_codes:
        The restored-code dicts produced by check_silent_drops.  Used to
        apply the extra HCC-at-risk penalty.
    """
    score = 1.0

    for w in warnings:
        sev = w.get("severity", "")
        if sev == SEV_CRITICAL:
            score -= 0.15
        elif sev == SEV_HIGH:
            score -= 0.05
        elif sev == SEV_MEDIUM:
            score -= 0.05
        elif sev == SEV_INFO:
            score -= 0.02

    # Extra penalty for restored codes that have an HCC mapping.
    # These represent revenue that was at risk due to the LLM silent drop.
    for rc in (restored_codes or []):
        if rc.get("hcc") is not None:
            score -= 0.10

    return max(round(score, 4), 0.0)


# ---------------------------------------------------------------------------
# 8b. Qualifier-contradiction detection (J44.1 overcoding guard)
# ---------------------------------------------------------------------------

# Each rule maps a coded qualifier (exacerbation, acute, etc.) to phrases in
# the note that directly contradict that qualifier.  Matches are performed
# case-insensitively against the FULL note text so language anywhere in the
# note — not just the Assessment — can invalidate the qualifier.
QUALIFIER_RULES: list[dict] = [
    {
        "code_pattern": "J44.1",  # COPD with (acute) exacerbation
        "qualifier": "exacerbation",
        "contradiction_phrases": [
            "denies acute exacerbation",
            "no acute exacerbation",
            "without exacerbation",
            "no current exacerbation",
            "denies exacerbation",
            "no exacerbation",
        ],
        "downgrade_to": "J44.9",  # COPD, unspecified / without exacerbation
        "severity": SEV_CRITICAL,
    },
    {
        "code_pattern": "I50.21",  # Acute systolic (congestive) heart failure
        "qualifier": "acute",
        "contradiction_phrases": [
            "chronic heart failure",
            "stable heart failure",
            "no acute decompensation",
        ],
        "downgrade_to": "I50.22",  # Chronic systolic (congestive) heart failure
        "severity": SEV_HIGH,
    },
    {
        "code_pattern": "N17",  # Acute kidney failure
        "qualifier": "acute",
        "contradiction_phrases": [
            "chronic kidney disease",
            "ckd stage",
            "no acute kidney",
        ],
        "downgrade_to": None,  # Remove entirely — do not substitute
        "severity": SEV_CRITICAL,
    },
    {
        "code_pattern": "J96.0",  # Acute respiratory failure
        "qualifier": "acute",
        "contradiction_phrases": [
            "chronic respiratory failure",
            "on home oxygen",
            "baseline oxygen",
        ],
        "downgrade_to": "J96.1",  # Chronic respiratory failure
        "severity": SEV_HIGH,
    },
]


def check_qualifier_contradictions(
    stage2_diagnoses: list[dict],
    note_text: str,
) -> tuple[list[dict], list[dict], list[dict]]:
    """Detect coded qualifiers (exacerbation, acute, etc.) contradicted by note text.

    For each diagnosis code that matches a QUALIFIER_RULES pattern, the FULL
    note text is searched for contradiction phrases.  When a contradiction is
    found the code is either:

    - downgraded to ``downgrade_to`` (e.g. J44.1 -> J44.9), or
    - removed entirely when ``downgrade_to`` is None (e.g. N17 when CKD is
      documented but no acute kidney injury language is present).

    Parameters
    ----------
    stage2_diagnoses:
        LLM-confirmed diagnosis dicts from Stage 2.
    note_text:
        The complete, untruncated clinical note as a single string.

    Returns
    -------
    (downgraded_entries, removed_entries, warnings)
        downgraded_entries — list of dicts describing each downgrade action.
        removed_entries    — list of dicts describing each removal action.
        warnings           — list of warning dicts for VerificationResult.warnings.
    """
    note_lower = (note_text or "").lower()

    downgraded_entries: list[dict] = []
    removed_entries: list[dict] = []
    warnings: list[dict] = []

    for diag in (stage2_diagnoses or []):
        raw_code = _get_icd_code_from_item(diag)
        if not raw_code:
            continue
        code = normalize_code(raw_code)
        if not code:
            continue

        for rule in QUALIFIER_RULES:
            pattern = normalize_code(rule["code_pattern"])
            # Match exact code OR prefix (e.g. "N17" matches "N17.0", "N17.9").
            if code != pattern and not code.startswith(pattern):
                continue

            # Check the full note for any contradiction phrase.
            matched_phrase: str | None = None
            for phrase in rule["contradiction_phrases"]:
                if phrase.lower() in note_lower:
                    matched_phrase = phrase
                    break

            if matched_phrase is None:
                # No contradiction found — qualifier is supported.
                continue

            original_desc = _description(code)
            downgrade_to: str | None = rule["downgrade_to"]
            severity = rule["severity"]

            logger.warning(
                "QUALIFIER CONTRADICTION — %s (%s) coded with qualifier '%s' but "
                "note contains contradicting phrase: \"%s\". %s.",
                code,
                original_desc,
                rule["qualifier"],
                matched_phrase,
                f"Downgrading to {downgrade_to}" if downgrade_to else "Removing code",
            )

            if downgrade_to:
                downgrade_desc = _description(downgrade_to)
                downgraded_entries.append({
                    "original_code": code,
                    "original_description": original_desc,
                    "downgraded_to": downgrade_to,
                    "downgraded_description": downgrade_desc,
                    "qualifier": rule["qualifier"],
                    "contradiction_phrase": matched_phrase,
                    "severity": severity,
                    "reason": "qualifier_contradicted_by_note",
                })
                warnings.append(_make_warning(
                    severity=severity,
                    code=W_QUALIFIER_CONTRADICTION,
                    message=(
                        f"OVERCODING — {code} ({original_desc}) codes the qualifier "
                        f'"{rule["qualifier"]}" but note states: "{matched_phrase}". '
                        f"Downgraded to {downgrade_to} ({downgrade_desc}). "
                        "This is a RADV audit red flag."
                    ),
                    icd10_code=code,
                    action_required=(
                        f"Replace {code} with {downgrade_to} ({downgrade_desc}). "
                        "Qualifier must be supported by clinical documentation."
                    ),
                ))
            else:
                removed_entries.append({
                    "removed_code": code,
                    "removed_description": original_desc,
                    "qualifier": rule["qualifier"],
                    "contradiction_phrase": matched_phrase,
                    "severity": severity,
                    "reason": "qualifier_contradicted_by_note",
                })
                warnings.append(_make_warning(
                    severity=severity,
                    code=W_QUALIFIER_CONTRADICTION,
                    message=(
                        f"OVERCODING — {code} ({original_desc}) codes the qualifier "
                        f'"{rule["qualifier"]}" but note states: "{matched_phrase}". '
                        "Code removed — no appropriate downgrade code exists. "
                        "This is a RADV audit red flag."
                    ),
                    icd10_code=code,
                    action_required=(
                        f"Remove {code} from the claim. "
                        "Qualifier must be supported by clinical documentation."
                    ),
                ))

            # A code can only match one rule — stop checking further rules.
            break

    return downgraded_entries, removed_entries, warnings


# ---------------------------------------------------------------------------
# MEAT field builder
# ---------------------------------------------------------------------------

def _build_meat_fields(meat: dict | None) -> dict:
    """Return meat, meat_completeness, and meat_status for a diagnosis entry.

    The LLM returns MEAT with short keys M/E/A/T.  A component is considered
    present when its value is a non-empty string.

    Returns a dict with three keys:
        meat            — the raw {M, E, A, T} dict, or {M:"", E:"", A:"", T:""}
        meat_completeness — int 0–4 counting non-empty components
        meat_status     — "complete" (4/4), "partial" (1-3), "missing" (0)
    """
    empty_meat: dict = {"M": "", "E": "", "A": "", "T": ""}

    if not meat or not isinstance(meat, dict):
        return {
            "meat": empty_meat,
            "meat_completeness": 0,
            "meat_status": "missing",
        }

    # Normalise to M/E/A/T keys regardless of what the LLM returned.
    normalised: dict = {
        "M": str(meat.get("M") or meat.get("monitor") or meat.get("monitoring") or "").strip(),
        "E": str(meat.get("E") or meat.get("evaluate") or meat.get("evaluation") or "").strip(),
        "A": str(meat.get("A") or meat.get("assess") or meat.get("assessment") or "").strip(),
        "T": str(meat.get("T") or meat.get("treat") or meat.get("treatment") or "").strip(),
    }

    completeness = sum(1 for v in normalised.values() if v)
    if completeness == 4:
        status = "complete"
    elif completeness > 0:
        status = "partial"
    else:
        status = "missing"

    return {
        "meat": normalised,
        "meat_completeness": completeness,
        "meat_status": status,
    }


# ---------------------------------------------------------------------------
# 9. Main orchestrator: run_stage3
# ---------------------------------------------------------------------------

def run_stage3(
    stage1_result: dict,
    stage2_result: dict,
    note_text: str = "",
) -> VerificationResult:
    """Orchestrate all Stage 3 verification checks and return a VerificationResult.

    This function is the single entry point for Stage 3. It is purely
    deterministic — no LLM calls, no network I/O beyond what icd_validator
    already does against the in-memory ICD-10-CM index and the RAF database
    for HCC lookups. Target runtime: < 500ms.

    Parameters
    ----------
    stage1_result:
        Dict representation of PreExtractionResult from Stage 1.
        Expected keys: explicit_icd_codes, problem_list_codes, sections, etc.
    stage2_result:
        Dict representation of LLMAnalysisResult from Stage 2.
        Expected keys: diagnoses, negated, suspects, meat_evidence.
    note_text:
        Full clinical note text.  Used by check_qualifier_contradictions to
        scan the entire note for qualifier-negating phrases (e.g. "denies
        acute exacerbation").  Defaults to empty string for backwards
        compatibility with callers that have not yet been updated.

    Returns
    -------
    VerificationResult with verified_diagnoses, warnings, and the full
    reconciliation_report for the audit trail.
    """
    t_start = time.perf_counter()

    stage1_explicit: list[str] = stage1_result.get("explicit_icd_codes") or []
    stage1_problem_list: list[str] = stage1_result.get("problem_list_codes") or []
    stage2_diagnoses: list[dict] = stage2_result.get("diagnoses") or []
    stage2_negated: list[dict] = stage2_result.get("negated") or []
    stage2_suspects: list[dict] = stage2_result.get("suspects") or []

    # Build a normalised-code-keyed MEAT index from the per-diagnosis "meat"
    # field that the LLM embeds in each diagnoses[] entry.  This is the primary
    # source of MEAT evidence.  The legacy top-level "meat_evidence" dict
    # (keyed by ICD code) is kept as a fallback for callers that pre-populate
    # it directly.
    meat_evidence_legacy: dict = stage2_result.get("meat_evidence") or {}
    per_diag_meat: dict[str, dict] = {}
    for _diag in stage2_diagnoses:
        _meat = _diag.get("meat")
        if _meat and isinstance(_meat, dict):
            _raw = _get_icd_code_from_item(_diag)
            _norm = normalize_code(_raw)
            if _norm:
                per_diag_meat[_norm] = _meat
            if _raw and _raw != _norm:
                per_diag_meat[_raw] = _meat

    # Normalised sets for set arithmetic.
    # Stage 1 codes may be dicts or strings — extract the code string
    def _get_code(item):
        if isinstance(item, dict):
            return item.get("icd_code") or item.get("code") or item.get("icd10") or item.get("diagnosis") or ""
        return str(item) if item else ""

    stage1_set = {normalize_code(_get_code(c)) for c in stage1_explicit if _get_code(c)}
    stage2_set = {normalize_code(d.get("icd10_code") or d.get("icd10") or d.get("code") or "") for d in stage2_diagnoses if d.get("icd10_code") or d.get("icd10")}
    stage2_negated_set = {normalize_code(n.get("icd10_code") or n.get("icd10") or "") for n in stage2_negated if n.get("icd10_code") or n.get("icd10")}
    problem_list_set = {normalize_code(_get_code(c)) for c in stage1_problem_list if _get_code(c)}

    # Determine which Stage 1 codes appear in the Assessment section.
    assessment_text: str = (stage1_result.get("sections") or {}).get("assessment_and_plan", "").lower()

    all_warnings: list[dict] = []

    # ------------------------------------------------------------------
    # Check 1 — Silent drops (heart failure bug detector)
    # ------------------------------------------------------------------
    dropped_entries, drop_warnings = check_silent_drops(
        stage1_codes=stage1_explicit,
        stage2_diagnoses=stage2_diagnoses,
        stage2_negated=stage2_negated,
        stage1_result=stage1_result,
    )
    all_warnings.extend(drop_warnings)

    # Codes to restore: all silent drops that were not explicitly negated.
    restored_code_set: set[str] = {
        e["icd10_code"] for e in dropped_entries
        if e.get("disposition") == "restored"
    }
    restored_codes: list[dict] = [e for e in dropped_entries if e.get("disposition") == "restored"]

    # ------------------------------------------------------------------
    # Check 1b — Qualifier contradictions (J44.1 / overcoding guard)
    # Must run before final assembly so downgraded/removed codes never
    # reach the verified_diagnoses list with their incorrect qualifier.
    # ------------------------------------------------------------------
    qualifier_downgraded, qualifier_removed, qualifier_warnings = check_qualifier_contradictions(
        stage2_diagnoses=stage2_diagnoses,
        note_text=note_text,
    )
    all_warnings.extend(qualifier_warnings)

    # Build lookup sets for downstream assembly.
    # Keys: original code that was acted on; value: replacement code (or None).
    qualifier_downgrade_map: dict[str, str] = {
        e["original_code"]: e["downgraded_to"]
        for e in qualifier_downgraded
    }
    qualifier_removed_set: set[str] = {e["removed_code"] for e in qualifier_removed}

    # ------------------------------------------------------------------
    # Check 2 — Overcoding / LLM inference without Stage 1 basis
    # ------------------------------------------------------------------
    inferred_entries, overcode_warnings = check_overcoding(
        stage2_diagnoses=stage2_diagnoses,
        stage1_codes=stage1_explicit,
    )
    all_warnings.extend(overcode_warnings)
    downgraded_codes = [e for e in inferred_entries if e.get("severity") != SEV_INFO]
    # Also surface qualifier downgrades and removals in this list so callers
    # can render them in the audit UI without digging into raw warnings.
    downgraded_codes.extend(qualifier_downgraded)
    downgraded_codes.extend(qualifier_removed)

    # ------------------------------------------------------------------
    # Check 3 — Specificity
    # ------------------------------------------------------------------
    specificity_warnings = check_specificity(stage2_diagnoses)
    for sw in specificity_warnings:
        all_warnings.append(_make_warning(
            severity=SEV_MEDIUM,
            code=W_SPECIFICITY,
            message=sw["message"],
            icd10_code=sw["icd10_code"],
            action_required="Use a more specific ICD-10-CM code if clinical documentation supports it.",
        ))

    # ------------------------------------------------------------------
    # Check 4 — Negation leaks
    # ------------------------------------------------------------------
    # Collect negation phrases from Stage 1 sections or any metadata the
    # LLM returned about negated conditions.
    negation_phrases: list[str] = []
    for neg in stage2_negated:
        if neg.get("reason"):
            negation_phrases.append(str(neg["reason"]))
        if neg.get("condition_name"):
            negation_phrases.append(str(neg["condition_name"]))

    _, negation_leak_warnings = check_negation_leaks(
        stage2_diagnoses=stage2_diagnoses,
        negation_phrases=negation_phrases,
    )
    all_warnings.extend(negation_leak_warnings)

    # ------------------------------------------------------------------
    # Check 5 — Duplicate HCCs
    # ------------------------------------------------------------------
    _, dup_hcc_warnings = check_duplicate_hccs(stage2_diagnoses)
    all_warnings.extend(dup_hcc_warnings)

    # ------------------------------------------------------------------
    # Check 5b — V28 dropped-code informational notices
    # Runs against the full Stage 2 diagnosis list so any code the LLM
    # confirmed (regardless of Stage 1 basis) gets an explanation if it
    # lost its HCC in the V24→V28 transition.
    # ------------------------------------------------------------------
    v28_dropped_warnings = check_v28_dropped_codes(stage2_diagnoses)
    all_warnings.extend(v28_dropped_warnings)

    # ------------------------------------------------------------------
    # Check 6 — Excludes1 conflicts
    # ------------------------------------------------------------------
    excludes1_conflict_entries, excl_warnings = check_excludes1(stage2_diagnoses)
    all_warnings.extend(excl_warnings)

    # ------------------------------------------------------------------
    # Check 7 — ICD-10 validity of Stage 2 codes
    # ------------------------------------------------------------------
    invalid_code_warnings: list[dict] = []
    rejected_codes: set[str] = set()
    for diag in stage2_diagnoses:
        raw_code = _get_icd_code_from_item(diag)
        if not raw_code:
            continue
        code = normalize_code(raw_code)
        if not validate_icd10_code(code):
            # Check whether the code even exists in the hierarchy (non-leaf) vs
            # completely unknown.
            exists = cm.is_valid_item(code) if code else False
            if exists:
                w = _make_warning(
                    severity=SEV_HIGH,
                    code=W_NON_BILLABLE,
                    message=(
                        f"{code} exists in ICD-10-CM but is not a billable (leaf) code. "
                        "A more specific child code is required for claim submission."
                    ),
                    icd10_code=code,
                    action_required="Replace with a valid billable child code.",
                )
            else:
                w = _make_warning(
                    severity=SEV_HIGH,
                    code=W_INVALID_ICD10,
                    message=f"{code} is not a valid ICD-10-CM code and will be excluded.",
                    icd10_code=code,
                    action_required="Remove or correct this code.",
                )
                rejected_codes.add(code)
            invalid_code_warnings.append(w)
            all_warnings.append(w)

    # ------------------------------------------------------------------
    # Check 8 — Problem list coverage
    # ------------------------------------------------------------------
    final_code_set_before_restore = stage2_set - rejected_codes
    final_code_set = final_code_set_before_restore | restored_code_set

    unaccounted_problem_list: list[str] = []
    problem_list_accounted: dict[str, str] = {}

    for pl_code in problem_list_set:
        if pl_code in final_code_set:
            problem_list_accounted[pl_code] = "included"
        elif pl_code in stage2_negated_set:
            problem_list_accounted[pl_code] = "negated"
        else:
            # This should have been caught by check_silent_drops — but may
            # still reach here if the code was invalid and rejected.
            problem_list_accounted[pl_code] = "unaccounted"
            unaccounted_problem_list.append(pl_code)
            desc = _description(pl_code)
            all_warnings.append(_make_warning(
                severity=SEV_CRITICAL,
                code=W_PROBLEM_LIST_UNACCOUNTED,
                message=(
                    f"{pl_code} ({desc}) is on the Active Problem List but has "
                    "no disposition in the final output (not included, not negated)."
                ),
                icd10_code=pl_code,
                action_required="Clinician must explicitly include or exclude this code.",
            ))

    # ------------------------------------------------------------------
    # Assemble verified diagnoses
    # ------------------------------------------------------------------
    # Start from Stage 2 diagnoses (minus invalid/rejected codes).
    verified_by_code: dict[str, dict] = {}

    for diag in stage2_diagnoses:
        raw_code = _get_icd_code_from_item(diag)
        if not raw_code:
            continue
        code = normalize_code(raw_code)
        if code in rejected_codes:
            continue

        # Qualifier contradiction — remove entirely.
        if code in qualifier_removed_set:
            continue

        # Qualifier contradiction — swap to downgraded code before assembly.
        if code in qualifier_downgrade_map:
            replacement = normalize_code(qualifier_downgrade_map[code])
            # Re-use the original diag dict but with the corrected code so
            # that MEAT evidence, source, and reasoning are preserved.
            diag = dict(diag)
            diag["icd10_code"] = replacement
            diag["icd10"] = replacement
            diag["code"] = replacement
            diag["qualifier_downgraded_from"] = code
            code = replacement

        in_stage1 = code in stage1_set
        in_problem = code in problem_list_set
        in_assess = code in assessment_text  # simple substring on normalised code

        # MEAT evidence for this code.
        # Primary source: per-diagnosis "meat" field from the LLM (M/E/A/T keys).
        # Fallback: legacy top-level "meat_evidence" dict keyed by ICD code.
        raw_meat = (
            per_diag_meat.get(code)
            or per_diag_meat.get(raw_code)
            or meat_evidence_legacy.get(code)
            or meat_evidence_legacy.get(raw_code)
        )
        meat_fields = _build_meat_fields(raw_meat)

        # meat_components boolean dict consumed by compute_confidence.
        meat_components: dict | None = None
        if meat_fields["meat_completeness"] > 0:
            meat_components = {k: bool(v) for k, v in meat_fields["meat"].items()}

        # Determine whether this code has Stage 3 warnings.
        code_warnings = [w for w in all_warnings if w.get("icd10_code") == code]
        stage3_clean = not any(
            w["severity"] in (SEV_CRITICAL, SEV_HIGH, SEV_MEDIUM) for w in code_warnings
        )

        # Assessment codes set: normalised codes whose string appears in the
        # assessment-and-plan section text (used by compute_confidence).
        _assessment_codes_set = {
            c for c in (stage1_set | problem_list_set) if c and c in assessment_text
        }

        confidence_score = compute_confidence(
            diagnosis=diag,
            stage1_codes=stage1_set,
            problem_list_codes=problem_list_set,
            assessment_codes=_assessment_codes_set,
            warnings_for_code=[w for w in all_warnings if w.get("icd10_code") == code],
        )

        hcc = get_hcc_mapping(code)

        # hcc_code is the bare number string (e.g. "226"); hcc is the prefixed
        # form (e.g. "HCC226") read by the frontend display layer (dx.hcc).
        _hcc_code_bare = str(hcc["hcc_code"]) if hcc and hcc.get("hcc_code") is not None else None
        _hcc_prefixed  = f"HCC{_hcc_code_bare}" if _hcc_code_bare else None
        _confidence_score = confidence_score
        _confidence_label = confidence_label(_confidence_score)

        verified_by_code[code] = {
            # ICD-10 code — both field names populated for all consumers.
            "icd10":      code,
            "icd10_code": code,
            "description": _description(code),
            # HCC fields — both forms populated for frontend and Stage 3 consumers.
            "hcc":             _hcc_prefixed,   # frontend reads dx.hcc  ("HCC226")
            "hcc_code":        _hcc_code_bare,  # Stage 3 internal use   ("226")
            "hcc_label":       hcc["hcc_label"] if hcc else None,
            "hcc_coefficient": hcc.get("raf_weight", 0.0) if hcc else 0.0,
            "raf_weight":      hcc["raf_weight"] if hcc else 0.0,
            "is_hcc_relevant":  hcc is not None,
            "is_risk_adjusting": hcc is not None,
            # Confidence — numeric float and human-readable label both present.
            "confidence":       _confidence_score,  # numeric float
            "confidence_label": _confidence_label,  # "high" / "medium" / "low"
            "source": diag.get("source", "stage2_llm"),
            "reasoning": diag.get("reasoning", ""),
            # MEAT evidence — always populated, never null.
            "meat":             meat_fields["meat"],
            "meat_completeness": meat_fields["meat_completeness"],
            "meat_status":      meat_fields["meat_status"],
            "stage1_found": in_stage1,
            "stage2_found": True,
            "stage3_restored": False,
            "icd10_valid": True,
            "icd10_billable": validate_icd10_code(code),
            "excludes1_conflicts": [
                c["code2"] for c in excludes1_conflict_entries if c["code1"] == code
            ] + [
                c["code1"] for c in excludes1_conflict_entries if c["code2"] == code
            ],
        }

    # Add restored (silently dropped) codes.
    for dropped in restored_codes:
        code = dropped["icd10_code"]
        if code in verified_by_code:
            # Already present — just mark it as having been flagged.
            verified_by_code[code]["stage3_restored"] = False
            continue

        in_problem = code in problem_list_set
        # Use hccinfhir for HCC lookup on restored codes so the full
        # HCC identifier, label, and coefficient are available for RAF
        # calculation and display — get_hcc_mapping returns a different
        # schema and may return None for codes that hccinfhir knows.
        hcc_info = _enrich_restored_code(code)
        # Preserve icd_validator result for raf_weight / is_hcc_relevant.
        hcc_legacy = get_hcc_mapping(code)

        # Restored codes are always in stage1; no MEAT evidence available.
        _restored_assessment_set = {
            c for c in (stage1_set | problem_list_set) if c and c in assessment_text
        }
        _restored_diag = {"icd10_code": code, "icd10": code, "code": code}
        confidence_score = compute_confidence(
            diagnosis=_restored_diag,
            stage1_codes=stage1_set,
            problem_list_codes=problem_list_set,
            assessment_codes=_restored_assessment_set,
            warnings_for_code=[w for w in all_warnings if w.get("icd10_code") == code],
        )

        # hcc_info["hcc"] is already the prefixed form ("HCC226") from
        # _enrich_restored_code.  Derive the bare number by stripping the prefix
        # so both field names are consistent with the Stage 2 branch above.
        _restored_hcc_prefixed = hcc_info["hcc"]  # e.g. "HCC226" or None
        _restored_hcc_bare = (
            _restored_hcc_prefixed[3:] if _restored_hcc_prefixed and _restored_hcc_prefixed.startswith("HCC")
            else _restored_hcc_prefixed
        )  # e.g. "226" or None
        _restored_confidence_label = confidence_label(confidence_score)

        verified_by_code[code] = {
            # ICD-10 code — both field names populated for all consumers.
            "icd10":      code,
            "icd10_code": code,
            "description": dropped.get("description") or _description(code),
            # HCC fields — both forms populated for frontend and Stage 3 consumers.
            "hcc":             _restored_hcc_prefixed,  # frontend reads dx.hcc  ("HCC226")
            "hcc_code":        _restored_hcc_bare,      # Stage 3 internal use   ("226")
            "hcc_label":       hcc_info["hcc_label"],
            "hcc_coefficient": hcc_info["hcc_coefficient"],
            "raf_weight":      hcc_legacy["raf_weight"] if hcc_legacy else hcc_info["hcc_coefficient"],
            "is_hcc_relevant":  _restored_hcc_prefixed is not None,
            "is_risk_adjusting": _restored_hcc_prefixed is not None,
            # Confidence — numeric float and human-readable label both present.
            "confidence":       confidence_score,            # numeric float
            "confidence_label": _restored_confidence_label,  # "flagged" for restored codes
            "source": dropped.get("source", "stage1_restored"),
            "reasoning": "Restored by Stage 3 — silent drop detected.",
            # Restored codes have no MEAT evidence — always missing.
            "meat":             {"M": "", "E": "", "A": "", "T": ""},
            "meat_completeness": 0,
            "meat_status":      "missing",
            "stage1_found": True,
            "stage2_found": False,
            "stage3_restored": True,
            "icd10_valid": validate_icd10_code(code),
            "icd10_billable": validate_icd10_code(code),
            "excludes1_conflicts": [],
        }

    verified_diagnoses = list(verified_by_code.values())

    # ------------------------------------------------------------------
    # Check 9 — Missing MEAT for HCC-carrying diagnoses (RADV audit risk)
    # ------------------------------------------------------------------
    for vdx in verified_diagnoses:
        if vdx.get("meat_status") != "missing":
            continue  # MEAT present (complete or partial) — no warning needed
        if not vdx.get("is_hcc_relevant"):
            continue  # Non-HCC diagnosis — MEAT is recommended but not critical
        icd_code = vdx.get("icd10_code", "")
        all_warnings.append(_make_warning(
            severity=SEV_HIGH,
            code=W_MISSING_MEAT,
            message=(
                f"{icd_code} ({_description(icd_code)}) is HCC-relevant but has no "
                "documented MEAT evidence (Monitor/Evaluate/Assess/Treat). "
                "MEAT documentation is required for RADV audit defensibility."
            ),
            icd10_code=icd_code,
            action_required=(
                "Add explicit MEAT documentation for this diagnosis in the clinical note "
                "or addendum before claim submission."
            ),
        ))
        logger.warning(
            "[Stage3] MISSING MEAT for HCC diagnosis %s — RADV audit risk",
            icd_code,
        )

    # ------------------------------------------------------------------
    # Quality score
    # ------------------------------------------------------------------
    quality_score = compute_quality_score(
        warnings=all_warnings,
        restored_count=len(restored_codes),
        total_diagnoses=len(verified_diagnoses),
        restored_codes=restored_codes,
    )

    # ------------------------------------------------------------------
    # Reconciliation report (audit trail)
    # ------------------------------------------------------------------
    confirmed_by_both = sorted(stage1_set & stage2_set - rejected_codes)
    dropped_by_llm_codes = sorted(stage1_set - stage2_set - stage2_negated_set)
    inferred_by_llm_codes = sorted(stage2_set - stage1_set - rejected_codes)

    # ICD-10 validation results summary.
    all_union_codes = list(stage1_set | stage2_set)
    icd10_validation: dict[str, dict] = {}
    for c in all_union_codes:
        icd10_validation[c] = {
            "valid": validate_icd10_code(c),
            "billable": validate_icd10_code(c),
            "description": _description(c),
        }

    # Excludes1 summary: code -> [conflicting codes].
    excludes1_summary: dict[str, list[str]] = {}
    for conflict in excludes1_conflict_entries:
        excludes1_summary.setdefault(conflict["code1"], []).append(conflict["code2"])
        excludes1_summary.setdefault(conflict["code2"], []).append(conflict["code1"])

    t_end = time.perf_counter()
    elapsed_ms = round((t_end - t_start) * 1000, 2)

    reconciliation_report = {
        # Before/after code lists.
        "stage1_codes": sorted(stage1_set),
        "stage2_codes": sorted(stage2_set),
        "confirmed_by_both": confirmed_by_both,
        "dropped_by_llm": [
            {
                "icd10_code": c,
                "description": _description(c),
                "source": "active_problem_list" if c in problem_list_set else "stage1_explicit",
                "llm_negated": c in stage2_negated_set,
                "llm_negation_reason": _find_negation_reason(c, stage2_negated),
                "disposition": "restored" if c in restored_code_set else "flagged_for_review",
            }
            for c in dropped_by_llm_codes
        ],
        "inferred_by_llm": [
            {
                "icd10_code": c,
                "description": _description(c),
                "llm_reasoning": next(
                    (d.get("reasoning", "") for d in stage2_diagnoses
                     if normalize_code(d.get("icd10_code", "")) == c),
                    "",
                ),
                "confidence": next(
                    (d.get("confidence", "unknown") for d in stage2_diagnoses
                     if normalize_code(d.get("icd10_code", "")) == c),
                    "unknown",
                ),
                "disposition": "rejected_invalid_code" if c in rejected_codes else "accepted",
            }
            for c in inferred_by_llm_codes
        ],
        # Problem list audit.
        "problem_list_accounted": problem_list_accounted,
        "problem_list_unaccounted": unaccounted_problem_list,
        # ICD-10 and Excludes1.
        "icd10_validation_results": icd10_validation,
        "excludes1_check_results": excludes1_summary,
        # Counts.
        "summary": {
            "stage1_total": len(stage1_set),
            "stage2_total": len(stage2_set),
            "confirmed_both": len(confirmed_by_both),
            "silent_drops_detected": len(dropped_by_llm_codes),
            "restored_count": len(restored_codes),
            "inferred_by_llm_count": len(inferred_by_llm_codes),
            "invalid_codes_rejected": len(rejected_codes),
            "excludes1_conflict_count": len(excludes1_conflict_entries),
            "v28_dropped_code_count": len(v28_dropped_warnings),
            "total_warnings": len(all_warnings),
            "critical_warnings": sum(1 for w in all_warnings if w["severity"] == SEV_CRITICAL),
            "high_warnings": sum(1 for w in all_warnings if w["severity"] == SEV_HIGH),
            "medium_warnings": sum(1 for w in all_warnings if w["severity"] == SEV_MEDIUM),
            "info_warnings": sum(1 for w in all_warnings if w["severity"] == SEV_INFO),
            "quality_score": quality_score,
            "stage3_elapsed_ms": elapsed_ms,
        },
    }

    logger.info(
        "Stage 3 complete in %.1fms — %d diagnoses verified, %d restored, "
        "%d critical warnings, quality=%.2f",
        elapsed_ms,
        len(verified_diagnoses),
        len(restored_codes),
        reconciliation_report["summary"]["critical_warnings"],
        quality_score,
    )

    return VerificationResult(
        verified_diagnoses=verified_diagnoses,
        restored_codes=restored_codes,
        downgraded_codes=downgraded_codes,
        warnings=all_warnings,
        excludes1_conflicts=excludes1_conflict_entries,
        specificity_warnings=specificity_warnings,
        quality_score=quality_score,
        reconciliation_report=reconciliation_report,
    )
