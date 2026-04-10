# Multi-Stage Verification Pipeline Design
## RAF Intelligence — Clinical Analysis Architecture

**Status:** PROPOSED — Awaiting approval before implementation
**Date:** 2026-03-30
**Replaces:** `backend/app/services/skill_pipeline.py` (single-stage Gemini approach)

---

## 1. Problem Statement

The current `skill_pipeline.py` routes the entire clinical note to a single Gemini call
with function-calling tools. This architecture has three failure modes:

| Failure Mode | Example | Impact |
|---|---|---|
| Silent omission | I11.0 is in the Active Problem List but Gemini does not return it | RAF undercount — HCC226 missed |
| Over-extraction | Gemini infers a condition from medication that provider has documented as resolved | RAF overcoding |
| No auditability | No way to know why a code is present or absent in the final output | Compliance risk |

The heart failure bug is the canonical example of the first failure mode. A note that
contains `I11.0 - Hypertensive heart disease with heart failure` in the Active Problem
List is parsed by Gemini under the general instruction "extract diagnoses." If Gemini
groups the note by chief complaint and loses the problem list section, I11.0 never
appears in the output. No alarm fires. The RAF score is silently wrong.

---

## 2. Proposed Architecture

```
Clinical Note
      |
      v
+------------------+
|  Stage 1         |  ~50-150ms
|  Rule-Based      |  No LLM
|  Pre-Extraction  |
+------------------+
      |
      | pre_extracted_codes[]
      | problem_list_codes[]
      | lab_values{}
      | medications[]
      |
      v
+------------------+
|  Stage 2         |  ~3000-8000ms
|  LLM Clinical    |  Gemini
|  Analysis        |
+------------------+
      |
      | diagnoses[]
      | suspects[]
      | negated[]
      | meat_evidence{}
      |
      v
+------------------+
|  Stage 3         |  ~200-500ms
|  Verification &  |  No LLM
|  Reconciliation  |
+------------------+
      |
      | verified_diagnoses[]
      | warnings[]
      | reconciliation_report{}
      |
      v
+------------------+
|  Stage 4         |  ~100-300ms
|  RAF Calculation |  No LLM
|  + Quality Score |
+------------------+
      |
      v
   Final Output
```

Stage 1 and the LLM prompt construction for Stage 2 can be considered a warm-up phase;
Stage 2 is the only blocking LLM call. Stages 3 and 4 are pure computation.

**Total estimated wall time: 3.5 – 9 seconds** (dominated by Stage 2 Gemini latency).

---

## 3. Data Contracts

### 3.1 Stage 1 Output — `PreExtractionResult`

```python
@dataclass
class PreExtractionResult:
    # ICD-10 codes found verbatim in the note (e.g., "I11.0", "E11.22")
    # Includes codes in any section: assessment, problem list, diagnoses
    explicit_icd_codes: list[str]

    # Codes extracted specifically from the "Active Problem List" section
    # These carry the highest obligation — every one must appear in final output
    # or have a documented reason for exclusion
    problem_list_codes: list[str]

    # Free-text condition names from the problem list (before ICD assignment)
    # Used as fallback when no ICD code is printed next to the condition
    problem_list_conditions: list[str]

    # Structured lab values
    lab_values: dict[str, LabValue]
    # e.g., {"HbA1c": LabValue(value=8.2, unit="%", date="2026-01-15", abnormal=True),
    #         "eGFR":  LabValue(value=38, unit="mL/min/1.73m2", date="2026-01-15", abnormal=True)}

    # Medications found in the note (normalized to lowercase)
    medications: list[str]

    # Raw section text, preserved for LLM context injection in Stage 2
    sections: dict[str, str]
    # e.g., {"active_problem_list": "...", "medications": "...", "labs": "..."}

    # Parser metadata
    parser_version: str
    parse_time_ms: float


@dataclass
class LabValue:
    value: float | str
    unit: str
    date: str | None
    abnormal: bool
    reference_range: str | None
```

### 3.2 Stage 2 Input — `LLMAnalysisRequest`

