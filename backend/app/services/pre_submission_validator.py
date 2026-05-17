"""
Pre-Submission Validator — Edifecs-RAEM-style coding-rule engine.

Runs a battery of validation rules over every ``raf_patient_hcc`` row for a
given tenant + measurement year and surfaces violations BEFORE an 837/EDPS
file ever ships. Catches things that, once submitted, would cost real money:

    R1  MEAT missing       — meat_status='missing' AND is_trumped=0 (MEDIUM)
    R2  Trumped but live   — is_trumped=1, would be invalid in the file (MEDIUM)
    R3  Invalid ICD-10     — icd10 not in simple_icd_10_cm (HIGH)
    R4  Unmapped HCC       — hcc_code IS NULL or 0 (HIGH)
    R5  Stale source       — created_at < NOW() - INTERVAL 18 MONTH (LOW)

The validator is read-only — it never mutates raf_patient_hcc, never queues
work, and never blocks submission. It returns a structured list of findings
the UI/dashboard renders so the coding team can fix issues before submit.

Tenant scoping
--------------
``raf_patient_hcc`` has no ``tenant_id`` column of its own — every row's
patient_id joins to ``patients.tenant_id`` for the tenant filter. This is
the same approach ``data_quality_monitor`` uses.

Public API
----------
    validate(cursor, tenant_id, measurement_year) -> list[Finding]

Each Finding is a dict with the keys documented on ``Finding`` below.
"""
from __future__ import annotations

import json
import logging
from typing import Any, TypedDict

from app.services.icd_validator import validate_icd10_code

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result shape
# ---------------------------------------------------------------------------

class Finding(TypedDict):
    """One coding-rule violation surfaced to the pre-submit dashboard."""
    rule_id: str          # "R1" .. "R5"
    severity: str         # "HIGH" | "MEDIUM" | "LOW"
    hcc_id: int           # raf_patient_hcc.id
    hcc_code: int | None  # raf_patient_hcc.hcc_code (None when unmapped)
    icd10: str | None     # offending ICD-10 (R3) or representative code
    patient_id: int       # raf_patient_hcc.patient_id
    message: str          # human-readable explanation


SEVERITY_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}

