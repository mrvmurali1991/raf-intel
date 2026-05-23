"""
MEAT Evidence Service — RADV audit defensibility for CMS-HCC V28.

For every HCC code assigned to a patient this service stores and retrieves the
complete MEAT evidence chain:

  * Which encounter(s) support the HCC
  * The exact text excerpt from the clinical note
  * Which MEAT elements are present (Monitor, Evaluate, Assess, Treat)
  * A completeness score (0.00 – 1.00, i.e. 0/4 – 4/4)
  * The AI model that extracted the evidence

Database table: raf_intelligence.raf_meat_evidence
  Columns (confirmed from DESCRIBE):
    id                 INT UNSIGNED PK AUTO_INCREMENT
    patient_hcc_id     INT UNSIGNED NOT NULL  (FK → raf_patient_hcc.id)
    encounter_id       INT UNSIGNED NOT NULL
    encounter_date     DATE NOT NULL
    meat_m             TEXT NULL
    meat_e             TEXT NULL
    meat_a             TEXT NULL
    meat_t             TEXT NULL
    meat_m_present     TINYINT(1) DEFAULT 0
    meat_e_present     TINYINT(1) DEFAULT 0
    meat_a_present     TINYINT(1) DEFAULT 0
    meat_t_present     TINYINT(1) DEFAULT 0
    completeness_score DECIMAL(5,4) DEFAULT 0.0000
    raw_note_excerpt   TEXT NULL
    created_at         DATETIME
    updated_at         DATETIME

NOTE: The table has no nlp_model or confidence column.  Those function
parameters are accepted for forward-compatibility and are logged only.

Public API
----------
store_meat_evidence(patient_hcc_id, encounter_id, encounter_date, ...)
    -> int                    evidence row id (insert or update-in-place)

get_meat_evidence(patient_id, year)
    -> list[dict]             all evidence rows joined to HCC metadata

get_meat_for_hcc(patient_hcc_id)
    -> list[dict]             evidence rows for one specific HCC assignment

calculate_meat_completeness(patient_id, year)
    -> dict                   aggregate completeness report

store_analysis_meat(patient_id, year, gemini_result)
    -> None                   persist MEAT from an analyze_clinical_note result

update_hcc_meat_status(patient_id, year)
    -> None                   refresh meat_status column in raf_patient_hcc
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

from app.config import settings
from app.db import raf_cursor

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _completeness_score(m: str | None, e: str | None, a: str | None, t: str | None) -> float:
    """Return a 0.00–1.00 completeness score from the four MEAT text fields."""
    present = sum(1 for v in (m, e, a, t) if v and v.strip())
    return round(present / 4.0, 4)


def _meat_status_from_score(score: float) -> str:
    """Map a 0.00–1.00 completeness score to the meat_status enum value."""
    if score >= 1.0:
        return "complete"
    if score > 0.0:
        return "partial"
    return "missing"


def _parse_hcc_number(hcc_code_raw: str | None) -> int | None:
    """
    Normalise HCC code strings such as "HCC18", "HCC 18", "18" → 18.
    Returns None if the value cannot be parsed.
    """
    if hcc_code_raw is None:
        return None
    raw = str(hcc_code_raw).upper().strip().lstrip("HCC").strip()
    try:
        return int(raw)
    except ValueError:
        return None


def _resolve_encounter_date(encounter_date: str | date) -> str:
    """Accept date objects or ISO strings; always return an ISO string."""
    if isinstance(encounter_date, date):
        return encounter_date.isoformat()
    return str(encounter_date)


# ---------------------------------------------------------------------------
# 1. store_meat_evidence
# ---------------------------------------------------------------------------

def store_meat_evidence(
    patient_hcc_id: int,
    encounter_id: int,
    encounter_date: str | date,
    meat_monitoring: str | None,
    meat_evaluation: str | None,
    meat_assessment: str | None,
    meat_treatment: str | None,
    raw_note_excerpt: str,
    nlp_model: str = settings.llm_model_meat,
    confidence: float = 0.0,
    # --- Document provenance (migration 022) ---
    document_upload_id: int | None = None,
    document_hash: str | None = None,
    document_page: int | None = None,
    document_offset_start: int | None = None,
    document_offset_end: int | None = None,
    context_classification: str | None = None,
    measurement_year: int | None = None,
) -> int:
    """Store MEAT evidence for a specific HCC + encounter.

    If a row already exists for the same (patient_hcc_id, encounter_id) pair
    it is updated in-place rather than duplicated.

    Parameters
    ----------
    patient_hcc_id:
        Primary key of the raf_patient_hcc row this evidence supports.
    encounter_id:
        OpenEMR encounter ID.
    encounter_date:
        Date of the encounter (ISO string "YYYY-MM-DD" or date object).
    meat_monitoring:
        Verbatim text from the note showing monitoring activity, or None.
    meat_evaluation:
        Verbatim text showing evaluation / testing, or None.
    meat_assessment:
        Verbatim text showing clinical assessment / reasoning, or None.
    meat_treatment:
        Verbatim text showing active treatment, or None.
    raw_note_excerpt:
        Broader excerpt from the note used as the source for extraction.
    nlp_model:
        Name of the AI model that produced this evidence (logged only).
    confidence:
        Model confidence 0.0–1.0 (logged only).
    document_upload_id:
        FK hint to raf_data_uploads.id — the file this excerpt came from.
    document_hash:
        SHA-256 hex digest of the source uploaded file for RADV traceability.
    document_page:
        1-based page number within the source document (PDFs).
    document_offset_start:
        Character/byte start offset of the excerpt within the source document.
    document_offset_end:
        Character/byte end offset of the excerpt within the source document.
    context_classification:
        Document context type (e.g. 'progress_note', 'discharge', 'lab').
    measurement_year:
        Explicit measurement year tag, useful for cross-year evidence joins.

    Returns
    -------
    int
        The ``id`` of the inserted or updated raf_meat_evidence row.

    Raises
    ------
    ValueError
        If patient_hcc_id does not exist in raf_patient_hcc.
    """
    enc_date_str = _resolve_encounter_date(encounter_date)
    score = _completeness_score(meat_monitoring, meat_evaluation, meat_assessment, meat_treatment)

    m_present = bool(meat_monitoring and meat_monitoring.strip())
    e_present = bool(meat_evaluation and meat_evaluation.strip())
    a_present = bool(meat_assessment and meat_assessment.strip())
    t_present = bool(meat_treatment and meat_treatment.strip())

    logger.debug(
        "store_meat_evidence: patient_hcc_id=%d encounter_id=%d score=%.4f model=%s confidence=%.2f",
        patient_hcc_id, encounter_id, score, nlp_model, confidence,
    )

    try:
        with raf_cursor() as cur:
            # 1. Verify the FK exists to give a clear error rather than a DB FK violation
            cur.execute(
                "SELECT id FROM raf_patient_hcc WHERE id = %s",
                (patient_hcc_id,),
            )
            if cur.fetchone() is None:
                raise ValueError(
                    f"patient_hcc_id {patient_hcc_id} does not exist in raf_patient_hcc"
                )

            # 2. Check for an existing row with the same (patient_hcc_id, encounter_id)
            cur.execute(
                """
                SELECT id FROM raf_meat_evidence
                WHERE patient_hcc_id = %s AND encounter_id = %s
                LIMIT 1
                """,
                (patient_hcc_id, encounter_id),
            )
            existing = cur.fetchone()

            if existing:
                # Update the existing row; keep created_at unchanged (updated_at auto-refreshes).
                # Provenance columns use COALESCE so a NULL kwarg leaves the stored value intact
                # (schema-safe if migration 022 has not yet applied).
                cur.execute(
                    """
                    UPDATE raf_meat_evidence
                    SET encounter_date          = %s,
                        meat_m                 = %s,
                        meat_e                 = %s,
                        meat_a                 = %s,
                        meat_t                 = %s,
                        meat_m_present         = %s,
                        meat_e_present         = %s,
                        meat_a_present         = %s,
                        meat_t_present         = %s,
                        completeness_score     = %s,
                        raw_note_excerpt       = %s,
                        document_upload_id     = COALESCE(%s, document_upload_id),
                        document_hash          = COALESCE(%s, document_hash),
                        document_page          = COALESCE(%s, document_page),
                        document_offset_start  = COALESCE(%s, document_offset_start),
                        document_offset_end    = COALESCE(%s, document_offset_end),
                        context_classification = COALESCE(%s, context_classification),
                        measurement_year       = COALESCE(%s, measurement_year)
                    WHERE id = %s
                    """,
                    (
                        enc_date_str,
                        meat_monitoring or None,
                        meat_evaluation or None,
                        meat_assessment or None,
                        meat_treatment or None,
                        int(m_present),
                        int(e_present),
                        int(a_present),
                        int(t_present),
                        score,
                        raw_note_excerpt or None,
                        document_upload_id,
                        document_hash or None,
                        document_page,
                        document_offset_start,
                        document_offset_end,
                        context_classification or None,
                        measurement_year,
                        existing["id"],
                    ),
                )
                evidence_id: int = existing["id"]
                logger.info(
                    "store_meat_evidence: updated row id=%d (patient_hcc_id=%d encounter_id=%d)",
                    evidence_id, patient_hcc_id, encounter_id,
                )
            else:
                # Insert a new row including provenance columns.
                cur.execute(
                    """
                    INSERT INTO raf_meat_evidence
                        (patient_hcc_id, encounter_id, encounter_date,
                         meat_m, meat_e, meat_a, meat_t,
                         meat_m_present, meat_e_present, meat_a_present, meat_t_present,
                         completeness_score, raw_note_excerpt,
                         document_upload_id, document_hash, document_page,
                         document_offset_start, document_offset_end,
                         context_classification, measurement_year)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        patient_hcc_id,
                        encounter_id,
                        enc_date_str,
                        meat_monitoring or None,
                        meat_evaluation or None,
                        meat_assessment or None,
                        meat_treatment or None,
                        int(m_present),
                        int(e_present),
                        int(a_present),
                        int(t_present),
                        score,
                        raw_note_excerpt or None,
                        document_upload_id,
                        document_hash or None,
                        document_page,
                        document_offset_start,
                        document_offset_end,
                        context_classification or None,
                        measurement_year,
                    ),
                )
                evidence_id = cur.lastrowid  # type: ignore[assignment]
                logger.info(
                    "store_meat_evidence: inserted row id=%d (patient_hcc_id=%d encounter_id=%d)",
                    evidence_id, patient_hcc_id, encounter_id,
                )
    except Exception as exc:
        logger.error(
            "store_meat_evidence failed patient_hcc_id=%d encounter_id=%d: %s",
            patient_hcc_id, encounter_id, exc,
        )
        raise

    return evidence_id


