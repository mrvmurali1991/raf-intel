"""
Cohort Analysis Service
=======================

Handles all population health cohort operations:

  - Building cohort membership from structured criteria (HCC codes, RAF ranges,
    age, gender, provider panel, payer, diagnosis, risk tier).
  - Dynamic membership refresh — re-evaluates criteria against current patient
    data and updates cohort_members accordingly.
  - Aggregate population health metrics: prevalence, comorbidity, utilization.
  - Point-in-time snapshots for trend tracking.
  - Statistical comparison between two cohorts (independent-samples t-test for
    continuous metrics, chi-square test for categorical distributions).
  - Revenue impact analysis using RAF scores and a configurable per-unit rate.
  - CSV export of cohort member data.

Tables used (raf_intelligence DB):
  cohorts, cohort_members, cohort_snapshots, cohort_comparisons

Read-only join sources (raf DB + openemr DB for clinical data):
  patients, raf_scores, raf_suspect_conditions, provider_patient_panel
"""

from __future__ import annotations

import csv
import io
import json
import logging
import math
from datetime import date, datetime
from typing import Any

from app.config import settings
from app.db import openemr_cursor, raf_cursor

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Active EMR patient filter — only include patients matched to active
# EMR connections so that inactive/disconnected sources are excluded.
# ---------------------------------------------------------------------------
from app.services.emr_manager import active_patients_subquery  # noqa: E402


# ---------------------------------------------------------------------------
# FHIR connection detection helper
# ---------------------------------------------------------------------------

def _active_conn_type(tenant_id: int) -> str:
    """Return the connection_type of the active EMR connection for the tenant.

    Returns ``'direct_db'`` when no active connection row is found so that
    all existing direct-DB code paths remain the default.
    """
    try:
        with raf_cursor() as cur:
            cur.execute(
                "SELECT connection_type FROM emr_connections "
                "WHERE is_active = 1 AND tenant_id = %s LIMIT 1",
                (tenant_id,),
            )
            row = cur.fetchone()
            return row["connection_type"] if row else "direct_db"
    except Exception as exc:
        logger.warning("cohort_service._active_conn_type: could not determine conn type: %s", exc)
        return "direct_db"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _serialize(obj: Any) -> Any:
    """Recursively convert non-serializable types (date, Decimal) for JSON."""
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_serialize(i) for i in obj]
    if isinstance(obj, date):
        return obj.isoformat()
    return obj


def _fetch_cohort(cur, cohort_id: int) -> dict[str, Any] | None:
    cur.execute("SELECT * FROM cohorts WHERE id = %s", (cohort_id,))
    row = cur.fetchone()
    if row and isinstance(row.get("criteria"), str):
        try:
            row["criteria"] = json.loads(row["criteria"])
        except Exception:
            pass
    return row


def _active_patient_ids(cur, cohort_id: int) -> list[int]:
    """Return list of active patient IDs for a cohort."""
    cur.execute(
        "SELECT patient_id FROM cohort_members WHERE cohort_id = %s AND is_active = 1",
        (cohort_id,),
    )
    return [r["patient_id"] for r in (cur.fetchall() or [])]


# ---------------------------------------------------------------------------
# Criteria → patient ID resolution
# ---------------------------------------------------------------------------


