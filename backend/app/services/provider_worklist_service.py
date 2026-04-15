"""
Provider Worklist Service — business logic for the provider-facing RAF worklist.

Responsibilities
----------------
- Return a prioritized list of patients a provider should see for RAF optimization,
  including open recapture gaps, suspect conditions, and estimated revenue impact.
- Return specific per-visit action items for a patient (HCCs to recapture,
  incomplete MEAT criteria, suggested diagnoses).
- Aggregate tenant-level summary statistics (patients at risk, RAF impact, top
  conditions, provider performance metrics).

All DB access goes through ``raf_cursor`` from app.db which commits on success
and rolls back on exception.

Tables accessed (all in the RAF Intelligence schema):
  patients               — demographic base: first_name, last_name, dob, tenant_id
  raf_patient_hcc        — active HCCs: hcc_code, icd10_codes, measurement_year,
                           raf_coefficient, meat_status, tenant_id
  recapture_gaps         — open gaps from prior year: status, hcc_code, icd10_code,
                           revenue_impact, provider_npi
  normalized_encounters  — encounter history: encounter_date, provider_npi, patient_id
  normalized_diagnoses   — diagnoses per encounter: icd10_code, hcc_code, description
  suspects               — NLP/lab suspects (optional): hcc_code, confidence, source

Tables that may not exist yet are handled gracefully; the relevant queries fall
back to empty lists rather than propagating exceptions.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from typing import Any

from app.db import raf_cursor
from app.services.cache_strategy import tenant_cached, TTL_WORKLIST

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Revenue assumed per open recapture gap when recapture_gaps.revenue_impact
# is NULL or the table does not exist.
# ---------------------------------------------------------------------------
_DEFAULT_REVENUE_PER_GAP: float = 3_000.00

# Priority score ceiling — patients at this score go to the top of the list.
_MAX_PRIORITY: int = 100


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _table_exists(table_name: str) -> bool:
    """Return True when *table_name* exists in the RAF Intelligence database."""
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM   information_schema.tables
            WHERE  table_schema = DATABASE()
              AND  table_name   = %s
            """,
            (table_name,),
        )
        row = cur.fetchone()
        return bool(row and row["cnt"])


def _safe_date(value: Any) -> str | None:
    """Convert a date/datetime/str to ISO-8601 string, or None."""
    if value is None:
        return None
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def _parse_icd10_codes(raw: Any) -> list[str]:
    """Deserialise icd10_codes JSON column; return [] on any error."""
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else [str(parsed)]
    except (json.JSONDecodeError, TypeError):
        return [str(raw)] if raw else []


def _build_priority_score(
    open_gap_count: int,
    suspected_hcc_count: int,
    total_revenue_at_risk: float,
) -> int:
    """
    Heuristic priority score (0–100).

    Weights:
      - Each open recapture gap contributes up to 15 points (max 5 gaps = 75 pts).
      - Each suspected HCC not yet in gaps contributes up to 5 points (max 3 = 15).
      - Revenue at risk above $5k adds a bonus (up to 10 pts).

    Higher score → provider should see this patient sooner.
    """
    gap_score = min(open_gap_count * 15, 75)
    suspect_score = min(suspected_hcc_count * 5, 15)
    revenue_bonus = min(int(max(total_revenue_at_risk - 5_000, 0) / 1_000), 10)
    return min(gap_score + suspect_score + revenue_bonus, _MAX_PRIORITY)


# ---------------------------------------------------------------------------
# 1. get_provider_worklist
# ---------------------------------------------------------------------------


