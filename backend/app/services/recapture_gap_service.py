"""
Recapture Gap Service

Detects HCC recapture gaps by comparing prior-year vs. current-year HCC presence
per patient, persists them in the ``recapture_gaps`` table, and provides query
and summary helpers used by bundle exports (CMS Bundle 6).

Table DDL (run once via migration):

    CREATE TABLE IF NOT EXISTS recapture_gaps (
        id                  INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
        patient_id          VARCHAR(64)  NOT NULL,
        tenant_id           VARCHAR(64)  NOT NULL,
        hcc_code            VARCHAR(32)  NOT NULL,
        icd10_code          VARCHAR(16)  NOT NULL,
        prior_year          SMALLINT     NOT NULL,
        current_year        SMALLINT     NOT NULL,
        status              ENUM('open','recaptured','dismissed') NOT NULL DEFAULT 'open',
        last_encounter_date DATE         NULL,
        provider_npi        VARCHAR(20)  NULL,
        revenue_impact      DECIMAL(10,2) NOT NULL DEFAULT 0.00,
        resolved_at         DATETIME     NULL,
        resolved_by         VARCHAR(128) NULL,
        created_at          DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at          DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
                                         ON UPDATE CURRENT_TIMESTAMP,
        UNIQUE KEY uq_gap (patient_id, hcc_code, prior_year, current_year)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.db import raf_cursor
from app.services.metrics_service import revenue_at_risk as _canonical_revenue_at_risk

logger = logging.getLogger(__name__)

# Revenue assumed per open recapture gap (adjustable via config in future)
_REVENUE_IMPACT_PER_GAP: float = 3000.00


# ---------------------------------------------------------------------------
# 1. detect_and_persist_gaps
# ---------------------------------------------------------------------------

def detect_and_persist_gaps(
    tenant_id: str,
    prior_year: int = 2025,
    current_year: int = 2026,
) -> dict[str, int]:
    """Compare prior-year HCCs against current-year and persist any gaps.

    A gap is an HCC that appears for a patient in ``prior_year`` but has no
    matching row in ``current_year``.  Each gap is inserted with
    status='open' and a fixed revenue_impact.  The UNIQUE KEY on
    (patient_id, hcc_code, prior_year, current_year) makes INSERT IGNORE
    idempotent so repeated calls are safe.

    Args:
        tenant_id:    Tenant scope for the query.
        prior_year:   Model year considered the baseline.
        current_year: Model year to check for recapture.

    Returns:
        {"new_gaps": N, "total_open": N}
    """
    # Pull prior-year HCCs alongside the best available provider NPI for the
    # patient (from provider_patient_panel + providers).  The LEFT JOIN on the
    # current-year HCC table lets us filter for missing recaptures in Python
    # to avoid a NOT-EXISTS subquery that is harder to read.
    #
    # model_version filter (migration 028): raf_patient_hcc gained a
    # model_version column (V24 | V28) in migration 028.  The same HCC number
    # means different clinical content under V24 vs V28, so gap detection MUST
    # restrict both sides to the same model version.  For payment years >= 2025
    # CMS mandates V28; pre-2025 rows used V24.
    #
    # icd10_codes is a JSON array; we extract the first element for the gap
    # record.  The column is named measurement_year (not model_year) per the
    # canonical schema (see database/schema.sql).
    prior_model_clause = " AND ph.model_version = 'V28'" if prior_year >= 2025 else " AND ph.model_version = 'V24'"
    current_model_clause = " AND c.model_version = 'V28'" if current_year >= 2025 else " AND c.model_version = 'V24'"

    detect_sql = f"""
        SELECT
            p.prior_patient_id          AS patient_id,
            p.prior_hcc_code            AS hcc_code,
            p.prior_icd10_code          AS icd10_code,
            pr.npi                      AS provider_npi,
            c.hcc_code                  AS current_hcc_code
        FROM (
            SELECT
                ph.patient_id                                   AS prior_patient_id,
                ph.hcc_code                                     AS prior_hcc_code,
                JSON_UNQUOTE(JSON_EXTRACT(ph.icd10_codes, '$[0]'))
                                                                AS prior_icd10_code
            FROM raf_patient_hcc ph
            WHERE ph.tenant_id       = %s
              AND ph.measurement_year = %s
              {prior_model_clause}
        ) p
        LEFT JOIN raf_patient_hcc c
               ON c.patient_id       = p.prior_patient_id
              AND c.hcc_code         = p.prior_hcc_code
              AND c.tenant_id        = %s
              AND c.measurement_year = %s
              {current_model_clause}
        LEFT JOIN provider_patient_panel ppp
               ON ppp.patient_id = p.prior_patient_id
        LEFT JOIN providers pr
               ON pr.id = ppp.provider_id
    """

    insert_sql = """
        INSERT IGNORE INTO recapture_gaps
            (patient_id, tenant_id, hcc_code, icd10_code,
             prior_year, current_year, status, provider_npi, revenue_impact)
        VALUES (%s, %s, %s, %s, %s, %s, 'open', %s, %s)
    """

    count_open_sql = """
        SELECT COUNT(*) AS total_open
        FROM recapture_gaps
        WHERE tenant_id    = %s
          AND prior_year   = %s
          AND current_year = %s
          AND status       = 'open'
    """

    new_gaps = 0

    with raf_cursor() as cursor:
        cursor.execute(detect_sql, (tenant_id, prior_year, tenant_id, current_year))
        rows = cursor.fetchall()

        batch: list[tuple] = []
        seen: set[tuple] = set()

        for row in rows:
            # Only insert where the current-year HCC is absent
            if row["current_hcc_code"] is not None:
                continue

            key = (row["patient_id"], row["hcc_code"])
            if key in seen:
                # De-duplicate within the batch (multiple providers per patient)
                continue
            seen.add(key)

            batch.append((
                row["patient_id"],
                tenant_id,
                row["hcc_code"],
                row["icd10_code"],
                prior_year,
                current_year,
                row["provider_npi"],
                _REVENUE_IMPACT_PER_GAP,
            ))

        if batch:
            cursor.executemany(insert_sql, batch)
            new_gaps = cursor.rowcount  # rows actually inserted (IGNORE skips dupes)

        cursor.execute(count_open_sql, (tenant_id, prior_year, current_year))
        total_open = cursor.fetchone()["total_open"]

    logger.info(
        "detect_and_persist_gaps tenant=%s prior=%s current=%s new=%d total_open=%d",
        tenant_id, prior_year, current_year, new_gaps, total_open,
    )
    return {"new_gaps": new_gaps, "total_open": total_open}


# ---------------------------------------------------------------------------
# 2. resolve_gap
# ---------------------------------------------------------------------------

def resolve_gap(gap_id: int, status: str, resolved_by: str) -> bool:
    """Transition a gap to 'recaptured' or 'dismissed'.

    Args:
        gap_id:      Primary key of the recapture_gaps row.
        status:      Target status — must be 'recaptured' or 'dismissed'.
        resolved_by: Username or user ID performing the resolution.

    Returns:
        True if the row was found and updated, False if gap_id did not exist.

    Raises:
        ValueError: If status is not an accepted terminal value.
    """
    allowed = {"recaptured", "dismissed"}
    if status not in allowed:
        raise ValueError(f"Invalid status '{status}'. Allowed: {allowed}")

    sql = """
        UPDATE recapture_gaps
           SET status      = %s,
               resolved_at = %s,
               resolved_by = %s
         WHERE id = %s
    """

    with raf_cursor() as cursor:
        cursor.execute(sql, (status, datetime.now(timezone.utc), resolved_by, gap_id))
        updated = cursor.rowcount

    if not updated:
        logger.warning("resolve_gap: gap_id=%d not found", gap_id)
        return False

    logger.info("resolve_gap: gap_id=%d status=%s by=%s", gap_id, status, resolved_by)
    return True


# ---------------------------------------------------------------------------
# 3. list_gaps
# ---------------------------------------------------------------------------

def list_gaps(
    tenant_id: str,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Return paginated recapture gaps for a tenant.

    Args:
        tenant_id: Tenant scope.
        status:    Optional filter — 'open', 'recaptured', or 'dismissed'.
        limit:     Page size (max rows returned).
        offset:    Rows to skip for pagination.

    Returns:
        List of gap dicts.
    """
    params: list[Any] = [tenant_id]
    status_clause = ""
    if status is not None:
        status_clause = "AND rg.status = %s"
        params.append(status)

    sql = f"""
        SELECT
            rg.id,
            rg.patient_id,
            rg.tenant_id,
            rg.hcc_code,
            rg.icd10_code,
            rg.prior_year,
            rg.current_year,
            rg.status,
            rg.last_encounter_date,
            rg.provider_npi,
            rg.revenue_impact,
            rg.resolved_at,
            rg.resolved_by,
            rg.created_at,
            rg.updated_at,
            CONCAT(pt.first_name, ' ', pt.last_name) AS patient_name
        FROM recapture_gaps rg
        LEFT JOIN patients pt
               ON pt.id = rg.patient_id
              AND pt.tenant_id = rg.tenant_id
        WHERE rg.tenant_id = %s
          {status_clause}
        ORDER BY rg.created_at DESC
        LIMIT %s OFFSET %s
    """
    params.extend([limit, offset])

    with raf_cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchall()


