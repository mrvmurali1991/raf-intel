"""Unit tests for the 837/834 EDI generators.

These tests stub out the database lookups so they run in CI without MySQL.
They verify the *shape* of the emitted X12 — segment counts, envelope
balance, mandatory ICD-10 placement, and ISA width.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.services.edi import common as x12
from app.services.edi import x12_834, x12_837


def _stub_patient_a(pid):
    return {
        "id": pid,
        "first_name": "JANE",
        "last_name": "DOE",
        "middle_name": "A",
        "dob": "1955-03-12",
        "sex": "F",
        "address": "742 EVERGREEN TER",
        "city": "SPRINGFIELD",
        "state": "IL",
        "zip": "627010000",
        "mrn": f"MRN{pid}",
        "ssn": "123456789",
    }


@pytest.fixture(autouse=True)
def _stub_db(monkeypatch):
    monkeypatch.setattr(x12_837, "_load_patient", _stub_patient_a)
    monkeypatch.setattr(x12_837, "_load_patient_mbi", lambda pid: "1EG4TE5MK73")
    monkeypatch.setattr(
        x12_837,
        "_load_encounter",
        lambda eid, pid: {
            "id": eid or 99,
            "encounter_date": "2026-04-15",
            "provider_npi": "1234567893",
            "place_of_service": "11",
        },
    )
    monkeypatch.setattr(
        x12_837,
        "_load_hcc_icd10s_for_patient",
        lambda pid, py=None: ["E11.65", "I50.23", "F32.9"],
    )
    monkeypatch.setattr(x12_834, "_load_patient", _stub_patient_a)
    monkeypatch.setattr(x12_834, "_load_patient_mbi", lambda pid: "1EG4TE5MK73")


# ---------------------------------------------------------------------------
# 837
# ---------------------------------------------------------------------------

def test_837_single_encounter_envelope() -> None:
    text = x12_837.generate_837_encounter(patient_id=3, encounter_id=None,
                                          hcc_codes=["E11.65", "I50.23"])
    assert text.startswith("ISA*")
    assert text.rstrip().endswith("~")
    assert "GS*HC*" in text
    assert "ST*837*" in text
    assert "GE*1*" in text
    assert "IEA*1*" in text


def test_837_isa_is_106_bytes() -> None:
    text = x12_837.generate_837_encounter(3, None, ["E11.65"])
    isa_line = text.splitlines()[0]
    assert len(isa_line) == 106, f"ISA must be 106 bytes incl terminator, got {len(isa_line)}"


def test_837_diagnosis_segment_present() -> None:
    text = x12_837.generate_837_encounter(3, None, ["E11.65", "I50.23"])
    assert "HI*ABK:E1165" in text
    assert "ABF:I5023" in text


def test_837_se_count_matches_segments() -> None:
    text = x12_837.generate_837_encounter(3, None, ["E11.65"])
    # Find ST..SE block
    body = text.split("ST*837*", 1)[1]
    body = "ST*837*" + body
    body = body.split("\nSE*", 1)
    head = body[0]
    se_line = "SE*" + body[1]
    se_count = int(se_line.split("*")[1])
    # Count segments in head + SE itself
    actual = head.count("~") + 1
    assert actual == se_count, f"SE01 says {se_count} but counted {actual}"


def test_837_batch_one_st_per_patient() -> None:
    text = x12_837.generate_837_batch([3, 4, 5], 2026)
    assert text.count("ST*837*") == 3
    assert text.count("SE*") == 3
    assert text.count("GS*HC*") == 1
    assert text.count("ISA*") == 1


def test_837_required_loops_present() -> None:
    text = x12_837.generate_837_encounter(3, None, ["E11.65"])
    # 1000A submitter, 1000B receiver, 2010AA billing prov, 2010BA subscriber
    assert "NM1*41*" in text
    assert "NM1*40*" in text
    assert "NM1*85*" in text
    assert "NM1*IL*" in text


# ---------------------------------------------------------------------------
# 834
# ---------------------------------------------------------------------------

def test_834_envelope() -> None:
    text = x12_834.generate_834_enrollment([3, 4], 2026)
    assert text.startswith("ISA*")
    assert "GS*BE*" in text
    assert "ST*834*" in text
    assert "BGN*" in text
    assert "GE*1*" in text
    assert "IEA*1*" in text


def test_834_one_ins_per_member() -> None:
    text = x12_834.generate_834_enrollment([3, 4, 5], 2026)
    assert text.count("\nINS*") == 3


def test_834_member_loop_segments() -> None:
    text = x12_834.generate_834_enrollment([3], 2026)
    assert "INS*Y*18*030" in text
    assert "NM1*IL*1*DOE*JANE" in text
    assert "DMG*D8*19550312*F" in text
    assert "HD*030" in text
    assert "DTP*348*D8*20260101" in text
    assert "DTP*349*D8*20261231" in text


def test_834_empty_patient_ids_raises() -> None:
    with pytest.raises(ValueError):
        x12_834.generate_834_enrollment([], 2026)


# ---------------------------------------------------------------------------
# Common
# ---------------------------------------------------------------------------

def test_normalize_icd10_strips_dot_and_uppercases() -> None:
    assert x12.normalize_icd10("E11.65") == "E1165"
    assert x12.normalize_icd10("i50.23") == "I5023"
    assert x12.normalize_icd10("") == ""


def test_isa_segment_pads_sender_and_receiver() -> None:
    isa = x12.isa_segment(
        sender_id="SEND",
        receiver_id="RECV",
        control_number="000000001",
        interchange_date=datetime(2026, 5, 17, 12, 0, tzinfo=timezone.utc),
    )
    # ISA06 (sender id) must be exactly 15 chars
    parts = isa.split("*")
    assert len(parts[6]) == 15
    assert len(parts[8]) == 15


def test_segment_strips_trailing_empty_elements() -> None:
    s = x12.segment("REF", "0F", "12345", "", "")
    assert s == "REF*0F*12345~"


def test_segment_preserves_inner_empty_elements() -> None:
    # composite elements must be passed as a tuple/list — pre-joining with ':'
    # would be sanitised by clean() since ':' is the sub-element separator.
    s = x12.segment("CLM", "C1", "0.00", "", "", ["11", "B", "1"], "Y")
    assert s == "CLM*C1*0.00***11:B:1*Y~"
