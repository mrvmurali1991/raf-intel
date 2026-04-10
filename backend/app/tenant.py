"""
Tenant isolation dependency for FastAPI.

Re-exports ``get_tenant_id`` from ``app.auth`` so routers can import from a
single, intention-revealing module.

Usage::

    from app.tenant import get_tenant_id

    @router.get("/resource")
    def endpoint(tenant_id: str = Depends(get_tenant_id)):
        ...
"""
from app.auth import get_tenant_id  # noqa: F401 — re-export
