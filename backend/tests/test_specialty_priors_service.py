"""
Unit tests for ``services.knowledge_graph.specialty_priors_service``.

These tests do NOT require the live backend or a real MySQL — they patch
``raf_cursor`` so the service runs entirely against an in-memory fake DB.

The fake DB is populated with a small but realistic slice of the curated
seed data (cardiology, nephrology, pulmonology, geriatrics) plus aliases
mirroring the production seed.  That way assertions like "Cardiology top-
likely starts with HCC 226 (CHF)" stay aligned with the production seed.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# Override the session-level ``server_available`` fixture from conftest.py.
# These tests are pure unit tests — they patch the DB cursor and do not need
# the live backend.  Without this override they would all be skipped on a
# developer laptop where uvicorn is not running.
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session", autouse=True)
def server_available():  # noqa: D401 — overrides conftest fixture
    """No-op: this module does not require the live backend."""
    yield


# ---------------------------------------------------------------------------
# Fake DB
# ---------------------------------------------------------------------------

_PRIORS_ROWS: list[dict[str, Any]] = [
    # Cardiology
    {"specialty": "Cardiology", "hcc_code": "226", "prior_weight": 5.00, "panel_prevalence_pct": 38.0,
     "source": "MEDPAR-specialty-mix", "notes": "CHF defining"},
    {"specialty": "Cardiology", "hcc_code": "248", "prior_weight": 4.00, "panel_prevalence_pct": 28.0,
     "source": "MEDPAR-specialty-mix", "notes": "AFib"},
    {"specialty": "Cardiology", "hcc_code": "216", "prior_weight": 3.50, "panel_prevalence_pct": 6.0,
     "source": "MEDPAR-specialty-mix", "notes": "AMI recent"},
    {"specialty": "Cardiology", "hcc_code": "96",  "prior_weight": 3.00, "panel_prevalence_pct": 14.0,
     "source": "MEDPAR-specialty-mix", "notes": "Valvular"},
    {"specialty": "Cardiology", "hcc_code": "108", "prior_weight": 3.00, "panel_prevalence_pct": 18.0,
     "source": "MEDPAR-specialty-mix", "notes": "Vascular"},
    {"specialty": "Cardiology", "hcc_code": "11",  "prior_weight": 0.50, "panel_prevalence_pct": 0.5,
     "source": "curated", "notes": "Lung Ca outside scope"},
    # Nephrology
    {"specialty": "Nephrology", "hcc_code": "138", "prior_weight": 8.00, "panel_prevalence_pct": 72.0,
     "source": "MEDPAR-specialty-mix", "notes": "CKD defining"},
    {"specialty": "Nephrology", "hcc_code": "136", "prior_weight": 8.00, "panel_prevalence_pct": 40.0,
     "source": "MEDPAR-specialty-mix", "notes": "ESRD"},
    {"specialty": "Nephrology", "hcc_code": "186", "prior_weight": 6.00, "panel_prevalence_pct": 8.0,
     "source": "MEDPAR-specialty-mix", "notes": "Kidney transplant"},
    {"specialty": "Nephrology", "hcc_code": "46",  "prior_weight": 4.00, "panel_prevalence_pct": 38.0,
     "source": "MEDPAR-specialty-mix", "notes": "Anemia of CKD"},
    # Pulmonology
    {"specialty": "Pulmonology", "hcc_code": "280", "prior_weight": 5.00, "panel_prevalence_pct": 65.0,
     "source": "MEDPAR-specialty-mix", "notes": "COPD"},
    {"specialty": "Pulmonology", "hcc_code": "279", "prior_weight": 4.00, "panel_prevalence_pct": 25.0,
     "source": "MEDPAR-specialty-mix", "notes": "Severe asthma"},
    {"specialty": "Pulmonology", "hcc_code": "11",  "prior_weight": 3.50, "panel_prevalence_pct": 9.0,
     "source": "MEDPAR-specialty-mix", "notes": "Lung Ca"},
    # Geriatrics
    {"specialty": "Geriatrics", "hcc_code": "125", "prior_weight": 4.00, "panel_prevalence_pct": 28.0,
     "source": "MEDPAR-specialty-mix", "notes": "Dementia"},
    {"specialty": "Geriatrics", "hcc_code": "170", "prior_weight": 3.00, "panel_prevalence_pct": 12.0,
     "source": "MEDPAR-specialty-mix", "notes": "Hip fracture"},
    {"specialty": "Geriatrics", "hcc_code": "48",  "prior_weight": 0.70, "panel_prevalence_pct": 4.0,
     "source": "curated", "notes": "Morbid obesity de-enriched"},
    # Internal Medicine — baseline 1.0x for everything seeded
    {"specialty": "Internal Medicine", "hcc_code": "19",  "prior_weight": 1.00, "panel_prevalence_pct": 18.0,
     "source": "AAFP-survey", "notes": "DM"},
    {"specialty": "Internal Medicine", "hcc_code": "138", "prior_weight": 1.00, "panel_prevalence_pct": 9.0,
     "source": "MEDPAR-specialty-mix", "notes": "CKD"},
]

_ALIAS_ROWS: list[dict[str, str]] = [
    {"raw_specialty": "Cards",                 "canonical_specialty": "Cardiology"},
    {"raw_specialty": "Cardio",                "canonical_specialty": "Cardiology"},
    {"raw_specialty": "Cardiology",            "canonical_specialty": "Cardiology"},
    {"raw_specialty": "Nephro",                "canonical_specialty": "Nephrology"},
    {"raw_specialty": "Nephrology",            "canonical_specialty": "Nephrology"},
    {"raw_specialty": "Renal",                 "canonical_specialty": "Nephrology"},
    {"raw_specialty": "Pulm",                  "canonical_specialty": "Pulmonology"},
    {"raw_specialty": "Pulmonology",           "canonical_specialty": "Pulmonology"},
    {"raw_specialty": "Geri",                  "canonical_specialty": "Geriatrics"},
    {"raw_specialty": "IM",                    "canonical_specialty": "Internal Medicine"},
    {"raw_specialty": "Internal Medicine",     "canonical_specialty": "Internal Medicine"},
    {"raw_specialty": "Internal Med",          "canonical_specialty": "Internal Medicine"},
    {"raw_specialty": "GI",                    "canonical_specialty": "Gastroenterology"},
]

_PROVIDERS: dict[int, str] = {
    101: "Cards",                # provider with alias
    102: "Nephrology",           # canonical
    103: "Pulm",                 # alias
    104: "MadeUpSpecialty",      # not seeded
    999: None,                   # missing specialty
}


class _FakeCursor:
    """Pretends to be a mysql.connector dictionary cursor."""

    def __init__(self) -> None:
        self._results: list[dict[str, Any]] = []

    def execute(self, sql: str, params: tuple = ()) -> None:
        sql_norm = " ".join(sql.split()).lower()
        params = params or ()

        if "from kg_specialty_aliases" in sql_norm and "lower(raw_specialty)" in sql_norm:
            target = params[0].lower()
            self._results = [
                {"canonical_specialty": r["canonical_specialty"]}
                for r in _ALIAS_ROWS
                if r["raw_specialty"].lower() == target
            ]
            return

        if "from kg_specialty_aliases" in sql_norm and "lower" not in sql_norm:
            self._results = [
                {"raw_specialty": r["raw_specialty"], "canonical_specialty": r["canonical_specialty"]}
                for r in _ALIAS_ROWS
            ]
            return

        if "from kg_specialty_hcc_priors" in sql_norm and "and hcc_code =" in sql_norm:
            spec, hcc = params[0], str(params[1])
            self._results = [
                {"prior_weight": r["prior_weight"], "source": r["source"], "notes": r["notes"]}
                for r in _PRIORS_ROWS
                if r["specialty"] == spec and str(r["hcc_code"]) == hcc
            ]
            return

        if "from kg_specialty_hcc_priors" in sql_norm and "order by prior_weight desc" in sql_norm:
            spec = params[0]
            limit = int(params[1]) if len(params) > 1 else 1000
            rows = [
                {
                    "hcc_code": r["hcc_code"],
                    "prior_weight": r["prior_weight"],
                    "panel_prevalence_pct": r["panel_prevalence_pct"],
                    "source": r["source"],
                    "notes": r["notes"],
                }
                for r in _PRIORS_ROWS
                if r["specialty"] == spec
            ]
            rows.sort(key=lambda r: (-r["prior_weight"], -(r["panel_prevalence_pct"] or 0), str(r["hcc_code"])))
            self._results = rows[:limit]
            return

        if "from kg_specialty_hcc_priors" in sql_norm:
            spec = params[0]
            self._results = [
                {
                    "hcc_code": r["hcc_code"],
                    "prior_weight": r["prior_weight"],
                    "panel_prevalence_pct": r["panel_prevalence_pct"],
                    "source": r["source"],
                    "notes": r["notes"],
                }
                for r in _PRIORS_ROWS
                if r["specialty"] == spec
            ]
            self._results.sort(key=lambda r: (-r["prior_weight"], str(r["hcc_code"])))
            return

        if "from providers" in sql_norm:
            pid = int(params[0])
            spec = _PROVIDERS.get(pid)
            self._results = [{"specialty": spec}] if pid in _PROVIDERS else []
            return

        # Unknown query — empty result
        self._results = []

    def fetchone(self) -> dict[str, Any] | None:
        return self._results[0] if self._results else None

    def fetchall(self) -> list[dict[str, Any]]:
        return list(self._results)

    def close(self) -> None:  # pragma: no cover
        pass


@contextmanager
def _fake_raf_cursor(dictionary: bool = True):
    yield _FakeCursor()


# ---------------------------------------------------------------------------
# Auto-patch the raf_cursor used by the service
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def patch_raf_cursor(monkeypatch):
    # Patch the symbol in the module under test (the service imported it
    # directly, so patching app.db is not enough).
    import app.services.knowledge_graph.specialty_priors_service as svc

    monkeypatch.setattr(svc, "raf_cursor", _fake_raf_cursor)
    yield


# ---------------------------------------------------------------------------
# canonicalize
# ---------------------------------------------------------------------------

class TestCanonicalize:
    def test_alias_exact(self):
        from app.services.knowledge_graph.specialty_priors_service import canonicalize
        assert canonicalize("Cards") == "Cardiology"

    def test_alias_case_insensitive(self):
        from app.services.knowledge_graph.specialty_priors_service import canonicalize
        assert canonicalize("cards") == "Cardiology"
        assert canonicalize("CARDS") == "Cardiology"

    def test_canonical_passthrough(self):
        from app.services.knowledge_graph.specialty_priors_service import canonicalize
        assert canonicalize("Cardiology") == "Cardiology"

    def test_whitespace_handling(self):
        from app.services.knowledge_graph.specialty_priors_service import canonicalize
        assert canonicalize("  Internal   Medicine  ") == "Internal Medicine"

    def test_fuzzy_match(self):
        from app.services.knowledge_graph.specialty_priors_service import canonicalize
        # close to "Cardiology"
        assert canonicalize("Cardiolgy") == "Cardiology"

    def test_unknown_returned_unchanged(self):
        from app.services.knowledge_graph.specialty_priors_service import canonicalize
        # Far enough away that fuzzy matching will not pick anything
        assert canonicalize("Astrology") == "Astrology"

    def test_empty_input(self):
        from app.services.knowledge_graph.specialty_priors_service import canonicalize
        assert canonicalize("") == ""
        assert canonicalize("   ") == ""


# ---------------------------------------------------------------------------
# get_priors_for_specialty
# ---------------------------------------------------------------------------

class TestGetPriorsForSpecialty:
    def test_cardiology_priors_returned(self):
        from app.services.knowledge_graph.specialty_priors_service import get_priors_for_specialty
        rows = get_priors_for_specialty("Cardiology")
        assert len(rows) >= 5
        assert all(r["specialty"] == "Cardiology" for r in rows)

    def test_alias_resolution_in_lookup(self):
        from app.services.knowledge_graph.specialty_priors_service import get_priors_for_specialty
        rows = get_priors_for_specialty("Cards")
        assert rows
        assert rows[0]["specialty"] == "Cardiology"

    def test_unknown_specialty_returns_empty(self):
        from app.services.knowledge_graph.specialty_priors_service import get_priors_for_specialty
        # Not seeded — fuzzy match may resolve to one of the canonical names,
        # but the specialty's prior list will be empty if our fake DB has
        # no rows for it.  Using something far from any canonical name:
        rows = get_priors_for_specialty("CompletelyUnknownDiscipline")
        # The fuzzy matcher returns the input unchanged here, so DB has no rows.
        assert rows == []


# ---------------------------------------------------------------------------
# apply_specialty_prior
# ---------------------------------------------------------------------------

class TestApplySpecialtyPrior:
    def test_nephrology_138_multiplies_8x(self):
        from app.services.knowledge_graph.specialty_priors_service import apply_specialty_prior
        out = apply_specialty_prior("Nephrology", "138", 0.5)
        assert out["applied"] is True
        assert out["prior_weight"] == 8.0
        assert out["adjusted_score"] == pytest.approx(4.0)
        assert out["specialty"] == "Nephrology"
        assert out["hcc_code"] == "138"

    def test_cardiology_chf_5x(self):
        from app.services.knowledge_graph.specialty_priors_service import apply_specialty_prior
        out = apply_specialty_prior("Cardiology", "226", 0.2)
        assert out["adjusted_score"] == pytest.approx(1.0)
        assert "Cardiology" in out["reason"]

    def test_alias_resolution_in_apply(self):
        from app.services.knowledge_graph.specialty_priors_service import apply_specialty_prior
        out = apply_specialty_prior("Nephro", "138", 1.0)
        assert out["specialty"] == "Nephrology"
        assert out["prior_weight"] == 8.0

    def test_missing_combo_uses_baseline(self):
        from app.services.knowledge_graph.specialty_priors_service import apply_specialty_prior
        out = apply_specialty_prior("Cardiology", "999", 0.5)
        assert out["applied"] is False
        assert out["prior_weight"] == 1.0
        assert out["adjusted_score"] == pytest.approx(0.5)

    def test_hcc_prefix_stripped(self):
        from app.services.knowledge_graph.specialty_priors_service import apply_specialty_prior
        out = apply_specialty_prior("Cardiology", "HCC226", 1.0)
        assert out["applied"] is True
        assert out["hcc_code"] == "226"

    def test_leading_zeros_stripped(self):
        from app.services.knowledge_graph.specialty_priors_service import apply_specialty_prior
        out = apply_specialty_prior("Internal Medicine", "0019", 2.0)
        assert out["applied"] is True
        assert out["hcc_code"] == "19"
        # IM weight is 1.0x baseline
        assert out["adjusted_score"] == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# top_n_likely_hccs
# ---------------------------------------------------------------------------

class TestTopNLikelyHccs:
    def test_cardiology_top_5_starts_with_chf(self):
        from app.services.knowledge_graph.specialty_priors_service import top_n_likely_hccs
        rows = top_n_likely_hccs("Cardiology", n=5)
        codes = [r["hcc_code"] for r in rows]
        # CHF/HFrEF/AMI/Valvular/Vascular are the top 5
        assert "226" in codes  # CHF
        assert "248" in codes  # AFib
        # The very top should be CHF (5.0 weight, highest prevalence among ties)
        assert rows[0]["hcc_code"] == "226"

    def test_nephrology_top_3(self):
        from app.services.knowledge_graph.specialty_priors_service import top_n_likely_hccs
        rows = top_n_likely_hccs("Nephrology", n=3)
        codes = {r["hcc_code"] for r in rows}
        # CKD (138), ESRD (136), Transplant (186) — these three weights
        # dominate.  138 has the highest prevalence among 8.0x peers.
        assert "138" in codes
        assert "136" in codes
        assert len(rows) == 3

    def test_pulmonology_top_3_starts_with_copd(self):
        from app.services.knowledge_graph.specialty_priors_service import top_n_likely_hccs
        rows = top_n_likely_hccs("Pulmonology", n=3)
        assert rows[0]["hcc_code"] == "280"  # COPD

    def test_n_zero_returns_empty(self):
        from app.services.knowledge_graph.specialty_priors_service import top_n_likely_hccs
        assert top_n_likely_hccs("Cardiology", n=0) == []


# ---------------------------------------------------------------------------
# compute_provider_calibrated_priors
# ---------------------------------------------------------------------------

class TestProviderCalibration:
    def test_cardiologist_provider(self):
        from app.services.knowledge_graph.specialty_priors_service import compute_provider_calibrated_priors
        out = compute_provider_calibrated_priors(101)
        assert out["raw_specialty"] == "Cards"
        assert out["canonical_specialty"] == "Cardiology"
        assert out["prior_count"] >= 5
        assert out["top_likely"]
        assert out["top_likely"][0]["hcc_code"] == "226"

    def test_nephrologist_provider(self):
        from app.services.knowledge_graph.specialty_priors_service import compute_provider_calibrated_priors
        out = compute_provider_calibrated_priors(102)
        assert out["canonical_specialty"] == "Nephrology"
        assert any(p["hcc_code"] == "138" for p in out["priors"])

    def test_unknown_specialty_provider(self):
        from app.services.knowledge_graph.specialty_priors_service import compute_provider_calibrated_priors
        out = compute_provider_calibrated_priors(104)
        # Specialty resolves (fuzzy or unchanged) but has no prior rows.
        assert out["prior_count"] == 0
        assert out["priors"] == []

    def test_missing_provider_returns_empty(self):
        from app.services.knowledge_graph.specialty_priors_service import compute_provider_calibrated_priors
        out = compute_provider_calibrated_priors(999)
        assert out["prior_count"] == 0
        assert out["raw_specialty"] is None or out["raw_specialty"] == ""


# ---------------------------------------------------------------------------
# apply_priors_to_scores (bulk)
# ---------------------------------------------------------------------------

class TestApplyPriorsToScores:
    def test_bulk_adjustment_and_sort(self):
        from app.services.knowledge_graph.specialty_priors_service import apply_priors_to_scores

        candidates = [
            {"hcc_code": "11",  "score": 0.9},  # cardiology de-enriches lung Ca (0.5x)
            {"hcc_code": "226", "score": 0.5},  # CHF 5.0x  -> 2.5
            {"hcc_code": "248", "score": 0.4},  # AFib 4.0x -> 1.6
        ]
        adjusted = apply_priors_to_scores("Cardiology", candidates)
        # Sorted desc by adjusted score
        assert adjusted[0]["hcc_code"] == "226"
        assert adjusted[0]["specialty_adjusted_score"] == pytest.approx(2.5)
        assert adjusted[1]["hcc_code"] == "248"
        # Verify input was not mutated
        assert candidates[1]["score"] == 0.5
        assert "specialty_adjusted_score" not in candidates[1]

    def test_missing_hcc_uses_baseline(self):
        from app.services.knowledge_graph.specialty_priors_service import apply_priors_to_scores
        adjusted = apply_priors_to_scores(
            "Cardiology",
            [{"hcc_code": "9999", "score": 0.7}],
        )
        assert adjusted[0]["specialty_adjusted_score"] == pytest.approx(0.7)
        assert adjusted[0]["specialty_prior"]["applied"] is False


# ---------------------------------------------------------------------------
# Sanity: missing-specialty defaults to 1.0x
# ---------------------------------------------------------------------------

class TestBaselineFallback:
    def test_unknown_specialty_keeps_score(self):
        from app.services.knowledge_graph.specialty_priors_service import apply_specialty_prior
        out = apply_specialty_prior("UnseededDiscipline", "226", 1.5)
        # Even if fuzzy-matches to nothing, the weight should be 1.0
        assert out["prior_weight"] == 1.0
        assert out["adjusted_score"] == pytest.approx(1.5)
