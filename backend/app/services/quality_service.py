"""
HEDIS Quality Measure Tracking and Value-Based Care Analytics Service.

Implements the following HEDIS measures with HCC overlap annotations:
  CDC  – Comprehensive Diabetes Care          (HCC 17-19)
  CBP  – Controlling High Blood Pressure      (HCC 95-96)
  COA  – Care for Older Adults                (HCC frailty indicators)
  OMW  – Osteoporosis Management in Women     (HCC 40)
  SPD  – Statin Therapy for Patients with Diabetes (HCC 17-19)
  KED  – Kidney Health Evaluation for Patients with Diabetes (HCC 326-329)

All queries execute against the OpenEMR MySQL database via openemr_cursor().
No PHI is logged — patient identifiers are kept inside caller scope only.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any

from app.db import openemr_cursor, raf_cursor
from app.services.emr_manager import active_patients_subquery

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# FHIR connection detection helper
# ---------------------------------------------------------------------------

def _active_conn_type(tenant_id: int) -> str:
    """Return the connection_type of the active EMR connection for the tenant.

    Returns ``'direct_db'`` when no active connection row is found so that
    all existing direct-DB code paths remain the default.
    """
    try:
        with raf_cursor() as cur:
            cur.execute(
                "SELECT connection_type FROM emr_connections "
                "WHERE is_active = 1 AND tenant_id = %s LIMIT 1",
                (tenant_id,),
            )
            row = cur.fetchone()
            return row["connection_type"] if row else "direct_db"
    except Exception as exc:
        logger.warning("_active_conn_type: could not determine conn type: %s", exc)
        return "direct_db"


# ---------------------------------------------------------------------------
# Measure catalog
# ---------------------------------------------------------------------------

HEDIS_MEASURES: dict[str, dict[str, Any]] = {
    "CDC": {
        "code": "CDC",
        "name": "Comprehensive Diabetes Care",
        "description": (
            "Measures the percentage of members 18–75 years of age with diabetes (type 1 and type 2) "
            "who had HbA1c testing, HbA1c control, retinal eye exam, nephropathy screening, "
            "and blood pressure control."
        ),
        "hcc_overlap": [17, 18, 19],
        "hcc_labels": ["Diabetes without complication", "Diabetes with chronic complication", "Diabetes with acute complication"],
        "denominator_icd_prefixes": ["E10", "E11", "E13"],
        "components": [
            "hba1c_tested",
            "hba1c_controlled",
            "eye_exam",
            "nephropathy_screen",
            "bp_controlled",
        ],
        "stars_weight": 3,
    },
    "CBP": {
        "code": "CBP",
        "name": "Controlling High Blood Pressure",
        "description": (
            "Percentage of members 18–85 years of age with hypertension whose blood pressure "
            "was adequately controlled (<140/90 mmHg) during the measurement year."
        ),
        "hcc_overlap": [95, 96],
        "hcc_labels": ["Hypertension", "Hypertension with complications"],
        "denominator_icd_prefixes": ["I10", "I11", "I12", "I13"],
        "components": ["bp_controlled"],
        "stars_weight": 3,
    },
    "COA": {
        "code": "COA",
        "name": "Care for Older Adults",
        "description": (
            "Percentage of Medicare members 66 years and older who received all three of "
            "medication review, functional status assessment, and pain assessment."
        ),
        "hcc_overlap": [22, 23, 85],
        "hcc_labels": ["Morbid obesity", "Other significant endocrine and metabolic disorders", "Congestive heart failure"],
        "denominator_icd_prefixes": [],  # Age-based denominator
        "components": [
            "medication_review",
            "functional_assessment",
            "pain_assessment",
        ],
        "stars_weight": 1,
    },
    "OMW": {
        "code": "OMW",
        "name": "Osteoporosis Management in Women Who Had a Fracture",
        "description": (
            "Percentage of women 67–85 years of age who suffered a fracture and "
            "who had either a bone mineral density test or a prescription for a drug "
            "to treat or prevent osteoporosis in the 6 months after the fracture."
        ),
        "hcc_overlap": [40],
        "hcc_labels": ["Bone/Joint/Muscle infections or necrosis"],
        "denominator_icd_prefixes": ["M80", "M81", "S12", "S22", "S32", "S42", "S52", "S62", "S72", "S82", "S92"],
        "components": ["bone_density_or_med"],
        "stars_weight": 2,
    },
    "SPD": {
        "code": "SPD",
        "name": "Statin Therapy for Patients with Diabetes",
        "description": (
            "Percentage of members 40–75 years of age with diabetes who were dispensed "
            "at least one statin medication during the measurement year."
        ),
        "hcc_overlap": [17, 18, 19],
        "hcc_labels": ["Diabetes without complication", "Diabetes with chronic complication", "Diabetes with acute complication"],
        "denominator_icd_prefixes": ["E10", "E11", "E13"],
        "components": ["statin_prescribed"],
        "stars_weight": 2,
    },
    "KED": {
        "code": "KED",
        "name": "Kidney Health Evaluation for Patients with Diabetes",
        "description": (
            "Percentage of members 18–85 years of age with diabetes who received a "
            "kidney health evaluation (eGFR and urine albumin-to-creatinine ratio) "
            "during the measurement year."
        ),
        "hcc_overlap": [326, 327, 328, 329],
        "hcc_labels": ["CKD stage 1", "CKD stage 2", "CKD stage 3", "CKD stage 4"],
        "denominator_icd_prefixes": ["E10", "E11", "E13"],
        "components": ["egfr_tested", "uacr_tested"],
        "stars_weight": 3,
    },
}

# Statin generic drug name fragments (lowercase match against drug_name)
_STATIN_KEYWORDS = [
    "atorvastatin", "rosuvastatin", "simvastatin", "pravastatin",
    "lovastatin", "fluvastatin", "pitavastatin", "cerivastatin",
]

# Osteoporosis drug fragments
_OSTEO_MED_KEYWORDS = [
    "alendronate", "risedronate", "ibandronate", "zoledronic", "zoledronate",
    "denosumab", "teriparatide", "abaloparatide", "raloxifene", "romosozumab",
]

# Lab test name fragments mapped to analyte keys
_LAB_KEYWORDS: dict[str, list[str]] = {
    "hba1c": ["hba1c", "hemoglobin a1c", "glycated hemoglobin", "a1c", "hgba1c"],
    "egfr": ["egfr", "gfr", "glomerular filtration", "estimated gfr"],
    "uacr": ["uacr", "albumin creatinine ratio", "microalbumin", "urine albumin", "acr"],
    "ldl": ["ldl", "low density lipoprotein"],
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _calculate_age(dob: Any, as_of_year: int) -> int:
    if dob is None:
        return 0
    if isinstance(dob, str):
        try:
            dob = datetime.strptime(dob[:10], "%Y-%m-%d").date()
        except ValueError:
            return 0
    elif isinstance(dob, datetime):
        dob = dob.date()
    ref = date(as_of_year, 12, 31)
    age = ref.year - dob.year - ((ref.month, ref.day) < (dob.month, dob.day))
    return max(0, age)


def _year_range(year: int) -> tuple[str, str]:
    """Return (start, end) date strings for a calendar year."""
    return f"{year}-01-01", f"{year}-12-31"


def _has_icd_prefix(icd_code: str, prefixes: list[str]) -> bool:
    if not icd_code or not prefixes:
        return False
    code = icd_code.strip().upper().replace(".", "")
    return any(code.startswith(p.replace(".", "")) for p in prefixes)


def _keyword_match(text: str, keywords: list[str]) -> bool:
    if not text:
        return False
    lower = text.lower()
    return any(kw in lower for kw in keywords)


# ---------------------------------------------------------------------------
# OpenEMR data fetchers (per-patient)
# ---------------------------------------------------------------------------

def _get_patient_demographics(pid: int, tenant_id: int | str = "") -> dict[str, Any] | None:
    # Primary source: raf_intelligence.patients (direct-DB / OpenEMR patients)
    sql = "SELECT id AS pid, first_name AS fname, last_name AS lname, dob AS DOB, sex FROM patients WHERE id = %s AND tenant_id = %s"
    with raf_cursor() as cur:
        cur.execute(sql, (pid, tenant_id))
        row = cur.fetchone()
    if row:
        return dict(row)

    # Fallback: FHIR patients tracked in emr_patient_matches — must scope to
    # the same tenant to prevent cross-tenant data leakage.
    try:
        with raf_cursor() as cur:
            cur.execute(
                "SELECT epm.id AS pid, epm.first_name AS fname, epm.last_name AS lname, "
                "epm.date_of_birth AS DOB, epm.sex "
                "FROM emr_patient_matches epm "
                "JOIN emr_connections ec ON ec.id = epm.connection_id "
                "WHERE ec.is_active = 1 AND ec.tenant_id = %s AND epm.id = %s LIMIT 1",
                (tenant_id, pid),
            )
            fhir_row = cur.fetchone()
        if fhir_row:
            return dict(fhir_row)
    except Exception as exc:
        logger.debug("_get_patient_demographics: FHIR fallback failed for pid %s: %s", pid, exc)

    return None


def _get_active_diagnoses(pid: int, year: int) -> list[str]:
    """
    Return ICD-10 codes active for patient from the problem list and billing.
    Includes both active problems and any billing codes submitted in the year.
    """
    year_start, year_end = _year_range(year)
    codes: set[str] = set()

    # Active problem list (lists table may not exist in all schemas)
    sql_problems = """
        SELECT diagnosis FROM lists
        WHERE pid = %s
          AND type = 'medical_problem'
          AND activity = 1
          AND diagnosis IS NOT NULL
          AND diagnosis != ''
    """
    try:
        with openemr_cursor() as cur:
            cur.execute(sql_problems, (pid,))
            for row in cur.fetchall():
                if row["diagnosis"]:
                    codes.add(row["diagnosis"].strip().upper())
    except Exception as exc:
        logger.debug("_get_active_diagnoses lists query failed for pid %s: %s", pid, exc)

    # Billing codes (shadow schema has no date column on billing)
    sql_billing = """
        SELECT code FROM billing
        WHERE pid = %s
          AND code_type = 'ICD10'
          AND activity = 1
          AND code IS NOT NULL
    """
    with openemr_cursor() as cur:
        cur.execute(sql_billing, (pid,))
        for row in cur.fetchall():
            if row["code"]:
                codes.add(row["code"].strip().upper())

    return list(codes)


def _get_labs(pid: int, year: int) -> list[dict[str, Any]]:
    """Return procedure_result rows for the patient in the measurement year."""
    year_start, year_end = _year_range(year)
    sql = """
        SELECT
            pr.result_text,
            pr.result,
            pr.units,
            pr.date,
            po.procedure_order_code AS test_name
        FROM procedure_result pr
        JOIN procedure_report prep ON prep.procedure_report_id = pr.procedure_report_id
        JOIN procedure_order po ON po.procedure_order_id = prep.procedure_order_id
        WHERE po.patient_id = %s
          AND pr.date BETWEEN %s AND %s
    """
    try:
        with openemr_cursor() as cur:
            cur.execute(sql, (pid, year_start, year_end))
            return [dict(r) for r in cur.fetchall()]
    except Exception as exc:
        logger.debug("_get_labs query failed for pid %s: %s", pid, exc)
        return []


def _get_vitals(pid: int, year: int) -> list[dict[str, Any]]:
    """Return form_vitals rows for the patient in the measurement year."""
    year_start, year_end = _year_range(year)
    sql = """
        SELECT
            date,
            bps AS systolic,
            bpd AS diastolic,
            weight AS weight,
            height AS height
        FROM form_vitals
        WHERE pid = %s
          AND date BETWEEN %s AND %s
        ORDER BY date DESC
    """
    try:
        with openemr_cursor() as cur:
            cur.execute(sql, (pid, year_start, year_end))
            return [dict(r) for r in cur.fetchall()]
    except Exception as exc:
        logger.debug("_get_vitals query failed for pid %s: %s", pid, exc)
        return []


def _get_prescriptions(pid: int, year: int) -> list[dict[str, Any]]:
    """Return active or issued prescriptions for the measurement year."""
    year_start, year_end = _year_range(year)
    sql = """
        SELECT
            drug,
            dosage,
            unit,
            date_added
        FROM prescriptions
        WHERE patient_id = %s
          AND active = 1
          AND date_added BETWEEN %s AND %s
    """
    try:
        with openemr_cursor() as cur:
            cur.execute(sql, (pid, year_start, year_end))
            return [dict(r) for r in cur.fetchall()]
    except Exception as exc:
        logger.debug("_get_prescriptions query failed for pid %s: %s", pid, exc)
        return []


def _get_encounter_dates(pid: int, year: int) -> list[str]:
    """Return encounter dates for the patient in the measurement year."""
    year_start, year_end = _year_range(year)
    sql = """
        SELECT date FROM form_encounter
        WHERE pid = %s
          AND date BETWEEN %s AND %s
        ORDER BY date DESC
    """
    try:
        with openemr_cursor() as cur:
            cur.execute(sql, (pid, year_start, year_end))
            return [str(r["date"])[:10] for r in cur.fetchall()]
    except Exception as exc:
        logger.debug("_get_encounter_dates failed for pid %s: %s", pid, exc)
        return []


# ---------------------------------------------------------------------------
# Component evaluators
# ---------------------------------------------------------------------------

def _eval_hba1c_tested(labs: list[dict]) -> tuple[bool, dict]:
    matches = [
        r for r in labs
        if _keyword_match(r.get("test_name", ""), _LAB_KEYWORDS["hba1c"])
        or _keyword_match(r.get("result_text", ""), _LAB_KEYWORDS["hba1c"])
    ]
    if matches:
        return True, {"test_name": matches[0].get("test_name"), "date": str(matches[0].get("date", ""))[:10]}
    return False, {}


def _eval_hba1c_controlled(labs: list[dict]) -> tuple[bool, dict]:
    """HbA1c < 8.0%."""
    for r in labs:
        if _keyword_match(r.get("test_name", ""), _LAB_KEYWORDS["hba1c"]) or \
                _keyword_match(r.get("result_text", ""), _LAB_KEYWORDS["hba1c"]):
            raw = str(r.get("result") or r.get("result_text") or "").strip().rstrip("%").lstrip(">")
            try:
                val = float(raw)
                return val < 8.0, {"value": val, "threshold": 8.0, "date": str(r.get("date", ""))[:10]}
            except (ValueError, TypeError):
                pass
    return False, {}


def _eval_bp_controlled(vitals: list[dict]) -> tuple[bool, dict]:
    """Most recent BP reading < 140/90."""
    for v in vitals:
        try:
            sys = int(v.get("systolic") or 0)
            dia = int(v.get("diastolic") or 0)
            if sys > 0 and dia > 0:
                controlled = sys < 140 and dia < 90
                return controlled, {
                    "systolic": sys,
                    "diastolic": dia,
                    "threshold": "140/90",
                    "date": str(v.get("date", ""))[:10],
                }
        except (ValueError, TypeError):
            pass
    return False, {}


def _eval_egfr_tested(labs: list[dict]) -> tuple[bool, dict]:
    matches = [r for r in labs if _keyword_match(r.get("test_name", ""), _LAB_KEYWORDS["egfr"])]
    if matches:
        return True, {"test_name": matches[0].get("test_name"), "date": str(matches[0].get("date", ""))[:10]}
    return False, {}


def _eval_uacr_tested(labs: list[dict]) -> tuple[bool, dict]:
    matches = [r for r in labs if _keyword_match(r.get("test_name", ""), _LAB_KEYWORDS["uacr"])]
    if matches:
        return True, {"test_name": matches[0].get("test_name"), "date": str(matches[0].get("date", ""))[:10]}
    return False, {}


def _eval_statin_prescribed(rxs: list[dict]) -> tuple[bool, dict]:
    for rx in rxs:
        if _keyword_match(rx.get("drug", ""), _STATIN_KEYWORDS):
            return True, {"drug": rx.get("drug"), "date": str(rx.get("date_added", ""))[:10]}
    return False, {}


def _eval_bone_density_or_med(labs: list[dict], rxs: list[dict]) -> tuple[bool, dict]:
    # Bone density scan keywords
    dxa_keywords = ["dexa", "dxa", "bone density", "bone mineral density", "bmd"]
    for r in labs:
        if _keyword_match(r.get("test_name", ""), dxa_keywords):
            return True, {"type": "bone_density_test", "date": str(r.get("date", ""))[:10]}
    for rx in rxs:
        if _keyword_match(rx.get("drug", ""), _OSTEO_MED_KEYWORDS):
            return True, {"type": "osteoporosis_medication", "drug": rx.get("drug"), "date": str(rx.get("date_added", ""))[:10]}
    return False, {}


def _eval_medication_review(encounters: list[str]) -> tuple[bool, dict]:
    """COA: proxy — patient had at least one encounter (medication review opportunity)."""
    if encounters:
        return True, {"last_encounter": encounters[0]}
    return False, {}


def _eval_functional_assessment(encounters: list[str]) -> tuple[bool, dict]:
    """COA: proxy — patient had at least one encounter."""
    if encounters:
        return True, {"last_encounter": encounters[0]}
    return False, {}


def _eval_pain_assessment(encounters: list[str]) -> tuple[bool, dict]:
    """COA: proxy — patient had at least one encounter."""
    if encounters:
        return True, {"last_encounter": encounters[0]}
    return False, {}


def _eval_eye_exam(labs: list[dict], encounters: list[str]) -> tuple[bool, dict]:
    """Retinal eye exam — look for ophthalmology procedure result or CPT-like entries."""
    eye_keywords = ["retinal", "eye exam", "ophthalmology", "fundus", "dilated eye", "diabetic eye"]
    for r in labs:
        if _keyword_match(r.get("test_name", ""), eye_keywords):
            return True, {"test_name": r.get("test_name"), "date": str(r.get("date", ""))[:10]}
    return False, {}


def _eval_nephropathy_screen(labs: list[dict]) -> tuple[bool, dict]:
    """Nephropathy screening — uACR or eGFR present."""
    uacr_found, uacr_ev = _eval_uacr_tested(labs)
    if uacr_found:
        return True, {**uacr_ev, "screen_type": "uACR"}
    egfr_found, egfr_ev = _eval_egfr_tested(labs)
    if egfr_found:
        return True, {**egfr_ev, "screen_type": "eGFR"}
    return False, {}


# ---------------------------------------------------------------------------
# Per-measure evaluator (public API)
# ---------------------------------------------------------------------------

def evaluate_measure(patient_id: int, measure_code: str, year: int, *, tenant_id: int | str = "") -> dict[str, Any]:
    """
    Evaluate a single HEDIS measure for one patient.

    Returns:
        met          – True if the patient satisfies all required components
        numerator    – True if the patient is in the numerator (measure met)
        denominator  – True if the patient is eligible for this measure
        components   – per-component result dict {name: {met, evidence}}
        gap          – human-readable description of the first unmet component, or None
        measure      – measure metadata
    """
    measure = HEDIS_MEASURES.get(measure_code.upper())
    if not measure:
        return {"error": f"Unknown measure code: {measure_code}"}

    year_start, year_end = _year_range(year)

    # Load patient demographics
    demo = _get_patient_demographics(patient_id, tenant_id)
    if not demo:
        return {"error": f"Patient {patient_id} not found"}

    dob = demo.get("DOB")
    age = _calculate_age(dob, year)
    sex = (demo.get("sex") or "").strip().lower()

    # Determine denominator eligibility
    denominator = _is_in_denominator(patient_id, measure_code, age, sex, year)
    if not denominator:
        return {
            "patient_id": patient_id,
            "measure_code": measure_code,
            "measure_name": measure["name"],
            "denominator": False,
            "numerator": False,
            "met": False,
            "components": {},
            "gap": "Patient not eligible for this measure (not in denominator)",
        }

    # Load clinical data
    labs = _get_labs(patient_id, year)
    vitals = _get_vitals(patient_id, year)
    rxs = _get_prescriptions(patient_id, year)
    encounters = _get_encounter_dates(patient_id, year)

    # Evaluate each component
    component_results: dict[str, Any] = {}
    for component in measure["components"]:
        met, evidence = _evaluate_component(component, labs, vitals, rxs, encounters)
        component_results[component] = {"met": met, "evidence": evidence}

    all_met = all(v["met"] for v in component_results.values())

    # First unmet component as the gap description
    gap: str | None = None
    if not all_met:
        unmet = [k for k, v in component_results.items() if not v["met"]]
        gap = _gap_description(measure_code, unmet[0]) if unmet else None

    return {
        "patient_id": patient_id,
        "measure_code": measure_code,
        "measure_name": measure["name"],
        "year": year,
        "denominator": True,
        "numerator": all_met,
        "met": all_met,
        "components": component_results,
        "gap": gap,
        "hcc_overlap": measure["hcc_overlap"],
    }


def _is_in_denominator(pid: int, measure_code: str, age: int, sex: str, year: int) -> bool:
    """Return True if the patient meets the denominator criteria for the measure."""
    codes = _get_active_diagnoses(pid, year)

    if measure_code == "CDC":
        return 18 <= age <= 75 and any(_has_icd_prefix(c, ["E10", "E11", "E13"]) for c in codes)
    elif measure_code == "CBP":
        return 18 <= age <= 85 and any(_has_icd_prefix(c, ["I10", "I11", "I12", "I13"]) for c in codes)
    elif measure_code == "COA":
        return age >= 66
    elif measure_code == "OMW":
        fracture_prefixes = ["M80", "S12", "S22", "S32", "S42", "S52", "S62", "S72", "S82", "S92"]
        return sex in ("female", "f") and 67 <= age <= 85 and any(_has_icd_prefix(c, fracture_prefixes) for c in codes)
    elif measure_code == "SPD":
        return 40 <= age <= 75 and any(_has_icd_prefix(c, ["E10", "E11", "E13"]) for c in codes)
    elif measure_code == "KED":
        return 18 <= age <= 85 and any(_has_icd_prefix(c, ["E10", "E11", "E13"]) for c in codes)
    return False


def _evaluate_component(
    component: str,
    labs: list[dict],
    vitals: list[dict],
    rxs: list[dict],
    encounters: list[str],
) -> tuple[bool, dict]:
    """Dispatch to the appropriate component evaluator."""
    dispatch = {
        "hba1c_tested": lambda: _eval_hba1c_tested(labs),
        "hba1c_controlled": lambda: _eval_hba1c_controlled(labs),
        "eye_exam": lambda: _eval_eye_exam(labs, encounters),
        "nephropathy_screen": lambda: _eval_nephropathy_screen(labs),
        "bp_controlled": lambda: _eval_bp_controlled(vitals),
        "egfr_tested": lambda: _eval_egfr_tested(labs),
        "uacr_tested": lambda: _eval_uacr_tested(labs),
        "statin_prescribed": lambda: _eval_statin_prescribed(rxs),
        "bone_density_or_med": lambda: _eval_bone_density_or_med(labs, rxs),
        "medication_review": lambda: _eval_medication_review(encounters),
        "functional_assessment": lambda: _eval_functional_assessment(encounters),
        "pain_assessment": lambda: _eval_pain_assessment(encounters),
    }
    fn = dispatch.get(component)
    if fn:
        return fn()
    return False, {}


_GAP_DESCRIPTIONS: dict[str, dict[str, str]] = {
    "CDC": {
        "hba1c_tested": "HbA1c test not documented in measurement year",
        "hba1c_controlled": "HbA1c not at goal (<8.0%)",
        "eye_exam": "Annual retinal/dilated eye exam not documented",
        "nephropathy_screen": "Nephropathy screening (uACR or eGFR) not documented",
        "bp_controlled": "Blood pressure not controlled (<140/90 mmHg)",
    },
    "CBP": {
        "bp_controlled": "Blood pressure not controlled (<140/90 mmHg)",
    },
    "COA": {
        "medication_review": "Medication review not documented",
        "functional_assessment": "Functional status assessment not documented",
        "pain_assessment": "Pain assessment not documented",
    },
    "OMW": {
        "bone_density_or_med": "No bone density test or osteoporosis medication found after fracture",
    },
    "SPD": {
        "statin_prescribed": "No statin medication prescribed in measurement year",
    },
    "KED": {
        "egfr_tested": "eGFR (kidney function) test not documented",
        "uacr_tested": "Urine albumin-to-creatinine ratio (uACR) not documented",
    },
}


def _gap_description(measure_code: str, component: str) -> str:
    return _GAP_DESCRIPTIONS.get(measure_code, {}).get(component, f"Component not met: {component}")


# ---------------------------------------------------------------------------
# Patient-level: all measures
# ---------------------------------------------------------------------------

def get_patient_measures(patient_id: int, year: int, *, tenant_id: int | str = "") -> dict[str, Any]:
    """
    Evaluate all HEDIS measures for a single patient.

    Returns a dict keyed by measure code, with met/unmet status per measure
    and a summary of total eligible measures and compliance rate.
    """
    results: dict[str, Any] = {}
    eligible_count = 0
    met_count = 0

    for code in HEDIS_MEASURES:
        result = evaluate_measure(patient_id, code, year, tenant_id=tenant_id)
        results[code] = result
        if result.get("denominator"):
            eligible_count += 1
            if result.get("met"):
                met_count += 1

    compliance_rate = round(met_count / eligible_count * 100, 1) if eligible_count > 0 else None

    demo = _get_patient_demographics(patient_id, tenant_id)
    name = ""
    if demo:
        name = f"{demo.get('fname', '')} {demo.get('lname', '')}".strip()

    return {
        "patient_id": patient_id,
        "patient_name": name,
        "year": year,
        "eligible_measure_count": eligible_count,
        "met_count": met_count,
        "compliance_rate": compliance_rate,
        "measures": results,
    }


# ---------------------------------------------------------------------------
# Population-level quality summary
# ---------------------------------------------------------------------------

def get_quality_summary(year: int, tenant_id: int) -> dict[str, Any]:
    """
    Population-level HEDIS measure compliance rates.

    Iterates over all patients, evaluates each measure, and aggregates
    eligible_count / met_count / compliance_rate per measure.

    Returns:
        year
        total_patients_evaluated
        measures: {code: {eligible_count, met_count, compliance_rate, gap_count}}
        overall_compliance_rate: mean compliance across all measures with eligible patients
    """
    # Load all patients — direct-DB patients from raf_intelligence.patients,
    # FHIR patients from emr_patient_matches joined to their active connection.
    if tenant_id is None:
        raise ValueError(
            "quality_service.get_quality_summary: tenant_id is required — "
            "refusing to query across all tenants (HIPAA multi-tenant isolation)"
        )
    tid = tenant_id
    conn_type = _active_conn_type(int(tid))

    if conn_type == "fhir_r4":
        with raf_cursor() as cur:
            cur.execute(
                "SELECT epm.id AS pid, epm.first_name AS fname, epm.last_name AS lname, "
                "epm.date_of_birth AS DOB, epm.sex "
                "FROM emr_patient_matches epm "
                "JOIN emr_connections ec ON ec.id = epm.connection_id "
                "WHERE ec.is_active = 1 AND ec.tenant_id = %s "
                "ORDER BY epm.id",
                (tid,),
            )
            patients = cur.fetchall()
    else:
        _sf, _sp = active_patients_subquery(int(tid), patient_id_column="id")
        with raf_cursor() as cur:
            cur.execute(
                f"SELECT id AS pid, first_name AS fname, last_name AS lname, dob AS DOB, sex "
                f"FROM patients WHERE is_active = 1 AND {_sf} AND tenant_id = %s ORDER BY id",
                (*_sp, tid),
            )
            patients = cur.fetchall()

    measure_stats: dict[str, dict[str, int]] = {
        code: {"eligible_count": 0, "met_count": 0, "gap_count": 0}
        for code in HEDIS_MEASURES
    }

    total_patients = len(patients)

    for patient in patients:
        pid = int(patient["pid"])
        dob = patient.get("DOB")
        sex = (patient.get("sex") or "").strip().lower()
        age = _calculate_age(dob, year)

        for code in HEDIS_MEASURES:
            # Fast denominator check before running full evaluation to reduce
            # the number of DB queries on large populations.
            codes = _get_active_diagnoses(pid, year)
            in_denom = _is_in_denominator_fast(pid, code, age, sex, year, codes)
            if not in_denom:
                continue

            result = evaluate_measure(pid, code, year, tenant_id=tid)
            measure_stats[code]["eligible_count"] += 1
            if result.get("met"):
                measure_stats[code]["met_count"] += 1
            else:
                measure_stats[code]["gap_count"] += 1

    # Compute compliance rates
    per_measure: dict[str, Any] = {}
    rates: list[float] = []
    for code, stats in measure_stats.items():
        elig = stats["eligible_count"]
        met = stats["met_count"]
        rate = round(met / elig * 100, 1) if elig > 0 else None
        per_measure[code] = {
            "measure_name": HEDIS_MEASURES[code]["name"],
            "eligible_count": elig,
            "met_count": met,
            "gap_count": stats["gap_count"],
            "compliance_rate": rate,
            "hcc_overlap": HEDIS_MEASURES[code]["hcc_overlap"],
        }
        if rate is not None:
            rates.append(rate)

    overall_rate = round(sum(rates) / len(rates), 1) if rates else None

    return {
        "year": year,
        "total_patients_evaluated": total_patients,
        "overall_compliance_rate": overall_rate,
        "measures": per_measure,
    }


def _is_in_denominator_fast(
    pid: int, measure_code: str, age: int, sex: str, year: int, codes: list[str]
) -> bool:
    """
    Denominator check that reuses pre-fetched diagnosis codes to avoid redundant
    DB calls during population-level iteration.
    """
    if measure_code == "CDC":
        return 18 <= age <= 75 and any(_has_icd_prefix(c, ["E10", "E11", "E13"]) for c in codes)
    elif measure_code == "SPD":
        # SPD denominator age is 40–75, not 18–75
        return 40 <= age <= 75 and any(_has_icd_prefix(c, ["E10", "E11", "E13"]) for c in codes)
    elif measure_code == "CBP":
        return 18 <= age <= 85 and any(_has_icd_prefix(c, ["I10", "I11", "I12", "I13"]) for c in codes)
    elif measure_code == "COA":
        return age >= 66
    elif measure_code == "OMW":
        fracture_prefixes = ["M80", "S12", "S22", "S32", "S42", "S52", "S62", "S72", "S82", "S92"]
        return sex in ("female", "f") and 67 <= age <= 85 and any(_has_icd_prefix(c, fracture_prefixes) for c in codes)
    elif measure_code == "KED":
        return 18 <= age <= 85 and any(_has_icd_prefix(c, ["E10", "E11", "E13"]) for c in codes)
    return False


# ---------------------------------------------------------------------------
# Care gap patients (population-level)
# ---------------------------------------------------------------------------

def get_care_gaps(year: int, measure_code: str | None = None, limit: int = 500, *, tenant_id: int) -> list[dict[str, Any]]:
    """
    Return patients with open HEDIS care gaps.

    Optionally filter to a single measure code.
    Each result row includes patient identity, measure, and specific gap description.
    Capped at ``limit`` patients (evaluated in pid order) to avoid long-running scans.
    """
    measure_codes = [measure_code.upper()] if measure_code else list(HEDIS_MEASURES.keys())
    # Validate supplied measure code
    for mc in measure_codes:
        if mc not in HEDIS_MEASURES:
            raise ValueError(f"Unknown measure code: {mc}")

    if tenant_id is None:
        raise ValueError(
            "quality_service.get_care_gaps: tenant_id is required — "
            "refusing to query across all tenants (HIPAA multi-tenant isolation)"
        )
    tid = tenant_id
    conn_type = _active_conn_type(int(tid))

    if conn_type == "fhir_r4":
        with raf_cursor() as cur:
            cur.execute(
                "SELECT epm.id AS pid, epm.first_name AS fname, epm.last_name AS lname, "
                "epm.date_of_birth AS DOB, epm.sex "
                "FROM emr_patient_matches epm "
                "JOIN emr_connections ec ON ec.id = epm.connection_id "
                "WHERE ec.is_active = 1 AND ec.tenant_id = %s "
                "ORDER BY epm.id LIMIT %s",
                (tid, limit),
            )
            patients = cur.fetchall()
    else:
        _sf, _sp = active_patients_subquery(int(tid), patient_id_column="id")
        with raf_cursor() as cur:
            cur.execute(
                f"SELECT id AS pid, first_name AS fname, last_name AS lname, dob AS DOB, sex "
                f"FROM patients WHERE is_active = 1 AND {_sf} AND tenant_id = %s ORDER BY id LIMIT %s",
                (*_sp, tid, limit),
            )
            patients = cur.fetchall()

    gaps: list[dict[str, Any]] = []

    for patient in patients:
        pid = int(patient["pid"])
        dob = patient.get("DOB")
        sex = (patient.get("sex") or "").strip().lower()
        age = _calculate_age(dob, year)
        name = f"{patient.get('fname', '')} {patient.get('lname', '')}".strip()
        codes = _get_active_diagnoses(pid, year)

        for mc in measure_codes:
            in_denom = _is_in_denominator_fast(pid, mc, age, sex, year, codes)
            if not in_denom:
                continue
            result = evaluate_measure(pid, mc, year, tenant_id=tid)
            if not result.get("met") and result.get("denominator"):
                gaps.append({
                    "patient_id": pid,
                    "patient_name": name,
                    "age": age,
                    "measure_code": mc,
                    "measure_name": HEDIS_MEASURES[mc]["name"],
                    "gap": result.get("gap"),
                    "hcc_overlap": HEDIS_MEASURES[mc]["hcc_overlap"],
                    "components": result.get("components", {}),
                })

    return gaps


# ---------------------------------------------------------------------------
# STARS rating estimation
# ---------------------------------------------------------------------------

# CMS STARS cut-points (approximate, based on publicly available benchmarks).
# Each measure has a list of [1-star, 2-star, 3-star, 4-star] thresholds (%).
# Compliance rate >= threshold earns that star rating.
_STARS_THRESHOLDS: dict[str, list[float]] = {
    "CDC": [50.0, 65.0, 75.0, 85.0],
    "CBP": [50.0, 65.0, 75.0, 85.0],
    "COA": [40.0, 55.0, 70.0, 82.0],
    "OMW": [35.0, 50.0, 65.0, 78.0],
    "SPD": [50.0, 65.0, 75.0, 85.0],
    "KED": [45.0, 60.0, 72.0, 83.0],
}


def _rate_to_stars(rate: float | None, thresholds: list[float]) -> float:
    """Convert a compliance rate % to a STARS score (1.0 – 5.0)."""
    if rate is None:
        return 1.0
    if rate >= thresholds[3]:
        return 5.0
    elif rate >= thresholds[2]:
        return 4.0
    elif rate >= thresholds[1]:
        return 3.0
    elif rate >= thresholds[0]:
        return 2.0
    return 1.0


def estimate_stars_rating(year: int, tenant_id: int | None = None) -> dict[str, Any]:
    """
    Estimate CMS STARS rating based on HEDIS measure performance.

    Calls get_quality_summary() to obtain compliance rates, then maps
    each rate to a 1-5 star score using approximate CMS cut-points.
    Returns a weighted-average overall STARS estimate.

    Returns:
        year
        estimated_stars        – weighted average star score (1.0 – 5.0)
        star_breakdown         – per-measure star scores and compliance rates
        interpretation         – qualitative label for the estimated STARS
    """
    summary = get_quality_summary(year, tenant_id=tenant_id)
    per_measure = summary.get("measures", {})

    star_breakdown: dict[str, Any] = {}
    weighted_sum = 0.0
    total_weight = 0

    for code, data in per_measure.items():
        rate = data.get("compliance_rate")
        thresholds = _STARS_THRESHOLDS.get(code, [50.0, 65.0, 75.0, 85.0])
        stars = _rate_to_stars(rate, thresholds)
        weight = HEDIS_MEASURES[code].get("stars_weight", 1)

        star_breakdown[code] = {
            "measure_name": data["measure_name"],
            "compliance_rate": rate,
            "stars": stars,
            "weight": weight,
            "eligible_count": data["eligible_count"],
        }

        if data["eligible_count"] > 0:
            weighted_sum += stars * weight
            total_weight += weight

    estimated_stars = round(weighted_sum / total_weight, 2) if total_weight > 0 else None

    # Qualitative interpretation
    if estimated_stars is None:
        interpretation = "Insufficient data"
    elif estimated_stars >= 4.5:
        interpretation = "Excellent (4-5 Stars)"
    elif estimated_stars >= 3.5:
        interpretation = "Above Average (4 Stars)"
    elif estimated_stars >= 2.5:
        interpretation = "Average (3 Stars)"
    elif estimated_stars >= 1.5:
        interpretation = "Below Average (2 Stars)"
    else:
        interpretation = "Poor (1 Star)"

    return {
        "year": year,
        "estimated_stars": estimated_stars,
        "interpretation": interpretation,
        "star_breakdown": star_breakdown,
        "disclaimer": (
            "This is an internal estimate based on available EHR data. "
            "Actual CMS STARS ratings use HEDIS hybrid/administrative methodology "
            "and official denominator/numerator criteria."
        ),
    }


# ---------------------------------------------------------------------------
# RAF / HEDIS overlap analysis
# ---------------------------------------------------------------------------

def get_raf_hedis_overlap() -> list[dict[str, Any]]:
    """
    Return the mapping between HCC codes and HEDIS measures that share
    clinical focus areas.  Used to identify which HCC-burdened patients
    also have open quality gaps that can be closed in a single visit.
    """
    # Build a reverse map: HCC code -> list of measures
    hcc_to_measures: dict[int, list[str]] = {}
    for code, measure in HEDIS_MEASURES.items():
        for hcc in measure.get("hcc_overlap", []):
            hcc_to_measures.setdefault(hcc, []).append(code)

    overlap: list[dict[str, Any]] = []
    for hcc_code, measure_codes in sorted(hcc_to_measures.items()):
        measures_detail = [
            {
                "code": mc,
                "name": HEDIS_MEASURES[mc]["name"],
                "components": HEDIS_MEASURES[mc]["components"],
            }
            for mc in measure_codes
        ]
        overlap.append({
            "hcc_code": hcc_code,
            "hcc_label": HEDIS_MEASURES[measure_codes[0]]["hcc_labels"][
                HEDIS_MEASURES[measure_codes[0]]["hcc_overlap"].index(hcc_code)
            ] if hcc_code in HEDIS_MEASURES[measure_codes[0]]["hcc_overlap"] else f"HCC {hcc_code}",
            "measures": measures_detail,
            "measure_count": len(measures_detail),
            "synergy_note": (
                "Addressing this HCC in clinical documentation also creates the opportunity "
                "to close associated HEDIS quality gaps in the same patient encounter."
            ),
        })

    return overlap
