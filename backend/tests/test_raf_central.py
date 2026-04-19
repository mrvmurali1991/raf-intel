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
        patch(
            "app.routers.raf_central._fetch_meat_letters",
            return_value={},
        ),
        patch(
            "app.routers.raf_central._fetch_patient_hcc_id",
            return_value=42,
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
    ]:
        resp = client.post(path, json=body)
        assert resp.status_code == 401, f"{path} did not require auth"
