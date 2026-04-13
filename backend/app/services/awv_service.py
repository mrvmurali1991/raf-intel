"""
Annual Wellness Visit (AWV) Scheduling Service.

Provides all business logic for:
  - Identifying Medicare patients eligible for an AWV in the current year
  - Creating, updating, and querying AWV schedule records
  - Logging outreach contact attempts
  - Generating HCC-gap-driven pre-visit, during-visit, and post-visit checklists
  - Recording post-visit clinical results and updating RAF score snapshots
  - Dashboard analytics: completion rates and revenue impact
  - Bulk outreach campaign generation

Revenue model assumptions
--------------------------
  AWV professional fee      : $250 per visit (estimated)
  RAF lift per HCC captured : coefficient from raf_scores tables
  Revenue per RAF point     : $12,000 (CMS MA benchmark)

All RAF scores are informational — verify against official CMS SAS software
before use in any payment determination.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime
from typing import Any, Optional

from app.db import raf_cursor, openemr_cursor
from app.services.emr_manager import active_patients_subquery

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_AWV_REVENUE_PER_VISIT: float = 250.0
_REVENUE_PER_RAF_POINT: float = 12_000.0

# CPT / HCPCS codes treated as "AWV completed" evidence in OpenEMR billing
_AWV_CPT_CODES = (
    "G0438", "G0439", "G0402",
    "99381", "99382", "99383", "99384", "99385", "99386", "99387",
    "99391", "99392", "99393", "99394", "99395", "99396", "99397",
)

# Default checklist items generated for every AWV — grouped by phase
_PRE_VISIT_DEFAULTS: list[tuple[str, str]] = [
    ("Review HCC gap list", "Pull the patient's open HCC gaps and prior-year uncaptured HCCs from the RAF system"),
    ("Verify Medicare eligibility", "Confirm active Part B enrollment and that no AWV has been billed in the current calendar year"),
    ("Confirm contact information", "Verify phone, address, and preferred communication method in the chart"),
    ("Order preventive screenings", "Pre-order any due USPSTF preventive screenings (mammogram, colonoscopy, DEXA, etc.)"),
    ("Prepare advance directive discussion", "Note whether an advance directive is on file and if it needs to be reviewed"),
]

_DURING_VISIT_DEFAULTS: list[tuple[str, str]] = [
    ("Obtain health risk assessment", "Complete the CMS-required Health Risk Assessment (HRA) questionnaire"),
    ("Review chronic condition list", "Reconcile problem list with known HCC conditions; confirm, update, or add diagnoses"),
    ("Capture open HCC gaps", "Document each open HCC gap condition with appropriate ICD-10 code and MEAT documentation"),
    ("Medication reconciliation", "Review all current medications for accuracy and potential signals"),
    ("Depression screening (PHQ-9)", "Administer PHQ-9 and document result"),
    ("Functional ability and safety", "Screen for fall risk, cognitive impairment, and functional limitations"),
    ("Personalized prevention plan", "Create or update the written prevention plan per AWV requirements"),
]

_POST_VISIT_DEFAULTS: list[tuple[str, str]] = [
    ("Submit claims", "Bill appropriate AWV CPT code (G0438 initial / G0439 subsequent / G0402 Welcome to Medicare)"),
    ("Update problem list", "Finalize ICD-10 codes in the EHR problem list based on visit documentation"),
    ("Close HCC gaps in RAF system", "Mark addressed HCC gaps as resolved in the RAF Intelligence platform"),
    ("Schedule follow-up", "Book any follow-up appointments for newly identified or uncontrolled conditions"),
    ("Send after-visit summary", "Provide patient with written after-visit summary per CMS requirements"),
]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

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


def _json_field(v: Any) -> Any:
    """Deserialise a JSON column value that may already be a list/dict."""
    if v is None:
        return None
    if isinstance(v, (list, dict)):
        return v
    try:
        return json.loads(v)
    except (ValueError, TypeError):
        return v


def _serialize_row(row: dict[str, Any]) -> dict[str, Any]:
    """Convert a raw DB row to a JSON-serialisable dict."""
    result: dict[str, Any] = {}
    for k, v in row.items():
        if isinstance(v, (datetime, date)):
            result[k] = v.isoformat()
        elif isinstance(v, (bytes, bytearray)):
            result[k] = v.decode("utf-8", errors="replace")
        else:
            result[k] = v
    # Deserialise known JSON columns
    for col in ("hcc_gaps_to_review", "hcc_codes_captured"):
        if col in result and isinstance(result[col], str):
            result[col] = _json_field(result[col])
    return result


# ---------------------------------------------------------------------------
# Eligible patient identification
# ---------------------------------------------------------------------------

def get_eligible_patients(tenant_id: str, year: int) -> dict[str, Any]:
    """
    Identify Medicare patients who are eligible for an AWV in *year* and have
    not yet had a completed AWV schedule record for that year.

    A patient is considered eligible when:
      - They do NOT already have a completed AWV billing entry (CPT G0438/G0439
        etc.) in OpenEMR for *year*, AND
      - They do NOT have an awv_schedules row with status='completed' for *year*.

    Returns patient demographics plus open HCC gap counts and estimated revenue.
    """
    if tenant_id is None:
        raise ValueError(
            "awv_service.get_eligible_patients: tenant_id is required — "
            "refusing to query across all tenants (HIPAA multi-tenant isolation)"
        )
    try:
        tid = int(tenant_id)
    except (TypeError, ValueError):
        raise ValueError(
            f"awv_service.get_eligible_patients: tenant_id must be numeric, got {tenant_id!r}"
        )

    awv_placeholders = ",".join(["%s"] * len(_AWV_CPT_CODES))

    # Patients who already have a billed AWV this year
    with openemr_cursor() as cur:
        cur.execute(
            f"""
            SELECT DISTINCT b.pid
            FROM billing b
            JOIN form_encounter fe ON b.pid = fe.pid AND b.encounter = fe.encounter
            WHERE b.code IN ({awv_placeholders})
              AND b.code_type IN ('CPT4', 'HCPCS')
              AND b.activity = 1
              AND YEAR(fe.date) = %s
            """,
            list(_AWV_CPT_CODES) + [year],
        )
        billed_rows = cur.fetchall()
    billed_pids: set[int] = {int(r["pid"]) for r in billed_rows}

    # Patients who already have a completed AWV schedule record
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT patient_id FROM awv_schedules
            WHERE schedule_year = %s AND status = 'completed'
            """,
            (year,),
        )
        scheduled_rows = cur.fetchall()
    completed_pids: set[int] = {int(r["patient_id"]) for r in scheduled_rows}

    excluded_pids = billed_pids | completed_pids

    # All patients from raf_intelligence.patients
    _sf, _sp = active_patients_subquery(tid, patient_id_column="id")
    with raf_cursor() as cur:
        cur.execute(
            f"""
            SELECT p.id AS pid, p.first_name AS fname, p.last_name AS lname,
                   p.dob AS DOB, p.sex,
                   p.phone AS phone_home, p.phone AS phone_cell,
                   p.address AS street, p.city, p.state,
                   p.zip AS postal_code, pp.provider_id AS providerID
            FROM patients p
            LEFT JOIN provider_patient_panel pp ON pp.patient_id = p.id AND pp.is_active = 1
            WHERE p.is_active = 1 AND {_sf}
              AND p.tenant_id = %s
            ORDER BY p.last_name, p.first_name
            """,
            (*_sp, tid),
        )
        all_patients = cur.fetchall()

    if not all_patients:
        return {
            "year": year,
            "total_eligible": 0,
            "total_already_completed": len(excluded_pids),
            "estimated_awv_revenue": 0.0,
            "patients": [],
        }

    # Last encounter date per patient
    with openemr_cursor() as cur:
        cur.execute("SELECT pid, MAX(date) AS last_enc FROM form_encounter GROUP BY pid")
        enc_rows = cur.fetchall()
    last_enc_map = {int(r["pid"]): r["last_enc"] for r in enc_rows}

    # Provider names
    with openemr_cursor() as cur:
        cur.execute("SELECT id, fname, lname FROM users WHERE id > 0")
        prov_rows = cur.fetchall()
    prov_name_map = {
        int(r["id"]): f"{r.get('fname', '')} {r.get('lname', '')}".strip()
        for r in prov_rows
    }

    # Open HCC gap counts per patient (prior-year HCCs not yet recaptured)
    all_pids = [int(p["pid"]) for p in all_patients]
    if all_pids:
        placeholders = ",".join(["%s"] * len(all_pids))
        with raf_cursor() as cur:
            cur.execute(
                f"""
                SELECT h.patient_id, COUNT(*) AS gap_count
                FROM raf_patient_hcc h
                WHERE h.measurement_year = %s
                  AND h.patient_id IN ({placeholders})
                  AND NOT EXISTS (
                      SELECT 1 FROM raf_patient_hcc h2
                      WHERE h2.patient_id = h.patient_id
                        AND h2.hcc_code = h.hcc_code
                        AND h2.measurement_year = %s
                  )
                GROUP BY h.patient_id
                """,
                [year - 1] + all_pids + [year],
            )
            gap_rows = cur.fetchall()
        hcc_gap_map = {int(r["patient_id"]): _coerce_int(r["gap_count"]) for r in gap_rows}
    else:
        hcc_gap_map = {}

    eligible: list[dict[str, Any]] = []
    for p in all_patients:
        pid = int(p["pid"])
        if pid in excluded_pids:
            continue

        provider_id_val = _coerce_int(p.get("providerID"), 0) or None
        last_enc = last_enc_map.get(pid)
        days_since = 0
        if last_enc:
            last_enc_date = last_enc.date() if isinstance(last_enc, datetime) else last_enc if isinstance(last_enc, date) else date.today()
            delta = (date.today() - last_enc_date).days
            days_since = max(0, delta)

        eligible.append({
            "patient_id": pid,
            "first_name": p.get("fname") or "",
            "last_name": p.get("lname") or "",
            "name": f"{p.get('fname', '')} {p.get('lname', '')}".strip(),
            "dob": _format_date(p.get("DOB")),
            "sex": p.get("sex") or "Unknown",
            "phone": p.get("phone_cell") or p.get("phone_home") or "",
            "provider_id": provider_id_val,
            "provider_name": prov_name_map.get(provider_id_val, "") if provider_id_val else "",
            "last_encounter_date": _format_date(last_enc),
            "days_since_last_visit": days_since,
            "open_hcc_gap_count": hcc_gap_map.get(pid, 0),
            "estimated_awv_revenue": _AWV_REVENUE_PER_VISIT,
        })

    return {
        "year": year,
        "total_eligible": len(eligible),
        "total_already_completed": len(excluded_pids),
        "estimated_awv_revenue": round(len(eligible) * _AWV_REVENUE_PER_VISIT, 2),
        "patients": eligible,
    }