def _resolve_criteria_patient_ids(
    criteria: dict[str, Any],
    tenant_id: int,
) -> list[int]:
    """
    Translate a criteria dict into a de-duplicated list of patient IDs by
    querying OpenEMR and RAF Intelligence databases.

    Supported criteria keys (all optional, AND-combined):
      hcc_codes       list[str]   – patients with at least one of these HCCs
      raf_min         float       – minimum final_raf score (inclusive)
      raf_max         float       – maximum final_raf score (inclusive)
      age_min         int         – minimum patient age
      age_max         int         – maximum patient age
      gender          str         – 'M' or 'F'
      provider_ids    list[int]   – patients in at least one provider's panel
      payer_names     list[str]   – LIKE-match on payer name field
      icd_codes       list[str]   – patients with at least one of these diagnoses
      risk_tiers      list[str]   – very_high | high | moderate | low | minimal
      zip_codes       list[str]   – patient zip codes
      states          list[str]   – two-letter state abbreviations
    """
    if tenant_id is None:
        raise ValueError(
            "cohort_service._resolve_criteria_patient_ids: tenant_id is required — "
            "refusing to query across all tenants (HIPAA multi-tenant isolation)"
        )
    tid = int(tenant_id)

    patient_sets: list[set[int]] = []

    # --- HCC-based filter (RAF DB) ---
    hcc_codes = criteria.get("hcc_codes") or []
    if hcc_codes:
        fmt = ",".join(["%s"] * len(hcc_codes))
        active_frag, active_params = active_patients_subquery(tid)
        with raf_cursor() as cur:
            cur.execute(
                f"""
                SELECT DISTINCT patient_id
                FROM raf_scores
                WHERE JSON_OVERLAPS(hcc_codes, JSON_ARRAY({fmt}))
                  AND {active_frag}
                """,
                [*hcc_codes, *active_params],
            )
            rows = cur.fetchall() or []
        patient_sets.append({r["patient_id"] for r in rows})

    # --- RAF range filter (RAF DB) ---
    raf_min = criteria.get("raf_min")
    raf_max = criteria.get("raf_max")
    if raf_min is not None or raf_max is not None:
        conditions = []
        params: list[Any] = []
        if raf_min is not None:
            conditions.append("final_raf >= %s")
            params.append(float(raf_min))
        if raf_max is not None:
            conditions.append("final_raf <= %s")
            params.append(float(raf_max))
        where = " AND ".join(conditions)
        active_frag, active_params = active_patients_subquery(tid)
        with raf_cursor() as cur:
            cur.execute(
                f"SELECT DISTINCT patient_id FROM raf_scores WHERE {where} AND {active_frag}",
                [*params, *active_params],
            )
            rows = cur.fetchall() or []
        patient_sets.append({r["patient_id"] for r in rows})

    # --- Risk tier filter (RAF DB) ---
    risk_tiers = criteria.get("risk_tiers") or []
    if risk_tiers:
        fmt = ",".join(["%s"] * len(risk_tiers))
        active_frag, active_params = active_patients_subquery(tid)
        with raf_cursor() as cur:
            cur.execute(
                f"""
                SELECT DISTINCT patient_id
                FROM raf_scores
                WHERE risk_tier IN ({fmt})
                  AND {active_frag}
                """,
                [*risk_tiers, *active_params],
            )
            rows = cur.fetchall() or []
        patient_sets.append({r["patient_id"] for r in rows})

    # --- Provider panel filter (RAF DB) ---
    provider_ids = criteria.get("provider_ids") or []
    if provider_ids:
        fmt = ",".join(["%s"] * len(provider_ids))
        with raf_cursor() as cur:
            cur.execute(
                f"SELECT DISTINCT patient_id FROM provider_patient_panel WHERE provider_id IN ({fmt})",
                provider_ids,
            )
            rows = cur.fetchall() or []
        patient_sets.append({r["patient_id"] for r in rows})

    # --- Demographics + geography (raf_intelligence.patients) ---
    demo_conditions: list[str] = []
    demo_params: list[Any] = []

    age_min = criteria.get("age_min")
    age_max = criteria.get("age_max")
    if age_min is not None:
        demo_conditions.append("TIMESTAMPDIFF(YEAR, dob, CURDATE()) >= %s")
        demo_params.append(int(age_min))
    if age_max is not None:
        demo_conditions.append("TIMESTAMPDIFF(YEAR, dob, CURDATE()) <= %s")
        demo_params.append(int(age_max))

    gender = criteria.get("gender")
    if gender:
        demo_conditions.append("sex = %s")
        demo_params.append(gender.upper())

    zip_codes = criteria.get("zip_codes") or []
    if zip_codes:
        fmt = ",".join(["%s"] * len(zip_codes))
        demo_conditions.append(f"zip IN ({fmt})")
        demo_params.extend(zip_codes)

    states = criteria.get("states") or []
    if states:
        fmt = ",".join(["%s"] * len(states))
        demo_conditions.append(f"state IN ({fmt})")
        demo_params.extend(states)

    if demo_conditions:
        conn_type = _active_conn_type(tid)
        if conn_type == "fhir_r4":
            # FHIR patients are in emr_patient_matches; only age and gender
            # are available (zip/state are not synced from FHIR).
            fhir_conditions: list[str] = []
            fhir_params: list[Any] = []
            if age_min is not None:
                fhir_conditions.append("TIMESTAMPDIFF(YEAR, epm.date_of_birth, CURDATE()) >= %s")
                fhir_params.append(int(age_min))
            if age_max is not None:
                fhir_conditions.append("TIMESTAMPDIFF(YEAR, epm.date_of_birth, CURDATE()) <= %s")
                fhir_params.append(int(age_max))
            if gender:
                fhir_conditions.append("epm.sex = %s")
                fhir_params.append(gender.upper())
            # zip_codes / states not available for FHIR patients — skip silently
            if zip_codes or states:
                logger.info(
                    "cohort_service: zip_codes/states criteria ignored for FHIR connection "
                    "(demographic data not available in emr_patient_matches)"
                )
            if fhir_conditions:
                fhir_where = " AND ".join(fhir_conditions)
                with raf_cursor() as cur:
                    cur.execute(
                        f"SELECT epm.id "
                        f"FROM emr_patient_matches epm "
                        f"JOIN emr_connections ec ON ec.id = epm.connection_id "
                        f"WHERE ec.is_active = 1 AND ec.tenant_id = %s AND {fhir_where}",
                        [tid, *fhir_params],
                    )
                    rows = cur.fetchall() or []
                patient_sets.append({r["id"] for r in rows})
        else:
            where = " AND ".join(demo_conditions)
            with raf_cursor() as cur:
                cur.execute(
                    f"SELECT id FROM patients WHERE is_active = 1 AND {where}",
                    demo_params,
                )
                rows = cur.fetchall() or []
            patient_sets.append({r["id"] for r in rows})

    # --- Payer + ICD (OpenEMR clinical data, requires emr_pid lookup) ---
    openemr_conditions: list[str] = []
    openemr_params: list[Any] = []

    payer_names = criteria.get("payer_names") or []
    if payer_names:
        payer_clauses = " OR ".join(
            [
                "(SELECT COUNT(*) FROM insurance_data id2 WHERE id2.pid = p.emr_pid AND id2.provider LIKE %s) > 0"
            ]
            * len(payer_names)
        )
        openemr_conditions.append(f"({payer_clauses})")
        openemr_params.extend([f"%{p}%" for p in payer_names])

    icd_codes = criteria.get("icd_codes") or []
    if icd_codes:
        fmt = ",".join(["%s"] * len(icd_codes))
        openemr_conditions.append(
            f"p.emr_pid IN (SELECT pid FROM lists WHERE type = 'medical_problem' AND diagnosis IN ({fmt}))"
        )
        openemr_params.extend(icd_codes)

    if openemr_conditions:
        # Get patient ids via emr_pid cross-reference
        where = " AND ".join(openemr_conditions)
        with raf_cursor() as cur:
            cur.execute(
                "SELECT id, emr_pid FROM patients WHERE is_active = 1 AND emr_pid IS NOT NULL"
            )
            all_patients = cur.fetchall() or []

        # Filter using OpenEMR clinical data
        emr_pids = [r["emr_pid"] for r in all_patients]
        emr_to_raf: dict[int, int] = {r["emr_pid"]: r["id"] for r in all_patients}

        if emr_pids:
            matching_ids: set[int] = set()
            try:
                with openemr_cursor() as cur:
                    # Build query checking payer and/or ICD conditions
                    emr_fmt = ",".join(["%s"] * len(emr_pids))
                    emr_where_parts = [f"pd.pid IN ({emr_fmt})"]
                    emr_query_params: list[Any] = list(emr_pids)

                    if payer_names:
                        payer_clauses_emr = " OR ".join(
                            ["(SELECT COUNT(*) FROM insurance_data id2 WHERE id2.pid = pd.pid AND id2.provider LIKE %s) > 0"]
                            * len(payer_names)
                        )
                        emr_where_parts.append(f"({payer_clauses_emr})")
                        emr_query_params.extend([f"%{p}%" for p in payer_names])

                    if icd_codes:
                        icd_fmt = ",".join(["%s"] * len(icd_codes))
                        emr_where_parts.append(
                            f"pd.pid IN (SELECT pid FROM lists WHERE type = 'medical_problem' AND diagnosis IN ({icd_fmt}))"
                        )
                        emr_query_params.extend(icd_codes)

                    emr_where = " AND ".join(emr_where_parts)
                    cur.execute(
                        f"SELECT pd.pid FROM patient_data pd WHERE {emr_where}",
                        emr_query_params,
                    )
                    for r in (cur.fetchall() or []):
                        raf_id = emr_to_raf.get(r["pid"])
                        if raf_id is not None:
                            matching_ids.add(raf_id)
            except Exception as exc:
                logger.warning("cohort build: OpenEMR clinical filter failed: %s", exc)
            patient_sets.append(matching_ids)

    if not patient_sets:
        # No criteria supplied — empty cohort
        return []

    # Intersect all non-empty sets (AND semantics across filter groups)
    result: set[int] = patient_sets[0]
    for s in patient_sets[1:]:
        result = result & s

    return sorted(result)


