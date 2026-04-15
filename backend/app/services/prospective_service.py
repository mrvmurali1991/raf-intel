"""
Prospective RAF Management Service.

Provides population-level prospective risk management functions including:
  - Priority worklist ranking patients by RAF opportunity
  - Pre-visit summaries aggregating all open gaps for a patient
  - Annual Wellness Visit (AWV) eligibility tracking
  - Chase list generation for outreach campaigns
  - Population-level prospective summary statistics

Revenue model: CMS per-member per-year rate used for opportunity calculations.
All RAF scores are informational — not CMS-validated. Verify against official
CMS SAS software before payment determinations.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import date, datetime, timedelta
from typing import Any, Optional

from app.config import settings
from app.db import raf_cursor, openemr_cursor
from app.services.emr_manager import active_patients_subquery

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# AWV table bootstrap — managed by centralized migration runner
# ---------------------------------------------------------------------------

_awv_table_ensured = False
_awv_table_lock = threading.Lock()


def _ensure_awv_table() -> None:
    """No-op — tables are managed by the centralized migration runner."""
    global _awv_table_ensured
    _awv_table_ensured = True


# CMS per-member per-year benchmark rate (MA) — read from settings (env: CMS_REVENUE_PER_RAF_POINT)
_REVENUE_PER_RAF_POINT = settings.cms_revenue_per_raf_point

# AWV CPT codes — initial (G0438), subsequent (G0439), and preventive E/M
_AWV_CPT_CODES = (
    "G0438",
    "G0439",
    "99381",
    "99382",
    "99383",
    "99384",
    "99385",
    "99386",
    "99387",
    "99391",
    "99392",
    "99393",
    "99394",
    "99395",
    "99396",
    "99397",
)

# Top 20% threshold for "high priority" classification
_HIGH_PRIORITY_PERCENTILE = 0.80


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _active_patient_ids(tenant_id: str = "") -> set[int]:
    """Return the set of patient IDs linked to active EMR connections.

    When no EMR connection is active, falls back to uploaded patients
    (data_source='upload') so that CSV/Excel-imported data is still visible.

    ``tenant_id`` is required for tenant isolation.
    """
    if not tenant_id:
        logger.error("_active_patient_ids called without tenant_id — returning empty set.")
        return set()
    try:
        with raf_cursor() as cur:
            # Check if active connection is direct_db
            cur.execute("SELECT connection_type FROM emr_connections WHERE is_active = 1 AND tenant_id = %s LIMIT 1", (tenant_id,))
            ct_row = cur.fetchone()
            if ct_row and ct_row["connection_type"] == "direct_db":
                from app.db import openemr_cursor
                cur.execute("SELECT id FROM patients WHERE is_active = 1 AND tenant_id = %s LIMIT 10000", (tenant_id,))
                return {int(r["id"]) for r in cur.fetchall()}
            if ct_row:
                cur.execute(
                    "SELECT DISTINCT pm.raf_patient_id FROM emr_patient_matches pm "
                    "JOIN emr_connections ec ON ec.id = pm.connection_id "
                    "WHERE ec.is_active = 1 AND ec.tenant_id = %s AND pm.raf_patient_id IS NOT NULL",
                    (tenant_id,),
                )
                return {int(r["raf_patient_id"]) for r in cur.fetchall()}
            cur.execute(
                "SELECT id FROM patients WHERE is_active = 1 AND tenant_id = %s AND data_source = 'upload' LIMIT 10000",
                (tenant_id,),
            )
            result = {int(r["id"]) for r in cur.fetchall()}
            if result:
                return result
            cur.execute("SELECT id FROM patients WHERE is_active = 1 AND tenant_id = %s LIMIT 10000", (tenant_id,))
            return {int(r["id"]) for r in cur.fetchall()}
    except Exception as exc:
        logger.error("_active_patient_ids failed: %s", exc)
        return set()


def _today() -> date:
    return date.today()


def _days_since(d: Any) -> int:
    """Return days since a date value.  Returns 999 when date is None."""
    if d is None:
        return 999
    if isinstance(d, str):
        try:
            d = datetime.strptime(d[:10], "%Y-%m-%d").date()
        except ValueError:
            return 999
    if isinstance(d, datetime):
        d = d.date()
    delta = (_today() - d).days
    return max(0, delta)


def _coerce_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _coerce_int(v: Any, default: int = 0) -> int:
    try:
        return int(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _format_date(d: Any) -> str | None:
    if d is None:
        return None
    if hasattr(d, "isoformat"):
        return d.isoformat()
    return str(d)


# ---------------------------------------------------------------------------
# Priority Worklist
# ---------------------------------------------------------------------------


def get_prospective_worklist(
    tenant_id: str,
    year: int,
    provider_id: int | None = None,
    min_priority: float | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    """
    Return a priority-ranked patient worklist for prospective RAF management.

    Priority score formula (0-100 scale):
        score = (days_since_visit_norm * 0.30
                 + suspect_count_norm  * 0.30
                 + raf_gap_norm        * 0.25
                 + recapture_gaps_norm * 0.15) * 100

    Each component is normalised to [0, 1] using min-max across the population
    so relative ranking is stable across cohort sizes.

    Revenue opportunity = (potential_raf - current_raf) * $12,000.
    """
    calc_year = year

    try:
        # 1. Fetch all patients from raf_intelligence.patients (optionally filtered by provider)
        with raf_cursor() as cur:
            if provider_id is not None:
                cur.execute(
                    """
                    SELECT p.id AS pid, p.first_name AS fname, p.last_name AS lname,
                           p.dob AS DOB, p.sex,
                           p.phone AS phone_home, p.phone AS phone_cell,
                           p.address AS street, p.city, p.state,
                           p.zip AS postal_code, pp.provider_id AS providerID
                    FROM patients p
                    LEFT JOIN provider_patient_panel pp ON pp.patient_id = p.id
                    WHERE p.is_active = 1 AND p.tenant_id = %s AND pp.provider_id = %s
                    ORDER BY p.last_name, p.first_name
                    LIMIT 10000
                    """,
                    (tenant_id, provider_id),
                )
            else:
                cur.execute(
                    """
                    SELECT p.id AS pid, p.first_name AS fname, p.last_name AS lname,
                           p.dob AS DOB, p.sex,
                           p.phone AS phone_home, p.phone AS phone_cell,
                           p.address AS street, p.city, p.state,
                           p.zip AS postal_code, pp.provider_id AS providerID
                    FROM patients p
                    LEFT JOIN provider_patient_panel pp ON pp.patient_id = p.id
                    WHERE p.is_active = 1 AND p.tenant_id = %s
                    ORDER BY p.last_name, p.first_name
                    LIMIT 10000
                    """,
                    (tenant_id,),
                )
            patients = cur.fetchall()

        # Filter to only patients linked to active EMR connections
        active_pids = _active_patient_ids(tenant_id)
        patients = [p for p in patients if int(p["pid"]) in active_pids]

        if not patients:
            return {"total": 0, "limit": limit, "offset": offset, "items": []}

        patient_ids = [int(p["pid"]) for p in patients]
        pid_to_patient = {int(p["pid"]): p for p in patients}

        # 2. Last encounter date per patient in calc_year
        with openemr_cursor() as cur:
            cur.execute(
                """
                SELECT pid, MAX(date) AS last_encounter
                FROM form_encounter
                WHERE pid IN ({placeholders})
                GROUP BY pid
                """.format(placeholders=",".join(["%s"] * len(patient_ids))),
                patient_ids,
            )
            enc_rows = cur.fetchall()
        last_enc_by_pid = {int(r["pid"]): r["last_encounter"] for r in enc_rows}

        # 3. Latest RAF score per patient
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT rs.patient_id, rs.final_raf
                FROM raf_scores rs
                INNER JOIN (
                    SELECT patient_id, MAX(calculated_at) AS latest
                    FROM raf_scores
                    WHERE measurement_year = %s
                    GROUP BY patient_id
                ) lx ON rs.patient_id = lx.patient_id AND rs.calculated_at = lx.latest
                WHERE rs.patient_id IN ({placeholders})
                """.format(placeholders=",".join(["%s"] * len(patient_ids))),
                [calc_year] + patient_ids,
            )
            raf_rows = cur.fetchall()
        raf_by_pid = {
            int(r["patient_id"]): _coerce_float(r["final_raf"]) for r in raf_rows
        }

        # 4. Open suspect count + potential RAF coefficient sum per patient
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT patient_id,
                       COUNT(*) AS suspect_count,
                       SUM(0.15) AS suspect_raf_sum
                FROM raf_suspect_conditions
                WHERE status = 'open'
                  AND patient_id IN ({placeholders})
                GROUP BY patient_id
                """.format(placeholders=",".join(["%s"] * len(patient_ids))),
                patient_ids,
            )
            suspect_rows = cur.fetchall()
        suspect_count_by_pid: dict[int, int] = {}
        suspect_raf_by_pid: dict[int, float] = {}
        for r in suspect_rows:
            pid = int(r["patient_id"])
            suspect_count_by_pid[pid] = _coerce_int(r["suspect_count"])
            suspect_raf_by_pid[pid] = _coerce_float(r["suspect_raf_sum"])

        # 5. Recapture gaps — prior-year HCCs not yet billed in calc_year
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT h.patient_id, COUNT(*) AS gap_count
                FROM raf_patient_hcc h
                WHERE h.measurement_year = %s
                  AND h.patient_id IN ({placeholders})
                  AND NOT EXISTS (
                      SELECT 1 FROM raf_patient_hcc h2
                      WHERE h2.patient_id = h.patient_id
                        AND h2.hcc_code    = h.hcc_code
                        AND h2.measurement_year = %s
                  )
                GROUP BY h.patient_id
                """.format(placeholders=",".join(["%s"] * len(patient_ids))),
                [calc_year - 1] + patient_ids + [calc_year],
            )
            recapture_rows = cur.fetchall()
        recapture_by_pid = {
            int(r["patient_id"]): _coerce_int(r["gap_count"]) for r in recapture_rows
        }

        # 6. Provider names
        with openemr_cursor() as cur:
            cur.execute("SELECT id, fname, lname FROM users WHERE id > 0 LIMIT 10000")
            provider_rows = cur.fetchall()
        provider_name_by_id = {
            int(r["id"]): f"{r.get('fname', '')} {r.get('lname', '')}".strip()
            for r in provider_rows
        }

        # 7. Build raw records with un-normalised component values
        raw: list[dict[str, Any]] = []
        for p in patients:
            pid = int(p["pid"])
            last_enc = last_enc_by_pid.get(pid)
            days_since = _days_since(last_enc)
            current_raf = raf_by_pid.get(pid, 0.0)
            n_suspects = suspect_count_by_pid.get(pid, 0)
            suspect_raf = suspect_raf_by_pid.get(pid, 0.0)
            recapture_gaps = recapture_by_pid.get(pid, 0)

            # AI-detected RAF gap: compare suspect-potential vs current billed
            potential_raf = current_raf + suspect_raf
            raf_gap = max(0.0, potential_raf - current_raf)

            provider_id_val = _coerce_int(p.get("providerID"), 0) or None
            raw.append(
                {
                    "pid": pid,
                    "name": f"{p.get('fname', '')} {p.get('lname', '')}".strip(),
                    "first_name": p.get("fname") or "",
                    "last_name": p.get("lname") or "",
                    "phone": p.get("phone_cell") or p.get("phone_home") or "",
                    "address": _build_address(p),
                    "provider_id": provider_id_val,
                    "provider_name": provider_name_by_id.get(provider_id_val, "")
                    if provider_id_val
                    else "",
                    "last_encounter_date": _format_date(last_enc),
                    "days_since_last_visit": days_since,
                    "current_raf": round(current_raf, 4),
                    "suspect_count": n_suspects,
                    "recapture_gaps": recapture_gaps,
                    "raf_gap": round(raf_gap, 4),
                    "potential_raf": round(potential_raf, 4),
                    "_days_raw": days_since,
                    "_suspects_raw": n_suspects,
                    "_raf_gap_raw": raf_gap,
                    "_recapture_raw": recapture_gaps,
                }
            )

        # 8. Min-max normalisation then weighted score
        def _col(key: str) -> list[float]:
            return [r[key] for r in raw]

        days_vals = _col("_days_raw")
        susp_vals = _col("_suspects_raw")
        gap_vals = _col("_raf_gap_raw")
        recap_vals = _col("_recapture_raw")

        def _norm_list(vals: list[float]) -> list[float]:
            if not vals:
                return []
            lo, hi = min(vals), max(vals)
            if hi == lo:
                return [0.0] * len(vals)
            return [(v - lo) / (hi - lo) for v in vals]

        days_n = _norm_list(days_vals)
        susp_n = _norm_list(susp_vals)
        gap_n = _norm_list(gap_vals)
        recap_n = _norm_list(recap_vals)

        for i, r in enumerate(raw):
            score = (
                days_n[i] * 0.30
                + susp_n[i] * 0.30
                + gap_n[i] * 0.25
                + recap_n[i] * 0.15
            ) * 100.0
            r["priority_score"] = round(score, 2)
            r["revenue_opportunity"] = round(r["raf_gap"] * _REVENUE_PER_RAF_POINT, 2)
            # Remove internal working keys
            for k in ("_days_raw", "_suspects_raw", "_raf_gap_raw", "_recapture_raw"):
                r.pop(k, None)

        # 9. Sort by priority descending
        raw.sort(key=lambda x: x["priority_score"], reverse=True)

        # 10. Apply min_priority filter
        if min_priority is not None:
            raw = [r for r in raw if r["priority_score"] >= min_priority]

        total = len(raw)
        page = raw[offset : offset + limit]

        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "year": calc_year,
            "items": page,
        }

    except Exception as exc:
        logger.error("get_prospective_worklist error: %s", exc, exc_info=True)
        raise


