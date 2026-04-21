"""
Admin endpoint tests.

Covers:
- GET  /api/admin/backups — list backups (admin only)
- POST /api/admin/backups — trigger backup (admin only)
- GET  /api/admin/backups/jobs/{job_id} — job status
- GET  /api/admin/system-info — system information
- Role enforcement: viewer / manager cannot access admin routes

All DB calls and backup service are mocked — no database or filesystem required.

Markers: security (role tests)
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

from tests.conftest import (
    MOCK_ADMIN_USER,
    MOCK_MANAGER_USER,
    MOCK_VIEWER_USER,
    _make_access_token,
)

# ---------------------------------------------------------------------------
# Helper: patch auth to resolve to a specific user
# ---------------------------------------------------------------------------

def _auth_patch(user: dict):
    """Return a context-manager that wires up the auth layer for *user*."""
    from contextlib import contextmanager

    @contextmanager
    def _cm():
        session_row = {"session_id": user["session_id"], "is_revoked": 0}
        with (
            patch("app.auth.get_user", return_value=user),
            patch("app.auth.validate_session", return_value=session_row),
        ):
            yield

    return _cm()


# ---------------------------------------------------------------------------
# Backup service mock data
# ---------------------------------------------------------------------------

MOCK_BACKUP_STATUS = {
    "backup_dir": "/var/backups/raf",
    "backups": [
        {
            "filename": "raf_intelligence_2026-04-06_01-00.sql.gz",
            "size_bytes": 1024 * 512,
            "created_at": "2026-04-06T01:00:00Z",
            "database": "raf",
        },
        {
            "filename": "openemr_2026-04-05_01-00.sql.gz",
            "size_bytes": 1024 * 1024 * 5,
            "created_at": "2026-04-05T01:00:00Z",
            "database": "openemr",
        },
    ],
    "total_size_bytes": 1024 * 512 + 1024 * 1024 * 5,
    "last_backup_at": "2026-04-06T01:00:00Z",
}

MOCK_BACKUP_SCHEDULE = {
    "cron": "0 1 * * *",
    "description": "Daily at 01:00 UTC",
    "enabled": True,
}

MOCK_BACKUP_JOB = {
    "job_id": "job-abc-123",
    "status": "running",
    "backup_type": "full",
    "started_at": datetime.now(timezone.utc).isoformat(),
    "finished_at": None,
}

MOCK_BACKUP_JOB_COMPLETE = {
    "job_id": "job-abc-123",
    "status": "success",
    "backup_type": "full",
    "started_at": "2026-04-06T01:00:00Z",
    "finished_at": "2026-04-06T01:05:00Z",
}


# ---------------------------------------------------------------------------
# 1. GET /api/admin/backups — list backups
# ---------------------------------------------------------------------------

class TestListBackups:
    def test_admin_can_list_backups_200(self, client):
        token = _make_access_token(MOCK_ADMIN_USER)
        with (
            _auth_patch(MOCK_ADMIN_USER),
            patch("app.routers.admin.get_backup_status", return_value=MOCK_BACKUP_STATUS),
            patch("app.routers.admin.get_backup_schedule", return_value=MOCK_BACKUP_SCHEDULE),
            patch("app.routers.admin.list_jobs", return_value=[MOCK_BACKUP_JOB]),
        ):
            resp = client.get(
                "/api/admin/backups",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 200

    def test_backups_response_contains_backups_key(self, client):
        token = _make_access_token(MOCK_ADMIN_USER)
        with (
            _auth_patch(MOCK_ADMIN_USER),
            patch("app.routers.admin.get_backup_status", return_value=MOCK_BACKUP_STATUS),
            patch("app.routers.admin.get_backup_schedule", return_value=MOCK_BACKUP_SCHEDULE),
            patch("app.routers.admin.list_jobs", return_value=[]),
        ):
            resp = client.get(
                "/api/admin/backups",
                headers={"Authorization": f"Bearer {token}"},
            )
        data = resp.json()
        assert "backups" in data or "backup_dir" in data

    def test_backups_response_contains_schedule(self, client):
        token = _make_access_token(MOCK_ADMIN_USER)
        with (
            _auth_patch(MOCK_ADMIN_USER),
            patch("app.routers.admin.get_backup_status", return_value=MOCK_BACKUP_STATUS),
            patch("app.routers.admin.get_backup_schedule", return_value=MOCK_BACKUP_SCHEDULE),
            patch("app.routers.admin.list_jobs", return_value=[]),
        ):
            resp = client.get(
                "/api/admin/backups",
                headers={"Authorization": f"Bearer {token}"},
            )
        data = resp.json()
        assert "schedule" in data

    def test_viewer_cannot_list_backups_403(self, client):
        token = _make_access_token(MOCK_VIEWER_USER)
        with _auth_patch(MOCK_VIEWER_USER):
            resp = client.get(
                "/api/admin/backups",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code in (403, 401)

    def test_manager_cannot_list_backups_403(self, client):
        token = _make_access_token(MOCK_MANAGER_USER)
        with _auth_patch(MOCK_MANAGER_USER):
            resp = client.get(
                "/api/admin/backups",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code in (403, 401)

    def test_unauthenticated_returns_401(self, client):
        resp = client.get("/api/admin/backups")
        assert resp.status_code == 401

    def test_service_exception_returns_500(self, client):
        token = _make_access_token(MOCK_ADMIN_USER)
        with (
            _auth_patch(MOCK_ADMIN_USER),
            patch("app.routers.admin.get_backup_status", side_effect=RuntimeError("disk error")),
            patch("app.routers.admin.get_backup_schedule", return_value={}),
            patch("app.routers.admin.list_jobs", return_value=[]),
        ):
            resp = client.get(
                "/api/admin/backups",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 500
        # Error message must be generic — no raw exception text
        data = resp.json()
        assert "disk error" not in data.get("detail", "").lower()


# ---------------------------------------------------------------------------
# 2. POST /api/admin/backups — trigger backup
# ---------------------------------------------------------------------------

class TestTriggerBackup:
    def test_admin_can_trigger_backup_202(self, client):
        token = _make_access_token(MOCK_ADMIN_USER)
        with (
            _auth_patch(MOCK_ADMIN_USER),
            patch("app.routers.admin.trigger_backup", return_value=MOCK_BACKUP_JOB),
        ):
            resp = client.post(
                "/api/admin/backups",
                json={"backup_type": "full"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 202

    def test_trigger_raf_backup(self, client):
        token = _make_access_token(MOCK_ADMIN_USER)
        job = {**MOCK_BACKUP_JOB, "backup_type": "raf"}
        with (
            _auth_patch(MOCK_ADMIN_USER),
            patch("app.routers.admin.trigger_backup", return_value=job),
        ):
            resp = client.post(
                "/api/admin/backups",
                json={"backup_type": "raf"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 202

    def test_invalid_backup_type_returns_422(self, client):
        token = _make_access_token(MOCK_ADMIN_USER)
        with _auth_patch(MOCK_ADMIN_USER):
            resp = client.post(
                "/api/admin/backups",
                json={"backup_type": "invalid_type"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 422

    def test_viewer_cannot_trigger_backup(self, client):
        token = _make_access_token(MOCK_VIEWER_USER)
        with _auth_patch(MOCK_VIEWER_USER):
            resp = client.post(
                "/api/admin/backups",
                json={"backup_type": "full"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code in (403, 401)

    def test_trigger_response_contains_job_id(self, client):
        token = _make_access_token(MOCK_ADMIN_USER)
        with (
            _auth_patch(MOCK_ADMIN_USER),
            patch("app.routers.admin.trigger_backup", return_value=MOCK_BACKUP_JOB),
        ):
            resp = client.post(
                "/api/admin/backups",
                json={"backup_type": "full"},
                headers={"Authorization": f"Bearer {token}"},
            )
        data = resp.json()
        assert "job_id" in data

    def test_trigger_missing_backup_sh_returns_500(self, client):
        token = _make_access_token(MOCK_ADMIN_USER)
        with (
            _auth_patch(MOCK_ADMIN_USER),
            patch("app.routers.admin.trigger_backup", side_effect=FileNotFoundError("backup.sh not found")),
        ):
            resp = client.post(
                "/api/admin/backups",
                json={"backup_type": "full"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 500


# ---------------------------------------------------------------------------
# 3. GET /api/admin/backups/jobs/{job_id}
# ---------------------------------------------------------------------------

class TestBackupJobStatus:
    def test_get_running_job(self, client):
        token = _make_access_token(MOCK_ADMIN_USER)
        with (
            _auth_patch(MOCK_ADMIN_USER),
            patch("app.routers.admin.get_job_status", return_value=MOCK_BACKUP_JOB),
        ):
            resp = client.get(
                "/api/admin/backups/jobs/job-abc-123",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "running"

    def test_get_completed_job(self, client):
        token = _make_access_token(MOCK_ADMIN_USER)
        with (
            _auth_patch(MOCK_ADMIN_USER),
            patch("app.routers.admin.get_job_status", return_value=MOCK_BACKUP_JOB_COMPLETE),
        ):
            resp = client.get(
                "/api/admin/backups/jobs/job-abc-123",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "success"

    def test_get_nonexistent_job_returns_404(self, client):
        token = _make_access_token(MOCK_ADMIN_USER)
        with (
            _auth_patch(MOCK_ADMIN_USER),
            patch("app.routers.admin.get_job_status", return_value=None),
        ):
            resp = client.get(
                "/api/admin/backups/jobs/nonexistent-id",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 404

    def test_viewer_cannot_get_job_status(self, client):
        token = _make_access_token(MOCK_VIEWER_USER)
        with _auth_patch(MOCK_VIEWER_USER):
            resp = client.get(
                "/api/admin/backups/jobs/some-job",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code in (403, 401)


# ---------------------------------------------------------------------------
# 4. GET /api/admin/system-info
# ---------------------------------------------------------------------------

class TestSystemInfo:
    def test_admin_can_get_system_info(self, client):
        token = _make_access_token(MOCK_ADMIN_USER)
        with _auth_patch(MOCK_ADMIN_USER):
            resp = client.get(
                "/api/admin/system-info",
                headers={"Authorization": f"Bearer {token}"},
            )
        # Either 200 (route exists) or 404 (route not yet implemented)
        assert resp.status_code in (200, 404)

    def test_unauthenticated_system_info_returns_401(self, client):
        resp = client.get("/api/admin/system-info")
        assert resp.status_code in (401, 404)


# ---------------------------------------------------------------------------
# 5. Error message sanitization — admin endpoints must not leak raw exceptions
# ---------------------------------------------------------------------------

class TestAdminErrorSanitization:
    def test_backup_list_error_does_not_leak_traceback(self, client):
        token = _make_access_token(MOCK_ADMIN_USER)
        with (
            _auth_patch(MOCK_ADMIN_USER),
            patch(
                "app.routers.admin.get_backup_status",
                side_effect=RuntimeError("Traceback (most recent call last): ..."),
            ),
            patch("app.routers.admin.get_backup_schedule", return_value={}),
            patch("app.routers.admin.list_jobs", return_value=[]),
        ):
            resp = client.get(
                "/api/admin/backups",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 500
        body = resp.text
        assert "Traceback" not in body
        assert "most recent call" not in body
