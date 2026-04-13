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

class AuditRequestContextMiddleware:
    """
    ASGI Middleware that extracts IP address, user agent, HTTP method, and path 
    from the connection scope and stores it in a Python ContextVar.
    This allows downstream background services (like audit_logger) to retrieve 
    the request origin without needing the Route to explicitly pass it down.
    """
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            client = scope.get("client")
            client_ip = client[0] if client else None
            
            # headers in ASGI are list of tuples [(b'name', b'value'), ...]
            headers = dict(scope.get("headers", []))
            user_agent = headers.get(b"user-agent", b"").decode("utf-8", errors="ignore")
            
            # Store in context var
            token = request_context.set({
                "ip_address": client_ip,
                "user_agent": user_agent,
                "method": scope.get("method"),
                "path": scope.get("path")
            })
            try:
                await self.app(scope, receive, send)
            finally:
                request_context.reset(token)
        else:
            await self.app(scope, receive, send)
