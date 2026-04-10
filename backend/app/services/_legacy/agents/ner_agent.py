"""
NER Agent — Extracts medical entities from clinical notes using Gemini.
Single API call, no local models needed.
Returns structured entities with ICD-10 codes and negation status.
"""
import json
import logging
import os
import requests

from app.config import settings

logger = logging.getLogger(__name__)

_NER_PROMPT = """You are a clinical NER (Named Entity Recognition) specialist.
Extract ALL medical entities from this clinical note.

For each entity return a JSON object with these exact keys:
- "name": full entity name (e.g. "Type 2 Diabetes Mellitus with diabetic chronic kidney disease")
- "icd10": most specific ICD-10-CM code (e.g. "E11.22"), empty string if unsure
- "category": one of "disease", "symptom", "medication", "procedure", "lab"
- "confidence": 0.0 to 1.0 based on how clearly documented
- "negated": true if patient DENIES, does NOT have, or it's ruled out

IMPORTANT RULES:
1. Extract EVERY diagnosis mentioned, even if only in the Assessment/Plan
2. Use the MOST SPECIFIC ICD-10 code (E11.22 not E11.9 if CKD is documented)
3. Include ALL medications with their dosages
4. Mark negated conditions (e.g. "denies chest pain" → negated: true)
5. Do NOT skip chronic conditions just because they're stable
6. Maximum 25 entities

Return ONLY a JSON array. No explanation text.

CLINICAL NOTE:
{note}"""


def extract(clinical_note: str) -> list[dict]:
    """
    Extract medical entities from clinical note using Gemini.

    Returns list of entity dicts with: name, icd10, category, confidence, negated
    """
    api_key = settings.google_api_key or os.getenv("GOOGLE_API_KEY", "")
    model = settings.gemini_model or "gemini-2.5-pro"
    url = f"https://aiplatform.googleapis.com/v1/publishers/google/models/{model}:generateContent?key={api_key}"

    # Truncate very long notes to ~10000 chars for NER prompt
    note_text = clinical_note[:10000] if len(clinical_note) > 10000 else clinical_note
    prompt = _NER_PROMPT.format(note=note_text)

    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.1,
            "maxOutputTokens": 4096,
        },
    }

    try:
        resp = requests.post(url, json=payload, timeout=60)
        resp.raise_for_status()
        data = resp.json()

        candidates = data.get("candidates", [])
        if not candidates:
            logger.warning("[NER Agent] No candidates returned")
            return []

        raw = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")

        # Strip markdown fences
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()

        # Handle truncated JSON from Gemini
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            # Try to fix truncated JSON by closing brackets
            fixed = raw
            if not fixed.endswith("]"):
                # Find last complete JSON object
                last_brace = fixed.rfind("}")
                if last_brace > 0:
                    fixed = fixed[:last_brace + 1] + "]"
            try:
                parsed = json.loads(fixed)
            except json.JSONDecodeError:
                logger.warning("[NER Agent] Could not parse even after fix, raw length=%d", len(raw))
                parsed = []

        if not isinstance(parsed, list):
            parsed = parsed.get("entities", []) if isinstance(parsed, dict) else []

        entities = []
        for ent in parsed[:25]:
            name = ent.get("name", "")
            if not name or len(name) < 3:
                continue
            entities.append({
                "name": name,
                "icd10": ent.get("icd10", "") or "",
                "category": ent.get("category", "disease"),
                "confidence": float(ent.get("confidence", 0.85)),
                "negated": bool(ent.get("negated", False)),
                "source": "ner_agent",
            })

        logger.info("[NER Agent] Extracted %d entities from note (%d chars)", len(entities), len(clinical_note))
        return entities

    except Exception as exc:
        logger.error("[NER Agent] Failed: %s", exc)
        return []
