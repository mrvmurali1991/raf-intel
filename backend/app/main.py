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
from pathlib import Path
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.config import settings
from app.db import check_connections, shutdown_db_executor
from app.monitoring import init_monitoring
from app.logging_config import configure_logging
from app.exception_handlers import register_exception_handlers
from app.middleware import setup_middleware
from app.router_registry import register_routers
from app.telemetry import init_telemetry

configure_logging()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# OpenAPI tags metadata — controls Swagger UI grouping and ordering
# ---------------------------------------------------------------------------

tags_metadata = [
    {"name": "auth", "description": "Authentication and user management"},
    {"name": "patients", "description": "Patient demographics and clinical data"},
    {"name": "raf", "description": "RAF score calculation and analysis"},
    {"name": "analysis", "description": "Clinical note NLP analysis"},
    {"name": "suspects", "description": "Suspect condition management"},
    {"name": "attestations", "description": "Provider sign-off workflow for suspect HCC conditions"},
    {"name": "chart-chase", "description": "Chart chase management — track requests for missing medical records"},
    {"name": "documents", "description": "Document upload and Gemini Vision analysis"},
    {"name": "ccda", "description": "C-CDA / CCD XML document ingestion, parsing, and export"},
    {"name": "claims", "description": "Claims data ingestion (837P/837I/CSV)"},
    {"name": "fhir", "description": "FHIR R4 EHR integration"},
    {"name": "smart_fhir", "description": "SMART on FHIR app launch (EHR-launch and standalone-launch flows)"},
    {"name": "providers", "description": "Provider management and scorecards"},
    {"name": "submissions", "description": "CMS RAPS/EDPS submission management"},
    {"name": "prospective", "description": "Prospective RAF management"},
    {"name": "awv", "description": "Annual Wellness Visit scheduling, outreach, checklists, and results"},
    {"name": "quality", "description": "HEDIS quality measures and STARS"},
    {"name": "benchmarks", "description": "Benchmarking and performance comparisons"},
    {"name": "care_gaps", "description": "Care gap closure workflow and provider task assignment"},
    {"name": "recapture_gaps", "description": "HCC recapture gap analysis — prior-year HCCs not yet documented in the current measurement year"},
    {"name": "cohorts", "description": "Cohort analysis and population health management — dynamic patient populations, snapshots, and cohort comparisons"},
    {"name": "adt", "description": "ADT feed real-time HL7v2 MLLP listener and message management"},
    {"name": "webhooks", "description": "Webhook event subscriptions"},
    {"name": "notifications", "description": "Email notification configuration and preferences"},
    {"name": "direct_messaging", "description": "Direct Messaging — S/MIME secure provider-to-provider clinical data exchange"},
    {"name": "jobs", "description": "Background job management"},
    {"name": "pipeline", "description": "Pipeline auto-chain run status and history"},
    {"name": "reports", "description": "Analytics and reporting"},
    {"name": "audit", "description": "Compliance and audit packages"},
    {"name": "radv", "description": "RADV (Risk Adjustment Data Validation) audit trail, MEAT compliance checks, and population-level readiness reports"},
    {"name": "bi_export", "description": "BI Tools Export — Tableau, PowerBI, Looker, Metabase, OData, CSV/JSON/Excel"},
    {"name": "health", "description": "Health checks and system status"},
    {"name": "icd10", "description": "ICD-10-CM code lookup and validation"},
    {"name": "compliance", "description": "HIPAA compliance status"},
    {"name": "admin", "description": "Administrative operations: data retention, purge"},
    {"name": "worklist", "description": "Coder worklist / review queue and productivity metrics"},
    {"name": "realtime", "description": "Real-time dashboard: SSE stream, WebSocket, alerts, KPI, dashboard configs"},
]


