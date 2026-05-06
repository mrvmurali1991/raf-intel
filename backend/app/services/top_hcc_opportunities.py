"""
Top HCC Opportunities Service.

For a single provider, surface the *top N HCCs by expected $ revenue lift*
if captured. Solves the "what should I code first?" paralysis by ranking
missing HCCs by deterministic dollar impact.

Scoring formula (deterministic, no LLM):

    opportunity_score = open_suspect_count_for_hcc
                      * raf_coefficient                      # CMS V28 / CNA / 2024
                      * HCC_BASE_RATE                        # imported, not hardcoded
                      * avg_confidence                       # mean of confidence_score

Peer capture rate (context):

    For the same HCC, average of `coded / (coded + open_suspects)` across all
    OTHER providers in the same specialty (excluding the current provider).
    Returns ``None`` when no peer panels exist.
"""
from __future__ import annotations

import logging
import statistics
from typing import Any

from app.db import raf_cursor
from app.services.emr_manager import active_patients_subquery
from app.services.provider_service import _HCC_BASE_RATE as HCC_BASE_RATE

logger = logging.getLogger(__name__)


# Coefficient table is currently curated for V28 / CNA / 2024 in this DB
DEFAULT_MODEL_SEGMENT: str = "CNA"
DEFAULT_COEFFICIENT_YEAR: int = 2024


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _provider_panel(provider_id: int, tenant_id: int) -> list[int]:
    """Return distinct active patient_ids attributed to this provider."""
    _sf, _sp = active_patients_subquery(tenant_id)
    with raf_cursor() as cur:
        cur.execute(
            f"""
            SELECT DISTINCT patient_id
            FROM provider_patient_panel
            WHERE provider_id = %s
              AND {_sf}
            """,
            (provider_id, *_sp),
        )
        return [int(r["patient_id"]) for r in cur.fetchall()]


def _coded_hccs_for_panel(panel: list[int], year: int) -> set[str]:
    """Return the set of (string) HCC codes already coded for any patient in panel/year."""
    if not panel:
        return set()
    placeholders = ",".join(["%s"] * len(panel))
    with raf_cursor() as cur:
        cur.execute(
            f"""
            SELECT DISTINCT hcc_code
            FROM raf_patient_hcc
            WHERE measurement_year = %s
              AND patient_id IN ({placeholders})
            """,
            tuple([year] + panel),
        )
        return {str(r["hcc_code"]) for r in cur.fetchall()}


def _open_suspects_aggregated(panel: list[int]) -> dict[str, dict[str, Any]]:
    """
    Aggregate open suspects in the panel by suspect_hcc.

    Returns a dict keyed by string HCC code with::

        {"<hcc>": {"patient_count": int, "avg_confidence": float}}

    Patient count counts distinct patients (so a patient with 2 suspects for the
    same HCC counts once). Average confidence is the mean of confidence_score
    across all rows for that HCC.
    """
    if not panel:
        return {}

    placeholders = ",".join(["%s"] * len(panel))
    with raf_cursor() as cur:
        cur.execute(
            f"""
            SELECT
                suspect_hcc                              AS hcc_code,
                COUNT(DISTINCT patient_id)               AS patient_count,
                AVG(COALESCE(confidence_score, 0))       AS avg_confidence
            FROM raf_suspect_conditions
            WHERE status = 'open'
              AND suspect_hcc IS NOT NULL
              AND patient_id IN ({placeholders})
            GROUP BY suspect_hcc
            """,
            tuple(panel),
        )
        rows = cur.fetchall() or []

    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        hcc = str(r["hcc_code"])
        out[hcc] = {
            "patient_count": int(r["patient_count"] or 0),
            "avg_confidence": round(float(r["avg_confidence"] or 0.0), 4),
        }
    return out


