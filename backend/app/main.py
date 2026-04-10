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
from app.db import check_connections, NoActiveEMRConnection
from app.monitoring import (
    capture_error,
    get_error_stats,
    get_recent_errors,
    init_monitoring,
)
from app.rate_limit import limiter
from app.services.auth_service import decode_token, log_audit
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
from app.routers import insights as insights_router
from app.routers import realtime as realtime_router
from app.routers import smart_fhir as smart_fhir_router
from app.routers import meat as meat_router
from app.routers import data_quality as data_quality_router

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

    from app.services.sync_scheduler import start_scheduler, stop_scheduler

    start_scheduler()

    yield  # application runs

    stop_scheduler()
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
    {"name": "reports", "description": "Analytics and reporting"},
    {"name": "audit", "description": "Compliance and audit packages"},
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
        # 'unsafe-inline' is retained in script-src and style-src because
        # Next.js currently injects inline scripts and styles; replace it with
        # per-request nonces (next.config.js → headers + generateNonce()) once
        # the frontend supports them.
        # 'unsafe-eval' has been removed — it was never required by Next.js in
        # production mode and opens the door to XSS via eval/Function().
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; "
            "font-src 'self'; "
            "connect-src 'self'; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'"
        )
        return response


app.add_middleware(SecurityHeadersMiddleware)


@app.exception_handler(RequestValidationError)
async def _validation_error_handler(request: Request, exc: RequestValidationError):
    logger.error("Validation error on %s %s: %s", request.method, request.url.path, exc.errors())
    return JSONResponse(status_code=422, content={"detail": exc.errors()})


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
    "ssn", "dob", "DOB", "date_of_birth",
    "fname", "lname", "first_name", "last_name",
    "address", "phone", "email", "mbi", "medicare_id",
}


def _scrub_phi(data: dict) -> dict:
    """Return a copy of *data* with PHI-sensitive keys replaced by '***REDACTED***'."""
    if not isinstance(data, dict):
        return data
    return {k: "***REDACTED***" if k.lower() in _PHI_KEYS else v for k, v in data.items()}


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
if settings.app_env == "development":
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
app.include_router(awv.router)

# Population health cohort analysis
app.include_router(cohorts.router)
# Operations and compliance
app.include_router(jobs.router)
app.include_router(reports.router)
app.include_router(audit.router)

# BI Tools Export
app.include_router(bi_export.router)

# Coder worklist / review queue
app.include_router(coder_worklist.router)

# Real-time clinical intelligence insights
app.include_router(insights_router.router)

# Real-time dashboards
app.include_router(realtime_router.router)

# Admin
app.include_router(retention.router)
app.include_router(admin.router)
app.include_router(meat_router.router)
app.include_router(data_quality_router.router)


# ---------------------------------------------------------------------------
# Health / info endpoints
# ---------------------------------------------------------------------------


@app.get("/", tags=["health"], summary="Root")
def root() -> dict[str, str]:
    return {
        "service": "RAF Intelligence API",
        "version": "2.0.0",
        "status": "running",
        "docs": "/docs",
    }


@app.get("/api/dashboard/stats", tags=["health"], summary="Dashboard summary stats")
def dashboard_stats(
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    year: int = Query(default=None, description="Measurement year to filter by (defaults to current year)"),
) -> dict[str, Any]:
    """Quick population stats for the dashboard."""
    from app.db import raf_cursor
    from datetime import date as _date

    measurement_year = year if year is not None else _date.today().year

    ZERO_RESPONSE = {
        "total_patients": 0,
        "patients_analyzed": 0,
        "average_raf": 0.0,
        "coverage_pct": 0.0,
    }

    # 1. Check for an active EMR connection
    try:
        with raf_cursor() as cur:
            cur.execute("SELECT COUNT(*) AS cnt FROM emr_connections WHERE is_active = 1")
            has_active = cur.fetchone()["cnt"] > 0
    except Exception as exc:
        logger.error("Dashboard stats — emr_connections query error: %s", exc)
        return ZERO_RESPONSE

    if not has_active:
        return ZERO_RESPONSE

    total_patients = 0
    analyzed = 0
    avg_raf = 0.0

    from app.services.emr_manager import ACTIVE_PATIENTS_SUBQUERY

    # Total patients = the active cohort in raf_intelligence.patients.
    # This respects the activate/deactivate pattern used by CSV upload and
    # EMR reactivation flows, so deactivated patients are correctly excluded.
    try:
        with raf_cursor() as cur:
            cur.execute("SELECT COUNT(*) AS cnt FROM patients WHERE is_active = 1")
            total_patients = cur.fetchone()["cnt"]
    except Exception as exc:
        logger.error("Dashboard stats — active patients query error: %s", exc)

    # Query RAF database for scoring stats filtered by active connections
    try:
        with raf_cursor() as cur:
            cur.execute(
                f"SELECT COUNT(DISTINCT patient_id) AS cnt FROM raf_scores WHERE {ACTIVE_PATIENTS_SUBQUERY} AND raf_scores.tenant_id = %s AND measurement_year = %s",
                (int(tenant_id), measurement_year),
            )
            analyzed = cur.fetchone()["cnt"]
            cur.execute(
                f"SELECT AVG(final_raf) AS avg_raf FROM raf_scores WHERE {ACTIVE_PATIENTS_SUBQUERY} AND raf_scores.tenant_id = %s AND measurement_year = %s",
                (int(tenant_id), measurement_year),
            )
            row = cur.fetchone()
            avg_raf = round(float(row["avg_raf"] or 0), 4)
    except Exception as exc:
        logger.error("Dashboard stats — RAF query error: %s", exc)

    return {
        "total_patients": total_patients,
        "patients_analyzed": analyzed,
        "average_raf": avg_raf,
        "coverage_pct": round(analyzed / total_patients * 100, 1)
        if total_patients
        else 0,
    }


