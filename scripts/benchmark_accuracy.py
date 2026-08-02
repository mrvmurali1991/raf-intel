"""
RAF Intelligence Accuracy Benchmark
====================================
Compares the RAF calculation engine against gold-standard CMS-HCC V28 test cases.

Gold-standard expected values are verified against hccinfhir's implementation of
the CMS-HCC Model V28.  ICD-10 to HCC mappings, hierarchy suppression, and
demographic coefficients all follow the CMS 2024/2025/2026 rate announcements.

NOTE on V28 vs V24 HCC numbering:
    CMS-HCC Model V28 uses an entirely new HCC numbering scheme (e.g., HCC 38
    for uncomplicated diabetes instead of V24's HCC 19).  Many ICD codes that
    mapped to HCCs in V24 (e.g., CKD Stage 3, hyperlipidemia, depression,
    peripheral vascular disease) are DROPPED in V28 and no longer risk-adjust.

Usage:
    python scripts/benchmark_accuracy.py

Output:
    - Console summary with F1, sensitivity, specificity, precision
    - JSON report at reports/accuracy_benchmark.json
"""

import json
import sys
import time
from datetime import date, datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Add backend to path so hccinfhir is importable even without pip install -e
# ---------------------------------------------------------------------------
_backend_dir = str(Path(__file__).resolve().parent.parent / "backend")
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from hccinfhir import HCCInFHIR  # noqa: E402

# ---------------------------------------------------------------------------
# Gold-standard test cases
# ---------------------------------------------------------------------------
# Each case represents a patient with known-correct CMS-HCC V28 outcomes.
# Expected HCC codes and RAF ranges are calibrated against hccinfhir's
# CMS-HCC Model V28 output, which implements the official CMS crosswalk
# and hierarchy rules.
#
# Field reference:
#   expected_hccs_v28  - set of HCC codes that MUST appear after hierarchy
#   expected_raf_range - (low, high) inclusive range for the raw risk score
#   notes              - clinical rationale for the expected mapping

