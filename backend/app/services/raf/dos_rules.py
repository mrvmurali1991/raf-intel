"""
CMS-HCC Date-of-Service (DOS) window and eligible-encounter rules.

This module is the SINGLE SOURCE OF TRUTH for:

  1. Which dates of service count toward a given CMS payment year (PY).
  2. Which provider/encounter types qualify as "face-to-face" for risk
     adjustment under CMS-HCC.
  3. The V24 / V28 blend weights CMS applies when computing the final
     risk score for PY2024, PY2025, and PY2026.

Any code that filters encounters for RAF scoring, suspect detection, or
MEAT evidence gathering MUST call :func:`is_eligible_encounter` or
:func:`filter_encounters_for_py` — no hand-rolled ``YEAR(date) == X``
SQL or ``if enc_type == "telehealth"`` branches anywhere else.

CMS source citations
--------------------
* **DOS window** — CMS-HCC risk scores for payment year Y use diagnoses
  from qualifying face-to-face encounters dated ``1/1/(Y-1)`` through
  ``12/31/(Y-1)`` (the "data collection year").  The model-segment-level
  rule is laid out in the CMS *Advance Notice* and finalised in the
  *Rate Announcement* every spring.  See:
    - 2024 Rate Announcement (PY2024), pp. 77-82
    - 2025 Rate Announcement (PY2025), Section II.B.1
    - 2026 Rate Announcement (PY2026), Section II.B.1

* **Eligible encounter types** — CMS has historically accepted diagnoses
  from three RAPS/EDPS encounter categories:
    - Inpatient hospital
    - Outpatient hospital
    - Professional (physician / qualified non-physician practitioner,
      face-to-face)
  Lab-only, DME, pharmacy, and non-face-to-face encounters are NOT
  eligible for risk-score submission.  See CMS *Risk Adjustment
  Processing System (RAPS) Participant Guide* and the *Medicare
  Managed Care Manual, Chapter 7*.

  **Telehealth** was permanently added as eligible face-to-face
  equivalent by CMS starting with CY2020 services (42 CFR §422.2),
  **only** when the underlying encounter is professional / outpatient.
  This module treats ``telehealth`` as eligible for PY2021+.

* **V24 → V28 transition blend** — CMS phased in the V28 model over
  three years (2026 PY and beyond are 100% V28).  Blend weights:
    - PY2024:  67% V24 / 33% V28   (2024 Rate Announcement, p. 80)
    - PY2025:  33% V24 / 67% V28   (2025 Rate Announcement, p. 70)
    - PY2026+:  0% V24 / 100% V28  (2026 Rate Announcement, p. 61)

Nothing in this module applies RAF coefficient math — it only decides
WHICH encounters feed the scorer and WHICH blend weights apply.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Iterable, Mapping, Protocol


# ---------------------------------------------------------------------------
# Eligible encounter categories
# ---------------------------------------------------------------------------

# Canonical CMS-face-to-face encounter type labels.  These are normalised
# (lower, stripped) before matching.
#
# The three RAPS/EDPS CMS-approved categories plus telehealth (explicitly
# accepted as a professional face-to-face substitute for services on/after
# 1/1/2020 per CMS-4203-F / 42 CFR §422.2).
ELIGIBLE_ENCOUNTER_TYPES: frozenset[str] = frozenset({
    "inpatient",
    "outpatient",
    "professional",
    "telehealth",
})

# Ineligible categories we actively reject with a human-readable reason.
# Anything not in ELIGIBLE_ENCOUNTER_TYPES is rejected; this table just
# gives a friendlier reason string for common cases the UI sees.
_KNOWN_INELIGIBLE_TYPES: Mapping[str, str] = {
    "lab":              "lab-only encounter not eligible for risk-score submission",
    "pharmacy":         "pharmacy-only encounter not eligible for risk-score submission",
    "dme":              "DME claim not eligible for risk-score submission",
    "institutional":    "institutional-only (SNF cost report) not face-to-face eligible",
    "snf":              "SNF cost-report encounter not face-to-face eligible",
    "hospice":          "hospice encounter excluded under CMS risk-adjustment rules",
    "ambulance":        "ambulance transport is not a face-to-face service",
    "home_health":      "home-health agency claim not face-to-face eligible",
    "unknown":          "encounter_type is unknown and therefore not accepted",
}


# ---------------------------------------------------------------------------
# Payment-year window registry
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PaymentYearWindow:
    """
    The CMS-defined DOS window and V24/V28 blend for a single payment year.

    Attributes
    ----------
    year:
        CMS payment year, e.g. ``2025``.
    dos_start:
        Inclusive start of the data collection window.  Per CMS rules this
        is ``date(year - 1, 1, 1)`` for all three supported PYs.
    dos_end:
        Inclusive end of the data collection window.  Per CMS rules this
        is ``date(year - 1, 12, 31)`` for all three supported PYs.
    model_blend:
        Mapping of model name ("V24" / "V28") to fractional weight.
        Weights always sum to 1.0.
    """
    year: int
    dos_start: date
    dos_end: date
    model_blend: Mapping[str, float]

    def __post_init__(self) -> None:
        # Defensive: keep the data model self-validating so a typo in the
        # registry below is caught at import time.
        total = round(sum(self.model_blend.values()), 6)
        if total != 1.0:
            raise ValueError(
                f"PaymentYearWindow(year={self.year}) blend weights must sum to 1.0, "
                f"got {total} from {dict(self.model_blend)}"
            )
        if self.dos_end < self.dos_start:
            raise ValueError(
                f"PaymentYearWindow(year={self.year}) dos_end {self.dos_end} "
                f"is before dos_start {self.dos_start}"
            )


PAYMENT_YEARS: dict[int, PaymentYearWindow] = {
    # PY2024 — 2024 Rate Announcement (Apr 2023), final blend confirmed Feb 2024.
    # 67% V24 / 33% V28 during the V28 phase-in.
    2024: PaymentYearWindow(
        year=2024,
        dos_start=date(2023, 1, 1),
        dos_end=date(2023, 12, 31),
        model_blend={"V24": 0.67, "V28": 0.33},
    ),
    # PY2025 — 2025 Rate Announcement (Mar 2024).  Middle year of the
    # phase-in: 33% V24 / 67% V28.
    2025: PaymentYearWindow(
        year=2025,
        dos_start=date(2024, 1, 1),
        dos_end=date(2024, 12, 31),
        model_blend={"V24": 0.33, "V28": 0.67},
    ),
    # PY2026 — 2026 Rate Announcement (Apr 2025).  V28 becomes 100%; V24
    # blend weight goes to zero.
    2026: PaymentYearWindow(
        year=2026,
        dos_start=date(2025, 1, 1),
        dos_end=date(2025, 12, 31),
        model_blend={"V24": 0.00, "V28": 1.00},
    ),
    # PY2027 — projected 100% V28 (no phase-in blend).  DOS window follows
    # standard CMS rule: data collected from PY-1.  Update model_blend if
    # CMS 2027 Advance Notice (expected Jan 2026) introduces changes.
    2027: PaymentYearWindow(
        year=2027,
        dos_start=date(2026, 1, 1),
        dos_end=date(2026, 12, 31),
        model_blend={"V24": 0.00, "V28": 1.00},
    ),
}


# ---------------------------------------------------------------------------
# Encounter protocol
# ---------------------------------------------------------------------------

class Encounter(Protocol):
    """
    Structural protocol for anything with a date and encounter_type.

    Any dict or dataclass with ``date`` / ``encounter_date`` and
    ``encounter_type`` / ``type`` keys is acceptable — the helpers in
    this module never mutate the input.
    """
    def get(self, key: str, default: object = ...) -> object: ...  # pragma: no cover


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def get_payment_year_window(payment_year: int) -> PaymentYearWindow:
    """
    Return the :class:`PaymentYearWindow` for *payment_year*.

    Raises
    ------
    KeyError
        If *payment_year* is not in :data:`PAYMENT_YEARS`.  Callers who
        want a graceful fallback should catch this and log a warning.
    """
    try:
        return PAYMENT_YEARS[payment_year]
    except KeyError as exc:
        raise KeyError(
            f"Unknown CMS payment year {payment_year}; supported: "
            f"{sorted(PAYMENT_YEARS.keys())}"
        ) from exc


def get_blend_weights(payment_year: int) -> Mapping[str, float]:
    """
    Return the V24/V28 blend weights mapping for *payment_year*.

    This is the ONLY place in the codebase that should know about the
    V28 phase-in schedule.  Everything else must import from here so a
    future CMS blend change is a one-line edit.
    """
    return get_payment_year_window(payment_year).model_blend


# ---------------------------------------------------------------------------
# Eligibility check
# ---------------------------------------------------------------------------

def _coerce_date(value: object) -> date | None:
    """
    Normalise a DOS value (str | date | datetime | None) to :class:`date`.

    Accepts ISO-8601 dates/datetimes; returns ``None`` on any parse error so
    callers can surface a proper reason instead of raising.
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        # Common DB formats: "2024-03-15", "2024-03-15 09:30:00", ISO-8601 with T.
        text = value.strip()
        if not text:
            return None
        # Try date first, then full datetime, then first 10 chars (YYYY-MM-DD).
        for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(text[: len(fmt) + 4], fmt).date()
            except ValueError:
                continue
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None
    return None


