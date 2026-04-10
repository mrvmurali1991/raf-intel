"""
Self-Improving Retraining Pipeline.

Captures human corrections to AI coding suggestions and uses them
to improve future accuracy by updating few-shot examples.

Public API
----------
log_correction(patient_id, encounter_id, ai_suggested_code,
               human_final_code, action, clinical_note_excerpt, reviewer)
    -> int          Insert a correction record; returns new row ID.

get_corrections(days)
    -> list[dict]   Return all corrections from the last N days.

export_few_shot_examples(min_corrections)
    -> list[dict]   Build ranked few-shot examples from correction history.

update_few_shot_file()
    -> dict         Merge new examples into few_shot_examples.json; return stats.

get_accuracy_stats(days)
    -> dict         Accuracy metrics over the last N days.

get_few_shot_examples()
    -> list[dict]   Load current few-shot examples from the JSON file.

Design decisions
----------------
* All DB access uses the raf_cursor() context manager from app.db, which
  handles connection pooling, commit, rollback, and cleanup automatically.
* The few_shot_examples.json file lives alongside this module so that
  gemini_service.py can import get_few_shot_examples() without a DB call.
* update_few_shot_file() caps the file at MAX_FEWSHOT_EXAMPLES entries and
  always preserves the originals when the DB has insufficient corrections.
* get_accuracy_stats() detects an improving trend by comparing the
  acceptance rate of the most recent 50% of corrections against the oldest.
"""
from __future__ import annotations

import json
import logging
import os
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from typing import Any

from app.db import raf_cursor

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FEWSHOT_FILE = os.path.join(os.path.dirname(__file__), "few_shot_examples.json")
MAX_FEWSHOT_EXAMPLES = 20

