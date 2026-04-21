"""
Prometheus metrics for RAF Intelligence.

Exposes application metrics via a ``/metrics`` endpoint and provides
middleware that automatically tracks HTTP request counts and durations.

Usage
-----
1. Call ``init_metrics(app)`` from main.py to register the middleware
   and ``/metrics`` route.
2. Use the module-level counters/gauges from other modules::

       from app.metrics import PIPELINE_RUNS, ACTIVE_CELERY_TASKS
       PIPELINE_RUNS.labels(status="success", phase="ner").inc()
"""

import logging
import time

from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

try:
    from prometheus_client import (
        CONTENT_TYPE_LATEST,
        CollectorRegistry,
        Counter,
        Gauge,
        Histogram,
        generate_latest,
    )

    REGISTRY = CollectorRegistry(auto_describe=True)

    # ---- HTTP metrics ----
    HTTP_REQUESTS_TOTAL = Counter(
        "http_requests_total",
        "Total HTTP requests",
        ["method", "path", "status"],
        registry=REGISTRY,
    )
    HTTP_REQUEST_DURATION = Histogram(
        "http_request_duration_seconds",
        "HTTP request duration in seconds",
        ["method", "path"],
        buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
        registry=REGISTRY,
    )

    # ---- Application metrics ----
    PIPELINE_RUNS = Counter(
        "pipeline_runs_total",
        "Total pipeline runs",
        ["status", "phase"],
        registry=REGISTRY,
    )
    ACTIVE_CELERY_TASKS = Gauge(
        "active_celery_tasks",
        "Number of currently active Celery tasks",
        registry=REGISTRY,
    )
    DB_POOL_ACTIVE = Gauge(
        "db_pool_active_connections",
        "Number of active database pool connections",
        registry=REGISTRY,
    )
    RAF_CALCULATIONS = Counter(
        "raf_calculations_total",
        "Total RAF score calculations",
        registry=REGISTRY,
    )

    # ---- Cache metrics ----
    CACHE_HITS = Counter(
        "cache_hits_total",
        "Total cache hits in tenant_cached decorator",
        ["entity"],
        registry=REGISTRY,
    )
    CACHE_MISSES = Counter(
        "cache_misses_total",
        "Total cache misses in tenant_cached decorator",
        ["entity"],
        registry=REGISTRY,
    )

    _PROMETHEUS_AVAILABLE = True
except ImportError:
    _PROMETHEUS_AVAILABLE = False
    logger.info("prometheus_client not installed; metrics disabled")

    class _NoOpLabels:
        def inc(self, amount: float = 1) -> None:
            pass

    class _NoOpCounter:
        def labels(self, **_kw) -> "_NoOpLabels":
            return _NoOpLabels()

        def inc(self, amount: float = 1) -> None:
            pass

    CACHE_HITS = _NoOpCounter()   # type: ignore[assignment]
    CACHE_MISSES = _NoOpCounter()  # type: ignore[assignment]


def _normalize_path(path: str) -> str:
    """Collapse numeric path segments to reduce cardinality."""
    parts = path.strip("/").split("/")
    normalized = []
    for part in parts:
        if part.isdigit():
            normalized.append(":id")
        else:
            normalized.append(part)
    return "/" + "/".join(normalized) if normalized else "/"


class PrometheusMiddleware(BaseHTTPMiddleware):
    """Track HTTP request count and duration for every request."""

    _SKIP_PATHS = {"/metrics", "/health", "/docs", "/redoc", "/openapi.json"}

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path in self._SKIP_PATHS:
            return await call_next(request)

        method = request.method
        normalized = _normalize_path(path)
        start = time.perf_counter()

        response = await call_next(request)

        duration = time.perf_counter() - start
        status = str(response.status_code)

        HTTP_REQUESTS_TOTAL.labels(method=method, path=normalized, status=status).inc()
        HTTP_REQUEST_DURATION.labels(method=method, path=normalized).observe(duration)

        return response


def init_metrics(app: FastAPI) -> None:
    """Register Prometheus middleware and /metrics endpoint."""
    if not _PROMETHEUS_AVAILABLE:
        logger.info("Prometheus metrics not initialized (prometheus_client missing)")
        return

    app.add_middleware(PrometheusMiddleware)

    @app.get("/metrics", include_in_schema=False)
    async def metrics_endpoint():
        """Prometheus scrape endpoint. No auth — restrict via network policy."""
        return Response(
            content=generate_latest(REGISTRY),
            media_type=CONTENT_TYPE_LATEST,
        )

    logger.info("Prometheus metrics endpoint registered at /metrics")
