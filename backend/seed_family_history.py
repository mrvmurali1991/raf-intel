"""Seed realistic family history data into OpenEMR's history_data table.

Targets demo patients with pid in 28-42. For each pid that exists in
patient_data but does not yet have a history_data row, a row is inserted
with plausible family history appropriate to a chronic-disease RAF population.

OpenEMR family history schema in history_data:
  Per-relative narrative fields:
    history_mother, history_father, history_siblings, history_offspring,
    history_spouse  — free-text narrative for each relation
  Per-condition boolean-style fields (values are "mother", "father",
  "siblings", etc. — a comma-separated list of affected relatives):
    relatives_cancer, relatives_tuberculosis, relatives_diabetes,
    relatives_high_blood_pressure, relatives_heart_problems,
    relatives_stroke, relatives_epilepsy, relatives_mental_illness,
    relatives_suicide

Usage (run from the backend/ directory with .env in scope):
    python seed_family_history.py

The script is idempotent: patients that already have a history_data row are
skipped with a log message.
"""

from __future__ import annotations

import logging
import os
import sys

# ---------------------------------------------------------------------------
# Bootstrap path so app.db resolves when run as a standalone script from
# anywhere under the backend/ tree.
# ---------------------------------------------------------------------------
_backend_dir = os.path.dirname(os.path.abspath(__file__))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

# Load .env before importing app modules so settings are populated.
try:
    from dotenv import load_dotenv  # type: ignore[import]

    _env_path = os.path.join(_backend_dir, ".env")
    if os.path.exists(_env_path):
        load_dotenv(_env_path, override=False)
except ImportError:
    pass  # python-dotenv not installed; rely on environment already being set.

from app.db import openemr_cursor  # noqa: E402 — must come after path/env setup

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# PID range to target
# ---------------------------------------------------------------------------
TARGET_PIDS: list[int] = list(range(28, 43))  # 28 through 42 inclusive

# ---------------------------------------------------------------------------
# Family history profiles — one profile per patient.
#
# Each profile maps to the exact column names in history_data:
#   history_<relation>  — narrative text shown in the chart
#   relatives_<condition> — comma-separated list of affected relatives
#     (OpenEMR stores values like "mother", "father", "siblings")
#
# Profiles are assigned round-robin so the full set is covered even if fewer
# than 15 patients exist in the pid range.
# ---------------------------------------------------------------------------

