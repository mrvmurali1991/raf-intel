"""
Full Integration Test for RAF Intelligence System.

Tests all components against the running backend at http://localhost:8500
"""
import json
import sys
import time

import requests

BASE = "http://localhost:8500"


def test(name: str, method: str, url: str, expected_status: int = 200, body=None):
    """Run a single HTTP test and report its result.

    Returns:
        Tuple of (passed: bool, response | None).
    """
    try:
        if method == "GET":
            r = requests.get(f"{BASE}{url}", timeout=30)
        else:
            r = requests.post(f"{BASE}{url}", json=body, timeout=60)

        passed = r.status_code == expected_status
        status_label = "PASS" if passed else f"FAIL (got {r.status_code})"
        print(f"  {'[OK]' if passed else '[!!]'} {status_label} | {method} {url}")
        if not passed:
            print(f"         Response: {r.text[:200]}")
        return passed, r
    except Exception as exc:
        print(f"  [!!] ERROR | {method} {url}: {exc}")
        return False, None


def run_all_tests() -> bool:
    passed = 0
    failed = 0
    total = 0

    print("=" * 60)
    print("RAF Intelligence System - Integration Test")
    print("=" * 60)

    # ------------------------------------------------------------------
    # 1. Health check
    # ------------------------------------------------------------------
    print("\n[1] Health Check")
    ok, r = test("health", "GET", "/health")
    total += 1
    passed += ok
    failed += not ok

    # ------------------------------------------------------------------
    # 2. Patients
    # ------------------------------------------------------------------
    print("\n[2] Patient APIs")
    ok, r = test("list patients", "GET", "/api/patients")
    total += 1
    passed += ok
    failed += not ok
    if ok and r is not None:
        data = r.json()
        patient_count = data.get("total", len(data.get("patients", [])))
        print(f"         Found {patient_count} patients")

    ok, r = test("get patient 4", "GET", "/api/patients/4")
    total += 1
    passed += ok
    failed += not ok

    ok, r = test("patient encounters", "GET", "/api/patients/4/encounters")
    total += 1
    passed += ok
    failed += not ok

    ok, r = test("patient diagnoses", "GET", "/api/patients/4/diagnoses")
    total += 1
    passed += ok
    failed += not ok

    ok, r = test("patient medications", "GET", "/api/patients/4/medications")
    total += 1
    passed += ok
    failed += not ok

    # ------------------------------------------------------------------
    # 3. RAF Calculation
    # ------------------------------------------------------------------
    print("\n[3] RAF Calculation")
    ok, r = test("calculate RAF pid=4", "POST", "/api/raf/calculate/4")
    total += 1
    passed += ok
    failed += not ok
    if ok and r is not None:
        data = r.json()
        print(f"         RAF Score: {data.get('raf_score', 'N/A')}")
        print(f"         HCCs: {data.get('raw_hcc_list', [])}")
        print(f"         Coefficients: {data.get('all_coefficients', {})}")

    ok, r = test("get RAF breakdown", "GET", "/api/raf/scores/4/breakdown")
    total += 1
    passed += ok
    failed += not ok

    # ------------------------------------------------------------------
    # 4. Batch RAF
    # ------------------------------------------------------------------
    print("\n[4] Batch RAF")
    for pid in [5, 6, 8, 10, 15]:
        ok, r = test(f"RAF pid={pid}", "POST", f"/api/raf/calculate/{pid}")
        total += 1
        passed += ok
        failed += not ok
        if ok and r is not None:
            data = r.json()
            raf = data.get("raf_score", 0) or 0
            print(
                f"         PID {pid}: RAF={float(raf):.3f}"
                f"  HCCs={data.get('raw_hcc_list', [])}"
            )

    # ------------------------------------------------------------------
    # 5. Suspects
    # ------------------------------------------------------------------
    print("\n[5] Suspect Conditions")
    ok, r = test("list all suspects", "GET", "/api/suspects")
    total += 1
    passed += ok
    failed += not ok

    ok, r = test("suspects for pid=4", "GET", "/api/suspects/4")
    total += 1
    passed += ok
    failed += not ok

    # ------------------------------------------------------------------
    # 6. Audit
    # ------------------------------------------------------------------
    print("\n[6] Audit Packages")
    ok, r = test("list audit packages", "GET", "/api/audit/packages")
    total += 1
    passed += ok
    failed += not ok

    ok, r = test("generate audit pid=4", "POST", "/api/audit/generate/4")
    total += 1
    passed += ok
    failed += not ok
    if ok and r is not None:
        print(f"         Audit generated: {r.json()}")

    # ------------------------------------------------------------------
    # 7. AI Analysis (may fail if Gemini key is invalid — acceptable)
    # ------------------------------------------------------------------
    print("\n[7] AI Analysis (requires valid Gemini key)")
    ok, r = test("analyze encounter", "POST", "/api/analysis/encounter/6")
    total += 1
    passed += ok
    failed += not ok
    if ok and r is not None:
        data = r.json()
        print(f"         Diagnoses found: {len(data.get('diagnoses', []))}")
        print(f"         Routing: {data.get('routing', 'N/A')}")

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print("\n" + "=" * 60)
    print(f"RESULTS: {passed}/{total} passed, {failed} failed")
    print("=" * 60)

    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
