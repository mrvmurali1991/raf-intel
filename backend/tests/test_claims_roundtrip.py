"""RAPS / EDS claims-file round-trip tests.

End-to-end: parse a simplified RAPS detail-A file or an EDS JSONL
encounter stream → extract beneficiary diagnoses → feed into hccinfhir
→ compare RAF score to a locked expected value.

Two formats must produce **identical** scores for identical diagnosis
sets — any divergence points at a parser bug (e.g. decimal-point or
case handling).
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("hccinfhir")

from app.services.raf.claims_ingest import (  # noqa: E402
    BeneficiaryClaims,
    normalise_icd10,
    parse_eds_jsonl,
    parse_raps_file,
    parse_raps_line,
    score_beneficiary_claims,
)

_CLAIMS = Path(__file__).resolve().parent / "fixtures" / "claims"


# ---------------------------------------------------------------------------
# ICD-10 normalisation
# ---------------------------------------------------------------------------

class TestNormaliseICD10:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("E11.9", "E119"),
            ("e11.9", "E119"),
            ("  E119  ", "E119"),
            ("I50.22", "I5022"),
            ("N18.4", "N184"),
            ("C50.911", "C50911"),
            ("E119", "E119"),
            ("E11.9.", "E119"),
        ],
    )
    def test_normalises_dotted_and_case(self, raw: str, expected: str) -> None:
        assert normalise_icd10(raw) == expected

    @pytest.mark.parametrize("raw", ["", "   ", "???", "123", "U!!!"])
    def test_rejects_invalid_codes(self, raw: str) -> None:
        assert normalise_icd10(raw) is None


# ---------------------------------------------------------------------------
# RAPS parsing
# ---------------------------------------------------------------------------

class TestRAPSParser:
    def test_header_and_trailer_ignored(self) -> None:
        assert parse_raps_line("HEADER|RAPS|2026|T") is None
        assert parse_raps_line("TRAILER|RAPS|7|END") is None
        assert parse_raps_line("") is None

    def test_detail_a_with_single_diagnosis(self) -> None:
        parsed = parse_raps_line("A|HIC123|PC1|2025-01-01|2025-01-01|PHY|E119")
        assert parsed is not None
        hicn, dxs = parsed
        assert hicn == "HIC123"
        assert dxs == ["E119"]

    def test_detail_a_with_multiple_diagnoses(self) -> None:
        parsed = parse_raps_line(
            "A|HIC123|PC1|2025-01-01|2025-01-01|PHY|E11.9|I50.22|J44.9"
        )
        assert parsed is not None
        _, dxs = parsed
        assert dxs == ["E119", "I5022", "J449"]

    def test_empty_diagnosis_cells_are_skipped(self) -> None:
        parsed = parse_raps_line("A|HIC|PC|2025-01-01|2025-01-01|PHY|E119|||J449")
        assert parsed is not None
        _, dxs = parsed
        assert dxs == ["E119", "J449"]

    def test_parse_file_aggregates_by_hicn(self) -> None:
        content = (_CLAIMS / "sample.raps").read_text()
        benes = parse_raps_file(content)
        by_id = {b.beneficiary_id: b for b in benes}
        # Bene ABC has 2 encounters, combined dxs
        abc = by_id["ABC1234567A"]
        assert abc.encounter_count == 2
        assert set(abc.dedup_diagnoses()) == {"E119", "I5022", "J449"}
        # Bene DEF has 2 encounters covering DM+CHF+CKD+depression
        defb = by_id["DEF7654321B"]
        assert set(defb.dedup_diagnoses()) == {"E1122", "N184", "I5033", "F329"}

    def test_unknown_bene_missing(self) -> None:
        content = (_CLAIMS / "sample.raps").read_text()
        benes = parse_raps_file(content)
        ids = {b.beneficiary_id for b in benes}
        assert "ZZZ" not in ids

    def test_dotted_code_normalises(self) -> None:
        """The final MNO record uses E119. (trailing dot) + I50.22."""
        content = (_CLAIMS / "sample.raps").read_text()
        benes = parse_raps_file(content)
        by_id = {b.beneficiary_id: b for b in benes}
        assert set(by_id["MNO1111111E"].dedup_diagnoses()) == {"E119", "I5022"}


# ---------------------------------------------------------------------------
# EDS JSONL parsing
# ---------------------------------------------------------------------------

class TestEDSParser:
    def test_parse_file_aggregates_by_beneficiary(self) -> None:
        content = (_CLAIMS / "sample.eds.jsonl").read_text()
        benes = parse_eds_jsonl(content)
        by_id = {b.beneficiary_id: b for b in benes}
        assert by_id["EDS-001"].encounter_count == 2
        assert set(by_id["EDS-001"].dedup_diagnoses()) == {
            "E119", "I5022", "J449",
        }

    def test_empty_diagnosis_list_allowed(self) -> None:
        content = (_CLAIMS / "sample.eds.jsonl").read_text()
        benes = parse_eds_jsonl(content)
        by_id = {b.beneficiary_id: b for b in benes}
        assert by_id["EDS-004"].dedup_diagnoses() == []

    def test_malformed_json_line_skipped(self) -> None:
        content = (
            '{"beneficiary_id":"EDS-X","diagnosis_codes":["E119"]}\n'
            'not-json-here\n'
            '{"beneficiary_id":"EDS-Y","diagnosis_codes":["I5022"]}\n'
        )
        benes = parse_eds_jsonl(content)
        ids = {b.beneficiary_id for b in benes}
        assert ids == {"EDS-X", "EDS-Y"}


# ---------------------------------------------------------------------------
# Round-trip scoring (parser → hccinfhir → locked score)
# ---------------------------------------------------------------------------

# Locked scores: 72-year-old female, non-dual, community, not new-enrollee.
# Each pair covers both a RAPS and an EDS bene with identical diagnoses;
# both must yield the same RAF.
_EXPECTED_SCORES_72F_CNA: dict[frozenset[str], float] = {
    frozenset({"E119", "I5022", "J449"}): 1.430,
    frozenset({"E1122", "N184", "I5033", "F329"}): 1.723,
    frozenset({"C50911"}): 0.581,
    frozenset(): 0.395,
    frozenset({"E119", "I5022"}): 1.033,
}


class TestRoundTripScoring:
    @pytest.mark.parametrize(
        "bene_id",
        ["ABC1234567A", "DEF7654321B", "GHI5555555C", "JKL8888888D", "MNO1111111E"],
    )
    def test_raps_roundtrip_matches_locked_score(self, bene_id: str) -> None:
        content = (_CLAIMS / "sample.raps").read_text()
        benes = {b.beneficiary_id: b for b in parse_raps_file(content)}
        bene = benes[bene_id]
        score = score_beneficiary_claims(bene, age=72, sex="F")
        key = frozenset(bene.dedup_diagnoses())
        assert score == pytest.approx(
            _EXPECTED_SCORES_72F_CNA[key], abs=0.001
        )

    @pytest.mark.parametrize(
        "bene_id",
        ["EDS-001", "EDS-002", "EDS-003", "EDS-004", "EDS-005"],
    )
    def test_eds_roundtrip_matches_locked_score(self, bene_id: str) -> None:
        content = (_CLAIMS / "sample.eds.jsonl").read_text()
        benes = {b.beneficiary_id: b for b in parse_eds_jsonl(content)}
        bene = benes[bene_id]
        score = score_beneficiary_claims(bene, age=72, sex="F")
        key = frozenset(bene.dedup_diagnoses())
        assert score == pytest.approx(
            _EXPECTED_SCORES_72F_CNA[key], abs=0.001
        )


class TestFormatParity:
    """A RAPS beneficiary and an EDS beneficiary with identical diagnoses
    must produce byte-identical RAF — this is the core parity guarantee."""

    @pytest.mark.parametrize(
        "raps_id,eds_id",
        [
            ("ABC1234567A", "EDS-001"),
            ("DEF7654321B", "EDS-002"),
            ("GHI5555555C", "EDS-003"),
            ("JKL8888888D", "EDS-004"),
            ("MNO1111111E", "EDS-005"),
        ],
    )
    def test_format_agnostic_scoring(self, raps_id: str, eds_id: str) -> None:
        raps_benes = {
            b.beneficiary_id: b
            for b in parse_raps_file((_CLAIMS / "sample.raps").read_text())
        }
        eds_benes = {
            b.beneficiary_id: b
            for b in parse_eds_jsonl((_CLAIMS / "sample.eds.jsonl").read_text())
        }
        assert set(raps_benes[raps_id].dedup_diagnoses()) == set(
            eds_benes[eds_id].dedup_diagnoses()
        ), "Fixture setup: RAPS and EDS pair must carry identical dx set"
        raps_score = score_beneficiary_claims(
            raps_benes[raps_id], age=72, sex="F"
        )
        eds_score = score_beneficiary_claims(
            eds_benes[eds_id], age=72, sex="F"
        )
        assert raps_score == eds_score, (
            f"Format drift: RAPS {raps_id}={raps_score} vs "
            f"EDS {eds_id}={eds_score} — parsers must be equivalent"
        )


class TestBeneficiaryClaims:
    def test_dedup_preserves_first_occurrence(self) -> None:
        bene = BeneficiaryClaims(
            beneficiary_id="X",
            diagnosis_codes=["E119", "I5022", "E119", "J449", "I5022"],
        )
        assert bene.dedup_diagnoses() == ["E119", "I5022", "J449"]

    def test_empty_starts_empty(self) -> None:
        assert BeneficiaryClaims(beneficiary_id="X").dedup_diagnoses() == []