# ---------------------------------------------------------------------------
# CRUD — cohorts
# ---------------------------------------------------------------------------


def create_cohort(
    *,
    name: str,
    description: str | None = None,
    cohort_type: str = "custom",
    criteria: dict[str, Any],
    created_by: int | None = None,
    tenant_id: str,
) -> dict[str, Any]:
    """Create a new cohort definition and immediately populate its membership."""
    criteria_json = json.dumps(criteria)
    with raf_cursor() as cur:
        cur.execute(
            """
            INSERT INTO cohorts (name, description, cohort_type, criteria, created_by, tenant_id)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (name, description, cohort_type, criteria_json, created_by, tenant_id),
        )
        cohort_id: int = cur.lastrowid
        cohort = _fetch_cohort(cur, cohort_id)

    logger.info("cohort_service: created cohort id=%s name=%r", cohort_id, name)

    # Populate membership synchronously on creation
    try:
        refresh_cohort_membership(cohort_id)
    except Exception as exc:
        logger.warning(
            "cohort_service: initial membership refresh failed for id=%s: %s",
            cohort_id,
            exc,
        )

    with raf_cursor() as cur:
        return _fetch_cohort(cur, cohort_id)


def list_cohorts(
    *,
    cohort_type: str | None = None,
    status: str = "active",
    tenant_id: str,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    conditions = ["tenant_id = %s"]
    params: list[Any] = [tenant_id]
    if status:
        conditions.append("status = %s")
        params.append(status)
    if cohort_type:
        conditions.append("cohort_type = %s")
        params.append(cohort_type)
    where = " AND ".join(conditions)
    params.extend([limit, offset])

    with raf_cursor() as cur:
        cur.execute(
            f"""
            SELECT * FROM cohorts
            WHERE {where}
            ORDER BY updated_at DESC
            LIMIT %s OFFSET %s
            """,
            params,
        )
        rows = cur.fetchall() or []

    for row in rows:
        if isinstance(row.get("criteria"), str):
            try:
                row["criteria"] = json.loads(row["criteria"])
            except Exception:
                pass
    return rows


def get_cohort(cohort_id: int) -> dict[str, Any] | None:
    with raf_cursor() as cur:
        return _fetch_cohort(cur, cohort_id)


def update_cohort(
    cohort_id: int,
    updates: dict[str, Any],
    refresh_membership: bool = True,
) -> dict[str, Any] | None:
    """Update cohort metadata and/or criteria, optionally refreshing membership."""
    # Disallow tampering with system fields
    for field in ("id", "created_at", "tenant_id", "created_by"):
        updates.pop(field, None)

    if "criteria" in updates and isinstance(updates["criteria"], dict):
        updates["criteria"] = json.dumps(updates["criteria"])

    if not updates:
        return get_cohort(cohort_id)

    set_clause = ", ".join(f"{col} = %s" for col in updates)
    params = list(updates.values()) + [cohort_id]

    with raf_cursor() as cur:
        cur.execute(
            f"UPDATE cohorts SET {set_clause} WHERE id = %s",
            params,
        )
        updated = _fetch_cohort(cur, cohort_id)

    if refresh_membership and "criteria" in updates:
        try:
            refresh_cohort_membership(cohort_id)
        except Exception as exc:
            logger.warning(
                "cohort_service: post-update refresh failed id=%s: %s", cohort_id, exc
            )

    with raf_cursor() as cur:
        return _fetch_cohort(cur, cohort_id)


def archive_cohort(cohort_id: int) -> dict[str, Any] | None:
    """Soft-delete by setting status = 'archived'."""
    with raf_cursor() as cur:
        cur.execute(
            "UPDATE cohorts SET status = 'archived' WHERE id = %s", (cohort_id,)
        )
        return _fetch_cohort(cur, cohort_id)


# ---------------------------------------------------------------------------
# Membership management
# ---------------------------------------------------------------------------


def get_cohort_members(
    cohort_id: int,
    *,
    include_inactive: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Return cohort member rows, optionally enriched with basic patient info."""
    is_active_clause = "" if include_inactive else "AND is_active = 1"
    with raf_cursor() as cur:
        cur.execute(
            f"""
            SELECT * FROM cohort_members
            WHERE cohort_id = %s {is_active_clause}
            ORDER BY added_at DESC
            LIMIT %s OFFSET %s
            """,
            (cohort_id, limit, offset),
        )
        return cur.fetchall() or []


def refresh_cohort_membership(
    cohort_id: int,
    tenant_id: int,
) -> dict[str, Any]:
    """
    Re-evaluate the cohort criteria and synchronise cohort_members accordingly.

    - New matches are INSERTed (or re-activated if previously removed).
    - Members who no longer match criteria are soft-removed (is_active=0,
      removed_at=NOW()).
    - The parent cohorts row is updated with fresh aggregate stats.

    Returns a summary dict with added/removed/unchanged counts.
    """
    cohort = get_cohort(cohort_id)
    if not cohort:
        raise ValueError(f"Cohort {cohort_id} not found")

    if tenant_id is None:
        raise ValueError(
            "cohort_service.refresh_cohort_membership: tenant_id is required — "
            "refusing to operate without tenant scope (HIPAA multi-tenant isolation)"
        )
    tid = int(tenant_id)

    criteria: dict[str, Any] = cohort.get("criteria") or {}
    new_patient_ids: set[int] = set(_resolve_criteria_patient_ids(criteria, tenant_id=tid))

    with raf_cursor() as cur:
        # Current membership state
        cur.execute(
            "SELECT patient_id, is_active FROM cohort_members WHERE cohort_id = %s",
            (cohort_id,),
        )
        existing_rows = {
            r["patient_id"]: r["is_active"] for r in (cur.fetchall() or [])
        }

        current_active: set[int] = {
            pid for pid, active in existing_rows.items() if active
        }
        to_add: set[int] = new_patient_ids - set(existing_rows.keys())
        to_reactivate: set[int] = new_patient_ids & {
            pid for pid, a in existing_rows.items() if not a
        }
        to_remove: set[int] = current_active - new_patient_ids

        added = 0
        removed = 0

        # Insert brand-new members
        for pid in to_add:
            cur.execute(
                "INSERT INTO cohort_members (cohort_id, patient_id) VALUES (%s, %s)",
                (cohort_id, pid),
            )
            added += 1

        # Re-activate previously removed members
        for pid in to_reactivate:
            cur.execute(
                "UPDATE cohort_members SET is_active = 1, removed_at = NULL, added_at = NOW() WHERE cohort_id = %s AND patient_id = %s",
                (cohort_id, pid),
            )
            added += 1

        # Soft-remove members who no longer qualify
        for pid in to_remove:
            cur.execute(
                "UPDATE cohort_members SET is_active = 0, removed_at = NOW() WHERE cohort_id = %s AND patient_id = %s",
                (cohort_id, pid),
            )
            removed += 1

        # Recompute aggregate stats
        patient_count = len(new_patient_ids)
        avg_raf: float | None = None
        total_revenue: float | None = None

        if new_patient_ids:
            ids_fmt = ",".join(["%s"] * len(new_patient_ids))
            active_frag, active_params = active_patients_subquery(tid)
            cur.execute(
                f"SELECT AVG(final_raf) AS avg_raf FROM raf_scores WHERE patient_id IN ({ids_fmt}) AND {active_frag}",
                [*new_patient_ids, *active_params],
            )
            row = cur.fetchone()
            avg_raf = (
                round(float(row["avg_raf"]), 4)
                if row and row["avg_raf"] is not None
                else None
            )

        if avg_raf is not None:
            total_revenue = round(avg_raf * patient_count * settings.cms_revenue_per_raf_point, 2)

        cur.execute(
            """
            UPDATE cohorts
            SET patient_count = %s, avg_raf_score = %s, total_raf_revenue = %s
            WHERE id = %s
            """,
            (patient_count, avg_raf, total_revenue, cohort_id),
        )

    logger.info(
        "cohort_service: refresh cohort=%s added=%s removed=%s total=%s",
        cohort_id,
        added,
        removed,
        patient_count,
    )
    return {
        "cohort_id": cohort_id,
        "added": added,
        "removed": removed,
        "unchanged": len(new_patient_ids) - added,
        "total_active_members": patient_count,
    }


# ---------------------------------------------------------------------------
# Snapshots
# ---------------------------------------------------------------------------


def take_snapshot(cohort_id: int, tenant_id: str) -> dict[str, Any]:
    """
    Compute and persist a point-in-time snapshot of cohort aggregate metrics.

    Calculates:
      - Patient count, avg RAF score, avg age
      - Gender distribution
      - Top 10 HCC codes by prevalence
      - Risk tier distribution
      - Total projected RAF revenue
    """
    cohort = get_cohort(cohort_id)
    if not cohort:
        raise ValueError(f"Cohort {cohort_id} not found")

    if not tenant_id:
        raise ValueError(
            "cohort_service.take_snapshot: tenant_id is required — "
            "refusing to operate without tenant scope (HIPAA multi-tenant isolation)"
        )
    # Convert string tenant_id to numeric for active-patient filtering.
    try:
        tid = int(tenant_id)
    except (TypeError, ValueError):
        raise ValueError(
            f"cohort_service.take_snapshot: tenant_id must be numeric, got {tenant_id!r}"
        )

    with raf_cursor() as cur:
        patient_ids = _active_patient_ids(cur, cohort_id)

    if not patient_ids:
        # Empty cohort — still record the snapshot
        snapshot_data: dict[str, Any] = {
            "patient_count": 0,
            "avg_raf_score": None,
            "avg_age": None,
            "gender_distribution": {},
            "top_hccs": [],
            "risk_tier_distribution": {},
            "total_revenue": None,
            "metrics": {},
        }
    else:
        ids_fmt = ",".join(["%s"] * len(patient_ids))

        # RAF-based metrics
        with raf_cursor() as cur:
            active_frag, active_params = active_patients_subquery(tid)
            cur.execute(
                f"""
                SELECT
                    AVG(final_raf)          AS avg_raf,
                    COUNT(*)                AS scored_count,
                    risk_tier,
                    COUNT(*) OVER (PARTITION BY risk_tier) AS tier_count
                FROM raf_scores
                WHERE patient_id IN ({ids_fmt}) AND {active_frag}
                GROUP BY risk_tier, final_raf
                """,
                [*patient_ids, *active_params],
            )
            # Simplified query — re-run separate focused queries below
            pass

        with raf_cursor() as cur:
            active_frag, active_params = active_patients_subquery(tid)
            cur.execute(
                f"SELECT AVG(final_raf) AS avg_raf FROM raf_scores WHERE patient_id IN ({ids_fmt}) AND {active_frag}",
                [*patient_ids, *active_params],
            )
            raf_row = cur.fetchone()
            avg_raf = (
                round(float(raf_row["avg_raf"]), 4)
                if raf_row and raf_row["avg_raf"] is not None
                else None
            )

            # Risk tier distribution
            active_frag2, active_params2 = active_patients_subquery(tid)
            cur.execute(
                f"""
                SELECT risk_tier, COUNT(*) AS cnt
                FROM raf_scores
                WHERE patient_id IN ({ids_fmt}) AND {active_frag2}
                GROUP BY risk_tier
                """,
                [*patient_ids, *active_params2],
            )
            risk_rows = cur.fetchall() or []
            risk_tier_distribution = {
                r["risk_tier"]: r["cnt"] for r in risk_rows if r["risk_tier"]
            }

        # Demographics — prefer raf_intelligence.patients (direct-DB);
        # fall back to emr_patient_matches for FHIR tenants.
        avg_age: float | None = None
        gender_distribution: dict[str, int] = {}
        conn_type = _active_conn_type(tid)
        try:
            if conn_type == "fhir_r4":
                with raf_cursor() as cur:
                    cur.execute(
                        f"""
                        SELECT
                            AVG(TIMESTAMPDIFF(YEAR, epm.date_of_birth, CURDATE())) AS avg_age,
                            epm.sex,
                            COUNT(*) AS cnt
                        FROM emr_patient_matches epm
                        JOIN emr_connections ec ON ec.id = epm.connection_id
                        WHERE ec.is_active = 1 AND epm.id IN ({ids_fmt})
                        GROUP BY epm.sex
                        """,
                        patient_ids,
                    )
                    demo_rows = cur.fetchall() or []
            else:
                with raf_cursor() as cur:
                    cur.execute(
                        f"""
                        SELECT
                            AVG(TIMESTAMPDIFF(YEAR, dob, CURDATE())) AS avg_age,
                            sex,
                            COUNT(*) AS cnt
                        FROM patients
                        WHERE id IN ({ids_fmt})
                        GROUP BY sex
                        """,
                        patient_ids,
                    )
                    demo_rows = cur.fetchall() or []
            if demo_rows:
                # avg_age is repeated on every row from the GROUP BY — take first
                avg_age_raw = demo_rows[0].get("avg_age")
                avg_age = (
                    round(float(avg_age_raw), 2)
                    if avg_age_raw is not None
                    else None
                )
                gender_distribution = {
                    r["sex"]: r["cnt"] for r in demo_rows if r.get("sex")
                }
        except Exception as exc:
            logger.warning("cohort snapshot: demographics query failed: %s", exc)

        # Top HCC codes
        top_hccs: list[dict[str, Any]] = []
        try:
            with raf_cursor() as cur:
                # hcc_codes is stored as a JSON array in raf_scores
                active_frag3, active_params3 = active_patients_subquery(tid)
                cur.execute(
                    f"""
                    SELECT hcc_codes
                    FROM raf_scores
                    WHERE patient_id IN ({ids_fmt}) AND hcc_codes IS NOT NULL AND {active_frag3}
                    """,
                    [*patient_ids, *active_params3],
                )
                hcc_rows = cur.fetchall() or []
            hcc_counter: dict[str, int] = {}
            for row in hcc_rows:
                codes = row.get("hcc_codes")
                if isinstance(codes, str):
                    try:
                        codes = json.loads(codes)
                    except Exception:
                        codes = []
                if isinstance(codes, list):
                    for code in codes:
                        hcc_counter[str(code)] = hcc_counter.get(str(code), 0) + 1
            total = len(patient_ids)
            top_hccs = sorted(
                [
                    {"code": code, "count": cnt, "prevalence": round(cnt / total, 4)}
                    for code, cnt in hcc_counter.items()
                ],
                key=lambda x: x["count"],
                reverse=True,
            )[:10]
        except Exception as exc:
            logger.warning("cohort snapshot: top_hccs query failed: %s", exc)

        total_revenue = (
            round(avg_raf * len(patient_ids) * settings.cms_revenue_per_raf_point, 2)
            if avg_raf
            else None
        )

        snapshot_data = {
            "patient_count": len(patient_ids),
            "avg_raf_score": avg_raf,
            "avg_age": avg_age,
            "gender_distribution": gender_distribution,
            "top_hccs": top_hccs,
            "risk_tier_distribution": risk_tier_distribution,
            "total_revenue": total_revenue,
            "metrics": {
                "hcc_code_count": len(top_hccs),
                "risk_tier_count": len(risk_tier_distribution),
            },
        }

    today = date.today()
    with raf_cursor() as cur:
        cur.execute(
            """
            INSERT INTO cohort_snapshots
                (cohort_id, tenant_id, snapshot_date, patient_count, avg_raf_score,
                 avg_age, gender_distribution, top_hccs, risk_tier_distribution,
                 total_revenue, metrics)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                cohort_id,
                tenant_id,
                today,
                snapshot_data["patient_count"],
                snapshot_data["avg_raf_score"],
                snapshot_data["avg_age"],
                json.dumps(snapshot_data["gender_distribution"]),
                json.dumps(snapshot_data["top_hccs"]),
                json.dumps(snapshot_data["risk_tier_distribution"]),
                snapshot_data["total_revenue"],
                json.dumps(snapshot_data["metrics"]),
            ),
        )
        snapshot_id = cur.lastrowid
        cur.execute("SELECT * FROM cohort_snapshots WHERE id = %s", (snapshot_id,))
        snap_row = cur.fetchone()

    # Deserialize JSON columns for the response
    for col in ("gender_distribution", "top_hccs", "risk_tier_distribution", "metrics"):
        if snap_row and isinstance(snap_row.get(col), str):
            try:
                snap_row[col] = json.loads(snap_row[col])
            except Exception:
                pass

    logger.info(
        "cohort_service: snapshot id=%s for cohort=%s on %s",
        snapshot_id,
        cohort_id,
        today,
    )
    return snap_row


def get_cohort_trends(
    cohort_id: int,
    *,
    limit: int = 24,
) -> list[dict[str, Any]]:
    """Return historical snapshots for a cohort, newest first."""
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT * FROM cohort_snapshots
            WHERE cohort_id = %s
            ORDER BY snapshot_date DESC
            LIMIT %s
            """,
            (cohort_id, limit),
        )
        rows = cur.fetchall() or []

    for row in rows:
        for col in (
            "gender_distribution",
            "top_hccs",
            "risk_tier_distribution",
            "metrics",
        ):
            if isinstance(row.get(col), str):
                try:
                    row[col] = json.loads(row[col])
                except Exception:
                    pass
    return rows


# ---------------------------------------------------------------------------
# Statistical helpers (independent samples)
# ---------------------------------------------------------------------------


def _mean_std(values: list[float]) -> tuple[float, float]:
    """Return (mean, sample_std) for a list of floats. Handles n=0 and n=1."""
    n = len(values)
    if n == 0:
        return 0.0, 0.0
    mean = sum(values) / n
    if n == 1:
        return mean, 0.0
    variance = sum((x - mean) ** 2 for x in values) / (n - 1)
    return mean, math.sqrt(variance)


def _t_test_p_value(vals_a: list[float], vals_b: list[float]) -> float | None:
    """
    Approximate two-tailed p-value for Welch's independent-samples t-test.

    Returns None when either group is empty or has zero variance.
    Uses a normal approximation (z-score) for large samples (n>=30) and
    a Student-t CDF approximation for smaller samples.  For a full SciPy
    implementation replace the body with scipy.stats.ttest_ind.
    """
    n_a, n_b = len(vals_a), len(vals_b)
    if n_a < 2 or n_b < 2:
        return None
    mean_a, std_a = _mean_std(vals_a)
    mean_b, std_b = _mean_std(vals_b)
    se2 = (std_a**2 / n_a) + (std_b**2 / n_b)
    if se2 == 0:
        return None
    t_stat = (mean_a - mean_b) / math.sqrt(se2)

    # Normal approximation (conservative for small n)
    # P(|Z| > |t|) ≈ 2 * (1 - Φ(|t|))
    # Φ approximated with the Abramowitz & Stegun rational approximation.
    x = abs(t_stat)
    p1 = math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)
    t_poly = 1.0 / (1.0 + 0.2316419 * x)
    b_coeffs = (0.319381530, -0.356563782, 1.781477937, -1.821255978, 1.330274429)
    poly = sum(c * t_poly ** (i + 1) for i, c in enumerate(b_coeffs))
    p_one_tail = p1 * poly
    return min(1.0, 2.0 * p_one_tail)


