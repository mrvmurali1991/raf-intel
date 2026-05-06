"""
Recapture Readiness Service — IMO Health–style problem-list sync score.

For every open recapture gap we produce a 0–100 *readiness* score that tells the
care team how defensible the recapture is right now.  The score is built from
four signals already in our databases:

  1. Whether the gap's ICD-10 code is on the patient's CURRENT problem list
     (``openemr.lists`` rows with ``type='medical_problem'`` and ``activity=1``).
  2. Whether the problem list entry was added/updated in the last 90 days.
  3. Whether the patient has had any encounter in the last 90 days
     (``openemr.form_encounter``).
  4. How many MEAT elements (Monitor / Evaluate / Assess / Treat) are flagged
     "present" in ``raf_meat_evidence`` for the corresponding HCC.

Scoring formula (max 100):

    + 30   ICD on current problem list
    + 20   Problem list entry updated < 90 days
    + 20   Any encounter < 90 days
    + 30   MEAT elements present  (10 each, capped at 30)

Defensibility tiers (used by the UI badges):

    >= 70   strong
    40-69   moderate
    < 40    weak

Public API
----------
compute_gap_readiness(gap_id, tenant_id) -> dict
bulk_compute_readiness(tenant_id, year)  -> list[dict]
compute_readiness_summary(tenant_id, year) -> dict

The service NEVER mutates the recapture_gaps table — it is a pure read/scoring
layer.  All cross-database joins are done in Python so we can read OpenEMR via
``openemr_cursor`` and RAF tables via ``raf_cursor``.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

from app.db import openemr_cursor, raf_cursor

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Scoring constants (single source of truth — DO NOT duplicate elsewhere)
# ---------------------------------------------------------------------------

#: Score awarded for the ICD being on the current problem list.
SCORE_PROBLEM_LIST: int = 30

#: Score awarded when the problem-list entry was added/updated in the recency window.
SCORE_PROBLEM_LIST_RECENT: int = 20

#: Score awarded when there is an encounter in the recency window.
SCORE_RECENT_ENCOUNTER: int = 20

#: Score awarded per MEAT element present (M, E, A, T).  Capped by ``MEAT_MAX_SCORE``.
SCORE_PER_MEAT: int = 10

#: Maximum total score from MEAT elements (so a fully documented MEAT does not
#: outweigh problem-list/encounter signals).
MEAT_MAX_SCORE: int = 30

#: Recency window (days) used for both problem-list freshness and encounters.
RECENCY_WINDOW_DAYS: int = 90

#: Defensibility tier thresholds (>= cutoff).
TIER_STRONG_MIN: int = 70
TIER_MODERATE_MIN: int = 40

#: Maximum total score (for clamping / display).
MAX_SCORE: int = 100


# ---------------------------------------------------------------------------
# Internal helpers — small DB readers, each takes a primitive id
# ---------------------------------------------------------------------------

def _normalize_icd(code: str | None) -> str:
    """Return ICD-10 in canonical form (uppercase, no whitespace, no dot)."""
    if not code:
        return ""
    return str(code).strip().upper().replace(".", "")


def _icd_matches(stored: str | None, target_norm: str) -> bool:
    """
    Compare a stored ``lists.diagnosis`` entry (which may be ``ICD10:E11.9`` or
    ``E11.9``) against an already-normalised target code.
    """
    if not stored or not target_norm:
        return False
    raw = str(stored).strip().upper()
    if raw.startswith("ICD10:"):
        raw = raw[len("ICD10:"):]
    return raw.replace(".", "") == target_norm


def _fetch_problem_list(patient_id: int | str) -> list[dict[str, Any]]:
    """
    Return active medical-problem rows from ``openemr.lists`` for ``patient_id``.

    Each row is normalised to::

        {
            "diagnosis": "E11.9",     # canonical, no dot, uppercase
            "raw_diagnosis": "ICD10:E11.9",
            "title": "Type 2 diabetes",
            "begdate": date | None,
            "date_added": datetime | None,
            "date_modified": datetime | None,
        }

    A best-effort SQL is used: not every OpenEMR install populates every
    timestamp column, so we tolerate ``None`` everywhere.
    """
    try:
        pid_int = int(patient_id)
    except (TypeError, ValueError):
        return []

    sql = """
        SELECT
            diagnosis,
            title,
            begdate,
            date          AS date_added,
            modifydate    AS date_modified
        FROM lists
        WHERE pid = %s
          AND type = 'medical_problem'
          AND activity = 1
    """

    try:
        with openemr_cursor() as cur:
            cur.execute(sql, (pid_int,))
            rows = cur.fetchall() or []
    except Exception as exc:
        # Some OpenEMR variants don't have the ``modifydate`` column — fall
        # back to a slimmer query rather than failing the whole readiness
        # calculation.
        logger.debug(
            "_fetch_problem_list: full query failed for pid=%s, retrying minimal: %s",
            pid_int, exc,
        )
        try:
            with openemr_cursor() as cur:
                cur.execute(
                    """
                    SELECT diagnosis, title, begdate
                    FROM lists
                    WHERE pid = %s
                      AND type = 'medical_problem'
                      AND activity = 1
                    """,
                    (pid_int,),
                )
                rows = cur.fetchall() or []
        except Exception as exc2:
            logger.warning("_fetch_problem_list failed for pid=%s: %s", pid_int, exc2)
            return []

    out: list[dict[str, Any]] = []
    for r in rows:
        raw = r.get("diagnosis")
        out.append({
            "diagnosis": _icd_strip_prefix(raw),
            "raw_diagnosis": raw,
            "title": r.get("title"),
            "begdate": r.get("begdate"),
            "date_added": r.get("date_added"),
            "date_modified": r.get("date_modified"),
        })
    return out


def _icd_strip_prefix(stored: str | None) -> str:
    if not stored:
        return ""
    raw = str(stored).strip().upper()
    if raw.startswith("ICD10:"):
        raw = raw[len("ICD10:"):]
    return raw.replace(".", "")


def _fetch_meat_status(patient_id: int | str, hcc_code: str, model_year: int) -> dict[str, int]:
    """
    Return ``{m, e, a, t}`` counts (each 0 or 1) summarising MEAT presence for
    one (patient, hcc, year) triple.

    raf_meat_evidence has no patient_id of its own — it links via
    ``patient_hcc_id`` to ``raf_patient_hcc``, so we join on the way through.
    """
    sql = """
        SELECT
            MAX(me.meat_m_present) AS m,
            MAX(me.meat_e_present) AS e,
            MAX(me.meat_a_present) AS a,
            MAX(me.meat_t_present) AS t
        FROM raf_meat_evidence me
        JOIN raf_patient_hcc ph
          ON ph.id = me.patient_hcc_id
        WHERE ph.patient_id      = %s
          AND ph.hcc_code        = %s
          AND ph.measurement_year = %s
    """
    try:
        with raf_cursor() as cur:
            cur.execute(sql, (patient_id, hcc_code, model_year))
            row = cur.fetchone()
    except Exception as exc:
        # Older deployments may use ``model_year`` instead of
        # ``measurement_year`` on raf_patient_hcc — retry once.
        logger.debug(
            "_fetch_meat_status retry with model_year column for pid=%s hcc=%s: %s",
            patient_id, hcc_code, exc,
        )
        try:
            with raf_cursor() as cur:
                cur.execute(
                    sql.replace("ph.measurement_year", "ph.model_year"),
                    (patient_id, hcc_code, model_year),
                )
                row = cur.fetchone()
        except Exception as exc2:
            logger.warning(
                "_fetch_meat_status failed pid=%s hcc=%s: %s",
                patient_id, hcc_code, exc2,
            )
            return {"m": 0, "e": 0, "a": 0, "t": 0}

    if not row:
        return {"m": 0, "e": 0, "a": 0, "t": 0}
    return {
        "m": int(row.get("m") or 0),
        "e": int(row.get("e") or 0),
        "a": int(row.get("a") or 0),
        "t": int(row.get("t") or 0),
    }


def _fetch_recent_encounters(
    patient_id: int | str,
    days: int = RECENCY_WINDOW_DAYS,
    today: date | None = None,
) -> dict[str, Any]:
    """
    Return ``{"count": N, "last_date": YYYY-MM-DD | None}`` for encounters in
    the last ``days`` days from ``openemr.form_encounter``.
    """
    try:
        pid_int = int(patient_id)
    except (TypeError, ValueError):
        return {"count": 0, "last_date": None}

    cutoff = (today or date.today()) - timedelta(days=days)

    try:
        with openemr_cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) AS cnt, MAX(date) AS last_date
                FROM form_encounter
                WHERE pid = %s
                  AND date >= %s
                """,
                (pid_int, cutoff),
            )
            row = cur.fetchone() or {}
    except Exception as exc:
        logger.warning("_fetch_recent_encounters failed pid=%s: %s", pid_int, exc)
        return {"count": 0, "last_date": None}

    last = row.get("last_date")
    return {
        "count": int(row.get("cnt") or 0),
        "last_date": last.isoformat() if hasattr(last, "isoformat") and last else None,
    }


