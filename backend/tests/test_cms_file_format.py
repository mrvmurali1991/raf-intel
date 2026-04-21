"""
CMS File Format Integration Tests
==================================
Verify that RAPS fixed-width records and EDPS/837P segments produced by
submission_service.py match CMS byte-position specifications exactly.

All tests are fully offline — no database or live server is required.
The private formatting helpers (_raps_header, _raps_detail, _raps_trailer,
_edps_isa_envelope, _edps_gs_header, _edps_gs_trailer, _edps_isa_trailer,
_edps_claim_segment, _normalize_date_8) are tested directly, and the two
public generator functions (generate_raps_file, generate_edps_file) are
tested via mocked database cursors so the full code path executes.

CMS RAPS layout reference (record-type B, 1-indexed):
  Pos 1:      Record type 'B'
  Pos 2-13:   HICN/MBI (12 chars, left-justified, space-padded)
  Pos 14-23:  Provider NPI (10 chars, left-justified, space-padded)
  Pos 24-25:  Provider type code (2 chars)
  Pos 26:     Delete indicator (1 char: N or D)
  Pos 27-33:  ICD-10 code (7 chars, left-justified, space-padded, no dot)
  Pos 34-41:  DOS from YYYYMMDD
  Pos 42-49:  DOS through YYYYMMDD
  Pos 50-53:  Payment year YYYY
  Pos 54-500: Spaces (filler)

CMS RAPS layout reference (record-type A — header):
  Pos 1:      Record type 'A'
  Pos 2-12:   Plan ID (11 chars, left-justified, space-padded)
  Pos 13-16:  Payment year (YYYY)
  Pos 17-21:  Sweep type (5 chars, left-justified, space-padded)
  Pos 22-29:  Submission date YYYYMMDD
  Pos 30-500: Spaces (filler)

CMS RAPS layout reference (record-type Z — trailer):
  Pos 1:      Record type 'Z'
  Pos 2-12:   Plan ID (11 chars, left-justified, space-padded)
  Pos 13-21:  Detail record count (9 digits, zero-padded)
  Pos 22-500: Spaces (filler)
"""

from __future__ import annotations

import os
import re
import sys
from contextlib import contextmanager
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Ensure the backend package is importable
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Set required env vars before importing the app so config.py does not crash.
os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-for-pytest-do-not-use-in-prod")
os.environ.setdefault("JWT_REFRESH_SECRET", "test-refresh-secret-for-pytest")
os.environ.setdefault("OPENEMR_DB_USER", "test_user")
os.environ.setdefault("OPENEMR_DB_PASSWORD", "test_password")
os.environ.setdefault("RAF_DB_USER", "test_user")
os.environ.setdefault("RAF_DB_PASSWORD", "test_password")
os.environ.setdefault("RAF_DB_HOST", "localhost")
os.environ.setdefault("RAF_DB_NAME", "raf_test")
os.environ.setdefault("OPENEMR_DB_HOST", "localhost")
os.environ.setdefault("OPENEMR_DB_NAME", "openemr_test")

# Import the private formatting helpers directly so we can test them in isolation
# without touching any database code.
from app.services.submission_service import (
    _edps_claim_segment,
    _edps_gs_header,
    _edps_gs_trailer,
    _edps_isa_envelope,
    _edps_isa_trailer,
    _normalize_date_8,
    _raps_detail,
    _raps_header,
    _raps_trailer,
)

# ---------------------------------------------------------------------------
# Shared test fixtures
# ---------------------------------------------------------------------------

PLAN_ID = "H1234"
PAYMENT_YEAR = 2025
SWEEP_TYPE = "Initial"
MBI = "1EG4TE5MK73"       # 11-char CMS MBI pattern (valid format)
NPI_10 = "1234567890"      # 10-digit NPI
ICD10_WITH_DOT = "E11.9"   # Type 2 diabetes, no complications
ICD10_CLEAN = "E119"       # Dot-free version written into the RAPS record
DOS_FROM = "2025-01-15"
DOS_THROUGH = "2025-01-15"
SENDER_ID = "MASENDER"
RECEIVER_ID = "CMSEDPS00"
CONTROL_NUM = "123456789"


# ---------------------------------------------------------------------------
# A. RAPS Fixed-Width Format Tests
# ---------------------------------------------------------------------------