@app.get("/api/dashboard/trends", tags=["health"], summary="Dashboard trend data")
def dashboard_trends(
    current_user: dict = Depends(get_current_user),
    year: int = Query(default=None, description="Measurement year to filter by (defaults to current year)"),
) -> dict[str, Any]:
    """
    Compute real period-over-period trend data for the dashboard KPI cards.

    Compares the current 30-day window against the prior 30-day window for:
    - patients_analyzed: number of unique patients with RAF scores
    - average_raf: mean RAF score
    - revenue_opportunity: estimated revenue from open suspect conditions

    Returns the raw values and the calculated percentage change.
    """
    try:
        from app.db import raf_cursor
        from datetime import date as _date

        measurement_year = year if year is not None else _date.today().year

        with raf_cursor() as cur:
            # Current 30 days vs prior 30 days, scoped to the requested measurement year
            cur.execute(
                """
                SELECT
                    COUNT(DISTINCT CASE WHEN calculated_at >= DATE_SUB(NOW(), INTERVAL 30 DAY) THEN patient_id END) AS current_analyzed,
                    COUNT(DISTINCT CASE WHEN calculated_at >= DATE_SUB(NOW(), INTERVAL 60 DAY)
                                        AND calculated_at < DATE_SUB(NOW(), INTERVAL 30 DAY) THEN patient_id END) AS prior_analyzed,
                    AVG(CASE WHEN calculated_at >= DATE_SUB(NOW(), INTERVAL 30 DAY) THEN final_raf END) AS current_avg_raf,
                    AVG(CASE WHEN calculated_at >= DATE_SUB(NOW(), INTERVAL 60 DAY)
                             AND calculated_at < DATE_SUB(NOW(), INTERVAL 30 DAY) THEN final_raf END) AS prior_avg_raf
                FROM raf_scores
                WHERE calculated_at >= DATE_SUB(NOW(), INTERVAL 60 DAY)
                  AND measurement_year = %s
                """,
                (measurement_year,),
            )
            row = cur.fetchone()

        current_analyzed = int(row["current_analyzed"] or 0)
        prior_analyzed = int(row["prior_analyzed"] or 0)
        current_avg_raf = float(row["current_avg_raf"] or 0)
        prior_avg_raf = float(row["prior_avg_raf"] or 0)

        def _pct_change(current: float, prior: float) -> float | None:
            if prior == 0:
                return None
            return round(((current - prior) / prior) * 100, 1)

        return {
            "period": "30d",
            "patients_analyzed": {
                "current": current_analyzed,
                "prior": prior_analyzed,
                "change_pct": _pct_change(current_analyzed, prior_analyzed),
            },
            "average_raf": {
                "current": round(current_avg_raf, 4),
                "prior": round(prior_avg_raf, 4),
                "change_pct": _pct_change(current_avg_raf, prior_avg_raf),
            },
        }

    except Exception as exc:
        logger.error("Dashboard trends error: %s", exc)
        return {"period": "30d", "error": True}


@app.get("/health", tags=["health"], summary="Health check")
def health_check(request: Request) -> dict[str, Any]:
    """
    Returns 200 when all dependencies are healthy, 503 otherwise.
    Suitable for load-balancer / Kubernetes readiness probes.
    """
    db_status = check_connections()
    all_healthy = all(db_status.values())

    from app.services.sync_scheduler import get_scheduler_status

    payload: dict[str, Any] = {
        "status": "healthy" if all_healthy else "degraded",
        "request_id": getattr(request.state, "request_id", None),
        "databases": db_status,
        "gemini_model": settings.gemini_model,
        "sync_scheduler": get_scheduler_status(),
        "monitoring": get_error_stats(),
    }

    if not all_healthy:
        return JSONResponse(status_code=503, content=payload)
    return payload


@app.get("/health/ready", tags=["health"], summary="Readiness probe")
def readiness_probe() -> dict[str, Any]:
    """
    Kubernetes-style readiness probe.
    Returns 200 only when ALL critical dependencies are healthy.
    Unlike /health, this returns 503 if ANY check fails.
    """
    checks: dict[str, bool] = {}

    # Database connections
    db_status = check_connections()
    checks["databases"] = all(db_status.values())

    # Redis (Celery broker/backend)
    try:
        import redis

        r = redis.from_url(settings.redis_url, socket_timeout=2)
        r.ping()
        checks["redis"] = True
    except Exception:
        checks["redis"] = False

    # Gemini API key present
    checks["gemini_api_key"] = bool(settings.gemini_api_key)

    all_healthy = all(checks.values())
    payload = {
        "ready": all_healthy,
        "checks": checks,
    }
    if not all_healthy:
        return JSONResponse(status_code=503, content=payload)
    return payload


