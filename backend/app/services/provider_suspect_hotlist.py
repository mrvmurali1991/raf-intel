"""
Real-Time Suspect Hot-List service.

Surfaces a provider's hottest open suspects — the "what should I action THIS
WEEK" list — by ranking each open ``raf_suspect_conditions`` row on a blended
*urgency score*::

    urgency_score = 0.5 * confidence
                  + 0.3 * (expected_dollars / max_panel_$)
                  + 0.2 * (days_open / 90)
    # capped at 1.0

Inspired by Navina's just-in-time alerts that drove their 86 % weekly active
rate.  The math is fully deterministic — no LLM call.

Public API
----------
get_hotlist(provider_id, year, *, limit=20, min_confidence=0.0) -> dict
    Returns ``{"items": [...], "summary": {...}, "provider_id": ..., "year": ...}``.

Each item carries::

    {
      "patient_id":      int,
      "patient_name":    str,
      "suspect_id":      int,
      "hcc_code":        str,
      "hcc_label":       str,
      "icd10":           str,
      "confidence":      float (0..1),
      "evidence_type":   str,
      "raf_coefficient": float,
      "expected_dollars": float,
      "days_open":       int,
      "urgency_score":   float (0..1),
    }

Conventions
-----------
* The dollar amount per suspect is deterministic::
      expected_dollars = raf_coefficient * confidence * _HCC_BASE_RATE
  where ``_HCC_BASE_RATE`` is imported from ``app.services.provider_service``
  (single source of truth — never hard-coded here).
* RAF coefficient is the per-HCC CMS V28 coefficient pulled from
  ``hcc_raf_coefficients`` for ``model_year=2024`` and the patient's stored
  segment (default ``CNA``).
* Schema gotchas (single-tenant): ``provider_patient_panel`` has no
  ``tenant_id`` / ``is_active`` columns; ``raf_suspect_conditions`` uses
  ``suspect_hcc`` (not ``hcc_code``) and ``confidence_score``.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any

from app.db import raf_cursor
from app.services.provider_service import _HCC_BASE_RATE
from app.services.raf_forecast import (
    DEFAULT_MODEL_SEGMENT,
    _coefficient_lookup,
    _resolve_segment,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tunable constants
# ---------------------------------------------------------------------------

# Recency window: a suspect open for >= this many days saturates the recency
# component of the urgency score.
DEFAULT_RECENCY_WINDOW_DAYS = 90

# High-confidence threshold for the summary aggregate.
HIGH_CONFIDENCE_THRESHOLD = 0.80

# Component weights for urgency_score.
W_CONFIDENCE = 0.5
W_DOLLARS = 0.3
W_RECENCY = 0.2


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _provider_panel_pids(provider_id: int) -> list[int]:
    """Return the patient pids in this provider's panel.

    `provider_patient_panel` has no ``is_active`` / ``tenant_id`` columns in
    the current single-tenant schema, so we just select by provider_id.
    """
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT patient_id
                FROM provider_patient_panel
                WHERE provider_id = %s
                """,
                (provider_id,),
            )
            rows = cur.fetchall() or []
        return [int(r["patient_id"]) for r in rows if r.get("patient_id") is not None]
    except Exception as exc:
        logger.warning("_provider_panel_pids provider=%s: %s", provider_id, exc)
        return []


def _open_suspects_for_panel(pids: list[int], year: int) -> list[dict[str, Any]]:
    """Bulk fetch all open suspects for a list of patient ids in `year`."""
    if not pids:
        return []
    placeholders = ",".join(["%s"] * len(pids))
    sql = f"""
        SELECT id, patient_id, suspect_hcc, suspect_icd10, evidence_type,
               confidence_score, created_at
        FROM raf_suspect_conditions
        WHERE measurement_year = %s
          AND status           = 'open'
          AND patient_id IN ({placeholders})
    """
    try:
        with raf_cursor() as cur:
            cur.execute(sql, (year, *pids))
            return list(cur.fetchall() or [])
    except Exception as exc:
        logger.warning(
            "_open_suspects_for_panel year=%s pid_count=%s: %s",
            year, len(pids), exc,
        )
        return []