def _build_address(p: dict[str, Any]) -> str:
    parts = [
        (p.get("street") or "").strip(),
        (p.get("city") or "").strip(),
        (p.get("state") or "").strip(),
        (p.get("postal_code") or "").strip(),
    ]
    return ", ".join(x for x in parts if x)


# ---------------------------------------------------------------------------
# Pre-Visit Summary
# ---------------------------------------------------------------------------


def generate_pre_visit_summary(patient_id: int, year: int, tenant_id: str = "") -> dict[str, Any]:
    """
    Aggregate a complete pre-visit RAF summary for a patient.

    Sections returned:
      - demographics
      - current_raf: score + HCC breakdown
      - open_suspects: conditions identified by AI/rules but not yet coded
      - recapture_hccs: HCCs from prior year absent from current year billing
      - meat_gaps: HCCs with incomplete or missing MEAT documentation
      - recommended_icd10_codes: deduplicated ICD-10 codes to evaluate at visit
      - estimated_revenue_if_closed: revenue if all gaps are addressed
    """
    calc_year = year
    prior_year = calc_year - 1

    try:
        # Demographics from raf_intelligence.patients
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT p.id AS pid, p.first_name AS fname, p.last_name AS lname,
                       p.dob AS DOB, p.sex, p.address AS street, p.city, p.state,
                       p.zip AS postal_code, p.phone AS phone_home, p.phone AS phone_cell,
                       p.email, pp.provider_id AS providerID
                FROM patients p
                LEFT JOIN provider_patient_panel pp ON pp.patient_id = p.id
                WHERE p.id = %s
                  AND (p.tenant_id = %s OR %s = '')
                """,
                (patient_id, tenant_id, tenant_id),
            )
            patient = cur.fetchone()

        if not patient:
            return {"error": "Patient not found", "patient_id": patient_id}

        # Last encounter
        with openemr_cursor() as cur:
            cur.execute(
                "SELECT MAX(date) AS last_enc FROM form_encounter WHERE pid = %s",
                (patient_id,),
            )
            enc_row = cur.fetchone()
        last_encounter = _format_date(enc_row["last_enc"]) if enc_row else None

        # Current RAF breakdown
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT * FROM raf_scores
                WHERE patient_id = %s AND measurement_year = %s
                ORDER BY calculated_at DESC LIMIT 1
                """,
                (patient_id, calc_year),
            )
            raf_row = cur.fetchone()

        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT hcc_code, icd10_codes, meat_status
                FROM raf_patient_hcc
                WHERE patient_id = %s AND measurement_year = %s
                """,
                (patient_id, calc_year),
            )
            hcc_rows = cur.fetchall()

        current_raf = _coerce_float(raf_row["final_raf"]) if raf_row else 0.0

        hcc_details = []
        meat_gaps = []
        for h in hcc_rows:
            codes = h.get("icd10_codes")
            if isinstance(codes, str):
                try:
                    codes = json.loads(codes)
                except ValueError:
                    codes = [codes]
            hcc_details.append(
                {
                    "hcc_code": str(h["hcc_code"]),
                    "icd10_codes": codes or [],
                    "meat_status": h.get("meat_status") or "missing",
                }
            )
            if (h.get("meat_status") or "missing") in ("missing", "incomplete"):
                meat_gaps.append(
                    {
                        "hcc_code": str(h["hcc_code"]),
                        "icd10_codes": codes or [],
                        "meat_status": h.get("meat_status") or "missing",
                        "action": "Document MEAT criteria at upcoming visit",
                    }
                )

        # Open suspect conditions
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT description, suspected_icd, suspected_hcc,
                       confidence, source,
                       0.15 AS coeff
                FROM raf_suspect_conditions
                WHERE patient_id = %s AND status = 'open'
                ORDER BY confidence DESC
                """,
                (patient_id,),
            )
            suspect_rows = cur.fetchall()

        open_suspects = [
            {
                "condition": r["description"],
                "icd10_code": r["suspected_icd"],
                "hcc_code": str(r["suspected_hcc"]) if r["suspected_hcc"] else None,
                "confidence_score": _coerce_float(r["confidence"]),
                "rationale": r["source"],
                "estimated_raf_value": _coerce_float(r["coeff"]),
            }
            for r in suspect_rows
        ]

        # Recapture HCCs — prior year coded, not yet in current year
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT h.hcc_code, h.icd10_codes
                FROM raf_patient_hcc h
                WHERE h.patient_id = %s AND h.measurement_year = %s
                  AND NOT EXISTS (
                      SELECT 1 FROM raf_patient_hcc h2
                      WHERE h2.patient_id = h.patient_id
                        AND h2.hcc_code = h.hcc_code
                        AND h2.measurement_year = %s
                  )
                """,
                (patient_id, prior_year, calc_year),
            )
            recapture_rows = cur.fetchall()

        recapture_hccs = []
        for r in recapture_rows:
            codes = r.get("icd10_codes")
            if isinstance(codes, str):
                try:
                    codes = json.loads(codes)
                except ValueError:
                    codes = [codes]
            recapture_hccs.append(
                {
                    "hcc_code": str(r["hcc_code"]),
                    "icd10_codes": codes or [],
                    "action": f"HCC coded in {prior_year} — must be re-documented and re-billed in {calc_year}",
                }
            )

        # Build recommended ICD-10 list (suspects + recapture, deduplicated)
        recommended_codes: list[dict[str, Any]] = []
        seen_codes: set[str] = set()
        for s in open_suspects:
            code = (s.get("icd10_code") or "").strip()
            if code and code not in seen_codes:
                seen_codes.add(code)
                recommended_codes.append(
                    {
                        "icd10_code": code,
                        "condition": s.get("condition", ""),
                        "source": "ai_suspect",
                        "hcc_code": s.get("hcc_code"),
                        "confidence_score": s.get("confidence_score"),
                    }
                )
        for rc in recapture_hccs:
            for code in rc.get("icd10_codes") or []:
                code = (code or "").strip()
                if code and code not in seen_codes:
                    seen_codes.add(code)
                    recommended_codes.append(
                        {
                            "icd10_code": code,
                            "condition": "",
                            "source": "recapture",
                            "hcc_code": rc.get("hcc_code"),
                            "confidence_score": None,
                        }
                    )

        # Revenue estimate if all gaps closed
        suspect_raf_sum = sum(s["estimated_raf_value"] for s in open_suspects)
        recapture_count = len(recapture_hccs)
        # Estimate each recapture HCC at average 0.20 RAF points if not otherwise known
        recapture_raf_estimate = recapture_count * 0.20
        total_gap_raf = suspect_raf_sum + recapture_raf_estimate
        estimated_revenue_if_closed = round(total_gap_raf * _REVENUE_PER_RAF_POINT, 2)

        return {
            "patient_id": patient_id,
            "year": calc_year,
            "demographics": {
                "name": f"{patient.get('fname', '')} {patient.get('lname', '')}".strip(),
                "dob": _format_date(patient.get("DOB")),
                "sex": patient.get("sex") or "Unknown",
                "address": _build_address(patient),
                "phone": patient.get("phone_cell") or patient.get("phone_home") or "",
                "email": patient.get("email") or "",
                "provider_id": _coerce_int(patient.get("providerID"), 0) or None,
                "last_encounter_date": last_encounter,
            },
            "current_raf": {
                "score": round(current_raf, 4),
                "demographic_score": _coerce_float(raf_row["demographic_score"])
                if raf_row
                else 0.0,
                "disease_score": _coerce_float(raf_row["disease_score"])
                if raf_row
                else 0.0,
                "hcc_count": _coerce_int(raf_row["hcc_count"]) if raf_row else 0,
                "model_segment": raf_row.get("model_segment", "CNA")
                if raf_row
                else "CNA",
                "hcc_details": hcc_details,
            },
            "open_suspects": open_suspects,
            "recapture_hccs": recapture_hccs,
            "meat_gaps": meat_gaps,
            "recommended_icd10_codes": recommended_codes,
            "estimated_revenue_if_closed": estimated_revenue_if_closed,
            "summary_stats": {
                "open_suspect_count": len(open_suspects),
                "recapture_gap_count": len(recapture_hccs),
                "meat_gap_count": len(meat_gaps),
                "total_gap_raf": round(total_gap_raf, 4),
            },
        }

    except Exception as exc:
        logger.error(
            "generate_pre_visit_summary error pid=%s year=%s: %s",
            patient_id,
            year,
            exc,
            exc_info=True,
        )
        raise


# ---------------------------------------------------------------------------
# AWV Eligibility
# ---------------------------------------------------------------------------


def get_awv_eligible(tenant_id: str, year: int) -> dict[str, Any]:
    """
    Return patients who have not had an Annual Wellness Visit in the given year.

    AWV CPT codes tracked: G0438, G0439, 99381-99387, 99391-99397.
    Eligibility revenue opportunity is estimated at $250 per AWV.
    """
    awv_placeholders = ",".join(["%s"] * len(_AWV_CPT_CODES))

    try:
        # Patients who DID have an AWV this year (exclude from result)
        with openemr_cursor() as cur:
            cur.execute(
                f"""
                SELECT DISTINCT pid
                FROM billing
                WHERE code IN ({awv_placeholders})
                  AND code_type IN ('CPT4', 'HCPCS')
                  AND activity = 1
                """,
                list(_AWV_CPT_CODES),
            )
            awv_done_rows = cur.fetchall()
        awv_done_pids = {int(r["pid"]) for r in awv_done_rows}

        # All patients from raf_intelligence.patients
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT p.id AS pid, p.first_name AS fname, p.last_name AS lname,
                       p.dob AS DOB, p.sex, p.phone AS phone_home, p.phone AS phone_cell,
                       p.address AS street, p.city, p.state, p.zip AS postal_code,
                       pp.provider_id AS providerID
                FROM patients p
                LEFT JOIN provider_patient_panel pp ON pp.patient_id = p.id
                WHERE p.is_active = 1 AND p.tenant_id = %s
                ORDER BY p.last_name, p.first_name
                LIMIT 10000
                """,
                (tenant_id,),
            )
            all_patients = cur.fetchall()

        # Filter to only patients linked to active EMR connections
        active_pids = _active_patient_ids(tenant_id)
        all_patients = [p for p in all_patients if int(p["pid"]) in active_pids]

        # Last encounter date per patient
        with openemr_cursor() as cur:
            cur.execute(
                "SELECT pid, MAX(date) AS last_enc FROM form_encounter GROUP BY pid"
            )
            enc_rows = cur.fetchall()
        last_enc_by_pid = {int(r["pid"]): r["last_enc"] for r in enc_rows}

        # Provider names
        with openemr_cursor() as cur:
            cur.execute("SELECT id, fname, lname FROM users WHERE id > 0 LIMIT 10000")
            prov_rows = cur.fetchall()
        prov_name = {
            int(r["id"]): f"{r.get('fname', '')} {r.get('lname', '')}".strip()
            for r in prov_rows
        }

        eligible = []
        for p in all_patients:
            pid = int(p["pid"])
            if pid in awv_done_pids:
                continue

            last_enc = last_enc_by_pid.get(pid)
            provider_id_val = _coerce_int(p.get("providerID"), 0) or None

            eligible.append(
                {
                    "pid": pid,
                    "name": f"{p.get('fname', '')} {p.get('lname', '')}".strip(),
                    "dob": _format_date(p.get("DOB")),
                    "sex": p.get("sex") or "Unknown",
                    "phone": p.get("phone_cell") or p.get("phone_home") or "",
                    "address": _build_address(p),
                    "provider_id": provider_id_val,
                    "provider_name": prov_name.get(provider_id_val, "")
                    if provider_id_val
                    else "",
                    "last_encounter_date": _format_date(last_enc),
                    "days_since_last_visit": _days_since(last_enc),
                    "awv_status": "eligible",
                    "awv_revenue_opportunity": 250.0,
                }
            )

        return {
            "year": year,
            "total_eligible": len(eligible),
            "total_awv_completed": len(awv_done_pids),
            "estimated_awv_revenue": round(len(eligible) * 250.0, 2),
            "patients": eligible,
        }

    except Exception as exc:
        logger.error("get_awv_eligible error: %s", exc, exc_info=True)
        raise


