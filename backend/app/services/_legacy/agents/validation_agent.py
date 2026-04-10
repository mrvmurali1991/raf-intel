"""
Validation Agent — Cross-checks and validates the final results.
Deduplicates diagnoses, validates ICD-10 codes, resolves conflicts.
"""
import logging
from typing import Any

logger = logging.getLogger(__name__)


def validate(diagnoses: list[dict], negated_entities: list[dict]) -> dict:
    """
    Validate and clean the final diagnosis list.

    1. Remove negated conditions
    2. Deduplicate by ICD-10 code (keep highest confidence)
    3. Remove diagnoses without ICD-10
    4. Sort by HCC weight descending (most impactful first)

    Returns dict with 'diagnoses' and 'negated_conditions'.
    """
    # Filter out negated
    negated_icds = {n.get("icd10", "").strip().lower() for n in negated_entities if n.get("icd10")}
    negated_names = {n.get("name", "").strip().lower() for n in negated_entities}

    active = []
    filtered_negated = []

    for dx in diagnoses:
        icd = (dx.get("icd10") or "").strip()
        name = (dx.get("name") or "").strip()

        if dx.get("negated") or icd.lower() in negated_icds or name.lower() in negated_names:
            filtered_negated.append({
                "icd10": icd,
                "description": name,
                "reason": "negated",
            })
            continue
        active.append(dx)

    # Filter out non-diagnosis entries (medications, labs, vitals)
    non_dx_categories = {"medication", "lab", "vital", "procedure"}
    active = [dx for dx in active if dx.get("category", "disease") not in non_dx_categories]

    # Deduplicate by ICD-10
    seen: dict[str, int] = {}
    unique: list[dict] = []
    for dx in active:
        icd = (dx.get("icd10") or "").strip()
        if not icd:
            continue  # Skip entries without ICD-10 code
        if icd in seen:
            idx = seen[icd]
            if dx.get("confidence", 0) > unique[idx].get("confidence", 0):
                unique[idx] = dx
        else:
            seen[icd] = len(unique)
            unique.append(dx)

    # Sort: HCC-mapped first (by weight desc), then by confidence
    def sort_key(dx):
        w = dx.get("hcc_weight") or 0
        c = dx.get("confidence") or 0
        return (-w, -c)

    unique.sort(key=sort_key)

    logger.info(
        "[Validation Agent] %d diagnoses → %d active, %d negated, %d unique",
        len(diagnoses), len(active), len(filtered_negated), len(unique),
    )

    return {
        "diagnoses": unique,
        "negated_conditions": filtered_negated,
    }
