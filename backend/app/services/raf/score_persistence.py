# DISCLAIMER: This module is part of the CMS-HCC RAF calculation engine.
# Not CMS-validated. For informational purposes only.
"""
Score persistence helpers.

Handles upserts to:
  - raf_scores          (_upsert_raf_score)
  - raf_patient_hcc     (_store_patient_hccs)
  - raf_patient_demographics (_upsert_patient_demographics)
"""

from __future__ import annotations

import json
import logging
from typing import Any

from hccinfhir.defaults import is_chronic_default

from app.db import raf_cursor
from app.services.raf.provenance import provenance_stamp

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Age-band helper (needed here for _upsert_patient_demographics)
# ---------------------------------------------------------------------------


def _get_age_band_from_age(age: int) -> str:
    """Return CMS age-band label for a given integer age."""
    if age < 35:
        return "0-34"
    if age < 45:
        return "35-44"
    if age < 55:
        return "45-54"
    if age < 60:
        return "55-59"
    if age < 65:
        return "60-64"
    if age < 70:
        return "65-69"
    if age < 75:
        return "70-74"
    if age < 80:
        return "75-79"
    if age < 85:
        return "80-84"
    if age < 90:
        return "85-89"
    if age < 95:
        return "90-94"
    return "95+"


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------


def _store_patient_hccs(
    patient_id: int,
    year: int,
    hcc_list: list,
    icd_codes: list[str],
    result: Any,
    score_type: str = "blended",
    tenant_id: str = "",  # Required — empty string will raise below
    model_version: str = "V28",
) -> None:
    """Store active HCCs in raf_patient_hcc table.

    Uses hccinfhir's hcc_details for the per-HCC coefficient and cc_to_dx for
    the exact ICD codes that triggered each HCC.  cc_to_dx values are sets of
    strings (e.g. {'I509', 'E119'}); convert to sorted lists before JSON-encoding.

    score_type controls which model's HCC list is stored: 'v24', 'v28', or 'blended'.
    For 'blended' we store the V28 HCC list (primary model for display purposes).
    """
    if not tenant_id:
        raise ValueError(
            "_store_patient_hccs: tenant_id is required — "
            "refusing to persist HCC data without tenant scope (HIPAA multi-tenant isolation)"
        )
    try:
        hcc_detail_map = {str(h.hcc): h for h in (result.hcc_details or [])}
        cc_to_dx: dict = result.cc_to_dx or {}

        with raf_cursor() as cur:
            # Prune only HCCs that are no longer present in the new hcc_list.
            # Preserving row IDs for still-valid HCCs is critical: raf_meat_evidence
            # has FK patient_hcc_id → raf_patient_hcc(id) ON DELETE CASCADE, so a
            # wholesale DELETE+INSERT would wipe all MEAT evidence on every recompute.
            # The UNIQUE KEY uq_patient_hcc_year (patient_id, hcc_code, measurement_year)
            # combined with ON DUPLICATE KEY UPDATE below handles the upsert for
            # still-valid HCCs without touching their row IDs.
            if hcc_list:
                new_hcc_ints = [
                    int(str(h)) for h in hcc_list if str(h).isdigit()
                ]
                if new_hcc_ints:
                    placeholders = ",".join(["%s"] * len(new_hcc_ints))
                    cur.execute(
                        f"DELETE FROM raf_patient_hcc "
                        f"WHERE patient_id = %s AND measurement_year = %s AND tenant_id = %s "
                        f"AND hcc_code NOT IN ({placeholders})",
                        (patient_id, year, tenant_id, *new_hcc_ints),
                    )
            for hcc in hcc_list:
                hcc_str = str(hcc)
                hcc_int = int(hcc_str) if hcc_str.isdigit() else 0

                raw_icd = cc_to_dx.get(hcc_str, set())
                related_icd: list[str] = (
                    sorted(raw_icd) if isinstance(raw_icd, set) else list(raw_icd)
                )

                coefficient = (
                    hcc_detail_map[hcc_str].coefficient
                    if hcc_str in hcc_detail_map
                    else 0.0
                )

                is_chronic = (
                    1
                    if is_chronic_default.get((hcc_str, "CMS-HCC Model V28"), True)
                    else 0
                )

                cur.execute(
                    """
                    INSERT INTO raf_patient_hcc
                        (patient_id, measurement_year, hcc_code, icd10_codes,
                         source_encounter_ids, raf_coefficient, meat_status, tenant_id,
                         is_chronic, model_version)
                    VALUES (%s, %s, %s, %s, '[]', %s, 'missing', %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        icd10_codes     = VALUES(icd10_codes),
                        raf_coefficient = VALUES(raf_coefficient),
                        tenant_id       = VALUES(tenant_id),
                        is_chronic      = VALUES(is_chronic),
                        model_version   = VALUES(model_version)
                    """,
                    (
                        patient_id,
                        year,
                        hcc_int,
                        json.dumps(related_icd),
                        coefficient,
                        tenant_id,
                        is_chronic,
                        model_version,
                    ),
                )
    except Exception as exc:
        logger.warning(
            "Failed to store HCCs for pid=%s tenant=%s: %s", patient_id, tenant_id, exc
        )


