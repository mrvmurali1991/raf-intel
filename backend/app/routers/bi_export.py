"""
BI Tools Export router
======================
Provides connectors for Tableau, PowerBI, Looker, Metabase, and generic
ODBC/API consumers.

Endpoints
---------
GET    /api/bi/datasets                     – List datasets (seeds pre-built on first call)
POST   /api/bi/datasets                     – Create custom dataset
GET    /api/bi/datasets/{id}                – Dataset detail with query template
PUT    /api/bi/datasets/{id}                – Update dataset metadata / query
POST   /api/bi/datasets/{id}/refresh        – Trigger synchronous data refresh
GET    /api/bi/datasets/{id}/download       – Download CSV / JSON / Excel file
GET    /api/bi/datasets/{id}/preview        – First 100 rows as JSON
GET    /api/bi/datasets/{id}/schema         – Column schema for BI tool import
POST   /api/bi/connections                  – Register a BI tool connection
GET    /api/bi/connections                  – List connections
POST   /api/bi/connections/{id}/push        – Push a dataset to the configured BI tool
GET    /api/bi/export-log                   – Paginated export audit history
GET    /api/bi/tableau/wdc                  – Tableau Web Data Connector HTML page
GET    /api/bi/odata/{dataset_name}         – OData v4 feed (PowerBI "Get Data → OData")

Authentication: all endpoints require a valid Bearer JWT.
"""
# Do NOT use 'from __future__ import annotations' — breaks FastAPI schema generation.

import logging
import time
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field

from app.auth import get_current_user, get_tenant_id
from app.services.bi_export_service import (
    PREBUILT_DATASETS,
    build_odata_metadata,
    build_odata_response,
    build_tableau_wdc_html,
    build_tableau_wdc_schema,
    create_connection,
    create_dataset,
    fetch_dataset_rows,
    get_connection,
    get_dataset,
    list_connections,
    list_datasets,
    list_export_log,
    log_export,
    push_to_powerbi,
    refresh_dataset,
    render_export,
    seed_prebuilt_datasets,
    update_dataset,
    _get_connection_api_key,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/bi", tags=["bi_export"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class DatasetCreateRequest(BaseModel):
    name: str = Field(..., max_length=255, description="Dataset display name")
    description: str | None = Field(default=None, description="Purpose and content summary")
    dataset_type: Literal[
        "raf_scores", "patient_demographics", "hcc_gaps",
        "provider_performance", "claims_summary", "quality_metrics",
        "financial", "custom"
    ] = Field(default="custom", description="Dataset category")
    query_template: str | None = Field(
        default=None,
        description="Parameterised SQL with :param_name placeholders",
    )
    columns_config: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Column descriptors: [{name, type, description, phi}]",
    )
    refresh_frequency: Literal["hourly", "daily", "weekly", "monthly", "on_demand"] = "on_demand"
    format: Literal["csv", "json", "parquet", "xlsx"] = "csv"


class DatasetUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    description: str | None = None
    query_template: str | None = None
    columns_config: list[dict[str, Any]] | None = None
    refresh_frequency: Literal["hourly", "daily", "weekly", "monthly", "on_demand"] | None = None
    format: Literal["csv", "json", "parquet", "xlsx"] | None = None


class ConnectionCreateRequest(BaseModel):
    name: str = Field(..., max_length=255, description="Human-readable label")
    bi_tool: Literal[
        "tableau", "powerbi", "looker", "metabase", "generic_odbc", "generic_api"
    ] = Field(..., description="Target BI platform")
    connection_config: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Non-secret configuration. "
            "Tableau: {server_url, site, project}. "
            "PowerBI: {push_url, workspace_id}. "
            "Looker: {base_url, client_id}. "
            "Generic: {endpoint, headers}."
        ),
    )
    api_key: str | None = Field(
        default=None,
        description="API key / PAT — encrypted at rest, never returned in responses",
    )
    refresh_schedule: str | None = Field(
        default=None,
        max_length=50,
        description='Cron expression for automatic push, e.g. "0 6 * * *"',
    )


class PushRequest(BaseModel):
    dataset_id: int = Field(..., description="ID of the dataset to push")
    anonymise: bool = Field(
        default=False,
        description="Strip PHI columns before pushing to the BI tool",
    )


# ---------------------------------------------------------------------------
# Helper — resolve dataset or 404
# ---------------------------------------------------------------------------

