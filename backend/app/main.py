"""
RAF Intelligence System – FastAPI application entry point.

Development:
    uvicorn app.main:app --host 0.0.0.0 --port 8500 --reload

Production (via gunicorn):
    gunicorn app.main:app -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8500 --workers 4

Environment:
    All config is read from the project root .env file via app/config.py.
"""
# Note: do NOT use 'from __future__ import annotations' here —
# it breaks FastAPI/Pydantic schema generation (ForwardRef errors in /openapi.json).

import logging
import os
import subprocess
import time
import uuid
from pathlib import Path
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

import jwt

from fastapi import Depends, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.middleware.base import BaseHTTPMiddleware

from app.auth import get_current_user, get_tenant_id
from app.config import settings
from app.db import check_connections, NoActiveEMRConnection, shutdown_db_executor
from app.monitoring import (
    capture_error,
    get_error_stats,
    get_recent_errors,
    init_monitoring,
)
from app.rate_limit import limiter
from app.services.auth_service import decode_token, log_audit
from app.audit_middleware import AuditRequestContextMiddleware
from app.phi_access_logger import PHIAccessLoggingMiddleware
from app.routers import (
    adt,
    admin,
    analysis,
    attestations,
    audit,
    awv,
    benchmarks,
    care_gaps,
    ccda,
    chart_chase,
    claims,
    clearinghouse,
    cohorts,
    direct_messaging,
    documents,
    emr,
    fhir,
    jobs,
    notifications,
    patients,
    prospective,
    providers,
    quality,
    raf,
    reports,
    retention,
    submissions,
    suspects,
    uploads,
    webhooks,
)
from app.routers import auth as auth_router
from app.routers import bi_export
from app.routers import coder_worklist
from app.routers import provider_worklist as provider_worklist_router
from app.routers import insights as insights_router
from app.routers import realtime as realtime_router
from app.routers import smart_fhir as smart_fhir_router
from app.routers import meat as meat_router
from app.routers import radv_audit as radv_audit_router
from app.routers import data_quality as data_quality_router
from app.routers import health as health_router
from app.routers import icd10 as icd10_router
from app.routers import bundles, cms_transmission
from app.routers import pipeline as pipeline_router
from app.routers import pipeline_settings as pipeline_settings_router
from app.routers import recapture_gaps as recapture_gaps_router
from app.routers import dashboard_analytics as dashboard_analytics_router

# ---------------------------------------------------------------------------
# Logging — structured JSON in production, human-readable in development
# ---------------------------------------------------------------------------

from app.logging_config import configure_logging

