"""
fix_hcc_descriptions.py

One-time backfill script: populates hcc_description and icd10_code for rows
in raf_patient_hcc where those columns are NULL, using the CMS HCC V28 model
mapping.

Usage (from the backend/ directory):
    python fix_hcc_descriptions.py [--dry-run]
"""

from __future__ import annotations

import argparse
import logging
import sys

# ---------------------------------------------------------------------------
# CMS HCC V28 lookup: hcc_code (int) -> (description, representative_icd10)
#
# The representative ICD-10 code is the most clinically common code that maps
# to the HCC; it is used only when icd10_code is also NULL.  If icd10_code is
# already populated, only the description is updated.
# ---------------------------------------------------------------------------
HCC_V28_MAP: dict[int, tuple[str, str]] = {
    # Diabetes
    17: ("Diabetes with Acute Complications", "E11.00"),
    18: ("Diabetes with Chronic Complications", "E11.40"),
    19: ("Diabetes without Complications", "E11.9"),
    # Vascular / Cardiac
    85: ("Congestive Heart Failure", "I50.20"),
    86: ("Acute Myocardial Infarction", "I21.9"),
    87: ("Unstable Angina and Other Acute Ischemic Heart Disease", "I20.0"),
    88: ("Angina Pectoris", "I20.9"),
    96: ("Specified Heart Arrhythmias", "I48.91"),
    110: ("Cystic Fibrosis", "J44.1"),
    111: ("Chronic Obstructive Pulmonary Disease", "J44.1"),
    112: ("Fibrosis of Lung and Other Chronic Lung Disorders", "J84.10"),
    # Renal
    137: ("Chronic Kidney Disease, Stage 5", "N18.5"),
    138: ("Chronic Kidney Disease, Severe (Stage 4)", "N18.4"),
    # Neurological
    154: ("Cerebral Hemorrhage", "I61.9"),
    155: ("Ischemic or Unspecified Stroke", "I63.9"),
    167: ("Major Depressive, Bipolar, and Paranoid Disorders", "F31.9"),
    # Cancer
    8: ("Metastatic Cancer and Acute Leukemia", "C80.1"),
    9: ("Lung and Other Severe Cancers", "C34.90"),
    10: ("Lymphoma and Other Cancers", "C85.90"),
    11: ("Colorectal, Bladder, and Other Cancers", "C18.9"),
    12: ("Breast, Prostate, and Other Cancers and Tumors", "C50.919"),
    # Musculoskeletal
    39: ("Bone/Joint/Muscle Infections/Necrosis", "M86.9"),
    40: ("Rheumatoid Arthritis and Specified Autoimmune Disorders", "M06.9"),
    # Other common HCCs
    21: ("Protein-Calorie Malnutrition", "E43"),
    22: ("Morbid Obesity", "E66.01"),
    23: ("Other Significant Endocrine and Metabolic Disorders", "E27.40"),
    35: ("Pancreatic Disease", "K86.1"),
    46: ("Severe Hematological Disorders", "D61.9"),
    47: ("Disorders of Immunity", "D84.9"),
    48: ("Coagulation Defects and Other Specified Hematological Disorders", "D68.9"),
    54: ("Dementia with Complications", "F02.81"),
    55: ("Dementia without Complications", "F03.90"),
    67: ("Quadriplegia", "G82.50"),
    68: ("Paraplegia", "G82.20"),
    69: ("Spinal Cord Disorders/Injuries", "G95.89"),
    70: ("Muscular Dystrophy", "G71.00"),
    71: ("Polyneuropathy", "G62.9"),
    72: ("Multiple Sclerosis", "G35"),
    73: ("Parkinson's and Huntington's Diseases", "G20"),
    74: ("Seizure Disorders and Convulsions", "G40.909"),
    75: ("Coma, Brain Compression/Anoxic Damage", "G93.1"),
    82: ("Respirator Dependence/Tracheostomy Status", "Z99.11"),
    83: ("Respiratory Arrest", "J96.90"),
    84: ("Cardio-Respiratory Failure and Shock", "J96.00"),
    # V28-specific codes raised in this ticket
    224: ("Specified Heart Arrhythmias", "I48.91"),
    238: ("Chronic Kidney Disease, Stage 4", "N18.4"),
    327: ("Congestive Heart Failure", "I50.20"),
}


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)


def run(dry_run: bool = False) -> None:
    # Import here so the script can be run from within the backend/ package
    # context where app/ is on the path.
    from app.db import raf_cursor  # noqa: PLC0415

    with raf_cursor() as cursor:
        cursor.execute(
            """
            SELECT id, patient_id, hcc_code, hcc_description, icd10_code
            FROM   raf_patient_hcc
            WHERE  hcc_description IS NULL
               OR  icd10_code IS NULL
            ORDER  BY hcc_code, patient_id
            """
        )
        rows = cursor.fetchall()

    if not rows:
        log.info("No rows with missing hcc_description or icd10_code found. Nothing to do.")
        return

    log.info("Found %d row(s) with missing data.", len(rows))

    updated = 0
    skipped = 0

    with raf_cursor() as cursor:
        for row in rows:
            row_id: int = row["id"]
            patient_id: int = row["patient_id"]
            hcc_code: int = int(row["hcc_code"])
            existing_desc: str | None = row["hcc_description"]
            existing_icd: str | None = row["icd10_code"]

            mapping = HCC_V28_MAP.get(hcc_code)
            if mapping is None:
                log.warning(
                    "HCC %d (patient_id=%d, row_id=%d): no mapping found — skipping.",
                    hcc_code,
                    patient_id,
                    row_id,
                )
                skipped += 1
                continue

            new_desc, new_icd = mapping

            # Only overwrite NULL columns; preserve any existing non-NULL value.
            desc_to_write = new_desc if existing_desc is None else existing_desc
            icd_to_write = new_icd if existing_icd is None else existing_icd

            log.info(
                "HCC %d (patient_id=%d, row_id=%d): desc=%r -> %r, icd10=%r -> %r%s",
                hcc_code,
                patient_id,
                row_id,
                existing_desc,
                desc_to_write,
                existing_icd,
                icd_to_write,
                "  [DRY RUN]" if dry_run else "",
            )

            if not dry_run:
                cursor.execute(
                    """
                    UPDATE raf_patient_hcc
                    SET    hcc_description = %s,
                           icd10_code      = %s
                    WHERE  id              = %s
                    """,
                    (desc_to_write, icd_to_write, row_id),
                )
            updated += 1

    log.info(
        "Done. %d row(s) %s, %d row(s) skipped (no mapping).",
        updated,
        "would be updated (dry run)" if dry_run else "updated",
        skipped,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill hcc_description / icd10_code in raf_patient_hcc.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be changed without writing to the database.",
    )
    args = parser.parse_args()
    run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