# ---------------------------------------------------------------------------
# AWV schedule CRUD
# ---------------------------------------------------------------------------

def list_schedules(
    tenant_id: str,
    year: int | None = None,
    status: str | None = None,
    provider_npi: str | None = None,
    patient_id: int | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    """Return a paginated list of AWV schedule records with optional filters."""
    conditions = ["s.tenant_id = %s"]
    params: list[Any] = [tenant_id]

    if year is not None:
        conditions.append("s.schedule_year = %s")
        params.append(year)
    if status is not None:
        conditions.append("s.status = %s")
        params.append(status)
    if provider_npi is not None:
        conditions.append("s.provider_npi = %s")
        params.append(provider_npi)
    if patient_id is not None:
        conditions.append("s.patient_id = %s")
        params.append(patient_id)

    where_clause = " AND ".join(conditions)

    with raf_cursor() as cur:
        cur.execute(
            f"SELECT COUNT(*) AS cnt FROM awv_schedules s WHERE {where_clause}",
            params,
        )
        total = _coerce_int(cur.fetchone()["cnt"])

    with raf_cursor() as cur:
        cur.execute(
            f"""
            SELECT s.*
            FROM awv_schedules s
            WHERE {where_clause}
            ORDER BY s.schedule_year DESC, s.updated_at DESC
            LIMIT %s OFFSET %s
            """,
            params + [limit, offset],
        )
        rows = cur.fetchall()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [_serialize_row(r) for r in rows],
    }


