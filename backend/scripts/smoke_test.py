#!/usr/bin/env python3
"""Backend smoke test - tests every documented endpoint for 200+non-empty data."""

import json
import subprocess
import sys
import datetime

BASE_URL = "http://localhost:8500"
TOKEN = None

def login():
    """Login and get JWT token."""
    result = subprocess.run(
        ["/usr/bin/curl", "-s", "-X", "POST", f"{BASE_URL}/api/auth/login",
         "-H", "Content-Type: application/json",
         "-d", '{"email":"admin@raf.health","password":"Admin@123"}'],
        capture_output=True, text=True, timeout=30
    )
    data = json.loads(result.stdout)
    return data["access_token"]


def hit(path, token, method="GET", body=None):
    """Hit an endpoint and return (status_code, body_dict_or_str)."""
    headers = ["-H", f"Authorization: Bearer {token}"]
    cmd = ["/usr/bin/curl", "-s", "-w", "\nHTTPSTATUS:%{http_code}", *headers]
    if method == "POST":
        cmd += ["-X", "POST", "-H", "Content-Type: application/json"]
        if body:
            cmd += ["-d", json.dumps(body)]
    cmd.append(f"{BASE_URL}{path}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    raw = result.stdout
    if "HTTPSTATUS:" in raw:
        parts = raw.rsplit("HTTPSTATUS:", 1)
        body_raw = parts[0].strip()
        code = int(parts[1].strip())
    else:
        body_raw = raw.strip()
        code = 0
    try:
        parsed = json.loads(body_raw)
    except Exception:
        parsed = body_raw
    return code, parsed


# Endpoints that may legitimately return empty data (newly created tables,
# or data-conditional responses like "no items closing soon")
ACCEPTABLE_EMPTY = {
    "/api/v1/dashboard/top-opportunities",  # no gaps with closing deadline in 14d
    "/api/v1/goals",                         # raf_goals table newly created, no seed data
}


def is_meaningful(data):
    """Check if response has meaningful non-empty data."""
    if data is None:
        return False
    if isinstance(data, (list,)):
        return len(data) > 0
    if isinstance(data, dict):
        if not data:
            return False
        # Check if it's all-None or all-zero
        vals = list(data.values())
        if all(v is None or v == 0 or v == [] or v == {} for v in vals):
            return "warn_zeros"
        return True
    if isinstance(data, str) and len(data) == 0:
        return False
    return True


def excerpt(data, max_len=150):
    """Return short excerpt of response."""
    s = json.dumps(data) if not isinstance(data, str) else data
    return s[:max_len] + ("..." if len(s) > max_len else "")


def main():
    global TOKEN
    print("Logging in as admin@raf.health...")
    TOKEN = login()
    print(f"Got JWT: {TOKEN[:40]}...\n")

    endpoints = [
        # Dashboard
        ("dashboard_stats", "/api/v1/dashboard/stats"),
        ("dashboard_kpi_trends", "/api/v1/dashboard/kpi-trends"),
        ("dashboard_top_opportunities", "/api/v1/dashboard/top-opportunities"),
        # Patients
        ("patients_list", "/api/v1/patients?limit=10"),
        # Worklist (provider/{id} requires path param; use /6 for seeded provider)
        ("worklist_provider", "/api/v1/worklist/provider/6"),
        ("worklist_summary", "/api/v1/worklist/summary"),
        ("worklist_provider_workload", "/api/v1/worklist/provider-workload"),
        # Suspects (no /dashboard endpoint — route is /suspects/{pid}; use seeded pid=22)
        ("suspects_list", "/api/v1/suspects"),
        ("suspects_by_patient", "/api/v1/suspects/22"),
        # Recapture
        ("recapture_gaps", "/api/v1/recapture/gaps"),
        ("reports_recapture_gaps", "/api/reports/recapture-gaps"),
        # Reports
        ("reports_revenue_opportunity", "/api/reports/revenue-opportunity"),
        ("reports_patient_scorecard", "/api/reports/patient-scorecard"),
        ("reports_hcc_distribution", "/api/reports/hcc-distribution"),
        # V28 Impact
        ("v28_impact_portfolio", "/api/v1/v28-impact/portfolio"),
        # RADV
        ("radv_audit_runs_legacy", "/api/radv/audit-runs"),
        ("radv_audit_runs_v1", "/api/v1/radv/audit-runs"),
        # Goals
        ("goals", "/api/v1/goals"),
        # HCC Rejections
        ("hcc_rejections", "/api/v1/hcc-rejections"),
        # Audit
        ("audit_chain_status", "/api/audit/chain/status"),
        ("audit_verify", "/api/audit/verify"),
        # Auth
        ("auth_me", "/api/v1/auth/me"),
        ("auth_tenants", "/api/auth/tenants"),
    ]

    results = []
    pass_count = 0
    fail_count = 0

    for name, path in endpoints:
        try:
            code, data = hit(path, TOKEN)
        except Exception as e:
            code, data = 0, f"REQUEST_ERROR: {e}"

        meaningful = is_meaningful(data)

        if code == 200 and meaningful is True:
            category = "PASS"
            pass_count += 1
        elif code == 200 and meaningful == "warn_zeros" and path in ACCEPTABLE_EMPTY:
            category = "PASS_EXPECTED_EMPTY"
            pass_count += 1
        elif code == 200 and not meaningful and path in ACCEPTABLE_EMPTY:
            category = "PASS_EXPECTED_EMPTY"
            pass_count += 1
        elif code == 200 and meaningful == "warn_zeros":
            category = "WARN_ZEROS"
            fail_count += 1
        elif code == 200 and not meaningful:
            category = "EMPTY_DATA"
            fail_count += 1
        elif code in (401, 403):
            category = "AUTH_FAIL"
            fail_count += 1
        elif code == 404:
            category = "NOT_FOUND"
            fail_count += 1
        elif code >= 500:
            category = "SERVER_ERROR"
            fail_count += 1
        elif code == 0:
            category = "REQUEST_ERROR"
            fail_count += 1
        else:
            category = f"HTTP_{code}"
            fail_count += 1

        entry = {
            "name": name,
            "path": path,
            "status_code": code,
            "category": category,
            "response_excerpt": excerpt(data),
        }

        if category == "SERVER_ERROR":
            # Fetch backend log tail
            log_result = subprocess.run(
                ["docker", "logs", "--tail", "30", "raf-backend"],
                capture_output=True, text=True, timeout=10
            )
            entry["log_excerpt"] = (log_result.stdout + log_result.stderr)[-1000:]

        results.append(entry)
        status_icon = "✓" if category == "PASS" else "✗"
        print(f"[{code}] {category:15s} {path}")

    print(f"\n{'='*60}")
    print(f"PASS: {pass_count} / {len(endpoints)}")
    print(f"FAIL: {fail_count} / {len(endpoints)}")
    print()

    failing = [r for r in results if r["category"] != "PASS"]
    if failing:
        print("FAILING ENDPOINTS:")
        for r in failing:
            print(f"  [{r['status_code']}] {r['category']} {r['path']}")
            print(f"       Excerpt: {r['response_excerpt'][:120]}")

    report = {
        "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
        "summary": {
            "total": len(endpoints),
            "pass": pass_count,
            "fail": fail_count,
            "pass_rate": f"{pass_count/len(endpoints)*100:.1f}%"
        },
        "results": results,
        "failing": failing
    }

    with open("/tmp/backend-smoke-report.json", "w") as f:
        json.dump(report, f, indent=2)

    print(f"\nReport saved to /tmp/backend-smoke-report.json")
    return fail_count


if __name__ == "__main__":
    fails = main()
    sys.exit(0 if fails == 0 else 1)
