"""Health Information Exchange (HIE) adapter package.

Provides a common FHIR R4 interface to CommonWell and Carequality networks,
both TEFCA-designated QHINs.  Legacy XCA/XDS.b transport is intentionally
omitted — all exchanges use the FHIR R4 dialect as directed by ONC guidance.

Public surface:
    HIEAdapter          — abstract base class
    CommonWellAdapter   — implementation against CommonWell /v1 FHIR API
    CarequalityAdapter  — implementation against QHIN FHIR R4 directory
    sync_patient_from_hie — orchestration entry point

Rate limit: 1 patient query per 2 seconds per network (CommonWell/Carequality
spec requirement), enforced via a per-network asyncio.Lock + timestamp gate.
"""
from .base import HIEAdapter, HIENetworkError, NetworkNotConfiguredError
from .commonwell import CommonWellAdapter
from .carequality import CarequalityAdapter

__all__ = [
    "HIEAdapter",
    "HIENetworkError",
    "NetworkNotConfiguredError",
    "CommonWellAdapter",
    "CarequalityAdapter",
]
