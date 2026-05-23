"""
radv_audit_service.py
=====================
RADV (Risk Adjustment Data Validation) audit service.

CMS's RADV audit process requires that every submitted HCC code be fully
traceable through: encounter → provider → diagnosis → supporting documentation.
This service assembles that complete evidence chain and surfaces gaps that
would fail a RADV audit.

Public API
----------
get_hcc_audit_trail(patient_id, hcc_code, measurement_year, tenant_id) -> dict
    Complete RADV audit chain for one patient/HCC combination.

generate_radv_report(tenant_id, measurement_year) -> dict
    Population-level RADV readiness report for a tenant and year.

check_meat_compliance(patient_id, hcc_code, tenant_id) -> dict
    Determine which MEAT criteria (Monitor/Evaluate/Assess/Treat) are met
    for a specific HCC based on stored evidence.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

from app.db import raf_cursor
from app.services.hccinfhir_utils import DEFAULT_MODEL, labels_default, lookup_hcc

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _hcc_label(hcc_code: int) -> str | None:
    """Return the human-readable label for an HCC code number, or None."""
    return labels_default.get((str(hcc_code), DEFAULT_MODEL))


def _parse_icd_list(raw: str | list | bytes | None) -> list[str]:
    """Normalise the icd10_codes column value to a plain list of strings.

    Handles the three shapes the column has worn over time:
      1. native list/tuple (when the driver inflates JSON for us)
      2. JSON-encoded string like `'["N18.6", "N18.4"]'`
         (must be parsed BEFORE the CSV fallback — otherwise CSV split
          produces `['["N18.6"', '"N18.4"]']` — the RADV-audit
          double-JSON-encoding bug coders flagged in round 2)
      3. plain CSV `'N18.6, N18.4'` (legacy)
    """
    if not raw:
        return []
    if isinstance(raw, (list, tuple)):
        return [str(c).strip() for c in raw if c]
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", errors="ignore")
    if isinstance(raw, str):
        s = raw.strip()
        # JSON-array string — most common from JSON columns.
        if s.startswith("["):
            try:
                import json as _json
                parsed = _json.loads(s)
                if isinstance(parsed, list):
                    return [str(c).strip() for c in parsed if c]
            except Exception:  # noqa: BLE001 — best-effort guard
                logger.debug("swallowed exception", exc_info=True)
        # CSV / single value fallback.
        return [c.strip() for c in s.split(",") if c.strip()]
    return []


def _float(val: Any) -> float:
    """Safely cast a value (e.g. Decimal) to float."""
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------------------
# 1. get_hcc_audit_trail
# ---------------------------------------------------------------------------


def get_hcc_audit_trail(
    patient_id: int,
    hcc_code: int,
    measurement_year: int,
    tenant_id: str,
) -> dict[str, Any]:
    """Return the complete RADV audit trail for one patient/HCC combination.

    The returned dict contains:
      patient            – demographics (name, dob, mbi/medicare_id, gender)
      hcc                – code number, description, RAF coefficient
      icd10_codes        – list of ICD-10 codes that map to this HCC
      icd10_details      – hccinfhir enrichment for each ICD code
      encounters         – list of supporting encounters (date, provider, facility,
                           encounter_type, encounter_id)
      diagnoses          – normalized diagnosis rows linked to those encounters
      meat_summary       – per-element booleans + overall completeness score
      documentation      – uploaded/linked document count
      audit_status       – "RADV_READY" | "INCOMPLETE" | "NO_DOCUMENTATION"
      gaps               – list of human-readable strings describing what is missing

    Raises
    ------
    ValueError
        If no raf_patient_hcc row exists for the given patient/HCC/year.
    """
    gaps: list[str] = []

    # ------------------------------------------------------------------
    # 1a. Fetch the raf_patient_hcc row
    # ------------------------------------------------------------------
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT
                id,
                hcc_code,
                icd10_codes,
                raf_coefficient,
                meat_status,
                source_encounter_ids AS source,
                created_at
            FROM raf_patient_hcc
            WHERE patient_id       = %s
              AND hcc_code         = %s
              AND measurement_year = %s
              AND tenant_id        = %s
            ORDER BY id DESC
            LIMIT 1
            """,
            (patient_id, hcc_code, measurement_year, tenant_id),
        )
        hcc_row = cur.fetchone()

    if not hcc_row:
        raise ValueError(
            f"No HCC {hcc_code} row found for patient {patient_id} "
            f"in year {measurement_year} (tenant {tenant_id})"
        )

    patient_hcc_id: int = hcc_row["id"]
    icd_codes = _parse_icd_list(hcc_row["icd10_codes"])

    # ------------------------------------------------------------------
    # 1b. Patient demographics
    # ------------------------------------------------------------------
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT
                p.id,
                p.first_name,
                p.last_name,
                p.dob,
                p.sex AS gender
            FROM patients p
            WHERE p.id        = %s
              AND p.tenant_id = %s
            LIMIT 1
            """,
            (patient_id, tenant_id),
        )
        demo_row = cur.fetchone()

    if demo_row:
        # MBI/insurance_id are not yet stored in raf_intelligence (the
        # raf_patient_demographics table only has CMS-segment fields, not
        # PHI identifiers). Surfaced as None until the FHIR Patient sync
        # populates them — a payer-audit-grade RADV packet will need them.
        patient_info: dict[str, Any] = {
            "patient_id": patient_id,
            "name": f"{demo_row.get('first_name', '')} {demo_row.get('last_name', '')}".strip(),
            "date_of_birth": str(demo_row["dob"]) if demo_row.get("dob") else None,
            "gender": demo_row.get("gender"),
            "mbi": None,
            "insurance_id": None,
        }
    else:
        patient_info = {"patient_id": patient_id}
        gaps.append("Patient demographics record not found")

    # ------------------------------------------------------------------
    # 1c. HCC details via hccinfhir
    # ------------------------------------------------------------------
    hcc_label = _hcc_label(hcc_code)
    # Gather enrichment for each ICD code
    icd_details: list[dict[str, Any]] = []
    for code in icd_codes:
        mapping = lookup_hcc(code)
        icd_details.append(
            {
                "icd10_code": code,
                "maps_to_hcc": mapping["maps_to_hcc"],
                "hcc_codes": mapping["hcc_codes"],
                "details": mapping["hcc_details"],
            }
        )

    # The "source" alias actually carries source_encounter_ids (JSON column),
    # which the mysql connector returns as a raw string `"[]"` rather than a
    # parsed list. Surface a parsed list of encounter ids under the more
    # accurate `source_encounter_ids` field name, and keep the empty default
    # so the auditor knows when no encounter linkage was recorded.
    _src_raw = hcc_row.get("source")
    if isinstance(_src_raw, str):
        try:
            import json as _json
            source_encounters = _json.loads(_src_raw) if _src_raw.strip() else []
        except Exception:
            logger.debug("swallowed exception", exc_info=True)
            source_encounters = []
    elif isinstance(_src_raw, list):
        source_encounters = _src_raw
    else:
        source_encounters = []

    hcc_info: dict[str, Any] = {
        "hcc_code": hcc_code,
        "description": hcc_label or f"HCC {hcc_code}",
        "raf_coefficient": _float(hcc_row.get("raf_coefficient")),
        "source_encounter_ids": source_encounters,
        "meat_status": hcc_row.get("meat_status"),
    }

    if not icd_codes:
        gaps.append("No ICD-10 codes linked to this HCC assignment")

    # ------------------------------------------------------------------
    # 1d. Supporting encounters via normalized_encounters
    # ------------------------------------------------------------------
    # The normalized_diagnoses table is not yet provisioned in every
    # environment (planned schema migration). When the join fails we
    # degrade to a patient-level encounter list rather than 500-ing the
    # whole audit trail — the gap is surfaced in the response so the
    # auditor knows the per-ICD linkage is missing.
    encounter_rows: list[dict[str, Any]] = []
    enc_rows: list[dict[str, Any]] = []
    if icd_codes:
        placeholders = ", ".join(["%s"] * len(icd_codes))
        try:
            with raf_cursor() as cur:
                cur.execute(
                    f"""
                    SELECT DISTINCT
                        ne.encounter_id              AS encounter_id,
                        ne.encounter_date,
                        ne.encounter_type,
                        ne.facility_name,
                        ne.provider_name,
                        ne.provider_npi,
                        ne.tenant_id
                    FROM normalized_encounters ne
                    JOIN normalized_diagnoses nd
                       ON nd.encounter_id = ne.encounter_id
                    WHERE ne.patient_id      = %s
                      AND ne.tenant_id       = %s
                      AND YEAR(ne.encounter_date) = %s
                      AND nd.icd10_code IN ({placeholders})
                    ORDER BY ne.encounter_date DESC
                    """,
                    (patient_id, tenant_id, measurement_year, *icd_codes),
                )
                enc_rows = cur.fetchall()
        except Exception as exc:
            logger.warning(
                "radv.audit_trail: per-ICD encounter join unavailable (%s) — "
                "falling back to patient-level encounters",
                exc,
            )
            gaps.append(
                "Per-ICD encounter linkage unavailable in this environment "
                "(normalized_diagnoses table not provisioned)"
            )
            try:
                with raf_cursor() as cur:
                    cur.execute(
                        """
                        SELECT
                            encounter_id,
                            encounter_date,
                            encounter_type,
                            facility_name,
                            provider_name,
                            provider_npi,
                            tenant_id
                          FROM normalized_encounters
                         WHERE patient_id = %s
                           AND tenant_id = %s
                           AND YEAR(encounter_date) = %s
                         ORDER BY encounter_date DESC
                         LIMIT 20
                        """,
                        (patient_id, tenant_id, measurement_year),
                    )
                    enc_rows = cur.fetchall() or []
            except Exception as exc2:
                logger.warning(
                    "radv.audit_trail: patient-level encounter fallback failed: %s",
                    exc2,
                )
                enc_rows = []

        for r in enc_rows:
            encounter_rows.append(
                {
                    "encounter_id": r["encounter_id"],
                    "encounter_date": str(r["encounter_date"]),
                    "encounter_type": r.get("encounter_type"),
                    "facility_name": r.get("facility_name"),
                    "provider_name": r.get("provider_name"),
                    "provider_npi": r.get("provider_npi"),
                }
            )

    if not encounter_rows:
        gaps.append(
            "No supporting encounters found for the ICD-10 codes linked to this HCC"
        )

    # ------------------------------------------------------------------
    # 1e. Normalized diagnoses for those encounters
    # ------------------------------------------------------------------
    diagnosis_rows: list[dict[str, Any]] = []
    enc_ids = [e["encounter_id"] for e in encounter_rows]
    if enc_ids:
        placeholders = ", ".join(["%s"] * len(enc_ids))
        with raf_cursor() as cur:
            cur.execute(
                f"""
                SELECT
                    nd.id,
                    nd.encounter_id,
                    nd.icd10_code,
                    nd.description,
                    nd.diagnosis_type,
                    nd.created_at
                FROM normalized_diagnoses nd
                WHERE nd.encounter_id IN ({placeholders})
                  AND nd.icd10_code   IN ({", ".join(["%s"] * len(icd_codes))})
                ORDER BY nd.encounter_id, nd.icd10_code
                """,
                (*enc_ids, *icd_codes),
            )
            diag_rows = cur.fetchall()

        for r in diag_rows:
            diagnosis_rows.append(
                {
                    "diagnosis_id": r["id"],
                    "encounter_id": r["encounter_id"],
                    "icd10_code": r["icd10_code"],
                    "description": r.get("description"),
                    "diagnosis_type": r.get("diagnosis_type"),
                }
            )

    if not diagnosis_rows:
        gaps.append("No confirmed diagnosis records found for this HCC")

    # ------------------------------------------------------------------
    # 1f. MEAT evidence from raf_meat_evidence
    # ------------------------------------------------------------------
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT
                MAX(meat_m_present)     AS has_m,
                MAX(meat_e_present)     AS has_e,
                MAX(meat_a_present)     AS has_a,
                MAX(meat_t_present)     AS has_t,
                MAX(completeness_score) AS best_score,
                COUNT(*)                AS evidence_rows
            FROM raf_meat_evidence
            WHERE patient_hcc_id = %s
            """,
            (patient_hcc_id,),
        )
        meat_agg = cur.fetchone()

    has_m = bool(meat_agg and meat_agg.get("has_m"))
    has_e = bool(meat_agg and meat_agg.get("has_e"))
    has_a = bool(meat_agg and meat_agg.get("has_a"))
    has_t = bool(meat_agg and meat_agg.get("has_t"))
    best_score = _float(meat_agg["best_score"]) if meat_agg else 0.0
    evidence_rows_count = int(meat_agg["evidence_rows"]) if meat_agg else 0

    meat_summary: dict[str, Any] = {
        "monitor": has_m,
        "evaluate": has_e,
        "assess": has_a,
        "treat": has_t,
        "completeness_score": best_score,
        "evidence_record_count": evidence_rows_count,
        "criteria_met": sum([has_m, has_e, has_a, has_t]),
    }

    if not has_m:
        gaps.append("MEAT: Monitoring evidence missing")
    if not has_e:
        gaps.append("MEAT: Evaluation evidence missing")
    if not has_a:
        gaps.append("MEAT: Assessment/diagnosis confirmation missing")
    if not has_t:
        gaps.append("MEAT: Treatment evidence missing")

    # ------------------------------------------------------------------
    # 1g. Supporting documents
    # ------------------------------------------------------------------
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) AS doc_count
            FROM documents
            WHERE patient_id = %s
              AND tenant_id  = %s
            """,
            (patient_id, tenant_id),
        )
        doc_row = cur.fetchone()

    doc_count = int(doc_row["doc_count"]) if doc_row else 0
    documentation_info: dict[str, Any] = {
        "total_documents": doc_count,
        "has_documentation": doc_count > 0,
    }

    if doc_count == 0:
        gaps.append("No clinical documentation uploaded for this patient")

    # ------------------------------------------------------------------
    # 1h. Determine overall RADV audit status
    # ------------------------------------------------------------------
    if not gaps:
        audit_status = "RADV_READY"
    elif doc_count == 0 or not encounter_rows:
        audit_status = "NO_DOCUMENTATION"
    else:
        audit_status = "INCOMPLETE"

    return {
        "patient": patient_info,
        "hcc": hcc_info,
        "measurement_year": measurement_year,
        "icd10_codes": icd_codes,
        "icd10_details": icd_details,
        "encounters": encounter_rows,
        "diagnoses": diagnosis_rows,
        "meat_summary": meat_summary,
        "documentation": documentation_info,
        "audit_status": audit_status,
        "gaps": gaps,
    }


# ---------------------------------------------------------------------------
# 2. generate_radv_report
# ---------------------------------------------------------------------------


def generate_radv_report(
    tenant_id: str,
    measurement_year: int,
) -> dict[str, Any]:
    """Generate a population-level RADV readiness report for a tenant/year.

    Returns
    -------
    dict with keys:
      tenant_id           str
      measurement_year    int
      generated_at        str    ISO timestamp
      summary             dict
        total_patients        int
        total_hccs            int
        hccs_fully_documented int   (meat_status = 'complete')
        hccs_partial          int   (meat_status = 'partial')
        hccs_missing          int   (meat_status = 'missing' or NULL)
        documentation_rate    float  0.00–1.00
      patients_needing_attention  list[dict]  patients with incomplete HCCs
      risk_score_by_completeness  dict  breakdown of RAF contribution by status
    """
    from datetime import datetime, timezone

    # ------------------------------------------------------------------
    # 2a. Aggregate HCC completeness across all patients for the year
    # ------------------------------------------------------------------
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT
                ph.patient_id,
                p.first_name,
                p.last_name,
                ph.hcc_code,
                ph.meat_status,
                ph.raf_coefficient
            FROM raf_patient_hcc ph
            JOIN patients p
               ON p.id        = ph.patient_id
              AND p.tenant_id = ph.tenant_id
            WHERE ph.tenant_id        = %s
              AND ph.measurement_year = %s
            ORDER BY ph.patient_id, ph.hcc_code
            """,
            (tenant_id, measurement_year),
        )
        all_hcc_rows = cur.fetchall()

    total_hccs = len(all_hcc_rows)
    hccs_complete = 0
    hccs_partial = 0
    hccs_missing = 0
    raf_by_status: dict[str, float] = {"complete": 0.0, "partial": 0.0, "missing": 0.0}

    # Track per-patient incomplete HCC counts for the "attention" list
    patient_incomplete: dict[int, dict[str, Any]] = {}

    for row in all_hcc_rows:
        status = (row.get("meat_status") or "missing").lower()
        raf_contrib = _float(row.get("raf_coefficient"))

        if status == "complete":
            hccs_complete += 1
            raf_by_status["complete"] += raf_contrib
        elif status == "partial":
            hccs_partial += 1
            raf_by_status["partial"] += raf_contrib
        else:
            hccs_missing += 1
            raf_by_status["missing"] += raf_contrib

        if status in ("partial", "missing"):
            pid: int = row["patient_id"]
            if pid not in patient_incomplete:
                patient_incomplete[pid] = {
                    "patient_id": pid,
                    "name": f"{row.get('first_name', '')} {row.get('last_name', '')}".strip(),
                    "incomplete_hcc_count": 0,
                    "hccs": [],
                }
            patient_incomplete[pid]["incomplete_hcc_count"] += 1
            patient_incomplete[pid]["hccs"].append(
                {
                    "hcc_code": row["hcc_code"],
                    "description": _hcc_label(row["hcc_code"]) or f"HCC {row['hcc_code']}",
                    "meat_status": status,
                    "raf_coefficient": raf_contrib,
                }
            )

    doc_rate = round(hccs_complete / total_hccs, 4) if total_hccs else 0.0

    # Sort patients by most incomplete HCCs first
    attention_list = sorted(
        patient_incomplete.values(),
        key=lambda x: x["incomplete_hcc_count"],
        reverse=True,
    )

    # Round RAF sums
    for k in raf_by_status:
        raf_by_status[k] = round(raf_by_status[k], 4)

    # Count distinct patients
    unique_patient_ids = {r["patient_id"] for r in all_hcc_rows}

    return {
        "tenant_id": tenant_id,
        "measurement_year": measurement_year,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total_patients": len(unique_patient_ids),
            "total_hccs": total_hccs,
            "hccs_fully_documented": hccs_complete,
            "hccs_partial": hccs_partial,
            "hccs_missing_documentation": hccs_missing,
            "documentation_rate": doc_rate,
        },
        "risk_score_by_completeness": raf_by_status,
        "patients_needing_attention": attention_list,
    }


