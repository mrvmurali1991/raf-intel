"""
Stage 1: Rule-Based Pre-Extraction
===================================
Deterministic extraction of all clinical data from the note before LLM
processing.  No LLM calls — pure regex/rule-based parsing.

Design contract: MULTI_STAGE_PIPELINE_DESIGN.md §3.1 and §4.1.

Performance target: <200ms on a standard clinical note (<15 000 chars).
No DB calls, no network calls, no async — everything runs in-process.

Public surface
--------------
run_stage1(clinical_note, problem_list=None, vitals_structured=None)
    -> ExtractionResult

Individual sub-functions are also exported so Stage 2 can call specific
extractors in isolation (e.g. to re-parse a single section after truncation).
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

try:
    from hccinfhir.defaults import dx_to_cc_default, labels_default, coefficients_default
    _HCC_AVAILABLE = True
except ImportError:  # pragma: no cover
    dx_to_cc_default = {}
    labels_default = {}
    coefficients_default = {}
    _HCC_AVAILABLE = False

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Parser version — bump when regex patterns change so Stage 3 can detect
# whether a cached Stage 1 result used the same parser as the current run.
# ---------------------------------------------------------------------------
PARSER_VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# ICD-10-CM structural pattern
# ---------------------------------------------------------------------------
# A valid ICD-10-CM code:
#   - One uppercase letter (A-Z excluding U which is reserved by WHO)
#   - Followed by exactly 2 digits
#   - Optionally followed by a dot and 1-4 alphanumeric characters
#
# Strict word boundaries prevent matching mid-word substrings.
_ICD10_PATTERN = re.compile(
    r"\b([A-TV-Z][0-9]{2}(?:\.[A-Z0-9]{1,4})?)\b",
    re.IGNORECASE,
)


def _normalize_icd(code: str) -> str:
    """Return the code in canonical uppercase form, e.g. 'e11.22' -> 'E11.22'."""
    return code.strip().upper()


def _is_valid_icd_structure(code: str) -> bool:
    """Return True if *code* matches the ICD-10-CM structural pattern."""
    return bool(_ICD10_PATTERN.fullmatch(code.strip()))


# ---------------------------------------------------------------------------
# Section header patterns
# ---------------------------------------------------------------------------
# Each tuple: (canonical_key, list_of_regex_patterns_for_that_header)
# Headers are matched case-insensitively.  The section runs from the matched
# header until the next recognised header (or end of note).
_SECTION_HEADERS: list[tuple[str, list[str]]] = [
    ("chief_complaint", [
        r"chief\s*complaint",
        r"reason\s+for\s+visit",
        r"cc\s*:",
    ]),
    ("hpi", [
        r"history\s+of\s+present\s+illness",
        r"\bHPI\b",
        r"present\s+illness",
    ]),
    ("pmh", [
        r"past\s+(?:medical\s+)?history",
        r"\bPMH\b",
        r"medical\s+history",
    ]),
    ("surgical_history", [
        r"surgical\s+(?:history|hx)",
        r"past\s+surgical",
        r"\bPSH\b",
    ]),
    ("family_history", [
        r"family\s+history",
        r"\bFH\b",
    ]),
    ("social_history", [
        r"social\s+history",
        r"\bSH\b",
    ]),
    ("review_of_systems", [
        r"review\s+of\s+systems",
        r"\bROS\b",
    ]),
    ("active_problem_list", [
        r"(?:active\s+)?problem\s+list\s*(?::|\s*active\s*:?)?",
        r"problem\s+list\s*:\s*active",
        r"active\s+diagnoses",
        r"active\s+problems",
    ]),
    ("medications", [
        r"(?:current\s+)?medications?",
        r"e-?prescription",
        r"medication\s+list",
        r"med(?:ication)?\s+reconciliation",
    ]),
    ("allergies", [
        r"allergi(?:es|c\s+reactions?)",
        r"drug\s+allergi(?:es)?",
        r"\bNKDA\b",
    ]),
    ("vitals", [
        r"vital\s+signs?",
        r"\bVS\b",
        r"vitals?\s*:",
    ]),
    ("physical_exam", [
        r"physical\s+exam(?:ination)?",
        r"objective\s+(?:findings?|data)",
        r"\bPE\b",
        r"\bExam\b",
    ]),
    ("labs", [
        r"laboratory\s+(?:results?|data|findings?)",
        r"\bLabs?\b",
        r"lab(?:oratory)?\s+values?",
        r"diagnostic\s+results?",
        r"lab(?:oratory)?\s+results?",
    ]),
    ("assessment", [
        r"assessment\s*(?:and\s+plan)?",
        r"assessment\s*/\s*plan",
        r"impression\s*(?:and\s+plan)?",
        r"\bA/P\b",
        r"\bA&P\b",
    ]),
    ("plan", [
        r"\bplan\b",
        r"treatment\s+plan",
    ]),
    ("subjective", [
        r"\bsubjective\b",
        r"\bS\s*:",
    ]),
    ("objective", [
        r"\bobjective\b",
        r"\bO\s*:",
    ]),
]

# Single compiled pattern that matches any known section header.
_ALL_HEADER_PATTERN = re.compile(
    r"(?:^|\n)\s*("
    + "|".join(
        "(?:" + "|".join(pats) + ")"
        for _, pats in _SECTION_HEADERS
    )
    + r")\s*[:\-\u2013\u2014]?\s*\n?",
    re.IGNORECASE | re.MULTILINE,
)


def _match_to_section_key(header_text: str) -> str:
    """Return the canonical section key for a matched header string."""
    ht = header_text.strip().lower()
    for key, pats in _SECTION_HEADERS:
        for pat in pats:
            if re.search(pat, ht, re.IGNORECASE):
                return key
    return "unstructured"


# ---------------------------------------------------------------------------
# Negation patterns
# ---------------------------------------------------------------------------
# Each tuple: (compiled_full_phrase_pattern, short_type_label)
_NEGATION_ENTRIES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"(denies?\s+.{3,80}?)(?:[.;,\n]|$)", re.IGNORECASE), "denies"),
    (re.compile(r"(no\s+evidence\s+of\s+.{3,80}?)(?:[.;,\n]|$)", re.IGNORECASE), "no_evidence_of"),
    (re.compile(r"(ruled?\s*out\s+.{3,80}?)(?:[.;,\n]|$)", re.IGNORECASE), "ruled_out"),
    (re.compile(r"(negative\s+for\s+.{3,80}?)(?:[.;,\n]|$)", re.IGNORECASE), "negative_for"),
    (re.compile(r"(no\s+(?:history|hx|known)\s+of\s+.{3,80}?)(?:[.;,\n]|$)", re.IGNORECASE), "no_history_of"),
    (re.compile(r"(not\s+consistent\s+with\s+.{3,80}?)(?:[.;,\n]|$)", re.IGNORECASE), "not_consistent_with"),
    (re.compile(r"(without\s+(?:evidence\s+of\s+)?.{3,80}?)(?:[.;,\n]|$)", re.IGNORECASE), "without"),
    (re.compile(r"(absence\s+of\s+.{3,80}?)(?:[.;,\n]|$)", re.IGNORECASE), "absence_of"),
]

# Keyword extraction patterns (group 1 = the negated condition text)
_NEGATION_KEYWORD_PATTERNS: list[re.Pattern] = [
    re.compile(r"\bdenies?\b\s+(.{3,80}?)(?:[.;,\n]|$)", re.IGNORECASE),
    re.compile(r"\bno\s+evidence\s+of\b\s+(.{3,80}?)(?:[.;,\n]|$)", re.IGNORECASE),
    re.compile(r"\bruled?\s*out\b\s+(.{3,80}?)(?:[.;,\n]|$)", re.IGNORECASE),
    re.compile(r"\bnegative\s+for\b\s+(.{3,80}?)(?:[.;,\n]|$)", re.IGNORECASE),
    re.compile(r"\bno\s+(?:history\s+of|hx\s+of|known)\b\s+(.{3,80}?)(?:[.;,\n]|$)", re.IGNORECASE),
    re.compile(r"\bnot\s+consistent\s+with\b\s+(.{3,80}?)(?:[.;,\n]|$)", re.IGNORECASE),
    re.compile(r"\bwithout\b\s+(?:evidence\s+of\s+)?(.{3,80}?)(?:[.;,\n]|$)", re.IGNORECASE),
    re.compile(r"\babsence\s+of\b\s+(.{3,80}?)(?:[.;,\n]|$)", re.IGNORECASE),
]


# ---------------------------------------------------------------------------
# Lab extraction patterns
# ---------------------------------------------------------------------------
# Each entry: (lab_name, list_of_regex_strings, default_unit)
# Group 1 = numeric value; Group 2 (optional) = unit from the note itself.
_LAB_PATTERNS: list[tuple[str, list[str], str]] = [
    ("HbA1c",       [r"(?:HbA1[Cc]|A1C|hemoglobin\s*A1c)\s*[:\s]*(\d+\.?\d*)\s*(%?)"],  "%"),
    ("eGFR",        [r"eGFR\s*[:\s]*(\d+\.?\d*)\s*(mL/min[^\s,;]*)?"],                   "mL/min/1.73m2"),
    ("Creatinine",  [r"(?:serum\s+)?creatinine\s*[:\s]*(\d+\.?\d*)\s*(mg/dL)?"],         "mg/dL"),
    ("BUN",         [r"\bBUN\b\s*[:\s]*(\d+\.?\d*)\s*(mg/dL)?"],                         "mg/dL"),
    ("LDL",         [r"LDL(?:-C|[\s\-]cholesterol)?\s*[:\s]*(\d+\.?\d*)\s*(mg/dL)?"],    "mg/dL"),
    ("HDL",         [r"HDL(?:-C|[\s\-]cholesterol)?\s*[:\s]*(\d+\.?\d*)\s*(mg/dL)?"],    "mg/dL"),
    ("Triglycerides",[r"(?:triglycerides?|TG)\s*[:\s]*(\d+\.?\d*)\s*(mg/dL)?"],          "mg/dL"),
    ("Hgb",         [r"(?:Hgb|Hemoglobin|Hb)\s*[:\s]*(\d+\.?\d*)\s*(g/dL)?"],           "g/dL"),
    ("WBC",         [r"\bWBC\b\s*[:\s]*(\d+\.?\d*)\s*(K/[uμ]L|x10[³3]/[uμ]L)?"],       "K/uL"),
    ("Platelets",   [r"(?:Platelets?|PLT)\s*[:\s]*(\d+\.?\d*)\s*(K/[uμ]L|x10[³3]/[uμ]L)?"], "K/uL"),
    ("Sodium",      [r"\bNa\b\s*[:\s]*(\d+\.?\d*)\s*(mEq/L|mmol/L)?"],                  "mEq/L"),
    ("Potassium",   [r"\bK\b\s*[:\s]*(\d+\.?\d*)(?:\s+L)?\s*(mEq/L|mmol/L)?"],          "mEq/L"),
    ("TSH",         [r"\bTSH\b\s*[:\s]*(\d+\.?\d*)\s*(mIU/L|uIU/mL)?"],                "mIU/L"),
    ("INR",         [r"\bINR\b\s*[:\s]*(\d+\.?\d*)"],                                    ""),
    ("BMI",         [r"\bBMI\b\s*[:\s]*(\d+\.?\d*)\s*(kg/m[²2])?"],                     "kg/m2"),
    ("O2 Sat",      [r"(?:O2\s*Sat|SpO2|Pulse\s*Ox)\s*[:\s]*(\d+\.?\d*)\s*(%?)"],       "%"),
    ("GDS",         [r"(?:GDS|Geriatric\s+Depression\s+Scale)\s*[:\s]*(\d+)\s*/\s*15"],  "/15"),
    ("CDT",         [r"(?:CDT|Clock[\s\-]?Drawing)\s*[:\s]*(\d)\s*/\s*5"],               "/5"),
]

# Date pattern to search near each extracted lab value
_LAB_DATE_PATTERN = re.compile(
    r"(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}|\d{4}[/\-]\d{1,2}[/\-]\d{1,2})"
)

# Abnormality thresholds — (operator_string, threshold_float)
_ABNORMAL_THRESHOLDS: dict[str, tuple[str, float]] = {
    "HbA1c":       (">=", 5.7),
    "eGFR":        ("<",  60.0),
    "Creatinine":  (">",  1.2),
    "BUN":         (">",  20.0),
    "LDL":         (">=", 130.0),
    "HDL":         ("<",  40.0),
    "Triglycerides":(">=", 150.0),
    "Hgb":         ("<",  12.0),
    "WBC":         (">",  11.0),
    "Platelets":   ("<",  150.0),
    "Sodium":      ("<",  135.0),
    "Potassium":   (">",  5.0),
    "TSH":         (">",  4.0),
    "INR":         (">",  1.1),
    "BMI":         (">=", 30.0),
    "O2 Sat":      ("<",  95.0),
    "GDS":         (">=", 5.0),
    "CDT":         ("<=", 3.0),
}

def _is_abnormal(lab_name: str, value: float) -> bool:
    """Return True if *value* crosses the clinical abnormality threshold."""
    entry = _ABNORMAL_THRESHOLDS.get(lab_name)
    if not entry:
        return False
    op, threshold = entry
    return {
        ">=": value >= threshold,
        ">":  value > threshold,
        "<=": value <= threshold,
        "<":  value < threshold,
    }.get(op, False)


# ---------------------------------------------------------------------------
# Vitals patterns
# ---------------------------------------------------------------------------
_VITAL_PATTERNS: dict[str, list[re.Pattern]] = {
    "bp": [
        re.compile(r"\bBP\b\s*[:\s]*(\d{2,3})\s*/\s*(\d{2,3})", re.IGNORECASE),
        re.compile(r"\bblood\s+pressure\b\s*[:\s]*(\d{2,3})\s*/\s*(\d{2,3})", re.IGNORECASE),
    ],
    "pulse": [
        re.compile(r"\b(?:HR|Heart\s*Rate|Pulse)\s*[:\s]*(\d{2,3})\s*(?:bpm)?", re.IGNORECASE),
    ],
    "temp": [
        re.compile(r"\b(?:Temp|Temperature)\b\s*[:\s]*(\d{2,3}\.?\d*)", re.IGNORECASE),
    ],
    "weight": [
        re.compile(r"\b(?:Weight|Wt)\s*[:\s]*(\d{2,4}\.?\d*)\s*(?:lbs?|kg)?", re.IGNORECASE),
    ],
    "height": [
        re.compile(r"\b(?:Height|Ht)\s*[:\s]*(\d{1,3}\.?\d*)\s*(?:in(?:ches)?|cm|ft)?", re.IGNORECASE),
    ],
    "bmi": [
        re.compile(r"\bBMI\s*[:\s]*(\d{2,3}\.?\d*)", re.IGNORECASE),
    ],
    "o2_sat": [
        re.compile(r"(?:O2\s*Sat|SpO2|Pulse\s*Ox)\s*[:\s]*(\d{2,3}\.?\d*)\s*%?", re.IGNORECASE),
    ],
    "rr": [
        re.compile(r"\b(?:RR|Resp(?:iratory)?\s*Rate)\s*[:\s]*(\d{1,2})\s*(?:/min)?", re.IGNORECASE),
    ],
}


# ---------------------------------------------------------------------------
# Demographics patterns
# ---------------------------------------------------------------------------
_AGE_PATTERNS: list[re.Pattern] = [
    re.compile(r"(\d{1,3})[- ]?(?:year|yr|y)[- ]?old", re.IGNORECASE),
    re.compile(r"\bage\s*[:\-]?\s*(\d{1,3})\b", re.IGNORECASE),
    re.compile(r"(\d{1,3})\s+(?:M|F|Male|Female)\s+(?:with|presents?)", re.IGNORECASE),
]

_DOB_PATTERN = re.compile(
    r"(?:DOB|Date\s+of\s+Birth)\s*[:\s]*(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}|\d{4}[/\-]\d{1,2}[/\-]\d{1,2})",
    re.IGNORECASE,
)

_SEX_PRIORITY: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(female|woman|girl)\b",      re.IGNORECASE), "female"),
    (re.compile(r"\b(male|man|boy)\b",            re.IGNORECASE), "male"),
    (re.compile(r"\b(she|her)\b",                 re.IGNORECASE), "female"),
    (re.compile(r"\b(he|his)\b",                  re.IGNORECASE), "male"),
    (re.compile(r"(?:^|\n|\s)(\d{1,3})[- ]?F\b", re.IGNORECASE), "female"),
    (re.compile(r"(?:^|\n|\s)(\d{1,3})[- ]?M\b", re.IGNORECASE), "male"),
]


# ---------------------------------------------------------------------------
# Medication parsing helpers
# ---------------------------------------------------------------------------
_MED_SECTION_BREAK = re.compile(
    r"^(?:allergies?|vitals?|assessment|plan|exam|physical|labs?|laboratory)",
    re.IGNORECASE,
)

_MED_STOP_LINE = re.compile(
    r"^\s*(?:"
    r"\d[\d\.]*\s*(?:mg|mcg|g|ml|mL|units?|u|IU|%)|"
    r"(?:QD|BID|TID|QID|PRN|AC|PC|HS|SL|INH|SC|IM|IV|PO|TOP|ODT)|"
    r"(?:tablet|capsule|cap|tab|patch|cream|gel|ointment|spray|solution|suspension|injection|inhaler|puff)s?"
    r")\s*$",
    re.IGNORECASE,
)

_MED_TRAILING_DOSE = re.compile(
    r"\s+\d[\d\.]*\s*(?:mg|mcg|g|ml|mL|units?|u|IU|%)\b.*$",
    re.IGNORECASE,
)

_MED_FREQ_PATTERN = re.compile(
    r"\b(QD|BID|TID|QID|PRN|once\s+daily|twice\s+daily|three\s+times\s+daily|"
    r"every\s+\d+\s+hours?|daily|weekly|monthly|at\s+bedtime|HS)\b",
    re.IGNORECASE,
)

_MED_DOSE_PATTERN = re.compile(
    r"(\d[\d\.]*\s*(?:mg|mcg|g|mL|ml|units?|u|IU|%)(?:/\w+)?)",
    re.IGNORECASE,
)

_MED_INDICATION_PATTERN = re.compile(r"\bfor\s+(.{3,50}?)(?:[,;.]|$)", re.IGNORECASE)

_MED_STRIP_TRAILING_TOKENS = re.compile(
    r"\s+(?:QD|BID|TID|QID|PRN|daily|once|twice|tablet|capsule|cap|tab|"
    r"patch|cream|gel|ointment|spray|inhaler|puff|oral|SL|SC|IM|IV|PO|TOP).*$",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class LabValue:
    """A single extracted lab measurement (used by Stage 2 prompt construction)."""
    value: float | str
    unit: str
    date: str | None
    abnormal: bool
    reference_range: str | None
    context_line: str = ""


@dataclass
class ExtractionResult:
    """
    Complete output of Stage 1 rule-based extraction.

    Field names align with the design doc §3.1 PreExtractionResult contract
    while extending it with the additional fields requested in the task spec.
    """

    # ICD-10 codes found verbatim anywhere in the note text
    explicit_icd_codes: list[dict]       # [{code, section, line_number, context}]

    # Codes extracted specifically from the Active Problem List section
    # — these carry the highest obligation in Stage 3 reconciliation
    problem_list_codes: list[dict]       # [{title, icd_code, status}]

    # Codes extracted from the Assessment / Assessment & Plan section
    assessment_codes: list[dict]         # [{icd_code, description, status, notes}]

    # Parsed lab measurements
    lab_values: list[dict]               # [{lab_name, value, unit, date, abnormal, context_line}]

    # Medications parsed from medication sections
    medications: list[dict]              # [{drug_name, dosage, frequency, indication}]

    # Parsed vitals
    vitals: dict                         # {bp_sys, bp_dia, bmi, o2_sat, weight, pulse, temp, rr}

    # Parsed demographics
    demographics: dict                   # {age, sex, dob_if_found}

    # Negation phrases
    negation_phrases: list[dict]         # [{phrase, condition_negated, line_number, negation_type}]

    # Raw section text keyed by canonical section name
    note_sections: dict                  # {section_name: section_text}

    # Union of ALL ICD codes found in any section — normalised, deduplicated.
    # Each code appears in both dotted (E11.22) and dot-free (E1122) forms so
    # Stage 3 set comparisons work regardless of the format source systems emit.
    all_unique_codes: set                # set[str]

    # HCC summary metrics (populated by _enrich_with_hcc in run_stage1)
    # hcc_carrying_count: number of unique extracted codes that map to an HCC.
    # total_potential_raf: raw sum of HCC coefficients across all three code
    #   lists before hierarchy/interaction adjustments — useful for Stage 3
    #   sanity-checking against the Stage 2 RAF estimate.
    hcc_carrying_count: int = 0
    total_potential_raf: float = 0.0

    # Parser metadata (always populated)
    parser_version: str = PARSER_VERSION
    parse_time_ms: float = 0.0


# ---------------------------------------------------------------------------
# Helper: build a line-start offset index for O(log n) line number lookups
# ---------------------------------------------------------------------------

def _build_line_index(text: str) -> list[int]:
    """Return a list of character offsets where each line starts (0-based)."""
    offsets: list[int] = [0]
    for i, ch in enumerate(text):
        if ch == "\n":
            offsets.append(i + 1)
    return offsets


def _char_to_lineno(offsets: list[int], char_pos: int) -> int:
    """Return the 1-based line number for *char_pos* using binary search."""
    lo, hi = 0, len(offsets) - 1
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if offsets[mid] <= char_pos:
            lo = mid
        else:
            hi = mid - 1
    return lo + 1


# ---------------------------------------------------------------------------
# 1. ICD-10 code extraction
# ---------------------------------------------------------------------------

def extract_icd_codes(text: str) -> list[dict]:
    """
    Find ALL ICD-10-CM codes in *text* using regex.

    Pattern: [A-TV-Z]\\d{2,3}\\.?\\d{0,4} with word boundary enforcement.

    Returns a list of dicts:
        code        — normalised ICD-10 code (uppercase, dot preserved)
        section     — canonical section name (populated later by run_stage1)
        line_number — 1-based line number in the original text
        context     — up to 160 characters of surrounding text
    """
    if not text:
        return []

    results: list[dict] = []
    seen_positions: set[int] = set()
    line_offsets = _build_line_index(text)

    for match in _ICD10_PATTERN.finditer(text):
        start = match.start()
        if start in seen_positions:
            continue
        seen_positions.add(start)

        raw_code = match.group(1)
        code = _normalize_icd(raw_code)

        if not _is_valid_icd_structure(code):
            continue

        line_num = _char_to_lineno(line_offsets, start)
        ctx_start = max(0, start - 50)
        ctx_end   = min(len(text), match.end() + 100)
        context   = text[ctx_start:ctx_end].replace("\n", " ").strip()

        results.append({
            "code":        code,
            "section":     "unknown",   # back-filled in run_stage1
            "line_number": line_num,
            "context":     context,
        })

    return results


def _assign_sections_to_codes(
    codes: list[dict],
    note_sections: dict[str, str],
) -> list[dict]:
    """
    Back-fill the 'section' key on each code dict by checking which section's
    text contains the code string.  Prefers active_problem_list > assessment.

    Mutates and returns *codes*.
    """
    # Pre-uppercase section texts for O(1) lookup
    upper_sections: dict[str, str] = {
        k: v.upper()
        for k, v in note_sections.items()
        if k != "unstructured"
    }

    for entry in codes:
        code = entry["code"]
        matched: list[str] = [k for k, v in upper_sections.items() if code in v]
        if matched:
            if "active_problem_list" in matched:
                entry["section"] = "active_problem_list"
            elif "assessment" in matched:
                entry["section"] = "assessment"
            else:
                entry["section"] = matched[0]

    return codes


# ---------------------------------------------------------------------------
# 2. Problem list extraction
# ---------------------------------------------------------------------------

def extract_problem_list(text: str) -> list[dict]:
    """
    Parse the Active Problem List section of *text*.

    Handles multiple formats encountered in real clinical notes:
        A.  I50.22 - Chronic systolic heart failure; Confirmed
        B.  Type 2 Diabetes Mellitus (E11.9)
        C.  E11.22 Heart failure with preserved EF
        D.  • CKD Stage 3b         (free-text, no code)
        E.  1. Hypertension        (numbered, no code)

    Returns a list of dicts:
        title    — condition description (free text)
        icd_code — ICD-10 code if present, else None
        status   — "confirmed" | "active" | "chronic" | "resolved" | "unspecified"
    """
    if not text:
        return []

    results: list[dict] = []
    seen_titles: set[str] = set()

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        # Skip lines that are themselves section headers
        if re.match(
            r"^(?:active\s+)?problem\s+list|^active\s+(?:diagnoses|problems)",
            line, re.IGNORECASE,
        ):
            continue

        icd_code: str | None = None
        status = "unspecified"
        title = ""

        # --- Format A: CODE - Description; Status ---
        ma = re.match(
            r"^(?:\d+[.):\s]+)?([A-TV-Z][0-9]{2}(?:\.[A-Z0-9]{1,4})?)\s*[-\u2013\u2014:]\s*(.+?)(?:;\s*(.+))?$",
            line, re.IGNORECASE,
        )
        if ma and _is_valid_icd_structure(ma.group(1)):
            icd_code = _normalize_icd(ma.group(1))
            title    = ma.group(2).strip()
            status   = (ma.group(3) or "unspecified").strip().lower()

        else:
            # --- Format B: Description (CODE) ---
            mb = re.search(
                r"\(([A-TV-Z][0-9]{2}(?:\.[A-Z0-9]{1,4})?)\)\s*$",
                line, re.IGNORECASE,
            )
            if mb and _is_valid_icd_structure(mb.group(1)):
                icd_code = _normalize_icd(mb.group(1))
                title    = line[:mb.start()].strip(" -\u2013\u2022\u2014\u25cf1234567890.()")
            else:
                # --- Format C: CODE Description (inline, no separator) ---
                mc = re.match(
                    r"^(?:\d+[.):\s]+)?([A-TV-Z][0-9]{2}(?:\.[A-Z0-9]{1,4})?)\s+(.+)$",
                    line, re.IGNORECASE,
                )
                if mc and _is_valid_icd_structure(mc.group(1)):
                    icd_code = _normalize_icd(mc.group(1))
                    title    = mc.group(2).strip()
                else:
                    # --- Format D / E: plain text, possibly bulleted or numbered ---
                    title = re.sub(
                        r"^[\d]+[.):\s]+|^[-\u2013\u2022\u2014\u25cf*\s]+",
                        "", line,
                    ).strip()
                    title = re.sub(
                        r"^\s*(?:confirmed|active|chronic|resolved|inactive)\s*[:;]?\s*",
                        "", title, flags=re.IGNORECASE,
                    ).strip()

        # Normalise status to a controlled vocabulary
        for keyword in ("confirmed", "active", "chronic", "resolved", "historical", "inactive", "stable"):
            if keyword in status.lower():
                status = keyword
                break

        if not title:
            continue
        title_key = title.lower().strip()
        if title_key in seen_titles:
            continue
        seen_titles.add(title_key)

        results.append({"title": title, "icd_code": icd_code, "status": status})

    return results


# ---------------------------------------------------------------------------
# 3. Assessment section extraction
# ---------------------------------------------------------------------------

def extract_assessment(text: str) -> list[dict]:
    """
    Parse the Assessment (or Assessment & Plan) section.

    Handles formats including:
        A.  I50.22 - Chronic systolic heart failure; Confirmed
        B.  1. E11.22 - DM Type 2, uncontrolled -- start Ozempic
        C.  #3 CKD Stage 3b (N18.32) -- monitor BMP
        D.  Hypertension - well controlled on current regimen

    Returns a list of dicts:
        icd_code    — ICD-10 code if present, else None
        description — condition description
        status      — "confirmed" | "stable" | "uncontrolled" | "unspecified" | …
        notes       — plan notes, if any
    """
    if not text:
        return []

    results: list[dict] = []
    seen: set[str] = set()

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        # Skip pure plan action lines
        if re.match(
            r"^[-*\u2022]\s+(?:continue|start|stop|refer|follow|monitor|order|obtain|schedule)\b",
            line, re.IGNORECASE,
        ):
            continue

        icd_code: str | None = None
        description = ""
        status = "unspecified"
        notes = ""

        # Format A/B: CODE - Description [; status or -- plan notes]
        ma = re.match(
            r"^(?:\d+[.):\s]*|#\d+\s*)?([A-TV-Z][0-9]{2}(?:\.[A-Z0-9]{1,4})?)\s*[-\u2013\u2014:]\s*(.+?)(?:[;\u2014\-]{1,2}\s*(.+))?$",
            line, re.IGNORECASE,
        )
        if ma and _is_valid_icd_structure(ma.group(1)):
            icd_code = _normalize_icd(ma.group(1))
            rest     = ma.group(2).strip()
            trailer  = (ma.group(3) or "").strip()

            status_m = re.search(
                r"\b(confirmed|active|chronic|resolved|historical|stable|worsening|uncontrolled|controlled)\b",
                rest, re.IGNORECASE,
            )
            if status_m:
                description = rest[:status_m.start()].strip(", ")
                status      = status_m.group(1).lower()
                notes       = rest[status_m.end():].strip(", ")
                if trailer:
                    notes = (notes + " -- " + trailer).strip(" -")
            else:
                description = rest
                notes       = trailer
        else:
            # Format C: Description (CODE) [-- notes]
            mb = re.search(
                r"\(([A-TV-Z][0-9]{2}(?:\.[A-Z0-9]{1,4})?)\)",
                line, re.IGNORECASE,
            )
            if mb and _is_valid_icd_structure(mb.group(1)):
                icd_code    = _normalize_icd(mb.group(1))
                description = line[:mb.start()].strip(" -\u2013\u2022\u2014\u25cf1234567890.#()")
                notes       = line[mb.end():].strip(" -\u2013\u2014;")
            else:
                # Format D: plain numbered/bulleted diagnosis, no code
                plain = re.match(
                    r"^(?:\d+[.):\s]*|#\d+\s*|[-\u2022*]\s*)(.{5,})$",
                    line, re.IGNORECASE,
                )
                if plain:
                    parts     = re.split(r"\s*[-\u2013\u2014;]\s*", plain.group(1), maxsplit=1)
                    description = parts[0].strip()
                    notes       = parts[1].strip() if len(parts) > 1 else ""
                else:
                    continue

        if not description and not icd_code:
            continue

        key = (icd_code or "").lower() + description.lower()[:40]
        if key in seen:
            continue
        seen.add(key)

        results.append({
            "icd_code":    icd_code,
            "description": description,
            "status":      status,
            "notes":       notes,
        })

    return results


# ---------------------------------------------------------------------------
# 4. Lab value extraction
# ---------------------------------------------------------------------------

def extract_lab_values(text: str) -> list[dict]:
    """
    Extract lab measurements from free text.

    Pattern library mirrors lab_suspect_engine.py but extends each match with
    unit, date, abnormality flag, and context line for Stage 3 evidence.

    Returns a list of dicts compatible with the LabValue dataclass:
        lab_name      — human-readable name (e.g. "HbA1c")
        value         — numeric value (float)
        unit          — unit string (from note or default)
        date          — nearest date found in context window (or None)
        abnormal      — True if value exceeds clinical threshold
        reference_range — always None (no structured reference range in free text)
        context_line  — the raw note line containing the match
    """
    if not text:
        return []

    results: list[dict] = []
    seen: set[tuple[str, float]] = set()

    for lab_name, patterns, default_unit in _LAB_PATTERNS:
        for pattern in patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                try:
                    value = float(match.group(1))
                except (IndexError, ValueError):
                    continue

                key = (lab_name, value)
                if key in seen:
                    continue
                seen.add(key)

                # Unit: prefer group 2 from the match if present
                try:
                    unit = (match.group(2) or "").strip() or default_unit
                except IndexError:
                    unit = default_unit

                # Date: search a 120-char window around the match
                win_s = max(0, match.start() - 60)
                win_e = min(len(text), match.end() + 60)
                date_m = _LAB_DATE_PATTERN.search(text[win_s:win_e])
                date_str = date_m.group(1) if date_m else None

                # Context line: the full line containing the match
                line_s = text.rfind("\n", 0, match.start()) + 1
                line_e = text.find("\n", match.end())
                line_e = line_e if line_e != -1 else len(text)
                context_line = text[line_s:line_e].strip()

                results.append({
                    "lab_name":        lab_name,
                    "value":           value,
                    "unit":            unit,
                    "date":            date_str,
                    "abnormal":        _is_abnormal(lab_name, value),
                    "reference_range": None,
                    "context_line":    context_line[:200],
                })

    return results


# ---------------------------------------------------------------------------
# 5. Medication extraction
# ---------------------------------------------------------------------------

def extract_medications(text: str) -> list[dict]:
    """
    Parse the medications section of *text*.

    Handles:
        - Numbered lists:  "1. Metformin 500mg BID"
        - Bulleted lists:  "• Lisinopril 10mg daily"
        - Inline tables:   "Metformin    500mg    twice daily    Diabetes"
        - Paragraph form:  "Patient is on metformin 500mg twice daily…"

    Returns a list of dicts:
        drug_name   — normalised lowercase drug name
        dosage      — dose string (may be empty)
        frequency   — frequency string (may be empty)
        indication  — indication text if parseable (may be empty)
    """
    if not text:
        return []

    results: list[dict] = []
    seen_drugs: set[str] = set()

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if _MED_SECTION_BREAK.match(line):
            break

        # Strip leading list bullets and numbers
        clean = re.sub(r"^[\d]+[.):\s]+|^[-\u2022*\u2192]\s*", "", line).strip()
        if len(clean) < 3:
            continue

        # Skip lines that are entirely dose/frequency tokens
        if _MED_STOP_LINE.match(clean):
            continue

        dose_m      = _MED_DOSE_PATTERN.search(clean)
        freq_m      = _MED_FREQ_PATTERN.search(clean)
        indication_m = _MED_INDICATION_PATTERN.search(clean)

        dosage     = dose_m.group(1).strip()    if dose_m      else ""
        frequency  = freq_m.group(1).strip().lower() if freq_m else ""
        indication = indication_m.group(1).strip()   if indication_m else ""

        # Drug name: text up to the first dose token, then strip trailing junk
        name_text = _MED_TRAILING_DOSE.sub("", clean).strip()
        name_text = _MED_STRIP_TRAILING_TOKENS.sub("", name_text).strip()

        if len(name_text) < 2:
            continue

        drug_name = name_text.lower().strip(" ,;:()")
        if drug_name in seen_drugs:
            continue
        seen_drugs.add(drug_name)

        results.append({
            "drug_name":  drug_name,
            "dosage":     dosage,
            "frequency":  frequency,
            "indication": indication,
        })

    return results


# ---------------------------------------------------------------------------
# 6. Vital signs extraction
# ---------------------------------------------------------------------------

def extract_vitals(text: str) -> dict:
    """
    Parse vital signs from free text.

    Returns a flat dict with keys:
        bp_sys, bp_dia, pulse, temp, weight, height, bmi, o2_sat, rr
    Values are numeric (int or float) or None when not found.
    """
    result: dict[str, Any] = {
        "bp_sys": None, "bp_dia": None, "pulse": None, "temp": None,
        "weight": None, "height": None, "bmi": None, "o2_sat": None, "rr": None,
    }
    if not text:
        return result

    for field_name, patterns in _VITAL_PATTERNS.items():
        for pat in patterns:
            m = pat.search(text)
            if not m:
                continue
            try:
                if field_name == "bp":
                    result["bp_sys"] = int(m.group(1))
                    result["bp_dia"] = int(m.group(2))
                elif field_name in ("pulse", "rr"):
                    result[field_name] = int(float(m.group(1)))
                else:
                    result[field_name] = float(m.group(1))
            except (IndexError, ValueError):
                continue
            break  # first matching pattern wins per field

    return result


# ---------------------------------------------------------------------------
# 7. Demographics extraction
# ---------------------------------------------------------------------------

def extract_demographics(text: str) -> dict:
    """
    Parse patient age and sex from the note.

    Returns:
        age          — integer age, or None
        sex          — "male" | "female" | None
        dob_if_found — DOB string, or None
    """
    result: dict[str, Any] = {"age": None, "sex": None, "dob_if_found": None}
    if not text:
        return result

    # Age
    for pat in _AGE_PATTERNS:
        m = pat.search(text)
        if m:
            raw = m.group(1)
            if "/" in raw or "-" in raw:
                continue
            try:
                age = int(raw)
                if 0 < age < 130:
                    result["age"] = age
                    break
            except ValueError:
                continue

    # DOB
    dob_m = _DOB_PATTERN.search(text)
    if dob_m:
        result["dob_if_found"] = dob_m.group(1)

    # Sex — work through patterns in confidence order; stop at first match
    for pat, sex_label in _SEX_PRIORITY:
        if pat.search(text):
            result["sex"] = sex_label
            break

    return result


# ---------------------------------------------------------------------------
# 8. Negation extraction
# ---------------------------------------------------------------------------

def extract_negations(text: str) -> list[dict]:
    """
    Find negation phrases in *text*.

    Detects:
        - "denies chest pain"
        - "no evidence of heart failure"
        - "ruled out PE"
        - "negative for UTI"
        - "no history of diabetes"
        - "not consistent with CHF"
        - "without evidence of sepsis"
        - "absence of focal neurological deficits"

    Returns a list of dicts:
        phrase            — the matched phrase (truncated to 150 chars)
        condition_negated — text following the negation keyword
        line_number       — 1-based line number
        negation_type     — short label ("denies", "ruled_out", etc.)
    """
    if not text:
        return []

    results: list[dict] = []
    seen_conditions: set[str] = set()
    line_offsets = _build_line_index(text)

    for full_pat, neg_type in _NEGATION_ENTRIES:
        for m in full_pat.finditer(text):
            phrase = m.group(1).strip()

            # Extract the condition text (after the negation keyword)
            condition = ""
            for kw_pat in _NEGATION_KEYWORD_PATTERNS:
                kw_m = kw_pat.match(phrase)
                if kw_m:
                    condition = kw_m.group(1).strip().rstrip(" ,;.")
                    break
            if not condition:
                condition = phrase.rstrip(" ,;.")

            condition_key = condition.lower()[:60]
            if condition_key in seen_conditions:
                continue
            seen_conditions.add(condition_key)

            line_num = _char_to_lineno(line_offsets, m.start())
            results.append({
                "phrase":            phrase[:150],
                "condition_negated": condition,
                "line_number":       line_num,
                "negation_type":     neg_type,
            })

    return results


# ---------------------------------------------------------------------------
# 9. Note section segmentation
# ---------------------------------------------------------------------------

def parse_note_sections(text: str) -> dict[str, str]:
    """
    Split a clinical note into named sections using header pattern matching.

    Returns a dict mapping canonical section names to raw section text.
    Text that does not belong to any recognised section is stored under
    "unstructured".

    Recognised section keys include:
        chief_complaint, hpi, pmh, surgical_history, family_history,
        social_history, review_of_systems, active_problem_list,
        medications, allergies, vitals, physical_exam, labs,
        assessment, plan, subjective, objective

    When the same section header appears more than once (e.g. two medication
    blocks), the section texts are concatenated.
    """
    if not text:
        return {"unstructured": ""}

    header_matches = list(_ALL_HEADER_PATTERN.finditer(text))
    if not header_matches:
        return {"unstructured": text}

    sections: dict[str, str] = {}

    # Text before the first header
    pre_text = text[:header_matches[0].start()].strip()
    if pre_text:
        sections["unstructured"] = pre_text

    for i, match in enumerate(header_matches):
        key = _match_to_section_key(match.group(1))
        body_start = match.end()
        body_end   = header_matches[i + 1].start() if i + 1 < len(header_matches) else len(text)
        body       = text[body_start:body_end].strip()

        if key in sections:
            sections[key] = sections[key] + "\n" + body
        else:
            sections[key] = body

    return sections


# ---------------------------------------------------------------------------
# 10. HCC enrichment
# ---------------------------------------------------------------------------

def _enrich_with_hcc(code_list: list[dict]) -> list[dict]:
    """
    Mutate each code dict in *code_list* in-place, adding HCC mapping fields.

    Fields added to every item:
        hcc_code        — e.g. "HCC85", or None when the code is not risk-adjusting
        hcc_label       — human-readable HCC label, or None
        hcc_coefficient — CMS-HCC Model V28 relative factor (float), 0.0 if absent
        risk_adjusting  — True when the ICD-10 code maps to at least one HCC

    The lookup uses in-memory dicts from hccinfhir — no I/O, essentially O(1)
    per code.  The function is safe to call when hccinfhir is not installed
    (all fields are set to their "not risk-adjusting" defaults).

    The 'icd_code' key is checked first; 'code' is the fallback so that both
    explicit_icd_codes dicts (keyed 'code') and problem_list/assessment dicts
    (keyed 'icd_code') are handled by a single function.
    """
    for item in code_list:
        raw = item.get("icd_code") or item.get("code") or ""
        code_no_dot = raw.replace(".", "").upper()

        hcc_set = dx_to_cc_default.get((code_no_dot, "CMS-HCC Model V28"))
        if hcc_set:
            hcc = next(iter(hcc_set))
            hcc_key = f"HCC{hcc}"
            item["hcc_code"]        = hcc_key
            item["hcc_label"]       = labels_default.get((hcc, "CMS-HCC Model V28")) or ""
            item["hcc_coefficient"] = coefficients_default.get((hcc_key, "CMS-HCC Model V28")) or 0.0
            item["risk_adjusting"]  = True
        else:
            item["hcc_code"]        = None
            item["hcc_label"]       = None
            item["hcc_coefficient"] = 0.0
            item["risk_adjusting"]  = False

    return code_list


# ---------------------------------------------------------------------------
# 11. Main orchestrator
# ---------------------------------------------------------------------------

def run_stage1(
    clinical_note: str,
    problem_list: list[dict] | None = None,
    vitals_structured: dict | None = None,
) -> ExtractionResult:
    """
    Orchestrate all Stage 1 rule-based extractions.

    Parameters
    ----------
    clinical_note:
        Raw free-text clinical note (up to ~15 000 chars recommended).
    problem_list:
        Optional pre-structured problem list from OpenEMR.  Each dict should
        have at minimum a 'code' (or 'icd_code') key.  These codes are merged
        with codes parsed from the note so that diagnoses in the EHR system
        but not printed in the note body are still captured by Stage 1.
    vitals_structured:
        Optional structured vitals dict from OpenEMR (form_vitals row).
        Recognised keys: bps, bpd, pulse, temp, weight, height, BMI,
        oxygen_saturation, respiration.  Structured values take precedence
        over regex-parsed values when both are present.

    Returns
    -------
    ExtractionResult
        Fully populated Stage 1 result.  parse_time_ms is always set.
    """
    t_start = time.perf_counter()

    if not clinical_note:
        logger.warning("[Stage1] Empty clinical note passed to run_stage1")
        return ExtractionResult(
            explicit_icd_codes=[],
            problem_list_codes=[],
            assessment_codes=[],
            lab_values=[],
            medications=[],
            vitals={},
            demographics={},
            negation_phrases=[],
            note_sections={},
            all_unique_codes=set(),
            parser_version=PARSER_VERSION,
            parse_time_ms=0.0,
        )

    # ------------------------------------------------------------------
    # Step 1: Section segmentation — most other steps depend on this
    # ------------------------------------------------------------------
    note_sections = parse_note_sections(clinical_note)

    # ------------------------------------------------------------------
    # Step 2: ICD-10 code extraction across the full note text
    # ------------------------------------------------------------------
    explicit_icd_codes = extract_icd_codes(clinical_note)
    explicit_icd_codes = _assign_sections_to_codes(explicit_icd_codes, note_sections)

    # ------------------------------------------------------------------
    # Step 3: Problem list — parse from note, then merge OpenEMR data
    # ------------------------------------------------------------------
    pl_section = note_sections.get("active_problem_list", "")
    parsed_pl  = extract_problem_list(pl_section)

    if problem_list:
        existing_pl_codes: set[str] = {
            e["icd_code"] for e in parsed_pl if e.get("icd_code")
        }
        for pl_item in problem_list:
            raw_code = (
                pl_item.get("code")
                or pl_item.get("icd_code")
                or pl_item.get("icd10_code")
                or ""
            )
            title = (
                pl_item.get("title")
                or pl_item.get("condition")
                or pl_item.get("description")
                or ""
            )
            if raw_code:
                norm = _normalize_icd(raw_code)
                if _is_valid_icd_structure(norm) and norm not in existing_pl_codes:
                    parsed_pl.append({
                        "title":    title,
                        "icd_code": norm,
                        "status":   pl_item.get("status", "active"),
                    })
                    existing_pl_codes.add(norm)

    problem_list_codes = parsed_pl

    # ------------------------------------------------------------------
    # Step 4: Assessment extraction
    # ------------------------------------------------------------------
    assessment_section = note_sections.get("assessment", "")
    assessment_codes   = extract_assessment(assessment_section)

    # ------------------------------------------------------------------
    # Step 4b: HCC enrichment — annotate all three code lists with HCC
    #          mapping data so Stage 3 can compare HCC counts directly.
    #          In-memory dict lookups; negligible overhead.
    # ------------------------------------------------------------------
    _enrich_with_hcc(explicit_icd_codes)
    _enrich_with_hcc([e for e in problem_list_codes if e.get("icd_code") or e.get("code")])
    _enrich_with_hcc(assessment_codes)

    # ------------------------------------------------------------------
    # Step 5: Lab values — search the full note (labs may appear in HPI)
    # ------------------------------------------------------------------
    lab_values = extract_lab_values(clinical_note)

    # ------------------------------------------------------------------
    # Step 6: Medications
    # ------------------------------------------------------------------
    med_section = note_sections.get("medications", "")
    medications = extract_medications(med_section if med_section else clinical_note)

    # ------------------------------------------------------------------
    # Step 7: Vitals — parse from note, merge structured data
    # ------------------------------------------------------------------
    vitals_section = note_sections.get("vitals", "")
    vitals = extract_vitals(vitals_section if vitals_section else clinical_note)

    if vitals_structured:
        _VITALS_FIELD_MAP: dict[str, str] = {
            "bps":               "bp_sys",
            "bpd":               "bp_dia",
            "pulse":             "pulse",
            "temp":              "temp",
            "weight":            "weight",
            "height":            "height",
            "BMI":               "bmi",
            "oxygen_saturation": "o2_sat",
            "respiration":       "rr",
        }
        for src_key, dest_key in _VITALS_FIELD_MAP.items():
            raw = vitals_structured.get(src_key)
            if raw is not None:
                try:
                    parsed_val: Any = (
                        float(raw) if "." in str(raw) else int(float(raw))
                    )
                    vitals[dest_key] = parsed_val
                except (TypeError, ValueError):
                    pass

    # ------------------------------------------------------------------
    # Step 8: Demographics
    # ------------------------------------------------------------------
    demographics = extract_demographics(clinical_note)

    # ------------------------------------------------------------------
    # Step 9: Negations
    # ------------------------------------------------------------------
    negation_phrases = extract_negations(clinical_note)

    # ------------------------------------------------------------------
    # Step 10: all_unique_codes — union of every ICD code found anywhere
    #          Each code is stored in BOTH dotted and dot-free form so
    #          Stage 3 set operations are format-agnostic.
    # ------------------------------------------------------------------
    all_unique_codes: set[str] = set()

    def _add_code(c: str | None) -> None:
        if c:
            n = _normalize_icd(c)
            all_unique_codes.add(n)
            all_unique_codes.add(n.replace(".", ""))

    for entry in explicit_icd_codes:
        _add_code(entry.get("code"))
    for entry in problem_list_codes:
        _add_code(entry.get("icd_code"))
    for entry in assessment_codes:
        _add_code(entry.get("icd_code"))

    # ------------------------------------------------------------------
    # Step 10b: HCC summary metrics
    #   hcc_carrying_count — deduplicated by HCC code so that the same HCC
    #     reached via different ICD codes (e.g. E11.65 and E11.9 both mapping
    #     to HCC19) is counted once.  This mirrors how Stage 2 counts HCCs.
    #   total_potential_raf — raw coefficient sum before hierarchy; useful as
    #     a ceiling estimate for quick Stage 3 discrepancy checks.
    # ------------------------------------------------------------------
    _seen_hcc_for_summary: set[str] = set()
    _total_raf: float = 0.0

    def _accumulate_hcc_metrics(entries: list[dict]) -> None:
        nonlocal _total_raf
        for entry in entries:
            hcc = entry.get("hcc_code")
            coeff = entry.get("hcc_coefficient", 0.0)
            if hcc and hcc not in _seen_hcc_for_summary:
                _seen_hcc_for_summary.add(hcc)
                _total_raf += coeff

    _accumulate_hcc_metrics(explicit_icd_codes)
    _accumulate_hcc_metrics(problem_list_codes)
    _accumulate_hcc_metrics(assessment_codes)

    hcc_carrying_count = len(_seen_hcc_for_summary)
    total_potential_raf = round(_total_raf, 4)

    # ------------------------------------------------------------------
    # Timing + logging
    # ------------------------------------------------------------------
    parse_time_ms = (time.perf_counter() - t_start) * 1000

    logger.info(
        "[Stage1] v%s complete in %.1fms | "
        "explicit=%d  problem_list=%d  assessment=%d  "
        "labs=%d  meds=%d  negations=%d  sections=%s  unique_codes=%d  "
        "hcc_carrying=%d  potential_raf=%.4f",
        PARSER_VERSION,
        parse_time_ms,
        len(explicit_icd_codes),
        len(problem_list_codes),
        len(assessment_codes),
        len(lab_values),
        len(medications),
        len(negation_phrases),
        sorted(note_sections.keys()),
        len(all_unique_codes),
        hcc_carrying_count,
        total_potential_raf,
    )

    if parse_time_ms > 200:
        logger.warning(
            "[Stage1] Performance budget exceeded: %.1fms (target <200ms). "
            "Note length: %d chars.",
            parse_time_ms,
            len(clinical_note),
        )

    return ExtractionResult(
        explicit_icd_codes=explicit_icd_codes,
        problem_list_codes=problem_list_codes,
        assessment_codes=assessment_codes,
        lab_values=lab_values,
        medications=medications,
        vitals=vitals,
        demographics=demographics,
        negation_phrases=negation_phrases,
        note_sections=note_sections,
        all_unique_codes=all_unique_codes,
        hcc_carrying_count=hcc_carrying_count,
        total_potential_raf=total_potential_raf,
        parser_version=PARSER_VERSION,
        parse_time_ms=parse_time_ms,
    )
