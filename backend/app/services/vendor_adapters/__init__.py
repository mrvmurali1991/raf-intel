"""
Vendor adapters package for REST API EMR integrations.

Each adapter normalises a specific EMR vendor's REST API into a common
interface defined by ``BaseVendorAdapter``.  Use ``get_adapter(connection)``
to obtain the correct adapter for a given ``emr_connections`` row.

Supported vendors
-----------------
* ``athenahealth`` – athenahealth platform API (OAuth2, paginated)
* ``drchrono``     – DrChrono REST API (OAuth2, cursor pagination)
* ``allscripts``   – Allscripts / Veradigm Unity API (OAuth2 or Unity auth)
* ``greenway``     – Greenway Health REST API (API key or OAuth2)
"""
from .allscripts import AllscriptsAdapter
from .athenahealth import AthenahealthAdapter
from .base import BaseVendorAdapter
from .drchrono import DrChronoAdapter
from .greenway import GreenwayAdapter
from .registry import get_adapter, list_supported_vendors

__all__ = [
    "BaseVendorAdapter",
    "AthenahealthAdapter",
    "DrChronoAdapter",
    "AllscriptsAdapter",
    "GreenwayAdapter",
    "get_adapter",
    "list_supported_vendors",
]
