"""Vertex AI Gemini client (BAA-covered).

This module provides a single entry point — :func:`llm_generate` — that
wraps Google Vertex AI's ``generateContent`` endpoint using a service
account for authentication.  Service-account auth is required for GCP
BAA coverage; the legacy ``generativelanguage.googleapis.com`` API-key
path is NOT covered by the BAA and is retained only as a fallback for
local development / emergency rollback, gated by ``LLM_USE_VERTEX``.

Environment variables
---------------------
GCP_PROJECT_ID              GCP project that hosts the Vertex AI endpoint.
GCP_LOCATION                Vertex AI region (default: ``us-central1``).
GOOGLE_APPLICATION_CREDENTIALS
                            Absolute path to the service-account JSON key
                            file.  Read by ``google.auth.default()``.
LLM_USE_VERTEX              ``true`` (default) → Vertex AI + SA creds.
                            ``false`` → legacy Generative Language API key.
GOOGLE_API_KEY              Only used when ``LLM_USE_VERTEX=false``.
GEMINI_MODEL                Default model name (e.g. ``gemini-2.0-flash``).

Usage
-----
>>> from app.services.llm import llm_generate
>>> text = llm_generate("Summarise this note: ...", model="gemini-2.0-flash")
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from contextvars import ContextVar
from typing import Any, Optional

import requests

# Module-level contextvar for tenant propagation. Callers (e.g. request
# middleware) can set this so audit events are correctly attributed without
# threading a tenant_id through every internal function. Defaults to None;
# unset reads resolve to "system" in the audit call to make log analysis
# distinguishable from a real tenant literally named "default".
current_tenant_id: ContextVar[str | None] = ContextVar(
    "current_tenant_id", default=None
)

# Guardrails are imported lazily inside call sites to avoid a circular
# import: ``app.services.ai_pipeline/__init__.py`` eagerly imports modules
# that themselves import from ``app.services.llm``.


def _guardrails():
    import importlib
    return importlib.import_module("app.services.ai_pipeline.guardrails")

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Audit — lazy import so the LLM client still works in test envs without a DB.
# ---------------------------------------------------------------------------

def _audit(action: str, *, model: str, before: dict | None = None,
           after: dict | None = None,
           tenant_id: str | None = None) -> None:
    """Best-effort audit emission. Never raises."""
    try:
        import importlib
        _audit_mod = importlib.import_module("app.services.audit")
        resolved_tenant = tenant_id
        if resolved_tenant is None:
            try:
                resolved_tenant = current_tenant_id.get()
            except LookupError:
                resolved_tenant = None
        if not resolved_tenant:
            resolved_tenant = "system"
        _audit_mod.log_event(
            tenant_id=resolved_tenant,
            action=action,
            actor_type="system",
            actor_id="llm_client",
            target_type="llm",
            target_id=model,
            before=before,
            after=after,
        )
    except Exception:  # pragma: no cover — audit is best-effort
        logger.debug("audit.log_event unavailable for action=%s", action)


def _prompt_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]

# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------

_VERTEX_SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]
_DEFAULT_LOCATION = "us-central1"
_DEFAULT_MODEL = "gemini-2.0-flash"
_REQUEST_TIMEOUT_SEC = 60


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _use_vertex() -> bool:
    return _env_bool("LLM_USE_VERTEX", True)


def _use_vertex_api_key() -> bool:
    """Route through the global Vertex publishers endpoint using GOOGLE_API_KEY.

    This is the BAA-eligible `aiplatform.googleapis.com/v1/publishers/...`
    endpoint that accepts API keys (Vertex AI Express/publisher mode), as
    distinct from the project-scoped endpoint that requires a service account.
    Enabled when ``LLM_VERTEX_API_KEY=true`` OR (Vertex is on, a GOOGLE_API_KEY
    is configured, and no project / SA credentials are set).
    """
    if _env_bool("LLM_VERTEX_API_KEY", False):
        return True
    if not _use_vertex():
        return False
    has_key = bool(os.getenv("GOOGLE_API_KEY", "").strip())
    has_sa = bool(os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()) or \
             bool(os.getenv("GCP_PROJECT_ID", "").strip())
    return has_key and not has_sa


# ---------------------------------------------------------------------------
# Credential cache — avoid re-loading the service account JSON on every call.
# google.auth.transport.requests.Request refreshes tokens in-place.
# ---------------------------------------------------------------------------

_creds_lock = threading.Lock()
_cached_creds: Any = None


def _load_credentials() -> Any:
    """Return cached, refreshed google-auth credentials.

    Uses Application Default Credentials — honours
    ``GOOGLE_APPLICATION_CREDENTIALS`` or workload-identity on GCP.
    """
    global _cached_creds
    with _creds_lock:
        if _cached_creds is None:
            # Import lazily so test envs without google-auth can still import
            # this module.
            from google.auth import default as ga_default  # type: ignore

            creds, _project = ga_default(scopes=_VERTEX_SCOPES)
            _cached_creds = creds
        creds = _cached_creds

    if not getattr(creds, "valid", False):
        from google.auth.transport.requests import Request as GARequest  # type: ignore

        creds.refresh(GARequest())
    return creds


def _reset_credentials_cache() -> None:
    """Test-only helper — drops the cached credentials."""
    global _cached_creds
    with _creds_lock:
        _cached_creds = None


# ---------------------------------------------------------------------------
# Request building
# ---------------------------------------------------------------------------

def _build_payload(
    prompt: str,
    system: Optional[str],
    temperature: float,
) -> dict:
    payload: dict[str, Any] = {
        "contents": [
            {"role": "user", "parts": [{"text": prompt}]},
        ],
        "generationConfig": {
            "temperature": float(temperature),
        },
    }
    if system:
        payload["systemInstruction"] = {"parts": [{"text": system}]}
    return payload


def _extract_text(response_json: dict) -> str:
    try:
        candidates = response_json.get("candidates") or []
        if not candidates:
            return ""
        parts = candidates[0].get("content", {}).get("parts", []) or []
        return "".join(p.get("text", "") for p in parts)
    except Exception:  # pragma: no cover — defensive
        logger.exception("Failed to extract text from Gemini response")
        return ""


# ---------------------------------------------------------------------------
# Vertex AI transport (BAA-covered, service-account auth)
# ---------------------------------------------------------------------------

def _vertex_url(model: str) -> str:
    project = os.getenv("GCP_PROJECT_ID", "").strip()
    location = os.getenv("GCP_LOCATION", _DEFAULT_LOCATION).strip() or _DEFAULT_LOCATION
    if not project:
        raise RuntimeError(
            "GCP_PROJECT_ID is not configured — required for Vertex AI transport"
        )
    return (
        f"https://{location}-aiplatform.googleapis.com/v1/projects/{project}"
        f"/locations/{location}/publishers/google/models/{model}:generateContent"
    )


def _call_vertex(
    prompt: str,
    model: str,
    system: Optional[str],
    temperature: float,
) -> str:
    creds = _load_credentials()
    url = _vertex_url(model)
    payload = _build_payload(prompt, system, temperature)

    headers = {
        "Authorization": f"Bearer {creds.token}",
        "Content-Type": "application/json",
    }

    resp = requests.post(
        url,
        headers=headers,
        data=json.dumps(payload),
        timeout=_REQUEST_TIMEOUT_SEC,
    )
    if resp.status_code >= 400:
        logger.error(
            "Vertex AI generateContent failed: status=%s body=%s",
            resp.status_code,
            resp.text[:500],
        )
        resp.raise_for_status()
    return _extract_text(resp.json())


# ---------------------------------------------------------------------------
# Vertex AI publisher transport (API key, BAA-eligible via aiplatform endpoint)
# ---------------------------------------------------------------------------

_VERTEX_APIKEY_BASE = "https://aiplatform.googleapis.com/v1/publishers/google/models"


def _vertex_apikey_url(model: str, method: str = "generateContent") -> str:
    api_key = os.getenv("GOOGLE_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "GOOGLE_API_KEY is not configured — required for Vertex API-key transport"
        )
    return f"{_VERTEX_APIKEY_BASE}/{model}:{method}?key={api_key}"


def _call_vertex_apikey(
    prompt: str,
    model: str,
    system: Optional[str],
    temperature: float,
) -> str:
    url = _vertex_apikey_url(model)
    payload = _build_payload(prompt, system, temperature)
    resp = requests.post(
        url,
        headers={"Content-Type": "application/json"},
        data=json.dumps(payload),
        timeout=_REQUEST_TIMEOUT_SEC,
    )
    if resp.status_code >= 400:
        logger.error(
            "Vertex API-key generateContent failed: status=%s body=%s",
            resp.status_code,
            resp.text[:500],
        )
        resp.raise_for_status()
    return _extract_text(resp.json())


# ---------------------------------------------------------------------------
# Legacy Generative Language API transport (API key, NOT BAA-covered)
# ---------------------------------------------------------------------------

def _call_generative_language(
    prompt: str,
    model: str,
    system: Optional[str],
    temperature: float,
) -> str:
    api_key = os.getenv("GOOGLE_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "GOOGLE_API_KEY is not configured — required when LLM_USE_VERTEX=false"
        )
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={api_key}"
    )
    payload = _build_payload(prompt, system, temperature)
    resp = requests.post(
        url,
        headers={"Content-Type": "application/json"},
        data=json.dumps(payload),
        timeout=_REQUEST_TIMEOUT_SEC,
    )
    if resp.status_code >= 400:
        logger.error(
            "Generative Language API failed: status=%s body=%s",
            resp.status_code,
            resp.text[:500],
        )
        resp.raise_for_status()
    return _extract_text(resp.json())


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def llm_generate_content(
    payload: dict,
    model: str = _DEFAULT_MODEL,
    *,
    timeout: int = _REQUEST_TIMEOUT_SEC,
    tenant_id: str | None = None,
) -> dict:
    """Transport-layer helper — POST a raw ``generateContent`` payload.

    Use this for callers that need multi-turn tool/function-calling,
    multimodal inline data, or a custom ``generationConfig`` that
    ``llm_generate`` does not expose.  Business logic (prompts, tools,
    response parsing) stays in the caller; only the HTTP transport and
    authentication are centralised here.

    Routing honours ``LLM_USE_VERTEX`` identically to :func:`llm_generate`.

    Parameters
    ----------
    payload:
        The full JSON body for ``:generateContent`` (contents, tools,
        systemInstruction, generationConfig, …).
    model:
        Gemini model name.
    timeout:
        Per-request timeout in seconds.

    Returns
    -------
    dict
        Parsed JSON response body.

    Raises
    ------
    RuntimeError
        If required credentials / project config are missing.
    requests.HTTPError
        On non-2xx responses from the upstream API.
    """
    _audit(
        "llm.request",
        model=model,
        before={
            "model": model,
            "payload_keys": sorted(list(payload.keys())) if isinstance(payload, dict) else [],
            "raw_payload": True,
        },
        after=None,
        tenant_id=tenant_id,
    )
    start = time.monotonic()
    try:
        if _use_vertex_api_key():
            url = _vertex_apikey_url(model)
            resp = requests.post(
                url,
                headers={"Content-Type": "application/json"},
                data=json.dumps(payload),
                timeout=timeout,
            )
        elif _use_vertex():
            creds = _load_credentials()
            url = _vertex_url(model)
            headers = {
                "Authorization": f"Bearer {creds.token}",
                "Content-Type": "application/json",
            }
            resp = requests.post(
                url,
                headers=headers,
                data=json.dumps(payload),
                timeout=timeout,
            )
        else:
            api_key = os.getenv("GOOGLE_API_KEY", "").strip()
            if not api_key:
                raise RuntimeError(
                    "GOOGLE_API_KEY is not configured — required when LLM_USE_VERTEX=false"
                )
            url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"{model}:generateContent?key={api_key}"
            )
            resp = requests.post(
                url,
                headers={"Content-Type": "application/json"},
                data=json.dumps(payload),
                timeout=timeout,
            )
        if resp.status_code >= 400:
            logger.error(
                "generateContent failed: status=%s body=%s",
                resp.status_code,
                resp.text[:500],
            )
            resp.raise_for_status()
        body = resp.json()
    except Exception as e:
        _audit(
            "llm.error",
            model=model,
            before=None,
            after={"error": str(e), "type": type(e).__name__},
            tenant_id=tenant_id,
        )
        raise
    elapsed_ms = int((time.monotonic() - start) * 1000)
    _audit(
        "llm.response",
        model=model,
        before=None,
        after={
            "output_chars": len(json.dumps(body)) if body is not None else 0,
            "latency_ms": elapsed_ms,
        },
        tenant_id=tenant_id,
    )
    return body


_STRICT_JSON_REMINDER = (
    "\n\nSTRICT OUTPUT: Respond with ONLY a single valid JSON document that "
    "conforms exactly to the required schema. No prose, no markdown fences, "
    "no commentary."
)


def llm_generate(
    prompt: str,
    model: str = _DEFAULT_MODEL,
    system: Optional[str] = None,
    temperature: float = 0.1,
    output_schema: dict | None = None,
    tenant_id: str | None = None,
) -> str:
    """Generate text from a Gemini model.

    Routes through Vertex AI (service-account auth, BAA-covered) when the
    ``LLM_USE_VERTEX`` flag is true (the default).  Set
    ``LLM_USE_VERTEX=false`` to fall back to the legacy API-key path.

    Parameters
    ----------
    prompt:
        User prompt.  Required.
    model:
        Gemini model name — e.g. ``gemini-2.0-flash`` (default) or
        ``gemini-2.5-pro``.
    system:
        Optional system instruction.
    temperature:
        Sampling temperature in ``[0.0, 2.0]``.  Defaults to ``0.1`` for
        deterministic clinical extraction.

    Returns
    -------
    str
        Concatenated text from the first candidate, or ``""`` on empty
        response.

    Raises
    ------
    RuntimeError
        If required credentials / project config are missing.
    requests.HTTPError
        On non-2xx responses from the upstream API.
    """
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("prompt must be a non-empty string")

    _g = _guardrails()
    sanitize_note_for_llm = _g.sanitize_note_for_llm
    validate_llm_output = _g.validate_llm_output

    # Sanitize before anything else so prompt_hash reflects what we send.
    safe_prompt = sanitize_note_for_llm(prompt)
    safe_system = sanitize_note_for_llm(system) if system else None

    def _emit_request(p: str) -> None:
        _audit(
            "llm.request",
            model=model,
            before={
                "prompt_hash": _prompt_hash(p),
                "model": model,
                "prompt_chars": len(p),
                "temperature": temperature,
            },
            after=None,
            tenant_id=tenant_id,
        )

    def _do_call(p: str, s: Optional[str]) -> str:
        if _use_vertex_api_key():
            return _call_vertex_apikey(p, model, s, temperature)
        if _use_vertex():
            return _call_vertex(p, model, s, temperature)
        return _call_generative_language(p, model, s, temperature)

    _emit_request(safe_prompt)
    start = time.monotonic()
    try:
        output = _do_call(safe_prompt, safe_system)
    except Exception as e:
        _audit(
            "llm.error",
            model=model,
            before=None,
            after={"error": str(e), "type": type(e).__name__},
            tenant_id=tenant_id,
        )
        raise
    elapsed_ms = int((time.monotonic() - start) * 1000)
    _audit(
        "llm.response",
        model=model,
        before=None,
        after={"output_chars": len(output), "latency_ms": elapsed_ms},
        tenant_id=tenant_id,
    )

    if output_schema is not None:
        ok, _parsed, err = validate_llm_output(output, output_schema)
        if not ok:
            # Retry once with a strict-JSON reminder appended.
            _audit(
                "llm.retry",
                model=model,
                before={"reason": "schema_validation_failed", "error": err},
                after=None,
                tenant_id=tenant_id,
            )
            retry_prompt = safe_prompt + _STRICT_JSON_REMINDER
            _emit_request(retry_prompt)
            start2 = time.monotonic()
            try:
                output = _do_call(retry_prompt, safe_system)
            except Exception as e:
                _audit(
                    "llm.error",
                    model=model,
                    before=None,
                    after={"error": str(e), "type": type(e).__name__},
                    tenant_id=tenant_id,
                )
                raise
            elapsed2 = int((time.monotonic() - start2) * 1000)
            _audit(
                "llm.response",
                model=model,
                before=None,
                after={"output_chars": len(output), "latency_ms": elapsed2},
                tenant_id=tenant_id,
            )
            ok2, _parsed2, err2 = validate_llm_output(output, output_schema)
            if not ok2:
                raise ValueError(
                    f"LLM output failed schema validation after retry: {err2}"
                )

    return output
