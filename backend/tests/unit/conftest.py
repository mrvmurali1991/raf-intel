"""
Unit-test conftest.

Overrides the session-scoped ``server_available`` fixture defined in
``backend/tests/conftest.py`` so pure-Python unit tests (e.g. the
context detector) do not require a live backend server.
"""
from __future__ import annotations

import pytest


@pytest.fixture(scope="session", autouse=True)
def server_available() -> None:
    """No-op — unit tests do not touch the network."""
    return None
