"""
Adapter registry.

Maps vendor slug strings (as stored in ``emr_connections.vendor``) to their
concrete ``BaseVendorAdapter`` subclass.  Call ``get_adapter(connection)``
to obtain an initialised adapter instance from a decrypted connection dict.

Usage::

    from app.services.vendor_adapters.registry import get_adapter

    adapter = get_adapter(connection)          # connection from get_connection_with_credentials()
    result  = adapter.test_connection()        # {success, message, latency_ms}
    summary = adapter.run_sync("incremental")  # {patients_synced, conditions_found, errors}
"""
from __future__ import annotations

from typing import Any

from .allscripts import AllscriptsAdapter
from .athenahealth import AthenahealthAdapter
from .base import BaseVendorAdapter
from .drchrono import DrChronoAdapter
from .greenway import GreenwayAdapter
from .openemr_fhir import OpenEMRFhirAdapter

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_ADAPTERS: dict[str, type[BaseVendorAdapter]] = {
    "athenahealth": AthenahealthAdapter,
    "drchrono": DrChronoAdapter,
    "allscripts": AllscriptsAdapter,
    "greenway": GreenwayAdapter,
}

# FHIR R4 adapters (separate from REST API adapters)
_FHIR_ADAPTERS: dict[str, type] = {
    "openemr": OpenEMRFhirAdapter,
}


def get_fhir_adapter(connection: dict[str, Any]) -> OpenEMRFhirAdapter | None:
    """Return a FHIR adapter for the connection's vendor, or None."""
    vendor = (connection.get("vendor") or "").lower().strip()
    cls = _FHIR_ADAPTERS.get(vendor)
    if cls is None:
        # Try generic FHIR adapter for any vendor with fhir_r4 connection type
        if connection.get("connection_type") == "fhir_r4":
            return OpenEMRFhirAdapter(connection)  # generic FHIR works for any R4 server
        return None
    return cls(connection)


def get_adapter(connection: dict[str, Any]) -> BaseVendorAdapter:
    """Return an initialised adapter for *connection*.

    Parameters
    ----------
    connection:
        Decrypted ``emr_connections`` row, as returned by
        ``get_connection_with_credentials()``.

    Raises
    ------
    ValueError
        If the ``vendor`` field is missing or no adapter is registered for it.
    """
    vendor: str = (connection.get("vendor") or "").lower().strip()
    if not vendor:
        raise ValueError(
            "connection is missing a 'vendor' field — cannot select an adapter"
        )

    cls = _ADAPTERS.get(vendor)
    if cls is None:
        supported = ", ".join(sorted(_ADAPTERS))
        raise ValueError(
            f"No REST API adapter for vendor '{vendor}'. "
            f"Supported vendors: {supported}"
        )

    return cls(connection)


def list_supported_vendors() -> list[str]:
    """Return the sorted list of vendor slugs that have registered adapters."""
    return sorted(_ADAPTERS)
