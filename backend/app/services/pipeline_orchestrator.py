# DISCLAIMER: This module orchestrates a multi-stage clinical analysis pipeline
# that produces CMS-HCC V28 RAF score estimates via the hccinfhir library
# (third-party, not CMS-validated). All outputs require clinician review before
# use in coding or payment determinations.

"""
Pipeline Orchestrator
Coordinates the multi-stage verification pipeline:
  Stage 1: Rule-based extraction (no LLM)
  Stage 2: LLM clinical analysis (Gemini with tools)
  Stage 3: Verification & reconciliation (no LLM)
  Stage 4: RAF calculation + quality scoring

Design reference: docs/MULTI_STAGE_PIPELINE_DESIGN.md
"""

import os
import threading
import time
import logging
from dataclasses import asdict
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Concurrency guard — limits the number of pipeline runs that can be
# executing Stage 2 (Gemini LLM) simultaneously.  This is the primary
# backpressure knob for batch processing: if 10,000 encounters are queued,
# at most MAX_CONCURRENT_ANALYSES will be live at once, preventing token
# exhaustion and OOM conditions.
#
# Tune via the PIPELINE_MAX_CONCURRENT_ANALYSES environment variable.
# Default 5 is conservative; raise to 20-50 for high-throughput paid quotas.
# ---------------------------------------------------------------------------
_MAX_CONCURRENT = int(os.environ.get("PIPELINE_MAX_CONCURRENT_ANALYSES", "5"))
_pipeline_semaphore = threading.Semaphore(_MAX_CONCURRENT)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _stage1_to_dict(stage1) -> dict[str, Any]:
    """
    Convert a PreExtractionResult dataclass to the plain dict format
    expected by stage3_verification.run_stage3().

    Stage 3 was written to accept a dict (to avoid a hard import dependency on
    the Stage 1 dataclass). This thin adapter bridges the two interfaces without
    requiring either module to change its internal contract.

    LabValue entries are also converted to dicts so the result is fully
    JSON-serialisable.
    """
    # Convert LabValue dataclasses to dicts (they may be plain dicts already
    # if stage1 was constructed differently, so guard with hasattr).
    lab_values_serialisable: list[Any] = []
    raw_labs = stage1.lab_values or []
    if isinstance(raw_labs, dict):
        # If dict, convert values to list
        for name, lv in raw_labs.items():
            if hasattr(lv, "__dataclass_fields__"):
                lab_values_serialisable.append(asdict(lv))
            elif isinstance(lv, dict):
                lab_values_serialisable.append(lv)
            else:
                lab_values_serialisable.append({"name": name, "value": str(lv)})
    elif isinstance(raw_labs, list):
        for lv in raw_labs:
            if hasattr(lv, "__dataclass_fields__"):
                lab_values_serialisable.append(asdict(lv))
            elif isinstance(lv, dict):
                lab_values_serialisable.append(lv)
            else:
                lab_values_serialisable.append(str(lv))

    return {
        "explicit_icd_codes":      list(stage1.explicit_icd_codes or []),
        "problem_list_codes":      list(stage1.problem_list_codes or []),
        "assessment_codes":        list(getattr(stage1, "assessment_codes", None) or []),
        "problem_list_conditions": list(getattr(stage1, "problem_list_conditions", None) or getattr(stage1, "problem_list_codes", None) or []),
        "demographics":            dict(getattr(stage1, "demographics", None) or {}),
        "lab_values":              lab_values_serialisable,
        "medications":             list(getattr(stage1, "medications", None) or []),
        "vitals":                  dict(getattr(stage1, "vitals", None) or {}),
        "negation_phrases":        list(getattr(stage1, "negation_phrases", None) or []),
        "note_sections":           dict(getattr(stage1, "note_sections", None) or getattr(stage1, "sections", None) or {}),
        "all_unique_codes":        list(getattr(stage1, "all_unique_codes", None) or set()),
        "parser_version":          getattr(stage1, "parser_version", "stage1_v1"),
        "parse_time_ms":           getattr(stage1, "parse_time_ms", 0.0),
    }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_verified_pipeline(
    clinical_note: str,
    *,
    patient_age: int | None = None,
    patient_sex: str | None = None,
    medications: list[str] | None = None,
    existing_hccs: list[str] | None = None,
    problem_list: list[dict] | None = None,
    recapture_gaps: list[dict] | None = None,
    latest_vitals: dict | None = None,
    med_diagnoses: list[dict] | None = None,
    encounter_year: int | None = None,
) -> dict[str, Any]:
    """
    Run the full multi-stage verified pipeline.

    Stage 1  (rule-based extraction, ~50-150ms)
      -> Stage 2 (Gemini LLM analysis, ~3-8s)
        -> Stage 3 (deterministic reconciliation, ~200-500ms)
          -> Stage 4 (result assembly, ~100ms)

    Returns the same top-level response format as skill_pipeline.run_pipeline()
    for backward compatibility, with two additional keys injected:

      "verification"  — Stage 3 reconciliation metadata (warnings, quality, etc.)
      "extraction"    — Stage 1 extraction summary (code counts, lab values, etc.)

    The "diagnoses" key is replaced with the Stage 3 verified diagnosis list,
    which may include codes restored by Stage 3 that the LLM silently dropped.

    Parameters
    ----------
    clinical_note:
        Raw clinical note text.
    patient_age, patient_sex:
        Demographics. When None, Stage 1 will attempt to parse them from the note.
    medications:
        Medication list from the EHR API (supplements note text parsing).
    existing_hccs:
        HCC codes already on file for this patient (for recapture gap analysis).
    problem_list:
        Active problem list from the EHR API. These codes carry the highest
        obligation — Stage 3 will raise CRITICAL warnings if any are unaccounted.
    recapture_gaps, latest_vitals, med_diagnoses:
        Additional EHR context passed directly to Stage 2 (Gemini).
    encounter_year:
        Encounter year for model version selection (reserved for future use).

    Returns
    -------
    dict with all Stage 2 fields plus "verification" and "extraction" keys.
    Timings for each stage are reported under result["_meta"]["timings"].
    """
    timings: dict[str, float] = {}

    # =========================================================================
    # STAGE 1: Rule-Based Extraction
    # =========================================================================
    t1 = time.time()
    try:
        from app.services.stage1_extraction import run_stage1
        stage1 = run_stage1(
            clinical_note,
            problem_list=problem_list,
            vitals_structured=latest_vitals,
        )
    except Exception as exc:
        # Stage 1 is fast and deterministic — failure is unrecoverable by design
        # (design doc §4.5). Raise immediately so the caller can fall back to
        # the single-stage pipeline.
        logger.error("[Pipeline] Stage 1 failed (unrecoverable): %s", exc, exc_info=True)
        raise

    timings["stage1_extraction"] = round(time.time() - t1, 3)
    logger.info(
        "[Pipeline] Stage 1 complete in %.3fs: %d explicit codes, "
        "%d problem list, %d assessment, %d labs, %d meds",
        timings["stage1_extraction"],
        len(stage1.explicit_icd_codes),
        len(stage1.problem_list_codes),
        len(getattr(stage1, "assessment_codes", []) or []),
        len(stage1.lab_values),
        len(stage1.medications),
    )

    # Resolve demographics: caller-supplied values take priority over parsed ones
    resolved_age = patient_age
    resolved_sex = patient_sex
    if stage1.demographics and not resolved_age:
        resolved_age = stage1.demographics.get("age")
    if stage1.demographics and not resolved_sex:
        resolved_sex = stage1.demographics.get("sex")

    # =========================================================================
    # STAGE 2: LLM Clinical Analysis (existing skill_pipeline — unchanged)
    # =========================================================================
    t2 = time.time()
    try:
        from app.services.skill_pipeline import run_pipeline as llm_pipeline

        # Acquire the concurrency semaphore before starting the Gemini call.
        # This limits the number of simultaneous LLM requests regardless of
        # how many threads/workers are processing a batch.
        acquired = _pipeline_semaphore.acquire(timeout=60)
        if not acquired:
            raise RuntimeError(
                f"Pipeline concurrency limit ({_MAX_CONCURRENT}) reached and "
                "semaphore was not released within 60 s. "
                "Increase PIPELINE_MAX_CONCURRENT_ANALYSES or reduce batch size."
            )
        try:
            stage2_result = llm_pipeline(
                clinical_note=clinical_note,
                patient_age=resolved_age,
                patient_sex=resolved_sex,
                medications=medications,
                existing_hccs=existing_hccs,
                problem_list=problem_list,
                recapture_gaps=recapture_gaps,
                latest_vitals=latest_vitals,
                med_diagnoses=med_diagnoses,
            )
        finally:
            _pipeline_semaphore.release()
    except Exception as exc:
        # Stage 2 (LLM) failure: fall back to a minimal Stage-1-only result
        # (design doc §4.5) so Stages 3 and 4 still run and produce a quality
        # score of 0.0 rather than crashing the entire request.
        logger.warning(
            "[Pipeline] Stage 2 LLM failed — continuing with Stage 1-only "
            "fallback result: %s",
            exc,
            exc_info=True,
        )
        stage2_result = _build_stage2_fallback(stage1)

    timings["stage2_llm"] = round(time.time() - t2, 3)
    logger.info(
        "[Pipeline] Stage 2 complete in %.3fs: %d diagnoses, %d suspects, %d negated",
        timings["stage2_llm"],
        len(stage2_result.get("diagnoses") or []),
        len(stage2_result.get("suspect_conditions") or []),
        len(stage2_result.get("negated_conditions") or stage2_result.get("negated") or []),
    )

    # =========================================================================
    # STAGE 3: Verification & Reconciliation
    # =========================================================================
    t3 = time.time()
    try:
        from app.services.stage3_verification import run_stage3

        # Stage 3 accepts a plain dict for stage1_result (no hard import of the
        # Stage 1 dataclass). Convert here via the thin adapter.
        stage1_dict = _stage1_to_dict(stage1)

        # Stage 3 expects all diagnosis items to use the key "icd10_code" and the
        # negated list to live under the key "negated".
        # skill_pipeline.run_pipeline() uses "icd10" in diagnosis/negated dicts and
        # "negated_conditions" as the list name.  Normalise everything here so Stage 3
        # always sees a consistent contract regardless of which Stage 2 implementation ran.
        stage2_for_stage3 = dict(stage2_result)

        # Normalise negated list key: copy whichever key exists to both.
        if "negated_conditions" in stage2_for_stage3 and "negated" not in stage2_for_stage3:
            stage2_for_stage3["negated"] = stage2_for_stage3["negated_conditions"]
        elif "negated" in stage2_for_stage3 and "negated_conditions" not in stage2_for_stage3:
            stage2_for_stage3["negated_conditions"] = stage2_for_stage3["negated"]

        def _normalize_icd_key(item: dict) -> dict:
            """Return a copy of *item* that always has an "icd10_code" key."""
            if not isinstance(item, dict):
                return item
            if "icd10_code" not in item or not item["icd10_code"]:
                # skill_pipeline uses "icd10" as the field name
                fallback = item.get("icd10") or item.get("code") or ""
                return {**item, "icd10_code": fallback}
            return item

        # Normalise the "diagnoses" list field names.
        if "diagnoses" in stage2_for_stage3:
            stage2_for_stage3["diagnoses"] = [
                _normalize_icd_key(d) for d in (stage2_for_stage3["diagnoses"] or [])
            ]

        # Normalise the "negated" / "negated_conditions" list field names.
        for negated_key in ("negated", "negated_conditions"):
            if negated_key in stage2_for_stage3:
                stage2_for_stage3[negated_key] = [
                    _normalize_icd_key(n) for n in (stage2_for_stage3[negated_key] or [])
                ]

        stage3 = run_stage3(stage1_dict, stage2_for_stage3, note_text=clinical_note)

    except Exception as exc:
        # Stage 3 is pure logic — failure should not occur in normal operation.
        # Raise immediately so the caller falls back to the single-stage pipeline
        # rather than silently returning unverified output (design doc §4.5).
        logger.error("[Pipeline] Stage 3 failed (unrecoverable): %s", exc, exc_info=True)
        raise

    timings["stage3_verification"] = round(time.time() - t3, 3)
    logger.info(
        "[Pipeline] Stage 3 complete in %.3fs: %d verified, %d restored, "
        "%d warnings, quality=%.2f",
        timings["stage3_verification"],
        len(stage3.verified_diagnoses),
        len(stage3.restored_codes),
        len(stage3.warnings),
        stage3.quality_score,
    )

    # =========================================================================
    # STAGE 4: Build the final result
    # =========================================================================
    t4 = time.time()

    # Start from the full Stage 2 response so all existing keys are preserved
    # (backward compatibility — consumers that use raf_score, hcc_details, etc.
    # from Stage 2 continue to work without changes).
    final_result: dict[str, Any] = dict(stage2_result)

    # Replace Stage 2 "diagnoses" with the Stage 3 verified list.
    # Stage 3 has already restored any silently-dropped codes and annotated
    # each entry with stage1_found / stage2_found / stage3_restored flags.
    #
    # Normalize field names on every entry so the frontend always sees a
    # consistent schema regardless of which code path produced the entry:
    #   icd10 / icd10_code  — both set to the same ICD-10 code string
    #   hcc                 — prefixed form "HCC226" (frontend reads dx.hcc)
    #   hcc_code            — bare number string "226" (Stage 3 internal use)
    #   confidence          — numeric float (Stage 3 already computes this)
    #   confidence_label    — human-readable string "high"/"medium"/"low"/"flagged"
    def _normalize_verified_dx(dx: dict) -> dict:
        if not isinstance(dx, dict):
            return dx
        dx = dict(dx)
        # ICD-10: ensure both aliases are present.
        code_val = dx.get("icd10_code") or dx.get("icd10") or ""
        dx["icd10"]      = code_val
        dx["icd10_code"] = code_val
        # HCC: ensure both the prefixed and bare forms are present.
        hcc_val  = dx.get("hcc") or ""
        hcc_code = dx.get("hcc_code") or ""
        if hcc_val and not hcc_val.startswith("HCC"):
            # bare number was stored in "hcc" — promote to prefixed form.
            hcc_code = hcc_val
            hcc_val  = f"HCC{hcc_val}"
        elif hcc_code and hcc_code.startswith("HCC"):
            # prefixed string was stored in "hcc_code" — strip prefix.
            hcc_val  = hcc_code
            hcc_code = hcc_code[3:]
        elif hcc_val and not hcc_code:
            # "hcc" is prefixed but "hcc_code" is missing — derive bare form.
            hcc_code = hcc_val[3:] if hcc_val.startswith("HCC") else hcc_val
        dx["hcc"]      = hcc_val or None
        dx["hcc_code"] = hcc_code or None
        # Confidence: ensure numeric float + label string are both present.
        conf = dx.get("confidence")
        conf_label = dx.get("confidence_label") or dx.get("confidence_text") or ""
        if isinstance(conf, str):
            # Legacy string confidence from Stage 2 — convert to numeric.
            _label_map = {"high": 0.85, "medium": 0.65, "low": 0.45, "flagged": 0.50}
            conf_label = conf_label or conf
            conf = _label_map.get(conf.lower(), 0.50)
        elif isinstance(conf, (int, float)) and not conf_label:
            if conf >= 0.80:
                conf_label = "high"
            elif conf >= 0.60:
                conf_label = "medium"
            else:
                conf_label = "low"
        dx["confidence"]       = conf
        dx["confidence_label"] = conf_label or "low"
        return dx

    final_result["diagnoses"] = [
        _normalize_verified_dx(dx) for dx in (stage3.verified_diagnoses or [])
    ]

    # Backfill hcc_coefficient and raf_weight from the Stage 2 RAF calculation
    # result into each diagnosis.  Stage 2's calculate_raf_score tool call
    # returns hcc_details with per-HCC coefficients, but these are not copied
    # into the per-diagnosis entries by default.
    _raf_tool_result = None
    for tc in (stage2_result.get("pipeline", {}).get("tool_calls", []) or []):
        if tc.get("function") == "calculate_raf_score" and tc.get("result"):
            _raf_tool_result = tc["result"]
            break
    if _raf_tool_result:
        _coeff_by_hcc = {}
        for hd in (_raf_tool_result.get("hcc_details") or _raf_tool_result.get("hcc_contributions") or []):
            hcc_num = str(hd.get("hcc", ""))
            _coeff_by_hcc[hcc_num] = round(float(hd.get("coefficient", 0)), 4)
        for dx in final_result["diagnoses"]:
            hcc_code = dx.get("hcc_code") or ""
            if hcc_code and hcc_code in _coeff_by_hcc:
                dx["hcc_coefficient"] = _coeff_by_hcc[hcc_code]
                dx["raf_weight"] = _coeff_by_hcc[hcc_code]

    # Inject Stage 3 verification metadata as a new top-level key.
    # This is additive — no existing keys are removed or renamed.
    #
    # cc_to_dx: HCC-to-ICD reverse mapping produced by the Stage 2 RAF tool call.
    # Surfaced here so auditors can trace every captured HCC back to the exact
    # ICD codes that triggered it without re-running the pipeline.
    cc_to_dx: dict[str, list[str]] = stage2_result.get("cc_to_dx") or {}

    final_result["verification"] = {
        "restored_codes":       stage3.restored_codes,
        "downgraded_codes":     stage3.downgraded_codes,
        "warnings":             stage3.warnings,
        "excludes1_conflicts":  stage3.excludes1_conflicts,
        "specificity_warnings": stage3.specificity_warnings,
        "quality_score":        stage3.quality_score,
        "reconciliation":       stage3.reconciliation_report,
        "cc_to_dx":             cc_to_dx,
    }

    # Inject Stage 1 extraction summary as a separate top-level key.
    # Consumers can use this for auditing (e.g. "how many codes were in the note
    # before the LLM ran?") without parsing the full reconciliation report.
    # stage1.lab_values is a list[dict] (ExtractionResult contract).
    # Build a name-keyed dict for the extraction summary; guard against both
    # list and legacy dict formats.
    lab_values_out: dict[str, Any] = {}
    raw_lv = stage1.lab_values or []
    if isinstance(raw_lv, dict):
        for name, lv in raw_lv.items():
            if hasattr(lv, "__dataclass_fields__"):
                lab_values_out[name] = asdict(lv)
            else:
                lab_values_out[name] = lv if isinstance(lv, dict) else str(lv)
    else:
        for lv in raw_lv:
            if isinstance(lv, dict):
                name = lv.get("lab_name") or lv.get("name") or str(len(lab_values_out))
                lab_values_out[name] = lv
            elif hasattr(lv, "__dataclass_fields__"):
                d = asdict(lv)
                name = d.get("lab_name") or d.get("name") or str(len(lab_values_out))
                lab_values_out[name] = d
            else:
                lab_values_out[str(len(lab_values_out))] = str(lv)

    final_result["extraction"] = {
        "explicit_codes_count": len(stage1.explicit_icd_codes),
        "problem_list_count":   len(stage1.problem_list_codes),
        "assessment_count":     len(getattr(stage1, "assessment_codes", None) or []),
        "lab_values":           lab_values_out,
        "all_unique_codes":     list(stage1.all_unique_codes),
    }

    # Update _meta timing block (Stage 2 may have already populated _meta).
    timings["stage4_finalize"] = round(time.time() - t4, 3)
    timings["total"] = round(
        timings.get("stage1_extraction", 0)
        + timings.get("stage2_llm", 0)
        + timings.get("stage3_verification", 0)
        + timings.get("stage4_finalize", 0),
        3,
    )
    existing_meta: dict[str, Any] = final_result.get("_meta") or {}
    final_result["_meta"] = {
        **existing_meta,
        "pipeline_version": "verified_v1",
        "stages": ["extraction", "llm_analysis", "verification", "finalize"],
        "timings": timings,
    }

    logger.info(
        "[Pipeline] Complete in %.1fs — %d verified diagnoses, quality=%.2f",
        timings["total"],
        len(stage3.verified_diagnoses),
        stage3.quality_score,
    )

    return final_result