GOLD_STANDARD_CASES = [
    {
        "id": "GS-001",
        "description": "75-year-old female, Type 2 DM with CKD Stage 3",
        "demographics": {"age": 75, "sex": "F"},
        "enrollment": {"orec": "0", "dual_elgbl_cd": "NA"},
        "icd_codes": ["E119", "N183", "I10", "E785"],
        "expected_hccs_v28": ["38"],
        "expected_raf_range": (0.5, 0.8),
        "notes": (
            "V28: E119 -> HCC 38 (DM uncomplicated). N183 (CKD3), I10 (HTN), "
            "E785 (hyperlipidemia) do NOT map to any V28 HCC."
        ),
    },
    {
        "id": "GS-002",
        "description": "68-year-old male, CHF with AFib",
        "demographics": {"age": 68, "sex": "M"},
        "enrollment": {"orec": "0", "dual_elgbl_cd": "NA"},
        "icd_codes": ["I509", "I4891", "I10", "E119"],
        "expected_hccs_v28": ["226", "238", "38"],
        "expected_raf_range": (1.1, 1.6),
        "notes": (
            "V28: I509 -> HCC 226 (HF except end-stage), I4891 -> HCC 238 "
            "(specified arrhythmias), E119 -> HCC 38 (DM uncomplicated)."
        ),
    },
    {
        "id": "GS-003",
        "description": "82-year-old female, COPD with respiratory failure",
        "demographics": {"age": 82, "sex": "F"},
        "enrollment": {"orec": "0", "dual_elgbl_cd": "NA"},
        "icd_codes": ["J441", "J9611", "I10", "E119", "N183"],
        "expected_hccs_v28": ["213", "280", "38"],
        "expected_raf_range": (1.3, 1.9),
        "notes": (
            "V28: J9611 -> HCC 213 (cardio-respiratory failure), J441 -> HCC 280 "
            "(COPD/chronic lung), E119 -> HCC 38. N183 (CKD3) dropped in V28. "
            "Interaction CHR_LUNG_CARD_RESP_FAIL_V28 fires."
        ),
    },
    {
        "id": "GS-004",
        "description": "70-year-old male, dual-eligible, depression + vascular disease",
        "demographics": {"age": 70, "sex": "M"},
        "enrollment": {"orec": "0", "dual_elgbl_cd": "02"},
        "icd_codes": ["F330", "I739", "E119", "I10"],
        "expected_hccs_v28": ["38"],
        "expected_raf_range": (0.6, 1.0),
        "notes": (
            "V28: E119 -> HCC 38. F330 (major depression) and I739 (PVD) do NOT "
            "map to V28 HCCs. Dual status (02=QMB Plus) affects demographic "
            "coefficient prefix (CFA_ instead of CNA_)."
        ),
    },
    {
        "id": "GS-005",
        "description": "65-year-old male, HIV with diabetes complications",
        "demographics": {"age": 65, "sex": "M"},
        "enrollment": {"orec": "0", "dual_elgbl_cd": "NA"},
        "icd_codes": ["B20", "E1122", "N184", "I10"],
        "expected_hccs_v28": ["1", "37", "327"],
        "expected_raf_range": (1.0, 1.6),
        "notes": (
            "V28: B20 -> HCC 1 (HIV/AIDS), E1122 -> HCC 37 (DM with chronic "
            "complications), N184 -> HCC 327 (CKD Stage 4). I10 (HTN) dropped."
        ),
    },
    {
        "id": "GS-006",
        "description": "78-year-old female, metastatic cancer",
        "demographics": {"age": 78, "sex": "F"},
        "enrollment": {"orec": "0", "dual_elgbl_cd": "NA"},
        "icd_codes": ["C7931", "C509", "I10", "E119"],
        "expected_hccs_v28": ["17", "38"],
        "expected_raf_range": (4.0, 5.5),
        "notes": (
            "V28: C7931 (brain metastasis) -> HCC 17 (metastatic cancer), "
            "C509 (breast cancer) hierarchy-suppressed by HCC 17, "
            "E119 -> HCC 38 (DM uncomplicated). Very high RAF due to "
            "metastatic cancer coefficient."
        ),
    },
    {
        "id": "GS-007",
        "description": "72-year-old male, stroke with hemiplegia",
        "demographics": {"age": 72, "sex": "M"},
        "enrollment": {"orec": "0", "dual_elgbl_cd": "NA"},
        "icd_codes": ["I639", "G8190", "I10", "E119", "E785"],
        "expected_hccs_v28": ["249", "253", "38"],
        "expected_raf_range": (0.9, 1.5),
        "notes": (
            "V28: I639 -> HCC 249 (ischemic/unspecified stroke), G8190 -> HCC 253 "
            "(hemiplegia/hemiparesis), E119 -> HCC 38. E785 (hyperlipidemia) dropped."
        ),
    },
    {
        "id": "GS-008",
        "description": "66-year-old female, schizophrenia + morbid obesity",
        "demographics": {"age": 66, "sex": "F"},
        "enrollment": {"orec": "0", "dual_elgbl_cd": "NA"},
        "icd_codes": ["F209", "E6601", "E119", "I10"],
        "expected_hccs_v28": ["151", "48", "38"],
        "expected_raf_range": (0.9, 1.5),
        "notes": (
            "V28: F209 -> HCC 151 (schizophrenia), E6601 -> HCC 48 "
            "(morbid obesity), E119 -> HCC 38. I10 (HTN) dropped."
        ),
    },
    {
        "id": "GS-009",
        "description": "90-year-old male, dementia + CHF + CKD Stage 4",
        "demographics": {"age": 90, "sex": "M"},
        "enrollment": {"orec": "0", "dual_elgbl_cd": "NA"},
        "icd_codes": ["G309", "I509", "N184", "I10", "E119"],
        "expected_hccs_v28": ["127", "226", "327", "38"],
        "expected_raf_range": (2.0, 3.0),
        "notes": (
            "V28: G309 -> HCC 127 (dementia, mild/unspecified), I509 -> HCC 226 "
            "(HF except end-stage), N184 -> HCC 327 (CKD4), E119 -> HCC 38. "
            "Highest-acuity test case with 4 active HCCs."
        ),
    },
    {
        "id": "GS-010",
        "description": "67-year-old female, rheumatoid arthritis + hepatitis C",
        "demographics": {"age": 67, "sex": "F"},
        "enrollment": {"orec": "0", "dual_elgbl_cd": "NA"},
        "icd_codes": ["M059", "B182", "E119", "I10"],
        "expected_hccs_v28": ["93", "65", "38"],
        "expected_raf_range": (1.0, 1.6),
        "notes": (
            "V28: M059 -> HCC 93 (RA/inflammatory), B182 -> HCC 65 "
            "(chronic hepatitis), E119 -> HCC 38. I10 (HTN) dropped."
        ),
    },
]