# ---------------------------------------------------------------------------
# 4. get_gap_stats
# ---------------------------------------------------------------------------

def get_gap_stats(tenant_id: str) -> dict[str, Any]:
    """Return aggregate gap statistics for a tenant.

    Returns:
        {
            "total_gaps": int,
            "open": int,
            "recaptured": int,
            "dismissed": int,
            "total_revenue_at_risk": float,   # canonical RAF-coefficient * CMS rate
            "total_revenue_at_risk_meta": dict,  # formula, version, last_computed_at
        }
    """
    sql = """
        SELECT
            COUNT(*)                                          AS total_gaps,
            SUM(status = 'open')                             AS open_count,
            SUM(status = 'recaptured')                       AS recaptured_count,
            SUM(status = 'dismissed')                        AS dismissed_count
        FROM recapture_gaps
        WHERE tenant_id = %s
    """

    with raf_cursor() as cursor:
        cursor.execute(sql, (tenant_id,))
        row = cursor.fetchone()

    # Canonical Revenue-at-Risk from metrics_service
    rar = _canonical_revenue_at_risk(tenant_id, scope="recapture")

    return {
        "total_gaps":                  int(row["total_gaps"] or 0),
        "open":                        int(row["open_count"] or 0),
        "recaptured":                  int(row["recaptured_count"] or 0),
        "dismissed":                   int(row["dismissed_count"] or 0),
        "total_revenue_at_risk":       rar["value"],
        "total_revenue_at_risk_meta":  rar["_meta"],
    }


