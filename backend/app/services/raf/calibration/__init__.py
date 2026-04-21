"""
Suspect-confidence calibration layer.

Raw confidence scores produced by the four suspect sources (regex/rule,
lab, med, llm) live in [0, 1] but they are **not** calibrated against a
ground-truth label.  A raw 0.8 from the regex path has no formal claim to
being the same "probability the suspect is a real, billable condition" as
a raw 0.8 from the LLM path.  This module converts per-source raw scores
into calibrated probabilities that a downstream consumer (UX sort order,
dollar-weighted prioritisation, auto-triage threshold) can actually treat
as a probability.

----------------------------------------------------------------------
IMPORTANT — READ BEFORE TRUSTING THESE NUMBERS
----------------------------------------------------------------------

1. **This is NOT chart-reviewer calibrated.**  The v1 calibrators shipped
   in ``calibration/models/*.joblib`` are fit against a *synthetic*
   labelled set produced by ``bootstrap.py`` from heuristics we think
   are reasonable (corroborating-signals-positive, negated / single-weak-
   signal-negative).  If those heuristics are systematically wrong, the
   calibrator will faithfully reproduce that bias.  **Bootstrap
   calibration improves nothing if the bootstrap rules are wrong.**

2. **Evaluation metric.**  When a real labelled set exists (chart review
   accept / dismiss outcomes from ``raf_suspect_conditions.status``), the
   right metrics are:
     - Brier score  (mean squared error between calibrated p and label)
     - Expected Calibration Error (ECE, 10 bins)
     - Reliability diagram (bucketed p vs empirical positive rate)
   These live nowhere in code today — add them when we have a holdout.

3. **Retraining with labelled data — exact steps.**
   a. Export labelled rows from production::

        SELECT evidence_type AS source,
               confidence_score AS raw_score,
               CASE status
                 WHEN 'accepted' THEN 1
                 WHEN 'coded'    THEN 1
                 WHEN 'dismissed' THEN 0
               END AS label
        FROM   raf_suspect_conditions
        WHERE  status IN ('accepted','coded','dismissed')
          AND  reviewed_at IS NOT NULL;

   b. Save as CSV with columns ``source,raw_score,label`` (one row per
      reviewed suspect).  Drop the synthetic bootstrap CSV or rename it.
   c. Run::

        python backend/scripts/fit_calibrators.py --input path/to/labels.csv

      This refits Platt and Isotonic per source and writes the
      ``.joblib`` artifacts under ``models/``.
   d. Commit the refit artifacts.  Do NOT refit in CI — artifacts are
      part of the release bundle and must be reviewed.
   e. Flip ``settings.use_calibrated_confidence`` on in the env you are
      rolling out to; leave the old raw score around for A/B.

4. **Runtime contract.**  Each suspect now exposes::

        raw_confidence         float in [0, 1]     (unchanged)
        calibrated_confidence  float in [0, 1]     (new, may == raw)

   When no calibrator artifact exists for a source, calibrated = raw
   (identity fallback) and a warning is logged once.
"""
from __future__ import annotations

from .calibrator import (
    Calibrator,
    IdentityCalibrator,
    IsotonicCalibrator,
    PlattCalibrator,
)
from .persistence import (
    available_sources,
    calibrate,
    load_calibrator,
    save_calibrator,
)

__all__ = [
    "Calibrator",
    "IdentityCalibrator",
    "IsotonicCalibrator",
    "PlattCalibrator",
    "available_sources",
    "calibrate",
    "load_calibrator",
    "save_calibrator",
]
