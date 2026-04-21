"""Suspect HCC detection engine (Agent 8).

Hybrid rule + LLM pipeline that discovers conditions a patient likely
has but which are *not* present in the coded problem list.

Consumes a ``PatientContextBundle`` (Agent 4) and emits
``SuspectCandidate`` records.  Every candidate is tagged for provider
query (Agent 9) — suspects are never auto-coded.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from pathlib import Path

from app.services.llm import llm_generate

from .rules import ALL_RULES
from .suspect_schema import (
    SupportingEvidence,
    SuspectCandidate,
    SuspectRule,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Rule layer
# ---------------------------------------------------------------------------
def run_rules(bundle: dict, rules: Iterable[SuspectRule] = ALL_RULES) -> list[SuspectCandidate]:
    out: list[SuspectCandidate] = []
    for rule in rules:
        try:
            cand = rule.evaluate(bundle)
        except Exception:  # noqa: BLE001
            logger.exception("Suspect rule %s crashed", rule.rule_id)
            continue
        if cand is not None:
            cand.source = "rule"
            cand.requires_provider_query = True
            out.append(cand)
    return out


# ---------------------------------------------------------------------------
# LLM layer
# ---------------------------------------------------------------------------
_PROMPT_PATH = Path(__file__).parent / "prompts" / "suspect_detect.md"


def _load_prompt_template() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


def _bundle_for_llm(bundle: dict) -> dict:
    """Redact PHI and keep only clinical-signal surfaces the LLM needs."""
    keep = ("labs", "medications", "vitals", "problem_list", "prior_hccs", "demographics_summary")
    return {k: bundle.get(k) for k in keep if k in bundle}


def run_llm(bundle: dict, model: str = "gemini-2.0-flash") -> list[SuspectCandidate]:
    template = _load_prompt_template()
    prompt = template.replace("{{BUNDLE_JSON}}", json.dumps(_bundle_for_llm(bundle), default=str))
    try:
        raw = llm_generate(prompt, model=model, temperature=0.1)
    except Exception:  # noqa: BLE001
        logger.exception("LLM suspect pass failed")
        return []

    try:
        payload = json.loads(_strip_fences(raw))
    except json.JSONDecodeError:
        logger.warning("LLM suspect pass returned non-JSON: %s", raw[:200])
        return []

    out: list[SuspectCandidate] = []
    for item in payload.get("suspects", []):
        try:
            out.append(SuspectCandidate(
                icd10=item["icd10"],
                hcc=item.get("hcc", ""),
                reason=item.get("reason", ""),
                supporting_evidence=[
                    SupportingEvidence(
                        type=e.get("type", "lab"),
                        ref_id=str(e.get("ref_id", "")),
                        value=str(e.get("value", "")),
                    )
                    for e in item.get("supporting_evidence", [])
                ],
                confidence=float(item.get("confidence", 0.5)),
                source="llm",
                requires_provider_query=True,
            ))
        except (KeyError, TypeError, ValueError):
            logger.warning("Malformed LLM suspect item: %s", item)
    return out


def _strip_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t[3:]
        if t.endswith("```"):
            t = t[: -3]
        if t.startswith("json"):
            t = t[4:]
    return t.strip()


# ---------------------------------------------------------------------------
# Merge & dedupe
# ---------------------------------------------------------------------------
def merge(rule_out: list[SuspectCandidate], llm_out: list[SuspectCandidate]) -> list[SuspectCandidate]:
    by_key: dict[str, SuspectCandidate] = {}
    for cand in [*rule_out, *llm_out]:
        key = cand.fingerprint
        if key not in by_key:
            by_key[key] = cand
            continue
        existing = by_key[key]
        # Merge: prefer rule icd10, union evidence, boost confidence, mark both.
        merged_evidence = {(e.type, e.ref_id): e for e in existing.supporting_evidence}
        for e in cand.supporting_evidence:
            merged_evidence.setdefault((e.type, e.ref_id), e)
        existing.supporting_evidence = list(merged_evidence.values())
        existing.confidence = min(1.0, max(existing.confidence, cand.confidence) + 0.1)
        existing.source = "both"
        if cand.source == "rule" and existing.source != "rule":
            existing.icd10 = cand.icd10
            existing.hcc = cand.hcc or existing.hcc
        existing.requires_provider_query = True
    return list(by_key.values())


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def detect_suspects(
    bundle: dict,
    *,
    use_llm: bool = True,
    model: str = "gemini-2.0-flash",
) -> list[SuspectCandidate]:
    """Run the full rule + LLM pipeline and return merged suspect list."""
    rule_hits = run_rules(bundle)
    llm_hits = run_llm(bundle, model=model) if use_llm else []
    return merge(rule_hits, llm_hits)
