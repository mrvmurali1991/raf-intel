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

import asyncio
import logging
import os
import subprocess
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.config import settings
from app.db import check_connections, shutdown_db_executor
from app.exception_handlers import register_exception_handlers
from app.logging_config import configure_logging
from app.middleware import setup_middleware
from app.metrics import init_metrics
from app.monitoring import init_monitoring
from app.router_registry import register_routers
from app.telemetry import init_telemetry, instrument_app

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
    {"name": "radv-audit-runs", "description": "RADV Audit Defense Workflow — sampling, evidence packaging, MAO-004 re-submission, exposure simulator, evidence export"},
    {"name": "bi_export", "description": "BI Tools Export — Tableau, PowerBI, Looker, Metabase, OData, CSV/JSON/Excel"},
    {"name": "health", "description": "Health checks and system status"},
    {"name": "icd10", "description": "ICD-10-CM code lookup and validation"},
    {"name": "compliance", "description": "HIPAA compliance status"},
    {"name": "admin", "description": "Administrative operations: data retention, purge"},
    {"name": "bulk_ingest", "description": "Bulk FHIR ingest — panel onboarding via $export or NDJSON upload"},
    {"name": "worklist", "description": "Coder worklist / review queue and productivity metrics"},
    {"name": "qa-review", "description": "Multi-rater QA review workflow — primary/secondary/tier-2 adjudication of accepted suspects"},
    {"name": "realtime", "description": "Real-time dashboard: SSE stream, WebSocket, alerts, KPI, dashboard configs"},
]


def _check_permission_resource_coverage() -> None:
    """At boot, verify every canonical resource has a `role_default_permissions`
    row for the admin role. Catches schema drift (the ENUM-too-narrow bug
    that silently 403'd clinicians for weeks)."""
    from app.db import raf_cursor
    from app.permission_resources import RESOURCE_NAMES
    try:
        with raf_cursor() as cur:
            cur.execute(
                "SELECT DISTINCT resource FROM role_default_permissions"
            )
            in_db = {r["resource"] for r in cur.fetchall() or []}
    except Exception as exc:  # noqa: BLE001
        logger.warning("permission_resource coverage probe skipped: %s", exc)
        return
    missing = sorted(RESOURCE_NAMES - in_db)
    extra = sorted(in_db - RESOURCE_NAMES - {""})
    if missing:
        logger.warning(
            "permission resources MISSING from DB (will 403 silently): %s",
            ", ".join(missing) or "(none)",
        )
    if extra:
        logger.info(
            "DB has extra permission resources not in code allowlist: %s",
            ", ".join(extra),
        )


