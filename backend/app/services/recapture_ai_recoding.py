"""
AI-suggested recoding for recapture gaps.

Workflow
--------
For an open recapture_gaps row (patient + ICD-10 + payment_year), pull the
patient's clinical notes from the past N months out of OpenEMR
(form_soap + form_clinical_notes joined to form_encounter for the date filter),
build a deterministic prompt for Gemini that asks for VERBATIM evidence quotes
supporting the chronic condition, parse the JSON response defensively, and
persist each suggestion to the recapture_ai_suggestions table.

Hallucination guardrails
------------------------
1. The prompt explicitly forbids fabrication and demands verbatim quotes.
2. We post-validate every returned phrase against the concatenated note
   corpus — phrases that are not a substring of the supplied notes are
   dropped before persistence.
3. If Gemini returns invalid JSON or any unexpected shape, suggest_recoding
   returns an empty list rather than raising.

Public API
----------
suggest_recoding(gap_id, *, months=12, llm_call=None)
    -> {gap_id, suggestions: [...], scanned_note_count, llm_model_used}

list_pending_suggestions(gap_id) -> list[dict]
accept_suggestion(suggestion_id, *, reviewer=None) -> dict
reject_suggestion(suggestion_id, *, reviewer=None) -> dict
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from typing import Any, Callable

from app.config import settings
from app.db import openemr_cursor, raf_cursor

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_NOTES = 25            # Cap notes sent to Gemini to keep prompt size sane
MAX_NOTE_CHARS = 4000     # Per-note truncation
DEFAULT_LOOKBACK_MONTHS = 12

_VALID_MEAT = {"M", "E", "A", "T"}


# ---------------------------------------------------------------------------
# Note retrieval
# ---------------------------------------------------------------------------

def _fetch_recent_notes(
    patient_id: int,
    months: int = DEFAULT_LOOKBACK_MONTHS,
) -> list[dict[str, Any]]:
    """Return clinical notes for *patient_id* from the past *months* months.

    Pulls from form_soap and form_clinical_notes, joining form_encounter via
    forms.encounter so we can filter by encounter date. Each row carries:
      ``note_id``         — composite "<source>:<id>" string
      ``encounter_date``  — date string YYYY-MM-DD (encounter.date) or None
      ``note_text``       — assembled note body
    """
    cutoff = (date.today() - timedelta(days=int(months * 30))).isoformat()

    out: list[dict[str, Any]] = []

    # SOAP notes (form_soap has no direct encounter column; join via forms)
    sql_soap = """
        SELECT
            fs.id   AS note_id,
            DATE(fe.date) AS encounter_date,
            CONCAT_WS('\n\n',
                IF(fs.subjective <> '', CONCAT('S: ', fs.subjective), NULL),
                IF(fs.objective  <> '', CONCAT('O: ', fs.objective),  NULL),
                IF(fs.assessment <> '', CONCAT('A: ', fs.assessment), NULL),
                IF(fs.plan       <> '', CONCAT('P: ', fs.plan),       NULL)
            ) AS note_text
        FROM form_soap fs
        JOIN forms f
          ON f.form_id = fs.id AND f.formdir = 'soap'
        JOIN form_encounter fe
          ON CAST(f.encounter AS UNSIGNED) = fe.encounter
        WHERE fs.pid = %s
          AND fs.activity = 1
          AND fe.date >= %s
        ORDER BY fe.date DESC
        LIMIT %s
    """

    # Clinical notes form (encounter is varchar; join cast)
    sql_cn = """
        SELECT
            fcn.id  AS note_id,
            DATE(fe.date) AS encounter_date,
            COALESCE(fcn.description, fcn.codetext, '') AS note_text
        FROM form_clinical_notes fcn
        JOIN form_encounter fe
          ON CAST(fcn.encounter AS UNSIGNED) = fe.encounter
        WHERE fcn.pid = %s
          AND (fcn.activity = 1 OR fcn.activity IS NULL)
          AND fe.date >= %s
        ORDER BY fe.date DESC
        LIMIT %s
    """

    try:
        with openemr_cursor() as cur:
            cur.execute(sql_soap, (patient_id, cutoff, MAX_NOTES))
            for r in cur.fetchall():
                txt = (r.get("note_text") or "").strip()
                if not txt:
                    continue
                out.append({
                    "note_id": f"soap:{r['note_id']}",
                    "encounter_date": (
                        r["encounter_date"].isoformat()
                        if r.get("encounter_date") else None
                    ),
                    "note_text": txt[:MAX_NOTE_CHARS],
                })
    except Exception as exc:
        logger.warning("_fetch_recent_notes: form_soap query failed: %s", exc)

    try:
        with openemr_cursor() as cur:
            cur.execute(sql_cn, (patient_id, cutoff, MAX_NOTES))
            for r in cur.fetchall():
                txt = (r.get("note_text") or "").strip()
                if not txt:
                    continue
                out.append({
                    "note_id": f"cn:{r['note_id']}",
                    "encounter_date": (
                        r["encounter_date"].isoformat()
                        if r.get("encounter_date") else None
                    ),
                    "note_text": txt[:MAX_NOTE_CHARS],
                })
    except Exception as exc:
        logger.debug("_fetch_recent_notes: form_clinical_notes unavailable: %s", exc)

    # Cap total notes after merging both sources
    return out[:MAX_NOTES]


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

def _build_prompt(
    icd10: str,
    hcc_code: str | None,
    notes: list[dict[str, Any]],
) -> str:
    """Build the deterministic Gemini prompt.

    The prompt is intentionally narrow: a single condition, a single JSON
    output shape, and a hard rule that quotes must be verbatim.
    """
    hcc_label = hcc_code or "unmapped"

    note_block_parts: list[str] = []
    for n in notes:
        note_block_parts.append(
            f"--- NOTE id={n['note_id']} date={n['encounter_date'] or 'unknown'} ---\n"
            f"{n['note_text']}"
        )
    note_block = "\n\n".join(note_block_parts) if note_block_parts else "(no notes available)"

    return (
        "You are an HCC coding auditor. Find evidence in these clinical notes "
        f"that the patient has the chronic condition with ICD-10 {icd10}, "
        f"HCC {hcc_label}.\n\n"
        "Return JSON only — no prose, no markdown fences. Schema:\n"
        '{"found": bool, "suggestions": [{"phrase": "verbatim quote from a note", '
        '"confidence": 0..1, "meat_element": "M|E|A|T", "note_id": "X", '
        '"encounter_date": "YYYY-MM-DD"}]}\n\n'
        "Rules:\n"
        "1. Every \"phrase\" MUST be a verbatim substring of one of the supplied "
        "notes. Do NOT paraphrase. Do NOT fabricate.\n"
        "2. Use note_id and encounter_date EXACTLY as printed in the note header.\n"
        "3. meat_element: M=Monitor, E=Evaluate, A=Assess, T=Treat.\n"
        "4. If no evidence is found, return {\"found\": false, \"suggestions\": []}.\n\n"
        f"NOTES:\n{note_block}\n"
    )


# ---------------------------------------------------------------------------
# Gemini call (thin wrapper that can be mocked in tests)
# ---------------------------------------------------------------------------

def _default_llm_call(prompt: str) -> Any:
    """Call Gemini and return the parsed JSON object.

    Wraps app.services._legacy.gemini_service._call_gemini so the rest of this
    module never imports Gemini directly — that lets tests inject a stub via
    the ``llm_call`` parameter on suggest_recoding().
    """
    from app.services._legacy.gemini_service import _call_gemini

    return _call_gemini(
        prompt,
        system_instruction=(
            "You are a strict JSON-only HCC coding auditor. Return ONLY the JSON "
            "object specified in the user prompt. Never invent quotes."
        ),
        temperature=0.1,
        max_output_tokens=2048,
    )


# ---------------------------------------------------------------------------
# Response parsing & validation
# ---------------------------------------------------------------------------

def _parse_response(
    raw: Any,
    notes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Defensively parse a Gemini response into a list of validated suggestions.

    On any failure (bad JSON, unexpected shape, no suggestions) returns [].
    Filters out any suggestion whose ``phrase`` is not a substring of the
    supplied note corpus — this is the hallucination guardrail.
    """
    # If the caller passed a string we may need to json.loads it
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.warning("recapture_ai_recoding: invalid JSON from Gemini: %s", exc)
            return []

    if not isinstance(raw, dict):
        logger.warning(
            "recapture_ai_recoding: unexpected response shape %s", type(raw)
        )
        return []

    suggestions = raw.get("suggestions")
    if not isinstance(suggestions, list):
        return []

    # Build the corpus once for verbatim-substring validation
    corpus = "\n".join(n.get("note_text", "") for n in notes)
    note_ids = {n["note_id"] for n in notes}

    cleaned: list[dict[str, Any]] = []
    for item in suggestions:
        if not isinstance(item, dict):
            continue
        phrase = (item.get("phrase") or "").strip()
        if not phrase:
            continue

        # Hallucination guardrail — phrase must be a substring of the corpus
        if phrase not in corpus:
            logger.info(
                "recapture_ai_recoding: dropped non-verbatim phrase %r", phrase[:80]
            )
            continue

        # Confidence — clamp to [0, 1]
        try:
            conf = float(item.get("confidence", 0.0))
        except (TypeError, ValueError):
            conf = 0.0
        conf = max(0.0, min(1.0, conf))

        meat = (item.get("meat_element") or "").upper().strip()
        if meat not in _VALID_MEAT:
            meat = None

        note_id = item.get("note_id") or ""
        if note_id and note_id not in note_ids:
            # The model returned an ID we don't recognise — keep the
            # suggestion but null the source so the UI shows "unknown source"
            # instead of a fabricated id.
            note_id = None

        enc_date = item.get("encounter_date") or None
        if enc_date:
            try:
                datetime.strptime(enc_date, "%Y-%m-%d")
            except (TypeError, ValueError):
                enc_date = None

        cleaned.append({
            "evidence_phrase": phrase,
            "confidence": conf,
            "meat_element": meat,
            "encounter_date": enc_date,
            "source_note_id": note_id,
        })

    return cleaned


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _load_gap(gap_id: int) -> dict[str, Any] | None:
    sql = """
        SELECT id, tenant_id, patient_id, icd10_code, hcc_code,
               condition_label, payment_year, status, evidence_phrase,
               meat_element, source_note_id, encounter_date
        FROM recapture_gaps
        WHERE id = %s
    """
    with raf_cursor() as cur:
        cur.execute(sql, (gap_id,))
        row = cur.fetchone()
    return row