def get_provider_worklist(
    provider_id: int,
    tenant_id: str,
    measurement_year: int,
) -> list[dict[str, Any]]:
    """
    Return a prioritized worklist of patients for a provider.

    Each item in the returned list contains:
      patient_id            — internal RAF patient ID
      patient_name          — "Last, First"
      dob                   — ISO-8601 date of birth
      last_visit_date       — ISO-8601 date of most recent encounter
      open_recapture_gaps   — list of gap dicts (hcc_code, icd10_codes,
                              prior_year, revenue_impact)
      suspect_conditions    — list of suspect dicts (hcc_code, source,
                              confidence) from NLP/lab analysis
      estimated_raf_impact  — sum of raf_coefficient for all open gaps
      estimated_revenue_at_risk — sum of revenue_impact for all open gaps
      priority_score        — 0–100 (higher = more urgent)

    Patients are sorted descending by priority_score.

    The provider filter uses provider_npi resolved from the ``providers``
    table when available, otherwise falls back to the raw provider_id string
    so the endpoint still returns data if the providers table has a different
    schema.

    Parameters
    ----------
    provider_id:
        Internal provider user ID (users.id).
    tenant_id:
        Tenant scope — mandatory for HIPAA isolation.
    measurement_year:
        The RAF measurement year to evaluate (e.g. 2026).
    """
    if not tenant_id:
        raise ValueError(
            "get_provider_worklist: tenant_id is required — "
            "refusing to operate without tenant scope (HIPAA multi-tenant isolation)"
        )

    # ---- Resolve provider NPI (optional — graceful fallback) ----
    provider_npi: str | None = None
    try:
        with raf_cursor() as cur:
            cur.execute(
                "SELECT npi FROM providers WHERE user_id = %s AND tenant_id = %s LIMIT 1",
                (provider_id, tenant_id),
            )
            row = cur.fetchone()
            if row:
                provider_npi = row["npi"]
    except Exception as exc:  # pragma: no cover
        logger.debug("get_provider_worklist: could not resolve NPI for provider %s: %s", provider_id, exc)

    # ---- Fetch patients assigned to this provider ----
    # Strategy: patients who have at least one encounter with this provider's NPI
    # (or provider_id used as a fallback NPI string) OR who have an open recapture
    # gap linked to this provider's NPI.  We always scope to tenant.
    npi_filter = provider_npi if provider_npi else str(provider_id)

    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT
                       p.id       AS patient_id,
                       COALESCE(NULLIF(p.first_name, ''), epm.first_name) AS first_name,
                       COALESCE(NULLIF(p.last_name,  ''), epm.last_name)  AS last_name,
                       p.dob
                FROM   patients p
                LEFT JOIN emr_patient_matches epm
                       ON  epm.patient_id  = p.id
                       AND epm.tenant_id   = %s
                WHERE  p.tenant_id  = %s
                  AND  p.is_active  = 1
                  AND  p.id IN (
                       SELECT ne.patient_id
                       FROM   normalized_encounters ne
                       WHERE  ne.tenant_id    = %s
                         AND  ne.provider_npi = %s
                  )
                ORDER BY COALESCE(NULLIF(p.last_name, ''), epm.last_name),
                         COALESCE(NULLIF(p.first_name, ''), epm.first_name)
                """,
                (tenant_id, tenant_id, tenant_id, npi_filter),
            )
            patients = cur.fetchall()
    except Exception as exc:
        logger.error("get_provider_worklist: patient query failed: %s", exc)
        return []

    if not patients:
        logger.debug(
            "get_provider_worklist: no patients found for provider=%s npi=%s tenant=%s",
            provider_id, npi_filter, tenant_id,
        )
        return []

    patient_ids = [p["patient_id"] for p in patients]
    id_placeholders = ", ".join(["%s"] * len(patient_ids))

    # ---- Last visit date per patient ----
    last_visit_map: dict[int, str | None] = {}
    try:
        with raf_cursor() as cur:
            cur.execute(
                f"""
                SELECT patient_id, MAX(encounter_date) AS last_visit
                FROM   normalized_encounters
                WHERE  tenant_id   = %s
                  AND  patient_id  IN ({id_placeholders})
                GROUP BY patient_id
                """,
                [tenant_id] + patient_ids,
            )
            for row in cur.fetchall():
                last_visit_map[row["patient_id"]] = _safe_date(row["last_visit"])
    except Exception as exc:
        logger.debug("get_provider_worklist: last visit query failed: %s", exc)

    # ---- Open recapture gaps per patient ----
    gaps_map: dict[int, list[dict[str, Any]]] = {pid: [] for pid in patient_ids}
    recapture_exists = _table_exists("recapture_gaps")
    if recapture_exists:
        try:
            with raf_cursor() as cur:
                cur.execute(
                    f"""
                    SELECT patient_id,
                           hcc_code,
                           icd10_code,
                           prior_year,
                           COALESCE(revenue_impact, %s) AS revenue_impact
                    FROM   recapture_gaps
                    WHERE  tenant_id   = %s
                      AND  status      = 'open'
                      AND  current_year = %s
                      AND  patient_id  IN ({id_placeholders})
                    ORDER BY patient_id, revenue_impact DESC
                    """,
                    [_DEFAULT_REVENUE_PER_GAP, tenant_id, measurement_year] + patient_ids,
                )
                for row in cur.fetchall():
                    pid = int(row["patient_id"]) if not isinstance(row["patient_id"], int) else row["patient_id"]
                    gaps_map.setdefault(pid, []).append({
                        "hcc_code": row["hcc_code"],
                        "icd10_codes": [row["icd10_code"]] if row["icd10_code"] else [],
                        "prior_year": row["prior_year"],
                        "revenue_impact": float(row["revenue_impact"] or 0),
                    })
        except Exception as exc:
            logger.debug("get_provider_worklist: recapture_gaps query failed: %s", exc)
    else:
        # Fall back: derive gaps from raf_patient_hcc — HCCs present in prior_year
        # but absent in measurement_year.
        prior_year = measurement_year - 1
        try:
            with raf_cursor() as cur:
                cur.execute(
                    f"""
                    SELECT ph.patient_id,
                           ph.hcc_code,
                           ph.icd10_codes,
                           %s AS prior_year,
                           COALESCE(ph.raf_coefficient * 3000, %s) AS revenue_impact
                    FROM   raf_patient_hcc ph
                    WHERE  ph.tenant_id       = %s
                      AND  ph.measurement_year = %s
                      AND  ph.patient_id       IN ({id_placeholders})
                      AND  NOT EXISTS (
                           SELECT 1
                           FROM   raf_patient_hcc cy
                           WHERE  cy.patient_id       = ph.patient_id
                             AND  cy.hcc_code         = ph.hcc_code
                             AND  cy.measurement_year = %s
                             AND  cy.tenant_id        = %s
                      )
                    ORDER BY ph.patient_id, ph.raf_coefficient DESC
                    """,
                    [prior_year, _DEFAULT_REVENUE_PER_GAP, tenant_id, prior_year]
                    + patient_ids
                    + [measurement_year, tenant_id],
                )
                for row in cur.fetchall():
                    pid = int(row["patient_id"]) if not isinstance(row["patient_id"], int) else row["patient_id"]
                    gaps_map.setdefault(pid, []).append({
                        "hcc_code": row["hcc_code"],
                        "icd10_codes": _parse_icd10_codes(row["icd10_codes"]),
                        "prior_year": prior_year,
                        "revenue_impact": float(row["revenue_impact"] or _DEFAULT_REVENUE_PER_GAP),
                    })
        except Exception as exc:
            logger.debug("get_provider_worklist: derived gaps query failed: %s", exc)

    # ---- RAF coefficient per open gap ----
    raf_coeff_map: dict[int, float] = {}
    try:
        with raf_cursor() as cur:
            cur.execute(
                f"""
                SELECT patient_id,
                       COALESCE(SUM(raf_coefficient), 0) AS total_coeff
                FROM   raf_patient_hcc
                WHERE  tenant_id        = %s
                  AND  measurement_year = %s
                  AND  patient_id       IN ({id_placeholders})
                GROUP BY patient_id
                """,
                [tenant_id, measurement_year] + patient_ids,
            )
            for row in cur.fetchall():
                pid = int(row["patient_id"]) if not isinstance(row["patient_id"], int) else row["patient_id"]
                raf_coeff_map[pid] = float(row["total_coeff"] or 0)
    except Exception as exc:
        logger.debug("get_provider_worklist: raf_coeff query failed: %s", exc)

    # ---- Suspect conditions (NLP / lab suspects) ----
    suspects_map: dict[int, list[dict[str, Any]]] = {pid: [] for pid in patient_ids}
    suspects_exists = _table_exists("suspects")
    if suspects_exists:
        try:
            with raf_cursor() as cur:
                cur.execute(
                    f"""
                    SELECT patient_id,
                           hcc_code,
                           source,
                           confidence
                    FROM   suspects
                    WHERE  tenant_id   = %s
                      AND  status      = 'open'
                      AND  patient_id  IN ({id_placeholders})
                    ORDER BY patient_id, confidence DESC
                    """,
                    [tenant_id] + patient_ids,
                )
                for row in cur.fetchall():
                    pid = int(row["patient_id"]) if not isinstance(row["patient_id"], int) else row["patient_id"]
                    suspects_map.setdefault(pid, []).append({
                        "hcc_code": row["hcc_code"],
                        "source": row["source"],
                        "confidence": float(row["confidence"] or 0),
                    })
        except Exception as exc:
            logger.debug("get_provider_worklist: suspects query failed: %s", exc)

    # ---- Assemble worklist items ----
    worklist: list[dict[str, Any]] = []
    for p in patients:
        pid: int = p["patient_id"]
        gaps = gaps_map.get(pid, [])
        suspects = suspects_map.get(pid, [])

        revenue_at_risk = sum(g["revenue_impact"] for g in gaps)
        estimated_raf_impact = raf_coeff_map.get(pid, 0.0)
        priority = _build_priority_score(
            open_gap_count=len(gaps),
            suspected_hcc_count=len(suspects),
            total_revenue_at_risk=revenue_at_risk,
        )

        worklist.append({
            "patient_id": pid,
            "patient_name": f"{p['last_name']}, {p['first_name']}",
            "dob": _safe_date(p["dob"]),
            "last_visit_date": last_visit_map.get(pid),
            "open_recapture_gaps": gaps,
            "suspect_conditions": suspects,
            "estimated_raf_impact": round(estimated_raf_impact, 4),
            "estimated_revenue_at_risk": round(revenue_at_risk, 2),
            "priority_score": priority,
        })

    # Sort: highest priority first; break ties by most revenue at risk.
    worklist.sort(key=lambda x: (-x["priority_score"], -x["estimated_revenue_at_risk"]))
    return worklist


# ---------------------------------------------------------------------------
# 2. get_patient_action_items
# ---------------------------------------------------------------------------


def get_patient_action_items(
    patient_id: int,
    tenant_id: str,
) -> list[dict[str, Any]]:
    """
    Return specific action items for a patient visit.

    Each item in the returned list represents one actionable task with keys:
      action_type     — one of: 'recapture_hcc' | 'incomplete_meat' |
                        'missing_encounter' | 'suggested_diagnosis'
      hcc_code        — HCC number (int)
      icd10_codes     — list of ICD-10-CM codes relevant to this action
      description     — human-readable description of the action
      meat_status     — current MEAT status ('missing'|'partial'|'complete') or None
      source          — 'recapture_gap' | 'nlp' | 'lab' | 'historical' | 'meat'
      priority        — 1 (highest) to 5 (lowest)

    Ordering: action_type priority first (recapture_hcc → incomplete_meat →
    missing_encounter → suggested_diagnosis), then by HCC code.

    Parameters
    ----------
    patient_id:
        Internal RAF patient ID.
    tenant_id:
        Tenant scope — mandatory for HIPAA isolation.
    """
    if not tenant_id:
        raise ValueError(
            "get_patient_action_items: tenant_id is required — "
            "refusing to operate without tenant scope (HIPAA multi-tenant isolation)"
        )

    # Verify patient belongs to tenant
    try:
        with raf_cursor() as cur:
            cur.execute(
                "SELECT id FROM patients WHERE id = %s AND tenant_id = %s AND is_active = 1 LIMIT 1",
                (patient_id, tenant_id),
            )
            if not cur.fetchone():
                logger.warning(
                    "get_patient_action_items: patient %s not found in tenant %s",
                    patient_id, tenant_id,
                )
                return []
    except Exception as exc:
        logger.error("get_patient_action_items: patient lookup failed: %s", exc)
        return []

    action_items: list[dict[str, Any]] = []

    # ---- Action 1: HCCs needing recapture (open gaps) ----
    recapture_exists = _table_exists("recapture_gaps")
    if recapture_exists:
        try:
            with raf_cursor() as cur:
                cur.execute(
                    """
                    SELECT hcc_code,
                           icd10_code,
                           prior_year,
                           COALESCE(revenue_impact, %s) AS revenue_impact
                    FROM   recapture_gaps
                    WHERE  patient_id = %s
                      AND  tenant_id  = %s
                      AND  status     = 'open'
                    ORDER BY revenue_impact DESC
                    """,
                    (_DEFAULT_REVENUE_PER_GAP, patient_id, tenant_id),
                )
                for row in cur.fetchall():
                    action_items.append({
                        "action_type": "recapture_hcc",
                        "hcc_code": row["hcc_code"],
                        "icd10_codes": [row["icd10_code"]] if row["icd10_code"] else [],
                        "description": (
                            f"HCC {row['hcc_code']} was documented in {row['prior_year']} "
                            f"but has not yet been recaptured this year. "
                            f"Estimated revenue impact: ${float(row['revenue_impact'] or 0):,.2f}."
                        ),
                        "meat_status": None,
                        "source": "recapture_gap",
                        "priority": 1,
                    })
        except Exception as exc:
            logger.debug("get_patient_action_items: recapture_gaps query failed: %s", exc)
    else:
        # Derive from raf_patient_hcc prior year
        current_year = date.today().year
        prior_year = current_year - 1
        try:
            with raf_cursor() as cur:
                cur.execute(
                    """
                    SELECT ph.hcc_code,
                           ph.icd10_codes,
                           %s AS prior_year
                    FROM   raf_patient_hcc ph
                    WHERE  ph.patient_id       = %s
                      AND  ph.tenant_id        = %s
                      AND  ph.measurement_year = %s
                      AND  NOT EXISTS (
                           SELECT 1
                           FROM   raf_patient_hcc cy
                           WHERE  cy.patient_id       = ph.patient_id
                             AND  cy.hcc_code         = ph.hcc_code
                             AND  cy.measurement_year = %s
                             AND  cy.tenant_id        = %s
                      )
                    ORDER BY ph.hcc_code
                    """,
                    (prior_year, patient_id, tenant_id, prior_year, current_year, tenant_id),
                )
                for row in cur.fetchall():
                    icd_codes = _parse_icd10_codes(row["icd10_codes"])
                    action_items.append({
                        "action_type": "recapture_hcc",
                        "hcc_code": row["hcc_code"],
                        "icd10_codes": icd_codes,
                        "description": (
                            f"HCC {row['hcc_code']} was documented in {row['prior_year']} "
                            "but has not yet been recaptured this year."
                        ),
                        "meat_status": None,
                        "source": "recapture_gap",
                        "priority": 1,
                    })
        except Exception as exc:
            logger.debug("get_patient_action_items: derived recapture query failed: %s", exc)

    # ---- Action 2: HCCs with incomplete MEAT criteria ----
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT hcc_code,
                       icd10_codes,
                       meat_status
                FROM   raf_patient_hcc
                WHERE  patient_id        = %s
                  AND  tenant_id         = %s
                  AND  meat_status       IN ('missing', 'partial')
                ORDER BY hcc_code
                """,
                (patient_id, tenant_id),
            )
            for row in cur.fetchall():
                icd_codes = _parse_icd10_codes(row["icd10_codes"])
                action_items.append({
                    "action_type": "incomplete_meat",
                    "hcc_code": row["hcc_code"],
                    "icd10_codes": icd_codes,
                    "description": (
                        f"HCC {row['hcc_code']} has MEAT status '{row['meat_status']}'. "
                        "Ensure Monitoring, Evaluation, Assessment, and Treatment are "
                        "documented in the encounter note."
                    ),
                    "meat_status": row["meat_status"],
                    "source": "meat",
                    "priority": 2,
                })
    except Exception as exc:
        logger.debug("get_patient_action_items: MEAT query failed: %s", exc)

    # ---- Action 3: Missing encounters (no encounter in current calendar year) ----
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT MAX(encounter_date) AS last_encounter
                FROM   normalized_encounters
                WHERE  patient_id = %s
                  AND  tenant_id  = %s
                """,
                (patient_id, tenant_id),
            )
            row = cur.fetchone()
            last_enc = row["last_encounter"] if row else None
            current_year = date.today().year
            has_current_year_visit = (
                last_enc is not None
                and (
                    (isinstance(last_enc, (date, datetime)) and last_enc.year == current_year)
                    or (isinstance(last_enc, str) and last_enc.startswith(str(current_year)))
                )
            )
            if not has_current_year_visit:
                action_items.append({
                    "action_type": "missing_encounter",
                    "hcc_code": None,
                    "icd10_codes": [],
                    "description": (
                        f"Patient has no encounter recorded in {current_year}. "
                        "Schedule a visit to allow HCC documentation and RAF scoring."
                    ),
                    "meat_status": None,
                    "source": "historical",
                    "priority": 3,
                })
    except Exception as exc:
        logger.debug("get_patient_action_items: encounter check failed: %s", exc)

    # ---- Action 4: Suggested diagnoses from NLP / lab suspects ----
    suspects_exists = _table_exists("suspects")
    if suspects_exists:
        try:
            with raf_cursor() as cur:
                cur.execute(
                    """
                    SELECT hcc_code,
                           icd10_code,
                           source,
                           confidence,
                           description
                    FROM   suspects
                    WHERE  patient_id = %s
                      AND  tenant_id  = %s
                      AND  status     = 'open'
                    ORDER BY confidence DESC
                    """,
                    (patient_id, tenant_id),
                )
                for row in cur.fetchall():
                    action_items.append({
                        "action_type": "suggested_diagnosis",
                        "hcc_code": row["hcc_code"],
                        "icd10_codes": [row["icd10_code"]] if row.get("icd10_code") else [],
                        "description": (
                            f"Suspected HCC {row['hcc_code']} from {row['source']} analysis "
                            f"(confidence: {float(row['confidence'] or 0):.0%}). "
                            + (row.get("description") or "Review and document if clinically appropriate.")
                        ),
                        "meat_status": None,
                        "source": row["source"],
                        "priority": 4,
                    })
        except Exception as exc:
            logger.debug("get_patient_action_items: suspects query failed: %s", exc)

    # ---- Also pull from normalized_diagnoses historical data ----
    # Find ICD-10 codes that mapped to HCCs historically but are not in the
    # current year's raf_patient_hcc — these are soft "consider re-documenting" hints.
    try:
        current_year = date.today().year
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT nd.icd10_code,
                       nd.hcc_code,
                       nd.description
                FROM   normalized_diagnoses nd
                JOIN   normalized_encounters ne ON ne.encounter_id = nd.encounter_id
                WHERE  nd.patient_id  = %s
                  AND  nd.tenant_id   = %s
                  AND  nd.hcc_code    IS NOT NULL
                  AND  nd.status      = 'active'
                  AND  ne.encounter_date < DATE_FORMAT(CURDATE(), '%Y-01-01')
                  AND  NOT EXISTS (
                       SELECT 1
                       FROM   raf_patient_hcc rph
                       WHERE  rph.patient_id       = nd.patient_id
                         AND  rph.hcc_code         = nd.hcc_code
                         AND  rph.measurement_year = %s
                         AND  rph.tenant_id        = %s
                  )
                ORDER BY nd.hcc_code
                LIMIT 10
                """,
                (patient_id, tenant_id, current_year, tenant_id),
            )
            for row in cur.fetchall():
                # Only add if not already covered by a recapture or suspect action.
                already_covered = any(
                    a["hcc_code"] == row["hcc_code"] and a["action_type"] in ("recapture_hcc", "suggested_diagnosis")
                    for a in action_items
                )
                if not already_covered:
                    action_items.append({
                        "action_type": "suggested_diagnosis",
                        "hcc_code": row["hcc_code"],
                        "icd10_codes": [row["icd10_code"]] if row["icd10_code"] else [],
                        "description": (
                            f"HCC {row['hcc_code']} ({row.get('description') or row['icd10_code']}) "
                            "documented in a prior year encounter. Consider re-evaluating and "
                            "documenting if the condition is still active."
                        ),
                        "meat_status": None,
                        "source": "historical",
                        "priority": 5,
                    })
    except Exception as exc:
        logger.debug("get_patient_action_items: historical diagnoses query failed: %s", exc)

    # Sort by priority then hcc_code (None last).
    action_items.sort(key=lambda x: (x["priority"], x["hcc_code"] or 9999))
    return action_items


