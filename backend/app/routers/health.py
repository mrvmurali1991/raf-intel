from datetime import datetime, timezone
from typing import Any
import time

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from app.auth import get_current_user, get_tenant_id
from app.config import settings
from app.db import check_connections, get_raf_pool, get_openemr_pool
from app.monitoring import get_error_stats
from app.services.sync_scheduler import get_scheduler_status
from app.services.pipeline_chain import get_latest_pipeline_status

router = APIRouter(tags=["health"])


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _check_raf_db() -> dict[str, Any]:
    """Ping the RAF database and return a status dict with latency."""
    conn = None
    start = time.monotonic()
    try:
        pool = get_raf_pool()
        conn = pool.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        cursor.fetchone()
        cursor.close()
        latency_ms = round((time.monotonic() - start) * 1000, 1)
        return {"status": "up", "latency_ms": latency_ms}
    except Exception as exc:
        return {"status": "down", "error": str(exc)}
    finally:
        if conn is not None:
            conn.close()


def _check_openemr_db() -> dict[str, Any]:
    """Ping the OpenEMR database and return a status dict with latency."""
    conn = None
    start = time.monotonic()
    try:
        pool = get_openemr_pool()
        conn = pool.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        cursor.fetchone()
        cursor.close()
        latency_ms = round((time.monotonic() - start) * 1000, 1)
        return {"status": "up", "latency_ms": latency_ms}
    except Exception as exc:
        return {"status": "down", "error": str(exc)}
    finally:
        if conn is not None:
            conn.close()


def _check_redis() -> dict[str, Any]:
    """Ping Redis and return a status dict with latency."""
    start = time.monotonic()
    try:
        import redis

        r = redis.from_url(settings.redis_url, socket_timeout=2)
        r.ping()
        latency_ms = round((time.monotonic() - start) * 1000, 1)
        return {"status": "up", "latency_ms": latency_ms}
    except ImportError:
        return {"status": "unavailable", "error": "redis package not installed"}
    except Exception as exc:
        return {"status": "down", "error": str(exc)}


def _check_gemini() -> dict[str, Any]:
    """Check whether a Gemini API key is configured."""
    configured = bool(settings.gemini_api_key)
    return {
        "status": "configured" if configured else "missing",
        "model": settings.gemini_model,
    }


_PIPELINE_PHASES = [
    "emr_sync",
    "normalization",
    "ai_analysis",
    "raf_calculation",
    "hcc_hierarchy",
    "suspect_scan",
    "gap_generation",
    "webhook",
]

# Map step names stored in pipeline_runs.steps_completed to canonical phase names.
_STEP_TO_PHASE: dict[str, str] = {
    "sync_encounters": "emr_sync",
    "sync_diagnoses": "normalization",
    "ai_analysis": "ai_analysis",
    "raf_calculation": "raf_calculation",
    "hcc_hierarchy": "hcc_hierarchy",
    "suspect_scan": "suspect_scan",
    "gap_generation": "gap_generation",
    "webhook": "webhook",
}


def _build_pipeline_block(tenant_id: str) -> dict[str, Any]:
    """Return the pipeline section for health/dashboard responses."""
    from app.db import raf_cursor

    # --- pipeline_settings ---------------------------------------------------
    settings_defaults = {
        "pipeline_mode": "auto_basic",
        "ai_analysis_enabled": False,
    }
    try:
        with raf_cursor() as cur:
            cur.execute(
                "SELECT pipeline_mode, ai_analysis_enabled FROM pipeline_settings WHERE tenant_id = %s",
                (tenant_id,),
            )
            row = cur.fetchone()
            if row:
                settings_defaults.update(
                    {k: v for k, v in row.items() if v is not None}
                )
    except Exception:
        pass

    mode: str = settings_defaults["pipeline_mode"]
    ai_enabled: bool = bool(settings_defaults["ai_analysis_enabled"])

    # --- latest run ----------------------------------------------------------
    last_run: dict | None = None
    completed_steps: set[str] = set()
    try:
        last_run = get_latest_pipeline_status(tenant_id)
        if last_run:
            steps = last_run.get("steps_completed") or []
            if isinstance(steps, list):
                completed_steps = set(steps)
    except Exception:
        pass

    # --- phase statuses ------------------------------------------------------
    phases: list[dict[str, str]] = []
    for phase in _PIPELINE_PHASES:
        # Determine which raw step names map to this phase.
        matched_steps = {s for s, p in _STEP_TO_PHASE.items() if p == phase}
        if matched_steps & completed_steps:
            status = "completed"
        elif last_run and last_run.get("current_step") in matched_steps:
            status = "running"
        else:
            status = "pending"
        phases.append({"name": phase, "status": status})

    return {
        "mode": mode,
        "ai_analysis_enabled": ai_enabled,
        "last_run": last_run,
        "phases": phases,
    }


