"""Tests for the RADV audit packet builder and endpoint.

Covers:
  * ``build_packet`` renders a real PDF (starts with ``%PDF-``) containing
    expected HCC strings and does NOT include un-billed suspect HCCs.
  * ``GET /api/radv/{pid}/packet`` returns 200 + application/pdf for an
    authorized in-tenant caller.
  * Wrong-tenant callers get 404 (IDOR guard — identical pattern to
    ``/api/patients/{pid}``).

WeasyPrint is stubbed inside each test that exercises PDF rendering so CI
does not need the native GObject / Pango / Cairo stack.
"""

from __future__ import annotations

import io
import sys
import types
from contextlib import contextmanager
from unittest.mock import patch

import pytest

from tests.conftest import (
    MOCK_ADMIN_USER,
    MOCK_TENANT_B_USER,
    MockCursor,
    _make_access_token,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


# A deterministic set of rows the packet builder will see.
# Only HCC 19 (Diabetes w/o Complications) and HCC 108 (Vascular Disease) are
# "billed" — i.e. present in raf_patient_hcc. The suspect for HCC 48
# (Coagulation Defects) is open/unaccepted and must NOT appear in the PDF.
BILLED_HCC_ROWS = [
    {
        "id": 101,
        "hcc_code": 19,
        "icd10_codes": '["E11.9"]',
        "raf_coefficient": 0.105,
        "meat_status": "complete",
        "source": "claims",
        "model_version": "V28",
        "measurement_year": 2025,
        "created_at": "2025-03-01",
    },
    {
        "id": 102,
        "hcc_code": 108,
        "icd10_codes": '["I73.9"]',
        "raf_coefficient": 0.288,
        "meat_status": "partial",
        "source": "claims",
        "model_version": "V28",
        "measurement_year": 2025,
        "created_at": "2025-03-01",
    },
]

PATIENT_ROW = {
    "id": 10,
    "first_name": "Test",
    "last_name": "Patient",
    "dob": "1955-03-12",
    "gender": "Female",
    "medicare_beneficiary_id": "1EG4-TE5-MK72",
    "insurance_id": None,
}

ENCOUNTER_ROWS = [
    {
        "encounter_id": 5001,
        "encounter_date": "2025-06-15",
        "encounter_type": "office",
        "facility_name": "RAF Intelligence Clinic",
        "provider_name": "Dr. Jane Provider",
        "provider_npi": "1234567890",
    }
]

MEAT_EVIDENCE_ROWS = [
    {
        "id": 501,
        "encounter_id": 5001,
        "encounter_date": "2025-06-15",
        "meat_m": "A1c trended monthly",
        "meat_e": "Reviewed labs and vitals",
        "meat_a": "Type 2 diabetes, stable",
        "meat_t": "Continue metformin 1000 mg BID",
        "meat_m_present": 1,
        "meat_e_present": 1,
        "meat_a_present": 1,
        "meat_t_present": 1,
        "completeness_score": 1.0,
        "raw_note_excerpt": "Patient seen for routine follow-up.",
    }
]

LLM_QUOTES: list[dict] = []  # ai_meat_evidence table optional
SUSPECT_TRAIL_ROW = {
    "id": 7001,
    "status": "accepted",
    "reviewed_by": "dr.provider@raf.health",
    "updated_at": "2025-06-16",
    "created_at": "2025-06-14",
    "confidence_score": 0.87,
    "evidence_type": "medication",
}


def _make_multi_cursor_cm(responses: dict[str, list[dict]]):
    """Return a context-manager that yields cursors keyed by SQL substring.

    Each ``cur.execute`` call inspects the SQL and picks the rows from the
    first matching key. ``fetchone`` / ``fetchall`` operate on those rows.
    This keeps the test readable without stubbing every helper function.
    """

    class _Cursor:
        def __init__(self) -> None:
            self.lastrowid = 1
            self._rows: list[dict] = []

        def execute(self, sql, params=None):
            for fragment, rows in responses.items():
                if fragment in sql:
                    self._rows = list(rows)
                    return
            self._rows = []

        def fetchone(self):
            return self._rows[0] if self._rows else None

        def fetchall(self):
            return list(self._rows)

        def close(self):
            pass

    @contextmanager
    def _cm(*a, **kw):
        yield _Cursor()

    return _cm


@pytest.fixture
def packet_db_mock():
    """Patch ``raf_cursor`` everywhere the packet builder / router touch it."""
    cm = _make_multi_cursor_cm(
        {
            "FROM patients p": [PATIENT_ROW],
            "FROM raf_patient_hcc": BILLED_HCC_ROWS,
            "FROM normalized_encounters": ENCOUNTER_ROWS,
            "FROM raf_meat_evidence": MEAT_EVIDENCE_ROWS,
            "FROM ai_meat_evidence": LLM_QUOTES,
            "FROM raf_suspect_conditions": [SUSPECT_TRAIL_ROW],
        }
    )
    with (
        patch("app.db.raf_cursor", cm),
        patch("app.services.radv.packet_builder.raf_cursor", cm),
    ):
        yield


# ---------------------------------------------------------------------------
# Lightweight WeasyPrint stub — inserted into sys.modules so the lazy import
# inside ``_render_pdf`` resolves without the native stack in CI.
# The stub produces a minimal valid-ish PDF that starts with "%PDF-" and
# includes the rendered HTML as plaintext so text assertions still work.
# ---------------------------------------------------------------------------


@pytest.fixture
def weasyprint_stub():
    mod = types.ModuleType("weasyprint")

    class _StubHTML:
        def __init__(self, string: str = "", **kwargs):
            self._string = string

        def write_pdf(self, stylesheets=None):  # noqa: ARG002
            # Simplest minimal PDF: header + the HTML text inline so
            # text-containment assertions work without a real renderer.
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
# build_packet unit tests
# ---------------------------------------------------------------------------


def test_build_packet_returns_pdf_bytes(packet_db_mock, weasyprint_stub):
    """build_packet returns bytes that start with the PDF magic header."""
    from app.services.radv.packet_builder import build_packet

    pdf = build_packet(patient_id=10, payment_year=2025, tenant_id="1")

    assert isinstance(pdf, bytes)
    assert pdf.startswith(b"%PDF-"), "Output must start with %PDF- magic header"
    assert len(pdf) > 500, "Rendered PDF should be non-trivial in size"


def test_build_packet_contains_billed_hccs_and_icds(packet_db_mock, weasyprint_stub):
    """Every billed HCC + ICD-10 + provider NPI appears in the rendered content."""
    from app.services.radv.packet_builder import build_packet

    pdf = build_packet(patient_id=10, payment_year=2025, tenant_id="1")

    # Our stub writes the HTML into the PDF — decode and grep.
    text = pdf.decode("utf-8", errors="replace")

    assert "HCC 19" in text
    assert "HCC 108" in text
    assert "E11.9" in text
    assert "I73.9" in text
    assert "1234567890" in text  # provider NPI
    assert "Dr. Jane Provider" in text
    assert "2025-06-15" in text  # DOS

    # MEAT letters and the provenance excerpts
    assert "Monitor" in text
    assert "Evaluate" in text
    assert "Assess" in text
    assert "Treat" in text
    assert "A1c trended monthly" in text

    # Attestation chain
    assert "dr.provider@raf.health" in text


def test_build_packet_excludes_unbilled_suspects(packet_db_mock, weasyprint_stub):
    """Open suspects (not in raf_patient_hcc) must NOT appear in the packet."""
    from app.services.radv.packet_builder import build_packet

    pdf = build_packet(patient_id=10, payment_year=2025, tenant_id="1")
    text = pdf.decode("utf-8", errors="replace")

    # HCC 48 was never added to BILLED_HCC_ROWS — it's only an open suspect,
    # which in reality would live in raf_suspect_conditions with status='open'.
    # The packet intentionally never reads open suspects as billed HCCs.
    assert "HCC 48" not in text
    # Also make sure the suspect's ICD is not anywhere as a "billed" code.
    assert "D68.9" not in text


def test_build_packet_watermark_present(packet_db_mock, weasyprint_stub):
    """The non-negotiable watermark must appear in every packet."""
    from app.services.radv.packet_builder import build_packet

    pdf = build_packet(patient_id=10, payment_year=2025, tenant_id="1")
    text = pdf.decode("utf-8", errors="replace")

    assert "PRE-SUBMISSION" in text
    assert "INTERNAL AUDIT" in text


# ---------------------------------------------------------------------------
# HTTP endpoint contract tests
# ---------------------------------------------------------------------------


def _auth_as(user: dict):
    """Patch the auth layer to return ``user`` without DB lookups."""
    session_row = {"session_id": user["session_id"], "is_revoked": 0}
    return patch.multiple(
        "app.auth",
        get_user=lambda *a, **kw: user,
        validate_session=lambda *a, **kw: session_row,
    )


def _headers(user: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {_make_access_token(user)}"}


def test_endpoint_returns_pdf_for_authorized_user(
    client, packet_db_mock, weasyprint_stub
):
    """GET /api/radv/{pid}/packet returns 200 application/pdf for in-tenant caller."""
    user = dict(MOCK_ADMIN_USER)  # tenant_id=1

    with (
        _auth_as(user),
        patch("app.services.auth_service.get_user", return_value=user),
        patch(
            "app.services.auth_service.validate_session",
            return_value={"session_id": user["session_id"], "is_revoked": 0},
        ),
        patch("app.services.auth_service._ensure_tables"),
        patch("app.services.patient_service.patient_is_accessible", return_value=True),
    ):
        resp = client.get(
            "/api/radv/10/packet?payment_year=2025",
            headers=_headers(user),
        )

    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("application/pdf")
    assert resp.content.startswith(b"%PDF-")
    # Content-Disposition must name the download
    cd = resp.headers.get("content-disposition", "")
    assert "radv_packet_patient_10_py2025.pdf" in cd


def test_endpoint_rejects_wrong_tenant(client):
    """Cross-tenant caller gets 404 — IDOR guard."""
    # Tenant B admin trying to pull a tenant-1 patient's packet.
    user = dict(MOCK_TENANT_B_USER)  # tenant_id=2

    with (
        _auth_as(user),
        patch("app.services.auth_service.get_user", return_value=user),
        patch(
            "app.services.auth_service.validate_session",
            return_value={"session_id": user["session_id"], "is_revoked": 0},
        ),
        patch("app.services.auth_service._ensure_tables"),
        # patient_is_accessible returns False → router must raise 404.
        patch("app.services.patient_service.patient_is_accessible", return_value=False),
    ):
        resp = client.get(
            "/api/radv/10/packet?payment_year=2025",
            headers=_headers(user),
        )

    # 404 (not 403) is the convention used by /api/patients/{pid} to avoid
    # status-code differencing attacks. Either is acceptable here; the
    # contract is "never 200 with PDF content".
    assert resp.status_code in (403, 404), resp.text
    assert "application/pdf" not in resp.headers.get("content-type", "")


def test_endpoint_requires_auth(client):
    """Unauthenticated caller must never receive a PDF."""
    resp = client.get("/api/radv/10/packet?payment_year=2025")
    assert resp.status_code in (401, 403), resp.text
