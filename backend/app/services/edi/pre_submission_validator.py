"""
Pre-submission validator (R1–R6) — lightweight gate run before 837 generation.

This is an MVP shim that mirrors the rule layout of the full validator
landing on `feat/pre-submission-validator`.  When that branch merges, this
module should delegate to the canonical implementation.

Rules
-----
    R1  Patient exists and has demographic data            (HIGH on miss)
    R2  Patient has MBI/HICN                               (HIGH on miss)
    R3  At least one confirmed HCC for the payment year    (HIGH on miss)
    R4  All ICD-10 codes pass format check                 (HIGH per code)
    R5  An encounter exists with a valid date-of-service   (MEDIUM)
    R6  Provider NPI is 10 digits                          (MEDIUM)

Returned shape per patient:
    {
        "patient_id": int,
        "passed": bool,
        "severity_summary": {"HIGH": int, "MEDIUM": int, "LOW": int},
        "findings": [{"rule": "R1", "severity": "HIGH", "message": "..."}],
    }
"""

from __future__ import annotations

import logging
import re
from typing import Any

from app.services.edi.common import normalize_icd10

logger = logging.getLogger(__name__)

SEV_HIGH = "HIGH"
SEV_MEDIUM = "MEDIUM"
SEV_LOW = "LOW"

_NPI_RE = re.compile(r"^\d{10}$")


def _has_patient(patient_id: int) -> dict[str, Any] | None:
    try:
        from app.db import raf_cursor

        with raf_cursor() as cur:
            cur.execute(
                "SELECT id, first_name, last_name, dob, sex FROM patients WHERE id = %s",
                (patient_id,),
            )
            return cur.fetchone()
    except Exception as exc:
        logger.warning("pre-submission R1 lookup failed for %s: %s", patient_id, exc)
        return None


def _patient_mbi(patient_id: int) -> str | None:
    try:
        from app.db import raf_cursor

        with raf_cursor() as cur:
            cur.execute(
                "SELECT hicn_mbi FROM raf_patient_demographics WHERE patient_id = %s",
                (patient_id,),
            )
            row = cur.fetchone() or {}
            return (row.get("hicn_mbi") or "").strip() or None
    except Exception:  # noqa: BLE001 — best-effort guard
        logger.debug("swallowed exception", exc_info=True)
        return None


def _patient_hcc_rows(patient_id: int, payment_year: int) -> list[dict[str, Any]]:
    try:
        from app.db import raf_cursor

        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT icd10_codes, status FROM raf_patient_hcc
                WHERE patient_id = %s AND measurement_year = %s
                """,
                (patient_id, payment_year),
            )
            return cur.fetchall() or []
    except Exception:  # noqa: BLE001 — best-effort guard
        logger.debug("swallowed exception", exc_info=True)
        return []


def _patient_encounter(patient_id: int) -> dict[str, Any] | None:
    try:
        from app.db import raf_cursor

        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT id, encounter_date, provider_npi
                FROM encounters
                WHERE patient_id = %s
                ORDER BY encounter_date DESC
                LIMIT 1
                """,
                (patient_id,),
            )
            return cur.fetchone()
    except Exception:  # noqa: BLE001 — best-effort guard
        logger.debug("swallowed exception", exc_info=True)
        return None


def _extract_icd10s(rows: list[dict[str, Any]]) -> list[str]:
    import json

    codes: list[str] = []
    for r in rows:
        raw = r.get("icd10_codes")
        if not raw:
            continue
        if isinstance(raw, str):
            stripped = raw.strip()
            if stripped.startswith("["):
                try:
                    items = json.loads(stripped)
                except Exception:
                    logger.debug("swallowed exception", exc_info=True)
                    items = [x.strip() for x in stripped.split(",")]
            else:
                items = [x.strip() for x in stripped.split(",")]
        elif isinstance(raw, list):
            items = list(raw)
        else:
            continue
        for c in items:
            if c and c not in codes:
                codes.append(c)
    return codes


def validate_patient(patient_id: int, payment_year: int) -> dict[str, Any]:
    findings: list[dict[str, str]] = []

    patient = _has_patient(patient_id)
    if not patient:
        findings.append({"rule": "R1", "severity": SEV_HIGH,
                         "message": f"Patient {patient_id} not found"})
        return _summarise(patient_id, findings)
    if not patient.get("dob") or not patient.get("first_name") or not patient.get("last_name"):
        findings.append({"rule": "R1", "severity": SEV_HIGH,
                         "message": "Patient missing core demographics (name/dob)"})

    if not _patient_mbi(patient_id):
        findings.append({"rule": "R2", "severity": SEV_HIGH,
                         "message": "No HICN/MBI on file"})

    hcc_rows = _patient_hcc_rows(patient_id, payment_year)
    if not hcc_rows:
        findings.append({"rule": "R3", "severity": SEV_HIGH,
                         "message": f"No HCC records for payment year {payment_year}"})

    icd_codes = _extract_icd10s(hcc_rows)
    bad_codes = [c for c in icd_codes if not normalize_icd10(c)]
    for c in bad_codes:
        findings.append({"rule": "R4", "severity": SEV_HIGH,
                         "message": f"Invalid ICD-10 format: {c}"})

    enc = _patient_encounter(patient_id)
    if not enc or not enc.get("encounter_date"):
        findings.append({"rule": "R5", "severity": SEV_MEDIUM,
                         "message": "No encounter with valid date-of-service"})
    if enc and enc.get("provider_npi"):
        npi = re.sub(r"\D+", "", str(enc.get("provider_npi") or ""))
        if not _NPI_RE.match(npi):
            findings.append({"rule": "R6", "severity": SEV_MEDIUM,
                             "message": f"Provider NPI is not 10 digits: '{enc.get('provider_npi')}'"})

    return _summarise(patient_id, findings)


def _summarise(patient_id: int, findings: list[dict[str, str]]) -> dict[str, Any]:
    summary = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for f in findings:
        summary[f["severity"]] = summary.get(f["severity"], 0) + 1
    return {
        "patient_id": patient_id,
        "passed": summary["HIGH"] == 0,
        "severity_summary": summary,
        "findings": findings,
    }


def validate_batch(patient_ids: list[int], payment_year: int) -> dict[str, Any]:
    results = [validate_patient(pid, payment_year) for pid in patient_ids]
    high = sum(r["severity_summary"]["HIGH"] for r in results)
    med = sum(r["severity_summary"]["MEDIUM"] for r in results)
    passed_ids = [r["patient_id"] for r in results if r["passed"]]
    failed_ids = [r["patient_id"] for r in results if not r["passed"]]
    return {
        "total": len(results),
        "passed": len(passed_ids),
        "failed": len(failed_ids),
        "high_severity_total": high,
        "medium_severity_total": med,
        "passed_patient_ids": passed_ids,
        "failed_patient_ids": failed_ids,
        "per_patient": results,
    }
