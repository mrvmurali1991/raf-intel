"""
API Contracts — expanded test suite (endpoint signature validation).

Verifies that critical FastAPI endpoints have required dependencies
(tenant isolation, rate limiting, auth) by inspecting source files directly.

No database or network required — uses file-level source inspection to
avoid triggering module imports that need native extensions (argon2).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helper: read module source without executing (avoids import chains)
# ---------------------------------------------------------------------------

def _read_module_source(module_path: str) -> str:
    """Read a module's source from disk without importing it."""
    spec = importlib.util.find_spec(module_path)
    if spec is None or spec.origin is None:
        pytest.skip(f"Cannot locate module {module_path}")
    with open(spec.origin, "r") as f:
        return f.read()


def _read_file_source(relative_path: str) -> str:
    """Read source directly from a known file path."""
    base = Path(__file__).resolve().parent.parent / "app"
    full_path = base / relative_path
    if not full_path.exists():
        pytest.skip(f"File not found: {full_path}")
    return full_path.read_text()


# ---------------------------------------------------------------------------
# 1. Document endpoints require tenant_id
# ---------------------------------------------------------------------------

class TestDocumentEndpointsTenantIsolation:
    """Every document endpoint must have a tenant_id parameter."""

    def test_get_document_has_tenant_id(self):
        source = _read_file_source("routers/documents.py")
        # Find the get_document_endpoint function and verify tenant_id in signature
        idx = source.find("def get_document_endpoint(")
        assert idx >= 0, "get_document_endpoint not found"
        sig_block = source[idx:idx + 300]
        assert "tenant_id" in sig_block

    def test_view_document_file_has_tenant_id(self):
        source = _read_file_source("routers/documents.py")
        idx = source.find("def view_document_file(")
        assert idx >= 0
        sig_block = source[idx:idx + 300]
        assert "tenant_id" in sig_block

    def test_get_analysis_has_tenant_id(self):
        source = _read_file_source("routers/documents.py")
        idx = source.find("def get_analysis_endpoint(")
        assert idx >= 0
        sig_block = source[idx:idx + 300]
        assert "tenant_id" in sig_block

    def test_get_diagnoses_has_tenant_id(self):
        source = _read_file_source("routers/documents.py")
        idx = source.find("def get_diagnoses_endpoint(")
        assert idx >= 0
        sig_block = source[idx:idx + 300]
        assert "tenant_id" in sig_block


# ---------------------------------------------------------------------------
# 2. Suspect KG endpoints require tenant_id
# ---------------------------------------------------------------------------

class TestSuspectKgTenantIsolation:
    """Every suspect KG endpoint must accept tenant_id."""

    def test_kg_detect_has_tenant_id(self):
        source = _read_file_source("routers/suspect_kg.py")
        idx = source.find("def kg_detect(")
        assert idx >= 0
        sig_block = source[idx:idx + 300]
        assert "tenant_id" in sig_block

    def test_kg_evidence_distribution_has_tenant_id(self):
        source = _read_file_source("routers/suspect_kg.py")
        idx = source.find("def kg_evidence_distribution(")
        assert idx >= 0
        sig_block = source[idx:idx + 300]
        assert "tenant_id" in sig_block

    def test_evidence_chain_has_tenant_id(self):
        source = _read_file_source("routers/suspect_kg.py")
        idx = source.find("def evidence_chain(")
        assert idx >= 0
        sig_block = source[idx:idx + 300]
        assert "tenant_id" in sig_block


# ---------------------------------------------------------------------------
# 3. Auth router rate limiting
# ---------------------------------------------------------------------------

class TestAuthRateLimiting:
    """Auth router must have rate limiting on login and sensitive endpoints."""

    def test_auth_module_imports_limiter(self):
        source = _read_file_source("routers/auth.py")
        assert "limiter" in source

    def test_auth_has_rate_limit_decorator(self):
        source = _read_file_source("routers/auth.py")
        assert "@limiter.limit" in source

    def test_auth_has_login_rate_key(self):
        source = _read_file_source("routers/auth.py")
        assert "login_rate_key" in source


# ---------------------------------------------------------------------------
# 4. Patient router tenant isolation
# ---------------------------------------------------------------------------

class TestPatientRouterTenantIsolation:
    """Patient endpoints must require tenant_id."""

    def test_patient_router_uses_get_tenant_id(self):
        source = _read_file_source("routers/patients.py")
        assert "get_tenant_id" in source

    def test_patient_router_imports_auth_dependency(self):
        source = _read_file_source("routers/patients.py")
        assert "get_current_user" in source


# ---------------------------------------------------------------------------
# 5. RAF router tenant isolation
# ---------------------------------------------------------------------------

class TestRafRouterTenantIsolation:
    """RAF score endpoints must require tenant_id."""

    def test_raf_router_uses_get_tenant_id(self):
        source = _read_file_source("routers/raf.py")
        assert "get_tenant_id" in source

    def test_raf_router_has_auth(self):
        source = _read_file_source("routers/raf.py")
        assert "get_current_user" in source


# ---------------------------------------------------------------------------
# 6. Document service tenant isolation
# ---------------------------------------------------------------------------

class TestDocumentServiceTenantIsolation:
    """get_document must accept tenant_id parameter."""

    def test_get_document_accepts_tenant_id(self):
        source = _read_file_source("services/document_service.py")
        idx = source.find("def get_document(")
        assert idx >= 0
        sig_block = source[idx:idx + 300]
        assert "tenant_id" in sig_block


# ---------------------------------------------------------------------------
# 7. Sync log field allowlist (SQL injection prevention)
# ---------------------------------------------------------------------------

class TestSyncLogAllowlist:
    """_update_sync_log must validate field names against allowlist."""

    def test_allowlist_includes_status(self):
        from app.services.fhir_service import _SYNC_LOG_FIELDS
        assert "status" in _SYNC_LOG_FIELDS

    def test_allowlist_includes_message(self):
        from app.services.fhir_service import _SYNC_LOG_FIELDS
        assert "message" in _SYNC_LOG_FIELDS

    def test_allowlist_includes_patients_synced(self):
        from app.services.fhir_service import _SYNC_LOG_FIELDS
        assert "patients_synced" in _SYNC_LOG_FIELDS

    def test_rejects_unknown_field(self):
        from app.services.fhir_service import _update_sync_log
        with pytest.raises(ValueError, match="disallowed field"):
            _update_sync_log(1, evil_field="drop table")

    def test_rejects_sql_injection_attempt(self):
        from app.services.fhir_service import _update_sync_log
        with pytest.raises(ValueError, match="disallowed field"):
            _update_sync_log(1, **{"status=1; DROP TABLE users; --": "x"})


# ---------------------------------------------------------------------------
# 8. Audit router has auth guard
# ---------------------------------------------------------------------------

class TestAuditRouterAuth:
    """Audit endpoints must require authentication."""

    def test_audit_router_has_auth(self):
        source = _read_file_source("routers/audit.py")
        assert "get_current_user" in source

    def test_audit_router_has_permission_check(self):
        source = _read_file_source("routers/audit.py")
        assert "require_permission" in source
