"""
Lightweight event emitter that fires webhooks without blocking the caller.

Usage
-----
    from app.services.event_emitter import emit

    emit("suspect.accepted", tenant_id, {"suspect_id": 42, "patient_id": 7})

The call returns immediately.  A daemon thread is spawned that calls
webhook_service.fire_event(), which handles retries and delivery logging.
Any exception inside the thread is caught and logged so it can never
surface as an unhandled thread exception.

Internal pipeline events
------------------------
Internal handlers (non-webhook) can be registered with ``register_handler``
and fired with ``emit_internal``.  This powers the auto-chaining pipeline
where EMR sync completion triggers normalization, which in turn triggers RAF
recalculation — all without blocking the caller and without Celery.

Pipeline event types
~~~~~~~~~~~~~~~~~~~~
* ``"emr_sync_completed"``         – Phase ①: fired after a successful EMR sync
* ``"normalization_completed"``    – Phase ②: fired after encounter/diagnosis normalization
* ``"analysis_requested"``         – Phase ③: triggers AI/NLP analysis of encounters
* ``"analysis_completed"``         – Phase ③→④: AI analysis done, triggers RAF calc
* ``"raf_calculation_completed"``  – Phase ④: fired after batch RAF recalculation + hierarchy
* ``"suspect_scan_completed"``     – Phase ⑤: fired after suspect detection scan
* ``"pipeline_completed"``         – Phase ⑧: full pipeline run finished
"""
from __future__ import annotations

import logging
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="webhook")

# ---------------------------------------------------------------------------
# Internal handler registry (pipeline auto-chain)
# ---------------------------------------------------------------------------

# Maps event_type -> list of callables(payload: dict) -> None
_internal_handlers: dict[str, list[Callable[[dict[str, Any]], None]]] = defaultdict(list)

# Dedicated thread pool for internal pipeline steps (separate from webhooks so
# a slow pipeline stage does not starve webhook delivery and vice-versa).
_pipeline_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="pipeline")


def register_handler(event_type: str, handler: Callable[[dict[str, Any]], None]) -> None:
    """Register an internal pipeline handler for *event_type*.

    Handlers are called in registration order inside a background thread when
    ``emit_internal`` is called with a matching *event_type*.

    Parameters
    ----------
    event_type : str
        Internal pipeline event name (e.g. ``"emr_sync_completed"``).
    handler : Callable[[dict], None]
        A callable that accepts a single ``payload`` dict argument.  Any
        exception it raises will be caught, logged, and swallowed so the
        remaining handlers in the chain still run.
    """
    _internal_handlers[event_type].append(handler)
    logger.debug(
        "event_emitter: registered internal handler %s for event '%s'",
        getattr(handler, "__name__", repr(handler)),
        event_type,
    )


def emit_internal(event_type: str, payload: dict[str, Any]) -> None:
    """Fire all registered internal handlers for *event_type* in a background thread.

    Returns immediately; handlers are executed asynchronously in the pipeline
    thread pool.  Each handler is wrapped in a try/except so a failure in one
    handler does not prevent subsequent handlers from running.

    Parameters
    ----------
    event_type : str
        Internal pipeline event name.
    payload : dict
        Arbitrary data describing the event.
    """
    handlers = list(_internal_handlers.get(event_type, []))
    if not handlers:
        logger.debug("event_emitter: no internal handlers for event '%s'", event_type)
        return

    def _run() -> None:
        for handler in handlers:
            name = getattr(handler, "__name__", repr(handler))
            try:
                handler(payload)
            except Exception as exc:
                logger.error(
                    "event_emitter: internal handler %s raised for event '%s': %s",
                    name, event_type, exc,
                )

    _pipeline_executor.submit(_run)
    logger.debug(
        "event_emitter: dispatched internal event '%s' to %d handler(s)",
        event_type, len(handlers),
    )


def emit(event_type: str, tenant_id: str, payload: dict[str, Any]) -> None:
    """
    Fire a webhook event in a background daemon thread.

    The caller is not blocked.  Errors during delivery are caught inside the
    thread and written to the application log; they will not propagate to the
    caller.

    Parameters
    ----------
    event_type : str
        One of the event types listed in webhook_service.WEBHOOK_EVENTS.
    tenant_id : str
        The tenant that owns the affected resource.
    payload : dict
        Arbitrary data describing the event (will be placed under the ``data``
        key of the webhook envelope).
    """
    def _run() -> None:
        try:
            # Import here to avoid circular imports at module load time.
            from app.services.webhook_service import fire_event
            fire_event(event_type, tenant_id, payload)
        except Exception as exc:
            logger.error(
                "event_emitter: unhandled error firing %s for tenant %s: %s",
                event_type, tenant_id, exc,
            )

        # After webhook delivery, also attempt email notification for relevant
        # event types when SMTP is configured.
        try:
            _maybe_send_email(event_type, payload)
        except Exception as exc:
            logger.error(
                "event_emitter: unhandled error sending email for %s: %s",
                event_type, exc,
            )

    _executor.submit(_run)
    logger.debug("event_emitter: dispatched %s for tenant %s", event_type, tenant_id)


# ---------------------------------------------------------------------------
# Email dispatch — maps event types to email_service helpers
# ---------------------------------------------------------------------------

def _maybe_send_email(event_type: str, payload: dict[str, Any]) -> None:
    """
    If SMTP is configured, dispatch a transactional email for events that
    have a direct user-facing impact.

    The ``payload`` dict is expected to carry a ``user_email`` key for events
    where a recipient is known.  Events without a recipient are silently
    skipped.

    This function is always called from inside the webhook thread pool so it
    is safe to import and call email_service (which itself runs in its own
    thread pool for the SMTP connection).
    """
    from app.services.email_service import (
        get_email_config,
        send_analysis_complete,
        send_care_gap_alert,
        send_suspect_alert,
        send_sync_failure_alert,
    )

    config = get_email_config()
    if not config["configured"]:
        return

    user_email: str = payload.get("user_email", "")
    if not user_email:
        logger.debug(
            "event_emitter: no user_email in payload for %s — skipping email", event_type
        )
        return

    if event_type in ("raf.score.calculated", "analysis.complete"):
        send_analysis_complete(
            user_email=user_email,
            patient_name=payload.get("patient_name", "Unknown Patient"),
            pid=payload.get("patient_id", ""),
            hcc_count=int(payload.get("hcc_count", 0)),
            raf_score=float(payload.get("raf_score", 0.0)),
        )

    elif event_type == "suspect.created":
        send_suspect_alert(
            user_email=user_email,
            patient_name=payload.get("patient_name", "Unknown Patient"),
            condition=payload.get("condition", payload.get("hcc_description", "Unknown condition")),
            confidence=float(payload.get("confidence", payload.get("confidence_score", 0.0))),
        )

    elif event_type == "quality.gap.opened":
        send_care_gap_alert(
            user_email=user_email,
            patient_name=payload.get("patient_name", "Unknown Patient"),
            measure_name=payload.get("measure_name", "Unknown measure"),
            due_date=str(payload.get("due_date", "Not specified")),
        )

    elif event_type in ("sync.failed", "emr.sync.failed", "fhir.sync.failed"):
        send_sync_failure_alert(
            user_email=user_email,
            connection_name=payload.get("connection_name", payload.get("source", "Unknown connection")),
            error_message=str(payload.get("error", payload.get("error_message", "Unknown error"))),
        )

    else:
        logger.debug("event_emitter: no email handler for event type %s", event_type)