# ---------------------------------------------------------------------------
# 2. get_meat_evidence
# ---------------------------------------------------------------------------

def get_meat_evidence(patient_id: int, year: int = None) -> list[dict[str, Any]]:
    """Retrieve all MEAT evidence rows for a patient's HCCs in a given year.

    Joins raf_meat_evidence → raf_patient_hcc so callers receive HCC metadata
    alongside the evidence.

    Parameters
    ----------
    patient_id:
        RAF Intelligence patient ID.
    year:
        Measurement / service year (defaults to 2026).

    Returns
    -------
    List of dicts, each containing all raf_meat_evidence columns plus:
        ``hcc_code``, ``icd10_codes``, ``meat_status`` from raf_patient_hcc.
    Returns an empty list if no evidence exists.
    """
    year = year or date.today().year
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT
                    me.id,
                    me.patient_hcc_id,
                    me.encounter_id,
                    me.encounter_date,
                    me.meat_m,
                    me.meat_e,
                    me.meat_a,
                    me.meat_t,
                    me.meat_m_present,
                    me.meat_e_present,
                    me.meat_a_present,
                    me.meat_t_present,
                    me.completeness_score,
                    me.raw_note_excerpt,
                    me.created_at,
                    me.updated_at,
                    ph.hcc_code,
                    ph.icd10_codes,
                    ph.meat_status
                FROM raf_meat_evidence me
                JOIN raf_patient_hcc ph ON ph.id = me.patient_hcc_id
                WHERE ph.patient_id        = %s
                  AND ph.measurement_year  = %s
                ORDER BY ph.hcc_code, me.encounter_date DESC
                """,
                (patient_id, year),
            )
            rows = cur.fetchall()
    except Exception as exc:
        logger.error("get_meat_evidence failed patient_id=%d year=%d: %s", patient_id, year, exc)
        return []

    # Convert Decimal to float for JSON serialisation
    result: list[dict[str, Any]] = []
    for row in rows:
        row = dict(row)
        row["completeness_score"] = float(row["completeness_score"])
        result.append(row)

    return result


# ---------------------------------------------------------------------------
# 3. get_meat_for_hcc
# ---------------------------------------------------------------------------

def get_meat_for_hcc(patient_hcc_id: int) -> list[dict[str, Any]]:
    """Retrieve all MEAT evidence rows for a single HCC assignment.

    Parameters
    ----------
    patient_hcc_id:
        Primary key of the raf_patient_hcc row.

    Returns
    -------
    List of dicts (raf_meat_evidence columns), ordered by encounter_date DESC.
    Returns an empty list if no evidence exists.
    """
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT
                    id,
                    patient_hcc_id,
                    encounter_id,
                    encounter_date,
                    meat_m,
                    meat_e,
                    meat_a,
                    meat_t,
                    meat_m_present,
                    meat_e_present,
                    meat_a_present,
                    meat_t_present,
                    completeness_score,
                    raw_note_excerpt,
                    created_at,
                    updated_at
                FROM raf_meat_evidence
                WHERE patient_hcc_id = %s
                ORDER BY encounter_date DESC
                """,
                (patient_hcc_id,),
            )
            rows = cur.fetchall()
    except Exception as exc:
        logger.error("get_meat_for_hcc failed patient_hcc_id=%d: %s", patient_hcc_id, exc)
        return []

    result: list[dict[str, Any]] = []
    for row in rows:
        row = dict(row)
        row["completeness_score"] = float(row["completeness_score"])
        result.append(row)

    return result