def _patient_names(pids: list[int]) -> dict[int, str]:
    """Return ``{pid: "First Last"}`` for the given pids — best-effort."""
    if not pids:
        return {}
    placeholders = ",".join(["%s"] * len(pids))
    try:
        with raf_cursor() as cur:
            cur.execute(
                f"""
                SELECT id AS pid, first_name, last_name
                FROM patients
                WHERE id IN ({placeholders})
                """,
                tuple(pids),
            )
            rows = cur.fetchall() or []
        return {
            int(r["pid"]): (
                f"{(r.get('first_name') or '').strip()} "
                f"{(r.get('last_name') or '').strip()}"
            ).strip()
            or f"Patient {r['pid']}"
            for r in rows
        }
    except Exception as exc:
        logger.debug("_patient_names: %s", exc)
        return {}


def _segments_for_pids(pids: list[int], year: int) -> dict[int, str]:
    """Bulk segment lookup; falls back to DEFAULT_MODEL_SEGMENT on miss."""
    if not pids:
        return {}
    placeholders = ",".join(["%s"] * len(pids))
    try:
        with raf_cursor() as cur:
            cur.execute(
                f"""
                SELECT patient_id, model_segment
                FROM raf_patient_demographics
                WHERE measurement_year = %s
                  AND patient_id IN ({placeholders})
                """,
                (year, *pids),
            )
            rows = cur.fetchall() or []
        return {
            int(r["patient_id"]): (r.get("model_segment") or DEFAULT_MODEL_SEGMENT)
            for r in rows
        }
    except Exception as exc:
        logger.debug("_segments_for_pids: %s", exc)
        return {}


def _hcc_label(hcc_code: str | int) -> str:
    """Best-effort human label for an HCC code; falls back to ``HCC <code>``."""
    code = str(hcc_code).lstrip("HCC").lstrip("0") or "0"
    try:
        # Imported lazily to avoid circulars during module load.
        from app.services.recapture_gap_service import _hcc_description
        label = _hcc_description(code)
        if label and not label.lower().startswith("hcc "):
            return label
        return label or f"HCC {code}"
    except Exception:
        return f"HCC {code}"