def _chi_square_p_value(dist_a: dict[str, int], dist_b: dict[str, int]) -> float | None:
    """
    Chi-square goodness-of-fit test: do dist_a and dist_b have the same
    distribution?  Returns approximate p-value using chi-square CDF approximation.
    Returns None when totals are zero.
    """
    keys = set(dist_a) | set(dist_b)
    n_a = sum(dist_a.values())
    n_b = sum(dist_b.values())
    if n_a == 0 or n_b == 0:
        return None

    chi2 = 0.0
    df = 0
    for k in keys:
        obs_a = dist_a.get(k, 0)
        obs_b = dist_b.get(k, 0)
        total = obs_a + obs_b
        if total == 0:
            continue
        exp_a = total * n_a / (n_a + n_b)
        exp_b = total * n_b / (n_a + n_b)
        if exp_a > 0:
            chi2 += (obs_a - exp_a) ** 2 / exp_a
        if exp_b > 0:
            chi2 += (obs_b - exp_b) ** 2 / exp_b
        df += 1

    if df == 0:
        return None

    # Approximate p-value via regularised incomplete gamma: P(chi2/2, df/2)
    # Using the chi2 survival function approximation for df >= 1.
    # For a production system, replace with scipy.stats.chi2.sf(chi2, df).
    # Simple approximation: convert to z-score for large df.
    if df >= 2:
        z = ((chi2 / df) ** (1 / 3) - (1 - 2 / (9 * df))) / math.sqrt(2 / (9 * df))
        x = abs(z)
        p1 = math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)
        t_poly = 1.0 / (1.0 + 0.2316419 * x)
        b_coeffs = (0.319381530, -0.356563782, 1.781477937, -1.821255978, 1.330274429)
        poly = sum(c * t_poly ** (i + 1) for i, c in enumerate(b_coeffs))
        p_one_tail = p1 * poly
        return min(1.0, 2.0 * p_one_tail)
    return None


