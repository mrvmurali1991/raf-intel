"""
HIPAA Audit Logger
Logs all access to Protected Health Information (PHI) for compliance.

Every read, analysis, or export of patient data must call log_phi_access()
so there is a durable audit trail satisfying the HIPAA Security Rule
§164.312(b) audit-controls standard.

The phi_audit logger is intentionally separate from the application logger
so it can be routed to a dedicated sink (file, CloudWatch, SIEM) without
mixing with general debug output.  Configure it in your logging setup, e.g.:

    [loggers]
    keys = phi_audit

    [handlers]
    keys = phi_file

    [logger_phi_audit]
    level    = INFO
    handlers = phi_file
    propagate = 0
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

# Dedicated logger — configure its handler in logging.ini / dictConfig
phi_logger = logging.getLogger("phi_audit")
_app_logger = logging.getLogger(__name__)


def log_phi_access(
    action: str,
    resource: str,
    patient_id: int | None = None,
    encounter_id: int | None = None,
    user: str = "system",
    details: str = "",
    tenant_id: int | None = None,
) -> None:
    """
    Emit a structured PHI-access audit record.

    Parameters
    ----------
    action:       Semantic operation — "view", "analyze", "export", "search",
                  "batch_analyze", "list".
    resource:     Data type accessed — "patient", "encounter", "clinical_note",
                  "diagnosis", "medication", "lab", "procedure", "profile".
    patient_id:   OpenEMR patient PID, if known.
    encounter_id: OpenEMR encounter ID, if known.
    user:         Authenticated username or "system" for background jobs.
    details:      Optional free-text context (keep PHI-free — IDs only).
    """
    if user == "system":
        _app_logger.warning(
            "PHI access logged without user identity — caller should pass user_id"
        )
    if tenant_id is None:
        _app_logger.warning(
            "no tenant_id provided, defaulting to 1 — caller: log_phi_access"
        )
        tid: int = 1
    else:
        tid = int(tenant_id)
    phi_logger.info(
        "PHI_ACCESS | action=%s | resource=%s | patient_id=%s | encounter_id=%s"
        " | user=%s | tenant=%s | timestamp=%s | details=%s",
        action,
        resource,
        patient_id,
        encounter_id,
        user,
        tid,
        datetime.now(tz=timezone.utc).isoformat(),
        details,
    )

    # Persist PHI access record to the database for durable HIPAA audit trail.
    try:
        from app.db import raf_cursor  # local import to avoid circular dependency

        # user may be a numeric string (user_id) or a username; coerce to int when possible.
        try:
            db_user_id: int | None = int(user)
        except (ValueError, TypeError):
            db_user_id = None

        resource_id_str = str(patient_id) if patient_id is not None else None

        with raf_cursor() as cur:
            cur.execute(
                "INSERT INTO audit_log"
                " (user_id, action, resource_type, resource_id, patient_id, details, created_at)"
                " VALUES (%s, %s, %s, %s, %s, %s, NOW())",
                (
                    db_user_id,
                    f"phi_{action}",
                    resource,
                    resource_id_str,
                    patient_id,
                    json.dumps(
                        {
                            "details": details,
                            "encounter_id": encounter_id,
                            "tenant_id": tid,
                        }
                    ),
                ),
            )
    except Exception:
        _app_logger.error("Failed to persist PHI access log to database", exc_info=True)
