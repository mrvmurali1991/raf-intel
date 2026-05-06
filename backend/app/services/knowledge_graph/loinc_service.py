"""
LOINC integration + lab signal graph.

Bridges free-text or coded laboratory results to LOINC codes, evaluates the
LOINC value against curated thresholds, and returns suggested condition
concepts (linked to HCCs via the knowledge graph).

This service is ontology-aware reasoning ON TOP of the existing
``lab_suspect_engine`` — it does NOT replace the legacy hardcoded thresholds.
The legacy engine continues to work unchanged; this module provides a database
backed signal table that the legacy engine consults first.

Public API
----------
resolve_lab_to_loinc(test_name)            -> list[dict]
evaluate_lab_value(loinc_code, value, unit) -> list[dict]
get_loinc_signals_for_hcc(hcc_code)        -> list[dict]
bulk_evaluate_patient_labs(patient_id, since_days=730) -> dict
evaluate_threshold(value, low, high, meaning) -> bool

Schema dependencies
-------------------
* ``kg_lab_signals``                (this migration)
* ``knowledge_graph_concepts``      (Agent 1 migration)
* ``knowledge_graph_edges``         (Agent 1 migration, optional, used for
                                     traversal not required by core API)
* ``hcc_icd10_crosswalk``           (existing)
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Any, Iterable

from app.db import openemr_cursor, raf_cursor

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Threshold evaluation (mirrors lab_suspect_engine semantics, on numeric inputs)
# ---------------------------------------------------------------------------

def evaluate_threshold(
    value: float,
    low: float | None,
    high: float | None,
    meaning: str,
) -> bool:
    """
    Return True when *value* satisfies the threshold rule.

    meaning:
        'above'   -> value >= high
        'below'   -> value <= low
        'outside' -> value < low OR value > high
        'within'  -> low <= value <= high
    """
    m = (meaning or "").lower()
    try:
        v = float(value)
    except (TypeError, ValueError):
        return False

    if m == "above":
        return high is not None and v >= float(high)
    if m == "below":
        return low is not None and v <= float(low)
    if m == "outside":
        if low is not None and v < float(low):
            return True
        if high is not None and v > float(high):
            return True
        return False
    if m == "within":
        if low is not None and v < float(low):
            return False
        if high is not None and v > float(high):
            return False
        return True
    logger.warning("Unknown threshold_meaning '%s'", meaning)
    return False


# ---------------------------------------------------------------------------
# Lab name normalisation + fuzzy resolution
# ---------------------------------------------------------------------------

# Cheap canonical aliases.  Used as a quick win before the SQL fuzzy LIKE.
_ALIASES: dict[str, str] = {
    "hba1c": "hemoglobin a1c",
    "a1c": "hemoglobin a1c",
    "glycohb": "hemoglobin a1c",
    "glycated hb": "hemoglobin a1c",
    "egfr": "estimated glomerular filtration rate",
    "ldl": "ldl cholesterol",
    "hdl": "hdl cholesterol",
    "tg": "triglycerides",
    "bnp": "natriuretic peptide b",
    "trop i": "troponin i",
    "trop t": "troponin t",
    "tnt": "troponin t",
    "tni": "troponin i",
    "cr": "creatinine",
    "creat": "creatinine",
    "psa": "prostate specific antigen",
    "tsh": "thyroid stimulating hormone",
    "fbg": "glucose fasting",
    "fbs": "glucose fasting",
    "hgb": "hemoglobin",
    "hb": "hemoglobin",
    "alt": "alanine aminotransferase",
    "ast": "aspartate aminotransferase",
    "ggt": "gamma glutamyl transferase",
    "alp": "alkaline phosphatase",
    "tbili": "bilirubin total",
    "dbili": "bilirubin direct",
    "cd4": "cd4 count",
    "viral load": "hiv viral load",
    "inr": "international normalized ratio",
    "pt": "prothrombin time",
    "ptt": "partial thromboplastin time",
}


_NON_ALPHANUM = re.compile(r"[^a-z0-9]+")


def _normalise(text: str) -> str:
    text = (text or "").lower().strip()
    text = _NON_ALPHANUM.sub(" ", text).strip()
    return _ALIASES.get(text, text)


def _tokens(text: str) -> set[str]:
    return {t for t in _normalise(text).split(" ") if t}


def _similarity(query: str, candidate: str) -> float:
    """Cheap Jaccard similarity over token sets, plus prefix boost."""
    q, c = _tokens(query), _tokens(candidate)
    if not q or not c:
        return 0.0
    jaccard = len(q & c) / len(q | c)
    # Substring boost — common when free-text says "HbA1c" but candidate is
    # "Hemoglobin A1c".
    nq, nc = _normalise(query), _normalise(candidate)
    sub = 0.2 if (nq and nc and (nq in nc or nc in nq)) else 0.0
    return min(1.0, jaccard + sub)


def resolve_lab_to_loinc(test_name: str, limit: int = 5) -> list[dict[str, Any]]:
    """
    Resolve a free-text lab/test name to candidate LOINC entries from
    ``kg_lab_signals``.

    Returns up to *limit* hits ordered by descending similarity:

        [{loinc_code, test_name, unit, similarity, signals_concept_id,
          threshold_meaning, threshold_low, threshold_high}, ...]
    """
    if not test_name or not test_name.strip():
        return []

    needle = _normalise(test_name)
    like_token = f"%{needle.split(' ')[0]}%" if needle else "%"

    rows: list[dict[str, Any]] = []
    sql = """
        SELECT id, loinc_code, test_name, unit, signals_concept_id,
               threshold_meaning, threshold_low, threshold_high, confidence
        FROM kg_lab_signals
        WHERE is_active = 1
          AND (LOWER(test_name) LIKE %s OR loinc_code = %s)
    """
    try:
        with raf_cursor() as cur:
            cur.execute(sql, (like_token, test_name.strip()))
            rows = cur.fetchall() or []
    except Exception as exc:
        logger.warning("resolve_lab_to_loinc: db lookup failed: %s", exc)
        return []

    # If LIKE returned nothing, fall back to a broader scan (still bounded).
    if not rows:
        try:
            with raf_cursor() as cur:
                cur.execute(
                    """
                    SELECT id, loinc_code, test_name, unit, signals_concept_id,
                           threshold_meaning, threshold_low, threshold_high, confidence
                    FROM kg_lab_signals
                    WHERE is_active = 1
                    LIMIT 500
                    """
                )
                rows = cur.fetchall() or []
        except Exception as exc:
            logger.warning("resolve_lab_to_loinc: broad scan failed: %s", exc)
            return []

    scored: list[dict[str, Any]] = []
    for r in rows:
        sim = _similarity(test_name, r["test_name"])
        if r.get("loinc_code") and r["loinc_code"].strip() == test_name.strip():
            sim = 1.0
        if sim <= 0.0:
            continue
        scored.append({
            "loinc_code": r["loinc_code"],
            "test_name": r["test_name"],
            "unit": r.get("unit"),
            "similarity": round(sim, 4),
            "signals_concept_id": r["signals_concept_id"],
            "threshold_meaning": r["threshold_meaning"],
            "threshold_low": float(r["threshold_low"]) if r.get("threshold_low") is not None else None,
            "threshold_high": float(r["threshold_high"]) if r.get("threshold_high") is not None else None,
            "confidence": float(r["confidence"]) if r.get("confidence") is not None else None,
        })

    # Deduplicate by loinc_code keeping the highest similarity.
    best: dict[str, dict[str, Any]] = {}
    for row in scored:
        prev = best.get(row["loinc_code"])
        if prev is None or row["similarity"] > prev["similarity"]:
            best[row["loinc_code"]] = row

    out = sorted(best.values(), key=lambda d: d["similarity"], reverse=True)
    return out[:limit]


# ---------------------------------------------------------------------------
# Lookup helpers — concept + HCC enrichment
# ---------------------------------------------------------------------------

def _fetch_concept(concept_id: int) -> dict[str, Any] | None:
    sql = """
        SELECT id, code_system, code, display_name, hcc_code
        FROM knowledge_graph_concepts
        WHERE id = %s
        LIMIT 1
    """
    try:
        with raf_cursor() as cur:
            cur.execute(sql, (concept_id,))
            row = cur.fetchone()
            return row
    except Exception as exc:
        logger.debug("_fetch_concept(%s) failed: %s", concept_id, exc)
        return None


def _hcc_for_icd10(icd10: str | None) -> str | None:
    if not icd10:
        return None
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT hcc_code FROM hcc_icd10_crosswalk
                WHERE REPLACE(icd10_code, '.', '') = REPLACE(%s, '.', '')
                LIMIT 1
                """,
                (icd10,),
            )
            row = cur.fetchone()
            if row and row.get("hcc_code") is not None:
                return f"HCC{row['hcc_code']}"
    except Exception as exc:
        logger.debug("_hcc_for_icd10(%s) failed: %s", icd10, exc)
    return None


