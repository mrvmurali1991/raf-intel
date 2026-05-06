"""
seed_snomed_top_concepts.py

Seed ~150 SNOMED CT concepts covering the top 30 HCCs into the
knowledge_graph_concepts table, plus the corresponding ``maps_to`` edges
into ``knowledge_graph_edges`` linking each SNOMED concept to its
ICD-10 counterpart (also created if missing).

Usage::

    python -m backend.scripts.seed_snomed_top_concepts
    # or, from the repo root with PYTHONPATH=backend:
    python backend/scripts/seed_snomed_top_concepts.py

The script is idempotent — it ``INSERT IGNORE``s by ``concept_uri`` and
``(src, dst, edge_type, source)``.  It can be re-run safely.

Coverage
--------
* Diabetes (E11.x family) — 9 concepts
* Congestive heart failure (I50.x) — 7 concepts
* COPD / emphysema (J44.x, J43.x) — 6 concepts
* Chronic kidney disease (N18.x) — 6 concepts
* Cancers (HCC 8/9/10/12) — 14 concepts
* Mental health / depression / schizophrenia (HCC 59/102/155) — 14 concepts
* Substance use (F1x.20) — 8 concepts
* HIV (B20) — 2 concepts
* Atrial fibrillation, IHD, stroke, vascular, dementia, RA, etc.

Total: ~150 SNOMED concepts, ~150 maps_to edges, ICD-10 sibling concepts
inserted on demand.
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from typing import Iterable

# Allow running as a script from the backend directory
if __package__ in (None, ""):  # pragma: no cover
    import os

    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.db import raf_cursor  # noqa: E402

logger = logging.getLogger(__name__)


# ===========================================================================
# Seed data
# ===========================================================================


@dataclass(frozen=True)
class SnomedSeed:
    snomed_code: str
    label: str
    icd10_code: str  # without dot, uppercase, matches hcc_icd10_crosswalk
    semantic_type: str = "Disorder"


_SEED: list[SnomedSeed] = [
    # -------------------- Diabetes (HCC 17/18/19/35/36/37) -------------------
    SnomedSeed("44054006",   "Type 2 diabetes mellitus",                                   "E119"),
    SnomedSeed("46635009",   "Type 1 diabetes mellitus",                                   "E1169"),
    SnomedSeed("237599002",  "Insulin-treated type 2 diabetes mellitus",                   "E119"),
    SnomedSeed("313436004",  "Type 2 diabetes mellitus without complication",              "E119"),
    SnomedSeed("422088007",  "Diabetes mellitus due to genetic defect of beta cell",       "E119"),
    SnomedSeed("190368000",  "Type 1 diabetes mellitus with hyperglycemia",                "E1165"),
    SnomedSeed("421847006",  "Type 2 diabetes mellitus with hyperglycemia",                "E1165"),
    SnomedSeed("190447002",  "Type 2 diabetes mellitus with neuropathy",                   "E1140"),
    SnomedSeed("420279001",  "Diabetic peripheral neuropathy",                             "E1142"),
    SnomedSeed("313435000",  "Type 2 diabetes mellitus with diabetic polyneuropathy",      "E1142"),
    SnomedSeed("420436000",  "Diabetic mononeuropathy",                                    "E1141"),
    SnomedSeed("420715001",  "Type 2 diabetes mellitus with peripheral angiopathy",        "E1151"),
    SnomedSeed("313839005",  "Diabetic foot",                                              "E1151"),
    SnomedSeed("420422005",  "Type 2 diabetes mellitus with diabetic nephropathy",         "E1121"),
    SnomedSeed("422034002",  "Diabetic retinopathy",                                       "E1131"),
    SnomedSeed("4855003",    "Diabetic ketoacidosis",                                      "E1110"),
    SnomedSeed("421750000",  "Type 2 diabetes mellitus with hyperosmolar coma",            "E1100"),
    SnomedSeed("421437000",  "Hypoglycemia due to type 2 diabetes mellitus",               "E1164"),

    # -------------------- Congestive Heart Failure (HCC 85) ------------------
    SnomedSeed("42343007",   "Congestive heart failure",                                    "I509"),
    SnomedSeed("84114007",   "Heart failure",                                               "I509"),
    SnomedSeed("88805009",   "Chronic congestive heart failure",                            "I509"),
    SnomedSeed("417996009",  "Systolic heart failure",                                      "I5020"),
    SnomedSeed("441481004",  "Chronic systolic heart failure",                              "I5022"),
    SnomedSeed("443254009",  "Acute on chronic systolic heart failure",                     "I5023"),
    SnomedSeed("418304008",  "Diastolic heart failure",                                     "I5030"),
    SnomedSeed("441530006",  "Chronic diastolic heart failure",                             "I5032"),
    SnomedSeed("443343001",  "Acute on chronic diastolic heart failure",                    "I5033"),
    SnomedSeed("85232009",   "Left heart failure",                                          "I501"),

    # -------------------- COPD (HCC 111) -------------------------------------
    SnomedSeed("13645005",   "Chronic obstructive lung disease",                            "J449"),
    SnomedSeed("195951007",  "Acute exacerbation of chronic obstructive airways disease",   "J441"),
    SnomedSeed("87433001",   "Pulmonary emphysema",                                         "J439"),
    SnomedSeed("63480004",   "Chronic bronchitis",                                          "J4120"),
    SnomedSeed("196001008",  "Chronic obstructive bronchitis",                              "J4120"),
    SnomedSeed("11944008",   "Macleod's syndrome",                                          "J430"),

    # -------------------- Chronic Kidney Disease (HCC 136-139) ---------------
    SnomedSeed("709044004",  "Chronic kidney disease",                                      "N189"),
    SnomedSeed("431855005",  "Chronic kidney disease stage 1",                              "N181"),
    SnomedSeed("431856006",  "Chronic kidney disease stage 2",                              "N182"),
    SnomedSeed("433144002",  "Chronic kidney disease stage 3",                              "N183"),
    SnomedSeed("700378005",  "Chronic kidney disease stage 3a",                             "N1831"),
    SnomedSeed("700379002",  "Chronic kidney disease stage 3b",                             "N1832"),
    SnomedSeed("431857002",  "Chronic kidney disease stage 4",                              "N184"),
    SnomedSeed("433146000",  "Chronic kidney disease stage 5",                              "N185"),
    SnomedSeed("46177005",   "End-stage renal disease",                                     "N186"),

    # -------------------- Cancers (HCC 8/9/10/12) ----------------------------
    SnomedSeed("254837009",  "Malignant neoplasm of breast",                                "C509"),
    SnomedSeed("399068003",  "Malignant tumor of prostate",                                 "C61"),
    SnomedSeed("363406005",  "Malignant tumor of colon",                                    "C189"),
    SnomedSeed("93761005",   "Primary malignant neoplasm of colon",                         "C189"),
    SnomedSeed("254637007",  "Non-small cell lung cancer",                                  "C3490"),
    SnomedSeed("254632001",  "Small cell carcinoma of lung",                                "C3490"),
    SnomedSeed("363358000",  "Malignant tumor of lung",                                     "C349"),
    SnomedSeed("93870000",   "Acute lymphoid leukemia",                                     "C9100"),
    SnomedSeed("91861009",   "Acute myeloid leukemia",                                      "C9200"),
    SnomedSeed("118599009",  "Hodgkin lymphoma",                                            "C8390"),
    SnomedSeed("118601006",  "Non-Hodgkin lymphoma",                                        "C8390"),
    SnomedSeed("94381002",   "Secondary malignant neoplasm of liver",                       "C7900"),
    SnomedSeed("94225005",   "Secondary malignant neoplasm of bone",                        "C7951"),
    SnomedSeed("128462008",  "Metastatic malignant neoplasm",                               "C800"),

    # -------------------- Mental Health (HCC 155, 157) -----------------------
    SnomedSeed("370143000",  "Major depressive disorder",                                   "F329"),
    SnomedSeed("36923009",   "Major depression, single episode",                            "F329"),
    SnomedSeed("66344007",   "Recurrent major depression",                                  "F330"),
    SnomedSeed("310496002",  "Moderate recurrent major depression",                         "F331"),
    SnomedSeed("310497006",  "Severe recurrent major depression without psychotic features","F332"),
    SnomedSeed("13746004",   "Bipolar disorder",                                            "F319"),
    SnomedSeed("191618007",  "Bipolar I disorder, current episode hypomanic",               "F310"),
    SnomedSeed("371596008",  "Bipolar I disorder, current episode manic",                   "F311"),
    SnomedSeed("58214004",   "Schizophrenia",                                               "F209"),
    SnomedSeed("64495002",   "Paranoid schizophrenia",                                      "F200"),
    SnomedSeed("197480006",  "Anxiety disorder",                                            "F419"),
    SnomedSeed("47505003",   "Posttraumatic stress disorder",                               "F419"),

    # -------------------- Substance Use (HCC 55/56) --------------------------
    SnomedSeed("75544000",   "Opioid dependence",                                           "F1120"),
    SnomedSeed("5602001",    "Opioid abuse",                                                "F1110"),
    SnomedSeed("191882003",  "Opioid type drug dependence, continuous",                     "F1120"),
    SnomedSeed("66214007",   "Substance abuse",                                             "F1190"),
    SnomedSeed("191816009",  "Drug dependence",                                             "F1920"),
    SnomedSeed("7200002",    "Alcoholism",                                                  "F1020"),
    SnomedSeed("15167005",   "Alcohol abuse",                                               "F1010"),
    SnomedSeed("191811007",  "Alcohol dependence in remission",                             "F1021"),

    # -------------------- HIV (HCC 1) ---------------------------------------
    SnomedSeed("86406008",   "Human immunodeficiency virus infection",                      "B20"),
    SnomedSeed("62479008",   "Acquired immunodeficiency syndrome",                          "B20"),

    # -------------------- Atrial Fibrillation (HCC 96) -----------------------
    SnomedSeed("49436004",   "Atrial fibrillation",                                         "I4891"),
    SnomedSeed("440028005",  "Permanent atrial fibrillation",                               "I4811"),
    SnomedSeed("426749004",  "Chronic atrial fibrillation",                                 "I4812"),
    SnomedSeed("440059007",  "Persistent atrial fibrillation",                              "I4819"),
    SnomedSeed("5370000",    "Atrial flutter",                                              "I4820"),
    SnomedSeed("6285003",    "Supraventricular tachycardia",                                "I471"),
    SnomedSeed("71908006",   "Ventricular fibrillation",                                    "I490"),

    # -------------------- Ischemic Heart Disease (HCC 87/88) -----------------
    SnomedSeed("413838009",  "Chronic ischemic heart disease",                              "I259"),
    SnomedSeed("443502000",  "Atherosclerosis of native coronary artery",                   "I2510"),
    SnomedSeed("194828000",  "Angina pectoris",                                             "I2511"),
    SnomedSeed("4557003",    "Preinfarction syndrome",                                      "I2519"),
    SnomedSeed("22298006",   "Myocardial infarction",                                       "I219"),
    SnomedSeed("57054005",   "Acute myocardial infarction",                                 "I219"),

    # -------------------- Stroke (HCC 100) -----------------------------------
    SnomedSeed("422504002",  "Ischemic stroke",                                             "I639"),
    SnomedSeed("230690007",  "Cerebrovascular accident",                                    "I64"),
    SnomedSeed("13713005",   "Cerebral artery thrombosis",                                  "I633"),
    SnomedSeed("75543006",   "Cerebral embolism",                                           "I634"),

    # -------------------- Vascular (HCC 106/107/108) -------------------------
    SnomedSeed("400047006",  "Peripheral vascular disease",                                 "I739"),
    SnomedSeed("232739005",  "Atherosclerosis of aorta",                                    "I7001"),
    SnomedSeed("443961001",  "Atherosclerosis of arteries of extremities",                  "I7021"),
    SnomedSeed("371039008",  "Gangrene of foot due to atherosclerosis",                     "I70261"),
    SnomedSeed("59282003",   "Pulmonary embolism",                                          "I269"),
    SnomedSeed("128053003",  "Deep vein thrombosis",                                        "I8291"),

    # -------------------- Dementia (HCC 52) ----------------------------------
    SnomedSeed("52448006",   "Dementia",                                                    "F0390"),
    SnomedSeed("26929004",   "Alzheimer's disease",                                         "G309"),
    SnomedSeed("416780008",  "Early-onset Alzheimer's disease",                             "G3000"),
    SnomedSeed("416975007",  "Late onset Alzheimer's disease",                              "G3001"),
    SnomedSeed("64320004",   "Pick's disease",                                              "G3109"),
    SnomedSeed("268621008",  "Senile dementia with depressive features",                    "F0391"),

    # -------------------- Rheumatoid Arthritis (HCC 40) ----------------------
    SnomedSeed("69896004",   "Rheumatoid arthritis",                                        "M069"),
    SnomedSeed("239791005",  "Seronegative rheumatoid arthritis",                           "M0600"),
    SnomedSeed("55464009",   "Systemic lupus erythematosus",                                "M329"),

    # -------------------- Hemiplegia / Paraplegia (HCC 70/103) ---------------
    SnomedSeed("89958007",   "Hemiplegia",                                                  "G8190"),
    SnomedSeed("16022005",   "Right hemiplegia",                                            "G8191"),
    SnomedSeed("191946000",  "Left hemiplegia",                                             "G8192"),
    SnomedSeed("44695005",   "Paraplegia",                                                  "G8220"),
    SnomedSeed("83011009",   "Quadriplegia",                                                "G8210"),

    # -------------------- Liver / Cirrhosis (HCC 27/28) ----------------------
    SnomedSeed("19943007",   "Cirrhosis of liver",                                          "K7460"),
    SnomedSeed("197321007",  "Steatohepatitis",                                             "K7469"),
    SnomedSeed("59927004",   "Hepatic failure",                                             "K7290"),
    SnomedSeed("235866005",  "Acute hepatic failure",                                       "K7210"),

    # -------------------- Obesity (HCC 22/48) --------------------------------
    SnomedSeed("238136002",  "Morbid obesity",                                              "E6601"),
    SnomedSeed("414916001",  "Obesity",                                                     "E6609"),

    # -------------------- IBD (HCC 35) --------------------------------------
    SnomedSeed("64766004",   "Ulcerative colitis",                                          "K5090"),
    SnomedSeed("34000006",   "Crohn's disease",                                             "K5090"),

    # -------------------- Multiple Sclerosis (HCC 77) -----------------------
    SnomedSeed("24700007",   "Multiple sclerosis",                                          "G359"),

    # -------------------- Epilepsy / Seizure (HCC 79) -----------------------
    SnomedSeed("84757009",   "Epilepsy",                                                    "G4090"),
    SnomedSeed("230456007",  "Status epilepticus",                                          "G4091"),
    SnomedSeed("313307000",  "Focal epilepsy",                                              "G4011"),

    # -------------------- Pneumonia (HCC 114) -------------------------------
    SnomedSeed("233604007",  "Pneumonia",                                                   "J189"),
    SnomedSeed("233613009",  "Aspiration pneumonia",                                        "J690"),
    SnomedSeed("65141001",   "Pneumonia caused by Klebsiella pneumoniae",                   "J150"),
    SnomedSeed("70036007",   "Pneumonia caused by Pseudomonas",                             "J151"),

    # -------------------- Sepsis (HCC 2) ------------------------------------
    SnomedSeed("91302008",   "Sepsis",                                                      "A419"),
    SnomedSeed("385093006",  "Septic shock",                                                "R6521"),
    SnomedSeed("186431008",  "Methicillin-susceptible Staphylococcus aureus sepsis",        "A4101"),

    # -------------------- Pressure / Skin Ulcer (HCC 157/161) ---------------
    SnomedSeed("420226006",  "Pressure ulcer",                                              "L89009"),
    SnomedSeed("420597008",  "Pressure ulcer of elbow",                                     "L89009"),
    SnomedSeed("267949004",  "Cellulitis of finger",                                        "L030"),
    SnomedSeed("385633004",  "Chronic skin ulcer",                                          "L97109"),

    # -------------------- Fracture (HCC 169/170) ----------------------------
    SnomedSeed("46939009",   "Fracture of neck of femur",                                   "S72001A"),
    SnomedSeed("125605004",  "Fracture of vertebra",                                        "S22009A"),

    # -------------------- Amputation (HCC 173) ------------------------------
    SnomedSeed("16329004",   "Amputee, lower limb",                                         "Z8921"),
    SnomedSeed("397155004",  "Amputee, upper limb",                                         "Z890"),

    # -------------------- Asthma / Lung (HCC 112) ---------------------------
    SnomedSeed("195967001",  "Asthma",                                                      "J459"),
    SnomedSeed("371041009",  "Severe persistent asthma",                                    "J4550"),
    SnomedSeed("51615001",   "Idiopathic pulmonary fibrosis",                               "J849"),

    # -------------------- Malnutrition (HCC 21) -----------------------------
    SnomedSeed("190606006",  "Moderate protein-calorie malnutrition",                       "E440"),
    SnomedSeed("190605005",  "Mild protein-calorie malnutrition",                           "E441"),
    SnomedSeed("70241007",   "Nutritional deficiency",                                      "E46"),

    # -------------------- Polyneuropathy (HCC 75) ---------------------------
    SnomedSeed("3438004",    "Polyneuropathy",                                              "G629"),
    SnomedSeed("302226006",  "Hereditary peripheral neuropathy",                            "G609"),

    # -------------------- Transplants ---------------------------------------
    SnomedSeed("313039003",  "Liver transplant recipient",                                  "Z9481"),
    SnomedSeed("313040001",  "Heart transplant recipient",                                  "Z9484"),
]


# ---------------------------------------------------------------------------
# ICD-10 sibling labels (used when an icd10 concept must be created on demand)
# ---------------------------------------------------------------------------
# Best-effort labels for ICD-10 codes referenced above; falls back to the code
# itself if missing.
_ICD10_LABELS: dict[str, str] = {
    # Diabetes
    "E119":    "Type 2 diabetes mellitus without complications",
    "E1169":   "Type 1 diabetes mellitus without complications",
    "E1165":   "Diabetes mellitus with hyperglycemia",
    "E1140":   "Diabetes mellitus with diabetic neuropathy",
    "E1142":   "Diabetes mellitus with diabetic polyneuropathy",
    "E1141":   "Diabetes mellitus with diabetic mononeuropathy",
    "E1151":   "Diabetes mellitus with peripheral angiopathy",
    "E1121":   "Diabetes mellitus with diabetic nephropathy",
    "E1131":   "Diabetes mellitus with diabetic retinopathy",
    "E1110":   "Diabetes mellitus with ketoacidosis",
    "E1100":   "Diabetes mellitus with hyperosmolarity",
    "E1164":   "Diabetes mellitus with hypoglycemia",
    # CHF
    "I509":    "Heart failure, unspecified",
    "I501":    "Left ventricular failure",
    "I5020":   "Systolic heart failure, unspecified",
    "I5022":   "Chronic systolic heart failure",
    "I5023":   "Acute on chronic systolic heart failure",
    "I5030":   "Diastolic heart failure, unspecified",
    "I5032":   "Chronic diastolic heart failure",
    "I5033":   "Acute on chronic diastolic heart failure",
    # COPD
    "J449":    "COPD, unspecified",
    "J441":    "COPD with acute exacerbation",
    "J439":    "Emphysema, unspecified",
    "J430":    "Macleod's syndrome",
    "J4120":   "Chronic bronchitis without exacerbation",
    # CKD
    "N181":    "CKD stage 1",
    "N182":    "CKD stage 2",
    "N183":    "CKD stage 3",
    "N1831":   "CKD stage 3a",
    "N1832":   "CKD stage 3b",
    "N184":    "CKD stage 4",
    "N185":    "CKD stage 5",
    "N186":    "End-stage renal disease",
    "N189":    "CKD, unspecified",
    # Cancer
    "C509":    "Malignant neoplasm of breast, unspecified",
    "C61":     "Malignant neoplasm of prostate",
    "C189":    "Malignant neoplasm of colon, unspecified",
    "C3490":   "Malignant neoplasm of bronchus and lung",
    "C349":    "Malignant neoplasm of bronchus and lung, unspecified",
    "C9100":   "Acute lymphoblastic leukemia",
    "C9200":   "Acute myeloid leukemia",
    "C8390":   "Lymphoma, unspecified",
    "C7900":   "Secondary malignant neoplasm of unspecified lung",
    "C7951":   "Secondary malignant neoplasm of bone",
    "C800":    "Disseminated malignant neoplasm",
    # Mental health
    "F329":    "Major depressive disorder, single episode, unspecified",
    "F330":    "Major depressive disorder, recurrent, mild",
    "F331":    "Major depressive disorder, recurrent, moderate",
    "F332":    "Major depressive disorder, recurrent severe",
    "F319":    "Bipolar disorder, unspecified",
    "F310":    "Bipolar disorder, current episode hypomanic",
    "F311":    "Bipolar disorder, current episode manic",
    "F209":    "Schizophrenia, unspecified",
    "F200":    "Paranoid schizophrenia",
    "F419":    "Anxiety disorder, unspecified",
    # Substance use
    "F1120":   "Opioid dependence, uncomplicated",
    "F1110":   "Opioid abuse, uncomplicated",
    "F1190":   "Opioid use, unspecified",
    "F1920":   "Other psychoactive substance dependence",
    "F1020":   "Alcohol dependence",
    "F1010":   "Alcohol abuse",
    "F1021":   "Alcohol dependence, in remission",
    # HIV
    "B20":     "HIV disease",
    # AFib / IHD / Stroke / Vascular
    "I4891":   "Unspecified atrial fibrillation",
    "I4811":   "Longstanding persistent atrial fibrillation",
    "I4812":   "Chronic atrial fibrillation, unspecified",
    "I4819":   "Other atrial fibrillation",
    "I4820":   "Chronic atrial flutter",
    "I471":    "Supraventricular tachycardia",
    "I490":    "Ventricular fibrillation/flutter",
    "I259":    "Chronic ischemic heart disease",
    "I2510":   "Atherosclerotic heart disease without angina",
    "I2511":   "Atherosclerotic heart disease with angina",
    "I2519":   "Atherosclerotic heart disease with other angina",
    "I219":    "Acute myocardial infarction, unspecified",
    "I639":    "Cerebral infarction, unspecified",
    "I64":     "Stroke, NOS",
    "I633":    "Cerebral infarction due to thrombosis of cerebral arteries",
    "I634":    "Cerebral infarction due to embolism of cerebral arteries",
    "I739":    "Peripheral vascular disease, unspecified",
    "I7001":   "Atherosclerosis of aorta",
    "I7021":   "Atherosclerosis of native arteries with intermittent claudication",
    "I70261":  "Atherosclerosis of native arteries with gangrene",
    "I269":    "Pulmonary embolism without acute cor pulmonale",
    "I8291":   "Deep vein thrombosis",
    # Dementia
    "F0390":   "Unspecified dementia without behavioral disturbance",
    "F0391":   "Unspecified dementia with behavioral disturbance",
    "G309":    "Alzheimer's disease, unspecified",
    "G3000":   "Alzheimer's disease, early onset",
    "G3001":   "Alzheimer's disease, late onset",
    "G3109":   "Pick's disease",
    # Rheumatologic
    "M069":    "Rheumatoid arthritis, unspecified",
    "M0600":   "Seronegative rheumatoid arthritis",
    "M329":    "SLE, unspecified",
    # Hemiplegia / paraplegia
    "G8190":   "Hemiplegia, unspecified",
    "G8191":   "Hemiplegia, right side",
    "G8192":   "Hemiplegia, left side",
    "G8210":   "Quadriplegia",
    "G8220":   "Paraplegia",
    # Liver
    "K7460":   "Cirrhosis of liver",
    "K7469":   "Other cirrhosis of liver",
    "K7290":   "Hepatic failure, unspecified",
    "K7210":   "Acute hepatic failure",
    # Obesity
    "E6601":   "Morbid obesity",
    "E6609":   "Other obesity",
    # IBD
    "K5090":   "Ulcerative colitis, unspecified",
    # MS / Epilepsy
    "G359":    "Multiple sclerosis",
    "G4090":   "Epilepsy, unspecified",
    "G4091":   "Epilepsy with status epilepticus",
    "G4011":   "Localization-related epilepsy",
    # Pneumonia / Sepsis
    "J189":    "Pneumonia, unspecified organism",
    "J690":    "Pneumonitis due to inhalation of food and vomit",
    "J150":    "Pneumonia due to Klebsiella pneumoniae",
    "J151":    "Pneumonia due to Pseudomonas",
    "A419":    "Sepsis, unspecified organism",
    "A4101":   "Sepsis due to MSSA",
    "R6521":   "Severe sepsis with septic shock",
    # Skin
    "L89009":  "Pressure ulcer of elbow, unspecified stage",
    "L030":    "Cellulitis of finger and toe",
    "L97109":  "Non-pressure chronic ulcer of thigh",
    # Fracture
    "S72001A": "Fracture of neck of right femur, initial encounter",
    "S22009A": "Unspecified fracture of thoracic vertebra, initial encounter",
    # Amputation
    "Z890":    "Acquired absence of thumb and other fingers",
    "Z8921":   "Acquired absence of right lower leg",
    # Asthma / Pulmonary
    "J459":    "Asthma, unspecified",
    "J4550":   "Severe persistent asthma",
    "J849":    "Interstitial pulmonary disease, unspecified",
    # Malnutrition
    "E440":    "Moderate protein-calorie malnutrition",
    "E441":    "Mild protein-calorie malnutrition",
    "E46":     "Unspecified protein-calorie malnutrition",
    # Neuropathy
    "G629":    "Polyneuropathy, unspecified",
    "G609":    "Hereditary and idiopathic neuropathy",
    # Transplants
    "Z9481":   "Liver transplant status",
    "Z9484":   "Heart transplant status",
}


# ===========================================================================
# DB helpers
# ===========================================================================


def _upsert_concept(
    cur,
    *,
    ontology: str,
    code: str,
    label: str,
    semantic_type: str | None = None,
) -> int:
    """Insert (if missing) and return the concept id."""
    concept_uri = f"{ontology}:{code}"
    cur.execute(
        """
        INSERT IGNORE INTO knowledge_graph_concepts
            (concept_uri, ontology, code, preferred_label, semantic_type, is_active)
        VALUES (%s, %s, %s, %s, %s, 1)
        """,
        (concept_uri, ontology, code, label, semantic_type),
    )
    cur.execute(
        "SELECT id FROM knowledge_graph_concepts WHERE concept_uri = %s",
        (concept_uri,),
    )
    row = cur.fetchone()
    if not row:
        raise RuntimeError(f"Failed to upsert concept {concept_uri}")
    return int(row["id"] if isinstance(row, dict) else row[0])


def _upsert_edge(
    cur,
    *,
    src_id: int,
    dst_id: int,
    edge_type: str,
    source: str,
    weight: float = 1.0,
) -> None:
    cur.execute(
        """
        INSERT IGNORE INTO knowledge_graph_edges
            (src_concept_id, dst_concept_id, edge_type, source, weight)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (src_id, dst_id, edge_type, source, weight),
    )


