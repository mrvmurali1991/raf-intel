"""
Tests for the FHIR Problem List write-back path.

Covers:
1. build_condition_body — pure body builder asserts the exact FHIR shape
   the spec requires (resourceType, clinicalStatus, verificationStatus,
   code.coding system http://hl7.org/fhir/sid/icd-10-cm, subject.reference,
   recordedDate, and both extensions).
2. push_problem_list_condition happy path — mocked OpenEMR FHIR client
   returns 201 + Location header and we return the parsed Condition id.
3. action_accept_suspect happy path — FHIR write succeeds; response
   includes the FHIR Condition id and push_method="fhir".
4. action_accept_suspect FHIR failure → fallback — FHIR write raises;
   we fall back to ``push_medical_problem`` and report
   push_method="fhir_then_mysql_fallback".
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.fhir_problem_list import (
    ICD10_SYSTEM,
    RAF_SUSPECT_EXT_URL,
    US_CORE_ASSERTED_DATE_URL,
    build_condition_body,
    push_problem_list_condition,
)

# ---------------------------------------------------------------------------
# Unit tests — build_condition_body
# ---------------------------------------------------------------------------


def test_build_condition_body_shape() -> None:
    body = build_condition_body(
        patient_emr_pid="3",
        icd10_code="E11.22",
        hcc_label="Diabetes w/ CKD",
        recorded_date="2026-05-17",
        source={"suspect_id": 42, "source": "raf_intelligence_normal_accept"},
    )

    assert body["resourceType"] == "Condition"

    # clinicalStatus + verificationStatus codings
    assert body["clinicalStatus"]["coding"][0]["code"] == "active"
    assert body["verificationStatus"]["coding"][0]["code"] == "confirmed"

    # code.coding uses the ICD-10-CM system + supplied code + display
    coding = body["code"]["coding"][0]
    assert coding["system"] == ICD10_SYSTEM
    assert coding["code"] == "E11.22"
    assert coding["display"] == "Diabetes w/ CKD"

    # subject.reference is the FHIR Patient/{pid}
    assert body["subject"]["reference"] == "Patient/3"

    # recordedDate is the ISO date the caller passed
    assert body["recordedDate"] == "2026-05-17"

    # Extensions include US Core assertedDate AND the RAF Intelligence
    # suspect_id pointer.
    urls = {ext["url"] for ext in body["extension"]}
    assert US_CORE_ASSERTED_DATE_URL in urls
    assert RAF_SUSPECT_EXT_URL in urls
    # The RAF extension should mention the suspect_id we passed.
    raf_ext = next(e for e in body["extension"] if e["url"] == RAF_SUSPECT_EXT_URL)
    assert "suspect_id=42" in raf_ext["valueString"]
    assert "raf_intelligence_normal_accept" in raf_ext["valueString"]

    # Problem List Item category
    cat_coding = body["category"][0]["coding"][0]
    assert cat_coding["code"] == "problem-list-item"


def test_build_condition_body_defaults_recorded_date_to_today() -> None:
    body = build_condition_body(
        patient_emr_pid="9",
        icd10_code="J44.9",
        hcc_label="COPD",
    )
    # ISO yyyy-mm-dd
    assert len(body["recordedDate"]) == 10
    assert body["recordedDate"][4] == "-"


# ---------------------------------------------------------------------------
# push_problem_list_condition happy path (mocked OpenEMRFhirAdapter + httpx)
# ---------------------------------------------------------------------------


def _make_fake_adapter() -> MagicMock:
    adapter = MagicMock()
    adapter.base_url = "https://localhost:7443/apis/default/fhir"
    adapter._auth_headers.return_value = {
        "Authorization": "Bearer fake-token",
        "Accept": "application/fhir+json",
    }
    adapter._force_refresh.return_value = None
    return adapter


def test_push_problem_list_condition_happy_path() -> None:
    adapter = _make_fake_adapter()

    fake_resp = MagicMock()
    fake_resp.status_code = 201
    fake_resp.headers = {
        "Location": (
            "https://localhost:7443/apis/default/fhir/Condition/"
            "abc-123-def/_history/1"
        )
    }
    fake_resp.json.return_value = {"id": "abc-123-def", "resourceType": "Condition"}

    fake_client_cm = MagicMock()
    fake_client = MagicMock()
    fake_client.post.return_value = fake_resp
    fake_client_cm.__enter__.return_value = fake_client
    fake_client_cm.__exit__.return_value = False

    with patch(
        "app.services.fhir_problem_list.httpx.Client",
        return_value=fake_client_cm,
    ):
        condition_id = push_problem_list_condition(
            patient_emr_pid="3",
            icd10_code="E11.22",
            hcc_label="Diabetes w/ CKD",
            source={"suspect_id": 7, "source": "raf_intelligence_normal_accept"},
            adapter=adapter,
        )

    assert condition_id == "abc-123-def"
    # Ensure we POSTed to the Condition endpoint with FHIR JSON body
    args, kwargs = fake_client.post.call_args
    assert args[0].endswith("/Condition")
    sent = kwargs["json"]
    assert sent["resourceType"] == "Condition"
    assert sent["subject"]["reference"] == "Patient/3"
    assert sent["code"]["coding"][0]["code"] == "E11.22"


def test_push_problem_list_condition_raises_on_4xx() -> None:
    adapter = _make_fake_adapter()
    fake_resp = MagicMock()
    fake_resp.status_code = 400
    fake_resp.headers = {}
    fake_resp.text = '{"resourceType":"OperationOutcome","issue":[]}'

    fake_client_cm = MagicMock()
    fake_client = MagicMock()
    fake_client.post.return_value = fake_resp
    fake_client_cm.__enter__.return_value = fake_client
    fake_client_cm.__exit__.return_value = False

    with patch(
        "app.services.fhir_problem_list.httpx.Client",
        return_value=fake_client_cm,
    ):
        with pytest.raises(RuntimeError):
            push_problem_list_condition(
                patient_emr_pid="3",
                icd10_code="E11.22",
                hcc_label="Diabetes w/ CKD",
                adapter=adapter,
            )


# ---------------------------------------------------------------------------
# Router integration — action_accept_suspect with FHIR write-back
# ---------------------------------------------------------------------------


@pytest.fixture()
def accept_result():
    return {
        "suspect_id": 5,
        "suspect_hcc": "HCC37",
        "suspect_icd10": "E11.9",
        "patient_id": 3,
        "tenant_id": 1,
    }


@pytest.fixture(autouse=True)
def _patch_router_guards():
    """Patch tenant-access guards so the action endpoint accepts pid=3."""
    with (
        patch(
            "app.services.patient_service.patient_is_accessible",
            return_value=True,
        ),
        patch(
            "app.routers.raf_central.patient_is_accessible",
            return_value=True,
            create=True,
        ),
        # Bypass the pending-clinical-query pre-check (uses raf_cursor)
        patch("app.routers.raf_central.raf_cursor") as cur_cm,
    ):
        # raf_cursor is a context manager; return a cursor that yields no rows
        fake_cur = MagicMock()
        fake_cur.fetchone.return_value = None
        cur_cm.return_value.__enter__.return_value = fake_cur
        cur_cm.return_value.__exit__.return_value = False
        yield


def test_action_accept_suspect_uses_fhir_when_push_to_emr_true(
    client, admin_headers, accept_result
) -> None:
    with (
        patch(
            "app.routers.raf_central.accept_suspect", return_value=accept_result
        ),
        patch(
            "app.routers.raf_central.push_problem_list_condition",
            return_value="fhir-cond-id-001",
        ) as fhir_push,
        patch(
            "app.routers.raf_central.reconcile_condition", return_value=True
        ) as recon,
        patch(
            "app.routers.raf_central.push_medical_problem", return_value=True
        ) as mysql_push,
        patch(
            "app.routers.raf_central.emit_audit_event"
        ) as audit,
        patch("app.routers.raf_central.cache_delete_pattern"),
    ):
        resp = client.post(
            "/api/raf-central/3/actions/accept-suspect",
            headers=admin_headers,
            json={"suspect_id": 5, "push_to_emr": True},
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["pushed_to_emr"] is True
    assert body["fhir_condition_id"] == "fhir-cond-id-001"
    assert body["fhir_reconciled"] is True
    assert body["push_method"] == "fhir"

    fhir_push.assert_called_once()
    recon.assert_called_once()
    mysql_push.assert_not_called()
    # Audit event emitted with the FHIR id
    audit_calls = [c for c in audit.call_args_list]
    assert any(
        c.args and c.args[0] == "SUSPECT_PUSHED_TO_EHR_VIA_FHIR" for c in audit_calls
    )


def test_action_accept_suspect_falls_back_to_push_medical_problem_on_fhir_failure(
    client, admin_headers, accept_result
) -> None:
    with (
        patch(
            "app.routers.raf_central.accept_suspect", return_value=accept_result
        ),
        patch(
            "app.routers.raf_central.push_problem_list_condition",
            side_effect=RuntimeError("FHIR endpoint unreachable"),
        ) as fhir_push,
        patch(
            "app.routers.raf_central.push_medical_problem", return_value=True
        ) as mysql_push,
        patch(
            "app.routers.raf_central.reconcile_condition", return_value=True
        ),
        patch(
            "app.routers.raf_central.emit_audit_event"
        ),
        patch("app.routers.raf_central.cache_delete_pattern"),
    ):
        resp = client.post(
            "/api/raf-central/3/actions/accept-suspect",
            headers=admin_headers,
            json={"suspect_id": 5, "push_to_emr": True},
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    # FHIR was attempted twice (initial + 1 retry), then MySQL fallback fired.
    assert fhir_push.call_count == 2
    mysql_push.assert_called_once()
    assert body["pushed_to_emr"] is True
    assert body["fhir_condition_id"] is None
    assert body["push_method"] == "fhir_then_mysql_fallback"


def test_action_accept_suspect_records_force_source_in_audit(
    client, admin_headers, accept_result
) -> None:
    with (
        patch(
            "app.routers.raf_central.accept_suspect", return_value=accept_result
        ),
        patch(
            "app.routers.raf_central.push_problem_list_condition",
            return_value="fhir-cond-id-002",
        ),
        patch(
            "app.routers.raf_central.reconcile_condition", return_value=True
        ),
        patch(
            "app.routers.raf_central.push_medical_problem", return_value=True
        ),
        patch(
            "app.routers.raf_central.emit_audit_event"
        ) as audit,
        patch("app.routers.raf_central.cache_delete_pattern"),
    ):
        resp = client.post(
            "/api/raf-central/3/actions/accept-suspect",
            headers=admin_headers,
            json={"suspect_id": 5, "push_to_emr": True, "force": True},
        )

    assert resp.status_code == 200
    # Find the push audit call and verify source string
    pushed_calls = [
        c for c in audit.call_args_list
        if c.args and c.args[0] == "SUSPECT_PUSHED_TO_EHR_VIA_FHIR"
    ]
    assert pushed_calls, "expected SUSPECT_PUSHED_TO_EHR_VIA_FHIR audit event"
    payload = pushed_calls[0].kwargs.get("payload", {})
    assert payload.get("source") == "raf_intelligence_force_accept"


def test_action_accept_suspect_emits_reconcile_mismatch_when_not_found(
    client, admin_headers, accept_result
) -> None:
    with (
        patch(
            "app.routers.raf_central.accept_suspect", return_value=accept_result
        ),
        patch(
            "app.routers.raf_central.push_problem_list_condition",
            return_value="fhir-cond-id-003",
        ),
        patch(
            "app.routers.raf_central.reconcile_condition", return_value=False
        ),
        patch(
            "app.routers.raf_central.push_medical_problem", return_value=True
        ),
        patch(
            "app.routers.raf_central.emit_audit_event"
        ) as audit,
        patch("app.routers.raf_central.cache_delete_pattern"),
    ):
        resp = client.post(
            "/api/raf-central/3/actions/accept-suspect",
            headers=admin_headers,
            json={"suspect_id": 5, "push_to_emr": True},
        )

    assert resp.status_code == 200
    assert resp.json()["fhir_reconciled"] is False
    mismatch_calls = [
        c for c in audit.call_args_list
        if c.args and c.args[0] == "SUSPECT_FHIR_RECONCILE_MISMATCH"
    ]
    assert mismatch_calls, "expected SUSPECT_FHIR_RECONCILE_MISMATCH audit event"
