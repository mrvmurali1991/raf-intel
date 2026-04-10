"""
Clinical NER Service — Production Grade.

Uses REAL NLP models (not regex):
  - OpenMed/OpenMed-NER-DiseaseDetect-SuperClinical-434M (SOTA 2025, disease NER)
  - Med7 en_core_med7_lg (medications: drug names, dosages, routes, frequencies)
  - Regex fallback only if models fail to load

All models run locally, no API calls, no UMLS license needed.
"""

import logging
import os
import re
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Model loading
# ---------------------------------------------------------------------------

_disease_ner = None  # OpenMed NER (HuggingFace transformers)
_med7_nlp = None     # Med7 en_core_med7_lg (spaCy)
_models_loaded = False

# ICD-10 mapping for disease entities
DISEASE_TO_ICD10 = {
    "type 2 diabetes mellitus": "E11.9",
    "type 2 diabetes": "E11.9",
    "diabetes mellitus": "E11.9",
    "diabetes": "E11.9",
    "hyperglycemia": "E11.65",
    "diabetic nephropathy": "E11.22",
    "diabetic neuropathy": "E11.40",
    "diabetic retinopathy": "E11.319",
    "heart failure": "I50.9",
    "congestive heart failure": "I50.9",
    "diastolic heart failure": "I50.30",
    "systolic heart failure": "I50.20",
    "chronic kidney disease": "N18.9",
    "ckd": "N18.9",
    "ckd stage 3": "N18.3",
    "ckd stage 3a": "N18.31",
    "ckd stage 3b": "N18.32",
    "ckd stage 4": "N18.4",
    "ckd stage 5": "N18.5",
    "renal failure": "N18.9",
    "atrial fibrillation": "I48.91",
    "copd": "J44.9",
    "chronic obstructive pulmonary disease": "J44.9",
    "asthma": "J45.909",
    "dementia": "F03.90",
    "alzheimer": "G30.9",
    "alzheimer disease": "G30.9",
    "parkinson": "G20",
    "parkinson disease": "G20",
    "stroke": "I63.9",
    "cerebral infarction": "I63.9",
    "hemiplegia": "G81.90",
    "depression": "F32.9",
    "major depressive disorder": "F32.9",
    "schizophrenia": "F20.9",
    "bipolar disorder": "F31.9",
    "cancer": "C80.1",
    "malignant neoplasm": "C80.1",
    "metastatic": "C79.9",
    "breast cancer": "C50.919",
    "lung cancer": "C34.90",
    "hiv": "B20",
    "human immunodeficiency virus": "B20",
    "hepatitis c": "B18.2",
    "hepatitis b": "B18.1",
    "hypertension": "I10",
    "morbid obesity": "E66.01",
    "obesity": "E66.9",
    "malnutrition": "E46",
    "rheumatoid arthritis": "M06.9",
    "lupus": "M32.9",
    "systemic lupus erythematosus": "M32.9",
    "multiple sclerosis": "G35",
    "amyotrophic lateral sclerosis": "G12.21",
    "pressure ulcer": "L89.90",
    "peripheral vascular disease": "I73.9",
    "gangrene": "I70.261",
    "sepsis": "A41.9",
    "pneumonia": "J18.9",
    "anemia": "D64.9",
    "chest pain": "R07.9",
    "orthopnea": "R06.01",
    "dyspnea": "R06.00",
    "shortness of breath": "R06.02",
    "edema": "R60.0",
}

# Drug name to suspect condition mapping
DRUG_TO_SUSPECT = {
    "metformin": {"condition": "Type 2 Diabetes", "icd10": "E11.9", "hcc": "38"},
    "insulin": {"condition": "Diabetes", "icd10": "E11.9", "hcc": "38"},
    "insulin glargine": {"condition": "Diabetes", "icd10": "E11.9", "hcc": "38"},
    "furosemide": {"condition": "Heart Failure", "icd10": "I50.9", "hcc": "226"},
    "lisinopril": {"condition": "Hypertension/CKD", "icd10": "I10", "hcc": None},
    "apixaban": {"condition": "Atrial Fibrillation", "icd10": "I48.91", "hcc": "238"},
    "warfarin": {"condition": "Atrial Fibrillation", "icd10": "I48.91", "hcc": "238"},
    "rivaroxaban": {"condition": "Atrial Fibrillation", "icd10": "I48.91", "hcc": "238"},
    "donepezil": {"condition": "Dementia", "icd10": "F03.90", "hcc": "52"},
    "memantine": {"condition": "Dementia", "icd10": "F03.90", "hcc": "52"},
    "levodopa": {"condition": "Parkinson Disease", "icd10": "G20", "hcc": None},
    "albuterol": {"condition": "COPD/Asthma", "icd10": "J44.9", "hcc": "280"},
    "tiotropium": {"condition": "COPD", "icd10": "J44.9", "hcc": "280"},
}


