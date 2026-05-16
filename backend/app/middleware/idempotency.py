"""
Idempotency-Key dependency for write endpoints.

This module provides a FastAPI *dependency* (not a global middleware) that
implements the standard ``Idempotency-Key`` header contract documented in
``API_CHANGELOG``:

  1. Client picks a UUID (or any opaque, unique string) and sends it as the
     ``Idempotency-Key`` request header on a write request (POST / PUT /
     PATCH / DELETE).
  2. The first request to arrive with a given key is processed normally;
     the resulting response body + status code are cached in Redis under a
     SHA-256 hash of ``tenant_id + key + method + path`` for 24 hours.
  3. Any duplicate request with the same key (same tenant + same route)
     short-circuits with the cached response, so retries / network blips /
     button-double-clicks never create duplicate writes.

Why a dependency instead of a global middleware?
------------------------------------------------
A global middleware would have to inspect every single request, including
GETs and health checks, and would have no easy way to know *which* routes
opt in to idempotency. A dependency is explicit: each route that wants
idempotency does::

    from app.middleware.idempotency import idempotency_key_dependency

    @router.post(
        "/api/claims",
        dependencies=[Depends(idempotency_key_dependency())],
    )
    def submit_claim(...):
        ...

This file intentionally does NOT wire the dependency into any router — it
just exposes the factory. Wiring it onto specific write endpoints is the
job of a follow-up change once each route's idempotency contract has been
reviewed.

Redis fallback behaviour
------------------------
The dependency reuses the application's existing Redis client (``app.cache``).
When Redis is unavailable, the dependency degrades gracefully: it does not
block the request, it simply skips dedup. Production deployments always
have Redis available (see ``app.cache._get_redis``), so this fallback only
matters in CI / local development.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable
from typing import Any

from fastapi import Depends, HTTPException, Request, Response, status

from app.auth import get_current_user, get_tenant_id
from app.cache import _get_redis  # canonical app-wide Redis client

logger = logging.getLogger(__name__)

# Header name per RFC draft-ietf-httpapi-idempotency-key-header.
IDEMPOTENCY_HEADER = "Idempotency-Key"

# Cached responses live for 24 hours — long enough to cover client retries
# after a partial outage but short enough to bound the Redis footprint.
IDEMPOTENCY_TTL_SECONDS = 24 * 60 * 60

# Redis key namespace so idempotency entries are easy to identify / flush
# without touching the rest of the cache.
IDEMPOTENCY_KEY_PREFIX = "idem:"

# Reasonable bounds on the client-supplied key — long enough for UUIDs and
# ULIDs but short enough to reject pathological inputs.
_MIN_KEY_LEN = 8
_MAX_KEY_LEN = 255


def _hash_idempotency_key(tenant_id: str, key: str, method: str, path: str) -> str:
    """
    Build the Redis lookup key for an idempotent request.

    The hash inputs are joined with NUL bytes so two distinct triples can
    never collide via concatenation tricks (e.g. tenant ``"1"`` + key
    ``"23abc"`` vs tenant ``"12"`` + key ``"3abc"``).

    Returns:
        e.g. ``"idem:9f8c...e1"``
    """
    payload = "\x00".join((tenant_id, key, method.upper(), path)).encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    return f"{IDEMPOTENCY_KEY_PREFIX}{digest}"


def idempotency_key_dependency() -> Callable[..., None]:
    """
    Return a FastAPI dependency that enforces ``Idempotency-Key`` semantics.

    Usage example::

        from fastapi import Depends
        from app.middleware.idempotency import idempotency_key_dependency

        @router.post(
            "/api/claims/submit",
            dependencies=[Depends(idempotency_key_dependency())],
            response_model=ClaimSubmissionResponse,
        )
        def submit_claim(payload: ClaimSubmission, ...):
            ...

    Behaviour:
      - If the request omits the header, the dependency is a no-op (we do
        not force every write to carry an idempotency key — that's the
        caller's prerogative).
      - If a cached response exists for ``sha256(tenant + key + method +
        path)``, the dependency raises an ``HTTPException`` whose body
        replays the cached response. The handler body never runs, so no
        duplicate write occurs.
      - If no cached response exists, the request flows through and the
        route handler is responsible for storing the response (a future
        commit will wrap this in an ``after_response`` hook; for now the
        dependency provides only the read-side check, which is the
        important half of the safety net for retries).
    """

    async def _check(
        request: Request,
        current_user: dict = Depends(get_current_user),
    ) -> None:
        raw_key = request.headers.get(IDEMPOTENCY_HEADER)
        if not raw_key:
            # Header not supplied → idempotency is opt-in, nothing to do.
            return

        key = raw_key.strip()
        if not (_MIN_KEY_LEN <= len(key) <= _MAX_KEY_LEN):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"{IDEMPOTENCY_HEADER} must be between {_MIN_KEY_LEN} and "
                    f"{_MAX_KEY_LEN} characters."
                ),
            )

        tenant_id = str(get_tenant_id(current_user) or "0")
        redis_key = _hash_idempotency_key(
            tenant_id=tenant_id,
            key=key,
            method=request.method,
            path=request.url.path,
        )

        client = _get_redis()
        if not client:
            # Redis not available — skip dedup silently. We log so prod
            # monitoring can flag prolonged outages, but we never block the
            # request just because the cache layer is down.
            logger.debug(
                "idempotency: redis unavailable, skipping dedup for key=%s",
                redis_key,
            )
            return

        try:
            cached = client.get(redis_key)
        except Exception as exc:
            logger.warning("idempotency: redis GET failed (%s) — skipping", exc)
            return

        if cached:
            # Duplicate request — replay the cached response. We raise an
            # HTTPException so the framework's exception handler short-
            # circuits the route body. The cached payload travels via the
            # exception's ``detail`` field; FastAPI serialises that into
            # the response body, and we mark the response with a header so
            # clients can distinguish a replay from a fresh write.
            try:
                payload = json.loads(cached)
            except (TypeError, ValueError):
                payload = {"replayed": True}

            raise HTTPException(
                status_code=payload.get("status_code", status.HTTP_200_OK),
                detail=payload.get("body", payload),
                headers={"Idempotent-Replay": "true"},
            )

        # No cached response — the route handler runs normally. Storing the
        # successful response back into Redis is intentionally left to a
        # follow-up wrapper so we can do it in an ``after_response`` hook
        # and only on 2xx outcomes.
        request.state.idempotency_redis_key = redis_key

    return _check


def store_idempotent_response(
    request: Request,
    response: Response,
    body: Any,
) -> None:
    """
    Helper for write handlers to persist their response under the request's
    idempotency key.

    Call this from a route handler (or a small response-hook wrapper) once
    the write has succeeded::

        @router.post("/api/claims", dependencies=[Depends(idempotency_key_dependency())])
        def submit_claim(request: Request, ...):
            result = svc.do_work(...)
            store_idempotent_response(request, response, result.model_dump())
            return result

    The cached payload is keyed under the same Redis key the dependency
    looked up, so a subsequent duplicate request short-circuits on the
    next call.
    """
    redis_key = getattr(request.state, "idempotency_redis_key", None)
    if not redis_key:
        return  # request did not carry an idempotency key — nothing to cache

    client = _get_redis()
    if not client:
        return

    payload = {
        "status_code": response.status_code if response is not None else 200,
        "body": body,
    }
    try:
        client.setex(
            redis_key,
            IDEMPOTENCY_TTL_SECONDS,
            json.dumps(payload, default=str),
        )
    except Exception as exc:
        logger.warning("idempotency: redis SETEX failed (%s)", exc)


__all__ = [
    "IDEMPOTENCY_HEADER",
    "IDEMPOTENCY_TTL_SECONDS",
    "idempotency_key_dependency",
    "store_idempotent_response",
]