# ---------------------------------------------------------------------------
# Core scoring — pure function (no DB) so it is easy to unit-test
# ---------------------------------------------------------------------------

def _score_components(
    *,
    icd_on_problem_list: bool,
    problem_list_recent: bool,
    recent_encounter: bool,
    meat: dict[str, int],
) -> tuple[int, dict[str, int]]:
    """Return ``(total_score, breakdown_dict)`` from already-resolved booleans."""
    breakdown: dict[str, int] = {
        "problem_list":          SCORE_PROBLEM_LIST if icd_on_problem_list else 0,
        "problem_list_recent":   SCORE_PROBLEM_LIST_RECENT if problem_list_recent else 0,
        "recent_encounter":      SCORE_RECENT_ENCOUNTER if recent_encounter else 0,
    }
    meat_total = sum(int(bool(meat.get(k, 0))) for k in ("m", "e", "a", "t")) * SCORE_PER_MEAT
    breakdown["meat"] = min(meat_total, MEAT_MAX_SCORE)

    total = sum(breakdown.values())
    return min(total, MAX_SCORE), breakdown


def _tier(score: int) -> str:
    """Map a 0–100 score to a defensibility tier."""
    if score >= TIER_STRONG_MIN:
        return "strong"
    if score >= TIER_MODERATE_MIN:
        return "moderate"
    return "weak"


