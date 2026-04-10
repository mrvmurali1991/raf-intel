"""
Pytest fixtures for the RAF Intelligence integration test suite.

All tests are INTEGRATION tests — they hit the live backend running at
http://localhost:8500.  If the server is unreachable, every test that
depends on `api_client` will be skipped automatically via the
`server_available` session-scoped auto-fixture.
"""
from __future__ import annotations

import pytest
import requests


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_URL = "http://localhost:8500"
REQUEST_TIMEOUT = 30  # seconds — analysis endpoints can be slow


# ---------------------------------------------------------------------------
# Session-level server availability guard
# ---------------------------------------------------------------------------

def _is_server_up(base_url: str) -> bool:
    """Return True if the backend health endpoint responds within 3 s."""
    try:
        r = requests.get(f"{base_url}/health", timeout=3)
        return r.status_code in (200, 503)  # 503 = degraded but alive
    except requests.exceptions.RequestException:
        return False


@pytest.fixture(scope="session", autouse=True)
def server_available():
    """
    Auto-use session fixture.  If the server is not reachable all tests that
    rely on `api_client` or `base_url` are skipped rather than erroring out
    with an unhelpful ConnectionError.
    """
    if not _is_server_up(BASE_URL):
        pytest.skip(
            f"RAF Intelligence backend is not reachable at {BASE_URL}. "
            "Start it with: uvicorn app.main:app --host 0.0.0.0 --port 8500 --reload",
            allow_module_level=True,
        )


# ---------------------------------------------------------------------------
# Core fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def base_url() -> str:
    """Base URL for the running backend."""
    return BASE_URL


@pytest.fixture(scope="session")
def api_client() -> requests.Session:
    """
    A shared requests.Session for the entire test run.

    Sets default headers (Accept: application/json) and a sensible timeout
    so individual tests do not need to manage connection details.
    """
    session = requests.Session()
    session.headers.update({"Accept": "application/json"})
    session.timeout = REQUEST_TIMEOUT
    yield session
    session.close()


# ---------------------------------------------------------------------------
# Patient fixtures — discovered dynamically from the live server
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def sample_patients(api_client: requests.Session, base_url: str) -> list[dict]:
    """
    Fetch patients that have at least one encounter from the live server.
    Returns a list of patient dicts (may be empty if no data is loaded).
    Cached for the whole session to avoid redundant network calls.
    """
    r = api_client.get(f"{base_url}/api/patients/with-encounters", timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    data = r.json()
    return data.get("patients", [])


@pytest.fixture(scope="session")
def first_pid(sample_patients: list[dict]) -> int:
    """
    PID of the first patient that has encounters.
    Tests that require a valid PID should depend on this fixture.
    Skips if no patients with encounters exist.
    """
    if not sample_patients:
        pytest.skip("No patients with encounters found — seed the database first.")
    patient = sample_patients[0]
    # OpenEMR stores the PID under 'pid' key
    return int(patient.get("pid") or patient.get("id") or patient.get("patient_id"))


@pytest.fixture(scope="session")
def first_encounter_id(
    api_client: requests.Session,
    base_url: str,
    first_pid: int,
) -> int:
    """
    Encounter ID of the first encounter for `first_pid`.
    Skips if the patient has no encounters.
    """
    r = api_client.get(
        f"{base_url}/api/patients/{first_pid}/encounters",
        timeout=REQUEST_TIMEOUT,
    )
    r.raise_for_status()
    data = r.json()
    encounters = data.get("encounters", [])
    if not encounters:
        pytest.skip(f"Patient {first_pid} has no encounters — seed the database first.")
    enc = encounters[0]
    return int(
        enc.get("id")
        or enc.get("encounter_id")
        or enc.get("eid")
        or enc.get("encounter")
    )


@pytest.fixture(scope="session")
def nonexistent_pid() -> int:
    """A PID that should not exist in any realistic test database."""
    return 999_999_999
