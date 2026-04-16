# DISCLAIMER: This module calculates CMS-HCC risk adjustment scores using the
# hccinfhir library, which is a third-party open-source implementation of the
# CMS-HCC model. It is NOT validated or endorsed by CMS. Results should be
# verified against the official CMS SAS software before use in payment
# determinations. This tool is designed for clinical analytics, gap identification,
# and prospective risk assessment — not for payment submission.

"""
Backward-compatibility facade.

All implementation has moved to the app.services.raf subpackage:
  app/services/raf/icd_formatter.py       — ICD-10 formatting, ESRD code sets
  app/services/raf/blend_weights.py       — blend weight tables, norm/MACI factors
  app/services/raf/enrollment_resolver.py — segment routing, enrollment resolution
  app/services/raf/score_persistence.py   — DB upsert helpers
  app/services/raf/calculator.py          — main orchestrator, breakdown, batch

Importing anything from this module continues to work without changes in any
router, service, or test file.
"""

# Re-export everything from the subpackage so any import like:
#   from app.services.raf_calculator import calculate_raf_score
# continues to resolve correctly.

from app.services.raf.icd_formatter import (  # noqa: F401
    _format_icd10,
    _ESRD_DIALYSIS_CODES,
    _ESRD_FUNCTIONING_GRAFT_CODES,
)

from app.services.raf.blend_weights import (  # noqa: F401
    _BLEND_WEIGHTS,
    _PACE_BLEND_WEIGHTS,
    _NORM_FACTORS_V28,
    _NORM_FACTORS_V24,
    _NORM_FACTORS_V22,
    _NORM_FACTORS,
    _MACI_FACTORS_V28,
    _MACI_FACTORS_V24,
    _MACI_FACTORS,
    _get_norm_factor,
    _get_maci_factor,
)

from app.services.raf.enrollment_resolver import (  # noqa: F401
    _SEGMENT_TO_PREFIX,
    determine_model_segment,
    _is_new_enrollee,
    _is_esrd,
    _get_enrollment_from_raf_db,
    _resolve_enrollment,
)

from app.services.raf.score_persistence import (  # noqa: F401
    _get_age_band_from_age,
    _store_patient_hccs,
    _upsert_raf_score,
    _upsert_patient_demographics,
)

from app.services.raf.calculator import (  # noqa: F401
    # processor singletons
    _processor,
    _processor_v24,
    _processor_v28,
    _processor_v22,
    _processor_esrd_v24,
    # demographic score tables
    _NE_DEMO_SCORES,
    _NE_CMS_COEFFICIENTS,
    _SEGMENT_TO_NE_CMS,
    _ne_age_key,
    _ESRD_DLY_DEMO_SCORES,
    _ESRD_FG_DEMO_SCORES,
    # helpers
    _calculate_age,
    _calc_age,
    _sex_code,
    _get_patient,
    _get_icd_codes,
    # hierarchy
    _HIERARCHY_MODEL_YEAR,
    _load_hierarchy_rules,
    _apply_hcc_hierarchy,
    # single-model runner
    _run_single_model,
    # NE / ESRD score helpers
    _calculate_new_enrollee_score,
    _calculate_esrd_demographic_score,
    # HCC label/coef helpers
    _get_hcc_label_v28,
    _get_hcc_coefficient_v28,
    _enrich_hcc_details,
    # public API
    calculate_raf_score,
    calculate_raf_score_multi_model,
    calculate_raf_for_all_patients,
    get_raf_breakdown,
    get_age_band,
)
