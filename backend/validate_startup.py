"""
RAF Intelligence — full startup validation script.

Checks that:
  1. All required packages are installed.
  2. All core modules, routers, and services import cleanly.
  3. The FastAPI application object loads without errors.

Exit code: 0 = all checks passed, 1 = one or more failures.

Run from the backend/ directory:
    python validate_startup.py
"""
from __future__ import annotations

import sys
import time

# Ensure the backend/ directory (cwd) is on sys.path so app.* imports resolve.
sys.path.insert(0, ".")

errors: list[str] = []
warnings: list[str] = []

SEPARATOR = "=" * 60


# ---------------------------------------------------------------------------
# 1. Required packages
# ---------------------------------------------------------------------------

print(f"\n{SEPARATOR}")
print("STEP 1 — Checking installed packages")
print(SEPARATOR)

import importlib.metadata as _meta  # noqa: E402 (after sys.path tweak)

required_packages = [
    "fastapi",
    "uvicorn",
    "mysql-connector-python",
    "google-genai",
    "python-dotenv",
    "simple-icd-10-cm",
    "pydantic",
    "httpx",
    "celery",
    "redis",
    "reportlab",
    "hccinfhir",
    "requests",
    "passlib",
    "PyJWT",
    "pyotp",
    "qrcode",
    "slowapi",
    "cryptography",
    "gunicorn",
]

for pkg in required_packages:
    try:
        _meta.version(pkg)
        print(f"  [ok] package: {pkg}")
    except _meta.PackageNotFoundError:
        msg = f"  [FAIL] package missing: {pkg}"
        print(msg)
        errors.append(msg)


# ---------------------------------------------------------------------------
# 2. Core module imports
# ---------------------------------------------------------------------------

print(f"\n{SEPARATOR}")
print("STEP 2 — Checking core module imports")
print(SEPARATOR)

# app.config
try:
    from app.config import settings  # noqa: F401
    print("  [ok] app.config (settings)")
except Exception as exc:
    msg = f"  [FAIL] app.config: {exc}"
    print(msg)
    errors.append(msg)

# Production secret-hygiene preflight.  In dev this just no-ops; in production
# it raises if JWT/encryption secrets are missing or weak, and returns a list
# of non-fatal warnings (e.g. DB_SSL_ENABLED=false, DB user == 'root').
try:
    from app.config import _validate_production, settings as _s  # type: ignore
    if _s.app_env == "production":
        prod_warnings = _validate_production(_s)
        if prod_warnings:
            for w in prod_warnings:
                msg = f"  [warn] prod secret hygiene: {w}"
                print(msg)
                warnings.append(msg)
        else:
            print("  [ok] prod secret hygiene (no warnings)")
    else:
        print(f"  [ok] prod secret hygiene SKIPPED (APP_ENV={_s.app_env})")
except RuntimeError as exc:
    # Fatal prod-only misconfigurations.
    msg = f"  [FAIL] prod secret hygiene: {exc}"
    print(msg)
    errors.append(msg)
except Exception as exc:
    msg = f"  [FAIL] prod secret hygiene preflight: {exc}"
    print(msg)
    errors.append(msg)

# app.db
try:
    from app.db import check_connections  # noqa: F401
    print("  [ok] app.db (check_connections)")
except Exception as exc:
    msg = f"  [FAIL] app.db: {exc}"
    print(msg)
    errors.append(msg)

# app.auth
try:
    from app.auth import (  # noqa: F401
        get_current_user,
        get_tenant_id,
        optional_auth,
        require_permission,
        require_role,
    )
    print("  [ok] app.auth (get_current_user, require_permission, require_role, get_tenant_id, optional_auth)")
except Exception as exc:
    msg = f"  [FAIL] app.auth: {exc}"
    print(msg)
    errors.append(msg)

# app.rate_limit
try:
    from app.rate_limit import limiter  # noqa: F401
    print("  [ok] app.rate_limit (limiter)")
except Exception as exc:
    msg = f"  [FAIL] app.rate_limit: {exc}"
    print(msg)
    errors.append(msg)


# ---------------------------------------------------------------------------
# 3. Router imports
# ---------------------------------------------------------------------------

print(f"\n{SEPARATOR}")
print("STEP 3 — Checking router imports")
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
    try:
        mod = __import__(f"app.routers.{r}", fromlist=["router"])
        if not hasattr(mod, "router"):
            raise AttributeError(f"module app.routers.{r} has no 'router' attribute")
        print(f"  [ok] router: {r}")
    except Exception as exc:
        msg = f"  [FAIL] router {r}: {exc}"
        print(msg)
        errors.append(msg)


# ---------------------------------------------------------------------------
# 4. Service imports
# ---------------------------------------------------------------------------

print(f"\n{SEPARATOR}")
print("STEP 4 — Checking service imports")
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
    try:
        __import__(f"app.services.{s}")
        print(f"  [ok] service: {s}")
    except Exception as exc:
        msg = f"  [FAIL] service {s}: {exc}"
        print(msg)
        errors.append(msg)


# ---------------------------------------------------------------------------
# 5. FastAPI application load
# ---------------------------------------------------------------------------

print(f"\n{SEPARATOR}")
print("STEP 5 — Loading FastAPI application")
print(SEPARATOR)

try:
    t0 = time.perf_counter()
    from app.main import app  # noqa: F401
    elapsed = (time.perf_counter() - t0) * 1000

    route_count = len(app.routes)
    print(f"  [ok] FastAPI app loaded in {elapsed:.1f} ms")
    print(f"       Routes registered: {route_count}")
    print(f"       Title:   {app.title}")
    print(f"       Version: {app.version}")
except Exception as exc:
    msg = f"  [FAIL] FastAPI app failed to load: {exc}"
    print(msg)
    errors.append(msg)


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

print(f"\n{SEPARATOR}")

if errors:
    print(f"RESULT: FAILED — {len(errors)} error(s) found\n")
    for err in errors:
        print(err)
    print(SEPARATOR)
    sys.exit(1)
else:
    print("RESULT: ALL CHECKS PASSED")
    print(f"  Packages checked : {len(required_packages)}")
    print(f"  Routers verified : {len(routers)}")
    print(f"  Services verified: {len(services)}")
    if warnings:
        print(f"  Warnings         : {len(warnings)} (non-fatal — review above)")
    print(SEPARATOR)
    sys.exit(0)
