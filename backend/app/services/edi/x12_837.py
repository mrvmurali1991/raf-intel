"""
X12 837 5010 — Health Care Claim / Encounter (Professional 005010X222A1).

This module emits *syntactically valid* 837P transactions for the EDPS
submission cycle.  Two entry points:

    generate_837_encounter(patient_id, encounter_id, hcc_codes, submitter_info)
        — single-encounter 837 file.

    generate_837_batch(patient_ids, payment_year, submitter_info, ...)
        — batched 837 file (one ST..SE per patient).

What this module does NOT do (out of scope for the MVP — see TODO):

    - Trading-partner-specific element overrides (each clearinghouse cares
      about a slightly different subset of optional segments).
    - Subscriber/dependent (2000C/2010CA) split when patient ≠ subscriber.
    - Service-line price/charge logic (CLM02 charge amount uses a deterministic
      placeholder of 0.00 — RA plans submit encounter data, not billable claims).
    - 999 / 277CA acknowledgement parsing on the inbound side.

The output is plain text; the caller is responsible for byte-level transport
(SFTP, AS2, REST drop-box).
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any, Iterable

from app.services.edi import common as x12
from app.services.edi.common import (
    ccyymmdd,
    clean,
    count_segments,
    ge_segment,
    gs_segment,
    iea_segment,
    isa_segment,
    join_segments,
    new_gs_control_number,
    new_isa_control_number,
    new_st_control_number,
    normalize_icd10,
    se_segment,
    segment,
    st_segment,
    upper,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Default submitter / receiver — overridden via submitter_info
# ---------------------------------------------------------------------------

_DEFAULT_SUBMITTER = {
    "submitter_name":      "RAF INTELLIGENCE",
    "submitter_id":        "RAFINTEL",
    "submitter_etin":      "RAFINTEL",
    "submitter_contact":   "DEMO CONTACT",
    "submitter_phone":     "5555550100",
    "receiver_name":       "CMS EDPS",
    "receiver_id":         "CMSEDPS",
    "billing_provider_npi":"1234567893",
    "billing_provider_name":"DEMO PROVIDER GROUP",
    "billing_provider_tax_id":"123456789",
    "billing_provider_taxonomy":"207Q00000X",
    "billing_provider_address":"123 MAIN ST",
    "billing_provider_city":"ANYTOWN",
    "billing_provider_state":"NY",
    "billing_provider_zip":"100010000",
    "test_indicator":      "T",
}


def _merge_submitter(submitter_info: dict | None) -> dict:
    merged = dict(_DEFAULT_SUBMITTER)
    if submitter_info:
        merged.update({k: v for k, v in submitter_info.items() if v is not None})
    return merged


# ---------------------------------------------------------------------------
# Patient / encounter / HCC look-ups
# ---------------------------------------------------------------------------

def _load_patient(patient_id: int) -> dict[str, Any]:
    """Return a normalized patient dict from the RAF DB.  Returns {} if missing."""
    try:
        from app.db import raf_cursor

        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT id, first_name, last_name, middle_name, dob, sex,
                       address, city, state, zip, mrn
                FROM patients
                WHERE id = %s
                """,
                (patient_id,),
            )
            row = cur.fetchone() or {}
    except Exception as exc:
        logger.warning("_load_patient(%s) failed: %s", patient_id, exc)
        row = {}
    return row


def _load_patient_mbi(patient_id: int) -> str:
    """Best-effort MBI/HICN resolution.  Empty string when not available."""
    try:
        from app.db import raf_cursor

        with raf_cursor() as cur:
            cur.execute(
                "SELECT hicn_mbi FROM raf_patient_demographics WHERE patient_id = %s",
                (patient_id,),
            )
            row = cur.fetchone() or {}
            return clean(row.get("hicn_mbi"))
    except Exception:
        return ""