def _coefficient_lookup(
    hcc_codes: list[str],
    segment: str = DEFAULT_MODEL_SEGMENT,
    year: int = DEFAULT_COEFFICIENT_YEAR,
) -> dict[str, float]:
    """Bulk fetch RAF coefficients for the given HCC codes / segment / year."""
    if not hcc_codes:
        return {}

    int_codes: list[int] = []
    for c in hcc_codes:
        try:
            int_codes.append(int(str(c).replace("HCC", "").strip()))
        except (ValueError, TypeError):
            continue
    if not int_codes:
        return {}

    placeholders = ",".join(["%s"] * len(int_codes))
    sql = f"""
        SELECT hcc_code, coefficient
        FROM hcc_raf_coefficients
        WHERE model_segment = %s
          AND model_year    = %s
          AND hcc_code IN ({placeholders})
    """
    try:
        with raf_cursor() as cur:
            cur.execute(sql, (segment, year, *int_codes))
            rows = cur.fetchall() or []
        return {str(r["hcc_code"]): float(r["coefficient"]) for r in rows}
    except Exception as exc:
        logger.warning("_coefficient_lookup failed codes=%s: %s", int_codes, exc)
        return {}


def _peer_capture_rates(
    hcc_codes: list[str],
    provider_id: int,
    tenant_id: int,
    year: int,
) -> dict[str, float | None]:
    """
    For each HCC code, compute the average capture rate across providers in
    the same specialty (excluding the current provider).

    capture_rate (per peer) = coded_for_hcc / (coded_for_hcc + open_suspects_for_hcc)
                              over the peer's panel.

    Returns a dict keyed by hcc_code → float (0..1) or None when no peers
    have any signal for that HCC.
    """
    if not hcc_codes:
        return {}

    # 1. Resolve the current provider's specialty
    with raf_cursor() as cur:
        cur.execute(
            "SELECT specialty FROM providers WHERE id = %s",
            (provider_id,),
        )
        me = cur.fetchone()
    specialty = (me or {}).get("specialty") or ""
    if not specialty:
        return {h: None for h in hcc_codes}

    # 2. Find peer providers (same specialty, different id).
    # NOTE: providers table has no tenant_id column on this branch — single-tenant deployment.
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT id
            FROM providers
            WHERE specialty = %s
              AND id <> %s
              AND status = 'active'
            """,
            (specialty, provider_id),
        )
        peer_ids = [int(r["id"]) for r in cur.fetchall() or []]

    if not peer_ids:
        return {h: None for h in hcc_codes}

    # 3. For each peer, compute coded + open_suspect counts for each requested HCC.
    #    Aggregating per peer first (then averaging) prevents one large panel
    #    from dominating.
    per_peer_rates: dict[str, list[float]] = {h: [] for h in hcc_codes}

    _sf, _sp = active_patients_subquery(tenant_id)
    int_codes_s = [str(int(str(h).replace("HCC", "").strip())) for h in hcc_codes if str(h).replace("HCC", "").strip().isdigit()]
    code_placeholders = ",".join(["%s"] * len(int_codes_s)) if int_codes_s else None

    for peer_id in peer_ids:
        with raf_cursor() as cur:
            cur.execute(
                f"""
                SELECT DISTINCT patient_id
                FROM provider_patient_panel
                WHERE provider_id = %s
                  AND {_sf}
                """,
                (peer_id, *_sp),
            )
            peer_panel = [int(r["patient_id"]) for r in cur.fetchall()]
        if not peer_panel:
            continue

        pp_ph = ",".join(["%s"] * len(peer_panel))

        # coded counts per hcc for this peer
        coded_counts: dict[str, int] = {}
        with raf_cursor() as cur:
            sql = f"""
                SELECT hcc_code, COUNT(DISTINCT patient_id) AS cnt
                FROM raf_patient_hcc
                WHERE measurement_year = %s AND patient_id IN ({pp_ph})
                GROUP BY hcc_code
            """
            cur.execute(sql, tuple([year] + peer_panel))
            for r in cur.fetchall() or []:
                coded_counts[str(r["hcc_code"])] = int(r["cnt"])

        # suspect counts per hcc for this peer
        suspect_counts: dict[str, int] = {}
        with raf_cursor() as cur:
            sql = f"""
                SELECT suspect_hcc AS hcc_code, COUNT(DISTINCT patient_id) AS cnt
                FROM raf_suspect_conditions
                WHERE status = 'open'
                  AND suspect_hcc IS NOT NULL
                  AND patient_id IN ({pp_ph})
                GROUP BY suspect_hcc
            """
            cur.execute(sql, tuple(peer_panel))
            for r in cur.fetchall() or []:
                suspect_counts[str(r["hcc_code"])] = int(r["cnt"])

        for hcc in hcc_codes:
            coded = coded_counts.get(hcc, 0)
            suspects = suspect_counts.get(hcc, 0)
            possible = coded + suspects
            if possible <= 0:
                continue
            per_peer_rates[hcc].append(coded / possible)

    out: dict[str, float | None] = {}
    for hcc, rates in per_peer_rates.items():
        out[hcc] = round(statistics.mean(rates), 4) if rates else None
    return out


def _hcc_label(hcc_code: str) -> str:
    """Resolve a human-readable label for an HCC code via hccinfhir defaults."""
    try:
        from hccinfhir.defaults import labels_default as _labels

        _V28 = "CMS-HCC Model V28"
    except ImportError:
        return f"HCC {hcc_code}"

    code_clean = str(hcc_code).replace("HCC", "").strip()
    return _labels.get((code_clean, _V28)) or f"HCC {code_clean}"


# ---------------------------------------------------------------------------
# Public: top HCC opportunities for a provider
# ---------------------------------------------------------------------------

def compute_top_hccs(
    provider_id: int,
    year: int,
    limit: int = 5,
    *,
    tenant_id: int | None = None,
    model_segment: str = DEFAULT_MODEL_SEGMENT,
    coefficient_year: int = DEFAULT_COEFFICIENT_YEAR,
) -> list[dict[str, Any]]:
    """
    Return the top *limit* HCC opportunities for a provider, ranked by expected
    $ revenue lift.

    A "missing" HCC means: open suspects exist in the panel for that HCC AND
    the HCC is NOT already coded for the panel in the same measurement year.

    Each entry in the returned list has the shape::

        {
          "hcc_code": "108",
          "hcc_label": "Vascular Disease",
          "patient_count_missing": 4,
          "avg_confidence": 0.78,
          "raf_coefficient": 0.299,
          "expected_lift": 11_169.6,
          "peer_capture_rate": 0.62 | None,
          "model_segment": "CNA",
          "model_year": 2024,
        }
    """
    tid = int(tenant_id) if tenant_id is not None else 1

    panel = _provider_panel(provider_id, tid)
    if not panel:
        return []

    suspect_agg = _open_suspects_aggregated(panel)
    if not suspect_agg:
        return []

    coded = _coded_hccs_for_panel(panel, year)

    # Only consider HCCs that are NOT already coded in the panel for the year.
    candidate_hccs = [hcc for hcc in suspect_agg.keys() if hcc not in coded]
    if not candidate_hccs:
        return []

    coeffs = _coefficient_lookup(candidate_hccs, model_segment, coefficient_year)

    # Score
    scored: list[dict[str, Any]] = []
    for hcc in candidate_hccs:
        agg = suspect_agg[hcc]
        coeff = coeffs.get(hcc, 0.0)
        if coeff <= 0:
            # Skip HCCs without a known coefficient — score would be zero and
            # ranking by zeros is noise.
            continue
        patient_count = agg["patient_count"]
        avg_conf = agg["avg_confidence"]
        expected_lift = patient_count * coeff * HCC_BASE_RATE * avg_conf
        scored.append(
            {
                "hcc_code": hcc,
                "hcc_label": _hcc_label(hcc),
                "patient_count_missing": patient_count,
                "avg_confidence": avg_conf,
                "raf_coefficient": round(coeff, 4),
                "expected_lift": round(expected_lift, 2),
                "model_segment": model_segment,
                "model_year": coefficient_year,
            }
        )

    scored.sort(key=lambda r: r["expected_lift"], reverse=True)
    top = scored[: max(int(limit), 0)]

    # Peer context — only fetch for the codes we'll actually return
    if top:
        peer_rates = _peer_capture_rates(
            [r["hcc_code"] for r in top], provider_id, tid, year
        )
        for r in top:
            r["peer_capture_rate"] = peer_rates.get(r["hcc_code"])
    return top
