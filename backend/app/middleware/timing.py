"""
Request timing and API versioning middleware.

Provides:
- add_process_time_header — adds X-Process-Time-Ms, increments request counter
- add_api_version_header  — adds X-API-Version + optional deprecation headers
- APIVersionRewriteMiddleware — rewrites /api/v1/<path> to /api/<path>
"""
import logging
import os
import time
from datetime import datetime

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

# Map path prefixes to ISO-8601 sunset dates.
# Populate when a v1 endpoint is superseded by v2.
_DEPRECATED_V1_PATHS: dict[str, str] = {
    # Example (uncomment when v2 lands):
    # "/api/v1/patients": "2028-01-01",
}


async def add_process_time_header(request: Request, call_next):
    """FastAPI @app.middleware('http') handler for per-request timing."""
    start = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - start) * 1000
    if os.getenv("APP_ENV", "production") != "production":
        response.headers["X-Process-Time-Ms"] = f"{elapsed_ms:.1f}"
    logger.debug("%s %s  %.1f ms", request.method, request.url.path, elapsed_ms)
    try:
        request.app.state.request_count = (
            getattr(request.app.state, "request_count", 0) + 1
        )
    except Exception:
        pass
    return response


async def add_api_version_header(request: Request, call_next):
    """
    Attach API versioning and optional deprecation headers to every response.

    - X-API-Version:  Always set to the current stable API version.
    - Deprecation:    Set to 'true' when the requested path is sunset-scheduled.
    - Sunset:         RFC 7231 formatted datetime when the endpoint will be removed.
    - Link:           Pointer to the successor resource in the next API version.
    """
    response = await call_next(request)
    response.headers["X-API-Version"] = "v1"

    path = request.url.path
    for deprecated_prefix, sunset_iso in _DEPRECATED_V1_PATHS.items():
        if path == deprecated_prefix or path.startswith(deprecated_prefix + "/"):
            sunset_dt = datetime.fromisoformat(sunset_iso)
            response.headers["Deprecation"] = "true"
            response.headers["Sunset"] = sunset_dt.strftime("%a, %d %b %Y %H:%M:%S GMT")
            successor = path.replace("/api/v1/", "/api/v2/", 1).replace("/api/", "/api/v2/", 1)
            response.headers["Link"] = f'<{successor}>; rel="successor-version"'
            break

    return response


class APIVersionRewriteMiddleware(BaseHTTPMiddleware):
    """
    Transparently rewrite ``/api/v1/<path>`` to ``/api/<path>``.

    This makes the versioned URL scheme functional without requiring changes
    to the 40+ existing router files. All routes registered under ``/api/``
    become available at both ``/api/`` and ``/api/v1/``.
    """

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path.startswith("/api/v1/"):
            new_path = "/api/" + path[len("/api/v1/"):]
            scope = request.scope
            scope["path"] = new_path
            scope["raw_path"] = new_path.encode("utf-8")
            request = Request(scope, request.receive, request._send)  # type: ignore[arg-type]
        return await call_next(request)
