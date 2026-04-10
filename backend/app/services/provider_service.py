"""
Provider management and scorecard calculation service.

Handles:
- CRUD for providers (with optional OpenEMR user auto-population)
- Patient panel management and auto-attribution from OpenEMR encounters
- Provider scorecard calculation with aggregate RAF/HCC metrics
- Per-HCC performance analysis
- Alert generation (suspects, recapture, MEAT gaps)
"""

from __future__ import annotations

import logging
import statistics
from datetime import date, datetime
from typing import Any, Optional

from app.config import settings
from app.db import raf_cursor, openemr_cursor

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Active EMR patient filter
# ---------------------------------------------------------------------------

from app.services.emr_manager import ACTIVE_PATIENTS_SUBQUERY, active_patients_subquery  # noqa: E402

# Base annual revenue per RAF point (CMS MA benchmark) — configurable via env CMS_REVENUE_PER_RAF_POINT
_ANNUAL_REVENUE_PER_RAF_POINT = settings.cms_revenue_per_raf_point

# Estimated incremental revenue per HCC coded (used for suspect opportunity)
_HCC_BASE_RATE = 12_000.0

# Scorecard is considered stale after this many hours
_SCORECARD_STALE_HOURS = 24



# ---------------------------------------------------------------------------
# Provider CRUD
# ---------------------------------------------------------------------------


