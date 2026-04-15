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

    Skips silently when:
    - OTEL_EXPORTER_OTLP_ENDPOINT env var is not set
    - opentelemetry packages are not installed
    """
    global _OTEL_INITIALIZED
    if _OTEL_INITIALIZED:
        return

    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        logger.info("OpenTelemetry disabled: OTEL_EXPORTER_OTLP_ENDPOINT not set")
        return

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import Resource, SERVICE_NAME
    except ImportError:
        logger.info("OpenTelemetry disabled: opentelemetry packages not installed")
        return

    # --- Resource ---
    service_name = os.getenv("OTEL_SERVICE_NAME", "raf-intelligence-backend")
    resource = Resource.create({SERVICE_NAME: service_name})

    # --- TracerProvider ---
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True)
    provider.add_span_processor(BatchSpanProcessor(exporter))
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
