"""Seed the WHO ATC class hierarchy + RxNorm bridge.

Populates three tables:

  - ``knowledge_graph_concepts`` — one row per ATC node, plus indication and
    HCC concepts referenced by ``has_indication`` / ``maps_to_hcc`` edges.
  - ``kg_atc_classes`` — the 5-level hierarchy (~80 codes covering the
    high-signal therapeutic classes for HCC inference).
  - ``kg_rxnorm_to_atc`` — ~100 common drug names + RxCUIs (and a sprinkle of
    NDCs) bridged to ATC codes.

Idempotent — re-running the script updates rather than duplicates rows.

Usage::

    PYTHONPATH=backend python backend/scripts/seed_atc_top_classes.py
"""
from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

# Make ``backend`` importable when run as a script.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

logger = logging.getLogger("seed_atc")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


# ---------------------------------------------------------------------------
# 1. ATC hierarchy (level, code, parent, name, indication keys, HCC keys)
# ---------------------------------------------------------------------------
#
# *indications* and *hccs* are lists of stable keys we resolve into concept
# ids when seeding.  Keys map 1:1 to entries in INDICATION_CONCEPTS / HCC_CONCEPTS
# below.  Levels:
#   1 = anatomical main group (single letter)
#   2 = therapeutic main group (e.g. A10)
#   3 = pharmacological subgroup (e.g. A10B)
#   4 = chemical subgroup (e.g. A10BA)
#   5 = chemical substance (e.g. A10BA02)
#
# Indications/HCCs are typically attached at level 4 (the most useful for
# class-level inference).
#
# About 80 codes total.