```python
@dataclass
class LLMAnalysisRequest:
    # Full clinical note (truncated to MAX_NOTE_CHARS)
    clinical_note: str

    # Stage 1 outputs, injected directly into the Gemini prompt
    # so the LLM has explicit awareness of what was pre-found
    pre_extracted_codes: list[str]
    problem_list_codes: list[str]
    problem_list_conditions: list[str]
    lab_values: dict[str, LabValue]
    medications: list[str]

    # Patient demographics (for context)
    age: int
    sex: str
    dual_status: str
```

### 3.3 Stage 2 Output — `LLMAnalysisResult`

```python
@dataclass
class LLMAnalysisResult:
    # Confirmed active diagnoses with coding rationale
    diagnoses: list[LLMDiagnosis]

    # Suspected conditions flagged for provider query (not yet coded)
    suspects: list[SuspectCondition]

    # Conditions the LLM determined are negated, historical, or resolved
    negated: list[NegatedCondition]

    # MEAT evidence keyed by ICD-10 code
    meat_evidence: dict[str, MEATEvidence]

    # Raw Gemini response metadata (token counts, latency)
    llm_metadata: dict[str, Any]


@dataclass
class LLMDiagnosis:
    icd10_code: str
    description: str
    confidence: str          # "high" | "medium" | "low"
    source: str              # "explicit_note" | "problem_list" | "inferred_medication"
                             # | "inferred_lab" | "clinical_inference"
    reasoning: str           # LLM's clinical rationale


@dataclass
class SuspectCondition:
    condition_name: str
    suggested_icd10: str | None
    trigger: str             # what triggered the suspicion
    trigger_type: str        # "medication_gap" | "lab_abnormality" | "clinical_pattern"
    query_language: str      # suggested provider query text


@dataclass
class NegatedCondition:
    icd10_code: str | None
    condition_name: str
    reason: str              # "patient denies", "resolved", "historical", "negated in note"


@dataclass
class MEATEvidence:
    monitoring: list[str]
    evaluation: list[str]
    assessment: list[str]
    treatment: list[str]
    overall_meat_met: bool
```

### 3.4 Stage 3 Output — `ReconciliationResult`

```python
@dataclass
class ReconciliationResult:
    # Final verified diagnoses — these feed Stage 4
    verified_diagnoses: list[VerifiedDiagnosis]

    # Warnings the downstream consumer must display
    warnings: list[ReconciliationWarning]

    # Full reconciliation audit trail
    reconciliation_report: ReconciliationReport


@dataclass
class VerifiedDiagnosis:
    icd10_code: str
    description: str
    hcc_code: str | None
    raf_weight: float
    is_hcc_relevant: bool
    confidence: str
    source: str
    meat_evidence: MEATEvidence | None
    stage1_found: bool       # True if Stage 1 pre-extraction found this code
    stage2_found: bool       # True if Stage 2 LLM returned this code
    icd10_valid: bool
    icd10_billable: bool
    excludes1_conflicts: list[str]


@dataclass
class ReconciliationWarning:
    severity: str            # "critical" | "high" | "medium" | "info"
    code: str                # machine-readable warning code
    message: str             # human-readable description
    icd10_code: str | None
    action_required: str     # what the end user should do


@dataclass
class ReconciliationReport:
    stage1_codes: list[str]
    stage2_codes: list[str]

    # Codes found in Stage 1 but NOT in Stage 2 (LLM dropped them)
    dropped_by_llm: list[DroppedCode]

    # Codes found in Stage 2 but NOT in Stage 1 (LLM inferred them)
    inferred_by_llm: list[InferredCode]

    # Codes present in both stages (high confidence)
    confirmed_by_both: list[str]

    # Problem list codes accounted for (in output or explicitly excluded)
    problem_list_accounted: dict[str, str]   # code -> "included" | "negated" | "historical"
    problem_list_unaccounted: list[str]      # codes with no disposition at all

    icd10_validation_results: dict[str, ValidationResult]
    excludes1_check_results: dict[str, list[str]]


@dataclass
class DroppedCode:
    icd10_code: str
    source: str              # where Stage 1 found it
    llm_negated: bool        # True if LLM explicitly negated it
    llm_negation_reason: str | None
    disposition: str         # "restored" | "excluded_with_reason" | "flagged_for_review"


@dataclass
class InferredCode:
    icd10_code: str
    llm_reasoning: str
    confidence: str
    supporting_evidence: list[str]   # medications, labs, text snippets that support it
    disposition: str         # "accepted" | "flagged_for_review" | "rejected_invalid_code"
```

