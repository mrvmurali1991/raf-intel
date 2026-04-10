"""
Confidence-Based Routing Service.

Routes coding results to the appropriate downstream workflow based on
pipeline agreement and per-diagnosis confidence signals.

Expected throughput distribution (target):
  AUTO_ACCEPT  – 60-70 % of cases  (high confidence, MedCAT + Gemini agree)
  HUMAN_REVIEW – 20-25 %           (medium confidence or partial agreement)
  FULL_AUDIT   – 10-15 %           (low confidence or clear disagreement)

Public API
----------
route_analysis_result(medcat_entities, gemini_diagnoses, negation_results,
                       candidate_codes)
    -> dict    Top-level routing decision for an entire encounter.

calculate_agreement(medcat_codes, gemini_codes)
    -> float   Jaccard similarity of the two code sets (0.0 – 1.0).

calculate_confidence(diagnosis, medcat_entities, candidate_codes,
                     negation_results)
    -> float   Composite confidence for a single Gemini diagnosis.

should_auto_accept(diagnosis, medcat_entities, gemini_confidence,
                   candidate_codes, negation_results)
    -> bool    True when all auto-accept gates pass.

get_review_priority(diagnoses)
    -> list[dict]   Diagnoses sorted lowest-confidence-first.

Design notes
------------
* All thresholds are module-level constants – change once, applies everywhere.
* HCC rarity penalties are drawn from a curated set of rare HCCs;
  common HCCs carry no penalty.
* Agreement is Jaccard (intersection / union) over normalised code strings;
  prefix matching adds partial credit for codes in the same category.
* Confidence is a weighted average of six signals:
    1. Gemini raw confidence       (weight 0.30)
    2. MedCAT entity match         (weight 0.25)
    3. Candidate-list presence     (weight 0.20)
    4. MEAT completeness           (weight 0.15)
    5. Negation agreement          (weight 0.05)
    6. ICD-10 code validity        (weight 0.05)
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Routing thresholds
# ---------------------------------------------------------------------------

AUTO_ACCEPT_CONFIDENCE: float = 0.95   # overall_confidence >= this → can auto-accept
HUMAN_REVIEW_CONFIDENCE: float = 0.80  # overall_confidence in [this, AUTO_ACCEPT) → quick review
# Below HUMAN_REVIEW_CONFIDENCE → full audit

AUTO_ACCEPT_AGREEMENT: float = 0.80    # agreement_score needed to reach auto-accept tier
HUMAN_REVIEW_AGREEMENT: float = 0.50   # minimum agreement to stay out of full audit

# Per-diagnosis auto-accept gates
PER_DX_AUTO_CONFIDENCE: float = 0.90         # a single dx needs >= this to auto-accept
PER_DX_RARE_HCC_CONFIDENCE: float = 0.95     # rare HCC codes require a stricter threshold

# Confidence signal weights (must sum to 1.0)
_WEIGHT_GEMINI_CONFIDENCE: float = 0.30
_WEIGHT_MEDCAT_MATCH: float = 0.25
_WEIGHT_CANDIDATE_PRESENCE: float = 0.20
_WEIGHT_MEAT_COMPLETENESS: float = 0.15
_WEIGHT_NEGATION_AGREEMENT: float = 0.05
_WEIGHT_CODE_VALIDITY: float = 0.05


# ---------------------------------------------------------------------------
# HCC rarity catalogue
# ---------------------------------------------------------------------------

# HCC codes that represent rare / complex conditions.
# Rare HCCs require a higher per-diagnosis confidence before auto-acceptance.
# Source: CMS-HCC V28 high-RAF, low-prevalence codes.
_RARE_HCC_CODES: frozenset[str] = frozenset(
    {
        # Rare cancers / neoplasms
        "HCC10", "HCC11", "HCC12",
        # Opportunistic infections
        "HCC6",
        # Septicaemia / severe infections
        "HCC2", "HCC3",
        # Severe CNS disorders
        "HCC72", "HCC73", "HCC74",
        # Transplant / end-stage organ failure
        "HCC134", "HCC135", "HCC136",
        # Severe haematologic
        "HCC46",
        # Rare autoimmune
        "HCC56",
        # Severe cardiovascular
        "HCC84",
    }
)

# Common HCC codes – strong prior that Gemini will get these right.
_COMMON_HCC_CODES: frozenset[str] = frozenset(
    {
        "HCC18",   # Diabetes without complications
        "HCC19",   # Diabetes with acute complications
        "HCC85",   # Congestive heart failure
        "HCC96",   # Ischemic heart disease
        "HCC108",  # COPD
        "HCC22",   # Morbid obesity
        "HCC48",   # Coagulation defects / haemorrhagic
        "HCC111",  # Chronic obstructive pulmonary disease
        "HCC55",   # Major depressive disorder
        "HCC162",  # Chronic kidney disease stage 3-5
    }
)


# ---------------------------------------------------------------------------
# Routing decision constants
# ---------------------------------------------------------------------------

class RoutingDecision:
    AUTO_ACCEPT = "auto_accept"
    HUMAN_REVIEW = "human_review"
    FULL_AUDIT = "full_audit"


# ---------------------------------------------------------------------------
# Public: top-level encounter routing
# ---------------------------------------------------------------------------

def route_analysis_result(
    medcat_entities: list[dict[str, Any]],
    gemini_diagnoses: list[dict[str, Any]],
    negation_results: list[dict[str, Any]],
    candidate_codes: list[dict[str, Any]],
) -> dict[str, Any]:
    """Determine the routing tier for an entire encounter analysis.

    Parameters
    ----------
    medcat_entities:
        List of entity dicts produced by MedCAT.  Each dict should contain
        at minimum ``{"icd10_code": str, "cui": str, "detected_name": str,
        "acc": float}``.  The ``acc`` field is the MedCAT accuracy score.

    gemini_diagnoses:
        List of diagnosis dicts from ``gemini_service.analyze_clinical_note``.
        Expected shape: ``{"icd10_code": str, "condition": str,
        "confidence": float, "negated": bool, "meat_score": int,
        "hcc_code": str | None, ...}``.

    negation_results:
        List of negation-checked result dicts.  Shape:
        ``{"icd10_code": str, "negated": bool, "negation_method": str}``.
        A code present here with ``negated=True`` agrees with Gemini if
        Gemini also flagged it as negated.

    candidate_codes:
        Ranked candidate ICD-10 codes from the retrieve-rank stage.
        Shape: ``{"icd10_code": str, "rank": int, "score": float}``.

    Returns
    -------
    dict with keys:
        routing            – one of RoutingDecision.{AUTO_ACCEPT,
                             HUMAN_REVIEW, FULL_AUDIT}
        overall_confidence – float 0.0-1.0
        agreement_score    – float 0.0-1.0 (Jaccard between MedCAT / Gemini)
        reasons            – list[str] human-readable explanation
        auto_accept_codes  – list[dict] diagnoses cleared for auto-acceptance
        review_codes       – list[dict] diagnoses needing human review
        flags              – list[str] red-flag messages
    """
    reasons: list[str] = []
    flags: list[str] = []
    auto_accept_codes: list[dict[str, Any]] = []
    review_codes: list[dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Guard: nothing to route
    # ------------------------------------------------------------------
    if not gemini_diagnoses:
        logger.warning("route_analysis_result: gemini_diagnoses is empty")
        return {
            "routing": RoutingDecision.FULL_AUDIT,
            "overall_confidence": 0.0,
            "agreement_score": 0.0,
            "reasons": ["No Gemini diagnoses provided – defaulting to full audit."],
            "auto_accept_codes": [],
            "review_codes": [],
            "flags": ["empty_gemini_output"],
        }

    # ------------------------------------------------------------------
    # 1. Build normalised code sets
    # ------------------------------------------------------------------
    medcat_codes: list[str] = _extract_medcat_codes(medcat_entities)
    gemini_codes: list[str] = [
        _norm_code(dx.get("icd10_code", ""))
        for dx in gemini_diagnoses
        if dx.get("icd10_code") and not dx.get("negated", False)
    ]

    # ------------------------------------------------------------------
    # 2. Calculate pipeline agreement (Jaccard)
    # ------------------------------------------------------------------
    agreement_score = calculate_agreement(medcat_codes, gemini_codes)
    logger.debug(
        "route_analysis_result: agreement=%.3f medcat_codes=%s gemini_codes=%s",
        agreement_score,
        medcat_codes,
        gemini_codes,
    )

    # ------------------------------------------------------------------
    # 3. Per-diagnosis confidence + auto-accept classification
    # ------------------------------------------------------------------
    per_dx_confidences: list[float] = []

    for dx in gemini_diagnoses:
        gemini_conf = float(dx.get("confidence", 0.5))

        dx_confidence = calculate_confidence(
            diagnosis=dx,
            medcat_entities=medcat_entities,
            candidate_codes=candidate_codes,
            negation_results=negation_results,
        )
        per_dx_confidences.append(dx_confidence)

        dx_auto = should_auto_accept(
            diagnosis=dx,
            medcat_entities=medcat_entities,
            gemini_confidence=gemini_conf,
            candidate_codes=candidate_codes,
            negation_results=negation_results,
        )

        enriched = {**dx, "computed_confidence": round(dx_confidence, 4)}
        if dx_auto:
            auto_accept_codes.append(enriched)
        else:
            review_codes.append(enriched)

    # ------------------------------------------------------------------
    # 4. Overall confidence = mean of per-diagnosis scores
    # ------------------------------------------------------------------
    if per_dx_confidences:
        overall_confidence = sum(per_dx_confidences) / len(per_dx_confidences)
    else:
        overall_confidence = 0.0

    overall_confidence = round(overall_confidence, 4)

    # ------------------------------------------------------------------
    # 5. Red flags
    # ------------------------------------------------------------------
    flags.extend(_detect_flags(gemini_diagnoses, negation_results, medcat_entities))

    # ------------------------------------------------------------------
    # 6. Derive routing tier
    # ------------------------------------------------------------------
    routing, tier_reasons = _derive_routing(
        overall_confidence=overall_confidence,
        agreement_score=agreement_score,
        auto_accept_count=len(auto_accept_codes),
        review_count=len(review_codes),
        flags=flags,
        gemini_diagnoses=gemini_diagnoses,
    )
    reasons.extend(tier_reasons)

    # When we end up in FULL_AUDIT, move all auto-accepted codes to review
    if routing == RoutingDecision.FULL_AUDIT:
        review_codes = auto_accept_codes + review_codes
        auto_accept_codes = []
        reasons.append(
            "All codes moved to review because encounter-level routing is FULL_AUDIT."
        )

    logger.info(
        "route_analysis_result: routing=%s overall_confidence=%.3f "
        "agreement=%.3f auto=%d review=%d flags=%s",
        routing,
        overall_confidence,
        agreement_score,
        len(auto_accept_codes),
        len(review_codes),
        flags,
    )

    return {
        "routing": routing,
        "overall_confidence": overall_confidence,
        "agreement_score": round(agreement_score, 4),
        "reasons": reasons,
        "auto_accept_codes": auto_accept_codes,
        "review_codes": review_codes,
        "flags": flags,
    }


# ---------------------------------------------------------------------------
# Public: agreement score
# ---------------------------------------------------------------------------

def calculate_agreement(medcat_codes: list[str], gemini_codes: list[str]) -> float:
    """Calculate Jaccard similarity between MedCAT and Gemini code sets.

    Pure Jaccard is augmented with partial prefix credit: if one pipeline
    returns E11.22 and the other returns E11 (a parent category), we award
    0.5 credit rather than treating it as a total miss.

    Parameters
    ----------
    medcat_codes:
        Normalised ICD-10 codes identified by MedCAT.
    gemini_codes:
        Normalised ICD-10 codes from Gemini (non-negated only).

    Returns
    -------
    float in [0.0, 1.0].  Returns 1.0 when both lists are empty (consistent
    empty result).  Returns 0.0 when only one list is empty.
    """
    mc_set = {_norm_code(c) for c in medcat_codes if c}
    gm_set = {_norm_code(c) for c in gemini_codes if c}

    if not mc_set and not gm_set:
        # Both pipelines found nothing – consistent, treat as full agreement
        return 1.0

    if not mc_set or not gm_set:
        # One pipeline returned nothing; agreement is zero
        return 0.0

    # Strict intersection
    strict_intersection = mc_set & gm_set
    strict_union = mc_set | gm_set

    # Partial credit: codes that share a 3-character prefix (same category)
    # but are not identical count as 0.5 in the numerator.
    partial_credit = 0.0
    mc_unmatched = mc_set - strict_intersection
    gm_unmatched = gm_set - strict_intersection

    matched_partial: set[str] = set()
    for mc in mc_unmatched:
        mc_prefix = mc.replace(".", "")[:3]
        for gm in gm_unmatched:
            gm_prefix = gm.replace(".", "")[:3]
            if mc_prefix == gm_prefix and gm not in matched_partial:
                partial_credit += 0.5
                matched_partial.add(gm)
                break  # each MedCAT code gets at most one partial match

    numerator = len(strict_intersection) + partial_credit
    denominator = len(strict_union)

    return min(1.0, numerator / denominator) if denominator > 0 else 1.0


# ---------------------------------------------------------------------------
# Public: per-diagnosis confidence
# ---------------------------------------------------------------------------

def calculate_confidence(
    diagnosis: dict[str, Any],
    medcat_entities: list[dict[str, Any]] | None = None,
    candidate_codes: list[dict[str, Any]] | None = None,
    negation_results: list[dict[str, Any]] | None = None,
) -> float:
    """Calculate a composite confidence score for a single Gemini diagnosis.

    The score is a weighted average of six independent signals:

    Signal                   Weight   Description
    ----------------------   ------   -------------------------------------------
    gemini_confidence         0.30    Raw confidence field from Gemini output
    medcat_match              0.25    MedCAT found the same / related entity
    candidate_presence        0.20    Code appeared in retrieve-rank candidates
    meat_completeness         0.15    Proportion of MEAT elements present (0-4)
    negation_agreement        0.05    Both pipelines agree on negation status
    code_validity             0.05    ICD-10-CM code passes structural check

    Parameters
    ----------
    diagnosis:
        Single diagnosis dict from Gemini (``icd10_code``, ``confidence``,
        ``negated``, ``meat_score``, ``hcc_code``, etc.).
    medcat_entities:
        Full list of MedCAT entities for this encounter.
    candidate_codes:
        Ranked candidate codes from the retrieve-rank pipeline.
    negation_results:
        Negation-checked results for this encounter.

    Returns
    -------
    float in [0.0, 1.0].
    """
    medcat_entities = medcat_entities or []
    candidate_codes = candidate_codes or []
    negation_results = negation_results or []

    icd_code = _norm_code(diagnosis.get("icd10_code", ""))
    gemini_neg = bool(diagnosis.get("negated", False))

    # -- Signal 1: Gemini raw confidence ------------------------------------
    s_gemini = _clamp(float(diagnosis.get("confidence", 0.5)))

    # -- Signal 2: MedCAT entity match -------------------------------------
    s_medcat = _medcat_match_score(icd_code, medcat_entities)

    # -- Signal 3: Candidate-list presence ---------------------------------
    s_candidate = _candidate_presence_score(icd_code, candidate_codes)

    # -- Signal 4: MEAT completeness ---------------------------------------
    raw_meat_score = diagnosis.get("meat_score", 0)
    try:
        meat_score = max(0, min(4, int(raw_meat_score)))
    except (TypeError, ValueError):
        meat_score = 0

    # Check whether individual MEAT fields are populated (richer signal)
    meat_dict = diagnosis.get("meat", {})
    if isinstance(meat_dict, dict):
        filled_fields = sum(
            1
            for v in (
                meat_dict.get("monitoring", ""),
                meat_dict.get("evaluation", ""),
                meat_dict.get("assessment", ""),
                meat_dict.get("treatment", ""),
            )
            if v and str(v).strip()
        )
        meat_score = max(meat_score, filled_fields)

    s_meat = meat_score / 4.0

    # -- Signal 5: Negation agreement --------------------------------------
    s_negation = _negation_agreement_score(icd_code, gemini_neg, negation_results)

    # -- Signal 6: ICD-10 code validity ------------------------------------
    s_validity = _code_validity_score(icd_code)

    # -- Weighted composite ------------------------------------------------
    composite = (
        _WEIGHT_GEMINI_CONFIDENCE * s_gemini
        + _WEIGHT_MEDCAT_MATCH * s_medcat
        + _WEIGHT_CANDIDATE_PRESENCE * s_candidate
        + _WEIGHT_MEAT_COMPLETENESS * s_meat
        + _WEIGHT_NEGATION_AGREEMENT * s_negation
        + _WEIGHT_CODE_VALIDITY * s_validity
    )

    logger.debug(
        "calculate_confidence %s: gemini=%.2f medcat=%.2f candidate=%.2f "
        "meat=%.2f negation=%.2f validity=%.2f -> composite=%.4f",
        icd_code,
        s_gemini,
        s_medcat,
        s_candidate,
        s_meat,
        s_negation,
        s_validity,
        composite,
    )

    return _clamp(composite)


# ---------------------------------------------------------------------------
# Public: per-diagnosis auto-accept gate
# ---------------------------------------------------------------------------

def should_auto_accept(
    diagnosis: dict[str, Any],
    medcat_entities: list[dict[str, Any]] | None = None,
    gemini_confidence: float = 0.0,
    candidate_codes: list[dict[str, Any]] | None = None,
    negation_results: list[dict[str, Any]] | None = None,
) -> bool:
    """Determine whether a specific diagnosis can be auto-accepted.

    All of the following gates must pass:

    Gate 1  Computed composite confidence >= PER_DX_AUTO_CONFIDENCE
            (or >= PER_DX_RARE_HCC_CONFIDENCE for rare HCC codes)
    Gate 2  MedCAT found a matching entity (score > 0)
    Gate 3  Code is present in the retrieve-rank candidate list
    Gate 4  ICD-10 code passes structural validation
    Gate 5  MEAT score >= 1 (at least one MEAT element documented)
    Gate 6  Negation status is consistent across both pipelines
    Gate 7  Not flagged as historical-only (without active treatment) or
            family-history-only
    Gate 8  Rare HCC: raw Gemini confidence also passes strict threshold

    Parameters
    ----------
    diagnosis:
        Single Gemini diagnosis dict.
    medcat_entities:
        MedCAT entity list for this encounter.
    gemini_confidence:
        Raw Gemini confidence value (passed explicitly so callers avoid
        re-extracting it from the dict).
    candidate_codes:
        Retrieve-rank candidate list.
    negation_results:
        Negation results for this encounter.

    Returns
    -------
    bool – True only when every gate passes.
    """
    medcat_entities = medcat_entities or []
    candidate_codes = candidate_codes or []
    negation_results = negation_results or []

    icd_code = _norm_code(diagnosis.get("icd10_code", ""))
    hcc_code = str(diagnosis.get("hcc_code") or "").strip()
    is_rare = hcc_code in _RARE_HCC_CODES

    # Compute composite confidence
    composite = calculate_confidence(
        diagnosis=diagnosis,
        medcat_entities=medcat_entities,
        candidate_codes=candidate_codes,
        negation_results=negation_results,
    )

    # Gate 1: composite confidence threshold (stricter for rare HCCs)
    threshold = PER_DX_RARE_HCC_CONFIDENCE if is_rare else PER_DX_AUTO_CONFIDENCE
    if composite < threshold:
        logger.debug(
            "should_auto_accept REJECT %s: composite %.4f < threshold %.4f (rare=%s)",
            icd_code, composite, threshold, is_rare,
        )
        return False

    # Gate 2: MedCAT must have found a matching entity
    medcat_score = _medcat_match_score(icd_code, medcat_entities)
    if medcat_score == 0.0:
        logger.debug("should_auto_accept REJECT %s: no MedCAT entity match", icd_code)
        return False

    # Gate 3: code must be in the retrieve-rank candidates
    candidate_score = _candidate_presence_score(icd_code, candidate_codes)
    if candidate_score == 0.0:
        logger.debug(
            "should_auto_accept REJECT %s: not in candidate list", icd_code
        )
        return False

    # Gate 4: ICD-10 code validity
    if _code_validity_score(icd_code) == 0.0:
        logger.debug("should_auto_accept REJECT %s: invalid ICD-10 code", icd_code)
        return False

    # Gate 5: MEAT – at least one element must be documented
    raw_meat = diagnosis.get("meat_score", 0)
    try:
        meat_score = max(0, min(4, int(raw_meat)))
    except (TypeError, ValueError):
        meat_score = 0

    if meat_score == 0:
        # Recheck using individual meat field text
        meat_dict = diagnosis.get("meat", {})
        if isinstance(meat_dict, dict):
            meat_score = sum(
                1
                for v in (
                    meat_dict.get("monitoring", ""),
                    meat_dict.get("evaluation", ""),
                    meat_dict.get("assessment", ""),
                    meat_dict.get("treatment", ""),
                )
                if v and str(v).strip()
            )

    if meat_score < 1:
        logger.debug(
            "should_auto_accept REJECT %s: MEAT score %d < 1", icd_code, meat_score
        )
        return False

    # Gate 6: negation consistency
    gemini_neg = bool(diagnosis.get("negated", False))
    neg_score = _negation_agreement_score(icd_code, gemini_neg, negation_results)
    if neg_score < 0.5:
        logger.debug(
            "should_auto_accept REJECT %s: negation disagreement (neg_score=%.2f)",
            icd_code, neg_score,
        )
        return False

    # Gate 7: not purely historical or family-history-only
    if diagnosis.get("historical") and not diagnosis.get("treatment"):
        # Historical diagnoses require at least active treatment to auto-accept
        logger.debug(
            "should_auto_accept REJECT %s: historical-only without active treatment",
            icd_code,
        )
        return False

    if diagnosis.get("family_history"):
        logger.debug(
            "should_auto_accept REJECT %s: family-history flag is set", icd_code
        )
        return False

    # Gate 8: rare HCC – raw Gemini confidence must also clear the strict bar
    if is_rare and gemini_confidence < PER_DX_RARE_HCC_CONFIDENCE:
        logger.debug(
            "should_auto_accept REJECT %s (rare HCC %s): raw Gemini confidence "
            "%.3f < %.3f",
            icd_code, hcc_code, gemini_confidence, PER_DX_RARE_HCC_CONFIDENCE,
        )
        return False

    logger.debug(
        "should_auto_accept ACCEPT %s: composite=%.4f medcat=%.2f "
        "candidate=%.2f meat=%d rare=%s",
        icd_code, composite, medcat_score, candidate_score, meat_score, is_rare,
    )
    return True


# ---------------------------------------------------------------------------
# Public: sort by review priority
# ---------------------------------------------------------------------------

def get_review_priority(diagnoses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return diagnoses sorted by review priority – lowest confidence first.

    Diagnoses with a pre-computed ``computed_confidence`` key (as set by
    ``route_analysis_result``) are sorted by that value.  Otherwise, the
    raw Gemini ``confidence`` is used as a fallback.  Ties are broken by
    MEAT score (ascending), then by HCC rarity (rare codes come first).

    Parameters
    ----------
    diagnoses:
        List of diagnosis dicts (may be raw Gemini output or enriched by
        ``route_analysis_result``).

    Returns
    -------
    New list sorted from highest-priority-to-review (lowest confidence) to
    lowest-priority (highest confidence).
    """
    def _sort_key(dx: dict[str, Any]) -> tuple[float, int, int]:
        confidence = float(
            dx.get("computed_confidence") or dx.get("confidence") or 0.5
        )
        meat = int(dx.get("meat_score") or 0)
        hcc = str(dx.get("hcc_code") or "")
        # Rare HCCs should surface ahead of common ones at the same confidence
        is_rare_flag = -1 if hcc in _RARE_HCC_CODES else 0
        return (confidence, meat, is_rare_flag)

    return sorted(diagnoses, key=_sort_key)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _norm_code(code: str) -> str:
    """Upper-case and strip an ICD-10 code string (no external dependency)."""
    return (code or "").strip().upper()


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    """Clamp *value* to [lo, hi]."""
    return max(lo, min(hi, value))