def get_schedule(awv_id: int) -> dict[str, Any] | None:
    """Return a single AWV schedule record by ID, or None if not found."""
    with raf_cursor() as cur:
        cur.execute("SELECT * FROM awv_schedules WHERE id = %s", (awv_id,))
        row = cur.fetchone()
    return _serialize_row(row) if row else None


def create_schedule(
    patient_id: int,
    tenant_id: str,
    schedule_year: int,
    provider_npi: str | None = None,
    visit_type: str | None = None,
    eligibility_date: str | None = None,
    location: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """
    Create a new AWV schedule record for a patient.

    Raises ValueError when a schedule already exists for the patient in
    *schedule_year* (enforced by the unique key on patient_id + schedule_year).
    """
    hcc_gaps, estimated_raf = _compute_hcc_gaps_and_raf(patient_id, schedule_year)

    with raf_cursor() as cur:
        cur.execute(
            """
            INSERT INTO awv_schedules
                (patient_id, tenant_id, schedule_year, provider_npi, status,
                 visit_type, eligibility_date, location, notes,
                 hcc_gaps_to_review, estimated_raf_impact)
            VALUES (%s, %s, %s, %s, 'eligible', %s, %s, %s, %s, %s, %s)
            """,
            (
                patient_id,
                tenant_id,
                schedule_year,
                provider_npi,
                visit_type,
                eligibility_date,
                location,
                notes,
                json.dumps(hcc_gaps),
                estimated_raf if estimated_raf else None,
            ),
        )
        new_id = cur.lastrowid

    record = get_schedule(new_id)
    _generate_checklist(new_id, patient_id, schedule_year)
    return record


def update_schedule(awv_id: int, updates: dict[str, Any]) -> dict[str, Any] | None:
    """
    Partial update of an AWV schedule record.

    Only a whitelisted set of columns may be updated through this function.
    Use the dedicated set_appointment and complete_schedule functions for
    status transitions that carry business logic.
    """
    allowed = {
        "provider_npi", "status", "visit_type", "location", "notes",
        "decline_reason", "outreach_attempts", "last_outreach_date",
        "hcc_gaps_to_review", "estimated_raf_impact",
    }
    filtered = {k: v for k, v in updates.items() if k in allowed}
    if not filtered:
        return get_schedule(awv_id)

    # Serialise JSON columns
    if "hcc_gaps_to_review" in filtered and isinstance(filtered["hcc_gaps_to_review"], (list, dict)):
        filtered["hcc_gaps_to_review"] = json.dumps(filtered["hcc_gaps_to_review"])

    set_clause = ", ".join(f"{k} = %s" for k in filtered)
    values = list(filtered.values()) + [awv_id]

    with raf_cursor() as cur:
        cur.execute(
            f"UPDATE awv_schedules SET {set_clause} WHERE id = %s",
            values,
        )

    return get_schedule(awv_id)


def set_appointment(
    awv_id: int,
    scheduled_date: str,
    location: str | None = None,
    notes: str | None = None,
) -> dict[str, Any] | None:
    """
    Record a confirmed appointment date for an AWV and advance status to 'scheduled'.
    """
    with raf_cursor() as cur:
        cur.execute(
            """
            UPDATE awv_schedules
            SET status = 'scheduled',
                scheduled_date = %s,
                location = COALESCE(%s, location),
                notes = COALESCE(%s, notes)
            WHERE id = %s
            """,
            (scheduled_date, location, notes, awv_id),
        )
    return get_schedule(awv_id)


def complete_schedule(
    awv_id: int,
    completed_date: str,
    conditions_reviewed: int = 0,
    conditions_confirmed: int = 0,
    new_conditions_identified: int = 0,
    hcc_codes_captured: list | None = None,
    raf_score_before: float | None = None,
    raf_score_after: float | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """
    Mark an AWV as completed and persist the visit results.

    Updates the schedule status to 'completed', sets the completed_date, and
    inserts (or replaces) a row in awv_visit_results with the clinical outcomes.
    """
    with raf_cursor() as cur:
        cur.execute(
            """
            UPDATE awv_schedules
            SET status = 'completed',
                completed_date = %s
            WHERE id = %s
            """,
            (completed_date, awv_id),
        )

    with raf_cursor() as cur:
        cur.execute(
            """
            INSERT INTO awv_visit_results
                (awv_id, conditions_reviewed, conditions_confirmed,
                 new_conditions_identified, hcc_codes_captured,
                 raf_score_before, raf_score_after, notes)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                conditions_reviewed       = VALUES(conditions_reviewed),
                conditions_confirmed      = VALUES(conditions_confirmed),
                new_conditions_identified = VALUES(new_conditions_identified),
                hcc_codes_captured        = VALUES(hcc_codes_captured),
                raf_score_before          = VALUES(raf_score_before),
                raf_score_after           = VALUES(raf_score_after),
                notes                     = VALUES(notes),
                updated_at                = NOW()
            """,
            (
                awv_id,
                conditions_reviewed,
                conditions_confirmed,
                new_conditions_identified,
                json.dumps(hcc_codes_captured or []),
                raf_score_before,
                raf_score_after,
                notes,
            ),
        )

    schedule = get_schedule(awv_id)
    results = get_visit_results(awv_id)
    return {"schedule": schedule, "results": results}


def get_visit_results(awv_id: int) -> dict[str, Any] | None:
    """Return visit results for a completed AWV, or None if not yet captured."""
    with raf_cursor() as cur:
        cur.execute("SELECT * FROM awv_visit_results WHERE awv_id = %s", (awv_id,))
        row = cur.fetchone()
    return _serialize_row(row) if row else None


# ---------------------------------------------------------------------------
# Outreach log
# ---------------------------------------------------------------------------

def log_outreach(
    awv_id: int,
    method: str,
    outcome: str,
    contacted_by: int | None = None,
    notes: str | None = None,
    contact_date: str | None = None,
) -> dict[str, Any]:
    """
    Record an outreach contact attempt and update the schedule's outreach counters.

    When outcome is 'scheduled', the schedule status is automatically advanced to
    'outreach_pending' if still in 'eligible' state (the actual appointment date
    is set separately via set_appointment).
    When outcome is 'declined', status is advanced to 'outreach_pending' (the
    caller should subsequently call update_schedule to set status='declined' plus
    decline_reason).
    """
    ts = contact_date or datetime.utcnow().isoformat(sep=" ", timespec="seconds")

    with raf_cursor() as cur:
        cur.execute(
            """
            INSERT INTO awv_outreach_log (awv_id, method, outcome, contact_date, contacted_by, notes)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (awv_id, method, outcome, ts, contacted_by, notes),
        )
        log_id = cur.lastrowid

    # Update outreach counters on the parent schedule
    with raf_cursor() as cur:
        cur.execute(
            """
            UPDATE awv_schedules
            SET outreach_attempts = outreach_attempts + 1,
                last_outreach_date = DATE(%s),
                status = CASE
                    WHEN status = 'eligible' THEN 'outreach_pending'
                    ELSE status
                END
            WHERE id = %s
            """,
            (ts, awv_id),
        )

    with raf_cursor() as cur:
        cur.execute("SELECT * FROM awv_outreach_log WHERE id = %s", (log_id,))
        row = cur.fetchone()
    return _serialize_row(row)


def list_outreach_log(awv_id: int) -> list[dict[str, Any]]:
    """Return all outreach log entries for an AWV, newest first."""
    with raf_cursor() as cur:
        cur.execute(
            "SELECT * FROM awv_outreach_log WHERE awv_id = %s ORDER BY contact_date DESC",
            (awv_id,),
        )
        rows = cur.fetchall()
    return [_serialize_row(r) for r in rows]


# ---------------------------------------------------------------------------
# Checklist management
# ---------------------------------------------------------------------------

def _generate_checklist(awv_id: int, patient_id: int, year: int) -> None:
    """
    Populate awv_checklists with the standard protocol items plus
    one HCC-specific 'during_visit' item for each open gap.

    Called automatically when a new schedule is created.
    """
    items: list[tuple[str, str, str]] = []  # (type, name, description)

    for name, desc in _PRE_VISIT_DEFAULTS:
        items.append(("pre_visit", name, desc))

    # Patient-specific HCC gap items
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT h.hcc_code, h.icd10_codes
                FROM raf_patient_hcc h
                WHERE h.patient_id = %s
                  AND h.measurement_year = %s
                  AND NOT EXISTS (
                      SELECT 1 FROM raf_patient_hcc h2
                      WHERE h2.patient_id = h.patient_id
                        AND h2.hcc_code = h.hcc_code
                        AND h2.measurement_year = %s
                  )
                """,
                (patient_id, year - 1, year),
            )
            gap_rows = cur.fetchall()
        for g in gap_rows:
            codes = _json_field(g.get("icd10_codes")) or []
            code_str = ", ".join(codes) if isinstance(codes, list) else str(codes)
            items.append((
                "during_visit",
                f"Capture HCC {g['hcc_code']}",
                f"Document and code HCC {g['hcc_code']} (ICD-10: {code_str}). "
                f"This HCC was present in {year - 1} but not yet captured in {year}.",
            ))
    except Exception as exc:  # pragma: no cover
        logger.warning("AWV checklist HCC gap fetch failed for patient %s: %s", patient_id, exc)

    for name, desc in _DURING_VISIT_DEFAULTS:
        items.append(("during_visit", name, desc))

    for name, desc in _POST_VISIT_DEFAULTS:
        items.append(("post_visit", name, desc))

    if not items:
        return

    rows = [(awv_id, t, n, d) for t, n, d in items]
    with raf_cursor() as cur:
        cur.executemany(
            """
            INSERT IGNORE INTO awv_checklists (awv_id, checklist_type, item_name, item_description)
            VALUES (%s, %s, %s, %s)
            """,
            rows,
        )


def get_checklist(awv_id: int) -> dict[str, Any]:
    """
    Return the full checklist for an AWV, grouped by phase.

    Generates the default checklist on first access if the table has no rows
    yet for this AWV (idempotent recovery path).
    """
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT * FROM awv_checklists
            WHERE awv_id = %s
            ORDER BY checklist_type, id
            """,
            (awv_id,),
        )
        rows = cur.fetchall()

    if not rows:
        # Recover — fetch the schedule and regenerate
        schedule = get_schedule(awv_id)
        if schedule:
            _generate_checklist(awv_id, schedule["patient_id"], schedule["schedule_year"])
            with raf_cursor() as cur:
                cur.execute(
                    "SELECT * FROM awv_checklists WHERE awv_id = %s ORDER BY checklist_type, id",
                    (awv_id,),
                )
                rows = cur.fetchall()

    serialised = [_serialize_row(r) for r in rows]

    grouped: dict[str, list[dict[str, Any]]] = {
        "pre_visit": [],
        "during_visit": [],
        "post_visit": [],
    }
    for item in serialised:
        phase = item.get("checklist_type", "pre_visit")
        grouped.setdefault(phase, []).append(item)

    total = len(serialised)
    completed = sum(1 for i in serialised if i.get("completed"))
    return {
        "awv_id": awv_id,
        "total_items": total,
        "completed_items": completed,
        "completion_pct": round(completed / total * 100, 1) if total else 0.0,
        "checklist": grouped,
    }


def mark_checklist_item(
    awv_id: int,
    item_id: int,
    completed: bool,
    completed_by: int | None = None,
) -> dict[str, Any] | None:
    """Toggle a checklist item complete/incomplete."""
    completed_at = datetime.utcnow().isoformat(sep=" ", timespec="seconds") if completed else None

    with raf_cursor() as cur:
        cur.execute(
            """
            UPDATE awv_checklists
            SET completed = %s,
                completed_by = %s,
                completed_at = %s
            WHERE id = %s AND awv_id = %s
            """,
            (1 if completed else 0, completed_by, completed_at, item_id, awv_id),
        )
        affected = cur.rowcount

    if not affected:
        return None

    with raf_cursor() as cur:
        cur.execute("SELECT * FROM awv_checklists WHERE id = %s", (item_id,))
        row = cur.fetchone()
    return _serialize_row(row) if row else None


# ---------------------------------------------------------------------------
# Dashboard analytics
# ---------------------------------------------------------------------------

def get_dashboard(tenant_id: str, year: int) -> dict[str, Any]:
    """
    Return AWV programme analytics for the dashboard.

    Metrics
    -------
    - total_schedules: all schedule records for the year
    - by_status: count per status enum value
    - completion_rate_pct: completed / total * 100
    - avg_outreach_attempts: mean contact attempts across all records
    - total_visits_completed: completed AWV count
    - awv_revenue_captured: completed visits * $250
    - total_conditions_reviewed / confirmed / new_identified: summed from results
    - avg_raf_lift: mean (raf_score_after - raf_score_before) from completed visits
    - total_raf_revenue_impact: sum of raf lifts * $12,000
    - patients_needing_outreach: status in (eligible, outreach_pending) with 0 upcoming appt
    """
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT
                COUNT(*)                             AS total_schedules,
                SUM(status = 'eligible')             AS cnt_eligible,
                SUM(status = 'outreach_pending')     AS cnt_outreach_pending,
                SUM(status = 'scheduled')            AS cnt_scheduled,
                SUM(status = 'completed')            AS cnt_completed,
                SUM(status = 'declined')             AS cnt_declined,
                SUM(status = 'no_show')              AS cnt_no_show,
                AVG(outreach_attempts)               AS avg_outreach_attempts
            FROM awv_schedules
            WHERE tenant_id = %s AND schedule_year = %s
            """,
            (tenant_id, year),
        )
        summary = cur.fetchone() or {}

    total = _coerce_int(summary.get("total_schedules"))
    completed_count = _coerce_int(summary.get("cnt_completed"))
    completion_rate = round(completed_count / total * 100, 1) if total else 0.0

    # Visit results aggregates
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT
                SUM(r.conditions_reviewed)        AS total_reviewed,
                SUM(r.conditions_confirmed)       AS total_confirmed,
                SUM(r.new_conditions_identified)  AS total_new,
                AVG(r.raf_score_after - r.raf_score_before) AS avg_raf_lift,
                SUM(r.raf_score_after - r.raf_score_before) AS total_raf_lift
            FROM awv_visit_results r
            JOIN awv_schedules s ON r.awv_id = s.id
            WHERE s.tenant_id = %s AND s.schedule_year = %s
              AND r.raf_score_before IS NOT NULL AND r.raf_score_after IS NOT NULL
            """,
            (tenant_id, year),
        )
        results_agg = cur.fetchone() or {}

    avg_raf_lift = _coerce_float(results_agg.get("avg_raf_lift"))
    total_raf_lift = _coerce_float(results_agg.get("total_raf_lift"))

    return {
        "year": year,
        "total_schedules": total,
        "by_status": {
            "eligible": _coerce_int(summary.get("cnt_eligible")),
            "outreach_pending": _coerce_int(summary.get("cnt_outreach_pending")),
            "scheduled": _coerce_int(summary.get("cnt_scheduled")),
            "completed": completed_count,
            "declined": _coerce_int(summary.get("cnt_declined")),
            "no_show": _coerce_int(summary.get("cnt_no_show")),
        },
        "completion_rate_pct": completion_rate,
        "avg_outreach_attempts": round(_coerce_float(summary.get("avg_outreach_attempts")), 2),
        "total_visits_completed": completed_count,
        "awv_revenue_captured": round(completed_count * _AWV_REVENUE_PER_VISIT, 2),
        "total_conditions_reviewed": _coerce_int(results_agg.get("total_reviewed")),
        "total_conditions_confirmed": _coerce_int(results_agg.get("total_confirmed")),
        "total_new_conditions_identified": _coerce_int(results_agg.get("total_new")),
        "avg_raf_lift_per_visit": round(avg_raf_lift, 4),
        "total_raf_revenue_impact": round(total_raf_lift * _REVENUE_PER_RAF_POINT, 2),
    }


# ---------------------------------------------------------------------------
# Bulk outreach campaign
# ---------------------------------------------------------------------------

def create_bulk_outreach(
    tenant_id: str,
    year: int,
    method: str,
    contacted_by: int | None = None,
    target_statuses: list[str] | None = None,
    provider_npi: str | None = None,
    max_patients: int = 500,
) -> dict[str, Any]:
    """
    Generate bulk outreach log entries for all eligible/pending AWV schedules.

    Selects schedules matching *target_statuses* (default: eligible and
    outreach_pending) and creates an outreach log entry with outcome
    'no_answer' (placeholder — the actual outcome is updated when the
    outreach staff completes the contact). Updates outreach counters.

    Returns a summary of how many records were created.
    """
    if target_statuses is None:
        target_statuses = ["eligible", "outreach_pending"]

    status_placeholders = ",".join(["%s"] * len(target_statuses))
    conditions = [f"tenant_id = %s", "schedule_year = %s", f"status IN ({status_placeholders})"]
    params: list[Any] = [tenant_id, year] + target_statuses

    if provider_npi:
        conditions.append("provider_npi = %s")
        params.append(provider_npi)

    where_clause = " AND ".join(conditions)

    with raf_cursor() as cur:
        cur.execute(
            f"SELECT id FROM awv_schedules WHERE {where_clause} LIMIT %s",
            params + [max_patients],
        )
        target_rows = cur.fetchall()

    if not target_rows:
        return {"created": 0, "awv_ids": [], "method": method}

    awv_ids = [int(r["id"]) for r in target_rows]
    ts = datetime.utcnow().isoformat(sep=" ", timespec="seconds")
    today_str = date.today().isoformat()

    log_rows = [
        (awv_id, method, "no_answer", ts, contacted_by, "Bulk outreach campaign")
        for awv_id in awv_ids
    ]

    with raf_cursor() as cur:
        cur.executemany(
            """
            INSERT INTO awv_outreach_log (awv_id, method, outcome, contact_date, contacted_by, notes)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            log_rows,
        )

    # Update counters on all targeted schedules
    id_placeholders = ",".join(["%s"] * len(awv_ids))
    with raf_cursor() as cur:
        cur.execute(
            f"""
            UPDATE awv_schedules
            SET outreach_attempts = outreach_attempts + 1,
                last_outreach_date = %s,
                status = CASE
                    WHEN status = 'eligible' THEN 'outreach_pending'
                    ELSE status
                END
            WHERE id IN ({id_placeholders})
            """,
            [today_str] + awv_ids,
        )

    return {
        "created": len(awv_ids),
        "awv_ids": awv_ids,
        "method": method,
        "campaign_date": today_str,
    }


