"""
Tests for app.services.ccda_parser — Direct Trust inbound C-CDA XML parser.

Covers:
- parse_ccda_xml returns correct problem count, ICD-10 codes, onset dates.
- Medications extracted: RxNorm codes + doses.
- Lab results extracted: LOINC codes + values + dates.
- Encounters extracted: type, start/end dates, provider NPI.
- Allergies extracted: substance, reaction, severity.
- HCC crosswalk lookup falls back gracefully when DB is unavailable.
- Oversized document raises ValueError.
- Malformed XML raises ValueError.
- parse_ccda_xml returns hcc_suspects list (deduplicated, DB-free path).
"""
from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Synthetic C-CDA XML builder
# ---------------------------------------------------------------------------

_CDA_NS = "urn:hl7-org:v3"


def _build_ccda(
    problems: list[dict] | None = None,
    medications: list[dict] | None = None,
    results: list[dict] | None = None,
    encounters: list[dict] | None = None,
    allergies: list[dict] | None = None,
) -> bytes:
    """Build a minimal but structurally valid C-CDA XML document."""

    def _prob_entry(p: dict) -> str:
        icd_code = p.get("icd10_code", "E11.9")
        name = p.get("name", "Diabetes")
        onset = p.get("onset", "20200101")
        return f"""
        <entry>
          <act classCode="ACT" moodCode="EVN">
            <templateId root="2.16.840.1.113883.10.20.22.4.3"/>
            <entryRelationship typeCode="SUBJ">
              <observation classCode="OBS" moodCode="EVN">
                <templateId root="2.16.840.1.113883.10.20.22.4.4"/>
                <statusCode code="active"/>
                <effectiveTime>
                  <low value="{onset}"/>
                </effectiveTime>
                <value xsi:type="CD"
                       code="{icd_code}"
                       codeSystem="2.16.840.1.113883.6.90"
                       displayName="{name}"
                       xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"/>
              </observation>
            </entryRelationship>
          </act>
        </entry>"""

    def _med_entry(m: dict) -> str:
        rxnorm = m.get("rxnorm", "860975")
        name = m.get("name", "Metformin 500 MG")
        dose_val = m.get("dose_val", "500")
        dose_unit = m.get("dose_unit", "mg")
        return f"""
        <entry>
          <substanceAdministration classCode="SBADM" moodCode="INT">
            <templateId root="2.16.840.1.113883.10.20.22.4.16"/>
            <statusCode code="active"/>
            <doseQuantity value="{dose_val}" unit="{dose_unit}"/>
            <consumable>
              <manufacturedProduct>
                <manufacturedMaterial>
                  <code code="{rxnorm}"
                        codeSystem="2.16.840.1.113883.6.88"
                        displayName="{name}"/>
                </manufacturedMaterial>
              </manufacturedProduct>
            </consumable>
          </substanceAdministration>
        </entry>"""

    def _result_entry(r: dict) -> str:
        loinc = r.get("loinc", "4548-4")
        name = r.get("name", "HbA1c")
        value = r.get("value", "7.2")
        unit = r.get("unit", "%")
        date = r.get("date", "20240115")
        return f"""
        <entry>
          <organizer classCode="BATTERY" moodCode="EVN">
            <templateId root="2.16.840.1.113883.10.20.22.4.1"/>
            <component>
              <observation classCode="OBS" moodCode="EVN">
                <code code="{loinc}"
                      codeSystem="2.16.840.1.113883.6.1"
                      displayName="{name}"/>
                <effectiveTime value="{date}"/>
                <value xsi:type="PQ" value="{value}" unit="{unit}"
                       xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"/>
              </observation>
            </component>
          </organizer>
        </entry>"""

    def _enc_entry(e: dict) -> str:
        enc_type = e.get("type", "Office Visit")
        start = e.get("start", "20240110")
        end = e.get("end", "20240110")
        npi = e.get("npi", "")
        npi_block = ""
        if npi:
            npi_block = f"""
            <performer>
              <assignedEntity>
                <id root="2.16.840.1.113883.4.6" extension="{npi}"/>
              </assignedEntity>
            </performer>"""
        return f"""
        <entry>
          <encounter classCode="ENC" moodCode="EVN">
            <templateId root="2.16.840.1.113883.10.20.22.4.49"/>
            <code displayName="{enc_type}"/>
            <effectiveTime>
              <low value="{start}"/>
              <high value="{end}"/>
            </effectiveTime>
            {npi_block}
          </encounter>
        </entry>"""

    def _allergy_entry(a: dict) -> str:
        substance = a.get("substance", "Penicillin")
        reaction = a.get("reaction", "Hives")
        return f"""
        <entry>
          <act classCode="ACT" moodCode="EVN">
            <templateId root="2.16.840.1.113883.10.20.22.4.30"/>
            <entryRelationship typeCode="SUBJ">
              <observation classCode="OBS" moodCode="EVN">
                <templateId root="2.16.840.1.113883.10.20.22.4.7"/>
                <participant typeCode="CSM">
                  <participantRole classCode="MANU">
                    <playingEntity classCode="MMAT">
                      <code displayName="{substance}"/>
                    </playingEntity>
                  </participantRole>
                </participant>
                <entryRelationship typeCode="MFST">
                  <observation classCode="OBS" moodCode="EVN">
                    <templateId root="2.16.840.1.113883.10.20.22.4.9"/>
                    <value xsi:type="CD" displayName="{reaction}"
                           xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"/>
                  </observation>
                </entryRelationship>
              </observation>
            </entryRelationship>
          </act>
        </entry>"""

    problems_xml = "\n".join(_prob_entry(p) for p in (problems or []))
    meds_xml     = "\n".join(_med_entry(m) for m in (medications or []))
    results_xml  = "\n".join(_result_entry(r) for r in (results or []))
    enc_xml      = "\n".join(_enc_entry(e) for e in (encounters or []))
    allergy_xml  = "\n".join(_allergy_entry(a) for a in (allergies or []))

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<ClinicalDocument xmlns="urn:hl7-org:v3"
                  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <templateId root="2.16.840.1.113883.10.20.22.1.1"/>
  <templateId root="2.16.840.1.113883.10.20.22.1.2"/>
  <code code="34133-9" codeSystem="2.16.840.1.113883.6.1"
        displayName="Summarization of Episode Note"/>
  <effectiveTime value="20240201"/>
  <recordTarget>
    <patientRole>
      <id root="2.16.840.1.113883.19.5" extension="MRN-12345"/>
      <patient>
        <name>
          <given>Jane</given>
          <family>Doe</family>
        </name>
        <birthTime value="19600315"/>
        <administrativeGenderCode code="F"/>
      </patient>
    </patientRole>
  </recordTarget>
  <component>
    <structuredBody>

      <!-- Problems section -->
      <component>
        <section>
          <templateId root="2.16.840.1.113883.10.20.22.2.5.1"/>
          <title>Problem List</title>
          {problems_xml}
        </section>
      </component>

      <!-- Medications section -->
      <component>
        <section>
          <templateId root="2.16.840.1.113883.10.20.22.2.1.1"/>
          <title>Medications</title>
          {meds_xml}
        </section>
      </component>

      <!-- Results section -->
      <component>
        <section>
          <templateId root="2.16.840.1.113883.10.20.22.2.3.1"/>
          <title>Results</title>
          {results_xml}
        </section>
      </component>

      <!-- Encounters section -->
      <component>
        <section>
          <templateId root="2.16.840.1.113883.10.20.22.2.22.1"/>
          <title>Encounters</title>
          {enc_xml}
        </section>
      </component>

      <!-- Allergies section -->
      <component>
        <section>
          <templateId root="2.16.840.1.113883.10.20.22.2.6.1"/>
          <title>Allergies</title>
          {allergy_xml}
        </section>
      </component>

    </structuredBody>
  </component>