# ---------------------------------------------------------------------------
# 4. calculate_meat_completeness
# ---------------------------------------------------------------------------

def calculate_meat_completeness(patient_id: int, year: int = None) -> dict[str, Any]:
    """Calculate MEAT completeness across all HCCs for a patient in a year.

    For each HCC the best (highest) completeness_score across all supporting
    encounters is used when classifying status.

    Returns
    -------
    dict with keys:
        overall_score   float   fraction of HCCs classified "complete"
        total_hccs      int
        complete_hccs   int     all 4 MEAT elements present in ≥1 encounter
        partial_hccs    int     1–3 MEAT elements present
        missing_hccs    int     no MEAT evidence at all
        per_hcc         list[dict]  one entry per HCC, see schema below

    year defaults to the current calendar year when not supplied.

    per_hcc entry schema:
        hcc_code        str
        patient_hcc_id  int
        meat_score      int     0–4, best score across encounters
        status          str     "complete" | "partial" | "missing"
        m               bool    any monitoring evidence present
        e               bool    any evaluation evidence present
        a               bool    any assessment evidence present
        t               bool    any treatment evidence present
        evidence_count  int     number of supporting evidence rows
    """
    year = year or date.today().year
    with raf_cursor() as cur:
        # Fetch all HCC assignments for this patient/year
        cur.execute(
            """
            SELECT id, hcc_code
            FROM raf_patient_hcc
            WHERE patient_id       = %s
              AND measurement_year = %s
            ORDER BY hcc_code
            """,
            (patient_id, year),
        )
        hcc_rows = cur.fetchall()

        if not hcc_rows:
            return {
                "overall_score": 0.0,
                "total_hccs": 0,
                "complete_hccs": 0,
                "partial_hccs": 0,
                "missing_hccs": 0,
                "per_hcc": [],
            }

        hcc_ids = [r["id"] for r in hcc_rows]

        # Fetch aggregated MEAT presence per HCC (best values across encounters)
        # Using MAX() so if ANY encounter covers an element it counts as present
        fmt_placeholders = ", ".join(["%s"] * len(hcc_ids))
        cur.execute(
            f"""
            SELECT
                patient_hcc_id,
                COUNT(*)         AS evidence_count,
                MAX(meat_m_present) AS has_m,
                MAX(meat_e_present) AS has_e,
                MAX(meat_a_present) AS has_a,
                MAX(meat_t_present) AS has_t
            FROM raf_meat_evidence
            WHERE patient_hcc_id IN ({fmt_placeholders})
            GROUP BY patient_hcc_id
            """,
            hcc_ids,
        )
        evidence_by_hcc: dict[int, dict[str, Any]] = {
            r["patient_hcc_id"]: r for r in cur.fetchall()
        }

        # Fetch representative extracted phrases + raw_note_excerpt per HCC.
        # Pull the most recent row per HCC (by encounter_date DESC, id DESC) so
        # the UI can show the current clinical excerpt in the MEAT tooltip.
        cur.execute(
            f"""
            SELECT me.patient_hcc_id, me.meat_m, me.meat_e, me.meat_a, me.meat_t,
                   me.raw_note_excerpt, me.encounter_date
            FROM raf_meat_evidence me
            JOIN (
                SELECT patient_hcc_id, MAX(id) AS latest_id
                FROM raf_meat_evidence
                WHERE patient_hcc_id IN ({fmt_placeholders})
                GROUP BY patient_hcc_id
            ) latest ON latest.latest_id = me.id
            """,
            hcc_ids,
        )
        phrases_by_hcc: dict[int, dict[str, Any]] = {
            r["patient_hcc_id"]: r for r in cur.fetchall()
        }

    complete_count = 0
    partial_count = 0
    missing_count = 0
    per_hcc: list[dict[str, Any]] = []

    for hcc_row in hcc_rows:
        phcc_id: int = hcc_row["id"]
        hcc_code: int = hcc_row["hcc_code"]
        ev = evidence_by_hcc.get(phcc_id)

        if ev:
            has_m = bool(ev["has_m"])
            has_e = bool(ev["has_e"])
            has_a = bool(ev["has_a"])
            has_t = bool(ev["has_t"])
            meat_score = sum([has_m, has_e, has_a, has_t])
            evidence_count = int(ev["evidence_count"])
        else:
            has_m = has_e = has_a = has_t = False
            meat_score = 0
            evidence_count = 0

        if meat_score == 4:
            status = "complete"
            complete_count += 1
        elif meat_score > 0:
            status = "partial"
            partial_count += 1
        else:
            status = "missing"
            missing_count += 1

        phrases = phrases_by_hcc.get(phcc_id) or {}
        per_hcc.append(
            {
                "hcc_code": str(hcc_code),
                "patient_hcc_id": phcc_id,
                "meat_score": meat_score,
                "status": status,
                "m": has_m,
                "e": has_e,
                "a": has_a,
                "t": has_t,
                "monitor": phrases.get("meat_m") or None,
                "evaluate": phrases.get("meat_e") or None,
                "assess": phrases.get("meat_a") or None,
                "treat": phrases.get("meat_t") or None,
                "raw_note_excerpt": phrases.get("raw_note_excerpt") or None,
                "evidence_count": evidence_count,
            }
        )

    total = len(hcc_rows)
    overall_score = round(complete_count / total, 4) if total > 0 else 0.0

    return {
        "overall_score": overall_score,
        "total_hccs": total,
        "complete_hccs": complete_count,
        "partial_hccs": partial_count,
        "missing_hccs": missing_count,
        "per_hcc": per_hcc,
    }


