"""
HCC Agent — Maps ICD-10 codes to HCC codes using CMS V28 crosswalk database.
No LLM calls — pure database lookup, instant and free.
"""
import logging
from typing import Any
from app.db import raf_cursor

logger = logging.getLogger(__name__)


def map_icd_to_hcc(diagnoses: list[dict]) -> list[dict]:
    """
    Enrich diagnoses with HCC codes and RAF weights from CMS crosswalk.

    For each diagnosis with an ICD-10 code, looks up:
    - HCC code from hcc_icd10_crosswalk
    - RAF coefficient from hcc_raf_coefficients

    Returns the same list with added 'hcc', 'hcc_label', 'hcc_weight' keys.
    """
    if not diagnoses:
        return diagnoses

    enriched = []
    for dx in diagnoses:
        icd10 = (dx.get("icd10") or "").strip()
        hcc = ""
        hcc_label = ""
        hcc_weight = None

        if icd10:
            # Try exact match, then without dot
            variants = [icd10, icd10.replace(".", ""), icd10.upper()]
            try:
                with raf_cursor() as cur:
                    for variant in variants:
                        cur.execute("""
                            SELECT c.hcc_code, c.hcc_label, r.coefficient
                            FROM hcc_icd10_crosswalk c
                            LEFT JOIN hcc_raf_coefficients r ON r.hcc_code = c.hcc_code
                            WHERE c.icd10_code = %s
                            LIMIT 1
                        """, (variant,))
                        row = cur.fetchone()
                        if row:
                            hcc = f"HCC{row['hcc_code']}"
                            hcc_label = row.get("hcc_label", "")
                            hcc_weight = float(row["coefficient"]) if row.get("coefficient") else None
                            break
            except Exception as exc:
                logger.warning("[HCC Agent] Lookup failed for %s: %s", icd10, exc)

        enriched.append({
            **dx,
            "hcc": hcc,
            "hcc_label": hcc_label,
            "hcc_weight": hcc_weight,
        })

    mapped = sum(1 for d in enriched if d.get("hcc"))
    logger.info("[HCC Agent] Mapped %d/%d diagnoses to HCC codes", mapped, len(enriched))
    return enriched
