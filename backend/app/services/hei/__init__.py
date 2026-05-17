"""CMS Health Equity Index (HEI) population segmentation package.

The HEI applies a reward factor to a Medicare Advantage contract's Star
Rating based on performance among enrollees with social risk factors
(dual-eligible, LIS, disability).  Starting with Plan Year 2027, HEI
replaces the legacy Reward Factor in the CMS Star Ratings formula.

We expose:
    - classify_patient_segment(pid, tenant_id) -> "dual"|"lis"|"disability"|"other"
    - SEGMENTS — canonical list of segment ids
"""
from app.services.hei.dual_eligible import (
    SEGMENTS,
    classify_patient_segment,
    classify_patients_bulk,
)

__all__ = ["SEGMENTS", "classify_patient_segment", "classify_patients_bulk"]