def create_provider(data: dict[str, Any]) -> dict[str, Any]:
    """Insert a new provider row and return the created record."""
    with raf_cursor() as cur:
        cur.execute(
            """
            INSERT INTO providers
                (openemr_user_id, npi, first_name, last_name, specialty, email, phone, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                data.get("openemr_user_id"),
                data.get("npi"),
                data["first_name"],
                data["last_name"],
                data.get("specialty"),
                data.get("email"),
                data.get("phone"),
                data.get("status", "active"),
            ),
        )
        new_id = cur.lastrowid
    return get_provider(new_id)


def get_provider(provider_id: int) -> dict[str, Any] | None:
    """Return a single provider by primary key, or None if not found."""

    with raf_cursor() as cur:
        cur.execute(
            "SELECT * FROM providers WHERE id = %s",
            (provider_id,),
        )
        row = cur.fetchone()
    if not row:
        return None
    return _serialize_provider(row)


def list_providers(
    specialty: str | None = None,
    status: str | None = None,
    search: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Return providers filtered by optional specialty, status, and name search."""

    conditions: list[str] = []
    params: list[Any] = []

    if status:
        conditions.append("status = %s")
        params.append(status)
    if specialty:
        conditions.append("specialty LIKE %s")
        params.append(f"%{specialty}%")
    if search:
        conditions.append("(first_name LIKE %s OR last_name LIKE %s OR npi LIKE %s)")
        params.extend([f"%{search}%", f"%{search}%", f"%{search}%"])

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params.extend([limit, offset])

    with raf_cursor() as cur:
        cur.execute(
            f"SELECT * FROM providers {where} ORDER BY last_name, first_name LIMIT %s OFFSET %s",
            tuple(params),
        )
        rows = cur.fetchall()
    return [_serialize_provider(r) for r in rows]


def update_provider(provider_id: int, data: dict[str, Any]) -> dict[str, Any] | None:
    """Partial update of a provider. Returns updated record or None if not found."""

    allowed = {
        "npi",
        "first_name",
        "last_name",
        "specialty",
        "email",
        "phone",
        "status",
    }
    updates = {k: v for k, v in data.items() if k in allowed}
    if not updates:
        return get_provider(provider_id)

    set_clause = ", ".join(f"{k} = %s" for k in updates)
    params = list(updates.values()) + [provider_id]

    with raf_cursor() as cur:
        cur.execute(
            f"UPDATE providers SET {set_clause} WHERE id = %s",
            tuple(params),
        )
    return get_provider(provider_id)


def deactivate_provider(provider_id: int) -> bool:
    """Set provider status to inactive. Returns True if a row was affected."""

    with raf_cursor() as cur:
        cur.execute(
            "UPDATE providers SET status = 'inactive' WHERE id = %s",
            (provider_id,),
        )
        return cur.rowcount > 0


def _serialize_provider(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "openemr_user_id": row.get("openemr_user_id"),
        "npi": row.get("npi"),
        "first_name": row["first_name"],
        "last_name": row["last_name"],
        "full_name": f"{row['first_name']} {row['last_name']}".strip(),
        "specialty": row.get("specialty"),
        "email": row.get("email"),
        "phone": row.get("phone"),
        "status": row.get("status", "active"),
        "created_at": str(row.get("created_at", "")),
        "updated_at": str(row.get("updated_at", "")),
    }


# ---------------------------------------------------------------------------
# Auto-discover providers from OpenEMR users table
# ---------------------------------------------------------------------------


def auto_discover_providers() -> dict[str, Any]:
    """
    Query OpenEMR users table and upsert matching provider records.

    Only users with a non-empty lname and a taxonomy/specialty are imported.
    Users that already exist (matched on openemr_user_id) are skipped.

    Returns a summary with created and skipped counts.
    """


    try:
        with openemr_cursor() as cur:
            cur.execute(
                """
                SELECT id, fname, lname, specialty, email, phone, npi
                FROM users
                WHERE active = 1
                  AND lname IS NOT NULL AND lname != ''
                  AND username != 'admin'
                ORDER BY lname, fname
                """
            )
            users = cur.fetchall()
    except Exception as exc:
        logger.error("auto_discover_providers openemr query failed: %s", exc)
        raise

    created: list[dict[str, Any]] = []
    skipped: list[int] = []

    # Fetch existing openemr_user_ids to avoid duplicates in one batch query
    with raf_cursor() as cur:
        cur.execute(
            "SELECT openemr_user_id FROM providers WHERE openemr_user_id IS NOT NULL"
        )
        existing_ids: set[int] = {r["openemr_user_id"] for r in cur.fetchall()}

    for u in users:
        uid = int(u["id"])
        if uid in existing_ids:
            skipped.append(uid)
            continue
        try:
            provider = create_provider(
                {
                    "openemr_user_id": uid,
                    "npi": u.get("npi") or None,
                    "first_name": u.get("fname") or "",
                    "last_name": u.get("lname") or "",
                    "specialty": u.get("specialty") or None,
                    "email": u.get("email") or None,
                    "phone": u.get("phone") or None,
                    "status": "active",
                }
            )
            created.append(provider)
            existing_ids.add(uid)
        except Exception as exc:
            logger.warning(
                "auto_discover: could not create provider for user %s: %s", uid, exc
            )

    return {
        "discovered": len(users),
        "created": len(created),
        "skipped": len(skipped),
        "providers": created,
    }


# ---------------------------------------------------------------------------
# Panel management
# ---------------------------------------------------------------------------


def get_panel_patients(
    provider_id: int,
    limit: int = 100,
    offset: int = 0,
    tenant_id: Optional[int] = None,
) -> list[dict[str, Any]]:
    """Return all patients attributed to a provider's panel."""

    if tenant_id is None:
        logger.warning(
            "provider_service.get_panel_patients: no tenant_id provided, defaulting to 1"
        )
        tid = 1
    else:
        tid = int(tenant_id)

    with raf_cursor() as cur:
        cur.execute(
            f"""
            SELECT patient_id, attribution, assigned_at
            FROM provider_patient_panel
            WHERE provider_id = %s
              AND {ACTIVE_PATIENTS_SUBQUERY}
              AND tenant_id = %s
            ORDER BY assigned_at DESC
            LIMIT %s OFFSET %s
            """,
            (provider_id, tid, limit, offset),
        )
        rows = cur.fetchall()

    if not rows:
        return []

    patient_ids = [r["patient_id"] for r in rows]
    panel_meta = {r["patient_id"]: r for r in rows}

    # Enrich with patient demographics from raf_intelligence.patients
    placeholders = ", ".join(["%s"] * len(patient_ids))
    try:
        with raf_cursor() as cur:
            cur.execute(
                f"SELECT id AS pid, first_name AS fname, last_name AS lname, dob AS DOB, sex FROM patients WHERE id IN ({placeholders})",
                tuple(patient_ids),
            )
            patients = {int(p["pid"]): p for p in cur.fetchall()}
    except Exception as exc:
        logger.warning("get_panel_patients patients query failed: %s", exc)
        patients = {}

    result: list[dict[str, Any]] = []
    for pid in patient_ids:
        meta = panel_meta[pid]
        p = patients.get(pid, {})
        result.append(
            {
                "patient_id": pid,
                "first_name": p.get("fname") or "",
                "last_name": p.get("lname") or "",
                "full_name": f"{p.get('fname', '')} {p.get('lname', '')}".strip(),
                "dob": str(p.get("DOB") or ""),
                "sex": (p.get("sex") or "").strip() or "Unknown",
                "attribution": meta["attribution"],
                "assigned_at": str(meta["assigned_at"]),
            }
        )
    return result


def assign_patient_to_provider(
    provider_id: int, patient_id: int, attribution: str = "manual"
) -> dict[str, Any]:
    """Assign (or re-attribute) a patient to a provider panel."""

    with raf_cursor() as cur:
        cur.execute(
            """
            INSERT INTO provider_patient_panel (provider_id, patient_id, attribution)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE
                attribution = VALUES(attribution),
                updated_at  = CURRENT_TIMESTAMP
            """,
            (provider_id, patient_id, attribution),
        )
    return {
        "provider_id": provider_id,
        "patient_id": patient_id,
        "attribution": attribution,
    }


def remove_patient_from_panel(provider_id: int, patient_id: int) -> bool:
    """Remove a patient from a provider's panel. Returns True if removed."""

    with raf_cursor() as cur:
        cur.execute(
            "DELETE FROM provider_patient_panel WHERE provider_id = %s AND patient_id = %s",
            (provider_id, patient_id),
        )
        return cur.rowcount > 0


def auto_attribute_patients(provider_id: int | None = None) -> dict[str, Any]:
    """
    Attribute patients to providers based on most-recent encounter provider
    in OpenEMR form_encounter joined with users table.

    If provider_id is given, only re-attributes patients whose most-recent
    provider maps to that provider record.  Otherwise runs globally.

    Returns attribution counts.
    """


    try:
        with openemr_cursor() as cur:
            cur.execute(
                """
                SELECT fe.pid, fe.provider_id AS openemr_user_id
                FROM form_encounter fe
                INNER JOIN (
                    SELECT pid, MAX(date) AS latest_date
                    FROM form_encounter
                    WHERE provider_id IS NOT NULL AND provider_id > 0
                    GROUP BY pid
                ) latest
                ON fe.pid = latest.pid AND fe.date = latest.latest_date
                ORDER BY fe.pid
                """
            )
            enc_rows = cur.fetchall()
    except Exception as exc:
        logger.error("auto_attribute_patients encounter query failed: %s", exc)
        raise

    # Build openemr_user_id → provider.id lookup
    with raf_cursor() as cur:
        cur.execute(
            "SELECT id, openemr_user_id FROM providers WHERE openemr_user_id IS NOT NULL AND status = 'active'"
        )
        user_to_provider: dict[int, int] = {
            int(r["openemr_user_id"]): int(r["id"]) for r in cur.fetchall()
        }

    attributed = 0
    skipped = 0

    for row in enc_rows:
        oe_uid = row.get("openemr_user_id")
        if not oe_uid:
            skipped += 1
            continue
        prov_id = user_to_provider.get(int(oe_uid))
        if not prov_id:
            skipped += 1
            continue
        if provider_id is not None and prov_id != provider_id:
            skipped += 1
            continue
        try:
            assign_patient_to_provider(prov_id, int(row["pid"]), attribution="auto")
            attributed += 1
        except Exception as exc:
            logger.warning(
                "auto_attribute: could not assign pid=%s: %s", row["pid"], exc
            )
            skipped += 1

    return {
        "total_encounters_processed": len(enc_rows),
        "patients_attributed": attributed,
        "patients_skipped": skipped,
    }


# ---------------------------------------------------------------------------
# Scorecard calculation
# ---------------------------------------------------------------------------


def calculate_provider_scorecard(
    provider_id: int,
    year: int,
    tenant_id: Optional[int] = None,
) -> dict[str, Any]:
    """
    Compute a full provider scorecard for the given measurement year and
    persist a snapshot.  Returns the scorecard dict.
    """

    if tenant_id is None:
        logger.warning(
            "provider_service.calculate_provider_scorecard: no tenant_id provided, defaulting to 1"
        )
        tid = 1
    else:
        tid = int(tenant_id)

    # --- 1. Get panel patient IDs (active EMR connections only) ---
    with raf_cursor() as cur:
        cur.execute(
            f"SELECT patient_id FROM provider_patient_panel WHERE provider_id = %s AND {ACTIVE_PATIENTS_SUBQUERY}",
            (provider_id,),
        )
        panel = [r["patient_id"] for r in cur.fetchall()]

    total_patients = len(panel)
    if total_patients == 0:
        return _empty_scorecard(provider_id, year)

    placeholders = ", ".join(["%s"] * total_patients)

    # --- 2. RAF scores ---
    with raf_cursor() as cur:
        cur.execute(
            f"""
            SELECT rs.patient_id, rs.final_raf
            FROM raf_scores rs
            INNER JOIN (
                SELECT patient_id, MAX(calculated_at) AS latest
                FROM raf_scores
                WHERE measurement_year = %s AND patient_id IN ({placeholders})
                GROUP BY patient_id
            ) lx ON rs.patient_id = lx.patient_id AND rs.calculated_at = lx.latest
            """,
            tuple([year] + panel),
        )
        score_rows = cur.fetchall()

    # NOTE: Converting DECIMAL columns to float can introduce floating-point
    # precision errors for values with many significant digits.  We round to
    # 4 decimal places here to keep arithmetic stable.  If exact decimal
    # arithmetic is required, use decimal.Decimal instead of float.
    raf_by_patient: dict[int, float] = {
        int(r["patient_id"]): round(float(r["final_raf"]), 4) for r in score_rows
    }
    patients_with_scores = len(raf_by_patient)
    average_raf = (
        round(statistics.mean(raf_by_patient.values()), 4) if raf_by_patient else None
    )

    # --- 3. HCC capture rate ---
    # coded HCCs for this year
    with raf_cursor() as cur:
        cur.execute(
            f"""
            SELECT COUNT(DISTINCT CONCAT(patient_id, '-', hcc_code)) AS coded
            FROM raf_patient_hcc
            WHERE measurement_year = %s AND patient_id IN ({placeholders})
            """,
            tuple([year] + panel),
        )
        row = cur.fetchone()
        coded_hcc_count = int(row["coded"]) if row else 0

    # open suspect HCCs (represent potential HCCs not yet coded)
    with raf_cursor() as cur:
        cur.execute(
            f"""
            SELECT COUNT(*) AS open_suspects
            FROM raf_suspect_conditions
            WHERE status = 'open'
              AND hcc_code IS NOT NULL
              AND patient_id IN ({placeholders})
            """,
            tuple(panel),
        )
        row = cur.fetchone()
        open_suspect_hccs = int(row["open_suspects"]) if row else 0

    possible_hcc_count = coded_hcc_count + open_suspect_hccs
    hcc_capture_rate = (
        round(coded_hcc_count / possible_hcc_count, 4)
        if possible_hcc_count > 0
        else None
    )

    # --- 4. Recapture rate ---
    prior_year = year - 1
    with raf_cursor() as cur:
        cur.execute(
            f"""
            SELECT COUNT(DISTINCT CONCAT(patient_id, '-', hcc_code)) AS prior_cnt
            FROM raf_patient_hcc
            WHERE measurement_year = %s AND patient_id IN ({placeholders})
            """,
            tuple([prior_year] + panel),
        )
        row = cur.fetchone()
        prior_year_hccs = int(row["prior_cnt"]) if row else 0

    with raf_cursor() as cur:
        cur.execute(
            f"""
            SELECT COUNT(DISTINCT CONCAT(rph.patient_id, '-', rph.hcc_code)) AS recaptured
            FROM raf_patient_hcc rph
            WHERE rph.measurement_year = %s
              AND rph.patient_id IN ({placeholders})
              AND EXISTS (
                  SELECT 1 FROM raf_patient_hcc prev
                  WHERE prev.patient_id = rph.patient_id
                    AND prev.hcc_code   = rph.hcc_code
                    AND prev.measurement_year = %s
              )
            """,
            tuple([year] + panel + [prior_year]),
        )
        row = cur.fetchone()
        recaptured_count = int(row["recaptured"]) if row else 0

    recapture_rate = (
        round(recaptured_count / prior_year_hccs, 4) if prior_year_hccs > 0 else None
    )

    # --- 5. Suspect conditions counts ---
    with raf_cursor() as cur:
        cur.execute(
            f"""
            SELECT status, COUNT(*) AS cnt
            FROM raf_suspect_conditions
            WHERE patient_id IN ({placeholders})
            GROUP BY status
            """,
            tuple(panel),
        )
        suspect_rows = cur.fetchall()

    suspect_counts: dict[str, int] = {}
    for r in suspect_rows:
        suspect_counts[r["status"]] = int(r["cnt"])

    suspects_open = suspect_counts.get("open", 0)
    suspects_accepted = suspect_counts.get("accepted", 0)
    suspects_dismissed = suspect_counts.get(
        "dismissed", suspect_counts.get("rejected", 0)
    )

    # --- 6. Revenue opportunity from open suspects ---
    with raf_cursor() as cur:
        cur.execute(
            f"""
            SELECT SUM(confidence_score) AS total_confidence
            FROM raf_suspect_conditions
            WHERE status = 'open'
              AND patient_id IN ({placeholders})
            """,
            tuple(panel),
        )
        row = cur.fetchone()
        total_confidence = float(row["total_confidence"] or 0) if row else 0.0

    # Revenue opportunity = open suspects weighted by confidence * base rate
    revenue_opportunity = (
        round(
            suspects_open
            * _HCC_BASE_RATE
            * (total_confidence / suspects_open if suspects_open else 0),
            2,
        )
        if suspects_open
        else 0.0
    )

    # --- 7. MEAT completeness average ---
    meat_avg: float | None = None
    try:
        with raf_cursor() as cur:
            cur.execute(
                f"""
                SELECT AVG(me.completeness_score) AS avg_meat
                FROM raf_meat_evidence me
                JOIN raf_patient_hcc ph ON ph.id = me.patient_hcc_id
                WHERE ph.patient_id IN ({placeholders})
                  AND ph.measurement_year = %s
                """,
                tuple(panel + [year]),
            )
            row = cur.fetchone()
            if row and row["avg_meat"] is not None:
                meat_avg = round(float(row["avg_meat"]), 4)
    except Exception as exc:
        logger.debug("MEAT completeness query failed (table may not exist): %s", exc)

    # --- 8. Documentation quality composite ---
    # Weighted average: 40% capture rate + 30% recapture + 30% MEAT
    doc_components = []
    if hcc_capture_rate is not None:
        doc_components.append(hcc_capture_rate * 0.40)
    if recapture_rate is not None:
        doc_components.append(recapture_rate * 0.30)
    if meat_avg is not None:
        doc_components.append(meat_avg * 0.30)
    doc_quality = round(sum(doc_components), 4) if doc_components else None

    # --- 9. Percentile rank vs other providers ---
    percentile_rank = _calculate_percentile_rank(provider_id, year, average_raf)

    # --- 10. Persist snapshot ---
    with raf_cursor() as cur:
        cur.execute(
            """
            INSERT INTO provider_scorecard_snapshots
                (provider_id, measurement_year, total_patients, patients_with_scores,
                 average_raf, hcc_capture_rate, recapture_rate,
                 suspects_open, suspects_accepted, suspects_dismissed,
                 revenue_opportunity, meat_completeness_avg,
                 documentation_quality_score, percentile_rank)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                provider_id,
                year,
                total_patients,
                patients_with_scores,
                average_raf,
                hcc_capture_rate,
                recapture_rate,
                suspects_open,
                suspects_accepted,
                suspects_dismissed,
                revenue_opportunity,
                meat_avg,
                doc_quality,
                percentile_rank,
            ),
        )

    provider = get_provider(provider_id)
    return {
        "provider_id": provider_id,
        "provider_name": provider["full_name"] if provider else "",
        "measurement_year": year,
        "total_patients": total_patients,
        "patients_with_scores": patients_with_scores,
        "average_raf": average_raf,
        "hcc_capture_rate": hcc_capture_rate,
        "recapture_rate": recapture_rate,
        "suspects_open": suspects_open,
        "suspects_accepted": suspects_accepted,
        "suspects_dismissed": suspects_dismissed,
        "revenue_opportunity": revenue_opportunity,
        "meat_completeness_avg": meat_avg,
        "documentation_quality_score": doc_quality,
        "percentile_rank": percentile_rank,
        "calculated_at": datetime.utcnow().isoformat(),
    }


def get_latest_scorecard(provider_id: int, year: int) -> dict[str, Any] | None:
    """
    Return the most recent scorecard snapshot for a provider/year, or None
    if no snapshot exists or the snapshot is stale (older than _SCORECARD_STALE_HOURS).
    """

    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT *
            FROM provider_scorecard_snapshots
            WHERE provider_id = %s AND measurement_year = %s
            ORDER BY calculated_at DESC
            LIMIT 1
            """,
            (provider_id, year),
        )
        row = cur.fetchone()

    if not row:
        return None

    calculated_at = row.get("calculated_at")
    if calculated_at:
        if isinstance(calculated_at, str):
            calculated_at = datetime.fromisoformat(calculated_at)
        age_hours = (datetime.utcnow() - calculated_at).total_seconds() / 3600
        if age_hours > _SCORECARD_STALE_HOURS:
            return None

    provider = get_provider(provider_id)
    return {
        "provider_id": provider_id,
        "provider_name": provider["full_name"] if provider else "",
        "measurement_year": year,
        "total_patients": row["total_patients"],
        "patients_with_scores": row["patients_with_scores"],
        "average_raf": float(row["average_raf"])
        if row["average_raf"] is not None
        else None,
        "hcc_capture_rate": float(row["hcc_capture_rate"])
        if row["hcc_capture_rate"] is not None
        else None,
        "recapture_rate": float(row["recapture_rate"])
        if row["recapture_rate"] is not None
        else None,
        "suspects_open": row["suspects_open"],
        "suspects_accepted": row["suspects_accepted"],
        "suspects_dismissed": row["suspects_dismissed"],
        "revenue_opportunity": float(row["revenue_opportunity"])
        if row["revenue_opportunity"] is not None
        else None,
        "meat_completeness_avg": float(row["meat_completeness_avg"])
        if row["meat_completeness_avg"] is not None
        else None,
        "documentation_quality_score": float(row["documentation_quality_score"])
        if row["documentation_quality_score"] is not None
        else None,
        "percentile_rank": float(row["percentile_rank"])
        if row["percentile_rank"] is not None
        else None,
        "calculated_at": str(row.get("calculated_at", "")),
        "cached": True,
    }


def _empty_scorecard(provider_id: int, year: int) -> dict[str, Any]:
    provider = get_provider(provider_id)
    return {
        "provider_id": provider_id,
        "provider_name": provider["full_name"] if provider else "",
        "measurement_year": year,
        "total_patients": 0,
        "patients_with_scores": 0,
        "average_raf": None,
        "hcc_capture_rate": None,
        "recapture_rate": None,
        "suspects_open": 0,
        "suspects_accepted": 0,
        "suspects_dismissed": 0,
        "revenue_opportunity": 0.0,
        "meat_completeness_avg": None,
        "documentation_quality_score": None,
        "percentile_rank": None,
        "calculated_at": datetime.utcnow().isoformat(),
    }


def _calculate_percentile_rank(
    provider_id: int, year: int, average_raf: float | None
) -> float | None:
    """
    Return the percentile rank (0-100) of this provider's average RAF
    compared to all other providers that have a snapshot for the same year.
    """
    if average_raf is None:
        return None
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT average_raf
                FROM provider_scorecard_snapshots
                WHERE measurement_year = %s AND average_raf IS NOT NULL
                ORDER BY calculated_at DESC
                """,
                (year,),
            )
            rows = cur.fetchall()
        all_scores = [float(r["average_raf"]) for r in rows]
        if len(all_scores) < 2:
            return None
        below = sum(1 for s in all_scores if s < average_raf)
        return round(below / len(all_scores) * 100, 1)
    except Exception as exc:
        logger.debug("percentile_rank calculation failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Per-HCC performance
# ---------------------------------------------------------------------------


def calculate_hcc_performance(
    provider_id: int,
    year: int,
    tenant_id: Optional[int] = None,
) -> list[dict[str, Any]]:
    """
    For each HCC present in the provider's panel, compute:
    - total patients with that HCC coded
    - open suspects for that HCC (uncoded)
    - capture rate
    - estimated revenue impact of missed HCCs

    Returns list sorted by revenue_impact descending (highest-value gaps first).
    """

    if tenant_id is None:
        logger.warning(
            "provider_service.calculate_hcc_performance: no tenant_id provided, defaulting to 1"
        )
        tid = 1
    else:
        tid = int(tenant_id)

    with raf_cursor() as cur:
        cur.execute(
            f"SELECT patient_id FROM provider_patient_panel WHERE provider_id = %s AND {ACTIVE_PATIENTS_SUBQUERY}",
            (provider_id,),
        )
        panel = [r["patient_id"] for r in cur.fetchall()]

    if not panel:
        return []

    placeholders = ", ".join(["%s"] * len(panel))

    # Coded HCCs for this panel/year
    with raf_cursor() as cur:
        cur.execute(
            f"""
            SELECT hcc_code, COUNT(DISTINCT patient_id) AS coded_count
            FROM raf_patient_hcc
            WHERE measurement_year = %s AND patient_id IN ({placeholders})
            GROUP BY hcc_code
            """,
            tuple([year] + panel),
        )
        coded_rows = cur.fetchall()

    coded_by_hcc: dict[str, int] = {
        r["hcc_code"]: int(r["coded_count"]) for r in coded_rows
    }

    # Open suspects by HCC
    with raf_cursor() as cur:
        cur.execute(
            f"""
            SELECT hcc_code, COUNT(*) AS suspect_count
            FROM raf_suspect_conditions
            WHERE status = 'open'
              AND hcc_code IS NOT NULL
              AND patient_id IN ({placeholders})
            GROUP BY hcc_code
            """,
            tuple(panel),
        )
        suspect_rows = cur.fetchall()

    suspect_by_hcc: dict[str, int] = {
        str(r["hcc_code"]): int(r["suspect_count"]) for r in suspect_rows
    }

    # Merge both HCC sets
    all_hccs = set(coded_by_hcc.keys()) | set(suspect_by_hcc.keys())

    try:
        from hccinfhir.defaults import labels_default as _labels

        _V28 = "CMS-HCC Model V28"
    except ImportError:
        _labels = {}
        _V28 = ""

    results: list[dict[str, Any]] = []
    for hcc in all_hccs:
        coded = coded_by_hcc.get(hcc, 0)
        suspects = suspect_by_hcc.get(hcc, 0)
        possible = coded + suspects
        capture_rate = round(coded / possible, 4) if possible > 0 else None
        missed = suspects
        revenue_impact = round(missed * _HCC_BASE_RATE, 2)

        code_clean = str(hcc).replace("HCC", "").strip()
        label = _labels.get((code_clean, _V28)) or f"HCC {code_clean}"

        results.append(
            {
                "hcc_code": hcc,
                "hcc_label": label,
                "coded_patients": coded,
                "open_suspects": suspects,
                "possible_patients": possible,
                "capture_rate": capture_rate,
                "missed_patients": missed,
                "revenue_impact": revenue_impact,
            }
        )

    results.sort(key=lambda x: x["revenue_impact"], reverse=True)
    return results


# ---------------------------------------------------------------------------
# Alert generation
# ---------------------------------------------------------------------------


def generate_provider_alerts(
    provider_id: int,
    tenant_id: Optional[int] = None,
) -> list[dict[str, Any]]:
    """
    Generate (and persist) alerts for a provider:

    1. suspect_condition   – open suspect conditions in the panel
    2. recapture_due       – chronic HCCs from prior year not yet recaptured
    3. meat_incomplete     – HCCs with incomplete MEAT documentation

    Existing active alerts are cleared before regenerating to avoid duplicates.
    Returns the list of newly created alert records.
    """

    if tenant_id is None:
        logger.warning(
            "provider_service.generate_provider_alerts: no tenant_id provided, defaulting to 1"
        )
        tid = 1
    else:
        tid = int(tenant_id)

    year = date.today().year

    with raf_cursor() as cur:
        cur.execute(
            f"SELECT patient_id FROM provider_patient_panel WHERE provider_id = %s AND {ACTIVE_PATIENTS_SUBQUERY}",
            (provider_id,),
        )
        panel = [r["patient_id"] for r in cur.fetchall()]

    if not panel:
        return []

    placeholders = ", ".join(["%s"] * len(panel))

    # Clear stale active alerts for this provider
    with raf_cursor() as cur:
        cur.execute(
            "DELETE FROM provider_alerts WHERE provider_id = %s AND status = 'active'",
            (provider_id,),
        )

    alerts_to_insert: list[tuple] = []

    # --- 1. Suspect condition alerts ---
    try:
        with raf_cursor() as cur:
            cur.execute(
                f"""
                SELECT patient_id, condition, icd10_code, hcc_code, confidence_score
                FROM raf_suspect_conditions
                WHERE status = 'open'
                  AND patient_id IN ({placeholders})
                ORDER BY confidence_score DESC
                LIMIT 200
                """,
                tuple(panel),
            )
            suspects = cur.fetchall()

        for s in suspects:
            title = (
                f"Open suspect: {s.get('condition', s.get('icd10_code', 'Unknown'))}"
            )
            severity = "high" if (s.get("confidence_score") or 0) >= 0.8 else "medium"
            alerts_to_insert.append(
                (
                    provider_id,
                    int(s["patient_id"]),
                    "suspect_condition",
                    severity,
                    title,
                    f"Confidence: {round(float(s.get('confidence_score') or 0) * 100)}%  |  HCC: {s.get('hcc_code') or 'N/A'}",
                    str(s.get("hcc_code") or ""),
                    str(s.get("icd10_code") or ""),
                )
            )
    except Exception as exc:
        logger.warning("generate_alerts suspect query failed: %s", exc)

    # --- 2. Recapture-due alerts ---
    try:
        prior_year = year - 1
        with raf_cursor() as cur:
            cur.execute(
                f"""
                SELECT ph.patient_id, ph.hcc_code
                FROM raf_patient_hcc ph
                WHERE ph.measurement_year = %s
                  AND ph.patient_id IN ({placeholders})
                  AND NOT EXISTS (
                      SELECT 1 FROM raf_patient_hcc curr
                      WHERE curr.patient_id = ph.patient_id
                        AND curr.hcc_code   = ph.hcc_code
                        AND curr.measurement_year = %s
                  )
                ORDER BY ph.patient_id
                LIMIT 200
                """,
                tuple([prior_year] + panel + [year]),
            )
            recapture_rows = cur.fetchall()

        try:
            from hccinfhir.defaults import labels_default as _labels

            _V28 = "CMS-HCC Model V28"
        except ImportError:
            _labels = {}
            _V28 = ""

        for r in recapture_rows:
            hcc = str(r["hcc_code"])
            code_clean = hcc.replace("HCC", "").strip()
            label = _labels.get((code_clean, _V28)) or f"HCC {code_clean}"
            alerts_to_insert.append(
                (
                    provider_id,
                    int(r["patient_id"]),
                    "recapture_due",
                    "high",
                    f"Recapture due: {label}",
                    f"HCC {hcc} was documented in {prior_year} but not yet recaptured in {year}.",
                    hcc,
                    "",
                )
            )
    except Exception as exc:
        logger.warning("generate_alerts recapture query failed: %s", exc)

    # --- 3. MEAT incomplete alerts ---
    try:
        with raf_cursor() as cur:
            cur.execute(
                f"""
                SELECT patient_id, hcc_code, meat_status
                FROM raf_patient_hcc
                WHERE measurement_year = %s
                  AND meat_status IN ('missing', 'incomplete')
                  AND patient_id IN ({placeholders})
                ORDER BY patient_id
                LIMIT 200
                """,
                tuple([year] + panel),
            )
            meat_rows = cur.fetchall()

        for r in meat_rows:
            hcc = str(r["hcc_code"])
            alerts_to_insert.append(
                (
                    provider_id,
                    int(r["patient_id"]),
                    "meat_incomplete",
                    "medium",
                    f"Incomplete MEAT for HCC {hcc}",
                    f"HCC {hcc} lacks sufficient MEAT documentation for year {year}.",
                    hcc,
                    "",
                )
            )
    except Exception as exc:
        logger.debug(
            "generate_alerts MEAT query failed (column may not exist): %s", exc
        )

    # Bulk insert
    if alerts_to_insert:
        with raf_cursor() as cur:
            cur.executemany(
                """
                INSERT INTO provider_alerts
                    (provider_id, patient_id, alert_type, severity,
                     title, description, hcc_code, icd10_code)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                alerts_to_insert,
            )

    return get_provider_alerts(provider_id)


