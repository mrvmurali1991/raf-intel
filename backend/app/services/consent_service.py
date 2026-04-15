"""
Consent Management Service — patient consent tracking for HIPAA compliance.

Tracks patient consent for data sharing, research use, treatment, and other
purposes.  Supports recording, checking, and revoking consent with full
audit trails via the immutable audit log.

Usage:
    from app.services.consent_service import record_consent, check_consent, revoke_consent

    record_consent(patient_id=123, tenant_id="1", consent_type="data_sharing", granted=True)
    allowed = check_consent(patient_id=123, tenant_id="1", consent_type="data_sharing")
    revoke_consent(patient_id=123, tenant_id="1", consent_type="data_sharing", revoked_by=42)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.db import raf_cursor
from app.services.immutable_audit import append_audit_entry

logger = logging.getLogger(__name__)

# Valid consent types
CONSENT_TYPES = {
    "data_sharing",
    "research_use",
    "treatment",
    "marketing",
    "third_party_disclosure",
    "analytics",
    "care_coordination",
}


def record_consent(
    *,
    patient_id: int,
    tenant_id: str,
    consent_type: str,
    granted: bool,
    expires_at: str | datetime | None = None,
    granted_by: int | None = None,
    details: str = "",
) -> dict[str, Any]:
    """Record or update a patient consent decision.

    If a consent record already exists for (patient_id, tenant_id, consent_type),
    it is updated.  Otherwise a new record is created.
    """
    if consent_type not in CONSENT_TYPES:
        raise ValueError(
            f"Invalid consent_type '{consent_type}'. "
            f"Valid types: {', '.join(sorted(CONSENT_TYPES))}"
        )

    expires_at_str: str | None = None
    if expires_at:
        if isinstance(expires_at, datetime):
            expires_at_str = expires_at.isoformat()
        else:
            expires_at_str = str(expires_at)

    now = datetime.now(tz=timezone.utc)

    with raf_cursor() as cur:
        # Check for existing record
        cur.execute(
            "SELECT id FROM patient_consents "
            "WHERE patient_id = %s AND tenant_id = %s AND consent_type = %s",
            (patient_id, tenant_id, consent_type),
        )
        existing = cur.fetchone()

        if existing:
            cur.execute(
                "UPDATE patient_consents SET granted = %s, granted_at = %s, "
                "expires_at = %s, revoked_at = NULL, details = %s, updated_at = %s "
                "WHERE id = %s",
                (granted, now, expires_at_str, details, now, existing["id"]),
            )
            record_id = existing["id"]
        else:
            cur.execute(
                "INSERT INTO patient_consents "
                "(patient_id, tenant_id, consent_type, granted, granted_at, "
                "expires_at, details, created_at, updated_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (patient_id, tenant_id, consent_type, granted, now,
                 expires_at_str, details, now, now),
            )
            record_id = cur.lastrowid

    append_audit_entry(
        event_type="consent_recorded",
        user_id=granted_by,
        tenant_id=tenant_id,
        resource_type="patient_consent",
        resource_id=str(record_id),
        action="consent_grant" if granted else "consent_deny",
        details={
            "patient_id": patient_id,
            "consent_type": consent_type,
            "granted": granted,
            "expires_at": expires_at_str,
        },
    )

    return {
        "id": record_id,
        "patient_id": patient_id,
        "tenant_id": tenant_id,
        "consent_type": consent_type,
        "granted": granted,
        "granted_at": now.isoformat(),
        "expires_at": expires_at_str,
    }


def check_consent(
    *,
    patient_id: int,
    tenant_id: str,
    consent_type: str,
) -> bool:
    """Check if a patient has active consent for a given type.

    Returns True only if consent is granted, not revoked, and not expired.
    """
    with raf_cursor() as cur:
        cur.execute(
            "SELECT granted, expires_at, revoked_at FROM patient_consents "
            "WHERE patient_id = %s AND tenant_id = %s AND consent_type = %s "
            "ORDER BY updated_at DESC LIMIT 1",
            (patient_id, tenant_id, consent_type),
        )
        row = cur.fetchone()

    if not row:
        return False
    if not row["granted"]:
        return False
    if row["revoked_at"] is not None:
        return False
    if row["expires_at"]:
        exp = row["expires_at"]
        if isinstance(exp, str):
            exp = datetime.fromisoformat(exp)
        if isinstance(exp, datetime) and exp < datetime.now(tz=timezone.utc):
            return False
    return True


def revoke_consent(
    *,
    patient_id: int,
    tenant_id: str,
    consent_type: str,
    revoked_by: int | None = None,
) -> bool:
    """Revoke a patient's consent. Returns True if a record was updated."""
    now = datetime.now(tz=timezone.utc)

    with raf_cursor() as cur:
        cur.execute(
            "UPDATE patient_consents SET revoked_at = %s, updated_at = %s "
            "WHERE patient_id = %s AND tenant_id = %s AND consent_type = %s "
            "AND revoked_at IS NULL",
            (now, now, patient_id, tenant_id, consent_type),
        )
        affected = cur.rowcount

    if affected > 0:
        append_audit_entry(
            event_type="consent_revoked",
            user_id=revoked_by,
            tenant_id=tenant_id,
            resource_type="patient_consent",
            resource_id=str(patient_id),
            action="consent_revoke",
            details={
                "patient_id": patient_id,
                "consent_type": consent_type,
            },
        )
    return affected > 0


def list_consents(
    *,
    patient_id: int,
    tenant_id: str,
) -> list[dict[str, Any]]:
    """List all consent records for a patient."""
    with raf_cursor() as cur:
        cur.execute(
            "SELECT id, patient_id, tenant_id, consent_type, granted, "
            "granted_at, expires_at, revoked_at, details, created_at, updated_at "
            "FROM patient_consents "
            "WHERE patient_id = %s AND tenant_id = %s "
            "ORDER BY updated_at DESC",
            (patient_id, tenant_id),
        )
        rows = cur.fetchall()
    result = []
    for r in rows:
        row_dict = dict(r)
        for k in ("granted_at", "expires_at", "revoked_at", "created_at", "updated_at"):
            if row_dict.get(k) and isinstance(row_dict[k], datetime):
                row_dict[k] = row_dict[k].isoformat()
        result.append(row_dict)
    return result
