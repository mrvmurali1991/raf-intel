"""
RAF Central unified-panel endpoint tests.

Covers `GET /api/raf-central/{pid}` shape + caching and the inline-action
endpoints (`accept-suspect`, `dismiss-suspect`, `mark-meat-reviewed`).

All DB + service calls are mocked. Auth uses `admin_headers` from conftest,
which resolves to MOCK_ADMIN_USER via the autouse `_patch_auth_resolution`
fixture.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def fake_breakdown():
    """Return a minimal but realistic `get_raf_breakdown` payload."""
    return {
        "raf_score": 1.234,
        "hcc_count": 2,
        "model_segment": "CNA",
        "model_version": "v28",
        "hcc_details": [
            {
                "hcc_code": "37",
                "hcc_label": "Diabetes w/ Chronic Complications",
                "icd10_codes": ["E11.22"],
                "coefficient": 0.302,
                "meat_status": "complete",
            },
            {
                "hcc_code": "111",
                "hcc_label": "COPD",
                "icd10_codes": ["J44.9"],
                "coefficient": 0.335,
                "meat_status": "missing",
            },
        ],
    }


@pytest.fixture()
def fake_suspects():
    return [
        {
            "suspect_id": 101,
            "suspect_hcc": "HCC59",
            "suspect_icd10": "F32.9",
            "confidence_score": 0.82,
            "evidence_type": "medication",
            "status": "open",
        },
        # Dismissed — should be filtered out by `_build_suspects`
        {
            "suspect_id": 102,
            "suspect_hcc": "HCC18",
            "suspect_icd10": "E11.9",
            "confidence_score": 0.90,
            "evidence_type": "lab",
            "status": "dismissed",
        },
    ]


@pytest.fixture()
def fake_recapture():
    return [
        {
            "id": 7,
            "hcc_code": "85",
            "icd10_code": "I50.9",
            "hcc_description": "Congestive Heart Failure",
            "prior_year": 2024,
            "current_year": 2025,
            "raf_impact": 3900.0,
            "last_encounter_date": "2024-11-14",
        }
    ]


@pytest.fixture()
def patch_panel_services(fake_breakdown, fake_suspects, fake_recapture):
    """Patch every downstream service the panel fans out to."""
    with (
        patch(
            "app.routers.raf_central.get_raf_breakdown",
            return_value=fake_breakdown,
        ),
        patch(
            "app.routers.raf_central.get_suspects_for_patient",
            return_value=fake_suspects,
        ),
        patch(
            "app.routers.raf_central.get_patient_gaps",
            return_value=fake_recapture,
        ),
        patch(
            "app.routers.raf_central.get_patient",
            return_value={"pid": "1", "fname": "Test", "lname": "Patient"},
        ),
        patch(
            "app.routers.raf_central.get_active_connection_id",
            return_value="test-conn",
        ),
        # Cache miss by default; individual tests override if needed.
        patch("app.routers.raf_central.cache_get", return_value=None),
        patch("app.routers.raf_central.cache_set", return_value=None),
        patch("app.routers.raf_central.cache_delete_pattern", return_value=None),
        # Silence letter-level MEAT lookups — table queries against mocked cursor.
        # _fetch_meat_letters now returns (letter_map, hcc_id_map) as a tuple;
        # _fetch_patient_hcc_id is no longer called in the main panel loop.
        patch(
            "app.routers.raf_central._fetch_meat_letters",
            return_value=({}, {}),
        ),
    ):
        yield


# ---------------------------------------------------------------------------
# GET /api/raf-central/{pid} — happy path
# ---------------------------------------------------------------------------


def test_panel_returns_full_payload_shape(client, admin_headers, patch_panel_services):
    resp = client.get("/api/raf-central/1?year=2025", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # Top-level shape
    for key in [
        "patient_id",
        "measurement_year",
        "generated_at",
        "raf_score",
        "meat_gaps",
        "suspects",
        "recapture",
        "coding_opt",
        "audit_readiness",
        "financial_impact",
    ]:
        assert key in body, f"missing key {key}"

    assert body["patient_id"] == 1
    assert body["measurement_year"] == 2025

    # RAF bar pulls from get_raf_breakdown
    assert body["raf_score"]["current"] == pytest.approx(1.234)
    assert body["raf_score"]["hcc_count"] == 2
    assert body["raf_score"]["year"] == 2025

    # MEAT gaps — one per hcc_detail
    assert len(body["meat_gaps"]) == 2
    codes = {g["hcc"] for g in body["meat_gaps"]}
    assert codes == {"37", "111"}
    complete = next(g for g in body["meat_gaps"] if g["hcc"] == "37")
    assert complete["status"] == "COMPLETE"
    missing = next(g for g in body["meat_gaps"] if g["hcc"] == "111")
    assert missing["status"] == "NOT_COMPLIANT"

    # Suspects — dismissed filtered out
    assert len(body["suspects"]) == 1
    assert body["suspects"][0]["id"] == 101
    assert body["suspects"][0]["hcc"] == 59

    # Recapture
    assert len(body["recapture"]) == 1
    assert body["recapture"][0]["hcc"] == "85"

    # Audit readiness — 1/2 complete = 50% → MEDIUM
    assert body["audit_readiness"]["hccs_total"] == 2
    assert body["audit_readiness"]["hccs_compliant"] == 1
    assert body["audit_readiness"]["risk_level"] == "MEDIUM"

    # Financial impact uses settings.cms_revenue_per_raf_point
    assert body["financial_impact"]["current_raf"] == pytest.approx(1.234)
    assert body["financial_impact"]["projected_raf"] > body["financial_impact"]["current_raf"]


# ---------------------------------------------------------------------------
# Auth + tenant guards
# ---------------------------------------------------------------------------


def test_panel_requires_auth(client):
    resp = client.get("/api/raf-central/1")
    assert resp.status_code == 401


def test_panel_rejects_user_without_tenant(client, admin_headers, patch_panel_services):
    """A tenant-less user is rejected — `get_current_user` catches it at the
    auth layer (401) before raf_central's own 403 guard runs."""
    from tests.conftest import MOCK_ADMIN_USER

    tenantless = dict(MOCK_ADMIN_USER)
    tenantless["tenant_id"] = None

    with patch("app.auth.get_user", return_value=tenantless):
        resp = client.get("/api/raf-central/1", headers=admin_headers)
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Caching behaviour
# ---------------------------------------------------------------------------


