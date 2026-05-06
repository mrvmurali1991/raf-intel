"""
MEAT Audit-Risk Service — RADV audit clawback risk badge per provider.

For a given provider this service:
  * Aggregates the MEAT completeness across all coded HCCs in the provider's
    panel (via provider_patient_panel + raf_patient_hcc + raf_meat_evidence)
  * Buckets the result into a risk tier (ready / at_risk / audit_risk /
    insufficient)
  * Surfaces the 5 weakest HCCs (those with MEAT < 0.75) along with which
    of the four MEAT components (M / E / A / T) are missing

Public API
----------
assess_provider_audit_risk(provider_id, year, tenant_id=None)
    -> dict   full risk assessment payload (see ASSESSMENT SCHEMA below)

get_meat_evidence_for_hcc(provider_id, hcc_code, year, tenant_id=None)
    -> list[dict]   per-patient evidence rows for a single HCC code in this
                    provider's panel

ASSESSMENT SCHEMA
-----------------
{
  "provider_id": int,
  "year": int,
  "meat_completeness": float,      # 0.0 - 1.0, mean MEAT across coded HCCs
  "hcc_count": int,                # number of distinct coded HCCs
  "risk_tier": "ready" | "at_risk" | "audit_risk" | "insufficient",
  "risk_label": "AUDIT-READY" | "AT RISK" | "AUDIT RISK" | "INSUFFICIENT DATA",
  "top_weak_hccs": [
    {
      "hcc_code": "85",
      "label": "Congestive Heart Failure",
      "meat_score": 0.5,
      "patient_hcc_ids": [12, 78, ...],
      "missing_components": ["Monitor", "Treat"]
    },
    ...
  ]
}

RISK TIER THRESHOLDS
--------------------
  meat >= 0.80  → ready       (green AUDIT-READY)
  0.60 <= m  < 0.80 → at_risk (amber AT RISK)
  meat <  0.60  → audit_risk  (red AUDIT RISK)
  hcc_count < 3 → insufficient (gray INSUFFICIENT DATA)

The thresholds are CMOs-of-RAF-programs-tested heuristics — they map to
RADV "minor" / "major" / "critical" deficiency categories used by the
auditors we benchmark against.
"""
from __future__ import annotations

import logging
from typing import Any

from app.db import raf_cursor
from app.services.emr_manager import active_patients_subquery

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Risk-tier thresholds
# ---------------------------------------------------------------------------

# Minimum number of coded HCCs required to render a meaningful risk verdict
# (RADV samples typically include 3-5 HCCs per chart, so anything below 3 is
# statistically meaningless).
_MIN_HCCS_FOR_RISK = 3

_TIER_READY = 0.80
_TIER_AT_RISK = 0.60

# Weak-HCC drilldown: 5 lowest-scoring HCCs with score < 0.75 are surfaced.
_WEAK_HCC_THRESHOLD = 0.75
_WEAK_HCC_LIMIT = 5