# ---------------------------------------------------------------------------
# Lifespan – startup / shutdown
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Verify DB connectivity on startup and log a summary."""
    logger.info("RAF Intelligence backend starting...")
    init_monitoring()
    init_telemetry(app)

    app.state.start_time = datetime.now(timezone.utc)
    app.state.request_count = 0

    logger.info("Gemini model: %s", settings.gemini_model)

    db_status = check_connections()
    for db_name, ok in db_status.items():
        logger.info("Database connection [%s]: %s", db_name, "OK" if ok else "FAILED")

    if not all(db_status.values()):
        logger.warning(
            "One or more database connections failed at startup. "
            "The API will start but some endpoints may return errors."
        )
    else:
        logger.info("All database connections healthy.")

    _check_alembic_migrations()

    if settings.app_env in ("development", "demo"):
        _run_demo_seeds()
    else:
        logger.info("Skipping demo seeds (app_env=%s)", settings.app_env)

    logger.info("RAF Intelligence backend ready on port %s", settings.app_port)
    logger.info("NER mode: Gemini API (no local models needed)")

    from app.services.sync_scheduler import start_scheduler, stop_scheduler
    from app.services.pipeline_chain import setup_pipeline_chain

    setup_pipeline_chain()
    start_scheduler()

    yield  # application runs

    stop_scheduler()
    shutdown_db_executor()
    logger.info("RAF Intelligence backend shutting down.")


def _check_alembic_migrations() -> None:
    """Check Alembic migration state; raise on drift when STRICT_MIGRATIONS=true."""
    strict = os.getenv("STRICT_MIGRATIONS", "true").strip().lower() in ("1", "true", "yes", "on")
    backend_dir = Path(__file__).resolve().parent.parent

    def _run(subcmd: str) -> tuple[int, str, str]:
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
        except Exception as exc:
            return 1, "", f"alembic {subcmd} failed: {exc}"

    def _parse_revisions(output: str) -> set[str]:
        revs: set[str] = set()
        for line in output.splitlines():
            token = line.strip().split(" ", 1)[0].strip().split("(", 1)[0].strip()
            if token and all(c.isalnum() for c in token):
                revs.add(token)
        return revs

    cur_rc, cur_out, cur_err = _run("current")
    head_rc, head_out, head_err = _run("heads")

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
        if strict:
            raise RuntimeError(
                f"Refusing to start: schema drift detected ({drift_reason}). "
                "Set STRICT_MIGRATIONS=false to bypass (not recommended)."
            )
        logger.warning(
            "STRICT_MIGRATIONS is disabled — continuing startup despite schema drift."
        )


def _run_demo_seeds() -> None:
    """Run idempotent demo data seeds (development / demo environments only).

    NOTE: seed_raf_demo and seed_encounters_scores_demo are intentionally
    DISABLED — they write rows with tenant_id='1' targeting OpenEMR pids
    1..15, which collides with the real synced patients and silently drops
    their RAF scores on every restart.
    """
    import importlib

    seeds = [
        ("seed_openemr_demo", "seed_openemr_demo"),
        ("seed_documents_demo", "seed_documents_demo"),
        ("seed_providers_demo", "seed_providers_demo"),
        ("seed_workflows_demo", "seed_workflows_demo"),
        ("seed_claims_cohorts_demo", "seed"),
    ]
    for mod_name, func_name in seeds:
        try:
            mod = importlib.import_module(f"app.{mod_name}")
            getattr(mod, func_name)()
        except Exception as exc:
            logger.error("Seed %s failed (non-fatal): %s", mod_name, exc)


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
    docs_url="/docs" if settings.app_env != "production" else None,
    redoc_url="/redoc" if settings.app_env != "production" else None,
    openapi_url="/openapi.json" if settings.app_env != "production" else None,
)

# Register exception handlers and rate limiter
register_exception_handlers(app)

# Register all middleware; returns cors_origins needed by emr_gate below
_cors_origins = setup_middleware(app)

# ---------------------------------------------------------------------------
# EMR-gate middleware
#
# When a tenant has zero active EMR connections AND no uploaded patient data,
# all clinical-data endpoints are blocked until a data source is configured.
#
# Exempt prefixes: /api/auth/*, /api/emr/*, /api/admin/*, /api/notifications/*,
#                  /api/pipeline/*, /api/uploads/*, /health, /docs, /redoc,
#                  /openapi.json
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

    try:
        from app.auth import _resolve_user
        user = await _resolve_user(request)
    except Exception:
        user = None

    if user is None:
        return await call_next(request)

    tenant_id = str(user.get("tenant_id") or "")
    if not tenant_id:
        return await call_next(request)

    try:
        from app.services import emr_manager
        conns = emr_manager.list_connections(tenant_id=tenant_id)
        active_count = sum(1 for c in conns if int(c.get("is_active") or 0) == 1)
    except Exception as exc:
        logger.warning("emr_gate: list_connections failed: %s", exc)
        return await call_next(request)

    has_uploaded_data = False
    if active_count == 0:
        try:
            from app.db import raf_cursor as _raf_cursor
            with _raf_cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM patients WHERE tenant_id = %s "
                    "AND data_source = 'upload' AND is_active = 1 LIMIT 1",
                    (tenant_id,),
                )
                has_uploaded_data = cur.fetchone() is not None
        except Exception as exc:
            logger.warning("emr_gate: uploaded-data check failed: %s", exc)

    if active_count == 0 and not has_uploaded_data:
        # CORS headers must be added manually — this middleware sits outside
        # CORSMiddleware, so the browser would otherwise see a network error.
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


# Register all routers
register_routers(app)