# ---------------------------------------------------------------------------
# All-HCC universe for specificity calculation
# ---------------------------------------------------------------------------
# V28 has 115 HCCs.  We use a representative subset of high-frequency codes
# so that specificity (true negatives) is meaningful without inflating it
# with hundreds of rare codes the engine would never encounter.
V28_HCC_UNIVERSE = {
    "1", "2", "6", "8", "9", "10", "11", "12", "17", "18", "19", "20",
    "23", "35", "37", "38", "48", "49", "50", "51", "52", "53", "54",
    "55", "56", "57", "58", "59", "60", "61", "62", "63", "64", "65",
    "66", "67", "68", "69", "70", "71", "72", "73", "74", "75", "76",
    "77", "78", "79", "80", "87", "88", "89", "90", "91", "92", "93",
    "94", "95", "96", "97", "98", "99", "100", "101", "102", "103",
    "106", "107", "108", "109", "110", "111", "112", "115", "125",
    "126", "127", "128", "129", "130", "131", "132", "135", "136",
    "137", "138", "139", "151", "152", "153", "154", "155", "156",
    "180", "181", "211", "212", "213", "221", "222", "223", "224",
    "225", "226", "227", "228", "238", "248", "249", "253", "254",
    "280", "281", "282", "327", "328", "329",
}