def get_provider_alerts(
    provider_id: int, status: str = "active"
) -> list[dict[str, Any]]:
    """Return active (or all) alerts for a provider."""

    with raf_cursor() as cur:
        if status == "all":
            cur.execute(
                "SELECT * FROM provider_alerts WHERE provider_id = %s ORDER BY created_at DESC",
                (provider_id,),
            )
        else:
            cur.execute(
                "SELECT * FROM provider_alerts WHERE provider_id = %s AND status = %s ORDER BY created_at DESC",
                (provider_id, status),
            )
        rows = cur.fetchall()
    return [_serialize_alert(r) for r in rows]


def acknowledge_alert(provider_id: int, alert_id: int) -> dict[str, Any] | None:
    """Mark an alert as acknowledged."""

    with raf_cursor() as cur:
        cur.execute(
            """
            UPDATE provider_alerts
            SET status = 'acknowledged', acknowledged_at = NOW()
            WHERE id = %s AND provider_id = %s
            """,
            (alert_id, provider_id),
        )
        if cur.rowcount == 0:
            return None
        cur.execute("SELECT * FROM provider_alerts WHERE id = %s", (alert_id,))
        row = cur.fetchone()
    return _serialize_alert(row) if row else None


def _serialize_alert(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "provider_id": row["provider_id"],
        "patient_id": row.get("patient_id"),
        "alert_type": row["alert_type"],
        "severity": row["severity"],
        "title": row["title"],
        "description": row.get("description"),
        "hcc_code": row.get("hcc_code") or None,
        "icd10_code": row.get("icd10_code") or None,
        "status": row["status"],
        "acknowledged_at": str(row.get("acknowledged_at") or ""),
        "created_at": str(row.get("created_at", "")),
    }


