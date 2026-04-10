#!/usr/bin/env python3
"""
import_full_crosswalk.py
------------------------
Generates the FULL CMS-HCC V28 ICD-10-CM crosswalk using hccinfhir and
simple_icd_10_cm libraries, and inserts into hcc_icd10_crosswalk table.

Usage (inside Docker):
    python3 /tmp/import_full_crosswalk.py
"""

import sys
import logging
import mysql.connector

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

DB_CONFIG = dict(
    host="mysql",
    port=3306,
    user="root",
    password="root",
    database="raf_intelligence",
    charset="utf8mb4",
    collation="utf8mb4_unicode_ci",
    autocommit=False,
    connect_timeout=10,
)

# HCC code -> condition_group mapping (broad clinical categories)
HCC_CONDITION_GROUP = {
    1: "HIV",
    2: "Septicemia/Shock",
    6: "Opportunistic Infections",
    8: "Cancer", 9: "Cancer", 10: "Cancer", 11: "Cancer", 12: "Cancer",
    17: "Diabetes", 18: "Diabetes", 19: "Diabetes",
    21: "Malnutrition",
    22: "Obesity",
    23: "Disorders of Fluid/Electrolyte/Acid-Base",
    29: "Hepatitis",
    33: "Liver Disease", 34: "Liver Disease", 35: "Liver Disease",
    37: "GI Disorders", 38: "GI Disorders",
    48: "Musculoskeletal",
    49: "Bone/Joint",
    51: "Spinal Disorders",
    52: "Spinal Disorders",
    62: "Amputation",
    63: "Amputation",
    64: "Amputation",
    66: "Vascular Disease", 67: "Vascular Disease", 68: "Vascular Disease",
    77: "Skin Ulcer", 78: "Skin Ulcer", 79: "Skin Ulcer", 80: "Skin Ulcer",
    86: "Mental Health", 87: "Mental Health", 88: "Mental Health",
    92: "Infections",
    93: "Infections",
    94: "Substance Use",
    96: "Heart Disease", 97: "Heart Disease", 98: "Heart Disease", 99: "Heart Disease",
    100: "Heart Disease", 101: "Heart Disease", 102: "Heart Disease", 103: "Heart Disease",
    107: "Blood Disorders", 108: "Blood Disorders", 109: "Blood Disorders",
    111: "Blood Disorders", 112: "Blood Disorders",
    114: "Immunodeficiency", 115: "Immunodeficiency",
    125: "Dementia", 126: "Dementia", 127: "Dementia",
    128: "Neurological", 129: "Neurological", 130: "Neurological",
    131: "Neurological", 132: "Neurological", 133: "Neurological",
    134: "Neurological", 135: "Neurological", 136: "Neurological",
    137: "Neurological",
    138: "Neurological",
    145: "Eye Disorders", 146: "Eye Disorders",
    149: "Developmental Disability",
    150: "Developmental Disability",
    151: "Developmental Disability",
    154: "Organ Transplant", 155: "Organ Transplant", 156: "Organ Transplant",
    157: "Organ Transplant",
    158: "Respiratory", 159: "Respiratory", 160: "Respiratory", 161: "Respiratory",
    162: "Respiratory",
    180: "Respiratory",
    190: "Stroke", 191: "Stroke", 192: "Stroke",
    193: "Stroke",
    195: "Vascular Disease", 196: "Vascular Disease", 197: "Vascular Disease",
    198: "Vascular Disease",
    199: "Vascular Disease",
    200: "Renal Disease", 201: "Renal Disease", 202: "Renal Disease",
    203: "Renal Disease", 204: "Renal Disease", 205: "Renal Disease",
    207: "Renal Disease", 208: "Renal Disease", 209: "Renal Disease",
    211: "Pulmonary", 212: "Pulmonary", 213: "Pulmonary",
    215: "Heart Disease", 216: "Heart Disease", 217: "Heart Disease",
    218: "Heart Disease", 219: "Heart Disease", 220: "Heart Disease",
    221: "Heart Disease", 222: "Heart Disease", 223: "Heart Disease",
    226: "Heart Disease", 227: "Heart Disease", 228: "Heart Disease",
    234: "Eye Disorders", 235: "Eye Disorders", 236: "Eye Disorders",
    237: "Eye Disorders",
    238: "Eye Disorders",
    248: "Trauma", 249: "Trauma", 253: "Trauma", 254: "Trauma",
    263: "Complications",
    267: "GI Disorders",
    268: "Skin Disorders",
    301: "Pediatric",
    302: "Pediatric",
    303: "Pediatric",
}


def format_icd10(code: str) -> str:
    """Insert dot after 3rd character if needed: E1165 -> E11.65"""
    code = code.strip().upper()
    if "." not in code and len(code) > 3:
        return code[:3] + "." + code[3:]
    return code


def main():
    import simple_icd_10_cm as icd
    from hccinfhir.defaults import dx_to_cc_default, labels_default

    # Build V28 HCC labels lookup: hcc_number_str -> label
    hcc_labels = {}
    for (cc, model), label in labels_default.items():
        if model == "CMS-HCC Model V28":
            hcc_labels[cc] = label

    # Build V28 ICD-10 -> HCC mappings
    v28_mappings = {}
    for (dx_code, model), hcc_set in dx_to_cc_default.items():
        if model == "CMS-HCC Model V28":
            for hcc in hcc_set:
                v28_mappings.setdefault(dx_code, set()).add(hcc)

    log.info("V28 mappings: %d ICD-10 codes -> HCCs", len(v28_mappings))

    # Build insert rows
    rows = []
    missing_desc = 0
    for dx_code, hcc_set in sorted(v28_mappings.items()):
        formatted = format_icd10(dx_code)
        # Try to get description
        try:
            desc = icd.get_description(dx_code)
            if not desc or desc == dx_code:
                desc = ""
        except Exception:
            desc = ""
            missing_desc += 1

        for hcc_str in sorted(hcc_set):
            hcc_num = int(hcc_str)
            label = hcc_labels.get(hcc_str, f"HCC {hcc_str}")
            group = HCC_CONDITION_GROUP.get(hcc_num, "Other")
            rows.append((formatted, desc, hcc_num, label, group, 2024))

    log.info("Total rows to insert: %d (missing descriptions: %d)", len(rows), missing_desc)

    # Connect and insert
    conn = mysql.connector.connect(**DB_CONFIG)
    cur = conn.cursor()

    # Clear existing data
    cur.execute("DELETE FROM hcc_icd10_crosswalk")
    deleted = cur.rowcount
    log.info("Deleted %d existing rows", deleted)

    INSERT_SQL = """
        INSERT INTO hcc_icd10_crosswalk
            (icd10_code, icd10_description, hcc_code, hcc_label, condition_group, effective_year)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            icd10_description = VALUES(icd10_description),
            hcc_label = VALUES(hcc_label),
            condition_group = VALUES(condition_group)
    """

    BATCH = 500
    for i in range(0, len(rows), BATCH):
        batch = rows[i : i + BATCH]
        cur.executemany(INSERT_SQL, batch)
        if (i // BATCH) % 5 == 0:
            log.info("  Inserted %d / %d ...", min(i + BATCH, len(rows)), len(rows))

    conn.commit()

    # Verify
    cur.execute("SELECT COUNT(*) FROM hcc_icd10_crosswalk")
    total = cur.fetchone()[0]
    log.info("Done. Total rows in hcc_icd10_crosswalk: %d", total)

    cur.close()
    conn.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log.exception("Fatal error: %s", exc)
        sys.exit(1)
