"""
Synthetic labelled-set generator for v1 calibration.

WHY THIS EXISTS
---------------
We do not have chart-reviewer-labelled outcomes yet (the
``raf_suspect_conditions.status`` column has few reviewed rows).  To
ship *something* better than raw uncalibrated scores, we generate a
synthetic label for each suspect from heuristics we trust.  A
calibrator fit on these labels is strictly bounded by the quality of
the heuristics — if the rules are wrong, the calibrator is wrong in
exactly the same way.

BOOTSTRAP LABEL RULES (v1)
--------------------------
A suspect row is labelled positive (``label=1``) iff **any** of:

  1. It has >= 2 independent corroborating signals.  For example a
     medication signal that co-occurs with a lab signal for the same
     HCC, or an LLM suspect that matches a regex-based one on the
     same ICD-10 3-char stem.
  2. It is a "historical recapture" suspect (source=history) — the
     prior-year coded HCC is essentially ground truth that the patient
     has the condition, only the recapture is missing.
  3. The evidence contains a lab value > 1.5x the threshold (strong
     lab signal, not a borderline result).

A suspect row is labelled negative (``label=0``) iff **any** of:

  A. The evidence note_snippet (LLM/NLP path) contains a negation
     cue near the concept ("no evidence of", "denies", "ruled out",
     "not consistent with").
  B. The source is a *single* signal AND raw_confidence < 0.45 (weak
     lone signal).
  C. The evidence shows a normalised lab value within 5% of the
     threshold (borderline) AND no corroborating signals.

Rows that satisfy neither rule are *excluded* from the bootstrap set
(not assigned 0.5 — that would teach the calibrator nothing).

Everything else (rules conflict, neither triggers) -> excluded.

This yields a class-imbalanced but non-degenerate label distribution,
which is what we want — a calibrator needs to see both classes.

OUTPUT
------
CSV with columns ``source,raw_score,label`` stored at
``calibration/bootstrap_set.csv``.  Consumed by
``scripts/fit_calibrators.py``.

KNOWN RISKS
-----------
* These rules are clinical heuristics, not ground truth.  Any
  systematic bias in them (e.g. we are too generous with rule #3)
  propagates to the calibrator.
* Rule #2 is *almost* tautological — historical suspects will look
  very well-calibrated because the label generator essentially agrees
  with the raw score inflation already baked into source=history.
  Replace with real chart review labels ASAP.
"""
from __future__ import annotations

import csv
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger(__name__)

_NEGATION_PATTERNS: tuple[re.Pattern, ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bno (evidence|history|signs?) of\b",
        r"\bdenies\b",
        r"\bruled out\b",
        r"\bnot consistent with\b",
        r"\bwithout\b.{0,30}\b(?:disease|condition|diagnosis)\b",
        r"\bnegative for\b",
        r"\bno longer\b",
    )
)


@dataclass(frozen=True)
class BootstrapRow:
    source: str
    raw_score: float
    label: int


def _icd_stem(icd: str | None) -> str:
    if not icd:
        return ""
    return str(icd).replace(".", "").strip().upper()[:3]


def _has_negation(snippet: str | None) -> bool:
    if not snippet:
        return False
    return any(p.search(snippet) for p in _NEGATION_PATTERNS)


def _lab_strength_ratio(evidence: dict[str, Any]) -> float | None:
    """Return |value / threshold| for lab evidence, or None."""
    try:
        v = float(evidence.get("value"))
        t = float(evidence.get("threshold"))
    except (TypeError, ValueError):
        return None
    if t == 0:
        return None
    return abs(v) / abs(t)