# ---------------------------------------------------------------------------
# Leaderboard and summary
# ---------------------------------------------------------------------------


def get_leaderboard(year: int) -> list[dict[str, Any]]:
    """
    Return all providers ranked by average_raf descending for the given year.
    Uses the latest scorecard snapshot per provider.
    """

    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT
                pss.*,
                p.first_name,
                p.last_name,
                p.specialty,
                p.npi,
                pss.meat_completeness_avg
            FROM provider_scorecard_snapshots pss
            JOIN providers p ON p.id = pss.provider_id
            INNER JOIN (
                SELECT provider_id, MAX(calculated_at) AS latest
                FROM provider_scorecard_snapshots
                WHERE measurement_year = %s
                GROUP BY provider_id
            ) lx ON pss.provider_id = lx.provider_id
               AND pss.calculated_at = lx.latest
            WHERE pss.measurement_year = %s
            ORDER BY pss.average_raf DESC
            """,
            (year, year),
        )
        rows = cur.fetchall()

    # Map specialty to category
    _PCP_SPECIALTIES = {"Internal Medicine", "Family Medicine", "General Practice", "Geriatrics"}
    _HOSPITALIST_SPECIALTIES = {"Hospital Medicine", "Hospitalist"}

    def _specialty_category(spec: str | None) -> str:
        if not spec:
            return "PCP"
        if spec in _PCP_SPECIALTIES:
            return "PCP"
        if spec in _HOSPITALIST_SPECIALTIES:
            return "Hospitalist"
        return "Specialist"

    result: list[dict[str, Any]] = []
    for rank, row in enumerate(rows, start=1):
        spec = row.get("specialty") or ""
        result.append(
            {
                "rank": rank,
                "provider_id": row["provider_id"],
                "first_name": row.get("first_name", ""),
                "last_name": row.get("last_name", ""),
                "provider_name": f"{row['first_name']} {row['last_name']}".strip(),
                "credential": "MD",
                "specialty": spec,
                "specialty_category": _specialty_category(spec),
                "practice_name": "Sunrise Health Partners",
                "npi": row.get("npi"),
                "patient_count": row["total_patients"],
                "avg_raf_score": float(row["average_raf"])
                if row["average_raf"] is not None
                else None,
                "hcc_capture_rate": float(row["hcc_capture_rate"])
                if row["hcc_capture_rate"] is not None
                else None,
                "recapture_rate": float(row["recapture_rate"])
                if row["recapture_rate"] is not None
                else None,
                "meat_score": float(row["meat_completeness_avg"])
                if row.get("meat_completeness_avg") is not None
                else None,
                "revenue_opportunity": float(row["revenue_opportunity"])
                if row["revenue_opportunity"] is not None
                else None,
                "documentation_quality_score": float(row["documentation_quality_score"])
                if row["documentation_quality_score"] is not None
                else None,
                "percentile_rank": float(row["percentile_rank"])
                if row["percentile_rank"] is not None
                else None,
                "calculated_at": str(row.get("calculated_at", "")),
            }
        )
    return result


def get_providers_summary(tenant_id: Optional[int] = None) -> dict[str, Any]:
    """Return aggregate statistics across all active providers."""

    if tenant_id is None:
        logger.warning(
            "provider_service.get_providers_summary: no tenant_id provided, defaulting to 1"
        )
        tid = 1
    else:
        tid = int(tenant_id)

    year = date.today().year

    with raf_cursor() as cur:
        cur.execute("SELECT COUNT(*) AS cnt FROM providers WHERE status = 'active'")
        row = cur.fetchone()
        total_providers = int(row["cnt"]) if row else 0

    with raf_cursor() as cur:
        _frag, _fparams = active_patients_subquery(tid)
        cur.execute(
            f"SELECT COUNT(DISTINCT patient_id) AS cnt FROM provider_patient_panel WHERE {_frag}",
            _fparams,
        )
        row = cur.fetchone()
        total_attributed = int(row["cnt"]) if row else 0

    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT
                AVG(average_raf)                AS avg_raf,
                AVG(hcc_capture_rate)           AS avg_capture,
                AVG(recapture_rate)             AS avg_recapture,
                SUM(revenue_opportunity)        AS total_revenue_opp,
                AVG(documentation_quality_score) AS avg_doc_quality
            FROM provider_scorecard_snapshots pss
            INNER JOIN (
                SELECT provider_id, MAX(calculated_at) AS latest
                FROM provider_scorecard_snapshots
                WHERE measurement_year = %s
                GROUP BY provider_id
            ) lx ON pss.provider_id = lx.provider_id
               AND pss.calculated_at = lx.latest
            WHERE pss.measurement_year = %s
            """,
            (year, year),
        )
        row = cur.fetchone()

    def _f(v: Any) -> float | None:
        return round(float(v), 4) if v is not None else None

    avg_raf = _f(row["avg_raf"]) if row else None
    avg_capture = _f(row["avg_capture"]) if row else None
    total_rev = round(float(row["total_revenue_opp"]), 2) if row and row["total_revenue_opp"] else 0.0
    avg_doc = _f(row["avg_doc_quality"]) if row else None

    return {
        "measurement_year": year,
        # Names the frontend expects
        "total_providers": total_providers,
        "avg_raf_score": avg_raf,
        "avg_capture_rate": avg_capture,
        "total_revenue_opportunity": total_rev,
        "avg_meat_completeness": avg_doc,
        # Keep legacy names for backward compatibility
        "total_active_providers": total_providers,
        "total_attributed_patients": total_attributed,
        "average_raf_across_providers": avg_raf,
        "average_hcc_capture_rate": avg_capture,
        "average_recapture_rate": _f(row["avg_recapture"]) if row else None,
        "average_documentation_quality": avg_doc,
    }