RULE_DESCRIPTIONS: dict[str, str] = {
    "R1": "Missing MEAT — HCC has no Monitor/Evaluate/Assess/Treat evidence in the chart.",
    "R2": "Trumped but submitted — row is suppressed by hierarchy and would be invalid in the 837.",
    "R3": "Invalid ICD-10 — code not found in simple_icd_10_cm (CMS would reject).",
    "R4": "Unmapped HCC — hcc_code is 0/NULL, no risk weight will be paid.",
    "R5": "Stale source — supporting encounter is older than 18 months.",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_icd_list(value: Any) -> list[str]:
    """Return a list of ICD-10 codes from the raf_patient_hcc.icd10_codes column.

    The column is JSON, but some MySQL drivers hand it back as a parsed list,
    others as a JSON string. Be defensive.
    """
    if value is None:
        return []
    if isinstance(value, list):
        return [str(c) for c in value if c]
    if isinstance(value, (bytes, bytearray)):
        try:
            value = value.decode("utf-8")
        except Exception:
            return []
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(c) for c in parsed if c]
        except Exception:
            # Fall back to single-code-as-string treatment.
            stripped = value.strip()
            if stripped and stripped not in ("[]", "null"):
                return [stripped]
    return []


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def validate(cursor: Any, tenant_id: int, measurement_year: int) -> list[Finding]:
    """Run all coding-rule checks for *tenant_id* + *measurement_year*.

    Parameters
    ----------
    cursor:
        A mysql-connector dictionary cursor (caller manages the connection
        lifecycle — typically via ``app.db.raf_cursor(dictionary=True)``).
    tenant_id:
        Numeric tenant id from the authenticated user.
    measurement_year:
        The measurement year to validate (e.g. 2026).

    Returns
    -------
    A list of ``Finding`` dicts. Empty list means the scope is clean.

    Notes
    -----
    The query joins to ``patients`` for tenant scoping. Rows belonging to
    patients in a different tenant are not loaded — there is no risk of
    cross-tenant data leak even if the rule code below has a bug.
    """
    findings: list[Finding] = []

    sql = """
        SELECT
            h.id              AS hcc_id,
            h.patient_id      AS patient_id,
            h.hcc_code        AS hcc_code,
            h.icd10_codes     AS icd10_codes,
            h.meat_status     AS meat_status,
            h.is_trumped      AS is_trumped,
            h.created_at      AS created_at,
            (h.created_at < NOW() - INTERVAL 18 MONTH) AS is_stale
        FROM raf_patient_hcc h
        JOIN patients p ON p.id = h.patient_id
        WHERE p.tenant_id = %(tenant_id)s
          AND h.measurement_year = %(year)s
        ORDER BY h.id
    """

    try:
        cursor.execute(sql, {"tenant_id": tenant_id, "year": measurement_year})
        rows = cursor.fetchall()
    except Exception as exc:
        logger.exception("pre_submission_validator: query failed")
        # Re-raise so the router can return 500 — silently returning [] would
        # hide real outages and the dashboard would falsely show "All clear".
        raise RuntimeError(f"Pre-submission query failed: {exc}") from exc

    for row in rows:
        hcc_id = int(row["hcc_id"])
        patient_id = int(row["patient_id"])
        hcc_code_raw = row.get("hcc_code")
        hcc_code = int(hcc_code_raw) if hcc_code_raw is not None else None
        meat_status = (row.get("meat_status") or "").lower()
        is_trumped = int(row.get("is_trumped") or 0)
        is_stale = bool(row.get("is_stale"))
        icd_codes = _parse_icd_list(row.get("icd10_codes"))
        primary_icd = icd_codes[0] if icd_codes else None

        # ----- R1: missing MEAT (skip if trumped — R2 already covers that) -
        if meat_status == "missing" and is_trumped == 0:
            findings.append(Finding(
                rule_id="R1",
                severity="MEDIUM",
                hcc_id=hcc_id,
                hcc_code=hcc_code,
                icd10=primary_icd,
                patient_id=patient_id,
                message=(
                    f"HCC {hcc_code or '?'} for patient {patient_id} has "
                    "meat_status='missing'. Add chart evidence (Monitor / "
                    "Evaluate / Assess / Treat) before submission or CMS RADV "
                    "will reverse the payment."
                ),
            ))

        # ----- R2: trumped row — must not be submitted ---------------------
        if is_trumped == 1:
            findings.append(Finding(
                rule_id="R2",
                severity="MEDIUM",
                hcc_id=hcc_id,
                hcc_code=hcc_code,
                icd10=primary_icd,
                patient_id=patient_id,
                message=(
                    f"HCC {hcc_code or '?'} for patient {patient_id} is "
                    "marked is_trumped=1 by the CMS-HCC hierarchy. "
                    "Submitting this row would create an invalid duplicate — "
                    "exclude it from the 837 generation."
                ),
            ))

        # ----- R3: each ICD-10 must validate against simple_icd_10_cm ------
        for icd in icd_codes:
            try:
                ok = validate_icd10_code(icd)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "pre_submission_validator: ICD validation crashed for %r: %s",
                    icd, exc,
                )
                ok = False
            if not ok:
                findings.append(Finding(
                    rule_id="R3",
                    severity="HIGH",
                    hcc_id=hcc_id,
                    hcc_code=hcc_code,
                    icd10=icd,
                    patient_id=patient_id,
                    message=(
                        f"ICD-10 code {icd!r} on HCC {hcc_code or '?'} "
                        f"(patient {patient_id}) is not a valid, assignable "
                        "ICD-10-CM leaf code. CMS will reject this claim."
                    ),
                ))

        # ----- R4: HCC must be mapped (non-zero, non-NULL) -----------------
        if hcc_code in (None, 0):
            findings.append(Finding(
                rule_id="R4",
                severity="HIGH",
                hcc_id=hcc_id,
                hcc_code=hcc_code,
                icd10=primary_icd,
                patient_id=patient_id,
                message=(
                    f"raf_patient_hcc row {hcc_id} for patient {patient_id} "
                    "has no HCC mapping (hcc_code is 0/NULL). No risk weight "
                    "will be paid — re-run the HCC mapper or correct the "
                    "ICD-10 list."
                ),
            ))

        # ----- R5: stale source (older than 18 months) ---------------------
        if is_stale:
            findings.append(Finding(
                rule_id="R5",
                severity="LOW",
                hcc_id=hcc_id,
                hcc_code=hcc_code,
                icd10=primary_icd,
                patient_id=patient_id,
                message=(
                    f"HCC {hcc_code or '?'} for patient {patient_id} was "
                    "captured more than 18 months ago. Refresh from a recent "
                    "encounter before submission or the diagnosis may be "
                    "questioned in audit."
                ),
            ))

    # Deterministic ordering: HIGH first, then MEDIUM, then LOW, ties by hcc_id
    findings.sort(key=lambda f: (SEVERITY_ORDER.get(f["severity"], 9), f["hcc_id"]))
    return findings


# ---------------------------------------------------------------------------
# Aggregation helpers (used by the router)
# ---------------------------------------------------------------------------

def summarize(findings: list[Finding]) -> dict[str, Any]:
    """Compute rule and severity totals for the dashboard KPIs."""
    rule_counts: dict[str, int] = {rid: 0 for rid in RULE_DESCRIPTIONS}
    severity_counts: dict[str, int] = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for f in findings:
        rule_counts[f["rule_id"]] = rule_counts.get(f["rule_id"], 0) + 1
        severity_counts[f["severity"]] = severity_counts.get(f["severity"], 0) + 1
    return {"rule_counts": rule_counts, "severity_counts": severity_counts}
