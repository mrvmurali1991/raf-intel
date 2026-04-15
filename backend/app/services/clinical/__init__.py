"""
Clinical domain package.

Re-exports from the flat services layer so that new code can import from
``app.services.clinical`` while existing imports continue to work.

Domain responsibilities:
- Patient demographics and data retrieval
- Encounter normalization and sync
- Diagnosis management
- MEAT evidence assessment
- Suspect condition engine
"""
from app.services.encounter_normalization_service import (  # noqa: F401
    sync_encounters,
    sync_diagnoses,
)
from app.services.meat_validator import validate_meat  # noqa: F401

__all__ = [
    "sync_encounters",
    "sync_diagnoses",
    "validate_meat",
]
