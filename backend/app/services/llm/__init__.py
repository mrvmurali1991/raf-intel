"""LLM client package.

Exposes a single entry point ``llm_generate`` that callers should use for
all Gemini interactions.  The underlying transport (Vertex AI with a
service-account, or the legacy Generative Language API with an API key) is
selected by the ``LLM_USE_VERTEX`` feature flag (default: true).
"""

from .vertex_client import (  # noqa: F401
    llm_generate,
    llm_generate_content,
)

__all__ = ["llm_generate", "llm_generate_content"]
