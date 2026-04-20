"""Forensic provenance helpers for RAF score persistence.

Each calculated score is stamped with:
  * the CMS-HCC model(s) that produced it,
  * the coefficient source (library + version),
  * a SHA-256 hash of ``coefficients_manifest.json`` at runtime,
  * the calculator's git commit SHA.

All lookups are cached at import time so the happy-path overhead is a single
dict read per RAF calculation.
"""

from __future__ import annotations

import hashlib
import logging
import os
import subprocess
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)


class CoefficientPinDriftError(RuntimeError):
    """Raised when the installed hccinfhir version diverges from the manifest pin.

    This error is raised in non-development environments (or whenever
    ``settings.allow_coefficient_drift`` is False) to prevent silently
    producing scores from an off-spec coefficient library.  Set the
    ``ALLOW_COEFFICIENT_DRIFT=true`` environment variable to downgrade this
    to a warning in emergency situations.
    """

_MANIFEST_PATH = Path(__file__).resolve().parent / "coefficients_manifest.json"


@lru_cache(maxsize=1)
def coefficient_manifest_hash() -> str | None:
    """SHA-256 of the coefficients manifest, or ``None`` if missing."""
    if not _MANIFEST_PATH.exists():
        logger.warning("coefficients_manifest.json missing at %s", _MANIFEST_PATH)
        return None
    h = hashlib.sha256()
    h.update(_MANIFEST_PATH.read_bytes())
    return h.hexdigest()


@lru_cache(maxsize=1)
def coefficient_source() -> str:
    """Identifier of the library+version providing coefficients at runtime.

    Prefers the live ``hccinfhir.__version__``; falls back to the pinned
    requirement string if the attribute is missing.
    """
    try:
        import hccinfhir

        version = getattr(hccinfhir, "__version__", None)
        if version:
            return f"hccinfhir=={version}"
    except ImportError:  # pragma: no cover — module always installed in prod
        pass
    return "hccinfhir==unknown"


@lru_cache(maxsize=1)
def calculator_commit_sha() -> str | None:
    """Git commit SHA of the calculator code, or ``None`` if unavailable.

    Read order:
      1. ``CALCULATOR_COMMIT_SHA`` env var (typically set in the container).
      2. ``git rev-parse HEAD`` executed in the backend dir.
      3. ``None`` — we log a warning but do not raise.
    """
    env_sha = os.environ.get("CALCULATOR_COMMIT_SHA") or os.environ.get("COMMIT_SHA")
    if env_sha:
        return env_sha.strip()[:40]

    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[3],
            capture_output=True,
            text=True,
            timeout=1.5,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()[:40]
    except (OSError, subprocess.SubprocessError) as exc:
        logger.debug("calculator_commit_sha: git lookup failed: %s", exc)

    return None


def provenance_stamp(model_version: str) -> dict[str, str | None]:
    """Bundle all provenance fields for one raf_scores row."""
    return {
        "model_version": model_version,
        "coefficient_source": coefficient_source(),
        "coefficient_manifest_hash": coefficient_manifest_hash(),
        "calculator_commit_sha": calculator_commit_sha(),
    }


# ---------------------------------------------------------------------------
# SBOM — Software Bill Of Materials attached to every RAF response.
#
# An auditor who later asks "what produced this number?" needs a single
# machine-readable struct with:
#   * every model and payment-year blended into the output
#   * the hccinfhir version that shipped those coefficients
#   * the SHA-256 of the coefficient manifest at calculation time
#   * the calculator git commit
#   * an ISO timestamp
# That struct is what we emit below. It is pure: no DB read, no external call.
# ---------------------------------------------------------------------------

import json
from datetime import datetime, timezone
from typing import Any


@lru_cache(maxsize=1)
def _manifest_pin() -> str | None:
    """Coefficient source recorded *inside* the manifest (e.g. hccinfhir==0.1.5)."""
    if not _MANIFEST_PATH.exists():
        return None
    try:
        data = json.loads(_MANIFEST_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    pin = data.get("coefficient_source")
    return str(pin) if pin else None


def _runtime_vs_pin_drift() -> bool:
    """True when live hccinfhir version diverges from the manifest pin.

    Used to set ``sbom["coefficient_pin_drift"]`` so consumers can flag
    scores that were computed against an off-spec library version.
    """
    pin = _manifest_pin()
    live = coefficient_source()
    if not pin or not live:
        return False
    return pin.strip() != live.strip()


def _assert_no_coefficient_drift() -> None:
    """Raise or warn when hccinfhir version diverges from the manifest pin.

    Behaviour is controlled by two inputs:
    - ``settings.app_env == "development"`` — in dev, never block; log a
      warning so developers notice the mismatch without being hard-stopped.
    - ``settings.allow_coefficient_drift`` — explicit opt-in flag (default
      False).  When True, always warn and proceed regardless of environment.

    In all other cases (production / staging) a ``CoefficientPinDriftError``
    is raised to prevent silently producing scores from an off-spec library.
    """
    if not _runtime_vs_pin_drift():
        return  # Happy path — no drift detected.

    pin = _manifest_pin()
    live = coefficient_source()
    msg = (
        f"hccinfhir coefficient version mismatch: manifest pins {pin!r} "
        f"but runtime reports {live!r}. RAF scores may be inaccurate."
    )

    # Import settings lazily to avoid circular imports at module load time.
    from app.config import settings  # noqa: PLC0415

    if settings.app_env == "development" or settings.allow_coefficient_drift:
        logger.warning(
            "CoefficientPinDrift (proceeding anyway — dev/allow_drift): %s", msg
        )
        return

    raise CoefficientPinDriftError(msg)


def build_score_sbom(
    *,
    models_used: list[str],
    payment_year: int,
    plan_type: str | None = None,
    frailty_applied: bool = False,
) -> dict[str, Any]:
    """Return the per-score SBOM block to attach to a RAF response.

    Also enforces the coefficient-pin drift gate: raises
    ``CoefficientPinDriftError`` in non-development environments when the
    installed hccinfhir version diverges from the manifest pin.

    Parameters
    ----------
    models_used : list[str]
        Every CMS-HCC / RxHCC model blended into the final score
        (e.g. ``["CMS-HCC Model V28"]`` or
        ``["CMS-HCC Model V22", "CMS-HCC Model V28"]`` for PACE).
    payment_year : int
        CMS payment year the blend and normalization targeted.
    plan_type : str, optional
        MA / PACE / FIDE_SNP — for cross-referencing the blend schedule.
    frailty_applied : bool
        Whether the frailty addend fired on this calculation.

    Returns
    -------
    dict — stable keys, JSON-safe values. Intended to be embedded as
    ``response["provenance_sbom"]`` on every RAF response.

    Raises
    ------
    CoefficientPinDriftError
        In non-development environments when hccinfhir version is off-spec
        and ``ALLOW_COEFFICIENT_DRIFT`` is not set to true.
    """
    _assert_no_coefficient_drift()

    return {
        "schema_version": "1",
        "models_used": sorted(set(models_used)),
        "payment_year": payment_year,
        "plan_type": plan_type,
        "frailty_applied": frailty_applied,
        "coefficient_source_runtime": coefficient_source(),
        "coefficient_source_manifest": _manifest_pin(),
        "coefficient_pin_drift": _runtime_vs_pin_drift(),
        "coefficient_manifest_hash": coefficient_manifest_hash(),
        "calculator_commit_sha": calculator_commit_sha(),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        ),
    }
