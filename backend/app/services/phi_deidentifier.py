"""
PHI De-identification Service — HIPAA Safe Harbor method.

Implements the Safe Harbor de-identification standard per HIPAA
§164.514(b)(2), removing or transforming the 18 categories of identifiers.

Usage:
    from app.services.phi_deidentifier import deidentify_patient, deidentify_dataset

    safe = deidentify_patient(patient_dict)
    safe_batch = deidentify_dataset(records)
"""
from __future__ import annotations

import hashlib
import random
import re
from copy import deepcopy
from datetime import date, datetime, timedelta
from typing import Any

from app.services.phi_detector import PHI_FIELD_NAMES, detect_phi_in_dict

# -------------------------------------------------------------------------
# Per-patient date shift — deterministic offset derived from patient_id
# so the same patient always gets the same shift (preserving intervals).
# -------------------------------------------------------------------------
_DATE_SHIFT_RANGE_DAYS = 365  # +/- 1 year


def _date_shift_days(patient_id: str | int) -> int:
    """Deterministic pseudo-random day offset for a patient."""
    seed = int(hashlib.sha256(str(patient_id).encode()).hexdigest(), 16)
    rng = random.Random(seed)
    return rng.randint(-_DATE_SHIFT_RANGE_DAYS, _DATE_SHIFT_RANGE_DAYS)


def _shift_date(value: Any, shift_days: int) -> str | None:
    """Shift a date value by *shift_days*.  Returns ISO string or None."""
    if value is None:
        return None
    dt: date | None = None
    if isinstance(value, datetime):
        dt = value.date()
    elif isinstance(value, date):
        dt = value
    elif isinstance(value, str):
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y-%m-%dT%H:%M:%S", "%m-%d-%Y"):
            try:
                dt = datetime.strptime(value[:10], fmt).date()
                break
            except (ValueError, IndexError):
                continue
    if dt is None:
        return "[DATE REMOVED]"
    shifted = dt + timedelta(days=shift_days)
    return shifted.isoformat()


# Fields that should be date-shifted rather than removed
_DATE_FIELDS = {
    "dob", "date_of_birth", "birth_date", "birthdate", "DOB",
    "death_date", "date_of_death", "admission_date", "discharge_date",
    "service_date", "encounter_date", "created_at", "updated_at",
}

# Fields to replace with a synthetic token rather than blank
_REDACT_TOKEN = "[REDACTED]"

# Fields containing names — replace with generic
_NAME_FIELDS = {
    "fname", "lname", "first_name", "last_name", "mname", "middle_name",
    "patient_name", "name", "maiden_name", "preferred_name", "legal_name",
    "alias", "guarantor_name", "emergency_contact_name", "next_of_kin",
    "provider_name", "subscriber_name",
}

# Lower-cased sets for matching
_DATE_FIELDS_LOWER = {f.lower() for f in _DATE_FIELDS}
_NAME_FIELDS_LOWER = {f.lower() for f in _NAME_FIELDS}
_PHI_LOWER = {f.lower() for f in PHI_FIELD_NAMES}

# Regex for ages > 89 — Safe Harbor requires aggregation to 90+
_AGE_FIELDS = {"age", "patient_age"}


def deidentify_patient(
    patient: dict[str, Any],
    patient_id_key: str = "id",
) -> dict[str, Any]:
    """Return a de-identified copy of a patient record.

    - Names replaced with ``[REDACTED]``
    - Dates shifted by a deterministic per-patient offset
    - SSN, MRN, MBI, phone, email, address fully removed
    - Ages > 89 capped to 90
    - All other detected PHI fields redacted
    """
    result = deepcopy(patient)
    pid = str(result.get(patient_id_key, "unknown"))
    shift = _date_shift_days(pid)

    # Replace the patient ID itself with a one-way token
    if patient_id_key in result:
        result[patient_id_key] = hashlib.sha256(
            f"deid-{pid}".encode()
        ).hexdigest()[:16]

    for key in list(result.keys()):
        key_lower = key.lower()

        # Name fields
        if key_lower in _NAME_FIELDS_LOWER:
            result[key] = _REDACT_TOKEN
            continue

        # Date fields — shift
        if key_lower in _DATE_FIELDS_LOWER:
            result[key] = _shift_date(result[key], shift)
            continue

        # Age cap
        if key_lower in _AGE_FIELDS:
            try:
                age = int(result[key])
                if age > 89:
                    result[key] = 90
            except (ValueError, TypeError):
                pass
            continue

        # Other known PHI fields — redact
        if key_lower in _PHI_LOWER:
            result[key] = _REDACT_TOKEN
            continue

    # Second pass: detect any remaining PHI by value patterns
    findings = detect_phi_in_dict(result, check_values=True)
    for finding in findings:
        field = finding["field"]
        if field in result and result[field] != _REDACT_TOKEN:
            result[field] = _REDACT_TOKEN

    return result


def deidentify_dataset(
    records: list[dict[str, Any]],
    patient_id_key: str = "id",
) -> list[dict[str, Any]]:
    """De-identify a batch of patient records."""
    return [deidentify_patient(r, patient_id_key=patient_id_key) for r in records]