def _extract_medcat_codes(medcat_entities: list[dict[str, Any]]) -> list[str]:
    """Pull ICD-10 codes out of MedCAT entity dicts.

    MedCAT entities may carry the code under several keys depending on
    the linker in use: ``icd10_code``, ``icd10``, ``linked_concept``, ``code``.
    """
    codes: list[str] = []
    for entity in medcat_entities:
        for key in ("icd10_code", "icd10", "linked_concept", "code"):
            val = entity.get(key)
            if val:
                code = _norm_code(str(val))
                if code and code not in codes:
                    codes.append(code)
                break
    return codes


def _medcat_match_score(
    icd_code: str,
    medcat_entities: list[dict[str, Any]],
) -> float:
    """Score how well MedCAT supports a given ICD-10 code.

    Returns
    -------
    1.0  – exact match on normalised code (boosted by MedCAT accuracy)
    0.70 – same 3-character category prefix (parent or sibling)
    0.40 – soft text match between entity name and code prefix
    0.0  – no relationship found
    """
    if not icd_code or not medcat_entities:
        return 0.0

    prefix = icd_code.replace(".", "")[:3]

    for entity in medcat_entities:
        # Exact code match
        for key in ("icd10_code", "icd10", "linked_concept", "code"):
            entity_code = _norm_code(str(entity.get(key) or ""))
            if entity_code and entity_code == icd_code:
                # Scale by MedCAT accuracy score when available
                acc = float(entity.get("acc", entity.get("accuracy", 1.0)) or 1.0)
                return _clamp(0.85 + 0.15 * acc)

        # Prefix (category) match
        for key in ("icd10_code", "icd10", "linked_concept", "code"):
            entity_code = _norm_code(str(entity.get(key) or ""))
            if entity_code and entity_code.replace(".", "")[:3] == prefix:
                return 0.70

    # Soft text match: check if the detected entity name overlaps with the
    # ICD-10 prefix (crude but useful when MedCAT returns SNOMED / CUI only)
    prefix_lower = prefix.lower()
    for entity in medcat_entities:
        name = (entity.get("detected_name") or entity.get("name") or "").lower()
        if name and (prefix_lower in name or name[:4] in prefix_lower):
            return 0.40

    return 0.0