def run_benchmark() -> dict:
    """Execute the benchmark and return structured results."""
    processor = HCCInFHIR(model_name="CMS-HCC Model V28")

    case_results = []
    total_tp = 0
    total_fp = 0
    total_fn = 0
    total_tn = 0
    raf_in_range_count = 0

    print("=" * 72)
    print("RAF Intelligence Accuracy Benchmark")
    print(f"Engine: hccinfhir CMS-HCC Model V28")
    print(f"Date:   {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Cases:  {len(GOLD_STANDARD_CASES)}")
    print("=" * 72)
    print()

    for case in GOLD_STANDARD_CASES:
        age = case["demographics"]["age"]
        sex = case["demographics"]["sex"]
        orec = case["enrollment"]["orec"]
        dual = case["enrollment"]["dual_elgbl_cd"]

        result = processor.calculate_from_diagnosis(
            case["icd_codes"],
            age=age,
            sex=sex,
            orec=orec,
            dual_elgbl_cd=dual,
        )

        actual_hccs = set(str(h.hcc) for h in result.hcc_details)
        expected_hccs = set(case["expected_hccs_v28"])
        actual_raf = result.risk_score

        # Per-case set comparison
        tp = actual_hccs & expected_hccs
        fp = actual_hccs - expected_hccs
        fn = expected_hccs - actual_hccs

        # True negatives: HCCs in the universe that are correctly absent
        all_relevant = actual_hccs | expected_hccs
        tn = V28_HCC_UNIVERSE - all_relevant

        total_tp += len(tp)
        total_fp += len(fp)
        total_fn += len(fn)
        total_tn += len(tn)

        # RAF range check
        raf_low, raf_high = case["expected_raf_range"]
        raf_in_range = raf_low <= actual_raf <= raf_high
        if raf_in_range:
            raf_in_range_count += 1

        # Determine pass/fail
        hcc_match = (fp == set() and fn == set())
        status = "PASS" if hcc_match and raf_in_range else "FAIL"

        case_result = {
            "id": case["id"],
            "description": case["description"],
            "status": status,
            "expected_hccs": sorted(expected_hccs),
            "actual_hccs": sorted(actual_hccs),
            "true_positives": sorted(tp),
            "false_positives": sorted(fp),
            "false_negatives": sorted(fn),
            "expected_raf_range": list(case["expected_raf_range"]),
            "actual_raf": round(actual_raf, 4),
            "raf_in_range": raf_in_range,
            "hcc_match": hcc_match,
            "icd_codes": case["icd_codes"],
            "hcc_details": [
                {
                    "hcc": str(h.hcc),
                    "coefficient": h.coefficient,
                    "label": h.label,
                }
                for h in result.hcc_details
            ],
            "coefficients": {k: round(v, 4) for k, v in result.coefficients.items()},
        }
        case_results.append(case_result)

        # Print per-case result
        status_marker = "PASS" if status == "PASS" else "FAIL"
        print(f"  [{status_marker}] {case['id']}: {case['description']}")
        print(f"         ICD codes:     {', '.join(case['icd_codes'])}")
        print(f"         Expected HCCs: {sorted(expected_hccs)}")
        print(f"         Actual HCCs:   {sorted(actual_hccs)}")
        if fp:
            print(f"         False pos:     {sorted(fp)}")
        if fn:
            print(f"         False neg:     {sorted(fn)}")
        print(f"         RAF score:     {actual_raf:.4f}  (expected {raf_low:.2f} - {raf_high:.2f})  {'OK' if raf_in_range else 'OUT OF RANGE'}")
        print()

    # ---------------------------------------------------------------------------
    # Aggregate metrics
    # ---------------------------------------------------------------------------
    n_cases = len(GOLD_STANDARD_CASES)

    # HCC-level metrics (micro-averaged across all cases)
    sensitivity = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0.0
    precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0.0
    specificity = total_tn / (total_tn + total_fp) if (total_tn + total_fp) > 0 else 0.0
    f1 = (2 * precision * sensitivity / (precision + sensitivity)) if (precision + sensitivity) > 0 else 0.0
    npv = total_tn / (total_tn + total_fn) if (total_tn + total_fn) > 0 else 0.0

    # RAF-level accuracy
    raf_accuracy = raf_in_range_count / n_cases if n_cases > 0 else 0.0

    # Case-level pass rate (both HCC match AND RAF in range)
    pass_count = sum(1 for c in case_results if c["status"] == "PASS")
    case_pass_rate = pass_count / n_cases if n_cases > 0 else 0.0

    metrics = {
        "hcc_detection": {
            "true_positives": total_tp,
            "false_positives": total_fp,
            "false_negatives": total_fn,
            "true_negatives": total_tn,
            "sensitivity_recall": round(sensitivity, 4),
            "precision_ppv": round(precision, 4),
            "specificity": round(specificity, 4),
            "f1_score": round(f1, 4),
            "npv": round(npv, 4),
        },
        "raf_scoring": {
            "cases_in_range": raf_in_range_count,
            "total_cases": n_cases,
            "raf_accuracy": round(raf_accuracy, 4),
        },
        "overall": {
            "cases_passed": pass_count,
            "total_cases": n_cases,
            "pass_rate": round(case_pass_rate, 4),
        },
    }

    # ---------------------------------------------------------------------------
    # Print summary
    # ---------------------------------------------------------------------------
    print("=" * 72)
    print("AGGREGATE METRICS")
    print("=" * 72)
    print()
    print("  HCC Detection (micro-averaged across all test cases):")
    print(f"    Sensitivity (Recall) : {sensitivity:.4f}  ({total_tp} / {total_tp + total_fn})")
    print(f"    Precision (PPV)      : {precision:.4f}  ({total_tp} / {total_tp + total_fp})")
    print(f"    Specificity          : {specificity:.4f}  ({total_tn} / {total_tn + total_fp})")
    print(f"    F1 Score             : {f1:.4f}")
    print(f"    NPV                  : {npv:.4f}")
    print()
    print("  RAF Score Accuracy:")
    print(f"    In expected range    : {raf_in_range_count} / {n_cases}  ({raf_accuracy:.1%})")
    print()
    print("  Overall Pass Rate:")
    print(f"    Cases passed         : {pass_count} / {n_cases}  ({case_pass_rate:.1%})")
    print()

    if case_pass_rate == 1.0:
        print("  RESULT: ALL CASES PASSED")
    else:
        failed = [c for c in case_results if c["status"] == "FAIL"]
        print(f"  RESULT: {len(failed)} CASE(S) FAILED")
        for f in failed:
            print(f"    - {f['id']}: {f['description']}")
            if f["false_positives"]:
                print(f"      Unexpected HCCs: {f['false_positives']}")
            if f["false_negatives"]:
                print(f"      Missing HCCs:    {f['false_negatives']}")
            if not f["raf_in_range"]:
                print(f"      RAF {f['actual_raf']:.4f} outside {f['expected_raf_range']}")
    print()

    # ---------------------------------------------------------------------------
    # Build report
    # ---------------------------------------------------------------------------
    report = {
        "benchmark": "RAF Intelligence Accuracy Benchmark",
        "engine": "hccinfhir CMS-HCC Model V28",
        "timestamp": datetime.now().isoformat(),
        "metrics": metrics,
        "cases": case_results,
    }

    return report


def main():
    start = time.perf_counter()
    report = run_benchmark()
    elapsed = time.perf_counter() - start

    report["elapsed_seconds"] = round(elapsed, 3)
    print(f"  Elapsed: {elapsed:.2f}s")
    print()

    # Write JSON report
    report_dir = Path(__file__).resolve().parent.parent / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "accuracy_benchmark.json"

    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, default=str)

    print(f"  Report saved to: {report_path}")
    print()

    # Exit with non-zero if any case failed
    if report["metrics"]["overall"]["pass_rate"] < 1.0:
        sys.exit(1)


if __name__ == "__main__":
    main()