# ---------------------------------------------------------------------------
# 3. get_worklist_summary
# ---------------------------------------------------------------------------


@tenant_cached("worklist", ttl=TTL_WORKLIST)
def get_worklist_summary(tenant_id: str) -> dict[str, Any]:
    """
    Return aggregate worklist statistics for a tenant.

    Response keys:
      total_patients_needing_attention  — patients with at least one open gap
      total_raf_impact_at_risk          — sum of raf_coefficient across all open gaps
      total_revenue_at_risk             — sum of revenue_impact across all open gaps
      top_conditions                    — list of top 10 HCC codes by frequency of
                                         open gaps, each with:
                                           hcc_code, gap_count, avg_revenue_impact
      provider_performance              — list of provider summaries, each with:
                                           provider_npi, patients_seen_ytd,
                                           open_gap_count, recapture_rate
      generated_at                      — ISO-8601 timestamp

    Parameters
    ----------
    tenant_id:
        Tenant scope — mandatory for HIPAA isolation.
    """
    if not tenant_id:
        raise ValueError(
            "get_worklist_summary: tenant_id is required — "
            "refusing to operate without tenant scope (HIPAA multi-tenant isolation)"
        )

    current_year = date.today().year
    prior_year = current_year - 1

    summary: dict[str, Any] = {
        "total_patients_needing_attention": 0,
        "total_raf_impact_at_risk": 0.0,
        "total_revenue_at_risk": 0.0,
        "top_conditions": [],
        "provider_performance": [],
        "generated_at": datetime.now(timezone.utc).isoformat() + "Z",
    }

    recapture_exists = _table_exists("recapture_gaps")

    # ---- Patients needing attention + revenue totals ----
    if recapture_exists:
        try:
            with raf_cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(DISTINCT rg.patient_id)    AS patients_with_gaps,
                           COALESCE(SUM(rg.revenue_impact), 0) AS total_revenue
                    FROM   recapture_gaps rg
                    JOIN   patients p ON p.id = rg.patient_id
                    WHERE  rg.tenant_id    = %s
                      AND  rg.status       = 'open'
                      AND  rg.current_year = %s
                      AND  p.is_active     = 1
                      AND  p.tenant_id     = %s
                    """,
                    (tenant_id, current_year, tenant_id),
                )
                row = cur.fetchone()
                if row:
                    summary["total_patients_needing_attention"] = int(row["patients_with_gaps"] or 0)
                    summary["total_revenue_at_risk"] = float(row["total_revenue"] or 0)
        except Exception as exc:
            logger.debug("get_worklist_summary: recapture totals query failed: %s", exc)
    else:
        # Derive from raf_patient_hcc
        try:
            with raf_cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(DISTINCT ph.patient_id) AS patients_with_gaps,
                           COALESCE(SUM(ph.raf_coefficient * %s), 0) AS total_revenue
                    FROM   raf_patient_hcc ph
                    JOIN   patients p ON p.id = ph.patient_id
                    WHERE  ph.tenant_id        = %s
                      AND  ph.measurement_year = %s
                      AND  p.is_active         = 1
                      AND  p.tenant_id         = %s
                      AND  NOT EXISTS (
                           SELECT 1
                           FROM   raf_patient_hcc cy
                           WHERE  cy.patient_id       = ph.patient_id
                             AND  cy.hcc_code         = ph.hcc_code
                             AND  cy.measurement_year = %s
                             AND  cy.tenant_id        = %s
                      )
                    """,
                    (_DEFAULT_REVENUE_PER_GAP, tenant_id, prior_year, tenant_id, current_year, tenant_id),
                )
                row = cur.fetchone()
                if row:
                    summary["total_patients_needing_attention"] = int(row["patients_with_gaps"] or 0)
                    summary["total_revenue_at_risk"] = float(row["total_revenue"] or 0)
        except Exception as exc:
            logger.debug("get_worklist_summary: derived totals query failed: %s", exc)

    # ---- Total RAF impact at risk ----
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT COALESCE(SUM(ph.raf_coefficient), 0) AS total_coeff
                FROM   raf_patient_hcc ph
                JOIN   patients p ON p.id = ph.patient_id
                WHERE  ph.tenant_id        = %s
                  AND  ph.measurement_year = %s
                  AND  p.is_active         = 1
                  AND  p.tenant_id         = %s
                """,
                (tenant_id, prior_year, tenant_id),
            )
            row = cur.fetchone()
            if row:
                summary["total_raf_impact_at_risk"] = round(float(row["total_coeff"] or 0), 4)
    except Exception as exc:
        logger.debug("get_worklist_summary: RAF coefficient query failed: %s", exc)

    # ---- Top 10 conditions by gap frequency ----
    if recapture_exists:
        try:
            with raf_cursor() as cur:
                cur.execute(
                    """
                    SELECT rg.hcc_code,
                           COUNT(*)                              AS gap_count,
                           AVG(COALESCE(rg.revenue_impact, %s)) AS avg_revenue_impact
                    FROM   recapture_gaps rg
                    JOIN   patients p ON p.id = rg.patient_id
                    WHERE  rg.tenant_id    = %s
                      AND  rg.status       = 'open'
                      AND  rg.current_year = %s
                      AND  p.is_active     = 1
                      AND  p.tenant_id     = %s
                    GROUP BY rg.hcc_code
                    ORDER BY gap_count DESC, avg_revenue_impact DESC
                    LIMIT 10
                    """,
                    (_DEFAULT_REVENUE_PER_GAP, tenant_id, current_year, tenant_id),
                )
                summary["top_conditions"] = [
                    {
                        "hcc_code": row["hcc_code"],
                        "gap_count": int(row["gap_count"]),
                        "avg_revenue_impact": round(float(row["avg_revenue_impact"] or 0), 2),
                    }
                    for row in cur.fetchall()
                ]
        except Exception as exc:
            logger.debug("get_worklist_summary: top conditions query failed: %s", exc)
    else:
        try:
            with raf_cursor() as cur:
                cur.execute(
                    """
                    SELECT ph.hcc_code,
                           COUNT(DISTINCT ph.patient_id)         AS gap_count,
                           AVG(ph.raf_coefficient * %s)          AS avg_revenue_impact
                    FROM   raf_patient_hcc ph
                    JOIN   patients p ON p.id = ph.patient_id
                    WHERE  ph.tenant_id        = %s
                      AND  ph.measurement_year = %s
                      AND  p.is_active         = 1
                      AND  p.tenant_id         = %s
                      AND  NOT EXISTS (
                           SELECT 1
                           FROM   raf_patient_hcc cy
                           WHERE  cy.patient_id       = ph.patient_id
                             AND  cy.hcc_code         = ph.hcc_code
                             AND  cy.measurement_year = %s
                             AND  cy.tenant_id        = %s
                      )
                    GROUP BY ph.hcc_code
                    ORDER BY gap_count DESC, avg_revenue_impact DESC
                    LIMIT 10
                    """,
                    (_DEFAULT_REVENUE_PER_GAP, tenant_id, prior_year, tenant_id, current_year, tenant_id),
                )
                summary["top_conditions"] = [
                    {
                        "hcc_code": row["hcc_code"],
                        "gap_count": int(row["gap_count"]),
                        "avg_revenue_impact": round(float(row["avg_revenue_impact"] or 0), 2),
                    }
                    for row in cur.fetchall()
                ]
        except Exception as exc:
            logger.debug("get_worklist_summary: derived top conditions query failed: %s", exc)

    # ---- Provider performance ----
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT ne.provider_npi,
                       COUNT(DISTINCT ne.patient_id) AS patients_seen_ytd
                FROM   normalized_encounters ne
                JOIN   patients p ON p.id = ne.patient_id
                WHERE  ne.tenant_id          = %s
                  AND  p.is_active           = 1
                  AND  p.tenant_id           = %s
                  AND  YEAR(ne.encounter_date) = %s
                GROUP BY ne.provider_npi
                ORDER BY patients_seen_ytd DESC
                LIMIT 20
                """,
                (tenant_id, tenant_id, current_year),
            )
            provider_rows = cur.fetchall()
    except Exception as exc:
        logger.debug("get_worklist_summary: provider performance query failed: %s", exc)
        provider_rows = []

    if provider_rows and recapture_exists:
        npi_list = [r["provider_npi"] for r in provider_rows if r["provider_npi"]]
        if npi_list:
            npi_placeholders = ", ".join(["%s"] * len(npi_list))
            gap_count_map: dict[str, int] = {}
            recaptured_map: dict[str, int] = {}
            try:
                with raf_cursor() as cur:
                    cur.execute(
                        f"""
                        SELECT provider_npi,
                               SUM(CASE WHEN status = 'open'        THEN 1 ELSE 0 END) AS open_gaps,
                               SUM(CASE WHEN status = 'recaptured'  THEN 1 ELSE 0 END) AS recaptured
                        FROM   recapture_gaps
                        WHERE  tenant_id    = %s
                          AND  current_year = %s
                          AND  provider_npi IN ({npi_placeholders})
                        GROUP BY provider_npi
                        """,
                        [tenant_id, current_year] + npi_list,
                    )
                    for row in cur.fetchall():
                        npi = row["provider_npi"]
                        gap_count_map[npi] = int(row["open_gaps"] or 0)
                        recaptured_map[npi] = int(row["recaptured"] or 0)
            except Exception as exc:
                logger.debug("get_worklist_summary: provider gap counts failed: %s", exc)

            for prow in provider_rows:
                npi = prow["provider_npi"]
                open_gaps = gap_count_map.get(npi, 0)
                recaptured = recaptured_map.get(npi, 0)
                total = open_gaps + recaptured
                recapture_rate = round(recaptured / total, 4) if total > 0 else None
                summary["provider_performance"].append({
                    "provider_npi": npi,
                    "patients_seen_ytd": int(prow["patients_seen_ytd"]),
                    "open_gap_count": open_gaps,
                    "recapture_rate": recapture_rate,
                })
    else:
        summary["provider_performance"] = [
            {
                "provider_npi": row["provider_npi"],
                "patients_seen_ytd": int(row["patients_seen_ytd"]),
                "open_gap_count": None,
                "recapture_rate": None,
            }
            for row in provider_rows
        ]

    return summary
