"""Per-score SBOM (Software Bill Of Materials) tests.

Every RAF calculation must ship with an embedded SBOM that tells an
auditor — months or years later — *exactly* what produced the number:

- Which CMS-HCC / RxHCC model(s) fed into the blend.
- Which hccinfhir version supplied the coefficients.
- Whether the runtime version diverged from the pinned manifest.
- The SHA-256 of the manifest snapshot active at calculation time.
- The git commit of the calculator code.
- An ISO-8601 UTC timestamp.

These fields together make every RAF number reproducible from
(patient diagnoses + beneficiary demographics + SBOM) alone.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.services.raf.provenance import (
    _manifest_pin,
    build_score_sbom,
    calculator_commit_sha,
    coefficient_manifest_hash,
    coefficient_source,
)


_MANIFEST_PATH = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "services"
    / "raf"
    / "coefficients_manifest.json"
)


class TestSBOMShape:
    def test_v28_sbom_has_all_required_fields(self) -> None:
        sbom = build_score_sbom(
            models_used=["CMS-HCC Model V28"],
            payment_year=2026,
            plan_type="MA",
        )
        required = {
            "schema_version",
            "models_used",
            "payment_year",
            "plan_type",
            "frailty_applied",
            "coefficient_source_runtime",
            "coefficient_source_manifest",
            "coefficient_pin_drift",
            "coefficient_manifest_hash",
            "calculator_commit_sha",
            "generated_at_utc",
        }
        missing = required - set(sbom.keys())
        assert not missing, f"SBOM missing required fields: {missing}"

    def test_sbom_is_json_serializable(self) -> None:
        """Must be safe to embed in any JSON API response or DB JSON column."""
        sbom = build_score_sbom(
            models_used=["CMS-HCC Model V28"],
            payment_year=2026,
            plan_type="PACE",
            frailty_applied=True,
        )
        # Must round-trip through json without error.
        serialized = json.dumps(sbom)
        restored = json.loads(serialized)
        assert restored == sbom


class TestSBOMContentAccuracy:
    def test_models_deduplicated_and_sorted(self) -> None:
        sbom = build_score_sbom(
            models_used=[
                "CMS-HCC Model V28",
                "CMS-HCC Model V22",
                "CMS-HCC Model V28",
            ],
            payment_year=2026,
        )
        assert sbom["models_used"] == [
            "CMS-HCC Model V22",
            "CMS-HCC Model V28",
        ]

    def test_pace_blend_shows_both_models(self) -> None:
        sbom = build_score_sbom(
            models_used=["CMS-HCC Model V22", "CMS-HCC Model V28"],
            payment_year=2026,
            plan_type="PACE",
        )
        assert sbom["models_used"] == [
            "CMS-HCC Model V22",
            "CMS-HCC Model V28",
        ]

    def test_runtime_source_matches_live_hccinfhir(self) -> None:
        sbom = build_score_sbom(
            models_used=["CMS-HCC Model V28"], payment_year=2026
        )
        assert sbom["coefficient_source_runtime"] == coefficient_source()
        assert sbom["coefficient_source_runtime"].startswith("hccinfhir==")

    def test_manifest_pin_matches_manifest_file(self) -> None:
        sbom = build_score_sbom(
            models_used=["CMS-HCC Model V28"], payment_year=2026
        )
        # If a manifest is on disk, the SBOM must surface its pinned version.
        assert sbom["coefficient_source_manifest"] == _manifest_pin()

    def test_manifest_hash_is_sha256_hex(self) -> None:
        sbom = build_score_sbom(
            models_used=["CMS-HCC Model V28"], payment_year=2026
        )
        h = sbom["coefficient_manifest_hash"]
        assert h is not None, "manifest hash must be present"
        assert re.fullmatch(r"[0-9a-f]{64}", h), (
            f"manifest hash {h!r} must be 64-char lowercase hex (SHA-256)"
        )
        assert h == coefficient_manifest_hash()

    def test_generated_at_is_recent_utc_iso(self) -> None:
        sbom = build_score_sbom(
            models_used=["CMS-HCC Model V28"], payment_year=2026
        )
        ts = sbom["generated_at_utc"]
        parsed = datetime.fromisoformat(ts)
        # Must be UTC-aware.
        assert parsed.tzinfo is not None
        assert parsed.tzinfo.utcoffset(None) == timezone.utc.utcoffset(None)
        # Within last 60s of "now".
        age = (datetime.now(timezone.utc) - parsed).total_seconds()
        assert 0 <= age < 60, f"generated_at timestamp suspicious: age={age}s"

    def test_calculator_commit_may_be_absent_but_string_when_present(self) -> None:
        sbom = build_score_sbom(
            models_used=["CMS-HCC Model V28"], payment_year=2026
        )
        sha = sbom["calculator_commit_sha"]
        if sha is not None:
            assert isinstance(sha, str) and len(sha) <= 40
            assert sha == calculator_commit_sha()


class TestSBOMDriftDetection:
    def test_pin_drift_flag_is_boolean(self) -> None:
        sbom = build_score_sbom(
            models_used=["CMS-HCC Model V28"], payment_year=2026
        )
        assert isinstance(sbom["coefficient_pin_drift"], bool)

    def test_pin_drift_false_when_runtime_matches_manifest(self) -> None:
        """Our CI env must pin hccinfhir to whatever the manifest says."""
        pin = _manifest_pin()
        live = coefficient_source()
        if pin is None:
            pytest.skip("No manifest pin recorded")
        if pin != live:
            pytest.skip(
                f"Runtime hccinfhir ({live}) doesn't match manifest pin "
                f"({pin}) — drift is expected-true"
            )
        sbom = build_score_sbom(
            models_used=["CMS-HCC Model V28"], payment_year=2026
        )
        assert sbom["coefficient_pin_drift"] is False


class TestSBOMPlanMetadata:
    @pytest.mark.parametrize("plan_type", ["MA", "PACE", "FIDE_SNP", None])
    def test_plan_type_echoed_verbatim(self, plan_type: str | None) -> None:
        sbom = build_score_sbom(
            models_used=["CMS-HCC Model V28"],
            payment_year=2026,
            plan_type=plan_type,
        )
        assert sbom["plan_type"] == plan_type

    @pytest.mark.parametrize("year", [2024, 2025, 2026])
    def test_payment_year_echoed_verbatim(self, year: int) -> None:
        sbom = build_score_sbom(
            models_used=["CMS-HCC Model V28"], payment_year=year
        )
        assert sbom["payment_year"] == year

    def test_frailty_flag_defaults_false(self) -> None:
        sbom = build_score_sbom(
            models_used=["CMS-HCC Model V28"], payment_year=2026
        )
        assert sbom["frailty_applied"] is False

    def test_frailty_flag_propagates(self) -> None:
        sbom = build_score_sbom(
            models_used=["CMS-HCC Model V28"],
            payment_year=2026,
            plan_type="PACE",
            frailty_applied=True,
        )
        assert sbom["frailty_applied"] is True


class TestSBOMManifestHashStability:
    def test_hash_matches_live_file_digest(self) -> None:
        import hashlib

        assert _MANIFEST_PATH.exists(), "manifest file must be present"
        expected = hashlib.sha256(_MANIFEST_PATH.read_bytes()).hexdigest()
        assert coefficient_manifest_hash() == expected
