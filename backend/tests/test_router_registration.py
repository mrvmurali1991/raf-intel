"""Lightweight sanity tests for the FastAPI app-mount layer.

Catches the "router file is untracked / a service module disappeared
between branches" class of bug at PR-time, before pytest collection
balloons into hard-to-read import errors.

These tests deliberately avoid a live DB or auth — they only assert
that the app boots and every router we promise customers actually
ended up registered.
"""
from __future__ import annotations

import pytest


def _route_paths():
    from app.main import app
    return [getattr(r, "path", "") for r in app.routes]


def test_app_boots_with_all_routers() -> None:
    paths = _route_paths()
    assert len(paths) > 100, f"Expected 100+ routes, got {len(paths)}"


@pytest.mark.parametrize(
    "prefix,description",
    [
        ("/api/kg/", "Knowledge-graph layer"),
        ("/api/kg/polypharmacy/", "Polypharmacy router"),
        ("/api/kg/brand-generic/", "Brand-to-generic bridge"),
        ("/api/recapture/", "Recapture workflow routers"),
        ("/api/worklist/", "Provider worklist router"),
        ("/api/dashboard/stats", "Dashboard stats endpoint"),
        ("/api/recapture/audit-readiness", "RADV audit-readiness endpoint"),
    ],
)
def test_required_route_prefix_registered(prefix: str, description: str) -> None:
    paths = _route_paths()
    assert any(p.startswith(prefix) for p in paths), (
        f"{description} not registered (looked for prefix {prefix!r}). "
        "Likely cause: a router import failed silently or a service "
        "module is missing from the branch."
    )


def test_kg_smoke_inputs_file_present() -> None:
    # The smoke-test fixture file must ship with the backend so dev
    # / staging pipelines can re-run the end-to-end probe.
    from pathlib import Path
    fixture = Path(__file__).resolve().parents[1] / "scripts" / "kg_smoke_inputs.json"
    assert fixture.exists(), f"kg_smoke_inputs.json missing at {fixture}"


def test_evaluation_fixtures_present() -> None:
    # The benchmark fixtures must ship; otherwise the calibration
    # report shown to customers would silently be empty.
    from pathlib import Path
    base = Path(__file__).resolve().parents[1] / "app" / "services" / "evaluation" / "fixtures"
    assert (base / "sample_charts.json").exists()
    assert (base / "extended_charts.json").exists()