configure_logging()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lifespan – startup / shutdown
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Verify DB connectivity on startup and log a summary."""
    logger.info("RAF Intelligence backend starting…")
    init_monitoring()

    # Metrics counters — used by /metrics endpoint
    app.state.start_time = datetime.now(timezone.utc)
    app.state.request_count = 0

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

    # ------------------------------------------------------------------
    # Alembic migration state check — NO auto-DDL at startup.
    # All schema changes must go through Alembic migrations.
    # ------------------------------------------------------------------
    strict_migrations = os.getenv("STRICT_MIGRATIONS", "true").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )

    # backend/ directory (parent of app/) — where alembic.ini lives
    backend_dir = Path(__file__).resolve().parent.parent

    def _run_alembic(subcmd: str) -> tuple[int, str, str]:
        try:
            proc = subprocess.run(
                ["alembic", subcmd],
                cwd=str(backend_dir),
                capture_output=True,
                text=True,
                timeout=30,
            )
            return proc.returncode, proc.stdout or "", proc.stderr or ""
        except FileNotFoundError as exc:
            return 127, "", f"alembic executable not found: {exc}"
        except subprocess.TimeoutExpired as exc:
            return 124, "", f"alembic {subcmd} timed out: {exc}"
        except Exception as exc:  # pragma: no cover - defensive
            return 1, "", f"alembic {subcmd} failed: {exc}"

    def _parse_revisions(output: str) -> set[str]:
        revs: set[str] = set()
        for line in output.splitlines():
            token = line.strip().split(" ", 1)[0].strip()
            # Strip trailing markers like "(head)"
            token = token.split("(", 1)[0].strip()
            if token and all(c.isalnum() for c in token):
                revs.add(token)
        return revs

    cur_rc, cur_out, cur_err = _run_alembic("current")
    head_rc, head_out, head_err = _run_alembic("heads")

    drift_detected = False
    drift_reason = ""
    if cur_rc != 0 or head_rc != 0:
        drift_detected = True
        drift_reason = (
            f"alembic invocation failed (current rc={cur_rc}, heads rc={head_rc}): "
            f"{cur_err.strip() or head_err.strip()}"
        )
    else:
        current_revs = _parse_revisions(cur_out)
        head_revs = _parse_revisions(head_out)
        if not head_revs:
            drift_detected = True
            drift_reason = "alembic heads returned no revisions"
        elif current_revs != head_revs:
            drift_detected = True
            drift_reason = (
                f"database revision {current_revs or '{none}'} "
                f"does not match alembic heads {head_revs}"
            )
        else:
            logger.info(
                "Alembic schema check OK: database at head revision(s) %s",
                ", ".join(sorted(head_revs)),
            )

    if drift_detected:
        logger.error(
            "SCHEMA DRIFT DETECTED: %s. Run 'alembic upgrade head' from the "
            "backend/ directory to apply pending migrations.",
            drift_reason,
        )
        if strict_migrations:
            raise RuntimeError(
                f"Refusing to start: schema drift detected ({drift_reason}). "
                "Set STRICT_MIGRATIONS=false to bypass (not recommended)."
            )
        logger.warning(
            "STRICT_MIGRATIONS is disabled — continuing startup despite schema drift."
        )

    # ------------------------------------------------------------------
    # Seed demo data (idempotent — safe to run on every restart)
    # Only runs in development or demo environments — never in production.
    # ------------------------------------------------------------------
    if settings.app_env in ("development", "demo"):
        # NOTE: seed_raf_demo and seed_encounters_scores_demo are intentionally
        # DISABLED. They write rows with tenant_id='1' targeting OpenEMR pids
        # 1..15, which collides with the real synced patients (ids 28..42,
        # tenant_id='default') and silently drops their RAF scores on every
        # restart. The EMR sync + on-demand RAF calculation already produce
        # the correct data for the 15 demo patients.
        _seeds = [
            ("seed_openemr_demo", "seed_openemr_demo"),
            ("seed_documents_demo", "seed_documents_demo"),
            ("seed_providers_demo", "seed_providers_demo"),
            ("seed_workflows_demo", "seed_workflows_demo"),
            ("seed_claims_cohorts_demo", "seed"),
        ]
        for mod_name, func_name in _seeds:
            try:
                import importlib

                mod = importlib.import_module(f"app.{mod_name}")
                getattr(mod, func_name)()
            except Exception as exc:
                logger.error("Seed %s failed (non-fatal): %s", mod_name, exc)
    else:
        logger.info("Skipping demo seeds (app_env=%s)", settings.app_env)

    logger.info("RAF Intelligence backend ready on port %s", settings.app_port)

    # NER uses Gemini API (no local models to preload)
    logger.info("NER mode: Gemini API (no local models needed)")

    # ------------------------------------------------------------------
    # Background / periodic work — Celery Beat (external process)
    # ------------------------------------------------------------------
    # The EMR sync scheduler and HIPAA retention sweep are now driven by
    # Celery Beat, NOT a daemon thread inside this process.
    #
    # You must start these two processes alongside uvicorn/gunicorn:
    #
    #   # Celery worker (processes tasks from default + heavy queues):
    #   celery -A app.services.celery_tasks worker \
    #       --loglevel=info --concurrency=4 -Q default,heavy
    #
    #   # Celery Beat (fires periodic tasks every 60 s / 1 h):
    #   celery -A app.services.celery_tasks beat --loglevel=info
    #
    # Both commands must run from the backend/ directory.
    #
    # start_scheduler() is kept as a no-op for health-endpoint compatibility.
    from app.services.sync_scheduler import start_scheduler, stop_scheduler
    from app.services.pipeline_chain import setup_pipeline_chain

    setup_pipeline_chain()
    start_scheduler()  # logs a reminder; no thread is started

    yield  # application runs

    stop_scheduler()  # no-op; Beat is an external process
    shutdown_db_executor()
    logger.info("RAF Intelligence backend shutting down.")


# ---------------------------------------------------------------------------
# OpenAPI tags metadata — controls Swagger UI grouping and ordering
# ---------------------------------------------------------------------------

tags_metadata = [
    {"name": "auth", "description": "Authentication and user management"},
    {"name": "patients", "description": "Patient demographics and clinical data"},
    {"name": "raf", "description": "RAF score calculation and analysis"},
    {"name": "analysis", "description": "Clinical note NLP analysis"},
    {"name": "suspects", "description": "Suspect condition management"},
    {
        "name": "attestations",
        "description": "Provider sign-off workflow for suspect HCC conditions",
    },
    {
        "name": "chart-chase",
        "description": "Chart chase management — track requests for missing medical records",
    },
    {"name": "documents", "description": "Document upload and Gemini Vision analysis"},
    {
        "name": "ccda",
        "description": "C-CDA / CCD XML document ingestion, parsing, and export",
    },
    {"name": "claims", "description": "Claims data ingestion (837P/837I/CSV)"},
    {"name": "fhir", "description": "FHIR R4 EHR integration"},
    {
        "name": "smart_fhir",
        "description": "SMART on FHIR app launch (EHR-launch and standalone-launch flows)",
    },
    {"name": "providers", "description": "Provider management and scorecards"},
    {"name": "submissions", "description": "CMS RAPS/EDPS submission management"},
    {"name": "prospective", "description": "Prospective RAF management"},
    {
        "name": "awv",
        "description": "Annual Wellness Visit scheduling, outreach, checklists, and results",
    },
    {"name": "quality", "description": "HEDIS quality measures and STARS"},
    {"name": "benchmarks", "description": "Benchmarking and performance comparisons"},
    {
        "name": "care_gaps",
        "description": "Care gap closure workflow and provider task assignment",
    },
    {
        "name": "recapture_gaps",
        "description": "HCC recapture gap analysis — prior-year HCCs not yet documented in the current measurement year",
    },
    {
        "name": "cohorts",
        "description": "Cohort analysis and population health management — dynamic patient populations, snapshots, and cohort comparisons",
    },
    {
        "name": "adt",
        "description": "ADT feed real-time HL7v2 MLLP listener and message management",
    },
    {"name": "webhooks", "description": "Webhook event subscriptions"},
    {
        "name": "notifications",
        "description": "Email notification configuration and preferences",
    },
    {
        "name": "direct_messaging",
        "description": "Direct Messaging — S/MIME secure provider-to-provider clinical data exchange",
    },
    {"name": "jobs", "description": "Background job management"},
    {"name": "pipeline", "description": "Pipeline auto-chain run status and history"},
    {"name": "reports", "description": "Analytics and reporting"},
    {"name": "audit", "description": "Compliance and audit packages"},
    {
        "name": "radv",
        "description": "RADV (Risk Adjustment Data Validation) audit trail, "
        "MEAT compliance checks, and population-level readiness reports",
    },
    {
        "name": "bi_export",
        "description": "BI Tools Export — Tableau, PowerBI, Looker, Metabase, OData, CSV/JSON/Excel",
    },
    {"name": "health", "description": "Health checks and system status"},
    {"name": "icd10", "description": "ICD-10-CM code lookup and validation"},
    {"name": "compliance", "description": "HIPAA compliance status"},
    {
        "name": "admin",
        "description": "Administrative operations: data retention, purge",
    },
    {
        "name": "worklist",
        "description": "Coder worklist / review queue and productivity metrics",
    },
    {
        "name": "realtime",
        "description": "Real-time dashboard: SSE stream, WebSocket, alerts, KPI, dashboard configs",
    },
]


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="RAF Intelligence API",
    description="""