@router.get("/", summary="Root")
def root() -> dict[str, str]:
    return {
        "service": "RAF Intelligence System",
        "version": "2.0.0",
        "status": "running",
        "docs": "/docs",
    }


@router.get("/api/dashboard/stats", summary="Dashboard summary stats")
def dashboard_stats(
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    year: int = Query(
        default=None,
        description="Measurement year to filter by (defaults to current year)",
    ),
) -> dict[str, Any]:
    """Quick population stats for the dashboard."""
    from app.db import raf_cursor
    from datetime import date as _date

    measurement_year = year if year is not None else _date.today().year

    ZERO_RESPONSE = {
        "total_patients": 0,
        "patients_analyzed": 0,
        "average_raf_score": 0.0,
        "coverage_pct": 0.0,
        "total_suspects_open": 0,
        "meat_compliance_pct": 0.0,
        "raf_distribution": [],
        "top_undercoded": [],
    }

    try:
        with raf_cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS cnt FROM emr_connections WHERE is_active = 1 AND tenant_id = %s",
                (tenant_id,),
            )
            has_active = cur.fetchone()["cnt"] > 0
    except Exception:
        return ZERO_RESPONSE

    has_uploaded_data = False
    if not has_active:
        try:
            with raf_cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM patients WHERE data_source = 'upload' AND is_active = 1 AND tenant_id = %s LIMIT 1",
                    (tenant_id,),
                )
                has_uploaded_data = cur.fetchone() is not None
        except Exception:
            pass
        if not has_uploaded_data:
            return ZERO_RESPONSE

    total_patients = 0
    analyzed = 0
    avg_raf = 0.0

    from app.services.emr_manager import ACTIVE_PATIENTS_SUBQUERY, active_patients_subquery

    _ds_filter = (
        " AND data_source = 'upload'" if (not has_active and has_uploaded_data) else ""
    )
    try:
        with raf_cursor() as cur:
            cur.execute(
                f"SELECT COUNT(*) AS cnt FROM patients WHERE is_active = 1 AND tenant_id = %s{_ds_filter}",
                (tenant_id,),
            )
            total_patients = cur.fetchone()["cnt"]
    except Exception:
        pass

    if not has_active and has_uploaded_data:
        _score_filter = "patient_id IN (SELECT id FROM patients WHERE is_active = 1 AND data_source = 'upload' AND tenant_id = %s)"
        _score_params: tuple = (int(tenant_id),)
    else:
        _sf, _sp = active_patients_subquery(int(tenant_id))
        _score_filter = _sf
        _score_params = _sp
    try:
        with raf_cursor() as cur:
            cur.execute(
                f"SELECT COUNT(DISTINCT patient_id) AS cnt FROM raf_scores WHERE {_score_filter} AND raf_scores.tenant_id = %s AND measurement_year = %s",
                (*_score_params, int(tenant_id), measurement_year),
            )
            analyzed = cur.fetchone()["cnt"]
            cur.execute(
                f"SELECT AVG(final_raf) AS avg_raf FROM raf_scores WHERE {_score_filter} AND raf_scores.tenant_id = %s AND measurement_year = %s",
                (*_score_params, int(tenant_id), measurement_year),
            )
            row = cur.fetchone()
            avg_raf = round(float(row["avg_raf"] or 0), 4)
    except Exception:
        pass

    # Suspects count
    total_suspects_open = 0
    try:
        with raf_cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS cnt FROM raf_suspect_conditions WHERE status = 'open' AND tenant_id = %s",
                (tenant_id,),
            )
            total_suspects_open = cur.fetchone()["cnt"]
    except Exception:
        pass

    # RAF distribution buckets
    raf_distribution = []
    try:
        with raf_cursor() as cur:
            cur.execute(
                f"""
                SELECT
                    CASE
                        WHEN final_raf < 0.5 THEN '0.0-0.5'
                        WHEN final_raf < 1.0 THEN '0.5-1.0'
                        WHEN final_raf < 1.5 THEN '1.0-1.5'
                        WHEN final_raf < 2.0 THEN '1.5-2.0'
                        WHEN final_raf < 3.0 THEN '2.0-3.0'
                        ELSE '3.0+'
                    END AS `range`,
                    COUNT(DISTINCT patient_id) AS count
                FROM raf_scores
                WHERE {_score_filter}
                  AND raf_scores.tenant_id = %s
                  AND measurement_year = %s
                GROUP BY `range`
                ORDER BY `range`
                """,
                (*_score_params, int(tenant_id), measurement_year),
            )
            raf_distribution = [dict(r) for r in cur.fetchall()]
    except Exception:
        pass

    # Top undercoded patients (patients with most suspect conditions)
    top_undercoded = []
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT sc.patient_id AS pid,
                       p.first_name AS fname, p.last_name AS lname,
                       rs.final_raf AS raf_score,
                       COUNT(*) AS suspect_count
                FROM raf_suspect_conditions sc
                JOIN patients p ON p.id = sc.patient_id
                LEFT JOIN raf_scores rs ON rs.patient_id = sc.patient_id
                  AND rs.measurement_year = %s
                WHERE sc.status = 'open' AND sc.tenant_id = %s
                GROUP BY sc.patient_id, p.first_name, p.last_name, rs.final_raf
                ORDER BY suspect_count DESC
                LIMIT 10
                """,
                (measurement_year, tenant_id),
            )
            for r in cur.fetchall():
                top_undercoded.append({
                    "id": str(r["pid"]),
                    "pid": str(r["pid"]),
                    "name": f"{r['fname'] or ''} {r['lname'] or ''}".strip(),
                    "raf_score": float(r["raf_score"]) if r.get("raf_score") else 0,
                    "suspect_count": int(r["suspect_count"]),
                })
    except Exception:
        pass

    return {
        "total_patients": total_patients,
        "patients_analyzed": analyzed,
        "average_raf_score": avg_raf,
        "coverage_pct": round(analyzed / total_patients * 100, 1)
        if total_patients
        else 0,
        "total_suspects_open": total_suspects_open,
        "meat_compliance_pct": 0.0,
        "raf_distribution": raf_distribution,
        "top_undercoded": top_undercoded,
        "pipeline": _build_pipeline_block(tenant_id),
    }


@router.get("/api/dashboard/trends", summary="Dashboard trend data")
def dashboard_trends(
    current_user: dict = Depends(get_current_user),
    year: int = Query(
        default=None,
        description="Measurement year to filter by (defaults to current year)",
    ),
) -> dict[str, Any]:
    """
    Compute real period-over-period trend data for the dashboard KPI cards.
    """
    try:
        from app.db import raf_cursor
        from datetime import date as _date

        measurement_year = year if year is not None else _date.today().year

        with raf_cursor() as cur:
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
            "average_raf_score": {
                "current": round(current_avg_raf, 4),
                "prior": round(prior_avg_raf, 4),
                "change_pct": _pct_change(current_avg_raf, prior_avg_raf),
            },
        }

    except Exception:
        return {"period": "30d", "error": True}


@router.get("/health/live", summary="Liveness probe")
def liveness_probe() -> dict[str, Any]:
    """
    Liveness probe — is the process alive?

    Always returns 200 as long as the Python process is running and the
    event loop is responsive.  Load balancers use this to decide whether to
    restart the container; it must never query external dependencies.
    """
    return {"status": "alive"}


@router.get("/health/ready", summary="Readiness probe")
def readiness_probe() -> dict[str, Any]:
    """
    Readiness probe — can the app serve traffic?

    Checks the RAF database (critical) and OpenEMR / Redis / Gemini
    (non-critical).  Returns 200 only when the RAF database is reachable.
    Load balancers use this to decide whether to route requests here.
    """
    checks: dict[str, Any] = {}
    all_ok = True

    # RAF database — critical: app cannot function without it.
    raf_check = _check_raf_db()
    checks["raf_database"] = raf_check
    if raf_check["status"] != "up":
        all_ok = False

    # OpenEMR database — non-critical: app degrades gracefully without it.
    checks["openemr_database"] = _check_openemr_db()

    # Redis — non-critical: Celery/cache is optional.
    checks["redis"] = _check_redis()

    # Gemini — non-critical: key presence check only (no network call).
    checks["gemini"] = _check_gemini()

    payload: dict[str, Any] = {
        "status": "ready" if all_ok else "not_ready",
        "checks": checks,
    }
    if not all_ok:
        return JSONResponse(status_code=503, content=payload)
    return payload


@router.get("/health", summary="Health check")
def health_check(request: Request) -> dict[str, Any]:
    """
    Legacy health check — kept for backward compatibility.

    Returns 200 when all dependencies are healthy, 503 otherwise.
    Prefer /health/live and /health/ready for Kubernetes probes.
    """
    db_status = check_connections()
    all_healthy = all(db_status.values())

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


@router.get("/health/detailed", summary="Detailed health (authenticated)")
def detailed_health(
    request: Request,
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Detailed health check — requires authentication.

    Includes per-database latency, Redis status, Gemini config, DB pool
    sizes, scheduler status, error stats, and process uptime.  Intended
    for operators and monitoring dashboards, not for load-balancer probes.
    """
    # Uptime — start_time is set in the FastAPI lifespan hook.
    start_time: datetime = getattr(
        request.app.state, "start_time", datetime.now(timezone.utc)
    )
    uptime_seconds = round(
        (datetime.now(timezone.utc) - start_time).total_seconds(), 1
    )

    # Dependency checks with latency.
    checks: dict[str, Any] = {
        "raf_database": _check_raf_db(),
        "openemr_database": _check_openemr_db(),
        "redis": _check_redis(),
        "gemini": _check_gemini(),
    }

    # Process-level metrics (requires psutil — optional dependency).
    process_info: dict[str, Any] = {}
    try:
        import psutil

        proc = psutil.Process()
        process_info["memory_mb"] = round(proc.memory_info().rss / 1024 / 1024, 1)
        process_info["cpu_percent"] = proc.cpu_percent(interval=None)
        process_info["threads"] = proc.num_threads()
    except ImportError:
        pass
    except Exception:
        pass

    overall_status = (
        "healthy"
        if checks["raf_database"]["status"] == "up"
        else "degraded"
    )

    tenant_id: str = get_tenant_id(current_user)

    return {
        "status": overall_status,
        "uptime_seconds": uptime_seconds,
        "started_at": start_time.isoformat(),
        "app_env": settings.app_env,
        "checks": checks,
        "scheduler": get_scheduler_status(),
        "monitoring": get_error_stats(),
        "process": process_info,
        "pipeline": _build_pipeline_block(tenant_id),
        "request_id": getattr(request.state, "request_id", None),
    }


@router.get("/metrics", include_in_schema=False)
async def metrics(
    request: Request, current_user: dict = Depends(get_current_user)
) -> dict[str, Any]:
    """
    Lightweight application metrics for operational monitoring.
    """
    start_time: datetime = getattr(
        request.app.state, "start_time", datetime.now(timezone.utc)
    )
    uptime_seconds = (datetime.now(timezone.utc) - start_time).total_seconds()
    request_count: int = getattr(request.app.state, "request_count", 0)

    payload: dict[str, Any] = {
        "uptime_seconds": round(uptime_seconds, 1),
        "requests_total": request_count,
        "app_env": settings.app_env,
    }
    try:
        import psutil

        proc = psutil.Process()
        payload["memory_mb"] = round(proc.memory_info().rss / 1024 / 1024, 1)
        payload["cpu_percent"] = proc.cpu_percent(interval=None)
    except ImportError:
        pass
    except Exception:
        pass

    return payload