def _recommended_actions(
    *,
    icd_on_problem_list: bool,
    problem_list_recent: bool,
    recent_encounter: bool,
    meat: dict[str, int],
) -> list[str]:
    """Return a UI-ready list of next-step actions (most impactful first)."""
    actions: list[str] = []
    if not icd_on_problem_list:
        actions.append("Add condition to active problem list")
    elif not problem_list_recent:
        actions.append("Reaffirm condition on problem list (refresh > 90 days)")
    if not recent_encounter:
        actions.append("Schedule a face-to-face visit within 90 days")
    missing_meat = [k.upper() for k in ("m", "e", "a", "t") if not meat.get(k)]
    if missing_meat:
        actions.append(
            "Add MEAT documentation: " + ", ".join(missing_meat)
        )
    return actions


# ---------------------------------------------------------------------------
# Recency helper — handles both DATE and DATETIME columns
# ---------------------------------------------------------------------------

def _is_recent(value: Any, days: int = RECENCY_WINDOW_DAYS, today: date | None = None) -> bool:
    """
    Return True if *value* (date / datetime / iso string) is within ``days``
    days of ``today``.  Future-dated rows are treated as recent.
    """
    if value is None:
        return False
    if isinstance(value, datetime):
        d = value.date()
    elif isinstance(value, date):
        d = value
    else:
        try:
            d = datetime.fromisoformat(str(value)).date()
        except (TypeError, ValueError):
            return False
    cutoff = (today or date.today()) - timedelta(days=days)
    return d >= cutoff


# ---------------------------------------------------------------------------
# Gap loaders — small wrappers so the public API can take just gap_id
# ---------------------------------------------------------------------------

def _load_gap(gap_id: int, tenant_id: str | int) -> dict[str, Any] | None:
    """Return a single recapture_gaps row scoped to ``tenant_id`` or None."""
    sql = """
        SELECT id, patient_id, tenant_id, hcc_code, icd10_code,
               prior_year, current_year, status,
               last_encounter_date, provider_npi, revenue_impact
        FROM recapture_gaps
        WHERE id = %s
          AND tenant_id = %s
        LIMIT 1
    """
    with raf_cursor() as cur:
        cur.execute(sql, (int(gap_id), str(tenant_id)))
        return cur.fetchone()


def _load_gaps_for_year(tenant_id: str | int, current_year: int) -> list[dict[str, Any]]:
    """Return every open gap for the tenant in ``current_year``."""
    sql = """
        SELECT id, patient_id, tenant_id, hcc_code, icd10_code,
               prior_year, current_year, status,
               last_encounter_date, provider_npi, revenue_impact
        FROM recapture_gaps
        WHERE tenant_id    = %s
          AND current_year = %s
          AND status       = 'open'
        ORDER BY id
    """
    with raf_cursor() as cur:
        cur.execute(sql, (str(tenant_id), int(current_year)))
        return cur.fetchall() or []


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_gap_readiness(
    gap_id: int,
    tenant_id: str | int,
    *,
    today: date | None = None,
) -> dict[str, Any]:
    """
    Compute the readiness score (0–100) for a single recapture gap.

    Returns a dict shaped for the API::

        {
            "gap_id": 1,
            "patient_id": "42",
            "hcc_code": "85",
            "icd10_code": "I50.9",
            "score": 70,
            "components": {
                "problem_list": True,
                "problem_list_recent": False,
                "recent_encounter": True,
                "meat": {"m": 1, "e": 1, "a": 0, "t": 0},
            },
            "score_breakdown": {
                "problem_list": 30,
                "problem_list_recent": 0,
                "recent_encounter": 20,
                "meat": 20,
            },
            "defensibility_tier": "moderate",
            "recommended_actions": ["Schedule a face-to-face visit within 90 days", ...],
        }

    Raises:
        LookupError: if the gap doesn't exist for this tenant.
    """
    gap = _load_gap(gap_id=gap_id, tenant_id=tenant_id)
    if gap is None:
        raise LookupError(f"Recapture gap {gap_id} not found for tenant {tenant_id!r}")

    return _score_gap_dict(gap, today=today)


