"""RAF numeric precision & rounding policy.

Every score and coefficient the RAF engine emits flows through a
rounding step. CMS publishes risk scores to 3 decimal places in rate
announcements but the payment calculation carries 4-decimal precision
through intermediate sums. Getting the rounding *boundary* behaviour
right is what separates an engine that matches CMS to the cent vs one
that drifts by 0.001 on edge cases.

This module documents our policy in one place so any change is
auditable.

Policy
------
1. **Intermediate sums, blend contributions, disease scores**: rounded
   to **4 decimal places** with Python's default round-half-to-even
   (banker's rounding). This matches the ``hccinfhir`` reference
   implementation that currently supplies our coefficients.
2. **Final published RAF (``payment_raf``)**: rounded to **4 decimals**.
   CMS publishes to 3, but we retain the extra digit for auditability;
   downstream consumers truncate at their own layer.
3. **Coefficient table values**: stored at **6-decimal precision** in
   snapshot fixtures (source precision of hccinfhir); this is wider than
   what we emit so no information is lost at the fixture boundary.

Boundary behaviour
------------------
Python's ``round()`` uses *banker's rounding*: values exactly halfway
between two representable results round to the nearest **even** last
digit. For example:
  * ``round(0.12345, 4) == 0.1234`` (even)
  * ``round(0.12355, 4) == 0.1236`` (even)

This is stable against accumulated floating-point error but differs
from the "half-away-from-zero" intuition. The test suite locks these
boundaries so a future migration to Decimal or to CMS SAS ``ROUND``
semantics is a deliberate, reviewed change.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

# The four decimal precision we emit everywhere.
RAF_PRECISION: int = 4

# Published CMS precision (for reference; we always store one digit wider).
CMS_PUBLISHED_PRECISION: int = 3


def round_raf(value: float, decimals: int = RAF_PRECISION) -> float:
    """Round a RAF value to the engine's standard precision.

    Uses banker's rounding to match the reference implementation we
    reconcile against. Callers that need half-away-from-zero (to mirror
    a CMS SAS ``ROUND`` call on a batch report, say) should use
    :func:`round_raf_half_up` instead and document why.
    """
    return round(value, decimals)


def round_raf_half_up(value: float, decimals: int = RAF_PRECISION) -> float:
    """Round using half-away-from-zero (SAS / CMS report convention).

    Intentionally implemented via ``Decimal`` to avoid floating-point
    boundary ambiguity.  Use ONLY at the presentation boundary — the
    core calculator uses :func:`round_raf` for internal arithmetic.
    """
    if value == 0:
        return 0.0
    q = Decimal(str(value)).quantize(
        Decimal(10) ** -decimals, rounding=ROUND_HALF_UP
    )
    return float(q)


def sum_to_precision(*terms: float, decimals: int = RAF_PRECISION) -> float:
    """Sum a sequence of floats and round the result once.

    Avoids the intermediate-rounding drift that comes from rounding
    each addend separately and then summing.
    """
    return round_raf(sum(terms), decimals)