### 3.5 Stage 4 Output — `PipelineResult`

```python
@dataclass
class PipelineResult:
    # === Core RAF output ===
    raf_score: float
    demographic_score: float
    disease_score: float
    hcc_details: list[HCCDetail]
    interaction_terms: list[dict]

    # === Verified diagnoses (from Stage 3) ===
    verified_diagnoses: list[VerifiedDiagnosis]
    suspects: list[SuspectCondition]
    negated: list[NegatedCondition]

    # === Quality & confidence metrics ===
    quality_score: float           # 0.0 - 1.0 composite score
    quality_breakdown: QualityBreakdown
    warnings: list[ReconciliationWarning]
    reconciliation_report: ReconciliationReport

    # === Pipeline metadata ===
    stage_timings: dict[str, float]   # ms per stage
    pipeline_version: str
    model_used: str


@dataclass
class QualityBreakdown:
    stage1_stage2_agreement_rate: float    # fraction of codes confirmed by both stages
    problem_list_coverage_rate: float      # fraction of problem list codes accounted for
    meat_evidence_rate: float              # fraction of HCC diagnoses with full MEAT
    llm_drop_count: int                    # how many Stage 1 codes LLM dropped
    llm_inference_count: int               # how many Stage 2 codes have no Stage 1 basis
    icd10_validity_rate: float             # fraction of codes that are valid/billable
    critical_warning_count: int
    high_warning_count: int
```

---

## 4. Function Signatures

### 4.1 Stage 1 — `run_pre_extraction`

```python
def run_pre_extraction(clinical_note: str) -> PreExtractionResult:
    """
    Parse the clinical note with regex and rule-based logic.
    No network calls. No LLM. Deterministic and fast.

    Responsibilities:
    - Identify and parse named sections (Active Problem List, Medications, Labs,
      Assessment & Plan, etc.) using header patterns.
    - Extract all ICD-10 codes mentioned explicitly anywhere in the note.
      Pattern: r'\b[A-Z]\d{2}(?:\.\w{1,4})?\b' with alphanumeric validation.
    - Extract all conditions from the Active Problem List section (both
      ICD-coded entries and free-text entries without codes).
    - Extract all lab values with value, unit, date, and abnormality flag.
    - Extract all medications (normalize to lowercase, strip dosages).
    - Preserve raw section text for Stage 2 prompt construction.
    """


def _extract_icd10_codes(text: str) -> list[str]:
    """Return all ICD-10 code strings found in text, deduplicated and validated
    against a basic structural pattern (letter + 2 digits + optional detail)."""


def _extract_problem_list(problem_list_section: str) -> tuple[list[str], list[str]]:
    """
    Returns (icd_codes, free_text_conditions) from the problem list section.
    Handles formats like:
      - "1. I11.0 - Hypertensive heart disease with heart failure"
      - "- Type 2 Diabetes Mellitus (E11.9)"
      - "• CKD Stage 3b"
    """


def _extract_lab_values(labs_text: str) -> dict[str, LabValue]:
    """
    Parse structured and semi-structured lab sections.
    Targets: HbA1c, eGFR, creatinine, BUN, BMI, sodium, potassium,
             INR/PT, TSH, hemoglobin, WBC, platelets, LDL, HDL, triglycerides.
    """


def _extract_medications(med_section: str) -> list[str]:
    """
    Tokenize the medications section. Strip dosages, frequencies, and routes.
    Return normalized lowercase drug names. Handle both list and paragraph formats.
    """


def _segment_note_sections(clinical_note: str) -> dict[str, str]:
    """
    Split the note into named sections using header pattern matching.
    Returns a dict with keys like: 'active_problem_list', 'medications',
    'labs', 'assessment_and_plan', 'subjective', 'objective', 'history'.
    Unknown text is assigned to 'unstructured'.
    """
```

