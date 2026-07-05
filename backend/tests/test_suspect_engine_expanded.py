"""
Suspect Condition Detection Engine — expanded test suite.

Covers: fingerprint determinism, context filter behavior, signal cache TTL,
evidence type mapping, module documentation, and source inspection.

No database or network required.
"""
from __future__ import annotations

import inspect

import pytest


# ---------------------------------------------------------------------------
# 1. Suspect fingerprint determinism
# ---------------------------------------------------------------------------

class TestSuspectFingerprint:
    """_suspect_fingerprint must produce stable, unique SHA-256 keys."""

    def test_deterministic_same_inputs(self):
        from app.services.suspect_engine import _suspect_fingerprint
        fp1 = _suspect_fingerprint(1, "medication", "E119")
        fp2 = _suspect_fingerprint(1, "medication", "E119")
        assert fp1 == fp2

    def test_unique_per_source(self):
        from app.services.suspect_engine import _suspect_fingerprint
        fp1 = _suspect_fingerprint(1, "medication", "E119")
        fp2 = _suspect_fingerprint(1, "lab", "E119")
        assert fp1 != fp2

    def test_unique_per_patient(self):
        from app.services.suspect_engine import _suspect_fingerprint
        fp1 = _suspect_fingerprint(1, "medication", "E119")
        fp2 = _suspect_fingerprint(2, "medication", "E119")
        assert fp1 != fp2

    def test_unique_per_code(self):
        from app.services.suspect_engine import _suspect_fingerprint
        fp1 = _suspect_fingerprint(1, "medication", "E119")
        fp2 = _suspect_fingerprint(1, "medication", "I509")
        assert fp1 != fp2

    def test_fingerprint_is_hex_string(self):
        from app.services.suspect_engine import _suspect_fingerprint
        fp = _suspect_fingerprint(1, "medication", "E119")
        assert isinstance(fp, str)
        # SHA-256 truncated to 32 hex chars
        assert len(fp) == 32
        assert all(c in "0123456789abcdef" for c in fp)

    def test_case_insensitive(self):
        from app.services.suspect_engine import _suspect_fingerprint
        fp1 = _suspect_fingerprint(1, "Medication", "E119")
        fp2 = _suspect_fingerprint(1, "medication", "e119")
        assert fp1 == fp2


# ---------------------------------------------------------------------------
# 2. Context filter behavior
# ---------------------------------------------------------------------------

class TestContextFilter:
    """_apply_context_filter accepts or rejects based on NLP context."""

    def test_accepts_positive_context(self):
        from app.services.suspect_engine import _apply_context_filter
        accept, conf, meta = _apply_context_filter(
            "Patient has active diabetes requiring insulin management",
            "diabetes",
            0.8,
        )
        assert accept is True

    def test_empty_snippet_accepts(self):
        from app.services.suspect_engine import _apply_context_filter
        accept, conf, meta = _apply_context_filter("", "diabetes", 0.8)
        assert accept is True

    def test_empty_target_accepts(self):
        from app.services.suspect_engine import _apply_context_filter
        accept, conf, meta = _apply_context_filter(
            "Some clinical text here", "", 0.8
        )
        assert accept is True

    def test_returns_tuple_of_three(self):
        from app.services.suspect_engine import _apply_context_filter
        result = _apply_context_filter(
            "Patient has diabetes", "diabetes", 0.75
        )
        assert isinstance(result, tuple)
        assert len(result) == 3

    def test_confidence_is_float(self):
        from app.services.suspect_engine import _apply_context_filter
        _, conf, _ = _apply_context_filter(
            "Patient has diabetes", "diabetes", 0.75
        )
        assert isinstance(conf, float)


# ---------------------------------------------------------------------------
# 3. Signal cache TTL
# ---------------------------------------------------------------------------

class TestSignalCacheTtl:
    """Cache TTL must be 300 seconds (5 minutes)."""

    def test_ttl_is_300_seconds(self):
        from app.services.suspect_engine import _SIGNAL_CACHE_TTL
        assert _SIGNAL_CACHE_TTL == 300

    def test_ttl_is_positive(self):
        from app.services.suspect_engine import _SIGNAL_CACHE_TTL
        assert _SIGNAL_CACHE_TTL > 0


# ---------------------------------------------------------------------------
# 4. Evidence type mapping
# ---------------------------------------------------------------------------

