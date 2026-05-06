"""
Pre-Visit HCC Briefing service.

For every upcoming visit (today through today + N days) for a given provider,
build a "huddle card" containing the patient's identity plus the top HCC gaps
that should be addressed during the visit.

Why this exists
---------------
Risk-adjustment vendors (Navina, Vim, etc.) live or die on whether a clinician
can see the open HCC gaps DURING the visit, not the next morning when the
encounter is locked. Surfacing the gaps with chief-complaint context, ranked
by ``confidence × expected_dollars``, is what unlocks point-of-care capture.

Sources
-------
* Visits  – ``openemr.form_encounter`` (provider_id, pid, date, reason).
* Patient – ``raf_intelligence.patients`` view (joined on ``patients.emr_pid``
  / ``patient_data.pid``).
* Suspects – ``raf_suspect_conditions`` (status='open').
* Recapture candidates – HCCs coded last year that are NOT yet present in
  the current measurement year.
* MEAT-weak HCCs – ``raf_patient_hcc.meat_status`` IN ('partial','missing').

Top-3 ranking
-------------
For each candidate gap we compute::

    expected_dollars = coefficient × _HCC_BASE_RATE
    score            = confidence × expected_dollars

then keep the highest ``limit_per_patient`` per visit.  Confidence defaults
used when the underlying signal does not carry one:

* Suspect              – ``confidence_score`` (already 0–1).
* Recapture candidate  – ``DEFAULT_CHRONIC_PERSISTENCE`` (0.85).
* MEAT-weak coded HCC  – derived from ``completeness_score`` (1 − score).

``_HCC_BASE_RATE`` is imported from ``provider_service`` per project policy
(no copy-paste constants).
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any

from app.db import openemr_cursor, raf_cursor
from app.services.provider_service import _HCC_BASE_RATE as HCC_BASE_RATE
from app.services.raf_forecast import (
    DEFAULT_CHRONIC_PERSISTENCE,
    DEFAULT_COEFFICIENT_YEAR,
    DEFAULT_MODEL_SEGMENT,
    _coefficient_lookup,
    _resolve_segment,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_DAYS_AHEAD: int = 7
DEFAULT_LIMIT_PER_PATIENT: int = 3

# Confidence floor for a "MEAT-weak" coded HCC's lift potential. We don't
# discount it as aggressively as a brand-new suspect because the diagnosis
# is already coded — the risk is documentation defensibility, not absence.
MEAT_WEAK_BASE_CONFIDENCE: float = 0.60


# ---------------------------------------------------------------------------
# HCC label lookup (best-effort)
# ---------------------------------------------------------------------------

def _hcc_label(hcc_code: str | int) -> str:
    """Return a human-readable HCC label or 'HCC NN' fallback."""
    code_clean = str(hcc_code).replace("HCC", "").strip()
    try:
        from hccinfhir.defaults import labels_default as _labels
        v28_label = _labels.get((code_clean, "CMS-HCC Model V28"))
        if v28_label:
            return v28_label
    except Exception:  # pragma: no cover — optional dep
        pass
    return f"HCC {code_clean}"


# ---------------------------------------------------------------------------
# Visit retrieval
# ---------------------------------------------------------------------------

def _upcoming_visits(provider_id: int, days_ahead: int) -> list[dict[str, Any]]:
    """Return upcoming form_encounter rows for a provider in [today, today+N].

    Encounters are joined to ``raf_intelligence.patients`` so the caller has
    fname / lname / dob / mrn / sex without a second hop.  Only patients with
    an active row in the patients table are returned (matches everywhere else
    in the codebase).
    """
    today = date.today()
    horizon = today + timedelta(days=days_ahead)

    # form_encounter.provider_id is OpenEMR users.id, NOT raf_intelligence.providers.id.
    # Translate via providers.openemr_user_id; fall back to provider_id directly.
    emr_uid = provider_id
    try:
        from app.db import raf_cursor
        with raf_cursor() as cur:
            cur.execute(
                "SELECT openemr_user_id FROM providers WHERE id = %s",
                (provider_id,),
            )
            row = cur.fetchone()
            if row and row.get("openemr_user_id"):
                emr_uid = int(row["openemr_user_id"])
    except Exception:
        pass

    try:
        with openemr_cursor() as cur:
            cur.execute(
                """
                SELECT id          AS encounter_id,
                       pid,
                       date        AS visit_dt,
                       reason
                FROM form_encounter
                WHERE provider_id = %s
                  AND date >= %s
                  AND date <  %s
                ORDER BY date ASC
                """,
                (emr_uid, today, horizon + timedelta(days=1)),
            )
            enc_rows = list(cur.fetchall() or [])
    except Exception as exc:
        logger.warning(
            "_upcoming_visits provider=%s: %s", provider_id, exc, exc_info=True,
        )
        return []

    if not enc_rows:
        return []

    pids = sorted({int(r["pid"]) for r in enc_rows if r.get("pid") is not None})
    patient_lookup: dict[int, dict[str, Any]] = {}
    if pids:
        placeholders = ",".join(["%s"] * len(pids))
        try:
            with raf_cursor() as cur:
                cur.execute(
                    f"""
                    SELECT id          AS patient_id,
                           emr_pid,
                           first_name,
                           last_name,
                           dob,
                           sex,
                           mrn
                    FROM patients
                    WHERE emr_pid IN ({placeholders})
                      AND is_active = 1
                    """,
                    tuple(pids),
                )
                for row in cur.fetchall() or []:
                    if row.get("emr_pid") is not None:
                        patient_lookup[int(row["emr_pid"])] = dict(row)
        except Exception as exc:
            logger.warning("_upcoming_visits patient join failed: %s", exc)

    visits: list[dict[str, Any]] = []
    for r in enc_rows:
        pid = int(r["pid"]) if r.get("pid") is not None else None
        if pid is None:
            continue
        prow = patient_lookup.get(pid)
        if not prow:
            # Patient is not in raf_intelligence.patients (inactive / orphan).
            # Skip — we cannot render a useful huddle card without identity.
            continue

        visit_dt = r.get("visit_dt")
        if isinstance(visit_dt, datetime):
            visit_date = visit_dt.date().isoformat()
            visit_time = visit_dt.strftime("%H:%M")
        elif isinstance(visit_dt, date):
            visit_date = visit_dt.isoformat()
            visit_time = ""
        else:
            visit_date = ""
            visit_time = ""

        visits.append({
            "encounter_id": int(r["encounter_id"]),
            "pid": pid,
            "patient_id": int(prow["patient_id"]),
            "visit_date": visit_date,
            "visit_time": visit_time,
            "encounter_reason": (r.get("reason") or "").strip(),
            "patient": prow,
        })
    return visits


# ---------------------------------------------------------------------------
# Gap candidate builders
# ---------------------------------------------------------------------------

def _suspect_candidates(
    patient_id: int, year: int, segment: str,
) -> list[dict[str, Any]]:
    """Open suspects → candidate gaps."""
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT id, suspect_hcc, suspect_icd10, evidence_type,
                       confidence_score
                FROM raf_suspect_conditions
                WHERE patient_id = %s
                  AND measurement_year = %s
                  AND status = 'open'
                """,
                (patient_id, year),
            )
            rows = list(cur.fetchall() or [])
    except Exception as exc:
        logger.debug("_suspect_candidates pid=%s: %s", patient_id, exc)
        return []

    if not rows:
        return []

    coeffs = _coefficient_lookup([r["suspect_hcc"] for r in rows], segment)
    out: list[dict[str, Any]] = []
    for r in rows:
        hcc_str = str(r["suspect_hcc"])
        coeff = coeffs.get(hcc_str, 0.0)
        confidence = float(r.get("confidence_score") or 0.0)
        expected = round(coeff * HCC_BASE_RATE, 2)
        out.append({
            "hcc_code": hcc_str,
            "hcc_label": _hcc_label(hcc_str),
            "evidence_type": r.get("evidence_type") or "",
            "evidence_snippet": _suspect_snippet(r),
            "confidence": round(confidence, 4),
            "expected_dollars": expected,
            "status": "suspect",
            "icd10": r.get("suspect_icd10") or "",
            "_score": confidence * expected,
        })
    return out


