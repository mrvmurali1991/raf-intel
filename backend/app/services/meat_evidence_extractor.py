"""MEAT evidence-snippet auto-extraction (Gap #12).

Competitors RAAPID / Keebler / Reveleer EVE surface the *exact sentence*
from the clinical note that proves each MEAT letter (Monitor / Evaluate /
Assess / Treat).  RAF Intelligence today only shows binary M/E/A/T
booleans — the raw text columns on ``raf_meat_evidence`` are mostly empty
because rule-based extraction does not carry sentence-level provenance.

This module bridges the gap.  For a single (patient_id, hcc_code, icd10,
year) tuple it:

  1. Pulls every clinical note attached to the patient in the
     measurement year (via ``openemr_connector.get_all_clinical_notes_for_patient``).
  2. For each note, prompts a Vertex AI Gemini model with a focused
     instruction that asks it to return the **verbatim sentence** that
     proves each of M / E / A / T for the supplied HCC, plus the
     character offsets of that sentence within the note text.
  3. Merges results across notes — keeping the highest-confidence
     sentence per letter, tie-breaking on the most recent encounter
     date — so the caller receives one canonical ``MEATEvidence``
     dataclass.

The output is persisted to ``raf_meat_evidence`` via
``meat_evidence_service.store_meat_evidence`` plus the new
``meat_*_offsets`` and ``source_encounter_id`` columns added in
Alembic migration 030.

Public API
----------
extract_meat_evidence_for_hcc(patient_id, hcc_code, icd10, measurement_year, tenant_id)
    -> MEATEvidence

MEATEvidence is a TypedDict with the shape the spec requires:
    {
      meat_m_text, meat_m_offsets,
      meat_e_text, meat_e_offsets,
      meat_a_text, meat_a_offsets,
      meat_t_text, meat_t_offsets,
      source_encounter_id,
    }

Failure mode: any LLM / network error returns an all-None result so the
caller can fall back to the rule-based extractor without crashing.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any

from app.db import raf_cursor

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# V28 HCC labels — used to give the LLM a human-readable target.
# ---------------------------------------------------------------------------
try:
    from hccinfhir.defaults import labels_default as _labels_default
except Exception:  # pragma: no cover — defensive
    _labels_default = {}

_V28_MODEL = "CMS-HCC Model V28"


def _hcc_label(hcc_code: str | int) -> str:
    code = str(hcc_code).replace("HCC", "").strip()
    return _labels_default.get((code, _V28_MODEL)) or f"HCC {code}"


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class MEATEvidence:
    """Sentence-level MEAT evidence for one HCC."""

    meat_m_text: str | None = None
    meat_m_offsets: list[int] | None = None
    meat_e_text: str | None = None
    meat_e_offsets: list[int] | None = None
    meat_a_text: str | None = None
    meat_a_offsets: list[int] | None = None
    meat_t_text: str | None = None
    meat_t_offsets: list[int] | None = None
    source_encounter_id: int | None = None
    # Confidence per letter — 0.0..1.0.  Internal use for the merge step.
    confidence: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("confidence", None)
        return d

    def letters_present(self) -> int:
        return sum(
            1 for v in (
                self.meat_m_text,
                self.meat_e_text,
                self.meat_a_text,
                self.meat_t_text,
            ) if v
        )


# ---------------------------------------------------------------------------
# Note collection
# ---------------------------------------------------------------------------

def _coerce_note_date(raw: Any) -> date | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    s = str(raw).strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s[: len(fmt) + 2], fmt).date()
        except ValueError:
            continue
    return None


def _fetch_year_notes(patient_id: int, year: int) -> list[dict[str, Any]]:
    """Return clinical notes for *patient_id* whose date is in *year*.

    Uses the existing ``openemr_connector.get_all_clinical_notes_for_patient``
    helper which already merges OpenEMR ``form_soap`` rows with
    ingested ``clinical_notes`` rows.  Notes outside the measurement
    year are filtered out so we don't burn LLM tokens on old chart data.
    """
    try:
        from app.services.openemr_connector import get_all_clinical_notes_for_patient
        raw = get_all_clinical_notes_for_patient(patient_id) or []
    except Exception as exc:
        logger.warning(
            "meat_extractor: note fetch failed pid=%s year=%s: %s",
            patient_id, year, exc,
        )
        return []

    kept: list[dict[str, Any]] = []
    for n in raw:
        text = (n.get("note_text") or "").strip()
        if not text:
            continue
        nd = _coerce_note_date(n.get("date"))
        if nd is None or nd.year != year:
            continue
        kept.append({
            "encounter_id": int(n.get("encounter") or 0) or None,
            "date": nd,
            "text": text,
        })
    # Most recent first — used for tie-breaking.
    kept.sort(key=lambda r: r["date"], reverse=True)
    return kept


# ---------------------------------------------------------------------------
# Prompt construction & LLM call
# ---------------------------------------------------------------------------

_PROMPT_TEMPLATE = """You are a CMS HCC RADV auditor extracting MEAT evidence from a clinical note.