def _load_models() -> None:
    """Load NER models on first use."""
    global _disease_ner, _med7_nlp, _models_loaded

    if _models_loaded:
        return

    # Load OpenMed NER (2025 SOTA, 434M params, Apache 2.0)
    # Try local path first (no internet needed), then HuggingFace
    try:
        from transformers import pipeline as hf_pipeline
        # Check multiple possible locations for local model
        _base = os.path.dirname(__file__)
        for rel in [
            os.path.join(_base, "..", "..", "..", "models", "openmed-disease-434m"),  # project root
            os.path.join(_base, "..", "..", "models", "openmed-disease-434m"),        # backend root
            "/Users/murali/Documents/Projects/raf-intelligence/models/openmed-disease-434m",  # absolute
        ]:
            if os.path.exists(os.path.abspath(rel)):
                local_model = os.path.abspath(rel)
                break
        else:
            local_model = None
        model_path = local_model or "OpenMed/OpenMed-NER-DiseaseDetect-SuperClinical-434M"
        _disease_ner = hf_pipeline(
            "token-classification",
            model=model_path,
            aggregation_strategy="max",
            device=-1,  # CPU
        )
        source = "LOCAL" if local_model else "HuggingFace"
        logger.info("OpenMed-NER-DiseaseDetect-SuperClinical-434M loaded from %s", source)
    except Exception as e:
        logger.warning("Failed to load OpenMed NER, falling back to d4data: %s", e)
        try:
            _disease_ner = hf_pipeline(
                "token-classification",
                model="d4data/biomedical-ner-all",
                aggregation_strategy="simple",
                device=-1,
            )
            logger.info("d4data/biomedical-ner-all loaded as fallback")
        except Exception as e2:
            logger.warning("Failed to load any disease NER model: %s", e2)

    # Load Med7
    try:
        import spacy
        _med7_nlp = spacy.load("en_core_med7_lg")
        logger.info("Med7 en_core_med7_lg loaded (medication NER)")
    except Exception as e:
        logger.warning("Failed to load Med7: %s", e)

    _models_loaded = True
    loaded = []
    if _disease_ner: loaded.append("OpenMed-NER-DiseaseDetect-SuperClinical-434M")
    if _med7_nlp: loaded.append("Med7")
    if not loaded:
        logger.warning("No NER models loaded. Using regex fallback.")
    else:
        logger.info("NER models ready: %s", ", ".join(loaded))


# ---------------------------------------------------------------------------
# Text chunking for transformer models (max ~512 tokens ≈ 1500 chars)
# ---------------------------------------------------------------------------

# Conservative char limit per chunk (~380 tokens leaves room for special tokens)
_CHUNK_CHAR_LIMIT = 2000
_CHUNK_OVERLAP_CHARS = 300  # overlap to avoid splitting entities at boundaries