def _explain(low: float | None, high: float | None, meaning: str, value: float, unit: str | None) -> str:
    u = f" {unit}" if unit else ""
    if meaning == "above":
        return f"{value}{u} ≥ {high}{u} (threshold-above)"
    if meaning == "below":
        return f"{value}{u} ≤ {low}{u} (threshold-below)"
    if meaning == "outside":
        return f"{value}{u} outside [{low}, {high}]{u}"
    if meaning == "within":
        return f"{value}{u} within [{low}, {high}]{u}"
    return f"{value}{u} matched rule ({meaning})"


# ---------------------------------------------------------------------------
# Core: evaluate a LOINC value against all signal rows
# ---------------------------------------------------------------------------

def evaluate_lab_value(
    loinc_code: str,
    value: float | int | str,
    unit: str | None = None,
) -> list[dict[str, Any]]:
    """
    Evaluate *value* against every signal row registered for *loinc_code*.

    Returns a list of triggered signals — empty when none fire or when the
    LOINC code is unknown.

    Each item:
        {
          loinc_code, test_name, unit,
          condition_concept_id, condition_code, condition_display, hcc_code,
          confidence, threshold_meaning, threshold_low, threshold_high,
          threshold_explanation
        }
    """
    if loinc_code is None:
        return []
    try:
        v = float(value)
    except (TypeError, ValueError):
        logger.debug("evaluate_lab_value: non-numeric value %r for %s", value, loinc_code)
        return []

    sql = """
        SELECT id, loinc_code, test_name, unit, threshold_low, threshold_high,
               threshold_meaning, signals_concept_id, confidence, notes
        FROM kg_lab_signals
        WHERE is_active = 1 AND loinc_code = %s
    """
    rows: list[dict[str, Any]] = []
    try:
        with raf_cursor() as cur:
            cur.execute(sql, (loinc_code.strip(),))
            rows = cur.fetchall() or []
    except Exception as exc:
        logger.warning("evaluate_lab_value: db lookup failed for %s: %s", loinc_code, exc)
        return []

    triggered: list[dict[str, Any]] = []
    for r in rows:
        low = float(r["threshold_low"]) if r.get("threshold_low") is not None else None
        high = float(r["threshold_high"]) if r.get("threshold_high") is not None else None
        meaning = (r.get("threshold_meaning") or "").lower()

        if not evaluate_threshold(v, low, high, meaning):
            continue

        concept = _fetch_concept(r["signals_concept_id"]) or {}
        hcc_code = concept.get("hcc_code")
        if not hcc_code and concept.get("code_system", "").lower() in ("icd10", "icd-10", "icd10cm"):
            hcc_code = _hcc_for_icd10(concept.get("code"))

        triggered.append({
            "signal_id": r["id"],
            "loinc_code": r["loinc_code"],
            "test_name": r["test_name"],
            "unit": r.get("unit") or unit,
            "value": v,
            "condition_concept_id": r["signals_concept_id"],
            "condition_code": concept.get("code"),
            "condition_display": concept.get("display_name"),
            "hcc_code": hcc_code,
            "confidence": float(r["confidence"]) if r.get("confidence") is not None else 0.7,
            "threshold_meaning": meaning,
            "threshold_low": low,
            "threshold_high": high,
            "threshold_explanation": _explain(low, high, meaning, v, r.get("unit") or unit),
            "notes": r.get("notes"),
        })
    return triggered


