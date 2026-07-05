"""
MEAT Validator — expanded test suite.

Covers: validate_meat function, keyword lexicon completeness, negation/
hypothetical/historical trigger lists, context window sizing, and
stopword exclusion of clinical terms.

No database or network required — all tests use the rule-based validator
directly or inspect module-level constants.
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# 1. validate_meat: complete MEAT
# ---------------------------------------------------------------------------

class TestValidateMeatComplete:
    """A note with all 4 MEAT elements should return COMPLETE status."""

    def test_all_four_elements_present(self):
        from app.services.meat_validator import validate_meat
        note = (
            "Patient with diabetes mellitus. "
            "Monitoring blood pressure and a1c levels. "
            "Evaluated via physical exam and auscultation. "
            "Assessment: stable and well-controlled. "
            "Continue medication with metformin titrated to 1000mg."
        )
        result = validate_meat(note, "E11.9", "Diabetes mellitus")
        assert result["status"] == "COMPLETE"
        assert result["elements_found"] == 4
        assert result["monitor"] is True
        assert result["evaluate"] is True
        assert result["assess"] is True
        assert result["treat"] is True

    def test_partial_with_two_elements(self):
        from app.services.meat_validator import validate_meat
        note = (
            "Patient with diabetes mellitus. "
            "Monitoring a1c levels. "
            "Assessment: stable."
        )
        result = validate_meat(note, "E11.9", "Diabetes mellitus")
        assert result["status"] == "PARTIAL"
        assert result["elements_found"] >= 2

    def test_empty_note_returns_missing(self):
        from app.services.meat_validator import validate_meat
        result = validate_meat("", "E11.9", "Diabetes mellitus")
        assert result["status"] == "MISSING"
        assert result["elements_found"] == 0


# ---------------------------------------------------------------------------
# 2. validate_meat: missing elements
# ---------------------------------------------------------------------------

class TestValidateMeatMissing:
    """Tests for missing MEAT elements."""

    def test_missing_treat_when_no_treatment_words(self):
        from app.services.meat_validator import validate_meat
        note = (
            "Patient with diabetes mellitus. "
            "Monitoring blood pressure. "
            "Evaluated via physical exam. "
            "Assessment: controlled."
        )
        result = validate_meat(note, "E11.9", "Diabetes mellitus")
        # Treat should be False since no treatment keywords present
        assert result["treat"] is False

    def test_no_condition_mention_returns_missing(self):
        from app.services.meat_validator import validate_meat
        note = "Patient presents for routine wellness visit. All normal."
        result = validate_meat(note, "E11.9", "Diabetes mellitus")
        # If condition isn't mentioned in the note, can't find MEAT evidence
        # Result depends on whether the condition text is found
        assert result["status"] in ("MISSING", "PARTIAL")

    def test_whitespace_only_note(self):
        from app.services.meat_validator import validate_meat
        result = validate_meat("   \n\t  ", "E11.9", "Diabetes")
        assert result["status"] == "MISSING"


# ---------------------------------------------------------------------------
# 3. Negation triggers
# ---------------------------------------------------------------------------

class TestNegationTriggers:
    """Negation trigger list must include all expected clinical negators."""

    def test_no_evidence_of(self):
        from app.services.meat_validator import NEGATION_TRIGGERS
        assert "no evidence of" in NEGATION_TRIGGERS

    def test_denies(self):
        from app.services.meat_validator import NEGATION_TRIGGERS
        assert "denies" in NEGATION_TRIGGERS

    def test_rules_out(self):
        from app.services.meat_validator import NEGATION_TRIGGERS
        assert "rules out" in NEGATION_TRIGGERS

    def test_negative_for(self):
        from app.services.meat_validator import NEGATION_TRIGGERS
        assert "negative for" in NEGATION_TRIGGERS

    def test_without(self):
        from app.services.meat_validator import NEGATION_TRIGGERS
        assert "without" in NEGATION_TRIGGERS

    def test_denied(self):
        from app.services.meat_validator import NEGATION_TRIGGERS
        assert "denied" in NEGATION_TRIGGERS


# ---------------------------------------------------------------------------
# 4. Hypothetical triggers
# ---------------------------------------------------------------------------

class TestHypotheticalTriggers:
    """Hypothetical trigger list must include uncertainty markers."""

    def test_possible(self):
        from app.services.meat_validator import HYPOTHETICAL_TRIGGERS
        assert "possible" in HYPOTHETICAL_TRIGGERS

    def test_suspected(self):
        from app.services.meat_validator import HYPOTHETICAL_TRIGGERS
        assert "suspected" in HYPOTHETICAL_TRIGGERS

    def test_probable(self):
        from app.services.meat_validator import HYPOTHETICAL_TRIGGERS
        assert "probable" in HYPOTHETICAL_TRIGGERS

    def test_could_be(self):
        from app.services.meat_validator import HYPOTHETICAL_TRIGGERS
        assert "could be" in HYPOTHETICAL_TRIGGERS

    def test_consider(self):
        from app.services.meat_validator import HYPOTHETICAL_TRIGGERS
        assert "consider" in HYPOTHETICAL_TRIGGERS


# ---------------------------------------------------------------------------
# 5. Historical triggers
# ---------------------------------------------------------------------------

class TestHistoricalTriggers:
    """Historical context triggers must be present."""

    def test_history_of(self):
        from app.services.meat_validator import HISTORICAL_TRIGGERS
        assert "history of" in HISTORICAL_TRIGGERS

    def test_resolved(self):
        from app.services.meat_validator import HISTORICAL_TRIGGERS
        assert "resolved" in HISTORICAL_TRIGGERS

    def test_status_post(self):
        from app.services.meat_validator import HISTORICAL_TRIGGERS
        assert "status post" in HISTORICAL_TRIGGERS

    def test_in_remission(self):
        from app.services.meat_validator import HISTORICAL_TRIGGERS
        assert "in remission" in HISTORICAL_TRIGGERS


# ---------------------------------------------------------------------------
# 6. Context window and stopwords
# ---------------------------------------------------------------------------

class TestContextWindow:
    """Context window and stopword configuration."""

    def test_context_window_reasonable_size(self):
        from app.services.meat_validator import CONTEXT_WINDOW_CHARS
        assert CONTEXT_WINDOW_CHARS >= 100
        assert CONTEXT_WINDOW_CHARS <= 500

    def test_max_evidence_snippets_bounded(self):
        from app.services.meat_validator import MAX_EVIDENCE_SNIPPETS
        assert MAX_EVIDENCE_SNIPPETS >= 1
        assert MAX_EVIDENCE_SNIPPETS <= 10

    def test_stopwords_exclude_clinical_terms(self):
        from app.services.meat_validator import _STOPWORDS
        # Clinical terms must NOT be in stopwords
        clinical_terms = ["diabetes", "heart", "kidney", "lung", "cancer",
                         "insulin", "blood", "liver", "renal"]
        for term in clinical_terms:
            assert term not in _STOPWORDS, f"'{term}' should not be a stopword"

    def test_stopwords_include_common_words(self):
        from app.services.meat_validator import _STOPWORDS
        assert "the" in _STOPWORDS
        assert "of" in _STOPWORDS
        assert "and" in _STOPWORDS

    def test_stopwords_is_set_type(self):
        from app.services.meat_validator import _STOPWORDS
        assert isinstance(_STOPWORDS, set)


# ---------------------------------------------------------------------------
# 7. Family triggers
# ---------------------------------------------------------------------------

class TestFamilyTriggers:
    """Family-history triggers must be present for context filtering."""

    def test_family_history(self):
        from app.services.meat_validator import FAMILY_TRIGGERS
        assert "family history" in FAMILY_TRIGGERS

    def test_mother(self):
        from app.services.meat_validator import FAMILY_TRIGGERS
        assert "mother" in FAMILY_TRIGGERS

    def test_father(self):
        from app.services.meat_validator import FAMILY_TRIGGERS
        assert "father" in FAMILY_TRIGGERS


# ---------------------------------------------------------------------------
# 8. MEAT keyword presence
# ---------------------------------------------------------------------------

class TestMeatKeywordPresence:
    """Verify critical keywords in each MEAT category."""

    def test_monitor_has_vitals(self):
        from app.services.meat_validator import MONITOR_KEYWORDS
        assert "vitals" in MONITOR_KEYWORDS

    def test_monitor_has_a1c(self):
        from app.services.meat_validator import MONITOR_KEYWORDS
        assert "a1c" in MONITOR_KEYWORDS

    def test_evaluate_has_physical_exam(self):
        from app.services.meat_validator import EVALUATE_KEYWORDS
        assert "physical exam" in EVALUATE_KEYWORDS

    def test_assess_has_stable(self):
        from app.services.meat_validator import ASSESS_KEYWORDS
        assert "stable" in ASSESS_KEYWORDS

    def test_treat_has_medication(self):
        from app.services.meat_validator import TREAT_KEYWORDS
        assert "medication" in TREAT_KEYWORDS

    def test_treat_no_bare_continue(self):
        """'continue' alone is a false-positive; should not be in TREAT."""
        from app.services.meat_validator import TREAT_KEYWORDS
        assert "continue" not in TREAT_KEYWORDS
