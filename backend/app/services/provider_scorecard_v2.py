"""
Provider Scorecard v2 — per-provider performance with peer benchmarking.

Pareto / Inovalon-style scorecard. Today the platform has *per-patient*
leakage metrics (recapture_gaps), but no aggregated per-provider rate.
This service rolls those up so the UI can render a single row per
provider with:

  * panel_size               — distinct patients attributed via
                                provider_patient_panel
  * avg_raf                  — mean of raf_scores.final_raf for those
                                patients in the given measurement year
  * recapture_rate_pct       — 1 - leakage_rate, where leakage is the
                                ratio of *open* recapture gaps in `year`
                                to prior-year HCC count
  * meat_compliance_pct      — (sum of per-HCC meat completeness) /
                                (4 * total_hccs) — i.e. average MEAT
                                completeness across the panel's coded
                                HCCs

Peer context (tenant-level):
  * tenant_avg_raf
  * tenant_avg_recapture_rate
  * tenant_avg_meat_compliance

Math precisely:
  leakage_rate           = open_recapture_gaps / prior_year_hcc_count
                           (0.0 when prior_year_hcc_count == 0)
  recapture_rate_pct     = round((1 - leakage_rate) * 100, 1)

  meat_score(hcc)        = (has_M + has_E + has_A + has_T) / 4
  meat_compliance_pct    = round( sum(meat_score) / total_hccs * 100, 1 )
                         = round( sum(has_M+has_E+has_A+has_T) / (4 * total_hccs) * 100, 1 )

NOTE
----
We deliberately do NOT create or touch ``provider_scorecard.py`` (which
does not exist) or ``provider_service.py`` (which does). The numbers
here are re-derived from the raw tables so the v1 scorecard surface
stays stable.
"""
# Do NOT add 'from __future__ import annotations' — it breaks FastAPI/Pydantic
# schema generation when types referenced from response_model live here.

import logging
import statistics
from datetime import date
from typing import Any, Optional

from app.db import raf_cursor

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _current_year() -> int:
    return date.today().year


def _resolve_tid(tenant_id) -> int:
    """Match the project-wide convention: fall back to tenant 1 when omitted."""
    return int(tenant_id) if tenant_id is not None else 1


def _safe_mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return float(statistics.mean(values))


# ---------------------------------------------------------------------------
# Core aggregator (shared by single + list endpoints)
# ---------------------------------------------------------------------------