def test_panel_serves_from_cache_when_present(client, admin_headers, fake_breakdown):
    """Cache hit must short-circuit all service fan-outs."""
    cached_payload = {
        "patient_id": 1,
        "measurement_year": 2025,
        "generated_at": "2026-04-17T12:00:00+00:00",
        "raf_score": {
            "current": 9.99,
            "prior_year": None,
            "delta": None,
            "hcc_count": 0,
            "model_segment": "CNA",
            "model_version": "v28",
            "year": 2025,
        },
        "meat_gaps": [],
        "suspects": [],
        "recapture": [],
        "coding_opt": [],
        "audit_readiness": {
            "meat_compliance_pct": 0.0,
            "hccs_compliant": 0,
            "hccs_total": 0,
            "risk_level": "LOW",
        },
        "financial_impact": {
            "current_raf": 9.99,
            "projected_raf": 9.99,
            "current_annual": 0.0,
            "projected_annual": 0.0,
            "pmpm_delta": 0.0,
            "annual_delta": 0.0,
            "revenue_per_raf_point": 11015.04,
        },
    }

    with (
        patch("app.routers.raf_central.cache_get", return_value=cached_payload),
        patch(
            "app.routers.raf_central.get_active_connection_id",
            return_value="test-conn",
        ),
        patch("app.routers.raf_central.get_raf_breakdown") as bk,
        patch("app.routers.raf_central.get_suspects_for_patient") as sp,
    ):
        resp = client.get("/api/raf-central/1?year=2025", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["raf_score"]["current"] == 9.99
        # Cache hit must skip fan-out
        bk.assert_not_called()
        sp.assert_not_called()


# ---------------------------------------------------------------------------
# Action endpoints
# ---------------------------------------------------------------------------


def test_accept_suspect_invalidates_cache(client, admin_headers):
    with (
        patch(
            "app.routers.raf_central.accept_suspect",
            return_value={"suspect_id": 5, "suspect_hcc": "HCC37", "suspect_icd10": "E11.9"},
        ) as acc,
        patch(
            "app.routers.raf_central.push_medical_problem", return_value=True
        ) as push,
        patch(
            "app.routers.raf_central.cache_delete_pattern"
        ) as inv,
    ):
        resp = client.post(
            "/api/raf-central/1/actions/accept-suspect",
            headers=admin_headers,
            json={"suspect_id": 5, "push_to_emr": True},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["ok"] is True
        assert body["pushed_to_emr"] is True
        acc.assert_called_once()
        push.assert_called_once()
        # Cache invalidation pattern: one for the panel + one for breakdown
        assert inv.call_count >= 1


def test_accept_suspect_skips_emr_push_when_disabled(client, admin_headers):
    with (
        patch(
            "app.routers.raf_central.accept_suspect",
            return_value={"suspect_id": 5, "suspect_hcc": "HCC37", "suspect_icd10": "E11.9"},
        ),
        patch(
            "app.routers.raf_central.push_medical_problem", return_value=True
        ) as push,
        patch("app.routers.raf_central.cache_delete_pattern"),
    ):
        resp = client.post(
            "/api/raf-central/1/actions/accept-suspect",
            headers=admin_headers,
            json={"suspect_id": 5, "push_to_emr": False},
        )
        assert resp.status_code == 200
        assert resp.json()["pushed_to_emr"] is False
        push.assert_not_called()


def test_dismiss_suspect_calls_service(client, admin_headers):
    with (
        patch(
            "app.routers.raf_central.dismiss_suspect",
            return_value={"suspect_id": 9, "status": "dismissed"},
        ) as dis,
        patch("app.routers.raf_central.cache_delete_pattern"),
    ):
        resp = client.post(
            "/api/raf-central/1/actions/dismiss-suspect",
            headers=admin_headers,
            json={"suspect_id": 9, "reason": "patient denies symptoms"},
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        # Verify reason threaded through
        _, kwargs = dis.call_args
        assert kwargs["reason"] == "patient denies symptoms"


def test_mark_meat_reviewed_sets_status_from_filled_letters(
    client, admin_headers, mock_raf_cursor_factory
):
    """Filling all four MEAT letters → meat_status = 'complete'."""
    patcher, _ = mock_raf_cursor_factory()
    with patcher, patch("app.routers.raf_central.cache_delete_pattern"):
        resp = client.post(
            "/api/raf-central/1/actions/mark-meat-reviewed",
            headers=admin_headers,
            json={
                "patient_hcc_id": 42,
                "monitor_note": "BP checked",
                "evaluate_note": "stable",
                "assess_note": "HTN controlled",
                "treat_note": "continue lisinopril",
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["ok"] is True
        assert body["meat_status"] == "complete"


def test_mark_meat_reviewed_partial_status(
    client, admin_headers, mock_raf_cursor_factory
):
    patcher, _ = mock_raf_cursor_factory()
    with patcher, patch("app.routers.raf_central.cache_delete_pattern"):
        resp = client.post(
            "/api/raf-central/1/actions/mark-meat-reviewed",
            headers=admin_headers,
            json={
                "patient_hcc_id": 42,
                "monitor_note": "BP checked",
                # only one letter filled
            },
        )
        assert resp.status_code == 200
        assert resp.json()["meat_status"] == "partial"


def test_action_endpoints_require_auth(client):
    for path, body in [
        ("/api/raf-central/1/actions/accept-suspect", {"suspect_id": 1}),
        ("/api/raf-central/1/actions/dismiss-suspect", {"suspect_id": 1}),
        ("/api/raf-central/1/actions/mark-meat-reviewed", {"patient_hcc_id": 1}),
        (
            "/api/raf-central/1/actions/start-treatment",
            {"hcc_code": "37", "icd10": "E11.9"},
        ),
        ("/api/raf-central/1/actions/order-lab", {"hcc_code": "37", "icd10": "E11.9"}),
    ]:
        resp = client.post(path, json=body)
        assert resp.status_code == 401, f"{path} did not require auth"


# ---------------------------------------------------------------------------
# Start-Treatment action — writes a prescription into OpenEMR
# ---------------------------------------------------------------------------


def test_start_treatment_happy_path_uses_hcc_fallback(client, admin_headers):
    """When the client does not supply a drug, the endpoint falls back to
    the hardcoded HCC→treatment map (HCC 37 → Metformin) and returns the
    new prescription id."""
    with (
        patch(
            "app.routers.raf_central.push_prescription", return_value=9123,
        ) as push_rx,
        patch("app.routers.raf_central.cache_delete_pattern") as inv,
    ):
        resp = client.post(
            "/api/raf-central/1/actions/start-treatment",
            headers=admin_headers,
            json={"hcc_code": "37", "icd10": "E11.9"},
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "ok"
    assert body["prescription_id"] == 9123
    assert body["drug"] == "Metformin 500mg"

    # push_prescription was called with the fallback drug + dosage
    push_rx.assert_called_once()
    _, kwargs = push_rx.call_args
    assert kwargs["drug_name"] == "Metformin 500mg"
    assert kwargs["rxnorm_code"] == "6809"
    assert kwargs["dosage"] == "500mg BID"
    assert kwargs["pid"] == 1
    # Cache invalidation fires — at least the raf_central:{pid}:* pattern
    assert inv.call_count >= 1


def test_start_treatment_uses_client_supplied_drug(client, admin_headers):
    """Client-supplied drug/rxnorm/dosage override the fallback map."""
    with (
        patch(
            "app.routers.raf_central.push_prescription", return_value=9124,
        ) as push_rx,
        patch("app.routers.raf_central.cache_delete_pattern"),
    ):
        resp = client.post(
            "/api/raf-central/1/actions/start-treatment",
            headers=admin_headers,
            json={
                "hcc_code": "999",  # not in fallback map
                "icd10": "Z99.9",
                "suggested_drug": "Atorvastatin 20mg",
                "suggested_rxnorm": "83367",
                "dosage": "20mg QHS",
            },
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["drug"] == "Atorvastatin 20mg"
    _, kwargs = push_rx.call_args
    assert kwargs["drug_name"] == "Atorvastatin 20mg"
    assert kwargs["rxnorm_code"] == "83367"
    assert kwargs["dosage"] == "20mg QHS"


def test_start_treatment_rejects_unknown_hcc_without_override(
    client, admin_headers,
):
    """An HCC with no fallback and no client override → 400, no EMR write."""
    with (
        patch("app.routers.raf_central.push_prescription") as push_rx,
        patch("app.routers.raf_central.cache_delete_pattern"),
    ):
        resp = client.post(
            "/api/raf-central/1/actions/start-treatment",
            headers=admin_headers,
            json={"hcc_code": "999", "icd10": "Z99.9"},
        )
    assert resp.status_code == 400
    push_rx.assert_not_called()


def test_start_treatment_accepts_without_ui_confirm(client, admin_headers):
    """Confirm-dialog protection is a UI concern — the endpoint itself
    must accept a direct POST without any confirm token/flag."""
    with (
        patch(
            "app.routers.raf_central.push_prescription", return_value=9125,
        ),
        patch("app.routers.raf_central.cache_delete_pattern"),
    ):
        resp = client.post(
            "/api/raf-central/1/actions/start-treatment",
            headers=admin_headers,
            json={"hcc_code": "85", "icd10": "I50.9"},  # CHF → Lisinopril
        )
    assert resp.status_code == 200
    assert resp.json()["drug"] == "Lisinopril 10mg"


def test_start_treatment_502_when_emr_disconnected(client, admin_headers):
    """push_prescription returns None when the decorator catches
    NoActiveEMRConnection — endpoint maps that to 502."""
    with (
        patch(
            "app.routers.raf_central.push_prescription", return_value=None,
        ),
        patch("app.routers.raf_central.cache_delete_pattern"),
    ):
        resp = client.post(
            "/api/raf-central/1/actions/start-treatment",
            headers=admin_headers,
            json={"hcc_code": "37", "icd10": "E11.9"},
        )
    assert resp.status_code == 502


# ---------------------------------------------------------------------------
# Order-lab action — happy path, explicit override, no-EMR skip, unmapped HCC
# ---------------------------------------------------------------------------


def test_order_lab_happy_path_uses_hcc_default_map(client, admin_headers):
    """HCC 37 (diabetes family) must default to Hemoglobin A1c (LOINC 4548-4)."""
    with (
        patch(
            "app.routers.raf_central.push_procedure_order",
            return_value=9001,
        ) as push,
        patch("app.routers.raf_central._log_raf_action") as log_action,
        patch("app.routers.raf_central.cache_delete_pattern"),
    ):
        resp = client.post(
            "/api/raf-central/1/actions/order-lab",
            headers=admin_headers,
            json={
                "hcc_code": "37",
                "icd10": "E11.9",
                "suggested_lab_code": None,
                "suggested_lab_name": None,
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "ok"
        assert body["procedure_order_id"] == 9001
        assert body["suggested_lab_code"] == "4548-4"

        # Verify push_procedure_order got the mapped code + icd10 diagnosis
        _, kwargs = push.call_args
        assert kwargs["procedure_code"] == "4548-4"
        assert kwargs["procedure_name"] == "Hemoglobin A1c"
        assert kwargs["diagnosis_code"] == "E11.9"
        assert kwargs["pid"] == 1
        assert log_action.called


def test_order_lab_uses_explicit_override(client, admin_headers):
    """An explicit suggested_lab_code must win over the HCC default map."""
    with (
        patch(
            "app.routers.raf_central.push_procedure_order",
            return_value=9100,
        ) as push,
        patch("app.routers.raf_central._log_raf_action"),
        patch("app.routers.raf_central.cache_delete_pattern"),
    ):
        resp = client.post(
            "/api/raf-central/1/actions/order-lab",
            headers=admin_headers,
            json={
                "hcc_code": "37",
                "icd10": "E11.9",
                "suggested_lab_code": "2857-1",
                "suggested_lab_name": "PSA",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["suggested_lab_code"] == "2857-1"
        _, kwargs = push.call_args
        assert kwargs["procedure_code"] == "2857-1"
        assert kwargs["procedure_name"] == "PSA"


def test_order_lab_returns_skipped_when_no_emr(client, admin_headers):
    """push_procedure_order→None + no EMR configured must yield 200/skipped,
    not 500 — explicit spec constraint."""
    from app.db import NoActiveEMRConnection

    class _RaisingCM:
        def __enter__(self):
            raise NoActiveEMRConnection("no active connection")

        def __exit__(self, *args):
            return False

    with (
        patch(
            "app.routers.raf_central.push_procedure_order",
            return_value=None,
        ),
        patch(
            "app.routers.raf_central.openemr_cursor",
            return_value=_RaisingCM(),
        ),
        patch("app.routers.raf_central._log_raf_action"),
        patch("app.routers.raf_central.cache_delete_pattern"),
    ):
        resp = client.post(
            "/api/raf-central/1/actions/order-lab",
            headers=admin_headers,
            json={"hcc_code": "37", "icd10": "E11.9"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "skipped"
        assert "no emr" in (body.get("reason") or "").lower()
        assert body["suggested_lab_code"] == "4548-4"


def test_order_lab_rejects_unmapped_hcc_without_suggestion(client, admin_headers):
    """Unknown HCC + no explicit suggested_lab_code → 400 (not a silent pick)."""
    with (
        patch("app.routers.raf_central.push_procedure_order") as push,
        patch("app.routers.raf_central._log_raf_action"),
        patch("app.routers.raf_central.cache_delete_pattern"),
    ):
        resp = client.post(
            "/api/raf-central/1/actions/order-lab",
            headers=admin_headers,
            json={"hcc_code": "9999", "icd10": "Z99.9"},
        )
        assert resp.status_code == 400
        assert "default lab mapping" in resp.json()["detail"].lower()
        push.assert_not_called()


# ---------------------------------------------------------------------------
# /actions/refresh-meat
# ---------------------------------------------------------------------------


def test_refresh_meat_happy_path(client, admin_headers):
    """POST refresh-meat should enqueue a Celery task and return 202/queued."""
    from unittest.mock import MagicMock

    fake_task = MagicMock()
    fake_task.id = "celery-task-uuid-1234"

    with patch(
        "app.routers.raf_central.task_refresh_meat_for_patient"
    ) as mock_task_cls:
        mock_task_cls.apply_async.return_value = fake_task
        resp = client.post(
            "/api/raf-central/1/actions/refresh-meat",
            headers=admin_headers,
            json={"max_days_lookback": 180},
        )

    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["status"] == "queued"
    assert body["job_id"] == "celery-task-uuid-1234"
    mock_task_cls.apply_async.assert_called_once()
    call_kwargs = mock_task_cls.apply_async.call_args.kwargs["kwargs"]
    assert call_kwargs["max_days_lookback"] == 180
    assert call_kwargs["patient_id"] == 1


def test_refresh_meat_requires_auth(client):
    """Missing bearer token should 401 before the task is enqueued."""
    from unittest.mock import MagicMock

    with patch(
        "app.routers.raf_central.task_refresh_meat_for_patient"
    ) as mock_task_cls:
        mock_task_cls.apply_async.return_value = MagicMock(id="x")
        resp = client.post("/api/raf-central/1/actions/refresh-meat", json={})
    assert resp.status_code in (401, 403)
    mock_task_cls.apply_async.assert_not_called()


def test_refresh_meat_500_on_enqueue_error(client, admin_headers):
    """apply_async raising must surface as 500."""
    with patch(
        "app.routers.raf_central.task_refresh_meat_for_patient"
    ) as mock_task_cls:
        mock_task_cls.apply_async.side_effect = RuntimeError("redis down")
        resp = client.post(
            "/api/raf-central/1/actions/refresh-meat",
            headers=admin_headers,
            json={},
        )
    assert resp.status_code == 500
    assert "enqueue" in resp.json()["detail"].lower()
