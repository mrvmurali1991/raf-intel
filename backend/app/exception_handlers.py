"""
Global exception handlers for RAF Intelligence FastAPI application.

Registered on the app in main.py via ``register_exception_handlers(app)``.
Handlers never leak internal stack traces or implementation details to clients.
"""
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.db import NoActiveEMRConnection
from app.monitoring import capture_error
from app.rate_limit import limiter

logger = logging.getLogger(__name__)


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
            content={"detail": "Validation error. Check your request parameters."},
        )

    @app.exception_handler(NoActiveEMRConnection)
    async def no_emr_handler(request: Request, exc: NoActiveEMRConnection):
        """Return 503 when no EMR connection is configured or reachable."""
        return JSONResponse(
            status_code=503,
            headers={"Retry-After": "60"},
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
            content={
                "detail": "Internal server error",
                "request_id": request_id,
            },
        )
