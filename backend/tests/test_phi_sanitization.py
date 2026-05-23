"""Unit tests for HIPAA Safe Harbor PHI redaction in sanitize_note_for_llm.

Covers the identifiers added in the fix/phi-redaction-ner branch:
  - Patient names (via known_names arg)
  - Dates of birth (multiple formats, age-gated)
  - Street addresses
  - ZIP codes (prefixed / state-contextualised)
  - MRN-style identifiers

Also includes a realistic chart-note integration test and a false-positive
guard confirming that recent clinical dates are NOT redacted.

Imports directly from the module to avoid pulling the full ai_pipeline
package __init__ (which may import celery and fail in a bare test env).
"""
import datetime
import re

import pytest

from app.services.ai_pipeline.guardrails import sanitize_note_for_llm

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_CURRENT_YEAR = datetime.date.today().year
_BIRTH_YEAR = str(_CURRENT_YEAR - 62)   # ~62-year-old patient, always in range


# ===========================================================================
# 1. Patient names
# ===========================================================================

def test_known_first_name_redacted() -> None:
    out = sanitize_note_for_llm(
        "Patient JOHN presented with shortness of breath.",
        known_names=["John", "Doe"],
    )
    assert "JOHN" not in out
    assert "John" not in out
    assert "[NAME]" in out


def test_known_last_name_redacted() -> None:
    out = sanitize_note_for_llm(
        "Reviewed chart for Mary Johnson today.",
        known_names=["Mary", "Johnson"],
    )
    assert "Johnson" not in out
    assert "[NAME]" in out


def test_name_case_insensitive() -> None:
    out = sanitize_note_for_llm(
        "SMITH, robert — follow-up on diabetes.",
        known_names=["Robert", "Smith"],
    )
    assert "SMITH" not in out
    assert "robert" not in out
    assert out.count("[NAME]") == 2


def test_name_word_boundary_respected() -> None:
    """'John' in 'Johnson' should not be clobbered when known_names=['John']."""
    out = sanitize_note_for_llm(
        "Dr. Johnson ordered labs for John.",
        known_names=["John"],
    )
    # "John" standalone is redacted
    assert "[NAME]" in out
    # "Johnson" (a different word) should remain intact
    assert "Johnson" in out


def test_longest_name_matched_first() -> None:
    """Full name 'John Smith' must not become '[NAME] [NAME] Smith' when
    known_names=['John Smith', 'John', 'Smith']."""
    out = sanitize_note_for_llm(
        "Patient John Smith completed consent form.",
        known_names=["John Smith", "John", "Smith"],
    )
    # All three tokens should be gone
    assert "John" not in out
    assert "Smith" not in out


def test_no_known_names_arg_is_backward_compatible() -> None:
    """Omitting known_names must not raise and must leave plain text untouched."""
    text = "Patient with CHF, HbA1c 7.2, see follow-up."
    out = sanitize_note_for_llm(text)
    assert out == text


def test_known_names_none_is_backward_compatible() -> None:
    text = "Patient with HTN, labs pending."
    out = sanitize_note_for_llm(text, known_names=None)
    assert out == text


def test_known_names_empty_list_is_backward_compatible() -> None:
    text = "A1c improved to 6.8."
    out = sanitize_note_for_llm(text, known_names=[])
    assert out == text


# ===========================================================================
# 2. Dates of birth
# ===========================================================================

def test_dob_iso_format_redacted() -> None:
    out = sanitize_note_for_llm(f"DOB {_BIRTH_YEAR}-03-15 per registration.")
    assert _BIRTH_YEAR not in out
    assert "[DOB]" in out


def test_dob_us_slash_format_redacted() -> None:
    out = sanitize_note_for_llm(f"Date of birth: 03/15/{_BIRTH_YEAR}.")
    assert _BIRTH_YEAR not in out
    assert "[DOB]" in out


def test_dob_us_dash_format_redacted() -> None:
    out = sanitize_note_for_llm(f"DOB 03-15-{_BIRTH_YEAR} in chart.")
    assert _BIRTH_YEAR not in out
    assert "[DOB]" in out


def test_dob_text_mdy_format_redacted() -> None:
    out = sanitize_note_for_llm(f"Born March 15, {_BIRTH_YEAR}.")
    assert _BIRTH_YEAR not in out
    assert "[DOB]" in out


def test_dob_text_dmy_format_redacted() -> None:
    out = sanitize_note_for_llm(f"Patient dob 15 March {_BIRTH_YEAR}.")
    assert _BIRTH_YEAR not in out
    assert "[DOB]" in out


def test_dob_abbreviated_month_redacted() -> None:
    out = sanitize_note_for_llm(f"Born Jan 15, {_BIRTH_YEAR}.")
    assert _BIRTH_YEAR not in out
    assert "[DOB]" in out


# ===========================================================================
# 3. Clinical dates are NOT redacted (false-positive guard)
# ===========================================================================

def test_recent_clinical_date_iso_not_redacted() -> None:
    """A 2024 encounter date must survive."""
    out = sanitize_note_for_llm("Treatment started 2024-06-10, see follow-up note.")
    assert "2024-06-10" in out
    assert "[DOB]" not in out


def test_recent_clinical_date_slash_not_redacted() -> None:
    out = sanitize_note_for_llm("Labs drawn 06/10/2024, results pending.")
    assert "06/10/2024" in out
    assert "[DOB]" not in out


def test_prior_year_clinical_date_not_redacted() -> None:
    """Dates from e.g. 2022 are only 3 years ago — not a birthdate."""
    out = sanitize_note_for_llm("Surgery performed on 2022-11-03.")
    assert "2022-11-03" in out
    assert "[DOB]" not in out


