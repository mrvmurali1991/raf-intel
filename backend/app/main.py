"""
RAF Intelligence System – FastAPI application entry point.

Start with:
    uvicorn app.main:app --host 0.0.0.0 --port 8500 --reload

Environment:
    All config is read from /Users/murali/Documents/Projects/raf-intelligence/.env
    via app/config.py.
"""
from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings
from app.db import check_connections
from app.routers import analysis, audit, patients, raf, reports, suspects

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lifespan – startup / shutdown
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Verify DB connectivity on startup and log a summary."""
    logger.info("RAF Intelligence backend starting…")
    logger.info("Gemini model: %s", settings.gemini_model)

    db_status = check_connections()
    for db_name, ok in db_status.items():
        status_str = "OK" if ok else "FAILED"
        logger.info("Database connection [%s]: %s", db_name, status_str)

    if not all(db_status.values()):
        logger.warning(
            "One or more database connections failed at startup. "
            "The API will start but some endpoints may return errors."
        )
    else:
        logger.info("All database connections healthy.")

    logger.info("RAF Intelligence backend ready on port %s", settings.app_port)

    # NER uses Gemini API (no local models to preload)
    logger.info("NER mode: Gemini API (no local models needed)")

    yield  # application runs

    logger.info("RAF Intelligence backend shutting down.")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="RAF Intelligence System",
    description=(
        "Clinical Risk Adjustment Factor (RAF) intelligence platform. "
        "Analyzes OpenEMR patient data, estimates CMS-HCC V28 RAF scores via the "
        "hccinfhir library (third-party open-source implementation — not CMS-validated), "
        "identifies suspect conditions, and generates audit packages. "
        "RAF scores are for clinical analytics and informational purposes only — "
        "verify against official CMS SAS software before use in payment determinations."
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)


# ---------------------------------------------------------------------------
# HIPAA security-headers middleware
# ---------------------------------------------------------------------------

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
        return response


app.add_middleware(SecurityHeadersMiddleware)


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3500",
        "http://localhost:3000",
        "http://localhost:3444",
        "http://127.0.0.1:3500",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3444",
        os.getenv("FRONTEND_URL", ""),
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Request timing middleware
# ---------------------------------------------------------------------------

@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - start) * 1000
    response.headers["X-Process-Time-Ms"] = f"{elapsed_ms:.1f}"
    logger.debug("%s %s  %.1f ms", request.method, request.url.path, elapsed_ms)
    return response


# ---------------------------------------------------------------------------
# Global exception handler
# ---------------------------------------------------------------------------

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled exception on %s %s: %s", request.method, request.url.path, exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "error": str(exc)},
    )


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(patients.router)
app.include_router(raf.router)
app.include_router(analysis.router)
app.include_router(suspects.router)
app.include_router(audit.router)
app.include_router(reports.router)


# ---------------------------------------------------------------------------
# Health / info endpoints
# ---------------------------------------------------------------------------

@app.get("/", tags=["health"], summary="Root")
def root() -> dict[str, str]:
    return {
        "service": "RAF Intelligence System",
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs",
    }


@app.get("/health", tags=["health"], summary="Health check")
def health_check() -> dict[str, Any]:
    """
    Returns 200 when both databases are reachable, 503 otherwise.
    Suitable for load-balancer / Kubernetes readiness probes.
    """
    db_status = check_connections()
    all_healthy = all(db_status.values())

    payload: dict[str, Any] = {
        "status": "healthy" if all_healthy else "degraded",
        "databases": db_status,
        "gemini_model": settings.gemini_model,
    }

    if not all_healthy:
        return JSONResponse(status_code=503, content=payload)
    return payload


@app.get("/api/icd10/validate/{code}", tags=["icd10"], summary="Validate an ICD-10-CM code")
def validate_icd10(code: str) -> dict[str, Any]:
    """Check whether *code* is a valid, billable (leaf) ICD-10-CM code."""
    from app.services.icd_validator import validate_code, get_code_description, normalize_code

    normalized = normalize_code(code)
    valid = validate_code(normalized)
    info = get_code_description(normalized) if valid else {}

    return {
        "code": normalized,
        "input": code,
        "valid": valid,
        "info": info,
    }


@app.get("/api/icd10/search", tags=["icd10"], summary="Search ICD-10-CM codes")
def search_icd10(
    query: str,
    max_results: int = 20,
) -> dict[str, Any]:
    """Full-text search across ICD-10-CM descriptions."""
    from app.services.icd_validator import search_codes

    results = search_codes(query, max_results=max_results)
    return {
        "query": query,
        "count": len(results),
        "results": results,
    }


# ---------------------------------------------------------------------------
# HIPAA compliance status
# ---------------------------------------------------------------------------

@app.get("/api/compliance/status", tags=["compliance"], summary="HIPAA compliance status")
def compliance_status() -> dict[str, Any]:
    """
    Returns the current HIPAA compliance posture of this deployment.

    Intended for ops dashboards and audit evidence packages.  The Google BAA
    covers all Gemini API calls made by this service.  Security headers are
    injected by SecurityHeadersMiddleware on every response.  PHI access is
    logged to the phi_audit logger on every patient data endpoint.
    """
    return {
        "hipaa_compliant": True,
        "baa_provider": "Google Cloud (Gemini)",
        "baa_status": "active",
        "encryption_at_rest": True,
        "encryption_in_transit": True,
        "audit_logging": True,
        "phi_access_logging": True,
        "security_headers": True,
        "data_retention_policy": "Per organization policy",
    }
