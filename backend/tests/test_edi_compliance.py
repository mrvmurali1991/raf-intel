"""EDI 837 5010 compliance tests — SBR09, MBI, DPS, and override gate.

All DB calls are monkeypatched so tests run in CI without MySQL.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.services.edi import x12_837


# ---------------------------------------------------------------------------
# Fixtures — stub DB helpers
# ---------------------------------------------------------------------------

_VALID_MBI = "1EG4TE5MK73"
_VALID_MBI_2 = "3CF6TN5HF62"

# Valid MBI must satisfy the CMS regex.  These two are test values that match.
_PATIENT_STUB = {
    "id": 42,
    "first_name": "JANE",
    "last_name": "DOE",
    "middle_name": "A",
    "dob": "1955-03-12",
    "sex": "F",
    "address": "742 EVERGREEN TER",
    "city": "SPRINGFIELD",
    "state": "IL",
    "zip": "627010000",
    "mrn": "MRN42",
}

_ENCOUNTER_STUB = {
    "id": 99,
    "encounter_date": "2026-04-15",
    "provider_npi": "1234567893",
    "place_of_service": "11",
    "procedure_code": "99214",
}


@pytest.fixture(autouse=True)
def _stub_db(monkeypatch):
    monkeypatch.setattr(x12_837, "_load_patient", lambda pid: dict(_PATIENT_STUB, id=pid))
    monkeypatch.setattr(x12_837, "_load_patient_mbi", lambda pid: _VALID_MBI)
    monkeypatch.setattr(
        x12_837,
        "_load_encounter",
        lambda eid, pid: dict(_ENCOUNTER_STUB, id=eid or 99),
    )
    monkeypatch.setattr(
        x12_837,
        "_load_hcc_icd10s_for_patient",
        lambda pid, py=None: ["E1165", "I5023"],
    )


# ---------------------------------------------------------------------------
# 1. SBR09 = 'MA' when destination is CMSEDPS
# ---------------------------------------------------------------------------

def test_sbr09_is_MA_for_cmsedps():
    """When receiver_id contains 'EDPS', SBR09 must be 'MA', not 'MB'."""
    text = x12_837.generate_837_encounter(
        patient_id=42,
        encounter_id=None,
        hcc_codes=["E11.65"],
        submitter_info={"receiver_id": "CMSEDPS", "receiver_name": "CMS EDPS"},
    )
    # SBR segment ends with the claim-filing indicator as the last non-empty element
    sbr_lines = [seg for seg in text.split("~") if seg.strip().startswith("SBR")]
    assert sbr_lines, "SBR segment not found"
    sbr = sbr_lines[0]
    elements = sbr.split("*")
    # SBR09 is index 9 (0-based), element 10 (1-based), strip trailing whitespace/~
    sbr09 = elements[9].rstrip("~\n").strip() if len(elements) > 9 else ""
    assert sbr09 == "MA", (
        f"SBR09 must be 'MA' for EDPS destination, got '{sbr09}'. "
        f"Full SBR: {sbr}"
    )
    assert "MB" not in sbr, "SBR segment must not contain 'MB' for EDPS destination"


def test_sbr09_is_not_MB_default():
    """Default submitter (CMSEDPS) should never produce MB in SBR."""
    text = x12_837.generate_837_encounter(patient_id=42, encounter_id=None)
    assert "SBR*P*18********MB" not in text


# ---------------------------------------------------------------------------
# 2. Invalid MBI raises ValueError
# ---------------------------------------------------------------------------

def test_invalid_mbi_raises_value_error(monkeypatch):
    """A spoofed / missing MBI must raise ValueError before building the 837."""
    monkeypatch.setattr(x12_837, "_load_patient_mbi", lambda pid: "PID42")
    with pytest.raises(ValueError, match="CMS-conformant"):
        x12_837.generate_837_encounter(patient_id=42, encounter_id=None, hcc_codes=["E11.65"])


def test_empty_mbi_raises_value_error(monkeypatch):
    """An empty MBI string must also raise ValueError."""
    monkeypatch.setattr(x12_837, "_load_patient_mbi", lambda pid: "")
    with pytest.raises(ValueError, match="CMS-conformant"):
        x12_837.generate_837_encounter(patient_id=42, encounter_id=None, hcc_codes=["E11.65"])


# ---------------------------------------------------------------------------
# 3. SV1 contains DPS composite (diagnosis pointers)
# ---------------------------------------------------------------------------

def test_sv1_contains_dps_composite_for_two_diagnoses():
    """SV1 must include a diagnosis-pointer composite when 2 ICD-10s are present."""
    text = x12_837.generate_837_encounter(
        patient_id=42, encounter_id=None, hcc_codes=["E11.65", "I50.23"]
    )
    sv1_lines = [seg.strip() for seg in text.split("~") if seg.strip().startswith("SV1")]
    assert sv1_lines, "SV1 segment not found"
    sv1 = sv1_lines[0]
    elements = sv1.split("*")
    # SV1 element 7 (0-based index 7) is the DPS composite: "1:2"
    # strip trailing ~, whitespace
    dps = elements[7].rstrip("~\n").strip() if len(elements) > 7 else ""
    assert ":" in dps, (
        f"SV1 DPS composite (element 8) must contain ':' for multiple diagnoses. "
        f"Got '{dps}'. Full SV1: {sv1}"
    )
    assert dps == "1:2", f"Expected DPS '1:2' for 2 diagnoses, got '{dps}'"


def test_sv1_dps_single_diagnosis():
    """SV1 must include pointer '1' for a single diagnosis."""
    text = x12_837.generate_837_encounter(
        patient_id=42, encounter_id=None, hcc_codes=["E11.65"]
    )
    sv1_lines = [seg.strip() for seg in text.split("~") if seg.strip().startswith("SV1")]
    assert sv1_lines
    sv1 = sv1_lines[0]
    elements = sv1.split("*")
    dps = elements[7].rstrip("~\n").strip() if len(elements) > 7 else ""
    assert dps == "1", f"Expected DPS '1' for single diagnosis, got '{dps}'"


def test_sv1_uses_encounter_procedure_code():
    """SV1 must use the encounter procedure_code (99214) not the hardcoded 99499."""
    text = x12_837.generate_837_encounter(
        patient_id=42, encounter_id=None, hcc_codes=["E11.65"]
    )
    assert "HC:99214" in text, "SV1 should use encounter procedure_code 99214"


def test_sv1_fallback_to_99499_when_no_proc_code(monkeypatch):
    """When no procedure_code on encounter, fall back to 99499 with a WARNING."""
    enc = dict(_ENCOUNTER_STUB)
    enc.pop("procedure_code", None)
    monkeypatch.setattr(x12_837, "_load_encounter", lambda eid, pid: enc)

    import logging
    with patch.object(x12_837.logger, "warning") as mock_warn:
        text = x12_837.generate_837_encounter(
            patient_id=42, encounter_id=None, hcc_codes=["E11.65"]
        )
    assert "HC:99499" in text
    warned = any("99499" in str(call) or "procedure_code" in str(call) for call in mock_warn.call_args_list)
    assert warned, "Expected a WARNING log about fallback to 99499"


# ---------------------------------------------------------------------------
# 4-7. Override gate — router-level tests
# ---------------------------------------------------------------------------

def _make_app():
    """Build a minimal FastAPI app with only the EDI router mounted."""
    from fastapi import FastAPI
    from app.routers.edi_generation import router as edi_router

    app = FastAPI()
    app.include_router(edi_router)
    return app


def _auth_overrides(app, user_role="coder"):
    """Inject fake auth so the endpoint runs without a real JWT."""
    from app.auth import get_current_user, get_tenant_id

    app.dependency_overrides[get_current_user] = lambda: {"id": 1, "role": user_role}
    app.dependency_overrides[get_tenant_id] = lambda: "TENANT1"


def _stub_validator_high(monkeypatch, failed_ids=None):
    """Make validate_batch report HIGH severity for the given patient ids."""
    from app.services.edi import pre_submission_validator as psv

    failed = failed_ids or [101]
    monkeypatch.setattr(
        psv,
        "validate_batch",
        lambda pids, py: {
            "per_patient": [],
            "failed_patient_ids": failed,
            "passed_patient_ids": [p for p in pids if p not in failed],
            "high_severity_total": len(failed),
        },
    )


def _stub_generate_837(monkeypatch):
    """Stub out the actual EDI generation + file save."""
    import app.routers.edi_generation as rmod

    monkeypatch.setattr(
        rmod,
        "generate_837_batch",
        lambda *a, **kw: "ISA*...\nST*837*0001~\nCLM*...\nSE*2*0001~\nGE*1*1~\nIEA*1*1~\n",
    )
    monkeypatch.setattr(
        rmod,
        "save_edi_file",
        lambda **kw: {"id": "FILE001", "file_size": 100, "sha256": "abc123", "file_path": "/tmp/f.edi"},
    )


@pytest.mark.parametrize(
    "payload,expected_status",
    [
        # override_reason too short (< 30 chars)
        (
            {
                "patient_ids": [101],
                "payment_year": 2026,
                "confirm_override": True,
                "override_reason": "short",
                "reviewer_user_id": 2,
            },
            422,
        ),
        # override_reason missing entirely
        (
            {
                "patient_ids": [101],
                "payment_year": 2026,
                "confirm_override": True,
                "override_reason": None,
                "reviewer_user_id": 2,
            },
            422,
        ),
        # reviewer_user_id missing
        (
            {
                "patient_ids": [101],
                "payment_year": 2026,
                "confirm_override": True,
                "override_reason": "This is a sufficiently long clinical justification reason.",
            },
            422,
        ),
        # batch override (len > 1)
        (
            {
                "patient_ids": [101, 102],
                "payment_year": 2026,
                "confirm_override": True,
                "override_reason": "This is a sufficiently long clinical justification reason.",
                "reviewer_user_id": 2,
            },
            422,
        ),
    ],
)
def test_override_gate_validation(payload, expected_status, monkeypatch):
    """Override requests missing required fields / violating constraints return 422."""
    _stub_validator_high(monkeypatch, failed_ids=payload.get("patient_ids", [101])[:1])
    _stub_generate_837(monkeypatch)

    app = _make_app()
    _auth_overrides(app)

    import app.routers.edi_generation as rmod
    # patch _persist_override_signature and _load_user so DB isn't needed
    monkeypatch.setattr(rmod, "_persist_override_signature", lambda **kw: None)
    monkeypatch.setattr(rmod, "_load_user", lambda uid: {"id": uid, "role": "billing_supervisor"})

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post("/api/edi/837/generate", json=payload)
    assert resp.status_code == expected_status, (
        f"Expected {expected_status}, got {resp.status_code}. Body: {resp.text}"
    )


def test_override_gate_non_supervisor_reviewer_returns_403(monkeypatch):
    """reviewer_user_id with role 'coder' (not supervisor) must return 403."""
    _stub_validator_high(monkeypatch, failed_ids=[101])
    _stub_generate_837(monkeypatch)

    app = _make_app()
    _auth_overrides(app)

    import app.routers.edi_generation as rmod
    monkeypatch.setattr(rmod, "_persist_override_signature", lambda **kw: None)
    # Reviewer has role 'coder' — not in _SUPERVISOR_ROLES
    monkeypatch.setattr(rmod, "_load_user", lambda uid: {"id": uid, "role": "coder"})

    client = TestClient(app, raise_server_exceptions=False)
    payload = {
        "patient_ids": [101],
        "payment_year": 2026,
        "confirm_override": True,
        "override_reason": "This is a sufficiently long clinical justification reason.",
        "reviewer_user_id": 99,
    }
    resp = client.post("/api/edi/837/generate", json=payload)
    assert resp.status_code == 403, (
        f"Expected 403 for non-supervisor reviewer, got {resp.status_code}. Body: {resp.text}"
    )
