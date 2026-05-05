"""
AWV Prioritization Engine
=========================

Ranks Medicare patients on a provider's panel by *expected RAF / revenue lift*
from completing an Annual Wellness Visit. Designed for outreach teams who must
decide which patient to call FIRST when their queue holds hundreds of names.

Plain-English Formula
---------------------
We score each patient on a 0-100 composite where 100 = "absolute top of the
worklist." The score blends four normalized signals, each within the patient's
own panel (so the math reweights itself per provider / tenant):

    score =  w1 * (expected_revenue_lift   / max_revenue_lift_in_panel)
           + w2 * (high_conf_suspect_count / max_high_conf_in_panel)
           + w3 * recency_factor          # (capped at 730 days)
           + w4 * no_awv_in_year_flag     # 1.0 if no AWV in 365 days else 0

Default weights (must sum to 1.0):
    w1 = 0.45   revenue / RAF lift opportunity
    w2 = 0.25   number of HIGH-confidence open suspects (>= 0.70)
    w3 = 0.15   days since last clinical encounter (more = higher)
    w4 = 0.15   has no AWV in last 365 days (1 / 0)

Per-tenant overrides may be supplied to ``rank_panel`` via the ``weights``
kwarg; values are renormalized to sum to 1.0 before use.

Expected Revenue Lift
---------------------
We use the same model as the suspect engine and provider scorecard:

    expected_revenue_lift = open_suspect_count
                          * _HCC_BASE_RATE                         (= $12,000)
                          * average_calibrated_confidence

This deliberately mirrors ``provider_service._HCC_BASE_RATE`` so the
prioritization view never disagrees with the scorecard view.

Output
------
``calculate_priority_score(patient_id, ...)`` returns a dict with the score,
underlying signals, and a list of human-readable ``reasons`` strings suitable
for tooltip rendering on the AWV outreach UI.

``rank_panel(...)`` returns the panel sorted by score DESC. Normalization is
performed in a single sweep so the ranking is stable and deterministic.

NOTE: deterministic math only — no LLM call.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Iterable

from app.db import openemr_cursor, raf_cursor
from app.services.emr_manager import active_patients_subquery
from app.services.provider_service import _HCC_BASE_RATE

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_WEIGHTS: dict[str, float] = {
    "revenue": 0.45,
    "high_conf_suspects": 0.25,
    "recency": 0.15,
    "no_awv": 0.15,
}

# Suspect confidence threshold for "high confidence". Mirrors review_queue
# defaults — auto-acceptable suspects sit above this line.
HIGH_CONFIDENCE_THRESHOLD: float = 0.70

# Recency saturates at this many days (so a patient with no visit in 5 years
# does not crowd out the rest of the panel completely).
RECENCY_CAP_DAYS: int = 730

# What counts as "needs an AWV in the rolling year" — 365 days.
AWV_LOOKBACK_DAYS: int = 365

# CPT/HCPCS codes treated as a completed AWV (kept in sync with awv_service).
_AWV_CPT_CODES: tuple[str, ...] = (
    "G0438", "G0439", "G0402",
    "99381", "99382", "99383", "99384", "99385", "99386", "99387",
    "99391", "99392", "99393", "99394", "99395", "99396", "99397",
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _coerce_int(v: Any, default: int = 0) -> int:
    try:
        return int(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _coerce_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _coerce_date(v: Any) -> date | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return datetime.fromisoformat(str(v)).date()
    except (TypeError, ValueError):
        return None


def _days_ago(d: date | None, ref: date | None = None) -> int | None:
    if d is None:
        return None
    ref = ref or date.today()
    return max(0, (ref - d).days)


def _normalize_weights(weights: dict[str, float] | None) -> dict[str, float]:
    """Return a weight dict that always contains all 4 keys and sums to 1.0."""
    merged = dict(DEFAULT_WEIGHTS)
    if weights:
        for k, v in weights.items():
            if k in merged:
                merged[k] = max(0.0, _coerce_float(v))
    total = sum(merged.values())
    if total <= 0:
        return dict(DEFAULT_WEIGHTS)
    return {k: v / total for k, v in merged.items()}


def _safe_div(num: float, denom: float) -> float:
    if not denom or denom <= 0:
        return 0.0
    return num / denom


# ---------------------------------------------------------------------------
# Per-patient signal extraction
# ---------------------------------------------------------------------------

@dataclass
class PatientSignals:
    """Raw, un-normalized inputs collected from the database for one patient."""

    patient_id: int
    name: str = ""
    provider_id: int | None = None
    suspect_count: int = 0
    high_confidence_suspect_count: int = 0
    average_confidence: float = 0.0
    open_care_gaps: int = 0
    last_encounter_date: date | None = None
    last_awv_date: date | None = None

    @property
    def expected_revenue_lift(self) -> float:
        # Same model as provider_service revenue_opportunity:
        #   suspects * $/HCC * avg_confidence
        return round(
            self.suspect_count * _HCC_BASE_RATE * self.average_confidence,
            2,
        )

    @property
    def expected_raf_lift(self) -> float:
        # Convert revenue back into RAF points (RAF * $/RAF = $).  We use the
        # same flat $12,000 / HCC heuristic that the rest of the platform uses.
        # This is a *coarse* expected value, not an actuarial calculation.
        return round(self.expected_revenue_lift / _HCC_BASE_RATE, 4)

    @property
    def last_encounter_days_ago(self) -> int | None:
        return _days_ago(self.last_encounter_date)

    @property
    def last_awv_days_ago(self) -> int | None:
        return _days_ago(self.last_awv_date)

    @property
    def no_awv_in_year(self) -> bool:
        if self.last_awv_date is None:
            return True
        days = _days_ago(self.last_awv_date) or 0
        return days >= AWV_LOOKBACK_DAYS


def _fetch_panel_signals(
    tenant_id: str,
    provider_id: int | None = None,
    patient_ids: Iterable[int] | None = None,
) -> list[PatientSignals]:
    """
    Build PatientSignals for every patient in the requested scope.

    Scope precedence:
        1. If ``patient_ids`` is provided, restrict to those IDs.
        2. Else, if ``provider_id`` is provided, restrict to that provider's
           active panel via ``provider_patient_panel``.
        3. Else, return every active patient in the tenant.

    All four queries are issued sequentially against ``raf_cursor`` /
    ``openemr_cursor`` and joined in Python — there are no cross-database
    JOINs available.
    """
    try:
        tid = int(tenant_id)
    except (TypeError, ValueError):
        raise ValueError(
            f"awv_prioritization: tenant_id must be numeric, got {tenant_id!r}"
        )

    explicit_ids = (
        [int(p) for p in patient_ids] if patient_ids is not None else None
    )

    # ----- Patient roster ----------------------------------------------------
    if explicit_ids is not None and not explicit_ids:
        return []

    if explicit_ids is not None:
        placeholders = ",".join(["%s"] * len(explicit_ids))
        sql = f"""
            SELECT p.id AS pid, p.first_name, p.last_name,
                   pp.provider_id AS provider_id
            FROM patients p
            LEFT JOIN provider_patient_panel pp
                   ON pp.patient_id = p.id AND pp.is_active = 1
            WHERE p.is_active = 1
              AND p.tenant_id = %s
              AND p.id IN ({placeholders})
        """
        params: tuple[Any, ...] = (str(tid), *explicit_ids)
    elif provider_id is not None:
        sql = """
            SELECT p.id AS pid, p.first_name, p.last_name,
                   pp.provider_id AS provider_id
            FROM patients p
            JOIN provider_patient_panel pp
                   ON pp.patient_id = p.id AND pp.is_active = 1
            WHERE p.is_active = 1
              AND p.tenant_id = %s
              AND pp.provider_id = %s
        """
        params = (str(tid), int(provider_id))
    else:
        sub_filter, sub_params = active_patients_subquery(tid, patient_id_column="id")
        sql = f"""
            SELECT p.id AS pid, p.first_name, p.last_name,
                   pp.provider_id AS provider_id
            FROM patients p
            LEFT JOIN provider_patient_panel pp
                   ON pp.patient_id = p.id AND pp.is_active = 1
            WHERE p.is_active = 1
              AND p.tenant_id = %s
              AND {sub_filter}
        """
        params = (str(tid), *sub_params)

    with raf_cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall() or []

    if not rows:
        return []

    signals: dict[int, PatientSignals] = {}
    for r in rows:
        pid = _coerce_int(r.get("pid"))
        if pid <= 0:
            continue
        first = (r.get("first_name") or "").strip()
        last = (r.get("last_name") or "").strip()
        provider_for_patient = (
            int(provider_id) if provider_id is not None
            else (_coerce_int(r.get("provider_id")) or None)
        )
        signals[pid] = PatientSignals(
            patient_id=pid,
            name=f"{first} {last}".strip() or f"Patient #{pid}",
            provider_id=provider_for_patient,
        )

    pids = list(signals.keys())
    pid_placeholders = ",".join(["%s"] * len(pids))

    # ----- Suspects (open + confidence) --------------------------------------
    try:
        with raf_cursor() as cur:
            cur.execute(
                f"""
                SELECT patient_id,
                       COUNT(*)                                   AS open_count,
                       SUM(confidence_score >= %s)                AS high_conf_count,
                       AVG(confidence_score)                      AS avg_conf
                FROM raf_suspect_conditions
                WHERE status = 'open'
                  AND tenant_id = %s
                  AND patient_id IN ({pid_placeholders})
                GROUP BY patient_id
                """,
                (HIGH_CONFIDENCE_THRESHOLD, str(tid), *pids),
            )
            for s in cur.fetchall() or []:
                pid = _coerce_int(s.get("patient_id"))
                sig = signals.get(pid)
                if not sig:
                    continue
                sig.suspect_count = _coerce_int(s.get("open_count"))
                sig.high_confidence_suspect_count = _coerce_int(s.get("high_conf_count"))
                sig.average_confidence = _coerce_float(s.get("avg_conf"))
    except Exception as exc:
        # raf_suspect_conditions may not be tenant-scoped on some legacy DBs.
        # Fall back to a tenant-less query rather than crashing the worklist.
        logger.warning(
            "awv_prioritization: suspect query failed (%s); retrying without tenant filter",
            exc,
        )
        try:
            with raf_cursor() as cur:
                cur.execute(
                    f"""
                    SELECT patient_id,
                           COUNT(*) AS open_count,
                           SUM(confidence_score >= %s) AS high_conf_count,
                           AVG(confidence_score) AS avg_conf
                    FROM raf_suspect_conditions
                    WHERE status = 'open'
                      AND patient_id IN ({pid_placeholders})
                    GROUP BY patient_id
                    """,
                    (HIGH_CONFIDENCE_THRESHOLD, *pids),
                )
                for s in cur.fetchall() or []:
                    pid = _coerce_int(s.get("patient_id"))
                    sig = signals.get(pid)
                    if not sig:
                        continue
                    sig.suspect_count = _coerce_int(s.get("open_count"))
                    sig.high_confidence_suspect_count = _coerce_int(s.get("high_conf_count"))
                    sig.average_confidence = _coerce_float(s.get("avg_conf"))
        except Exception as exc2:
            logger.error("awv_prioritization: suspect fallback also failed: %s", exc2)

    # ----- Open care gap tasks -----------------------------------------------
    try:
        with raf_cursor() as cur:
            cur.execute(
                f"""
                SELECT patient_id, COUNT(*) AS gap_count
                FROM care_gap_tasks
                WHERE tenant_id = %s
                  AND status IN ('open','in_progress','scheduled')
                  AND patient_id IN ({pid_placeholders})
                GROUP BY patient_id
                """,
                (str(tid), *pids),
            )
            for g in cur.fetchall() or []:
                pid = _coerce_int(g.get("patient_id"))
                sig = signals.get(pid)
                if sig:
                    sig.open_care_gaps = _coerce_int(g.get("gap_count"))
    except Exception as exc:
        # care_gap_tasks may not exist in older deployments — tolerate silently.
        logger.debug("awv_prioritization: care_gap_tasks query skipped: %s", exc)

    # ----- Last clinical encounter (OpenEMR) ---------------------------------
    try:
        with openemr_cursor() as cur:
            cur.execute(
                f"""
                SELECT pid, MAX(date) AS last_enc
                FROM form_encounter
                WHERE pid IN ({pid_placeholders})
                GROUP BY pid
                """,
                tuple(pids),
            )
            for e in cur.fetchall() or []:
                pid = _coerce_int(e.get("pid"))
                sig = signals.get(pid)
                if sig:
                    sig.last_encounter_date = _coerce_date(e.get("last_enc"))
    except Exception as exc:
        logger.warning("awv_prioritization: last-encounter query failed: %s", exc)

    # ----- Last AWV billed (OpenEMR billing) ---------------------------------
    cpt_placeholders = ",".join(["%s"] * len(_AWV_CPT_CODES))
    try:
        with openemr_cursor() as cur:
            cur.execute(
                f"""
                SELECT b.pid, MAX(fe.date) AS last_awv
                FROM billing b
                JOIN form_encounter fe
                       ON b.pid = fe.pid AND b.encounter = fe.encounter
                WHERE b.code IN ({cpt_placeholders})
                  AND b.code_type IN ('CPT4','HCPCS')
                  AND b.activity = 1
                  AND b.pid IN ({pid_placeholders})
                GROUP BY b.pid
                """,
                (*_AWV_CPT_CODES, *pids),
            )
            for a in cur.fetchall() or []:
                pid = _coerce_int(a.get("pid"))
                sig = signals.get(pid)
                if sig:
                    sig.last_awv_date = _coerce_date(a.get("last_awv"))
    except Exception as exc:
        logger.warning("awv_prioritization: last-AWV query failed: %s", exc)

    return list(signals.values())


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _recency_factor(days: int | None) -> float:
    """0.0 if seen today, 1.0 if seen RECENCY_CAP_DAYS ago or never."""
    if days is None:
        return 1.0
    return max(0.0, min(1.0, days / RECENCY_CAP_DAYS))


def _score_one(
    sig: PatientSignals,
    *,
    max_revenue: float,
    max_high_conf: int,
    weights: dict[str, float],
) -> tuple[float, dict[str, float], list[str]]:
    """
    Compute the composite 0-100 score plus per-component contributions and
    a list of human-readable reasons.
    """
    rev_norm = _safe_div(sig.expected_revenue_lift, max_revenue)
    hc_norm = _safe_div(float(sig.high_confidence_suspect_count), float(max_high_conf or 1))
    rec_norm = _recency_factor(sig.last_encounter_days_ago)
    no_awv_norm = 1.0 if sig.no_awv_in_year else 0.0

    components: dict[str, float] = {
        "revenue":            weights["revenue"] * rev_norm,
        "high_conf_suspects": weights["high_conf_suspects"] * hc_norm,
        "recency":            weights["recency"] * rec_norm,
        "no_awv":             weights["no_awv"] * no_awv_norm,
    }
    raw = sum(components.values())
    score = round(min(1.0, max(0.0, raw)) * 100.0, 2)

    reasons: list[str] = []
    if sig.suspect_count:
        reasons.append(
            f"{sig.suspect_count} open suspect"
            + ("s" if sig.suspect_count != 1 else "")
            + (
                f" ({sig.high_confidence_suspect_count} high-confidence)"
                if sig.high_confidence_suspect_count else ""
            )
        )
    if sig.expected_revenue_lift > 0:
        reasons.append(f"~${sig.expected_revenue_lift:,.0f} expected RAF lift")
    if sig.open_care_gaps:
        reasons.append(f"{sig.open_care_gaps} open care gap(s)")
    if sig.last_encounter_days_ago is None:
        reasons.append("no encounter on record")
    elif sig.last_encounter_days_ago >= 365:
        reasons.append(f"last visit {sig.last_encounter_days_ago} days ago")
    if sig.no_awv_in_year:
        if sig.last_awv_date is None:
            reasons.append("no AWV ever billed")
        else:
            months = (sig.last_awv_days_ago or 0) // 30
            reasons.append(f"no AWV in {months} months")

    return score, components, reasons


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def calculate_priority_score(
    patient_id: int,
    tenant_id: str,
    *,
    weights: dict[str, float] | None = None,
    panel_signals: list[PatientSignals] | None = None,
) -> dict[str, Any]:
    """
    Score a single patient.

    Normalization is *panel-relative*: a patient's score depends on what
    other patients exist in the same panel. When called for one patient in
    isolation we score against that patient's own metrics (rev_norm = 1.0 if
    the patient has any opportunity, else 0.0). This keeps the function
    independently usable while ``rank_panel`` provides the calibrated panel-
    wide ranking.

    The optional ``panel_signals`` kwarg lets callers reuse pre-fetched panel
    statistics so we don't re-query the DB N times when scoring a list.
    """
    weights = _normalize_weights(weights)

    if panel_signals is None:
        panel_signals = _fetch_panel_signals(
            tenant_id=tenant_id,
            patient_ids=[int(patient_id)],
        )

    target = next(
        (s for s in panel_signals if s.patient_id == int(patient_id)),
        None,
    )
    if target is None:
        return {
            "patient_id": int(patient_id),
            "score": 0.0,
            "expected_raf_lift": 0.0,
            "expected_revenue_lift": 0.0,
            "suspect_count": 0,
            "high_confidence_suspect_count": 0,
            "last_encounter_days_ago": None,
            "last_awv_days_ago": None,
            "open_care_gaps": 0,
            "reasons": ["patient not found in panel"],
            "components": {},
            "weights": weights,
        }

    max_revenue = max((s.expected_revenue_lift for s in panel_signals), default=0.0)
    max_high_conf = max(
        (s.high_confidence_suspect_count for s in panel_signals), default=0
    )

    score, components, reasons = _score_one(
        target,
        max_revenue=max_revenue,
        max_high_conf=max_high_conf,
        weights=weights,
    )

    return {
        "patient_id": target.patient_id,
        "patient_name": target.name,
        "provider_id": target.provider_id,
        "score": score,
        "expected_raf_lift": target.expected_raf_lift,
        "expected_revenue_lift": target.expected_revenue_lift,
        "suspect_count": target.suspect_count,
        "high_confidence_suspect_count": target.high_confidence_suspect_count,
        "average_confidence": round(target.average_confidence, 4),
        "last_encounter_days_ago": target.last_encounter_days_ago,
        "last_awv_days_ago": target.last_awv_days_ago,
        "open_care_gaps": target.open_care_gaps,
        "no_awv_in_year": target.no_awv_in_year,
        "reasons": reasons,
        "components": {k: round(v, 4) for k, v in components.items()},
        "weights": weights,
    }


def rank_panel(
    tenant_id: str,
    *,
    provider_id: int | None = None,
    patient_ids: Iterable[int] | None = None,
    limit: int = 50,
    weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    """
    Rank an entire panel and return the top *limit* patients.

    Either ``provider_id`` or ``patient_ids`` may be supplied to restrict the
    panel.  When neither is supplied we score every active patient for the
    tenant (subject to the EMR-active filter).
    """
    weights = _normalize_weights(weights)
    panel = _fetch_panel_signals(
        tenant_id=tenant_id,
        provider_id=provider_id,
        patient_ids=patient_ids,
    )

    if not panel:
        return {
            "tenant_id": tenant_id,
            "provider_id": provider_id,
            "total_panel_size": 0,
            "limit": limit,
            "weights": weights,
            "patients": [],
        }

    max_revenue = max((s.expected_revenue_lift for s in panel), default=0.0)
    max_high_conf = max((s.high_confidence_suspect_count for s in panel), default=0)

    scored: list[dict[str, Any]] = []
    for sig in panel:
        score, components, reasons = _score_one(
            sig,
            max_revenue=max_revenue,
            max_high_conf=max_high_conf,
            weights=weights,
        )
        scored.append({
            "patient_id": sig.patient_id,
            "patient_name": sig.name,
            "provider_id": sig.provider_id,
            "score": score,
            "expected_raf_lift": sig.expected_raf_lift,
            "expected_revenue_lift": sig.expected_revenue_lift,
            "suspect_count": sig.suspect_count,
            "high_confidence_suspect_count": sig.high_confidence_suspect_count,
            "average_confidence": round(sig.average_confidence, 4),
            "last_encounter_days_ago": sig.last_encounter_days_ago,
            "last_awv_days_ago": sig.last_awv_days_ago,
            "open_care_gaps": sig.open_care_gaps,
            "no_awv_in_year": sig.no_awv_in_year,
            "reasons": reasons,
            "components": {k: round(v, 4) for k, v in components.items()},
        })

    # Deterministic tie-break: score DESC, revenue DESC, patient_id ASC.
    scored.sort(
        key=lambda r: (-r["score"], -r["expected_revenue_lift"], r["patient_id"])
    )
    top = scored[: max(1, int(limit))]

    return {
        "tenant_id": tenant_id,
        "provider_id": provider_id,
        "total_panel_size": len(panel),
        "limit": int(limit),
        "weights": weights,
        "patients": top,
    }


__all__ = [
    "DEFAULT_WEIGHTS",
    "HIGH_CONFIDENCE_THRESHOLD",
    "RECENCY_CAP_DAYS",
    "AWV_LOOKBACK_DAYS",
    "PatientSignals",
    "calculate_priority_score",
    "rank_panel",
]