# ---------------------------------------------------------------------------
# Lifespan – startup / shutdown
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Verify DB connectivity on startup and log a summary."""
    logger.info("RAF Intelligence backend starting...")
    init_monitoring()

    app.state.start_time = datetime.now(timezone.utc)
    app.state.request_count = 0

    # Audit chain boot-time integrity check — Patient Safety round-2 fix.
    # Must run before any request handler is active.  Raises RuntimeError
    # (exit non-zero) if the JSONL was deleted after DB events were committed.
    try:
        from app.services.immutable_audit import verify_chain_on_boot
        verify_chain_on_boot()
        logger.info("Audit chain boot check: OK")
    except RuntimeError as _audit_boot_exc:
        logger.critical("Audit chain boot check FAILED: %s", _audit_boot_exc)
        raise  # propagates — uvicorn/gunicorn will exit non-zero

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

    # ------------------------------------------------------------------
    # Startup dependency validation
    # ------------------------------------------------------------------

    # 1. RAF DB — critical. Log clearly so the operator knows immediately.
    raf_db_ok = db_status.get("raf", False)
    if not raf_db_ok:
        logger.warning(
            "STARTUP WARNING: RAF database is unreachable. "
            "Most API endpoints will fail until the database is available."
        )
    else:
        logger.info("Startup check [raf_db]: OK")

    # 2. Redis — non-critical (used for caching / rate-limiting). Log but
    #    do not prevent startup.
    try:
        import redis as _redis_module

        _r = _redis_module.from_url(settings.redis_url, socket_timeout=3)
        _r.ping()
        logger.info("Startup check [redis]: OK")
    except ImportError:
        logger.info("Startup check [redis]: package not installed — skipped")
    except Exception as _redis_exc:  # noqa: BLE001
        logger.warning(
            "Startup check [redis]: UNREACHABLE (%s). "
            "Caching and rate-limiting features may be degraded.",
            _redis_exc,
        )

    # 3. OpenEMR — non-critical. A warning is sufficient; the app operates in
    #    a degraded state (no EMR data) until the connection is restored.
    openemr_ok = db_status.get("openemr", False)
    if not openemr_ok:
        logger.warning(
            "Startup check [openemr]: UNREACHABLE. "
            "EMR-dependent features (FHIR sync, clinical notes) will be "
            "unavailable until the OpenEMR database is reachable."
        )
    else:
        logger.info("Startup check [openemr]: OK")

    _check_alembic_migrations()

    if settings.app_env in ("development", "demo"):
        _run_demo_seeds()
    else:
        logger.info("Skipping demo seeds (app_env=%s)", settings.app_env)

    logger.info("RAF Intelligence backend ready on port %s", settings.app_port)
    logger.info("NER mode: Gemini API (no local models needed)")

    # Coverage check: every resource used in require_permission(...) must
    # exist in role_default_permissions, and every canonical resource must
    # also be granted to at least the admin role. Catches the 24-missing-
    # resource bug class at boot instead of in production 403s.
    try:
        _check_permission_resource_coverage()
    except Exception as exc:  # noqa: BLE001
        logger.error("permission resource coverage check failed: %s", exc)

    from app.services.pipeline_chain import setup_pipeline_chain
    from app.services.sync_scheduler import start_scheduler, stop_scheduler

    setup_pipeline_chain()
    start_scheduler()

    # Auto-sync polling task — runs only when AUTO_SYNC_ENABLED=true.
    _auto_sync_task = None
    if settings.auto_sync_enabled:
        from app.services.auto_sync_loop import run_auto_sync_loop

        _auto_sync_task = asyncio.create_task(
            run_auto_sync_loop(interval=settings.auto_sync_interval_seconds),
            name="auto_sync_loop",
        )
        logger.info(
            "auto_sync: background task started (interval=%ds)",
            settings.auto_sync_interval_seconds,
        )
    else:
        logger.info("auto_sync: disabled (AUTO_SYNC_ENABLED=false)")

    # Recover zombie jobs left in RUNNING/QUEUED state by a previous crash
    # or restart. FastAPI BackgroundTasks are in-process and lost on restart,
    # so without this sweep callers polling /api/analysis/jobs/{id} would wait
    # forever. Guarded so a failure here never prevents boot.
    try:
        from app.services.job_service import recover_stale_jobs

        recovered = recover_stale_jobs(stale_after_hours=1)
        if recovered:
            logger.warning(
                "Startup recovery: marked %d stale raf_jobs rows as FAILED", recovered
            )
        else:
            logger.info("Startup recovery: no stale raf_jobs rows found.")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Startup recovery of stale jobs failed (non-fatal): %s", exc)

    yield  # application runs

    if _auto_sync_task is not None and not _auto_sync_task.done():
        _auto_sync_task.cancel()
        try:
            await _auto_sync_task
        except asyncio.CancelledError:
            pass
        logger.info("auto_sync: background task stopped.")

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
                check=False, cwd=str(backend_dir),
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
            logger.debug("swallowed exception", exc_info=True)
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

    # If BOTH invocations failed, the alembic binary/env is broken — not drift.
    # Downgrade to a warning and skip the check unless STRICT_MIGRATIONS=true.
    if cur_rc != 0 and head_rc != 0:
        logger.warning(
            "Alembic probe unavailable (current rc=%s, heads rc=%s) — skipping drift check. %s",
            cur_rc,
            head_rc,
            (cur_err.strip() or head_err.strip()),
        )
        if strict:
            raise RuntimeError(
                f"Refusing to start: alembic probe unavailable (current rc={cur_rc}, "
                f"heads rc={head_rc}). Set STRICT_MIGRATIONS=false to bypass."
            )
        return

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

    seed_panel_demo runs FIRST — it owns the core patient panel (patient_data,
    raf_patient_hcc, recapture_gaps, raf_suspect_conditions, raf_scores,
    normalized_encounters).  It is a no-op when is_demo=1 rows already exist,
    so a ``docker compose up`` restart after a non-destructive stop never
    duplicates data.  A ``docker compose down -v`` wipe triggers a full reseed
    on the next ``up``, keeping the demo panel resilient to volume rebuilds.
    """
    import importlib

    seeds = [
        # Panel seed runs first — idempotency guard: COUNT(is_demo=1) >= 12
        ("seed_panel_demo", "seed_panel_demo"),
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

# Register observability (must happen BEFORE the app receives its first request —
# Starlette refuses add_middleware after startup, so keep these at module scope).
init_metrics(app)
init_telemetry(app)

# Apply OTel auto-instrumentation (FastAPI routes / outbound requests / MySQL).
# init_telemetry() above already covers most of this when an OTLP endpoint is
# configured; instrument_app() is the thinner helper kept idempotent so calling
# both is safe. Wrapped in try/except so a missing optional package can never
# block startup. See docs/TRACING.md.
try:
    instrument_app(app)
except Exception as _otel_exc:  # noqa: BLE001 - tracing must never crash boot
    logger.warning("instrument_app skipped: %s", _otel_exc)

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
    "/metrics",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/",
)
_EMR_GATE_ALLOWED_EXACT = {"/", "/health", "/metrics"}


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
        logger.debug("swallowed exception", exc_info=True)
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