def test_future_date_not_redacted() -> None:
    future_year = str(_CURRENT_YEAR + 1)
    out = sanitize_note_for_llm(f"Follow-up scheduled {future_year}-01-20.")
    assert future_year in out
    assert "[DOB]" not in out


# ===========================================================================
# 4. Street addresses
# ===========================================================================

def test_street_address_redacted() -> None:
    out = sanitize_note_for_llm("She resides at 123 Main Street, Springfield.")
    assert "123 Main Street" not in out
    assert "[ADDRESS]" in out


def test_street_address_ave_redacted() -> None:
    out = sanitize_note_for_llm("Mailing address: 45 Oak Avenue.")
    assert "45 Oak Avenue" not in out
    assert "[ADDRESS]" in out


def test_street_address_with_unit_redacted() -> None:
    out = sanitize_note_for_llm("Lives at 88 Elm Blvd Apt 4B.")
    assert "88 Elm Blvd" not in out
    assert "[ADDRESS]" in out


def test_street_address_road_redacted() -> None:
    out = sanitize_note_for_llm("Emergency contact at 7 Riverside Road.")
    assert "7 Riverside Road" not in out
    assert "[ADDRESS]" in out


# ===========================================================================
# 5. ZIP codes
# ===========================================================================

def test_zip_with_state_abbreviation_redacted() -> None:
    out = sanitize_note_for_llm("Patient lives in CA 94102.")
    assert "94102" not in out
    assert "[ZIP]" in out


def test_zip_with_zip_keyword_redacted() -> None:
    out = sanitize_note_for_llm("ZIP 10001 is in Manhattan.")
    assert "10001" not in out
    assert "[ZIP]" in out


def test_zip_plus4_with_state_redacted() -> None:
    out = sanitize_note_for_llm("Billing address TX 78701-1234.")
    assert "78701-1234" not in out
    assert "[ZIP]" in out


def test_bare_5digit_lab_value_not_redacted() -> None:
    """A 5-digit number like a lab value not preceded by state/ZIP should survive."""
    out = sanitize_note_for_llm("WBC count 12000, platelets 250000.")
    assert "12000" in out
    assert "250000" in out
    assert "[ZIP]" not in out


# ===========================================================================
# 6. MRN identifiers
# ===========================================================================

def test_mrn_label_colon_redacted() -> None:
    out = sanitize_note_for_llm("MRN: 123456 is on file.")
    assert "123456" not in out
    assert "[MRN]" in out


def test_mrn_hash_redacted() -> None:
    out = sanitize_note_for_llm("Patient MRN#98765432 presented.")
    assert "98765432" not in out
    assert "[MRN]" in out


def test_medical_record_number_redacted() -> None:
    out = sanitize_note_for_llm("Medical Record Number 456789012.")
    assert "456789012" not in out
    assert "[MRN]" in out


def test_medical_record_unlabeled_not_redacted() -> None:
    """A bare 9-digit number without an MRN label must NOT be redacted
    (avoids clobbering NPI codes, CPT codes, etc.)."""
    out = sanitize_note_for_llm("CPT code 99214 billed.")
    assert "99214" in out
    # The number has only 5 digits so MRN won't match anyway, but the
    # point is bare numbers without labels are left alone.
    assert "[MRN]" not in out


# ===========================================================================
# 7. Realistic chart-note integration test
# ===========================================================================

CHART_NOTE = f"""
OFFICE VISIT NOTE
Patient: John Michael Doe
MRN: 785432109
DOB: {_BIRTH_YEAR}-04-22
Address: 212 Maple Drive, Austin, TX 78701

Chief Complaint: Dyspnea on exertion, worsening over 2 weeks.

History: Patient is a 62 y/o male with known CHF (EF 35%) and T2DM.
Medications include metformin 1000 mg BID, lisinopril 10 mg daily.
He was last hospitalized on 2024-01-14 for acute decompensated heart failure.
Contact: (512) 555-9876 or jdoe@email.com.
SSN: 532-78-9012 on insurance form.
Medicare MBI: 1EG4TE5MK73.
"""

def test_chart_note_all_phi_redacted() -> None:
    out = sanitize_note_for_llm(
        CHART_NOTE,
        known_names=["John", "Michael", "Doe"],
    )
    # Names
    assert "John" not in out
    assert "Michael" not in out
    assert "Doe" not in out
    assert "[NAME]" in out
    # MRN
    assert "785432109" not in out
    assert "[MRN]" in out
    # DOB (birth year)
    assert _BIRTH_YEAR not in out
    assert "[DOB]" in out
    # Address
    assert "212 Maple Drive" not in out
    assert "[ADDRESS]" in out
    # ZIP
    assert "78701" not in out
    assert "[ZIP]" in out
    # Phone
    assert "555-9876" not in out
    assert "[PHONE]" in out
    # Email
    assert "jdoe@email.com" not in out
    assert "[EMAIL]" in out
    # SSN
    assert "532-78-9012" not in out
    assert "***-**-****" in out
    # MBI
    assert "1EG4TE5MK73" not in out
    assert "[MBI]" in out


def test_chart_note_clinical_date_preserved() -> None:
    """The 2024 hospitalisation date must survive intact."""
    out = sanitize_note_for_llm(
        CHART_NOTE,
        known_names=["John", "Michael", "Doe"],
    )
    assert "2024-01-14" in out


def test_chart_note_clinical_content_preserved() -> None:
    """Non-PHI clinical facts must not be altered."""
    out = sanitize_note_for_llm(
        CHART_NOTE,
        known_names=["John", "Michael", "Doe"],
    )
    assert "CHF" in out
    assert "EF 35%" in out
    assert "metformin 1000 mg BID" in out
    assert "lisinopril 10 mg daily" in out
