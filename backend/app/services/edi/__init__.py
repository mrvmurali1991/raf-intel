"""
EDI generation package — ASC X12 5010 outbound transactions.

Modules:
    x12_837 — Health Care Claim/Encounter (837 5010 — Institutional/Professional)
    x12_834 — Benefit Enrollment and Maintenance (834 5010)
    common  — shared segment builders, control numbers, validation primitives

These modules emit *syntactically valid* 5010 X12 text. Production use still
requires trading-partner agreements, clearinghouse routing, MAO-001
acknowledgement parsing, and 999/277CA ack handling — see TODO list in
README.
"""

from app.services.edi.x12_837 import generate_837_encounter, generate_837_batch
from app.services.edi.x12_834 import generate_834_enrollment

__all__ = [
    "generate_837_encounter",
    "generate_837_batch",
    "generate_834_enrollment",
]
