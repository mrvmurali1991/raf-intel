"""
Worker health-check script for Docker / Kubernetes liveness probes.

Checks:
  1. Redis connectivity (PING via the configured REDIS_URL)
  2. Celery inspector ping to at least one active worker

Exit codes:
  0 — both checks passed
  1 — one or more checks failed

Usage (Docker-compose healthcheck):
    healthcheck:
      test: ["CMD", "python", "-m", "app.worker"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 20s

Or directly:
    python -m app.worker
"""

from __future__ import annotations

import logging
import os
import sys

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
logger = logging.getLogger("worker-health")

# ---------------------------------------------------------------------------
# Resolve Redis URL from settings or fallback to env var directly so this
# script can run before the full FastAPI config stack is loaded.
# ---------------------------------------------------------------------------

def _redis_url() -> str:
    try:
        from app.config import settings
        return settings.redis_url
    except Exception:
        logger.debug("swallowed exception", exc_info=True)
        return os.getenv("REDIS_URL", "redis://localhost:6379/0")


def check_redis(url: str) -> bool:
    """Return True if Redis responds to PING within 5 seconds."""
    try:
        import redis as redis_lib  # type: ignore[import]
        client = redis_lib.from_url(url, socket_connect_timeout=5, socket_timeout=5)
        result = client.ping()
        if result:
            logger.debug("Redis PING OK")
            return True
        logger.warning("Redis PING returned falsy: %r", result)
        return False
    except ImportError:
        logger.warning("redis package not installed — skipping Redis check")
        return True  # non-fatal: let Celery check determine overall health
    except Exception as exc:
        logger.warning("Redis check failed: %s", exc)
        return False


def check_celery(url: str) -> bool:
    """Return True if at least one Celery worker responds to a ping within 5 s."""
    try:
        from celery import Celery  # type: ignore[import]
        app = Celery(broker=url, backend=url)
        inspector = app.control.inspect(timeout=5)
        active = inspector.ping()
        if active:
            logger.debug("Celery workers responded: %s", list(active.keys()))
            return True
        logger.warning("No Celery workers responded to ping")
        return False
    except ImportError:
        logger.warning("celery package not installed — skipping Celery check")
        return True
    except Exception as exc:
        logger.warning("Celery check failed: %s", exc)
        return False


def main() -> int:
    url = _redis_url()
    redis_ok = check_redis(url)
    celery_ok = check_celery(url)

    if redis_ok and celery_ok:
        print("OK: Redis and Celery workers are healthy")
        return 0

    if not redis_ok:
        print("FAIL: Redis is unreachable", file=sys.stderr)
    if not celery_ok:
        print("FAIL: No Celery workers responded", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