def _load_encounter(encounter_id: int | None, patient_id: int) -> dict[str, Any]:
    """Return encounter info (date_of_service, npi, place_of_service).

    If encounter_id is None, fall back to the latest encounter for the patient.
    """
    try:
        from app.db import raf_cursor

        with raf_cursor() as cur:
            if encounter_id is not None:
                cur.execute(
                    """
                    SELECT id, patient_id, encounter_date, provider_npi,
                           place_of_service, encounter_type
                    FROM encounters
                    WHERE id = %s AND patient_id = %s
                    LIMIT 1
                    """,
                    (encounter_id, patient_id),
                )
            else:
                cur.execute(
                    """
                    SELECT id, patient_id, encounter_date, provider_npi,
                           place_of_service, encounter_type
                    FROM encounters
                    WHERE patient_id = %s
                    ORDER BY encounter_date DESC
                    LIMIT 1
                    """,
                    (patient_id,),
                )
            row = cur.fetchone() or {}
    except Exception as exc:
        logger.warning("_load_encounter(%s,%s) failed: %s", encounter_id, patient_id, exc)
        row = {}
    return row


def _load_hcc_icd10s_for_patient(patient_id: int, payment_year: int | None = None) -> list[str]:
    """Return ICD-10 codes (deduped, normalised) confirmed for the patient."""
    icd_codes: list[str] = []
    try:
        from app.db import raf_cursor

        with raf_cursor() as cur:
            if payment_year is not None:
                cur.execute(
                    """
                    SELECT icd10_codes FROM raf_patient_hcc
                    WHERE patient_id = %s
                      AND measurement_year = %s
                      AND (status = 'confirmed' OR status IS NULL)
                    """,
                    (patient_id, payment_year),
                )
            else:
                cur.execute(
                    """
                    SELECT icd10_codes FROM raf_patient_hcc
                    WHERE patient_id = %s
                      AND (status = 'confirmed' OR status IS NULL)
                    """,
                    (patient_id,),
                )
            rows = cur.fetchall() or []
    except Exception as exc:
        logger.warning("_load_hcc_icd10s_for_patient(%s) failed: %s", patient_id, exc)
        rows = []

    import json
    for r in rows:
        raw = r.get("icd10_codes")
        if not raw:
            continue
        items: list[str]
        if isinstance(raw, str):
            stripped = raw.strip()
            if stripped.startswith("["):
                try:
                    items = json.loads(stripped)
                except Exception:
                    items = [x.strip() for x in stripped.split(",")]
            else:
                items = [x.strip() for x in stripped.split(",")]
        elif isinstance(raw, list):
            items = list(raw)
        else:
            continue
        for c in items:
            n = normalize_icd10(c)
            if n and n not in icd_codes:
                icd_codes.append(n)
    return icd_codes


# ---------------------------------------------------------------------------
# 837 Loop builders
# ---------------------------------------------------------------------------

def _bht_segment(*, batch_id: str, originator_app: str = "RAFINTEL") -> str:
    """BHT — Beginning of Hierarchical Transaction (loop 1000 header)."""
    now = datetime.now(timezone.utc)
    return segment(
        "BHT",
        "0019",          # BHT01 hierarchical structure (information source / subscriber / patient)
        "00",            # BHT02 transaction set purpose: original
        clean(batch_id, 30) or originator_app,
        ccyymmdd(now),
        now.strftime("%H%M"),
        "CH",            # BHT06 chargeable
    )


def _submitter_loop(s: dict) -> list[str]:
    """1000A — Submitter (NM1*41) + PER (contact)."""
    return [
        segment(
            "NM1",
            "41",                              # entity identifier code (submitter)
            "2",                               # 2 = non-person entity
            upper(s["submitter_name"], 35),
            "", "", "", "",
            "46",                              # ID code qualifier — ETIN
            upper(s["submitter_etin"], 35),
        ),
        segment(
            "PER",
            "IC",
            upper(s.get("submitter_contact", ""), 35),
            "TE",
            x12.digits_only(s.get("submitter_phone", ""), 12),
        ),
    ]


