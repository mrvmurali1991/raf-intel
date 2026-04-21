"""
Per-source calibrator persistence + lazy runtime loading.

Layout on disk::

    backend/app/services/raf/calibration/models/
        regex.joblib
        lab.joblib
        med.joblib
        llm.joblib

Models are fit offline by ``backend/scripts/fit_calibrators.py`` and
committed.  **No fitting happens at runtime.**  Loading is lazy (first
call per process) and cached.

When no artifact exists for a source, we fall back to
:class:`IdentityCalibrator` — calibrated == raw — and log a single
warning so the signal is visible in prod logs without spamming.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Mapping

from .calibrator import Calibrator, IdentityCalibrator

logger = logging.getLogger(__name__)

MODEL_DIR = Path(__file__).parent / "models"

#: Canonical per-source keys.  Any other source string received at
#: runtime is mapped onto these via :func:`_normalise_source`.
CANONICAL_SOURCES: tuple[str, ...] = ("regex", "lab", "med", "llm")

#: Aliases used in production suspect rows -> canonical key.
_SOURCE_ALIASES: Mapping[str, str] = {
    "rule": "regex",
    "regex": "regex",
    "medication": "med",
    "med": "med",
    "lab": "lab",
    "laboratory": "lab",
    "llm": "llm",
    "nlp": "llm",
    "history": "regex",  # historical-recapture is a deterministic rule
    "both": "llm",       # rule+LLM merged — LLM is the weaker signal
    "imaging": "regex",
    "referral": "regex",
    "historical": "regex",
}


def _normalise_source(src: str | None) -> str:
    if not src:
        return "regex"
    return _SOURCE_ALIASES.get(str(src).strip().lower(), "regex")


# ---------------------------------------------------------------------------
# Thread-safe lazy cache
# ---------------------------------------------------------------------------
_cache_lock = threading.Lock()
_cache: dict[str, Calibrator] = {}
_missing_warned: set[str] = set()


def _artifact_path(source: str) -> Path:
    return MODEL_DIR / f"{source}.joblib"


def save_calibrator(source: str, calibrator: Calibrator) -> Path:
    """Persist a fitted calibrator to disk.  Called by the fit script."""
    import joblib

    key = _normalise_source(source)
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    path = _artifact_path(key)
    joblib.dump(calibrator, path)
    logger.info("calibration: saved %s -> %s", key, path)
    with _cache_lock:
        _cache[key] = calibrator
    return path


def _load_from_disk(source: str) -> Calibrator:
    import joblib

    path = _artifact_path(source)
    if not path.exists():
        if source not in _missing_warned:
            logger.warning(
                "calibration: no artifact for source=%s at %s — "
                "falling back to IdentityCalibrator (calibrated == raw). "
                "Run backend/scripts/fit_calibrators.py to train.",
                source,
                path,
            )
            _missing_warned.add(source)
        return IdentityCalibrator()
    try:
        cal = joblib.load(path)
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "calibration: failed to load %s: %s — using IdentityCalibrator.",
            path,
            exc,
        )
        return IdentityCalibrator()
    if not isinstance(cal, Calibrator):
        logger.error(
            "calibration: artifact %s is not a Calibrator (got %s) — "
            "using IdentityCalibrator.",
            path,
            type(cal).__name__,
        )
        return IdentityCalibrator()
    return cal


def load_calibrator(source: str) -> Calibrator:
    """Return the calibrator for *source*, caching across calls.

    *source* accepts any of the runtime aliases (e.g. ``"medication"``,
    ``"nlp"``, ``"rule"``); they are normalised internally.
    """
    key = _normalise_source(source)
    with _cache_lock:
        cached = _cache.get(key)
        if cached is not None:
            return cached
    cal = _load_from_disk(key)
    with _cache_lock:
        _cache.setdefault(key, cal)
    return cal


def calibrate(source: str, raw_score: float) -> float:
    """Shortcut: load + transform a single raw score."""
    try:
        raw = float(raw_score)
    except (TypeError, ValueError):
        return 0.0
    raw = max(0.0, min(1.0, raw))
    cal = load_calibrator(source)
    try:
        return cal.transform_one(raw)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "calibration.calibrate failed for source=%s raw=%.3f: %s — "
            "returning raw.",
            source,
            raw,
            exc,
        )
        return raw


def available_sources() -> list[str]:
    """Return canonical source keys that have a trained artifact on disk."""
    return [s for s in CANONICAL_SOURCES if _artifact_path(s).exists()]


def reset_cache() -> None:
    """Test hook — clear the in-memory cache."""
    with _cache_lock:
        _cache.clear()
        _missing_warned.clear()
