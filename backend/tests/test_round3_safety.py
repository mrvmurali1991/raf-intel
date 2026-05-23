"""
Patient Safety round-3 regression tests.

Covers:
  N3: raf_central accept handler correctly threads meat_signed/user_role/user_id
      through to push_problem_list_condition so the confirmed path is reachable.
  N1: _REVERSAL_ALLOWED_ROLES includes "physician" (consistent with credentialed
      write roles in fhir_problem_list).
  N2: EDI override gate enforces reviewer_user_id != submitter user_id (4-eyes).
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch, call

import pytest


# ---------------------------------------------------------------------------
# N3 — raf_central wires meat_signed / user_role / user_id to FHIR push
#
# We test the call site directly: verify that the three local variables
# (_meat_signed, _user_role, _user_id) are computed and forwarded rather
# than testing the full accept flow (which requires a live DB).
# ---------------------------------------------------------------------------

class TestFhirCallSiteWireup:
    """
    Static analysis of the call-site patch: parse the source of
    action_accept_suspect and confirm the safety kwargs are present.

    This avoids the need for a full DB mock while still verifying the
    bug (missing kwargs) cannot regress silently.
    """

    def test_push_call_includes_meat_signed(self) -> None:
        """push_problem_list_condition call must include meat_signed kwarg."""
        import inspect
        from app.routers import raf_central

        src = inspect.getsource(raf_central.action_accept_suspect)
        assert "meat_signed=_meat_signed" in src, (
            "push_problem_list_condition call site is missing meat_signed=_meat_signed"
        )

    def test_push_call_includes_user_role(self) -> None:
        """push_problem_list_condition call must include user_role kwarg."""
        import inspect
        from app.routers import raf_central

        src = inspect.getsource(raf_central.action_accept_suspect)
        assert "user_role=_user_role" in src, (
            "push_problem_list_condition call site is missing user_role=_user_role"
        )

    def test_push_call_includes_user_id(self) -> None:
        """push_problem_list_condition call must include user_id kwarg."""
        import inspect
        from app.routers import raf_central

        src = inspect.getsource(raf_central.action_accept_suspect)
        assert "user_id=_user_id" in src, (
            "push_problem_list_condition call site is missing user_id=_user_id"
        )

    def test_user_role_sourced_from_current_user(self) -> None:
        """_user_role must be derived from current_user.get('role')."""
        import inspect
        from app.routers import raf_central

        src = inspect.getsource(raf_central.action_accept_suspect)
        assert '_user_role = current_user.get("role")' in src, (
            "_user_role not set from current_user.get('role')"
        )

    def test_user_id_sourced_from_current_user(self) -> None:
        """_user_id must be derived from current_user id fields."""
        import inspect
        from app.routers import raf_central

        src = inspect.getsource(raf_central.action_accept_suspect)
        assert '_user_id = current_user.get("id") or current_user.get("user_id")' in src, (
            "_user_id not set from current_user id fields"
        )

    def test_meat_signed_sourced_from_body(self) -> None:
        """_meat_signed must be derived from body.meat_signed."""
        import inspect
        from app.routers import raf_central

        src = inspect.getsource(raf_central.action_accept_suspect)
        assert "_meat_signed = bool(body.meat_signed)" in src, (
            "_meat_signed not set from body.meat_signed"
        )


class TestAcceptMeatSignedKwargsViaFhirLib:
    """
    End-to-end style: call push_problem_list_condition with meat_signed=True
    and a coder role — confirm the FHIR body uses 'confirmed' verification.
    This validates the round-trip through the build_condition_body logic.
    """

    def test_accept_meat_signed_results_in_confirmed_writeback(self) -> None:
        """meat_signed=True + coder role -> verificationStatus confirmed."""
        from app.services.fhir_problem_list import build_condition_body

        body = build_condition_body(
            patient_emr_pid="7",
            icd10_code="E11.9",
            hcc_label="Type 2 Diabetes",
            source={"suspect_id": 99, "source": "raf_intelligence_normal_accept"},
            meat_signed=True,
            user_role="coder",
            user_npi="1234567890",
        )
        ver_code = body["verificationStatus"]["coding"][0]["code"]
        assert ver_code == "confirmed", (
            f"Expected 'confirmed' when meat_signed=True + coder role, got '{ver_code}'"
        )
        # recorder should be set
        assert body.get("recorder") == {"reference": "Practitioner/1234567890"}

    def test_accept_no_meat_results_in_provisional(self) -> None:
        """meat_signed=False -> verificationStatus provisional."""
        from app.services.fhir_problem_list import build_condition_body

        body = build_condition_body(
            patient_emr_pid="7",
            icd10_code="E11.9",
            hcc_label="Type 2 Diabetes",
            source={"suspect_id": 99, "source": "raf_intelligence_normal_accept"},
            meat_signed=False,
            user_role="coder",
        )
        ver_code = body["verificationStatus"]["coding"][0]["code"]
        assert ver_code == "provisional", (
            f"Expected 'provisional' when meat_signed=False, got '{ver_code}'"
        )


# ---------------------------------------------------------------------------
# N1 — physician role is in _REVERSAL_ALLOWED_ROLES
# ---------------------------------------------------------------------------

def test_reversal_allows_physician() -> None:
    """physician must be in _REVERSAL_ALLOWED_ROLES (consistent with credentialed write roles)."""
    from app.routers.suspects import _REVERSAL_ALLOWED_ROLES

    assert "physician" in _REVERSAL_ALLOWED_ROLES, (
        f"'physician' missing from _REVERSAL_ALLOWED_ROLES={_REVERSAL_ALLOWED_ROLES}"
    )
    # confirm coder and admin remain
    assert "coder" in _REVERSAL_ALLOWED_ROLES
    assert "admin" in _REVERSAL_ALLOWED_ROLES


# ---------------------------------------------------------------------------
# N2 — EDI override rejects same user as both submitter and reviewer
# ---------------------------------------------------------------------------

def test_edi_override_rejects_self_review() -> None:
    """reviewer_user_id == submitter user_id must return HTTP 422."""
    from fastapi import HTTPException
    from app.routers.edi_generation import generate_837, Generate837Request

    body = Generate837Request(
        patient_ids=[1],
        payment_year=2025,
        run_pre_submission_validator=True,
        confirm_override=True,
        override_reason="A" * 40,  # meets the 30-char min
        reviewer_user_id=99,  # same as current_user below
    )

    current_user = {"id": 99, "role": "admin", "tenant_id": "tenant1"}

    # Mock validate_batch to report a failure so the override branch is entered.
    fake_report = {
        "per_patient": [],
        "failed_patient_ids": [1],
        "passed_patient_ids": [],
        "high_severity_total": 1,
    }

    with patch("app.routers.edi_generation.validate_batch", return_value=fake_report):
        with pytest.raises(HTTPException) as exc_info:
            generate_837(body=body, current_user=current_user, tenant_id="tenant1")

    assert exc_info.value.status_code == 422
    assert "4-eyes" in exc_info.value.detail, (
        f"Expected 4-eyes message, got: {exc_info.value.detail}"
    )
