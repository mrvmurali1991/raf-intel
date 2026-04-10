"""
Suspect Agent — Identifies undocumented conditions from medications and labs.
"""
import json
import logging
import os
import requests
from app.config import settings

logger = logging.getLogger(__name__)

_SUSPECT_PROMPT = """You are a clinical coding gap analyst.

Given the patient's current diagnoses and medications, identify potential SUSPECT conditions:
conditions the patient likely has but are NOT yet documented/coded.

CURRENT DIAGNOSES:
{diagnoses_list}

CURRENT MEDICATIONS:
{medications_list}

Look for:
1. Medications without matching diagnoses (e.g. metformin without diabetes coded)
2. Lab values suggesting uncoded conditions
3. Related conditions commonly seen together

Return a JSON array where each element has:
- "condition": condition name
- "icd10": suggested ICD-10 code
- "confidence": 0.0-1.0
- "evidence_type": "medication" or "lab" or "clinical_pattern"
- "evidence": explanation of why this is suspected

Return empty array [] if no suspects found.

CLINICAL NOTE:
{note}"""


def detect(diagnoses: list[dict], medications: list[str], clinical_note: str) -> list[dict]:
    """Identify suspected undocumented conditions."""
    api_key = settings.google_api_key or os.getenv("GOOGLE_API_KEY", "")
    model = settings.gemini_model or "gemini-2.5-pro"
    url = f"https://aiplatform.googleapis.com/v1/publishers/google/models/{model}:generateContent?key={api_key}"

    dx_lines = [f"- {d.get('icd10','')} {d.get('name','')}" for d in diagnoses]
    med_lines = [f"- {m}" for m in medications] if medications else ["- None documented"]

    note_text = clinical_note[:8000] if len(clinical_note) > 8000 else clinical_note
    prompt = _SUSPECT_PROMPT.format(
        diagnoses_list="\n".join(dx_lines),
        medications_list="\n".join(med_lines),
        note=note_text,
    )

    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.1,
            "maxOutputTokens": 2048,
        },
    }

    try:
        resp = requests.post(url, json=payload, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        candidates = data.get("candidates", [])
        if not candidates:
            return []
        raw = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
        parsed = json.loads(raw.strip())
        if not isinstance(parsed, list):
            parsed = parsed.get("suspects", []) if isinstance(parsed, dict) else []
        logger.info("[Suspect Agent] Found %d suspect conditions", len(parsed))
        return parsed
    except Exception as exc:
        logger.error("[Suspect Agent] Failed: %s", exc)
        return []