def _days_open(created_at: Any, now: datetime | None = None) -> int:
    """Return the number of whole days since `created_at`. Robust to naive/aware."""
    if not created_at:
        return 0
    now = now or datetime.now(timezone.utc)
    if isinstance(created_at, datetime):
        ca = created_at
    else:
        try:
            ca = datetime.fromisoformat(str(created_at))
        except Exception:
            return 0
    # Normalise both to naive UTC for comparison.
    if ca.tzinfo is not None:
        ca = ca.astimezone(timezone.utc).replace(tzinfo=None)
    if now.tzinfo is not None:
        now = now.astimezone(timezone.utc).replace(tzinfo=None)
    delta = now - ca
    return max(0, int(delta.days))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_hotlist(
    provider_id: int,
    year: int | None = None,
    *,
    limit: int = 20,
    min_confidence: float = 0.0,
    recency_window_days: int = DEFAULT_RECENCY_WINDOW_DAYS,
    _suspects_override: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Compute the provider's real-time suspect hot-list.

    Parameters
    ----------
    provider_id : int
        Internal provider id (matches ``provider_patient_panel.provider_id``).
    year : int, optional
        Measurement year; defaults to the current calendar year.
    limit : int
        Maximum number of items returned, sorted by ``urgency_score`` desc.
    min_confidence : float
        Drop suspects with ``confidence_score < min_confidence`` before
        ranking.  ``0.0`` keeps everything.
    recency_window_days : int
        Days at which the recency contribution saturates to 1.0.
    _suspects_override : list, optional
        Test hook — bypasses the panel + suspect DB queries.  Each row must
        carry ``id``, ``patient_id``, ``suspect_hcc``, ``suspect_icd10``,
        ``evidence_type``, ``confidence_score``, ``created_at``.

    Returns
    -------
    dict
        ``{"provider_id", "measurement_year", "items": [...], "summary": {...}}``
    """
    year = year or date.today().year
    limit = max(1, int(limit))
    min_confidence = max(0.0, min(1.0, float(min_confidence)))
    window = max(1, int(recency_window_days))

    # 1. Resolve panel + open suspects -------------------------------------
    if _suspects_override is not None:
        suspects = list(_suspects_override)
    else:
        pids = _provider_panel_pids(provider_id)
        suspects = _open_suspects_for_panel(pids, year)

    # 2. Filter by min_confidence ------------------------------------------
    if min_confidence > 0:
        suspects = [
            s for s in suspects
            if float(s.get("confidence_score") or 0.0) >= min_confidence
        ]

    # Total open count is BEFORE limit but AFTER min_confidence so the header
    # matches what the user has filtered to.  We surface the unfiltered count
    # separately as ``total_open_unfiltered``.
    total_open_filtered = len(suspects)

    # 3. Pre-compute coefficients per (segment, hcc) -----------------------
    suspect_pids = [int(s["patient_id"]) for s in suspects]
    segments = _segments_for_pids(suspect_pids, year) if suspect_pids else {}

    # Group HCCs by segment for batched coefficient lookup.
    by_segment: dict[str, set[str]] = {}
    for s in suspects:
        seg = segments.get(int(s["patient_id"]), DEFAULT_MODEL_SEGMENT)
        by_segment.setdefault(seg, set()).add(str(s["suspect_hcc"]))

    coeff_cache: dict[tuple[str, str], float] = {}
    for seg, codes in by_segment.items():
        coeffs = _coefficient_lookup(list(codes), seg)
        for hcc_str, c in coeffs.items():
            coeff_cache[(seg, hcc_str)] = c

    # 4. Compute expected $ per suspect and the panel max ($) --------------
    enriched: list[dict[str, Any]] = []
    for s in suspects:
        pid = int(s["patient_id"])
        seg = segments.get(pid, DEFAULT_MODEL_SEGMENT)
        hcc_str = str(s["suspect_hcc"])
        coeff = float(coeff_cache.get((seg, hcc_str), 0.0))
        confidence = float(s.get("confidence_score") or 0.0)
        expected = round(coeff * confidence * _HCC_BASE_RATE, 2)
        days = _days_open(s.get("created_at"))
        enriched.append(
            {
                "patient_id": pid,
                "suspect_id": int(s["id"]),
                "hcc_code": hcc_str,
                "icd10": s.get("suspect_icd10") or "",
                "evidence_type": s.get("evidence_type") or "",
                "confidence": round(confidence, 4),
                "raf_coefficient": round(coeff, 4),
                "expected_dollars": expected,
                "days_open": days,
            }
        )

    max_panel_dollars = max((e["expected_dollars"] for e in enriched), default=0.0)

    # 5. Compute urgency_score and patient names --------------------------
    name_lookup = _patient_names(list({e["patient_id"] for e in enriched}))

    for e in enriched:
        conf_part = W_CONFIDENCE * e["confidence"]
        dollar_part = (
            W_DOLLARS * (e["expected_dollars"] / max_panel_dollars)
            if max_panel_dollars > 0
            else 0.0
        )
        recency_part = W_RECENCY * min(1.0, e["days_open"] / window)
        urgency = min(1.0, conf_part + dollar_part + recency_part)
        e["urgency_score"] = round(urgency, 4)
        e["hcc_label"] = _hcc_label(e["hcc_code"])
        e["patient_name"] = name_lookup.get(e["patient_id"]) or f"Patient {e['patient_id']}"

    # 6. Sort by urgency desc, take top N ----------------------------------
    enriched.sort(key=lambda r: r["urgency_score"], reverse=True)
    items = enriched[:limit]

    # 7. Aggregates --------------------------------------------------------
    high_conf = sum(1 for e in enriched if e["confidence"] >= HIGH_CONFIDENCE_THRESHOLD)
    total_dollars = round(sum(e["expected_dollars"] for e in enriched), 2)
    avg_per_suspect = (
        round(total_dollars / total_open_filtered, 2) if total_open_filtered else 0.0
    )

    summary = {
        "total_open": total_open_filtered,
        "high_confidence_count": high_conf,
        "total_expected_dollars": total_dollars,
        "avg_dollars_per_suspect": avg_per_suspect,
        "max_panel_dollars": round(max_panel_dollars, 2),
        "high_confidence_threshold": HIGH_CONFIDENCE_THRESHOLD,
    }

    return {
        "provider_id": provider_id,
        "measurement_year": year,
        "min_confidence": min_confidence,
        "limit": limit,
        "items": items,
        "summary": summary,
    }