def _extract_encounter_type(encounter: Mapping[str, object]) -> str:
    """Return a lowercase, stripped encounter-type string, or ``""``."""
    for key in ("encounter_type", "type", "encounter_category"):
        raw = encounter.get(key) if hasattr(encounter, "get") else None
        if raw:
            return str(raw).strip().lower()
    return ""


def _extract_dos(encounter: Mapping[str, object]) -> object:
    """Return the first DOS-like field present on the encounter."""
    for key in ("date", "encounter_date", "dos", "service_date"):
        if hasattr(encounter, "get"):
            val = encounter.get(key)
            if val:
                return val
    return None


def is_eligible_encounter(
    encounter: Mapping[str, object],
    payment_year: int,
) -> tuple[bool, str]:
    """
    Decide whether *encounter* contributes to the RAF score for *payment_year*.

    Parameters
    ----------
    encounter:
        Any mapping with a DOS field (``date`` / ``encounter_date`` /
        ``dos`` / ``service_date``) and an encounter-type field
        (``encounter_type`` / ``type`` / ``encounter_category``).
    payment_year:
        CMS payment year (2024, 2025, or 2026 today).

    Returns
    -------
    tuple[bool, str]
        ``(True, "")`` when the encounter qualifies.
        ``(False, reason)`` when it does not, where *reason* is a short
        human-readable string safe to surface in the UI
        (e.g. ``"DOS 2023-11-15 outside PY2025 window (2024-01-01..2024-12-31)"``).
    """
    try:
        window = get_payment_year_window(payment_year)
    except KeyError as exc:
        return False, str(exc)

    # -- Encounter type ----------------------------------------------------
    etype = _extract_encounter_type(encounter)
    if not etype:
        return False, "encounter_type missing; cannot verify face-to-face eligibility"
    if etype not in ELIGIBLE_ENCOUNTER_TYPES:
        hint = _KNOWN_INELIGIBLE_TYPES.get(etype)
        if hint:
            return False, f"encounter_type={etype} not eligible: {hint}"
        return False, (
            f"encounter_type={etype} not eligible; must be one of "
            f"{sorted(ELIGIBLE_ENCOUNTER_TYPES)}"
        )

    # -- DOS window --------------------------------------------------------
    raw_dos = _extract_dos(encounter)
    dos = _coerce_date(raw_dos)
    if dos is None:
        return False, "encounter has no parseable date-of-service"

    if dos < window.dos_start or dos > window.dos_end:
        return False, (
            f"DOS {dos.isoformat()} outside PY{payment_year} window "
            f"({window.dos_start.isoformat()}..{window.dos_end.isoformat()})"
        )

    return True, ""


