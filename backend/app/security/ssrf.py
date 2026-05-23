"""SSRF protection helpers.

``_assert_safe_outbound_url`` must be called at every HTTP entry-point that
accepts admin/tenant-supplied URLs (FHIR base_url, OAuth2 token_url, etc.)
before any outbound network request is issued.

Rejection policy
----------------
The following are always rejected:
- Non-HTTPS schemes in non-development environments (http is allowed in dev).
- file://, ftp://, and any other non-HTTP scheme.
- Hostnames that resolve to RFC-1918 private addresses.
- Loopback (127.0.0.0/8, ::1).
- Link-local (169.254.0.0/16, fe80::/10).
- Unique-local IPv6 (fc00::/7).
- Multicast and reserved ranges.
- Anything ipaddress flags as is_private, is_loopback, is_link_local,
  is_multicast, or is_reserved.

In development (settings.app_env == "development") plain http:// URLs are
accepted so local OpenEMR / FHIR sandboxes can be configured without TLS.
"""

from __future__ import annotations

import ipaddress
import socket
import urllib.parse

from app.config import settings


def _assert_safe_outbound_url(url: str) -> None:
    """Validate that *url* is safe to use as an outbound HTTP destination.

    Parameters
    ----------
    url:
        The URL that will be used as the base for an outbound HTTP request.
        Must be a fully-qualified URL with a scheme and hostname.

    Raises
    ------
    ValueError
        With a human-readable reason when the URL is rejected.
    """
    if not url or not url.strip():
        raise ValueError("Refusing outbound request: URL is empty")

    try:
        parsed = urllib.parse.urlparse(url)
    except Exception as exc:
        raise ValueError(f"Refusing outbound request: unparseable URL — {exc}") from exc

    scheme = (parsed.scheme or "").lower()

    # ------------------------------------------------------------------
    # Scheme check
    # ------------------------------------------------------------------
    allowed_schemes = {"https"}
    if settings.app_env == "development":
        allowed_schemes.add("http")

    if scheme not in allowed_schemes:
        raise ValueError(
            f"Refusing outbound request to non-public address: "
            f"scheme '{scheme}' is not allowed (allowed: {sorted(allowed_schemes)})"
        )

    hostname = parsed.hostname
    if not hostname:
        raise ValueError("Refusing outbound request: URL has no hostname")

    # ------------------------------------------------------------------
    # Resolve and inspect all addresses returned for the hostname
    # ------------------------------------------------------------------
    try:
        addr_infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise ValueError(
            f"Refusing outbound request: cannot resolve hostname '{hostname}' — {exc}"
        ) from exc

    if not addr_infos:
        raise ValueError(
            f"Refusing outbound request: hostname '{hostname}' resolved to no addresses"
        )

    for _family, _type, _proto, _canonname, sockaddr in addr_infos:
        # sockaddr is (address, port) for IPv4; (address, port, flow, scope) for IPv6.
        raw_addr = sockaddr[0]
        try:
            addr = ipaddress.ip_address(raw_addr)
        except ValueError:
            # Shouldn't happen for results from getaddrinfo, but be safe.
            continue

        _reject_if_non_public(addr, hostname)


def _reject_if_non_public(addr: ipaddress.IPv4Address | ipaddress.IPv6Address, hostname: str) -> None:
    """Raise ValueError when *addr* is a non-public address."""
    reasons: list[str] = []

    if addr.is_loopback:
        reasons.append("loopback")
    if addr.is_private:
        reasons.append("private/RFC-1918")
    if addr.is_link_local:
        reasons.append("link-local")
    if addr.is_multicast:
        reasons.append("multicast")
    if addr.is_reserved:
        reasons.append("reserved")
    # IPv6-specific: unique-local (fc00::/7)
    if isinstance(addr, ipaddress.IPv6Address):
        if addr in ipaddress.ip_network("fc00::/7"):
            reasons.append("unique-local")

    if reasons:
        raise ValueError(
            f"Refusing outbound request to non-public address: "
            f"'{hostname}' resolves to {addr} ({', '.join(reasons)})"
        )