def _upsert_raf_score(
    result: dict[str, Any],
    score_type: str = "blended",
    tenant_id: str = "",  # Required — empty string will raise below
) -> None:
    """Persist RAF score to raf_scores table.

    score_type: 'v24' | 'v28' | 'blended' — stored in the score_type column to
    differentiate which model produced the score.

    Per-model blend fields stored (NULL when a model was not run):
      v24_score         — raw CMS-HCC V24 risk score
      v28_score         — raw CMS-HCC V28 risk score
      blended_raw_score — weighted blend of v24/v28 raw scores
      blend_v24_weight  — V24 weight applied (e.g. 0.33 for PY2025)
      blend_v28_weight  — V28 weight applied (e.g. 0.67 for PY2025)
      v24_hcc_count     — HCC count from V24 model
      v28_hcc_count     — HCC count from V28 model

    These columns are added by migration 003_raf_scores_blend_columns.  The
    INSERT gracefully omits them when the column list is not yet present (the
    ON DUPLICATE KEY UPDATE block also skips them).  Once the migration runs,
    the columns will be populated on all subsequent RAF calculations.
    """
    if not tenant_id:
        raise ValueError(
            "_upsert_raf_score: tenant_id is required — "
            "refusing to persist RAF score without tenant scope (HIPAA multi-tenant isolation)"
        )

    # Extract blend metadata from the result dict (present after calculate_raf_score).
    blend_weights: dict = result.get("blend_weights") or {}
    v24_w: float | None = blend_weights.get("v24")
    v28_w: float | None = blend_weights.get("v28")
    v24_score: float | None = result.get("v24_score")  # None when V24 not run
    v28_score: float | None = result.get("v28_score")  # None when V28 not run
    blended_raw: float | None = result.get("blended_raw_score")

    # HCC counts per model — derive from the per-model HCC lists when available.
    v24_hcc_list = result.get("v24_hcc_list")
    v28_hcc_list = result.get("v28_hcc_list")
    v24_hcc_count: int | None = len(v24_hcc_list) if v24_hcc_list is not None else None
    v28_hcc_count: int | None = len(v28_hcc_list) if v28_hcc_list is not None else None

    # Provenance stamp — model_version derives from score_type; "blended" rows
    # are labelled BLEND so that auditors can distinguish a blended row from a
    # pure single-model row at a glance.
    model_version_label = {"v24": "V24", "v28": "V28", "blended": "BLEND"}.get(
        score_type, score_type.upper()
    )
    stamp = provenance_stamp(model_version_label)

    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                INSERT INTO raf_scores (
                    patient_id, measurement_year, score_type, model_segment,
                    demographic_score, disease_score, interaction_score,
                    total_raw, normalization_factor, final_raf,
                    hcc_count, calculated_at, tenant_id,
                    v24_score, v28_score, blended_raw_score,
                    blend_v24_weight, blend_v28_weight,
                    v24_hcc_count, v28_hcc_count,
                    model_version, coefficient_source,
                    coefficient_manifest_hash, calculator_commit_sha
                ) VALUES (
                    %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, NOW(), %s,
                    %s, %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s
                )
                ON DUPLICATE KEY UPDATE
                    demographic_score        = VALUES(demographic_score),
                    disease_score            = VALUES(disease_score),
                    interaction_score        = VALUES(interaction_score),
                    total_raw                = VALUES(total_raw),
                    normalization_factor     = VALUES(normalization_factor),
                    final_raf                = VALUES(final_raf),
                    hcc_count                = VALUES(hcc_count),
                    tenant_id                = VALUES(tenant_id),
                    v24_score                = VALUES(v24_score),
                    v28_score                = VALUES(v28_score),
                    blended_raw_score        = VALUES(blended_raw_score),
                    blend_v24_weight         = VALUES(blend_v24_weight),
                    blend_v28_weight         = VALUES(blend_v28_weight),
                    v24_hcc_count            = VALUES(v24_hcc_count),
                    v28_hcc_count            = VALUES(v28_hcc_count),
                    model_version            = VALUES(model_version),
                    coefficient_source       = VALUES(coefficient_source),
                    coefficient_manifest_hash = VALUES(coefficient_manifest_hash),
                    calculator_commit_sha    = VALUES(calculator_commit_sha),
                    calculated_at            = NOW()
                """,
                (
                    result["patient_id"],
                    result["measurement_year"],
                    score_type,
                    result["model_segment"],
                    result["demographic_score"],
                    result["disease_score"],
                    result["interaction_score"],
                    result["subtotal"],
                    result["normalization_factor"],
                    result["payment_raf"],
                    len(result["final_hcc_list"]),
                    tenant_id,
                    v24_score,
                    v28_score,
                    blended_raw,
                    v24_w,
                    v28_w,
                    v24_hcc_count,
                    v28_hcc_count,
                    stamp["model_version"],
                    stamp["coefficient_source"],
                    stamp["coefficient_manifest_hash"],
                    stamp["calculator_commit_sha"],
                ),
            )

            # Sync the authoritative RAF columns back to the patients table so
            # that list/search queries always reflect the latest calculated score
            # without requiring a JOIN to raf_scores.
            #
            # NOTE: when `patients` is a VIEW (OpenEMR-bridged deployments) this
            # UPDATE will fail because the VIEW doesn't expose those columns.
            # Wrap it independently so a failure here doesn't roll back the
            # raf_scores INSERT above.
            patient_id: int = result["patient_id"]
            final_raf: float = result["payment_raf"]
            demographic_score: float = result["demographic_score"]
            try:
                cur.execute(
                    """
                    UPDATE patients SET
                        raf_score        = %s,
                        hcc_count        = (
                            SELECT COUNT(*)
                            FROM raf_patient_hcc
                            WHERE patient_id = %s
                              AND measurement_year = %s
                              AND tenant_id = %s
                              AND is_trumped = 0
                        ),
                        demographic_score = %s,
                        updated_at        = NOW()
                    WHERE id = %s AND tenant_id = %s
                    """,
                    (
                        final_raf,
                        patient_id,
                        result["measurement_year"],
                        tenant_id,
                        demographic_score,
                        patient_id,
                        tenant_id,
                    ),
                )
            except Exception as denorm_exc:
                logger.warning(
                    "Skipped patients-table denormalization for pid=%s "
                    "(read-only VIEW or missing column): %s",
                    patient_id,
                    denorm_exc,
                )
    except Exception as exc:
        logger.error(
            "Failed to persist raf_scores for pid=%s tenant=%s: %s",
            result["patient_id"],
            tenant_id,
            exc,
        )


def _upsert_patient_demographics(
    patient_id: int,
    measurement_year: int,
    age: int,
    sex: str,
    model_segment: str,
    dual_type: str,
    orec: str,
    institutional: bool,
    enrollment_source: str,
    tenant_id: str = "",  # Required — empty string will raise below
) -> None:
    """Persist (or refresh) enrollment and demographic info in raf_patient_demographics."""
    if not tenant_id:
        raise ValueError(
            "_upsert_patient_demographics: tenant_id is required — "
            "refusing to persist demographics without tenant scope (HIPAA multi-tenant isolation)"
        )
    age_band = _get_age_band_from_age(age)

    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                INSERT INTO raf_patient_demographics
                    (patient_id, measurement_year, age_band, sex,
                     dual_status, dual_type, disabled, orec,
                     institutional, enrollment_source, model_segment, tenant_id)
                VALUES
                    (%s, %s, %s, %s,
                     %s, %s, %s, %s,
                     %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    age_band          = VALUES(age_band),
                    sex               = VALUES(sex),
                    dual_status       = VALUES(dual_status),
                    dual_type         = VALUES(dual_type),
                    disabled          = VALUES(disabled),
                    orec              = VALUES(orec),
                    institutional     = VALUES(institutional),
                    enrollment_source = VALUES(enrollment_source),
                    model_segment     = VALUES(model_segment),
                    tenant_id         = VALUES(tenant_id),
                    updated_at        = NOW()
                """,
                (
                    patient_id,
                    measurement_year,
                    age_band,
                    sex,
                    1 if dual_type != "non_dual" else 0,
                    dual_type,
                    1 if orec == "1" else 0,
                    orec,
                    1 if institutional else 0,
                    enrollment_source,
                    model_segment,
                    tenant_id,
                ),
            )
    except Exception as exc:
        logger.warning(
            "_upsert_patient_demographics pid=%s year=%s tenant=%s: %s",
            patient_id,
            measurement_year,
            tenant_id,
            exc,
        )