def _candidate_presence_score(
    icd_code: str,
    candidate_codes: list[dict[str, Any]],
) -> float:
    """Score a code's presence in the retrieve-rank candidate list.

    Returns
    -------
    1.0  – exact match at rank 1
    0.85 – exact match at rank 2-3
    0.70 – exact match at rank 4+
    0.50 – same 3-character category prefix at any rank
    0.0  – not in candidate list
    """
    if not icd_code or not candidate_codes:
        return 0.0

    prefix = icd_code.replace(".", "")[:3]
    best = 0.0

    for candidate in candidate_codes:
        cand_code = _norm_code(candidate.get("icd10_code", ""))
        rank = int(candidate.get("rank", 99))

        if cand_code == icd_code:
            if rank == 1:
                return 1.0
            elif rank <= 3:
                best = max(best, 0.85)
            else:
                best = max(best, 0.70)
        elif cand_code.replace(".", "")[:3] == prefix:
            best = max(best, 0.50)

    return best


def _negation_agreement_score(
    icd_code: str,
    gemini_negated: bool,
    negation_results: list[dict[str, Any]],
) -> float:
    """Compare Gemini negation status against the dedicated negation pipeline.

    Returns
    -------
    1.0  – both pipelines agree (both positive or both negative)
    0.3  – pipelines disagree (one says negated, the other does not)
    0.7  – code not found in negation_results (neutral / partial credit)
    """
    if not icd_code or not negation_results:
        return 0.70  # neutral: no negation data to compare against

    prefix = icd_code.replace(".", "")[:3]

    for neg in negation_results:
        neg_code = _norm_code(neg.get("icd10_code", ""))
        if neg_code == icd_code or neg_code.replace(".", "")[:3] == prefix:
            pipeline_negated = bool(neg.get("negated", False))
            return 1.0 if pipeline_negated == gemini_negated else 0.3

    return 0.70  # code not in negation results


