"""Tests for the provider scorecard PDF service and endpoint.

Covers:
  * ``generate_provider_pdf`` returns real PDF bytes containing the
    provider name, year, KPIs, and the watermark footer.
  * ``GET /api/providers/{id}/report.pdf`` returns 200 + application/pdf
    for an authorized caller, with a sane Content-Disposition filename.
  * Unknown provider id returns 404 (no PDF body).
  * Unauthenticated callers get 401/403 — never a PDF.

WeasyPrint is stubbed in each test that exercises rendering so CI does not
need the GObject/Pango/Cairo native stack — same pattern as
``test_radv_packet.py``.
"""

from __future__ import annotations

import sys
import types
from unittest.mock import patch

import pytest

from tests.conftest import MOCK_ADMIN_USER, _make_access_token


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


PROVIDER_ROW = {
    "id": 42,
    "openemr_user_id": 7,
    "npi": "1234567890",
    "first_name": "Jane",
    "last_name": "Provider",
    "credential": "MD",
    "specialty": "Internal Medicine",
    "specialty_category": "pcp",
    "practice_name": "RAF Clinic North",
    "email": "jane@raf.health",
    "phone": "555-1234",
    "status": "active",
    "created_at": "2026-01-01",
    "updated_at": "2026-04-01",
}

SCORECARD = {
    "provider_id": 42,
    "provider_name": "Jane Provider",
    "measurement_year": 2026,
    "total_patients": 220,
    "patients_with_scores": 215,
    "average_raf": 1.273,
    "hcc_capture_rate": 0.78,
    "recapture_rate": 0.81,
    "suspects_open": 14,
    "suspects_accepted": 33,
    "suspects_dismissed": 4,
    "revenue_opportunity": 168000.0,
    "meat_completeness_avg": 0.74,
    "documentation_quality_score": 0.79,
    "percentile_rank": 82.0,
    "calculated_at": "2026-05-04T12:00:00+00:00",
    "cached": True,
}

HCC_PERFORMANCE = [
    {
        "hcc_code": "108",
        "hcc_label": "Vascular Disease",
        "coded_patients": 9,
        "open_suspects": 6,
        "possible_patients": 15,
        "capture_rate": 0.6,
        "missed_patients": 6,
        "revenue_impact": 72000.0,
    },
    {
        "hcc_code": "19",
        "hcc_label": "Diabetes Without Complications",
        "coded_patients": 25,
        "open_suspects": 4,
        "possible_patients": 29,
        "capture_rate": 0.86,
        "missed_patients": 4,
        "revenue_impact": 48000.0,
    },
    {
        "hcc_code": "85",
        "hcc_label": "Congestive Heart Failure",
        "coded_patients": 4,
        "open_suspects": 3,
        "possible_patients": 7,
        "capture_rate": 0.57,
        "missed_patients": 3,
        "revenue_impact": 36000.0,
    },
]


@pytest.fixture
def provider_pdf_mocks():
    """Patch the scorecard / provider lookups used by the PDF builder."""
    with (
        patch(
            "app.services.provider_pdf_report.logger"
        ),  # silence info logs in test output
        patch(
            "app.services.provider_service.get_provider",
            return_value=PROVIDER_ROW,
        ),
        patch(
            "app.services.provider_service.get_latest_scorecard",
            return_value=SCORECARD,
        ),
        patch(
            "app.services.provider_service.calculate_provider_scorecard",
            return_value=SCORECARD,
        ),
        patch(
            "app.services.provider_service.calculate_hcc_performance",
            return_value=HCC_PERFORMANCE,
        ),
    ):
        yield


@pytest.fixture
def weasyprint_stub():
    """Replace WeasyPrint with a tiny stub that emits %PDF-… + the HTML
    body inline so text-containment assertions still work.
    """
    mod = types.ModuleType("weasyprint")

    class _StubHTML:
        def __init__(self, string: str = "", **kwargs):
            self._string = string

        def write_pdf(self, stylesheets=None):  # noqa: ARG002
            body = self._string.encode("utf-8", errors="replace")
            return b"%PDF-1.4\n" + body + b"\n%%EOF\n"

    class _StubCSS:
        def __init__(self, filename: str | None = None, **kwargs):
            self.filename = filename

    mod.HTML = _StubHTML
    mod.CSS = _StubCSS

    sys.modules["weasyprint"] = mod
    try:
        yield mod
    finally:
        sys.modules.pop("weasyprint", None)


# ---------------------------------------------------------------------------
# Service-level smoke tests
# ---------------------------------------------------------------------------


def test_generate_provider_pdf_returns_pdf_bytes(provider_pdf_mocks, weasyprint_stub):
    """generate_provider_pdf returns bytes that start with '%PDF-'."""
    from app.services.provider_pdf_report import generate_provider_pdf

    pdf = generate_provider_pdf(provider_id=42, year=2026, tenant_id=1)

    assert isinstance(pdf, bytes)
    assert pdf.startswith(b"%PDF-")
    assert len(pdf) > 500


