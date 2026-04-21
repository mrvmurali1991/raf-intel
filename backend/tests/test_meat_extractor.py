"""Tests for ai_pipeline.meat_extractor."""
from __future__ import annotations

import json
from dataclasses import dataclass

import pytest
from app.services.ai_pipeline.meat_extractor import (
    MEATEvidence,
    extract_meat_evidence,
    is_face_to_face_encounter,
    validate_quote_in_source,
)


@dataclass
class _Candidate:
    icd10: str
    description: str
    hcc: str


SAMPLE_NOTE = (
    "Office Visit 2026-03-14\n"
    "CC: Diabetes follow-up.\n"
    "HPI: 62 yo M with DM2, home BG log shows fasting 150-180.\n"
    "Labs: HbA1c 8.3 (up from 7.1 in Dec).\n"
    "Assessment: DM2 uncontrolled.\n"
    "Plan: Continue metformin 1000 mg BID. Add empagliflozin 10 mg daily. "
    "Refer to RD for MNT. Return in 3 months."
)


# --------------------------------------------------------------------------- #
# validate_quote_in_source
# --------------------------------------------------------------------------- #


def test_validate_quote_exact_substring():
    assert validate_quote_in_source("HbA1c 8.3", SAMPLE_NOTE)


def test_validate_quote_whitespace_normalised():
    assert validate_quote_in_source(
        "Continue metformin 1000 mg BID.", SAMPLE_NOTE
    )
    # Collapsed newlines still match.
    assert validate_quote_in_source(
        "metformin 1000 mg BID. Add empagliflozin 10 mg daily.", SAMPLE_NOTE
    )


def test_validate_quote_rejects_paraphrase():
    assert not validate_quote_in_source("patient has diabetes", SAMPLE_NOTE)
    assert not validate_quote_in_source("HbA1c was 8.4", SAMPLE_NOTE)


def test_validate_quote_rejects_empty():
    assert not validate_quote_in_source("", SAMPLE_NOTE)
    assert not validate_quote_in_source(None, SAMPLE_NOTE)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# is_face_to_face_encounter
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "enc,expected",
    [
        ("Office Visit", True),
        ("Outpatient", True),
        ("Annual Wellness Visit", True),
        ("Telehealth Video", True),
        ("Telephone encounter", False),
        ("Phone call", False),
        ("Lab only", False),
        ("Administrative", False),
        ("Portal message", False),
        ("", False),
        (None, False),
        ("Something weird", False),
    ],
)
def test_face_to_face_gate(enc, expected):
    assert is_face_to_face_encounter(enc) is expected


# --------------------------------------------------------------------------- #
# extract_meat_evidence — with mocked LLM
# --------------------------------------------------------------------------- #


def _fake_llm(response: str):
    def _inner(prompt: str, model: str = "", temperature: float = 0.0, **_):
        return response
    return _inner


def test_extract_meat_all_four_verbatim():
    cand = _Candidate("E11.65", "Type 2 DM with hyperglycemia", "HCC37")
    llm_resp = json.dumps({
        "m_quote": "home BG log shows fasting 150-180",
        "e_quote": "HbA1c 8.3 (up from 7.1 in Dec)",
        "a_quote": "DM2 uncontrolled",
        "t_quote": "Continue metformin 1000 mg BID.",
        "encounter_date": "2026-03-14",
        "is_face_to_face": True,
        "overall_valid": True,
        "reason_if_invalid": None,
    })
    out = extract_meat_evidence(
        cand,
        SAMPLE_NOTE,
        context={"encounter_type": "Office Visit", "encounter_date": "2026-03-14"},
        llm=_fake_llm(llm_resp),
    )
    assert isinstance(out, MEATEvidence)
    assert out.is_face_to_face is True
    assert out.overall_valid is True
    assert out.m_quote == "home BG log shows fasting 150-180"
    assert out.e_quote.startswith("HbA1c 8.3")
    assert out.a_quote == "DM2 uncontrolled"
    assert out.t_quote.startswith("Continue metformin")
    assert out.dropped_quotes == []


def test_extract_meat_drops_hallucinated_quote():
    cand = _Candidate("E11.65", "Type 2 DM", "HCC37")
    llm_resp = json.dumps({
        "m_quote": "patient reports good adherence",  # NOT in note
        "e_quote": "HbA1c 8.3",                         # verbatim
        "a_quote": "DM2 uncontrolled",                  # verbatim
        "t_quote": "start insulin glargine 10u",        # NOT in note
        "encounter_date": "2026-03-14",
        "is_face_to_face": True,
        "overall_valid": True,
        "reason_if_invalid": None,
    })
    out = extract_meat_evidence(
        cand,
        SAMPLE_NOTE,
        context={"encounter_type": "Office Visit"},
        llm=_fake_llm(llm_resp),
    )
    assert out.m_quote is None
    assert out.e_quote == "HbA1c 8.3"
    assert out.a_quote == "DM2 uncontrolled"
    assert out.t_quote is None
    assert any("m_quote" in d for d in out.dropped_quotes)
    assert any("t_quote" in d for d in out.dropped_quotes)
    assert out.overall_valid is True  # at least one MEAT + F2F


def test_extract_meat_rejects_non_f2f_without_llm_call():
    cand = _Candidate("E11.65", "DM2", "HCC37")
    called = {"n": 0}

    def _boom(*_a, **_kw):
        called["n"] += 1
        raise AssertionError("LLM should not be called for non-F2F encounter")

    out = extract_meat_evidence(
        cand,
        SAMPLE_NOTE,
        context={"encounter_type": "Telephone"},
        llm=_boom,
    )
    assert called["n"] == 0
    assert out.is_face_to_face is False
    assert out.overall_valid is False
    assert "not face-to-face" in (out.reason_if_invalid or "")


def test_extract_meat_empty_note():
    cand = _Candidate("E11.65", "DM2", "HCC37")
    out = extract_meat_evidence(cand, "", context={"encounter_type": "Office"})
    assert out.overall_valid is False
    assert out.reason_if_invalid == "empty note"


def test_extract_meat_all_quotes_dropped_marks_invalid():
    cand = _Candidate("E11.65", "DM2", "HCC37")
    bad = json.dumps({
        "m_quote": "fake m",
        "e_quote": "fake e",
        "a_quote": "fake a",
        "t_quote": "fake t",
        "encounter_date": "2026-03-14",
        "is_face_to_face": True,
        "overall_valid": True,
        "reason_if_invalid": None,
    })
    # Both initial and retry return the same hallucinated payload.
    out = extract_meat_evidence(
        cand,
        SAMPLE_NOTE,
        context={"encounter_type": "Office Visit"},
        llm=_fake_llm(bad),
    )
    assert out.m_quote is None and out.t_quote is None
    assert out.overall_valid is False
    assert "verbatim" in (out.reason_if_invalid or "").lower() or \
           "no verbatim" in (out.reason_if_invalid or "").lower()