### 4.2 Stage 2 — `run_llm_analysis`

```python
async def run_llm_analysis(
    request: LLMAnalysisRequest,
) -> LLMAnalysisResult:
    """
    Send the clinical note + Stage 1 extractions to Gemini.
    Uses function-calling for ICD-10 validation, HCC lookup, and RAF calculation
    (reusing existing tool implementations from skill_pipeline.py).

    The prompt instructs Gemini to:
    1. VALIDATE Stage 1 extractions — confirm each is active, not negated,
       not historical. For each code, state whether it is confirmed or excluded
       and why.
    2. INFER additional conditions not explicitly coded — from medication gaps,
       lab abnormalities, and clinical language in the note.
    3. DOCUMENT MEAT evidence for every HCC-relevant diagnosis.
    4. FLAG suspects for provider query (not for coding).

    Critically, the prompt injects the Stage 1 pre_extracted_codes and
    problem_list_codes explicitly so the LLM cannot silently omit them.
    Every pre-extracted code must appear in either diagnoses[] or negated[]
    in the response — no silent drops allowed by prompt instruction.
    """


def _build_llm_prompt(request: LLMAnalysisRequest) -> str:
    """
    Construct the Gemini system + user prompt.

    Key prompt engineering decisions:
    - Inject pre_extracted_codes as a numbered list with the instruction:
      "For each of the following codes found by automated extraction, you MUST
       explicitly classify them as: active_confirmed, negated, historical, or
       needs_review. Do not omit any."
    - Inject problem_list_codes separately with higher obligation language:
      "The following codes appear in the Active Problem List. Each one requires
       explicit disposition. If you do not include a code in your diagnoses,
       you must document the clinical reason it is excluded."
    - Inject lab abnormalities with clinical thresholds for interpretation.
    - Inject medication list for gap analysis.
    """


def _parse_llm_response(raw_response: dict) -> LLMAnalysisResult:
    """
    Parse Gemini function-calling response into structured LLMAnalysisResult.
    Handles partial responses, missing fields, and malformed tool call results.
    """
```

### 4.3 Stage 3 — `run_reconciliation`

```python
def run_reconciliation(
    pre_extraction: PreExtractionResult,
    llm_analysis: LLMAnalysisResult,
) -> ReconciliationResult:
    """
    Deterministic comparison and validation pass. No LLM.

    Reconciliation algorithm:
    1. Build sets: stage1_set = set(pre_extraction.explicit_icd_codes)
                   stage2_set = set(code for d in llm_analysis.diagnoses)
    2. dropped_by_llm = stage1_set - stage2_set
       For each dropped code: check if it appears in llm_analysis.negated.
       If negated: record with reason, mark disposition = "excluded_with_reason".
       If NOT negated: this is a silent drop — severity = CRITICAL warning,
       disposition = "flagged_for_review". Restore the code to verified output
       with confidence = "flagged" so the UI can highlight it.
    3. inferred_by_llm = stage2_set - stage1_set
       For each inferred code: validate ICD-10, run HCC lookup.
       If invalid code: severity = HIGH warning, reject from final output.
       If valid: accept with confidence from LLM, flag as "llm_inferred".
    4. problem_list_unaccounted: any problem_list_code not in verified output
       and not in llm_analysis.negated. Severity = CRITICAL.
    5. Run validate_code_set() on all codes in the union of Stage 1 and Stage 2.
    6. Run excludes1 checks on the final verified set.
    7. Compute quality metrics for Stage 4.
    """


def _check_for_silent_drops(
    stage1_codes: list[str],
    llm_diagnoses: list[LLMDiagnosis],
    llm_negated: list[NegatedCondition],
) -> list[DroppedCode]:
    """
    Core heart-failure-bug detection logic.

    For each code in stage1_codes:
      - Is it in llm_diagnoses? -> confirmed, no issue
      - Is it in llm_negated?   -> excluded with documented reason, acceptable
      - Neither?                -> SILENT DROP, critical warning
    """


def _validate_inferred_codes(
    inferred_codes: list[str],
    llm_analysis: LLMAnalysisResult,
) -> list[InferredCode]:
    """
    For codes the LLM added that were not in Stage 1:
    - Validate ICD-10 syntax and billability
    - Run HCC lookup
    - Score confidence based on LLM reasoning quality
    - Flag any code with only 'clinical_inference' source as medium confidence
    """


def _check_excludes1(verified_codes: list[str]) -> dict[str, list[str]]:
    """
    For each code in verified_codes, check for Excludes1 conflicts with
    other codes in the same set. Return a dict mapping each code to its
    list of conflicting codes.
    """


def _check_problem_list_coverage(
    problem_list_codes: list[str],
    verified_diagnoses: list[VerifiedDiagnosis],
    negated: list[NegatedCondition],
) -> tuple[dict[str, str], list[str]]:
    """
    Returns (accounted_map, unaccounted_list).
    Every problem list code should map to "included", "negated", or "historical".
    Anything else appears in unaccounted_list as a CRITICAL warning.
    """
```