# ---------------------------------------------------------------------------
# 3. check_meat_compliance
# ---------------------------------------------------------------------------


def check_meat_compliance(
    patient_id: int,
    hcc_code: int,
    tenant_id: str,
    measurement_year: int | None = None,
) -> dict[str, Any]:
    """Check MEAT compliance for a specific patient/HCC combination.

    Examines stored raf_meat_evidence rows (populated by the MEAT validator
    and NLP analysis pipeline) and determines which of the four MEAT criteria
    are satisfied.

    Returns
    -------
    dict with keys:
      patient_id          int
      hcc_code            int
      hcc_description     str
      measurement_year    int
      patient_hcc_id      int | None
      criteria:
        monitor:   {met: bool, excerpt: str | None, encounter_ids: list[int]}
        evaluate:  {met: bool, excerpt: str | None, encounter_ids: list[int]}
        assess:    {met: bool, excerpt: str | None, encounter_ids: list[int]}
        treat:     {met: bool, excerpt: str | None, encounter_ids: list[int]}
      criteria_met_count  int   0–4
      overall_status      str   "COMPLETE" | "PARTIAL" | "MISSING"
      last_evidence_date  str | None
      recommendation      str   plain-language next-step guidance
    """
    year = measurement_year or date.today().year

    # ------------------------------------------------------------------
    # 3a. Look up patient_hcc_id
    # ------------------------------------------------------------------
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT id
            FROM raf_patient_hcc
            WHERE patient_id       = %s
              AND hcc_code         = %s
              AND measurement_year = %s
              AND tenant_id        = %s
            ORDER BY id DESC
            LIMIT 1
            """,
            (patient_id, hcc_code, year, tenant_id),
        )
        hcc_row = cur.fetchone()

    patient_hcc_id: int | None = hcc_row["id"] if hcc_row else None

    # ------------------------------------------------------------------
    # 3b. Fetch all MEAT evidence rows for this HCC assignment
    # ------------------------------------------------------------------
    evidence_list: list[dict[str, Any]] = []
    if patient_hcc_id is not None:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT
                    encounter_id,
                    encounter_date,
                    meat_m,
                    meat_e,
                    meat_a,
                    meat_t,
                    meat_m_present,
                    meat_e_present,
                    meat_a_present,
                    meat_t_present,
                    completeness_score,
                    raw_note_excerpt
                FROM raf_meat_evidence
                WHERE patient_hcc_id = %s
                ORDER BY encounter_date DESC
                """,
                (patient_hcc_id,),
            )
            evidence_list = [dict(r) for r in cur.fetchall()]

    # ------------------------------------------------------------------
    # 3c. Aggregate per-criterion evidence across all encounters
    # ------------------------------------------------------------------
    def _agg_criterion(
        present_key: str, text_key: str
    ) -> dict[str, Any]:
        met = False
        excerpt: str | None = None
        enc_ids: list[int] = []
        for ev in evidence_list:
            if ev.get(present_key):
                met = True
                enc_ids.append(ev["encounter_id"])
                if excerpt is None:
                    excerpt = ev.get(text_key)
        return {"met": met, "excerpt": excerpt, "encounter_ids": enc_ids}

    criteria = {
        "monitor": _agg_criterion("meat_m_present", "meat_m"),
        "evaluate": _agg_criterion("meat_e_present", "meat_e"),
        "assess": _agg_criterion("meat_a_present", "meat_a"),
        "treat": _agg_criterion("meat_t_present", "meat_t"),
    }

    criteria_met_count = sum(1 for c in criteria.values() if c["met"])

    if criteria_met_count == 4:
        overall_status = "COMPLETE"
    elif criteria_met_count > 0:
        overall_status = "PARTIAL"
    else:
        overall_status = "MISSING"

    # Last encounter date with any evidence
    last_evidence_date: str | None = None
    if evidence_list:
        raw_date = evidence_list[0].get("encounter_date")
        last_evidence_date = str(raw_date) if raw_date else None

    # ------------------------------------------------------------------
    # 3d. Human-readable recommendation
    # ------------------------------------------------------------------
    missing_criteria = [
        label
        for label, key in [
            ("Monitoring", "monitor"),
            ("Evaluation", "evaluate"),
            ("Assessment", "assess"),
            ("Treatment", "treat"),
        ]
        if not criteria[key]["met"]
    ]

    if overall_status == "COMPLETE":
        recommendation = (
            "All MEAT criteria are documented. This HCC is RADV-defensible."
        )
    elif overall_status == "MISSING":
        recommendation = (
            "No MEAT evidence found. Run NLP analysis on clinical notes or "
            "upload supporting documentation to establish an audit trail."
        )
    else:
        recommendation = (
            f"Missing MEAT evidence for: {', '.join(missing_criteria)}. "
            "Review recent clinical notes and update documentation to achieve "
            "full RADV defensibility."
        )

    return {
        "patient_id": patient_id,
        "hcc_code": hcc_code,
        "hcc_description": _hcc_label(hcc_code) or f"HCC {hcc_code}",
        "measurement_year": year,
        "patient_hcc_id": patient_hcc_id,
        "criteria": criteria,
        "criteria_met_count": criteria_met_count,
        "overall_status": overall_status,
        "last_evidence_date": last_evidence_date,
        "recommendation": recommendation,
    }