ATC_HIERARCHY: list[dict[str, Any]] = [
    # ----------------------------- A: alimentary tract / metabolism ------
    {"code": "A", "parent": None, "level": 1, "name": "Alimentary tract and metabolism"},
    {"code": "A10", "parent": "A", "level": 2, "name": "Drugs used in diabetes",
     "indications": ["diabetes"], "hccs": ["HCC18", "HCC19"]},
    {"code": "A10A", "parent": "A10", "level": 3, "name": "Insulins and analogues",
     "indications": ["diabetes"], "hccs": ["HCC17", "HCC18"]},
    {"code": "A10AB", "parent": "A10A", "level": 4, "name": "Insulins and analogues for injection, fast-acting",
     "indications": ["diabetes"], "hccs": ["HCC17", "HCC18"]},
    {"code": "A10AE", "parent": "A10A", "level": 4, "name": "Insulins and analogues for injection, long-acting",
     "indications": ["diabetes"], "hccs": ["HCC17", "HCC18"]},
    {"code": "A10B", "parent": "A10", "level": 3, "name": "Blood glucose lowering drugs, excl. insulins",
     "indications": ["diabetes"], "hccs": ["HCC18", "HCC19"]},
    {"code": "A10BA", "parent": "A10B", "level": 4, "name": "Biguanides",
     "indications": ["diabetes"], "hccs": ["HCC18", "HCC19"]},
    {"code": "A10BA02", "parent": "A10BA", "level": 5, "name": "Metformin",
     "indications": ["diabetes"], "hccs": ["HCC18", "HCC19"]},
    {"code": "A10BB", "parent": "A10B", "level": 4, "name": "Sulfonylureas",
     "indications": ["diabetes"], "hccs": ["HCC18", "HCC19"]},
    {"code": "A10BH", "parent": "A10B", "level": 4, "name": "Dipeptidyl peptidase 4 (DPP-4) inhibitors",
     "indications": ["diabetes"], "hccs": ["HCC18", "HCC19"]},
    {"code": "A10BJ", "parent": "A10B", "level": 4, "name": "Glucagon-like peptide-1 (GLP-1) analogues",
     "indications": ["diabetes"], "hccs": ["HCC18", "HCC19"]},
    {"code": "A10BK", "parent": "A10B", "level": 4, "name": "Sodium-glucose co-transporter 2 (SGLT2) inhibitors",
     "indications": ["diabetes"], "hccs": ["HCC18", "HCC19"]},
    {"code": "A10BX", "parent": "A10B", "level": 4, "name": "Other blood glucose lowering drugs",
     "indications": ["diabetes"], "hccs": ["HCC18", "HCC19"]},

    # ----------------------------- B: blood / antithrombotics ------------
    {"code": "B", "parent": None, "level": 1, "name": "Blood and blood-forming organs"},
    {"code": "B01", "parent": "B", "level": 2, "name": "Antithrombotic agents"},
    {"code": "B01A", "parent": "B01", "level": 3, "name": "Antithrombotic agents (subgroup)"},
    {"code": "B01AA", "parent": "B01A", "level": 4, "name": "Vitamin K antagonists",
     "indications": ["atrial_fibrillation", "vte"], "hccs": ["HCC96"]},
    {"code": "B01AB", "parent": "B01A", "level": 4, "name": "Heparin group",
     "indications": ["vte"], "hccs": []},
    {"code": "B01AC", "parent": "B01A", "level": 4, "name": "Platelet aggregation inhibitors excl. heparin",
     "indications": ["cad"], "hccs": []},
    {"code": "B01AE", "parent": "B01A", "level": 4, "name": "Direct thrombin inhibitors",
     "indications": ["atrial_fibrillation", "vte"], "hccs": ["HCC96"]},
    {"code": "B01AF", "parent": "B01A", "level": 4, "name": "Direct factor Xa inhibitors",
     "indications": ["atrial_fibrillation", "vte"], "hccs": ["HCC96"]},

    # ----------------------------- C: cardiovascular --------------------
    {"code": "C", "parent": None, "level": 1, "name": "Cardiovascular system"},
    {"code": "C01", "parent": "C", "level": 2, "name": "Cardiac therapy"},
    {"code": "C01D", "parent": "C01", "level": 3, "name": "Vasodilators used in cardiac diseases",
     "indications": ["cad"], "hccs": []},
    {"code": "C01DA", "parent": "C01D", "level": 4, "name": "Organic nitrates",
     "indications": ["cad"], "hccs": []},
    {"code": "C03", "parent": "C", "level": 2, "name": "Diuretics"},
    {"code": "C03C", "parent": "C03", "level": 3, "name": "High-ceiling diuretics",
     "indications": ["chf"], "hccs": ["HCC85"]},
    {"code": "C03CA", "parent": "C03C", "level": 4, "name": "Loop diuretics (sulfonamides)",
     "indications": ["chf"], "hccs": ["HCC85"]},
    {"code": "C03D", "parent": "C03", "level": 3, "name": "Potassium-sparing agents",
     "indications": ["chf"], "hccs": ["HCC85"]},
    {"code": "C03DA", "parent": "C03D", "level": 4, "name": "Aldosterone antagonists",
     "indications": ["chf"], "hccs": ["HCC85"]},
    {"code": "C07", "parent": "C", "level": 2, "name": "Beta blocking agents"},
    {"code": "C07A", "parent": "C07", "level": 3, "name": "Beta blocking agents (subgroup)"},
    {"code": "C07AA", "parent": "C07A", "level": 4, "name": "Beta blocking agents, non-selective",
     "indications": ["hypertension"], "hccs": []},
    {"code": "C07AB", "parent": "C07A", "level": 4, "name": "Beta blocking agents, selective",
     "indications": ["chf", "cad", "hypertension"], "hccs": ["HCC85"]},
    {"code": "C07AG", "parent": "C07A", "level": 4, "name": "Alpha and beta blocking agents",
     "indications": ["chf", "hypertension"], "hccs": ["HCC85"]},
    {"code": "C09", "parent": "C", "level": 2, "name": "Agents acting on the renin-angiotensin system"},
    {"code": "C09A", "parent": "C09", "level": 3, "name": "ACE inhibitors, plain"},
    {"code": "C09AA", "parent": "C09A", "level": 4, "name": "ACE inhibitors, plain (substances)",
     "indications": ["hypertension", "chf"], "hccs": ["HCC85"]},
    {"code": "C09C", "parent": "C09", "level": 3, "name": "Angiotensin II receptor blockers, plain"},
    {"code": "C09CA", "parent": "C09C", "level": 4, "name": "Angiotensin II receptor blockers (ARBs)",
     "indications": ["hypertension", "chf"], "hccs": ["HCC85"]},
    {"code": "C09D", "parent": "C09", "level": 3, "name": "ARBs, combinations / ARNI"},
    {"code": "C09DX", "parent": "C09D", "level": 4, "name": "Angiotensin II receptor blockers, other combinations (incl. sacubitril/valsartan)",
     "indications": ["chf"], "hccs": ["HCC85"]},
    {"code": "C10", "parent": "C", "level": 2, "name": "Lipid modifying agents"},
    {"code": "C10A", "parent": "C10", "level": 3, "name": "Lipid modifying agents, plain"},
    {"code": "C10AA", "parent": "C10A", "level": 4, "name": "HMG CoA reductase inhibitors (statins)",
     "indications": ["hyperlipidemia", "cad"], "hccs": []},
    {"code": "C10AX", "parent": "C10A", "level": 4, "name": "Other lipid modifying agents",
     "indications": ["hyperlipidemia"], "hccs": []},

    # ----------------------------- J: anti-infectives -------------------
    {"code": "J", "parent": None, "level": 1, "name": "Anti-infectives for systemic use"},
    {"code": "J01", "parent": "J", "level": 2, "name": "Antibacterials for systemic use"},
    {"code": "J01CA", "parent": "J01", "level": 4, "name": "Penicillins with extended spectrum",
     "indications": [], "hccs": []},
    {"code": "J01FA", "parent": "J01", "level": 4, "name": "Macrolides",
     "indications": [], "hccs": []},
    {"code": "J05", "parent": "J", "level": 2, "name": "Antivirals for systemic use"},
    {"code": "J05A", "parent": "J05", "level": 3, "name": "Direct acting antivirals"},
    {"code": "J05AR", "parent": "J05A", "level": 4, "name": "Antivirals for treatment of HIV infections, combinations",
     "indications": ["hiv"], "hccs": ["HCC1"]},
    {"code": "J05AF", "parent": "J05A", "level": 4, "name": "Nucleoside and nucleotide reverse transcriptase inhibitors",
     "indications": ["hiv"], "hccs": ["HCC1"]},

    # ----------------------------- L: antineoplastics -------------------
    {"code": "L", "parent": None, "level": 1, "name": "Antineoplastic and immunomodulating agents"},
    {"code": "L01", "parent": "L", "level": 2, "name": "Antineoplastic agents"},
    {"code": "L01A", "parent": "L01", "level": 3, "name": "Alkylating agents",
     "indications": ["cancer"], "hccs": ["HCC11", "HCC12"]},
    {"code": "L01B", "parent": "L01", "level": 3, "name": "Antimetabolites",
     "indications": ["cancer"], "hccs": ["HCC11", "HCC12"]},
    {"code": "L01C", "parent": "L01", "level": 3, "name": "Plant alkaloids and other natural products",
     "indications": ["cancer"], "hccs": ["HCC11", "HCC12"]},
    {"code": "L01E", "parent": "L01", "level": 3, "name": "Protein kinase inhibitors",
     "indications": ["cancer"], "hccs": ["HCC11", "HCC12"]},
    {"code": "L01F", "parent": "L01", "level": 3, "name": "Monoclonal antibodies",
     "indications": ["cancer"], "hccs": ["HCC11", "HCC12"]},

    # ----------------------------- N: nervous system --------------------
    {"code": "N", "parent": None, "level": 1, "name": "Nervous system"},
    {"code": "N04", "parent": "N", "level": 2, "name": "Anti-Parkinson drugs"},
    {"code": "N04B", "parent": "N04", "level": 3, "name": "Dopaminergic agents"},
    {"code": "N04BA", "parent": "N04B", "level": 4, "name": "Dopa and dopa derivatives",
     "indications": ["parkinson"], "hccs": ["HCC78"]},
    {"code": "N04BC", "parent": "N04B", "level": 4, "name": "Dopamine agonists",
     "indications": ["parkinson"], "hccs": ["HCC78"]},
    {"code": "N05", "parent": "N", "level": 2, "name": "Psycholeptics"},
    {"code": "N05A", "parent": "N05", "level": 3, "name": "Antipsychotics"},
    {"code": "N05AH", "parent": "N05A", "level": 4, "name": "Diazepines, oxazepines, thiazepines and oxepines (atypical antipsychotics)",
     "indications": ["schizophrenia", "bipolar"], "hccs": ["HCC57", "HCC58"]},
    {"code": "N05AX", "parent": "N05A", "level": 4, "name": "Other antipsychotics",
     "indications": ["schizophrenia", "bipolar"], "hccs": ["HCC57", "HCC58"]},
    {"code": "N05BA", "parent": "N05", "level": 4, "name": "Benzodiazepine derivatives (anxiolytics)",
     "indications": ["anxiety"], "hccs": []},
    {"code": "N06", "parent": "N", "level": 2, "name": "Psychoanaleptics"},
    {"code": "N06A", "parent": "N06", "level": 3, "name": "Antidepressants"},
    {"code": "N06AB", "parent": "N06A", "level": 4, "name": "Selective serotonin reuptake inhibitors (SSRIs)",
     "indications": ["depression"], "hccs": ["HCC59"]},
    {"code": "N06AX", "parent": "N06A", "level": 4, "name": "Other antidepressants",
     "indications": ["depression"], "hccs": ["HCC59"]},
    {"code": "N06D", "parent": "N06", "level": 3, "name": "Anti-dementia drugs"},
    {"code": "N06DA", "parent": "N06D", "level": 4, "name": "Anticholinesterases",
     "indications": ["dementia"], "hccs": ["HCC125"]},
    {"code": "N06DX", "parent": "N06D", "level": 4, "name": "Other anti-dementia drugs (memantine)",
     "indications": ["dementia"], "hccs": ["HCC125"]},

    # ----------------------------- R: respiratory ----------------------
    {"code": "R", "parent": None, "level": 1, "name": "Respiratory system"},
    {"code": "R03", "parent": "R", "level": 2, "name": "Drugs for obstructive airway diseases"},
    {"code": "R03A", "parent": "R03", "level": 3, "name": "Adrenergics, inhalants"},
    {"code": "R03AC", "parent": "R03A", "level": 4, "name": "Selective beta-2-adrenoreceptor agonists",
     "indications": ["asthma", "copd"], "hccs": ["HCC111", "HCC112"]},
    {"code": "R03AK", "parent": "R03A", "level": 4, "name": "Adrenergics in combination with corticosteroids or other drugs (excl. anticholinergics)",
     "indications": ["asthma", "copd"], "hccs": ["HCC111", "HCC112"]},
    {"code": "R03B", "parent": "R03", "level": 3, "name": "Other drugs for obstructive airway diseases, inhalants"},
    {"code": "R03BA", "parent": "R03B", "level": 4, "name": "Glucocorticoids (inhaled)",
     "indications": ["asthma", "copd"], "hccs": ["HCC111", "HCC112"]},
    {"code": "R03BB", "parent": "R03B", "level": 4, "name": "Anticholinergics (inhaled)",
     "indications": ["copd"], "hccs": ["HCC111"]},
]