# ---------------------------------------------------------------------------
# Reverse lookup: which labs signal a given HCC?
# ---------------------------------------------------------------------------

def _normalise_hcc(hcc_code: str | int) -> str:
    s = str(hcc_code).strip()
    if not s:
        return ""
    if s.upper().startswith("HCC"):
        return s.upper()
    return f"HCC{s}"


def get_loinc_signals_for_hcc(hcc_code: str | int) -> list[dict[str, Any]]:
    """
    Reverse lookup — return every kg_lab_signals row whose linked concept
    maps (directly or via icd10 crosswalk) to *hcc_code*.

    *hcc_code* may be supplied as ``"HCC18"`` or just ``18``.
    """
    target = _normalise_hcc(hcc_code)
    if not target:
        return []
    target_num = target.removeprefix("HCC")

    # NOTE: knowledge_graph_concepts columns are ``ontology``, ``code``,
    # ``preferred_label`` — NOT the legacy ``code_system`` / ``display_name`` /
    # ``hcc_code`` names that an earlier draft of this service expected.
    sql = """
        SELECT s.id, s.loinc_code, s.test_name, s.unit, s.threshold_low,
               s.threshold_high, s.threshold_meaning, s.confidence, s.notes,
               c.id  AS concept_id, c.code AS concept_code,
               c.ontology AS concept_ontology,
               c.preferred_label AS concept_display
        FROM kg_lab_signals s
        JOIN knowledge_graph_concepts c ON c.id = s.signals_concept_id
        WHERE s.is_active = 1
    """
    rows: list[dict[str, Any]] = []
    try:
        with raf_cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall() or []
    except Exception as exc:
        logger.warning("get_loinc_signals_for_hcc: db lookup failed: %s", exc)
        return []

    out: list[dict[str, Any]] = []
    for r in rows:
        concept_ontology = (r.get("concept_ontology") or "").strip().lower()
        concept_code = (r.get("concept_code") or "").strip()

        # If the concept is itself an HCC concept, compare codes directly.
        if concept_ontology == "hcc":
            cmp_hcc = (
                concept_code
                if concept_code.upper().startswith("HCC")
                else f"HCC{concept_code}"
            )
            if cmp_hcc.upper() != target:
                continue
        else:
            # Otherwise treat the concept code as ICD-10 and traverse the crosswalk.
            mapped = _hcc_for_icd10(concept_code)
            if mapped is None or mapped.upper() != target:
                continue

        out.append({
            "loinc_code": r["loinc_code"],
            "test_name": r["test_name"],
            "unit": r.get("unit"),
            "threshold_meaning": r["threshold_meaning"],
            "threshold_low": float(r["threshold_low"]) if r.get("threshold_low") is not None else None,
            "threshold_high": float(r["threshold_high"]) if r.get("threshold_high") is not None else None,
            "confidence": float(r["confidence"]) if r.get("confidence") is not None else None,
            "condition_concept_id": r["concept_id"],
            "condition_code": r["concept_code"],
            "condition_display": r["concept_display"],
            "hcc_code": target,
            "notes": r.get("notes"),
        })
    return out