# DDL executed once per process (idempotent).
_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS raf_coding_corrections (
    id              INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    patient_id      INT UNSIGNED NOT NULL,
    encounter_id    INT UNSIGNED,
    ai_suggested_code  VARCHAR(10),
    human_final_code   VARCHAR(10),
    action          ENUM('accepted', 'rejected', 'modified') NOT NULL,
    clinical_note_excerpt  TEXT,
    reviewer        VARCHAR(100),
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_created_at  (created_at),
    INDEX idx_action      (action),
    INDEX idx_patient     (patient_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""

_table_initialised = False


def _ensure_table() -> None:
    """Create the corrections table if it does not exist (run once per process)."""
    global _table_initialised
    if _table_initialised:
        return
    try:
        with raf_cursor() as cur:
            cur.execute(_CREATE_TABLE_SQL)
        _table_initialised = True
        logger.info("raf_coding_corrections table verified/created")
    except Exception as exc:
        logger.error("Failed to create raf_coding_corrections table: %s", exc)
        raise


# ---------------------------------------------------------------------------
# 1. log_correction
# ---------------------------------------------------------------------------

def log_correction(
    patient_id: int,
    encounter_id: int | None,
    ai_suggested_code: str,
    human_final_code: str,
    action: str,
    clinical_note_excerpt: str = "",
    reviewer: str = "",
) -> int:
    """Log a human correction to an AI suggestion.

    Parameters
    ----------
    patient_id:
        OpenEMR patient PID.
    encounter_id:
        OpenEMR encounter ID (None if not encounter-specific).
    ai_suggested_code:
        The ICD-10-CM code originally suggested by Gemini.
    human_final_code:
        The ICD-10-CM code chosen by the human reviewer.  May equal
        ``ai_suggested_code`` when ``action="accepted"``.
    action:
        One of ``"accepted"``, ``"rejected"``, or ``"modified"``.
    clinical_note_excerpt:
        Optional short excerpt from the clinical note (for context in
        few-shot examples).
    reviewer:
        Username or role of the human reviewer.

    Returns
    -------
    int
        The auto-incremented primary key of the newly inserted row.

    Raises
    ------
    ValueError
        If ``action`` is not one of the three allowed values.
    RuntimeError
        On database errors.
    """
    action = action.lower().strip()
    if action not in {"accepted", "rejected", "modified"}:
        raise ValueError(
            f"action must be 'accepted', 'rejected', or 'modified'; got {action!r}"
        )

    _ensure_table()

    insert_sql = """
        INSERT INTO raf_coding_corrections
            (patient_id, encounter_id, ai_suggested_code, human_final_code,
             action, clinical_note_excerpt, reviewer)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """
    with raf_cursor() as cur:
        cur.execute(
            insert_sql,
            (
                patient_id,
                encounter_id,
                ai_suggested_code.upper().strip() if ai_suggested_code else None,
                human_final_code.upper().strip() if human_final_code else None,
                action,
                clinical_note_excerpt[:2000] if clinical_note_excerpt else "",
                reviewer[:100] if reviewer else "",
            ),
        )
        new_id: int = cur.lastrowid  # type: ignore[assignment]

    logger.info(
        "Correction logged: id=%d patient=%d action=%s ai=%s human=%s reviewer=%s",
        new_id,
        patient_id,
        action,
        ai_suggested_code,
        human_final_code,
        reviewer,
    )
    return new_id


# ---------------------------------------------------------------------------
# 2. get_corrections
# ---------------------------------------------------------------------------

def get_corrections(days: int = 30) -> list[dict[str, Any]]:
    """Return all corrections recorded within the last *days* calendar days.

    Parameters
    ----------
    days:
        Look-back window in days (default 30).  Pass 0 for all records.

    Returns
    -------
    List of dicts with keys matching the ``raf_coding_corrections`` columns,
    plus a Python ``datetime`` object for ``created_at``.
    """
    _ensure_table()

    if days > 0:
        cutoff = datetime.utcnow() - timedelta(days=days)
        sql = """
            SELECT id, patient_id, encounter_id,
                   ai_suggested_code, human_final_code,
                   action, clinical_note_excerpt, reviewer, created_at
            FROM raf_coding_corrections
            WHERE created_at >= %s
            ORDER BY created_at DESC
        """
        params: tuple[Any, ...] = (cutoff,)
    else:
        sql = """
            SELECT id, patient_id, encounter_id,
                   ai_suggested_code, human_final_code,
                   action, clinical_note_excerpt, reviewer, created_at
            FROM raf_coding_corrections
            ORDER BY created_at DESC
        """
        params = ()

    with raf_cursor() as cur:
        cur.execute(sql, params)
        rows: list[dict[str, Any]] = cur.fetchall()  # type: ignore[assignment]

    return rows


# ---------------------------------------------------------------------------
# 3. export_few_shot_examples
# ---------------------------------------------------------------------------

def export_few_shot_examples(min_corrections: int = 10) -> list[dict[str, Any]]:
    """Build ranked few-shot examples from human correction history.

    Selection criteria (in priority order):
    1. ``action = 'modified'`` – the AI was wrong and a human fixed it.
       These are the most instructive cases.
    2. Cases where multiple distinct reviewers independently chose the same
       human_final_code (inter-rater agreement signals high confidence).
    3. Diverse HCC categories – we favour examples that cover categories
       not already represented, capping at one per HCC chapter.

    The returned examples are formatted for direct inclusion in
    ``few_shot_examples.json`` and are compatible with the schema already
    consumed by ``gemini_service.py``.

    Parameters
    ----------
    min_corrections:
        Minimum number of correction records required before this function
        returns anything (avoids polluting examples with sparse data).

    Returns
    -------
    List of up to ``MAX_FEWSHOT_EXAMPLES`` example dicts.  Returns ``[]``
    when there are fewer than *min_corrections* records.
    """
    all_corrections = get_corrections(days=0)

    if len(all_corrections) < min_corrections:
        logger.info(
            "export_few_shot_examples: only %d corrections, need %d – skipping",
            len(all_corrections),
            min_corrections,
        )
        return []

    # ------------------------------------------------------------------ #
    # Step 1 – separate modified corrections (AI was wrong)               #
    # ------------------------------------------------------------------ #
    modified = [c for c in all_corrections if c["action"] == "modified"]

    # ------------------------------------------------------------------ #
    # Step 2 – multi-reviewer agreement on the same (note, human_code)    #
    # ------------------------------------------------------------------ #
    # Key: (ai_suggested_code, human_final_code); value: set of reviewers
    agreement: dict[tuple[str, str], set[str]] = defaultdict(set)
    note_map: dict[tuple[str, str], str] = {}
    for c in modified:
        key = (c["ai_suggested_code"] or "", c["human_final_code"] or "")
        reviewer = c.get("reviewer") or "unknown"
        agreement[key].add(reviewer)
        if c.get("clinical_note_excerpt") and key not in note_map:
            note_map[key] = c["clinical_note_excerpt"]

    # Sort by number of agreeing reviewers descending
    ranked_keys = sorted(
        agreement.keys(),
        key=lambda k: len(agreement[k]),
        reverse=True,
    )

    # ------------------------------------------------------------------ #
    # Step 3 – build examples, capping HCC chapter diversity              #
    # ------------------------------------------------------------------ #
    examples: list[dict[str, Any]] = []
    seen_hcc_chapters: set[str] = set()

    for ai_code, human_code in ranked_keys:
        if len(examples) >= MAX_FEWSHOT_EXAMPLES:
            break

        note_excerpt = note_map.get((ai_code, human_code), "")
        if not note_excerpt:
            continue  # Skip entries without clinical context

        # Derive a rough HCC chapter from the first letter of human_final_code
        chapter = human_code[0] if human_code else "?"
        if chapter in seen_hcc_chapters:
            continue
        seen_hcc_chapters.add(chapter)

        examples.append(
            {
                "note_excerpt": note_excerpt,
                "codes": [
                    {
                        "icd10": human_code,
                        "hcc": None,  # populated downstream if needed
                        "description": "",
                        "source": "human_correction",
                    }
                ],
                "ai_was": ai_code,
                "num_reviewers": len(agreement[(ai_code, human_code)]),
                "meat": {"M": "", "E": "", "A": "", "T": ""},
                "rationale": (
                    f"Human reviewers corrected AI suggestion {ai_code!r} "
                    f"to {human_code!r} "
                    f"({len(agreement[(ai_code, human_code)])} reviewer(s) agreed)."
                ),
            }
        )

    logger.info(
        "export_few_shot_examples: built %d examples from %d corrections",
        len(examples),
        len(all_corrections),
    )
    return examples


# ---------------------------------------------------------------------------
# 4. update_few_shot_file
# ---------------------------------------------------------------------------

def update_few_shot_file() -> dict[str, int]:
    """Merge the latest correction-derived examples into the JSON file.

    Workflow
    --------
    1. Load the current examples from ``few_shot_examples.json``.
    2. Call ``export_few_shot_examples()`` to generate new candidates.
    3. Prepend new examples (they have the highest recency relevance) and
       de-duplicate by ``(ai_was, icd10)`` key.
    4. Truncate to ``MAX_FEWSHOT_EXAMPLES`` entries.
    5. Write back to disk atomically via a temp-file swap.

    Returns
    -------
    dict with keys:
        ``added``   – how many new examples were merged in.
        ``removed`` – how many old examples were displaced.
        ``total``   – total examples now in the file.
    """
    current = get_few_shot_examples()
    new_candidates = export_few_shot_examples()

    if not new_candidates:
        return {"added": 0, "removed": 0, "total": len(current)}

    # De-duplicate: an example is identified by its first code's icd10 value.
    existing_codes: set[str] = {
        ex["codes"][0]["icd10"] for ex in current if ex.get("codes")
    }

    truly_new = [
        ex for ex in new_candidates
        if ex.get("codes") and ex["codes"][0]["icd10"] not in existing_codes
    ]

    merged = truly_new + current  # new examples go first
    before_count = len(merged)
    merged = merged[:MAX_FEWSHOT_EXAMPLES]
    after_count = len(merged)

    added = len(truly_new)
    removed = before_count - after_count

    _write_fewshot_file(merged)

    logger.info(
        "update_few_shot_file: added=%d removed=%d total=%d",
        added,
        removed,
        after_count,
    )
    return {"added": added, "removed": removed, "total": after_count}


# ---------------------------------------------------------------------------
# 5. get_accuracy_stats
# ---------------------------------------------------------------------------

def get_accuracy_stats(days: int = 30) -> dict[str, Any]:
    """Calculate AI accuracy metrics from correction records.

    Parameters
    ----------
    days:
        Look-back window (default 30).

    Returns
    -------
    dict with keys:
        ``total_suggestions``     – total correction records in window.
        ``accepted_unchanged``    – count where action == 'accepted'.
        ``accepted_modified``     – count where action == 'modified'.
        ``rejected``              – count where action == 'rejected'.
        ``accuracy_rate``         – accepted_unchanged / total (0.0–1.0).
        ``partial_accuracy_rate`` – (accepted + modified) / total.
        ``top_error_categories``  – list of {ai_code, count, common_correction}
                                    for the most frequently wrong AI codes.
        ``improving_trend``       – True if recent half has better accuracy.
        ``period_days``           – the requested look-back window.
        ``generated_at``          – ISO-8601 UTC timestamp.
    """
    corrections = get_corrections(days=days)
    total = len(corrections)

    if total == 0:
        return {
            "total_suggestions": 0,
            "accepted_unchanged": 0,
            "accepted_modified": 0,
            "rejected": 0,
            "accuracy_rate": 0.0,
            "partial_accuracy_rate": 0.0,
            "top_error_categories": [],
            "improving_trend": False,
            "period_days": days,
            "generated_at": datetime.utcnow().isoformat() + "Z",
        }

    action_counts: Counter[str] = Counter(c["action"] for c in corrections)
    accepted_unchanged = action_counts.get("accepted", 0)
    accepted_modified = action_counts.get("modified", 0)
    rejected = action_counts.get("rejected", 0)

    accuracy_rate = accepted_unchanged / total
    partial_accuracy_rate = (accepted_unchanged + accepted_modified) / total

    # ------------------------------------------------------------------ #
    # Top error categories                                                 #
    # ------------------------------------------------------------------ #
    # Group modified/rejected by ai_suggested_code
    error_groups: dict[str, list[str]] = defaultdict(list)
    for c in corrections:
        if c["action"] in ("modified", "rejected"):
            ai_code = c.get("ai_suggested_code") or "unknown"
            human_code = c.get("human_final_code") or "unknown"
            error_groups[ai_code].append(human_code)

    top_errors: list[dict[str, Any]] = []
    for ai_code, human_codes in sorted(
        error_groups.items(), key=lambda kv: len(kv[1]), reverse=True
    )[:10]:
        most_common_correction, _ = Counter(human_codes).most_common(1)[0]
        top_errors.append(
            {
                "ai_code": ai_code,
                "error_count": len(human_codes),
                "common_correction": most_common_correction,
            }
        )

    # ------------------------------------------------------------------ #
    # Improving trend: compare older half vs recent half by accuracy rate  #
    # ------------------------------------------------------------------ #
    improving_trend = False
    if total >= 10:
        # corrections are returned newest-first; reverse to chronological order
        chron = list(reversed(corrections))
        midpoint = total // 2
        old_half = chron[:midpoint]
        new_half = chron[midpoint:]

        def _acceptance_rate(records: list[dict[str, Any]]) -> float:
            if not records:
                return 0.0
            accepted = sum(1 for r in records if r["action"] == "accepted")
            return accepted / len(records)

        old_rate = _acceptance_rate(old_half)
        new_rate = _acceptance_rate(new_half)
        improving_trend = new_rate > old_rate

    return {
        "total_suggestions": total,
        "accepted_unchanged": accepted_unchanged,
        "accepted_modified": accepted_modified,
        "rejected": rejected,
        "accuracy_rate": round(accuracy_rate, 4),
        "partial_accuracy_rate": round(partial_accuracy_rate, 4),
        "top_error_categories": top_errors,
        "improving_trend": improving_trend,
        "period_days": days,
        "generated_at": datetime.utcnow().isoformat() + "Z",
    }


# ---------------------------------------------------------------------------
# 6. get_few_shot_examples
# ---------------------------------------------------------------------------

def get_few_shot_examples() -> list[dict[str, Any]]:
    """Load the current few-shot examples from the JSON file.

    If the file does not exist, it is created with the 20 default examples
    bundled with this module.

    Returns
    -------
    List of example dicts.  Never raises – returns ``[]`` on unexpected errors.
    """
    if not os.path.exists(FEWSHOT_FILE):
        logger.info(
            "few_shot_examples.json not found at %s – initialising defaults",
            FEWSHOT_FILE,
        )
        _init_default_examples()

    try:
        with open(FEWSHOT_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, list):
            return data
        logger.error(
            "few_shot_examples.json has unexpected root type %s; returning []",
            type(data),
        )
        return []
    except (OSError, json.JSONDecodeError) as exc:
        logger.error("Failed to load few_shot_examples.json: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _write_fewshot_file(examples: list[dict[str, Any]]) -> None:
    """Write *examples* to ``FEWSHOT_FILE`` using an atomic temp-file swap."""
    tmp_path = FEWSHOT_FILE + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(examples, fh, indent=2, ensure_ascii=False, default=str)
        os.replace(tmp_path, FEWSHOT_FILE)
    except OSError as exc:
        logger.error("Failed to write few_shot_examples.json: %s", exc)
        # Clean up orphaned temp file if present
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        raise


def _init_default_examples() -> None:
    """Write the 20 bundled default few-shot examples to disk.

    Covers all major CMS-HCC V28 categories:
    HCC 1  (HIV), HCC 18 (DM with complications), HCC 21 (malnutrition),
    HCC 27 (liver disease), HCC 39/40 (rheumatologic), HCC 52 (dementia),
    HCC 57 (schizophrenia), HCC 75 (ALS), HCC 84 (respiratory failure),
    HCC 85 (CHF), HCC 96 (AF), HCC 100 (stroke sequelae), HCC 108 (PAD),
    HCC 111 (COPD), HCC 135 (OSA), HCC 155 (MDD), HCC 326/329 (ESRD/CKD).
    """
    defaults: list[dict[str, Any]] = [
        {
            "note_excerpt": (
                "72yo M with Type 2 DM with A1c 8.2%, on metformin 1000mg BID "
                "and insulin glargine 20u. Diabetic nephropathy with eGFR 42. "
                "Continue current regimen, referred to nephrology."
            ),
            "codes": [
                {
                    "icd10": "E11.22",
                    "hcc": "18",
                    "description": "Type 2 DM with diabetic chronic kidney disease",
                },
                {
                    "icd10": "N18.3",
                    "hcc": "329",
                    "description": "CKD Stage 3 (moderate)",
                },
            ],
            "meat": {
                "M": "A1c 8.2%, eGFR 42",
                "E": "Nephropathy assessed, eGFR reviewed",
                "A": "DM with nephropathy documented",
                "T": "Metformin 1000mg BID, insulin glargine 20u, nephrology referral",
            },
            "rationale": (
                "eGFR 42 = CKD stage 3b. E11.22 requires both DM2 and CKD; "
                "N18.3 separately captures stage."
            ),
        },
        {
            "note_excerpt": (
                "68yo F with systolic CHF, EF 30% on last echo. On carvedilol "
                "25mg BID, lisinopril 10mg, furosemide 40mg. Weight stable, no "
                "edema today. BNP 480."
            ),
            "codes": [
                {
                    "icd10": "I50.22",
                    "hcc": "85",
                    "description": "Chronic systolic (congestive) heart failure",
                }
            ],
            "meat": {
                "M": "BNP 480, weight stable",
                "E": "Echo EF 30%, no edema on exam",
                "A": "Chronic systolic CHF documented",
                "T": "Carvedilol, lisinopril, furosemide",
            },
            "rationale": (
                "EF 30% = systolic dysfunction; 'chronic' because ongoing. "
                "I50.22 not I50.9 (unspecified)."
            ),
        },
        {
            "note_excerpt": (
                "75yo M with COPD, FEV1 40% predicted (GOLD III). On tiotropium, "
                "fluticasone/salmeterol. Moderate exacerbation treated with "
                "prednisone burst and azithromycin. SpO2 88% on room air."
            ),
            "codes": [
                {
                    "icd10": "J44.1",
                    "hcc": "111",
                    "description": "COPD with acute exacerbation",
                },
                {
                    "icd10": "J96.01",
                    "hcc": "84",
                    "description": "Acute respiratory failure with hypoxia",
                },
            ],
            "meat": {
                "M": "SpO2 88%, FEV1 40%",
                "E": "Pulmonary function tests reviewed",
                "A": "GOLD III COPD with acute exacerbation",
                "T": "Tiotropium, fluticasone/salmeterol, prednisone burst, azithromycin",
            },
            "rationale": (
                "Active exacerbation → J44.1 not J44.0. SpO2 88% on RA supports "
                "acute hypoxic respiratory failure."
            ),
        },
        {
            "note_excerpt": (
                "80yo F with major depressive disorder, recurrent, moderate severity. "
                "On sertraline 100mg daily. PHQ-9 score 12. Referred to behavioral "
                "health. Denied suicidal ideation."
            ),
            "codes": [
                {
                    "icd10": "F33.1",
                    "hcc": "155",
                    "description": "Major depressive disorder, recurrent, moderate",
                }
            ],
            "meat": {
                "M": "PHQ-9 score 12",
                "E": "Mood and affect assessed, SI screened",
                "A": "MDD recurrent moderate documented",
                "T": "Sertraline 100mg, behavioral health referral",
            },
            "rationale": (
                "PHQ-9 12 = moderate. F33.1 = recurrent moderate. "
                "'Denied SI' is not negation of the diagnosis."
            ),
        },
        {
            "note_excerpt": (
                "70yo M with Stage 3B CKD (eGFR 34), not on dialysis. Proteinuria "
                "2+ on UA. BP 148/90. On lisinopril 20mg, amlodipine 10mg. "
                "Renal diet counseled."
            ),
            "codes": [
                {
                    "icd10": "N18.32",
                    "hcc": "329",
                    "description": "Chronic kidney disease, stage 3b",
                },
                {
                    "icd10": "I10",
                    "hcc": None,
                    "description": "Essential hypertension",
                },
            ],
            "meat": {
                "M": "eGFR 34, BP 148/90, proteinuria 2+",
                "E": "UA reviewed, renal function assessed",
                "A": "CKD 3B with proteinuria",
                "T": "Lisinopril 20mg, amlodipine 10mg, renal diet",
            },
            "rationale": (
                "eGFR 34 = stage 3b → N18.32 not N18.3. "
                "Proteinuria warrants separate notation."
            ),
        },
        {
            "note_excerpt": (
                "66yo F with atrial fibrillation, non-valvular, on apixaban 5mg BID. "
                "Heart rate 78 bpm today, no palpitations. CHA2DS2-VASc 5. "
                "Rhythm strip shows AF."
            ),
            "codes": [
                {
                    "icd10": "I48.91",
                    "hcc": "96",
                    "description": "Unspecified atrial fibrillation",
                },
                {
                    "icd10": "Z79.01",
                    "hcc": None,
                    "description": "Long-term current use of anticoagulants",
                },
            ],
            "meat": {
                "M": "HR 78 bpm, rhythm strip",
                "E": "EKG showing AF, CHA2DS2-VASc scored",
                "A": "Non-valvular AF documented",
                "T": "Apixaban 5mg BID",
            },
            "rationale": (
                "Non-valvular unspecified chronicity = I48.91. "
                "Anticoagulant use separately captured with Z79.01."
            ),
        },
        {
            "note_excerpt": (
                "74yo M with peripheral artery disease, left lower extremity. "
                "ABI 0.65. On cilostazol 100mg BID, aspirin 81mg. Vascular surgery "
                "referral for possible revascularization. Claudication at 100 feet."
            ),
            "codes": [
                {
                    "icd10": "I70.212",
                    "hcc": "108",
                    "description": (
                        "Atherosclerosis of native arteries of left leg "
                        "with intermittent claudication"
                    ),
                }
            ],
            "meat": {
                "M": "ABI 0.65",
                "E": "Claudication at 100 feet, ABI measured",
                "A": "PAD left LE with intermittent claudication",
                "T": "Cilostazol, aspirin, vascular surgery referral",
            },
            "rationale": (
                "Laterality and symptom specificity required. "
                "ABI 0.65 confirms PAD with claudication."
            ),
        },
        {
            "note_excerpt": (
                "78yo M, BMI 38, morbid obesity. Counseled on weight loss. "
                "Referred to bariatric surgery program. Associated hypertension "
                "and obstructive sleep apnea. On CPAP nightly."
            ),
            "codes": [
                {
                    "icd10": "E66.01",
                    "hcc": None,
                    "description": "Morbid obesity due to excess calories",
                },
                {
                    "icd10": "G47.33",
                    "hcc": "135",
                    "description": "Obstructive sleep apnea (adult)",
                },
                {
                    "icd10": "I10",
                    "hcc": None,
                    "description": "Essential hypertension",
                },
            ],
            "meat": {
                "M": "BMI 38 documented",
                "E": "OSA assessed, CPAP compliance evaluated",
                "A": "Morbid obesity with comorbidities",
                "T": "CPAP, bariatric referral, weight counseling",
            },
            "rationale": (
                "BMI 38 = morbid obesity → E66.01. OSA is HCC-mapped and "
                "requires separate code."
            ),
        },
        {
            "note_excerpt": (
                "71yo F with rheumatoid arthritis on methotrexate 15mg weekly "
                "and hydroxychloroquine 200mg BID. Joints stable, ESR 32. "
                "Ophthalmology follow-up scheduled for HCQ monitoring."
            ),
            "codes": [
                {
                    "icd10": "M05.79",
                    "hcc": "40",
                    "description": (
                        "Rheumatoid arthritis with rheumatoid factor of multiple "
                        "sites without organ or systems involvement"
                    ),
                }
            ],
            "meat": {
                "M": "ESR 32",
                "E": "Joint exam stable, ophthalmology monitoring",
                "A": "Seropositive RA documented",
                "T": "Methotrexate 15mg weekly, hydroxychloroquine 200mg BID",
            },
            "rationale": (
                "Multiple joint sites without organ involvement = M05.79. "
                "DMARDs require long-term drug Z code."
            ),
        },
        {
            "note_excerpt": (
                "69yo M, HIV positive, on tenofovir/emtricitabine/dolutegravir. "
                "Viral load undetectable, CD4 count 620. No opportunistic "
                "infections. Annual labs reviewed."
            ),
            "codes": [
                {
                    "icd10": "B20",
                    "hcc": "1",
                    "description": "Human immunodeficiency virus [HIV] disease",
                }
            ],
            "meat": {
                "M": "Viral load undetectable, CD4 620",
                "E": "Annual labs reviewed, no OIs",
                "A": "HIV disease on ART",
                "T": "Tenofovir/emtricitabine/dolutegravir",
            },
            "rationale": (
                "B20 (HIV disease) not Z21 (asymptomatic) because patient is "
                "actively managed on ART. HCC 1 = highest RAF weight."
            ),
        },
        {
            "note_excerpt": (
                "67yo F with history of breast cancer, left, ER+/PR+, s/p "
                "lumpectomy and radiation 3 years ago. Currently on letrozole "
                "2.5mg daily. No evidence of recurrence on CT chest/abdomen."
            ),
            "codes": [
                {
                    "icd10": "Z85.3",
                    "hcc": None,
                    "description": "Personal history of malignant neoplasm of breast",
                },
                {
                    "icd10": "Z79.818",
                    "hcc": None,
                    "description": (
                        "Long-term current use of other agents affecting "
                        "estrogen receptors"
                    ),
                },
            ],
            "meat": {
                "M": "CT chest/abdomen NED",
                "E": "Recurrence surveillance imaging reviewed",
                "A": "Breast cancer history documented, no recurrence",
                "T": "Letrozole 2.5mg daily",
            },
            "rationale": (
                "No active disease → Z85.3 (history). "
                "Letrozole as adjuvant hormonal therapy → Z79.818."
            ),
        },
        {
            "note_excerpt": (
                "76yo M with vascular dementia, moderate stage. MMSE 16/30. "
                "Lives with daughter who reports increasing confusion. Safety "
                "concerns discussed. On donepezil 10mg daily."
            ),
            "codes": [
                {
                    "icd10": "F01.51",
                    "hcc": "52",
                    "description": "Vascular dementia with behavioral disturbance",
                }
            ],
            "meat": {
                "M": "MMSE 16/30",
                "E": "Cognitive assessment, safety evaluation",
                "A": "Moderate vascular dementia documented",
                "T": "Donepezil 10mg daily, caregiver education",
            },
            "rationale": (
                "Increasing confusion = behavioral disturbance → F01.51 not F01.50. "
                "Caregiver reports count as evaluation."
            ),
        },
        {
            "note_excerpt": (
                "65yo M with schizophrenia, paranoid type, on olanzapine 20mg daily "
                "and haloperidol decanoate 100mg IM monthly. Stable, no "
                "hospitalizations in past year. Insight limited."
            ),
            "codes": [
                {
                    "icd10": "F20.0",
                    "hcc": "57",
                    "description": "Paranoid schizophrenia",
                }
            ],
            "meat": {
                "M": "Psychiatric status assessed, no hospitalizations",
                "E": "Insight evaluated, symptom review",
                "A": "Paranoid schizophrenia stable",
                "T": "Olanzapine 20mg daily, haloperidol decanoate 100mg IM monthly",
            },
            "rationale": (
                "F20.0 paranoid type specifically documented. Both oral and "
                "depot antipsychotics = long-term drug use."
            ),
        },
        {
            "note_excerpt": (
                "70yo F with systemic lupus erythematosus with lupus nephritis, "
                "class III. Creatinine 1.8, UPCR 1.2. On hydroxychloroquine and "
                "mycophenolate 2g daily. Rheumatology co-managing."
            ),
            "codes": [
                {
                    "icd10": "M32.14",
                    "hcc": "39",
                    "description": (
                        "Glomerular disease in systemic lupus erythematosus"
                    ),
                }
            ],
            "meat": {
                "M": "Creatinine 1.8, UPCR 1.2",
                "E": "Renal function monitored, rheumatology co-management",
                "A": "SLE with lupus nephritis class III",
                "T": "Hydroxychloroquine, mycophenolate 2g daily",
            },
            "rationale": (
                "M32.14 codes lupus with renal involvement specifically. "
                "N08 separately captures nephritis manifestation when documented."
            ),
        },
        {
            "note_excerpt": (
                "73yo M with liver cirrhosis secondary to NASH, decompensated. "
                "Ascites present, paracentesis done. Total bilirubin 4.2, albumin "
                "2.8, INR 1.9. On spironolactone, lactulose, rifaximin."
            ),
            "codes": [
                {
                    "icd10": "K74.60",
                    "hcc": "27",
                    "description": "Unspecified cirrhosis of liver",
                },
                {
                    "icd10": "K76.6",
                    "hcc": "27",
                    "description": "Portal hypertension",
                },
                {
                    "icd10": "R18.0",
                    "hcc": None,
                    "description": "Malignant ascites",
                },
            ],
            "meat": {
                "M": "Bilirubin 4.2, albumin 2.8, INR 1.9",
                "E": "Ascites on exam, LFTs reviewed",
                "A": "Decompensated NASH cirrhosis with ascites and portal HTN",
                "T": "Spironolactone, lactulose, rifaximin, paracentesis",
            },
            "rationale": (
                "NASH cirrhosis = K74.60 (not alcoholic K70.x). "
                "Ascites and portal HTN coded separately."
            ),
        },
        {
            "note_excerpt": (
                "68yo F with Type 2 DM and proliferative diabetic retinopathy, "
                "right eye, with vitreous hemorrhage. Last ophthalmology visit "
                "showed new NVD. On anti-VEGF injections."
            ),
            "codes": [
                {
                    "icd10": "E11.3511",
                    "hcc": "18",
                    "description": (
                        "Type 2 DM with proliferative diabetic retinopathy "
                        "with combined traction retinal detachment and "
                        "rhegmatogenous retinal detachment, right eye"
                    ),
                },
                {
                    "icd10": "H43.11",
                    "hcc": None,
                    "description": "Vitreous hemorrhage, right eye",
                },
            ],
            "meat": {
                "M": "Ophthalmology follow-up, NVD documented",
                "E": "Funduscopic exam, vitreous hemorrhage identified",
                "A": "PDR with vitreous hemorrhage right eye",
                "T": "Anti-VEGF injections",
            },
            "rationale": (
                "Proliferative DR requires laterality and complication specificity. "
                "Vitreous hemorrhage coded separately."
            ),
        },
        {
            "note_excerpt": (
                "77yo M with sequelae of ischemic stroke 2 years ago. Residual "
                "left hemiparesis and dysarthria. On aspirin 325mg and atorvastatin "
                "40mg. Continues PT/OT."
            ),
            "codes": [
                {
                    "icd10": "I69.351",
                    "hcc": "100",
                    "description": (
                        "Hemiplegia and hemiparesis following cerebral infarction "
                        "affecting right dominant side"
                    ),
                },
                {
                    "icd10": "I69.322",
                    "hcc": "100",
                    "description": "Dysarthria following cerebral infarction",
                },
            ],
            "meat": {
                "M": "Neurological deficits assessed",
                "E": "PT/OT evaluation of function",
                "A": "Post-stroke hemiparesis and dysarthria",
                "T": "Aspirin 325mg, atorvastatin 40mg, PT/OT",
            },
            "rationale": (
                "Residual neurological deficits from old stroke = I69.x codes, "
                "not acute stroke. Each deficit coded separately."
            ),
        },
        {
            "note_excerpt": (
                "65yo F with end-stage renal disease on hemodialysis 3x/week. "
                "Dialysis fistula left forearm functioning well. ESA administered. "
                "Interdialytic weight gain 2kg."
            ),
            "codes": [
                {
                    "icd10": "N18.6",
                    "hcc": "326",
                    "description": "End-stage renal disease",
                },
                {
                    "icd10": "Z99.2",
                    "hcc": None,
                    "description": "Dependence on renal dialysis",
                },
                {
                    "icd10": "D63.1",
                    "hcc": None,
                    "description": "Anemia in chronic kidney disease",
                },
            ],
            "meat": {
                "M": "Interdialytic weight gain 2kg, ESA administered",
                "E": "Fistula assessed, dialysis adequacy evaluated",
                "A": "ESRD on HD, CKD anemia",
                "T": "Hemodialysis 3x/week, erythropoietin stimulating agent",
            },
            "rationale": (
                "N18.6 for ESRD. Z99.2 for dialysis dependence. "
                "Anemia of CKD (D63.1) separately coded."
            ),
        },
        {
            "note_excerpt": (
                "70yo M with amyotrophic lateral sclerosis, bulbar onset. PEG tube "
                "placed 3 months ago for dysphagia. FVC 55%. Riluzole 50mg BID. "
                "Palliative care team involved."
            ),
            "codes": [
                {
                    "icd10": "G12.21",
                    "hcc": "75",
                    "description": "Amyotrophic lateral sclerosis",
                },
                {
                    "icd10": "J96.10",
                    "hcc": "84",
                    "description": (
                        "Chronic respiratory failure, unspecified whether "
                        "with hypoxia or hypercapnia"
                    ),
                },
                {
                    "icd10": "Z43.1",
                    "hcc": None,
                    "description": "Encounter for attention to gastrostomy",
                },
            ],
            "meat": {
                "M": "FVC 55%, respiratory status",
                "E": "Pulmonary function, dysphagia assessed",
                "A": "Bulbar onset ALS with respiratory compromise",
                "T": "Riluzole 50mg BID, PEG tube, palliative care",
            },
            "rationale": (
                "G12.21 specific for ALS. FVC 55% = respiratory failure warranting "
                "J96 code. PEG encounter Z43.1."
            ),
        },
        {
            "note_excerpt": (
                "69yo F with protein-calorie malnutrition, severe, BMI 16.4. "
                "Admitted for nutritional support. Albumin 2.1, prealbumin 8. "
                "Dietitian consultation ordered. TPN initiated."
            ),
            "codes": [
                {
                    "icd10": "E43",
                    "hcc": "21",
                    "description": "Unspecified severe protein-calorie malnutrition",
                }
            ],
            "meat": {
                "M": "Albumin 2.1, prealbumin 8, BMI 16.4",
                "E": "Nutritional status assessed by dietitian",
                "A": "Severe protein-calorie malnutrition documented",
                "T": "TPN initiated, dietitian consultation",
            },
            "rationale": (
                "BMI 16.4 + albumin 2.1 = severe malnutrition → E43. "
                "HCC 21 carries significant RAF weight."
            ),
        },
    ]

    _write_fewshot_file(defaults)
    logger.info(
        "Initialised few_shot_examples.json with %d default examples", len(defaults)
    )