def _count_corroborating(suspect: dict[str, Any], cohort: Iterable[dict[str, Any]]) -> int:
    """
    Count suspects in *cohort* (same patient, same measurement year) whose
    ICD-10 3-char stem matches and which come from a *different* source.
    This captures "lab + med both flagged HCC37 for this patient".
    """
    key_stem = _icd_stem(suspect.get("suspected_icd") or suspect.get("icd10"))
    key_pid = suspect.get("patient_id")
    my_source = suspect.get("source")
    if not key_stem:
        return 0
    count = 0
    for other in cohort:
        if other is suspect:
            continue
        if other.get("patient_id") != key_pid:
            continue
        if other.get("source") == my_source:
            continue
        other_stem = _icd_stem(other.get("suspected_icd") or other.get("icd10"))
        if other_stem == key_stem:
            count += 1
    return count


def label_suspect(
    suspect: dict[str, Any],
    cohort: Iterable[dict[str, Any]],
) -> int | None:
    """
    Apply bootstrap label rules.  Returns 0, 1, or None (exclude).

    *cohort* is the list of all suspects across patients used to detect
    corroborating signals.  Pass the same iterable for every call within a
    batch.
    """
    source = (suspect.get("source") or "").lower()
    raw_score = float(suspect.get("confidence") or suspect.get("raw_score") or 0.0)
    evidence = suspect.get("evidence") or {}
    snippet = evidence.get("note_snippet") or evidence.get("evidence_text") or ""

    corroborating = _count_corroborating(suspect, cohort)

    # ---- Negative rules (evaluated first; a negation wins over a weak
    # corroboration signal because negation is high-precision). ----
    if _has_negation(snippet):
        return 0

    lab_ratio = _lab_strength_ratio(evidence)
    if corroborating == 0 and lab_ratio is not None and 0.95 <= lab_ratio <= 1.05:
        # borderline lab, no other support
        return 0

    if corroborating == 0 and raw_score < 0.45:
        return 0

    # ---- Positive rules ----
    if corroborating >= 1:
        return 1
    if source == "history":
        return 1
    if lab_ratio is not None and lab_ratio >= 1.5:
        return 1

    return None  # ambiguous — exclude from bootstrap


def build_bootstrap_set(suspects: list[dict[str, Any]]) -> list[BootstrapRow]:
    """Apply :func:`label_suspect` to every input row, drop excluded."""
    rows: list[BootstrapRow] = []
    for s in suspects:
        label = label_suspect(s, suspects)
        if label is None:
            continue
        source = (s.get("source") or "unknown").lower()
        raw = float(s.get("confidence") or s.get("raw_score") or 0.0)
        rows.append(BootstrapRow(source=source, raw_score=raw, label=int(label)))
    return rows


DEFAULT_CSV_PATH = Path(__file__).parent / "bootstrap_set.csv"


def write_csv(rows: list[BootstrapRow], path: Path | str = DEFAULT_CSV_PATH) -> Path:
    """Serialise the bootstrap set to CSV."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["source", "raw_score", "label"])
        for r in rows:
            writer.writerow([r.source, f"{r.raw_score:.6f}", r.label])
    logger.info("bootstrap set: wrote %d rows to %s", len(rows), out)
    return out


def read_csv(path: Path | str = DEFAULT_CSV_PATH) -> list[BootstrapRow]:
    out: list[BootstrapRow] = []
    with Path(path).open("r", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            out.append(
                BootstrapRow(
                    source=row["source"],
                    raw_score=float(row["raw_score"]),
                    label=int(row["label"]),
                )
            )
    return out


def class_balance(rows: list[BootstrapRow]) -> dict[str, float]:
    """Return fraction-positive per source.  Useful sanity check."""
    from collections import Counter

    counts: dict[str, list[int]] = {}
    for r in rows:
        counts.setdefault(r.source, []).append(r.label)
    out: dict[str, float] = {}
    for src, labels in counts.items():
        total = len(labels)
        pos = sum(labels)
        out[src] = pos / total if total else 0.0
    out["_overall"] = (
        sum(r.label for r in rows) / len(rows) if rows else 0.0
    )
    out["_count"] = float(len(rows))
    out["_by_source_count"] = {src: len(v) for src, v in counts.items()}  # type: ignore[assignment]
    return out