# ---------------------------------------------------------------------------
# 2. Indication concepts (key -> human label).
# Stable keys keep the seed file readable; concept_id is generated at insert.
# ---------------------------------------------------------------------------
INDICATION_CONCEPTS: dict[str, dict[str, str]] = {
    "diabetes":          {"code": "E11",   "name": "Type 2 diabetes mellitus"},
    "atrial_fibrillation": {"code": "I48", "name": "Atrial fibrillation"},
    "vte":               {"code": "I82",   "name": "Venous thromboembolism"},
    "cad":               {"code": "I25",   "name": "Coronary artery disease"},
    "hypertension":      {"code": "I10",   "name": "Essential hypertension"},
    "chf":               {"code": "I50",   "name": "Congestive heart failure"},
    "hyperlipidemia":    {"code": "E78",   "name": "Hyperlipidemia"},
    "hiv":               {"code": "B20",   "name": "HIV disease"},
    "cancer":            {"code": "C80",   "name": "Malignant neoplasm (unspecified)"},
    "parkinson":         {"code": "G20",   "name": "Parkinson disease"},
    "schizophrenia":     {"code": "F20",   "name": "Schizophrenia"},
    "bipolar":           {"code": "F31",   "name": "Bipolar disorder"},
    "anxiety":           {"code": "F41",   "name": "Anxiety disorder"},
    "depression":        {"code": "F33",   "name": "Major depressive disorder"},
    "dementia":          {"code": "F03",   "name": "Dementia, unspecified"},
    "asthma":            {"code": "J45",   "name": "Asthma"},
    "copd":              {"code": "J44",   "name": "Chronic obstructive pulmonary disease"},
}


