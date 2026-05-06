#!/usr/bin/env python3
"""
seed_loinc_top_signals.py
-------------------------
Seed the knowledge graph with the top ~50 LOINC codes most relevant to
HCC risk adjustment.

For each LOINC code we:
  1. Insert a row in ``knowledge_graph_concepts`` (code_system='LOINC') if
     missing.  This represents the *test*.
  2. Insert / refresh one or more rows in ``kg_lab_signals`` linking the LOINC
     value rule to a *condition concept* (also looked up / inserted in
     ``knowledge_graph_concepts``, code_system='ICD10').
  3. Insert a ``has_lab_signal`` edge in ``knowledge_graph_edges`` from the
     LOINC concept to the condition concept (idempotent).

Run:
    python -m backend.scripts.seed_loinc_top_signals
or:
    python backend/scripts/seed_loinc_top_signals.py

Idempotent: re-running will not duplicate rows.

Prerequisites
-------------
* ``knowledge_graph_concepts`` and ``knowledge_graph_edges`` tables exist
  (Agent 1 migration applied).
* ``kg_lab_signals`` table exists (this PR's migration applied).
"""
from __future__ import annotations

import logging
import os
import sys
from typing import Any

# Allow running as a script: ``python backend/scripts/seed_loinc_top_signals.py``
_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.abspath(os.path.join(_HERE, ".."))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from app.db import raf_cursor  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("seed_loinc")


# ---------------------------------------------------------------------------
# Curated LOINC -> threshold -> condition mapping
# ---------------------------------------------------------------------------
# Each row:
#   loinc_code, test_name, unit, low, high, meaning,
#   condition_icd10, condition_display, hcc_code, confidence, notes
#
# meaning ∈ {'above','below','outside','within'}
#   - 'above'   triggers when value >= high
#   - 'below'   triggers when value <= low
#   - 'outside' triggers when value < low OR value > high
#   - 'within'  triggers when low <= value <= high
#
# Rows beyond a basic 25 cover the requested top-50 surface.

