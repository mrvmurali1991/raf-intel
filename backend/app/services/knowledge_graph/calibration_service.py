"""
KG inference-time calibration service.

The KG benchmark harness (``app.services.evaluation.kg_benchmark``) fits Platt
scaling parameters ``(a, b)`` on a held-out validation set and reports the
ECE lift in its calibration block.  Those parameters get persisted as a JSON
artefact under ``calibration_artefacts/`` so that production inference can
apply the same monotone re-mapping at runtime — turning raw model
confidences into well-calibrated probabilities.

Public API
----------
load_calibration() -> tuple[float, float]
    Return the persisted Platt ``(a, b)``.  Falls back to the identity
    transform ``(1.0, 0.0)`` when the artefact is missing or malformed.
    Cached at module level — first call reads from disk, subsequent calls
    return the cached tuple.

apply_calibration(raw, a=None, b=None) -> float
    Compute ``sigmoid(a*raw + b)``, clamped to ``[0, 1]``.  When ``a`` or
    ``b`` is ``None`` the function returns the raw value clipped to
    ``[0, 1]`` — i.e. an explicit identity opt-out for callers that want
    to disable calibration without paying the load cost.

reload_calibration() -> tuple[float, float]
    Drop the module-level cache and re-read from disk.  Useful from tests
    and from any future hot-reload admin endpoint.

Design notes
------------
* No numpy / scipy dependency — stdlib only — so this module imports cheaply
  even in cold-start FastAPI workers.
* Numerically-stable sigmoid (same shape as ``kg_benchmark._platt_apply``).
* The benchmark harness (training-time code) is *not* imported from here.
  We deliberately duplicate the four-line sigmoid math rather than couple
  inference to the eval pipeline.
* Identity fallback ``(a=1.0, b=0.0)`` does NOT collapse to identity for
  ``apply_calibration(raw, 1.0, 0.0)`` — that path returns
  ``sigmoid(raw)`` (the squashing logistic), which is *not* the raw value.
  Callers that want pass-through should use the ``a=None`` / ``b=None``
  signal.  The identity behaviour is therefore advertised at the
  ``load_calibration`` boundary: when the artefact is missing the function
  returns ``(1.0, 0.0)`` and downstream wiring should detect that and
  treat raw_confidence == calibrated_confidence.  This matches the
  contract documented on the frontend ``DBSuspect`` type.
"""
from __future__ import annotations

import json
import logging
import math
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ARTEFACT_DIR: Path = Path(__file__).resolve().parent / "calibration_artefacts"
ARTEFACT_PATH: Path = ARTEFACT_DIR / "platt_v1.json"

# Identity Platt params.  When the artefact is missing or malformed we return
# these so callers can detect "no calibration available" by comparing.
_IDENTITY_PARAMS: tuple[float, float] = (1.0, 0.0)


# ---------------------------------------------------------------------------
# Module-level cache
# ---------------------------------------------------------------------------

_cache_lock = threading.RLock()
_cached_params: tuple[float, float] | None = None
_cached_metadata: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_calibration() -> tuple[float, float]:
    """Return the persisted Platt ``(a, b)`` from the JSON artefact.

    Falls back to the identity tuple ``(1.0, 0.0)`` when the artefact is
    missing, unreadable, or malformed.  Cached after the first call so the
    JSON is read at most once per process.
    """
    global _cached_params, _cached_metadata
    with _cache_lock:
        if _cached_params is not None:
            return _cached_params
        params, metadata = _read_artefact(ARTEFACT_PATH)
        _cached_params = params
        _cached_metadata = metadata
        return params


def apply_calibration(
    raw: float,
    a: float | None = None,
    b: float | None = None,
) -> float:
    """Apply Platt scaling to a raw confidence.

    Returns ``sigmoid(a*raw + b)`` clamped to ``[0, 1]``.  When *a* or *b*
    is ``None`` the function returns ``raw`` clipped to ``[0, 1]`` — an
    explicit pass-through that lets callers gate calibration without
    re-loading the artefact.

    Notes
    -----
    Numerically-stable sigmoid: pick the branch that avoids overflow on
    large-magnitude inputs.  This mirrors the implementation in
    ``app.services.evaluation.kg_benchmark._platt_apply`` so a model
    calibrated by the benchmark and applied here produces identical output.
    """
    if raw is None:
        return 0.0
    try:
        raw_f = float(raw)
    except (TypeError, ValueError):
        return 0.0

    if a is None or b is None:
        # Identity opt-out: just clip to [0, 1].
        return _clamp01(raw_f)

    z = float(a) * raw_f + float(b)
    if z >= 0.0:
        ez = math.exp(-z)
        out = 1.0 / (1.0 + ez)
    else:
        ez = math.exp(z)
        out = ez / (1.0 + ez)
    return _clamp01(out)


def reload_calibration() -> tuple[float, float]:
    """Drop the module-level cache and re-read the artefact from disk."""
    global _cached_params, _cached_metadata
    with _cache_lock:
        _cached_params = None
        _cached_metadata = None
    return load_calibration()


def get_metadata() -> dict[str, Any]:
    """Return the metadata block from the loaded artefact (or empty dict).

    Useful for ``/admin`` style introspection — the number of charts the
    fit was performed on, the ECE before/after, the trained_at timestamp.
    """
    # Force a load if it hasn't happened yet.
    load_calibration()
    with _cache_lock:
        return dict(_cached_metadata or {})


def is_identity(a: float, b: float, *, tol: float = 1e-9) -> bool:
    """Return True when ``(a, b)`` is the identity Platt fit ``(1.0, 0.0)``.

    Wiring uses this to decide whether ``calibrated_confidence`` carries
    new information vs duplicates ``raw_confidence``.
    """
    return abs(a - _IDENTITY_PARAMS[0]) <= tol and abs(b - _IDENTITY_PARAMS[1]) <= tol


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _clamp01(x: float) -> float:
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x


def _read_artefact(path: Path) -> tuple[tuple[float, float], dict[str, Any]]:
    """Read the JSON artefact and return ``((a, b), metadata)``.

    Any error path returns ``(_IDENTITY_PARAMS, {})``.  Errors are logged
    at INFO level — a missing artefact is an expected initial-deploy state,
    not a bug.
    """
    if not path.exists():
        logger.info(
            "kg calibration artefact not found at %s; falling back to identity",
            path,
        )
        return _IDENTITY_PARAMS, {}
    try:
        raw_text = path.read_text(encoding="utf-8")
        payload = json.loads(raw_text)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(
            "kg calibration artefact %s could not be read (%s); falling back to identity",
            path, exc,
        )
        return _IDENTITY_PARAMS, {}

    if not isinstance(payload, dict):
        logger.warning(
            "kg calibration artefact %s is not a JSON object; falling back to identity",
            path,
        )
        return _IDENTITY_PARAMS, {}

    a_val = payload.get("a")
    b_val = payload.get("b")
    try:
        a_f = float(a_val)
        b_f = float(b_val)
    except (TypeError, ValueError):
        logger.warning(
            "kg calibration artefact %s missing valid 'a' / 'b' floats (got a=%r b=%r); "
            "falling back to identity",
            path, a_val, b_val,
        )
        return _IDENTITY_PARAMS, {}

    if not (math.isfinite(a_f) and math.isfinite(b_f)):
        logger.warning(
            "kg calibration artefact %s has non-finite params (a=%r b=%r); "
            "falling back to identity",
            path, a_f, b_f,
        )
        return _IDENTITY_PARAMS, {}

    return (a_f, b_f), payload