Definitions (CMS Risk-Adjustment guide):
  M = Monitor   — vitals trending, labs trending, symptom progression notes
  E = Evaluate  — assessment of severity, response to treatment, diagnostic workup
  A = Assess    — explicit diagnosis statement or differential
  T = Treat     — current medication, procedure, referral, lifestyle order

For the HCC below, return the SINGLE BEST verbatim sentence in the note
that PROVES each letter.  If a letter has no supporting sentence, return
null for that letter.

HCC target:
  Code  : HCC {hcc_code}
  Label : {hcc_label}
  ICD-10: {icd10}

Clinical note ({note_length} chars):
\"\"\"
{note_text}
\"\"\"

Return STRICT JSON with this exact shape (no commentary, no markdown):
{{
  "m_sentence": <string or null>,
  "m_start":    <int or null>,
  "m_end":      <int or null>,
  "m_confidence": <float 0..1>,
  "e_sentence": <string or null>,
  "e_start":    <int or null>,
  "e_end":      <int or null>,
  "e_confidence": <float 0..1>,
  "a_sentence": <string or null>,
  "a_start":    <int or null>,
  "a_end":      <int or null>,
  "a_confidence": <float 0..1>,
  "t_sentence": <string or null>,
  "t_start":    <int or null>,
  "t_end":      <int or null>,
  "t_confidence": <float 0..1>
}}

Rules:
  * The sentence MUST appear verbatim in the note (copy it exactly).
  * Offsets are 0-based character positions: note_text[start:end] == sentence.
  * Confidence > 0.6 means the evidence is RADV-defensible.
  * If no sentence applies, set sentence/start/end to null and confidence to 0.