def _persist_suggestions(
    gap_id: int,
    suggestions: list[dict[str, Any]],
    llm_model_used: str,
) -> list[int]:
    """Insert suggestions into recapture_ai_suggestions, return inserted IDs."""
    if not suggestions:
        return []

    insert_sql = """
        INSERT INTO recapture_ai_suggestions
            (gap_id, evidence_phrase, confidence, meat_element,
             encounter_date, source_note_id, llm_model_used, status)
        VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending')
    """
    ids: list[int] = []
    with raf_cursor() as cur:
        for s in suggestions:
            cur.execute(insert_sql, (
                gap_id,
                s["evidence_phrase"],
                s["confidence"],
                s.get("meat_element"),
                s.get("encounter_date"),
                s.get("source_note_id"),
                llm_model_used,
            ))
            ids.append(cur.lastrowid)
    return ids


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def suggest_recoding(
    gap_id: int,
    *,
    months: int = DEFAULT_LOOKBACK_MONTHS,
    llm_call: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    """Scan recent notes for evidence of the gap's chronic condition.

    Parameters
    ----------
    gap_id:
        Primary key of a recapture_gaps row.
    months:
        Lookback window in months (default 12).
    llm_call:
        Optional callable that takes the prompt string and returns a parsed
        JSON object. Defaults to the production Vertex/Gemini caller. Tests
        inject a stub here to avoid network calls.

    Returns
    -------
    dict with keys
        ``gap_id``             : int
        ``suggestions``        : list[dict] (newly persisted, with ``id``)
        ``scanned_note_count`` : int
        ``llm_model_used``     : str
        ``error``              : str (only present on failure)
    """
    gap = _load_gap(gap_id)
    if not gap:
        return {
            "gap_id": gap_id,
            "suggestions": [],
            "scanned_note_count": 0,
            "llm_model_used": settings.gemini_model,
            "error": f"recapture_gap {gap_id} not found",
        }

    notes = _fetch_recent_notes(int(gap["patient_id"]), months=months)

    # No notes → nothing to scan, persist nothing, return empty list
    if not notes:
        return {
            "gap_id": gap_id,
            "suggestions": [],
            "scanned_note_count": 0,
            "llm_model_used": settings.gemini_model,
        }

    prompt = _build_prompt(
        icd10=str(gap["icd10_code"]),
        hcc_code=gap.get("hcc_code"),
        notes=notes,
    )

    caller = llm_call or _default_llm_call

    try:
        raw = caller(prompt)
    except Exception as exc:
        # Defensive: any LLM error → empty result, never raise out of here
        logger.error("suggest_recoding: LLM call failed for gap_id=%s: %s", gap_id, exc)
        return {
            "gap_id": gap_id,
            "suggestions": [],
            "scanned_note_count": len(notes),
            "llm_model_used": settings.gemini_model,
            "error": f"llm_call_failed: {exc}",
        }

    cleaned = _parse_response(raw, notes)

    inserted_ids = _persist_suggestions(
        gap_id=gap_id,
        suggestions=cleaned,
        llm_model_used=settings.gemini_model,
    )

    enriched: list[dict[str, Any]] = []
    for sid, s in zip(inserted_ids, cleaned):
        enriched.append({**s, "id": sid, "status": "pending"})

    return {
        "gap_id": gap_id,
        "suggestions": enriched,
        "scanned_note_count": len(notes),
        "llm_model_used": settings.gemini_model,
    }


def list_pending_suggestions(gap_id: int) -> list[dict[str, Any]]:
    """Return all pending suggestions for *gap_id*, ordered newest first."""
    sql = """
        SELECT id, gap_id, evidence_phrase, confidence, meat_element,
               encounter_date, source_note_id, llm_model_used,
               status, reviewed_by, reviewed_at, created_at
        FROM recapture_ai_suggestions
        WHERE gap_id = %s AND status = 'pending'
        ORDER BY confidence DESC, created_at DESC
    """
    with raf_cursor() as cur:
        cur.execute(sql, (gap_id,))
        rows = cur.fetchall()

    out: list[dict[str, Any]] = []
    for r in rows:
        # Normalise dates / Decimals for JSON
        if r.get("encounter_date") and not isinstance(r["encounter_date"], str):
            r["encounter_date"] = r["encounter_date"].isoformat()
        if r.get("created_at") and not isinstance(r["created_at"], str):
            r["created_at"] = r["created_at"].isoformat()
        if r.get("reviewed_at") and not isinstance(r["reviewed_at"], str):
            r["reviewed_at"] = r["reviewed_at"].isoformat()
        if r.get("confidence") is not None:
            r["confidence"] = float(r["confidence"])
        out.append(r)
    return out


def accept_suggestion(
    suggestion_id: int,
    *,
    reviewer: str | None = None,
) -> dict[str, Any]:
    """Promote suggestion to recapture_gap evidence and mark accepted.

    Returns a dict with keys ``ok``, ``suggestion_id``, ``gap_id`` on success;
    ``error`` on failure.
    """
    fetch_sql = """
        SELECT id, gap_id, evidence_phrase, meat_element,
               encounter_date, source_note_id, status
        FROM recapture_ai_suggestions
        WHERE id = %s
    """
    update_gap_sql = """
        UPDATE recapture_gaps
        SET evidence_phrase = %s,
            meat_element    = %s,
            encounter_date  = COALESCE(%s, encounter_date),
            source_note_id  = COALESCE(%s, source_note_id)
        WHERE id = %s
    """
    update_suggestion_sql = """
        UPDATE recapture_ai_suggestions
        SET status      = 'accepted',
            reviewed_by = %s,
            reviewed_at = NOW()
        WHERE id = %s
    """

    with raf_cursor() as cur:
        cur.execute(fetch_sql, (suggestion_id,))
        row = cur.fetchone()
        if not row:
            return {"ok": False, "error": f"suggestion {suggestion_id} not found"}
        if row["status"] != "pending":
            return {
                "ok": False,
                "error": f"suggestion {suggestion_id} already {row['status']}",
            }

        cur.execute(update_gap_sql, (
            row["evidence_phrase"],
            row["meat_element"],
            row["encounter_date"],
            row["source_note_id"],
            row["gap_id"],
        ))
        cur.execute(update_suggestion_sql, (reviewer, suggestion_id))

    return {
        "ok": True,
        "suggestion_id": suggestion_id,
        "gap_id": int(row["gap_id"]),
        "status": "accepted",
    }


def reject_suggestion(
    suggestion_id: int,
    *,
    reviewer: str | None = None,
) -> dict[str, Any]:
    """Mark a suggestion as rejected (no change to recapture_gap)."""
    sql = """
        UPDATE recapture_ai_suggestions
        SET status      = 'rejected',
            reviewed_by = %s,
            reviewed_at = NOW()
        WHERE id = %s AND status = 'pending'
    """
    with raf_cursor() as cur:
        cur.execute(sql, (reviewer, suggestion_id))
        affected = cur.rowcount

    if affected == 0:
        return {"ok": False, "error": f"suggestion {suggestion_id} not pending"}

    return {"ok": True, "suggestion_id": suggestion_id, "status": "rejected"}
