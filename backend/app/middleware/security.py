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
    - Browser XSS filter (X-XSS-Protection)
    - HTTPS-only for 1 year (Strict-Transport-Security)
    - No caching of PHI responses (Cache-Control / Pragma)
    - Reduced referrer leakage (Referrer-Policy)
    - Camera / mic / geolocation disabled (Permissions-Policy)
    """

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
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
        # Nonce-based CSP for script-src/style-src replaces 'unsafe-inline'.
        # Each response gets a unique nonce that the frontend must include
        # in its inline <script> and <style> tags.
        _csp_nonce = os.urandom(16).hex()
        response.headers["Content-Security-Policy"] = (
            f"default-src 'self'; "
            f"script-src 'self' 'nonce-{_csp_nonce}'; "
            f"style-src 'self' 'nonce-{_csp_nonce}'; "
            f"img-src 'self' data: blob:; "
            f"font-src 'self'; "
            f"connect-src 'self' {os.environ.get('FRONTEND_URL', '')} {os.environ.get('NEXT_PUBLIC_API_URL', '')}; "
            f"frame-ancestors 'none'; "
            f"base-uri 'self'; "
            f"form-action 'self'"
        )
        return response
