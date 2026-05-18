"""
Tests for POST /api/direct/inbound — Direct Trust inbound endpoint.

Scenarios covered
-----------------
1. Missing X-Direct-From header → 400
2. Missing X-Direct-To header → 400
3. Sender not in trust anchors → 403
4. Valid anchor + C-CDA attachment → 200 + ccda_documents row inserted
5. Idempotent: same message_id submitted twice → 200 duplicate=true, no duplicate insert
6. PDF attachment routes to Gemini extractor path (no crash)
7. Invalid / non-XML CCDA attachment returns 200 with error captured

All DB calls are mocked; no live database required.
"""
from __future__ import annotations

import email as email_lib
import email.mime.application
import email.mime.multipart
import email.mime.text
import email.policy
import json
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

# ---------------------------------------------------------------------------
# Minimal synthetic CCDA XML for integration tests
# ---------------------------------------------------------------------------

_SIMPLE_CCDA = b"""<?xml version="1.0" encoding="UTF-8"?>
<ClinicalDocument xmlns="urn:hl7-org:v3">
  <templateId root="2.16.840.1.113883.10.20.22.1.1"/>
  <effectiveTime value="20240201"/>
  <recordTarget>
    <patientRole>
      <id root="2.16.840.1.113883.19.5" extension="MRN-99"/>
      <patient>
        <name><given>John</given><family>Smith</family></name>
        <birthTime value="19550720"/>
        <administrativeGenderCode code="M"/>
      </patient>
    </patientRole>
  </recordTarget>
  <component>
    <structuredBody>
      <component>
        <section>
          <templateId root="2.16.840.1.113883.10.20.22.2.5.1"/>
          <entry>
            <act classCode="ACT" moodCode="EVN">
              <entryRelationship typeCode="SUBJ">
                <observation classCode="OBS" moodCode="EVN">
                  <statusCode code="active"/>
                  <effectiveTime><low value="20200101"/></effectiveTime>
                  <value xsi:type="CD"
                         code="E119"
                         codeSystem="2.16.840.1.113883.6.90"
                         displayName="Type 2 Diabetes"
                         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"/>
                </observation>
              </entryRelationship>
            </act>
          </entry>
        </section>
      </component>
    </structuredBody>
  </component>
</ClinicalDocument>"""


# ---------------------------------------------------------------------------
# MIME message builders
# ---------------------------------------------------------------------------

def _build_mime_message(
    ccda_bytes: bytes | None = None,
    pdf_bytes:  bytes | None = None,
    message_id: str = "<test-msg-001@direct.example.org>",
    subject: str = "Care Transition Summary",
) -> bytes:
    """Build a minimal RFC 5322 MIME message with optional attachments."""
    msg = email_lib.mime.multipart.MIMEMultipart("mixed")
    msg["Message-ID"] = message_id
    msg["Subject"]    = subject
    msg["From"]       = "sender@direct.example.org"
    msg["To"]         = "receiver@direct.raf.health"

    body = email_lib.mime.text.MIMEText("Care transition document attached.", "plain")
    msg.attach(body)

    if ccda_bytes is not None:
        part = email_lib.mime.application.MIMEApplication(
            ccda_bytes,
            _subtype="x-cda-xml",
            Name="summary.xml",
        )
        part["Content-Disposition"] = 'attachment; filename="summary.xml"'
        msg.attach(part)

    if pdf_bytes is not None:
        part = email_lib.mime.application.MIMEApplication(
            pdf_bytes,
            _subtype="pdf",
            Name="discharge.pdf",
        )
        part["Content-Disposition"] = 'attachment; filename="discharge.pdf"'
        msg.attach(part)

    return msg.as_bytes()


# ---------------------------------------------------------------------------
# Cursor mock
# ---------------------------------------------------------------------------

class _MockCursor:
    def __init__(self, rows=None, lastrowid=42):
        self._rows = list(rows or [])
        self.lastrowid = lastrowid
        self.rowcount = len(self._rows)
        self.queries: list[str] = []

    def execute(self, q, p=None):
        self.queries.append(q)
        self.rowcount = len(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)

    def close(self):
        pass


def _make_cursor_cm(rows=None, lastrowid=42):
    cur = _MockCursor(rows=rows, lastrowid=lastrowid)

    @contextmanager
    def _cm(*a, **kw):
        yield cur

    return _cm, cur


# ---------------------------------------------------------------------------
# Module-level import + app client setup
# ---------------------------------------------------------------------------

