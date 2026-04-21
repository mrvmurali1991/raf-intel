"""
Calibrator ABC and concrete implementations.

Two standard techniques:

* :class:`PlattCalibrator` — fit a 1-D logistic regression mapping raw
  score -> P(label=1).  Robust with small samples, assumes a sigmoid
  relationship.  Good default when N < 1k.
* :class:`IsotonicCalibrator` — fit a non-parametric, monotone-increasing
  step function.  Better than Platt when there are enough labels
  (N > ~1k) because it can recover arbitrary monotone shapes, but
  overfits on small samples.

Both preserve ordering, both return values clamped to ``[0, 1]``.

The ABC also defines :class:`IdentityCalibrator`, used as the safe
fallback when no model artifact exists on disk for a given source —
calibrated == raw, so callers can keep calling ``.transform`` and not
have to branch on "is the calibrator trained".
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod

import numpy as np

logger = logging.getLogger(__name__)

# Lazy sklearn import — sklearn is a heavy dependency and the identity
# fallback does not need it.  The Platt / Isotonic classes import inside
# their methods so that a minimal runtime without sklearn can still load
# this module and get IdentityCalibrator.


class Calibrator(ABC):
    """Abstract base.  ``fit`` then ``transform``."""

    #: Set to True by subclasses after a successful ``fit``.
    fitted: bool

    def __init__(self) -> None:
        self.fitted = False

    @abstractmethod
    def fit(self, raw_scores: np.ndarray, labels: np.ndarray) -> "Calibrator":
        """Fit on paired ``(raw_score, label)`` arrays.

        *raw_scores* are floats in [0, 1].  *labels* are 0/1.  Returns
        ``self`` so callers can chain.
        """

    @abstractmethod
    def transform(self, raw_scores: np.ndarray) -> np.ndarray:
        """Return calibrated probabilities for an array of raw scores."""

    # Convenience: accept scalar or array.
    def transform_one(self, raw: float) -> float:
        arr = np.asarray([float(raw)], dtype=float)
        return float(self.transform(arr)[0])


class IdentityCalibrator(Calibrator):
    """No-op passthrough.  Used when no trained artifact exists."""

    def __init__(self) -> None:
        super().__init__()
        # Identity is "fitted" by definition — there is nothing to fit.
        self.fitted = True

    def fit(self, raw_scores: np.ndarray, labels: np.ndarray) -> "IdentityCalibrator":
        return self

    def transform(self, raw_scores: np.ndarray) -> np.ndarray:
        arr = np.asarray(raw_scores, dtype=float)
        return np.clip(arr, 0.0, 1.0)


class PlattCalibrator(Calibrator):
    """Logistic regression on a single feature (the raw score).

    Uses sklearn's ``LogisticRegression`` with no regularisation penalty
    tuning beyond the defaults.  Kept deliberately simple; the whole
    point of Platt scaling is to be the sane default when labelled data
    is scarce.
    """

    def __init__(self) -> None:
        super().__init__()
        self._model = None  # sklearn LogisticRegression, set at fit time

    def fit(self, raw_scores: np.ndarray, labels: np.ndarray) -> "PlattCalibrator":
        from sklearn.linear_model import LogisticRegression

        x = np.asarray(raw_scores, dtype=float).reshape(-1, 1)
        y = np.asarray(labels, dtype=int).ravel()

        if x.shape[0] == 0:
            raise ValueError("PlattCalibrator.fit called with no samples.")
        if set(np.unique(y).tolist()) - {0, 1}:
            raise ValueError("PlattCalibrator labels must be 0 or 1.")
        if len(np.unique(y)) < 2:
            # sklearn refuses to fit on one class.  Degenerate but can
            # happen on tiny toy datasets.  Fall back to the empirical
            # base rate so callers still get *something* sensible.
            logger.warning(
                "PlattCalibrator.fit: only one class present — "
                "using degenerate constant calibrator at base rate=%.3f",
                float(y.mean()) if y.size else 0.5,
            )
            self._constant = float(y.mean()) if y.size else 0.5
            self._model = None
            self.fitted = True
            return self

        self._constant = None
        self._model = LogisticRegression(
            solver="lbfgs",
            max_iter=1000,
        ).fit(x, y)
        self.fitted = True
        return self

    def transform(self, raw_scores: np.ndarray) -> np.ndarray:
        if not self.fitted:
            raise RuntimeError("PlattCalibrator.transform called before fit().")
        arr = np.asarray(raw_scores, dtype=float).reshape(-1, 1)
        if self._model is None:
            # Degenerate constant calibrator.  ``self._constant`` may be
            # exactly 0.0; do NOT use ``or 0.5`` here — that would flip a
            # genuine base-rate-zero to 0.5.
            const = self._constant if self._constant is not None else 0.5
            out = np.full(arr.shape[0], float(const))
        else:
            probs = self._model.predict_proba(arr)
            # sklearn always orders classes ascending: [class=0, class=1]
            out = probs[:, 1]
        return np.clip(out, 0.0, 1.0)


class IsotonicCalibrator(Calibrator):
    """Non-parametric monotone calibration."""

    def __init__(self) -> None:
        super().__init__()
        self._model = None  # sklearn IsotonicRegression

    def fit(self, raw_scores: np.ndarray, labels: np.ndarray) -> "IsotonicCalibrator":
        from sklearn.isotonic import IsotonicRegression

        x = np.asarray(raw_scores, dtype=float).ravel()
        y = np.asarray(labels, dtype=float).ravel()
        if x.shape[0] == 0:
            raise ValueError("IsotonicCalibrator.fit called with no samples.")

        self._model = IsotonicRegression(
            y_min=0.0,
            y_max=1.0,
            out_of_bounds="clip",
            increasing=True,
        ).fit(x, y)
        self.fitted = True
        return self

    def transform(self, raw_scores: np.ndarray) -> np.ndarray:
        if not self.fitted or self._model is None:
            raise RuntimeError("IsotonicCalibrator.transform called before fit().")
        arr = np.asarray(raw_scores, dtype=float).ravel()
        out = self._model.predict(arr)
        return np.clip(out, 0.0, 1.0)
