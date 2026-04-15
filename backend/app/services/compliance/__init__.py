"""
Compliance domain package.

Re-exports from the flat services layer so that new code can import from
``app.services.compliance`` while existing imports continue to work.

Domain responsibilities:
- HIPAA audit logging (PHI access events)
- Data retention policy enforcement
- PHI detection and de-identification
- Encryption services
"""
from app.services.audit_logger import log_phi_access  # noqa: F401
from app.services.data_retention import run_retention_sweep, RetentionPolicy  # noqa: F401
from app.services.phi_detector import detect_phi_in_dict, get_phi_field_names  # noqa: F401
from app.services.phi_deidentifier import deidentify_patient, deidentify_dataset  # noqa: F401
from app.services.encryption_service import encrypt, decrypt  # noqa: F401

__all__ = [
    "log_phi_access",
    "run_retention_sweep",
    "RetentionPolicy",
    "detect_phi_in_dict",
    "get_phi_field_names",
    "deidentify_patient",
    "deidentify_dataset",
    "encrypt",
    "decrypt",
]