"""

_JSON_BLOB_RE = re.compile(r"\{.*\}", re.DOTALL)


def _llm_extract_one_note(
    note_text: str,
    hcc_code: str,
    hcc_label: str,
    icd10: str,
    *,
    tenant_id: str | None = None,
) -> dict[str, Any] | None:
    """Call Gemini once for a single note. Returns parsed dict or None on failure."""
    # Truncate very long notes to keep prompt size predictable.  4000 chars
    # captures a typical full SOAP note while staying well under the
    # gemini-2.0-flash context window.
    truncated = note_text[:4000]
    prompt = _PROMPT_TEMPLATE.format(
        hcc_code=hcc_code,
        hcc_label=hcc_label,
        icd10=icd10 or "(no ICD-10 supplied)",
        note_length=len(truncated),
        note_text=truncated,
    )

    try:
        from app.services.llm import llm_generate
        raw = llm_generate(
            prompt,
            temperature=0.0,
            tenant_id=tenant_id,
        )
    except Exception as exc:
        logger.warning("meat_extractor: llm_generate failed: %s", exc)
        return None

    if not raw:
        return None

    # Gemini sometimes returns ```json … ``` fences — strip them.
    stripped = raw.strip()
    if stripped.startswith("```"):
        # Remove the leading fence line and any trailing fence.
        parts = stripped.split("```")
        # parts == ["", "json\n{...}\n", ""] typically
        if len(parts) >= 2:
            stripped = parts[1]
            if stripped.lstrip().lower().startswith("json"):
                stripped = stripped.split("\n", 1)[1] if "\n" in stripped else ""

    # Fallback: grab the first {...} blob.
    blob = stripped.strip()
    if not blob.startswith("{"):
        m = _JSON_BLOB_RE.search(stripped)
        if not m:
            logger.debug("meat_extractor: no JSON blob in LLM response")
            return None
        blob = m.group(0)

    try:
        return json.loads(blob)
    except json.JSONDecodeError as exc:
        logger.debug("meat_extractor: JSON parse failed: %s", exc)
        return None


def _validate_offsets(note_text: str, sentence: str | None, start: Any, end: Any) -> list[int] | None:
    """Sanity-check the offsets returned by the LLM.

    If they are missing / non-integer / point at the wrong slice we try to
    relocate the sentence ourselves via ``str.find``.  Returns ``[start, end]``
    or ``None`` if we cannot verify the sentence appears in the note at all.
    """
    if not sentence:
        return None
    try:
        s = int(start)
        e = int(end)
    except (TypeError, ValueError):
        s = e = -1
    if 0 <= s < e <= len(note_text) and note_text[s:e].strip() == sentence.strip():
        return [s, e]
    # Try to relocate.
    idx = note_text.find(sentence)
    if idx >= 0:
        return [idx, idx + len(sentence)]
    return None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def extract_meat_evidence_for_hcc(
    patient_id: int,
    hcc_code: str | int,
    icd10: str,
    measurement_year: int,
    tenant_id: str = "",
) -> MEATEvidence:
    """Extract MEAT sentence-level evidence for one HCC.

    Parameters
    ----------
    patient_id:
        RAF Intelligence patient ID.
    hcc_code:
        HCC code as a string ("18" / "HCC18") or int.
    icd10:
        Representative ICD-10 code for this HCC (gives the LLM clinical
        precision when the HCC label alone is ambiguous).
    measurement_year:
        Only encounters in this calendar year are scanned.
    tenant_id:
        Tenant ID forwarded to the LLM audit trail.

    Returns
    -------
    MEATEvidence
        Best evidence per letter across all notes.  All fields may be
        ``None`` when no clinical text was extractable.
    """
    hcc_str = str(hcc_code).replace("HCC", "").strip()
    label = _hcc_label(hcc_str)

    notes = _fetch_year_notes(patient_id, measurement_year)
    if not notes:
        logger.info(
            "meat_extractor: pid=%s hcc=%s year=%s — no notes in year",
            patient_id, hcc_str, measurement_year,
        )
        return MEATEvidence()

    # --- Per-letter merge state.  Keep best confidence; tie-break on
    # most recent encounter date (notes are pre-sorted newest first).
    best: dict[str, dict[str, Any]] = {
        letter: {"conf": -1.0, "text": None, "offsets": None, "enc_id": None}
        for letter in ("m", "e", "a", "t")
    }

    for note in notes:
        parsed = _llm_extract_one_note(
            note["text"], hcc_str, label, icd10, tenant_id=tenant_id or None,
        )
        if not parsed:
            continue
        for letter in ("m", "e", "a", "t"):
            sentence = parsed.get(f"{letter}_sentence")
            if not sentence or not str(sentence).strip():
                continue
            offsets = _validate_offsets(
                note["text"],
                str(sentence),
                parsed.get(f"{letter}_start"),
                parsed.get(f"{letter}_end"),
            )
            if offsets is None:
                # Hallucinated sentence — drop.
                continue
            try:
                conf = float(parsed.get(f"{letter}_confidence") or 0.0)
            except (TypeError, ValueError):
                conf = 0.0
            cur = best[letter]
            # Strictly-greater confidence wins; equal confidence is
            # already resolved correctly because notes iterate newest-first
            # and we only overwrite on '>'.
            if conf > cur["conf"]:
                best[letter] = {
                    "conf": conf,
                    "text": str(sentence).strip(),
                    "offsets": offsets,
                    "enc_id": note["encounter_id"],
                }

    # Pick the source_encounter_id as the encounter contributing the most
    # accepted letters (ties broken by most recent — first hit wins because
    # the merge above already preferred newer notes for equal confidence).
    enc_counts: dict[int, int] = {}
    for letter in ("m", "e", "a", "t"):
        eid = best[letter]["enc_id"]
        if eid:
            enc_counts[eid] = enc_counts.get(eid, 0) + 1
    source_enc: int | None = None
    if enc_counts:
        source_enc = max(enc_counts.items(), key=lambda kv: kv[1])[0]

    out = MEATEvidence(
        meat_m_text=best["m"]["text"],
        meat_m_offsets=best["m"]["offsets"],
        meat_e_text=best["e"]["text"],
        meat_e_offsets=best["e"]["offsets"],
        meat_a_text=best["a"]["text"],
        meat_a_offsets=best["a"]["offsets"],
        meat_t_text=best["t"]["text"],
        meat_t_offsets=best["t"]["offsets"],
        source_encounter_id=source_enc,
        confidence={
            letter: float(best[letter]["conf"]) for letter in ("m", "e", "a", "t")
        },
    )

    logger.info(
        "meat_extractor: pid=%s hcc=%s year=%s — letters=%d/4 enc=%s",
        patient_id, hcc_str, measurement_year, out.letters_present(), source_enc,
    )
    return out


# ---------------------------------------------------------------------------
# Persistence — write the extracted evidence into raf_meat_evidence.
# ---------------------------------------------------------------------------

def _ensure_offset_columns() -> None:
    """Idempotently ensure the new JSON / source_encounter_id columns exist.

    Alembic 030 is the source of truth, but environments that have not yet
    run migrations should still be able to use this code without crashing.
    """
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_schema = DATABASE()
                  AND table_name   = 'raf_meat_evidence'
                """
            )
            existing = {str(r["column_name"]).lower() for r in cur.fetchall() or []}
            for col in (
                "meat_m_offsets", "meat_e_offsets",
                "meat_a_offsets", "meat_t_offsets",
            ):
                if col not in existing:
                    cur.execute(
                        f"ALTER TABLE raf_meat_evidence ADD COLUMN `{col}` JSON NULL"
                    )
            if "source_encounter_id" not in existing:
                cur.execute(
                    "ALTER TABLE raf_meat_evidence "
                    "ADD COLUMN `source_encounter_id` INT NULL"
                )
    except Exception as exc:
        # Best-effort — alembic should handle this. We log and continue.
        logger.debug("meat_extractor: _ensure_offset_columns skipped: %s", exc)