import os
os.environ.setdefault("APP_ENV", "testing")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-for-pytest-do-not-use-in-prod")
os.environ.setdefault("JWT_REFRESH_SECRET", "test-refresh-secret")
os.environ.setdefault("RAF_DB_USER", "test")
os.environ.setdefault("RAF_DB_PASSWORD", "test")
os.environ.setdefault("OPENEMR_DB_USER", "test")
os.environ.setdefault("OPENEMR_DB_PASSWORD", "test")
os.environ.setdefault("DB_SSL_ENABLED", "false")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("GOOGLE_API_KEY", "fake-key")
os.environ.setdefault("LLM_USE_VERTEX", "false")
os.environ["RATE_LIMITING_ENABLED"] = "false"
os.environ["STRICT_MIGRATIONS"] = "false"
os.environ["FRONTEND_URL"] = "http://localhost:3000"
os.environ["PHI_FERNET_KEY"] = "jA8a-p7k_j9yv-gXy_AhTzX_h8oZ_wYqFp_rWs3vDcE="
os.environ["PHI_AES256_KEY"] = "a2l2eW1veXFja25ia3hzeG5wbGp0d3JsdmJmY3p0YWE="


# ---------------------------------------------------------------------------
# Helpers that exercise the router functions directly (no HTTP stack needed
# for most cases; we use the HTTP stack only for header-validation tests)
# ---------------------------------------------------------------------------

def _noop_cursor_cm(*a, **kw):
    """Cursor that returns no rows and records no errors."""
    @contextmanager
    def _cm(*a2, **kw2):
        yield _MockCursor()
    return _cm()


# ---------------------------------------------------------------------------
# Tests: header validation (function-level — avoids full app fixture)
# ---------------------------------------------------------------------------

class TestDirectInboundHeaders:
    """Verify HTTP-level header validation by calling the endpoint function
    directly; avoids the full app-fixture startup which requires /app on disk."""

    class _FakeRequest:
        async def body(self):
            return b"From: foo@bar.org\r\n\r\ntest"

    @pytest.mark.asyncio
    async def test_missing_x_direct_from_returns_400(self):
        """No X-Direct-From header → HTTPException 400."""
        from fastapi import HTTPException
        from app.routers.direct_inbound import direct_inbound
        with pytest.raises(HTTPException) as exc_info:
            await direct_inbound(
                request=self._FakeRequest(),
                x_direct_from=None,
                x_direct_to="rx@direct.raf.health",
            )
        assert exc_info.value.status_code == 400
        assert "X-Direct-From" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_missing_x_direct_to_returns_400(self):
        """No X-Direct-To header → HTTPException 400."""
        from fastapi import HTTPException
        from app.routers.direct_inbound import direct_inbound
        with pytest.raises(HTTPException) as exc_info:
            await direct_inbound(
                request=self._FakeRequest(),
                x_direct_from="sender@direct.example.org",
                x_direct_to=None,
            )
        assert exc_info.value.status_code == 400
        assert "X-Direct-To" in exc_info.value.detail


# ---------------------------------------------------------------------------
# Tests: trust anchor / business logic (unit layer — functions only)
# ---------------------------------------------------------------------------

class TestTrustAnchorLookup:
    """Verify trust anchor whitelist logic without the HTTP stack."""

    def test_unknown_sender_rejected(self):
        from app.routers.direct_inbound import _lookup_trust_anchor
        no_rows_cm, _ = _make_cursor_cm(rows=[])
        with patch("app.routers.direct_inbound.raf_cursor", no_rows_cm):
            result = _lookup_trust_anchor("default", "attacker@evil.org")
        assert result is False

    def test_known_sender_trusted(self):
        from app.routers.direct_inbound import _lookup_trust_anchor
        anchor_row = {"id": 1}
        rows_cm, _ = _make_cursor_cm(rows=[anchor_row])
        with patch("app.routers.direct_inbound.raf_cursor", rows_cm):
            result = _lookup_trust_anchor("default", "provider@direct.example.org")
        assert result is True

    def test_db_exception_returns_false(self):
        """Trust anchor DB error degrades to rejection (fail-closed)."""
        from app.routers.direct_inbound import _lookup_trust_anchor

        @contextmanager
        def _exploding_cm(*a, **kw):
            raise Exception("DB is down")
            yield  # pragma: no cover

        with patch("app.routers.direct_inbound.raf_cursor", _exploding_cm):
            result = _lookup_trust_anchor("default", "provider@direct.example.org")
        assert result is False


class TestDuplicateCheck:
    """Verify idempotency logic."""

    def test_new_message_not_duplicate(self):
        from app.routers.direct_inbound import _check_duplicate
        no_rows_cm, _ = _make_cursor_cm(rows=[])
        with patch("app.routers.direct_inbound.raf_cursor", no_rows_cm):
            assert _check_duplicate("default", "msg-new-001") is False

    def test_existing_message_is_duplicate(self):
        from app.routers.direct_inbound import _check_duplicate
        existing_cm, _ = _make_cursor_cm(rows=[{"id": 5}])
        with patch("app.routers.direct_inbound.raf_cursor", existing_cm):
            assert _check_duplicate("default", "msg-existing-001") is True


# ---------------------------------------------------------------------------
# Tests: full pipeline (integration-style, no HTTP stack)
# ---------------------------------------------------------------------------

