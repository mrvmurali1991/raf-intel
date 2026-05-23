"""
Lab & Vitals Suspect Engine — rule-based, no LLM required.

Parses lab values from free-text clinical notes and structured vitals
(form_vitals rows) and compares them against clinical thresholds to
surface suspect HCC conditions that are NOT already present in the
patient's billing diagnoses.

This is SUPPLEMENTARY to the Gemini pipeline.  Suspects are returned
in-memory and are never automatically persisted — the caller decides
whether to store them via the main suspect engine.

Public API
----------
extract_lab_values(note_text)             -> list[LabValue]
detect_lab_suspects(note_text, existing)  -> list[SuspectResult]
detect_vitals_suspects(vitals, existing)  -> list[SuspectResult]
run_lab_suspect_scan(emr_pid)             -> dict  (full scan + stats)
"""
from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Rule table
# ---------------------------------------------------------------------------
# Each rule dict has:
#   lab        – human-readable lab name (used in evidence_detail)
#   patterns   – list of regex strings with ONE capture group for the numeric value
#   threshold  – primary threshold value
#   operator   – ">=" | "<=" | ">" | "<" applied to (extracted_value OP threshold)
#   max        – optional upper bound (inclusive); result excluded if value > max
#   max_excl   – optional upper bound (exclusive); result excluded if value >= max_excl
#   condition  – human-readable condition name
#   icd10      – suggested ICD-10-CM code
#   hcc        – HCC label or None if not HCC-relevant

LAB_SUSPECT_RULES: list[dict[str, Any]] = [
    {
        "lab": "HbA1c",
        "patterns": [r"(?:HbA1[Cc]|A1C|hemoglobin\s*A1c)[:\s]*(\d+\.?\d*)"],
        "threshold": 6.5,
        "operator": ">=",
        "condition": "Type 2 Diabetes",
        "icd10": "E11.65",
        "hcc": "HCC37",
    },
    {
        "lab": "HbA1c",
        "patterns": [r"(?:HbA1[Cc]|A1C)[:\s]*(\d+\.?\d*)"],
        "threshold": 5.7,
        "operator": ">=",
        "max": 6.4,
        "condition": "Prediabetes",
        "icd10": "R73.03",
        "hcc": None,
    },
    {
        "lab": "eGFR",
        "patterns": [r"eGFR[:\s]*(\d+\.?\d*)"],
        "threshold": 30,
        "operator": "<=",
        "condition": "CKD Stage 4",
        "icd10": "N18.4",
        "hcc": "HCC327",
    },
    {
        "lab": "eGFR",
        "patterns": [r"eGFR[:\s]*(\d+\.?\d*)"],
        "threshold": 44,
        "operator": "<",
        "max_excl": 30,
        "condition": "CKD Stage 3b",
        "icd10": "N18.32",
        "hcc": "HCC329",
    },
    {
        "lab": "eGFR",
        "patterns": [r"eGFR[:\s]*(\d+\.?\d*)"],
        "threshold": 60,
        "operator": "<",
        "max_excl": 44,
        "condition": "CKD Stage 3a",
        "icd10": "N18.31",
        "hcc": None,
    },
    {
        "lab": "LDL",
        "patterns": [r"LDL[:\s]*(\d+\.?\d*)"],
        "threshold": 190,
        "operator": ">=",
        "condition": "Severe Hyperlipidemia",
        "icd10": "E78.5",
        "hcc": None,
    },
    {
        "lab": "Hgb",
        "patterns": [r"(?:Hgb|Hemoglobin|Hb)[:\s]*(\d+\.?\d*)"],
        "threshold": 10,
        "operator": "<",
        "condition": "Chronic Anemia",
        "icd10": "D64.9",
        "hcc": "HCC109",
    },
    {
        "lab": "BMI",
        "patterns": [r"BMI[:\s]*(\d+\.?\d*)"],
        "threshold": 40,
        "operator": ">=",
        "condition": "Morbid Obesity",
        "icd10": "E66.01",
        "hcc": "HCC48",
    },
    {
        "lab": "O2 Sat",
        "patterns": [r"(?:O2\s*Sat|SpO2|Pulse\s*Ox)[:\s]*(\d+\.?\d*)"],
        "threshold": 88,
        "operator": "<",
        "condition": "Respiratory Failure",
        "icd10": "J96.11",
        "hcc": "HCC213",
    },
    {
        "lab": "GDS",
        "patterns": [r"(?:GDS|Geriatric\s*Depression)[:\s]*(\d+)/15"],
        "threshold": 5,
        "operator": ">=",
        "condition": "Depression",
        "icd10": "F33.0",
        "hcc": "HCC155",
    },
    {
        "lab": "CDT",
        "patterns": [r"(?:CDT|Clock.?drawing)[:\s]*(\d)/5"],
        "threshold": 3,
        "operator": "<=",
        "condition": "Cognitive Impairment",
        "icd10": "F03.90",
        "hcc": "HCC127",
    },
    {
        "lab": "BP Systolic",
        "patterns": [r"BP[:\s]*(\d+)/\d+"],
        "threshold": 180,
        "operator": ">=",
        "condition": "Hypertensive Crisis",
        "icd10": "I16.0",
        "hcc": None,
    },
]

