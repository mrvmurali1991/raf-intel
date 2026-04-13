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
    *,
    tenant_id: int | str = "unknown",
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
        _app_logger.debug(
            "PHI access logged without user identity — caller should pass user_id"
        )
    tid = tenant_id
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

        # fetch context for audit logs
        from app.audit_middleware import request_context
        req_ctx = request_context.get()
        ip_address = req_ctx.get("ip_address") if req_ctx else None
        user_agent = req_ctx.get("user_agent") if req_ctx else None
        request_method = req_ctx.get("method") if req_ctx else None
        request_path = req_ctx.get("path") if req_ctx else None

        with raf_cursor() as cur:
            cur.execute(
                "INSERT INTO audit_log"
                " (user_id, action, resource_type, resource_id, patient_id, ip_address, user_agent, request_method, request_path, details, created_at)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())",
                (
                    db_user_id,
                    f"phi_{action}",
                    resource,
                    resource_id_str,
                    patient_id,
                    ip_address,
                    user_agent,
                    request_method,
                    request_path,
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
