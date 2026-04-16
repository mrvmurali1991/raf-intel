"""
AI / coder action audit helper.

Writes to the ``ai_audit_log`` table (see migration 014_ai_audit_log).

This is the single source of truth for AI + coder decision audit events.
It is deliberately separate from :mod:`app.services.audit_logger`
(which handles HIPAA PHI access logs) — this table records *actions*,
not *reads*.

Event taxonomy (``action`` column)
----------------------------------
LLM lifecycle
    ``llm.request``        — prompt submitted (stores hash, model, tokens)
    ``llm.response``       — response received (tokens, latency, model)
    ``llm.error``          — provider/transport error
    ``llm.retry``          — retry attempted after schema-validation failure

AI pipeline
    ``ai.candidate.created``   — HCC candidate proposed
    ``ai.suspect.created``     — Suspect created
    ``ai.provider_query.created`` — Provider query raised

Coder decisions
    ``coder.decision.accept``
    ``coder.decision.reject``
    ``coder.decision.edit``

Configuration
    ``config.update``
    ``pipeline_settings.update``
"""
from __future__ import annotations

import json
import logging
from typing import Any, Mapping

from app.db import raf_cursor

log = logging.getLogger(__name__)

# -- canonical action strings -------------------------------------------------

LLM_REQUEST = "llm.request"
LLM_RESPONSE = "llm.response"
LLM_ERROR = "llm.error"
LLM_RETRY = "llm.retry"

AI_CANDIDATE_CREATED = "ai.candidate.created"
AI_SUSPECT_CREATED = "ai.suspect.created"
AI_PROVIDER_QUERY_CREATED = "ai.provider_query.created"

CODER_ACCEPT = "coder.decision.accept"
CODER_REJECT = "coder.decision.reject"
CODER_EDIT = "coder.decision.edit"

CONFIG_UPDATE = "config.update"
PIPELINE_SETTINGS_UPDATE = "pipeline_settings.update"


def _jsonable(v: Any) -> Any:
    if v is None:
        return None
    try:
        json.dumps(v)
        return v
    except TypeError:
        return json.loads(json.dumps(v, default=str))


def log_event(
    *,
    tenant_id: str,
    action: str,
    actor_type: str = "system",
    actor_id: str | None = None,
    target_type: str | None = None,
    target_id: str | int | None = None,
    before: Mapping[str, Any] | None = None,
    after: Mapping[str, Any] | None = None,
) -> int | None:
    """Insert an audit row. Returns new id, or None on failure (never raises)."""
    if actor_type not in ("system", "user"):
        raise ValueError("actor_type must be 'system' or 'user'")
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                INSERT INTO ai_audit_log
                  (tenant_id, actor_type, actor_id, action,
                   target_type, target_id, `before`, `after`)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    tenant_id,
                    actor_type,
                    actor_id,
                    action,
                    target_type,
                    str(target_id) if target_id is not None else None,
                    json.dumps(_jsonable(dict(before))) if before else None,
                    json.dumps(_jsonable(dict(after))) if after else None,
                ),
            )
            new_id = getattr(cur, "lastrowid", None)
            return int(new_id) if new_id else None
    except Exception:  # pragma: no cover — audit must never break callers
        log.exception("ai_audit_log insert failed action=%s target=%s/%s",
                      action, target_type, target_id)
        return None


# NOTE: a previous convenience wrapper named ``log`` was removed because it
# shadowed the module-level ``log = logging.getLogger(__name__)``. That
# collision silently broke the error handler inside :func:`log_event` — any
# DB failure raised ``AttributeError`` on ``log.exception(...)`` and the real
# cause never reached logs. Use :func:`log_event` directly.