PROFILES: list[dict] = [
    # Profile A — heavy cardiovascular & diabetes burden (typical RAF patient)
    {
        "history_mother": "Hypertension diagnosed at age 55. Type 2 diabetes for 20 years. "
                          "Died of congestive heart failure at age 78.",
        "history_father": "Coronary artery disease, CABG at age 62. Hyperlipidemia. "
                          "Stroke at age 70, residual left-sided weakness. Died at 75.",
        "history_siblings": "One brother with type 2 diabetes and hypertension. "
                            "One sister with breast cancer diagnosed at age 52, in remission.",
        "history_offspring": "No known chronic illness in children.",
        "history_spouse": "Spouse with hyperlipidemia.",
        "relatives_cancer": "siblings",
        "relatives_diabetes": "mother,siblings",
        "relatives_high_blood_pressure": "mother,father,siblings",
        "relatives_heart_problems": "father",
        "relatives_stroke": "father",
        "relatives_epilepsy": "",
        "relatives_mental_illness": "",
        "relatives_tuberculosis": "",
        "relatives_suicide": "",
    },
    # Profile B — cancer-predominant family history
    {
        "history_mother": "Breast cancer at age 60, bilateral mastectomy. Hypertension. "
                          "Died of metastatic ovarian cancer at age 71.",
        "history_father": "Colorectal cancer at age 65, partial colectomy. Hyperlipidemia.",
        "history_siblings": "One sister with breast cancer. One brother healthy.",
        "history_offspring": "Daughter with BRCA1 positive screening result.",
        "history_spouse": "No significant family history reported.",
        "relatives_cancer": "mother,father,siblings,offspring",
        "relatives_diabetes": "",
        "relatives_high_blood_pressure": "mother",
        "relatives_heart_problems": "",
        "relatives_stroke": "",
        "relatives_epilepsy": "",
        "relatives_mental_illness": "",
        "relatives_tuberculosis": "",
        "relatives_suicide": "",
    },
    # Profile C — metabolic syndrome + mental health cluster
    {
        "history_mother": "Type 2 diabetes and obesity. Hypertension. "
                          "Myocardial infarction at age 68.",
        "history_father": "Bipolar disorder. Alcohol use disorder. "
                          "Hypertension, died of stroke at age 63.",
        "history_siblings": "Two brothers with type 2 diabetes. One sister with depression.",
        "history_offspring": "Son with anxiety disorder.",
        "history_spouse": "Spouse with type 2 diabetes.",
        "relatives_cancer": "",
        "relatives_diabetes": "mother,siblings,spouse",
        "relatives_high_blood_pressure": "mother,father",
        "relatives_heart_problems": "mother",
        "relatives_stroke": "father",
        "relatives_epilepsy": "",
        "relatives_mental_illness": "father,siblings,offspring",
        "relatives_tuberculosis": "",
        "relatives_suicide": "",
    },
    # Profile D — stroke and neurological history
    {
        "history_mother": "Ischemic stroke at age 72, aphasia. Atrial fibrillation on warfarin. "
                          "Died at 80 of aspiration pneumonia.",
        "history_father": "TIA at age 67. Hypertension and hyperlipidemia. "
                          "Coronary artery disease, stent placement.",
        "history_siblings": "Sister with migraine disorder. Brother with hypertension.",
        "history_offspring": "No known illness.",
        "history_spouse": "Spouse with hypertension and type 2 diabetes.",
        "relatives_cancer": "",
        "relatives_diabetes": "spouse",
        "relatives_high_blood_pressure": "mother,father,siblings,spouse",
        "relatives_heart_problems": "father",
        "relatives_stroke": "mother,father",
        "relatives_epilepsy": "",
        "relatives_mental_illness": "",
        "relatives_tuberculosis": "",
        "relatives_suicide": "",
    },
    # Profile E — mixed: heart disease + diabetes + cancer
    {
        "history_mother": "Hypertension, type 2 diabetes for 15 years. "
                          "Heart failure diagnosed at 70. Died at 77.",
        "history_father": "Lung cancer, smoker, died at 69. Hypertension.",
        "history_siblings": "One brother with CAD, stent at age 58. "
                            "One sister with type 2 diabetes.",
        "history_offspring": "Son with prediabetes and hypertension.",
        "history_spouse": "No known chronic illness.",
        "relatives_cancer": "father",
        "relatives_diabetes": "mother,siblings,offspring",
        "relatives_high_blood_pressure": "mother,father,siblings,offspring",
        "relatives_heart_problems": "mother,siblings",
        "relatives_stroke": "",
        "relatives_epilepsy": "",
        "relatives_mental_illness": "",
        "relatives_tuberculosis": "",
        "relatives_suicide": "",
    },
    # Profile F — autoimmune and endocrine cluster
    {
        "history_mother": "Hypothyroidism, rheumatoid arthritis. Type 2 diabetes.",
        "history_father": "Type 1 diabetes. Coronary artery disease. Died at 72.",
        "history_siblings": "Sister with lupus. Brother with type 2 diabetes.",
        "history_offspring": "Daughter with Hashimoto's thyroiditis.",
        "history_spouse": "Spouse with hypertension.",
        "relatives_cancer": "",
        "relatives_diabetes": "mother,father,siblings",
        "relatives_high_blood_pressure": "spouse",
        "relatives_heart_problems": "father",
        "relatives_stroke": "",
        "relatives_epilepsy": "",
        "relatives_mental_illness": "",
        "relatives_tuberculosis": "",
        "relatives_suicide": "",
    },
    # Profile G — predominantly hypertension and CAD
    {
        "history_mother": "Hypertension since age 45. Heart failure at 74. "
                          "Pacemaker placement. Died at 82.",
        "history_father": "Hypertension and hyperlipidemia. MI at age 60, survived. "
                          "CABG at 65.",
        "history_siblings": "All three siblings with hypertension. "
                            "One brother with CAD and type 2 diabetes.",
        "history_offspring": "No significant history.",
        "history_spouse": "Spouse with hypertension and obesity.",
        "relatives_cancer": "",
        "relatives_diabetes": "siblings",
        "relatives_high_blood_pressure": "mother,father,siblings,spouse",
        "relatives_heart_problems": "mother,father,siblings",
        "relatives_stroke": "",
        "relatives_epilepsy": "",
        "relatives_mental_illness": "",
        "relatives_tuberculosis": "",
        "relatives_suicide": "",
    },
    # Profile H — cancer + mental health + substance use
    {
        "history_mother": "Colon cancer at age 58, colostomy. Anxiety disorder.",
        "history_father": "Alcohol use disorder. Died of liver cirrhosis at 61. "
                          "Hypertension.",
        "history_siblings": "Brother with depression and alcohol use disorder. "
                            "Sister with breast cancer at 50.",
        "history_offspring": "No known illness.",
        "history_spouse": "Spouse with depression.",
        "relatives_cancer": "mother,siblings",
        "relatives_diabetes": "",
        "relatives_high_blood_pressure": "father",
        "relatives_heart_problems": "",
        "relatives_stroke": "",
        "relatives_epilepsy": "",
        "relatives_mental_illness": "mother,father,siblings,spouse",
        "relatives_tuberculosis": "",
        "relatives_suicide": "",
    },
    # Profile I — diabetes dominant across all generations
    {
        "history_mother": "Type 2 diabetes since age 50. Peripheral neuropathy and CKD. "
                          "Hypertension. Died at 74 of ESRD.",
        "history_father": "Type 2 diabetes. Hypertension. "
                          "Coronary artery disease, died at 68.",
        "history_siblings": "All four siblings with type 2 diabetes. "
                            "Two with hypertension.",
        "history_offspring": "Two children with type 2 diabetes. "
                             "One child with prediabetes.",
        "history_spouse": "Spouse with type 2 diabetes and hypertension.",
        "relatives_cancer": "",
        "relatives_diabetes": "mother,father,siblings,offspring,spouse",
        "relatives_high_blood_pressure": "mother,father,siblings,spouse",
        "relatives_heart_problems": "father",
        "relatives_stroke": "",
        "relatives_epilepsy": "",
        "relatives_mental_illness": "",
        "relatives_tuberculosis": "",
        "relatives_suicide": "",
    },
    # Profile J — cerebrovascular + hypertension, aging cohort
    {
        "history_mother": "Hypertension, hemorrhagic stroke at age 66. "
                          "Survived with right-sided weakness. Died at 73.",
        "history_father": "Hypertension and hyperlipidemia. "
                          "Peripheral vascular disease. Died of MI at 70.",
        "history_siblings": "Sister with hypertension and CKD. "
                            "Brother with stroke at age 59.",
        "history_offspring": "Son with hypertension diagnosed at 38.",
        "history_spouse": "No known illness.",
        "relatives_cancer": "",
        "relatives_diabetes": "",
        "relatives_high_blood_pressure": "mother,father,siblings,offspring",
        "relatives_heart_problems": "father",
        "relatives_stroke": "mother,siblings",
        "relatives_epilepsy": "",
        "relatives_mental_illness": "",
        "relatives_tuberculosis": "",
        "relatives_suicide": "",
    },
    # Profile K — prostate/colon cancer in males, breast in females
    {
        "history_mother": "Breast cancer at age 55, lumpectomy + radiation, survived. "
                          "Type 2 diabetes. Hypertension.",
        "history_father": "Prostate cancer at age 67, radical prostatectomy. "
                          "Hyperlipidemia.",
        "history_siblings": "Brother with colon cancer at 60. "
                            "Sister with hypertension.",
        "history_offspring": "No known malignancy.",
        "history_spouse": "Spouse with hyperlipidemia.",
        "relatives_cancer": "mother,father,siblings",
        "relatives_diabetes": "mother",
        "relatives_high_blood_pressure": "mother,siblings",
        "relatives_heart_problems": "",
        "relatives_stroke": "",
        "relatives_epilepsy": "",
        "relatives_mental_illness": "",
        "relatives_tuberculosis": "",
        "relatives_suicide": "",
    },
    # Profile L — COPD/respiratory + heart failure
    {
        "history_mother": "COPD (heavy smoker). Hypertension. "
                          "Heart failure, died at 71.",
        "history_father": "Emphysema, on home oxygen. Died at 68. "
                          "Hypertension and type 2 diabetes.",
        "history_siblings": "Two brothers who smoke heavily, one with COPD.",
        "history_offspring": "Daughter with asthma.",
        "history_spouse": "Spouse with asthma and hypertension.",
        "relatives_cancer": "",
        "relatives_diabetes": "father",
        "relatives_high_blood_pressure": "mother,father,spouse",
        "relatives_heart_problems": "mother",
        "relatives_stroke": "",
        "relatives_epilepsy": "",
        "relatives_mental_illness": "",
        "relatives_tuberculosis": "",
        "relatives_suicide": "",
    },
    # Profile M — epilepsy + mental health + diabetes
    {
        "history_mother": "Epilepsy since childhood. Type 2 diabetes. "
                          "Depression, managed with medication.",
        "history_father": "Hypertension. Died of MI at age 60.",
        "history_siblings": "Sister with epilepsy. Brother with schizophrenia.",
        "history_offspring": "Son with generalized anxiety disorder.",
        "history_spouse": "Spouse with type 2 diabetes.",
        "relatives_cancer": "",
        "relatives_diabetes": "mother,spouse",
        "relatives_high_blood_pressure": "father",
        "relatives_heart_problems": "father",
        "relatives_stroke": "",
        "relatives_epilepsy": "mother,siblings",
        "relatives_mental_illness": "mother,siblings,offspring",
        "relatives_tuberculosis": "",
        "relatives_suicide": "",
    },
    # Profile N — renal disease + hypertension + diabetes triad
    {
        "history_mother": "CKD stage 4, on dialysis for 3 years. Type 2 diabetes. "
                          "Hypertension. Died at 69.",
        "history_father": "Hypertension and type 2 diabetes. "
                          "MI at age 65. Died at 72.",
        "history_siblings": "Brother with type 2 diabetes and hypertension, "
                            "developing CKD. Sister with hypertension.",
        "history_offspring": "No known chronic illness yet.",
        "history_spouse": "Spouse with type 2 diabetes.",
        "relatives_cancer": "",
        "relatives_diabetes": "mother,father,siblings,spouse",
        "relatives_high_blood_pressure": "mother,father,siblings",
        "relatives_heart_problems": "father",
        "relatives_stroke": "",
        "relatives_epilepsy": "",
        "relatives_mental_illness": "",
        "relatives_tuberculosis": "",
        "relatives_suicide": "",
    },
    # Profile O — lean family history (control profile for variety)
    {
        "history_mother": "Osteoporosis, hip fracture at age 80. Mild hypertension. "
                          "Died at 88 of natural causes.",
        "history_father": "Hyperlipidemia. Type 2 diabetes diagnosed at age 72. "
                          "Otherwise healthy, died at 85.",
        "history_siblings": "One sister with hypertension. One brother with no known illness.",
        "history_offspring": "Children healthy.",
        "history_spouse": "Spouse with hyperlipidemia.",
        "relatives_cancer": "",
        "relatives_diabetes": "father",
        "relatives_high_blood_pressure": "mother,siblings",
        "relatives_heart_problems": "",
        "relatives_stroke": "",
        "relatives_epilepsy": "",
        "relatives_mental_illness": "",
        "relatives_tuberculosis": "",
        "relatives_suicide": "",
    },
]


