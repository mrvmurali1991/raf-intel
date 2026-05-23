"""Unit tests for the SSRF allowlist helper (app.security.ssrf).

These tests run entirely in-process — no actual network requests are made.
socket.getaddrinfo is monkeypatched to control address resolution.
"""

from __future__ import annotations

import pytest


def _make_getaddrinfo(ip: str):
    """Return a mock getaddrinfo that always resolves to *ip*."""
    import socket

    def _fake(host, port, *args, **kwargs):
        if ":" in ip:
            family = socket.AF_INET6
            sockaddr = (ip, port or 0, 0, 0)
        else:
            family = socket.AF_INET
            sockaddr = (ip, port or 0)
        return [(family, socket.SOCK_STREAM, 0, "", sockaddr)]

    return _fake


# ---------------------------------------------------------------------------
# Test the SSRF helper directly
# ---------------------------------------------------------------------------

class TestAssertSafeOutboundUrl:
    def test_https_public_passes(self, monkeypatch) -> None:
        """Plain HTTPS to a public IP should be accepted."""
        from app.security import ssrf
        monkeypatch.setattr(
            "app.security.ssrf.socket.getaddrinfo",
            _make_getaddrinfo("93.184.216.34"),  # example.com
        )
        # Should not raise
        ssrf._assert_safe_outbound_url("https://example.com/fhir/r4")

    def test_localhost_rejected(self, monkeypatch) -> None:
        """localhost (127.0.0.1) must be rejected."""
        from app.security import ssrf
        monkeypatch.setattr(
            "app.security.ssrf.socket.getaddrinfo",
            _make_getaddrinfo("127.0.0.1"),
        )
        with pytest.raises(ValueError, match="non-public address"):
            ssrf._assert_safe_outbound_url("https://localhost:8080/api")

    def test_127_range_rejected(self, monkeypatch) -> None:
        """127.x.x.x loopback range must be rejected."""
        from app.security import ssrf
        monkeypatch.setattr(
            "app.security.ssrf.socket.getaddrinfo",
            _make_getaddrinfo("127.0.0.2"),
        )
        with pytest.raises(ValueError, match="non-public address"):
            ssrf._assert_safe_outbound_url("https://internal.local/token")

    def test_rfc1918_10_x_rejected(self, monkeypatch) -> None:
        """10.x.x.x RFC-1918 addresses must be rejected."""
        from app.security import ssrf
        monkeypatch.setattr(
            "app.security.ssrf.socket.getaddrinfo",
            _make_getaddrinfo("10.1.2.216"),
        )
        with pytest.raises(ValueError, match="non-public address"):
            ssrf._assert_safe_outbound_url("https://openemr.internal/oauth2")

    def test_rfc1918_192_168_rejected(self, monkeypatch) -> None:
        """192.168.x.x must be rejected."""
        from app.security import ssrf
        monkeypatch.setattr(
            "app.security.ssrf.socket.getaddrinfo",
            _make_getaddrinfo("192.168.1.1"),
        )
        with pytest.raises(ValueError, match="non-public address"):
            ssrf._assert_safe_outbound_url("https://192.168.1.1/fhir")

    def test_link_local_169_254_rejected(self, monkeypatch) -> None:
        """169.254.x.x link-local (AWS metadata) must be rejected."""
        from app.security import ssrf
        monkeypatch.setattr(
            "app.security.ssrf.socket.getaddrinfo",
            _make_getaddrinfo("169.254.169.254"),
        )
        with pytest.raises(ValueError, match="non-public address"):
            ssrf._assert_safe_outbound_url("https://169.254.169.254/latest/meta-data/")

    def test_file_scheme_rejected(self, monkeypatch) -> None:
        """file:// scheme must always be rejected."""
        from app.security import ssrf
        with pytest.raises(ValueError, match="scheme"):
            ssrf._assert_safe_outbound_url("file:///etc/passwd")

    def test_ftp_scheme_rejected(self, monkeypatch) -> None:
        """ftp:// scheme must always be rejected."""
        from app.security import ssrf
        with pytest.raises(ValueError, match="scheme"):
            ssrf._assert_safe_outbound_url("ftp://ftp.example.com/data")

    def test_http_rejected_in_production(self, monkeypatch) -> None:
        """http:// must be rejected when app_env != 'development'."""
        from app.config import settings
        from app.security import ssrf
        monkeypatch.setattr(
            "app.security.ssrf.socket.getaddrinfo",
            _make_getaddrinfo("93.184.216.34"),
        )
        monkeypatch.setattr(settings, "app_env", "production")
        with pytest.raises(ValueError, match="scheme"):
            ssrf._assert_safe_outbound_url("http://example.com/fhir")

    def test_http_allowed_in_development(self, monkeypatch) -> None:
        """http:// must be accepted when app_env == 'development'."""
        from app.config import settings
        from app.security import ssrf
        monkeypatch.setattr(
            "app.security.ssrf.socket.getaddrinfo",
            _make_getaddrinfo("93.184.216.34"),
        )
        monkeypatch.setattr(settings, "app_env", "development")
        # Should not raise
        ssrf._assert_safe_outbound_url("http://example.com/fhir")

    def test_ipv6_loopback_rejected(self, monkeypatch) -> None:
        """IPv6 loopback (::1) must be rejected."""
        from app.security import ssrf
        monkeypatch.setattr(
            "app.security.ssrf.socket.getaddrinfo",
            _make_getaddrinfo("::1"),
        )
        with pytest.raises(ValueError, match="non-public address"):
            ssrf._assert_safe_outbound_url("https://localhost/fhir")

    def test_empty_url_rejected(self, monkeypatch) -> None:
        """Empty URL must be rejected."""
        from app.security import ssrf
        with pytest.raises(ValueError, match="empty"):
            ssrf._assert_safe_outbound_url("")