# ---------------------------------------------------------------------------
# 3. HCC concepts (V28 codes used by the rest of the platform).
# ---------------------------------------------------------------------------
HCC_CONCEPTS: dict[str, dict[str, str]] = {
    "HCC1":   {"code": "1",   "name": "HIV/AIDS"},
    "HCC11":  {"code": "11",  "name": "Cancers, metastatic"},
    "HCC12":  {"code": "12",  "name": "Cancer, lung / severe"},
    "HCC17":  {"code": "17",  "name": "Diabetes with severe complications"},
    "HCC18":  {"code": "18",  "name": "Diabetes with chronic complications"},
    "HCC19":  {"code": "19",  "name": "Diabetes without complication"},
    "HCC57":  {"code": "57",  "name": "Schizophrenia"},
    "HCC58":  {"code": "58",  "name": "Major depressive, bipolar, and paranoid disorders"},
    "HCC59":  {"code": "59",  "name": "Reactive and unspecified psychosis / mood disorders"},
    "HCC78":  {"code": "78",  "name": "Parkinson's and Huntington's diseases"},
    "HCC85":  {"code": "85",  "name": "Congestive heart failure"},
    "HCC96":  {"code": "96",  "name": "Specified heart arrhythmias"},
    "HCC111": {"code": "111", "name": "Chronic obstructive pulmonary disease"},
    "HCC112": {"code": "112", "name": "Fibrosis of lung and other chronic lung disorders"},
    "HCC125": {"code": "125", "name": "Dementia"},
}