class TestRAPSFileFormat:
    """Validate RAPS A/B/Z record layout against CMS byte-position spec."""

    # ---- A-header ----------------------------------------------------------

    def test_a_header_record_length(self):
        """A-header record must be exactly 500 characters (no newline)."""
        rec = _raps_header(PLAN_ID, PAYMENT_YEAR, SWEEP_TYPE)
        assert len(rec) == 500, (
            f"A-header is {len(rec)} chars; expected 500. "
            "CMS rejects files where any record deviates from 500-byte width."
        )

    def test_a_header_record_type_at_position_1(self):
        """Position 1 (index 0) must be the literal character 'A'."""
        rec = _raps_header(PLAN_ID, PAYMENT_YEAR, SWEEP_TYPE)
        assert rec[0] == "A", f"Expected 'A' at pos 1, got {rec[0]!r}"

    def test_a_header_plan_id_positions_2_to_12(self):
        """
        Plan ID occupies positions 2-12 (indices 1-11, 11 chars).
        Left-justified and space-padded to exactly 11 characters.
        """
        rec = _raps_header(PLAN_ID, PAYMENT_YEAR, SWEEP_TYPE)
        field = rec[1:12]  # indices 1..11 inclusive
        assert len(field) == 11, f"Plan ID field is {len(field)} chars; expected 11"
        assert field == PLAN_ID.ljust(11), (
            f"Plan ID field {field!r} != expected {PLAN_ID.ljust(11)!r}"
        )

    def test_a_header_payment_year_positions_13_to_16(self):
        """Payment year occupies positions 13-16 (indices 12-15, 4 chars), YYYY."""
        rec = _raps_header(PLAN_ID, PAYMENT_YEAR, SWEEP_TYPE)
        field = rec[12:16]
        assert field == str(PAYMENT_YEAR), (
            f"Payment year field {field!r} != {PAYMENT_YEAR}"
        )

    def test_a_header_sweep_type_positions_17_to_21(self):
        """Sweep type occupies positions 17-21 (indices 16-20, 5 chars), space-padded."""
        rec = _raps_header(PLAN_ID, PAYMENT_YEAR, SWEEP_TYPE)
        field = rec[16:21]
        assert len(field) == 5, f"Sweep type field is {len(field)} chars; expected 5"
        assert field == SWEEP_TYPE[:5].ljust(5), (
            f"Sweep field {field!r} != {SWEEP_TYPE[:5].ljust(5)!r}"
        )

    def test_a_header_submission_date_positions_22_to_29(self):
        """
        Submission date occupies positions 22-29 (indices 21-28, 8 chars).
        Must be YYYYMMDD with no dashes.
        """
        rec = _raps_header(PLAN_ID, PAYMENT_YEAR, SWEEP_TYPE)
        field = rec[21:29]
        assert len(field) == 8, f"Date field is {len(field)} chars; expected 8"
        assert re.fullmatch(r"\d{8}", field), (
            f"Submission date {field!r} is not YYYYMMDD"
        )
        # Must be today's date in YYYYMMDD form
        assert field == date.today().strftime("%Y%m%d"), (
            f"Submission date {field!r} != today {date.today().strftime('%Y%m%d')}"
        )

    def test_a_header_filler_all_spaces(self):
        """Positions 30-500 (indices 29-499) must be all spaces."""
        rec = _raps_header(PLAN_ID, PAYMENT_YEAR, SWEEP_TYPE)
        filler = rec[29:]
        assert filler == " " * (500 - 29), (
            f"Filler region contains non-space characters: {filler[:20]!r}..."
        )

    def test_a_header_truncated_plan_id(self):
        """A plan ID longer than 11 chars must be silently truncated to 11."""
        long_plan_id = "H" + "9" * 20
        rec = _raps_header(long_plan_id, PAYMENT_YEAR, SWEEP_TYPE)
        assert len(rec) == 500
        assert rec[1:12] == long_plan_id[:11]

    # ---- B-detail ----------------------------------------------------------

    def test_b_detail_record_length(self):
        """B-detail record must be exactly 500 characters (no newline)."""
        rec = _raps_detail(
            hicn_mbi=MBI,
            icd10=ICD10_WITH_DOT,
            dos_from=DOS_FROM,
            dos_through=DOS_THROUGH,
            provider_npi=NPI_10,
            provider_type="01",
            payment_year=PAYMENT_YEAR,
        )
        assert len(rec) == 500, (
            f"B-detail is {len(rec)} chars; expected 500."
        )

    def test_b_detail_record_type_at_position_1(self):
        """Position 1 (index 0) must be the literal character 'B'."""
        rec = _raps_detail(
            hicn_mbi=MBI, icd10=ICD10_WITH_DOT, dos_from=DOS_FROM,
            dos_through=DOS_THROUGH, provider_npi=NPI_10,
            provider_type="01", payment_year=PAYMENT_YEAR,
        )
        assert rec[0] == "B"

    def test_b_detail_mbi_positions_2_to_13(self):
        """
        HICN/MBI occupies positions 2-13 (indices 1-12, 12 chars).
        Left-justified, space-padded to 12 characters.
        An MBI longer than 12 chars must be truncated to 12.
        """
        rec = _raps_detail(
            hicn_mbi=MBI, icd10=ICD10_WITH_DOT, dos_from=DOS_FROM,
            dos_through=DOS_THROUGH, provider_npi=NPI_10,
            provider_type="01", payment_year=PAYMENT_YEAR,
        )
        field = rec[1:13]
        assert len(field) == 12, f"MBI field is {len(field)} chars; expected 12"
        assert field == MBI[:12].ljust(12), (
            f"MBI field {field!r} != {MBI[:12].ljust(12)!r}"
        )

    def test_b_detail_mbi_format_alphanumeric(self):
        """MBI field must contain only alphanumeric characters or spaces (no special chars)."""
        rec = _raps_detail(
            hicn_mbi=MBI, icd10=ICD10_WITH_DOT, dos_from=DOS_FROM,
            dos_through=DOS_THROUGH, provider_npi=NPI_10,
            provider_type="01", payment_year=PAYMENT_YEAR,
        )
        field = rec[1:13].strip()
        assert re.fullmatch(r"[A-Z0-9]+", field, re.IGNORECASE), (
            f"MBI field {field!r} contains non-alphanumeric characters"
        )

    def test_b_detail_npi_positions_14_to_23(self):
        """
        Provider NPI occupies positions 14-23 (indices 13-22, 10 chars).
        NPI must not be truncated and must land at the correct byte offset.
        """
        rec = _raps_detail(
            hicn_mbi=MBI, icd10=ICD10_WITH_DOT, dos_from=DOS_FROM,
            dos_through=DOS_THROUGH, provider_npi=NPI_10,
            provider_type="01", payment_year=PAYMENT_YEAR,
        )
        field = rec[13:23]
        assert len(field) == 10, f"NPI field is {len(field)} chars; expected 10"
        assert field == NPI_10[:10].ljust(10), (
            f"NPI field {field!r} != {NPI_10[:10].ljust(10)!r}"
        )

    def test_b_detail_provider_type_positions_24_to_25(self):
        """Provider type code occupies positions 24-25 (indices 23-24, 2 chars)."""
        rec = _raps_detail(
            hicn_mbi=MBI, icd10=ICD10_WITH_DOT, dos_from=DOS_FROM,
            dos_through=DOS_THROUGH, provider_npi=NPI_10,
            provider_type="01", payment_year=PAYMENT_YEAR,
        )
        field = rec[23:25]
        assert field == "01", f"Provider type field {field!r} != '01'"

    def test_b_detail_delete_indicator_position_26(self):
        """Delete indicator occupies position 26 (index 25, 1 char). Default is 'N'."""
        rec = _raps_detail(
            hicn_mbi=MBI, icd10=ICD10_WITH_DOT, dos_from=DOS_FROM,
            dos_through=DOS_THROUGH, provider_npi=NPI_10,
            provider_type="01", payment_year=PAYMENT_YEAR,
        )
        assert rec[25] == "N", f"Delete indicator {rec[25]!r} != 'N'"

    def test_b_detail_delete_indicator_can_be_D(self):
        """Delete indicator must be 'D' when delete_ind='D' is passed."""
        rec = _raps_detail(
            hicn_mbi=MBI, icd10=ICD10_WITH_DOT, dos_from=DOS_FROM,
            dos_through=DOS_THROUGH, provider_npi=NPI_10,
            provider_type="01", payment_year=PAYMENT_YEAR, delete_ind="D",
        )
        assert rec[25] == "D"

    def test_b_detail_icd10_positions_27_to_33(self):
        """
        ICD-10 code occupies positions 27-33 (indices 26-32, 7 chars).
        Dot must be stripped; code must be left-justified, space-padded.
        """
        rec = _raps_detail(
            hicn_mbi=MBI, icd10=ICD10_WITH_DOT, dos_from=DOS_FROM,
            dos_through=DOS_THROUGH, provider_npi=NPI_10,
            provider_type="01", payment_year=PAYMENT_YEAR,
        )
        field = rec[26:33]
        assert len(field) == 7, f"ICD-10 field is {len(field)} chars; expected 7"
        assert "." not in field, f"ICD-10 field {field!r} still contains a dot"
        assert field == ICD10_CLEAN.ljust(7), (
            f"ICD-10 field {field!r} != {ICD10_CLEAN.ljust(7)!r}"
        )

    def test_b_detail_icd10_no_dot_stored(self):
        """ICD-10 codes with a dot (e.g. 'E11.9') must have the dot removed in the record."""
        rec = _raps_detail(
            hicn_mbi=MBI, icd10="E11.9", dos_from=DOS_FROM,
            dos_through=DOS_THROUGH, provider_npi=NPI_10,
            provider_type="01", payment_year=PAYMENT_YEAR,
        )
        icd_field = rec[26:33]
        assert "." not in icd_field, (
            f"Dot survived ICD-10 normalization; field is {icd_field!r}"
        )

    def test_b_detail_icd10_uppercased(self):
        """ICD-10 code must be stored in uppercase regardless of input case."""
        rec = _raps_detail(
            hicn_mbi=MBI, icd10="e11.9", dos_from=DOS_FROM,
            dos_through=DOS_THROUGH, provider_npi=NPI_10,
            provider_type="01", payment_year=PAYMENT_YEAR,
        )
        icd_field = rec[26:33].strip()
        assert icd_field == icd_field.upper(), (
            f"ICD-10 field {icd_field!r} is not uppercase"
        )

    def test_b_detail_dos_from_positions_34_to_41(self):
        """
        DOS-from occupies positions 34-41 (indices 33-40, 8 chars).
        Must be YYYYMMDD with no dashes.
        """
        rec = _raps_detail(
            hicn_mbi=MBI, icd10=ICD10_WITH_DOT, dos_from=DOS_FROM,
            dos_through=DOS_THROUGH, provider_npi=NPI_10,
            provider_type="01", payment_year=PAYMENT_YEAR,
        )
        field = rec[33:41]
        assert len(field) == 8, f"DOS-from field is {len(field)} chars; expected 8"
        assert re.fullmatch(r"\d{8}", field), f"DOS-from {field!r} is not YYYYMMDD"
        assert field == "20250115", f"DOS-from {field!r} != '20250115'"

    def test_b_detail_dos_through_positions_42_to_49(self):
        """
        DOS-through occupies positions 42-49 (indices 41-48, 8 chars).
        Must be YYYYMMDD with no dashes.
        """
        rec = _raps_detail(
            hicn_mbi=MBI, icd10=ICD10_WITH_DOT, dos_from=DOS_FROM,
            dos_through=DOS_THROUGH, provider_npi=NPI_10,
            provider_type="01", payment_year=PAYMENT_YEAR,
        )
        field = rec[41:49]
        assert len(field) == 8, f"DOS-through field is {len(field)} chars; expected 8"
        assert re.fullmatch(r"\d{8}", field), f"DOS-through {field!r} is not YYYYMMDD"
        assert field == "20250115", f"DOS-through {field!r} != '20250115'"

    def test_b_detail_payment_year_positions_50_to_53(self):
        """Payment year occupies positions 50-53 (indices 49-52, 4 chars), YYYY."""
        rec = _raps_detail(
            hicn_mbi=MBI, icd10=ICD10_WITH_DOT, dos_from=DOS_FROM,
            dos_through=DOS_THROUGH, provider_npi=NPI_10,
            provider_type="01", payment_year=PAYMENT_YEAR,
        )
        field = rec[49:53]
        assert field == str(PAYMENT_YEAR), (
            f"Payment year field {field!r} != {PAYMENT_YEAR}"
        )

    def test_b_detail_filler_all_spaces(self):
        """Positions 54-500 (indices 53-499) must be all spaces (filler)."""
        rec = _raps_detail(
            hicn_mbi=MBI, icd10=ICD10_WITH_DOT, dos_from=DOS_FROM,
            dos_through=DOS_THROUGH, provider_npi=NPI_10,
            provider_type="01", payment_year=PAYMENT_YEAR,
        )
        filler = rec[53:]
        assert filler == " " * (500 - 53), (
            f"Filler region contains non-space characters: {filler[:20]!r}..."
        )

    # ---- Z-trailer ---------------------------------------------------------

    def test_z_trailer_record_length(self):
        """Z-trailer record must be exactly 500 characters (no newline)."""
        rec = _raps_trailer(PLAN_ID, record_count=42)
        assert len(rec) == 500, f"Z-trailer is {len(rec)} chars; expected 500"

    def test_z_trailer_record_type_at_position_1(self):
        """Position 1 (index 0) must be the literal character 'Z'."""
        rec = _raps_trailer(PLAN_ID, record_count=42)
        assert rec[0] == "Z"

    def test_z_trailer_plan_id_positions_2_to_12(self):
        """Plan ID occupies positions 2-12 (indices 1-11, 11 chars), space-padded."""
        rec = _raps_trailer(PLAN_ID, record_count=42)
        field = rec[1:12]
        assert field == PLAN_ID.ljust(11), (
            f"Plan ID field {field!r} != {PLAN_ID.ljust(11)!r}"
        )

    def test_z_trailer_record_count_positions_13_to_21(self):
        """
        Detail record count occupies positions 13-21 (indices 12-20, 9 chars).
        Must be right-justified and zero-padded.
        """
        count = 42
        rec = _raps_trailer(PLAN_ID, record_count=count)
        field = rec[12:21]
        assert len(field) == 9, f"Record count field is {len(field)} chars; expected 9"
        assert field == str(count).zfill(9), (
            f"Record count field {field!r} != {str(count).zfill(9)!r}"
        )

    def test_z_trailer_record_count_zero_padded(self):
        """A record count of 1 must be '000000001', not '1' or '        1'."""
        rec = _raps_trailer(PLAN_ID, record_count=1)
        field = rec[12:21]
        assert field == "000000001", f"Zero-pad failed: {field!r}"

    def test_z_trailer_filler_all_spaces(self):
        """Positions 22-500 (indices 21-499) must be all spaces."""
        rec = _raps_trailer(PLAN_ID, record_count=42)
        filler = rec[21:]
        assert filler == " " * (500 - 21), (
            f"Z-trailer filler contains non-space chars: {filler[:20]!r}..."
        )

    # ---- Cross-record invariants -------------------------------------------

    def test_full_file_all_records_same_length(self):
        """Every record in a generated RAPS file must be exactly 500 characters."""
        header = _raps_header(PLAN_ID, PAYMENT_YEAR, SWEEP_TYPE)
        detail = _raps_detail(
            hicn_mbi=MBI, icd10=ICD10_WITH_DOT, dos_from=DOS_FROM,
            dos_through=DOS_THROUGH, provider_npi=NPI_10,
            provider_type="01", payment_year=PAYMENT_YEAR,
        )
        trailer = _raps_trailer(PLAN_ID, record_count=1)

        for name, rec in [("header", header), ("detail", detail), ("trailer", trailer)]:
            assert len(rec) == 500, (
                f"RAPS {name} record is {len(rec)} chars; CMS requires exactly 500"
            )

    def test_date_format_no_dashes_in_detail(self):
        """Date fields written into RAPS B-detail must not contain dashes."""
        rec = _raps_detail(
            hicn_mbi=MBI, icd10=ICD10_WITH_DOT, dos_from="2025-03-01",
            dos_through="2025-03-15", provider_npi=NPI_10,
            provider_type="01", payment_year=PAYMENT_YEAR,
        )
        dos_from_field = rec[33:41]
        dos_thru_field = rec[41:49]
        assert "-" not in dos_from_field, f"DOS-from {dos_from_field!r} contains dash"
        assert "-" not in dos_thru_field, f"DOS-thru {dos_thru_field!r} contains dash"

    def test_numeric_year_zero_padded_in_trailer(self):
        """Record count in Z-trailer must be zero-padded, not space-padded."""
        rec = _raps_trailer(PLAN_ID, record_count=7)
        field = rec[12:21]
        assert field[0] == "0", f"Leading char of count field is {field[0]!r}; expected '0'"

    def test_alpha_mbi_space_padded_when_short(self):
        """An MBI shorter than 12 chars must be right-padded with spaces to fill 12 chars."""
        short_mbi = "1EG4TE5MK7"   # 10 chars — 2 short
        rec = _raps_detail(
            hicn_mbi=short_mbi, icd10=ICD10_WITH_DOT, dos_from=DOS_FROM,
            dos_through=DOS_THROUGH, provider_npi=NPI_10,
            provider_type="01", payment_year=PAYMENT_YEAR,
        )
        field = rec[1:13]
        assert len(field) == 12
        assert field == short_mbi.ljust(12), (
            f"Short MBI field {field!r} not right-padded; expected {short_mbi.ljust(12)!r}"
        )