def _aggregate_provider_metrics(
    tenant_id,
    year: int,
    provider_filter: Optional[int] = None,
) -> tuple[list[dict[str, Any]], dict[str, float]]:
    """Compute per-provider metrics + tenant averages.

    Returns (rows, tenant_averages).

    When ``provider_filter`` is provided, only that provider's row is
    returned in ``rows``, but the tenant averages are STILL computed
    across the entire active-provider population so the single-provider
    endpoint can still render a peer delta.
    """
    tid = _resolve_tid(tenant_id)
    yr = int(year)
    prior_year = yr - 1

    providers_sql = """
        SELECT id, npi, full_name, specialty
        FROM providers
        WHERE status = 'active'
        ORDER BY id
    """

    panel_sql = """
        SELECT provider_id, COUNT(DISTINCT patient_id) AS panel_size
        FROM provider_patient_panel
        GROUP BY provider_id
    """

    panel_patients_sql = """
        SELECT provider_id, patient_id
        FROM provider_patient_panel
    """

    with raf_cursor() as cur:
        cur.execute(providers_sql)
        providers = cur.fetchall() or []

        cur.execute(panel_sql)
        panel_sizes = {
            int(r["provider_id"]): int(r["panel_size"])
            for r in (cur.fetchall() or [])
        }

        cur.execute(panel_patients_sql)
        panel_by_provider: dict[int, list[int]] = {}
        for r in (cur.fetchall() or []):
            panel_by_provider.setdefault(int(r["provider_id"]), []).append(
                int(r["patient_id"])
            )

    rows: list[dict[str, Any]] = []

    for p in providers:
        pid = int(p["id"])
        panel = panel_by_provider.get(pid, [])
        psize = panel_sizes.get(pid, 0)

        avg_raf = 0.0
        recapture_rate_pct = 0.0
        meat_compliance_pct = 0.0

        if panel:
            placeholders = ", ".join(["%s"] * len(panel))

            with raf_cursor() as cur:
                # 1) avg_raf — latest score per patient for ``year``.
                cur.execute(
                    f"""
                    SELECT rs.patient_id, rs.final_raf
                    FROM raf_scores rs
                    INNER JOIN (
                        SELECT patient_id, MAX(calculated_at) AS latest
                        FROM raf_scores
                        WHERE measurement_year = %s
                          AND patient_id IN ({placeholders})
                        GROUP BY patient_id
                    ) lx
                       ON rs.patient_id = lx.patient_id
                      AND rs.calculated_at = lx.latest
                    """,
                    tuple([yr] + panel),
                )
                score_rows = cur.fetchall() or []
                raf_values = [
                    float(r["final_raf"]) for r in score_rows
                    if r.get("final_raf") is not None
                ]
                avg_raf = round(_safe_mean(raf_values), 4)

                # 2) recapture_rate_pct via leakage_rate.
                #    leakage = open recapture_gaps for ``year`` / prior_year HCC count
                cur.execute(
                    f"""
                    SELECT COUNT(*) AS open_gaps
                    FROM recapture_gaps
                    WHERE tenant_id    = %s
                      AND current_year = %s
                      AND status       = 'open'
                      AND patient_id IN ({placeholders})
                    """,
                    tuple([str(tid), yr] + panel),
                )
                open_gaps_row = cur.fetchone() or {}
                open_gaps = int(open_gaps_row.get("open_gaps") or 0)

                cur.execute(
                    f"""
                    SELECT COUNT(DISTINCT CONCAT(patient_id, '-', hcc_code))
                           AS prior_hccs
                    FROM raf_patient_hcc
                    WHERE measurement_year = %s
                      AND patient_id IN ({placeholders})
                    """,
                    tuple([prior_year] + panel),
                )
                prior_row = cur.fetchone() or {}
                prior_hccs = int(prior_row.get("prior_hccs") or 0)

                if prior_hccs > 0:
                    leakage_rate = min(1.0, max(0.0, open_gaps / prior_hccs))
                    recapture_rate_pct = round((1.0 - leakage_rate) * 100.0, 1)
                else:
                    # No prior-year HCCs to recapture → trivially 100%.
                    recapture_rate_pct = 100.0

                # 3) meat_compliance_pct
                #    For each HCC in raf_patient_hcc for these panel patients
                #    in ``year``, MEAT score = (M+E+A+T present) / 4.
                #    Then compliance = sum(meat_score) / total_hccs.
                cur.execute(
                    f"""
                    SELECT
                        SUM(CASE WHEN me.meat_m_present = 1 THEN 1 ELSE 0 END) AS sum_m,
                        SUM(CASE WHEN me.meat_e_present = 1 THEN 1 ELSE 0 END) AS sum_e,
                        SUM(CASE WHEN me.meat_a_present = 1 THEN 1 ELSE 0 END) AS sum_a,
                        SUM(CASE WHEN me.meat_t_present = 1 THEN 1 ELSE 0 END) AS sum_t,
                        COUNT(*)                                                AS total_hccs
                    FROM raf_patient_hcc ph
                    LEFT JOIN raf_meat_evidence me ON me.patient_hcc_id = ph.id
                    WHERE ph.measurement_year = %s
                      AND ph.patient_id IN ({placeholders})
                    """,
                    tuple([yr] + panel),
                )
                m_row = cur.fetchone() or {}
                total_hccs = int(m_row.get("total_hccs") or 0)
                if total_hccs > 0:
                    sum_present = (
                        int(m_row.get("sum_m") or 0)
                        + int(m_row.get("sum_e") or 0)
                        + int(m_row.get("sum_a") or 0)
                        + int(m_row.get("sum_t") or 0)
                    )
                    meat_compliance_pct = round(
                        sum_present / (4.0 * total_hccs) * 100.0, 1
                    )
                else:
                    meat_compliance_pct = 0.0

        rows.append(
            {
                "provider_id":          pid,
                "provider_npi":         p.get("npi"),
                "provider_name":        p.get("full_name") or "",
                "specialty":            p.get("specialty"),
                "panel_size":           int(psize),
                "avg_raf":              avg_raf,
                "recapture_rate_pct":   recapture_rate_pct,
                "meat_compliance_pct":  meat_compliance_pct,
            }
        )

    # Tenant averages computed across providers WITH a non-empty panel
    # (excluding empty-panel rows keeps the peer benchmark from being
    # dragged toward zero by inactive providers).
    active = [r for r in rows if r["panel_size"] > 0]
    tenant_averages = {
        "tenant_avg_raf": round(
            _safe_mean([r["avg_raf"] for r in active]), 4
        ),
        "tenant_avg_recapture_rate": round(
            _safe_mean([r["recapture_rate_pct"] for r in active]), 1
        ),
        "tenant_avg_meat_compliance": round(
            _safe_mean([r["meat_compliance_pct"] for r in active]), 1
        ),
    }

    if provider_filter is not None:
        rows = [r for r in rows if r["provider_id"] == int(provider_filter)]

    return rows, tenant_averages


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compute_provider_scorecard(
    provider_id: int,
    tenant_id,
    year: int,
) -> dict[str, Any]:
    """Return the full v2 scorecard payload for one provider.

    The returned dict carries the provider's metrics PLUS tenant
    averages so the UI can render a peer delta without a second call.

    Schema::

        {
            "provider_id":               int,
            "provider_npi":              str | None,
            "provider_name":             str,
            "specialty":                 str | None,
            "panel_size":                int,
            "avg_raf":                   float,
            "recapture_rate_pct":        float,   # 0..100
            "meat_compliance_pct":       float,   # 0..100
            "tenant_avg_raf":            float,
            "tenant_avg_recapture_rate": float,
            "tenant_avg_meat_compliance":float,
            "year":                      int,
        }

    Raises:
        ValueError: when ``provider_id`` does not exist (active) for this
                    tenant.
    """
    rows, averages = _aggregate_provider_metrics(
        tenant_id=tenant_id,
        year=year,
        provider_filter=int(provider_id),
    )
    if not rows:
        raise ValueError(f"provider_id {provider_id} not found (or inactive)")

    payload = dict(rows[0])
    payload.update(averages)
    payload["year"] = int(year) if year else _current_year()
    return payload


def list_provider_scorecards(
    tenant_id,
    year: int,
) -> dict[str, Any]:
    """Return scorecards for every active provider.

    Schema::

        {
            "year":                       int,
            "providers":                  [ <single-provider payload>, ... ],
            "tenant_avg_raf":             float,
            "tenant_avg_recapture_rate":  float,
            "tenant_avg_meat_compliance": float,
        }
    """
    rows, averages = _aggregate_provider_metrics(
        tenant_id=tenant_id,
        year=year,
        provider_filter=None,
    )
    return {
        "year":     int(year) if year else _current_year(),
        "providers": rows,
        **averages,
    }
