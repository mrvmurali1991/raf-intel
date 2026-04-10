"""
Gemini 2.5 Pro clinical note analysis service — full pipeline edition.

Pipeline
--------
Raw clinical note
  → MedCAT entity extraction         (medcat_service.extract_entities)
  → Assertion / negation filter       (assertion_service.filter_negated_entities)
  → Retrieve-Rank ICD candidates      (retrieve_rank_service.get_candidates)
  → Gemini selection + MEAT + suspects

Gemini's job is NOT to hallucinate codes.  It receives:
  - Structured entity list from MedCAT (with assertion status)
  - A ranked list of valid ICD-10-CM leaf codes from Retrieve-Rank
  - Patient demographics, medications, labs
  - 20 few-shot examples covering common HCC conditions

Gemini then:
  1. Selects the single best code for each active condition FROM the candidates.
  2. Extracts verbatim MEAT evidence for each selected code.
  3. Identifies suspect conditions implied by medications / labs.

Public API
----------
analyze_clinical_note(note_text, patient_age, patient_sex,
                       medications, lab_results, existing_hccs)
    -> dict          Full pipeline analysis with enriched results.

extract_meat_evidence(note_text, diagnosis, icd10_code)
    -> dict          Focused MEAT extraction for one diagnosis.

suggest_icd10_codes(clinical_text)
    -> list[dict]    Top-5 ICD-10-CM suggestions from free text.

validate_coding_with_tree_search(note_text, initial_codes)
    -> list[dict]    ICD tree-search validation; refines non-leaf codes.

batch_analyze(encounters_list)
    -> list[dict]    Process multiple encounters sequentially.

Design decisions
----------------
* Module-level singleton Gemini client — one HTTP connection pool.
* All Gemini calls go through _call_gemini() which handles:
    - JSON fence stripping
    - Exponential-backoff retry (up to MAX_RETRIES)
    - Structured logging with token usage
    - Graceful fallback on malformed JSON
* response_mime_type="application/json" on every call for valid JSON output.
* temperature=0.1 throughout — medical coding requires deterministic output.
* Thinking disabled (budget_tokens=0) for latency; enable per-call for
  complex differential diagnoses.
* The .env is loaded from /Users/murali/Documents/Projects/raf-intelligence/.env
  via app.config.settings (which calls load_dotenv at import time).
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

from google import genai
from google.genai import types

from app.config import settings
from app.services._legacy.assertion_service import filter_negated_entities
from app.services.icd_validator import (
    get_children_with_descriptions,
    get_description,
    get_hcc_mapping,
    normalize_code,
    validate_icd10_code,
)
from app.services._legacy.medcat_service import extract_entities
from app.services._legacy.retrieve_rank_service import retrieve_and_rank

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_RETRIES = 3
RETRY_BASE_DELAY = 2.0          # seconds; doubles on each retry
MAX_OUTPUT_TOKENS = 8192
TREE_SEARCH_MAX_DEPTH = 4
BATCH_DELAY_SECONDS = 0.5

# Confidence thresholds for routing
_THRESHOLD_AUTO_ACCEPT = 0.90
_THRESHOLD_HUMAN_REVIEW = 0.70

# ---------------------------------------------------------------------------
# Gemini client (module-level singleton)
# ---------------------------------------------------------------------------

_api_key: str = ""

VERTEX_BASE = "https://aiplatform.googleapis.com/v1/publishers/google/models"


def _get_api_key() -> str:
    """Return the API key."""
    global _api_key
    if not _api_key:
        _api_key = settings.google_api_key or os.getenv("GOOGLE_API_KEY", "")
        if not _api_key:
            raise RuntimeError(
                "GOOGLE_API_KEY is not configured. "
                "Set it in the .env file or as an environment variable."
            )
        logger.info("Gemini API key loaded (model=%s)", settings.gemini_model)
    return _api_key


# ---------------------------------------------------------------------------
# Low-level call wrapper — uses Vertex AI REST API directly
# ---------------------------------------------------------------------------

def _call_gemini(
    prompt: str,
    *,
    system_instruction: str | None = None,
    temperature: float = 0.1,
    max_output_tokens: int = MAX_OUTPUT_TOKENS,
    model: str | None = None,
) -> dict[str, Any] | list[Any]:
    """Call Gemini via Vertex AI REST API and return parsed JSON.

    Implements exponential-backoff retry on transient API errors.
    Strips markdown code fences if the model ignores the mime-type instruction.
    """
    import requests as _requests

    api_key = _get_api_key()
    target_model = model or settings.gemini_model
    url = f"{VERTEX_BASE}/{target_model}:generateContent?key={api_key}"

    # Build request payload
    contents = [{"role": "user", "parts": [{"text": prompt}]}]
    if system_instruction:
        contents.insert(0, {"role": "user", "parts": [{"text": f"[SYSTEM INSTRUCTION]: {system_instruction}"}]})

    payload: dict[str, Any] = {
        "contents": contents,
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": temperature,
            "maxOutputTokens": max_output_tokens,
        },
    }

    last_exc: Exception | None = None
    raw = ""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = _requests.post(url, json=payload, timeout=120)
            resp.raise_for_status()
            data = resp.json()

            # Extract text from response
            candidates = data.get("candidates", [])
            if candidates:
                parts = candidates[0].get("content", {}).get("parts", [])
                raw = parts[0].get("text", "") if parts else ""
            else:
                raw = ""

            # Log usage
            usage = data.get("usageMetadata", {})
            if usage:
                logger.debug(
                    "Gemini tokens — prompt: %s, candidates: %s, total: %s",
                    usage.get("promptTokenCount", 0),
                    usage.get("candidatesTokenCount", 0),
                    usage.get("totalTokenCount", 0),
                )

            raw = raw.strip()

            # Strip markdown fences
            if raw.startswith("```"):
                lines = raw.splitlines()
                inner = lines[1:] if lines[0].startswith("```") else lines
                if inner and inner[-1].strip() == "```":
                    inner = inner[:-1]
                raw = "\n".join(inner).strip()

            parsed = json.loads(raw)
            return parsed  # type: ignore[return-value]

        except json.JSONDecodeError as exc:
            logger.error(
                "Gemini JSON parse failure (attempt %d/%d): %s\nRaw: %.500s",
                attempt, MAX_RETRIES, exc, raw,
            )
            last_exc = exc
            break  # JSON errors are not transient

        except Exception as exc:
            last_exc = exc
            if attempt < MAX_RETRIES:
                delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
                logger.warning(
                    "Gemini API error (attempt %d/%d), retrying in %.1fs: %s",
                    attempt, MAX_RETRIES, delay, exc,
                )
                time.sleep(delay)
            else:
                logger.error(
                    "Gemini API failed after %d attempts: %s", MAX_RETRIES, exc
                )

    raise RuntimeError(f"Gemini call failed: {last_exc}") from last_exc


# ---------------------------------------------------------------------------
# Few-shot examples (20 examples covering common HCC conditions)
# ---------------------------------------------------------------------------

_FEW_SHOT_EXAMPLES = """\
═══════════════════════════════════════════════════════════════
 20 FEW-SHOT EXAMPLES — CMS-HCC V28 CODING
 Study these carefully before coding the note below.
