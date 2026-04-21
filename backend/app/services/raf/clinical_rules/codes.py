"""Shared ICD-10-CM prefixes and Rx-class strings for clinical rules.

Every rule must import constants from this module instead of duplicating
them inline. Any change to these lists is a medically-significant change
and should be reviewed by a clinical coder.

Sources:
    ICD-10-CM Official Guidelines for Coding and Reporting (FY2024), CDC/CMS
    AHA Coding Clinic guidance (cited per-list below)
    CMS-HCC V28 ICD-to-CC crosswalk, CY2024 Rate Announcement

NOTE: Prefix lists are intentionally conservative. They are used only to
check specificity — never to derive an HCC mapping (that is hccinfhir's job).
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# ICD-10-CM prefix groups (used for specificity / supporting-dx checks)
# Stored as tuples for cheap startswith() usage.  Always strip dots first.
# ---------------------------------------------------------------------------

# Diabetes mellitus — all types (E08–E13 family).
# Source: ICD-10-CM FY2024 Chapter 4 guideline I.C.4.a.
ICD10_DIABETES_ANY: tuple[str, ...] = ("E08", "E09", "E10", "E11", "E13")

# Diabetes-with-complication fourth-character categories.
# E11.2x renal, E11.3x ophthalmic, E11.4x neuro, E11.5x circulatory,
# E11.6x other specified, E11.8 unspecified complication (still counts as
# "with complications" per guideline I.C.4.a.2). Parallel pattern for E08–E13.
# Source: ICD-10-CM FY2024 Tabular List, categories E08.2–E13.8.
ICD10_DIABETES_WITH_COMPLICATION_SUFFIX: tuple[str, ...] = (
    "2", "3", "4", "5", "6", "8",
)

# CKD stage-specific codes (N18.3–N18.6). N18.9 is non-specific.
# Source: ICD-10-CM FY2024 N18.x tabular.
ICD10_CKD_STAGE_SPECIFIC: tuple[str, ...] = (
    "N183",   # Stage 3 (further split into N1830/31/32 since FY2024)
    "N1830", "N1831", "N1832",
    "N184",   # Stage 4
    "N185",   # Stage 5
    "N186",   # ESRD
)
ICD10_CKD_ANY: tuple[str, ...] = ("N18",)

# CHF / heart failure family.
# Source: ICD-10-CM FY2024 I50.x tabular.  I50.9 (unspecified) is advisory-
# only; stage specificity is preferred per AHA Coding Clinic 2Q 2017 p.12.
ICD10_CHF_ANY: tuple[str, ...] = ("I50",)
ICD10_CHF_SPECIFIC: tuple[str, ...] = (
    "I501",    # Left ventricular failure
    "I5020", "I5021", "I5022", "I5023",  # Systolic
    "I5030", "I5031", "I5032", "I5033",  # Diastolic
    "I5040", "I5041", "I5042", "I5043",  # Combined
    "I5081", "I5082", "I5083", "I5084", "I5089",
)

# COPD.
# Source: ICD-10-CM FY2024 J44.x tabular.
ICD10_COPD_ANY: tuple[str, ...] = ("J44",)

# Major depressive disorder (recurrent / single episode) — MDD codes that
# support HCC 155 (Major Depression, Bipolar, and Paranoid Disorders).
# Source: ICD-10-CM FY2024 F32.x and F33.x tabular.
# F32.0 mild, F32.1 moderate, F32.2 severe w/o psychosis, F32.3 severe w/
# psychosis, F33 recurrent.  F32.9 unspecified is advisory.
ICD10_MDD_ANY: tuple[str, ...] = ("F32", "F33")

# Active malignancy prefixes — C00–C96 (excludes D0x in-situ and benign).
# Source: ICD-10-CM FY2024 Chapter 2 guideline I.C.2.
ICD10_ACTIVE_CANCER: tuple[str, ...] = tuple(f"C{n:02d}" for n in range(0, 97))

# History-of-cancer (personal history Z85.x) — should NOT count as active.
# Source: ICD-10-CM FY2024 guideline I.C.21.c.4.
ICD10_HISTORY_OF_CANCER: tuple[str, ...] = ("Z85",)

# Stroke sequelae (I69.x) — used for stroke rule.
# Source: ICD-10-CM FY2024 I69.x tabular.
ICD10_STROKE_SEQUELAE: tuple[str, ...] = ("I69",)

# Acute MI (I21.x) and subsequent MI (I22.x).
# Source: ICD-10-CM FY2024 I21–I22 tabular.  AHA Coding Clinic 1Q 2017 p.24
# clarifies: code I21 only within the 4-week encounter window; after that use
# I25.2 (old MI).
ICD10_ACUTE_MI: tuple[str, ...] = ("I21", "I22")
ICD10_OLD_MI: tuple[str, ...] = ("I252",)

# Peripheral Vascular Disease (I70.2x+ symptomatic, I73.9 unspec).
# Source: ICD-10-CM FY2024 I70 and I73 tabular.
ICD10_PVD_ANY: tuple[str, ...] = ("I70", "I73")
ICD10_PVD_SPECIFIC: tuple[str, ...] = (
    "I702",   # Atherosclerosis of native arteries of extremities
    "I703",   # Atherosclerosis of bypass graft
    "I7389",  # Other specified peripheral vascular diseases
)

# Acquired absence of limb (Z89.x) and traumatic amputation (S48/S58/S78/S88).
# Source: ICD-10-CM FY2024 Z89.x tabular and Chapter 19 amputation codes.
ICD10_AMPUTATION_STATUS: tuple[str, ...] = ("Z89",)
ICD10_AMPUTATION_ACUTE: tuple[str, ...] = ("S48", "S58", "S78", "S88")


# ---------------------------------------------------------------------------
# Rx-class identifiers
#
# We deliberately match by a canonical normalized class-name set rather than
# RxNorm IDs because the current evidence extractor (Gemini) produces free-
# text "drug class" strings.  Class names are lower-cased with whitespace
# stripped before comparison (see rules.rx_class_present).
#
# Sources: AHFS Drug Information (ASHP) class names; ATC level-4 where
# AHFS does not disambiguate (e.g. SGLT2 inhibitors).
# ---------------------------------------------------------------------------

RX_CLASS_DIABETES: frozenset[str] = frozenset({
    "biguanide", "biguanides", "metformin",
    "sulfonylurea", "sulfonylureas",
    "meglitinide", "meglitinides",
    "thiazolidinedione", "thiazolidinediones",
    "dpp-4 inhibitor", "dpp4 inhibitor", "dpp-4 inhibitors",
    "sglt2 inhibitor", "sglt-2 inhibitor", "sglt2 inhibitors",
    "glp-1 agonist", "glp1 agonist", "glp-1 receptor agonist",
    "insulin",
    "alpha-glucosidase inhibitor",
    "amylin analog",
})

RX_CLASS_CHF: frozenset[str] = frozenset({
    "ace inhibitor", "acei", "ace inhibitors",
    "arb", "angiotensin receptor blocker",
    "arni", "angiotensin receptor neprilysin inhibitor",
    "beta blocker", "beta-blocker", "beta blockers",
    "mra", "mineralocorticoid receptor antagonist",
    "spironolactone", "eplerenone",
    "loop diuretic", "loop diuretics",
    "sglt2 inhibitor", "sglt-2 inhibitor",   # class I for HFrEF per 2022 ACC/AHA/HFSA
    "digoxin", "ivabradine", "hydralazine/nitrate",
})

RX_CLASS_COPD: frozenset[str] = frozenset({
    "saba", "short-acting beta agonist",
    "laba", "long-acting beta agonist",
    "sama", "short-acting muscarinic antagonist",
    "lama", "long-acting muscarinic antagonist",
    "ics", "inhaled corticosteroid", "inhaled corticosteroids",
    "ics/laba", "laba/lama", "ics/laba/lama", "triple therapy",
    "roflumilast", "theophylline",
})

RX_CLASS_DEPRESSION: frozenset[str] = frozenset({
    "ssri", "selective serotonin reuptake inhibitor",
    "snri", "serotonin-norepinephrine reuptake inhibitor",
    "tca", "tricyclic antidepressant",
    "maoi", "monoamine oxidase inhibitor",
    "atypical antidepressant",
    "bupropion", "mirtazapine", "trazodone", "vilazodone", "vortioxetine",
})

RX_CLASS_ANTIPLATELET_ANTICOAG: frozenset[str] = frozenset({
    "antiplatelet", "aspirin",
    "p2y12 inhibitor", "clopidogrel", "ticagrelor", "prasugrel",
    "anticoagulant", "doac", "warfarin", "apixaban", "rivaroxaban",
    "dabigatran", "edoxaban",
})

RX_CLASS_CANCER_TREATMENT: frozenset[str] = frozenset({
    "chemotherapy", "antineoplastic", "cytotoxic",
    "immunotherapy", "checkpoint inhibitor",
    "targeted therapy", "monoclonal antibody",
    "hormonal therapy", "tamoxifen", "aromatase inhibitor",
    "radiation therapy", "radiotherapy",
})


# ---------------------------------------------------------------------------
# LOINC codes for supporting labs (used by e.g. CKD rule for eGFR, CHF rule
# for BNP, COPD rule for PFT).
#
# Sources: LOINC User's Guide v2.78; KDIGO 2024 Clinical Practice Guideline.
# ---------------------------------------------------------------------------

LOINC_EGFR: frozenset[str] = frozenset({
    "48642-3",   # Glomerular filtration rate/1.73 sq M.predicted by Creatinine-based formula (MDRD)
    "48643-1",   # GFR (MDRD, non-AA)
    "62238-1",   # GFR (CKD-EPI)
    "88293-6",   # eGFR CKD-EPI 2021
    "98979-8",   # eGFR cystatin-C (CKD-EPI 2021)
})

LOINC_HBA1C: frozenset[str] = frozenset({
    "4548-4",    # Hemoglobin A1c/Hemoglobin.total in Blood
    "17856-6",   # HbA1c (calculated)
    "4549-2",
})

LOINC_BNP: frozenset[str] = frozenset({
    "30934-4",   # NT-proBNP
    "33762-6",   # NT-proBNP (alt)
    "42637-9",   # BNP
})

# PFT-related LOINCs (FEV1, FVC, ratio).
LOINC_PFT: frozenset[str] = frozenset({
    "19870-5",   # FEV1
    "19868-9",   # FEV1/FVC
    "19876-2",   # FVC
    "20147-7",   # FEV1/FVC ratio measured
})


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def normalize_icd(code: str | None) -> str:
    """Strip dots and whitespace, upper-case. Returns empty string for None."""
    if not code:
        return ""
    return code.replace(".", "").strip().upper()


def has_prefix(codes: list[str] | set[str], prefixes: tuple[str, ...]) -> bool:
    """True if any code in `codes` starts with any prefix in `prefixes`."""
    for c in codes:
        nc = normalize_icd(c)
        for p in prefixes:
            if nc.startswith(p):
                return True
    return False


def any_code_matches(codes: list[str] | set[str], targets: tuple[str, ...]) -> bool:
    """True if any code in `codes` exactly matches a target (post-normalization)."""
    target_set = {t.replace(".", "").upper() for t in targets}
    for c in codes:
        if normalize_icd(c) in target_set:
            return True
    return False


def normalize_rx_class(raw: str | None) -> str:
    """Canonicalize a free-text rx class string for membership checks."""
    if not raw:
        return ""
    return raw.strip().lower().replace("_", " ").replace("  ", " ")


def rx_class_present(rx_entries: list[str], class_set: frozenset[str]) -> bool:
    """True if any of `rx_entries` (free text) normalises into `class_set`."""
    for r in rx_entries or []:
        if normalize_rx_class(r) in class_set:
            return True
    return False