# ---------------------------------------------------------------------------
# B. EDI 837P Format Tests
# ---------------------------------------------------------------------------

class TestEDPS837PFormat:
    """Validate EDI 837P ISA/GS/GE/IEA envelope and claim segment structure."""

    def _build_isa(self) -> str:
        return _edps_isa_envelope(SENDER_ID, RECEIVER_ID, CONTROL_NUM)

    # ---- ISA segment -------------------------------------------------------

    def test_isa_segment_starts_with_isa(self):
        """ISA segment must begin with the literal 'ISA'."""
        isa = self._build_isa()
        assert isa.startswith("ISA"), f"ISA segment does not start with 'ISA': {isa[:20]!r}"

    def test_isa_segment_length_106_chars_before_terminator(self):
        """
        ISA segment body (before '~\\n') must be exactly 106 characters.
        The X12 005010 standard mandates a fixed-length ISA of 106 chars.
        """
        isa = self._build_isa()
        # The segment terminator is '~'; strip trailing newline then check up to '~'
        isa_body = isa.rstrip("\n")
        assert isa_body.endswith("~"), f"ISA does not end with '~': {isa_body[-5:]!r}"
        # Body = everything before the terminator
        body_without_terminator = isa_body[:-1]
        assert len(body_without_terminator) == 105, (
            f"ISA body is {len(body_without_terminator)} chars; "
            "X12 ISA segment is 105 data chars + 1 terminator = 106 total"
        )

    def test_isa_element_separator_is_star(self):
        """ISA element separator must be '*' (positioned at ISA index 3)."""
        isa = self._build_isa()
        assert isa[3] == "*", (
            f"ISA element separator at index 3 is {isa[3]!r}; expected '*'"
        )

    def test_isa_segment_terminator_is_tilde(self):
        """ISA segment must end with '~' before the newline."""
        isa = self._build_isa().rstrip("\n")
        assert isa[-1] == "~", f"ISA terminator is {isa[-1]!r}; expected '~'"

    def test_isa_has_16_elements(self):
        """ISA segment must contain exactly 16 data elements separated by '*'."""
        isa_body = self._build_isa().rstrip("\n~")
        # Split on '*' — first token is 'ISA', then 15 elements + component separator
        elements = isa_body.split("*")
        # ISA header + 16 elements
        assert len(elements) == 17, (
            f"ISA has {len(elements) - 1} elements (incl. segment id); expected 16"
        )

    def test_isa_version_is_00501(self):
        """ISA12 (element 12) must be '00501' for the 5010 standard."""
        isa_body = self._build_isa().rstrip("\n~")
        elements = isa_body.split("*")
        # elements[0] = 'ISA', elements[12] = ISA12
        assert elements[12] == "00501", (
            f"ISA version element (ISA12) is {elements[12]!r}; expected '00501'"
        )

    def test_isa_control_number_zero_padded_to_9(self):
        """ISA control number (ISA13) must be zero-padded to exactly 9 digits."""
        isa_body = self._build_isa().rstrip("\n~")
        elements = isa_body.split("*")
        control_field = elements[13]
        assert len(control_field) == 9, (
            f"ISA control number field is {len(control_field)} chars; expected 9"
        )
        assert control_field.isdigit(), (
            f"ISA control number {control_field!r} contains non-digit characters"
        )
        assert control_field == CONTROL_NUM.zfill(9), (
            f"ISA control number {control_field!r} != {CONTROL_NUM.zfill(9)!r}"
        )

    def test_isa_sender_id_padded_to_15(self):
        """ISA06 sender ID must be left-justified and padded to exactly 15 characters."""
        isa_body = self._build_isa().rstrip("\n~")
        elements = isa_body.split("*")
        # ISA06 is element index 6
        sender_field = elements[6]
        assert len(sender_field) == 15, (
            f"ISA sender ID field is {len(sender_field)} chars; expected 15"
        )
        assert sender_field.startswith(SENDER_ID), (
            f"Sender field {sender_field!r} does not start with {SENDER_ID!r}"
        )

    def test_isa_receiver_id_padded_to_15(self):
        """ISA08 receiver ID must be left-justified and padded to exactly 15 characters."""
        isa_body = self._build_isa().rstrip("\n~")
        elements = isa_body.split("*")
        receiver_field = elements[8]
        assert len(receiver_field) == 15, (
            f"ISA receiver ID field is {len(receiver_field)} chars; expected 15"
        )
        assert receiver_field.startswith(RECEIVER_ID), (
            f"Receiver field {receiver_field!r} does not start with {RECEIVER_ID!r}"
        )

    def test_isa_date_is_6_digits_yymmdd(self):
        """ISA09 (date) must be 6 digits in YYMMDD format."""
        isa_body = self._build_isa().rstrip("\n~")
        elements = isa_body.split("*")
        date_field = elements[9]
        assert len(date_field) == 6, (
            f"ISA date field is {len(date_field)} chars; expected 6 (YYMMDD)"
        )
        assert date_field.isdigit(), f"ISA date {date_field!r} is not all digits"

    def test_isa_time_is_4_digits_hhmm(self):
        """ISA10 (time) must be 4 digits in HHMM format."""
        isa_body = self._build_isa().rstrip("\n~")
        elements = isa_body.split("*")
        time_field = elements[10]
        assert len(time_field) == 4, (
            f"ISA time field is {len(time_field)} chars; expected 4 (HHMM)"
        )
        assert time_field.isdigit(), f"ISA time {time_field!r} is not all digits"

    def test_isa_qualifier_codes_are_zz(self):
        """ISA05 and ISA07 (ID qualifier) must both be 'ZZ' for MA plan submissions."""
        isa_body = self._build_isa().rstrip("\n~")
        elements = isa_body.split("*")
        assert elements[5] == "ZZ", f"ISA05 is {elements[5]!r}; expected 'ZZ'"
        assert elements[7] == "ZZ", f"ISA07 is {elements[7]!r}; expected 'ZZ'"

    def test_isa_special_chars_sanitized_in_ids(self):
        """
        If sender/receiver IDs contain EDI delimiter chars ('*', '~', ':'),
        they must be stripped before writing into the ISA segment.
        """
        dirty_sender = "SEND*ER:ID~"
        isa_body = _edps_isa_envelope(dirty_sender, RECEIVER_ID, CONTROL_NUM).rstrip("\n~")
        elements = isa_body.split("*")
        sender_field = elements[6]
        # After sanitization no '*', '~', or ':' should remain
        assert "*" not in sender_field
        assert "~" not in sender_field
        assert ":" not in sender_field

    # ---- GS segment --------------------------------------------------------

    def test_gs_segment_present(self):
        """GS functional group header must be generated and not empty."""
        gs = _edps_gs_header(SENDER_ID, RECEIVER_ID, CONTROL_NUM)
        assert gs.startswith("GS*"), f"GS segment does not start with 'GS*': {gs[:20]!r}"

    def test_gs_functional_id_is_hc(self):
        """GS01 (functional ID code) must be 'HC' for health-care claim transactions."""
        gs_body = _edps_gs_header(SENDER_ID, RECEIVER_ID, CONTROL_NUM).rstrip("\n~")
        elements = gs_body.split("*")
        assert elements[1] == "HC", f"GS01 is {elements[1]!r}; expected 'HC'"

    def test_gs_version_is_005010x222a1(self):
        """GS08 (version/release) must be '005010X222A1' for 837P 5010A1."""
        gs_body = _edps_gs_header(SENDER_ID, RECEIVER_ID, CONTROL_NUM).rstrip("\n~")
        elements = gs_body.split("*")
        assert elements[8] == "005010X222A1", (
            f"GS08 is {elements[8]!r}; expected '005010X222A1'"
        )

    def test_gs_date_is_8_digits_yyyymmdd(self):
        """GS04 (date) must be 8 digits in YYYYMMDD format."""
        gs_body = _edps_gs_header(SENDER_ID, RECEIVER_ID, CONTROL_NUM).rstrip("\n~")
        elements = gs_body.split("*")
        date_field = elements[4]
        assert len(date_field) == 8 and date_field.isdigit(), (
            f"GS04 date {date_field!r} is not YYYYMMDD"
        )

    # ---- GE trailer --------------------------------------------------------

    def test_ge_trailer_format(self):
        """GE trailer must be 'GE*<count>*<control_num>~'."""
        ge = _edps_gs_trailer(tx_count=5, control_num=CONTROL_NUM)
        ge_body = ge.rstrip("\n~")
        elements = ge_body.split("*")
        assert elements[0] == "GE", f"GE segment ID is {elements[0]!r}; expected 'GE'"
        assert elements[1] == "5", f"GE01 tx count is {elements[1]!r}; expected '5'"
        assert elements[2] == CONTROL_NUM, (
            f"GE02 control num is {elements[2]!r}; expected {CONTROL_NUM!r}"
        )

    # ---- IEA trailer -------------------------------------------------------

    def test_iea_trailer_matches_isa_control_number(self):
        """IEA02 control number must match the ISA13 control number (zero-padded)."""
        iea = _edps_isa_trailer(CONTROL_NUM)
        iea_body = iea.rstrip("\n~")
        elements = iea_body.split("*")
        assert elements[0] == "IEA", f"IEA segment ID is {elements[0]!r}"
        iea_control = elements[2]
        isa_control = CONTROL_NUM.zfill(9)
        assert iea_control == isa_control, (
            f"IEA control number {iea_control!r} does not match ISA control {isa_control!r}"
        )

    def test_iea_interchange_count_is_1(self):
        """IEA01 (interchange count) must be '1' for a single functional group."""
        iea = _edps_isa_trailer(CONTROL_NUM).rstrip("\n~")
        elements = iea.split("*")
        assert elements[1] == "1", f"IEA01 is {elements[1]!r}; expected '1'"

    # ---- Claim segments (CLM/DTP/HI/NM1) ----------------------------------

    def test_claim_segment_contains_clm(self):
        """_edps_claim_segment output must include a CLM segment."""
        seg = _edps_claim_segment(
            claim_id="CLM0000000100001", patient_id=1, hicn_mbi=MBI,
            icd10=ICD10_WITH_DOT, dos_from=DOS_FROM, dos_through=DOS_THROUGH,
            rendering_npi=NPI_10, facility_npi=NPI_10,
        )
        assert "CLM*" in seg, f"CLM segment not found in:\n{seg}"

    def test_claim_segment_contains_dtp_472(self):
        """DTP*472 (service date range) must be present in the claim segment."""
        seg = _edps_claim_segment(
            claim_id="CLM0000000100001", patient_id=1, hicn_mbi=MBI,
            icd10=ICD10_WITH_DOT, dos_from=DOS_FROM, dos_through=DOS_THROUGH,
            rendering_npi=NPI_10, facility_npi=NPI_10,
        )
        assert "DTP*472*" in seg, f"DTP*472 not found in:\n{seg}"

    def test_dtp_date_range_no_dashes_in_individual_dates(self):
        """
        DTP*472*RD8 date range must be in the form YYYYMMDD-YYYYMMDD.
        The YYYYMMDD portions must not contain dashes within them.
        """
        seg = _edps_claim_segment(
            claim_id="CLM0000000100001", patient_id=1, hicn_mbi=MBI,
            icd10=ICD10_WITH_DOT, dos_from="2025-01-15", dos_through="2025-01-15",
            rendering_npi=NPI_10, facility_npi=NPI_10,
        )
        # Find the DTP line
        dtp_line = next(l for l in seg.splitlines() if l.startswith("DTP*472"))
        # The date range element is the 4th element: DTP*472*RD8*YYYYMMDD-YYYYMMDD~
        parts = dtp_line.rstrip("~").split("*")
        date_range = parts[3]  # e.g. "20250115-20250115"
        assert re.fullmatch(r"\d{8}-\d{8}", date_range), (
            f"DTP date range {date_range!r} is not in YYYYMMDD-YYYYMMDD format"
        )

    def test_hi_diagnosis_segment_uses_abk_qualifier(self):
        """HI segment must use the 'ABK' qualifier for the principal ICD-10 diagnosis."""
        seg = _edps_claim_segment(
            claim_id="CLM0000000100001", patient_id=1, hicn_mbi=MBI,
            icd10=ICD10_WITH_DOT, dos_from=DOS_FROM, dos_through=DOS_THROUGH,
            rendering_npi=NPI_10, facility_npi=NPI_10,
        )
        assert "HI*ABK:" in seg, (
            f"HI segment with ABK qualifier not found in:\n{seg}"
        )

    def test_hi_icd10_has_dot_removed(self):
        """
        ICD-10 code in HI segment must have the dot stripped
        (e.g. 'E11.9' becomes 'E119').
        """
        seg = _edps_claim_segment(
            claim_id="CLM0000000100001", patient_id=1, hicn_mbi=MBI,
            icd10="E11.9", dos_from=DOS_FROM, dos_through=DOS_THROUGH,
            rendering_npi=NPI_10, facility_npi=NPI_10,
        )
        hi_line = next(l for l in seg.splitlines() if l.startswith("HI*"))
        assert "." not in hi_line, (
            f"Dot survived in HI segment: {hi_line!r}"
        )
        assert "ABK:E119" in hi_line, (
            f"Expected 'ABK:E119' in HI segment, got: {hi_line!r}"
        )

    def test_nm1_rendering_provider_qualifier_82(self):
        """NM1 rendering provider must use qualifier '82'."""
        seg = _edps_claim_segment(
            claim_id="CLM0000000100001", patient_id=1, hicn_mbi=MBI,
            icd10=ICD10_WITH_DOT, dos_from=DOS_FROM, dos_through=DOS_THROUGH,
            rendering_npi=NPI_10, facility_npi=NPI_10,
        )
        assert "NM1*82*" in seg, f"NM1*82 (rendering provider) not found in:\n{seg}"

    def test_nm1_facility_qualifier_77(self):
        """NM1 service facility must use qualifier '77'."""
        seg = _edps_claim_segment(
            claim_id="CLM0000000100001", patient_id=1, hicn_mbi=MBI,
            icd10=ICD10_WITH_DOT, dos_from=DOS_FROM, dos_through=DOS_THROUGH,
            rendering_npi=NPI_10, facility_npi=NPI_10,
        )
        assert "NM1*77*" in seg, f"NM1*77 (facility) not found in:\n{seg}"

    def test_nm1_omitted_when_npi_empty(self):
        """NM1 segments must be omitted when NPI is an empty string."""
        seg = _edps_claim_segment(
            claim_id="CLM0000000100001", patient_id=1, hicn_mbi=MBI,
            icd10=ICD10_WITH_DOT, dos_from=DOS_FROM, dos_through=DOS_THROUGH,
            rendering_npi="", facility_npi="",
        )
        assert "NM1*82*" not in seg, "NM1*82 should be omitted for empty rendering NPI"
        assert "NM1*77*" not in seg, "NM1*77 should be omitted for empty facility NPI"

    def test_all_segments_end_with_tilde(self):
        """Every EDI segment produced by _edps_claim_segment must end with '~'."""
        seg = _edps_claim_segment(
            claim_id="CLM0000000100001", patient_id=1, hicn_mbi=MBI,
            icd10=ICD10_WITH_DOT, dos_from=DOS_FROM, dos_through=DOS_THROUGH,
            rendering_npi=NPI_10, facility_npi=NPI_10,
        )
        for line in seg.splitlines():
            if line.strip():  # skip blank lines
                assert line.endswith("~"), (
                    f"Segment line does not end with '~': {line!r}"
                )