═══════════════════════════════════════════════════════════════

── EXAMPLE 1: Diabetes with CKD (E11.22 + N18.3) ──────────────
Note: "55M with T2DM, A1c 8.1%, eGFR 42 (CKD Stage 3), on
      metformin 1000mg BID and lisinopril 10mg daily."
Coding:
  E11.22  Type 2 diabetes with diabetic CKD (NOT E11 or E11.2)
  N18.3   CKD Stage 3 (eGFR 42 confirms Stage 3a/3b)
MEAT for E11.22:
  Monitor: A1c 8.1% ordered/reviewed
  Evaluate: eGFR 42 documents kidney involvement
  Assess: "T2DM with CKD Stage 3" in assessment
  Treat: metformin 1000mg BID, lisinopril 10mg
HCC: E11.22 → HCC37 (Diabetes with Chronic Complications)
     N18.3  → HCC329

── EXAMPLE 2: Diabetes with Hyperglycemia (E11.65) ────────────
Note: "T2DM, blood glucose 312 today, patient poorly compliant
      with insulin. Increase glargine to 30 units nightly."
Coding:
  E11.65  Type 2 diabetes with hyperglycemia (glucose 312 is
          the specificity determinant; NOT E11.9)
MEAT for E11.65:
  Monitor: blood glucose 312 documented
  Evaluate: compliance assessed
  Assess: hyperglycemia in assessment
  Treat: glargine dose increased to 30 units
HCC: E11.65 → HCC37

── EXAMPLE 3: CHF Unspecified Systolic + Acute Exacerbation ──
Note: "65F with systolic CHF, EF 35%, presenting with worsening
      dyspnea, 2+ pitting edema. BNP 1240. Admitted for IV
      diuresis with furosemide."
Coding:
  I50.20  Unspecified systolic (congestive) heart failure
          (EF 35% is systolic; no acute/chronic specified → use .20)
  E87.70  Fluid overload (BNP 1240, edema)
MEAT for I50.20:
  Monitor: BNP 1240, daily weights ordered
  Evaluate: dyspnea, 2+ pitting edema on exam; EF 35% on echo
  Assess: "systolic CHF exacerbation" in assessment
  Treat: IV furosemide for diuresis
HCC: I50.20 → HCC85

── EXAMPLE 4: CHF Chronic Systolic ───────────────────────────
Note: "Known chronic systolic CHF, EF 30-35%, on carvedilol,
      lisinopril, and spironolactone. Stable, no acute symptoms."
Coding:
  I50.22  Chronic systolic (congestive) heart failure
          (chronic — NOT I50.20 unspecified)
HCC: I50.22 → HCC85

── EXAMPLE 5: CKD Stage 4 (N18.4) ────────────────────────────
Note: "CKD Stage 4, eGFR 22. Nephrology f/u in 3 months.
      Dietary phosphate restriction counselled. Considering
      AV fistula creation for anticipated HD."
Coding:
  N18.4   CKD Stage 4 (eGFR 22 confirms)
MEAT for N18.4:
  Monitor: eGFR 22 reviewed
  Evaluate: nephrology referral for specialist evaluation
  Assess: Stage 4 documented explicitly
  Treat: dietary restriction + AV fistula planning
HCC: N18.4 → HCC329

── EXAMPLE 6: COPD Exacerbation (J44.1) ──────────────────────
Note: "COPD exacerbation. Patient presents with worsening
      cough, increased sputum, FEV1 45% predicted. Started
      prednisone 40mg and azithromycin 500mg."
Coding:
  J44.1   COPD with (acute) exacerbation — NOT J44.9
          (exacerbation explicitly documented)
MEAT for J44.1:
  Monitor: FEV1 45% predicted
  Evaluate: worsening cough, increased sputum
  Assess: COPD exacerbation in assessment
  Treat: prednisone 40mg + azithromycin 500mg
HCC: J44.1 → HCC280

── EXAMPLE 7: COPD Stable (J44.9) ───────────────────────────
Note: "COPD, stable on tiotropium and albuterol PRN. Last
      spirometry: FEV1/FVC 0.58. No acute symptoms."
Coding:
  J44.9   COPD unspecified (no exacerbation documented)
HCC: J44.9 → HCC280

── EXAMPLE 8: Dementia (F03.90 + G30.1) ──────────────────────
Note: "78M with Alzheimer's disease, moderate stage, on
      donepezil 10mg. Caregiver reports increasing confusion
      and wandering. MMSE 16/30."