def _receiver_loop(s: dict) -> list[str]:
    """1000B — Receiver (NM1*40)."""
    return [
        segment(
            "NM1",
            "40",
            "2",
            upper(s["receiver_name"], 35),
            "", "", "", "",
            "46",
            upper(s["receiver_id"], 35),
        )
    ]


def _billing_provider_loop(s: dict, hl_id: int) -> list[str]:
    """2000A / 2010AA — Billing Provider hierarchy."""
    seg = [
        # HL — top-level provider
        segment("HL", str(hl_id), "", "20", "1"),
        segment("PRV", "BI", "PXC", upper(s.get("billing_provider_taxonomy", ""))),
        # 2010AA — billing provider name
        segment(
            "NM1",
            "85",
            "2",
            upper(s["billing_provider_name"], 35),
            "", "", "", "",
            "XX",
            x12.digits_only(s["billing_provider_npi"], 10),
        ),
        segment("N3", upper(s.get("billing_provider_address", ""), 55)),
        segment(
            "N4",
            upper(s.get("billing_provider_city", ""), 30),
            upper(s.get("billing_provider_state", ""), 2),
            clean(s.get("billing_provider_zip", ""), 15),
        ),
        segment("REF", "EI", x12.digits_only(s.get("billing_provider_tax_id", ""), 12)),
    ]
    return seg


def _subscriber_loop(
    *,
    hl_id: int,
    parent_hl_id: int,
    patient: dict,
    mbi: str,
) -> list[str]:
    """2000B — Subscriber.  In Medicare Advantage the patient IS the subscriber."""
    return [
        segment("HL", str(hl_id), str(parent_hl_id), "22", "0"),
        segment("SBR", "P", "18", "", "", "", "", "", "", "MB"),  # MB = Medicare Part B
        segment(
            "NM1",
            "IL",                                       # insured/subscriber
            "1",                                        # person
            upper(patient.get("last_name", ""), 35),
            upper(patient.get("first_name", ""), 25),
            upper(patient.get("middle_name", ""), 25),
            "", "",
            "MI",                                       # member identification number
            clean(mbi, 80) or f"PID{patient.get('id','UNKNOWN')}",
        ),
        segment(
            "N3",
            upper(patient.get("address", ""), 55),
        ),
        segment(
            "N4",
            upper(patient.get("city", ""), 30),
            upper(patient.get("state", ""), 2),
            x12.digits_only(patient.get("zip", ""), 15),
        ),
        segment(
            "DMG",
            "D8",
            ccyymmdd(patient.get("dob")),
            upper(patient.get("sex", "U"), 1) or "U",
        ),
    ]


def _clm_and_diagnosis_segments(
    *,
    encounter: dict,
    icd10_codes: list[str],
    claim_id: str,
) -> list[str]:
    """2300 — Claim header + diagnosis (HI*BK / BF)."""
    eos_date = encounter.get("encounter_date")
    pos = clean(encounter.get("place_of_service", "11"))  # 11 = office
    facility_code = pos or "11"

    segs: list[str] = [
        segment(
            "CLM",
            clean(claim_id, 38),
            "0.00",                              # CLM02 charge amount (RA encounter — no charge)
            "", "",
            [facility_code, "B", "1"],           # CLM05 — place of service composite
            "Y", "A", "Y", "Y",                  # CLM06–09 supplementary flags
        ),
        segment("DTP", "472", "D8", ccyymmdd(eos_date)),
    ]

    # HI segment: principal diagnosis (BK) + up to 11 add'l (BF), per 5010 spec
    if icd10_codes:
        principal = icd10_codes[0]
        addl = icd10_codes[1:12]
        composites: list[list[str]] = [["ABK", principal]]
        for code in addl:
            composites.append(["ABF", code])
        # X12 HI elements are composite — we pass them as tuples
        segs.append(segment("HI", *composites))
    return segs


