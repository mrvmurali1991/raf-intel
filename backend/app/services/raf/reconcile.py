"""RAF reconciliation — cross-check hccinfhir against CMS-published tables.

This module is the independent audit layer between the third-party
``hccinfhir`` library and CMS's own publicly released coefficient /
hierarchy tables.  It exists because we trust hccinfhir blindly in the
RAF scoring hot path today; that is a RADV audit defect.  The
reconciliation gives us:

  * A build-time gate (see :file:`backend/scripts/check_cms_reconciliation.py`)
    that fails CI if hccinfhir's bundled coefficients drift from our
    hand-transcribed CMS reference CSVs.
  * A runtime guard (:func:`validate_hierarchy`) that refuses to emit a
    score when hccinfhir's hierarchy output diverges from an independent
    re-implementation of the CMS trumping rules.

Public API
----------

* :func:`reconcile_coefficients(model, payment_year)` -> ReconciliationReport
* :func:`validate_hierarchy(hccs, model)` -> list[int]
* :class:`HierarchyMismatchError`
* :class:`ReconciliationReport`

Reference CSVs live at :mod:`app.services.raf.cms_reference` —
see that package's docstring for sourcing rules.
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Maximum allowed absolute difference between our reference CSV value and
#: hccinfhir's bundled value before the reconciliation gate fails.
EPSILON: float = 0.0001

#: Root of the CMS reference CSV tree.
_CMS_REF_ROOT: Path = Path(__file__).resolve().parent / "cms_reference"
_COEFF_DIR: Path = _CMS_REF_ROOT / "coefficient_tables"
_HIER_DIR: Path = _CMS_REF_ROOT / "hierarchy"

#: Supported models for reconciliation.  Other models (ESRD, PACE, RxHCC)
#: will be added as we publish their reference CSVs.
ModelKey = Literal["V24", "V28"]

#: Map (model, payment_year) -> reference CSV filename (under _COEFF_DIR).
#: A missing entry means "no published CMS table for that year yet" — the
#: CI gate skips it and logs a SOURCE_PENDING warning.
_COEFFICIENT_FILES: dict[tuple[str, int], str] = {
    ("V28", 2026): "v28_community_nondual_aged_2026.csv",
    ("V28", 2025): "v28_community_nondual_aged_2025.csv",
    ("V24", 2024): "v24_community_nondual_aged_2024.csv",
}

#: Map model -> reference hierarchy CSV (year-independent — CMS hierarchy
#: rules are fixed once a model version is finalized).
_HIERARCHY_FILES: dict[str, str] = {
    "V24": "v24_hierarchy.csv",
    "V28": "v28_hierarchy.csv",
}

#: Map short model key to the full hccinfhir ModelName string.
_MODEL_NAMES: dict[str, str] = {
    "V24": "CMS-HCC Model V24",
    "V28": "CMS-HCC Model V28",
}

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class HierarchyMismatchError(RuntimeError):
    """Raised when hccinfhir's applied hierarchy diverges from the independent
    re-implementation backed by :file:`cms_reference/hierarchy/`."""


class CoefficientReferenceMissingError(FileNotFoundError):
    """The reference CSV for a requested (model, year) does not exist."""


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CoefficientDiff:
    """A single divergence between reference CSV and hccinfhir."""

    kind: str                  # "hcc" | "demo"
    key: str                   # HCC number as str, or demographic key (e.g. "F65_69")
    reference_value: float | None
    library_value: float | None
    delta: float | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "key": self.key,
            "reference_value": self.reference_value,
            "library_value": self.library_value,
            "delta": self.delta,
        }


@dataclass
class ReconciliationReport:
    """Result of reconciling one (model, payment_year) against hccinfhir."""

    model: str
    payment_year: int
    reference_csv: str
    epsilon: float
    checked_count: int = 0
    diffs: list[CoefficientDiff] = field(default_factory=list)
    source_pending: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True if no material diffs were found."""
        return not self.diffs and not self.source_pending

    def as_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "payment_year": self.payment_year,
            "reference_csv": self.reference_csv,
            "epsilon": self.epsilon,
            "checked_count": self.checked_count,
            "source_pending": self.source_pending,
            "ok": self.ok,
            "diffs": [d.as_dict() for d in self.diffs],
            "notes": list(self.notes),
        }