LOINC_SIGNALS: list[dict[str, Any]] = [
    # --- Diabetes / HbA1c ---------------------------------------------------
    {"loinc_code": "4548-4", "test_name": "Hemoglobin A1c", "unit": "%",
     "low": None, "high": 6.5, "meaning": "above",
     "condition_icd10": "E11.9", "condition_display": "Type 2 Diabetes Mellitus",
     "hcc_code": "HCC36", "confidence": 0.85,
     "notes": "HbA1c >= 6.5% supports diabetes diagnosis"},
    {"loinc_code": "4548-4", "test_name": "Hemoglobin A1c", "unit": "%",
     "low": None, "high": 9.0, "meaning": "above",
     "condition_icd10": "E11.65", "condition_display": "Type 2 DM with hyperglycemia (uncontrolled)",
     "hcc_code": "HCC36", "confidence": 0.90,
     "notes": "HbA1c >= 9.0% indicates uncontrolled diabetes"},

    # --- Renal: eGFR --------------------------------------------------------
    {"loinc_code": "33914-3", "test_name": "Estimated Glomerular Filtration Rate",
     "unit": "mL/min/1.73m2", "low": 60.0, "high": None, "meaning": "below",
     "condition_icd10": "N18.9", "condition_display": "Chronic kidney disease, unspecified",
     "hcc_code": None, "confidence": 0.70,
     "notes": "eGFR <= 60 suggests CKD"},
    {"loinc_code": "33914-3", "test_name": "Estimated Glomerular Filtration Rate",
     "unit": "mL/min/1.73m2", "low": 30.0, "high": None, "meaning": "below",
     "condition_icd10": "N18.4", "condition_display": "CKD Stage 4",
     "hcc_code": "HCC326", "confidence": 0.85,
     "notes": "eGFR <= 30 indicates CKD stage 4"},
    {"loinc_code": "33914-3", "test_name": "Estimated Glomerular Filtration Rate",
     "unit": "mL/min/1.73m2", "low": 15.0, "high": None, "meaning": "below",
     "condition_icd10": "N18.5", "condition_display": "CKD Stage 5",
     "hcc_code": "HCC326", "confidence": 0.92,
     "notes": "eGFR <= 15 indicates CKD stage 5 / ESRD candidate"},

    # --- Lipid panel --------------------------------------------------------
    {"loinc_code": "13457-7", "test_name": "LDL Cholesterol (calculated)",
     "unit": "mg/dL", "low": None, "high": 190.0, "meaning": "above",
     "condition_icd10": "E78.5", "condition_display": "Hyperlipidemia, unspecified",
     "hcc_code": None, "confidence": 0.60,
     "notes": "LDL >= 190 mg/dL = severe hyperlipidemia"},
    {"loinc_code": "2093-3", "test_name": "Total Cholesterol",
     "unit": "mg/dL", "low": None, "high": 240.0, "meaning": "above",
     "condition_icd10": "E78.0", "condition_display": "Pure hypercholesterolemia",
     "hcc_code": None, "confidence": 0.55, "notes": "Total chol >= 240 mg/dL"},
    {"loinc_code": "2085-9", "test_name": "HDL Cholesterol",
     "unit": "mg/dL", "low": 40.0, "high": None, "meaning": "below",
     "condition_icd10": "E78.6", "condition_display": "Lipoprotein deficiency",
     "hcc_code": None, "confidence": 0.50, "notes": "Low HDL"},
    {"loinc_code": "2571-8", "test_name": "Triglycerides",
     "unit": "mg/dL", "low": None, "high": 500.0, "meaning": "above",
     "condition_icd10": "E78.1", "condition_display": "Pure hyperglyceridemia",
     "hcc_code": None, "confidence": 0.65,
     "notes": "TG >= 500 mg/dL = severe hypertriglyceridemia"},

    # --- Cardiac biomarkers -------------------------------------------------
    {"loinc_code": "30934-4", "test_name": "B-type Natriuretic Peptide (BNP)",
     "unit": "pg/mL", "low": None, "high": 400.0, "meaning": "above",
     "condition_icd10": "I50.9", "condition_display": "Heart failure, unspecified",
     "hcc_code": "HCC85", "confidence": 0.80,
     "notes": "BNP >= 400 pg/mL strongly suggests CHF"},
    {"loinc_code": "33762-6", "test_name": "NT-proBNP",
     "unit": "pg/mL", "low": None, "high": 900.0, "meaning": "above",
     "condition_icd10": "I50.9", "condition_display": "Heart failure, unspecified",
     "hcc_code": "HCC85", "confidence": 0.80,
     "notes": "NT-proBNP >= 900 pg/mL suggests CHF"},
    {"loinc_code": "10839-9", "test_name": "Troponin I",
     "unit": "ng/mL", "low": None, "high": 0.04, "meaning": "above",
     "condition_icd10": "I21.4", "condition_display": "Acute MI (NSTEMI)",
     "hcc_code": "HCC222", "confidence": 0.85,
     "notes": "Troponin I elevation suggests acute myocardial injury"},
    {"loinc_code": "6598-7", "test_name": "Troponin T",
     "unit": "ng/mL", "low": None, "high": 0.01, "meaning": "above",
     "condition_icd10": "I21.4", "condition_display": "Acute MI (NSTEMI)",
     "hcc_code": "HCC222", "confidence": 0.85, "notes": "TnT elevation"},

    # --- Renal: creatinine --------------------------------------------------
    {"loinc_code": "2160-0", "test_name": "Creatinine, serum",
     "unit": "mg/dL", "low": None, "high": 1.5, "meaning": "above",
     "condition_icd10": "N17.9", "condition_display": "Acute kidney injury, unspecified",
     "hcc_code": "HCC326", "confidence": 0.55,
     "notes": "Creatinine elevation requires clinical context"},

    # --- Cancer markers -----------------------------------------------------
    {"loinc_code": "2857-1", "test_name": "Prostate Specific Antigen",
     "unit": "ng/mL", "low": None, "high": 4.0, "meaning": "above",
     "condition_icd10": "R97.20", "condition_display": "Elevated PSA",
     "hcc_code": None, "confidence": 0.50,
     "notes": "Elevated PSA, not diagnostic of prostate cancer"},
    {"loinc_code": "10334-1", "test_name": "CA 125",
     "unit": "U/mL", "low": None, "high": 35.0, "meaning": "above",
     "condition_icd10": "C56.9", "condition_display": "Malignant neoplasm of ovary",
     "hcc_code": "HCC18", "confidence": 0.55,
     "notes": "Elevated CA-125 in appropriate clinical context"},
    {"loinc_code": "2039-6", "test_name": "Carcinoembryonic Antigen (CEA)",
     "unit": "ng/mL", "low": None, "high": 5.0, "meaning": "above",
     "condition_icd10": "C18.9", "condition_display": "Malignant neoplasm of colon",
     "hcc_code": "HCC22", "confidence": 0.55,
     "notes": "Elevated CEA may indicate GI malignancy"},

    # --- Endocrine ----------------------------------------------------------
    {"loinc_code": "3016-3", "test_name": "Thyrotropin (TSH)",
     "unit": "mIU/L", "low": 0.4, "high": 4.0, "meaning": "outside",
     "condition_icd10": "E03.9", "condition_display": "Hypothyroidism, unspecified",
     "hcc_code": None, "confidence": 0.55,
     "notes": "TSH outside reference range"},
    {"loinc_code": "3026-2", "test_name": "Thyroxine (T4) free",
     "unit": "ng/dL", "low": 0.8, "high": 1.8, "meaning": "outside",
     "condition_icd10": "E03.9", "condition_display": "Hypothyroidism, unspecified",
     "hcc_code": None, "confidence": 0.50,
     "notes": "Free T4 outside reference range"},

    # --- Glucose ------------------------------------------------------------
    {"loinc_code": "2345-7", "test_name": "Glucose, serum",
     "unit": "mg/dL", "low": None, "high": 200.0, "meaning": "above",
     "condition_icd10": "R73.9", "condition_display": "Hyperglycemia, unspecified",
     "hcc_code": None, "confidence": 0.55,
     "notes": "Random glucose >= 200 mg/dL indicates hyperglycemia"},
    {"loinc_code": "1558-6", "test_name": "Glucose, fasting",
     "unit": "mg/dL", "low": None, "high": 126.0, "meaning": "above",
     "condition_icd10": "E11.9", "condition_display": "Type 2 Diabetes Mellitus",
     "hcc_code": "HCC36", "confidence": 0.70,
     "notes": "Fasting glucose >= 126 mg/dL on two occasions = diabetes"},

    # --- Hematology ---------------------------------------------------------
    # Anemia -- sex-specific thresholds use two rows.
    {"loinc_code": "718-7", "test_name": "Hemoglobin (female)",
     "unit": "g/dL", "low": 11.0, "high": None, "meaning": "below",
     "condition_icd10": "D64.9", "condition_display": "Anemia, unspecified (female)",
     "hcc_code": "HCC48", "confidence": 0.75,
     "notes": "Hgb <= 11 g/dL in females suggests anemia"},
    {"loinc_code": "718-7", "test_name": "Hemoglobin (male)",
     "unit": "g/dL", "low": 13.0, "high": None, "meaning": "below",
     "condition_icd10": "D64.9", "condition_display": "Anemia, unspecified (male)",
     "hcc_code": "HCC48", "confidence": 0.75,
     "notes": "Hgb <= 13 g/dL in males suggests anemia"},
    {"loinc_code": "4544-3", "test_name": "Hematocrit",
     "unit": "%", "low": 36.0, "high": None, "meaning": "below",
     "condition_icd10": "D64.9", "condition_display": "Anemia, unspecified",
     "hcc_code": "HCC48", "confidence": 0.65, "notes": "Low Hct"},
    {"loinc_code": "777-3", "test_name": "Platelet count",
     "unit": "10*9/L", "low": 100.0, "high": None, "meaning": "below",
     "condition_icd10": "D69.6", "condition_display": "Thrombocytopenia, unspecified",
     "hcc_code": "HCC48", "confidence": 0.70,
     "notes": "Platelets <= 100 indicates thrombocytopenia"},
    {"loinc_code": "6690-2", "test_name": "Leukocytes (WBC)",
     "unit": "10*9/L", "low": 4.0, "high": 11.0, "meaning": "outside",
     "condition_icd10": "D72.829", "condition_display": "Abnormality of leukocytes",
     "hcc_code": None, "confidence": 0.45,
     "notes": "WBC outside reference range"},

    # --- Coagulation --------------------------------------------------------
    {"loinc_code": "6301-6", "test_name": "INR",
     "unit": "ratio", "low": None, "high": 4.0, "meaning": "above",
     "condition_icd10": "D68.32", "condition_display": "Hemorrhagic disorder due to anticoagulants",
     "hcc_code": "HCC48", "confidence": 0.60,
     "notes": "INR >= 4 indicates supratherapeutic anticoagulation"},
    {"loinc_code": "5902-2", "test_name": "Prothrombin time (PT)",
     "unit": "s", "low": None, "high": 14.0, "meaning": "above",
     "condition_icd10": "D68.4", "condition_display": "Acquired coagulation factor deficiency",
     "hcc_code": "HCC48", "confidence": 0.50, "notes": "Prolonged PT"},

    # --- Hepatic ------------------------------------------------------------
    {"loinc_code": "1751-7", "test_name": "Albumin, serum",
     "unit": "g/dL", "low": 3.0, "high": None, "meaning": "below",
     "condition_icd10": "E46", "condition_display": "Unspecified protein-calorie malnutrition",
     "hcc_code": "HCC23", "confidence": 0.70,
     "notes": "Albumin <= 3.0 g/dL suggests malnutrition or liver dysfunction"},
    {"loinc_code": "1975-2", "test_name": "Bilirubin, total",
     "unit": "mg/dL", "low": None, "high": 2.0, "meaning": "above",
     "condition_icd10": "K76.9", "condition_display": "Liver disease, unspecified",
     "hcc_code": "HCC62", "confidence": 0.55,
     "notes": "Elevated total bilirubin"},
    {"loinc_code": "1742-6", "test_name": "Alanine Aminotransferase (ALT)",
     "unit": "U/L", "low": None, "high": 100.0, "meaning": "above",
     "condition_icd10": "K76.9", "condition_display": "Liver disease, unspecified",
     "hcc_code": "HCC62", "confidence": 0.55,
     "notes": "ALT > 2x upper limit suggests hepatocellular injury"},
    {"loinc_code": "1920-8", "test_name": "Aspartate Aminotransferase (AST)",
     "unit": "U/L", "low": None, "high": 100.0, "meaning": "above",
     "condition_icd10": "K76.9", "condition_display": "Liver disease, unspecified",
     "hcc_code": "HCC62", "confidence": 0.55, "notes": "AST elevation"},
    {"loinc_code": "6768-6", "test_name": "Alkaline Phosphatase",
     "unit": "U/L", "low": None, "high": 200.0, "meaning": "above",
     "condition_icd10": "K83.1", "condition_display": "Obstruction of bile duct",
     "hcc_code": "HCC62", "confidence": 0.50, "notes": "ALP elevation"},

    # --- HIV ----------------------------------------------------------------
    {"loinc_code": "24467-3", "test_name": "CD4 cell count",
     "unit": "cells/uL", "low": 200.0, "high": None, "meaning": "below",
     "condition_icd10": "B20", "condition_display": "Human immunodeficiency virus disease",
     "hcc_code": "HCC1", "confidence": 0.85,
     "notes": "CD4 < 200 indicates AIDS-defining immunosuppression"},
    {"loinc_code": "20447-9", "test_name": "HIV Viral Load",
     "unit": "copies/mL", "low": None, "high": 200.0, "meaning": "above",
     "condition_icd10": "B20", "condition_display": "Human immunodeficiency virus disease",
     "hcc_code": "HCC1", "confidence": 0.80,
     "notes": "Detectable viral load suggests inadequate viral suppression"},

    # --- Pulmonary / metabolic ---------------------------------------------
    {"loinc_code": "2019-8", "test_name": "PaCO2 arterial",
     "unit": "mm Hg", "low": None, "high": 50.0, "meaning": "above",
     "condition_icd10": "J96.20", "condition_display": "Acute and chronic respiratory failure",
     "hcc_code": "HCC213", "confidence": 0.75,
     "notes": "PaCO2 >= 50 indicates hypercapnic respiratory failure"},
    {"loinc_code": "2703-7", "test_name": "PaO2 arterial",
     "unit": "mm Hg", "low": 60.0, "high": None, "meaning": "below",
     "condition_icd10": "J96.20", "condition_display": "Acute and chronic respiratory failure",
     "hcc_code": "HCC213", "confidence": 0.75,
     "notes": "PaO2 < 60 indicates hypoxemic respiratory failure"},
    {"loinc_code": "2744-1", "test_name": "Arterial pH",
     "unit": "pH", "low": 7.30, "high": 7.45, "meaning": "outside",
     "condition_icd10": "E87.2", "condition_display": "Acidosis",
     "hcc_code": "HCC23", "confidence": 0.55,
     "notes": "pH outside reference indicates acid-base disturbance"},

    # --- Electrolytes ------------------------------------------------------
    {"loinc_code": "2823-3", "test_name": "Potassium",
     "unit": "mmol/L", "low": 3.5, "high": 5.5, "meaning": "outside",
     "condition_icd10": "E87.5", "condition_display": "Hyperkalemia",
     "hcc_code": "HCC23", "confidence": 0.55,
     "notes": "Potassium outside 3.5-5.5"},
    {"loinc_code": "2951-2", "test_name": "Sodium",
     "unit": "mmol/L", "low": 135.0, "high": 145.0, "meaning": "outside",
     "condition_icd10": "E87.1", "condition_display": "Hypo-osmolality and hyponatremia",
     "hcc_code": "HCC23", "confidence": 0.55,
     "notes": "Sodium outside 135-145"},
    {"loinc_code": "17861-6", "test_name": "Calcium, total",
     "unit": "mg/dL", "low": 8.5, "high": 10.5, "meaning": "outside",
     "condition_icd10": "E83.51", "condition_display": "Hypocalcemia",
     "hcc_code": "HCC23", "confidence": 0.50,
     "notes": "Calcium outside reference"},
    {"loinc_code": "2777-1", "test_name": "Phosphate",
     "unit": "mg/dL", "low": 2.5, "high": 4.5, "meaning": "outside",
     "condition_icd10": "E83.30", "condition_display": "Disorder of phosphorus metabolism",
     "hcc_code": "HCC23", "confidence": 0.50, "notes": "Phosphate disturbance"},
    {"loinc_code": "19123-9", "test_name": "Magnesium",
     "unit": "mg/dL", "low": 1.7, "high": 2.6, "meaning": "outside",
     "condition_icd10": "E83.42", "condition_display": "Hypomagnesemia",
     "hcc_code": "HCC23", "confidence": 0.50, "notes": "Mg disturbance"},

    # --- Iron studies ------------------------------------------------------
    {"loinc_code": "2276-4", "test_name": "Ferritin",
     "unit": "ng/mL", "low": 30.0, "high": None, "meaning": "below",
     "condition_icd10": "D50.9", "condition_display": "Iron deficiency anemia, unspecified",
     "hcc_code": "HCC48", "confidence": 0.65,
     "notes": "Ferritin <= 30 ng/mL = iron deficiency"},
    {"loinc_code": "2498-4", "test_name": "Iron, serum",
     "unit": "ug/dL", "low": 60.0, "high": None, "meaning": "below",
     "condition_icd10": "D50.9", "condition_display": "Iron deficiency anemia, unspecified",
     "hcc_code": "HCC48", "confidence": 0.55, "notes": "Low serum iron"},

    # --- Vitamins / nutrition ----------------------------------------------
    {"loinc_code": "2132-9", "test_name": "Vitamin B12",
     "unit": "pg/mL", "low": 200.0, "high": None, "meaning": "below",
     "condition_icd10": "D51.0", "condition_display": "Vitamin B12 deficiency anemia",
     "hcc_code": "HCC48", "confidence": 0.65, "notes": "B12 deficiency"},
    {"loinc_code": "1989-3", "test_name": "Vitamin D 25-OH",
     "unit": "ng/mL", "low": 20.0, "high": None, "meaning": "below",
     "condition_icd10": "E55.9", "condition_display": "Vitamin D deficiency, unspecified",
     "hcc_code": None, "confidence": 0.50, "notes": "Vit D insufficiency"},

    # --- Inflammatory markers ----------------------------------------------
    {"loinc_code": "1988-5", "test_name": "C-reactive protein",
     "unit": "mg/L", "low": None, "high": 10.0, "meaning": "above",
     "condition_icd10": "R79.82", "condition_display": "Elevated CRP",
     "hcc_code": None, "confidence": 0.40,
     "notes": "Elevated CRP suggests inflammation"},
    {"loinc_code": "30341-2", "test_name": "Erythrocyte sedimentation rate",
     "unit": "mm/h", "low": None, "high": 30.0, "meaning": "above",
     "condition_icd10": "R70.0", "condition_display": "Elevated ESR",
     "hcc_code": None, "confidence": 0.40, "notes": "Elevated ESR"},

    # --- Urinalysis / proteinuria ------------------------------------------
    {"loinc_code": "9318-7", "test_name": "Albumin/Creatinine ratio (urine)",
     "unit": "mg/g", "low": None, "high": 30.0, "meaning": "above",
     "condition_icd10": "N18.9", "condition_display": "Chronic kidney disease, unspecified",
     "hcc_code": None, "confidence": 0.65,
     "notes": "ACR >= 30 = albuminuria"},
    {"loinc_code": "20454-5", "test_name": "Protein, urine",
     "unit": "mg/dL", "low": None, "high": 30.0, "meaning": "above",
     "condition_icd10": "R80.9", "condition_display": "Proteinuria, unspecified",
     "hcc_code": None, "confidence": 0.50,
     "notes": "Proteinuria"},

    # --- Cardiac additional -----------------------------------------------
    {"loinc_code": "9457-3", "test_name": "Ejection fraction (LV)",
     "unit": "%", "low": 40.0, "high": None, "meaning": "below",
     "condition_icd10": "I50.22", "condition_display": "Chronic systolic heart failure",
     "hcc_code": "HCC85", "confidence": 0.85,
     "notes": "LVEF <= 40% indicates systolic HF"},
]


