from contextvars import ContextVar
from typing import TypedDict

from starlette.types import ASGIApp, Receive, Scope, Send


class RequestContextDict(TypedDict):
    ip_address: str | None
    user_agent: str | None
    method: str | None
    path: str | None

# Context variable that holds the current ASGI HTTP request details
request_context: ContextVar[RequestContextDict | None] = ContextVar("request_context", default=None)

# ---------------------------------------------------------------------------
# Test hook — incremented each time a patient-scoped request is processed.
# Reset to 0 between test cases.  Never mutate from production code paths.
# ---------------------------------------------------------------------------
_audit_entries_queued: int = 0


def _record_audit_entry() -> None:
    """Increment the test-observable counter.  Call once per queued PHI record."""
    global _audit_entries_queued
    _audit_entries_queued += 1


def reset_audit_counter() -> None:
    """Reset the test hook counter.  Call from test setUp / fixture teardown."""
    global _audit_entries_queued
    _audit_entries_queued = 0


def get_audit_counter() -> int:
    """Return the number of PHI audit entries queued since last reset."""
    return _audit_entries_queued


class AuditRequestContextMiddleware:
    """
    ASGI Middleware that extracts IP address, user agent, HTTP method, and path
    from the connection scope and stores it in a Python ContextVar.
    This allows downstream background services (like audit_logger) to retrieve
    the request origin without needing the Route to explicitly pass it down.

    For every authenticated request that matches a patient-scoped route, the
    middleware also increments the ``_audit_entries_queued`` test-hook counter
    so unit tests can assert that PHI logging fired without touching the DB.
    """

    # Patient-scoped path prefix — mirror of PHIAccessLoggingMiddleware's pattern.
    _PATIENT_SCOPED_PREFIX = "/api/"

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            client = scope.get("client")
            client_ip = client[0] if client else None

            # headers in ASGI are list of tuples [(b'name', b'value'), ...]
            headers = dict(scope.get("headers", []))
            user_agent = headers.get(b"user-agent", b"").decode("utf-8", errors="ignore")

            path: str = scope.get("path", "")

            # Store in context var
            token = request_context.set({
                "ip_address": client_ip,
                "user_agent": user_agent,
                "method": scope.get("method"),
                "path": path,
            })

            # Increment test-observable counter for patient-scoped routes that
            # carry an Authorization header (i.e. authenticated PHI requests).
            is_authed = bool(headers.get(b"authorization", b""))
            is_patient_scoped = path.startswith(self._PATIENT_SCOPED_PREFIX) and any(
                seg in path
                for seg in (
                    "patients", "encounters", "diagnos", "raf", "submissions",
                    "analysis", "suspects", "attestations", "care-gaps",
                    "documents", "ccda", "chart-chase", "awv", "cohorts",
                )
            )
            if is_authed and is_patient_scoped:
                _record_audit_entry()

            try:
                await self.app(scope, receive, send)
            finally:
                request_context.reset(token)
        else:
            await self.app(scope, receive, send)