# ---------------------------------------------------------------------------
# API-compatible wrappers used by app/routers/recapture_gaps.py
# ---------------------------------------------------------------------------

def detect_gaps(tenant_id: str, measurement_year: int) -> dict[str, Any]:
    """Wrapper: detect recapture gaps for (measurement_year-1) → measurement_year.

    Args:
        tenant_id:        Tenant scope.
        measurement_year: The current measurement year. Prior year is derived
                          as ``measurement_year - 1``.

    Returns:
        {"new_gaps": int, "total_open": int, "prior_year": int, "current_year": int}
    """
    prior_year = measurement_year - 1
    result = detect_and_persist_gaps(
        tenant_id=tenant_id,
        prior_year=prior_year,
        current_year=measurement_year,
    )
    result["prior_year"] = prior_year
    result["current_year"] = measurement_year
    return result


def get_patient_gaps(patient_id: int, tenant_id: str) -> list[dict[str, Any]]:
    """Return all open gaps for a specific patient, enriched with HCC description.

    Args:
        patient_id: Numeric patient PK.
        tenant_id:  Tenant scope.

    Returns:
        List of open gap dicts, each including ``hcc_description`` and ``raf_impact``.
    """
    sql = """
        SELECT
            rg.id,
            rg.patient_id,
            rg.hcc_code,
            rg.icd10_code,
            rg.prior_year,
            rg.current_year,
            rg.status,
            rg.last_encounter_date,
            rg.provider_npi,
            rg.revenue_impact  AS raf_impact,
            rg.created_at,
            rg.updated_at
        FROM recapture_gaps rg
        WHERE rg.tenant_id  = %s
          AND rg.patient_id = %s
          AND rg.status     = 'open'
        ORDER BY rg.revenue_impact DESC, rg.hcc_code
    """
    with raf_cursor() as cursor:
        cursor.execute(sql, (tenant_id, patient_id))
        rows = cursor.fetchall()

    # Attach HCC description from model_constants (best-effort; empty string on miss)
    try:
        from app.model_constants import (
            RXHCC_COEFFICIENTS,  # noqa: F401 — avoid circular
        )
    except ImportError:
        pass

    result: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["hcc_description"] = _hcc_description(str(row["hcc_code"]))
        # Normalise date to ISO string for JSON serialisation
        led = item.get("last_encounter_date")
        if led and hasattr(led, "isoformat"):
            item["last_encounter_date"] = led.isoformat()
        ca = item.get("created_at")
        if ca and hasattr(ca, "isoformat"):
            item["created_at"] = ca.isoformat()
        ua = item.get("updated_at")
        if ua and hasattr(ua, "isoformat"):
            item["updated_at"] = ua.isoformat()
        result.append(item)
    return result