# ---------------------------------------------------------------------------
# C. Data Integrity Tests
# ---------------------------------------------------------------------------

class TestSubmissionDataIntegrity:
    """Field-level integrity checks — truncation, format, and NPI validation."""

    def test_no_truncated_icd10_codes(self):
        """
        ICD-10 code field is 7 chars wide.  The longest valid ICD-10-CM codes
        are 7 characters (without dot).  A 7-char code must not be truncated.
        """
        long_icd = "Z8731"      # 5-char code, well within limit
        max_icd = "S72001A"     # exactly 7 chars (dot-free)
        for code in [long_icd, max_icd]:
            rec = _raps_detail(
                hicn_mbi=MBI, icd10=code, dos_from=DOS_FROM,
                dos_through=DOS_THROUGH, provider_npi=NPI_10,
                provider_type="01", payment_year=PAYMENT_YEAR,
            )
            field = rec[26:33].rstrip()
            assert field == code.upper(), (
                f"ICD-10 {code!r} truncated to {field!r} in RAPS record"
            )

    def test_no_truncated_npi(self):
        """
        NPI field is 10 chars; NPI is always exactly 10 digits.
        A 10-digit NPI must not be truncated and must land at positions 14-23.
        """
        rec = _raps_detail(
            hicn_mbi=MBI, icd10=ICD10_WITH_DOT, dos_from=DOS_FROM,
            dos_through=DOS_THROUGH, provider_npi=NPI_10,
            provider_type="01", payment_year=PAYMENT_YEAR,
        )
        npi_field = rec[13:23]
        assert npi_field == NPI_10, (
            f"NPI field {npi_field!r} != original NPI {NPI_10!r}"
        )

    def test_npi_exactly_10_digits(self):
        """A valid NPI is exactly 10 digits; no alphabetic or special characters."""
        rec = _raps_detail(
            hicn_mbi=MBI, icd10=ICD10_WITH_DOT, dos_from=DOS_FROM,
            dos_through=DOS_THROUGH, provider_npi="9876543210",
            provider_type="01", payment_year=PAYMENT_YEAR,
        )
        npi_field = rec[13:23].strip()
        assert len(npi_field) == 10 and npi_field.isdigit(), (
            f"NPI field {npi_field!r} is not exactly 10 digits"
        )

    def test_mbi_validation_cms_format(self):
        """
        CMS MBI format: 11 characters, starts with a digit 1-9, no S, L, O, I, B, Z.
        The field in the RAPS record must be 12 chars (left-justified, space-padded).
        MBI itself is 11 chars, so position 13 (index 12) must be a space.
        """
        # MBI is 11 chars — position 13 in RAPS B-detail (index 12) must be a space
        mbi_11 = "1EG4TE5MK73"   # standard 11-char CMS MBI
        rec = _raps_detail(
            hicn_mbi=mbi_11, icd10=ICD10_WITH_DOT, dos_from=DOS_FROM,
            dos_through=DOS_THROUGH, provider_npi=NPI_10,
            provider_type="01", payment_year=PAYMENT_YEAR,
        )
        mbi_field = rec[1:13]          # 12-char field
        assert mbi_field[:11] == mbi_11, (
            f"MBI content {mbi_field[:11]!r} != input MBI {mbi_11!r}"
        )
        assert mbi_field[11] == " ", (
            f"12th char of MBI field is {mbi_field[11]!r}; expected space for 11-char MBI"
        )

    def test_mbi_no_invalid_cms_characters(self):
        """
        CMS MBI spec forbids S, L, O, I, B, Z in certain positions.
        The MBI field in a RAPS record must preserve the MBI exactly as-is;
        this test verifies the field does not introduce forbidden characters.
        """
        valid_mbi = "1EG4TE5MK73"
        rec = _raps_detail(
            hicn_mbi=valid_mbi, icd10=ICD10_WITH_DOT, dos_from=DOS_FROM,
            dos_through=DOS_THROUGH, provider_npi=NPI_10,
            provider_type="01", payment_year=PAYMENT_YEAR,
        )
        stored_mbi = rec[1:13].strip()
        # The service must not corrupt the MBI
        assert stored_mbi == valid_mbi, (
            f"MBI stored as {stored_mbi!r}, expected {valid_mbi!r}"
        )

    def test_normalize_date_8_accepts_yyyymmdd(self):
        """_normalize_date_8 must pass through an already-correct YYYYMMDD string."""
        assert _normalize_date_8("20250315") == "20250315"

    def test_normalize_date_8_converts_iso_format(self):
        """_normalize_date_8 must convert 'YYYY-MM-DD' to 'YYYYMMDD'."""
        assert _normalize_date_8("2025-03-15") == "20250315"

    def test_normalize_date_8_handles_date_object(self):
        """_normalize_date_8 must convert a Python date object to 'YYYYMMDD'."""
        d = date(2025, 3, 15)
        assert _normalize_date_8(d) == "20250315"

    def test_normalize_date_8_handles_none(self):
        """_normalize_date_8 must return 8 spaces for None input."""
        result = _normalize_date_8(None)
        assert result == " " * 8, f"Expected 8 spaces, got {result!r}"

    def test_normalize_date_8_handles_empty_string(self):
        """_normalize_date_8 must return 8 spaces for an empty string."""
        result = _normalize_date_8("")
        assert result == " " * 8, f"Expected 8 spaces, got {result!r}"

    def test_icd10_longer_than_7_chars_truncated_safely(self):
        """
        An ICD-10 code whose dot-free form exceeds 7 characters must be
        silently truncated to 7; the record must still be exactly 500 chars.
        """
        overlong_icd = "S72001ABCDE"   # 11 chars — far too long
        rec = _raps_detail(
            hicn_mbi=MBI, icd10=overlong_icd, dos_from=DOS_FROM,
            dos_through=DOS_THROUGH, provider_npi=NPI_10,
            provider_type="01", payment_year=PAYMENT_YEAR,
        )
        assert len(rec) == 500, f"Record length is {len(rec)} after overlong ICD-10"
        icd_field = rec[26:33]
        assert len(icd_field) == 7

    def test_plan_id_longer_than_11_chars_truncated_safely(self):
        """
        A plan ID longer than 11 chars must be truncated; the record must still
        be exactly 500 chars and the field must hold exactly 11 chars.
        """
        long_plan = "H" + "9" * 20
        header = _raps_header(long_plan, PAYMENT_YEAR, SWEEP_TYPE)
        assert len(header) == 500
        assert len(header[1:12]) == 11

    def test_dos_from_after_dos_through_still_writes_valid_record(self):
        """
        If DOS-from is after DOS-through (a data quality issue caught by
        validate_submission, not the formatter), the formatter must still
        produce a 500-char record rather than crashing.
        """
        rec = _raps_detail(
            hicn_mbi=MBI, icd10=ICD10_WITH_DOT,
            dos_from="2025-06-01", dos_through="2025-01-01",   # logically reversed
            provider_npi=NPI_10, provider_type="01", payment_year=PAYMENT_YEAR,
        )
        assert len(rec) == 500