# ---------------------------------------------------------------------------
# Stage 2 fallback result (used when Gemini is unavailable)
# ---------------------------------------------------------------------------

def _build_stage2_fallback(stage1) -> dict[str, Any]:
    """
    Build a minimal Stage 2 result from Stage 1 data when the LLM call fails.

    All codes are taken from Stage 1's explicit_icd_codes and marked as
    "needs_review" so Stage 3 flags the entire result for human review.

    Design doc §4.5: "if Gemini errors, fall back to a minimal LLM result
    that contains only the Stage 1 codes marked as 'llm_unavailable'."
    """
    # stage1.explicit_icd_codes is a list of dicts: {code, section, line_number, context}.
    # Extract the code string defensively.
    def _extract_code_str(item: Any) -> str:
        if isinstance(item, dict):
            return item.get("code") or item.get("icd10_code") or item.get("icd_code") or ""
        return str(item) if item else ""

    fallback_diagnoses = [
        {
            "icd10_code": _extract_code_str(item),
            "description": "",
            "confidence": "needs_review",
            "source": "stage1_fallback",
            "reasoning": "LLM unavailable — code extracted by Stage 1 rule-based parser only.",
            "hcc": None,
        }
        for item in (stage1.explicit_icd_codes or [])
        if _extract_code_str(item)
    ]

    return {
        "diagnoses":          fallback_diagnoses,
        "suspect_conditions": [],
        "negated_conditions": [],
        "negated":            [],
        "meat_evidence":      {},
        "raf_score":          None,
        "hcc_details":        [],
        "_meta": {
            "pipeline_version": "stage1_fallback",
            "llm_fallback":     True,
            "warning":          "LLM (Stage 2) was unavailable. Results are Stage 1 extractions only. Human review required.",
        },
    }