def test_generate_provider_pdf_contains_provider_and_year(
    provider_pdf_mocks, weasyprint_stub
):
    """Provider name, NPI, specialty, and year all show up in the rendered HTML."""
    from app.services.provider_pdf_report import generate_provider_pdf

    pdf = generate_provider_pdf(provider_id=42, year=2026, tenant_id=1)
    text = pdf.decode("utf-8", errors="replace")

    # Provider header
    assert "Jane Provider" in text
    assert "1234567890" in text  # NPI
    assert "Internal Medicine" in text
    assert "2026" in text  # year

    # KPIs (formatted values land verbatim in the HTML)
    assert "1.273" in text          # avg RAF
    assert "78%" in text            # capture rate
    assert "81%" in text            # recapture
    assert "74%" in text            # MEAT

    # Top HCC opportunities
    assert "HCC 108" in text
    assert "Vascular Disease" in text
    assert "$72,000" in text


def test_generate_provider_pdf_includes_watermark_footer(
    provider_pdf_mocks, weasyprint_stub
):
    """Footer watermark must appear in every generated report."""
    from app.services.provider_pdf_report import generate_provider_pdf

    pdf = generate_provider_pdf(provider_id=42, year=2026, tenant_id=1)
    text = pdf.decode("utf-8", errors="replace")

    assert "RAF Intelligence" in text
    assert "Generated" in text
    assert "Confidential" in text


def test_audit_risk_band_high_when_low_meat(provider_pdf_mocks, weasyprint_stub):
    """Sanity-check the audit-risk derivation: very low MEAT triggers HIGH band."""
    low_card = dict(SCORECARD, meat_completeness_avg=0.20, suspects_open=40)
    with (
        patch(
            "app.services.provider_service.get_latest_scorecard",
            return_value=low_card,
        ),
        patch(
            "app.services.provider_service.calculate_provider_scorecard",
            return_value=low_card,
        ),
    ):
        from app.services.provider_pdf_report import generate_provider_pdf

        pdf = generate_provider_pdf(provider_id=42, year=2026, tenant_id=1)
        text = pdf.decode("utf-8", errors="replace")
        assert "HIGH" in text


# ---------------------------------------------------------------------------
# HTTP endpoint contract tests
# ---------------------------------------------------------------------------


def _auth_as(user: dict):
    """Patch the auth layer to return *user* without DB lookups."""
    session_row = {"session_id": user["session_id"], "is_revoked": 0}
    return patch.multiple(
        "app.auth",
        get_user=lambda *a, **kw: user,
        validate_session=lambda *a, **kw: session_row,
    )


def _headers(user: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {_make_access_token(user)}"}


def test_endpoint_returns_pdf_for_authorized_user(
    client, provider_pdf_mocks, weasyprint_stub
):
    """GET /api/providers/{id}/report.pdf returns 200 application/pdf with a
    sane attachment filename."""
    user = dict(MOCK_ADMIN_USER)

    with (
        _auth_as(user),
        patch("app.services.auth_service.get_user", return_value=user),
        patch(
            "app.services.auth_service.validate_session",
            return_value={"session_id": user["session_id"], "is_revoked": 0},
        ),
        patch("app.services.auth_service._ensure_tables"),
        # Router-level provider lookup uses provider_service.get_provider
        patch(
            "app.routers.provider_pdf_report.get_provider",
            return_value=PROVIDER_ROW,
        ),
    ):
        resp = client.get(
            "/api/providers/42/report.pdf?year=2026",
            headers=_headers(user),
        )

    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("application/pdf")
    assert resp.content.startswith(b"%PDF-")

    cd = resp.headers.get("content-disposition", "")
    # filename is sanitized/lower-cased
    assert "provider-provider-2026.pdf" in cd


def test_endpoint_returns_404_for_unknown_provider(client):
    """Unknown provider id → 404, never a PDF."""
    user = dict(MOCK_ADMIN_USER)

    with (
        _auth_as(user),
        patch("app.services.auth_service.get_user", return_value=user),
        patch(
            "app.services.auth_service.validate_session",
            return_value={"session_id": user["session_id"], "is_revoked": 0},
        ),
        patch("app.services.auth_service._ensure_tables"),
        patch(
            "app.routers.provider_pdf_report.get_provider",
            return_value=None,
        ),
    ):
        resp = client.get(
            "/api/providers/9999/report.pdf?year=2026",
            headers=_headers(user),
        )

    assert resp.status_code == 404
    assert "application/pdf" not in resp.headers.get("content-type", "")


def test_endpoint_requires_auth(client):
    """Unauthenticated caller must never receive a PDF."""
    resp = client.get("/api/providers/42/report.pdf?year=2026")
    assert resp.status_code in (401, 403)
    assert "application/pdf" not in resp.headers.get("content-type", "")