# ---------------------------------------------------------------------------
# DB helpers — concept upsert + edge upsert
# ---------------------------------------------------------------------------

def _upsert_concept(
    cur,
    code_system: str,
    code: str,
    display_name: str,
    hcc_code: str | None = None,
) -> int:
    """Insert if missing, return concept id.
    Maps the original code_system/display_name params onto the canonical
    Agent-1 schema: ontology / preferred_label.
    hcc_code is stashed in metadata since the foundation schema has no such column.
    """
    ontology = (code_system or "").lower()  # 'LOINC' -> 'loinc' etc.
    cur.execute(
        """
        SELECT id FROM knowledge_graph_concepts
        WHERE ontology = %s AND code = %s
        LIMIT 1
        """,
        (ontology, code),
    )
    row = cur.fetchone()
    if row:
        cid = row["id"] if isinstance(row, dict) else row[0]
        cur.execute(
            """
            UPDATE knowledge_graph_concepts
            SET preferred_label = COALESCE(NULLIF(%s, ''), preferred_label)
            WHERE id = %s
            """,
            (display_name or "", cid),
        )
        return int(cid)

    import json as _json
    cur.execute(
        """
        INSERT INTO knowledge_graph_concepts
            (concept_uri, ontology, code, preferred_label, metadata)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (
            f"{ontology}:{code}",
            ontology,
            code,
            display_name,
            _json.dumps({"hcc_code": hcc_code}) if hcc_code else None,
        ),
    )
    return int(cur.lastrowid)


def _upsert_edge(cur, src_id: int, dst_id: int, edge_type: str, weight: float = 1.0) -> None:
    cur.execute(
        """
        SELECT id FROM knowledge_graph_edges
        WHERE src_concept_id = %s AND dst_concept_id = %s AND edge_type = %s
        LIMIT 1
        """,
        (src_id, dst_id, edge_type),
    )
    if cur.fetchone():
        return
    cur.execute(
        """
        INSERT INTO knowledge_graph_edges
            (src_concept_id, dst_concept_id, edge_type, weight)
        VALUES (%s, %s, %s, %s)
        """,
        (src_id, dst_id, edge_type, weight),
    )


def _signal_exists(
    cur,
    loinc_code: str,
    test_name: str,
    low: float | None,
    high: float | None,
    meaning: str,
    concept_id: int,
) -> bool:
    cur.execute(
        """
        SELECT id FROM kg_lab_signals
        WHERE loinc_code = %s
          AND test_name = %s
          AND COALESCE(threshold_low, -9e9)  = COALESCE(%s, -9e9)
          AND COALESCE(threshold_high, 9e9)  = COALESCE(%s, 9e9)
          AND threshold_meaning = %s
          AND signals_concept_id = %s
        LIMIT 1
        """,
        (loinc_code, test_name, low, high, meaning, concept_id),
    )
    return bool(cur.fetchone())


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def seed() -> dict[str, int]:
    inserted_signals = 0
    skipped_signals = 0
    inserted_loinc_concepts = 0
    inserted_condition_concepts = 0
    inserted_edges = 0

    with raf_cursor() as cur:
        for row in LOINC_SIGNALS:
            loinc = row["loinc_code"]
            test_name = row["test_name"]
            unit = row.get("unit")
            low = row.get("low")
            high = row.get("high")
            meaning = row["meaning"]
            icd = row["condition_icd10"]
            cond_display = row["condition_display"]
            hcc = row.get("hcc_code")
            conf = row.get("confidence", 0.7)
            notes = row.get("notes")

            # 1. LOINC concept -- code_system 'LOINC'
            cur.execute(
                "SELECT id FROM knowledge_graph_concepts WHERE ontology='loinc' AND code=%s LIMIT 1",
                (loinc,),
            )
            existed_loinc = bool(cur.fetchone())
            loinc_id = _upsert_concept(cur, "LOINC", loinc, test_name)
            if not existed_loinc:
                inserted_loinc_concepts += 1

            # 2. Condition concept -- code_system 'ICD10'
            cur.execute(
                "SELECT id FROM knowledge_graph_concepts WHERE ontology='icd10' AND code=%s LIMIT 1",
                (icd,),
            )
            existed_cond = bool(cur.fetchone())
            cond_id = _upsert_concept(cur, "ICD10", icd, cond_display, hcc)
            if not existed_cond:
                inserted_condition_concepts += 1

            # 3. kg_lab_signals row
            if _signal_exists(cur, loinc, test_name, low, high, meaning, cond_id):
                skipped_signals += 1
            else:
                cur.execute(
                    """
                    INSERT INTO kg_lab_signals
                        (loinc_code, test_name, unit, threshold_low, threshold_high,
                         threshold_meaning, signals_concept_id, confidence, source, notes,
                         is_active)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1)
                    """,
                    (
                        loinc, test_name, unit, low, high, meaning, cond_id,
                        conf, "curated", notes,
                    ),
                )
                inserted_signals += 1

            # 4. Edge: LOINC --has_lab_signal--> condition
            cur.execute(
                """
                SELECT id FROM knowledge_graph_edges
                WHERE src_concept_id=%s AND dst_concept_id=%s AND edge_type='has_lab_signal'
                LIMIT 1
                """,
                (loinc_id, cond_id),
            )
            if not cur.fetchone():
                _upsert_edge(cur, loinc_id, cond_id, "has_lab_signal", float(conf))
                inserted_edges += 1

    summary = {
        "rules_processed": len(LOINC_SIGNALS),
        "signals_inserted": inserted_signals,
        "signals_skipped_existing": skipped_signals,
        "loinc_concepts_inserted": inserted_loinc_concepts,
        "condition_concepts_inserted": inserted_condition_concepts,
        "edges_inserted": inserted_edges,
    }
    log.info("seed complete: %s", summary)
    return summary


if __name__ == "__main__":
    try:
        seed()
    except Exception as exc:
        log.exception("seeding failed: %s", exc)
        sys.exit(1)
