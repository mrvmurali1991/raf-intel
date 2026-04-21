"""
Pipeline domain package.

Re-exports from the flat services layer so that new code can import from
``app.services.pipeline`` while existing imports (``app.services.pipeline_chain``,
etc.) continue to work without modification.

Domain responsibilities:
- Pipeline orchestration and chain execution
- Stage-by-stage event emission
- Skill-based pipeline routing
"""
from app.services.event_emitter import (  # noqa: F401
    emit,
    emit_internal,
    register_handler,
)
from app.services.pipeline_chain import setup_pipeline_chain  # noqa: F401
from app.services.pipeline_orchestrator import run_verified_pipeline  # noqa: F401
from app.services.skill_pipeline import run_pipeline  # noqa: F401

__all__ = [
    "setup_pipeline_chain",
    "run_verified_pipeline",
    "emit",
    "emit_internal",
    "register_handler",
    "run_pipeline",
]
