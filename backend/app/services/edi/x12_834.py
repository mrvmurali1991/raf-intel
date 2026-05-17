"""
X12 834 5010 — Benefit Enrollment and Maintenance (005010X220A1).

Emits an 834 file enrolling a set of patients into a single sponsor plan
for the given plan year.  All members are treated as new enrollments
(INS01="Y", INS03="030").  Termination / change maintenance types are out
of scope for this MVP.
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
    se_segment,
    segment,
    st_segment,
    upper,
)

logger = logging.getLogger(__name__)


_DEFAULT_SPONSOR = {
    "sponsor_name":  "DEMO PLAN SPONSOR",
    "sponsor_id":    "SPONSOR1",
    "payer_name":    "CMS",
    "payer_id":      "CMSEDPS",
    "sender_id":     "RAFINTEL",
    "receiver_id":   "CMSEDPS",
    "plan_id":       "H9999-001",
    "plan_name":     "DEMO MA PLAN",
    "test_indicator":"T",
}


def _merge_sponsor(info: dict | None) -> dict:
    merged = dict(_DEFAULT_SPONSOR)
    if info:
        merged.update({k: v for k, v in info.items() if v is not None})
    return merged


def _load_patient(patient_id: int) -> dict[str, Any]:
    try:
        from app.db import raf_cursor

        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT id, first_name, last_name, middle_name, dob, sex,
                       address, city, state, zip, mrn, ssn
                FROM patients
                WHERE id = %s
                """,
                (patient_id,),
            )
            return cur.fetchone() or {}
    except Exception as exc:
        logger.warning("834 _load_patient(%s) failed: %s", patient_id, exc)
        return {}


def _load_patient_mbi(patient_id: int) -> str:
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


# ---------------------------------------------------------------------------
# 834 segment builders
# ---------------------------------------------------------------------------

def _bgn_segment(*, batch_id: str) -> str:
    """BGN — Beginning Segment."""
    now = datetime.now(timezone.utc)
    return segment(
        "BGN",
        "00",                         # BGN01 transaction set purpose: original
        clean(batch_id, 30),
        ccyymmdd(now),
        now.strftime("%H%M"),
        "",                           # BGN05 time zone
        "",                           # BGN06 reference id
        "",                           # BGN07 transaction type
        "2",                          # BGN08 action code — change (5010 default for full file)
    )


def _sponsor_loops(s: dict) -> list[str]:
    """1000A (Sponsor) + 1000B (Payer)."""
    return [
        segment(
            "N1",
            "P5",                                 # N101 plan sponsor
            upper(s["sponsor_name"], 60),
            "FI",                                 # N103 federal taxpayer id
            clean(s["sponsor_id"], 80),
        ),
        segment(
            "N1",
            "IN",                                 # N101 insurer (payer)
            upper(s["payer_name"], 60),
            "FI",
            clean(s["payer_id"], 80),
        ),
    ]


