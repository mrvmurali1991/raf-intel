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

import logging
from datetime import datetime, timezone

# Dedicated logger — configure its handler in logging.ini / dictConfig
phi_logger = logging.getLogger("phi_audit")


def log_phi_access(
    action: str,
    resource: str,
    patient_id: int | None = None,
    encounter_id: int | None = None,
    user: str = "system",
    details: str = "",
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
    phi_logger.info(
        "PHI_ACCESS | action=%s | resource=%s | patient_id=%s | encounter_id=%s"
        " | user=%s | timestamp=%s | details=%s",
        action,
        resource,
        patient_id,
        encounter_id,
        user,
        datetime.now(tz=timezone.utc).isoformat(),
        details,
    )