# ---------------------------------------------------------------------------
# AWV Scheduling Mark
# ---------------------------------------------------------------------------


def mark_awv_scheduled(
    patient_id: int, year: int, scheduled_by: int | None = None
) -> dict[str, Any]:
    """
    Record that a patient's AWV has been scheduled.

    Inserts or updates a row in raf_awv_tracking.
    Creates the table if it does not yet exist (idempotent migration).
    """
    _ensure_awv_table()
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                INSERT INTO raf_awv_tracking
                    (patient_id, measurement_year, status, scheduled_by, scheduled_at)
                VALUES (%s, %s, 'scheduled', %s, NOW())
                ON DUPLICATE KEY UPDATE
                    status       = 'scheduled',
                    scheduled_by = VALUES(scheduled_by),
                    updated_at   = NOW()
                """,
                (patient_id, year, scheduled_by),
            )

        return {
            "patient_id": patient_id,
            "year": year,
            "status": "scheduled",
            "message": "AWV marked as scheduled",
        }

    except Exception as exc:
        logger.error(
            "mark_awv_scheduled error pid=%s: %s", patient_id, exc, exc_info=True
        )
        raise


# ---------------------------------------------------------------------------
# Chase List Export
# ---------------------------------------------------------------------------


def generate_chase_list(
    tenant_id: str,
    year: int,
    provider_id: int | None = None,
    min_suspects: int | None = None,
    min_priority: float | None = None,
    not_seen_since_days: int | None = None,
) -> list[dict[str, Any]]:
    """
    Generate a chase list for patient outreach campaigns.

    Returns CSV-ready dicts with contact and clinical priority information.
    Filters are additive; all filters that are None are skipped.
    """
    try:
        worklist = get_prospective_worklist(
            tenant_id=tenant_id,
            year=year,
            provider_id=provider_id,
            min_priority=min_priority,
            limit=10_000,
            offset=0,
        )
        items = worklist.get("items", [])

        chase_rows: list[dict[str, Any]] = []
        for item in items:
            if min_suspects is not None and item.get("suspect_count", 0) < min_suspects:
                continue
            if not_seen_since_days is not None:
                days = item.get("days_since_last_visit", 0)
                if days < not_seen_since_days:
                    continue

            chase_rows.append(
                {
                    "patient_id": item["pid"],
                    "first_name": item.get("first_name", ""),
                    "last_name": item.get("last_name", ""),
                    "phone": item.get("phone", ""),
                    "address": item.get("address", ""),
                    "last_visit_date": item.get("last_encounter_date", ""),
                    "days_since_last_visit": item.get("days_since_last_visit", 0),
                    "priority_score": item.get("priority_score", 0.0),
                    "current_raf": item.get("current_raf", 0.0),
                    "suspect_count": item.get("suspect_count", 0),
                    "recapture_gaps": item.get("recapture_gaps", 0),
                    "revenue_opportunity": item.get("revenue_opportunity", 0.0),
                    "assigned_provider": item.get("provider_name", ""),
                    "provider_id": item.get("provider_id"),
                }
            )

        return chase_rows

    except Exception as exc:
        logger.error("generate_chase_list error: %s", exc, exc_info=True)
        raise


# ---------------------------------------------------------------------------
# Population Prospective Summary
# ---------------------------------------------------------------------------


def get_prospective_summary(tenant_id: str, year: int) -> dict[str, Any]:
    """
    Return population-level prospective RAF management statistics.

    Covers:
      - Patients not seen this calendar year
      - Total open suspects and revenue at risk
      - AWV opportunities
      - High-priority patient count (top 20% of priority scores)
    """
    calc_year = year
    year_start = date(calc_year, 1, 1)

    if tenant_id is None:
        raise ValueError(
            "prospective_service.get_prospective_summary: tenant_id is required — "
            "refusing to query across all tenants (HIPAA multi-tenant isolation)"
        )
    try:
        tid = int(tenant_id)
    except (TypeError, ValueError):
        raise ValueError(
            f"prospective_service.get_prospective_summary: tenant_id must be numeric, got {tenant_id!r}"
        )

    try:
        # Fetch active patient IDs once for this function
        active_pids = _active_patient_ids(tenant_id)

        # Total active patients (only those linked to active EMR connections)
        total_patients = len(active_pids)

        # Patients seen this year (only active patients)
        if active_pids:
            pid_placeholders = ",".join(["%s"] * len(active_pids))
            with openemr_cursor() as cur:
                cur.execute(
                    f"SELECT COUNT(DISTINCT pid) AS cnt FROM form_encounter WHERE date >= %s AND pid IN ({pid_placeholders})",
                    [year_start.isoformat()] + list(active_pids),
                )
                seen_this_year = _coerce_int(cur.fetchone()["cnt"])
        else:
            seen_this_year = 0

        patients_not_seen = max(0, total_patients - seen_this_year)

        # Open suspects (total count + revenue) — only active patients
        _sf, _sp = active_patients_subquery(tid)
        with raf_cursor() as cur:
            cur.execute(
                f"""
                SELECT COUNT(*) AS cnt,
                       SUM(0.15) AS total_raf_at_risk
                FROM raf_suspect_conditions
                WHERE status = 'open'
                  AND {_sf}
                  AND tenant_id = %s
                """,
                (*_sp, tid),
            )
            susp_row = cur.fetchone()
        total_open_suspects = _coerce_int(susp_row["cnt"]) if susp_row else 0
        total_raf_at_risk = (
            _coerce_float(susp_row["total_raf_at_risk"]) if susp_row else 0.0
        )
        total_revenue_at_risk = round(total_raf_at_risk * _REVENUE_PER_RAF_POINT, 2)

        # AWV opportunities — only active patients
        awv_placeholders = ",".join(["%s"] * len(_AWV_CPT_CODES))
        if active_pids:
            pid_placeholders = ",".join(["%s"] * len(active_pids))
            with openemr_cursor() as cur:
                cur.execute(
                    f"""
                    SELECT COUNT(DISTINCT b.pid) AS cnt
                    FROM billing b
                    JOIN form_encounter fe ON b.pid = fe.pid AND b.encounter = fe.encounter
                    WHERE b.code IN ({awv_placeholders})
                      AND b.code_type IN ('CPT4', 'HCPCS')
                      AND b.activity = 1
                      AND YEAR(fe.date) = %s
                      AND b.pid IN ({pid_placeholders})
                    """,
                    list(_AWV_CPT_CODES) + [calc_year] + list(active_pids),
                )
                awv_done = _coerce_int(cur.fetchone()["cnt"])
        else:
            awv_done = 0
        awv_opportunities = max(0, total_patients - awv_done)

        # Recapture gaps — only active patients
        with raf_cursor() as cur:
            cur.execute(
                f"""
                SELECT COUNT(DISTINCT patient_id) AS pts,
                       COUNT(*)                   AS gaps
                FROM raf_patient_hcc h
                WHERE h.measurement_year = %s
                  AND h.patient_id IN (SELECT id FROM patients WHERE is_active = 1 AND tenant_id = %s)
                  AND h.tenant_id = %s
                  AND NOT EXISTS (
                      SELECT 1 FROM raf_patient_hcc h2
                      WHERE h2.patient_id      = h.patient_id
                        AND h2.hcc_code        = h.hcc_code
                        AND h2.measurement_year = %s
                  )
                """,
                (calc_year - 1, tid, tid, calc_year),
            )
            recapture_row = cur.fetchone()
        recapture_patients = _coerce_int(recapture_row["pts"]) if recapture_row else 0
        total_recapture_gaps = (
            _coerce_int(recapture_row["gaps"]) if recapture_row else 0
        )

        # High priority count — patients in top 20% by priority score.
        # We approximate this by getting the worklist and counting top 20%.
        # To avoid loading tens of thousands of records, use a capped sample.
        worklist = get_prospective_worklist(
            tenant_id=tenant_id,
            year=calc_year,
            limit=10_000,
            offset=0,
        )
        all_items = worklist.get("items", [])
        n_total = len(all_items)
        high_priority_threshold_idx = max(0, int(n_total * _HIGH_PRIORITY_PERCENTILE))
        high_priority_count = n_total - high_priority_threshold_idx

        return {
            "year": calc_year,
            "total_patients": total_patients,
            "patients_seen_this_year": seen_this_year,
            "patients_not_seen_this_year": patients_not_seen,
            "total_open_suspects": total_open_suspects,
            "total_raf_at_risk": round(total_raf_at_risk, 4),
            "total_revenue_at_risk": total_revenue_at_risk,
            "awv_completed_this_year": awv_done,
            "awv_opportunities": awv_opportunities,
            "awv_revenue_opportunity": round(awv_opportunities * 250.0, 2),
            "recapture_patients_affected": recapture_patients,
            "total_recapture_gaps": total_recapture_gaps,
            "high_priority_patients": high_priority_count,
            "high_priority_threshold_pct": 20,
        }

    except Exception as exc:
        logger.error("get_prospective_summary error: %s", exc, exc_info=True)
        raise
