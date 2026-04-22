"""
Unit tests for the Chapman-style clinical context detector and its
integration with the suspect engine.

These tests do NOT require a live backend server.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from app.services.nlp.context_detector import detect_context


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _ctx(text: str, concept: str) -> dict[str, Any]:
    """Locate *concept* in *text* and run detect_context on its span."""
    pos = text.lower().find(concept.lower())
    assert pos >= 0, f"concept {concept!r} not in text {text!r}"
    return dict(detect_context(text, pos, pos + len(concept)))


# ---------------------------------------------------------------------------
# Negation
# ---------------------------------------------------------------------------

class TestNegation:

    def test_denies_chest_pain(self) -> None:
        ctx = _ctx("Patient denies chest pain today.", "chest pain")
        assert ctx["negated"] is True
        assert ctx["experiencer"] == "patient"

    def test_no_evidence_of_chf(self) -> None:
        ctx = _ctx("Echo shows no evidence of CHF at this visit.", "CHF")
        assert ctx["negated"] is True

    def test_ruled_out_mi(self) -> None:
        ctx = _ctx("Troponins negative, MI was ruled out overnight.", "MI")
        # Forward-looking "was ruled out" AFTER the span
        assert ctx["negated"] is True

    def test_ruled_out_pre(self) -> None:
        ctx = _ctx("We ruled out pulmonary embolism with CTPA.", "pulmonary embolism")
        assert ctx["negated"] is True

    def test_plain_positive_mention_not_negated(self) -> None:
        ctx = _ctx("Patient reports chest pain radiating to jaw.", "chest pain")
        assert ctx["negated"] is False
        assert ctx["experiencer"] == "patient"

    def test_pseudo_negation_not_fired(self) -> None:
        # "no change in CHF" must not trigger negated.
        ctx = _ctx("No change in CHF status since last visit.", "CHF")
        assert ctx["negated"] is False

    def test_termination_word_cancels_negation(self) -> None:
        # Termination term ("but") between "denies" and the target cancels it.
        ctx = _ctx(
            "Patient denies fever but reports chest pain today.", "chest pain",
        )
        assert ctx["negated"] is False


# ---------------------------------------------------------------------------
# Uncertainty
# ---------------------------------------------------------------------------

class TestUncertainty:

    def test_possible_sepsis(self) -> None:
        ctx = _ctx("Labs suggest possible sepsis; starting broad abx.", "sepsis")
        assert ctx["uncertain"] is True
        # not negated
        assert ctx["negated"] is False

    def test_rule_out_pneumonia(self) -> None:
        # r/o is both uncertain (workup) and hypothetical (contingent)
        ctx = _ctx("CXR ordered to r/o pneumonia.", "pneumonia")
        assert ctx["uncertain"] is True

    def test_suspected_ckd(self) -> None:
        ctx = _ctx("Elevated creatinine, suspected CKD.", "CKD")
        assert ctx["uncertain"] is True


# ---------------------------------------------------------------------------
# Family history
# ---------------------------------------------------------------------------

class TestFamily:

    def test_family_history_of_cad(self) -> None:
        ctx = _ctx("Family history of CAD in father.", "CAD")
        assert ctx["family"] is True
        assert ctx["experiencer"] == "family"
        # Not negated — it just belongs to someone else.
        assert ctx["negated"] is False

    def test_family_history_of_dm(self) -> None:
        ctx = _ctx("FH of DM on maternal side.", "DM")
        assert ctx["family"] is True
        assert ctx["experiencer"] == "family"

    def test_mother_with_breast_cancer(self) -> None:
        ctx = _ctx("Mother with breast cancer diagnosed at 52.", "breast cancer")
        assert ctx["family"] is True

    def test_patient_history_not_family(self) -> None:
        ctx = _ctx("Patient has a history of DM on metformin.", "DM")
        assert ctx["family"] is False
        assert ctx["experiencer"] == "patient"


# ---------------------------------------------------------------------------
# Historical
# ---------------------------------------------------------------------------

class TestHistorical:

    def test_history_of_pe_2018(self) -> None:
        ctx = _ctx("History of PE 2018, on lifelong anticoagulation.", "PE")
        assert ctx["historical"] is True
        assert ctx["negated"] is False
        assert ctx["family"] is False

    def test_h_o_mi(self) -> None:
        ctx = _ctx("PMH: h/o MI 2015.", "MI")
        assert ctx["historical"] is True

    def test_status_post(self) -> None:
        ctx = _ctx("S/p CABG x3 in 2010.", "CABG")
        assert ctx["historical"] is True

    def test_no_historical_for_fresh_dx(self) -> None:
        ctx = _ctx("Admitted with new-onset atrial fibrillation.",
                   "atrial fibrillation")
        assert ctx["historical"] is False


# ---------------------------------------------------------------------------
# Hypothetical
# ---------------------------------------------------------------------------

class TestHypothetical:

    def test_if_worsens(self) -> None:
        ctx = _ctx("Return if pneumonia symptoms worsen.", "pneumonia")
        assert ctx["hypothetical"] is True

    def test_consider(self) -> None:
        ctx = _ctx("Consider dialysis if creatinine trends upward.", "dialysis")
        assert ctx["hypothetical"] is True


# ---------------------------------------------------------------------------
# Empty / edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:

    def test_empty_text(self) -> None:
        ctx = detect_context("", 0, 0)
        assert ctx == {
            "negated": False, "uncertain": False, "historical": False,
            "hypothetical": False, "family": False, "experiencer": "patient",
        }

    def test_invalid_span(self) -> None:
        ctx = detect_context("abc", 5, 10)
        assert ctx["negated"] is False

    def test_sentence_boundary_isolation(self) -> None:
        # Negation in a previous sentence must NOT leak to a later mention.
        text = "Patient denies chest pain. CHF confirmed on echo."
        pos = text.find("CHF")
        ctx = dict(detect_context(text, pos, pos + 3))
        assert ctx["negated"] is False


# ---------------------------------------------------------------------------
# Integration with suspect_engine._apply_context_filter
# ---------------------------------------------------------------------------

class TestSuspectEngineIntegration:
    """Prove the engine rejects negated hits it would previously have accepted."""

    def test_negated_nlp_suspect_is_dropped(self) -> None:
        from app.services import suspect_engine as se

        accept, conf, ctx = se._apply_context_filter(
            snippet="Workup shows no evidence of CHF on today's visit.",
            target_text="CHF",
            base_confidence=0.9,
        )
        assert accept is False
        assert conf == 0.0
        assert ctx["negated"] is True

    def test_family_history_suspect_is_dropped(self) -> None:
        from app.services import suspect_engine as se

        accept, conf, ctx = se._apply_context_filter(
            snippet="Family history of CAD in father diagnosed at 55.",
            target_text="CAD",
            base_confidence=0.8,
        )
        assert accept is False
        assert ctx["family"] is True
        assert ctx["experiencer"] == "family"

    def test_hypothetical_suspect_is_dropped(self) -> None:
        from app.services import suspect_engine as se

        accept, _conf, ctx = se._apply_context_filter(
            snippet="Return to ED if pneumonia symptoms develop overnight.",
            target_text="pneumonia",
            base_confidence=0.7,
        )
        assert accept is False
        assert ctx["hypothetical"] is True

    def test_historical_suspect_admitted_but_dampened(self) -> None:
        from app.services import suspect_engine as se

        accept, conf, ctx = se._apply_context_filter(
            snippet="History of PE 2018, still on apixaban.",
            target_text="PE",
            base_confidence=1.0,
        )
        # Historical mentions ARE accepted — they drive recapture — but
        # with reduced confidence so they don't outrank fresh findings.
        assert accept is True
        assert ctx["historical"] is True
        assert conf < 1.0

    def test_plain_positive_mention_accepted_untouched(self) -> None:
        from app.services import suspect_engine as se

        accept, conf, _ctx = se._apply_context_filter(
            snippet="Started patient on Ozempic for uncontrolled DM today.",
            target_text="DM",
            base_confidence=0.9,
        )
        assert accept is True
        assert conf == 0.9

    def test_scan_note_vs_billing_rejects_negated_hit(self) -> None:
        """
        End-to-end: build a fake raf_nlp_jobs row whose note_snippet negates
        the candidate ICD.  Before the context filter the engine would have
        emitted a suspect; after the filter it must emit zero.
        """
        from app.services import suspect_engine as se

        fake_job: dict[str, Any] = {
            "id": 42,
            "encounter_id": 7,
            "result_json": (
                '{"identified_diagnoses": [{'
                '"icd_code": "I50.9", "hcc_code": "HCC226", '
                '"description": "CHF", "confidence": 0.9, '
                '"note_snippet": "Echo shows no evidence of CHF."'
                "}]}"
            ),
            "created_at": None,
        }

        class _Cur:
            def __init__(self) -> None:
                self._rows: list[dict[str, Any]] = [fake_job]

            def execute(self, *_a: Any, **_kw: Any) -> None:
                return None

            def fetchall(self) -> list[dict[str, Any]]:
                return self._rows

        class _CM:
            def __enter__(self) -> _Cur:
                return _Cur()

            def __exit__(self, *_a: Any) -> None:
                return None

        with (
            patch.object(se, "raf_cursor", lambda: _CM()),
            patch.object(se, "_coded_icd_set", lambda _pid, **_kw: set()),
            patch.object(se, "_coded_hcc_set", lambda _pid, **_kw: set()),
        ):
            suspects = se.scan_note_vs_billing(patient_id=111)

        assert suspects == [], (
            "Negated CHF mention must not produce a suspect — got "
            f"{suspects!r}"
        )


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
