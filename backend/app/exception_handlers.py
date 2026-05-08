"""
Global exception handlers for RAF Intelligence FastAPI application.

Registered on the app in main.py via ``register_exception_handlers(app)``.
Handlers never leak internal stack traces or implementation details to clients.

NOTE: FastAPI exception handlers run inside the ASGI app but *outside* the
middleware chain, so responses they produce do NOT pass through
CORSMiddleware.  To prevent CORS errors in the browser when a 500 occurs on
a cross-origin request, ``_cors_headers_for_request`` injects the
Access-Control-Allow-Origin header directly into every error response.
"""
import logging
import os

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.db import NoActiveEMRConnection
from app.monitoring import capture_error
from app.rate_limit import limiter

logger = logging.getLogger(__name__)

# Mirrors the dev-safe localhost origins list from app/middleware/__init__.py.
# We replicate the small constant here rather than importing it to avoid a
# circular-import (middleware imports FastAPI; exception_handlers is imported
# by main.py before middleware is set up).
_DEV_ORIGINS = {
    "http://localhost:3500",
    "http://localhost:3000",
    "http://localhost:3001",
    "http://localhost:3444",
    "http://localhost:3445",
    "http://127.0.0.1:3500",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:3001",
    "http://127.0.0.1:3444",
    "http://127.0.0.1:3445",
}


def _cors_headers_for_request(request: Request) -> dict[str, str]:
    """Return CORS headers to attach to error responses.

    Only emits headers when the incoming Origin is in the allowed list so we
    don't accidentally open CORS to arbitrary origins.
    """
    origin = request.headers.get("origin", "")
    if not origin:
        return {}
    frontend_url = os.getenv("FRONTEND_URL", "")
    allowed = _DEV_ORIGINS | ({frontend_url} if frontend_url else set())
    if origin not in allowed:
        return {}
    return {
        "access-control-allow-origin": origin,
        "access-control-allow-credentials": "true",
        "vary": "Origin",
    }


def register_exception_handlers(app: FastAPI) -> None:
    """Attach all exception handlers and the rate-limiter to *app*."""

    # Rate limiting (slowapi)
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    @app.exception_handler(RequestValidationError)
    async def _validation_error_handler(
        request: Request, exc: RequestValidationError
    ):
        logger.error(
            "Validation error on %s %s: %s",
            request.method,
            request.url.path,
            exc.errors(),
        )
        return JSONResponse(
            status_code=422,
            headers=_cors_headers_for_request(request),
            content={"detail": "Validation error. Check your request parameters."},
        )

    @app.exception_handler(NoActiveEMRConnection)
    async def no_emr_handler(request: Request, exc: NoActiveEMRConnection):
        """Return 503 when no EMR connection is configured or reachable."""
        return JSONResponse(
            status_code=503,
            headers={"Retry-After": "60", **_cors_headers_for_request(request)},
            content={
                "detail": (
                    "No active EMR connection configured. "
                    "Add a connection via the EMR Config page."
                ),
                "emr_connected": False,
            },
        )

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        request_id = getattr(request.state, "request_id", "unknown")
        logger.error(
            "Unhandled exception on %s %s [request_id=%s]",
            request.method,
            request.url.path,
            request_id,
            exc_info=True,
        )
        capture_error(
            exc,
            context={
                "method": request.method,
                "path": request.url.path,
                "request_id": request_id,
            },
        )
        return JSONResponse(
            status_code=500,
            headers=_cors_headers_for_request(request),
            content={
                "detail": "Internal server error",
                "request_id": request_id,
            },
        )
