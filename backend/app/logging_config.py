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

PHI Audit Log (HIPAA 164.312(b))
--------------------------------
The ``phi_audit`` logger writes to a rotating file at
``/app/logs/phi_access.log`` (50 MB per file, 200 backups -> ~10 GB total
on-disk retention; long-term retention is handled by external log shipping
to immutable storage).  Propagation to the root logger is disabled so PHI
events are never duplicated to stdout / aggregated container logs.

PHI Scrubbing
-------------
The ``JSONFormatter._redact`` pipeline runs on **every** formatted message
(including the ``exception`` traceback string) to strip credentials AND
PHI-like tokens (MRNs, dates, DOB/SSN-prefixed values, name-adjacent
fields).  The level is tunable via ``PHI_SCRUB_LEVEL``:

* ``minimal``    – credentials only (legacy behavior).
* ``standard``   – credentials + MRN/DOB/SSN/date patterns (default).
* ``aggressive`` – everything in ``standard`` plus heuristic name tokens
                   (e.g. capitalized bigrams) — may over-scrub legitimate
                   identifiers like class names, use with care.
"""

import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler


# ---------------------------------------------------------------------------
# PHI scrub patterns
# ---------------------------------------------------------------------------

# Credentials / connection strings — always stripped at every level.
_CREDENTIAL_PATTERNS = (
    re.compile(r"password[=:]\S+", re.IGNORECASE),
    re.compile(r"token[=:]\S+", re.IGNORECASE),
    re.compile(r"api[_-]?key[=:]\S+", re.IGNORECASE),
    re.compile(r"secret[=:]\S+", re.IGNORECASE),
    re.compile(r"credential[s]?[=:]\S+", re.IGNORECASE),
    re.compile(r"authorization[=:]\s*(?:Bearer|Basic)\s+\S+", re.IGNORECASE),
    re.compile(r"redis://:[^@]+@"),
    re.compile(r"mysql://[^@]+@"),
)

# Standard PHI patterns — MRN/DOB/SSN/dates/name-labeled values.
_PHI_STANDARD_PATTERNS = (
    # Labelled PHI fields: DOB: 1952-03-14, MRN: 1234567890, SSN: 123-45-6789, Name: John Smith
    re.compile(r"\b(DOB|Date[-_ ]?of[-_ ]?Birth)\b\s*[:=]\s*\S+(?:\s+\S+)?", re.IGNORECASE),
    re.compile(r"\b(MRN|Medical[-_ ]?Record[-_ ]?Number)\b\s*[:=]\s*\S+", re.IGNORECASE),
    re.compile(r"\b(SSN|Social[-_ ]?Security)\b\s*[:=]\s*\S+", re.IGNORECASE),
    re.compile(r"\b(patient[-_ ]?name|first[-_ ]?name|last[-_ ]?name|full[-_ ]?name)\b\s*[:=]\s*[^,\}\]\"\n]+", re.IGNORECASE),
    # SSN like 123-45-6789
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    # 10-digit MRN-like sequences (word-boundary so we don't chew timestamps).
    re.compile(r"(?<!\d)\d{10}(?!\d)"),
    # US date MM/DD/YYYY and ISO YYYY-MM-DD (when *not* followed by a time
    # component — avoids redacting log timestamps which include "T..").
    re.compile(r"\b(0?[1-9]|1[0-2])/(0?[1-9]|[12]\d|3[01])/(19|20)\d{2}\b"),
    re.compile(r"(?<!\d)(?<!T)(19|20)\d{2}-(0?[1-9]|1[0-2])-(0?[1-9]|[12]\d|3[01])(?!T)(?!\d)"),
)

# Aggressive — heuristically redacts likely person names (two capitalized
# tokens in a row that are not common code identifiers).  False-positive
# prone, opt-in only.
_PHI_AGGRESSIVE_PATTERNS = (
    re.compile(r"\b([A-Z][a-z]{1,15})\s+([A-Z][a-z]{1,15})\b"),
)


def _scrub_patterns_for_level(level: str):
    level = (level or "standard").strip().lower()
    if level == "minimal":
        return _CREDENTIAL_PATTERNS
    if level == "aggressive":
        return _CREDENTIAL_PATTERNS + _PHI_STANDARD_PATTERNS + _PHI_AGGRESSIVE_PATTERNS
    # standard / unknown -> standard
    return _CREDENTIAL_PATTERNS + _PHI_STANDARD_PATTERNS


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

    # Resolved at instance-construction time so unit tests can monkey-patch
    # PHI_SCRUB_LEVEL between formatter instances.
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._sensitive_patterns = _scrub_patterns_for_level(
            os.getenv("PHI_SCRUB_LEVEL", "aggressive")
        )

    # Kept as a class attribute for back-compat with anything that imports it.
    _SENSITIVE_PATTERNS = _CREDENTIAL_PATTERNS + _PHI_STANDARD_PATTERNS

    def _redact(self, text: str) -> str:
        for pattern in self._sensitive_patterns:
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

        # Include exception traceback when present — scrub it *before* it
        # lands in the JSON payload so tracebacks containing PHI never leave
        # the process untouched.
        if record.exc_info and record.exc_info[0]:
            log_entry["exception"] = self._redact(self.formatException(record.exc_info))

        # Inject OpenTelemetry trace context when available.
        try:
            from opentelemetry import trace as _otel_trace

            span = _otel_trace.get_current_span()
            ctx = span.get_span_context()
            if ctx and ctx.trace_id:
                log_entry["trace_id"] = format(ctx.trace_id, "032x")
                log_entry["span_id"] = format(ctx.span_id, "016x")
        except Exception:  # noqa: BLE001 — best-effort guard
            logger.debug("swallowed exception", exc_info=True)

        # Promote well-known extra fields to top-level keys.
        for key in self._EXTRA_FIELDS:
            if hasattr(record, key):
                log_entry[key] = getattr(record, key)

        # Scrub the entire serialized payload — covers free-text in the
        # message and any extras we promoted above.
        return self._redact(json.dumps(log_entry, default=str))


# ---------------------------------------------------------------------------
# PHI audit logger
# ---------------------------------------------------------------------------

_PHI_LOG_PATH = os.getenv("PHI_AUDIT_LOG_PATH", "/app/logs/phi_access.log")


def _install_phi_audit_handler() -> None:
    """Attach a durable RotatingFileHandler to the ``phi_audit`` logger.

    HIPAA 164.312(b) requires PHI access events be retained on durable
    storage.  stdout-only logging is lost on container restart, so we
    rotate to a bind-mounted volume.  50 MB * 200 = ~10 GB retained
    on-disk; promtail/external shipper handles long-term retention.
    """
    phi_logger = logging.getLogger("phi_audit")
    # Avoid double-attaching across reloads.
    for h in phi_logger.handlers:
        if isinstance(h, RotatingFileHandler) and getattr(h, "_phi_audit", False):
            return

    try:
        os.makedirs(os.path.dirname(_PHI_LOG_PATH), exist_ok=True)
        handler = RotatingFileHandler(
            _PHI_LOG_PATH,
            maxBytes=50_000_000,
            backupCount=200,
            encoding="utf-8",
        )
        handler.setFormatter(JSONFormatter())
        handler._phi_audit = True  # type: ignore[attr-defined]
        phi_logger.addHandler(handler)
        phi_logger.setLevel(logging.INFO)
        # CRITICAL: do not propagate PHI events to the root stdout handler.
        phi_logger.propagate = False
    except (OSError, PermissionError) as exc:
        # Fall back to root logger so we at least surface that the durable
        # handler could not be installed — operational alert, not a crash.
        logging.getLogger(__name__).error(
            "PHI audit file handler could not be installed at %s: %s. "
            "Falling back to stdout (HIPAA 164.312(b) compliance at risk).",
            _PHI_LOG_PATH,
            exc,
        )


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
    logging.getLogger("argon2").setLevel(logging.WARNING)

    # Durable PHI audit log — HIPAA 164.312(b).
    _install_phi_audit_handler()


# ---------------------------------------------------------------------------
# Inline smoke test — `python -m app.logging_config`
# ---------------------------------------------------------------------------

if __name__ == "__main__":  # pragma: no cover
    # Force standard level for the test, regardless of environment.
    os.environ["PHI_SCRUB_LEVEL"] = "standard"
    fmt = JSONFormatter()

    sample_traceback = (
        'Traceback (most recent call last):\n'
        '  File "x.py", line 1, in <module>\n'
        '    raise ValueError("patient John Smith DOB: 1952-03-14 '
        'MRN: 1234567890 SSN: 123-45-6789 admitted 03/14/2024")\n'
        'ValueError: lookup failed for John Smith DOB: 1952-03-14'
    )
    scrubbed = fmt._redact(sample_traceback)
    print("SCRUBBED OUTPUT:")
    print(scrubbed)

    # Standard level redacts DOB-labelled value, MRN-labelled value, SSN,
    # the 10-digit MRN sequence, and the US date.  Names are *not* scrubbed
    # at standard level (aggressive only) — keep that documented.
    assert "1952-03-14" not in scrubbed, "DOB ISO date must be redacted"
    assert "1234567890" not in scrubbed, "10-digit MRN must be redacted"
    assert "123-45-6789" not in scrubbed, "SSN must be redacted"
    assert "03/14/2024" not in scrubbed, "US date must be redacted"

    # Aggressive level must additionally redact the person name.
    os.environ["PHI_SCRUB_LEVEL"] = "aggressive"
    aggressive_fmt = JSONFormatter()
    aggressive_scrubbed = aggressive_fmt._redact(sample_traceback)
    assert "John Smith" not in aggressive_scrubbed, "Name must be redacted at aggressive level"

    print("\nOK: scrubber redacted DOB, MRN, SSN, US date at standard; name at aggressive.")
