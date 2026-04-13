from typing import Any

from fastapi import APIRouter, Depends, Query

from app.auth import get_current_user
from app.services.icd_validator import (
    get_code_description,
    normalize_code,
    search_codes,
    validate_code,
)

router = APIRouter(prefix="/api/icd10", tags=["icd10"])


@router.get("/validate/{code}", summary="Validate an ICD-10-CM code")
def validate_icd10(
    code: str,
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Check whether *code* is a valid, billable (leaf) ICD-10-CM code."""
    normalized = normalize_code(code)
    valid = validate_code(normalized)
    info = get_code_description(normalized) if valid else {}

    return {
        "code": normalized,
        "input": code,
        "valid": valid,
        "info": info,
    }


@router.get("/search", summary="Search ICD-10-CM codes")
def search_icd10(
    query: str,
    max_results: int = Query(default=20, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Full-text search across ICD-10-CM descriptions."""
    results = search_codes(query, max_results=max_results)
    return {
        "query": query,
        "count": len(results),
        "results": results,
    }