class TestEvidenceTypeMap:
    """_EVIDENCE_TYPE_MAP must cover all expected source types."""

    def test_medication_source_mapped(self):
        from app.services.suspect_engine import _EVIDENCE_TYPE_MAP
        assert "medication" in _EVIDENCE_TYPE_MAP

    def test_lab_source_mapped(self):
        from app.services.suspect_engine import _EVIDENCE_TYPE_MAP
        assert "lab" in _EVIDENCE_TYPE_MAP

    def test_historical_source_mapped(self):
        from app.services.suspect_engine import _EVIDENCE_TYPE_MAP
        assert "historical" in _EVIDENCE_TYPE_MAP

    def test_nlp_source_mapped(self):
        from app.services.suspect_engine import _EVIDENCE_TYPE_MAP
        assert "nlp" in _EVIDENCE_TYPE_MAP

    def test_comorbidity_source_mapped(self):
        from app.services.suspect_engine import _EVIDENCE_TYPE_MAP
        assert "comorbidity" in _EVIDENCE_TYPE_MAP

    def test_specificity_upgrade_mapped(self):
        from app.services.suspect_engine import _EVIDENCE_TYPE_MAP
        assert "specificity_upgrade" in _EVIDENCE_TYPE_MAP

    def test_imaging_source_mapped(self):
        from app.services.suspect_engine import _EVIDENCE_TYPE_MAP
        assert "imaging" in _EVIDENCE_TYPE_MAP

    def test_all_values_are_valid_enum_values(self):
        from app.services.suspect_engine import _EVIDENCE_TYPE_MAP
        valid_enums = {"medication", "lab", "imaging", "referral", "historical"}
        for source, mapped_type in _EVIDENCE_TYPE_MAP.items():
            assert mapped_type in valid_enums, (
                f"Source '{source}' maps to invalid enum value '{mapped_type}'"
            )


# ---------------------------------------------------------------------------
# 5. Module documentation (7 strategies)
# ---------------------------------------------------------------------------

class TestModuleDocumentation:
    """Module docstring documents 7 scanning strategies."""

    def test_module_has_docstring(self):
        import app.services.suspect_engine as se
        assert se.__doc__ is not None
        assert len(se.__doc__) > 100

    def test_mentions_medication_strategy(self):
        import app.services.suspect_engine as se
        assert "medication" in se.__doc__.lower() or "Medication" in se.__doc__

    def test_mentions_lab_strategy(self):
        import app.services.suspect_engine as se
        assert "lab" in se.__doc__.lower() or "Lab" in se.__doc__

    def test_mentions_historical_strategy(self):
        import app.services.suspect_engine as se
        assert "historical" in se.__doc__.lower() or "Historical" in se.__doc__

    def test_mentions_nlp_strategy(self):
        import app.services.suspect_engine as se
        doc = se.__doc__
        assert "nlp" in doc.lower() or "NLP" in doc

    def test_mentions_comorbidity_strategy(self):
        import app.services.suspect_engine as se
        doc = se.__doc__
        assert "comorbidity" in doc.lower() or "Comorbidity" in doc

    def test_mentions_specificity_strategy(self):
        import app.services.suspect_engine as se
        doc = se.__doc__
        assert "specificity" in doc.lower() or "Specificity" in doc

    def test_mentions_seven_strategies(self):
        import app.services.suspect_engine as se
        doc = se.__doc__
        assert "seven" in doc.lower() or "7" in doc


# ---------------------------------------------------------------------------
# 6. _map_evidence_type function
# ---------------------------------------------------------------------------

class TestMapEvidenceType:
    """_map_evidence_type returns correct enum values."""

    def test_medication_maps_to_medication(self):
        from app.services.suspect_engine import _map_evidence_type
        assert _map_evidence_type("medication") == "medication"

    def test_lab_maps_to_lab(self):
        from app.services.suspect_engine import _map_evidence_type
        assert _map_evidence_type("lab") == "lab"

    def test_unknown_source_defaults_to_medication(self):
        from app.services.suspect_engine import _map_evidence_type
        assert _map_evidence_type("unknown_source_xyz") == "medication"

    def test_note_nlp_maps_to_referral(self):
        from app.services.suspect_engine import _map_evidence_type
        assert _map_evidence_type("note_nlp") == "referral"
