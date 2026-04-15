"""
EMR (Electronic Medical Record) domain package.

Re-exports from the flat services layer so that new code can import from
``app.services.emr`` while existing imports continue to work.

Domain responsibilities:
- EMR connection management (create, list, activate, delete)
- Vendor adapter dispatch (OpenEMR, Athena, Allscripts, etc.)
- Active patient subquery helpers
- EMR sync orchestration
"""
from app.services.emr_manager import (  # noqa: F401
    list_connections,
    get_connection,
    get_connection_with_credentials,
    get_active_direct_db_credentials,
    create_connection,
    update_connection,
    active_patients_subquery,
)
from app.services import vendor_adapters  # noqa: F401

__all__ = [
    "list_connections",
    "get_connection",
    "get_connection_with_credentials",
    "get_active_direct_db_credentials",
    "create_connection",
    "update_connection",
    "active_patients_subquery",
    "vendor_adapters",
]