# ---------------------------------------------------------------------------
# Seed logic
# ---------------------------------------------------------------------------


def _get_existing_pids(cursor) -> set[int]:
    """Return the set of pids that already have a row in history_data."""
    cursor.execute(
        "SELECT DISTINCT pid FROM history_data WHERE pid IN (%s)"
        % ",".join(["%s"] * len(TARGET_PIDS)),
        tuple(TARGET_PIDS),
    )
    rows = cursor.fetchall()
    if rows and isinstance(rows[0], dict):
        return {r["pid"] for r in rows}
    return {r[0] for r in rows}


def _get_present_pids(cursor) -> list[int]:
    """Return the pids from TARGET_PIDS that actually exist in patient_data."""
    cursor.execute(
        "SELECT pid FROM patient_data WHERE pid IN (%s) ORDER BY pid"
        % ",".join(["%s"] * len(TARGET_PIDS)),
        tuple(TARGET_PIDS),
    )
    rows = cursor.fetchall()
    if rows and isinstance(rows[0], dict):
        return [r["pid"] for r in rows]
    return [r[0] for r in rows]


def seed_family_history() -> None:
    with openemr_cursor(tenant_id="1") as cur:
        present_pids = _get_present_pids(cur)
        if not present_pids:
            log.warning(
                "No patients found in patient_data for pids %s–%s. "
                "Ensure demo patients are loaded first.",
                TARGET_PIDS[0],
                TARGET_PIDS[-1],
            )
            return

        existing_pids = _get_existing_pids(cur)
        log.info(
            "Found %d patients in range, %d already have history_data rows.",
            len(present_pids),
            len(existing_pids),
        )

        inserted = 0
        skipped = 0

        for idx, pid in enumerate(present_pids):
            if pid in existing_pids:
                log.info("pid=%d — skipping (history_data row already exists).", pid)
                skipped += 1
                continue

            profile = PROFILES[idx % len(PROFILES)]

            cur.execute(
                """
                INSERT INTO history_data (
                    pid,
                    history_mother,
                    history_father,
                    history_siblings,
                    history_offspring,
                    history_spouse,
                    relatives_cancer,
                    relatives_tuberculosis,
                    relatives_diabetes,
                    relatives_high_blood_pressure,
                    relatives_heart_problems,
                    relatives_stroke,
                    relatives_epilepsy,
                    relatives_mental_illness,
                    relatives_suicide,
                    `date`
                ) VALUES (
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    NOW()
                )
                """,
                (
                    pid,
                    profile["history_mother"],
                    profile["history_father"],
                    profile["history_siblings"],
                    profile["history_offspring"],
                    profile["history_spouse"],
                    profile["relatives_cancer"],
                    profile["relatives_tuberculosis"],
                    profile["relatives_diabetes"],
                    profile["relatives_high_blood_pressure"],
                    profile["relatives_heart_problems"],
                    profile["relatives_stroke"],
                    profile["relatives_epilepsy"],
                    profile["relatives_mental_illness"],
                    profile["relatives_suicide"],
                ),
            )
            log.info("pid=%d — inserted family history (profile %s).", pid, chr(65 + idx % len(PROFILES)))
            inserted += 1

    log.info(
        "Done. Inserted: %d  Skipped (already existed): %d  Not found in DB: %d",
        inserted,
        skipped,
        len(TARGET_PIDS) - len(present_pids),
    )


if __name__ == "__main__":
    seed_family_history()