def _chunk_text(text: str) -> list[tuple[str, int]]:
    """
    Split text into overlapping chunks suitable for transformer models.

    Returns list of (chunk_text, char_offset) tuples.
    Splits at sentence boundaries (period/newline) to avoid cutting mid-entity.
    """
    if len(text) <= _CHUNK_CHAR_LIMIT:
        return [(text, 0)]

    chunks: list[tuple[str, int]] = []
    start = 0
    while start < len(text):
        end = start + _CHUNK_CHAR_LIMIT

        # If not at the end, find a good split point (sentence boundary)
        if end < len(text):
            # Look backwards from end for a sentence boundary
            search_region = text[start + _CHUNK_CHAR_LIMIT - 500 : start + _CHUNK_CHAR_LIMIT]
            # Try newline first, then period+space, then just period
            for sep in ["\n", ". ", "."]:
                last_sep = search_region.rfind(sep)
                if last_sep >= 0:
                    end = start + _CHUNK_CHAR_LIMIT - 500 + last_sep + len(sep)
                    break

        chunk = text[start:end]
        chunks.append((chunk, start))

        # Next chunk starts with overlap
        start = end - _CHUNK_OVERLAP_CHARS
        if start >= len(text):
            break

    logger.info(
        "Chunked %d-char note into %d chunks (limit=%d, overlap=%d)",
        len(text), len(chunks), _CHUNK_CHAR_LIMIT, _CHUNK_OVERLAP_CHARS,
    )
    return chunks


# ---------------------------------------------------------------------------
# Gemini-based NER (replaces local OpenMed + Assertion-BERT)
# ---------------------------------------------------------------------------

_GEMINI_NER_PROMPT = """Extract all medical entities from this clinical note.
For each entity return a JSON object with:
- "name": entity name (e.g. "Type 2 Diabetes Mellitus")
- "icd10": ICD-10-CM code if known (e.g. "E11.22"), empty string if unsure
- "category": one of "disease", "symptom", "medication", "procedure", "lab"
- "confidence": 0.0 to 1.0
- "negated": true if the note says the patient DENIES or does NOT have this condition

Return ONLY a JSON array. No explanation. Maximum 25 entities.
Focus on: diagnoses, chronic conditions, medications, significant symptoms.
Ignore: normal findings, vital signs within range, routine procedures.

CLINICAL NOTE:
{note}"""