def filter_encounters_for_py(
    encounters: Iterable[Mapping[str, object]],
    payment_year: int,
) -> list[Mapping[str, object]]:
    """
    Return the subset of *encounters* eligible for *payment_year*.

    The input iterable is not mutated; each surviving element is the
    original object reference (cheap pass-through).

    Callers that need to know WHY each dropped encounter was excluded
    should use :func:`is_eligible_encounter` directly and collect the
    reasons alongside.
    """
    kept: list[Mapping[str, object]] = []
    for enc in encounters:
        ok, _reason = is_eligible_encounter(enc, payment_year)
        if ok:
            kept.append(enc)
    return kept


def partition_encounters_for_py(
    encounters: Iterable[Mapping[str, object]],
    payment_year: int,
) -> tuple[list[Mapping[str, object]], list[dict[str, object]]]:
    """
    Split *encounters* into (eligible, excluded_with_reason).

    The second list contains dicts of the form::

        {"encounter": <original>, "reason": "DOS ... outside ..."}

    so API responses can surface exclusion reasons to end users.
    """
    eligible: list[Mapping[str, object]] = []
    excluded: list[dict[str, object]] = []
    for enc in encounters:
        ok, reason = is_eligible_encounter(enc, payment_year)
        if ok:
            eligible.append(enc)
        else:
            excluded.append({"encounter": enc, "reason": reason})
    return eligible, excluded


# Silence F401 for time — kept imported for future TZ-aware edge-case support.
_ = time
