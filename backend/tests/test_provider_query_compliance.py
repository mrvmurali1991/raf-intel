"""Tests for the AHIMA/ACDIS provider-query compliance linter and drafter.

The linter MUST reject leading-language drafts. False negatives here mean
non-compliant queries could reach providers — treat failures as blocking.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.ai_pipeline.provider_query import (
    ProviderQuery,
    SupportingCitation,
    generate_query,
    lint,
)


def _q(subject: str, body: str, citations=None) -> ProviderQuery:
    if citations is None:
        citations = [
            SupportingCitation(
                document_id="doc-1",
                span_start=0,
                span_end=20,
                quote="A1c 8.2 on 2026-03-01",
            )
        ]
    return ProviderQuery(
        to_provider_id="prov-1",
        patient_id="pat-1",
        subject=subject,
        body=body,
        supporting_citations=citations,
    )


# ---------------------------------------------------------------------------
# Leading-language rejection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "body,expected_flag",
    [
        (
            "Please confirm patient has diabetes.",
            "LEADING_CONFIRM",
        ),
        (
            "Can you confirm the diagnosis of CHF?",
            "LEADING_CONFIRM",
        ),
        (
            "This should be coded as E11.9.",
            "LEADING_SHOULD_BE_CODED",
        ),
        (
            "Please code this as CHF exacerbation.",
            "LEADING_SHOULD_BE_CODED",
        ),
        (
            "Please indicate diabetes if applicable.",
            "LEADING_INDICATE_DX",
        ),
        (
            "Is this CHF?",
            "LEADING_INDICATE_DX",
        ),
        (
            "Clarifying this diagnosis will improve our RAF score.",
            "FINANCIAL_IMPACT",
        ),
    ],
)
def test_leading_language_is_flagged(body: str, expected_flag: str) -> None:
    flags = lint(_q("Clarification requested", body))
    assert expected_flag in flags, f"Expected {expected_flag} in {flags} for body: {body!r}"


def test_compliant_draft_passes() -> None:
    body = (
        "Dear Dr. Smith,\n\n"
        "During chart review, the following was noted:\n"
        "- A1c 8.2 on 2026-03-01\n"
        "- metformin 1000mg BID\n\n"
        "Could you clarify the clinical significance? Options include:\n"
        "  a) Type 2 diabetes mellitus, currently managed\n"
        "  b) Pre-diabetes / impaired glucose tolerance\n"
        "  c) Clinically undetermined\n\n"
        "Thank you."
    )
    flags = lint(_q("Clarification requested: glycemic findings", body))
    assert flags == [], f"Compliant draft was flagged: {flags}"


def test_missing_citations_flagged() -> None:
    q = _q("s", "body", citations=[])
    assert "NO_EVIDENCE" in lint(q)


def test_single_option_question_flagged() -> None:
    body = "Could you confirm the finding? a) yes"
    assert "SINGLE_OPTION" in lint(_q("s", body))


def test_uncited_numeric_claim_flagged() -> None:
    body = (
        "Labs show A1c 9.9. Options:\n"
        "  a) DM type 2\n  b) Pre-diabetes\n  c) Undetermined\n"
        "Could you clarify?"
    )
    citations = [SupportingCitation(document_id="d", quote="metformin prescription")]
    assert "UNCITED_CLAIM" in lint(_q("s", body, citations=citations))


# ---------------------------------------------------------------------------
# End-to-end drafter (LLM mocked)
# ---------------------------------------------------------------------------


def test_generate_query_flags_leading_llm_output() -> None:
    candidate = SimpleNamespace(
        patient_id="pat-1",
        attending_provider_id="prov-1",
        hcc="HCC18",
        icd10_guess="E11.9",
        meat_gaps=["assessment"],
    )
    bundle = SimpleNamespace(patient_id="pat-1", primary_provider_id="prov-1")

    def fake_llm(_prompt: str) -> dict:
        return {
            "subject": "Confirm diabetes",
            "body": "Please confirm patient has diabetes.",
            "supporting_citations": [
                {"document_id": "d1", "span_start": 0, "span_end": 10, "quote": "A1c 8.2"}
            ],
        }

    q = generate_query(candidate, bundle, llm_fn=fake_llm)
    assert q.requires_human_review
    assert "LEADING_CONFIRM" in q.compliance_flags


def test_generate_query_clean_draft_has_no_flags() -> None:
    candidate = SimpleNamespace(
        patient_id="pat-1",
        attending_provider_id="prov-1",
        meat_gaps=["assessment"],
    )
    bundle = SimpleNamespace(patient_id="pat-1")

    def fake_llm(_prompt: str) -> dict:
        return {
            "subject": "Clarification requested: glycemic findings",
            "body": (
                "Dear Dr. Smith,\n\n"
                "Chart review noted:\n- A1c 8.2 on 2026-03-01\n- metformin 1000mg BID\n\n"
                "Could you clarify? Options:\n"
                "  a) Type 2 DM, currently managed\n"
                "  b) Pre-diabetes\n"
                "  c) Clinically undetermined\n"
            ),
            "supporting_citations": [
                {
                    "document_id": "d1",
                    "span_start": 0,
                    "span_end": 30,
                    "quote": "A1c 8.2 on 2026-03-01",
                }
            ],
        }

    q = generate_query(candidate, bundle, llm_fn=fake_llm)
    assert q.compliance_flags == []
    assert not q.requires_human_review
    assert q.patient_id == "pat-1"
    assert q.to_provider_id == "prov-1"