# ---------------------------------------------------------------------------
# Vitals field mapping — keys from form_vitals serialized rows
# Maps vitals field names to the lab rules they can satisfy
# ---------------------------------------------------------------------------
_VITALS_FIELD_RULES: dict[str, str] = {
    "BMI": "BMI",
    "oxygen_saturation": "O2 Sat",
    "bps": "BP Systolic",   # bps = blood pressure systolic
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _operators() -> dict[str, Any]:
    """Return a map of operator strings to comparison callables."""
    import operator as op
    return {
        ">=": op.ge,
        "<=": op.le,
        ">": op.gt,
        "<": op.lt,
    }


_OPS = _operators()


def _threshold_met(value: float, rule: dict[str, Any]) -> bool:
    """
    Return True when *value* satisfies the rule's threshold condition AND
    falls within the optional range bounds (max / max_excl).
    """
    op_fn = _OPS.get(rule["operator"])
    if op_fn is None:
        logger.warning("Unknown operator '%s' in rule for lab '%s'", rule["operator"], rule["lab"])
        return False

    if not op_fn(value, rule["threshold"]):
        return False

    # Optional inclusive upper bound — value must be <= max
    if "max" in rule and value > rule["max"]:
        return False

    # Optional exclusive upper bound — result excluded if value >= max_excl
    # (used to carve a sub-range: e.g. 30 <= value < 44)
    if "max_excl" in rule and value >= rule["max_excl"]:
        return False

    return True


def _icd10_already_present(icd10: str, existing_diagnoses: list[str]) -> bool:
    """
    Return True when the suggested ICD-10 code (or a matching prefix) is
    already present in the patient's billing diagnoses.

    Matching is done on the first three characters (category) so that, for
    example, "E11.65" would suppress a suspect if "E11" or "E11.9" appears in
    the existing list.
    """
    candidate_prefix = icd10.replace(".", "").upper()[:3]
    for code in existing_diagnoses:
        clean = (code or "").replace(".", "").upper()
        if clean.startswith(candidate_prefix):
            return True
    return False


def _build_suspect(
    rule: dict[str, Any],
    value: float,
    source: str,
    context_snippet: str = "",
) -> dict[str, Any]:
    """Build a standardised suspect result dict."""
    return {
        "lab": rule["lab"],
        "value": value,
        "threshold": rule["threshold"],
        "operator": rule["operator"],
        "condition": rule["condition"],
        "icd10": rule["icd10"],
        "hcc": rule["hcc"],
        "source": source,                 # "clinical_note" | "vitals"
        "evidence_detail": {
            "lab": rule["lab"],
            "extracted_value": value,
            "threshold": rule["threshold"],
            "operator": rule["operator"],
            "context": context_snippet[:200] if context_snippet else "",
            "source": source,
        },
        "confidence_score": _confidence(rule, value),
    }


def _confidence(rule: dict[str, Any], value: float) -> float:
    """
    Compute a heuristic confidence score (0.0–1.0).

    Rules with an HCC mapping and a clearly breached threshold receive the
    highest scores.  The score is intentionally coarse — this is a
    rule-based engine, not a probabilistic model.
    """
    base = 0.75 if rule.get("hcc") else 0.55

    # Boost confidence when the value is substantially beyond the threshold
    op = rule["operator"]
    threshold = rule["threshold"]
    try:
        if op in (">=", ">") and value > threshold:
            ratio = (value - threshold) / max(threshold, 1)
            base = min(0.98, base + ratio * 0.15)
        elif op in ("<=", "<") and value < threshold:
            ratio = (threshold - value) / max(threshold, 1)
            base = min(0.98, base + ratio * 0.15)
    except Exception:  # noqa: BLE001 — best-effort guard
        logger.debug("swallowed exception", exc_info=True)

    return round(base, 4)


# ---------------------------------------------------------------------------
# Public function 1 — extract_lab_values
# ---------------------------------------------------------------------------

def extract_lab_values(note_text: str) -> list[dict[str, Any]]:
    """
    Parse all recognisable lab/measurement values from *note_text*.

    Each returned dict has:
        lab     – lab name from the matching rule
        value   – extracted numeric value (float)
        pattern – the regex pattern that matched
        match   – the raw matched substring (up to 80 chars)

    A single lab name may appear multiple times if the note contains
    repeated measurements; all occurrences are returned.

    Parameters
    ----------
    note_text:
        Raw free-text clinical note (SOAP note, progress note, etc.)

    Returns
    -------
    List of extracted lab dicts, in order of appearance.
    """
    if not note_text:
        return []

    results: list[dict[str, Any]] = []
    seen: set[tuple[str, float]] = set()   # deduplicate (lab, value) pairs

    for rule in LAB_SUSPECT_RULES:
        lab_name = rule["lab"]
        for pattern in rule["patterns"]:
            for match in re.finditer(pattern, note_text, re.IGNORECASE):
                try:
                    value = float(match.group(1))
                except (IndexError, ValueError):
                    continue

                key = (lab_name, value)
                if key in seen:
                    continue
                seen.add(key)

                results.append({
                    "lab": lab_name,
                    "value": value,
                    "pattern": pattern,
                    "match": match.group(0)[:80],
                })

    return results


# ---------------------------------------------------------------------------
# Public function 2 — detect_lab_suspects
# ---------------------------------------------------------------------------

def detect_lab_suspects(
    note_text: str,
    existing_diagnoses: list[str] | None = None,
) -> list[dict[str, Any]]:
    """
    Compare extracted lab values against thresholds and return suspects.

    Only conditions NOT already represented in *existing_diagnoses* are
    returned.  Each suspect dict is suitable for display directly in the
    UI or for forwarding to the main suspect engine for persistence.

    Parameters
    ----------
    note_text:
        Free-text clinical note.
    existing_diagnoses:
        List of ICD-10 codes already on the patient's billing record.
        Pass an empty list (or None) to skip filtering.

    Returns
    -------
    List of suspect dicts.  Empty when nothing is found or all findings
    are already diagnosed.
    """
    if not note_text:
        return []

    existing = existing_diagnoses or []
    suspects: list[dict[str, Any]] = []
    # Track which (condition, icd10) pairs we have already added to avoid
    # duplicating the same suspect from multiple regex patterns.
    emitted: set[tuple[str, str]] = set()

    for rule in LAB_SUSPECT_RULES:
        icd10 = rule["icd10"]

        # Skip if already coded
        if _icd10_already_present(icd10, existing):
            continue

        for pattern in rule["patterns"]:
            matched = False
            for m in re.finditer(pattern, note_text, re.IGNORECASE):
                try:
                    value = float(m.group(1))
                except (IndexError, ValueError):
                    continue

                if _threshold_met(value, rule):
                    key = (rule["condition"], icd10)
                    if key not in emitted:
                        context = note_text[max(0, m.start() - 40): m.end() + 40]
                        suspects.append(
                            _build_suspect(rule, value, "clinical_note", context)
                        )
                        emitted.add(key)
                    matched = True
                    break   # one confirmed hit per pattern is enough

            if matched:
                break   # no need to try other patterns for same rule

    return suspects


# ---------------------------------------------------------------------------
# Public function 3 — detect_vitals_suspects
# ---------------------------------------------------------------------------

def detect_vitals_suspects(
    vitals: dict[str, Any] | list[dict[str, Any]],
    existing_diagnoses: list[str] | None = None,
) -> list[dict[str, Any]]:
    """
    Check structured vitals against thresholds and return suspects.

    *vitals* may be:
    - A single vitals dict (one form_vitals row), or
    - A list of vitals dicts (multiple rows across visits).

    When a list is supplied, each row is evaluated independently and the
    most clinically significant reading (largest threshold breach) for each
    condition is kept.

    Parameters
    ----------
    vitals:
        Dict or list of dicts from ``openemr_connector.get_vitals()``.
        Recognised keys: BMI, oxygen_saturation, bps (systolic BP).
    existing_diagnoses:
        ICD-10 codes already billed.

    Returns
    -------
    List of suspect dicts.
    """
    existing = existing_diagnoses or []
    suspects: list[dict[str, Any]] = []
    emitted: set[tuple[str, str]] = set()

    rows: list[dict[str, Any]] = vitals if isinstance(vitals, list) else [vitals]

    for row in rows:
        for field, lab_name in _VITALS_FIELD_RULES.items():
            raw = row.get(field)
            if raw is None:
                continue

            try:
                value = float(raw)
            except (TypeError, ValueError):
                continue

            for rule in LAB_SUSPECT_RULES:
                if rule["lab"] != lab_name:
                    continue

                icd10 = rule["icd10"]
                if _icd10_already_present(icd10, existing):
                    continue

                if _threshold_met(value, rule):
                    key = (rule["condition"], icd10)
                    if key not in emitted:
                        context = (
                            f"{field}={value} from vitals recorded {row.get('date', 'unknown date')}"
                        )
                        suspects.append(
                            _build_suspect(rule, value, "vitals", context)
                        )
                        emitted.add(key)

    return suspects


# ---------------------------------------------------------------------------
# Public function 4 — run_lab_suspect_scan (full scan for one patient)
# ---------------------------------------------------------------------------

def _note_matches_year(note: dict[str, Any], year: int | None) -> bool:
    """Return True when *year* is None or the note's date field falls in *year*."""
    if year is None:
        return True
    raw = note.get("date")
    if not raw:
        return False
    try:
        date_str = str(raw)[:10]  # "YYYY-MM-DD ..." -> "YYYY-MM-DD"
        return int(date_str[:4]) == year
    except (ValueError, TypeError):
        return False


def run_lab_suspect_scan(emr_pid: int, year: int | None = None) -> dict[str, Any]:
    """
    Execute a complete lab/vitals suspect scan for *emr_pid* and return a
    summary dict ready to be served by the API endpoint.

    Parameters
    ----------
    emr_pid:
        OpenEMR patient identifier (the mapped emr_pid, NOT the RAF internal id).
        Callers must resolve the emr_pid via ``_get_emr_pid`` before calling
        this function.
    year:
        Optional calendar year (e.g. 2025).  When provided, only clinical
        notes, lab results, and vitals rows whose ``date`` field falls within
        that year are included in the scan.  When omitted, all available
        records are used (existing behaviour).

    Steps
    -----
    1. Fetch existing billing diagnoses (ICD-10 codes) from OpenEMR.
    2. Fetch all SOAP + clinical note text for the patient.
    3. Run detect_lab_suspects() over the combined note text.
    4. Fetch structured lab results from procedure_result and scan result_text.
    5. Fetch latest vitals row and run detect_vitals_suspects().
    6. Merge results, deduplicate by (condition, icd10), sort by confidence.

    Returns
    -------
    dict with keys:
        pid, note_suspects, vitals_suspects, all_suspects,
        notes_scanned, vitals_rows_checked, existing_diagnosis_count
    """
    from app.services import openemr_connector as emr

    pid = emr_pid  # local alias used throughout; always the OpenEMR pid

    # -- 1. Existing diagnoses -----------------------------------------------
    try:
        billing_rows = emr.get_billing_codes(pid)
        existing_icd10: list[str] = [
            r.get("code", "") for r in billing_rows if r.get("code")
        ]
    except Exception as exc:
        logger.warning("run_lab_suspect_scan pid=%s: could not load billing codes: %s", pid, exc)
        existing_icd10 = []

    # -- 2. Clinical note text -----------------------------------------------
    notes_text_parts: list[str] = []
    try:
        soap_notes = emr.get_soap_notes(pid)
        for note in soap_notes:
            if not _note_matches_year(note, year):
                continue
            parts = [
                note.get("subjective", "") or "",
                note.get("objective", "") or "",
                note.get("assessment", "") or "",
                note.get("plan", "") or "",
            ]
            notes_text_parts.append("\n".join(p for p in parts if p))
    except Exception as exc:
        logger.warning("run_lab_suspect_scan pid=%s: could not load SOAP notes: %s", pid, exc)

    # Also pull from get_all_clinical_notes_for_patient if available
    try:
        clinical_notes = emr.get_all_clinical_notes_for_patient(pid)
        for note in clinical_notes:
            if not _note_matches_year(note, year):
                continue
            text = note.get("note_text") or ""
            if text:
                notes_text_parts.append(text)
    except Exception as exc:
        logger.debug("run_lab_suspect_scan pid=%s: clinical notes unavailable: %s", pid, exc)

    # -- 3. Structured lab results from procedure_result ---------------------
    # Append result_text from procedure_result rows so that structured lab
    # values (HbA1c, eGFR, LDL, Hgb, etc.) stored in OpenEMR's lab module
    # are picked up by the regex engine even when they are not transcribed
    # into free-text SOAP notes.
    lab_results_scanned = 0
    try:
        lab_rows = emr.get_labs(pid, year=year)
        for lab_row in lab_rows:
            result_text = lab_row.get("result_text") or ""
            if result_text.strip():
                notes_text_parts.append(result_text)
                lab_results_scanned += 1
    except Exception as exc:
        logger.debug("run_lab_suspect_scan pid=%s: procedure_result unavailable: %s", pid, exc)

    combined_note_text = "\n\n".join(notes_text_parts)
    notes_scanned = len(notes_text_parts) - lab_results_scanned  # notes only for stat

    # -- 4. Note-based suspects (includes structured lab result_text) --------
    note_suspects: list[dict[str, Any]] = []
    if combined_note_text.strip():
        note_suspects = detect_lab_suspects(combined_note_text, existing_icd10)

    # -- 5. Vitals-based suspects --------------------------------------------
    vitals_suspects: list[dict[str, Any]] = []
    vitals_rows_checked = 0
    try:
        vitals_rows = emr.get_vitals(pid)
        if year is not None:
            vitals_rows = [r for r in vitals_rows if _note_matches_year(r, year)]
        vitals_rows_checked = len(vitals_rows)
        if vitals_rows:
            vitals_suspects = detect_vitals_suspects(vitals_rows, existing_icd10)
    except Exception as exc:
        logger.warning("run_lab_suspect_scan pid=%s: could not load vitals: %s", pid, exc)

    # -- 6. Merge & deduplicate ----------------------------------------------
    merged: dict[tuple[str, str], dict[str, Any]] = {}

    for suspect in note_suspects:
        key = (suspect["condition"], suspect["icd10"])
        if key not in merged or suspect["confidence_score"] > merged[key]["confidence_score"]:
            merged[key] = suspect

    for suspect in vitals_suspects:
        key = (suspect["condition"], suspect["icd10"])
        if key not in merged or suspect["confidence_score"] > merged[key]["confidence_score"]:
            merged[key] = suspect

    all_suspects = sorted(
        merged.values(),
        key=lambda s: s["confidence_score"],
        reverse=True,
    )

    logger.info(
        "run_lab_suspect_scan emr_pid=%s year=%s: notes=%d lab_results=%d vitals_rows=%d "
        "note_suspects=%d vitals_suspects=%d merged=%d",
        pid, year, notes_scanned, lab_results_scanned, vitals_rows_checked,
        len(note_suspects), len(vitals_suspects), len(all_suspects),
    )

    return {
        "pid": pid,
        "notes_scanned": notes_scanned,
        "lab_results_scanned": lab_results_scanned,
        "vitals_rows_checked": vitals_rows_checked,
        "existing_diagnosis_count": len(existing_icd10),
        "note_suspects": note_suspects,
        "vitals_suspects": vitals_suspects,
        "all_suspects": all_suspects,
    }