def _code_validity_score(icd_code: str) -> float:
    """Return a validity score based on a structural check of the ICD-10 code.

    We use a lightweight structural check to avoid importing
    ``simple_icd_10_cm`` here.  Callers who need authoritative leaf
    validation should call ``icd_validator.validate_icd10_code`` directly.

    Pattern: [A-Z][0-9]{2}[0-9A-Z]{0,4}  (dots stripped for checking)

    Returns
    -------
    1.0  – structurally valid
    0.3  – structurally invalid (wrong length or characters)
    0.0  – empty string
    """
    if not icd_code:
        return 0.0

    code = icd_code.replace(".", "").upper()

    if len(code) < 3 or len(code) > 7:
        return 0.3

    # First character must be a letter (ICD-10-CM starts with A-Z)
    if not code[0].isalpha():
        return 0.3

    # Characters 2-3 must be digits
    if not code[1].isdigit() or not code[2].isdigit():
        return 0.3

    # Remaining characters must be alphanumeric
    for ch in code[3:]:
        if not ch.isalnum():
            return 0.3

    return 1.0


def _detect_flags(
    gemini_diagnoses: list[dict[str, Any]],
    negation_results: list[dict[str, Any]],
    medcat_entities: list[dict[str, Any]],
) -> list[str]:
    """Detect encounter-level red flags that influence routing decisions.

    Flags produced
    --------------
    empty_gemini_output       – no Gemini diagnoses (handled upstream)
    no_medcat_entities        – MedCAT returned no entities at all
    rare_hcc_present          – at least one rare HCC code is in the encounter
    low_gemini_confidence     – average raw Gemini confidence < 0.60
    meat_absent               – a non-negated, non-historical dx has meat_score 0
    negation_conflict         – exactly one code has a negation disagreement
    multiple_negation_flips   – two or more codes have negation disagreements
    """
    flags: list[str] = []

    # -- Flag: no MedCAT entities
    if not medcat_entities:
        flags.append("no_medcat_entities")

    # -- Flag: rare HCC present
    for dx in gemini_diagnoses:
        hcc = str(dx.get("hcc_code") or "")
        if hcc in _RARE_HCC_CODES:
            flags.append("rare_hcc_present")
            break

    # -- Flag: low average Gemini confidence across non-negated diagnoses
    active_confidences = [
        float(dx.get("confidence", 0.5))
        for dx in gemini_diagnoses
        if not dx.get("negated")
    ]
    if active_confidences and (sum(active_confidences) / len(active_confidences)) < 0.60:
        flags.append("low_gemini_confidence")

    # -- Flags: negation conflicts and MEAT absence
    negation_flip_count = 0
    meat_absent_flagged = False

    for dx in gemini_diagnoses:
        # Skip negated / historical / family-history codes for MEAT check
        if dx.get("negated") or dx.get("historical") or dx.get("family_history"):
            continue

        icd_code = _norm_code(dx.get("icd10_code", ""))
        gemini_neg = bool(dx.get("negated", False))

        # Negation agreement check
        neg_score = _negation_agreement_score(icd_code, gemini_neg, negation_results)
        if neg_score < 0.5:
            negation_flip_count += 1

        # MEAT absence check
        if not meat_absent_flagged:
            raw_meat = dx.get("meat_score", 0)
            try:
                meat = max(0, min(4, int(raw_meat)))
            except (TypeError, ValueError):
                meat = 0
            if meat == 0:
                meat_dict = dx.get("meat", {})
                if isinstance(meat_dict, dict):
                    meat = sum(
                        1
                        for v in (
                            meat_dict.get("monitoring", ""),
                            meat_dict.get("evaluation", ""),
                            meat_dict.get("assessment", ""),
                            meat_dict.get("treatment", ""),
                        )
                        if v and str(v).strip()
                    )
            if meat == 0:
                flags.append("meat_absent")
                meat_absent_flagged = True

    if negation_flip_count == 1:
        flags.append("negation_conflict")
    elif negation_flip_count >= 2:
        flags.append("multiple_negation_flips")

    # Deduplicate while preserving insertion order
    return list(dict.fromkeys(flags))