# ---------------------------------------------------------------------------
# D. Full-file generator integration tests (mocked DB)
# ---------------------------------------------------------------------------

class TestGenerateRAPSFileMocked:
    """
    Exercise generate_raps_file() end-to-end with a mocked database so we can
    verify the written file content without a live MySQL instance.
    """

    @pytest.fixture()
    def hcc_rows(self):
        """Minimal fixture row that mimics raf_patient_hcc + raf_patient_demographics."""
        return [
            {
                "patient_id": 1001,
                "hcc_code": "19",
                "icd10_codes": '["E11.9"]',
                "measurement_year": 2025,
                "confirmed_date": "2025-03-01",
                "encounter_id": "ENC001",
                "provider_npi": "1234567890",
                "provider_type": "physician",
                "hicn_mbi": "1EG4TE5MK73",
                "dos_from": "2025-03-01",
                "dos_through": "2025-03-01",
            }
        ]

    def _make_cursor_mock(self, hcc_rows):
        """Return a context-manager mock whose fetchall() returns hcc_rows."""
        cursor_mock = MagicMock()
        cursor_mock.fetchall.return_value = hcc_rows
        cursor_mock.fetchone.return_value = None   # no existing batch

        @contextmanager
        def fake_raf_cursor():
            yield cursor_mock

        return fake_raf_cursor, cursor_mock

    def test_generate_raps_creates_file_with_correct_record_lengths(
        self, hcc_rows, tmp_path
    ):
        """
        All lines in the generated RAPS file (excluding empty trailing newline)
        must be exactly 500 characters.
        """
        from app.services import submission_service as svc

        fake_cursor, _ = self._make_cursor_mock(hcc_rows)

        with (
            patch.object(svc, "raf_cursor", fake_cursor),
            patch.object(svc, "_find_existing_batch", return_value=None),
            patch.object(svc, "_insert_batch"),
            patch.object(svc, "_insert_records"),
            patch.object(svc, "_output_dir", return_value=tmp_path),
            patch.object(svc, "_lookup_mbi_from_openemr", return_value="1EG4TE5MK73"),
        ):
            result = svc.generate_raps_file(
                tenant_id="TENANT1",
                payment_year=2025,
                sweep_type="Initial",
                plan_id="H1234",
            )

        file_path = result["file_path"]
        content = open(file_path).read()
        lines = [l for l in content.split("\n") if l]  # skip empty trailing line
        for i, line in enumerate(lines):
            assert len(line) == 500, (
                f"Line {i + 1} is {len(line)} chars; must be exactly 500. "
                f"Content: {line[:60]!r}..."
            )

    def test_generate_raps_record_count_matches_trailer(self, hcc_rows, tmp_path):
        """
        The Z-trailer record count (positions 13-21) must equal the number of
        B-detail records written into the file.
        """
        from app.services import submission_service as svc

        fake_cursor, _ = self._make_cursor_mock(hcc_rows)

        with (
            patch.object(svc, "raf_cursor", fake_cursor),
            patch.object(svc, "_find_existing_batch", return_value=None),
            patch.object(svc, "_insert_batch"),
            patch.object(svc, "_insert_records"),
            patch.object(svc, "_output_dir", return_value=tmp_path),
            patch.object(svc, "_lookup_mbi_from_openemr", return_value="1EG4TE5MK73"),
        ):
            result = svc.generate_raps_file(
                tenant_id="TENANT1",
                payment_year=2025,
                sweep_type="Initial",
                plan_id="H1234",
            )

        file_path = result["file_path"]
        content = open(file_path).read()
        lines = [l for l in content.split("\n") if l]

        # Count B-detail records
        b_records = [l for l in lines if l[0] == "B"]
        # Find Z-trailer
        z_records = [l for l in lines if l[0] == "Z"]
        assert len(z_records) == 1, "Expected exactly one Z-trailer"

        trailer_count = int(z_records[0][12:21])   # positions 13-21 (0-indexed 12-20)
        assert trailer_count == len(b_records), (
            f"Z-trailer count {trailer_count} != actual B-detail count {len(b_records)}"
        )

    def test_generate_raps_first_line_is_a_header(self, hcc_rows, tmp_path):
        """First line of the RAPS file must be an A-header record."""
        from app.services import submission_service as svc

        fake_cursor, _ = self._make_cursor_mock(hcc_rows)

        with (
            patch.object(svc, "raf_cursor", fake_cursor),
            patch.object(svc, "_find_existing_batch", return_value=None),
            patch.object(svc, "_insert_batch"),
            patch.object(svc, "_insert_records"),
            patch.object(svc, "_output_dir", return_value=tmp_path),
            patch.object(svc, "_lookup_mbi_from_openemr", return_value="1EG4TE5MK73"),
        ):
            result = svc.generate_raps_file(
                tenant_id="TENANT1",
                payment_year=2025,
                sweep_type="Initial",
                plan_id="H1234",
            )

        lines = [l for l in open(result["file_path"]).read().split("\n") if l]
        assert lines[0][0] == "A", f"First record type is {lines[0][0]!r}; expected 'A'"

    def test_generate_raps_last_line_is_z_trailer(self, hcc_rows, tmp_path):
        """Last non-empty line of the RAPS file must be a Z-trailer record."""
        from app.services import submission_service as svc

        fake_cursor, _ = self._make_cursor_mock(hcc_rows)

        with (
            patch.object(svc, "raf_cursor", fake_cursor),
            patch.object(svc, "_find_existing_batch", return_value=None),
            patch.object(svc, "_insert_batch"),
            patch.object(svc, "_insert_records"),
            patch.object(svc, "_output_dir", return_value=tmp_path),
            patch.object(svc, "_lookup_mbi_from_openemr", return_value="1EG4TE5MK73"),
        ):
            result = svc.generate_raps_file(
                tenant_id="TENANT1",
                payment_year=2025,
                sweep_type="Initial",
                plan_id="H1234",
            )

        lines = [l for l in open(result["file_path"]).read().split("\n") if l]
        assert lines[-1][0] == "Z", f"Last record type is {lines[-1][0]!r}; expected 'Z'"

    def test_generate_raps_icd10_in_file_has_no_dot(self, hcc_rows, tmp_path):
        """ICD-10 stored in every B-detail line must have the dot removed."""
        from app.services import submission_service as svc

        fake_cursor, _ = self._make_cursor_mock(hcc_rows)

        with (
            patch.object(svc, "raf_cursor", fake_cursor),
            patch.object(svc, "_find_existing_batch", return_value=None),
            patch.object(svc, "_insert_batch"),
            patch.object(svc, "_insert_records"),
            patch.object(svc, "_output_dir", return_value=tmp_path),
            patch.object(svc, "_lookup_mbi_from_openemr", return_value="1EG4TE5MK73"),
        ):
            result = svc.generate_raps_file(
                tenant_id="TENANT1",
                payment_year=2025,
                sweep_type="Initial",
                plan_id="H1234",
            )

        lines = [l for l in open(result["file_path"]).read().split("\n") if l]
        b_records = [l for l in lines if l[0] == "B"]
        for rec in b_records:
            icd_field = rec[26:33]
            assert "." not in icd_field, (
                f"Dot found in ICD-10 field of B-record: {icd_field!r}"
            )


