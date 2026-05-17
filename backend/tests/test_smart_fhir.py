"""
Tests for the SMART on FHIR 2.0 + CDS Hooks 2.0 integration.

Covers:

- ``GET /smart/.well-known/smart-configuration`` returns a spec-conformant
  discovery document.
- ``GET /smart/launch`` renders an HTML page that performs the SMART launch
  hand-off in the browser.
- ``GET /smart/authorize`` issues an authorization code bound to a PKCE
  challenge and redirects to the client's redirect_uri.
- ``POST /smart/token`` verifies the code_verifier against the stored
  challenge (happy path and PKCE-mismatch failure path).
- ``GET /cds-services`` advertises both ``raf-suspects`` and
  ``hcc-suggestions-realtime``.
- ``POST /cds-services/hcc-suggestions-realtime`` returns CDS Hooks cards
  with a ``suggestions[].actions[].resource`` of resourceType=Condition.
"""
from __future__ import annotations

import base64
import hashlib
import os
import secrets
from contextlib import contextmanager
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _b64url_no_pad(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _make_pkce_pair() -> tuple[str, str]:
    verifier = _b64url_no_pad(secrets.token_bytes(32))
    challenge = _b64url_no_pad(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


# ---------------------------------------------------------------------------
# /smart/.well-known/smart-configuration
# ---------------------------------------------------------------------------


REQUIRED_DISCOVERY_KEYS = {
    "authorization_endpoint",
    "token_endpoint",
    "code_challenge_methods_supported",
    "grant_types_supported",
    "scopes_supported",
    "capabilities",
}


def test_smart_configuration_discovery_doc_is_valid(client):
    """Discovery doc must include every SMART 2.0 metadata field we promise."""
    r = client.get("/smart/.well-known/smart-configuration")
    assert r.status_code == 200, r.text
    body = r.json()

    missing = REQUIRED_DISCOVERY_KEYS - set(body.keys())
    assert not missing, f"discovery doc missing keys: {missing}"

    # Exact values mandated by the task spec.
    assert body["code_challenge_methods_supported"] == ["S256"]
    assert "authorization_code" in body["grant_types_supported"]
    assert "client_credentials" in body["grant_types_supported"]

    for required_scope in (
        "openid",
        "fhirUser",
        "launch",
        "launch/patient",
        "patient/Patient.read",
        "patient/Condition.read",
        "patient/Condition.write",
    ):
        assert required_scope in body["scopes_supported"], required_scope

    for required_capability in (
        "launch-ehr",
        "launch-standalone",
        "client-public",
        "client-confidential-symmetric",
        "sso-openid-connect",
        "context-banner",
        "context-style",
        "permission-patient",
    ):
        assert required_capability in body["capabilities"], required_capability


def test_smart_configuration_content_type_is_json(client):
    """RFC 8414 §3.2 requires application/json."""
    r = client.get("/smart/.well-known/smart-configuration")
    assert "application/json" in r.headers.get("content-type", "")


# ---------------------------------------------------------------------------
# /smart/launch HTML
# ---------------------------------------------------------------------------


def test_smart_launch_renders_html_with_pkce_redirect(client):
    """Launch page must hand back HTML that boots the PKCE+authorize hand-off."""
    r = client.get(
        "/smart/launch",
        params={"iss": "https://fhir.example.org", "launch": "abc123"},
    )
    assert r.status_code == 200, r.text
    assert "text/html" in r.headers.get("content-type", "")
    html = r.text
    # Sanity checks: page must reference PKCE + the iss the EHR passed in.
    assert "code_challenge" in html
    assert "S256" in html
    assert "https://fhir.example.org" in html


# ---------------------------------------------------------------------------
# /smart/authorize + /smart/token  (PKCE happy path & mismatch)
# ---------------------------------------------------------------------------


def _do_authorize(client, code_challenge: str):
    r = client.get(
        "/smart/authorize",
        params={
            "response_type": "code",
            "client_id": "raf-test-client",
            "redirect_uri": "https://example.test/cb",
            "scope": "openid fhirUser launch patient/Patient.read",
            "state": "xyz-state-001",
            "aud": "https://fhir.example.org",
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        },
        follow_redirects=False,
    )
    return r


def test_authorize_returns_302_with_code_and_state(client):
    _verifier, challenge = _make_pkce_pair()
    r = _do_authorize(client, challenge)
    assert r.status_code == 302, r.text
    loc = r.headers["location"]
    assert loc.startswith("https://example.test/cb?")
    assert "code=" in loc
    assert "state=xyz-state-001" in loc


def test_authorize_rejects_non_s256_challenge(client):
    r = client.get(
        "/smart/authorize",
        params={
            "response_type": "code",
            "client_id": "raf-test-client",
            "redirect_uri": "https://example.test/cb",
            "scope": "openid",
            "state": "z",
            "code_challenge": "anything",
            "code_challenge_method": "plain",
        },
        follow_redirects=False,
    )
    assert r.status_code == 400


def _extract_code(location: str) -> str:
    # location = "https://.../cb?code=<...>&state=..."
    qs = location.split("?", 1)[1]
    for pair in qs.split("&"):
        if pair.startswith("code="):
            return pair[len("code=") :]
    raise AssertionError(f"no code in {location!r}")


def test_token_happy_path_verifies_pkce_and_issues_bearer(client):
    verifier, challenge = _make_pkce_pair()
    auth = _do_authorize(client, challenge)
    code = _extract_code(auth.headers["location"])

    tok = client.post(
        "/smart/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": "https://example.test/cb",
            "client_id": "raf-test-client",
            "code_verifier": verifier,
        },
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert tok.status_code == 200, tok.text
    body = tok.json()
    assert body["token_type"] == "Bearer"
    assert body["expires_in"] == 3600
    assert body["access_token"]


def test_token_rejects_wrong_pkce_verifier(client):
    _verifier, challenge = _make_pkce_pair()
    auth = _do_authorize(client, challenge)
    code = _extract_code(auth.headers["location"])

    tok = client.post(
        "/smart/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": "https://example.test/cb",
            "client_id": "raf-test-client",
            "code_verifier": "not-the-real-verifier",
        },
    )
    assert tok.status_code == 400
    assert "PKCE" in tok.json().get("detail", "")


def test_token_authorization_code_is_single_use(client):
    verifier, challenge = _make_pkce_pair()
    auth = _do_authorize(client, challenge)
    code = _extract_code(auth.headers["location"])

    form = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": "https://example.test/cb",
        "client_id": "raf-test-client",
        "code_verifier": verifier,
    }
    first = client.post("/smart/token", data=form)
    assert first.status_code == 200, first.text
    second = client.post("/smart/token", data=form)
    assert second.status_code == 400