def bulk_compute_readiness(
    tenant_id: str | int,
    year: int,
    *,
    today: date | None = None,
) -> list[dict[str, Any]]:
    """Return a per-gap readiness payload for every OPEN gap in ``year``."""
    gaps = _load_gaps_for_year(tenant_id=tenant_id, current_year=year)
    return [_score_gap_dict(g, today=today) for g in gaps]


def compute_readiness_summary(
    tenant_id: str | int,
    year: int,
    *,
    today: date | None = None,
) -> dict[str, Any]:
    """
    Aggregate-only summary used by the dashboard card.

    ::

        {
            "year": 2026,
            "total_open_gaps": 16,
            "average_score": 42.5,
            "defensibility_distribution": {
                "strong": 3, "moderate": 6, "weak": 7
            },
            "actionable_gaps": 13   # gaps with at least one recommended action
        }
    """
    rows = bulk_compute_readiness(tenant_id=tenant_id, year=year, today=today)

    if not rows:
        return {
            "year": int(year),
            "total_open_gaps": 0,
            "average_score": 0.0,
            "defensibility_distribution": {"strong": 0, "moderate": 0, "weak": 0},
            "actionable_gaps": 0,
        }

    dist = {"strong": 0, "moderate": 0, "weak": 0}
    actionable = 0
    total_score = 0
    for r in rows:
        dist[r["defensibility_tier"]] = dist.get(r["defensibility_tier"], 0) + 1
        total_score += int(r["score"])
        if r["recommended_actions"]:
            actionable += 1

    return {
        "year": int(year),
        "total_open_gaps": len(rows),
        "average_score": round(total_score / len(rows), 1),
        "defensibility_distribution": dist,
        "actionable_gaps": actionable,
    }


# ---------------------------------------------------------------------------
# Internal: glue gap row → score payload
# ---------------------------------------------------------------------------

def _score_gap_dict(gap: dict[str, Any], *, today: date | None = None) -> dict[str, Any]:
    """Compute the readiness payload for one already-loaded gap row."""
    target_icd = _normalize_icd(gap.get("icd10_code"))
    patient_id = gap.get("patient_id")
    hcc_code = str(gap.get("hcc_code") or "")
    current_year = int(gap.get("current_year") or date.today().year)

    # --- 1. Problem list ---
    problem_rows = _fetch_problem_list(patient_id)
    matching = [r for r in problem_rows if _icd_matches(r.get("raw_diagnosis"), target_icd)]
    icd_on_problem_list = bool(matching)

    problem_list_recent = False
    if icd_on_problem_list:
        # Use whichever timestamp is most recent across modify/added/begdate.
        for r in matching:
            for col in ("date_modified", "date_added", "begdate"):
                if _is_recent(r.get(col), today=today):
                    problem_list_recent = True
                    break
            if problem_list_recent:
                break

    # --- 2. Encounters ---
    enc = _fetch_recent_encounters(patient_id, today=today)
    recent_encounter = enc["count"] > 0

    # --- 3. MEAT ---
    meat = _fetch_meat_status(patient_id, hcc_code, current_year)

    # --- 4. Score ---
    score, breakdown = _score_components(
        icd_on_problem_list=icd_on_problem_list,
        problem_list_recent=problem_list_recent,
        recent_encounter=recent_encounter,
        meat=meat,
    )

    return {
        "gap_id": int(gap.get("id") or 0),
        "patient_id": patient_id,
        "hcc_code": hcc_code,
        "icd10_code": gap.get("icd10_code"),
        "current_year": current_year,
        "score": score,
        "components": {
            "problem_list": icd_on_problem_list,
            "problem_list_recent": problem_list_recent,
            "recent_encounter": recent_encounter,
            "meat": meat,
        },
        "score_breakdown": breakdown,
        "defensibility_tier": _tier(score),
        "recommended_actions": _recommended_actions(
            icd_on_problem_list=icd_on_problem_list,
            problem_list_recent=problem_list_recent,
            recent_encounter=recent_encounter,
            meat=meat,
        ),
        "problem_list_matches": [
            {
                "diagnosis": m.get("diagnosis"),
                "title": m.get("title"),
                "begdate": _isoformat(m.get("begdate")),
                "date_modified": _isoformat(m.get("date_modified")),
            }
            for m in matching
        ],
        "last_encounter_in_window": enc.get("last_date"),
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }


def _isoformat(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)