# ---------------------------------------------------------------------------
# Prometheus /metrics — auth-gated to prevent public scraping.
#
# An existing /metrics endpoint is registered by app.metrics.init_metrics.
# We add a thin middleware that runs ahead of it and enforces HTTP Basic
# Auth using METRICS_BASIC_AUTH_USER / METRICS_BASIC_AUTH_PASSWORD env
# vars (also exposed as ``settings.metrics_basic_auth`` for callers that
# prefer the typed config object).  If either var is unset, the endpoint
# behaves as before (closed via network policy only) so existing scrape
# configs aren't silently broken on upgrade.
#
# Reminder: Prometheus label cardinality is unbounded — NEVER include
# patient_id, MRN, or any per-user identifier as a label value.  Existing
# metric definitions in app/metrics.py use coarse labels (method, path,
# status, phase) only.
# ---------------------------------------------------------------------------

from prometheus_client import make_asgi_app, Counter, Histogram  # noqa: E402,F401
from starlette.middleware.base import BaseHTTPMiddleware  # noqa: E402

# Auth-gated /metrics — protect from public scraping; allowlist via env IP list or basic auth
metrics_app = make_asgi_app()


def _metrics_basic_auth_expected() -> str:
    """Return the expected ``Authorization: Basic <b64>`` header, or '' when unset."""
    user = os.getenv("METRICS_BASIC_AUTH_USER", "")
    pw = os.getenv("METRICS_BASIC_AUTH_PASSWORD", "")
    cfg = getattr(settings, "metrics_basic_auth", "") or ""
    if cfg:
        return cfg
    if not user or not pw:
        return ""
    import base64
    return "Basic " + base64.b64encode(f"{user}:{pw}".encode()).decode()


class _MetricsAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/metrics":
            expected = _metrics_basic_auth_expected()
            if expected:
                provided = request.headers.get("Authorization", "")
                if provided != expected:
                    return JSONResponse(
                        status_code=401,
                        content={"detail": "Unauthorized"},
                        headers={"WWW-Authenticate": 'Basic realm="metrics"'},
                    )
        return await call_next(request)


app.add_middleware(_MetricsAuthMiddleware)


# Register all routers
register_routers(app)

# ---------------------------------------------------------------------------
# EDI generation router (Gap #7).  Registered here so it is independent of
# router_registry.py — that file is under heavy churn from other branches.
# ---------------------------------------------------------------------------
try:
    import copy as _copy_for_edi
    from app.routers import edi_generation as _edi_gen

    app.include_router(_edi_gen.router, include_in_schema=False)
    _edi_v1 = _copy_for_edi.copy(_edi_gen.router)
    if _edi_v1.prefix.startswith("/api/"):
        _edi_v1.prefix = "/api/v1/" + _edi_v1.prefix[len("/api/"):]
    app.include_router(_edi_v1)
except Exception as _edi_exc:  # pragma: no cover
    logger.warning("EDI router registration failed: %s", _edi_exc)