def _member_loop_2000(
    *,
    patient: dict,
    mbi: str,
    plan_year: int,
    sponsor: dict,
) -> list[str]:
    """One member loop — INS, REF, NM1, DMG, HD, DTP per 5010 spec."""
    pid = patient.get("id")
    member_id = mbi or f"PID{pid or 'UNKNOWN'}"

    coverage_start = date(plan_year, 1, 1)
    coverage_end = date(plan_year, 12, 31)

    segs = [
        # 2000 INS — Member Level Detail (subscriber + add)
        segment(
            "INS",
            "Y",          # INS01 yes — subscriber
            "18",         # INS02 individual relationship code: self
            "030",        # INS03 maintenance type code: audit/compare (or 021 = addition)
            "XN",         # INS04 maintenance reason code (Not Applicable)
            "A",          # INS05 benefit status code: active
            "",           # INS06 medicare plan code
            "",           # INS07 cobra qualifying event
            "FT",         # INS08 employment status: full-time
        ),
        # 2000 REF*0F — Subscriber Number
        segment("REF", "0F", clean(member_id, 30)),
        # 2000 REF*1L — Group/Policy Number
        segment("REF", "1L", clean(sponsor.get("plan_id", ""), 30)),
        # 2100A NM1 — Member Name
        segment(
            "NM1",
            "IL",
            "1",
            upper(patient.get("last_name", ""), 35),
            upper(patient.get("first_name", ""), 25),
            upper(patient.get("middle_name", ""), 25),
            "", "",
            "34" if patient.get("ssn") else "ZZ",
            x12.digits_only(patient.get("ssn"), 9) or clean(member_id, 30),
        ),
        # 2100A N3 — Address line
        segment("N3", upper(patient.get("address", ""), 55)),
        # 2100A N4 — City/State/ZIP
        segment(
            "N4",
            upper(patient.get("city", ""), 30),
            upper(patient.get("state", ""), 2),
            x12.digits_only(patient.get("zip", ""), 15),
        ),
        # 2100A DMG — Demographics
        segment(
            "DMG",
            "D8",
            ccyymmdd(patient.get("dob")),
            upper(patient.get("sex", "U"), 1) or "U",
        ),
        # 2300 HD — Health Coverage
        segment(
            "HD",
            "030",        # HD01 maintenance type code
            "",
            "HMO",        # HD03 insurance line code
            clean(sponsor.get("plan_name", ""), 50),
            "IND",        # HD05 coverage level: individual
        ),
        # 2300 DTP*348 — Benefit Begin
        segment("DTP", "348", "D8", ccyymmdd(coverage_start)),
        # 2300 DTP*349 — Benefit End
        segment("DTP", "349", "D8", ccyymmdd(coverage_end)),
    ]
    return segs


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def generate_834_enrollment(
    patient_ids: list[int],
    plan_year: int,
    sponsor_info: dict | None = None,
) -> str:
    """Generate a complete 834 5010 enrollment file.

    Parameters
    ----------
    patient_ids : list[int]
        RAF patient IDs to enroll.
    plan_year : int
        Calendar year of coverage (e.g. 2026).
    sponsor_info : dict | None
        Overrides for sponsor / payer / plan defaults.

    Returns
    -------
    str
        Complete 5010 EDI text — ISA…IEA.
    """
    if not patient_ids:
        raise ValueError("generate_834_enrollment: patient_ids must be non-empty")

    sponsor = _merge_sponsor(sponsor_info)

    isa_ctrl = new_isa_control_number()
    gs_ctrl = new_gs_control_number()
    st_ctrl = new_st_control_number(1)
    now = datetime.now(timezone.utc)

    isa = isa_segment(
        sender_id=sponsor["sender_id"],
        receiver_id=sponsor["receiver_id"],
        control_number=isa_ctrl,
        test_indicator=sponsor.get("test_indicator", "T"),
        interchange_date=now,
    )
    gs = gs_segment(
        transaction="834",
        sender_code=sponsor["sender_id"],
        receiver_code=sponsor["receiver_id"],
        control_number=gs_ctrl,
        transaction_date=now,
        version="005010X220A1",
    )

    body: list[str] = []
    body.append(st_segment(transaction="834", control_number=st_ctrl))
    body.append(_bgn_segment(batch_id=f"ENR{plan_year}"))
    body.append(segment("REF", "38", clean(sponsor.get("plan_id", ""), 30)))   # master policy
    body.append(segment("DTP", "007", "D8", ccyymmdd(date(plan_year, 1, 1)))) # effective date
    body.extend(_sponsor_loops(sponsor))

    skipped = 0
    enrolled = 0
    for pid in patient_ids:
        patient = _load_patient(pid)
        if not patient:
            logger.info("834: patient %s not found — skipping", pid)
            skipped += 1
            continue
        patient["id"] = patient.get("id") or pid
        mbi = _load_patient_mbi(pid)
        body.extend(
            _member_loop_2000(
                patient=patient,
                mbi=mbi,
                plan_year=plan_year,
                sponsor=sponsor,
            )
        )
        enrolled += 1

    if skipped:
        logger.info("834 enrollment: %d skipped, %d enrolled", skipped, enrolled)

    body_text = join_segments(body)
    seg_count = count_segments(body_text) + 1  # +1 for SE
    body_text += se_segment(segment_count=seg_count, control_number=st_ctrl) + "\n"

    ge = ge_segment(num_transactions=1, control_number=gs_ctrl)
    iea = iea_segment(num_functional_groups=1, control_number=isa_ctrl)

    return "\n".join([isa.rstrip("\n"), gs, body_text.rstrip("\n"), ge, iea]) + "\n"
