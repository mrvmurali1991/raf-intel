"""RADV audit packet export package.

Assembles the per-patient, per-payment-year CMS Risk Adjustment Data
Validation (RADV) packet — the bundle of evidence a health plan would
submit in response to a CMS RADV audit request.

Public API
----------
build_packet(patient_id, payment_year, db, tenant_id) -> bytes
    Return the rendered PDF as raw bytes. Includes every HCC billed for
    the patient/year, with ICD-10 chain, DOS, rendering provider, MEAT
    letter evidence, LLM quote + char-offset provenance, and
    suspect -> accept audit trail (who accepted, when).
"""

from app.services.radv.packet_builder import build_packet  # noqa: F401

__all__ = ["build_packet"]