# ---------------------------------------------------------------------------
# Internal: compute HCC gap list and estimated RAF impact for a new schedule
# ---------------------------------------------------------------------------

def _compute_hcc_gaps_and_raf(patient_id: int, year: int) -> tuple[list[str], float | None]:
    """
    Return (list_of_hcc_codes_with_gaps, estimated_raf_lift).

    Gaps are prior-year HCCs not yet present in the current year.
    RAF lift is estimated from the stored coefficients for each gap HCC.
    Returns ([], None) when no gap data is available.
    """
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT h.hcc_code
                FROM raf_patient_hcc h
                WHERE h.patient_id = %s
                  AND h.measurement_year = %s
                  AND NOT EXISTS (
                      SELECT 1 FROM raf_patient_hcc h2
                      WHERE h2.patient_id = h.patient_id
                        AND h2.hcc_code = h.hcc_code
                        AND h2.measurement_year = %s
                  )
                """,
                (patient_id, year - 1, year),
            )
            gap_rows = cur.fetchall()

        if not gap_rows:
            return [], None

        hcc_codes = [str(r["hcc_code"]) for r in gap_rows]
        code_ints = [int(c) for c in hcc_codes]
        placeholders = ",".join(["%s"] * len(code_ints))

        with raf_cursor() as cur:
            cur.execute(
                f"""
                SELECT SUM(coefficient) AS total_coeff
                FROM hcc_raf_coefficients
                WHERE hcc_code IN ({placeholders})
                  AND model_segment = 'CNA'
                  AND model_year = (
                      SELECT MAX(model_year) FROM hcc_raf_coefficients
                  )
                """,
                code_ints,
            )
            coeff_row = cur.fetchone()

        total_coeff = _coerce_float(coeff_row["total_coeff"]) if coeff_row else None
        return hcc_codes, (round(total_coeff, 4) if total_coeff else None)

    except Exception as exc:
        logger.warning("_compute_hcc_gaps_and_raf error pid=%s year=%s: %s", patient_id, year, exc)
        return [], None
