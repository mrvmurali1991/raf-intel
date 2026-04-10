"""
Pipeline Orchestrator — Coordinates specialized agents for clinical analysis.

Flow:
  1. NER Agent (Gemini) → extract entities
  2. HCC Agent (DB) → map ICD to HCC codes
  3. MEAT Agent + Suspect Agent (Gemini, PARALLEL) → evidence + gaps
  4. Validation Agent (local) → deduplicate, validate, finalize
"""
import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from app.services.agents import ner_agent, meat_agent, suspect_agent, hcc_agent, validation_agent

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=3)


def run_pipeline(
    clinical_note: str,
    *,
    patient_age: int | None = None,
    patient_sex: str | None = None,
    medications: list[str] | None = None,
    existing_hccs: list[str] | None = None,
) -> dict[str, Any]:
    """
    Run the full agentic analysis pipeline.

    Returns structured result with: diagnoses, suspect_conditions,
    negated_conditions, pipeline metadata, confidence_routing.
    """
    pipeline_meta = {
        "stages_run": [],
        "timings": {},
        "medcat_entities": [],  # kept for frontend compatibility
        "after_negation_filter": [],
        "candidate_codes": [],
    }

    total_start = time.time()

    # ── Step 1: NER Agent ──────────────────────────────────────────
    t0 = time.time()
    entities = ner_agent.extract(clinical_note)
    pipeline_meta["timings"]["ner"] = round(time.time() - t0, 2)
    pipeline_meta["stages_run"].append("ner_agent")

    # Separate negated vs present
    present = [e for e in entities if not e.get("negated")]
    negated = [e for e in entities if e.get("negated")]

    # Store for frontend pipeline display
    pipeline_meta["medcat_entities"] = entities
    pipeline_meta["after_negation_filter"] = present

    logger.info("[Orchestrator] NER: %d entities (%d present, %d negated) in %.1fs",
                len(entities), len(present), len(negated), pipeline_meta["timings"]["ner"])

    if not present:
        logger.warning("[Orchestrator] No present entities found, returning empty result")
        return _build_result([], [], negated, pipeline_meta, total_start)

    # ── Step 2: HCC Mapping (instant, DB only) ────────────────────
    t1 = time.time()
    present_with_hcc = hcc_agent.map_icd_to_hcc(present)
    pipeline_meta["timings"]["hcc_mapping"] = round(time.time() - t1, 2)
    pipeline_meta["stages_run"].append("hcc_agent")

    logger.info("[Orchestrator] HCC mapping: %.2fs", pipeline_meta["timings"]["hcc_mapping"])

    # ── Step 3: MEAT + Suspects in PARALLEL ────────────────────────
    t2 = time.time()

    # Run MEAT and Suspects concurrently using threads
    with ThreadPoolExecutor(max_workers=2) as pool:
        meat_future = pool.submit(meat_agent.evaluate, present_with_hcc, clinical_note)
        suspect_future = pool.submit(
            suspect_agent.detect,
            present_with_hcc,
            medications or [],
            clinical_note
        )

        meat_results = meat_future.result(timeout=180)
        suspect_results = suspect_future.result(timeout=120)

    pipeline_meta["timings"]["meat_and_suspects"] = round(time.time() - t2, 2)
    pipeline_meta["stages_run"].extend(["meat_agent", "suspect_agent"])

    logger.info("[Orchestrator] MEAT + Suspects: %.1fs (parallel)",
                pipeline_meta["timings"]["meat_and_suspects"])

    # ── Step 4: Merge MEAT results back into diagnoses ─────────────
    # MEAT agent returns enriched diagnoses — merge with HCC data
    final_diagnoses = _merge_meat_with_hcc(present_with_hcc, meat_results)

    # ── Step 5: Validation ─────────────────────────────────────────
    t3 = time.time()
    validated = validation_agent.validate(final_diagnoses, negated)
    pipeline_meta["timings"]["validation"] = round(time.time() - t3, 2)
    pipeline_meta["stages_run"].append("validation_agent")

    return _build_result(
        validated["diagnoses"],
        suspect_results,
        validated["negated_conditions"],
        pipeline_meta,
        total_start,
    )


def _merge_meat_with_hcc(hcc_diagnoses: list[dict], meat_results: list[dict]) -> list[dict]:
    """Merge MEAT evidence into HCC-mapped diagnoses."""
    # Build lookup from MEAT results by ICD-10
    meat_by_icd: dict[str, dict] = {}
    for m in meat_results:
        icd = (m.get("icd10") or "").strip()
        if icd:
            meat_by_icd[icd] = m

    merged = []
    for dx in hcc_diagnoses:
        icd = (dx.get("icd10") or "").strip()
        meat_data = meat_by_icd.get(icd, {})

        meat = meat_data.get("meat", {"M": "", "E": "", "A": "", "T": ""})
        if isinstance(meat, dict):
            # Normalize keys
            meat = {
                "M": meat.get("M", "") or meat.get("monitoring", ""),
                "E": meat.get("E", "") or meat.get("evaluation", ""),
                "A": meat.get("A", "") or meat.get("assessment", ""),
                "T": meat.get("T", "") or meat.get("treatment", ""),
            }
        else:
            meat = {"M": "", "E": "", "A": "", "T": ""}

        meat_score = sum(1 for v in meat.values() if v and v.strip())

        merged.append({
            "icd10": icd,
            "description": dx.get("name", "") or dx.get("description", "") or meat_data.get("description", ""),
            "hcc": dx.get("hcc", ""),
            "hcc_label": dx.get("hcc_label", ""),
            "hcc_weight": dx.get("hcc_weight"),
            "confidence": float(meat_data.get("confidence", dx.get("confidence", 0.5))),
            "meat": meat,
            "meat_score": meat_score,
            "source": "agentic_pipeline",
        })

    return merged


def _build_result(
    diagnoses: list[dict],
    suspects: list[dict],
    negated: list[dict],
    pipeline_meta: dict,
    total_start: float,
) -> dict[str, Any]:
    """Build the final result dict."""
    total_time = round(time.time() - total_start, 2)
    pipeline_meta["timings"]["total"] = total_time

    # Confidence routing
    if diagnoses:
        avg_confidence = sum(d.get("confidence", 0) for d in diagnoses) / len(diagnoses)
        hcc_count = sum(1 for d in diagnoses if d.get("hcc"))
    else:
        avg_confidence = 0
        hcc_count = 0

    if avg_confidence >= 0.85 and hcc_count > 0:
        routing = "auto_accept"
    elif avg_confidence >= 0.70:
        routing = "human_review"
    else:
        routing = "full_audit"

    logger.info("[Orchestrator] Pipeline complete in %.1fs: %d diagnoses, %d suspects, routing=%s",
                total_time, len(diagnoses), len(suspects), routing)

    return {
        "diagnoses": diagnoses,
        "suspect_conditions": suspects,
        "negated_conditions": negated,
        "pipeline": pipeline_meta,
        "confidence_routing": {
            "routing": routing,
            "overall_confidence": round(avg_confidence, 3),
            "hcc_count": hcc_count,
            "agreement_score": round(avg_confidence, 3),
        },
        "coding_notes": f"Agentic pipeline: {len(diagnoses)} diagnoses, {hcc_count} HCC-mapped, {len(suspects)} suspects",
        "_meta": {
            "pipeline_version": "agentic_v1",
            "total_time_seconds": total_time,
            "stages": pipeline_meta["stages_run"],
            "timings": pipeline_meta["timings"],
        },
    }
