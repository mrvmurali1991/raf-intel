"""Tests for app.services.nlp_suspect_extractor.

Covers:
  1. Happy path — single COPD suspect extracted with correct offsets.
  2. existing_codes filter — already-coded ICD is dropped.
  3. V28 hierarchy — superordinate HCC trumps subordinate in the same chain.

All three test cases mock Gemini via monkeypatch so no real API calls happen.
"""

from __future__ import annotations

import json

import pytest

from app.services import nlp_suspect_extractor as nse


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _stub_llm(response_json: dict):
    """Return a callable usable as the `llm` injection hook."""
    payload = json.dumps(response_json)

    def _fn(prompt, *, model=None, system=None, temperature=None, **kwargs):
        return payload

    return _fn


# ---------------------------------------------------------------------------
# 1. Happy path
# ---------------------------------------------------------------------------


def test_extract_returns_copd_suspect_with_offsets() -> None:
    note = (
        "Visit 04/12: 65 yo M with hx COPD on tiotropium. "
        "Wheezing on exam, FEV1 47% predicted. Continues albuterol PRN."
    )
    evidence = "65 yo M with hx COPD on tiotropium."
    llm_stub = _stub_llm(
        {
            "suspects": [
                {
                    "hcc_code": "138",
                    "icd10": "J44.9",
                    "confidence": 0.92,
                    "evidence_sentence": evidence,
                }
            ]
        }
    )

    result = nse.extract_hcc_suspects_from_note(
        note_text=note,
        existing_codes=[],
        measurement_year=2026,
        llm=llm_stub,
    )

    assert len(result) == 1
    s = result[0]
    assert s.hcc_code == "138"
    assert s.icd10 == "J44.9"
    assert s.confidence == pytest.approx(0.92)
    assert s.evidence_sentence == evidence
    # Offsets must point at the exact substring location.
    assert note[s.evidence_start : s.evidence_end] == evidence
    assert s.model_version == nse.MODEL_VERSION


# ---------------------------------------------------------------------------
# 2. existing_codes filter
# ---------------------------------------------------------------------------


def test_extract_filters_out_already_coded_icd() -> None:
    """If the patient already has the ICD on the chart we must drop the
    LLM-emitted suspect, even when the LLM still returns it."""
    note = "Type 2 DM with hyperglycemia, A1c 9.4. Titrating insulin."
    llm_stub = _stub_llm(
        {
            "suspects": [
                {
                    "hcc_code": "19",
                    "icd10": "E11.65",
                    "confidence": 0.9,
                    "evidence_sentence": "Type 2 DM with hyperglycemia, A1c 9.4.",
                }
            ]
        }
    )

    # E11.65 already coded for this measurement year — must be filtered.
    result = nse.extract_hcc_suspects_from_note(
        note_text=note,
        existing_codes=["E11.65"],
        measurement_year=2026,
        llm=llm_stub,
    )

    assert result == []


# ---------------------------------------------------------------------------
# 3. V28 hierarchy trumping
# ---------------------------------------------------------------------------


def test_extract_applies_v28_hierarchy_trumping(monkeypatch) -> None:
    """When two HCCs from the same V28 chain come back, only the most-severe
    one should survive."""
    note = (
        "CKD stage 5 — eGFR 12. Discussed dialysis access. "
        "Has had prior CKD stage 3 documented."
    )
    sent_5 = "CKD stage 5 — eGFR 12."
    sent_3 = "Has had prior CKD stage 3 documented."

    # Confidence-sorted output — we want to assert the hierarchy filter
    # (not just confidence sort) is what eliminates the loser.
    llm_stub = _stub_llm(
        {
            "suspects": [
                {
                    "hcc_code": "326",
                    "icd10": "N18.5",
                    "confidence": 0.95,
                    "evidence_sentence": sent_5,
                },
                {
                    "hcc_code": "329",
                    "icd10": "N18.3",
                    "confidence": 0.80,
                    "evidence_sentence": sent_3,
                },
            ]
        }
    )

    # Force the V28 lookup so this test is deterministic regardless of which
    # hccinfhir version is installed. The renal chain is one of the fallback
    # chains so we monkeypatch the module-level lookup directly.
    monkeypatch.setattr(
        nse,
        "_V28_TRUMPED_BY",
        {329: [326, 327, 328], 328: [326, 327], 327: [326]},
    )

    result = nse.extract_hcc_suspects_from_note(
        note_text=note,
        existing_codes=[],
        measurement_year=2026,
        llm=llm_stub,
    )

    # Only HCC 326 should remain; HCC 329 must be trumped.
    assert len(result) == 1
    assert result[0].hcc_code == "326"
    assert result[0].icd10 == "N18.5"


# ---------------------------------------------------------------------------
# 4. Bonus — hallucinated evidence sentence is rejected
# ---------------------------------------------------------------------------


def test_extract_rejects_hallucinated_evidence() -> None:
    """If the LLM returns an evidence_sentence that is NOT verbatim in the
    note, the finding must be dropped (anti-hallucination guard)."""
    note = "Hemophilia A on prophylactic factor VIII every other day."
    llm_stub = _stub_llm(
        {
            "suspects": [
                {
                    "hcc_code": "111",
                    "icd10": "D66",
                    "confidence": 0.94,
                    # Plausible but NOT present in the note verbatim.
                    "evidence_sentence": "Patient has severe hemophilia A.",
                }
            ]
        }
    )

    result = nse.extract_hcc_suspects_from_note(
        note_text=note,
        existing_codes=[],
        measurement_year=2026,
        llm=llm_stub,
    )
    assert result == []