# ---------------------------------------------------------------------------
# CSV loaders (no external deps — stdlib csv is fine for <100 rows)
# ---------------------------------------------------------------------------


def _load_coefficient_csv(path: Path) -> list[dict[str, str]]:
    """Load a coefficient reference CSV, skipping ``#`` comment lines.

    Returns a list of dict rows with keys ``kind``, ``key``, ``value``, ``label``.
    """
    rows: list[dict[str, str]] = []
    with path.open() as f:
        # Strip comment lines that start with '#' so DictReader sees the header.
        data_lines = [ln for ln in f if ln.strip() and not ln.lstrip().startswith("#")]
    reader = csv.DictReader(data_lines)
    for row in reader:
        rows.append({k: (v or "").strip() for k, v in row.items()})
    return rows


def _load_hierarchy_csv(path: Path) -> set[tuple[int, int]]:
    """Load a hierarchy reference CSV, skipping ``#`` comment lines.

    Returns a set of (parent, child) integer pairs.
    """
    pairs: set[tuple[int, int]] = set()
    with path.open() as f:
        data_lines = [ln for ln in f if ln.strip() and not ln.lstrip().startswith("#")]
    reader = csv.DictReader(data_lines)
    for row in reader:
        parent = int((row.get("hcc_parent") or "").strip())
        child = int((row.get("hcc_child") or "").strip())
        pairs.add((parent, child))
    return pairs


# ---------------------------------------------------------------------------
# Public reconciliation API
# ---------------------------------------------------------------------------


def list_supported_combos() -> list[tuple[str, int]]:
    """Return every (model, payment_year) pair with a reference CSV present."""
    return sorted(_COEFFICIENT_FILES.keys())


def reconcile_coefficients(
    model: str,
    payment_year: int,
    *,
    epsilon: float = EPSILON,
) -> ReconciliationReport:
    """Reconcile the reference CSV for (model, payment_year) against hccinfhir.

    Loads the committed CMS reference CSV, then pulls the corresponding value
    out of hccinfhir's ``coefficients_default`` dict and diffs them.  The
    prefix in use is ``cna_`` (Community Non-Dual Aged) — the most common
    community segment and the one CMS publishes in its Rate Announcement
    coefficient tables.  HCC coefficients and demographic (age/sex) factors
    are both checked.

    Args:
        model:         "V24" or "V28".
        payment_year:  CMS payment year (e.g. 2024, 2025, 2026).
        epsilon:       Max absolute delta treated as matching.

    Returns:
        :class:`ReconciliationReport`.  ``report.ok`` is True iff every
        reference row matches hccinfhir within ``epsilon``.

    Raises:
        CoefficientReferenceMissingError: if no CSV exists for (model, year).
    """
    key = (model, payment_year)
    if key not in _COEFFICIENT_FILES:
        raise CoefficientReferenceMissingError(
            f"No CMS reference CSV registered for model={model} year={payment_year}. "
            f"Supported combos: {list_supported_combos()}"
        )

    csv_path = _COEFF_DIR / _COEFFICIENT_FILES[key]
    report = ReconciliationReport(
        model=model,
        payment_year=payment_year,
        reference_csv=str(csv_path),
        epsilon=epsilon,
    )

    # Detect SOURCE_PENDING marker (a stub CSV we've not yet transcribed).
    head = csv_path.read_text().splitlines()
    if any("SOURCE_PENDING" in ln.upper() for ln in head[:10]):
        report.source_pending = True
        report.notes.append(
            "Reference CSV marked SOURCE_PENDING — coefficients not transcribed yet."
        )
        return report

    try:
        from hccinfhir.defaults import coefficients_default  # type: ignore[import-untyped]
    except ImportError as exc:   # pragma: no cover — hccinfhir is a hard dep
        report.notes.append(f"hccinfhir import failed: {exc}")
        return report

    model_name = _MODEL_NAMES[model]
    ref_rows = _load_coefficient_csv(csv_path)

    for row in ref_rows:
        kind = row["kind"]
        key_s = row["key"]
        try:
            ref_val: float | None = float(row["value"]) if row["value"] else None
        except ValueError:
            ref_val = None

        # Build the hccinfhir coefficient lookup key.
        if kind == "hcc":
            hccinfhir_key = f"cna_hcc{key_s}"
        elif kind == "demo":
            hccinfhir_key = f"cna_{key_s.lower()}"
        else:
            report.notes.append(f"Unknown kind={kind!r} in row {row!r}; skipped")
            continue

        lib_val = coefficients_default.get((hccinfhir_key, model_name))
        report.checked_count += 1

        # Compute delta / decide diff.
        if ref_val is None and lib_val is None:
            continue
        if ref_val is None or lib_val is None:
            report.diffs.append(
                CoefficientDiff(
                    kind=kind,
                    key=key_s,
                    reference_value=ref_val,
                    library_value=lib_val,
                    delta=None,
                )
            )
            continue

        delta = abs(float(lib_val) - ref_val)
        if delta > epsilon:
            report.diffs.append(
                CoefficientDiff(
                    kind=kind,
                    key=key_s,
                    reference_value=ref_val,
                    library_value=float(lib_val),
                    delta=delta,
                )
            )

    return report


