"""
tests/test_meat_audit_service.py — Dual-coder MEAT audit workflow + PDF.

Covers:
  * record_primary_evidence: validation + state transition to primary_coded
  * submit_for_review: high-revenue and old-age triggers, missing-phrase guard
  * approve_review: state transition + same-coder rejection
  * reject_review: requires reason, transitions back to rejected
  * get_review_queue: status filter
  * compute_audit_readiness: percentage maths + missing_meat surfacing
  * recapture_audit_pdf.render_audit_html: smoke test (no WeasyPrint required)

All DB calls are mocked; no real database is required.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.services import meat_audit_service as svc
from app.services.meat_audit_service import (
    HIGH_REVENUE_THRESHOLD,
    OLD_GAP_DAYS,
    approve_review,
    compute_audit_readiness,
    get_review_queue,
    record_primary_evidence,
    reject_review,
    submit_for_review,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _scripted_cursor(*, fetchone_results=None, fetchall_results=None, rowcounts=None):
    """Return a raf_cursor context-manager mock whose responses are scripted.

    Each list is consumed in order across successive ``execute()`` calls — i.e.
    the i-th ``fetchone()`` returns ``fetchone_results[i]`` (or the last value
    if the script is shorter), same for ``fetchall()`` and ``rowcount``.
    """
    fetchone_results = list(fetchone_results or [])
    fetchall_results = list(fetchall_results or [])
    rowcounts = list(rowcounts or [])

    cur = MagicMock()
    state = {"calls": 0}

    def _execute(*args, **kwargs):
        state["calls"] += 1
        # Pop the next scripted value (or repeat the last)
        if fetchone_results:
            cur.fetchone.return_value = fetchone_results.pop(0)
        if fetchall_results:
            cur.fetchall.return_value = fetchall_results.pop(0)
        if rowcounts:
            cur.rowcount = rowcounts.pop(0)

    cur.execute.side_effect = _execute

    @contextmanager
    def _cm(*args, **kwargs):
        yield cur

    return _cm, cur


def _gap_row(**overrides: Any) -> dict[str, Any]:
    base = {
        "id": 1,
        "patient_id": "100",
        "tenant_id": "1",
        "hcc_code": "85",
        "icd10_code": "I50.9",
        "prior_year": 2025,
        "current_year": 2026,
        "status": "open",
        "last_encounter_date": None,
        "provider_npi": "1234567890",
        "revenue_impact": 3000.00,
        "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "evidence_phrase": None,
        "evidence_source_url": None,
        "meat_element": None,
        "primary_coder_id": None,
        "primary_coded_at": None,
        "secondary_coder_id": None,
        "secondary_approved_at": None,
        "audit_status": "draft",
        "audit_notes": None,
    }
    base.update(overrides)
    return base


# ===========================================================================
# 1. record_primary_evidence
# ===========================================================================


class TestRecordPrimaryEvidence:
    def test_happy_path_returns_updated_gap(self):
        # First execute = UPDATE (rowcount=1), second execute = SELECT
        updated = _gap_row(
            audit_status="primary_coded",
            evidence_phrase="CHF stable on lasix",
            meat_element="T",
            primary_coder_id=42,
            primary_coded_at=datetime(2026, 5, 5, tzinfo=timezone.utc),
        )
        cm, cur = _scripted_cursor(
            fetchone_results=[updated],
            rowcounts=[1, 1],
        )
        with patch("app.services.meat_audit_service.raf_cursor", cm):
            result = record_primary_evidence(
                gap_id=1,
                coder_id=42,
                phrase="CHF stable on lasix",
                meat_element="t",  # lowercase — must be normalised
                tenant_id="1",
            )
        assert result["audit_status"] == "primary_coded"
        assert result["meat_element"] == "T"
        assert result["primary_coder_id"] == 42

    def test_blank_phrase_rejected(self):
        with pytest.raises(ValueError, match="phrase"):
            record_primary_evidence(
                gap_id=1, coder_id=42, phrase="   ", meat_element="M",
            )

    def test_invalid_meat_element_rejected(self):
        with pytest.raises(ValueError, match="meat_element"):
            record_primary_evidence(
                gap_id=1, coder_id=42, phrase="ok", meat_element="Q",
            )

    def test_missing_gap_raises(self):
        cm, cur = _scripted_cursor(rowcounts=[0])
        with patch("app.services.meat_audit_service.raf_cursor", cm), \
             pytest.raises(ValueError, match="not found"):
            record_primary_evidence(
                gap_id=999, coder_id=42, phrase="ok", meat_element="M", tenant_id="1",
            )


# ===========================================================================
# 2. submit_for_review
# ===========================================================================


class TestSubmitForReview:
    def test_high_revenue_triggers_review_pending(self):
        gap = _gap_row(
            revenue_impact=HIGH_REVENUE_THRESHOLD + 1.0,
            audit_status="primary_coded",
            evidence_phrase="hypertension monitored",
            meat_element="M",
            primary_coder_id=42,
        )
        updated = {**gap, "audit_status": "review_pending"}
        cm, cur = _scripted_cursor(fetchone_results=[gap, updated])
        with patch("app.services.meat_audit_service.raf_cursor", cm):
            result = submit_for_review(gap_id=1, coder_id=42, tenant_id="1")
        assert result["audit_status"] == "review_pending"
        assert result["review_required"] is True

    def test_old_gap_triggers_review_pending(self):
        old_created = datetime.now(timezone.utc) - timedelta(days=OLD_GAP_DAYS + 5)
        gap = _gap_row(
            revenue_impact=100.0,  # well below threshold
            audit_status="primary_coded",
            evidence_phrase="dx noted",
            meat_element="A",
            primary_coder_id=42,
            created_at=old_created,
        )
        updated = {**gap, "audit_status": "review_pending"}
        cm, cur = _scripted_cursor(fetchone_results=[gap, updated])
        with patch("app.services.meat_audit_service.raf_cursor", cm):
            result = submit_for_review(gap_id=1, coder_id=42, tenant_id="1")
        assert result["review_required"] is True

    def test_low_revenue_recent_gap_does_not_require_review(self):
        gap = _gap_row(
            revenue_impact=100.0,
            audit_status="primary_coded",
            evidence_phrase="dx noted",
            meat_element="A",
            primary_coder_id=42,
            created_at=datetime.now(timezone.utc),
        )
        updated = {**gap}  # status unchanged
        cm, cur = _scripted_cursor(fetchone_results=[gap, updated])
        with patch("app.services.meat_audit_service.raf_cursor", cm):
            result = submit_for_review(gap_id=1, coder_id=42, tenant_id="1")
        assert result["review_required"] is False
        assert result["audit_status"] == "primary_coded"

    def test_missing_phrase_blocks_submit(self):
        gap = _gap_row(audit_status="primary_coded", evidence_phrase=None)
        cm, cur = _scripted_cursor(fetchone_results=[gap])
        with patch("app.services.meat_audit_service.raf_cursor", cm), \
             pytest.raises(ValueError, match="evidence_phrase"):
            submit_for_review(gap_id=1, coder_id=42, tenant_id="1")

    def test_wrong_state_blocks_submit(self):
        gap = _gap_row(audit_status="approved", evidence_phrase="ok", meat_element="M")
        cm, cur = _scripted_cursor(fetchone_results=[gap])
        with patch("app.services.meat_audit_service.raf_cursor", cm), \
             pytest.raises(ValueError, match="audit_status"):
            submit_for_review(gap_id=1, coder_id=42, tenant_id="1")


# ===========================================================================
# 3. approve_review
# ===========================================================================


class TestApproveReview:
    def test_happy_path(self):
        gap = _gap_row(
            audit_status="review_pending",
            evidence_phrase="ok", meat_element="T",
            primary_coder_id=42,
        )
        approved = {
            **gap,
            "audit_status": "approved",
            "secondary_coder_id": 99,
            "secondary_approved_at": datetime.now(timezone.utc),
        }
        cm, cur = _scripted_cursor(fetchone_results=[gap, approved])
        with patch("app.services.meat_audit_service.raf_cursor", cm):
            result = approve_review(gap_id=1, secondary_coder_id=99, tenant_id="1")
        assert result["audit_status"] == "approved"
        assert result["secondary_coder_id"] == 99

    def test_same_coder_rejected(self):
        gap = _gap_row(audit_status="review_pending", primary_coder_id=42)
        cm, cur = _scripted_cursor(fetchone_results=[gap])
        with patch("app.services.meat_audit_service.raf_cursor", cm), \
             pytest.raises(ValueError, match="differ from primary"):
            approve_review(gap_id=1, secondary_coder_id=42, tenant_id="1")

    def test_wrong_state(self):
        gap = _gap_row(audit_status="draft", primary_coder_id=42)
        cm, cur = _scripted_cursor(fetchone_results=[gap])
        with patch("app.services.meat_audit_service.raf_cursor", cm), \
             pytest.raises(ValueError, match="audit_status"):
            approve_review(gap_id=1, secondary_coder_id=99, tenant_id="1")


# ===========================================================================
# 4. reject_review
# ===========================================================================


class TestRejectReview:
    def test_happy_path(self):
        gap = _gap_row(audit_status="review_pending", primary_coder_id=42)
        rejected = {**gap, "audit_status": "rejected", "secondary_coder_id": 99,
                    "audit_notes": "[REJECT] phrase too vague"}
        cm, cur = _scripted_cursor(fetchone_results=[gap, rejected])
        with patch("app.services.meat_audit_service.raf_cursor", cm):
            result = reject_review(
                gap_id=1, secondary_coder_id=99,
                reason="phrase too vague", tenant_id="1",
            )
        assert result["audit_status"] == "rejected"

    def test_blank_reason(self):
        with pytest.raises(ValueError, match="reason"):
            reject_review(gap_id=1, secondary_coder_id=99, reason="   ", tenant_id="1")

    def test_wrong_state(self):
        gap = _gap_row(audit_status="approved")
        cm, cur = _scripted_cursor(fetchone_results=[gap])
        with patch("app.services.meat_audit_service.raf_cursor", cm), \
             pytest.raises(ValueError, match="audit_status"):
            reject_review(gap_id=1, secondary_coder_id=99, reason="bad", tenant_id="1")


# ===========================================================================
# 5. get_review_queue
# ===========================================================================


class TestGetReviewQueue:
    def test_returns_rows_for_status(self):
        rows = [
            _gap_row(id=1, audit_status="review_pending", revenue_impact=4000),
            _gap_row(id=2, audit_status="review_pending", revenue_impact=2000),
        ]
        cm, cur = _scripted_cursor(fetchall_results=[rows])
        with patch("app.services.meat_audit_service.raf_cursor", cm):
            queue = get_review_queue(tenant_id="1", status="review_pending")
        assert len(queue) == 2
        assert {q["id"] for q in queue} == {1, 2}


# ===========================================================================
# 6. compute_audit_readiness
# ===========================================================================


class TestAuditReadiness:
    def test_empty_tenant_returns_zeroes(self):
        cm, cur = _scripted_cursor(fetchall_results=[[]])
        with patch("app.services.meat_audit_service.raf_cursor", cm):
            result = compute_audit_readiness(tenant_id="1")
        assert result == {
            "total_gaps": 0,
            "with_evidence": 0,
            "dual_signed": 0,
            "audit_ready_pct": 0.0,
            "missing_meat": [],
        }

    def test_mixed_states(self):
        rows = [
            # Fully approved + dual signed
            {"id": 1, "patient_id": "p1", "hcc_code": "85",
             "evidence_phrase": "ok", "meat_element": "M",
             "audit_status": "approved", "primary_coder_id": 1,
             "secondary_coder_id": 2, "revenue_impact": 5000},
            # Has evidence but not approved
            {"id": 2, "patient_id": "p2", "hcc_code": "19",
             "evidence_phrase": "ok", "meat_element": "T",
             "audit_status": "primary_coded", "primary_coder_id": 1,
             "secondary_coder_id": None, "revenue_impact": 3000},
            # No evidence at all
            {"id": 3, "patient_id": "p3", "hcc_code": "111",
             "evidence_phrase": None, "meat_element": None,
             "audit_status": "draft", "primary_coder_id": None,
             "secondary_coder_id": None, "revenue_impact": 4000},
        ]
        cm, cur = _scripted_cursor(fetchall_results=[rows])
        with patch("app.services.meat_audit_service.raf_cursor", cm):
            result = compute_audit_readiness(tenant_id="1")
        assert result["total_gaps"] == 3
        assert result["with_evidence"] == 2
        assert result["dual_signed"] == 1
        assert result["audit_ready_pct"] == round(1 / 3 * 100, 2)
        # Missing list should include gaps 2 and 3, ordered by revenue desc.
        ids = [m["gap_id"] for m in result["missing_meat"]]
        assert ids == [3, 2]

    def test_readiness_rises_after_approval(self):
        # Initial state: no approvals.
        before_rows = [
            {"id": 1, "patient_id": "p1", "hcc_code": "85",
             "evidence_phrase": None, "meat_element": None,
             "audit_status": "draft", "primary_coder_id": None,
             "secondary_coder_id": None, "revenue_impact": 5000},
            {"id": 2, "patient_id": "p2", "hcc_code": "19",
             "evidence_phrase": None, "meat_element": None,
             "audit_status": "draft", "primary_coder_id": None,
             "secondary_coder_id": None, "revenue_impact": 2000},
        ]
        # After workflow: gap 1 approved.
        after_rows = [
            {"id": 1, "patient_id": "p1", "hcc_code": "85",
             "evidence_phrase": "monitored", "meat_element": "M",
             "audit_status": "approved", "primary_coder_id": 1,
             "secondary_coder_id": 2, "revenue_impact": 5000},
            {"id": 2, "patient_id": "p2", "hcc_code": "19",
             "evidence_phrase": None, "meat_element": None,
             "audit_status": "draft", "primary_coder_id": None,
             "secondary_coder_id": None, "revenue_impact": 2000},
        ]
        cm_before, _ = _scripted_cursor(fetchall_results=[before_rows])
        cm_after, _ = _scripted_cursor(fetchall_results=[after_rows])

        with patch("app.services.meat_audit_service.raf_cursor", cm_before):
            before = compute_audit_readiness(tenant_id="1")
        with patch("app.services.meat_audit_service.raf_cursor", cm_after):
            after = compute_audit_readiness(tenant_id="1")

        assert before["audit_ready_pct"] == 0.0
        assert after["audit_ready_pct"] == 50.0
        assert after["dual_signed"] == 1


# ===========================================================================
# 7. PDF / HTML render smoke test
# ===========================================================================


class TestAuditPdfRender:
    def test_render_audit_html_contains_header_and_gap(self):
        from app.services import recapture_audit_pdf as pdf_mod

        approved_gaps = [
            {
                "id": 1, "patient_id": "100", "patient_name": "Jane Doe",
                "hcc_code": "85", "icd10_code": "I50.9",
                "prior_year": 2025, "current_year": 2026,
                "evidence_phrase": "Patient remains on furosemide for CHF.",
                "evidence_source_url": "fhir://DocumentReference/abc",
                "meat_element": "T", "revenue_impact": 4500.0,
                "primary_coder_id": 42, "primary_coder_name": "Alice Coder",
                "primary_coder_email": "alice@x.com",
                "primary_coded_at": "2026-04-01T10:00:00",
                "secondary_coder_id": 99, "secondary_coder_name": "Bob Reviewer",
                "secondary_coder_email": "bob@x.com",
                "secondary_approved_at": "2026-04-02T11:00:00",
                "audit_notes": "Looks complete.",
                "audit_status": "approved",
            }
        ]
        readiness = {
            "total_gaps": 1, "with_evidence": 1, "dual_signed": 1,
            "audit_ready_pct": 100.0, "missing_meat": [],
        }

        with patch.object(pdf_mod, "get_approved_gaps_for_pdf", return_value=approved_gaps), \
             patch.object(pdf_mod, "compute_audit_readiness", return_value=readiness):
            html = pdf_mod.render_audit_html(tenant_id="1", year=2026)

        assert "RADV Audit Defense" in html
        assert "Tenant 1" in html
        assert "HCC 85" in html
        assert "Patient remains on furosemide" in html
        assert "Alice Coder" in html
        assert "Bob Reviewer" in html
        assert "100.0%" in html

    def test_build_audit_pdf_returns_bytes_when_weasyprint_available(self):
        """Smoke test — only runs when WeasyPrint is importable."""
        try:
            import weasyprint  # noqa: F401
        except Exception:
            pytest.skip("WeasyPrint not installed in this environment")

        from app.services import recapture_audit_pdf as pdf_mod

        with patch.object(pdf_mod, "get_approved_gaps_for_pdf", return_value=[]), \
             patch.object(pdf_mod, "compute_audit_readiness",
                          return_value={"total_gaps": 0, "with_evidence": 0,
                                        "dual_signed": 0, "audit_ready_pct": 0.0,
                                        "missing_meat": []}):
            pdf = pdf_mod.build_audit_pdf(tenant_id="1")

        assert isinstance(pdf, bytes)
        assert pdf.startswith(b"%PDF-")