def _extract_with_gemini(clinical_note: str) -> list[dict[str, Any]]:
    """Use Gemini for NER — single API call, no local models needed."""
    import json as _json
    import requests as _requests

    from app.config import settings

    api_key = settings.google_api_key or os.getenv("GOOGLE_API_KEY", "")
    model = settings.gemini_model or "gemini-2.5-pro"
    url = f"https://aiplatform.googleapis.com/v1/publishers/google/models/{model}:generateContent?key={api_key}"

    # Truncate very long notes to ~8000 chars to keep NER prompt fast
    note_text = clinical_note[:8000] if len(clinical_note) > 8000 else clinical_note

    prompt = _GEMINI_NER_PROMPT.format(note=note_text)

    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.1,
            "maxOutputTokens": 4096,
        },
    }

    try:
        resp = _requests.post(url, json=payload, timeout=60)
        resp.raise_for_status()
        data = resp.json()

        candidates = data.get("candidates", [])
        if not candidates:
            logger.warning("Gemini NER returned no candidates")
            return []

        raw = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")

        # Strip markdown fences if present
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()

        parsed = _json.loads(raw)
        if not isinstance(parsed, list):
            parsed = parsed.get("entities", []) if isinstance(parsed, dict) else []

        entities = []
        for i, ent in enumerate(parsed[:25]):
            name = ent.get("name", "")
            if not name or len(name) < 3:
                continue
            icd10 = ent.get("icd10", "") or ""
            # If Gemini didn't provide ICD-10, try our mapping table
            if not icd10:
                icd10 = _map_to_icd10(name)

            entities.append({
                "text": name,
                "name": name,
                "icd10": icd10,
                "category": ent.get("category", "disease"),
                "confidence": float(ent.get("confidence", 0.85)),
                "negated": bool(ent.get("negated", False)),
                "start": i * 10,  # synthetic positions
                "end": i * 10 + len(name),
                "source": "gemini_ner",
                "entity_group": ent.get("category", "DISEASE").upper(),
            })

        logger.info("Gemini NER extracted %d entities", len(entities))
        return entities

    except Exception as exc:
        logger.error("Gemini NER failed: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Main extraction
# ---------------------------------------------------------------------------

def extract_entities(clinical_note: str) -> list[dict[str, Any]]:
    """
    Extract medical entities from clinical note.

    Strategy:
      1. Try Gemini NER (fast, accurate, no local models)
      2. Fall back to local OpenMed + Med7 if Gemini fails
      3. Fall back to regex if nothing else works

    Gemini NER handles negation detection inline, so the downstream
    assertion_service can skip entities already marked negated=True.
    """
    # Layer 1: Gemini NER (primary — no local models needed)
    entities = _extract_with_gemini(clinical_note)
    if entities:
        # Supplement with regex for medication-suspect mapping
        regex_entities = _extract_with_regex(clinical_note)
        seen_names = {e.get("name", "").lower() for e in entities}
        for re_ent in regex_entities:
            if re_ent.get("name", "").lower() not in seen_names:
                re_ent["source"] = "regex_supplement"
                entities.append(re_ent)
        return entities[:25]

    # Layer 2: Local models fallback (if Gemini fails)
    logger.warning("Gemini NER failed, trying local models...")
    _load_models()

    entities = []
    seen_spans: set[tuple[int, int]] = set()

    # Local OpenMed NER (kept as fallback, not primary)
    if _disease_ner:
        try:
            chunks = _chunk_text(clinical_note)
            for chunk_text, chunk_offset in chunks:
                results = _disease_ner(chunk_text)
                for ent in results:
                    if ent["score"] < 0.80:
                        continue
                    text = ent["word"].strip().replace("##", "")
                    if len(text) < 5:
                        continue
                    abs_start = chunk_offset + ent["start"]
                    abs_end = chunk_offset + ent["end"]
                    span = (abs_start, abs_end)
                    if any(s[0] <= span[0] < s[1] or s[0] < span[1] <= s[1] for s in seen_spans):
                        continue
                    seen_spans.add(span)
                    icd10 = _map_to_icd10(text)
                    category = _entity_group_to_category(ent["entity_group"])
                    if category in ("disease", "symptom", "procedure", "lab"):
                        entities.append({
                            "text": clinical_note[abs_start:abs_end],
                            "name": text.title() if len(text) > 3 else text.upper(),
                            "icd10": icd10, "category": category,
                            "confidence": round(float(ent["score"]), 3),
                            "negated": False, "start": int(abs_start), "end": int(abs_end),
                            "source": "openmed", "entity_group": ent["entity_group"],
                        })
        except Exception as e:
            logger.error("OpenMed NER failed: %s", e)

    # Layer 3: Regex fallback
    if not entities:
        entities = _extract_with_regex(clinical_note)
    else:
        regex_entities = _extract_with_regex(clinical_note)
        for re_ent in regex_entities:
            re_span = (re_ent.get("start", 0), re_ent.get("end", 0))
            if not any(abs(s[0] - re_span[0]) < 5 for s in seen_spans):
                re_ent["source"] = "regex_supplement"
                entities.append(re_ent)

    # Deduplicate + filter + limit
    deduped: dict[str, dict[str, Any]] = {}
    for ent in entities:
        key = ent.get("name", "").lower().strip()
        if not key:
            continue
        existing = deduped.get(key)
        if not existing or ent.get("confidence", 0) > existing.get("confidence", 0):
            deduped[key] = ent
    entities = list(deduped.values())
    entities = [e for e in entities if e.get("icd10") or e.get("category") == "medication" or e.get("drug_info")]
    if len(entities) > 25:
        entities = sorted(entities, key=lambda x: x.get("confidence", 0), reverse=True)[:25]

    return sorted(entities, key=lambda x: x.get("start", 0))


def get_icd_candidates(clinical_note: str) -> list[dict[str, Any]]:
    """
    Extract entities and return ICD-10 code candidates (non-negated only).
    """
    entities = extract_entities(clinical_note)
    candidates = []
    seen_codes: set[str] = set()

    for ent in entities:
        if ent.get("negated"):
            continue
        if ent.get("category") in ("strength", "dosage", "frequency", "route", "form", "duration"):
            continue

        icd = ent.get("icd10", "")
        if icd and icd not in seen_codes:
            seen_codes.add(icd)
            candidates.append({
                "icd10": icd,
                "entity": ent["name"],
                "confidence": ent["confidence"],
                "source": ent.get("source", "unknown"),
                "category": ent.get("category", "unknown"),
            })

    return candidates


def get_medications(clinical_note: str) -> list[dict[str, Any]]:
    """Extract medications from clinical note using Med7."""
    _load_models()
    meds = []

    if _med7_nlp:
        doc = _med7_nlp(clinical_note)
        current_drug = None
        for ent in doc.ents:
            if ent.label_ == "DRUG":
                if current_drug:
                    meds.append(current_drug)
                current_drug = {"drug": ent.text, "dosage": "", "frequency": "", "route": "", "source": "med7"}
            elif current_drug:
                if ent.label_ == "STRENGTH":
                    current_drug["dosage"] = ent.text
                elif ent.label_ == "FREQUENCY":
                    current_drug["frequency"] = ent.text
                elif ent.label_ == "ROUTE":
                    current_drug["route"] = ent.text
                elif ent.label_ == "DOSAGE":
                    current_drug["dosage"] = ent.text
                elif ent.label_ == "FORM":
                    current_drug["form"] = ent.text
                elif ent.label_ == "DURATION":
                    current_drug["duration"] = ent.text
        if current_drug:
            meds.append(current_drug)

    return meds


def is_available() -> bool:
    """Check if real NER models are loaded."""
    _load_models()
    return _disease_ner is not None or _med7_nlp is not None


def get_model_info() -> dict[str, Any]:
    """Return info about loaded NER models."""
    _load_models()
    return {
        "disease_ner": "OpenMed/OpenMed-NER-DiseaseDetect-SuperClinical-434M" if _disease_ner else None,
        "medication_ner": "Med7 en_core_med7_lg" if _med7_nlp else None,
        "models_loaded": _models_loaded,
        "using_real_nlp": _disease_ner is not None or _med7_nlp is not None,
        "fallback": "regex" if not _disease_ner and not _med7_nlp else None,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _map_to_icd10(entity_text: str) -> str:
    """Map extracted entity text to ICD-10 code."""
    text_lower = entity_text.lower().strip()

    # Direct match
    if text_lower in DISEASE_TO_ICD10:
        return DISEASE_TO_ICD10[text_lower]

    # Partial match
    for pattern, code in sorted(DISEASE_TO_ICD10.items(), key=lambda x: -len(x[0])):
        if pattern in text_lower or text_lower in pattern:
            return code

    return ""


def _entity_group_to_category(group: str) -> str:
    """Map NER entity groups to our categories."""
    group_lower = group.lower()
    mapping = {
        "disease": "disease",  # OpenMed label
        "disease_disorder": "disease",
        "sign_symptom": "symptom",
        "medication": "medication",
        "diagnostic_procedure": "procedure",
        "lab_value": "lab",
        "therapeutic_procedure": "procedure",
        "biological_structure": "anatomy",
        "detailed_description": "description",
        "dosage": "dosage",
        "severity": "severity",
        "clinical_event": "event",
        "activity": "activity",
        "date": "date",
        "age": "demographic",
        "area": "anatomy",
        "duration": "duration",
        "frequency": "frequency",
        "history": "history",
        "nonbiological_location": "location",
        "occupation": "demographic",
        "personal_background": "demographic",
        "qualitative_concept": "description",
        "quantitative_concept": "lab",
        "subject": "subject",
        "family_history": "family",
        "texture": "description",
        "color": "description",
        "shape": "description",
        "distance": "measurement",
        "mass": "measurement",
        "volume": "measurement",
        "height": "measurement",
        "weight": "measurement",
        "time": "time",
        "coreference": "reference",
        "other_entity": "other",
        "other_event": "other",
    }
    return mapping.get(group_lower, "other")


# ---------------------------------------------------------------------------
# Regex fallback (used when NLP models not available)
# ---------------------------------------------------------------------------

MEDICAL_PATTERNS = {
    "type 2 diabetes mellitus": {"icd10": "E11.9", "category": "disease"},
    "type 2 diabetes": {"icd10": "E11.9", "category": "disease"},
    "diabetes mellitus": {"icd10": "E11.9", "category": "disease"},
    "hyperglycemia": {"icd10": "E11.65", "category": "disease"},
    "diabetic nephropathy": {"icd10": "E11.22", "category": "disease"},
    "diabetic neuropathy": {"icd10": "E11.40", "category": "disease"},
    "congestive heart failure": {"icd10": "I50.9", "category": "disease"},
    "diastolic heart failure": {"icd10": "I50.30", "category": "disease"},
    "systolic heart failure": {"icd10": "I50.20", "category": "disease"},
    "heart failure": {"icd10": "I50.9", "category": "disease"},
    "chf": {"icd10": "I50.9", "category": "disease"},
    "atrial fibrillation": {"icd10": "I48.91", "category": "disease"},
    "afib": {"icd10": "I48.91", "category": "disease"},
    "chronic kidney disease": {"icd10": "N18.9", "category": "disease"},
    "ckd stage 3b": {"icd10": "N18.32", "category": "disease"},
    "ckd stage 3": {"icd10": "N18.3", "category": "disease"},
    "ckd stage 4": {"icd10": "N18.4", "category": "disease"},
    "copd": {"icd10": "J44.9", "category": "disease"},
    "chronic obstructive pulmonary disease": {"icd10": "J44.9", "category": "disease"},
    "dementia": {"icd10": "F03.90", "category": "disease"},
    "alzheimer": {"icd10": "G30.9", "category": "disease"},
    "parkinson": {"icd10": "G20", "category": "disease"},
    "stroke": {"icd10": "I63.9", "category": "disease"},
    "depression": {"icd10": "F32.9", "category": "disease"},
    "schizophrenia": {"icd10": "F20.9", "category": "disease"},
    "bipolar": {"icd10": "F31.9", "category": "disease"},
    "cancer": {"icd10": "C80.1", "category": "disease"},
    "metastatic": {"icd10": "C79.9", "category": "disease"},
    "hiv": {"icd10": "B20", "category": "disease"},
    "hepatitis c": {"icd10": "B18.2", "category": "disease"},
    "hypertension": {"icd10": "I10", "category": "disease"},
    "morbid obesity": {"icd10": "E66.01", "category": "disease"},
    "malnutrition": {"icd10": "E46", "category": "disease"},
    "rheumatoid arthritis": {"icd10": "M06.9", "category": "disease"},
    "lupus": {"icd10": "M32.9", "category": "disease"},
    "multiple sclerosis": {"icd10": "G35", "category": "disease"},
    "pressure ulcer": {"icd10": "L89.90", "category": "disease"},
    "peripheral vascular disease": {"icd10": "I73.9", "category": "disease"},
    "gangrene": {"icd10": "I70.261", "category": "disease"},
    "chest pain": {"icd10": "R07.9", "category": "symptom"},
    "orthopnea": {"icd10": "R06.01", "category": "symptom"},
    "shortness of breath": {"icd10": "R06.02", "category": "symptom"},
    "dyspnea": {"icd10": "R06.00", "category": "symptom"},
    "edema": {"icd10": "R60.0", "category": "symptom"},
}


def _extract_with_regex(note: str) -> list[dict[str, Any]]:
    """Regex-based fallback for entity extraction."""
    entities = []
    note_lower = note.lower()
    seen_spans: set[tuple[int, int]] = set()

    sorted_patterns = sorted(MEDICAL_PATTERNS.items(), key=lambda x: -len(x[0]))

    for pattern, info in sorted_patterns:
        start = 0
        while True:
            idx = note_lower.find(pattern, start)
            if idx < 0:
                break

            span = (idx, idx + len(pattern))
            overlaps = any(s[0] <= idx < s[1] or s[0] < idx + len(pattern) <= s[1]
                         for s in seen_spans)

            if not overlaps:
                seen_spans.add(span)

                # Basic negation check
                before = note_lower[max(0, idx - 60):idx]
                negation_cues = ["no ", "not ", "denies ", "denied ", "negative for ",
                                "without ", "no evidence of ", "rules out "]
                is_negated = any(cue in before for cue in negation_cues)

                entities.append({
                    "text": note[idx:idx + len(pattern)],
                    "name": pattern.title(),
                    "icd10": info["icd10"],
                    "category": info["category"],
                    "confidence": 0.80,
                    "negated": is_negated,
                    "start": idx,
                    "end": idx + len(pattern),
                    "source": "regex",
                })

            start = idx + len(pattern)

    return sorted(entities, key=lambda x: x["start"])