def _require_dataset(dataset_id: int, tenant_id: str) -> dict[str, Any]:
    ds = get_dataset(dataset_id, tenant_id)
    if not ds:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")
    return ds


def _require_connection(connection_id: int, tenant_id: str) -> dict[str, Any]:
    conn = get_connection(connection_id, tenant_id)
    if not conn:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connection not found")
    return conn


# ---------------------------------------------------------------------------
# Dataset endpoints
# ---------------------------------------------------------------------------

@router.get(
    "/datasets",
    summary="List available datasets",
    description=(
        "Returns all dataset definitions for the current tenant. "
        "On first call, the six pre-built analytics datasets are seeded automatically."
    ),
)
def api_list_datasets(
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> dict[str, Any]:
    # Seed pre-built datasets on first access (idempotent)
    try:
        seeded = seed_prebuilt_datasets(tenant_id)
        if seeded:
            logger.info("Seeded %d pre-built BI datasets for tenant %s", seeded, tenant_id)
    except Exception as exc:
        logger.warning("Pre-built dataset seeding failed: %s", exc)

    datasets = list_datasets(tenant_id)
    return {"count": len(datasets), "datasets": datasets}


@router.post(
    "/datasets",
    status_code=status.HTTP_201_CREATED,
    summary="Create a custom dataset",
)
def api_create_dataset(
    body: DatasetCreateRequest,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> dict[str, Any]:
    new_id = create_dataset(
        name=body.name,
        description=body.description,
        dataset_type=body.dataset_type,
        query_template=body.query_template,
        columns_config=body.columns_config,
        refresh_frequency=body.refresh_frequency,
        fmt=body.format,
        tenant_id=tenant_id,
    )
    return {"id": new_id, "message": "Dataset created"}


@router.get(
    "/datasets/{dataset_id}",
    summary="Dataset detail including query template",
)
def api_get_dataset(
    dataset_id: int,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> dict[str, Any]:
    return _require_dataset(dataset_id, tenant_id)


@router.put(
    "/datasets/{dataset_id}",
    summary="Update a dataset definition",
)
def api_update_dataset(
    dataset_id: int,
    body: DatasetUpdateRequest,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> dict[str, Any]:
    updates = body.model_dump(exclude_none=True)
    # Rename 'format' to avoid Python keyword collision in service layer
    if "format" in updates:
        updates["format"] = updates.pop("format")
    ok = update_dataset(dataset_id, updates, tenant_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found or no changes")
    return {"id": dataset_id, "message": "Dataset updated"}


@router.post(
    "/datasets/{dataset_id}/refresh",
    summary="Refresh dataset — re-execute the query and update row count",
)
def api_refresh_dataset(
    dataset_id: int,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> dict[str, Any]:
    _require_dataset(dataset_id, tenant_id)  # 404 guard
    result = refresh_dataset(dataset_id, tenant_id)
    if not result["success"]:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=result.get("error", "Refresh failed"),
        )
    return result


@router.get(
    "/datasets/{dataset_id}/download",
    summary="Download dataset as CSV, JSON, or Excel",
    description=(
        "Streams the full dataset as a file attachment. "
        "Supported formats: csv (default), json, xlsx. "
        "Set anonymise=true to strip PHI columns before export."
    ),
)
def api_download_dataset(
    dataset_id: int,
    format: Literal["csv", "json", "xlsx"] = Query(default="csv"),
    anonymise: bool = Query(default=False, description="Strip PHI columns"),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> Response:
    ds = _require_dataset(dataset_id, tenant_id)
    t0 = time.perf_counter()

    try:
        rows, columns = fetch_dataset_rows(ds, tenant_id, anonymise=anonymise)
    except Exception as exc:
        logger.error("Dataset download query failed (id=%s): %s", dataset_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Query execution failed")

    content, media_type, filename = render_export(rows, columns, format, ds.get("name", "export"))
    elapsed_ms = int((time.perf_counter() - t0) * 1000)

    log_export(
        export_type="file",
        status="success",
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        row_count=len(rows),
        file_size=len(content),
        duration_ms=elapsed_ms,
        exported_by=current_user.get("id"),
    )

    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get(
    "/datasets/{dataset_id}/preview",
    summary="Preview first 100 rows as JSON",
)
def api_preview_dataset(
    dataset_id: int,
    anonymise: bool = Query(default=False),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> dict[str, Any]:
    ds = _require_dataset(dataset_id, tenant_id)
    try:
        rows, columns = fetch_dataset_rows(ds, tenant_id, limit=100, anonymise=anonymise)
    except Exception as exc:
        logger.error("Dataset preview failed (id=%s): %s", dataset_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Query execution failed")
    return {
        "dataset_id": dataset_id,
        "name": ds.get("name"),
        "columns": columns,
        "row_count": len(rows),
        "rows": rows,
        "preview": True,
    }


@router.get(
    "/datasets/{dataset_id}/schema",
    summary="Column schema for BI tool import (Tableau WDC / PowerBI)",
    description=(
        "Returns the column definitions in both the native RAF Intelligence "
        "format and the Tableau WDC schema format so BI tools can auto-map types."
    ),
)
def api_dataset_schema(
    dataset_id: int,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> dict[str, Any]:
    ds = _require_dataset(dataset_id, tenant_id)
    tableau_schema = build_tableau_wdc_schema(ds)
    return {
        "dataset_id": dataset_id,
        "name": ds.get("name"),
        "dataset_type": ds.get("dataset_type"),
        "columns": tableau_schema.get("columns", []),
        "tableau_wdc_schema": tableau_schema,
    }


# ---------------------------------------------------------------------------
# Connection endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/connections",
    status_code=status.HTTP_201_CREATED,
    summary="Register a BI tool connection",
    description=(
        "Saves a connection to a BI platform. "
        "The api_key is encrypted at rest; it is never returned in any response."
    ),
)
def api_create_connection(
    body: ConnectionCreateRequest,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> dict[str, Any]:
    new_id = create_connection(
        name=body.name,
        bi_tool=body.bi_tool,
        connection_config=body.connection_config,
        api_key=body.api_key,
        refresh_schedule=body.refresh_schedule,
        tenant_id=tenant_id,
    )
    return {"id": new_id, "message": "Connection created"}


@router.get(
    "/connections",
    summary="List BI tool connections",
)
def api_list_connections(
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> dict[str, Any]:
    connections = list_connections(tenant_id)
    return {"count": len(connections), "connections": connections}


@router.post(
    "/connections/{connection_id}/push",
    summary="Push a dataset to the configured BI tool",
    description=(
        "Fetches the dataset rows and pushes them to the BI tool via its API. "
        "Currently supports PowerBI REST push datasets. "
        "For Tableau and Looker the data is serialised to JSON returned in the "
        "response body for the caller to relay."
    ),
)
def api_push_to_connection(
    connection_id: int,
    body: PushRequest,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> dict[str, Any]:
    conn = _require_connection(connection_id, tenant_id)
    ds = get_dataset(body.dataset_id, tenant_id)
    if not ds:
        raise HTTPException(status_code=404, detail="Dataset not found")

    t0 = time.perf_counter()
    try:
        rows, columns = fetch_dataset_rows(ds, tenant_id, anonymise=body.anonymise)
    except Exception as exc:
        logger.error("Push fetch failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Query execution failed")

    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    bi_tool = conn.get("bi_tool", "")

    if bi_tool == "powerbi":
        api_key = _get_connection_api_key(connection_id, tenant_id)
        if not api_key:
            raise HTTPException(status_code=400, detail="No API key configured for this connection")
        result = push_to_powerbi(conn, api_key, ds.get("name", "export"), rows)
        push_status = "success" if result.get("success") else "failed"

        log_export(
            export_type="api_push",
            status=push_status,
            tenant_id=tenant_id,
            dataset_id=body.dataset_id,
            connection_id=connection_id,
            row_count=len(rows),
            duration_ms=elapsed_ms,
            error_message=result.get("error") if not result.get("success") else None,
            exported_by=current_user.get("id"),
        )

        if not result.get("success"):
            raise HTTPException(status_code=502, detail=result.get("error", "Push failed"))
        return result

    # For non-REST-push tools (Tableau, Looker, generic): return the data
    # payload so the caller or a downstream webhook can relay it.
    log_export(
        export_type="api_push",
        status="success",
        tenant_id=tenant_id,
        dataset_id=body.dataset_id,
        connection_id=connection_id,
        row_count=len(rows),
        duration_ms=elapsed_ms,
        exported_by=current_user.get("id"),
    )
    return {
        "bi_tool": bi_tool,
        "dataset": ds.get("name"),
        "row_count": len(rows),
        "columns": columns,
        "rows": rows,
        "duration_ms": elapsed_ms,
        "note": (
            f"Direct API push is not implemented for {bi_tool}. "
            "Use the /download endpoint and import the file into your BI tool, "
            "or use the OData feed endpoint for PowerBI desktop."
        ),
    }


# ---------------------------------------------------------------------------
# Export log
# ---------------------------------------------------------------------------

@router.get(
    "/export-log",
    summary="Paginated export audit history",
)
def api_export_log(
    dataset_id: int | None = Query(default=None, description="Filter by dataset"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> dict[str, Any]:
    rows = list_export_log(tenant_id, dataset_id=dataset_id, limit=limit, offset=offset)
    # Serialise datetime fields
    result = []
    for row in rows:
        r = dict(row)
        for k, v in r.items():
            if hasattr(v, "isoformat"):
                r[k] = v.isoformat()
        result.append(r)
    return {"count": len(result), "log": result}


# ---------------------------------------------------------------------------
# Tableau WDC endpoint
# ---------------------------------------------------------------------------

@router.get(
    "/tableau/wdc",
    response_class=HTMLResponse,
    summary="Tableau Web Data Connector HTML page",
    description=(
        "Returns the WDC HTML/JS page. Open this URL in Tableau Desktop via "
        '"Web Data Connector" and enter a Dataset ID plus your API Bearer token.'
    ),
)
def api_tableau_wdc(
    request: Request,
) -> HTMLResponse:
    # The WDC page is intentionally unauthenticated so Tableau can load it
    # before the user provides their token in the UI.
    base = str(request.base_url).rstrip("/")
    html = build_tableau_wdc_html(base)
    return HTMLResponse(content=html)


# ---------------------------------------------------------------------------
# OData v4 endpoint (PowerBI "Get Data → OData Feed")
# ---------------------------------------------------------------------------

@router.get(
    "/odata/{dataset_name}",
    summary="OData v4 feed for PowerBI and other OData consumers",
    description=(
        "Returns dataset rows as an OData v4 JSON feed. "
        "Point PowerBI Desktop at: GET /api/bi/odata/{dataset_name} "
        "where dataset_name is the dataset_type key (e.g. raf_scores, hcc_gaps). "
        "Append /$metadata to retrieve the CSDL schema."
    ),
)
def api_odata_feed(
    dataset_name: str,
    metadata: bool = Query(default=False, alias="$metadata", description="Return CSDL metadata XML"),
    top: int | None = Query(default=None, alias="$top", description="OData $top — row limit"),
    skip: int = Query(default=0, alias="$skip", description="OData $skip — row offset"),
    anonymise: bool = Query(default=False),
    request: Request = None,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> Response:
    # Resolve dataset by type name
    with __import__("app.db", fromlist=["raf_cursor"]).raf_cursor() as cur:
        cur.execute(
            "SELECT * FROM bi_datasets WHERE dataset_type = %s AND tenant_id = %s LIMIT 1",
            (dataset_name, tenant_id),
        )
        row = cur.fetchone()

    # Fall back to pre-built definition if no DB record exists
    if not row and dataset_name not in PREBUILT_DATASETS:
        raise HTTPException(status_code=404, detail=f"Dataset '{dataset_name}' not found")

    if not row:
        # Use pre-built definition transiently (no DB record needed for metadata)
        prebuilt = PREBUILT_DATASETS[dataset_name]
        ds: dict[str, Any] = {
            "id": 0,
            "name": prebuilt["name"],
            "dataset_type": dataset_name,
            "query_template": prebuilt["query_template"],
            "columns_config": prebuilt["columns_config"],
        }
    else:
        ds = dict(row)

    from app.services.bi_export_service import _resolve_query
    _, columns = _resolve_query(ds)

    if metadata:
        xml = build_odata_metadata(ds.get("name", dataset_name), columns)
        return Response(content=xml, media_type="application/xml")

    try:
        rows, columns = fetch_dataset_rows(
            ds, tenant_id, limit=top, offset=skip, anonymise=anonymise
        )
    except Exception as exc:
        logger.error("OData feed query failed (%s): %s", dataset_name, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Query execution failed")

    odata_base = str(request.base_url).rstrip("/") + "/api/bi/odata" if request else ""
    payload = build_odata_response(rows, ds.get("name", dataset_name), odata_base)

    log_export(
        export_type="api_push",
        status="success",
        tenant_id=tenant_id,
        dataset_id=ds.get("id") or None,
        row_count=len(rows),
        exported_by=current_user.get("id"),
    )

    return Response(
        content=__import__("json").dumps(payload, default=str),
        media_type="application/json;odata.metadata=minimal",
    )