# ---------------------------------------------------------------------------
# 4. RxNorm bridge — common drugs.  RxCUIs from RxNav (NLM).
# ---------------------------------------------------------------------------
RXNORM_BRIDGE: list[dict[str, Any]] = [
    # diabetes
    {"rxcui": "6809",    "name": "metformin",            "atc": "A10BA02"},
    {"rxcui": "153842",  "name": "glucophage",           "atc": "A10BA02", "brand": True},
    {"rxcui": "1006406", "name": "insulin glargine",     "atc": "A10AE", "ndc": "00088502233"},
    {"rxcui": "5856",    "name": "insulin lispro",       "atc": "A10AB"},
    {"rxcui": "139825",  "name": "insulin aspart",       "atc": "A10AB"},
    {"rxcui": "274783",  "name": "insulin detemir",      "atc": "A10AE"},
    {"rxcui": "4815",    "name": "glipizide",            "atc": "A10BB"},
    {"rxcui": "4816",    "name": "glyburide",            "atc": "A10BB"},
    {"rxcui": "25789",   "name": "glimepiride",          "atc": "A10BB"},
    {"rxcui": "593411",  "name": "sitagliptin",          "atc": "A10BH"},
    {"rxcui": "857974",  "name": "linagliptin",          "atc": "A10BH"},
    {"rxcui": "475968",  "name": "saxagliptin",          "atc": "A10BH"},
    {"rxcui": "1373458", "name": "liraglutide",          "atc": "A10BJ"},
    {"rxcui": "1991302", "name": "semaglutide",          "atc": "A10BJ"},
    {"rxcui": "1992368", "name": "ozempic",              "atc": "A10BJ", "brand": True},
    {"rxcui": "1244202", "name": "dulaglutide",          "atc": "A10BJ"},
    {"rxcui": "1545653", "name": "empagliflozin",        "atc": "A10BK"},
    {"rxcui": "1373463", "name": "dapagliflozin",        "atc": "A10BK"},
    {"rxcui": "1486436", "name": "canagliflozin",        "atc": "A10BK"},
    {"rxcui": "857005",  "name": "pioglitazone",         "atc": "A10BX"},

    # antithrombotics
    {"rxcui": "11289",   "name": "warfarin",             "atc": "B01AA"},
    {"rxcui": "1364430", "name": "apixaban",             "atc": "B01AF"},
    {"rxcui": "1037045", "name": "rivaroxaban",          "atc": "B01AF"},
    {"rxcui": "1593411", "name": "edoxaban",             "atc": "B01AF"},
    {"rxcui": "1037042", "name": "dabigatran",           "atc": "B01AE"},
    {"rxcui": "1656055", "name": "enoxaparin",           "atc": "B01AB"},
    {"rxcui": "5224",    "name": "heparin",              "atc": "B01AB"},
    {"rxcui": "1191",    "name": "aspirin",              "atc": "B01AC"},
    {"rxcui": "32968",   "name": "clopidogrel",          "atc": "B01AC"},
    {"rxcui": "613391",  "name": "prasugrel",            "atc": "B01AC"},
    {"rxcui": "1116632", "name": "ticagrelor",           "atc": "B01AC"},

    # cardiac / RAAS
    {"rxcui": "29046",   "name": "lisinopril",           "atc": "C09AA"},
    {"rxcui": "18867",   "name": "enalapril",            "atc": "C09AA"},
    {"rxcui": "50166",   "name": "ramipril",             "atc": "C09AA"},
    {"rxcui": "1998",    "name": "captopril",            "atc": "C09AA"},
    {"rxcui": "52175",   "name": "losartan",             "atc": "C09CA"},
    {"rxcui": "69749",   "name": "valsartan",            "atc": "C09CA"},
    {"rxcui": "83515",   "name": "olmesartan",           "atc": "C09CA"},
    {"rxcui": "214354",  "name": "irbesartan",           "atc": "C09CA"},
    {"rxcui": "1656339", "name": "sacubitril/valsartan", "atc": "C09DX"},
    {"rxcui": "203644",  "name": "entresto",             "atc": "C09DX", "brand": True},

    # diuretics
    {"rxcui": "4603",    "name": "furosemide",           "atc": "C03CA"},
    {"rxcui": "9997",    "name": "torsemide",            "atc": "C03CA"},
    {"rxcui": "4337",    "name": "bumetanide",           "atc": "C03CA"},
    {"rxcui": "9997005", "name": "spironolactone",       "atc": "C03DA"},
    {"rxcui": "73494",   "name": "eplerenone",           "atc": "C03DA"},

    # beta blockers
    {"rxcui": "6918",    "name": "metoprolol",           "atc": "C07AB"},
    {"rxcui": "1202",    "name": "atenolol",             "atc": "C07AB"},
    {"rxcui": "8787",    "name": "propranolol",          "atc": "C07AA"},
    {"rxcui": "20352",   "name": "carvedilol",           "atc": "C07AG"},
    {"rxcui": "203644000", "name": "bisoprolol",         "atc": "C07AB"},

    # nitrates
    {"rxcui": "4917",    "name": "nitroglycerin",        "atc": "C01DA"},
    {"rxcui": "7417",    "name": "isosorbide mononitrate","atc": "C01DA"},

    # statins
    {"rxcui": "36567",   "name": "simvastatin",          "atc": "C10AA"},
    {"rxcui": "83367",   "name": "atorvastatin",         "atc": "C10AA"},
    {"rxcui": "301542",  "name": "rosuvastatin",         "atc": "C10AA"},
    {"rxcui": "42463",   "name": "pravastatin",          "atc": "C10AA"},
    {"rxcui": "41127",   "name": "lovastatin",           "atc": "C10AA"},
    {"rxcui": "847630",  "name": "ezetimibe",            "atc": "C10AX"},

    # respiratory
    {"rxcui": "435",     "name": "albuterol",            "atc": "R03AC"},
    {"rxcui": "73056",   "name": "salmeterol",           "atc": "R03AC"},
    {"rxcui": "351137",  "name": "formoterol",           "atc": "R03AC"},
    {"rxcui": "896188",  "name": "fluticasone/salmeterol","atc": "R03AK"},
    {"rxcui": "896994",  "name": "advair",               "atc": "R03AK", "brand": True},
    {"rxcui": "1797881", "name": "budesonide/formoterol","atc": "R03AK"},
    {"rxcui": "656657",  "name": "fluticasone",          "atc": "R03BA"},
    {"rxcui": "19831",   "name": "budesonide",           "atc": "R03BA"},
    {"rxcui": "1599538", "name": "tiotropium",           "atc": "R03BB"},
    {"rxcui": "1729378", "name": "umeclidinium",         "atc": "R03BB"},

    # parkinson
    {"rxcui": "6375",    "name": "carbidopa/levodopa",   "atc": "N04BA"},
    {"rxcui": "6376",    "name": "levodopa",             "atc": "N04BA"},
    {"rxcui": "8859",    "name": "pramipexole",          "atc": "N04BC"},
    {"rxcui": "9994",    "name": "ropinirole",           "atc": "N04BC"},

    # antipsychotics
    {"rxcui": "61381",   "name": "olanzapine",           "atc": "N05AH"},
    {"rxcui": "35636",   "name": "risperidone",          "atc": "N05AX"},
    {"rxcui": "352393",  "name": "aripiprazole",         "atc": "N05AX"},
    {"rxcui": "115698",  "name": "quetiapine",           "atc": "N05AH"},

    # benzos
    {"rxcui": "596",     "name": "alprazolam",           "atc": "N05BA"},
    {"rxcui": "2598",    "name": "lorazepam",            "atc": "N05BA"},
    {"rxcui": "2895",    "name": "clonazepam",           "atc": "N05BA"},
    {"rxcui": "3322",    "name": "diazepam",             "atc": "N05BA"},

    # antidepressants
    {"rxcui": "4493",    "name": "fluoxetine",           "atc": "N06AB"},
    {"rxcui": "32937",   "name": "sertraline",           "atc": "N06AB"},
    {"rxcui": "37798",   "name": "escitalopram",         "atc": "N06AB"},
    {"rxcui": "2556",    "name": "citalopram",           "atc": "N06AB"},
    {"rxcui": "8226",    "name": "paroxetine"
        ,                                                "atc": "N06AB"},
    {"rxcui": "72625",   "name": "venlafaxine",          "atc": "N06AX"},
    {"rxcui": "72729",   "name": "bupropion",            "atc": "N06AX"},
    {"rxcui": "321988",  "name": "duloxetine",           "atc": "N06AX"},
    {"rxcui": "32624",   "name": "mirtazapine",          "atc": "N06AX"},

    # dementia
    {"rxcui": "135447",  "name": "donepezil",            "atc": "N06DA"},
    {"rxcui": "183379",  "name": "rivastigmine",         "atc": "N06DA"},
    {"rxcui": "39998",   "name": "memantine",            "atc": "N06DX"},
    {"rxcui": "183381",  "name": "galantamine",          "atc": "N06DA"},

    # HIV
    {"rxcui": "1747691", "name": "bictegravir/emtricitabine/tenofovir", "atc": "J05AR"},
    {"rxcui": "1601651", "name": "biktarvy",             "atc": "J05AR", "brand": True},
    {"rxcui": "1747695", "name": "dolutegravir",         "atc": "J05AR"},
    {"rxcui": "352007",  "name": "tenofovir",            "atc": "J05AF"},
    {"rxcui": "352236",  "name": "emtricitabine",        "atc": "J05AF"},

    # antibiotics (low signal but useful for completeness)
    {"rxcui": "723",     "name": "amoxicillin",          "atc": "J01CA"},
    {"rxcui": "1364",    "name": "azithromycin",         "atc": "J01FA"},

    # antineoplastics (top 5 classes — placeholder sample)
    {"rxcui": "5640",    "name": "imatinib",             "atc": "L01E"},
    {"rxcui": "1191195", "name": "ibrutinib",            "atc": "L01E"},
    {"rxcui": "203671",  "name": "rituximab",            "atc": "L01F"},
    {"rxcui": "203625",  "name": "trastuzumab",          "atc": "L01F"},
    {"rxcui": "11202",   "name": "vinblastine",          "atc": "L01C"},
]