Enterprise-grade RAF (Risk Adjustment Factor) scoring and HCC coding platform.

## Version

Current API version: **v1**

All endpoints are prefixed with `/api/`. The API version is communicated via:
- `X-API-Version` response header
- `Accept` header: `application/vnd.raf-intelligence.v1+json`

## Authentication

Most endpoints require a valid JWT access token.
""",
    version="2.0.0",
    lifespan=lifespan,
    openapi_tags=tags_metadata,
    contact={"name": "RAF Intelligence Support", "email": "support@raf.health"},
    license_info={"name": "Proprietary"},
    # Disable interactive API docs in production to avoid leaking the full
    # schema to unauthenticated users. Docs remain available in development.
    docs_url="/docs" if settings.app_env != "production" else None,
    redoc_url="/redoc" if settings.app_env != "production" else None,
    openapi_url="/openapi.json" if settings.app_env != "production" else None,
)

# ---------------------------------------------------------------------------
# Rate limiting (slowapi)
# ---------------------------------------------------------------------------

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


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
        response.headers["X-CSP-Nonce"] = _csp_nonce
        return response


app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(PHIAccessLoggingMiddleware)
app.add_middleware(AuditRequestContextMiddleware)


@app.exception_handler(RequestValidationError)
async def _validation_error_handler(request: Request, exc: RequestValidationError):
    logger.error(
        "Validation error on %s %s: %s", request.method, request.url.path, exc.errors()
    )
    return JSONResponse(
        status_code=422,
        content={"detail": "Validation error. Check your request parameters."},
    )


# ---------------------------------------------------------------------------
# Request ID tracing middleware
# ---------------------------------------------------------------------------


class RequestIDMiddleware(BaseHTTPMiddleware):
    """
    Generate a unique request ID for every request and inject it into:
    - The response headers as ``X-Request-ID``
    - The request state as ``request.state.request_id``
    - All log records via a context variable

    This enables end-to-end tracing across the entire stack:
    frontend → backend → database → external services.
    """

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


app.add_middleware(RequestIDMiddleware)


# ---------------------------------------------------------------------------
# Audit logging middleware
# ---------------------------------------------------------------------------

_PHI_KEYS = {
    "ssn",
    "dob",
    "DOB",
    "date_of_birth",
    "fname",
    "lname",
    "first_name",
    "last_name",
    "address",
    "phone",
    "email",
    "mbi",
    "medicare_id",
}


def _scrub_phi(data: dict) -> dict:
    """Return a copy of *data* with PHI-sensitive keys replaced by '***REDACTED***'."""
    if not isinstance(data, dict):
        return data
    return {
        k: "***REDACTED***" if k.lower() in _PHI_KEYS else v for k, v in data.items()
    }


class AuditLoggingMiddleware(BaseHTTPMiddleware):
    """
    Lightweight request audit middleware.

    Writes one row per API request to audit_log (path, method, user_id,
    status code, timestamp).  Skips health/docs/static endpoints to keep
    the log focused on clinical and auth activity.
    """

    _SKIP_PREFIXES = ("/health", "/docs", "/redoc", "/openapi.json", "/favicon")

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        # Skip noise endpoints
        for prefix in self._SKIP_PREFIXES:
            if path.startswith(prefix):
                return await call_next(request)

        response = await call_next(request)

        # Best-effort – never let audit failure break a request
        try:
            user_id: int | None = None
            auth_header = request.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                try:
                    payload = decode_token(auth_header[len("Bearer ") :])
                    user_id = int(payload.get("sub", 0)) or None
                except (jwt.PyJWTError, Exception):
                    pass

            forwarded = request.headers.get("X-Forwarded-For")
            ip = (
                forwarded.split(",")[0].strip()
                if forwarded
                else (request.client.host if request.client else None)
            )

            raw_details: dict[str, Any] = {
                "query_params": dict(request.query_params),
            }
            log_audit(
                action="http_request",
                user_id=user_id,
                resource_type="http",
                ip_address=ip,
                user_agent=request.headers.get("User-Agent"),
                request_method=request.method,
                request_path=path,
                response_status=response.status_code,
                details=_scrub_phi(raw_details),
            )
        except Exception as exc:
            logger.error("Audit log write failed: %s", exc, exc_info=True)

        return response


app.add_middleware(AuditLoggingMiddleware)


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------

_frontend_url = os.getenv("FRONTEND_URL", "")
if settings.app_env == "production":
    if not _frontend_url:
        raise RuntimeError("FRONTEND_URL must be set in production")
    if _frontend_url.startswith("http://"):
        raise RuntimeError("FRONTEND_URL must use https:// in production")
_cors_origins: list[str] = []
if settings.app_env in ("development", "testing"):
    _cors_origins = [
        "http://localhost:3500",
        "http://localhost:3000",
        "http://localhost:3001",
        "http://localhost:3444",
        "http://127.0.0.1:3500",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3001",
        "http://127.0.0.1:3444",
    ]
if _frontend_url:
    _cors_origins.append(_frontend_url)

if not _cors_origins:
    logger.warning(
        "CORS allow_origins is empty — all cross-origin requests will be blocked. Set FRONTEND_URL."
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
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


# ---------------------------------------------------------------------------
# Request timing middleware
# ---------------------------------------------------------------------------


@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - start) * 1000
    if os.getenv("APP_ENV", "production") != "production":
        response.headers["X-Process-Time-Ms"] = f"{elapsed_ms:.1f}"
    logger.debug("%s %s  %.1f ms", request.method, request.url.path, elapsed_ms)
    # Increment the global request counter (best-effort; non-atomic under high
    # concurrency but accurate enough for operational dashboards).
    try:
        app.state.request_count = getattr(app.state, "request_count", 0) + 1
    except Exception:
        pass
    return response


# ---------------------------------------------------------------------------
# Global exception handler — never leaks internal detail to clients
# ---------------------------------------------------------------------------


@app.exception_handler(NoActiveEMRConnection)
async def no_emr_handler(request: Request, exc: NoActiveEMRConnection):
    """Return 503 when no EMR connection is configured or reachable."""
    return JSONResponse(
        status_code=503,
        headers={"Retry-After": "60"},
        content={
            "detail": "No active EMR connection configured. Add a connection via the EMR Config page.",
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


# ---------------------------------------------------------------------------
# Structured logging with request context
# ---------------------------------------------------------------------------


class StructuredLoggingMiddleware(BaseHTTPMiddleware):
    """
    Attach structured request context to every log record during a request.

    Injects ``request_id``, ``method``, ``path``, and ``user_id`` into the
    Python logging context so that all log messages emitted during request
    processing automatically include these fields.

    After the response is sent, emits a single structured access log line
    suitable for ingestion by ELK / Datadog / CloudWatch.
    """

    async def dispatch(self, request: Request, call_next):
        request_id = getattr(request.state, "request_id", "unknown")
        method = request.method
        path = request.url.path

        # Best-effort user extraction from JWT
        user_id: str | None = None
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            try:
                payload = decode_token(auth_header[len("Bearer ") :])
                user_id = str(payload.get("sub", "")) or None
            except Exception:
                pass

        # Create a logging adapter with request context
        extra = {
            "request_id": request_id,
            "method": method,
            "path": path,
            "user_id": user_id,
        }

        start = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - start) * 1000

        # Structured access log
        logger.info(
            "http_access",
            extra={
                **extra,
                "status_code": response.status_code,
                "duration_ms": round(elapsed_ms, 1),
                "client_ip": request.client.host if request.client else None,
            },
        )

        return response


app.add_middleware(StructuredLoggingMiddleware)


# ---------------------------------------------------------------------------
# API versioning header
# ---------------------------------------------------------------------------


@app.middleware("http")
async def add_api_version_header(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-API-Version"] = "v1"
    return response


# ---------------------------------------------------------------------------
# EMR-gate middleware
#
# When the authenticated tenant has zero active EMR connections, all
# clinical-data endpoints are blocked. The user must Activate a connection
# in EMR Configuration before they can see patients, RAF, audits, etc.
#
# Endpoints that remain accessible while gated:
#   - /, /health, /docs, /openapi.json
#   - /api/auth/*    (login, refresh, logout, me)
#   - /api/emr/*     (so user can re-activate)
#   - /api/admin/*   (admin tools)
#   - /api/notifications/*
# ---------------------------------------------------------------------------

_EMR_GATE_ALLOWED_PREFIXES = (
    "/api/auth",
    "/api/emr",
    "/api/admin",
    "/api/notifications",
    "/api/pipeline",
    "/api/uploads",
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/",
)

_EMR_GATE_ALLOWED_EXACT = {"/", "/health"}


def _path_is_emr_gate_exempt(path: str) -> bool:
    if path in _EMR_GATE_ALLOWED_EXACT:
        return True
    for prefix in _EMR_GATE_ALLOWED_PREFIXES:
        if path == prefix or path.startswith(prefix + "/"):
            return True
    if not path.startswith("/api/"):
        return True  # static / non-API
    return False


@app.middleware("http")
async def emr_gate(request: Request, call_next):
    path = request.url.path
    if _path_is_emr_gate_exempt(path):
        return await call_next(request)

    # Resolve user from token; if unauthenticated, let downstream auth deps
    # return 401 as usual.
    try:
        from app.auth import _resolve_user

        user = await _resolve_user(request)
    except Exception:
        user = None

    if user is None:
        return await call_next(request)

    tenant_id = str(user.get("tenant_id") or "1")

    try:
        from app.services import emr_manager

        conns = emr_manager.list_connections(tenant_id=tenant_id)
        active_count = sum(1 for c in conns if int(c.get("is_active") or 0) == 1)
    except Exception as exc:
        logger.warning("emr_gate: list_connections failed: %s", exc)
        return await call_next(request)

    # Also allow access when the tenant has uploaded patient data, even if
    # no EMR connection is active — the tenant still has a valid data source.
    has_uploaded_data = False
    if active_count == 0:
        try:
            from app.db import raf_cursor as _raf_cursor

            with _raf_cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM patients WHERE tenant_id = %s AND data_source = 'upload' AND is_active = 1 LIMIT 1",
                    (tenant_id,),
                )
                has_uploaded_data = cur.fetchone() is not None
        except Exception as exc:
            logger.warning("emr_gate: uploaded-data check failed: %s", exc)

    if active_count == 0 and not has_uploaded_data:
        # CORS headers must be added manually because this middleware sits
        # OUTSIDE the CORSMiddleware (decorators added later wrap earlier
        # middlewares). Without these headers the browser reports the 423
        # as a "Network Error" and the user never sees the message.
        origin = request.headers.get("origin", "")
        cors_headers: dict[str, str] = {}
        if origin and (origin in _cors_origins or "*" in _cors_origins):
            cors_headers["access-control-allow-origin"] = origin
            cors_headers["access-control-allow-credentials"] = "true"
            cors_headers["vary"] = "Origin"
        return JSONResponse(
            status_code=423,
            content={
                "detail": "No data source available. Connect an EMR or upload a patient file to get started.",
                "code": "NO_DATA_SOURCE",
            },
            headers=cors_headers,
        )

    return await call_next(request)


# ---------------------------------------------------------------------------
# Routers — registered in logical/dependency order
# ---------------------------------------------------------------------------

# Auth must come first (other routers depend on it for token issuance)
app.include_router(auth_router.router)

# Core clinical entities
app.include_router(patients.router)
app.include_router(raf.router)
app.include_router(analysis.router)
app.include_router(suspects.router)
app.include_router(attestations.router)
app.include_router(chart_chase.router)
app.include_router(documents.router)
app.include_router(ccda.router)
app.include_router(uploads.router)

# Payer / claims workflows
app.include_router(claims.router)
app.include_router(submissions.router)
app.include_router(bundles.router)
app.include_router(cms_transmission.router)

# Integrations
app.include_router(fhir.router)
app.include_router(smart_fhir_router.router)
app.include_router(emr.router)
app.include_router(adt.router)
app.include_router(webhooks.router)
app.include_router(notifications.router)
app.include_router(direct_messaging.router)
app.include_router(clearinghouse.router)

# Provider and quality management
app.include_router(providers.router)
app.include_router(quality.router)
app.include_router(prospective.router)
app.include_router(benchmarks.router)
app.include_router(care_gaps.router)
app.include_router(recapture_gaps_router.router)
app.include_router(awv.router)

# Population health cohort analysis
app.include_router(cohorts.router)
# Operations and compliance
app.include_router(jobs.router)
app.include_router(pipeline_router.router)
app.include_router(pipeline_settings_router.router)
app.include_router(reports.router)
app.include_router(dashboard_analytics_router.router)
app.include_router(audit.router)

# BI Tools Export
app.include_router(bi_export.router)

# Coder worklist / review queue
app.include_router(coder_worklist.router)

# Provider worklist — prioritized patient lists and action items for RAF optimization
app.include_router(provider_worklist_router.router)

# Real-time clinical intelligence insights
app.include_router(insights_router.router)

# Real-time dashboards
app.include_router(realtime_router.router)

# Health and info
app.include_router(health_router.router)
app.include_router(icd10_router.router)

# Admin
app.include_router(retention.router)
app.include_router(admin.router)
app.include_router(meat_router.router)
app.include_router(radv_audit_router.router)
app.include_router(data_quality_router.router)
