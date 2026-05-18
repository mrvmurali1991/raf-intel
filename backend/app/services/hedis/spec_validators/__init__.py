"""HEDIS NCQA spec self-validators package.

Each module in this package provides a ``validate_measure_spec(measurement_year)``
function that returns a structured self-validation report for one HEDIS measure.

The validators encode what the publicly documented NCQA HEDIS technical
specification summary says (age ranges, look-back windows, value-set OIDs,
exclusion criteria) and compare those requirements against the implementation in
``app.services.hedis.measures``.

IMPORTANT: These reports reflect *self-validation* against publicly available
NCQA specification summaries.  They do NOT constitute official NCQA
certification.  External NCQA certification by a licensed vendor is required
before submitting rates to payers or CMS.
"""

from app.services.hedis.spec_validators.bcs import validate_measure_spec as validate_bcs
from app.services.hedis.spec_validators.ccs import validate_measure_spec as validate_ccs
from app.services.hedis.spec_validators.hbd import validate_measure_spec as validate_hbd
from app.services.hedis.spec_validators.cbp import validate_measure_spec as validate_cbp
from app.services.hedis.spec_validators.fum import validate_measure_spec as validate_fum

VALIDATORS = {
    "BCS": validate_bcs,
    "CCS": validate_ccs,
    "HBD": validate_hbd,
    "CBP": validate_cbp,
    "FUM": validate_fum,
}

__all__ = ["VALIDATORS", "validate_bcs", "validate_ccs", "validate_hbd", "validate_cbp", "validate_fum"]
