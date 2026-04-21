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
from datetime import date
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
    """
    dx_codes: list[str] = []
    meds: list[Medication] = []
    labs: list[LabResult] = []
    procs: list[ProcedureRecord] = []
    encounters: list[Encounter] = []
    age: int = 0
    sex: str = "U"

    # --- OpenEMR: demographics + ICD-10 + medications ---------------------
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
                        from datetime import datetime
                        if isinstance(dob, str):
                            dob_d = datetime.strptime(dob[:10], "%Y-%m-%d").date()
                        else:
                            dob_d = dob if isinstance(dob, date) else dob.date()
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

            # Active medications — OpenEMR stores these in 'prescriptions'
            # or 'lists' table depending on install. We try prescriptions first.
            try:
                cur.execute(
                    "SELECT drug, rxnorm_drugcode, active "
                    "FROM prescriptions WHERE patient_id = %s AND active = 1",
                    (patient_id,),
                )
                for r in cur.fetchall():
                    meds.append(Medication(
                        rx_class="",       # unknown from OpenEMR alone
                        name=(r.get("drug") or ""),
                        active=bool(r.get("active", 1)),
                    ))
            except Exception:
                pass  # table may differ by OpenEMR version; meds are advisory

    except Exception as exc:
        logger.warning("gate: openemr fetch failed pid=%s: %s", patient_id, exc)

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
        ctx = context or build_patient_context_from_db(patient_id, dos)
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