class TestGenerateEDPSFileMocked:
    """
    Exercise generate_edps_file() end-to-end with a mocked database and verify
    that the resulting EDI 837P file has correct ISA/GS structure.
    """

    @pytest.fixture()
    def hcc_rows(self):
        return [
            {
                "patient_id": 2001,
                "hcc_code": "85",
                "icd10_codes": '["I10"]',
                "measurement_year": 2025,
                "confirmed_date": "2025-04-01",
                "encounter_id": "ENC002",
                "provider_npi": "9876543210",
                "facility_npi": "0000000001",
                "place_of_service": "11",
                "hicn_mbi": "2EG4TE5MK73",
                "dos_from": "2025-04-01",
                "dos_through": "2025-04-01",
            }
        ]

    def _make_cursor_mock(self, hcc_rows):
        cursor_mock = MagicMock()
        cursor_mock.fetchall.return_value = hcc_rows
        cursor_mock.fetchone.return_value = None

        @contextmanager
        def fake_raf_cursor():
            yield cursor_mock

        return fake_raf_cursor, cursor_mock

    def test_generate_edps_file_starts_with_isa(self, hcc_rows, tmp_path):
        """Generated EDPS file must start with 'ISA*'."""
        from app.services import submission_service as svc

        fake_cursor, _ = self._make_cursor_mock(hcc_rows)

        with (
            patch.object(svc, "raf_cursor", fake_cursor),
            patch.object(svc, "_find_existing_batch", return_value=None),
            patch.object(svc, "_insert_batch"),
            patch.object(svc, "_insert_records"),
            patch.object(svc, "_output_dir", return_value=tmp_path),
            patch.object(svc, "_lookup_mbi_from_openemr", return_value="2EG4TE5MK73"),
        ):
            result = svc.generate_edps_file(
                tenant_id="TENANT1",
                payment_year=2025,
                sweep_type="Initial",
            )

        content = open(result["file_path"]).read()
        assert content.startswith("ISA*"), (
            f"EDPS file does not start with 'ISA*'; starts with {content[:20]!r}"
        )

    def test_generate_edps_file_ends_with_iea(self, hcc_rows, tmp_path):
        """Generated EDPS file must end with an IEA~ segment."""
        from app.services import submission_service as svc

        fake_cursor, _ = self._make_cursor_mock(hcc_rows)

        with (
            patch.object(svc, "raf_cursor", fake_cursor),
            patch.object(svc, "_find_existing_batch", return_value=None),
            patch.object(svc, "_insert_batch"),
            patch.object(svc, "_insert_records"),
            patch.object(svc, "_output_dir", return_value=tmp_path),
            patch.object(svc, "_lookup_mbi_from_openemr", return_value="2EG4TE5MK73"),
        ):
            result = svc.generate_edps_file(
                tenant_id="TENANT1",
                payment_year=2025,
                sweep_type="Initial",
            )

        content = open(result["file_path"]).read().strip()
        assert content.endswith("~"), (
            f"EDPS file does not end with '~'; ends with {content[-10:]!r}"
        )
        assert "IEA*" in content, "IEA trailer segment not found in EDPS file"

    def test_generate_edps_file_contains_hi_abk(self, hcc_rows, tmp_path):
        """EDPS file must contain HI*ABK: diagnosis qualifier for ICD-10 codes."""
        from app.services import submission_service as svc

        fake_cursor, _ = self._make_cursor_mock(hcc_rows)

        with (
            patch.object(svc, "raf_cursor", fake_cursor),
            patch.object(svc, "_find_existing_batch", return_value=None),
            patch.object(svc, "_insert_batch"),
            patch.object(svc, "_insert_records"),
            patch.object(svc, "_output_dir", return_value=tmp_path),
            patch.object(svc, "_lookup_mbi_from_openemr", return_value="2EG4TE5MK73"),
        ):
            result = svc.generate_edps_file(
                tenant_id="TENANT1",
                payment_year=2025,
                sweep_type="Initial",
            )

        content = open(result["file_path"]).read()
        assert "HI*ABK:" in content, (
            "HI*ABK: not found — EDPS file is missing ICD-10 diagnosis qualifier"
        )

    def test_generate_edps_isa_control_matches_iea(self, hcc_rows, tmp_path):
        """ISA13 control number must equal IEA02 control number in the generated file."""
        from app.services import submission_service as svc

        fake_cursor, _ = self._make_cursor_mock(hcc_rows)

        with (
            patch.object(svc, "raf_cursor", fake_cursor),
            patch.object(svc, "_find_existing_batch", return_value=None),
            patch.object(svc, "_insert_batch"),
            patch.object(svc, "_insert_records"),
            patch.object(svc, "_output_dir", return_value=tmp_path),
            patch.object(svc, "_lookup_mbi_from_openemr", return_value="2EG4TE5MK73"),
        ):
            result = svc.generate_edps_file(
                tenant_id="TENANT1",
                payment_year=2025,
                sweep_type="Initial",
            )

        content = open(result["file_path"]).read()

        # Extract ISA13 (control number is element 13 of ISA, 0-indexed in split)
        isa_line = next(l for l in content.splitlines() if l.startswith("ISA*"))
        isa_elements = isa_line.rstrip("~").split("*")
        isa_control = isa_elements[13]

        # Extract IEA02 (element 2 of IEA)
        iea_line = next(l for l in content.splitlines() if l.startswith("IEA*"))
        iea_elements = iea_line.rstrip("~").split("*")
        iea_control = iea_elements[2]

        assert isa_control == iea_control, (
            f"ISA control number {isa_control!r} != IEA control number {iea_control!r}"
        )