# ---------------------------------------------------------------------------
# 5. store_analysis_meat
# ---------------------------------------------------------------------------

def store_analysis_meat(
    patient_id: int,
    year: int,
    gemini_result: dict[str, Any],
    # --- Document provenance (migration 022) ---
    document_upload_id: int | None = None,
    document_hash: str | None = None,
    document_page: int | None = None,
    document_offset_start: int | None = None,
    document_offset_end: int | None = None,
    context_classification: str | None = None,
    measurement_year: int | None = None,
) -> None:
    """Persist MEAT evidence from a Gemini analyze_clinical_note result.

    Iterates over every diagnosis in gemini_result["diagnoses"] that:
      - Has a non-null hcc_code
      - Is not negated
      - Is not historical
      - Has at least one non-empty MEAT element

    For each qualifying diagnosis it looks up (or skips) the corresponding
    raf_patient_hcc row and calls store_meat_evidence.

    Parameters
    ----------
    patient_id:
        RAF Intelligence patient ID.
    year:
        Measurement year (e.g. 2026).
    gemini_result:
        Dict returned by gemini_service.analyze_clinical_note().
        Expected keys: "diagnoses", "_meta" (optional).
    document_upload_id:
        FK hint to raf_data_uploads.id — the file this analysis was run on.
    document_hash:
        SHA-256 hex digest of the source uploaded file for RADV traceability.
    document_page:
        1-based page number within the source document (PDFs).
    document_offset_start:
        Character/byte start offset of the excerpt within the source document.
    document_offset_end:
        Character/byte end offset of the excerpt within the source document.
    context_classification:
        Document context type (e.g. 'progress_note', 'discharge', 'lab').
    measurement_year:
        Explicit measurement year tag; defaults to the ``year`` parameter when
        not supplied so evidence rows are always linkable by year.

    Notes
    -----
    * If no matching raf_patient_hcc row exists the diagnosis is skipped with
      a warning — it may not have been persisted yet.
    * encounter_id is read from gemini_result["_meta"]["encounter_id"] if
      present, otherwise defaults to 0 (sentinel value).
    * encounter_date is read from gemini_result["_meta"]["encounter_date"] if
      present, otherwise today's date is used.
    """
    diagnoses: list[dict[str, Any]] = gemini_result.get("diagnoses", [])
    if not diagnoses:
        logger.debug(
            "store_analysis_meat: no diagnoses in result for patient_id=%d year=%d",
            patient_id, year,
        )
        return

    meta: dict[str, Any] = gemini_result.get("_meta", {})
    encounter_id: int = int(meta.get("encounter_id", 0))
    enc_date_raw = meta.get("encounter_date") or date.today().isoformat()
    enc_date_str = _resolve_encounter_date(enc_date_raw)
    nlp_model: str = str(meta.get("model", settings.llm_model_meat))

    # Load all HCC assignments for this patient/year once so we avoid
    # a per-diagnosis DB round-trip
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT id, hcc_code
            FROM raf_patient_hcc
            WHERE patient_id       = %s
              AND measurement_year = %s
            """,
            (patient_id, year),
        )
        hcc_map: dict[int, int] = {
            hcc_num: int(r["id"])
            for r in cur.fetchall()
            for hcc_num in (_parse_hcc_number(r["hcc_code"]),)
            if hcc_num is not None
        }

    stored = 0
    skipped_no_hcc = 0
    skipped_negated = 0
    skipped_no_meat = 0

    for dx in diagnoses:
        # Skip negated or pure historical diagnoses
        if dx.get("negated"):
            skipped_negated += 1
            continue
        if dx.get("historical") and not dx.get("meat_score", 0):
            # Historical diagnoses with MEAT still provide recapture evidence
            skipped_negated += 1
            continue

        # Resolve HCC number
        raw_hcc = dx.get("hcc_code") or (
            (dx.get("hcc_mapping") or {}).get("hcc_code")
        )
        hcc_num = _parse_hcc_number(raw_hcc)
        if hcc_num is None:
            skipped_no_hcc += 1
            continue

        patient_hcc_id = hcc_map.get(hcc_num)
        if patient_hcc_id is None:
            logger.warning(
                "store_analysis_meat: no raf_patient_hcc row for patient_id=%d year=%d hcc=%s — skipping",
                patient_id, year, raw_hcc,
            )
            skipped_no_hcc += 1
            continue

        # Extract MEAT text from the Gemini diagnosis dict
        meat_block: dict[str, str] = dx.get("meat") or {}
        monitoring: str | None = meat_block.get("monitoring") or None
        evaluation: str | None = meat_block.get("evaluation") or None
        assessment: str | None = meat_block.get("assessment") or None
        treatment: str | None = meat_block.get("treatment") or None

        # Skip if genuinely no MEAT evidence at all
        if not any([monitoring, evaluation, assessment, treatment]):
            skipped_no_meat += 1
            logger.debug(
                "store_analysis_meat: no MEAT text for HCC %s (patient_id=%d) — skipping",
                raw_hcc, patient_id,
            )
            continue

        raw_excerpt: str = dx.get("supporting_text") or ""
        # Fallback 1: look up the source clinical note linked to this encounter
        # so the UI tooltip can show a real clinical excerpt even when the LLM
        # didn't return a supporting_text quote.
        if not raw_excerpt and encounter_id:
            try:
                with raf_cursor() as cur:
                    cur.execute(
                        "SELECT text FROM clinical_notes WHERE encounter_id=%s ORDER BY id DESC LIMIT 1",
                        (encounter_id,),
                    )
                    r = cur.fetchone()
                    if r and r.get("text"):
                        raw_excerpt = str(r["text"])[:500]
            except Exception:  # noqa: BLE001 — best-effort guard
                logger.debug("swallowed exception", exc_info=True)
        # Fallback 2: stitch MEAT phrases together so the excerpt is never
        # empty when we have any MEAT signal.
        if not raw_excerpt:
            raw_excerpt = " | ".join(
                s for s in (monitoring, evaluation, assessment, treatment) if s
            )[:500]
        confidence: float = float(dx.get("confidence", 0.0))

        try:
            store_meat_evidence(
                patient_hcc_id=patient_hcc_id,
                encounter_id=encounter_id,
                encounter_date=enc_date_str,
                meat_monitoring=monitoring,
                meat_evaluation=evaluation,
                meat_assessment=assessment,
                meat_treatment=treatment,
                raw_note_excerpt=raw_excerpt,
                nlp_model=nlp_model,
                confidence=confidence,
                document_upload_id=document_upload_id,
                document_hash=document_hash,
                document_page=document_page,
                document_offset_start=document_offset_start,
                document_offset_end=document_offset_end,
                context_classification=context_classification,
                measurement_year=measurement_year if measurement_year is not None else year,
            )
            stored += 1
        except ValueError as exc:
            # FK miss after our map lookup — shouldn't happen, log and continue
            logger.error(
                "store_analysis_meat: %s (patient_id=%d hcc=%s)", exc, patient_id, raw_hcc
            )

    logger.info(
        "store_analysis_meat: patient_id=%d year=%d — stored=%d "
        "skipped_no_hcc=%d skipped_negated=%d skipped_no_meat=%d",
        patient_id, year, stored, skipped_no_hcc, skipped_negated, skipped_no_meat,
    )


# ---------------------------------------------------------------------------
# 6. update_hcc_meat_status
# ---------------------------------------------------------------------------

def update_hcc_meat_status(
    patient_id: int,
    year: int = None,
    *,
    max_status: str = "complete",
) -> None:
    """Recompute and persist meat_status for every HCC of a patient/year.

    Reads the best (MAX) MEAT element presence across all evidence rows for
    each HCC and writes the appropriate enum value back to raf_patient_hcc:

        all 4 present → "complete"  (capped by *max_status*)
        1–3 present   → "partial"
        none          → "missing"

    **Clinical-rule billing gate** (added 2026-04): before promoting an HCC
    to "complete" (billed), the per-HCC clinical sanity rules in
    app.services.raf.clinical_rules are evaluated. If a rule FAILs, the
    target status is demoted from "complete" to "partial" so the HCC is
    NOT billed. WARNings are logged but allow promotion.

    This function is idempotent — safe to call multiple times.

    Parameters
    ----------
    patient_id:
        RAF Intelligence patient ID.
    year:
        Measurement year (defaults to current year).
    max_status:
        Ceiling on the status this call may write.  Pass ``"partial"`` when
        the evidence comes exclusively from the rule-based regex validator so
        that an HCC can never reach ``"complete"`` via keyword matching alone.
        The LLM-validated path (``store_analysis_meat``) keeps the default
        ``"complete"`` ceiling.  This enforces ``settings.require_llm_meat_for_billing``.

    Notes
    -----
    The rule-based ``meat_validator`` is advisory-only (see its module
    docstring).  Callers from ``auto_meat_extractor`` MUST pass
    ``max_status="partial"`` when ``settings.require_llm_meat_for_billing``
    is True so that billed RAF scores are never gated on regex evidence.
    """
    year = year or date.today().year

    # Validate the ceiling value so callers cannot accidentally pass an
    # invalid enum string.
    _valid_statuses = ("complete", "partial", "missing")
    if max_status not in _valid_statuses:
        raise ValueError(
            f"update_hcc_meat_status: max_status={max_status!r} is not valid; "
            f"must be one of {_valid_statuses}"
        )

    # Reuse calculate_meat_completeness to get per-HCC MEAT scores.
    # We do an independent targeted UPDATE so we touch only the rows that
    # actually need changing (avoids spurious updated_at bumps).
    report = calculate_meat_completeness(patient_id, year)

    if not report["per_hcc"]:
        logger.debug(
            "update_hcc_meat_status: no HCCs found for patient_id=%d year=%d",
            patient_id, year,
        )
        return

    # Status ordering for ceiling enforcement
    _status_rank = {"missing": 0, "partial": 1, "complete": 2}
    cap_rank = _status_rank[max_status]

    # -------------------------------------------------------------------
    # Clinical-rule billing gate
    # -------------------------------------------------------------------
    # Collect HCCs that *would* be promoted to "complete" and run the gate
    # across all of them in one pass. Fail-open: if the gate raises or is
    # unavailable we log and proceed with the legacy ceiling-only behavior.
    candidate_hccs: list[int] = []
    for hcc_entry in report["per_hcc"]:
        if hcc_entry["status"] == "complete":
            try:
                candidate_hccs.append(int(str(hcc_entry["hcc_code"]).lstrip("HCChcc ")))
            except (ValueError, TypeError):
                continue

    blocked: set[int] = set()
    # Feature-flag gate — allows emergency rollback of clinical billing gate
    # without redeploying. When disabled, candidate HCCs are promoted with
    # only the legacy ceiling check (pre-billing-gate behaviour).
    _gate_enabled = True
    try:
        from app.config import settings as _settings
        _gate_enabled = bool(getattr(_settings, "use_clinical_billing_gate", True))
    except Exception:  # noqa: BLE001 — best-effort guard
        logger.debug("swallowed exception", exc_info=True)

    # ---------------------------------------------------------------------------
    # Lazy import of immutable_audit — if unavailable we degrade gracefully but
    # do NOT silently skip gate failures (fail-closed).
    # ---------------------------------------------------------------------------
    try:
        from app.services.immutable_audit import append_audit_entry as _append_audit_entry
    except Exception as _audit_import_err:
        logger.warning(
            "update_hcc_meat_status: immutable_audit unavailable — audit events "
            "will NOT be written (pid=%d year=%d): %s",
            patient_id, year, _audit_import_err,
        )
        _append_audit_entry = None  # type: ignore[assignment]

    def _emit_audit(event_type: str, details: dict) -> None:
        """Best-effort audit emission — never raises."""
        if _append_audit_entry is None:
            return
        try:
            _append_audit_entry(
                event_type=event_type,
                resource_type="patient_hcc",
                resource_id=str(patient_id),
                action="meat_status_gate",
                details=details,
            )
        except Exception as _ae:
            logger.warning(
                "update_hcc_meat_status: failed to write audit entry "
                "event_type=%s (pid=%d): %s",
                event_type, patient_id, _ae,
            )

    # SEV-1 fix: gate errors are FAIL-CLOSED.  Any exception from
    # gate_billed_promotion blocks promotion for the affected HCCs and emits
    # a CLINICAL_RULE_GATE_ERROR audit entry.  Only a clean truthy return
    # allows promotion.
    _gate_error: bool = False  # True  → gate threw; all candidates blocked

    if _gate_enabled:
        try:
            from datetime import date as _date_cls

            from app.services.raf.clinical_rules.billing_gate import gate_billed_promotion

            gate_out = gate_billed_promotion(
                patient_id=patient_id,
                candidate_hccs=candidate_hccs,
                dos=_date_cls(year, 12, 31),
            )
            blocked = set(gate_out.get("blocked_hccs") or [])
            if blocked:
                logger.warning(
                    "update_hcc_meat_status: clinical-rule gate BLOCKED HCCs %s "
                    "for pid=%d year=%d — will remain 'partial' rather than 'complete'",
                    sorted(blocked), patient_id, year,
                )
                for _hcc in sorted(blocked):
                    _emit_audit(
                        "CLINICAL_RULE_GATE_DENIED",
                        {
                            "tenant_id": None,
                            "patient_id": patient_id,
                            "hcc_code": _hcc,
                            "denial_reason": gate_out.get("reason") or "clinical rule failed",
                            "year": year,
                        },
                    )
            # Emit PROMOTED for each candidate HCC that was NOT blocked.
            for _hcc in candidate_hccs:
                if _hcc not in blocked:
                    _emit_audit(
                        "CLINICAL_RULE_GATE_PROMOTED",
                        {
                            "tenant_id": None,
                            "patient_id": patient_id,
                            "hcc_code": _hcc,
                            "year": year,
                        },
                    )
        except Exception as exc:
            # FAIL-CLOSED: gate threw → block ALL candidate HCCs.
            _gate_error = True
            blocked = set(candidate_hccs)
            logger.error(
                "update_hcc_meat_status: clinical-rule gate EXCEPTION (pid=%d year=%d) "
                "— ALL %d candidate HCCs blocked (fail-closed): %s",
                patient_id, year, len(blocked), exc,
                exc_info=True,
            )
            for _hcc in sorted(blocked):
                _emit_audit(
                    "CLINICAL_RULE_GATE_ERROR",
                    {
                        "tenant_id": None,
                        "patient_id": patient_id,
                        "hcc_code": _hcc,
                        "exception_class": type(exc).__name__,
                        "exception_message": str(exc),
                        "year": year,
                    },
                )
    else:
        logger.info(
            "update_hcc_meat_status: clinical billing gate DISABLED by feature flag "
            "(pid=%d year=%d)",
            patient_id, year,
        )

    # One-time sentinel to avoid log spam when last_recomputed_at is absent.
    _recomputed_col_warned: bool = False

    updated = 0
    with raf_cursor() as cur:
        for hcc_entry in report["per_hcc"]:
            phcc_id: int = hcc_entry["patient_hcc_id"]
            raw_status: str = hcc_entry["status"]

            # Apply the ceiling: never promote beyond max_status.
            effective_status = raw_status
            if _status_rank.get(raw_status, 0) > cap_rank:
                effective_status = max_status
                logger.debug(
                    "update_hcc_meat_status: hcc_id=%d status capped from %s → %s "
                    "(require_llm_meat_for_billing gate)",
                    phcc_id, raw_status, effective_status,
                )

            # Apply gate: if this HCC was blocked, refuse to mark "complete".
            # When blocked due to a gate *exception* (_gate_error=True) the
            # status is set to "pending_rule_review" to make the failure
            # visible in the UI / downstream queries.  A normal rule-denial
            # (gate returned blocked list without raising) keeps "partial" so
            # the existing denial path is unchanged.
            try:
                hcc_num = int(str(hcc_entry["hcc_code"]).lstrip("HCChcc "))
            except (ValueError, TypeError):
                hcc_num = -1
            if effective_status == "complete" and hcc_num in blocked:
                effective_status = "pending_rule_review" if _gate_error else "partial"

            # Read the current status so we can log genuine transitions and
            # always write the freshly-computed value (demotion-safe).
            cur.execute(
                "SELECT meat_status FROM raf_patient_hcc WHERE id = %s",
                (phcc_id,),
            )
            existing_row = cur.fetchone()
            old_status: str | None = (existing_row or {}).get("meat_status")

            # Always write the new status + score — no WHERE guard.
            # This ensures demotion (e.g. complete → partial) is applied.
            try:
                cur.execute(
                    """
                    UPDATE raf_patient_hcc
                    SET meat_status        = %s,
                        completeness_score = %s,
                        updated_at         = NOW(),
                        last_recomputed_at = NOW()
                    WHERE id = %s
                    """,
                    (effective_status, hcc_entry["meat_score"] / 4.0, phcc_id),
                )
            except Exception as _col_exc:
                # MySQL error 1054 = unknown column (last_recomputed_at absent).
                _errno = getattr(_col_exc, "args", [None])[0]
                if _errno == 1054 and not _recomputed_col_warned:
                    _recomputed_col_warned = True
                    logger.warning(
                        "update_hcc_meat_status: column last_recomputed_at does not exist "
                        "in raf_patient_hcc — retrying without it. "
                        "Run: ALTER TABLE raf_patient_hcc ADD COLUMN "
                        "last_recomputed_at DATETIME NULL AFTER updated_at;"
                    )
                    cur.execute(
                        """
                        UPDATE raf_patient_hcc
                        SET meat_status        = %s,
                            completeness_score = %s,
                            updated_at         = NOW()
                        WHERE id = %s
                        """,
                        (effective_status, hcc_entry["meat_score"] / 4.0, phcc_id),
                    )
                else:
                    raise

            updated += 1

            # Audit trail: log every genuine status transition (including demotion).
            if old_status != effective_status:
                logger.info(
                    "meat_status changed hcc=%s patient=%s old=%s new=%s reason=recompute",
                    hcc_entry["hcc_code"], patient_id, old_status, effective_status,
                )
            else:
                logger.debug(
                    "update_hcc_meat_status: hcc_id=%d status unchanged → %s",
                    phcc_id, effective_status,
                )

    logger.info(
        "update_hcc_meat_status: patient_id=%d year=%d max_status=%s — "
        "%d/%d rows updated (blocked_by_gate=%d)",
        patient_id, year, max_status, updated, report["total_hccs"], len(blocked),
    )


# ---------------------------------------------------------------------------
# 7. recompute_meat_status_for_patient
# ---------------------------------------------------------------------------

def recompute_meat_status_for_patient(
    patient_id: int,
    payment_year: int | None = None,
) -> dict[str, Any]:
    """Recompute MEAT completeness and persist meat_status for every HCC.

    This is the canonical entry-point for batch jobs that need to refresh the
    stored meat_status after evidence has changed.  It calls
    ``calculate_meat_completeness`` and then ``update_hcc_meat_status`` so
    every HCC — including those that were previously "complete" — gets the
    status that matches the current evidence set.

    Demotion (e.g. complete → partial when evidence is removed) is fully
    supported because ``update_hcc_meat_status`` no longer uses a
    ``WHERE meat_status != …`` guard.

    Parameters
    ----------
    patient_id:
        RAF Intelligence patient ID.
    payment_year:
        Measurement / payment year.  Defaults to the current calendar year.

    Returns
    -------
    dict with keys:
        patient_id      int
        year            int
        total_hccs      int
        complete_hccs   int
        partial_hccs    int
        missing_hccs    int
        overall_score   float
    """
    year: int = payment_year or date.today().year

    logger.info(
        "recompute_meat_status_for_patient: starting patient_id=%d year=%d",
        patient_id, year,
    )

    update_hcc_meat_status(patient_id, year)

    # Return a summary computed after the writes so callers get fresh counts.
    report = calculate_meat_completeness(patient_id, year)

    result: dict[str, Any] = {
        "patient_id": patient_id,
        "year": year,
        "total_hccs": report["total_hccs"],
        "complete_hccs": report["complete_hccs"],
        "partial_hccs": report["partial_hccs"],
        "missing_hccs": report["missing_hccs"],
        "overall_score": report["overall_score"],
    }

    logger.info(
        "recompute_meat_status_for_patient: done patient_id=%d year=%d — "
        "total=%d complete=%d partial=%d missing=%d score=%.4f",
        patient_id, year,
        result["total_hccs"], result["complete_hccs"],
        result["partial_hccs"], result["missing_hccs"],
        result["overall_score"],
    )

    return result
