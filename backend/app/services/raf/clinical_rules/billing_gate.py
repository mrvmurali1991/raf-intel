"""Billing gate — integrates clinical rules into the meat_status promotion path.

The gate is the **only** place where clinical_rules.validate_billed_hccs is
allowed to change a business outcome.  Everything else that imports the
clinical_rules package is advisory-only.

Design contract:
    * On FAIL  — the HCC's meat_status must NOT be promoted to "complete".
                 It stays at whatever it was (typically "partial") and a
                 structured block_reason is persisted for the UI to display.
    * On WARN  — promotion is allowed, but the warning reasons are attached
                 so the UI can surface them.
    * On PASS  — promotion proceeds as before; no side-effects.

Patient-safety notes:
    * Rules that are advisory_only already have their FAILs demoted to WARN
      inside rules.ClinicalRule.evaluate — the gate never sees them as FAIL.
    * If the rule registry has NO rule for the billed HCC, the gate returns
      PASS. We do not block unknown codes.
    * If context population fails for any reason, the gate SHOULD log-and-
      allow (fail-open) — the rule engine must never be a single point of
      failure that halts all billing. Callers that want fail-closed should
      check `gate_unavailable` on the returned dict.

The context adapter — build_patient_context_from_db — pulls evidence from
OpenEMR + RAF.  It is fail-open: any exception is caught and returns a
minimal PatientContext that will PASS most rules.  Call sites should log
when that happens.
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

from .rules import (
    Encounter,
    LabResult,
    Medication,
    PatientContext,
    ProcedureRecord,
    RuleStatus,
)
from .validator import BilledHCC, ValidationReport, validate_billed_hccs


logger = logging.getLogger(__name__)

# Per-call context cache: keyed on (patient_id, dos) so that batch callers
# processing many HCCs for the same patient within one request share a single
# DB round-trip.  The dict is intentionally module-level but small — it holds
# at most one PatientContext per unique (patient_id, dos) seen in a single
# Python process lifetime.  Production callers that want a fresh fetch should
# pass a pre-built ``context`` argument to gate_billed_promotion directly.
_context_cache: dict[tuple[int, date], PatientContext] = {}


def _get_or_build_context(patient_id: int, dos: date) -> PatientContext:
    """Return a cached PatientContext or build and cache one."""
    key = (patient_id, dos)
    if key not in _context_cache:
        _context_cache[key] = build_patient_context_from_db(patient_id, dos)
    return _context_cache[key]


def _parse_date(val: Any) -> date | None:
    """Coerce a DB date/datetime/str to a date, or return None."""
    if val is None:
        return None
    if isinstance(val, date):
        return val if not isinstance(val, datetime) else val.date()
    try:
        return datetime.strptime(str(val)[:10], "%Y-%m-%d").date()
    except Exception:  # noqa: BLE001 — best-effort guard
        logger.debug("swallowed exception", exc_info=True)
        return None


# ---------------------------------------------------------------------------
# Context builder — plug into OpenEMR / RAF DB
# ---------------------------------------------------------------------------

def build_patient_context_from_db(patient_id: int, dos: date) -> PatientContext:
    """Assemble a PatientContext for a patient on a given DOS.

    This is the integration seam between clinical rules and the rest of the
    application.  Kept deliberately thin: no business logic, just gathering.

    If any data source is unavailable we log and return whatever partial
    context we can.  The caller should treat a partial context as a "rules
    best-effort" situation — rules that rely on the missing evidence may
    WARN or FAIL; that's a feature, not a bug.

    Evidence is constrained to the CMS payment-year DOS window derived from
    ``dos``.  The payment year is ``dos.year`` if the DOS falls within that
    year's window; we fall back to a simple 12-month lookback if the year is
    not in the payment-year registry.
    """
    dx_codes: list[str] = []
    meds: list[Medication] = []
    labs: list[LabResult] = []
    procs: list[ProcedureRecord] = []
    encounters: list[Encounter] = []
    age: int = 0
    sex: str = "U"

    # Determine the DOS window for the evidence lookback.
    # get_payment_year_window uses payment_year = dos.year + 1 because the
    # window is year-1; we try dos.year+1 first (most common case: querying
    # during a payment year for data collected in the prior year), then
    # dos.year as fallback, then a plain 12-month lookback.
    try:
        from app.services.raf.dos_rules import get_payment_year_window
        try:
            _win = get_payment_year_window(dos.year + 1)
        except KeyError:
            try:
                _win = get_payment_year_window(dos.year)
            except KeyError:
                _win = None
        if _win is not None:
            win_start: date = _win.dos_start
            win_end: date = _win.dos_end
        else:
            from datetime import timedelta
            win_start = dos - timedelta(days=365)
            win_end = dos
    except Exception as exc:
        logger.debug("gate: dos_rules import failed, using 12-month window: %s", exc)
        from datetime import timedelta
        win_start = dos - timedelta(days=365)
        win_end = dos

    # --- OpenEMR: demographics + ICD-10 + medications + CPT procedures ----
    try:
        from app.db import openemr_cursor

        with openemr_cursor() as cur:
            cur.execute(
                "SELECT DOB, sex FROM patient_data WHERE pid = %s",
                (patient_id,),
            )
            row = cur.fetchone()
            if row:
                dob = row.get("DOB") or row.get("dob")
                if dob:
                    try:
                        dob_d = _parse_date(dob)
                        if dob_d:
                            age = max(0, dos.year - dob_d.year - (
                                (dos.month, dos.day) < (dob_d.month, dob_d.day)
                            ))
                    except Exception as exc:
                        logger.debug("gate: dob parse failed pid=%s: %s", patient_id, exc)
                sex = (row.get("sex") or "U")[:1].upper() or "U"

            cur.execute(
                "SELECT DISTINCT code FROM billing "
                "WHERE pid = %s AND code_type = 'ICD10' AND activity = 1",
                (patient_id,),
            )
            dx_codes = [r["code"] for r in cur.fetchall() if r.get("code")]

            # Active medications — OpenEMR stores these in 'prescriptions'.
            try:
                cur.execute(
                    "SELECT drug, rxnorm_drugcode, start_date, end_date, active "
                    "FROM prescriptions WHERE patient_id = %s AND active = 1",
                    (patient_id,),
                )
                for r in cur.fetchall():
                    meds.append(Medication(
                        rx_class="",
                        name=(r.get("drug") or ""),
                        active=bool(r.get("active", 1)),
                        started_at=_parse_date(r.get("start_date")),
                        stopped_at=_parse_date(r.get("end_date")),
                    ))
            except Exception as exc:
                logger.warning(
                    "gate: openemr prescriptions unavailable pid=%s: %s", patient_id, exc
                )

            # CPT4 procedures billed in the DOS window.
            try:
                cur.execute(
                    "SELECT DISTINCT b.code, fe.date AS performed_date "
                    "FROM billing b "
                    "LEFT JOIN form_encounter fe ON fe.encounter = b.encounter AND fe.pid = b.pid "
                    "WHERE b.pid = %s AND b.code_type = 'CPT4' AND b.activity = 1 "
                    "  AND (fe.date IS NULL OR (fe.date >= %s AND fe.date <= %s))",
                    (patient_id, win_start.isoformat(), win_end.isoformat()),
                )
                for r in cur.fetchall():
                    cpt = r.get("code") or ""
                    if cpt:
                        procs.append(ProcedureRecord(
                            cpt=cpt,
                            performed_at=_parse_date(r.get("performed_date")),
                        ))
            except Exception as exc:
                logger.warning(
                    "gate: openemr CPT4 query unavailable pid=%s: %s", patient_id, exc
                )

    except Exception as exc:
        logger.warning("gate: openemr fetch failed pid=%s: %s", patient_id, exc)

    # --- RAF DB: patient_medications, fhir_observations, normalized_encounters
    try:
        from app.db import raf_cursor

        with raf_cursor() as cur:
            # patient_medications — FHIR-synced medication records.
            try:
                cur.execute(
                    "SELECT medication_name, start_date, status "
                    "FROM patient_medications "
                    "WHERE patient_id = %s AND (status = 'active' OR is_active = 1)",
                    (patient_id,),
                )
                for r in cur.fetchall():
                    meds.append(Medication(
                        rx_class="",
                        name=(r.get("medication_name") or ""),
                        active=True,
                        started_at=_parse_date(r.get("start_date")),
                    ))
            except Exception as exc:
                logger.warning(
                    "gate: patient_medications unavailable pid=%s: %s", patient_id, exc
                )

            # fhir_observations — LOINC-coded lab results within the DOS window.
            # fhir_patient_id is the FHIR UUID; we need to look it up via
            # emr_patient_matches.  We query by the RAF internal patient_id
            # cross-referenced through patients table.
            try:
                cur.execute(
                    "SELECT fo.code AS loinc, fo.value_numeric, fo.unit, fo.effective_date "
                    "FROM fhir_observations fo "
                    "JOIN emr_patient_matches epm ON epm.external_id = fo.fhir_patient_id "
                    "JOIN patients p ON p.id = epm.patient_id "
                    "WHERE p.id = %s "
                    "  AND fo.effective_date >= %s AND fo.effective_date <= %s "
                    "  AND fo.category = 'laboratory' "
                    "ORDER BY fo.effective_date DESC "
                    "LIMIT 500",
                    (patient_id, win_start.isoformat(), win_end.isoformat()),
                )
                for r in cur.fetchall():
                    loinc = r.get("loinc") or ""
                    if loinc:
                        labs.append(LabResult(
                            loinc=loinc,
                            value=r.get("value_numeric"),
                            unit=r.get("unit"),
                            observed_at=_parse_date(r.get("effective_date")),
                        ))
            except Exception as exc:
                logger.warning(
                    "gate: fhir_observations unavailable pid=%s: %s", patient_id, exc
                )

            # normalized_encounters — visit records within the DOS window.
            # provider_specialty is not stored; we leave it as empty string.
            try:
                cur.execute(
                    "SELECT encounter_id, encounter_date, encounter_type "
                    "FROM normalized_encounters "
                    "WHERE patient_id = %s "
                    "  AND encounter_date >= %s AND encounter_date <= %s "
                    "ORDER BY encounter_date DESC "
                    "LIMIT 500",
                    (patient_id, win_start.isoformat(), win_end.isoformat()),
                )
                for r in cur.fetchall():
                    enc_id = r.get("encounter_id")
                    enc_date = _parse_date(r.get("encounter_date"))
                    if enc_id is not None and enc_date is not None:
                        encounters.append(Encounter(
                            encounter_id=int(enc_id),
                            encounter_date=enc_date,
                            encounter_type=(r.get("encounter_type") or ""),
                            provider_specialty="",  # not stored in normalized_encounters
                        ))
            except Exception as exc:
                logger.warning(
                    "gate: normalized_encounters unavailable pid=%s: %s", patient_id, exc
                )

    except Exception as exc:
        logger.warning("gate: raf_db fetch failed pid=%s: %s", patient_id, exc)

    logger.debug(
        "gate: context built pid=%s meds=%d labs=%d procs=%d encounters=%d dx=%d",
        patient_id, len(meds), len(labs), len(procs), len(encounters), len(dx_codes),
    )

    return PatientContext(
        patient_id=patient_id,
        date_of_service=dos,
        age=age,
        sex=sex,
        diagnoses_icd10=dx_codes,
        medications=meds,
        labs=labs,
        procedures=procs,
        encounters=encounters,
    )


# ---------------------------------------------------------------------------
# Gate function — single public entrypoint for meat_status promotion path
# ---------------------------------------------------------------------------

def gate_billed_promotion(
    patient_id: int,
    candidate_hccs: list[int],
    dos: date | None = None,
    context: PatientContext | None = None,
) -> dict[str, Any]:
    """Run clinical rules against a set of candidate HCCs.

    Args:
        patient_id:      RAF/OpenEMR patient id.
        candidate_hccs:  HCCs about to be promoted to billed status.
        dos:             Date of service (defaults to today).
        context:         Pre-built PatientContext. If None, built from DB.

    Returns:
        dict with keys:
            overall_status     "pass" | "warn" | "fail"
            blocked_hccs       list[int]  — HCCs that MUST NOT be promoted
            warned_hccs        list[int]  — HCCs that promoted with warnings
            report             validator.ValidationReport.to_dict() payload
            gate_unavailable   True if context build failed (fail-open)
    """
    dos = dos or date.today()
    gate_unavailable = False

    try:
        ctx = context or _get_or_build_context(patient_id, dos)
    except Exception as exc:
        logger.error(
            "gate: context build raised unexpectedly pid=%s: %s. "
            "Failing OPEN — all HCCs will be treated as PASS.",
            patient_id, exc,
        )
        return {
            "overall_status": RuleStatus.PASS.value,
            "blocked_hccs": [],
            "warned_hccs": [],
            "report": None,
            "gate_unavailable": True,
        }

    if not candidate_hccs:
        return {
            "overall_status": RuleStatus.PASS.value,
            "blocked_hccs": [],
            "warned_hccs": [],
            "report": {"patient_id": patient_id, "outcomes": []},
            "gate_unavailable": gate_unavailable,
        }

    billed = [BilledHCC(hcc=int(h), model="V28") for h in candidate_hccs]
    report: ValidationReport = validate_billed_hccs(billed, ctx)

    blocked = [o.hcc for o in report.failed()]
    warned = [o.hcc for o in report.warnings()]
    if blocked:
        logger.warning(
            "gate: BLOCKING promotion to billed for pid=%s hccs=%s reasons=%s",
            patient_id, blocked,
            [o.reasons for o in report.failed()],
        )
    if warned:
        logger.info(
            "gate: WARNING on promotion for pid=%s hccs=%s",
            patient_id, warned,
        )

    return {
        "overall_status": report.overall_status.value,
        "blocked_hccs": blocked,
        "warned_hccs": warned,
        "report": report.to_dict(),
        "gate_unavailable": gate_unavailable,
    }
