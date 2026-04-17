"""Part D (RxHCC) risk-adjustment scoring.

Medicare Part D bids use a separate risk-adjustment model family
(RxHCC) with its own coefficient tables, segmentation, and
hierarchies. CY2026 uses **RxHCC Model V08**; prior years used V05.

This module provides a thin wrapper over ``hccinfhir`` that:

- Computes a Part D RAF score from diagnoses + demographics.
- Returns a structured dict with demographic, HCC, and total scores
  so consumers can audit each contribution.
- Attaches the per-score SBOM for provenance.

Scope
-----
Only the base RxHCC score is computed — CMS also applies a
**normalization factor**, **coding-intensity adjustment**, and
**low-income premium subsidy (LIPS)** adjustment at the payment
layer. Those are outside this module's scope and should be layered
on top by the Part D payment service.
"""

from __future__ import annotations

import logging
from typing import Any

from app.services.raf.provenance import build_score_sbom

logger = logging.getLogger(__name__)

# Payment-year → RxHCC model name mapping.
# Source: CMS MA/Part D Final Rate Announcements.
#
# Note: V05 coefficients are locked by our snapshot harness for audit
# purposes but end-to-end *scoring* via hccinfhir is only wired for V08
# (see RAFResult.model_name literal). Prior-year reprocessing must use
# the V08 path with the relevant payment-year normalization factor.
_RX_MODEL_BY_YEAR: dict[int, str] = {
    2024: "RxHCC Model V08",
    2025: "RxHCC Model V08",
    2026: "RxHCC Model V08",
}


def _resolve_rx_model(payment_year: int) -> str:
    return _RX_MODEL_BY_YEAR.get(payment_year, _RX_MODEL_BY_YEAR[2026])


def calculate_partd_raf(
    *,
    diagnosis_codes: list[str],
    age: int,
    sex: str,
    dual_elgbl_cd: str = "NA",
    orec: str = "0",
    new_enrollee: bool = False,
    payment_year: int = 2026,
) -> dict[str, Any]:
    """Calculate a Part D (RxHCC) risk score.

    Parameters
    ----------
    diagnosis_codes : list[str]
        Dotless ICD-10-CM codes for the beneficiary's reporting window.
    age, sex, dual_elgbl_cd, orec, new_enrollee
        Standard CMS demographic attributes.
    payment_year : int
        Payment year for model-version lookup.

    Returns
    -------
    dict with:
        - model_name          (str) which RxHCC model ran
        - risk_score          (float) total Part D RAF
        - demographic_score   (float) Demographic-only contribution
        - hcc_score           (float) HCC-derived contribution
        - hcc_list            (list[str]) triggered RxHCC categories
        - payment_year        (int)
        - provenance_sbom     (dict) machine-readable bill of materials
    """
    from hccinfhir import Demographics, HCCInFHIR

    model_name = _resolve_rx_model(payment_year)

    demo = Demographics(
        age=age, sex=sex,
        dual_elgbl_cd=dual_elgbl_cd,
        orec=orec, new_enrollee=new_enrollee,
    )
    processor = HCCInFHIR(model_name=model_name)
    result = processor.calculate_from_diagnosis(
        diagnosis_codes=diagnosis_codes, demographics=demo,
    )

    total = round(float(result.risk_score), 4)
    demographic = round(float(result.risk_score_demographics), 4)
    hcc = round(float(result.risk_score_hcc), 4)
    hcc_list = list(getattr(result, "hcc_list", []) or [])

    sbom = build_score_sbom(
        models_used=[model_name],
        payment_year=payment_year,
        plan_type="PART_D",
        frailty_applied=False,
    )

    logger.info(
        "Part D RAF: model=%s year=%d age=%d sex=%s total=%s hcc_count=%d",
        model_name, payment_year, age, sex, total, len(hcc_list),
    )

    return {
        "model_name": model_name,
        "payment_year": payment_year,
        "risk_score": total,
        "demographic_score": demographic,
        "hcc_score": hcc,
        "hcc_list": hcc_list,
        "is_new_enrollee": new_enrollee,
        "provenance_sbom": sbom,
    }


__all__ = ["calculate_partd_raf"]
