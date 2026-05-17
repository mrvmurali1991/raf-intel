"""
Tests for `app.services.suspect_enrichment.enrich_suspects_for_patient`.

The service:
  * Pulls MEAT completeness via `calculate_meat_completeness`.
  * Pulls trumped map via `raf_central._fetch_trumped_map`.
  * Persists both onto each `raf_suspect_conditions.evidence_detail` JSON.

All DB cursors are mocked here — we only verify the SQL the service emits
and the values it passes to JSON_SET.
"""

from __future__ import annotations

import json
import sys
import types
from unittest.mock import patch

import pytest


def _ensure_raf_central_patch_target():
    """Pre-load `app.routers.raf_central._fetch_trumped_map` so that
    `unittest.mock.patch` can resolve the attribute path.

    Suspect enrichment uses a *lazy* import to avoid a circular dep, so the
    attribute is normally only created on first call to the service. In a
    headless test env (no `qrcode`, no live DB), importing the real router
    fails, so we stub the bare minimum the patch lookup needs.
    """
    if "app.routers.raf_central" in sys.modules:
        return
    stub = types.ModuleType("app.routers.raf_central")
    stub._fetch_trumped_map = lambda *a, **kw: {}
    import app.routers  # noqa: F401  — ensure parent package is real
    sys.modules["app.routers.raf_central"] = stub
    setattr(sys.modules["app.routers"], "raf_central", stub)


_ensure_raf_central_patch_target()


def _patch_targets():
    """Return paths used by the enrichment service so we can swap them out."""
    return (
        "app.services.suspect_enrichment.raf_cursor",
        "app.services.meat_evidence_service.calculate_meat_completeness",
        "app.routers.raf_central._fetch_trumped_map",
    )


def test_tenant_id_is_required():
    """Calling without tenant_id must raise to prevent cross-tenant writes."""
    from app.services.suspect_enrichment import enrich_suspects_for_patient

    with pytest.raises(ValueError, match="tenant_id"):
        enrich_suspects_for_patient(patient_id=3, tenant_id="", year=2025)


def test_to_hcc_int_handles_common_shapes():
    from app.services.suspect_enrichment import _to_hcc_int

    assert _to_hcc_int("HCC 85") == 85
    assert _to_hcc_int("HCC85") == 85
    assert _to_hcc_int("85") == 85
    assert _to_hcc_int(85) == 85
    assert _to_hcc_int(None) is None
    assert _to_hcc_int("abc") is None
    assert _to_hcc_int("0") is None  # 0 → None (no real HCC)


def test_enrich_writes_meat_and_trumped_per_row():
    """Two suspects → both rows updated with correct (meat, trumped) tuples."""
    from tests.conftest import make_cursor_cm  # type: ignore[attr-defined]
    cm, cursor = make_cursor_cm(
        rows=[
            {"id": 11, "suspect_hcc": "HCC59"},   # MEAT 0.75, not trumped
            {"id": 12, "suspect_hcc": "85"},      # MEAT 1.0, trumped by 84
            {"id": 13, "suspect_hcc": "999"},     # no MEAT, no trump
        ]
    )

    fake_meat = {
        "per_hcc": [
            {"hcc_code": 59,  "m": True,  "e": True,  "a": True,  "t": False},
            {"hcc_code": 85,  "m": True,  "e": True,  "a": True,  "t": True},
            {"hcc_code": 200, "m": False, "e": False, "a": False, "t": False},
        ]
    }
    fake_trumped = {85: 84}

    cap_calls: list[tuple[str, tuple]] = []
    orig_execute = cursor.execute

    def _capturing_execute(sql, params=None):
        cap_calls.append((sql, params or ()))
        return orig_execute(sql, params)

    cursor.execute = _capturing_execute  # type: ignore[assignment]

    with patch("app.services.suspect_enrichment.raf_cursor", cm), patch(
        "app.services.meat_evidence_service.calculate_meat_completeness",
        return_value=fake_meat,
    ), patch(
        "app.routers.raf_central._fetch_trumped_map", return_value=fake_trumped
    ):
        from app.services.suspect_enrichment import enrich_suspects_for_patient
        n = enrich_suspects_for_patient(patient_id=3, tenant_id="t1", year=2025)

    # MockCursor reports rowcount=1 per UPDATE → all 3 counted.
    assert n == 3

    update_calls = [c for c in cap_calls if "UPDATE raf_suspect_conditions" in c[0]]
    assert len(update_calls) == 3

    # row 11 → meat 3/4=0.75, no trump
    assert update_calls[0][1] == (json.dumps(0.75), json.dumps(None), 11)
    # row 12 → meat 4/4=1.0, trumped by 84
    assert update_calls[1][1] == (json.dumps(1.0), json.dumps(84), 12)
    # row 13 → no MEAT for HCC 999, no trump
    assert update_calls[2][1] == (json.dumps(None), json.dumps(None), 13)


def test_enrich_swallows_meat_failure():
    """MEAT lookup blowing up must not stop trumped-map enrichment."""
    from tests.conftest import make_cursor_cm  # type: ignore[attr-defined]
    cm, cursor = make_cursor_cm(
        rows=[{"id": 21, "suspect_hcc": "HCC85"}]
    )

    cap: list[tuple] = []
    orig = cursor.execute
    def _cap(sql, params=None):
        cap.append((sql, params or ()))
        return orig(sql, params)
    cursor.execute = _cap  # type: ignore[assignment]

    with patch("app.services.suspect_enrichment.raf_cursor", cm), patch(
        "app.services.meat_evidence_service.calculate_meat_completeness",
        side_effect=RuntimeError("DB down"),
    ), patch(
        "app.routers.raf_central._fetch_trumped_map", return_value={85: 84}
    ):
        from app.services.suspect_enrichment import enrich_suspects_for_patient
        n = enrich_suspects_for_patient(patient_id=3, tenant_id="t1", year=2025)

    assert n == 1
    update = [c for c in cap if "UPDATE raf_suspect_conditions" in c[0]][0]
    # meat = null (failure), trumped = 84
    assert update[1] == (json.dumps(None), json.dumps(84), 21)
