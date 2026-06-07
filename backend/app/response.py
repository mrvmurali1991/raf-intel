"""
Shared response-shape helpers.

All list endpoints should return a consistent paginated envelope so the
frontend has a single contract to code against.
"""
from typing import Any


def paginated_response(
    items: list[Any],
    total: int,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    """Return a standard paginated envelope.

    Args:
        items:  The page of records for this request.
        total:  Total matching rows (ignoring pagination).
        limit:  The page-size that was requested.
        offset: The row offset that was requested.

    Returns a dict with keys: items, total, limit, offset, has_more.
    """
    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": offset + limit < total,
    }