# ---------------------------------------------------------------------------
# Hierarchy validation (runtime hot-path check)
# ---------------------------------------------------------------------------


def _load_hierarchy_pairs(model: str) -> set[tuple[int, int]]:
    if model not in _HIERARCHY_FILES:
        raise CoefficientReferenceMissingError(
            f"No CMS reference hierarchy CSV for model={model}. "
            f"Supported: {sorted(_HIERARCHY_FILES)}"
        )
    return _load_hierarchy_csv(_HIER_DIR / _HIERARCHY_FILES[model])


def _independent_trim(hccs: list[int], pairs: set[tuple[int, int]]) -> list[int]:
    """Independent re-implementation of CMS HCC trumping.

    For every (parent, child) rule in ``pairs``: if ``parent`` is present in
    ``hccs``, ``child`` must be suppressed.  This is deliberately written
    from scratch without reference to hccinfhir so it can serve as a
    cross-check.
    """
    present = set(hccs)
    suppressed: set[int] = set()
    for parent, child in pairs:
        if parent in present and child in present:
            suppressed.add(child)
    return sorted(present - suppressed)


def validate_hierarchy(hccs: list[int], model: str) -> list[int]:
    """Independently trim child HCCs per CMS rules and cross-check hccinfhir.

    Args:
        hccs:    List of HCC integer codes that hccinfhir has emitted after
                 its own hierarchy application.  Order does not matter.
        model:   "V24" or "V28".

    Returns:
        The sorted list of HCC codes that remain after independent trimming.
        Equal in length and content to ``hccs`` on success.

    Raises:
        HierarchyMismatchError: if any HCC in the input would have been
            trimmed by an independent application of CMS trumping rules.
            This means hccinfhir failed to drop a child HCC whose parent is
            present — a billing/payment safety issue.
    """
    pairs = _load_hierarchy_pairs(model)
    trimmed = _independent_trim(hccs, pairs)
    # hccinfhir should already have trimmed. If our trim drops anything,
    # that is a divergence.
    if sorted(hccs) != trimmed:
        dropped = sorted(set(hccs) - set(trimmed))
        raise HierarchyMismatchError(
            f"hccinfhir returned HCCs {sorted(hccs)} but CMS {model} hierarchy "
            f"rules require dropping {dropped}.  Refusing to emit score."
        )
    return trimmed
