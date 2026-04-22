"""
OpenTelemetry distributed tracing for RAF Intelligence.

Instruments FastAPI, Celery, MySQL, and Redis with OTLP export.
Gracefully no-ops when OTEL_EXPORTER_OTLP_ENDPOINT is not set or
opentelemetry packages are not installed.

Usage
-----
Call ``init_telemetry(app)`` once from main.py lifespan/startup.
"""

import logging
import os

logger = logging.getLogger(__name__)

_OTEL_INITIALIZED = False


def init_telemetry(app=None) -> None:
    """
    Bootstrap OpenTelemetry tracing.

    When ``settings.otel_exporter_otlp_endpoint`` is set, spans are exported
    via OTLP/gRPC (insecure, short timeout so a missing collector never stalls
    startup).  When the endpoint is absent but APP_ENV is "development", a
    ConsoleSpanExporter is used instead.  Otherwise tracing is a no-op.

    The function is idempotent — safe to call multiple times.
    """
    global _OTEL_INITIALIZED
    if _OTEL_INITIALIZED:
        return

    # Prefer the typed settings value; fall back to raw env so the function
    # works even if called before the app config is fully initialised.
    try:
        from app.config import settings as _settings
        endpoint: str = _settings.otel_exporter_otlp_endpoint or ""
        app_env: str = _settings.app_env
    except Exception:
        endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
        app_env = os.getenv("APP_ENV", "production")

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import SERVICE_NAME, Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor
    except ImportError:
        logger.info("OpenTelemetry disabled: opentelemetry-sdk not installed")
        return

    service_name = os.getenv("OTEL_SERVICE_NAME", "raf-intelligence-backend")
    resource = Resource.create({SERVICE_NAME: service_name})
    provider = TracerProvider(resource=resource)

    if endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,
            )
            # insecure=True and a short timeout so a missing collector never
            # blocks startup beyond a single gRPC connection attempt.
            exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True, timeout=2)
            provider.add_span_processor(BatchSpanProcessor(exporter))
            logger.info("OpenTelemetry: OTLP exporter -> %s", endpoint)
        except ImportError:
            logger.warning(
                "opentelemetry-exporter-otlp-proto-grpc not installed; "
                "OTEL_EXPORTER_OTLP_ENDPOINT ignored"
            )
    elif app_env == "development":
        try:
            from opentelemetry.sdk.trace.export import ConsoleSpanExporter
            provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
            logger.info("OpenTelemetry: ConsoleSpanExporter active (development)")
        except ImportError:
            pass
    else:
        logger.info("OpenTelemetry disabled: OTEL_EXPORTER_OTLP_ENDPOINT not set")
        return

    trace.set_tracer_provider(provider)
    trace.set_tracer_provider(provider)

    # --- Instrument FastAPI ---
    if app is not None:
        try:
            from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

            def _server_request_hook(span, scope):
                """Add tenant_id and user_id as span attributes."""
                if span and span.is_recording():
                    if hasattr(scope, "get"):
                        state = scope.get("state", {})
                        if hasattr(state, "tenant_id"):
                            span.set_attribute("app.tenant_id", str(state.tenant_id))
                        if hasattr(state, "user_id"):
                            span.set_attribute("app.user_id", str(state.user_id))

            FastAPIInstrumentor.instrument_app(
                app,
                server_request_hook=_server_request_hook,
                excluded_urls="health,metrics",
            )
            logger.info("OpenTelemetry: FastAPI instrumented")
        except ImportError:
            logger.warning("opentelemetry-instrumentation-fastapi not installed")

    # --- Instrument Celery ---
    try:
        from opentelemetry.instrumentation.celery import CeleryInstrumentor

        CeleryInstrumentor().instrument()
        logger.info("OpenTelemetry: Celery instrumented")
    except ImportError:
        logger.debug("opentelemetry-instrumentation-celery not installed")

    # --- Instrument MySQL ---
    try:
        from opentelemetry.instrumentation.mysql import MySQLInstrumentor

        MySQLInstrumentor().instrument()
        logger.info("OpenTelemetry: MySQL instrumented")
    except ImportError:
        logger.debug("opentelemetry-instrumentation-mysql not installed")

    # --- Instrument Redis ---
    try:
        from opentelemetry.instrumentation.redis import RedisInstrumentor

        RedisInstrumentor().instrument()
        logger.info("OpenTelemetry: Redis instrumented")
    except ImportError:
        logger.debug("opentelemetry-instrumentation-redis not installed")

    _OTEL_INITIALIZED = True
    logger.info("OpenTelemetry tracing initialized (endpoint=%s)", endpoint)
