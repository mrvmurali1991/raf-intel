"""
Token-bucket rate limiter for external API calls.

Used to prevent quota exhaustion when batch-processing large numbers of
encounters through the Gemini API. Each call to acquire() blocks until a
token is available (or the timeout elapses), smoothing the request rate to
the configured sustained rate while still allowing short bursts.

Environment variables
---------------------
GEMINI_RATE_LIMIT_RPS   Sustained requests per second (default: 10)
GEMINI_RATE_LIMIT_BURST Maximum burst size / bucket capacity (default: 20)

Gemini quota reference
----------------------
Free tier  : 60 RPM  (~1 RPS)
Pay-as-you-go: 1000 RPM (~16 RPS)
The defaults (10 RPS / burst 20) are conservative for paid usage and safe
for free-tier when a single worker runs sequentially.
"""

import logging
import os
import threading
import time

logger = logging.getLogger(__name__)


class TokenBucketRateLimiter:
    """Thread-safe token-bucket rate limiter for external API calls."""

    def __init__(self, rate: float, burst: int) -> None:
        """
        Args:
            rate:  Sustained token replenishment rate in tokens per second.
            burst: Maximum bucket capacity (peak burst size).
        """
        if rate <= 0:
            raise ValueError(f"rate must be positive, got {rate}")
        if burst < 1:
            raise ValueError(f"burst must be >= 1, got {burst}")

        self.rate = rate
        self.burst = burst
        self._tokens: float = float(burst)
        self._last_refill: float = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self, timeout: float = 30.0) -> bool:
        """
        Block until a token is available or *timeout* seconds elapse.

        Returns True when a token is acquired, False on timeout.
        """
        deadline = time.monotonic() + timeout
        sleep_interval = min(0.1, 1.0 / self.rate)

        while True:
            with self._lock:
                self._refill()
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return True

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(sleep_interval, remaining))

    def _refill(self) -> None:
        """Refill tokens based on elapsed time since last refill. Must be called under lock."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(float(self.burst), self._tokens + elapsed * self.rate)
        self._last_refill = now

    @property
    def current_tokens(self) -> float:
        """Snapshot of current token count (informational, not guaranteed)."""
        with self._lock:
            self._refill()
            return self._tokens


# ---------------------------------------------------------------------------
# Module-level singleton — imported by skill_pipeline and any other caller
# that makes Gemini API requests.
# ---------------------------------------------------------------------------

gemini_limiter = TokenBucketRateLimiter(
    rate=float(os.environ.get("GEMINI_RATE_LIMIT_RPS", "10")),
    burst=int(os.environ.get("GEMINI_RATE_LIMIT_BURST", "20")),
)