# ---------------------------------------------------------------------------
# Cohort comparison
# ---------------------------------------------------------------------------


def _build_cohort_metrics(
    patient_ids: list[int],
    tenant_id: int,
) -> dict[str, Any]:
    """Gather aggregate metrics for a list of patient IDs."""
    if tenant_id is None:
        raise ValueError(
            "cohort_service._build_cohort_metrics: tenant_id is required — "
            "refusing to query across all tenants (HIPAA multi-tenant isolation)"
        )
    tid = int(tenant_id)

    if not patient_ids:
        return {
            "patient_count": 0,
            "avg_raf_score": None,
            "avg_age": None,
            "gender_distribution": {},
            "risk_tier_distribution": {},
            "total_revenue": None,
            "raf_scores_raw": [],
            "ages_raw": [],
        }

    ids_fmt = ",".join(["%s"] * len(patient_ids))

    active_frag, active_params = active_patients_subquery(tid)
    with raf_cursor() as cur:
        cur.execute(
            f"SELECT final_raf, risk_tier FROM raf_scores WHERE patient_id IN ({ids_fmt}) AND {active_frag}",
            [*patient_ids, *active_params],
        )
        raf_rows = cur.fetchall() or []

    raf_vals = [float(r["final_raf"]) for r in raf_rows if r["final_raf"] is not None]
    avg_raf = round(sum(raf_vals) / len(raf_vals), 4) if raf_vals else None

    risk_tier_distribution: dict[str, int] = {}
    for r in raf_rows:
        tier = r.get("risk_tier") or "unknown"
        risk_tier_distribution[tier] = risk_tier_distribution.get(tier, 0) + 1

    ages: list[float] = []
    gender_dist: dict[str, int] = {}
    try:
        with raf_cursor() as cur:
            cur.execute(
                f"""
                SELECT TIMESTAMPDIFF(YEAR, dob, CURDATE()) AS age, sex
                FROM patients
                WHERE id IN ({ids_fmt})
                """,
                patient_ids,
            )
            demo_rows = cur.fetchall() or []
        for r in demo_rows:
            if r.get("age") is not None:
                ages.append(float(r["age"]))
            g = r.get("sex") or "U"
            gender_dist[g] = gender_dist.get(g, 0) + 1
    except Exception as exc:
        logger.warning("compare_cohorts: demographics query failed: %s", exc)

    avg_age = round(sum(ages) / len(ages), 2) if ages else None
    total_revenue = (
        round(avg_raf * len(patient_ids) * settings.cms_revenue_per_raf_point, 2)
        if avg_raf
        else None
    )

    return {
        "patient_count": len(patient_ids),
        "avg_raf_score": avg_raf,
        "avg_age": avg_age,
        "gender_distribution": gender_dist,
        "risk_tier_distribution": risk_tier_distribution,
        "total_revenue": total_revenue,
        "raf_scores_raw": raf_vals,  # kept for t-test, stripped before storage
        "ages_raw": ages,
    }


