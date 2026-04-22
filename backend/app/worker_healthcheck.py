"""
Worker semantic healthcheck.

Checks:
  1. Redis is reachable and responding to PING.
  2. At least one Celery worker node is visible via inspector.ping().

Exit codes:
  0 — healthy
  1 — unhealthy (prints reason to stderr, no PHI)

Separate from any worker.py healthcheck hook Agent-F may add.
"""

import os
import sys


def main() -> int:
    redis_url: str = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

    # --- 1. Redis reachability ---
    try:
        import redis  # type: ignore

        client = redis.Redis.from_url(redis_url, socket_connect_timeout=2, socket_timeout=2)
        if not client.ping():
            print("UNHEALTHY: Redis ping returned False", file=sys.stderr)
            return 1
    except Exception as exc:  # noqa: BLE001
        print(f"UNHEALTHY: Redis unreachable — {type(exc).__name__}", file=sys.stderr)
        return 1

    # --- 2. Celery inspector ---
    try:
        from celery import current_app  # type: ignore  # noqa: PLC0415

        inspector = current_app.control.inspect(timeout=2)
        pong = inspector.ping()
        if not isinstance(pong, dict) or len(pong) == 0:
            print("UNHEALTHY: No Celery worker nodes responded to ping", file=sys.stderr)
            return 1
    except Exception as exc:  # noqa: BLE001
        print(f"UNHEALTHY: Celery inspector error — {type(exc).__name__}", file=sys.stderr)
        return 1

    print("OK: Redis reachable, Celery workers active")
    return 0


if __name__ == "__main__":
    sys.exit(main())
