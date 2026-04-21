"""
Benchmarks Router
=================
Accuracy benchmarking endpoints for the RAF Intelligence NLP pipeline.

Routes
------
POST /api/benchmarks/run                 Run the full accuracy benchmark (admin)
GET  /api/benchmarks/results             Latest benchmark run results
GET  /api/benchmarks/results/history     Historical benchmark run summaries
GET  /api/benchmarks/test-cases          List built-in gold-standard test cases
POST /api/benchmarks/test-cases/custom   Run the pipeline against a custom test case

All endpoints require authentication.  The /run endpoint additionally requires
the "admin" role to prevent accidental high-cost pipeline runs.
"""
# Removed: from __future__ import annotations (breaks FastAPI schema generation)

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator

from app.auth import get_current_user, require_role

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/benchmarks", tags=["benchmarks"])

# Thread pool used to run the CPU/IO-bound benchmark off the event loop
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="benchmark")

# In-memory cache of the most recently triggered run (avoids a DB round-trip
# for the common pattern of POST /run → GET /results).
_last_run_result: dict[str, Any] | None = None
_last_run_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class BenchmarkRunResponse(BaseModel):
    """Summary returned immediately when a benchmark is enqueued/completed."""
    run_id: str
    run_timestamp: str
    suite_version: str
    total_cases: int
    icd10_metrics: dict[str, Any]
    hcc_metrics: dict[str, Any]
    raf_metrics: dict[str, Any]
    duration_seconds: float
    per_case_results: list[dict[str, Any]] = Field(default_factory=list)


class BenchmarkHistoryEntry(BaseModel):
    run_id: str
    run_timestamp: str
    suite_version: str
    total_cases: int
    icd10_f1: float
    hcc_f1: float
    hcc_capture_rate: float
    raf_mae: float
    raf_within_range_rate: float
    duration_seconds: float


class CustomTestCase(BaseModel):
    """A single custom test case submitted by a user."""
    note_text: str = Field(..., min_length=50, description="Clinical note text (min 50 chars)")
    expected_icd10_codes: list[str] = Field(default_factory=list)
    expected_hcc_codes: list[int] = Field(default_factory=list)
    expected_raf_score_range: list[float] = Field(
        default_factory=lambda: [0.0, 99.0],
        description="[min_raf, max_raf]",
    )
    patient_age: int | None = Field(None, ge=18, le=115)
    patient_sex: str | None = Field(None, pattern="^[MFmf]$")
    name: str | None = Field(None, max_length=120)
    category: str | None = Field(None, max_length=80)

    @field_validator("expected_raf_score_range")
    @classmethod
    def validate_range(cls, v: list[float]) -> list[float]:
        if len(v) != 2:
            raise ValueError("expected_raf_score_range must be [min, max]")
        if v[0] > v[1]:
            raise ValueError("raf_score_range min must be <= max")
        return v


class RunBenchmarkRequest(BaseModel):
    """Optional body for the /run endpoint."""
    suite: str = Field("builtin", description="'builtin' to run the 25 gold-standard cases")
    custom_cases: list[CustomTestCase] | None = None
    include_per_case_detail: bool = True


# ---------------------------------------------------------------------------
# POST /api/benchmarks/run
# ---------------------------------------------------------------------------

@router.post(
    "/run",
    summary="Run full accuracy benchmark",
    response_model=BenchmarkRunResponse,
    status_code=status.HTTP_200_OK,
)
def run_benchmark(
    body: RunBenchmarkRequest = RunBenchmarkRequest(),
    current_user: dict = Depends(require_role("admin")),
) -> dict[str, Any]:
    """
    Run the NLP pipeline against the built-in gold-standard test cases and return
    precision/recall/F1 metrics for ICD-10, HCC, and RAF score accuracy.

    Requires admin role.  This endpoint is synchronous — it blocks until all
    pipeline calls complete (typically 2-8 seconds per case depending on Gemini
    latency).  For production monitoring, trigger this from a scheduled task
    rather than user-facing UI.

    Responses include per-case detail by default.  Set ``include_per_case_detail``
    to ``false`` for a compact summary response.
    """
    global _last_run_result

    from app.services.benchmark_service import (
        GOLD_STANDARD_TEST_CASES,
        run_accuracy_benchmark,
    )

    # Build the test case list
    if body.suite == "builtin":
        test_cases = GOLD_STANDARD_TEST_CASES
    elif body.custom_cases:
        test_cases = [
            {
                "id":                       f"CUSTOM-{i + 1:03d}",
                "name":                     c.name or f"Custom case {i + 1}",
                "category":                 c.category or "Custom",
                "note_text":                c.note_text,
                "expected_icd10_codes":     c.expected_icd10_codes,
                "expected_hcc_codes":       c.expected_hcc_codes,
                "expected_raf_score_range": c.expected_raf_score_range,
            }
            for i, c in enumerate(body.custom_cases)
        ]
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide suite='builtin' or a non-empty custom_cases list.",
        )

    logger.info(
        "[BenchmarkRouter] User %s triggered benchmark run (%d cases)",
        current_user.get("username"),
        len(test_cases),
    )

    result = run_accuracy_benchmark(test_cases)
    with _last_run_lock:
        _last_run_result = result

    if not body.include_per_case_detail:
        result = {k: v for k, v in result.items() if k != "per_case_results"}
        result["per_case_results"] = []

    return result


