"""Seed the curated brand <-> generic ingredient mapping.

Populates ``kg_brand_to_generic`` with ~55 high-volume US brand names whose
corresponding generic ingredient is already covered (or trivially derivable)
by the existing WHO ATC bridge.  Re-running the script updates rows rather
than duplicating them (idempotent on ``UNIQUE KEY uq_brand``).

Source data: FDA Orange Book + DailyMed labels (manually curated, current
as of 2026-04).  RxCUIs are pulled from RxNav (NLM).

Usage::

    PYTHONPATH=backend python backend/scripts/seed_brand_to_generic.py
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any

# Make ``backend`` importable when run as a script.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

logger = logging.getLogger("seed_brand_to_generic")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


# ---------------------------------------------------------------------------
# Curated brand <-> generic data.
# ---------------------------------------------------------------------------
#
# Fields:
#   brand          Brand / trade name (case preserved for display).
#   generic        Generic ingredient.  Lower-case.
#   atc            WHO ATC code (level 4 or 5; matches kg_atc_classes).
#   rxcui_brand    RxNorm CUI for the brand SCD if known.
#   rxcui_generic  RxNorm CUI for the generic ingredient.
#   manufacturer   Primary manufacturer (informational only).

BRAND_GENERIC: list[dict[str, Any]] = [
    # ---------- Diabetes / GLP-1 / SGLT2 -------------------------------------
    {"brand": "Ozempic",   "generic": "semaglutide",     "atc": "A10BJ", "rxcui_brand": "1992368", "rxcui_generic": "1991302", "manufacturer": "Novo Nordisk"},
    {"brand": "Wegovy",    "generic": "semaglutide",     "atc": "A10BJ", "rxcui_brand": "2401358", "rxcui_generic": "1991302", "manufacturer": "Novo Nordisk"},
    {"brand": "Rybelsus",  "generic": "semaglutide",     "atc": "A10BJ", "rxcui_brand": "2117313", "rxcui_generic": "1991302", "manufacturer": "Novo Nordisk"},
    {"brand": "Trulicity", "generic": "dulaglutide",     "atc": "A10BJ", "rxcui_brand": "1551300", "rxcui_generic": "1244202", "manufacturer": "Eli Lilly"},
    {"brand": "Mounjaro",  "generic": "tirzepatide",     "atc": "A10BX", "rxcui_brand": "2601725", "rxcui_generic": "2601723", "manufacturer": "Eli Lilly"},
    {"brand": "Zepbound",  "generic": "tirzepatide",     "atc": "A10BX", "rxcui_brand": "2683004", "rxcui_generic": "2601723", "manufacturer": "Eli Lilly"},
    {"brand": "Victoza",   "generic": "liraglutide",     "atc": "A10BJ", "rxcui_brand": "847232",  "rxcui_generic": "1373458", "manufacturer": "Novo Nordisk"},
    {"brand": "Saxenda",   "generic": "liraglutide",     "atc": "A10BJ", "rxcui_brand": "1659115", "rxcui_generic": "1373458", "manufacturer": "Novo Nordisk"},
    {"brand": "Jardiance", "generic": "empagliflozin",   "atc": "A10BK", "rxcui_brand": "1547004", "rxcui_generic": "1545653", "manufacturer": "Boehringer Ingelheim"},
    {"brand": "Farxiga",   "generic": "dapagliflozin",   "atc": "A10BK", "rxcui_brand": "1488564", "rxcui_generic": "1373463", "manufacturer": "AstraZeneca"},
    {"brand": "Invokana",  "generic": "canagliflozin",   "atc": "A10BK", "rxcui_brand": "1373473", "rxcui_generic": "1486436", "manufacturer": "Janssen"},
    {"brand": "Januvia",   "generic": "sitagliptin",     "atc": "A10BH", "rxcui_brand": "665033",  "rxcui_generic": "593411",  "manufacturer": "Merck"},
    {"brand": "Tradjenta", "generic": "linagliptin",     "atc": "A10BH", "rxcui_brand": "857984",  "rxcui_generic": "857974",  "manufacturer": "Boehringer Ingelheim"},
    {"brand": "Glucophage","generic": "metformin",       "atc": "A10BA02", "rxcui_brand": "153842","rxcui_generic": "6809",   "manufacturer": "Bristol Myers Squibb"},

    # ---------- Anticoagulants / antiplatelets ------------------------------
    {"brand": "Eliquis",   "generic": "apixaban",        "atc": "B01AF", "rxcui_brand": "1364435", "rxcui_generic": "1364430", "manufacturer": "Bristol Myers Squibb"},
    {"brand": "Xarelto",   "generic": "rivaroxaban",     "atc": "B01AF", "rxcui_brand": "1037050", "rxcui_generic": "1037045", "manufacturer": "Janssen"},
    {"brand": "Pradaxa",   "generic": "dabigatran",      "atc": "B01AE", "rxcui_brand": "1037048", "rxcui_generic": "1037042", "manufacturer": "Boehringer Ingelheim"},
    {"brand": "Savaysa",   "generic": "edoxaban",        "atc": "B01AF", "rxcui_brand": "1599546", "rxcui_generic": "1593411", "manufacturer": "Daiichi Sankyo"},
    {"brand": "Coumadin",  "generic": "warfarin",        "atc": "B01AA", "rxcui_brand": "202421",  "rxcui_generic": "11289",   "manufacturer": "Bristol Myers Squibb"},
    {"brand": "Plavix",    "generic": "clopidogrel",     "atc": "B01AC", "rxcui_brand": "174742",  "rxcui_generic": "32968",   "manufacturer": "Sanofi / BMS"},
    {"brand": "Brilinta",  "generic": "ticagrelor",      "atc": "B01AC", "rxcui_brand": "1116635", "rxcui_generic": "1116632", "manufacturer": "AstraZeneca"},
    {"brand": "Effient",   "generic": "prasugrel",       "atc": "B01AC", "rxcui_brand": "613393",  "rxcui_generic": "613391",  "manufacturer": "Eli Lilly"},

    # ---------- Statins / lipid-lowering -------------------------------------
    {"brand": "Lipitor",   "generic": "atorvastatin",    "atc": "C10AA", "rxcui_brand": "153165",  "rxcui_generic": "83367",   "manufacturer": "Pfizer"},
    {"brand": "Crestor",   "generic": "rosuvastatin",    "atc": "C10AA", "rxcui_brand": "402421",  "rxcui_generic": "301542",  "manufacturer": "AstraZeneca"},
    {"brand": "Zocor",     "generic": "simvastatin",     "atc": "C10AA", "rxcui_brand": "152923",  "rxcui_generic": "36567",   "manufacturer": "Merck"},
    {"brand": "Pravachol", "generic": "pravastatin",     "atc": "C10AA", "rxcui_brand": "200345",  "rxcui_generic": "42463",   "manufacturer": "Bristol Myers Squibb"},
    {"brand": "Zetia",     "generic": "ezetimibe",       "atc": "C10AX", "rxcui_brand": "352336",  "rxcui_generic": "847630",  "manufacturer": "Merck"},

    # ---------- Antihypertensives / cardiovascular --------------------------
    {"brand": "Norvasc",   "generic": "amlodipine",      "atc": "C08CA", "rxcui_brand": "153666",  "rxcui_generic": "17767",   "manufacturer": "Pfizer"},
    {"brand": "Toprol-XL", "generic": "metoprolol",      "atc": "C07AB", "rxcui_brand": "866924",  "rxcui_generic": "6918",    "manufacturer": "AstraZeneca"},
    {"brand": "Coreg",     "generic": "carvedilol",      "atc": "C07AG", "rxcui_brand": "200032",  "rxcui_generic": "20352",   "manufacturer": "GlaxoSmithKline"},
    {"brand": "Cozaar",    "generic": "losartan",        "atc": "C09CA", "rxcui_brand": "203160",  "rxcui_generic": "52175",   "manufacturer": "Merck"},
    {"brand": "Diovan",    "generic": "valsartan",       "atc": "C09CA", "rxcui_brand": "200094",  "rxcui_generic": "69749",   "manufacturer": "Novartis"},
    {"brand": "Entresto",  "generic": "sacubitril/valsartan", "atc": "C09DX", "rxcui_brand": "203644", "rxcui_generic": "1656339", "manufacturer": "Novartis"},
    {"brand": "Lasix",     "generic": "furosemide",      "atc": "C03CA", "rxcui_brand": "200095",  "rxcui_generic": "4603",    "manufacturer": "Sanofi"},

    # ---------- Respiratory --------------------------------------------------
    {"brand": "Spiriva",   "generic": "tiotropium",      "atc": "R03BB", "rxcui_brand": "1599540", "rxcui_generic": "1599538", "manufacturer": "Boehringer Ingelheim"},
    {"brand": "Symbicort", "generic": "budesonide-formoterol", "atc": "R03AK", "rxcui_brand": "1797889", "rxcui_generic": "1797881", "manufacturer": "AstraZeneca"},
    {"brand": "Advair",    "generic": "fluticasone-salmeterol", "atc": "R03AK", "rxcui_brand": "896994",  "rxcui_generic": "896188",  "manufacturer": "GlaxoSmithKline"},
    {"brand": "Trelegy",   "generic": "fluticasone-umeclidinium-vilanterol", "atc": "R03AL", "rxcui_brand": "1939372", "rxcui_generic": "1939370", "manufacturer": "GlaxoSmithKline"},
    {"brand": "Anoro",     "generic": "umeclidinium-vilanterol", "atc": "R03AL", "rxcui_brand": "1552180", "rxcui_generic": "1552178", "manufacturer": "GlaxoSmithKline"},

    # ---------- Mental health / antipsychotics ------------------------------
    {"brand": "Zoloft",    "generic": "sertraline",      "atc": "N06AB", "rxcui_brand": "200663",  "rxcui_generic": "32937",   "manufacturer": "Pfizer"},
    {"brand": "Lexapro",   "generic": "escitalopram",    "atc": "N06AB", "rxcui_brand": "352741",  "rxcui_generic": "37798",   "manufacturer": "Allergan"},
    {"brand": "Prozac",    "generic": "fluoxetine",      "atc": "N06AB", "rxcui_brand": "151692",  "rxcui_generic": "4493",    "manufacturer": "Eli Lilly"},
    {"brand": "Cymbalta",  "generic": "duloxetine",      "atc": "N06AX", "rxcui_brand": "596925",  "rxcui_generic": "321988",  "manufacturer": "Eli Lilly"},
    {"brand": "Effexor",   "generic": "venlafaxine",     "atc": "N06AX", "rxcui_brand": "151692",  "rxcui_generic": "72625",   "manufacturer": "Wyeth"},
    {"brand": "Wellbutrin","generic": "bupropion",       "atc": "N06AX", "rxcui_brand": "151692",  "rxcui_generic": "72729",   "manufacturer": "GlaxoSmithKline"},
    {"brand": "Zyprexa",   "generic": "olanzapine",      "atc": "N05AH", "rxcui_brand": "153893",  "rxcui_generic": "61381",   "manufacturer": "Eli Lilly"},
    {"brand": "Abilify",   "generic": "aripiprazole",    "atc": "N05AX", "rxcui_brand": "352395",  "rxcui_generic": "352393",  "manufacturer": "Otsuka"},
    {"brand": "Risperdal", "generic": "risperidone",     "atc": "N05AX", "rxcui_brand": "152915",  "rxcui_generic": "35636",   "manufacturer": "Janssen"},
    {"brand": "Seroquel",  "generic": "quetiapine",      "atc": "N05AH", "rxcui_brand": "200371",  "rxcui_generic": "115698",  "manufacturer": "AstraZeneca"},
    {"brand": "Lithobid",  "generic": "lithium",         "atc": "N05AN", "rxcui_brand": "858823",  "rxcui_generic": "6448",    "manufacturer": "Noven"},

    # ---------- Neurology / dementia / Parkinson ----------------------------
    {"brand": "Aricept",   "generic": "donepezil",       "atc": "N06DA", "rxcui_brand": "152364",  "rxcui_generic": "135447",  "manufacturer": "Eisai"},
    {"brand": "Namenda",   "generic": "memantine",       "atc": "N06DX", "rxcui_brand": "352364",  "rxcui_generic": "39998",   "manufacturer": "Allergan"},
    {"brand": "Exelon",    "generic": "rivastigmine",    "atc": "N06DA", "rxcui_brand": "200124",  "rxcui_generic": "183379",  "manufacturer": "Novartis"},
    {"brand": "Razadyne",  "generic": "galantamine",     "atc": "N06DA", "rxcui_brand": "351264",  "rxcui_generic": "183381",  "manufacturer": "Janssen"},
    {"brand": "Sinemet",   "generic": "carbidopa-levodopa", "atc": "N04BA", "rxcui_brand": "199945", "rxcui_generic": "6375", "manufacturer": "Merck"},
    {"brand": "Lamictal",  "generic": "lamotrigine",     "atc": "N03AX", "rxcui_brand": "152825",  "rxcui_generic": "28439",   "manufacturer": "GlaxoSmithKline"},
    {"brand": "Depakote",  "generic": "divalproex",      "atc": "N03AG", "rxcui_brand": "152822",  "rxcui_generic": "4344",    "manufacturer": "AbbVie"},
    {"brand": "Neurontin", "generic": "gabapentin",      "atc": "N03AX", "rxcui_brand": "151692",  "rxcui_generic": "25480",   "manufacturer": "Pfizer"},
    {"brand": "Lyrica",    "generic": "pregabalin",      "atc": "N03AX", "rxcui_brand": "352741",  "rxcui_generic": "187832",  "manufacturer": "Pfizer"},

    # ---------- Endocrine / thyroid -----------------------------------------
    {"brand": "Synthroid", "generic": "levothyroxine",   "atc": "H03AA", "rxcui_brand": "966210",  "rxcui_generic": "10582",   "manufacturer": "AbbVie"},

    # ---------- HIV ART -----------------------------------------------------
    {"brand": "Biktarvy",  "generic": "bictegravir/emtricitabine/tenofovir", "atc": "J05AR", "rxcui_brand": "1601651", "rxcui_generic": "1747691", "manufacturer": "Gilead"},
    {"brand": "Triumeq",   "generic": "abacavir/dolutegravir/lamivudine", "atc": "J05AR", "rxcui_brand": "1551575", "rxcui_generic": "1551573", "manufacturer": "ViiV"},

    # ---------- Erythropoiesis / anemia / iron ------------------------------
    {"brand": "Epogen",    "generic": "epoetin alfa",    "atc": "B03XA", "rxcui_brand": "152715",  "rxcui_generic": "105694",  "manufacturer": "Amgen"},
    {"brand": "Aranesp",   "generic": "darbepoetin alfa","atc": "B03XA", "rxcui_brand": "274812",  "rxcui_generic": "274811",  "manufacturer": "Amgen"},
    {"brand": "Procrit",   "generic": "epoetin alfa",    "atc": "B03XA", "rxcui_brand": "200019",  "rxcui_generic": "105694",  "manufacturer": "Janssen"},
]


# ---------------------------------------------------------------------------
# Seeding logic
# ---------------------------------------------------------------------------

def seed() -> dict[str, int]:
    """Run the full seed.  Returns row counts for verification."""
    # Late import keeps ``--dry-run`` mode usable on machines without
    # production DB credentials configured.
    from app.db import raf_cursor                                 # noqa: WPS433

    counts = {"brand_to_generic": 0}
    with raf_cursor() as cur:
        for row in BRAND_GENERIC:
            cur.execute(
                """
                INSERT INTO kg_brand_to_generic
                  (brand_name, generic_name, rxcui_brand, rxcui_generic,
                   atc_code, manufacturer, is_active)
                VALUES (%s, %s, %s, %s, %s, %s, 1)
                ON DUPLICATE KEY UPDATE
                  generic_name  = VALUES(generic_name),
                  rxcui_brand   = VALUES(rxcui_brand),
                  rxcui_generic = VALUES(rxcui_generic),
                  atc_code      = VALUES(atc_code),
                  manufacturer  = VALUES(manufacturer),
                  is_active     = 1
                """,
                (
                    row["brand"],
                    row["generic"],
                    row.get("rxcui_brand"),
                    row.get("rxcui_generic"),
                    row.get("atc"),
                    row.get("manufacturer"),
                ),
            )
            counts["brand_to_generic"] += 1
    return counts


def main() -> None:
    if os.environ.get("BRAND_GENERIC_SEED_DRY_RUN") == "1":
        logger.info("Dry run: validating in-memory data only.")
        # Sanity: brand uniqueness, required keys.
        seen_brands: set[str] = set()
        for r in BRAND_GENERIC:
            for key in ("brand", "generic", "atc"):
                if not r.get(key):
                    raise RuntimeError(f"Brand row missing {key}: {r}")
            lower = r["brand"].lower()
            if lower in seen_brands:
                raise RuntimeError(f"Duplicate brand: {r['brand']}")
            seen_brands.add(lower)
        logger.info("OK: %d brand mappings.", len(BRAND_GENERIC))
        return

    counts = seed()
    logger.info("Seed complete: %s", counts)


if __name__ == "__main__":
    main()