Coding:
  G30.1   Alzheimer's disease with late onset (age 78 → late onset)
  F03.90  Unspecified dementia without behavioral disturbance
          (Alzheimer's codes with G30.x + F02.xx/F03.xx combo)
MEAT for G30.1:
  Monitor: MMSE 16/30 documents severity
  Evaluate: caregiver report of confusion and wandering
  Assess: "moderate Alzheimer's" in assessment
  Treat: donepezil 10mg
HCC: F03.90 → HCC52

── EXAMPLE 9: Cancer — Breast + Bone Metastasis ──────────────
Note: "C50.912 known invasive ductal carcinoma right breast,
      status post mastectomy. Bone scan positive for osseous
      metastases T4 and L2. Starting zoledronic acid."
Coding:
  C50.911  Malignant neoplasm of unspecified site of right female breast
  C79.51   Secondary malignant neoplasm of bone
           (metastases = secondary; T4/L2 osseous = bone)
MEAT for C79.51:
  Monitor: bone scan reviewed
  Evaluate: positive scan T4, L2
  Assess: osseous metastases documented
  Treat: zoledronic acid initiated
HCC: C50.911 → HCC12; C79.51 → HCC11

── EXAMPLE 10: Atrial Fibrillation (I48.91) ──────────────────
Note: "Persistent AFib, rate controlled on metoprolol 50mg BID
      and apixaban 5mg BID. Heart rate 78 bpm at visit."
Coding:
  I48.11  Longstanding persistent atrial fibrillation
          (OR I48.91 unspecified if duration unclear)
  NOTE: Use I48.11 when 'persistent' is clearly documented
MEAT for I48.11:
  Monitor: heart rate 78 bpm
  Evaluate: rate-controlled status
  Assess: persistent AFib in assessment
  Treat: metoprolol + apixaban
HCC: I48.11 → HCC226

── EXAMPLE 11: Depression — Moderate (F32.1) ─────────────────
Note: "Major depressive disorder, moderate severity. PHQ-9
      score 14. Continuing sertraline 100mg. Referred to
      psychotherapy."
Coding:
  F32.1   Major depressive disorder, single episode, moderate
          (PHQ-9 14 = moderate; single episode unless recurrent stated)
MEAT for F32.1:
  Monitor: PHQ-9 14 scored
  Evaluate: severity assessment moderate
  Assess: MDD moderate documented
  Treat: sertraline 100mg + psychotherapy referral
HCC: F32.1 → HCC155

── EXAMPLE 12: Recurrent Depression (F33.1) ─────────────────
Note: "Recurrent MDD, moderate episode. Second episode this
      year. PHQ-9 12. Adjusted escitalopram to 20mg."
Coding:
  F33.1   MDD recurrent, moderate (recurrent explicitly stated)
          NOT F32.x — use F33 series for recurrent episodes
HCC: F33.1 → HCC155

── EXAMPLE 13: Parkinson's Disease (G20) ─────────────────────
Note: "Parkinson's disease. Tremor well-controlled on
      carbidopa-levodopa 25-100mg TID. Gait assessment stable.
      DBS not yet warranted."
Coding:
  G20     Parkinson's disease (no further specificity in ICD-10-CM)
MEAT for G20:
  Monitor: gait assessment stable
  Evaluate: tremor assessment
  Assess: Parkinson's disease in assessment
  Treat: carbidopa-levodopa TID, DBS considered
HCC: G20 → HCC173

── EXAMPLE 14: HIV (B20) ─────────────────────────────────────
Note: "HIV, CD4 count 620, viral load undetectable. Continuing
      bictegravir/emtricitabine/TAF (Biktarvy)."
Coding:
  B20     HIV disease (use B20 when HIV is active/on treatment;
          Z21 only when asymptomatic and not on treatment)
MEAT for B20:
  Monitor: CD4 620, viral load undetectable
  Evaluate: lab results reviewed
  Assess: HIV controlled, documented
  Treat: Biktarvy continued
HCC: B20 → HCC1

── EXAMPLE 15: NEGATION — Do NOT code ───────────────────────
Note: "Patient denies chest pain. No evidence of CHF.
      Cardiac exam unremarkable. EKG normal."
Coding: NONE of these should be coded.
  'chest pain'   → negated ("denies") → negated_conditions list
  'CHF'          → negated ("no evidence of") → negated_conditions list
  'EKG normal'   → normal finding, not a diagnosis
Lesson: Negated and normal findings are NEVER coded as diagnoses.

── EXAMPLE 16: HISTORICAL — Context Matters ──────────────────
Note: "PMH: stroke 3 years ago, no residual deficits.
      Currently presents for hypertension management.
      BP 148/92 today."
Coding:
  I10     Hypertension (current, being addressed today)
  Z86.73  Personal history of TIA and cerebral infarction
          (historical stroke, no current deficit → Z86.73 NOT I63)
  NOT coded: I63 (stroke is historical, no current deficit documented)

── EXAMPLE 17: SUSPECT — On insulin but no diabetes coded ────
Note: "Medications: insulin glargine 20 units nightly, aspirin
      81mg. No other diagnoses documented."
Coding: No confirmed diagnoses to code.
Suspect:
  E11.9   Type 2 Diabetes Mellitus (highly likely given insulin glargine)
          evidence_type: medication
          evidence: "insulin glargine 20 units nightly"
          confidence: 0.92
Lesson: Long-acting insulin without a diabetes diagnosis = strong suspect.

── EXAMPLE 18: MEAT COMPLETE ─────────────────────────────────
Note: "HTN well-controlled. BP 128/78 on lisinopril 10mg.
      Labs: BMP WNL. Continue current regimen. Discussed
      salt restriction and exercise."
Coding:
  I10     Essential (primary) hypertension
MEAT for I10 (ALL FOUR present):
  Monitor:    BP 128/78 today; BMP WNL (electrolyte monitoring)
  Evaluate:   BP response to treatment evaluated as "well-controlled"
  Assess:     "HTN well-controlled" in assessment
  Treat:      lisinopril 10mg; salt restriction; exercise counselling
meat_score: 4/4 — optimal documentation

── EXAMPLE 19: MEAT INCOMPLETE ──────────────────────────────
Note: "Past medical history includes Type 2 diabetes."
Coding:
  E11.9   Type 2 DM (PMH — historical flag: true)
MEAT for E11.9 (ZERO present):
  Monitor:    "" (no monitoring documented)
  Evaluate:   "" (no evaluation)
  Assess:     "" (mentioned in PMH only, not in today's assessment)
  Treat:      "" (no treatment listed)
meat_score: 0/4 — insufficient for HCC capture
Documentation gap: Condition only in PMH; no current MEAT evidence.
                   Physician should address DM in today's assessment
                   and document monitoring/treatment.

── EXAMPLE 20: COMPLEX MIXED CASE ──────────────────────────
Note: "72F with T2DM (A1c 9.2%, insulin-dependent), CKD Stage
      3b (eGFR 38), CHF chronic systolic EF 28%, COPD stable.
      Medications: insulin detemir 30u, furosemide 40mg,
      carvedilol 12.5mg, tiotropium. Presents for routine follow-up.
      BP 134/80, HR 72. Pedal edema 1+. Labs: BMP ordered."
Coding:
  E11.65  T2DM with hyperglycemia (A1c 9.2% = hyperglycemia)
  N18.32  CKD Stage 3b (eGFR 38 is 3b range 30-44)
  I50.22  Chronic systolic CHF (EF 28%, explicitly chronic)
  J44.9   COPD without exacerbation (stable, no acute exacerbation)
MEAT for E11.65:
  Monitor: A1c 9.2%, BMP ordered
  Evaluate: lab results reviewed
  Assess: T2DM with hyperglycemia documented
  Treat: insulin detemir 30u
No suspects (all conditions documented).
HCCs: HCC37, HCC329, HCC85, HCC280 — all captured.

═══════════════════════════════════════════════════════════════
 END OF FEW-SHOT EXAMPLES
═══════════════════════════════════════════════════════════════
"""

# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

_SYSTEM_ANALYZE = (
    """\
You are an expert CMS-HCC Version 28 medical coder and clinical documentation
specialist performing RAF (Risk Adjustment Factor) analysis.

CRITICAL RULE — CODE SELECTION:
You will receive a list of CANDIDATE ICD-10-CM codes derived from the clinical
note by the NLP pipeline.  You MUST select codes ONLY from these candidates.
Do NOT invent or hallucinate codes outside the candidate list.  If no candidate
is appropriate, omit that diagnosis.

CODING RULES YOU MUST FOLLOW:
1. Code to the HIGHEST SPECIFICITY available in the candidates.
   Never use a category code (e.g. E11) when a more specific leaf is offered
   (e.g. E11.22).
2. Detect NEGATED conditions.  Phrases such as "denies", "no evidence of",
   "ruled out", "not present", "negative for" indicate negation.
   Mark these in negated_conditions; do NOT include in diagnoses.
3. Distinguish ACTIVE vs HISTORICAL.  Past Medical History (PMH) items not
   addressed in today's note are historical (historical: true).
4. Apply MEAT criteria strictly:
   - Monitor   : lab orders, vitals tracking, imaging follow-up
   - Evaluate  : physical exam findings, specialist referrals, test results
   - Assess    : documented assessment, clinical reasoning, problem list entry
   - Treat     : medications, procedures, counselling, diet changes
5. Flag SUSPECT CONDITIONS when:
   - A medication strongly implies an undocumented diagnosis
     (e.g. furosemide without CHF/oedema diagnosis)
   - An abnormal lab value implies an undocumented diagnosis
     (e.g. eGFR < 60 without CKD; A1c > 7 without diabetes)
6. Output ONLY the JSON structure specified below.  No prose outside JSON.
"""
    + _FEW_SHOT_EXAMPLES
    + """
OUTPUT JSON SCHEMA (return exactly this structure; arrays may be empty):
{
  "diagnoses": [
    {
      "condition": "<clinical condition name>",
      "icd10_code": "<most specific ICD-10-CM code from candidates, e.g. E11.22>",
      "icd10_description": "<official description of that code>",
      "hcc_code": "<e.g. HCC37 or null if not HCC-mapped>",
      "confidence": <0.0-1.0>,
      "negated": false,
      "historical": <true|false>,
      "family_history": false,
      "meat": {
        "monitoring": "<verbatim monitoring evidence from note or empty string>",
        "evaluation": "<verbatim evaluation evidence or empty string>",
        "assessment": "<verbatim assessment text or empty string>",
        "treatment": "<verbatim treatment evidence or empty string>"
      },
      "meat_score": <0-4>,
      "supporting_text": "<exact quote from note>"
    }
  ],
  "suspect_conditions": [
    {
      "condition": "<suspected condition name>",
      "evidence": "<why this is suspected>",
      "evidence_type": "<medication|lab|pattern>",
      "suspect_icd10": "<suggested ICD-10-CM code>",
      "suspect_hcc": "<e.g. HCC85 or null>",
      "confidence": <0.0-1.0>
    }
  ],
  "negated_conditions": ["<condition name>"],
  "coding_notes": "<observations about documentation gaps or opportunities>"
}\
"""
)

_SYSTEM_MEAT = """\
You are an expert clinical documentation specialist.  Extract MEAT evidence
(Monitor, Evaluate, Assess, Treat) for the specific diagnosis supplied.

Return ONLY this JSON — no prose:
{
  "diagnosis": "<condition name>",
  "icd10_code": "<code>",
  "meat": {
    "monitoring": "<verbatim text from note showing monitoring, or empty string>",
    "evaluation": "<verbatim text showing evaluation/testing, or empty string>",
    "assessment": "<verbatim text showing clinical assessment, or empty string>",
    "treatment": "<verbatim text showing active treatment, or empty string>"
  },
  "meat_present": {
    "monitoring": <true|false>,
    "evaluation": <true|false>,
    "assessment": <true|false>,
    "treatment": <true|false>
  },
  "meat_score": <0-4>,
  "sufficient_for_hcc": <true if meat_score >= 1>,
  "documentation_gap": "<plain-English note on what MEAT evidence is missing>"
}\
"""

_SYSTEM_ICD_SUGGEST = """\
You are a certified medical coder.  Given the clinical text, suggest the
five most appropriate ICD-10-CM codes.

Return ONLY this JSON array — no prose:
[
  {
    "icd10_code": "<code with dot, e.g. J18.9>",
    "description": "<official code description>",
    "confidence": <0.0-1.0>,
    "rationale": "<one sentence explaining the suggestion>"
  }
]\
"""

_SYSTEM_TREE_PICK = """\
You are a CMS-HCC V28 medical coder.  Given a clinical note and a list of
ICD-10-CM child codes (with descriptions), select the single most appropriate
child code that best matches the clinical documentation.

Return ONLY this JSON object — no prose:
{
  "selected_code": "<ICD-10-CM code>",
  "description": "<code description>",
  "rationale": "<one sentence>"
}\
"""


# ---------------------------------------------------------------------------
# 1. analyze_clinical_note  — FULL PIPELINE
# ---------------------------------------------------------------------------

def analyze_clinical_note(
    note_text: str,
    patient_age: int | None = None,
    patient_sex: str | None = None,
    medications: list[str] | None = None,
    lab_results: list[dict[str, Any]] | None = None,
    existing_hccs: list[str] | None = None,
) -> dict[str, Any]:
    """Perform a comprehensive CMS-HCC V28 analysis of a clinical note.

    Runs the full pipeline:
      note → MedCAT → assertion filter → retrieve-rank → Gemini

    Parameters
    ----------
    note_text:
        Raw clinical note text (SOAP note, progress note, discharge summary).
    patient_age:
        Patient's age in years.
    patient_sex:
        ``"M"`` / ``"Male"`` / ``"F"`` / ``"Female"``.
    medications:
        List of active medication names for suspect-condition detection.
    lab_results:
        List of ``{name, value, units, abnormal: bool}`` dicts.
    existing_hccs:
        HCC codes already captured for this patient/year.

    Returns
    -------
    dict with keys:
        ``pipeline_stages``, ``diagnoses``, ``suspect_conditions``,
        ``negated_conditions``, ``coding_notes``, ``confidence_routing``,
        ``overall_confidence``, ``_meta``

    On error the returned dict contains an ``error`` key and empty arrays.
    """
    if not note_text or not note_text.strip():
        return _empty_analysis(error="note_text is empty")

    # ------------------------------------------------------------------
    # Stage 1 — MedCAT entity extraction
    # ------------------------------------------------------------------
    try:
        raw_entities: list[dict[str, Any]] = extract_entities(note_text)
    except Exception as exc:
        logger.error("MedCAT extraction failed: %s", exc)
        raw_entities = []

    logger.info("Pipeline stage 1: %d entities extracted by MedCAT", len(raw_entities))

    # ------------------------------------------------------------------
    # Stage 2 — Assertion / negation filtering
    # ------------------------------------------------------------------
    try:
        present_entities: list[dict[str, Any]] = filter_negated_entities(
            raw_entities, note_text
        )
    except Exception as exc:
        logger.error("Assertion filter failed: %s", exc)
        present_entities = raw_entities  # fallback: use all entities

    negated_from_pipeline = [
        e.get("name") or e.get("text", "")
        for e in raw_entities
        if e not in present_entities
    ]
    logger.info(
        "Pipeline stage 2: %d entities after negation filter (%d negated)",
        len(present_entities),
        len(raw_entities) - len(present_entities),
    )

    # ------------------------------------------------------------------
    # Stage 3 — Retrieve-Rank ICD candidates
    # retrieve_and_rank returns entities enriched with a `candidates` key.
    # We flatten those into a deduplicated list for the Gemini prompt.
    # ------------------------------------------------------------------
    try:
        enriched_entities: list[dict[str, Any]] = retrieve_and_rank(
            present_entities, clinical_note=note_text
        )
    except Exception as exc:
        logger.error("Retrieve-rank failed: %s", exc)
        enriched_entities = present_entities

    # Flatten and deduplicate candidates across all entities
    _seen_cands: set[str] = set()
    candidate_codes: list[dict[str, Any]] = []
    for ent in enriched_entities:
        entity_name = ent.get("name") or ent.get("text") or ""
        for cand in ent.get("candidates", []):
            code = cand.get("code", "")
            if code and code not in _seen_cands:
                _seen_cands.add(code)
                candidate_codes.append(
                    {
                        "icd10_code": code,
                        "description": cand.get("description", ""),
                        "retrieval_score": cand.get("relevance_score", 0.0),
                        "entity_source": entity_name,
                        "hcc_code": None,  # enriched below
                        "hcc_mapping": None,
                    }
                )

    # Attach HCC mappings to flattened candidates
    for cand in candidate_codes:
        mapping = get_hcc_mapping(cand["icd10_code"])
        cand["hcc_mapping"] = mapping
        cand["hcc_code"] = mapping.get("hcc_code") if mapping else None

    logger.info("Pipeline stage 3: %d ICD candidates from retrieve-rank", len(candidate_codes))

    # Summarize NER findings for concise prompt (reduces tokens 10x)
    if present_entities and len(present_entities) > 10:
        # Only include unique entities with ICD-10 codes
        seen: set[str] = set()
        summary_entities: list[dict[str, Any]] = []
        for e in present_entities:
            key = e.get("icd10", "") or e.get("name", "")
            if key and key not in seen:
                seen.add(key)
                summary_entities.append(e)
        present_entities = summary_entities[:20]  # Cap at 20

    # Limit candidate codes to top 50 by retrieval score
    if len(candidate_codes) > 50:
        candidate_codes.sort(key=lambda c: c.get("retrieval_score", 0.0), reverse=True)
        candidate_codes = candidate_codes[:50]

    # ------------------------------------------------------------------
    # Stage 4 — Build Gemini prompt
    # ------------------------------------------------------------------
    context_lines: list[str] = []

    if patient_age is not None or patient_sex:
        demo = []
        if patient_age is not None:
            demo.append(f"Age: {patient_age}")
        if patient_sex:
            demo.append(f"Sex: {patient_sex}")
        context_lines.append("PATIENT DEMOGRAPHICS: " + ", ".join(demo))

    if existing_hccs:
        context_lines.append(
            "PREVIOUSLY CAPTURED HCCs THIS YEAR: " + ", ".join(existing_hccs)
        )

    if medications:
        context_lines.append(
            "ACTIVE MEDICATIONS:\n" + "\n".join(f"  - {m}" for m in medications)
        )

    if lab_results:
        lab_lines = []
        for lab in lab_results[:25]:
            flag = " [ABNORMAL]" if lab.get("abnormal") else ""
            lab_lines.append(
                f"  {lab.get('name', lab.get('result_text', '?'))}: "
                f"{lab.get('value', '?')} {lab.get('units', '')}{flag}"
            )
        context_lines.append("RECENT LAB RESULTS:\n" + "\n".join(lab_lines))

    # Format structured entity input for Gemini
    if present_entities:
        ent_lines: list[str] = []
        for ent in present_entities:
            name = ent.get("name") or ent.get("text") or "unknown"
            conf = ent.get("confidence", 0.0)
            assertion = ent.get("assertion", {})
            status = assertion.get("assertion", "present") if isinstance(assertion, dict) else "present"
            ent_lines.append(f"  - {name} (confidence={conf:.2f}, assertion={status})")
        context_lines.append(
            "MEDCAT EXTRACTED ENTITIES (active/present only):\n" + "\n".join(ent_lines)
        )

    # Format candidate codes list for Gemini
    if candidate_codes:
        cand_lines: list[str] = []
        for c in candidate_codes:
            code = c.get("icd10_code", "")
            desc = c.get("description", "")
            hcc = c.get("hcc_code", "")
            hcc_label = f" [HCC: {hcc}]" if hcc else ""
            entity_src = c.get("entity_source", "")
            cand_lines.append(f"  {code}: {desc}{hcc_label}  (from: {entity_src})")
        context_lines.append(
            "ICD-10-CM CANDIDATE CODES (SELECT FROM THESE ONLY — do not use codes "
            "not in this list):\n" + "\n".join(cand_lines)
        )
    else:
        context_lines.append(
            "ICD-10-CM CANDIDATE CODES: None identified by NLP pipeline. "
            "Use your expert knowledge for entity-driven code selection, "
            "but prefer codes strongly supported by the note text."
        )

    context_block = "\n".join(context_lines) + "\n\n" if context_lines else ""

    prompt = (
        f"{context_block}"
        f"CLINICAL NOTE:\n"
        f"{'=' * 60}\n"
        f"{note_text.strip()}\n"
        f"{'=' * 60}\n\n"
        f"Perform full CMS-HCC V28 analysis per your instructions. "
        f"Select codes ONLY from the candidate list above."
    )

    # ------------------------------------------------------------------
    # Stage 4 — Call Gemini
    # ------------------------------------------------------------------
    try:
        result = _call_gemini(
            prompt,
            system_instruction=_SYSTEM_ANALYZE,
            temperature=0.1,
            max_output_tokens=MAX_OUTPUT_TOKENS,
        )
    except RuntimeError as exc:
        logger.error("analyze_clinical_note Gemini call failed: %s", exc)
        return _empty_analysis(error=str(exc))

    if not isinstance(result, dict):
        return _empty_analysis(error="Unexpected response shape from Gemini")

    # ------------------------------------------------------------------
    # Post-process: validate / enrich codes, compute routing
    # ------------------------------------------------------------------
    result = _enrich_analysis(result)

    # Merge negated conditions from pipeline with Gemini's own detections
    gemini_negated: list[str] = result.get("negated_conditions", [])
    merged_negated = list({*negated_from_pipeline, *gemini_negated})
    result["negated_conditions"] = merged_negated

    # Compute overall confidence and routing decision
    overall_conf = _compute_overall_confidence(result)
    routing = _compute_routing(overall_conf)

    result["pipeline_stages"] = {
        "medcat_entities": raw_entities,
        "after_negation_filter": present_entities,
        "candidate_codes": candidate_codes,
        "enriched_entities": enriched_entities,
    }
    result["confidence_routing"] = routing
    result["overall_confidence"] = overall_conf
    result["_meta"] = {
        "model": settings.gemini_model,
        "patient_age": patient_age,
        "patient_sex": patient_sex,
        "entities_extracted": len(raw_entities),
        "entities_after_filter": len(present_entities),
        "candidates_provided": len(candidate_codes),
    }

    return result


# ---------------------------------------------------------------------------
# 2. extract_meat_evidence
# ---------------------------------------------------------------------------

def extract_meat_evidence(
    note_text: str,
    diagnosis: str,
    icd10_code: str,
) -> dict[str, Any]:
    """Extract focused MEAT evidence for a specific diagnosis from a note.

    Parameters
    ----------
    note_text:
        Full clinical note text.
    diagnosis:
        Human-readable condition name (e.g. ``"Type 2 Diabetes"``).
    icd10_code:
        The ICD-10-CM code for the diagnosis (e.g. ``"E11.22"``).

    Returns
    -------
    dict with keys:
        ``diagnosis``, ``icd10_code``, ``meat``, ``meat_present``,
        ``meat_score``, ``sufficient_for_hcc``, ``documentation_gap``
    """
    if not note_text or not diagnosis:
        return _empty_meat(diagnosis, icd10_code, error="Missing required arguments")

    code_desc = get_description(icd10_code) if icd10_code else ""
    prompt = (
        f"DIAGNOSIS: {diagnosis}\n"
        f"ICD-10-CM CODE: {icd10_code}"
        + (f" ({code_desc})" if code_desc else "")
        + f"\n\nCLINICAL NOTE:\n{'=' * 60}\n{note_text.strip()}\n{'=' * 60}\n\n"
        f"Extract MEAT evidence for this specific diagnosis only."
    )

    try:
        result = _call_gemini(
            prompt,
            system_instruction=_SYSTEM_MEAT,
            temperature=0.1,
            max_output_tokens=1024,
        )
    except RuntimeError as exc:
        logger.error("extract_meat_evidence failed for %s: %s", diagnosis, exc)
        return _empty_meat(diagnosis, icd10_code, error=str(exc))

    if not isinstance(result, dict):
        return _empty_meat(diagnosis, icd10_code, error="Unexpected response shape")

    score = result.get("meat_score", 0)
    result["meat_score"] = max(0, min(4, int(score) if str(score).isdigit() else 0))
    result.setdefault("sufficient_for_hcc", result["meat_score"] >= 1)
    return result


# ---------------------------------------------------------------------------
# 3. suggest_icd10_codes
# ---------------------------------------------------------------------------

def suggest_icd10_codes(clinical_text: str) -> list[dict[str, Any]]:
    """Suggest the top-5 ICD-10-CM codes for a free-text clinical description.

    Parameters
    ----------
    clinical_text:
        Any clinical free text.

    Returns
    -------
    List (up to 5) of ``{icd10_code, description, confidence, rationale,
    is_valid_leaf, hcc_mapping}`` dicts, ordered by descending confidence.
    """
    if not clinical_text or not clinical_text.strip():
        return []

    prompt = (
        f"CLINICAL TEXT:\n{clinical_text.strip()}\n\n"
        f"Suggest the five most appropriate ICD-10-CM codes."
    )

    try:
        raw = _call_gemini(
            prompt,
            system_instruction=_SYSTEM_ICD_SUGGEST,
            temperature=0.1,
            max_output_tokens=1024,
        )
    except RuntimeError as exc:
        logger.error("suggest_icd10_codes failed: %s", exc)
        return []

    if not isinstance(raw, list):
        if isinstance(raw, dict):
            for key in ("suggestions", "codes", "results"):
                if isinstance(raw.get(key), list):
                    raw = raw[key]
                    break
        if not isinstance(raw, list):
            logger.error("suggest_icd10_codes: unexpected shape %s", type(raw))
            return []

    suggestions: list[dict[str, Any]] = []
    for item in raw[:5]:
        if not isinstance(item, dict):
            continue
        code = normalize_code(item.get("icd10_code", ""))
        is_valid = validate_icd10_code(code) if code else False
        desc = item.get("description") or (get_description(code) if code else "")
        suggestions.append(
            {
                "icd10_code": code,
                "description": desc,
                "confidence": float(item.get("confidence", 0.0)),
                "rationale": item.get("rationale", ""),
                "is_valid_leaf": is_valid,
                "hcc_mapping": get_hcc_mapping(code) if is_valid else None,
            }
        )

    suggestions.sort(key=lambda x: x["confidence"], reverse=True)
    return suggestions


# ---------------------------------------------------------------------------
# 4. validate_coding_with_tree_search
# ---------------------------------------------------------------------------

def validate_coding_with_tree_search(
    note_text: str,
    initial_codes: list[str],
) -> list[dict[str, Any]]:
    """Validate ICD-10-CM codes and use tree-search to fix non-leaf codes.

    Algorithm per code:
      1. Normalise the code string.
      2. If the code is a valid leaf → accept as-is.
      3. If the code exists but is NOT a leaf → get its immediate children
         and ask Gemini to select the best match.  Repeat up to
         TREE_SEARCH_MAX_DEPTH levels.
      4. If the code is completely invalid → ask Gemini to suggest a
         replacement.

    Parameters
    ----------
    note_text:
        The clinical note used to guide code selection at each tree level.
    initial_codes:
        List of ICD-10-CM codes to validate (dots optional).

    Returns
    -------
    List of ``{original_code, final_code, description, is_valid_leaf,
    was_refined, refinement_path, hcc_mapping}`` dicts.
    """
    if not initial_codes:
        return []

    return [_validate_and_refine_code(raw_code, note_text) for raw_code in initial_codes]


def _validate_and_refine_code(
    code: str,
    note_text: str,
) -> dict[str, Any]:
    """Internal: validate one code, walking the ICD tree when needed."""
    original = code
    norm = normalize_code(code)
    refinement_path: list[str] = [norm]

    if validate_icd10_code(norm):
        desc = get_description(norm)
        return {
            "original_code": original,
            "final_code": norm,
            "description": desc,
            "is_valid_leaf": True,
            "was_refined": False,
            "refinement_path": refinement_path,
            "hcc_mapping": get_hcc_mapping(norm),
        }

    from simple_icd_10_cm import is_valid_item  # local import to avoid circular

    current = norm
    was_refined = False

    if is_valid_item(current):
        for _depth in range(TREE_SEARCH_MAX_DEPTH):
            children = get_children_with_descriptions(current)
            if not children:
                was_refined = True
                break

            selected = _ask_gemini_pick_child(note_text, current, children)
            if not selected:
                break

            refinement_path.append(selected)
            current = selected
            was_refined = True

            if validate_icd10_code(current):
                break

        desc = get_description(current)
        return {
            "original_code": original,
            "final_code": current,
            "description": desc,
            "is_valid_leaf": validate_icd10_code(current),
            "was_refined": was_refined,
            "refinement_path": refinement_path,
            "hcc_mapping": get_hcc_mapping(current),
        }

    replacement = _ask_gemini_replacement_code(note_text, code)
    if replacement:
        rep_norm = normalize_code(replacement)
        refinement_path.append(rep_norm)
        return {
            "original_code": original,
            "final_code": rep_norm,
            "description": get_description(rep_norm),
            "is_valid_leaf": validate_icd10_code(rep_norm),
            "was_refined": True,
            "refinement_path": refinement_path,
            "hcc_mapping": get_hcc_mapping(rep_norm),
        }

    return {
        "original_code": original,
        "final_code": norm,
        "description": None,
        "is_valid_leaf": False,
        "was_refined": False,
        "refinement_path": refinement_path,
        "hcc_mapping": None,
    }


def _ask_gemini_pick_child(
    note_text: str,
    parent_code: str,
    children: list[dict[str, Any]],
) -> str | None:
    """Ask Gemini to choose the best child code for *parent_code* given the note."""
    children_block = "\n".join(
        f"  {c['code']}: {c['description']}"
        + (" [leaf - assignable]" if c["is_leaf"] else " [not yet leaf]")
        for c in children
    )
    prompt = (
        f"ICD-10-CM code '{parent_code}' is a category (not assignable for billing).\n"
        f"Its child codes are:\n{children_block}\n\n"
        f"CLINICAL NOTE:\n{'=' * 60}\n{note_text.strip()}\n{'=' * 60}\n\n"
        f"Select the single most appropriate child code."
    )
    try:
        result = _call_gemini(
            prompt,
            system_instruction=_SYSTEM_TREE_PICK,
            temperature=0.0,
            max_output_tokens=256,
        )
        if isinstance(result, dict) and result.get("selected_code"):
            return normalize_code(result["selected_code"])
    except RuntimeError as exc:
        logger.warning("_ask_gemini_pick_child failed for %s: %s", parent_code, exc)
    return None


def _ask_gemini_replacement_code(note_text: str, invalid_code: str) -> str | None:
    """Ask Gemini to suggest a valid replacement for a completely invalid code."""
    prompt = (
        f"The ICD-10-CM code '{invalid_code}' does not exist in the ICD-10-CM index.\n"
        f"Based on the clinical note below, suggest the single most appropriate "
        f"valid ICD-10-CM leaf code as a replacement.\n\n"
        f"CLINICAL NOTE:\n{'=' * 60}\n{note_text.strip()}\n{'=' * 60}\n\n"
        f'Return JSON: {{"selected_code": "<code>", "description": "<desc>", '
        f'"rationale": "<one sentence>"}}'
    )
    try:
        result = _call_gemini(
            prompt,
            system_instruction=_SYSTEM_TREE_PICK,
            temperature=0.1,
            max_output_tokens=256,
        )
        if isinstance(result, dict) and result.get("selected_code"):
            return result["selected_code"]
    except RuntimeError as exc:
        logger.warning("_ask_gemini_replacement_code failed for %s: %s", invalid_code, exc)
    return None


# ---------------------------------------------------------------------------
# 5. batch_analyze
# ---------------------------------------------------------------------------

def batch_analyze(
    encounters_list: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Analyze multiple encounters sequentially through the full pipeline.

    Each element of *encounters_list* is a dict that may contain:
        ``encounter_id``   (str)  — propagated to output
        ``note_text``      (str)  — REQUIRED; skipped if absent/empty
        ``patient_age``    (int)
        ``patient_sex``    (str)
        ``medications``    (list[str])
        ``lab_results``    (list[dict])
        ``existing_hccs``  (list[str])

    Returns
    -------
    List of analysis result dicts, one per encounter with non-empty
    ``note_text``.  Each result is augmented with ``encounter_id``
    and ``batch_index``.
    """
    if not encounters_list:
        return []

    results: list[dict[str, Any]] = []
    total = len(encounters_list)

    for idx, encounter in enumerate(encounters_list):
        encounter_id = encounter.get("encounter_id", f"batch_{idx}")
        note_text = encounter.get("note_text", "")

        if not note_text or not note_text.strip():
            logger.debug(
                "batch_analyze: skipping encounter %s (empty note)", encounter_id
            )
            continue

        logger.info(
            "batch_analyze: processing %d/%d (encounter_id=%s)",
            idx + 1, total, encounter_id,
        )

        analysis = analyze_clinical_note(
            note_text=note_text,
            patient_age=encounter.get("patient_age"),
            patient_sex=encounter.get("patient_sex"),
            medications=encounter.get("medications"),
            lab_results=encounter.get("lab_results"),
            existing_hccs=encounter.get("existing_hccs"),
        )
        analysis["encounter_id"] = encounter_id
        analysis["batch_index"] = idx
        results.append(analysis)

        if idx < total - 1:
            time.sleep(BATCH_DELAY_SECONDS)

    logger.info(
        "batch_analyze: completed %d/%d encounters", len(results), total
    )
    return results


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _enrich_analysis(result: dict[str, Any]) -> dict[str, Any]:
    """Validate ICD-10 codes and attach HCC mappings.  Modifies in-place."""
    for dx in result.get("diagnoses", []):
        raw_code = dx.get("icd10_code", "")
        if raw_code:
            norm = normalize_code(raw_code)
            dx["icd10_code"] = norm
            dx["icd10_valid"] = validate_icd10_code(norm)
            if not dx.get("icd10_description") and norm:
                dx["icd10_description"] = get_description(norm) or None
            if not dx.get("hcc_code"):
                mapping = get_hcc_mapping(norm)
                if mapping:
                    dx["hcc_code"] = mapping.get("hcc_code")
            dx["hcc_mapping"] = get_hcc_mapping(norm)
        raw_score = dx.get("meat_score", 0)
        try:
            dx["meat_score"] = max(0, min(4, int(raw_score)))
        except (TypeError, ValueError):
            dx["meat_score"] = 0

    for suspect in result.get("suspect_conditions", []):
        raw_code = suspect.get("suspect_icd10", "")
        if raw_code:
            norm = normalize_code(raw_code)
            suspect["suspect_icd10"] = norm
            suspect["code_valid"] = validate_icd10_code(norm)
            if not suspect.get("code_description"):
                suspect["code_description"] = get_description(norm) or None
            suspect["hcc_mapping"] = get_hcc_mapping(norm)

    return result


def _compute_overall_confidence(result: dict[str, Any]) -> float:
    """Compute a weighted average confidence across all diagnoses."""
    diagnoses = result.get("diagnoses", [])
    if not diagnoses:
        return 0.0
    scores = [float(dx.get("confidence", 0.0)) for dx in diagnoses]
    return round(sum(scores) / len(scores), 4)


def _compute_routing(overall_confidence: float) -> str:
    """Map overall confidence to a routing decision.

    Returns
    -------
    ``"auto_accept"``   — confidence >= 0.90; safe to auto-post
    ``"human_review"``  — 0.70 <= confidence < 0.90; coder review recommended
    ``"full_audit"``    — confidence < 0.70; full audit required
    """
    if overall_confidence >= _THRESHOLD_AUTO_ACCEPT:
        return "auto_accept"
    if overall_confidence >= _THRESHOLD_HUMAN_REVIEW:
        return "human_review"
    return "full_audit"


def _empty_analysis(error: str = "") -> dict[str, Any]:
    """Return a structurally valid but empty analysis result."""
    base: dict[str, Any] = {
        "pipeline_stages": {
            "medcat_entities": [],
            "after_negation_filter": [],
            "candidate_codes": [],
        },
        "diagnoses": [],
        "suspect_conditions": [],
        "negated_conditions": [],
        "coding_notes": "",
        "confidence_routing": "full_audit",
        "overall_confidence": 0.0,
    }
    if error:
        base["error"] = error
        logger.warning("analyze_clinical_note returning empty result: %s", error)
    return base


def _empty_meat(
    diagnosis: str,
    icd10_code: str,
    error: str = "",
) -> dict[str, Any]:
    """Return a structurally valid but empty MEAT result."""
    base: dict[str, Any] = {
        "diagnosis": diagnosis,
        "icd10_code": icd10_code,
        "meat": {
            "monitoring": "",
            "evaluation": "",
            "assessment": "",
            "treatment": "",
        },
        "meat_present": {
            "monitoring": False,
            "evaluation": False,
            "assessment": False,
            "treatment": False,
        },
        "meat_score": 0,
        "sufficient_for_hcc": False,
        "documentation_gap": "",
    }
    if error:
        base["error"] = error
    return base
