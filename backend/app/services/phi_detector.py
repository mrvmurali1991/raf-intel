"""
PHI Detector — pattern-based detection of Protected Health Information.

Uses regex patterns to identify fields containing PHI per HIPAA Safe Harbor
method (§164.514(b)(2)).  Augments the manually curated ``_PHI_KEYS`` set
in ``main.py`` by scanning arbitrary data dicts at runtime.

Usage:
    from app.services.phi_detector import detect_phi_in_dict, PHI_FIELD_NAMES

    findings = detect_phi_in_dict({"patient_name": "Jane Doe", "score": 1.2})
    # => [{"field": "patient_name", "reason": "name_pattern"}, ...]
"""
from __future__ import annotations

import re
from typing import Any

# -------------------------------------------------------------------------
# Comprehensive PHI field name set — union of all tables in the system
# -------------------------------------------------------------------------
PHI_FIELD_NAMES: set[str] = {
    # Names
    "fname", "lname", "first_name", "last_name", "mname", "middle_name",
    "patient_name", "name", "provider_name", "subscriber_name",
    "maiden_name", "preferred_name", "legal_name", "alias",
    "guarantor_name", "emergency_contact_name", "next_of_kin",
    # Dates
    "dob", "DOB", "date_of_birth", "birth_date", "birthdate",
    "death_date", "date_of_death", "admission_date", "discharge_date",
    # Identifiers
    "ssn", "social_security", "ssn_last4",
    "mrn", "medical_record_number", "patient_id_external",
    "mbi", "medicare_id", "medicare_beneficiary_id", "hicn",
    "medicaid_id", "insurance_id", "subscriber_id", "policy_number",
    "group_number", "member_id", "plan_id",
    "npi", "provider_npi", "referring_npi", "billing_npi",
    "drivers_license", "passport_number",
    # Contact
    "phone", "phone_home", "phone_cell", "phone_work", "phone_number",
    "fax", "fax_number",
    "email", "email_address", "patient_email",
    # Address
    "address", "street", "street_address", "address_line1", "address_line2",
    "city", "state", "zip", "zip_code", "postal_code", "county",
    "country",
    # Account / financial
    "account_number", "billing_account", "claim_number",
    "bank_account", "credit_card", "routing_number",
    # Clinical identifiers that can be PHI
    "encounter_id", "accession_number", "specimen_id",
    # Device / vehicle
    "device_serial", "vin", "license_plate",
    # Web / IP
    "ip_address", "url", "biometric_id",
    # Photos
    "photo", "image_url", "face_image",
}

# Lower-cased version for fast membership checks
_PHI_FIELD_NAMES_LOWER: set[str] = {k.lower() for k in PHI_FIELD_NAMES}

# -------------------------------------------------------------------------
# Value-level regex patterns
# -------------------------------------------------------------------------
_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("phone", re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")),
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")),
    ("mrn", re.compile(r"\bMRN[:\s#-]*\d{4,}\b", re.IGNORECASE)),
    ("npi", re.compile(r"\b\d{10}\b")),  # NPI is exactly 10 digits
    ("dob", re.compile(
        r"\b(?:0[1-9]|1[0-2])[/\-](?:0[1-9]|[12]\d|3[01])[/\-](?:19|20)\d{2}\b"
    )),
    ("date_iso", re.compile(
        r"\b(?:19|20)\d{2}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])\b"
    )),
    ("zip_code", re.compile(r"\b\d{5}(?:-\d{4})?\b")),
]


def detect_phi_in_dict(
    data: dict[str, Any],
    *,
    check_values: bool = True,
) -> list[dict[str, str]]:
    """Scan a dict for fields that contain or likely contain PHI.

    Returns a list of ``{"field": ..., "reason": ...}`` dicts.

    Parameters
    ----------
    data : dict
        Flat dictionary to inspect.
    check_values : bool
        When True (default), also run regex patterns against string values.
    """
    findings: list[dict[str, str]] = []
    if not isinstance(data, dict):
        return findings

    for key, value in data.items():
        key_lower = key.lower()

        # 1. Field name match
        if key_lower in _PHI_FIELD_NAMES_LOWER:
            findings.append({"field": key, "reason": "phi_field_name"})
            continue

        # 2. Heuristic name fragments
        for fragment in ("name", "phone", "email", "addr", "ssn", "birth", "npi", "mrn", "mbi"):
            if fragment in key_lower:
                findings.append({"field": key, "reason": f"name_contains_{fragment}"})
                break
        else:
            # 3. Value pattern matching
            if check_values and isinstance(value, str) and len(value) < 500:
                for pattern_name, pattern in _PATTERNS:
                    if pattern.search(value):
                        findings.append({"field": key, "reason": f"value_matches_{pattern_name}"})
                        break

    return findings


def get_phi_field_names() -> set[str]:
    """Return the full set of known PHI field names (lower-cased)."""
    return _PHI_FIELD_NAMES_LOWER.copy()