def persist_meat_evidence(
    patient_hcc_id: int,
    evidence: MEATEvidence,
    *,
    encounter_date: date | None = None,
    measurement_year: int | None = None,
) -> int | None:
    """Persist ``MEATEvidence`` into ``raf_meat_evidence``.

    Routes through ``meat_evidence_service.store_meat_evidence`` for the
    text + presence columns (so all existing book-keeping fires) and then
    issues a follow-up UPDATE for the new offset / source_encounter_id
    columns added in migration 030.

    Returns the row id, or ``None`` when there is no evidence worth
    persisting (all four letters empty).
    """
    if evidence.letters_present() == 0:
        return None

    _ensure_offset_columns()

    # Use the source encounter as the canonical encounter_id when we have
    # one; otherwise fall back to a sentinel 0 (matches existing
    # auto_meat_extractor convention).
    enc_id = int(evidence.source_encounter_id or 0)
    enc_date = encounter_date or date.today()

    # Stitched excerpt — gives the UI tooltip something readable even when
    # the full note isn't shown alongside the chips.
    excerpt_parts = [
        evidence.meat_m_text,
        evidence.meat_e_text,
        evidence.meat_a_text,
        evidence.meat_t_text,
    ]
    excerpt = " | ".join(p for p in excerpt_parts if p)[:4000]

    from app.services import meat_evidence_service

    try:
        evidence_id = meat_evidence_service.store_meat_evidence(
            patient_hcc_id=patient_hcc_id,
            encounter_id=enc_id,
            encounter_date=enc_date,
            meat_monitoring=evidence.meat_m_text,
            meat_evaluation=evidence.meat_e_text,
            meat_assessment=evidence.meat_a_text,
            meat_treatment=evidence.meat_t_text,
            raw_note_excerpt=excerpt,
            nlp_model="gemini-2.0-flash:meat_extractor",
            confidence=sum(evidence.confidence.values()) / 4.0,
            measurement_year=measurement_year,
        )
    except Exception as exc:
        logger.warning(
            "meat_extractor: store_meat_evidence failed phcc=%s: %s",
            patient_hcc_id, exc,
        )
        return None

    # Follow-up UPDATE for offset + source_encounter_id columns.
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                UPDATE raf_meat_evidence
                SET meat_m_offsets      = %s,
                    meat_e_offsets      = %s,
                    meat_a_offsets      = %s,
                    meat_t_offsets      = %s,
                    source_encounter_id = COALESCE(%s, source_encounter_id)
                WHERE id = %s
                """,
                (
                    json.dumps(evidence.meat_m_offsets) if evidence.meat_m_offsets else None,
                    json.dumps(evidence.meat_e_offsets) if evidence.meat_e_offsets else None,
                    json.dumps(evidence.meat_a_offsets) if evidence.meat_a_offsets else None,
                    json.dumps(evidence.meat_t_offsets) if evidence.meat_t_offsets else None,
                    evidence.source_encounter_id,
                    evidence_id,
                ),
            )
    except Exception as exc:
        logger.warning(
            "meat_extractor: offset UPDATE failed id=%s: %s",
            evidence_id, exc,
        )

    return evidence_id
