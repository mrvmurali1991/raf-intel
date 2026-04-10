"""
Error monitoring integration.
Supports Sentry SDK when SENTRY_DSN is configured.
Falls back to structured JSON logging when Sentry is not available.
"""
import logging
import traceback
from datetime import datetime, timezone
from app.config import settings

logger = logging.getLogger(__name__)

# Track errors in-memory for the admin dashboard
_recent_errors: list[dict] = []
_MAX_ERRORS = 100

def init_monitoring():
    """Initialize Sentry if DSN is configured. Called once from main.py lifespan."""
    if settings.sentry_dsn:
        try:
            import sentry_sdk
            sentry_sdk.init(dsn=settings.sentry_dsn, environment=settings.sentry_environment, traces_sample_rate=0.1)
            logger.info("Sentry initialized (env=%s)", settings.sentry_environment)
        except ImportError:
            logger.warning("SENTRY_DSN is set but sentry-sdk is not installed. pip install sentry-sdk")
    else:
        logger.info("Sentry not configured (set SENTRY_DSN to enable)")

def capture_error(exc: Exception, context: dict = None):
    """Capture an error to Sentry and local store."""
    error_record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "type": type(exc).__name__,
        "message": str(exc),
        "traceback": traceback.format_exc(),
        "context": context or {},
    }
    _recent_errors.append(error_record)
    if len(_recent_errors) > _MAX_ERRORS:
        _recent_errors.pop(0)

    try:
        import sentry_sdk
        sentry_sdk.capture_exception(exc)
    except ImportError:
        pass

def get_recent_errors(limit=50) -> list[dict]:
    return list(reversed(_recent_errors[-limit:]))

def get_error_stats() -> dict:
    """Return error counts by type for the admin dashboard."""
    from collections import Counter
    types = Counter(e["type"] for e in _recent_errors)
    return {
        "total_errors": len(_recent_errors),
        "error_types": dict(types.most_common(10)),
        "last_error": _recent_errors[-1] if _recent_errors else None,
    }