def _derive_routing(
    overall_confidence: float,
    agreement_score: float,
    auto_accept_count: int,
    review_count: int,
    flags: list[str],
    gemini_diagnoses: list[dict[str, Any]],
) -> tuple[str, list[str]]:
    """Derive the encounter-level routing tier and produce explanatory reasons.

    Returns
    -------
    (routing_tier: str, reasons: list[str])
    """
    reasons: list[str] = []

    # Hard flags always force FULL_AUDIT regardless of confidence scores
    hard_audit_flags = {"multiple_negation_flips", "no_medcat_entities"}
    triggered = hard_audit_flags & set(flags)
    if triggered:
        reasons.append(
            f"Hard-audit flag(s) triggered: {', '.join(sorted(triggered))}."
        )
        return RoutingDecision.FULL_AUDIT, reasons

    # Agreement too low even for human-review tier
    if agreement_score < HUMAN_REVIEW_AGREEMENT:
        reasons.append(
            f"Agreement score {agreement_score:.2f} is below the minimum "
            f"{HUMAN_REVIEW_AGREEMENT:.2f} threshold for human-review tier."
        )
        reasons.append(
            "MedCAT and Gemini disagree substantially on the code set – "
            "clinical validation required."
        )
        return RoutingDecision.FULL_AUDIT, reasons

    # Confidence too low even for human-review tier
    if overall_confidence < HUMAN_REVIEW_CONFIDENCE:
        reasons.append(
            f"Overall confidence {overall_confidence:.2f} is below the "
            f"human-review threshold {HUMAN_REVIEW_CONFIDENCE:.2f}."
        )
        return RoutingDecision.FULL_AUDIT, reasons

    # All diagnoses cleared auto-accept gates individually
    all_auto_accepted = review_count == 0 and auto_accept_count > 0
    high_confidence = overall_confidence >= AUTO_ACCEPT_CONFIDENCE
    high_agreement = agreement_score >= AUTO_ACCEPT_AGREEMENT

    # Soft flags may downgrade auto-accept to human-review but not to audit
    soft_flags = {"rare_hcc_present", "low_gemini_confidence", "meat_absent",
                  "negation_conflict"}
    triggered_soft = set(flags) & soft_flags

    if all_auto_accepted and high_confidence and high_agreement:
        if not triggered_soft:
            reasons.append(
                f"All {auto_accept_count} diagnosis/diagnoses cleared all "
                f"auto-accept gates."
            )
            reasons.append(
                f"Overall confidence {overall_confidence:.2f} >= "
                f"{AUTO_ACCEPT_CONFIDENCE:.2f} and agreement "
                f"{agreement_score:.2f} >= {AUTO_ACCEPT_AGREEMENT:.2f}."
            )
            return RoutingDecision.AUTO_ACCEPT, reasons
        else:
            reasons.append(
                f"Soft flag(s) present ({', '.join(sorted(triggered_soft))}) "
                f"– downgrading from auto-accept to human-review."
            )
            return RoutingDecision.HUMAN_REVIEW, reasons

    # Mixed: some auto-accepted, some require review
    if auto_accept_count > 0 and review_count > 0:
        reasons.append(
            f"{auto_accept_count} code(s) cleared auto-accept; "
            f"{review_count} code(s) require human review."
        )
        return RoutingDecision.HUMAN_REVIEW, reasons

    # All codes require review, but confidence is in the acceptable range
    reasons.append(
        f"Confidence {overall_confidence:.2f} is in the human-review range "
        f"[{HUMAN_REVIEW_CONFIDENCE:.2f}, {AUTO_ACCEPT_CONFIDENCE:.2f})."
    )
    if triggered_soft:
        reasons.append(
            f"Soft flag(s) also present: {', '.join(sorted(triggered_soft))}."
        )
    return RoutingDecision.HUMAN_REVIEW, reasons