### 4.4 Stage 4 — `run_raf_and_quality`

```python
def run_raf_and_quality(
    reconciliation: ReconciliationResult,
    pre_extraction: PreExtractionResult,
    llm_analysis: LLMAnalysisResult,
    age: int,
    sex: str,
    dual_status: str,
    stage_timings: dict[str, float],
) -> PipelineResult:
    """
    Final stage. Pure computation.

    1. Extract ICD-10 codes from reconciliation.verified_diagnoses.
    2. Call existing _handle_calculate_raf_score() with verified codes.
    3. Compute quality_score:
         base = 1.0
         - 0.15 per critical warning (cap at 0.45 deduction)
         - 0.05 per high warning (cap at 0.20 deduction)
         - 0.10 if problem_list_coverage_rate < 1.0
         - 0.05 if stage1_stage2_agreement_rate < 0.85
         + 0.05 bonus if meat_evidence_rate == 1.0
         floor at 0.0
    4. Assemble and return PipelineResult.
    """


def _compute_quality_score(
    warnings: list[ReconciliationWarning],
    report: ReconciliationReport,
    llm_analysis: LLMAnalysisResult,
) -> tuple[float, QualityBreakdown]:
    """Compute 0.0-1.0 quality score and the breakdown components."""
```

### 4.5 Top-Level Orchestrator

```python
async def run_multi_stage_pipeline(
    clinical_note: str,
    age: int,
    sex: str,
    dual_status: str = "non_dual",
) -> PipelineResult:
    """
    Main entry point. Orchestrates all four stages with timing.

    Execution plan:
    1. Stage 1 runs synchronously (fast, deterministic).
    2. Stage 2 runs async (LLM call).
       Stage 1 result is used to build the Stage 2 prompt before the await.
    3. Stage 3 runs synchronously after Stage 2 completes.
    4. Stage 4 runs synchronously after Stage 3 completes.

    Error handling:
    - Stage 1 failure: unrecoverable, raise immediately.
    - Stage 2 failure: if Gemini errors, fall back to a minimal LLM result
      that contains only the Stage 1 codes marked as "llm_unavailable".
      Stage 3 will flag all codes as "needs_review" but the pipeline completes.
    - Stage 3 failure: unrecoverable (it is pure logic), raise immediately.
    - Stage 4 failure: return partial result with raf_score = null and
      quality_score = 0.0 rather than crashing.
    """
```

---

## 5. How Reconciliation Catches the Heart Failure Bug

The following trace shows exactly how a note containing `I11.0` in the Active Problem
List but missing it from the Gemini response would be caught:

