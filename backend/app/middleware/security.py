"""
Security headers middleware — HIPAA-aligned HTTP response headers.
"""
import os

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Attach HTTP security headers required for HIPAA-aligned deployments.

    Headers enforce:
    - No MIME sniffing (X-Content-Type-Options)
    - No iframe embedding (X-Frame-Options)
    - HTTPS-only for 1 year (Strict-Transport-Security)
    - No caching of PHI responses (Cache-Control / Pragma)
    - Reduced referrer leakage (Referrer-Policy)
    - Camera / mic / geolocation disabled (Permissions-Policy)
    """

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        # X-XSS-Protection deliberately omitted: the header is obsolete and
        # modern browsers ignore it (or, worse, the legacy filter has been a
        # source of side-channel bugs). CSP above handles XSS defence.
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=()"
        )
        # Content-Security-Policy: restrict resource loading to same-origin.
        # static.cloudflareinsights.com is allowlisted because Cloudflare's
        # edge auto-injects the Web Analytics beacon on proxied sites. The
        # cleaner long-term fix is to disable CF Web Analytics for this
        # hostname (HIPAA-aligned: no third-party tracker touches PHI pages),
        # but the allowlist keeps the console quiet in the meantime.
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' https://static.cloudflareinsights.com; "
            "style-src 'self'; "
            "img-src 'self' data: blob:; "
            "font-src 'self'; "
            f"connect-src 'self' {os.environ.get('FRONTEND_URL', '')} {os.environ.get('NEXT_PUBLIC_API_URL', '')} https://cloudflareinsights.com; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'"
        )
        return response
