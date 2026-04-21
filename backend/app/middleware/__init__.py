"""
Middleware package for RAF Intelligence.

Provides a single ``setup_middleware(app)`` entry point that registers all
middleware in the correct order.  Import this in main.py instead of
scattering individual add_middleware calls.

Middleware execution order (outermost to innermost — last added runs first):
  1. StructuredLoggingMiddleware   — captures access log after timing is known
  2. AuditLoggingMiddleware        — writes audit row per request
  3. RequestIDMiddleware           — injects X-Request-ID
  4. PHIAccessLoggingMiddleware    — PHI field-level access log
  5. AuditRequestContextMiddleware — populates audit context vars
  6. SecurityHeadersMiddleware     — HIPAA security response headers
  7. CORSMiddleware                — outermost for preflight

FastAPI's add_middleware stacks like a LIFO queue: the LAST middleware added
executes FIRST on the incoming request and LAST on the outgoing response.
"""
import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.audit_middleware import AuditRequestContextMiddleware
from app.config import settings
from app.middleware.request_logging import (
    AuditLoggingMiddleware,
    RequestIDMiddleware,
    StructuredLoggingMiddleware,
)
from app.middleware.security import SecurityHeadersMiddleware
from app.middleware.tenant_guard import TenantGuardMiddleware
from app.middleware.timing import (
    APIVersionRewriteMiddleware,
    add_api_version_header,
    add_process_time_header,
)
from app.phi_access_logger import PHIAccessLoggingMiddleware

logger = logging.getLogger(__name__)


def _build_cors_origins() -> list[str]:
    """Derive the CORS allowed-origins list from environment configuration."""
    frontend_url = os.getenv("FRONTEND_URL", "")

    if settings.app_env == "production":
        if not frontend_url:
            raise RuntimeError("FRONTEND_URL must be set in production")
        if frontend_url.startswith("http://"):
            raise RuntimeError("FRONTEND_URL must use https:// in production")

    origins: list[str] = []
    if settings.app_env in ("development", "testing"):
        origins = [
            "http://localhost:3500",
            "http://localhost:3000",
            "http://localhost:3001",
            "http://localhost:3444",
            "http://127.0.0.1:3500",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:3001",
            "http://127.0.0.1:3444",
        ]
    if frontend_url:
        origins.append(frontend_url)

    if not origins:
        logger.warning(
            "CORS allow_origins is empty — all cross-origin requests will be "
            "blocked. Set FRONTEND_URL."
        )
    return origins


def setup_middleware(app: FastAPI) -> list[str]:
    """
    Register all middleware on *app* and return the CORS origins list.

    The CORS origins are returned so that the EMR-gate middleware (defined
    inline in main.py because it closes over ``app``) can reuse them without
    re-computing the list.
    """
    cors_origins = _build_cors_origins()

    # Registration order is LIFO — last registered = outermost (runs first).
    # We add in outermost-last order so that reading top-to-bottom reflects
    # request-processing order.

    # Innermost: structured logging (needs request_id from RequestIDMiddleware)
    app.add_middleware(StructuredLoggingMiddleware)

    # Audit log — database write per request
    app.add_middleware(AuditLoggingMiddleware)

    # Request ID injection
    app.add_middleware(RequestIDMiddleware)

    # PHI access logging
    app.add_middleware(PHIAccessLoggingMiddleware)

    # Audit request context (populates context vars for downstream services)
    app.add_middleware(AuditRequestContextMiddleware)

    # Tenant isolation guard — rejects requests without valid tenant_id
    app.add_middleware(TenantGuardMiddleware)

    # HIPAA security headers
    app.add_middleware(SecurityHeadersMiddleware)

    # Timing + versioning — registered via @app.middleware("http") style
    app.middleware("http")(add_process_time_header)
    app.middleware("http")(add_api_version_header)

    # URL versioning rewrite: /api/v1/<path> -> /api/<path>
    app.add_middleware(APIVersionRewriteMiddleware)

    # CORS — must be outermost so preflight OPTIONS is handled before auth
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "Accept",
            "Origin",
            "X-Requested-With",
        ],
    )

    # Prometheus metrics middleware + /metrics endpoint
    try:
        from app.metrics import init_metrics
        init_metrics(app)
    except Exception as exc:
        logger.warning("Could not initialise Prometheus metrics: %s", exc)

    return cors_origins