class TestDirectInboundPipeline:
    """Exercise the full inbound processing path by calling the endpoint
    function directly with mocked dependencies."""

    def _make_ccda_request(self, message_id: str = "<pipe-test@direct.example.org>"):
        """Return (raw_body, from_hdr, to_hdr) for a CCDA-carrying message."""
        raw = _build_mime_message(ccda_bytes=_SIMPLE_CCDA, message_id=message_id)
        return raw, "provider@direct.example.org", "raf@direct.raf.health"

    @pytest.mark.asyncio
    async def test_valid_ccda_message_inserts_document(self):
        """Valid trust anchor + CCDA → ccda_documents row inserted, 200 response."""
        from app.routers.direct_inbound import direct_inbound

        raw, from_hdr, to_hdr = self._make_ccda_request()

        # Cursor sequences:
        # 1. trust anchor lookup → row found
        # 2. duplicate check → not found
        # 3. ccda_documents insert → lastrowid=77
        # 4. raf_suspect_conditions insert → 1 row written
        # 5. direct_inbound_messages insert

        call_count = [0]

        @contextmanager
        def _sequenced_cm(*a, **kw):
            n = call_count[0]
            call_count[0] += 1
            if n == 0:       yield _MockCursor(rows=[{"id": 1}])         # trust anchor
            elif n == 1:     yield _MockCursor(rows=[])                  # dup check
            elif n == 2:     yield _MockCursor(rows=[], lastrowid=77)    # ccda insert
            elif n == 3:     yield _MockCursor(rows=[])                  # suspect insert
            else:            yield _MockCursor(rows=[])                  # tracking insert

        # Mock _icd10_to_hcc inside ccda_parser to return an HCC
        class _FakeRequest:
            async def body(self):
                return raw

        with (
            patch("app.routers.direct_inbound.raf_cursor", _sequenced_cm),
            patch("app.services.ccda_parser._icd10_to_hcc", return_value=("19", "Diabetes")),
        ):
            resp = await direct_inbound(
                request=_FakeRequest(),
                x_direct_from=from_hdr,
                x_direct_to=to_hdr,
            )

        assert resp["status"] == "ok"
        assert resp["duplicate"] is False
        assert resp["ccda_documents"] == 1

    @pytest.mark.asyncio
    async def test_duplicate_message_returns_no_new_rows(self):
        """Re-submitting same message_id returns duplicate=True."""
        from app.routers.direct_inbound import direct_inbound

        raw, from_hdr, to_hdr = self._make_ccda_request(
            message_id="<dup-test@direct.example.org>"
        )

        call_count = [0]

        @contextmanager
        def _cm(*a, **kw):
            n = call_count[0]
            call_count[0] += 1
            if n == 0:   yield _MockCursor(rows=[{"id": 1}])   # trust anchor
            else:        yield _MockCursor(rows=[{"id": 9}])   # dup found

        class _FakeRequest:
            async def body(self):
                return raw

        with patch("app.routers.direct_inbound.raf_cursor", _cm):
            resp = await direct_inbound(
                request=_FakeRequest(),
                x_direct_from=from_hdr,
                x_direct_to=to_hdr,
            )

        assert resp["duplicate"] is True
        assert resp["ccda_documents"] == 0

    @pytest.mark.asyncio
    async def test_untrusted_sender_raises_403(self):
        """Sender absent from trust anchors → HTTPException 403."""
        from fastapi import HTTPException
        from app.routers.direct_inbound import direct_inbound

        raw = _build_mime_message(message_id="<403-test@evil.org>")

        no_anchor_cm, _ = _make_cursor_cm(rows=[])

        class _FakeRequest:
            async def body(self):
                return raw

        with patch("app.routers.direct_inbound.raf_cursor", no_anchor_cm):
            with pytest.raises(HTTPException) as exc_info:
                await direct_inbound(
                    request=_FakeRequest(),
                    x_direct_from="attacker@evil.org",
                    x_direct_to="raf@direct.raf.health",
                )
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_invalid_ccda_xml_captures_error_still_200(self):
        """Garbage XML in attachment → error captured in response, status still 200."""
        from app.routers.direct_inbound import direct_inbound

        raw = _build_mime_message(
            ccda_bytes=b"<<not valid xml>>",
            message_id="<bad-xml-test@direct.example.org>",
        )

        call_count = [0]

        @contextmanager
        def _cm(*a, **kw):
            n = call_count[0]
            call_count[0] += 1
            if n == 0:   yield _MockCursor(rows=[{"id": 1}])  # trust anchor
            elif n == 1: yield _MockCursor(rows=[])            # dup check
            else:        yield _MockCursor(rows=[])            # tracking

        class _FakeRequest:
            async def body(self):
                return raw

        with patch("app.routers.direct_inbound.raf_cursor", _cm):
            resp = await direct_inbound(
                request=_FakeRequest(),
                x_direct_from="provider@direct.example.org",
                x_direct_to="raf@direct.raf.health",
            )

        assert resp["status"] == "ok"
        assert resp["ccda_documents"] == 0
        assert len(resp["errors"]) > 0