def _service_line(*, line_no: int, encounter: dict) -> list[str]:
    """2400 — Service Line.

    For encounter (non-billable) submissions we use a placeholder HCPCS
    (99499 — unlisted E/M) and $0 charge.  Trading partners that mandate
    real CPT codes will override this layer.
    """
    eos = encounter.get("encounter_date")
    npi = x12.digits_only(encounter.get("provider_npi", ""), 10)
    segs = [
        segment(
            "LX",
            str(line_no),
        ),
        segment(
            "SV1",
            ["HC", "99499"],
            "0.00",
            "UN",
            "1",
            clean(encounter.get("place_of_service", "11")),
            "",
            "1",
        ),
        segment("DTP", "472", "D8", ccyymmdd(eos)),
    ]
    if npi:
        segs.append(
            segment(
                "NM1",
                "82",                       # rendering provider
                "1",
                "", "", "", "", "",
                "XX",
                npi,
            )
        )
    return segs


# ---------------------------------------------------------------------------
# Top-level entry points
# ---------------------------------------------------------------------------

def _build_transaction_set(
    *,
    patient_id: int,
    encounter_id: int | None,
    icd10_codes: list[str],
    submitter: dict,
    st_idx: int,
    hl_starting_id: int = 1,
    claim_id: str | None = None,
) -> tuple[str, int]:
    """Build ONE ST..SE block for a single patient/encounter.

    Returns (st_text, next_hl_id).
    """
    st_ctrl = new_st_control_number(st_idx)

    patient = _load_patient(patient_id) or {"id": patient_id}
    mbi = _load_patient_mbi(patient_id)
    encounter = _load_encounter(encounter_id, patient_id) or {
        "encounter_date": date.today().isoformat(),
        "place_of_service": "11",
    }

    cleaned_icd10 = [normalize_icd10(c) for c in icd10_codes if c]
    cleaned_icd10 = [c for c in cleaned_icd10 if c]
    if not cleaned_icd10:
        # We still emit a syntactically valid claim so it can be inspected,
        # but flag this in the logs — most trading partners will reject it.
        logger.warning(
            "837 transaction set has no valid ICD-10 codes "
            "(patient_id=%s, encounter_id=%s)",
            patient_id,
            encounter_id,
        )

    claim_id_final = claim_id or f"CLM{patient_id}-{encounter.get('id', 0)}-{st_idx:04d}"

    body_segments: list[str] = []
    body_segments.append(st_segment(transaction="837", control_number=st_ctrl))
    body_segments.append(_bht_segment(batch_id=f"BHT{st_idx}"))
    body_segments.extend(_submitter_loop(submitter))
    body_segments.extend(_receiver_loop(submitter))

    hl_id = hl_starting_id
    body_segments.extend(_billing_provider_loop(submitter, hl_id))
    parent_hl = hl_id
    hl_id += 1

    body_segments.extend(
        _subscriber_loop(
            hl_id=hl_id,
            parent_hl_id=parent_hl,
            patient=patient,
            mbi=mbi,
        )
    )
    hl_id += 1

    body_segments.extend(
        _clm_and_diagnosis_segments(
            encounter=encounter,
            icd10_codes=cleaned_icd10,
            claim_id=claim_id_final,
        )
    )
    body_segments.extend(_service_line(line_no=1, encounter=encounter))

    body_text = join_segments(body_segments)
    seg_count = count_segments(body_text) + 1   # +1 for SE itself
    body_text += se_segment(segment_count=seg_count, control_number=st_ctrl) + "\n"

    return body_text, hl_id