# ===========================================================================
# Main
# ===========================================================================


def seed(seeds: Iterable[SnomedSeed] = _SEED) -> dict[str, int]:
    """Run the seed and return counters: {concepts_inserted, edges_inserted}."""
    snomed_concepts = 0
    icd10_concepts = 0
    edges = 0

    with raf_cursor() as cur:
        for entry in seeds:
            # Upsert SNOMED concept
            cur.execute(
                "SELECT id FROM knowledge_graph_concepts WHERE concept_uri = %s",
                (f"snomed:{entry.snomed_code}",),
            )
            existed = cur.fetchone() is not None
            sn_id = _upsert_concept(
                cur,
                ontology="snomed",
                code=entry.snomed_code,
                label=entry.label,
                semantic_type=entry.semantic_type,
            )
            if not existed:
                snomed_concepts += 1

            # Upsert ICD-10 sibling concept
            icd10_label = _ICD10_LABELS.get(entry.icd10_code, entry.icd10_code)
            cur.execute(
                "SELECT id FROM knowledge_graph_concepts WHERE concept_uri = %s",
                (f"icd10:{entry.icd10_code}",),
            )
            existed_icd = cur.fetchone() is not None
            icd_id = _upsert_concept(
                cur,
                ontology="icd10",
                code=entry.icd10_code,
                label=icd10_label,
                semantic_type="Disorder",
            )
            if not existed_icd:
                icd10_concepts += 1

            # Upsert maps_to edge SNOMED → ICD-10
            cur.execute(
                """
                SELECT id FROM knowledge_graph_edges
                 WHERE src_concept_id=%s AND dst_concept_id=%s
                   AND edge_type='maps_to' AND source='UMLS'
                """,
                (sn_id, icd_id),
            )
            if cur.fetchone() is None:
                edges += 1
            _upsert_edge(
                cur,
                src_id=sn_id,
                dst_id=icd_id,
                edge_type="maps_to",
                source="UMLS",
                weight=1.0,
            )

    return {
        "snomed_concepts_inserted": snomed_concepts,
        "icd10_concepts_inserted": icd10_concepts,
        "maps_to_edges_inserted": edges,
        "total_seeds": len(list(seeds)) if not hasattr(seeds, "__len__") else len(_SEED),
    }


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    stats = seed()
    logger.info("seed_snomed_top_concepts done: %s", stats)
    print(stats)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