def _suspect_snippet(suspect: dict[str, Any]) -> str:
    """Build a short, human-readable evidence snippet for a suspect row."""
    icd = suspect.get("suspect_icd10") or ""
    et = (suspect.get("evidence_type") or "").replace("_", " ")
    if icd and et:
        return f"{et.capitalize()} suggests {icd} (open suspect)"
    if et:
        return f"{et.capitalize()} suggests open suspect"
    if icd:
        return f"Open suspect for {icd}"
    return "Open suspect"


def _recapture_candidates(
    patient_id: int, year: int, segment: str,
) -> list[dict[str, Any]]:
    """Prior-year chronic HCCs not yet recaptured in current year."""
    prior = year - 1
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT prior.hcc_code,
                       prior.raf_coefficient,
                       prior.icd10_codes
                FROM raf_patient_hcc prior
                LEFT JOIN raf_patient_hcc cur
                  ON  cur.patient_id       = prior.patient_id
                  AND cur.hcc_code         = prior.hcc_code
                  AND cur.measurement_year = %s
                WHERE prior.patient_id       = %s
                  AND prior.measurement_year = %s
                  AND cur.id IS NULL
                """,
                (year, patient_id, prior),
            )
            rows = list(cur.fetchall() or [])
    except Exception as exc:
        logger.debug("_recapture_candidates pid=%s: %s", patient_id, exc)
        return []

    if not rows:
        return []

    # Resolve missing coefficients for any rows with NULL/0 raf_coefficient.
    fallback = _coefficient_lookup(
        [r["hcc_code"] for r in rows if not r.get("raf_coefficient")],
        segment,
    )

    out: list[dict[str, Any]] = []
    for r in rows:
        hcc_str = str(r["hcc_code"])
        coeff = float(r.get("raf_coefficient") or 0.0)
        if not coeff:
            coeff = fallback.get(hcc_str, 0.0)
        expected = round(coeff * HCC_BASE_RATE, 2)
        confidence = DEFAULT_CHRONIC_PERSISTENCE
        out.append({
            "hcc_code": hcc_str,
            "hcc_label": _hcc_label(hcc_str),
            "evidence_type": "prior_year",
            "evidence_snippet": (
                f"Coded last year (HCC {hcc_str}) — not yet recaptured this year"
            ),
            "confidence": round(confidence, 4),
            "expected_dollars": expected,
            "status": "recapture",
            "icd10": "",
            "_score": confidence * expected,
        })
    return out


def _meat_weak_candidates(patient_id: int, year: int) -> list[dict[str, Any]]:
    """Coded HCCs whose MEAT documentation is incomplete this year."""
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT id           AS patient_hcc_id,
                       hcc_code,
                       raf_coefficient,
                       meat_status
                FROM raf_patient_hcc
                WHERE patient_id        = %s
                  AND measurement_year  = %s
                  AND meat_status      IN ('partial', 'missing')
                """,
                (patient_id, year),
            )
            rows = list(cur.fetchall() or [])
    except Exception as exc:
        logger.debug("_meat_weak_candidates pid=%s: %s", patient_id, exc)
        return []

    if not rows:
        return []

    # Pull average completeness scores for these HCCs in one shot.
    ids = [int(r["patient_hcc_id"]) for r in rows]
    placeholders = ",".join(["%s"] * len(ids))
    completeness_by_hcc: dict[int, float] = {}
    try:
        with raf_cursor() as cur:
            cur.execute(
                f"""
                SELECT patient_hcc_id, AVG(completeness_score) AS avg_score
                FROM raf_meat_evidence
                WHERE patient_hcc_id IN ({placeholders})
                GROUP BY patient_hcc_id
                """,
                tuple(ids),
            )
            for row in cur.fetchall() or []:
                completeness_by_hcc[int(row["patient_hcc_id"])] = float(
                    row["avg_score"] or 0.0
                )
    except Exception as exc:
        logger.debug("_meat_weak_candidates completeness lookup: %s", exc)

    out: list[dict[str, Any]] = []
    for r in rows:
        hcc_str = str(r["hcc_code"])
        coeff = float(r.get("raf_coefficient") or 0.0)
        expected = round(coeff * HCC_BASE_RATE, 2)
        completeness = completeness_by_hcc.get(int(r["patient_hcc_id"]), 0.0)
        # Risk that this HCC is dropped on RADV review = (1 − completeness).
        # Clamp confidence to a floor so MEAT-weak gaps still rank meaningfully.
        confidence = max(MEAT_WEAK_BASE_CONFIDENCE, 1.0 - completeness)
        meat_status = (r.get("meat_status") or "missing").lower()
        out.append({
            "hcc_code": hcc_str,
            "hcc_label": _hcc_label(hcc_str),
            "evidence_type": "meat_gap",
            "evidence_snippet": (
                f"MEAT documentation {meat_status} — strengthen during visit"
            ),
            "confidence": round(confidence, 4),
            "expected_dollars": expected,
            "status": "meat_weak",
            "icd10": "",
            "_score": confidence * expected,
        })
    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_upcoming_briefings(
    provider_id: int,
    days_ahead: int = DEFAULT_DAYS_AHEAD,
    limit_per_patient: int = DEFAULT_LIMIT_PER_PATIENT,
    measurement_year: int | None = None,
) -> list[dict[str, Any]]:
    """Build pre-visit huddle cards for a provider's upcoming visits.

    Parameters
    ----------
    provider_id:
        OpenEMR provider id (matches ``form_encounter.provider_id``).  This is
        the same id stored on ``providers`` rows for OpenEMR-imported users.
    days_ahead:
        Inclusive horizon in days from today.  Defaults to 7.
    limit_per_patient:
        Number of HCC gaps to surface per visit (top-N by ranking score).
    measurement_year:
        Defaults to the year of each visit's date.  Useful in tests where the
        seeded data lives in a fixed year.

    Returns
    -------
    A list of dicts (chronological by visit_date / visit_time).  Empty list
    when the provider has no upcoming visits — the router decorates that with
    a helpful empty-state message.
    """
    if days_ahead < 0:
        days_ahead = 0
    if limit_per_patient < 1:
        limit_per_patient = 1

    visits = _upcoming_visits(provider_id, days_ahead)
    if not visits:
        return []

    briefings: list[dict[str, Any]] = []
    for v in visits:
        # Year defaults: prefer caller override, else year of the visit, else
        # current year.
        try:
            visit_year = int((v.get("visit_date") or "")[:4])
        except (TypeError, ValueError):
            visit_year = date.today().year
        year = measurement_year or visit_year or date.today().year

        pid = v["pid"]
        try:
            segment = _resolve_segment(pid, year)
        except Exception:
            segment = DEFAULT_MODEL_SEGMENT

        candidates: list[dict[str, Any]] = []
        candidates.extend(_suspect_candidates(pid, year, segment))
        candidates.extend(_recapture_candidates(pid, year, segment))
        candidates.extend(_meat_weak_candidates(pid, year))

        # De-dupe by hcc_code, keeping the highest-scoring entry. A patient
        # might surface as both an open suspect AND a prior-year unrecaptured
        # HCC; we don't want the same code twice on the huddle card.
        best_by_hcc: dict[str, dict[str, Any]] = {}
        for c in candidates:
            key = c["hcc_code"]
            if key not in best_by_hcc or c["_score"] > best_by_hcc[key]["_score"]:
                best_by_hcc[key] = c

        ranked = sorted(
            best_by_hcc.values(), key=lambda c: c["_score"], reverse=True,
        )[:limit_per_patient]

        # Strip private ranking key before returning
        for c in ranked:
            c.pop("_score", None)

        total_potential = round(
            sum((c.get("expected_dollars") or 0.0) * (c.get("confidence") or 0.0)
                for c in ranked),
            2,
        )

        p = v["patient"]
        dob = p.get("dob")
        dob_iso = dob.isoformat() if hasattr(dob, "isoformat") else (
            str(dob) if dob else None
        )
        age = _calc_age(dob)
        full_name = " ".join(
            x for x in [(p.get("first_name") or "").strip(),
                       (p.get("last_name") or "").strip()] if x
        ) or f"Patient {pid}"

        briefings.append({
            "encounter_id": v["encounter_id"],
            "patient_id": int(p["patient_id"]),
            "pid": pid,
            "patient_name": full_name,
            "dob": dob_iso,
            "age": age,
            "sex": p.get("sex"),
            "mrn": p.get("mrn"),
            "visit_date": v["visit_date"],
            "visit_time": v["visit_time"],
            "encounter_reason": v["encounter_reason"],
            "measurement_year": year,
            "model_segment": segment,
            "top_hccs": ranked,
            "total_potential_dollars": total_potential,
        })

    return briefings


def _calc_age(dob: Any) -> int | None:
    if not dob:
        return None
    if isinstance(dob, str):
        try:
            dob = datetime.fromisoformat(dob).date()
        except ValueError:
            return None
    if isinstance(dob, datetime):
        dob = dob.date()
    if not isinstance(dob, date):
        return None
    today = date.today()
    return today.year - dob.year - (
        (today.month, today.day) < (dob.month, dob.day)
    )


# ---------------------------------------------------------------------------
# Misc public re-exports (helpful for tests / external callers)
# ---------------------------------------------------------------------------

__all__ = [
    "DEFAULT_DAYS_AHEAD",
    "DEFAULT_LIMIT_PER_PATIENT",
    "DEFAULT_COEFFICIENT_YEAR",
    "MEAT_WEAK_BASE_CONFIDENCE",
    "get_upcoming_briefings",
]