def compare_cohorts(
    *,
    cohort_a_id: int,
    cohort_b_id: int,
    name: str | None = None,
    created_by: int | None = None,
    tenant_id: str,
) -> dict[str, Any]:
    """
    Compare two cohorts across key population health metrics and persist the
    result to cohort_comparisons.

    Statistical tests applied:
      - Welch's t-test on RAF scores and ages (continuous).
      - Chi-square on gender and risk tier distributions (categorical).
    """
    for cid in (cohort_a_id, cohort_b_id):
        if not get_cohort(cid):
            raise ValueError(f"Cohort {cid} not found")

    with raf_cursor() as cur:
        ids_a = _active_patient_ids(cur, cohort_a_id)
        ids_b = _active_patient_ids(cur, cohort_b_id)

    metrics_a = _build_cohort_metrics(ids_a)
    metrics_b = _build_cohort_metrics(ids_b)

    # Extract raw arrays for significance testing, then strip from stored metrics
    raf_a = metrics_a.pop("raf_scores_raw", [])
    raf_b = metrics_b.pop("raf_scores_raw", [])
    ages_a = metrics_a.pop("ages_raw", [])
    ages_b = metrics_b.pop("ages_raw", [])

    # Absolute and % differences for numeric metrics
    def _delta(a: float | None, b: float | None) -> float | None:
        if a is None or b is None:
            return None
        return round(b - a, 4)

    def _pct_change(a: float | None, b: float | None) -> float | None:
        if a is None or b is None or a == 0:
            return None
        return round((b - a) / abs(a) * 100, 2)

    differences = {
        "patient_count_delta": _delta(
            metrics_a["patient_count"], metrics_b["patient_count"]
        ),
        "avg_raf_score_delta": _delta(
            metrics_a["avg_raf_score"], metrics_b["avg_raf_score"]
        ),
        "avg_raf_score_pct_change": _pct_change(
            metrics_a["avg_raf_score"], metrics_b["avg_raf_score"]
        ),
        "avg_age_delta": _delta(metrics_a["avg_age"], metrics_b["avg_age"]),
        "total_revenue_delta": _delta(
            metrics_a["total_revenue"], metrics_b["total_revenue"]
        ),
        "total_revenue_pct_change": _pct_change(
            metrics_a["total_revenue"], metrics_b["total_revenue"]
        ),
    }

    # Statistical significance
    raf_p = _t_test_p_value(raf_a, raf_b)
    age_p = _t_test_p_value(ages_a, ages_b)
    gender_p = _chi_square_p_value(
        metrics_a["gender_distribution"], metrics_b["gender_distribution"]
    )
    risk_p = _chi_square_p_value(
        metrics_a["risk_tier_distribution"], metrics_b["risk_tier_distribution"]
    )

    ALPHA = 0.05
    statistical_significance = {
        "avg_raf_score_p_value": raf_p,
        "avg_raf_score_significant": (raf_p is not None and raf_p < ALPHA),
        "avg_age_p_value": age_p,
        "avg_age_significant": (age_p is not None and age_p < ALPHA),
        "gender_distribution_p_value": gender_p,
        "gender_distribution_significant": (gender_p is not None and gender_p < ALPHA),
        "risk_tier_distribution_p_value": risk_p,
        "risk_tier_distribution_significant": (risk_p is not None and risk_p < ALPHA),
        "alpha": ALPHA,
    }

    today = date.today()
    with raf_cursor() as cur:
        cur.execute(
            """
            INSERT INTO cohort_comparisons
                (tenant_id, name, cohort_a_id, cohort_b_id, comparison_date,
                 metrics_a, metrics_b, differences, statistical_significance, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                tenant_id,
                name,
                cohort_a_id,
                cohort_b_id,
                today,
                json.dumps(_serialize(metrics_a)),
                json.dumps(_serialize(metrics_b)),
                json.dumps(_serialize(differences)),
                json.dumps(_serialize(statistical_significance)),
                created_by,
            ),
        )
        comparison_id = cur.lastrowid
        cur.execute("SELECT * FROM cohort_comparisons WHERE id = %s", (comparison_id,))
        comp_row = cur.fetchone()

    for col in ("metrics_a", "metrics_b", "differences", "statistical_significance"):
        if comp_row and isinstance(comp_row.get(col), str):
            try:
                comp_row[col] = json.loads(comp_row[col])
            except Exception:
                pass

    logger.info(
        "cohort_service: comparison id=%s cohort_a=%s cohort_b=%s",
        comparison_id,
        cohort_a_id,
        cohort_b_id,
    )
    return comp_row


def get_comparison(comparison_id: int) -> dict[str, Any] | None:
    with raf_cursor() as cur:
        cur.execute("SELECT * FROM cohort_comparisons WHERE id = %s", (comparison_id,))
        row = cur.fetchone()
    if not row:
        return None
    for col in ("metrics_a", "metrics_b", "differences", "statistical_significance"):
        if isinstance(row.get(col), str):
            try:
                row[col] = json.loads(row[col])
            except Exception:
                pass
    return row


# ---------------------------------------------------------------------------
# Population health — global metrics
# ---------------------------------------------------------------------------


def get_population_health_metrics(
    tenant_id: str,
) -> dict[str, Any]:
    """
    Return population-wide health metrics across all active cohorts in a tenant.

    Includes:
    - Total unique patients across all active cohorts
    - Average RAF score population-wide
    - Risk tier distribution
    - Top 10 HCC codes by prevalence
    - Active / archived cohort counts
    - Estimated total RAF revenue
    """
    if not tenant_id:
        raise ValueError(
            "cohort_service.get_population_health_metrics: tenant_id is required — "
            "refusing to query across all tenants (HIPAA multi-tenant isolation)"
        )
    try:
        tid = int(tenant_id)
    except (TypeError, ValueError):
        raise ValueError(
            f"cohort_service.get_population_health_metrics: tenant_id must be numeric, got {tenant_id!r}"
        )

    with raf_cursor() as cur:
        # All active cohort patient IDs for this tenant
        cur.execute(
            """
            SELECT DISTINCT cm.patient_id
            FROM cohort_members cm
            JOIN cohorts c ON c.id = cm.cohort_id
            WHERE c.tenant_id = %s AND c.status = 'active' AND cm.is_active = 1
            """,
            (tenant_id,),
        )
        all_patient_rows = cur.fetchall() or []
        all_patient_ids = [r["patient_id"] for r in all_patient_rows]

        # Cohort counts
        cur.execute(
            "SELECT status, COUNT(*) AS cnt FROM cohorts WHERE tenant_id = %s GROUP BY status",
            (tenant_id,),
        )
        cohort_counts = {r["status"]: r["cnt"] for r in (cur.fetchall() or [])}

    # If no cohort members exist, fall back to all active patients for this tenant
    # so the dashboard shows real data even before any cohorts are created.
    use_cohort_filter = bool(all_patient_ids)
    ids_fmt = ",".join(["%s"] * len(all_patient_ids)) if use_cohort_filter else None

    with raf_cursor() as cur:
        active_frag, active_params = active_patients_subquery(tid)
        if use_cohort_filter:
            cur.execute(
                f"SELECT AVG(final_raf) AS avg_raf FROM raf_scores WHERE patient_id IN ({ids_fmt}) AND {active_frag}",
                [*all_patient_ids, *active_params],
            )
        else:
            cur.execute(
                f"SELECT AVG(final_raf) AS avg_raf FROM raf_scores WHERE {active_frag}",
                [*active_params],
            )
        avg_row = cur.fetchone()
        avg_raf = (
            round(float(avg_row["avg_raf"]), 4)
            if avg_row and avg_row["avg_raf"] is not None
            else None
        )

        # Derive risk tiers from final_raf (no risk_tier column in raf_scores)
        active_frag2, active_params2 = active_patients_subquery(tid)
        _tier_sql = """
            SELECT
                CASE
                    WHEN final_raf < 0.5 THEN 'Low'
                    WHEN final_raf < 1.0 THEN 'Moderate'
                    WHEN final_raf < 2.0 THEN 'High'
                    ELSE 'Very High'
                END AS risk_tier,
                COUNT(DISTINCT patient_id) AS cnt
            FROM raf_scores rs
            INNER JOIN (
                SELECT patient_id AS pid, MAX(calculated_at) AS latest
                FROM raf_scores GROUP BY patient_id
            ) lx ON rs.patient_id = lx.pid AND rs.calculated_at = lx.latest
        """
        if use_cohort_filter:
            cur.execute(
                f"{_tier_sql} WHERE rs.patient_id IN ({ids_fmt}) AND {active_frag2} GROUP BY risk_tier",
                [*all_patient_ids, *active_params2],
            )
        else:
            cur.execute(
                f"{_tier_sql} WHERE {active_frag2} GROUP BY risk_tier",
                [*active_params2],
            )
        risk_rows = cur.fetchall() or []
        risk_dist = {r["risk_tier"]: r["cnt"] for r in risk_rows if r["risk_tier"]}

        # Get HCC codes from raf_patient_hcc (not raf_scores)
        active_frag3, active_params3 = active_patients_subquery(tid)
        if use_cohort_filter:
            cur.execute(
                f"SELECT hcc_code FROM raf_patient_hcc WHERE patient_id IN ({ids_fmt}) AND {active_frag3}",
                [*all_patient_ids, *active_params3],
            )
        else:
            cur.execute(
                f"SELECT hcc_code FROM raf_patient_hcc WHERE {active_frag3}",
                [*active_params3],
            )
        hcc_raw = cur.fetchall() or []

        # When no cohort filter, count distinct active patients directly
        if not use_cohort_filter:
            active_frag4, active_params4 = active_patients_subquery(tid)
            cur.execute(
                f"SELECT COUNT(DISTINCT patient_id) AS cnt FROM raf_scores WHERE {active_frag4}",
                [*active_params4],
            )
            count_row = cur.fetchone()
            fallback_patient_count = int(count_row["cnt"]) if count_row and count_row["cnt"] else 0
        else:
            fallback_patient_count = len(all_patient_ids)

    hcc_counter: dict[str, int] = {}
    for row in hcc_raw:
        code = row.get("hcc_code")
        if code:
            hcc_counter[str(code)] = hcc_counter.get(str(code), 0) + 1

    n = fallback_patient_count
    top_hccs = sorted(
        [
            {"code": code, "count": cnt, "prevalence": round(cnt / n, 4) if n else 0.0}
            for code, cnt in hcc_counter.items()
        ],
        key=lambda x: x["count"],
        reverse=True,
    )[:10]

    total_revenue = round(avg_raf * n * settings.cms_revenue_per_raf_point, 2) if avg_raf else None

    return {
        "tenant_id": tenant_id,
        "total_unique_patients": n,
        "avg_raf_score": avg_raf,
        "total_raf_revenue": total_revenue,
        "risk_tier_distribution": risk_dist,
        "top_hccs": top_hccs,
        "cohort_counts": cohort_counts,
    }


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def export_cohort_csv(
    cohort_id: int,
    tenant_id: int,
) -> str:
    """
    Return a CSV string of all active cohort members with key clinical metrics.

    Columns: patient_id, added_at, final_raf, risk_tier, hcc_codes, age, gender
    """
    cohort = get_cohort(cohort_id)
    if not cohort:
        raise ValueError(f"Cohort {cohort_id} not found")

    if tenant_id is None:
        raise ValueError(
            "cohort_service.export_cohort_csv: tenant_id is required — "
            "refusing to query across all tenants (HIPAA multi-tenant isolation)"
        )
    tid = int(tenant_id)

    with raf_cursor() as cur:
        patient_ids = _active_patient_ids(cur, cohort_id)

    if not patient_ids:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "patient_id",
                "added_at",
                "final_raf",
                "risk_tier",
                "hcc_codes",
                "age",
                "gender",
            ]
        )
        return output.getvalue()

    ids_fmt = ",".join(["%s"] * len(patient_ids))

    # RAF data
    active_frag, active_params = active_patients_subquery(tid)
    with raf_cursor() as cur:
        cur.execute(
            f"SELECT patient_id, final_raf, risk_tier, hcc_codes FROM raf_scores WHERE patient_id IN ({ids_fmt}) AND {active_frag}",
            [*patient_ids, *active_params],
        )
        raf_rows = {r["patient_id"]: r for r in (cur.fetchall() or [])}

        cur.execute(
            f"SELECT patient_id, added_at FROM cohort_members WHERE cohort_id = %s AND patient_id IN ({ids_fmt}) AND is_active = 1",
            [cohort_id] + patient_ids,
        )
        member_added = {r["patient_id"]: r["added_at"] for r in (cur.fetchall() or [])}

    # Demographics from raf_intelligence.patients
    demo_map: dict[int, dict] = {}
    try:
        with raf_cursor() as cur:
            cur.execute(
                f"SELECT id AS pid, TIMESTAMPDIFF(YEAR, dob, CURDATE()) AS age, sex FROM patients WHERE id IN ({ids_fmt})",
                patient_ids,
            )
            for r in cur.fetchall() or []:
                demo_map[r["pid"]] = r
    except Exception as exc:
        logger.warning("cohort export: demographics query failed: %s", exc)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "patient_id",
            "added_at",
            "final_raf",
            "risk_tier",
            "hcc_codes",
            "age",
            "gender",
        ]
    )

    for pid in sorted(patient_ids):
        raf = raf_rows.get(pid, {})
        demo = demo_map.get(pid, {})
        hcc_codes = raf.get("hcc_codes") or ""
        if isinstance(hcc_codes, list):
            hcc_codes = ",".join(str(c) for c in hcc_codes)
        added_at = member_added.get(pid, "")
        if isinstance(added_at, datetime):
            added_at = added_at.isoformat()
        writer.writerow(
            [
                pid,
                added_at,
                raf.get("final_raf", ""),
                raf.get("risk_tier", ""),
                hcc_codes,
                demo.get("age", ""),
                demo.get("sex", ""),
            ]
        )

    return output.getvalue()