def close_gap(gap_id: int, tenant_id: str) -> None:
    """Mark a gap as recaptured (closed) when the HCC is re-documented.

    Args:
        gap_id:    Primary key of the recapture_gaps row.
        tenant_id: Tenant scope — used as a safety guard so a tenant cannot
                   close another tenant's gap.

    Raises:
        ValueError: If the gap does not exist or belongs to a different tenant.
    """
    check_sql = "SELECT id FROM recapture_gaps WHERE id = %s AND tenant_id = %s"
    update_sql = """
        UPDATE recapture_gaps
           SET status      = 'recaptured',
               resolved_at = %s,
               resolved_by = 'system'
         WHERE id = %s
    """
    with raf_cursor() as cursor:
        cursor.execute(check_sql, (gap_id, tenant_id))
        if not cursor.fetchone():
            raise ValueError(f"Gap {gap_id} not found for tenant {tenant_id}")
        cursor.execute(update_sql, (datetime.now(timezone.utc), gap_id))
    logger.info("close_gap: gap_id=%d tenant=%s", gap_id, tenant_id)


def get_gap_summary(tenant_id: str) -> dict[str, Any]:
    """Return aggregate recapture gap statistics for a tenant.

    Includes top patients by revenue at risk and a per-HCC breakdown of open gaps.

    Returns::

        {
            "total_open_gaps":    int,
            "total_raf_at_risk":  float,
            "gaps_by_hcc":        [{"hcc_code": str, "count": int, "raf_at_risk": float}, ...],
            "top_patients_by_impact": [{"patient_id": int, "patient_name": str,
                                        "open_gaps": int, "raf_at_risk": float}, ...],
        }
    """
    stats_sql = """
        SELECT COUNT(*) AS total_open_gaps
        FROM recapture_gaps
        WHERE tenant_id = %s
          AND status    = 'open'
    """

    hcc_sql = """
        SELECT
            rg.hcc_code,
            COUNT(*)                                                    AS gap_count,
            COALESCE(SUM(ph.raf_coefficient), COUNT(*) * 0.15)         AS raf_at_risk
        FROM recapture_gaps rg
        LEFT JOIN raf_patient_hcc ph
               ON ph.patient_id       = rg.patient_id
              AND ph.hcc_code         = rg.hcc_code
              AND ph.measurement_year = rg.prior_year
              AND ph.tenant_id        = rg.tenant_id
        WHERE rg.tenant_id = %s
          AND rg.status    = 'open'
        GROUP BY rg.hcc_code
        ORDER BY raf_at_risk DESC
        LIMIT 20
    """

    patients_sql = """
        SELECT
            rg.patient_id,
            CONCAT(COALESCE(pt.first_name, ''), ' ', COALESCE(pt.last_name, '')) AS patient_name,
            COUNT(*)                                                    AS open_gaps,
            COALESCE(SUM(ph.raf_coefficient), COUNT(*) * 0.15)         AS raf_at_risk
        FROM recapture_gaps rg
        LEFT JOIN patients pt
               ON pt.id = rg.patient_id AND pt.tenant_id = rg.tenant_id
        LEFT JOIN raf_patient_hcc ph
               ON ph.patient_id       = rg.patient_id
              AND ph.hcc_code         = rg.hcc_code
              AND ph.measurement_year = rg.prior_year
              AND ph.tenant_id        = rg.tenant_id
        WHERE rg.tenant_id = %s
          AND rg.status    = 'open'
        GROUP BY rg.patient_id, patient_name
        ORDER BY raf_at_risk DESC
        LIMIT 10
    """

    with raf_cursor() as cursor:
        cursor.execute(stats_sql, (tenant_id,))
        stats_row = cursor.fetchone()

        cursor.execute(hcc_sql, (tenant_id,))
        hcc_rows = cursor.fetchall()

        cursor.execute(patients_sql, (tenant_id,))
        patient_rows = cursor.fetchall()

    # Canonical Revenue-at-Risk from metrics_service
    rar = _canonical_revenue_at_risk(tenant_id, scope="recapture")

    return {
        "total_open_gaps": int(stats_row["total_open_gaps"] or 0),
        "total_raf_at_risk": rar["_meta"]["total_raf_points"],
        "total_revenue_at_risk": rar["value"],
        "total_revenue_at_risk_meta": rar["_meta"],
        "gaps_by_hcc": [
            {
                "hcc_code": r["hcc_code"],
                "description": _hcc_description(str(r["hcc_code"])),
                "count": int(r["gap_count"]),
                "raf_at_risk": float(r["raf_at_risk"]),
            }
            for r in hcc_rows
        ],
        "top_patients_by_impact": [
            {
                "patient_id": r["patient_id"],
                "patient_name": (r["patient_name"] or "").strip() or "Unknown",
                "open_gaps": int(r["open_gaps"]),
                "raf_at_risk": float(r["raf_at_risk"]),
            }
            for r in patient_rows
        ],
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _hcc_description(hcc_code: str) -> str:
    """Return a human-readable label for an HCC code (best-effort)."""
    # Normalise: strip leading "HCC" prefix if present
    code = hcc_code.lstrip("HCC").lstrip("0")
    _LABELS: dict[str, str] = {
        "1": "HIV/AIDS",
        "2": "Septicemia / Severe Sepsis",
        "6": "Opportunistic Infections",
        "8": "Metastatic Cancer / Acute Leukemia",
        "9": "Lung, Upper Digestive Tract, and Other Severe Cancers",
        "10": "Lymphoma / Head, Neck, and Other Major Cancers",
        "11": "Colorectal, Bladder, and Other Cancers",
        "12": "Breast, Prostate, and Other Cancers and Tumors",
        "17": "Diabetes with Acute Complications",
        "18": "Diabetes with Chronic Complications",
        "19": "Diabetes without Complications",
        "21": "Protein-Calorie Malnutrition",
        "22": "Morbid Obesity",
        "23": "Other Significant Endocrine and Metabolic Disorders",
        "27": "End-Stage Liver Disease",
        "28": "Cirrhosis of Liver",
        "29": "Chronic Hepatitis",
        "33": "Intestinal Obstruction / Perforation",
        "34": "Chronic Pancreatitis",
        "35": "Inflammatory Bowel Disease",
        "39": "Bone/Joint/Muscle Infections/Necrosis",
        "40": "Rheumatoid Arthritis and Inflammatory Connective Tissue Disease",
        "46": "Severe Hematological Disorders",
        "47": "Disorders of Immunity",
        "48": "Coagulation Defects and Other Specified Hematological Disorders",
        "54": "Drug / Alcohol Psychosis",
        "55": "Drug / Alcohol Dependence",
        "57": "Schizophrenia",
        "58": "Major Depressive, Bipolar, and Paranoid Disorders",
        "70": "Quadriplegia",
        "71": "Paraplegia",
        "72": "Spinal Cord Disorders / Injuries",
        "73": "Amyotrophic Lateral Sclerosis / Other Motor Neuron Disease",
        "74": "Cerebral Palsy",
        "75": "Myasthenia Gravis / Myoneural Disorders / Guillain-Barré Syndrome",
        "76": "Muscular Dystrophy",
        "77": "Multiple Sclerosis",
        "78": "Parkinson's and Huntington's Diseases",
        "79": "Seizure Disorders and Convulsions",
        "80": "Coma, Brain Compression / Anoxic Damage",
        "82": "Respirator Dependence / Tracheostomy Status",
        "83": "Respiratory Arrest",
        "84": "Cardio-Respiratory Failure and Shock",
        "85": "Congestive Heart Failure",
        "86": "Acute Myocardial Infarction",
        "87": "Unstable Angina / Other Acute Ischemic Heart Disease",
        "88": "Angina Pectoris / Old Myocardial Infarction",
        "96": "Specified Heart Arrhythmias",
        "99": "Cerebral Hemorrhage",
        "100": "Ischemic or Unspecified Stroke",
        "103": "Hemiplegia / Hemiparesis",
        "104": "Monoplegia, Other Paralytic Syndromes",
        "106": "Atherosclerosis of the Extremities with Ulceration / Gangrene",
        "107": "Vascular Disease with Complications",
        "108": "Vascular Disease",
        "110": "Cystic Fibrosis",
        "111": "Chronic Obstructive Pulmonary Disease",
        "112": "Fibrosis of Lung / Other Chronic Lung Disorders",
        "114": "Aspiration / Specified Bacterial Pneumonias",
        "115": "Pneumococcal Pneumonia, Empyema, Lung Abscess",
        "122": "Proliferative Diabetic Retinopathy / Vitreous Hemorrhage",
        "124": "Exudative Macular Degeneration",
        "134": "Dialysis Status",
        "135": "Acute Renal Failure",
        "136": "Chronic Kidney Disease Stage 5",
        "137": "Chronic Kidney Disease Stage 4",
        "138": "Chronic Kidney Disease Stage 3",
        "157": "Pressure Ulcer of Skin with Necrosis Through to Muscle",
        "158": "Pressure Ulcer of Skin with Full Thickness Skin Loss",
        "161": "Chronic Ulcer of Skin, Except Pressure",
        "162": "Severe Skin Burn / Condition",
        "166": "Severe Head Injury",
        "167": "Major Head Injury",
        "169": "Vertebral Fractures without Spinal Cord Injury",
        "170": "Hip Fracture / Dislocation",
        "176": "Complications of Specified Implanted Device or Graft",
        "186": "Major Organ Transplant / Replacement Status",
    }
    return _LABELS.get(code, f"HCC {hcc_code}")


# ---------------------------------------------------------------------------
# 5. get_recapture_bundle
# ---------------------------------------------------------------------------

def get_recapture_bundle(tenant_id: str) -> list[dict[str, Any]]:
    """Return CMS Bundle 6 payload for all gaps belonging to a tenant.

    Each row maps directly to the CMS Bundle 6 fields:
        Patient_ID, HCC, Prior_Year, Current_Status,
        Last_Encounter_Date, Provider_NPI.

    Only rows with status 'open' or 'recaptured' are included (dismissed gaps
    are excluded from regulatory submissions).

    Args:
        tenant_id: Tenant scope.

    Returns:
        List of bundle-ready dicts.
    """
    sql = """
        SELECT
            rg.patient_id            AS Patient_ID,
            rg.hcc_code              AS HCC,
            rg.icd10_code            AS ICD10,
            rg.prior_year            AS Prior_Year,
            rg.current_year          AS Current_Year,
            rg.status                AS Current_Status,
            rg.last_encounter_date   AS Last_Encounter_Date,
            rg.provider_npi          AS Provider_NPI,
            rg.revenue_impact        AS Revenue_Impact
        FROM recapture_gaps rg
        WHERE rg.tenant_id = %s
          AND rg.status IN ('open', 'recaptured')
        ORDER BY rg.patient_id, rg.hcc_code
    """

    with raf_cursor() as cursor:
        cursor.execute(sql, (tenant_id,))
        rows = cursor.fetchall()

    # Normalise date fields to ISO strings for JSON serialisation
    bundle: list[dict[str, Any]] = []
    for row in rows:
        led = row["Last_Encounter_Date"]
        bundle.append({
            "Patient_ID":          row["Patient_ID"],
            "HCC":                 row["HCC"],
            "ICD10":               row["ICD10"],
            "Prior_Year":          row["Prior_Year"],
            "Current_Year":        row["Current_Year"],
            "Current_Status":      row["Current_Status"],
            "Last_Encounter_Date": led.isoformat() if led else None,
            "Provider_NPI":        row["Provider_NPI"],
            "Revenue_Impact":      float(row["Revenue_Impact"]),
        })

    return bundle
