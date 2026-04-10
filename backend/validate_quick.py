"""
RAF Intelligence — quick import validation script (CI/CD friendly).

Lighter than validate_startup.py: verifies that every module, router, and
service can be imported cleanly WITHOUT loading the full FastAPI application
object or triggering lifespan events (no DB connections, no network I/O).

Suitable for:
  - Pre-commit hooks
  - CI pipeline smoke tests
  - Docker build-time layer verification

Exit code: 0 = all imports resolved, 1 = one or more failures.

Run from the backend/ directory:
    python validate_quick.py
"""
from __future__ import annotations

import importlib
import sys
import time

# Ensure backend/ (cwd) is on the path.
sys.path.insert(0, ".")

errors: list[str] = []
SEPARATOR = "-" * 50
t_start = time.perf_counter()


def _check(label: str, import_path: str, required_attrs: list[str] | None = None) -> bool:
    """
    Attempt to import *import_path* and optionally assert *required_attrs* exist.

    Returns True on success, False on failure (and appends to errors).
    """
    try:
        mod = importlib.import_module(import_path)
        if required_attrs:
            for attr in required_attrs:
                if not hasattr(mod, attr):
                    raise AttributeError(f"missing attribute '{attr}'")
        print(f"  [ok] {label}")
        return True
    except Exception as exc:
        msg = f"  [FAIL] {label}: {exc}"
        print(msg)
        errors.append(msg)
        return False


# ---------------------------------------------------------------------------
# Core modules
# ---------------------------------------------------------------------------

print(f"\n{SEPARATOR}")
print("Core modules")
print(SEPARATOR)

_check("app.config", "app.config", ["settings"])
_check("app.db", "app.db", ["check_connections"])
_check(
    "app.auth",
    "app.auth",
    ["get_current_user", "require_permission", "require_role", "get_tenant_id", "optional_auth"],
)
_check("app.rate_limit", "app.rate_limit", ["limiter"])


# ---------------------------------------------------------------------------
# Routers  (each must expose a `router` attribute)
# ---------------------------------------------------------------------------

print(f"\n{SEPARATOR}")
print("Routers")
print(SEPARATOR)

routers = [
    "auth",
    "patients",
    "raf",
    "analysis",
    "suspects",
    "audit",
    "reports",
    "providers",
    "documents",
    "claims",
    "fhir",
    "submissions",
    "prospective",
    "quality",
    "webhooks",
    "jobs",
    "benchmarks",
]

for r in routers:
    _check(f"router/{r}", f"app.routers.{r}", ["router"])


# ---------------------------------------------------------------------------
# Services
# ---------------------------------------------------------------------------

print(f"\n{SEPARATOR}")
print("Services")
print(SEPARATOR)

services = [
    "auth_service",
    "raf_calculator",
    "multi_model_calculator",
    "openemr_connector",
    "pipeline_orchestrator",
    "skill_pipeline",
    "stage1_extraction",
    "stage3_verification",
    "suspect_engine",
    "lab_suspect_engine",
    "meat_evidence_service",
    "icd_validator",
    "hccinfhir_utils",
    "confidence_router",
    "review_queue",
    "audit_logger",
    "fhir_service",
    "claims_service",
    "document_service",
    "provider_service",
    "submission_service",
    "prospective_service",
    "quality_service",
    "webhook_service",
    "event_emitter",
    "job_service",
    "benchmark_service",
    "encryption_service",
]

for s in services:
    _check(f"service/{s}", f"app.services.{s}")


# ---------------------------------------------------------------------------
# Installed packages (lightweight — just verify importability, no version pin)
# ---------------------------------------------------------------------------

print(f"\n{SEPARATOR}")
print("Key third-party packages")
print(SEPARATOR)

# Maps PyPI name -> importable module name
third_party = {
    "fastapi":    "fastapi",
    "uvicorn":    "uvicorn",
    "pydantic":   "pydantic",
    "httpx":      "httpx",
    "celery":     "celery",
    "redis":      "redis",
    "reportlab":  "reportlab",
    "hccinfhir":  "hccinfhir",
    "requests":   "requests",
    "passlib":    "passlib",
    "PyJWT":      "jwt",
    "pyotp":      "pyotp",
    "slowapi":    "slowapi",
    "cryptography": "cryptography",
    "gunicorn":   "gunicorn",
}

for display_name, module_name in third_party.items():
    _check(f"pkg:{display_name}", module_name)


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

elapsed = (time.perf_counter() - t_start) * 1000

print(f"\n{SEPARATOR}")
if errors:
    print(f"RESULT: FAILED — {len(errors)} error(s) in {elapsed:.0f} ms\n")
    for err in errors:
        print(err)
    print(SEPARATOR)
    sys.exit(1)
else:
    total = 4 + len(routers) + len(services) + len(third_party)
    print(f"RESULT: ALL {total} CHECKS PASSED in {elapsed:.0f} ms")
    print(f"  Core modules : 4")
    print(f"  Routers      : {len(routers)}")
    print(f"  Services     : {len(services)}")
    print(f"  Packages     : {len(third_party)}")
    print(SEPARATOR)
    sys.exit(0)