_TIER_LABELS: dict[str, str] = {
    "ready": "AUDIT-READY",
    "at_risk": "AT RISK",
    "audit_risk": "AUDIT RISK",
    "insufficient": "INSUFFICIENT DATA",
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _classify_tier(meat_completeness: float, hcc_count: int) -> str:
    """Map a (completeness, count) pair to one of the four risk tiers."""
    if hcc_count < _MIN_HCCS_FOR_RISK:
        return "insufficient"
    if meat_completeness >= _TIER_READY:
        return "ready"
    if meat_completeness >= _TIER_AT_RISK:
        return "at_risk"
    return "audit_risk"


def _missing_components(has_m: bool, has_e: bool, has_a: bool, has_t: bool) -> list[str]:
    """Return the human-readable names of the MEAT elements that are missing."""
    missing: list[str] = []
    if not has_m:
        missing.append("Monitor")
    if not has_e:
        missing.append("Evaluate")
    if not has_a:
        missing.append("Assess")
    if not has_t:
        missing.append("Treat")
    return missing


def _hcc_label(hcc_code: str) -> str:
    """Look up a V28 HCC label, falling back to ``HCC <code>``.

    Imports are local because hccinfhir takes a noticeable amount of memory
    to initialise and we don't want this service to pay that cost at module
    load time when the function is never called.
    """
    try:
        from app.services.raf.calculator import _get_hcc_label_v28

        return _get_hcc_label_v28(str(hcc_code))
    except Exception:  # pragma: no cover — defensive fallback
        return f"HCC {hcc_code}"


def _panel_patient_ids(provider_id: int, tid: int) -> list[int]:
    """Return the active-EMR patient IDs in this provider's panel."""
    sub_sql, sub_params = active_patients_subquery(tid)
    with raf_cursor() as cur:
        cur.execute(
            f"SELECT patient_id FROM provider_patient_panel "
            f"WHERE provider_id = %s AND {sub_sql}",
            (provider_id, *sub_params),
        )
        return [r["patient_id"] for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# 1. assess_provider_audit_risk
# ---------------------------------------------------------------------------


def assess_provider_audit_risk(
    provider_id: int,
    year: int = 2026,
    tenant_id: int | str | None = None,
) -> dict[str, Any]:
    """Compute the full audit-risk assessment for one provider.

    Parameters
    ----------
    provider_id:
        Database id of the provider in ``providers``.
    year:
        Measurement year (defaults to 2026 — current RAF year).
    tenant_id:
        Caller's tenant id; ``None`` falls back to single-tenant id 1.

    Returns
    -------
    dict
        See ASSESSMENT SCHEMA in the module docstring.
    """
    tid = int(tenant_id) if tenant_id is not None else 1

    panel = _panel_patient_ids(provider_id, tid)

    if not panel:
        logger.debug(
            "assess_provider_audit_risk: provider %s has no panel patients", provider_id
        )
        return {
            "provider_id": provider_id,
            "year": year,
            "meat_completeness": 0.0,
            "hcc_count": 0,
            "risk_tier": "insufficient",
            "risk_label": _TIER_LABELS["insufficient"],
            "top_weak_hccs": [],
        }

    placeholders = ", ".join(["%s"] * len(panel))

    with raf_cursor() as cur:
        # Aggregate MEAT presence per (hcc_code) across the panel.
        # We count an HCC as having a component "present" when ANY supporting
        # encounter for ANY patient documents that component — RADV auditors
        # look at any defensible chart in the lookback window.
        cur.execute(
            f"""
            SELECT
                ph.hcc_code            AS hcc_code,
                COUNT(DISTINCT ph.id)  AS phcc_count,
                MAX(me.meat_m_present) AS has_m,
                MAX(me.meat_e_present) AS has_e,
                MAX(me.meat_a_present) AS has_a,
                MAX(me.meat_t_present) AS has_t
            FROM raf_patient_hcc ph
            LEFT JOIN raf_meat_evidence me ON me.patient_hcc_id = ph.id
            WHERE ph.measurement_year = %s
              AND ph.patient_id IN ({placeholders})
            GROUP BY ph.hcc_code
            ORDER BY ph.hcc_code
            """,
            tuple([year] + panel),
        )
        agg_rows = cur.fetchall()

        # We also need the underlying patient_hcc_ids so the modal can drill
        # into the per-patient evidence rows for a given HCC.
        cur.execute(
            f"""
            SELECT id, hcc_code
            FROM raf_patient_hcc
            WHERE measurement_year = %s
              AND patient_id IN ({placeholders})
            """,
            tuple([year] + panel),
        )
        phcc_by_code: dict[str, list[int]] = {}
        for r in cur.fetchall():
            code = str(r["hcc_code"])
            phcc_by_code.setdefault(code, []).append(int(r["id"]))

    if not agg_rows:
        return {
            "provider_id": provider_id,
            "year": year,
            "meat_completeness": 0.0,
            "hcc_count": 0,
            "risk_tier": "insufficient",
            "risk_label": _TIER_LABELS["insufficient"],
            "top_weak_hccs": [],
        }

    per_hcc: list[dict[str, Any]] = []
    for r in agg_rows:
        has_m = bool(r["has_m"])
        has_e = bool(r["has_e"])
        has_a = bool(r["has_a"])
        has_t = bool(r["has_t"])
        score = sum([has_m, has_e, has_a, has_t]) / 4.0
        code = str(r["hcc_code"])
        per_hcc.append(
            {
                "hcc_code": code,
                "label": _hcc_label(code),
                "meat_score": round(score, 4),
                "patient_hcc_ids": phcc_by_code.get(code, []),
                "missing_components": _missing_components(has_m, has_e, has_a, has_t),
            }
        )

    hcc_count = len(per_hcc)
    meat_completeness = (
        round(sum(h["meat_score"] for h in per_hcc) / hcc_count, 4)
        if hcc_count
        else 0.0
    )

    # Top weak HCCs = lowest-scoring HCCs below the WEAK threshold, capped.
    weak_sorted = sorted(
        (h for h in per_hcc if h["meat_score"] < _WEAK_HCC_THRESHOLD),
        key=lambda h: (h["meat_score"], h["hcc_code"]),
    )
    top_weak = weak_sorted[:_WEAK_HCC_LIMIT]

    tier = _classify_tier(meat_completeness, hcc_count)

    return {
        "provider_id": provider_id,
        "year": year,
        "meat_completeness": meat_completeness,
        "hcc_count": hcc_count,
        "risk_tier": tier,
        "risk_label": _TIER_LABELS[tier],
        "top_weak_hccs": top_weak,
    }


# ---------------------------------------------------------------------------
# 2. get_meat_evidence_for_hcc
# ---------------------------------------------------------------------------


def get_meat_evidence_for_hcc(
    provider_id: int,
    hcc_code: str,
    year: int = 2026,
    tenant_id: int | str | None = None,
) -> list[dict[str, Any]]:
    """Per-patient MEAT evidence for one HCC across this provider's panel.

    Returns one row per (patient, encounter) covering the requested HCC, with
    a flag for each MEAT component plus a short evidence snippet for the
    coder to eyeball without leaving the badge modal.

    Returns
    -------
    list[dict]   each dict has:
        patient_id          int
        patient_hcc_id      int
        encounter_id        int
        encounter_date      str (YYYY-MM-DD)
        components_present  list[str]   subset of ['Monitor','Evaluate','Assess','Treat']
        components_missing  list[str]   the complement
        meat_score          float       this row's completeness (0.0 - 1.0)
        evidence_snippet    str         first ~240 chars of supporting text
    """
    tid = int(tenant_id) if tenant_id is not None else 1
    panel = _panel_patient_ids(provider_id, tid)
    if not panel:
        return []

    placeholders = ", ".join(["%s"] * len(panel))

    # raf_patient_hcc.hcc_code is stored as INT in this schema (numeric), but
    # callers may pass "85" or "HCC85". Normalise to the integer form.
    raw = str(hcc_code).upper().lstrip("HCC").strip()
    try:
        hcc_int = int(raw)
    except ValueError:
        logger.warning("get_meat_evidence_for_hcc: unparseable hcc_code=%r", hcc_code)
        return []

    with raf_cursor() as cur:
        cur.execute(
            f"""
            SELECT
                ph.id              AS patient_hcc_id,
                ph.patient_id      AS patient_id,
                me.encounter_id    AS encounter_id,
                me.encounter_date  AS encounter_date,
                me.meat_m_present  AS has_m,
                me.meat_e_present  AS has_e,
                me.meat_a_present  AS has_a,
                me.meat_t_present  AS has_t,
                me.completeness_score AS score,
                me.raw_note_excerpt AS excerpt
            FROM raf_patient_hcc ph
            LEFT JOIN raf_meat_evidence me ON me.patient_hcc_id = ph.id
            WHERE ph.measurement_year = %s
              AND ph.hcc_code         = %s
              AND ph.patient_id IN ({placeholders})
            ORDER BY ph.patient_id, me.encounter_date DESC
            """,
            tuple([year, hcc_int] + panel),
        )
        rows = cur.fetchall()

    out: list[dict[str, Any]] = []
    for r in rows:
        has_m = bool(r["has_m"])
        has_e = bool(r["has_e"])
        has_a = bool(r["has_a"])
        has_t = bool(r["has_t"])
        present: list[str] = []
        if has_m:
            present.append("Monitor")
        if has_e:
            present.append("Evaluate")
        if has_a:
            present.append("Assess")
        if has_t:
            present.append("Treat")

        excerpt = r.get("excerpt") or ""
        if len(excerpt) > 240:
            excerpt = excerpt[:240].rstrip() + "..."

        score_raw = r.get("score")
        if score_raw is None:
            score = sum([has_m, has_e, has_a, has_t]) / 4.0
        else:
            score = float(score_raw)

        out.append(
            {
                "patient_id": int(r["patient_id"]),
                "patient_hcc_id": int(r["patient_hcc_id"]),
                "encounter_id": int(r["encounter_id"]) if r.get("encounter_id") else None,
                "encounter_date": (
                    r["encounter_date"].isoformat()
                    if r.get("encounter_date") and hasattr(r["encounter_date"], "isoformat")
                    else (r.get("encounter_date") or None)
                ),
                "components_present": present,
                "components_missing": _missing_components(has_m, has_e, has_a, has_t),
                "meat_score": round(score, 4),
                "evidence_snippet": excerpt,
            }
        )

    return out