```
Stage 1 — _extract_problem_list():
  problem_list_codes = ["I11.0", "E11.22", "N18.3"]
  explicit_icd_codes = ["I11.0", "E11.22", "N18.3"]

Stage 2 — Gemini returns:
  diagnoses = [
    LLMDiagnosis(icd10_code="E11.22", ...),
    LLMDiagnosis(icd10_code="N18.3", ...),
    # I11.0 absent — silent drop
  ]
  negated = []   # LLM did not even mention I11.0

Stage 3 — _check_for_silent_drops():
  stage1_set = {"I11.0", "E11.22", "N18.3"}
  stage2_set = {"E11.22", "N18.3"}
  dropped = stage1_set - stage2_set = {"I11.0"}

  For I11.0:
    in llm_negated? -> NO
    -> DroppedCode(
         icd10_code="I11.0",
         source="active_problem_list",
         llm_negated=False,
         disposition="flagged_for_review"
       )
    -> ReconciliationWarning(
         severity="critical",
         code="SILENT_DROP_PROBLEM_LIST",
         message="I11.0 (Hypertensive heart disease with heart failure) appears
                  in the Active Problem List but was dropped by LLM analysis
                  without documented reason. Code restored with flag.",
         icd10_code="I11.0",
         action_required="Clinician review required before finalizing."
       )

  I11.0 is restored to verified_diagnoses with:
    stage1_found=True, stage2_found=False, confidence="flagged"

Stage 4:
  I11.0 -> HCC226 (Heart Failure) -> RAF weight applied
  quality_score -= 0.15 for the critical warning
  quality_breakdown.critical_warning_count = 1
  quality_breakdown.llm_drop_count = 1
```

The user sees the correct RAF score (I11.0 included) AND a critical warning that flags
the discrepancy for clinical review. The old pipeline would have silently returned a
lower, incorrect RAF score with no indication anything was wrong.

---

## 6. Parallel Execution Opportunities

```
Time 0ms ──────────────────────────────────────────────────────────────
  [Stage 1] run_pre_extraction()            ~50-150ms

Time ~150ms ────────────────────────────────────────────────────────────
  [Stage 2] run_llm_analysis()              ~3000-8000ms
  [Prep]    While awaiting Stage 2, pre-compute:
            - ICD-10 validation for all Stage 1 codes
            - HCC lookups for all Stage 1 codes
            These results are used immediately in Stage 3.

Time ~3500ms ───────────────────────────────────────────────────────────
  [Stage 3] run_reconciliation()            ~200-500ms
  [Stage 4] run_raf_and_quality()           ~100-300ms

Total: ~4000-9000ms
```

Note: The ICD-10 validation and HCC lookup pre-computation during Stage 2's await
window is an important optimization. By the time Gemini responds, all Stage 1 codes
are already validated, so Stage 3 does not start from zero.

The Stage 2 LLM call is the only true bottleneck. If sub-3s total latency is required
in a future iteration, Stage 2 can be split into two parallel Gemini calls:
(a) validation of Stage 1 codes and (b) open-ended inference — but that adds
complexity and doubles token cost. Not recommended until latency data justifies it.

---

## 7. Time Budget

| Stage | Work | Estimated Time |
|---|---|---|
| Stage 1 | Regex parsing, section segmentation, lab/med extraction | 50 – 150ms |
| Stage 2 (prompt build) | Construct Gemini prompt with Stage 1 injections | 5 – 15ms |
| Stage 2 (Gemini call) | LLM inference, function-calling round trips | 3000 – 8000ms |
| Stage 1 pre-compute (parallel) | ICD-10 validation + HCC lookup for Stage 1 codes | 100 – 400ms |
| Stage 3 | Reconciliation, set comparisons, Excludes1 checks | 200 – 500ms |
| Stage 4 | RAF calculation, quality scoring, result assembly | 100 – 300ms |
| **Total** | | **~3500 – 9500ms** |

The 50th percentile Gemini latency for a medium-complexity note is approximately
4-5 seconds, giving a typical total pipeline time of ~5 seconds.

---

## 8. Warning Severity Taxonomy

| Code | Severity | Meaning |
|---|---|---|
| `SILENT_DROP_PROBLEM_LIST` | critical | LLM dropped a code from the Active Problem List with no documented reason |
| `SILENT_DROP_EXPLICIT_CODE` | high | LLM dropped an explicitly stated ICD-10 code from a non-problem-list section |
| `PROBLEM_LIST_UNACCOUNTED` | critical | A problem list code has no disposition in the final output |
| `INVALID_ICD10_CODE` | high | A code returned by Stage 2 fails ICD-10 validation |
| `NON_BILLABLE_CODE` | high | A code exists but is a header code, not a leaf/billable code |
| `EXCLUDES1_CONFLICT` | high | Two codes in the final set have an ICD-10 Excludes1 relationship |
| `LLM_INFERRED_NO_EVIDENCE` | medium | LLM added a code with no supporting Stage 1 evidence |
| `MISSING_MEAT_FOR_HCC` | medium | An HCC-relevant diagnosis lacks full MEAT documentation |
| `LOW_CONFIDENCE_INFERENCE` | info | LLM marked a diagnosis as low confidence |
| `LLM_FALLBACK_ACTIVE` | info | Stage 2 failed and the pipeline ran in Stage 1-only fallback mode |

