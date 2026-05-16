"""
HIPAA 164.312(b) — Real-DB audit log integration tests.

These tests require a live MySQL instance with the RAF schema applied.
Skip them in CI unless RAF_DB_HOST is set:

    pytest -m integration tests/integration/test_audit_log_real_db.py

The fixture connects directly via mysql-connector-python using the same
env vars the application uses so no second config is needed.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any, Generator

import pytest

# ---------------------------------------------------------------------------
# Markers
# ---------------------------------------------------------------------------
pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# PHI tokens that must never appear verbatim in audit_log rows
# ---------------------------------------------------------------------------
_PHI_PATTERNS = [
    "Smith",
    "Jones",
    "1960-01-01",
    "555-12",  # partial SSN/phone sentinel
    "MRN",
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ADMIN_USER_ID = 1  # id used in seed / JWT tokens


def _phi_free(text: str | None) -> bool:
    """Return True when *text* contains none of the known PHI test sentinels."""
    if not text:
        return True
    for pat in _PHI_PATTERNS:
        if pat.lower() in text.lower():
            return False
    return True


# ---------------------------------------------------------------------------
# Session-scoped real-DB fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def real_db():
    """
    Yield a mysql-connector-python connection to the RAF database.

    Skips the entire session when RAF_DB_HOST is not configured so that
    the normal ``pytest`` run (unit tests only) is unaffected.
    """
    host = os.environ.get("RAF_DB_HOST")
    if not host:
        pytest.skip("RAF_DB_HOST not set — skipping real-DB integration tests")

    import mysql.connector  # type: ignore[import]

    conn = mysql.connector.connect(
        host=host,
        port=int(os.environ.get("RAF_DB_PORT", "3306")),
        user=os.environ.get("RAF_DB_USER", "root"),
        password=os.environ.get("RAF_DB_PASSWORD", ""),
        database=os.environ.get("RAF_DB_NAME", "raf_intelligence"),
        ssl_disabled=os.environ.get("DB_SSL_ENABLED", "false").lower() != "true",
        autocommit=True,
        connection_timeout=10,
    )
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture()
def db_cursor(real_db):
    """Function-scoped dict cursor; closed automatically after each test."""
    cur = real_db.cursor(dictionary=True)
    try:
        yield cur
    finally:
        cur.close()


# ---------------------------------------------------------------------------
# Lightweight HTTP client against the live app
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def live_base_url() -> str:
    return os.environ.get("TEST_BASE_URL", "http://localhost:8500")


@pytest.fixture(scope="session")
def admin_session(live_base_url: str):
    """
    Log in as admin and return a requests.Session with Bearer token set.
    Skips if the server is unreachable.
    """
    import requests

    session = requests.Session()
    try:
        r = session.post(
            f"{live_base_url}/api/auth/login",
            json={"email": "admin@raf.health", "password": "Admin@123"},
            timeout=5,
        )
        r.raise_for_status()
        token = r.json()["access_token"]
        session.headers["Authorization"] = f"Bearer {token}"
    except Exception as exc:
        pytest.skip(f"Live server not reachable: {exc}")
    return session


@pytest.fixture(scope="session")
def viewer_session(live_base_url: str):
    """
    Log in as a viewer (non-admin) user.  Creates the user via admin API if
    it does not already exist, then logs in.
    Skips when the server is unreachable.
    """
    import requests

    # First get an admin token to potentially create the viewer
    admin = requests.Session()
    try:
        r = admin.post(
            f"{live_base_url}/api/auth/login",
            json={"email": "admin@raf.health", "password": "Admin@123"},
            timeout=5,
        )
        r.raise_for_status()
        admin.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    except Exception as exc:
        pytest.skip(f"Live server not reachable: {exc}")

    # Try to register a viewer account; ignore if it already exists
    viewer_email = "integ-viewer@raf-test.internal"
    viewer_pw = "Viewer@IntegTest1"
    admin.post(
        f"{live_base_url}/api/auth/register",
        json={
            "email": viewer_email,
            "password": viewer_pw,
            "full_name": "Integration Viewer",
            "role": "viewer",
        },
        timeout=5,
    )

    session = requests.Session()
    try:
        r = session.post(
            f"{live_base_url}/api/auth/login",
            json={"email": viewer_email, "password": viewer_pw},
            timeout=5,
        )
        r.raise_for_status()
        session.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    except Exception as exc:
        pytest.skip(f"Could not log in as viewer: {exc}")
    return session


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPhiAuditRealDb:
    """PHI-access audit log persistence verified against a live MySQL instance."""

    def _latest_audit_row(
        self, cur, *, action: str, patient_id: int, after_ts: float
    ) -> dict[str, Any] | None:
        """
        Fetch the most recent audit_log row matching *action* and *patient_id*
        that was inserted after *after_ts* (unix epoch seconds).
        """
        cur.execute(
            """
            SELECT id, user_id, action, resource_type, resource_id,
                   patient_id, details, created_at
            FROM   audit_log
            WHERE  action      = %s
              AND  patient_id  = %s
              AND  created_at >= FROM_UNIXTIME(%s)
            ORDER  BY id DESC
            LIMIT  1
            """,
            (action, patient_id, int(after_ts)),
        )
        return cur.fetchone()

    def _cleanup(self, cur, *, action: str, patient_id: int) -> None:
        cur.execute(
            "DELETE FROM audit_log WHERE action = %s AND patient_id = %s",
            (action, patient_id),
        )

    # ------------------------------------------------------------------

    @pytest.mark.integration
    def test_phi_get_writes_audit_row(
        self, admin_session, live_base_url, db_cursor
    ) -> None:
        """
        GET /api/patients/{pid} must persist a phi_view row in audit_log.

        Asserts:
        - Row exists with action='phi_view'.
        - patient_id column matches the requested pid.
        - user_id column is set (not NULL).
        - details JSON column contains no patient name, DOB, or SSN sentinel.
        """
        pid = 1
        before = time.time() - 1  # small buffer for clock skew

        resp = admin_session.get(f"{live_base_url}/api/patients/{pid}", timeout=10)
        # 200 or 404 are both acceptable — what matters is the audit row
        assert resp.status_code in (200, 404, 403), (
            f"Unexpected status {resp.status_code}: {resp.text[:200]}"
        )

        # Give the async DB write a moment to commit
        time.sleep(0.3)

        row = self._latest_audit_row(
            db_cursor, action="phi_view", patient_id=pid, after_ts=before
        )
        try:
            assert row is not None, (
                "No phi_view row found in audit_log after GET /api/patients/1"
            )
            assert row["patient_id"] == pid
            assert row["user_id"] is not None, "user_id must not be NULL in audit_log"
            assert row["action"] == "phi_view"

            details_raw = row.get("details")
            details_str = (
                json.dumps(details_raw)
                if isinstance(details_raw, dict)
                else (details_raw or "")
            )
            assert _phi_free(details_str), (
                f"PHI sentinel found in audit_log.details: {details_str[:200]}"
            )
        finally:
            self._cleanup(db_cursor, action="phi_view", patient_id=pid)

    # ------------------------------------------------------------------

    @pytest.mark.integration
    def test_phi_get_does_not_log_phi_in_message(
        self, admin_session, live_base_url, db_cursor
    ) -> None:
        """
        The details JSON in audit_log must not contain MRN, DOB, or full name.

        Checks both the `details` column and the `resource_id` column which
        must store only the numeric patient id, never freeform PHI text.
        """
        pid = 1
        before = time.time() - 1

        admin_session.get(f"{live_base_url}/api/patients/{pid}", timeout=10)
        time.sleep(0.3)

        db_cursor.execute(
            """
            SELECT details, resource_id, resource_type
            FROM   audit_log
            WHERE  action     = 'phi_view'
              AND  patient_id = %s
              AND  created_at >= FROM_UNIXTIME(%s)
            ORDER  BY id DESC
            LIMIT  1
            """,
            (pid, int(before)),
        )
        row = db_cursor.fetchone()
        try:
            assert row is not None, "Expected at least one phi_view row"

            details_raw = row.get("details")
            details_str = (
                json.dumps(details_raw)
                if isinstance(details_raw, dict)
                else (details_raw or "")
            )
            assert _phi_free(details_str), (
                f"PHI found in details column: {details_str[:300]}"
            )

            # resource_id must be a numeric string, not a patient name
            rid = row.get("resource_id") or ""
            assert rid.isdigit() or rid == "", (
                f"resource_id should be numeric patient id, got: {rid!r}"
            )
        finally:
            db_cursor.execute(
                "DELETE FROM audit_log WHERE action='phi_view' AND patient_id=%s",
                (pid,),
            )

    # ------------------------------------------------------------------

    @pytest.mark.integration
    def test_unauthorized_access_does_not_leak_phi_in_audit(
        self, viewer_session, live_base_url, db_cursor
    ) -> None:
        """
        When a viewer hits a patient endpoint and an audit row is written,
        that row must not embed PHI regardless of the HTTP response code.

        This doubles as a guard: if the app ever starts writing PHI to the
        audit trail for failed requests the test will catch it.
        """
        pid = 1
        before = time.time() - 1

        # viewer may get 200, 403, or 404 — we don't care about the HTTP outcome
        viewer_session.get(f"{live_base_url}/api/patients/{pid}", timeout=10)
        time.sleep(0.3)

        db_cursor.execute(
            """
            SELECT details, resource_id
            FROM   audit_log
            WHERE  patient_id = %s
              AND  created_at >= FROM_UNIXTIME(%s)
            ORDER  BY id DESC
            LIMIT  5
            """,
            (pid, int(before)),
        )
        rows = db_cursor.fetchall()
        try:
            for row in rows:
                details_raw = row.get("details")
                details_str = (
                    json.dumps(details_raw)
                    if isinstance(details_raw, dict)
                    else (details_raw or "")
                )
                assert _phi_free(details_str), (
                    f"PHI leaked into audit_log.details for viewer request: "
                    f"{details_str[:300]}"
                )
        finally:
            db_cursor.execute(
                "DELETE FROM audit_log WHERE patient_id=%s AND created_at >= FROM_UNIXTIME(%s)",
                (pid, int(before)),
            )
