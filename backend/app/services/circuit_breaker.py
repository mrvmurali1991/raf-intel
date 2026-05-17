"""Simple circuit breaker for external service calls."""
import logging
import threading
import time
from enum import Enum
from functools import wraps

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    CLOSED = "closed"        # Normal operation
    OPEN = "open"            # Failing, reject calls fast
    HALF_OPEN = "half_open"  # Testing recovery


class CircuitBreakerError(Exception):
    """Raised when a circuit breaker is OPEN and the call is rejected."""

    def __init__(self, service_name: str, retry_after: float) -> None:
        self.service_name = service_name
        self.retry_after = retry_after
        super().__init__(
            f"Circuit breaker OPEN for '{service_name}'. "
            f"Retry after {retry_after:.0f}s."
        )


class CircuitBreaker:
    """
    Thread-safe circuit breaker.

    States
    ------
    CLOSED     Normal operation — calls pass through.
    OPEN       Too many recent failures — calls are rejected immediately
               with CircuitBreakerError to avoid piling up.
    HALF_OPEN  recovery_timeout has elapsed — one probe call is allowed
               through.  Success → CLOSED; failure → OPEN again.
    """

    def __init__(
        self,
        service_name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        half_open_max_calls: int = 1,
    ) -> None:
        self.service_name = service_name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time = 0.0
        self._half_open_calls = 0
        self._lock = threading.Lock()

    @property
    def state(self) -> CircuitState:
        with self._lock:
            if (
                self._state == CircuitState.OPEN
                and time.time() - self._last_failure_time >= self.recovery_timeout
            ):
                self._state = CircuitState.HALF_OPEN
                self._half_open_calls = 0
                logger.info("Circuit breaker '%s' → HALF_OPEN", self.service_name)
            return self._state

    def record_success(self) -> None:
        with self._lock:
            self._failure_count = 0
            if self._state != CircuitState.CLOSED:
                logger.info("Circuit breaker '%s' → CLOSED", self.service_name)
            self._state = CircuitState.CLOSED

    def record_failure(self) -> None:
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()
            if self._failure_count >= self.failure_threshold:
                if self._state != CircuitState.OPEN:
                    logger.warning(
                        "Circuit breaker '%s' → OPEN (failures=%d)",
                        self.service_name,
                        self._failure_count,
                    )
                self._state = CircuitState.OPEN

    def __call__(self, func):  # type: ignore[override]
        """Use as a decorator: @openemr_breaker"""

        @wraps(func)
        def wrapper(*args, **kwargs):  # type: ignore[misc]
            current_state = self.state
            if current_state == CircuitState.OPEN:
                elapsed = time.time() - self._last_failure_time
                retry_after = max(0.0, self.recovery_timeout - elapsed)
                raise CircuitBreakerError(self.service_name, retry_after)

            try:
                result = func(*args, **kwargs)
                self.record_success()
                return result
            except CircuitBreakerError:
                # Do not count our own rejection as a failure.
                raise
            except Exception:
                self.record_failure()
                raise

        return wrapper


# ---------------------------------------------------------------------------
# Pre-configured circuit breakers — one instance per external service.
# Tune thresholds per service SLA / expected recovery times.
# ---------------------------------------------------------------------------

#: Direct MySQL to OpenEMR — recovers fairly quickly; 5 failures, 60 s cooldown.
openemr_breaker = CircuitBreaker(
    "openemr",
    failure_threshold=5,
    recovery_timeout=60.0,
)

#: FHIR R4 HTTP calls — slightly stricter; 3 failures, 90 s cooldown.
fhir_breaker = CircuitBreaker(
    "fhir_api",
    failure_threshold=3,
    recovery_timeout=90.0,
)

#: Gemini API — external AI; 3 failures, 120 s cooldown.
gemini_breaker = CircuitBreaker(
    "gemini_api",
    failure_threshold=3,
    recovery_timeout=120.0,
)

#: CMS SFTP — slow external; 3 failures, 3-minute cooldown.
sftp_breaker = CircuitBreaker(
    "cms_sftp",
    failure_threshold=3,
    recovery_timeout=180.0,
)


# ---------------------------------------------------------------------------
# Per-key registry — so we get one circuit per (tenant_id, ehr_base_url)
# instead of a single global CB that taking down one tenant trips for all.
# ---------------------------------------------------------------------------

_keyed_breakers: dict[str, CircuitBreaker] = {}
_keyed_lock = threading.Lock()


def get_breaker(
    key: str,
    *,
    failure_threshold: int = 5,
    recovery_timeout: float = 60.0,
) -> CircuitBreaker:
    """Get-or-create a CircuitBreaker for a stable key (e.g. f'fhir:{tenant}:{url}').
    All callers with the same key share the same breaker state."""
    with _keyed_lock:
        cb = _keyed_breakers.get(key)
        if cb is None:
            cb = CircuitBreaker(
                key, failure_threshold=failure_threshold,
                recovery_timeout=recovery_timeout,
            )
            _keyed_breakers[key] = cb
        return cb


def all_breakers_status() -> list[dict]:
    """Snapshot all keyed circuit-breakers for health probes."""
    with _keyed_lock:
        items = list(_keyed_breakers.items())
    out: list[dict] = []
    for key, cb in items:
        elapsed = time.time() - cb._last_failure_time if cb._last_failure_time else 0
        next_attempt: float | None = None
        if cb._state == CircuitState.OPEN:
            next_attempt = max(0.0, cb.recovery_timeout - elapsed)
        out.append({
            "key": key,
            "state": cb._state.value,
            "consecutive_failures": cb._failure_count,
            "last_failure_time": cb._last_failure_time or None,
            "next_attempt_in_seconds": next_attempt,
        })
    return out