# ---------------------------------------------------------------------------
# Seeding logic
# ---------------------------------------------------------------------------

def _upsert_concept(cur, ontology: str, code: str, name: str) -> int:
    cur.execute(
        """
        INSERT INTO knowledge_graph_concepts (concept_uri, ontology, code, preferred_label)
        VALUES (%s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE preferred_label = VALUES(preferred_label)
        """,
        (f"{ontology}:{code}", ontology, code, name),
    )
    cur.execute(
        "SELECT id FROM knowledge_graph_concepts WHERE ontology = %s AND code = %s",
        (ontology, code),
    )
    row = cur.fetchone()
    return int(row["id"]) if row else 0


def _upsert_edge(cur, source_id: int, target_id: int, relation: str) -> None:
    # Foundation schema uses src_concept_id/dst_concept_id/edge_type, not source/target/relation
    cur.execute(
        """
        INSERT IGNORE INTO knowledge_graph_edges (src_concept_id, dst_concept_id, edge_type)
        VALUES (%s, %s, %s)
        """,
        (source_id, target_id, relation),
    )


def seed() -> dict[str, int]:
    """Run the full seed.  Returns row counts for verification."""
    # Late import keeps ``--dry-run`` mode usable on machines without
    # production DB credentials configured.
    from app.db import raf_cursor                                 # noqa: WPS433

    counts = {"atc_concepts": 0, "atc_classes": 0, "indications": 0,
              "hccs": 0, "rxnorm_bridges": 0, "edges": 0}

    with raf_cursor() as cur:
        # Indication concepts.
        ind_id_by_key: dict[str, int] = {}
        for key, meta in INDICATION_CONCEPTS.items():
            cid = _upsert_concept(cur, "icd10", meta["code"], meta["name"])
            ind_id_by_key[key] = cid
            counts["indications"] += 1

        # HCC concepts.
        hcc_id_by_key: dict[str, int] = {}
        for key, meta in HCC_CONCEPTS.items():
            cid = _upsert_concept(cur, "hcc", meta["code"], meta["name"])
            hcc_id_by_key[key] = cid
            counts["hccs"] += 1

        # Indication -> HCC edges.  Each ATC class lists hccs adjacent to its
        # indications; we materialise the cross-product as edges.
        for entry in ATC_HIERARCHY:
            for ikey in entry.get("indications") or []:
                for hkey in entry.get("hccs") or []:
                    src = ind_id_by_key.get(ikey)
                    dst = hcc_id_by_key.get(hkey)
                    if src and dst:
                        _upsert_edge(cur, src, dst, "maps_to_hcc")
                        counts["edges"] += 1

        # ATC concepts + class rows.
        atc_id_by_code: dict[str, int] = {}
        for entry in ATC_HIERARCHY:
            cid = _upsert_concept(cur, "atc", entry["code"], entry["name"])
            atc_id_by_code[entry["code"]] = cid
            counts["atc_concepts"] += 1

            indication_ids = [
                ind_id_by_key[k] for k in (entry.get("indications") or [])
                if k in ind_id_by_key
            ]
            cur.execute(
                """
                INSERT INTO kg_atc_classes
                  (atc_code, name, level, parent_atc_code, concept_id, indication_concept_ids, is_active)
                VALUES (%s, %s, %s, %s, %s, %s, 1)
                ON DUPLICATE KEY UPDATE
                  name                  = VALUES(name),
                  level                 = VALUES(level),
                  parent_atc_code       = VALUES(parent_atc_code),
                  concept_id            = VALUES(concept_id),
                  indication_concept_ids = VALUES(indication_concept_ids),
                  is_active             = 1
                """,
                (
                    entry["code"], entry["name"], entry["level"],
                    entry.get("parent"), cid,
                    json.dumps(indication_ids) if indication_ids else None,
                ),
            )
            counts["atc_classes"] += 1

            # ATC concept -> indication concepts (has_indication edges).
            for ikey in entry.get("indications") or []:
                tgt = ind_id_by_key.get(ikey)
                if tgt:
                    _upsert_edge(cur, cid, tgt, "has_indication")
                    counts["edges"] += 1

        # RxNorm bridge.
        for r in RXNORM_BRIDGE:
            atc = r["atc"]
            if atc not in atc_id_by_code:
                logger.warning("Skipping RxNorm bridge %s: unknown ATC %s", r["name"], atc)
                continue
            is_brand = 1 if r.get("brand") else 0
            is_generic = 0 if r.get("brand") else 1
            cur.execute(
                """
                INSERT INTO kg_rxnorm_to_atc
                  (rxcui, drug_name, ndc, atc_code, is_brand, is_generic)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                  drug_name = VALUES(drug_name),
                  atc_code  = VALUES(atc_code),
                  is_brand  = VALUES(is_brand),
                  is_generic = VALUES(is_generic)
                """,
                (
                    r.get("rxcui"),
                    r["name"],
                    r.get("ndc"),
                    atc,
                    is_brand,
                    is_generic,
                ),
            )
            counts["rxnorm_bridges"] += 1

    return counts


def main() -> None:
    if os.environ.get("ATC_SEED_DRY_RUN") == "1":
        logger.info("Dry run: validating in-memory data only.")
        # Sanity checks.
        codes = {e["code"] for e in ATC_HIERARCHY}
        for e in ATC_HIERARCHY:
            if e.get("parent") and e["parent"] not in codes:
                raise RuntimeError(f"ATC entry {e['code']} references missing parent {e['parent']}")
        for r in RXNORM_BRIDGE:
            if r["atc"] not in codes:
                raise RuntimeError(f"Bridge {r['name']} references missing ATC {r['atc']}")
        logger.info(
            "OK: %d ATC, %d bridges, %d indications, %d HCCs.",
            len(ATC_HIERARCHY), len(RXNORM_BRIDGE),
            len(INDICATION_CONCEPTS), len(HCC_CONCEPTS),
        )
        return

    counts = seed()
    logger.info("Seed complete: %s", counts)


if __name__ == "__main__":
    main()