def test_token_client_credentials_grant_issues_bearer(client):
    r = client.post(
        "/smart/token",
        data={
            "grant_type": "client_credentials",
            "client_id": "raf-backend",
            "scope": "system/Condition.write",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["token_type"] == "Bearer"
    assert body["scope"] == "system/Condition.write"


# ---------------------------------------------------------------------------
# CDS Hooks discovery + hcc-suggestions-realtime
# ---------------------------------------------------------------------------


def test_cds_services_lists_both_services(client):
    r = client.get("/cds-services")
    assert r.status_code == 200, r.text
    body = r.json()
    ids = {svc["id"] for svc in body.get("services", [])}
    assert "raf-suspects" in ids
    assert "hcc-suggestions-realtime" in ids


@pytest.fixture()
def _cds_hooks_secret(monkeypatch):
    secret = "test-cds-shared-secret"
    monkeypatch.setenv("CDS_HOOKS_SHARED_SECRET", secret)
    return secret


@contextmanager
def _mock_suspects_for_pid(rows: list[dict]):
    """Patch the cds_hooks module's DB helpers so the route returns rows
    without hitting MySQL."""
    with (
        patch(
            "app.routers.cds_hooks._resolve_internal_pid", return_value=3
        ),
        patch("app.routers.cds_hooks._patient_exists", return_value=True),
        patch(
            "app.routers.cds_hooks._fetch_open_suspects", return_value=rows
        ),
        patch("app.routers.cds_hooks._emit_audit"),
    ):
        yield


def test_hcc_suggestions_realtime_returns_condition_resources(
    client, _cds_hooks_secret
):
    fake_suspects = [
        {
            "id": 1,
            "suspect_hcc": 138,
            "suspect_icd10": "J44.9",
            "evidence_type": "rule",
            "confidence_score": 0.92,
        },
        {
            "id": 2,
            "suspect_hcc": 19,
            "suspect_icd10": "E11.9",
            "evidence_type": "rule",
            "confidence_score": 0.88,
        },
    ]
    with _mock_suspects_for_pid(fake_suspects):
        r = client.post(
            "/cds-services/hcc-suggestions-realtime",
            json={
                "hook": "patient-view",
                "hookInstance": "test-instance-001",
                "context": {"patientId": "3"},
            },
            headers={"authorization": f"Bearer {_cds_hooks_secret}"},
        )
    assert r.status_code == 200, r.text
    cards = r.json().get("cards", [])
    assert len(cards) == 2

    first = cards[0]
    assert first["indicator"] == "info"
    suggestions = first.get("suggestions") or []
    assert len(suggestions) == 1
    actions = suggestions[0].get("actions") or []
    assert len(actions) == 1
    resource = actions[0].get("resource") or {}
    assert resource.get("resourceType") == "Condition"

    codings = resource.get("code", {}).get("coding", [])
    assert any(
        c.get("system") == "http://hl7.org/fhir/sid/icd-10-cm"
        and c.get("code") == "J44.9"
        for c in codings
    )
    # subject must reference the patient by FHIR ID
    assert resource.get("subject", {}).get("reference") == "Patient/3"
    # clinicalStatus is required by US Core Condition profile
    assert resource.get("clinicalStatus")


def test_hcc_suggestions_realtime_requires_bearer(client, _cds_hooks_secret):
    with _mock_suspects_for_pid([]):
        r = client.post(
            "/cds-services/hcc-suggestions-realtime",
            json={
                "hook": "patient-view",
                "hookInstance": "x",
                "context": {"patientId": "3"},
            },
        )
    assert r.status_code == 401


def test_hcc_suggestions_realtime_503_when_secret_unset(client, monkeypatch):
    monkeypatch.delenv("CDS_HOOKS_SHARED_SECRET", raising=False)
    r = client.post(
        "/cds-services/hcc-suggestions-realtime",
        json={
            "hook": "patient-view",
            "hookInstance": "x",
            "context": {"patientId": "3"},
        },
        headers={"authorization": "Bearer anything"},
    )
    assert r.status_code == 503