</ClinicalDocument>"""
    return xml.encode("utf-8")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

THREE_PROBLEMS = [
    {"icd10_code": "E119",  "name": "Type 2 Diabetes",  "onset": "20180601"},
    {"icd10_code": "I10",   "name": "Hypertension",     "onset": "20190101"},
    {"icd10_code": "I509",  "name": "Heart Failure",    "onset": "20220301"},
]

TWO_MEDS = [
    {"rxnorm": "860975", "name": "Metformin 500 MG", "dose_val": "500", "dose_unit": "mg"},
    {"rxnorm": "308460", "name": "Lisinopril 10 MG", "dose_val": "10",  "dose_unit": "mg"},
]

FOUR_RESULTS = [
    {"loinc": "4548-4",  "name": "HbA1c",         "value": "7.2",  "unit": "%",     "date": "20240115"},
    {"loinc": "2345-7",  "name": "Glucose",        "value": "110",  "unit": "mg/dL", "date": "20240115"},
    {"loinc": "2160-0",  "name": "Creatinine",     "value": "1.1",  "unit": "mg/dL", "date": "20240115"},
    {"loinc": "17861-6", "name": "Calcium",        "value": "9.4",  "unit": "mg/dL", "date": "20240115"},
]


# ---------------------------------------------------------------------------
# Tests: parse_ccda_xml core extractions
# ---------------------------------------------------------------------------

class TestParseCCDAXml:
    """Unit tests for parse_ccda_xml — no DB required (HCC lookup mocked)."""

    def _make_hcc_mock(self, mapping: dict[str, tuple]):
        """Return a patcher that routes specific ICD-10s to HCC codes."""
        def _fake_lookup(icd10: str) -> tuple:
            return mapping.get(icd10, (None, None))
        return patch(
            "app.services.ccda_parser._icd10_to_hcc",
            side_effect=_fake_lookup,
        )

    def test_three_problems_extracted(self):
        """parse_ccda_xml returns exactly 3 problem entries."""
        xml = _build_ccda(problems=THREE_PROBLEMS)
        with patch("app.services.ccda_parser._icd10_to_hcc", return_value=(None, None)):
            result = __import__(
                "app.services.ccda_parser", fromlist=["parse_ccda_xml"]
            ).parse_ccda_xml(xml)
        assert len(result["problems"]) == 3

    def test_problem_icd10_codes(self):
        """Each problem has the correct ICD-10 code."""
        xml = _build_ccda(problems=THREE_PROBLEMS)
        from app.services.ccda_parser import parse_ccda_xml
        with patch("app.services.ccda_parser._icd10_to_hcc", return_value=(None, None)):
            result = parse_ccda_xml(xml)
        codes = {p["icd10_code"] for p in result["problems"]}
        assert "E119" in codes
        assert "I10"  in codes
        assert "I509" in codes

    def test_problem_onset_dates(self):
        """Onset dates are extracted as ISO strings."""
        xml = _build_ccda(problems=THREE_PROBLEMS)
        from app.services.ccda_parser import parse_ccda_xml
        with patch("app.services.ccda_parser._icd10_to_hcc", return_value=(None, None)):
            result = parse_ccda_xml(xml)
        onset_dates = {p["onset_date"] for p in result["problems"] if p.get("onset_date")}
        assert "2018-06-01" in onset_dates
        assert "2019-01-01" in onset_dates
        assert "2022-03-01" in onset_dates

    def test_hcc_mapping_applied(self):
        """HCC codes from mock crosswalk are reflected in problems and hcc_suspects."""
        xml = _build_ccda(problems=THREE_PROBLEMS)
        from app.services.ccda_parser import parse_ccda_xml
        hcc_map = {
            "E119": ("19",  "Diabetes Without Complication"),
            "I10":  ("85",  "Hypertension"),
            "I509": ("85",  "Heart Failure"),
        }
        with patch("app.services.ccda_parser._icd10_to_hcc", side_effect=lambda c: hcc_map.get(c, (None, None))):
            result = parse_ccda_xml(xml)
        hcc_in_problems = {p["hcc_code"] for p in result["problems"] if p.get("hcc_code")}
        assert "19" in hcc_in_problems
        assert "85" in hcc_in_problems
        # hcc_suspects is deduplicated
        assert len(result["hcc_suspects"]) == len(set(result["hcc_suspects"]))
        assert "19" in result["hcc_suspects"]

    def test_two_medications_extracted(self):
        """parse_ccda_xml extracts 2 medications with RxNorm codes and doses."""
        xml = _build_ccda(medications=TWO_MEDS)
        from app.services.ccda_parser import parse_ccda_xml
        with patch("app.services.ccda_parser._icd10_to_hcc", return_value=(None, None)):
            result = parse_ccda_xml(xml)
        assert len(result["medications"]) == 2
        rxnorm_codes = {m["rxnorm_code"] for m in result["medications"]}
        assert "860975" in rxnorm_codes
        assert "308460" in rxnorm_codes

    def test_medication_dose(self):
        """Medication dose string is assembled correctly."""
        xml = _build_ccda(medications=TWO_MEDS)
        from app.services.ccda_parser import parse_ccda_xml
        with patch("app.services.ccda_parser._icd10_to_hcc", return_value=(None, None)):
            result = parse_ccda_xml(xml)
        metformin = next(m for m in result["medications"] if m["rxnorm_code"] == "860975")
        assert metformin["dose"] == "500 mg"

    def test_four_lab_results_extracted(self):
        """parse_ccda_xml extracts 4 lab results with LOINC codes."""
        xml = _build_ccda(results=FOUR_RESULTS)
        from app.services.ccda_parser import parse_ccda_xml
        with patch("app.services.ccda_parser._icd10_to_hcc", return_value=(None, None)):
            result = parse_ccda_xml(xml)
        assert len(result["results"]) == 4
        loincs = {r["loinc_code"] for r in result["results"]}
        assert "4548-4" in loincs
        assert "2345-7" in loincs
        assert "2160-0" in loincs
        assert "17861-6" in loincs

    def test_result_value_and_date(self):
        """Result value and date are extracted correctly."""
        xml = _build_ccda(results=FOUR_RESULTS)
        from app.services.ccda_parser import parse_ccda_xml
        with patch("app.services.ccda_parser._icd10_to_hcc", return_value=(None, None)):
            result = parse_ccda_xml(xml)
        hba1c = next(r for r in result["results"] if r["loinc_code"] == "4548-4")
        assert "7.2" in (hba1c["value"] or "")
        assert hba1c["result_date"] == "2024-01-15"

    def test_encounters_extracted(self):
        """Encounter type, dates, and NPI are extracted."""
        enc = [{"type": "Office Visit", "start": "20240110", "end": "20240110", "npi": "1234567890"}]
        xml = _build_ccda(encounters=enc)
        from app.services.ccda_parser import parse_ccda_xml
        with patch("app.services.ccda_parser._icd10_to_hcc", return_value=(None, None)):
            result = parse_ccda_xml(xml)
        assert len(result["encounters"]) == 1
        e = result["encounters"][0]
        assert e["type"] == "Office Visit"
        assert e["start_date"] == "2024-01-10"
        assert e["provider_npi"] == "1234567890"

    def test_allergies_extracted(self):
        """Allergy substance and reaction are extracted."""
        alg = [{"substance": "Penicillin", "reaction": "Hives"}]
        xml = _build_ccda(allergies=alg)
        from app.services.ccda_parser import parse_ccda_xml
        with patch("app.services.ccda_parser._icd10_to_hcc", return_value=(None, None)):
            result = parse_ccda_xml(xml)
        assert len(result["allergies"]) == 1
        assert result["allergies"][0]["substance"] == "Penicillin"
        assert result["allergies"][0]["reaction"] == "Hives"

    def test_patient_identifiers_extracted(self):
        """Patient MRN, name, DOB, and gender are extracted from recordTarget."""
        xml = _build_ccda()
        from app.services.ccda_parser import parse_ccda_xml
        with patch("app.services.ccda_parser._icd10_to_hcc", return_value=(None, None)):
            result = parse_ccda_xml(xml)
        patient = result["patient"]
        assert patient["mrn"] == "MRN-12345"
        assert patient["first_name"] == "Jane"
        assert patient["last_name"] == "Doe"
        assert patient["date_of_birth"] == "1960-03-15"
        assert patient["gender"] == "female"

    def test_oversized_document_raises(self):
        """Documents over 20 MB raise ValueError."""
        from app.services.ccda_parser import parse_ccda_xml, _MAX_BYTES
        oversized = b"x" * (_MAX_BYTES + 1)
        with pytest.raises(ValueError, match="exceeds maximum size"):
            parse_ccda_xml(oversized)

    def test_malformed_xml_raises(self):
        """Malformed XML raises ValueError."""
        from app.services.ccda_parser import parse_ccda_xml
        with pytest.raises(ValueError, match="XML parse error"):
            parse_ccda_xml(b"<<not xml>>")

    def test_hcc_db_error_degrades_gracefully(self):
        """DB exception during HCC lookup does not crash the parser.

        We simulate the failure by patching ``raf_cursor`` inside the
        ``_icd10_to_hcc`` helper so the DB path raises.  The function has
        its own try/except and returns (None, None) — problems are still
        extracted with null HCC codes.
        """
        xml = _build_ccda(problems=THREE_PROBLEMS)
        from app.services.ccda_parser import parse_ccda_xml

        @contextmanager
        def _exploding_cm(*a, **kw):
            raise Exception("DB is down")
            yield  # pragma: no cover

        with patch("app.db.raf_cursor", _exploding_cm):
            result = parse_ccda_xml(xml)

        # Problems still extracted; HCC codes fall back to None
        assert len(result["problems"]) == 3
        assert all(p["hcc_code"] is None for p in result["problems"])

    def test_combined_document_all_sections(self):
        """Full synthetic CCDA with 3 problems + 2 meds + 4 results parses cleanly."""
        xml = _build_ccda(
            problems=THREE_PROBLEMS,
            medications=TWO_MEDS,
            results=FOUR_RESULTS,
            encounters=[{"type": "Office Visit", "start": "20240110", "end": "20240110"}],
            allergies=[{"substance": "Sulfa", "reaction": "Rash"}],
        )
        from app.services.ccda_parser import parse_ccda_xml
        with patch("app.services.ccda_parser._icd10_to_hcc", return_value=(None, None)):
            result = parse_ccda_xml(xml)
        assert len(result["problems"])    == 3
        assert len(result["medications"]) == 2
        assert len(result["results"])     == 4
        assert len(result["encounters"])  == 1
        assert len(result["allergies"])   == 1
        assert "parse_warnings" in result