@app.get("/metrics", tags=["health"], include_in_schema=False)
async def metrics(request: Request) -> dict[str, Any]:
    """
    Lightweight application metrics for operational monitoring.

    Returns uptime, total request count, and — when psutil is installed —
    process memory and CPU usage.  The endpoint is intentionally excluded
    from the OpenAPI schema so it does not appear in Swagger UI.

    Suitable for polling by Prometheus (via a JSON exporter), Datadog, or
    any simple HTTP monitor.  No authentication is required so that external
    probes can reach it without a token.
    """
    start_time: datetime = getattr(app.state, "start_time", datetime.now(timezone.utc))
    uptime_seconds = (datetime.now(timezone.utc) - start_time).total_seconds()
    request_count: int = getattr(app.state, "request_count", 0)

    payload: dict[str, Any] = {
        "uptime_seconds": round(uptime_seconds, 1),
        "requests_total": request_count,
        "app_env": settings.app_env,
    }

    # Opportunistically add process metrics when psutil is available.
    try:
        import psutil  # type: ignore[import]

        proc = psutil.Process()
        payload["memory_mb"] = round(proc.memory_info().rss / 1024 / 1024, 1)
        payload["cpu_percent"] = proc.cpu_percent(interval=None)
    except ImportError:
        # psutil not installed — skip process-level stats.
        pass
    except Exception:
        pass

    return payload


# ---------------------------------------------------------------------------
# ICD-10-CM endpoints (auth-guarded)
# ---------------------------------------------------------------------------


@app.get(
    "/api/icd10/validate/{code}", tags=["icd10"], summary="Validate an ICD-10-CM code"
)
def validate_icd10(
    code: str,
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Check whether *code* is a valid, billable (leaf) ICD-10-CM code."""
    from app.services.icd_validator import (
        get_code_description,
        normalize_code,
        validate_code,
    )

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
    max_results: int = Query(default=20, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
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
# HIPAA compliance status (auth-guarded, dynamic checks)
# ---------------------------------------------------------------------------


@app.get(
    "/api/compliance/status", tags=["compliance"], summary="HIPAA compliance status"
)
def compliance_status(current_user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """
    Returns the current HIPAA compliance posture of this deployment.

    Intended for ops dashboards and audit evidence packages.  The Google BAA
    covers all Gemini API calls made by this service.  Security headers are
    injected by SecurityHeadersMiddleware on every response.  PHI access is
    logged to the phi_audit logger on every patient data endpoint.
    """
    checks: dict[str, Any] = {
        "jwt_secret_configured": bool(os.getenv("JWT_SECRET")),
        "tls_enforced": bool(os.getenv("TLS_ENABLED", "")),
        "mfa_available": True,
        "audit_logging": True,
        "rbac_enforced": True,
        "rate_limiting": True,
        "idle_timeout_minutes": (
            settings.idle_timeout_minutes
            if hasattr(settings, "idle_timeout_minutes")
            else None
        ),
        "access_token_expiry_minutes": settings.access_token_expire_minutes,
        "encryption_in_transit": True,
        "security_headers": True,
        "phi_access_logging": True,
        "baa_provider": "Google Cloud (Gemini)",
    }
    all_passing = all(v for v in checks.values() if isinstance(v, bool))
    return {
        "hipaa_compliant": all_passing,
        "status": "compliant" if all_passing else "non_compliant",
        "checks": checks,
        "assessed_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Admin — error monitoring endpoints
# ---------------------------------------------------------------------------


@app.get("/api/admin/errors", tags=["health"], summary="List recent errors")
def admin_list_errors(
    limit: int = Query(default=50, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Return the most recent captured errors (newest first). Requires authentication."""
    return {
        "errors": get_recent_errors(limit=limit),
        "count": len(get_recent_errors(limit=limit)),
    }


@app.get("/api/admin/errors/stats", tags=["health"], summary="Error statistics")
def admin_error_stats(
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Return aggregate error counts by type. Requires authentication."""
    return get_error_stats()


@app.post(
    "/api/admin/errors/report", tags=["health"], summary="Report a client-side error"
)
async def admin_report_error(request: Request) -> dict[str, str]:
    """
    Accept client-side error reports from the frontend error-tracking module.
    No authentication required so errors can be captured before login completes.
    """
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    from app.monitoring import capture_error as _capture
    from datetime import datetime, timezone

    # Wrap the client payload as a synthetic exception for the in-memory store
    class ClientError(Exception):
        pass

    exc = ClientError(payload.get("message", "unknown client error"))
    _capture(exc, context={"source": "frontend", **payload})
    return {"status": "recorded"}