---

## 9. Technology Decisions

### What changes vs. the current pipeline

| Aspect | Current | Proposed |
|---|---|---|
| Entry point | `run_pipeline()` in `skill_pipeline.py` | `run_multi_stage_pipeline()` in `multi_stage_pipeline.py` |
| LLM tool reuse | Tools defined inline | Stage 2 imports tool handlers from `skill_pipeline.py` unchanged |
| ICD-10 validation | LLM calls `validate_icd10` tool | Stage 3 calls `validate_code_set()` directly |
| HCC lookup | LLM calls `lookup_hcc` tool | Stage 3 calls `_handle_lookup_hcc()` directly |
| RAF calculation | LLM calls `calculate_raf_score` tool | Stage 4 calls `_handle_calculate_raf_score()` directly |
| Error visibility | None | `warnings[]` array with severity codes |
| Auditability | None | Full `reconciliation_report{}` in every response |

### What does NOT change

- `icd_validator.py` and `validate_code_set()` — reused as-is
- All tool handler functions (`_handle_lookup_hcc`, `_handle_validate_icd10`, etc.) — reused as-is
- The Gemini API client configuration and retry logic — reused
- The `hccinfhir` RAF calculation — reused via `_handle_calculate_raf_score`
- All database schema and queries — no changes

### New file structure

```
backend/app/services/
  skill_pipeline.py              # UNCHANGED — tool handlers stay here
  multi_stage_pipeline.py        # NEW — orchestrator and stage functions
  pre_extractor.py               # NEW — Stage 1 rule-based extraction
  reconciler.py                  # NEW — Stage 3 verification logic
```

---

## 10. Rollout Strategy

Because this is a significant behavioral change, the following phased rollout is recommended:

**Phase 1 — Shadow mode**
Run both pipelines on every request. Log the differences between old and new outputs.
Do not change the API response yet. Collect data on how often the new pipeline catches
discrepancies.

**Phase 2 — Opt-in**
Add a query parameter `?pipeline=v2` that routes to the new multi-stage pipeline.
Let QA and clinical reviewers validate the output quality.

**Phase 3 — Default**
Make the multi-stage pipeline the default. Keep the old pipeline accessible via
`?pipeline=v1` for one release cycle as a fallback.

**Phase 4 — Retire**
Remove the single-stage pipeline after confirming zero regression.

---

## 11. Open Questions for Review

The following decisions need sign-off before implementation begins:

1. **Restoration policy for silent drops**: Should Stage 3 automatically restore
   silently-dropped problem list codes to the final output (current design), or
   should it flag them but exclude them and require explicit clinician confirmation?
   Auto-restore is safer for RAF completeness but could include truly-resolved
   conditions if the problem list is stale.

2. **Stage 2 fallback behavior**: If Gemini is unavailable, the current design falls
   back to a Stage 1-only result with all codes marked "needs_review." Is this
   acceptable, or should the entire pipeline fail?

3. **Excludes1 enforcement**: Should Excludes1 conflicts be hard-rejected from the
   output, or flagged as warnings while still being included? Hard rejection is
   technically correct but could surprise users who intentionally code both (rare
   edge cases exist).

4. **Quality score threshold**: Is there a minimum quality_score below which the
   system should refuse to display a RAF score and require human review? Suggest 0.5
   as an initial threshold.

5. **Parallel LLM calls for large notes**: For notes over 10,000 characters, should
   the pipeline split the note into sections and run Stage 2 in parallel? This would
   reduce latency at the cost of higher token usage and more complex merging logic in
   Stage 3.