# ---------------------------------------------------------------------------
# Bulk evaluation for a patient — pulls labs from openemr.procedure_result
# ---------------------------------------------------------------------------

_NUMERIC_RE = re.compile(r"-?\d+\.?\d*")


def _coerce_numeric(raw: Any) -> float | None:
    """Best-effort numeric extraction from procedure_result.result strings."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    s = str(raw).strip()
    if not s:
        return None
    m = _NUMERIC_RE.search(s)
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


def _patient_labs(patient_id: int, since_days: int) -> list[dict[str, Any]]:
    """Pull recent labs for a patient via the OpenEMR pool."""
    cutoff = datetime.utcnow() - timedelta(days=max(1, int(since_days)))
    sql = """
        SELECT
            pr.id,
            pr.procedure_order_id,
            pr.result_code,
            pr.result_text,
            pr.date,
            pr.result AS value,
            pr.units AS unit,
            pr.range,
            pr.abnormal
        FROM procedure_result pr
        JOIN procedure_order po ON po.procedure_order_id = pr.procedure_order_id
        WHERE po.patient_id = %s AND (pr.date IS NULL OR pr.date >= %s)
        ORDER BY pr.date DESC
        LIMIT 1000
    """
    try:
        with openemr_cursor() as cur:
            cur.execute(sql, (patient_id, cutoff))
            return cur.fetchall() or []
    except Exception as exc:
        logger.warning("bulk_evaluate_patient_labs: openemr fetch failed: %s", exc)
        return []


def bulk_evaluate_patient_labs(
    patient_id: int,
    since_days: int = 730,
) -> dict[str, Any]:
    """
    Pull every recent lab for *patient_id* and run the LOINC signal engine.

    Resolution order for each lab row:
        1. ``result_code``                — assumed to be a LOINC if present
        2. ``result_text``                — fuzzy-resolved via resolve_lab_to_loinc
    """
    labs = _patient_labs(patient_id, since_days)
    triggered: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []

    for lab in labs:
        v = _coerce_numeric(lab.get("value"))
        if v is None:
            continue

        unit = lab.get("unit")
        loinc_candidates: list[str] = []

        code = (lab.get("result_code") or "").strip()
        if code:
            # Heuristic: LOINC codes look like "1234-5".
            if re.match(r"^\d{1,5}-\d$", code):
                loinc_candidates.append(code)

        if not loinc_candidates:
            label = lab.get("result_text") or ""
            for hit in resolve_lab_to_loinc(label, limit=1):
                loinc_candidates.append(hit["loinc_code"])

        if not loinc_candidates:
            unresolved.append({
                "lab_id": lab.get("id"),
                "result_code": code,
                "result_text": lab.get("result_text"),
                "value": v,
                "unit": unit,
            })
            continue

        for loinc in loinc_candidates:
            for sig in evaluate_lab_value(loinc, v, unit):
                sig.update({
                    "lab_id": lab.get("id"),
                    "result_date": lab.get("date").isoformat() if lab.get("date") else None,
                    "source": "kg_lab_signals",
                })
                triggered.append(sig)

    # Deduplicate triggered signals by (signal_id, lab_id) keeping latest date.
    dedup: dict[tuple, dict[str, Any]] = {}
    for sig in triggered:
        key = (sig.get("signal_id"), sig.get("lab_id"))
        prev = dedup.get(key)
        if prev is None or (sig.get("result_date") or "") > (prev.get("result_date") or ""):
            dedup[key] = sig
    triggered = sorted(
        dedup.values(),
        key=lambda s: (s.get("confidence") or 0.0),
        reverse=True,
    )

    return {
        "patient_id": patient_id,
        "since_days": since_days,
        "labs_scanned": len(labs),
        "triggered_signals": triggered,
        "unresolved_labs": unresolved,
    }


# ---------------------------------------------------------------------------
# Convenience: bulk-evaluate via in-memory list of (loinc, value, unit)
# Used by the lab_suspect_engine integration to avoid hitting OpenEMR twice.
# ---------------------------------------------------------------------------

def evaluate_many(
    rows: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Evaluate an iterable of {loinc_code, value, unit} rows."""
    out: list[dict[str, Any]] = []
    for r in rows:
        loinc = r.get("loinc_code")
        if not loinc:
            continue
        for sig in evaluate_lab_value(loinc, r.get("value"), r.get("unit")):
            out.append(sig)
    return out