# ---------------------------------------------------------------------------
# GET /api/benchmarks/results
# ---------------------------------------------------------------------------

@router.get(
    "/results",
    summary="Latest benchmark results",
    response_model=BenchmarkRunResponse,
)
def get_latest_results(
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Return the most recent benchmark run result.

    Checks the in-memory cache first (populated by ``POST /run`` in the same
    process), then falls back to the database.  Returns HTTP 404 when no runs
    have been recorded yet.
    """
    with _last_run_lock:
        cached = _last_run_result
    if cached:
        return cached

    from app.services.benchmark_service import get_latest_benchmark_result
    result = get_latest_benchmark_result()

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "No benchmark results found. "
                "Run POST /api/benchmarks/run to generate the first result."
            ),
        )

    return result


# ---------------------------------------------------------------------------
# GET /api/benchmarks/results/history
# ---------------------------------------------------------------------------

@router.get(
    "/results/history",
    summary="Historical benchmark run summaries",
)
def get_benchmark_history(
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Return summary rows for recent benchmark runs in reverse chronological order.

    Per-case detail is omitted from history entries to keep response sizes small.
    Fetch ``GET /api/benchmarks/results`` for the full latest result.
    """
    from app.services.benchmark_service import get_benchmark_history

    history = get_benchmark_history(limit=limit)
    return {
        "count": len(history),
        "runs":  history,
    }


# ---------------------------------------------------------------------------
# GET /api/benchmarks/test-cases
# ---------------------------------------------------------------------------

@router.get(
    "/test-cases",
    summary="List built-in gold-standard test cases",
)
def list_test_cases(
    category: str | None = Query(None, description="Filter by category"),
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Return metadata for all 25 built-in gold-standard test cases.

    Note text is truncated to 300 characters for readability.  Use
    ``POST /api/benchmarks/run`` to execute the full pipeline against these cases.
    """
    from app.services.benchmark_service import get_test_cases

    cases = get_test_cases()

    if category:
        cases = [c for c in cases if (c.get("category") or "").lower() == category.lower()]

    # Collect unique categories for discovery
    categories = sorted({c.get("category") or "" for c in get_test_cases()})

    return {
        "total": len(cases),
        "categories": categories,
        "cases": cases,
    }


# ---------------------------------------------------------------------------
# POST /api/benchmarks/test-cases/custom
# ---------------------------------------------------------------------------

@router.post(
    "/test-cases/custom",
    summary="Run pipeline against a custom test case",
    status_code=status.HTTP_200_OK,
)
def run_custom_test_case(
    body: CustomTestCase,
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Run the NLP pipeline against a single custom test case and return accuracy
    metrics compared to the provided expected values.

    Useful for iterative testing of specific clinical scenarios during
    development or validation.  Does not persist the result to benchmark history.
    """
    from app.services.benchmark_service import run_accuracy_benchmark

    test_case = {
        "id":                       "CUSTOM-ADHOC",
        "name":                     body.name or "Ad-hoc custom case",
        "category":                 body.category or "Custom",
        "note_text":                body.note_text,
        "expected_icd10_codes":     body.expected_icd10_codes,
        "expected_hcc_codes":       body.expected_hcc_codes,
        "expected_raf_score_range": body.expected_raf_score_range,
    }

    result = run_accuracy_benchmark([test_case])

    # Return the single case result enriched with the full pipeline output
    case_result = result["per_case_results"][0] if result["per_case_results"] else {}
    return {
        "case_id":       "CUSTOM-ADHOC",
        "name":          body.name or "Ad-hoc custom case",
        "icd10_metrics": result["icd10_metrics"],
        "hcc_metrics":   result["hcc_metrics"],
        "raf_metrics":   result["raf_metrics"],
        "case_detail":   case_result,
        "run_id":        result["run_id"],
        "duration_seconds": result["duration_seconds"],
    }
