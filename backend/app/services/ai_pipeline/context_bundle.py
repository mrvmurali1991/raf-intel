"""
Patient-context bundle assembly for LLM prompts.

Produces a structured, token-budget-aware PatientContextBundle that
downstream agents (suspect engine, chart-review summarizer, MEAT validator)
feed into Gemini/Claude as JSON. This module performs NO LLM calls.

Schema is the contract between the bundle builder and agents 5/6/7:

    PatientContextBundle {
        patient_id: UUID | str | int
        measurement_year: int            # default = current calendar year
        hcc_model_version: str           # "V24" | "V28"
        demographics:          Demographics
        active_problem_list:   list[ProblemEntry]
        prior_encounters_this_year: list[EncounterEntry]
        recent_labs_12mo:      list[LabEntry]     # abnormal-only when mode="abnormal_only"
        active_medications:    list[MedicationEntry]
        clinical_notes:        list[NoteEntry]    # on/after cutoff_date
        meta:                  BundleMeta         # counts, trims, char_count
    }

Table mapping (real columns discovered via recon, see claudeMd):
    patients                    (id, first_name, last_name, dob, sex, mrn, emr_pid, ...)
    fhir_conditions             (fhir_patient_id, icd10_codes, display, clinical_status, onset_date)
    fhir_encounters             (raf_patient_id, encounter_date, status, encounter_type,
                                 type_display, period_start, provider_name)
    fhir_observations           (fhir_patient_id, code, code_display, value_numeric,
                                 value_string, unit, effective_date, status)  # labs
    patient_medications         (patient_id, medication_name, fhir_id, start_date, status)
    form_clinical_notes         (pid, encounter, date, clinical_notes_type, description)
    emr_patient_matches.external_id  -> FHIR UUID

NOTE: form_clinical_notes uses columns `description` (note body) and
`clinical_notes_type` (category). Do NOT use `note` / `note_type` — those are
OpenEMR legacy aliases that raise 1054 Unknown column (see commit f012311).
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Literal

try:
    from pydantic import BaseModel, Field
    _HAS_PYDANTIC = True
except Exception:  # pragma: no cover
    logger.debug("swallowed exception", exc_info=True)
    _HAS_PYDANTIC = False
    BaseModel = object  # type: ignore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEFAULT_HCC_MODEL_VERSION = "V28"
TOKEN_BUDGET_CHARS = 30_000          # ~7.5k tokens
NOTE_TRUNCATE_CHARS = 4_000          # per-note hard cap

Mode = Literal["full", "abnormal_only"]


# ---------------------------------------------------------------------------
# Pydantic models (fallback to dataclasses if pydantic unavailable)
# ---------------------------------------------------------------------------

if _HAS_PYDANTIC:

    class Demographics(BaseModel):
        age: int | None = None
        sex: str | None = None
        dob: str | None = None          # ISO date
        mrn: str | None = None
        first_name: str | None = None
        last_name: str | None = None

    class ProblemEntry(BaseModel):
        icd10: str | None = None
        description: str | None = None
        onset_date: str | None = None
        clinical_status: str | None = None

    class EncounterEntry(BaseModel):
        encounter_id: str | None = None
        date: str | None = None
        type: str | None = None
        provider: str | None = None
        status: str | None = None

    class LabEntry(BaseModel):
        code: str | None = None
        name: str | None = None
        value: str | None = None        # str to carry numeric or categorical
        unit: str | None = None
        date: str | None = None
        abnormal_flag: bool = False

    class MedicationEntry(BaseModel):
        name: str | None = None
        rxnorm: str | None = None
        start_date: str | None = None
        status: str | None = None

    class NoteEntry(BaseModel):
        id: str | None = None
        encounter_id: str | None = None
        date: str | None = None
        type: str | None = None
        text: str = ""

    class BundleMeta(BaseModel):
        char_count: int = 0
        trimmed_notes: int = 0
        trimmed_labs: int = 0
        source_tables: list[str] = Field(default_factory=list)

    class PatientContextBundle(BaseModel):
        patient_id: str
        measurement_year: int
        hcc_model_version: str = DEFAULT_HCC_MODEL_VERSION
        cutoff_date: str | None = None
        mode: Mode = "full"
        demographics: Demographics = Field(default_factory=Demographics)
        active_problem_list: list[ProblemEntry] = Field(default_factory=list)
        prior_encounters_this_year: list[EncounterEntry] = Field(default_factory=list)
        recent_labs_12mo: list[LabEntry] = Field(default_factory=list)
        active_medications: list[MedicationEntry] = Field(default_factory=list)
        clinical_notes: list[NoteEntry] = Field(default_factory=list)
        meta: BundleMeta = Field(default_factory=BundleMeta)

else:  # pragma: no cover - dataclass fallback

    @dataclass
    class Demographics:
        age: int | None = None
        sex: str | None = None
        dob: str | None = None
        mrn: str | None = None
        first_name: str | None = None
        last_name: str | None = None

    @dataclass
    class ProblemEntry:
        icd10: str | None = None
        description: str | None = None
        onset_date: str | None = None
        clinical_status: str | None = None

    @dataclass
    class EncounterEntry:
        encounter_id: str | None = None
        date: str | None = None
        type: str | None = None
        provider: str | None = None
        status: str | None = None

    @dataclass
    class LabEntry:
        code: str | None = None
        name: str | None = None
        value: str | None = None
        unit: str | None = None
        date: str | None = None
        abnormal_flag: bool = False

    @dataclass
    class MedicationEntry:
        name: str | None = None
        rxnorm: str | None = None
        start_date: str | None = None
        status: str | None = None

    @dataclass
    class NoteEntry:
        id: str | None = None
        encounter_id: str | None = None
        date: str | None = None
        type: str | None = None
        text: str = ""

    @dataclass
    class BundleMeta:
        char_count: int = 0
        trimmed_notes: int = 0
        trimmed_labs: int = 0
        source_tables: list = field(default_factory=list)

    @dataclass
    class PatientContextBundle:
        patient_id: str
        measurement_year: int
        hcc_model_version: str = DEFAULT_HCC_MODEL_VERSION
        cutoff_date: str | None = None
        mode: Mode = "full"
        demographics: Demographics = field(default_factory=Demographics)
        active_problem_list: list = field(default_factory=list)
        prior_encounters_this_year: list = field(default_factory=list)
        recent_labs_12mo: list = field(default_factory=list)
        active_medications: list = field(default_factory=list)
        clinical_notes: list = field(default_factory=list)
        meta: BundleMeta = field(default_factory=BundleMeta)


# ---------------------------------------------------------------------------
# DB loaders — each takes a cursor so tests can inject fakes
# ---------------------------------------------------------------------------

def _iso(d: Any) -> str | None:
    if d is None:
        return None
    if isinstance(d, (date, datetime)):
        return d.isoformat()[:10]
    return str(d)[:10]


def _load_demographics(cur, patient_id) -> tuple[Demographics, str | None]:
    """Returns (demographics, fhir_patient_uuid_or_none)."""
    cur.execute(
        "SELECT id, first_name, last_name, dob, sex, mrn, emr_pid, data_source "
        "FROM patients WHERE id = %s LIMIT 1",
        (patient_id,),
    )
    row = cur.fetchone()
    if not row:
        return Demographics(), None

    dob = row.get("dob")
    age = None
    if dob:
        try:
            d = dob if isinstance(dob, date) else datetime.fromisoformat(str(dob)).date()
            today = date.today()
            age = today.year - d.year - ((today.month, today.day) < (d.month, d.day))
        except Exception:
            logger.debug("swallowed exception", exc_info=True)
            age = None

    demo = Demographics(
        age=age,
        sex=row.get("sex"),
        dob=_iso(dob),
        mrn=row.get("mrn"),
        first_name=row.get("first_name"),
        last_name=row.get("last_name"),
    )
    fhir_uuid = None
    if str(row.get("data_source") or "").lower() == "fhir":
        fhir_uuid = str(row.get("emr_pid") or "").strip() or None
    return demo, fhir_uuid


def _load_problems(cur, patient_id, fhir_uuid) -> list[ProblemEntry]:
    out: list[ProblemEntry] = []
    if fhir_uuid:
        cur.execute(
            "SELECT icd10_codes, display, onset_date, clinical_status "
            "FROM fhir_conditions "
            "WHERE fhir_patient_id = %s "
            "AND clinical_status IN ('active','recurrence','relapse','') "
            "ORDER BY onset_date DESC LIMIT 200",
            (fhir_uuid,),
        )
        for r in cur.fetchall() or []:
            out.append(ProblemEntry(
                icd10=r.get("icd10_codes"),
                description=r.get("display"),
                onset_date=_iso(r.get("onset_date")),
                clinical_status=r.get("clinical_status"),
            ))
    else:
        cur.execute(
            "SELECT DISTINCT ed.icd10_code AS icd10, ed.description AS display, "
            "e.encounter_date AS onset_date "
            "FROM encounter_diagnoses ed "
            "JOIN encounters e ON e.id = ed.encounter_id "
            "WHERE ed.patient_id = %s "
            "ORDER BY e.encounter_date DESC LIMIT 200",
            (patient_id,),
        )
        for r in cur.fetchall() or []:
            out.append(ProblemEntry(
                icd10=r.get("icd10"),
                description=r.get("display"),
                onset_date=_iso(r.get("onset_date")),
                clinical_status="active",
            ))
    return out


def _load_encounters(cur, patient_id, measurement_year: int) -> list[EncounterEntry]:
    year_start = date(measurement_year, 1, 1)
    year_end = date(measurement_year, 12, 31)
    cur.execute(
        "SELECT id, encounter_date, status, encounter_type, type_display, provider_name "
        "FROM fhir_encounters "
        "WHERE raf_patient_id = %s "
        "  AND encounter_date BETWEEN %s AND %s "
        "ORDER BY encounter_date DESC LIMIT 500",
        (patient_id, year_start, year_end),
    )
    rows = cur.fetchall() or []
    if not rows:
        # Legacy encounters table fallback
        cur.execute(
            "SELECT id, encounter_date, encounter_type, provider_name, status "
            "FROM encounters "
            "WHERE patient_id = %s AND encounter_date BETWEEN %s AND %s "
            "ORDER BY encounter_date DESC LIMIT 500",
            (patient_id, year_start, year_end),
        )
        rows = cur.fetchall() or []
    return [
        EncounterEntry(
            encounter_id=(str(r.get("id")) if r.get("id") is not None else None),
            date=_iso(r.get("encounter_date")),
            type=r.get("type_display") or r.get("encounter_type"),
            provider=r.get("provider_name"),
            status=r.get("status"),
        )
        for r in rows
    ]


def _load_labs(cur, patient_id, fhir_uuid, cutoff_date: date, mode: Mode) -> list[LabEntry]:
    window_start = cutoff_date - timedelta(days=365)
    out: list[LabEntry] = []
    if fhir_uuid:
        cur.execute(
            "SELECT code, code_display, value_numeric, value_string, unit, "
            "       effective_date, status "
            "FROM fhir_observations "
            "WHERE fhir_patient_id = %s "
            "  AND category = 'laboratory' "
            "  AND effective_date BETWEEN %s AND %s "
            "ORDER BY effective_date DESC LIMIT 500",
            (fhir_uuid, window_start, cutoff_date),
        )
        for r in cur.fetchall() or []:
            val = r.get("value_numeric")
            val_str = str(val) if val is not None else (r.get("value_string") or "")
            status = (r.get("status") or "").lower()
            abn = status in ("abnormal", "high", "low", "critical")
            if mode == "abnormal_only" and not abn:
                continue
            out.append(LabEntry(
                code=r.get("code"),
                name=r.get("code_display"),
                value=val_str,
                unit=r.get("unit"),
                date=_iso(r.get("effective_date")),
                abnormal_flag=abn,
            ))
    return out


def _load_medications(cur, patient_id) -> list[MedicationEntry]:
    cur.execute(
        "SELECT medication_name, fhir_id, start_date, status "
        "FROM patient_medications "
        "WHERE patient_id = %s "
        "  AND (status = 'active' OR is_active = 1) "
        "ORDER BY start_date DESC LIMIT 200",
        (patient_id,),
    )
    rows = cur.fetchall() or []
    return [
        MedicationEntry(
            name=r.get("medication_name"),
            rxnorm=r.get("fhir_id"),   # rxnorm not stored separately; fhir_id is the handle
            start_date=_iso(r.get("start_date")),
            status=r.get("status"),
        )
        for r in rows
    ]


def _load_notes(cur, patient_id, emr_pid, cutoff_date: date) -> list[NoteEntry]:
    """Pulls OpenEMR clinical notes on/after cutoff_date. Uses `description`
    and `clinical_notes_type` per OpenEMR schema (commit f012311)."""
    if not emr_pid:
        return []
    try:
        cur.execute(
            "SELECT id, pid, encounter, date, "
            "       COALESCE(clinical_notes_type, 'clinical_note') AS note_type, "
            "       COALESCE(description, '') AS note_text "
            "FROM form_clinical_notes "
            "WHERE pid = %s AND date >= %s "
            "ORDER BY date DESC LIMIT 200",
            (emr_pid, cutoff_date),
        )
    except Exception as exc:
        logger.debug("form_clinical_notes unavailable: %s", exc)
        return []
    rows = cur.fetchall() or []
    return [
        NoteEntry(
            id=str(r.get("id")),
            encounter_id=(str(r.get("encounter")) if r.get("encounter") is not None else None),
            date=_iso(r.get("date")),
            type=r.get("note_type"),
            text=(r.get("note_text") or "")[:NOTE_TRUNCATE_CHARS],
        )
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Trim helpers
# ---------------------------------------------------------------------------

def _char_count(bundle: PatientContextBundle) -> int:
    return len(json.dumps(to_llm_payload(bundle), default=str))


def _trim_to_budget(bundle: PatientContextBundle, budget: int) -> None:
    """Mutates bundle in place: drops oldest notes, then non-abnormal labs,
    until under budget. Logs what was trimmed into meta."""
    # Pass 1: trim non-abnormal labs oldest-first
    if _char_count(bundle) > budget:
        non_abn = [l for l in bundle.recent_labs_12mo if not getattr(l, "abnormal_flag", False)]
        abn = [l for l in bundle.recent_labs_12mo if getattr(l, "abnormal_flag", False)]
        non_abn_sorted = sorted(non_abn, key=lambda l: getattr(l, "date", "") or "", reverse=True)
        while non_abn_sorted and _char_count(bundle) > budget:
            dropped = non_abn_sorted.pop()  # oldest
            bundle.meta.trimmed_labs += 1
            logger.info("bundle trim: dropped lab code=%s date=%s", getattr(dropped, "code", None), getattr(dropped, "date", None))
            bundle.recent_labs_12mo = abn + non_abn_sorted

    # Pass 2: trim oldest notes
    if _char_count(bundle) > budget:
        notes_sorted = sorted(bundle.clinical_notes, key=lambda n: getattr(n, "date", "") or "", reverse=True)
        while notes_sorted and _char_count(bundle) > budget:
            dropped = notes_sorted.pop()
            bundle.meta.trimmed_notes += 1
            logger.info("bundle trim: dropped note id=%s date=%s", getattr(dropped, "id", None), getattr(dropped, "date", None))
            bundle.clinical_notes = notes_sorted

    bundle.meta.char_count = _char_count(bundle)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def assemble_bundle(
    patient_id: Any,
    cutoff_date: date | None = None,
    mode: Mode = "full",
    *,
    hcc_model_version: str = DEFAULT_HCC_MODEL_VERSION,
    measurement_year: int | None = None,
    cursor=None,
    token_budget_chars: int = TOKEN_BUDGET_CHARS,
) -> PatientContextBundle:
    """Assemble a patient-context bundle for LLM prompts.

    Args:
        patient_id:         internal `patients.id`
        cutoff_date:        notes are included if date >= cutoff_date.
                            Defaults to 12 months before today.
        mode:               "full" returns all labs; "abnormal_only" filters
                            to abnormal/high/low/critical observations.
        hcc_model_version:  "V24" or "V28"
        measurement_year:   default current calendar year
        cursor:             optional DB cursor (dict-style). If None, acquires
                            one from app.db.raf_cursor().
        token_budget_chars: JSON-serialized-char cap. Default 30,000.

    Returns:
        PatientContextBundle
    """
    today = date.today()
    if cutoff_date is None:
        cutoff_date = today - timedelta(days=365)
    if measurement_year is None:
        measurement_year = today.year

    def _build(cur) -> PatientContextBundle:
        demo, fhir_uuid = _load_demographics(cur, patient_id)
        # Need emr_pid again for notes (OpenEMR pid) — refetch light
        cur.execute(
            "SELECT emr_pid FROM patients WHERE id = %s LIMIT 1", (patient_id,)
        )
        prow = cur.fetchone() or {}
        emr_pid = prow.get("emr_pid")

        bundle = PatientContextBundle(
            patient_id=str(patient_id),
            measurement_year=measurement_year,
            hcc_model_version=hcc_model_version,
            cutoff_date=cutoff_date.isoformat(),
            mode=mode,
            demographics=demo,
            active_problem_list=_load_problems(cur, patient_id, fhir_uuid),
            prior_encounters_this_year=_load_encounters(cur, patient_id, measurement_year),
            recent_labs_12mo=_load_labs(cur, patient_id, fhir_uuid, cutoff_date + timedelta(days=365), mode),
            active_medications=_load_medications(cur, patient_id),
            clinical_notes=_load_notes(cur, patient_id, emr_pid, cutoff_date),
        )
        bundle.meta.source_tables = [
            "patients", "fhir_conditions", "fhir_encounters",
            "fhir_observations", "patient_medications", "form_clinical_notes",
        ]
        bundle.meta.char_count = _char_count(bundle)
        _trim_to_budget(bundle, token_budget_chars)
        return bundle

    if cursor is not None:
        return _build(cursor)

    # Acquire a cursor lazily so tests that inject `cursor=` don't need DB.
    from app.db import raf_cursor  # type: ignore
    with raf_cursor() as cur:
        return _build(cur)


def to_llm_payload(bundle: PatientContextBundle) -> dict:
    """Serialize bundle to plain JSON-safe dict for LLM prompts. This is the
    exact shape agents 5/6/7 read."""
    if _HAS_PYDANTIC and isinstance(bundle, BaseModel):
        data = bundle.model_dump()
    else:
        data = asdict(bundle)  # type: ignore
    # Fixed top-level key order for prompt stability
    return {
        "patient_id": data.get("patient_id"),
        "measurement_year": data.get("measurement_year"),
        "hcc_model_version": data.get("hcc_model_version"),
        "cutoff_date": data.get("cutoff_date"),
        "mode": data.get("mode"),
        "demographics": data.get("demographics"),
        "active_problem_list": data.get("active_problem_list"),
        "prior_encounters_this_year": data.get("prior_encounters_this_year"),
        "recent_labs_12mo": data.get("recent_labs_12mo"),
        "active_medications": data.get("active_medications"),
        "clinical_notes": data.get("clinical_notes"),
        "meta": data.get("meta"),
    }


__all__ = [
    "PatientContextBundle",
    "Demographics",
    "ProblemEntry",
    "EncounterEntry",
    "LabEntry",
    "MedicationEntry",
    "NoteEntry",
    "BundleMeta",
    "assemble_bundle",
    "to_llm_payload",
    "DEFAULT_HCC_MODEL_VERSION",
    "TOKEN_BUDGET_CHARS",
]
