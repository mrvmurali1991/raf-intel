"""
MEAT Agent — Finds Monitor/Evaluate/Assess/Treat evidence for each diagnosis.
Single Gemini call that evaluates ALL diagnoses at once.
"""
import json
import logging
import os
import requests

from app.config import settings

logger = logging.getLogger(__name__)

_MEAT_PROMPT = """You are a clinical documentation specialist evaluating MEAT compliance.

For EACH diagnosis below, find evidence of MEAT in the clinical note:
- M (Monitor): Labs, vitals, imaging, follow-up orders related to this condition
- E (Evaluate): Clinical findings, exam results, test interpretations
- A (Assess): Clinical assessment, status update, staging, severity
- T (Treat): Medications, procedures, referrals, lifestyle modifications

DIAGNOSES TO EVALUATE:
{diagnoses_list}

Return a JSON array where each element has:
- "icd10": the ICD-10 code
- "description": diagnosis description
- "confidence": 0.0-1.0 how well documented this diagnosis is
- "meat": {{"M": "evidence text", "E": "evidence text", "A": "evidence text", "T": "evidence text"}}
- "meat_score": integer 0-4 (count of non-empty MEAT elements)
- "hcc_relevant": true if this is an HCC-relevant chronic condition

IMPORTANT:
1. Evaluate EVERY diagnosis, do not skip any
2. Quote specific text from the note as evidence
3. Empty string "" if no evidence found for that MEAT element
4. Be thorough — missed MEAT evidence = lost revenue

CLINICAL NOTE:
{note}"""


def evaluate(diagnoses: list[dict], clinical_note: str) -> list[dict]:
    """
    Evaluate MEAT compliance for each diagnosis.

    Args:
        diagnoses: list of dicts with at least 'name' and 'icd10'
        clinical_note: the full clinical note text

    Returns list of diagnosis dicts enriched with MEAT evidence.
    """
    if not diagnoses:
        return []

    api_key = settings.google_api_key or os.getenv("GOOGLE_API_KEY", "")
    model = settings.gemini_model or "gemini-2.5-pro"
    url = f"https://aiplatform.googleapis.com/v1/publishers/google/models/{model}:generateContent?key={api_key}"

    # Build diagnosis list for prompt
    dx_lines = []
    for i, dx in enumerate(diagnoses, 1):
        icd = dx.get("icd10", "")
        name = dx.get("name", "")
        dx_lines.append(f"{i}. {icd} - {name}")
    diagnoses_list = "\n".join(dx_lines)

    note_text = clinical_note[:12000] if len(clinical_note) > 12000 else clinical_note
    prompt = _MEAT_PROMPT.format(diagnoses_list=diagnoses_list, note=note_text)

    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.1,
            "maxOutputTokens": 8192,
        },
    }

    try:
        resp = requests.post(url, json=payload, timeout=120)
        resp.raise_for_status()
        data = resp.json()

        candidates = data.get("candidates", [])
        if not candidates:
            logger.warning("[MEAT Agent] No candidates returned")
            return diagnoses

        raw = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]

        try:
            parsed = json.loads(raw.strip())
        except json.JSONDecodeError:
            fixed = raw.strip()
            last_brace = fixed.rfind("}")
            if last_brace > 0:
                fixed = fixed[:last_brace + 1] + "]"
            try:
                parsed = json.loads(fixed)
            except json.JSONDecodeError:
                logger.warning("[MEAT Agent] JSON parse failed, raw=%d chars", len(raw))
                parsed = []
        if not isinstance(parsed, list):
            parsed = parsed.get("diagnoses", []) if isinstance(parsed, dict) else []

        logger.info("[MEAT Agent] Evaluated %d diagnoses for MEAT compliance", len(parsed))
        return parsed

    except Exception as exc:
        logger.error("[MEAT Agent] Failed: %s", exc)
        # Return original diagnoses with empty MEAT
        return [
            {**dx, "meat": {"M": "", "E": "", "A": "", "T": ""}, "meat_score": 0, "confidence": dx.get("confidence", 0.5)}
            for dx in diagnoses
        ]
