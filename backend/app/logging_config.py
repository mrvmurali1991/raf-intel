"""
Structured JSON logging configuration for RAF Intelligence.

Usage
-----
Call ``configure_logging()`` once at application startup (before any other
logging calls).  In development (APP_ENV != "production") a human-readable
format is used.  In production every log record is emitted as a single-line
JSON object suitable for ingestion by ELK, Datadog, CloudWatch Logs, etc.

Extra fields
------------
Any logger.info/warning/error call that passes ``extra={"request_id": ...,
"user_id": ..., "patient_id": ..., "tenant_id": ..., "duration_ms": ...}``
will have those fields promoted to top-level keys in the JSON payload.
"""

import json
import logging
import os
import re
import sys
from datetime import datetime, timezone


class JSONFormatter(logging.Formatter):
    """Emit each log record as a single-line JSON object."""

    # Fields to promote from ``record`` extras to top-level JSON keys.
    _EXTRA_FIELDS = (
        "request_id",
        "user_id",
        "patient_id",
        "tenant_id",
        "duration_ms",
        "trace_id",
        "span_id",
    )

    # Regex patterns for sensitive values that must be redacted from any
    # log payload before emission.
    _SENSITIVE_PATTERNS = (
        re.compile(r"password[=:]\S+", re.IGNORECASE),
        re.compile(r"token[=:]\S+", re.IGNORECASE),
        re.compile(r"api[_-]?key[=:]\S+", re.IGNORECASE),
        re.compile(r"secret[=:]\S+", re.IGNORECASE),
        re.compile(r"credential[s]?[=:]\S+", re.IGNORECASE),
        re.compile(r"authorization[=:]\s*(?:Bearer|Basic)\s+\S+", re.IGNORECASE),
        re.compile(r"redis://:[^@]+@"),
        re.compile(r"mysql://[^@]+@"),
    )

    @classmethod
    def _redact(cls, text: str) -> str:
        for pattern in cls._SENSITIVE_PATTERNS:
            text = pattern.sub("***REDACTED***", text)
        return text

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Include exception traceback when present.
        if record.exc_info and record.exc_info[0]:
            log_entry["exception"] = self.formatException(record.exc_info)

        # Inject OpenTelemetry trace context when available.
        try:
            from opentelemetry import trace as _otel_trace

            span = _otel_trace.get_current_span()
            ctx = span.get_span_context()
            if ctx and ctx.trace_id:
                log_entry["trace_id"] = format(ctx.trace_id, "032x")
                log_entry["span_id"] = format(ctx.span_id, "016x")
        except Exception:
            pass

        # Promote well-known extra fields to top-level keys.
        for key in self._EXTRA_FIELDS:
            if hasattr(record, key):
                log_entry[key] = getattr(record, key)

        return self._redact(json.dumps(log_entry, default=str))


def configure_logging() -> None:
    """
    Replace the root logger's handlers with a single StreamHandler.

    - Production  → JSONFormatter (machine-parseable)
    - Development → human-readable timestamped format

    Safe to call multiple times; the root handler list is replaced on each
    call so the formatter reflects the current APP_ENV.
    """
    app_env = os.getenv("APP_ENV", "development")
    log_format = os.getenv("LOG_FORMAT", "")  # "json" forces JSON in any env
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    if app_env == "production" or log_format.lower() == "json":
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s  %(levelname)-8s %(name)s  %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )

    # Replace any existing handlers (avoids duplicate output on reload).
    root.handlers = [handler]

    # Silence noisy third-party loggers that add no operational value.
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("hccinfhir").setLevel(logging.WARNING)
    logging.getLogger("multipart").setLevel(logging.WARNING)
    logging.getLogger("passlib").setLevel(logging.WARNING)