def generate_837_encounter(
    patient_id: int,
    encounter_id: int | None,
    hcc_codes: Iterable[str] | None = None,
    submitter_info: dict | None = None,
) -> str:
    """Generate a complete 837 5010 file for a single patient/encounter.

    Parameters
    ----------
    patient_id : int
        RAF patient ID.
    encounter_id : int | None
        Encounter ID; if None, the latest encounter for the patient is used.
    hcc_codes : iterable of ICD-10 strings (NOT HCC codes — name kept for
        backward-compatibility with the gap-7 spec).  If empty, codes are
        loaded from raf_patient_hcc.
    submitter_info : dict | None
        Overrides for submitter / receiver / billing-provider defaults.

    Returns
    -------
    str
        Complete 5010 EDI text — ISA…IEA.
    """
    submitter = _merge_submitter(submitter_info)
    icd10s = [normalize_icd10(c) for c in (hcc_codes or [])]
    icd10s = [c for c in icd10s if c]
    if not icd10s:
        icd10s = _load_hcc_icd10s_for_patient(patient_id)

    isa_ctrl = new_isa_control_number()
    gs_ctrl = new_gs_control_number()
    now = datetime.now(timezone.utc)

    isa = isa_segment(
        sender_id=submitter["submitter_id"],
        receiver_id=submitter["receiver_id"],
        control_number=isa_ctrl,
        test_indicator=submitter.get("test_indicator", "T"),
        interchange_date=now,
    )
    gs = gs_segment(
        transaction="837",
        sender_code=submitter["submitter_id"],
        receiver_code=submitter["receiver_id"],
        control_number=gs_ctrl,
        transaction_date=now,
        version="005010X222A1",
    )

    st_text, _ = _build_transaction_set(
        patient_id=patient_id,
        encounter_id=encounter_id,
        icd10_codes=icd10s,
        submitter=submitter,
        st_idx=1,
    )

    ge = ge_segment(num_transactions=1, control_number=gs_ctrl)
    iea = iea_segment(num_functional_groups=1, control_number=isa_ctrl)

    parts = [
        isa.rstrip("\n"),
        gs,
        st_text.rstrip("\n"),
        ge,
        iea,
    ]
    return "\n".join(parts) + "\n"


def generate_837_batch(
    patient_ids: list[int],
    payment_year: int,
    submitter_info: dict | None = None,
    *,
    patient_icd10_overrides: dict[int, list[str]] | None = None,
) -> str:
    """Generate a multi-patient 837 file — one ST..SE per patient.

    Patients with no valid ICD-10 codes are skipped (and logged).
    """
    submitter = _merge_submitter(submitter_info)
    overrides = patient_icd10_overrides or {}

    isa_ctrl = new_isa_control_number()
    gs_ctrl = new_gs_control_number()
    now = datetime.now(timezone.utc)

    isa = isa_segment(
        sender_id=submitter["submitter_id"],
        receiver_id=submitter["receiver_id"],
        control_number=isa_ctrl,
        test_indicator=submitter.get("test_indicator", "T"),
        interchange_date=now,
    )
    gs = gs_segment(
        transaction="837",
        sender_code=submitter["submitter_id"],
        receiver_code=submitter["receiver_id"],
        control_number=gs_ctrl,
        transaction_date=now,
    )

    st_chunks: list[str] = []
    txn_count = 0
    for idx, pid in enumerate(patient_ids, start=1):
        icd10s = overrides.get(pid) or _load_hcc_icd10s_for_patient(pid, payment_year)
        if not icd10s:
            logger.info("837 batch: skipping patient %s — no confirmed ICD-10 codes", pid)
            continue
        txn_count += 1
        st_text, _ = _build_transaction_set(
            patient_id=pid,
            encounter_id=None,
            icd10_codes=icd10s,
            submitter=submitter,
            st_idx=txn_count,
        )
        st_chunks.append(st_text.rstrip("\n"))

    ge = ge_segment(num_transactions=max(txn_count, 1), control_number=gs_ctrl)
    iea = iea_segment(num_functional_groups=1, control_number=isa_ctrl)

    parts = [isa.rstrip("\n"), gs, *st_chunks, ge, iea]
    return "\n".join(parts) + "\n"
