"""
CDS Hooks integration — locked-down for PHI safety.

Implements the CDS Hooks 2.0 discovery + invocation pattern. The discovery
document at GET /cds-services is intentionally open (the spec requires it
to be public so EHRs can register). All invocation endpoints require:

  1. A pre-shared bearer secret (env CDS_HOOKS_SHARED_SECRET) supplied via
     either the standard `Authorization: Bearer <secret>` header OR the
     `fhirAuthorization.access_token` field in the request body.
  2. Optional IP allow-list (env CDS_HOOKS_ALLOWED_IPS, comma-separated
     CIDR or bare IPs). When set, requests not from those sources are 403.
  3. Per-source-IP rate limit (60 req/min, in-memory token bucket).
  4. A real patient resolution for the supplied context.patientId. If the
     id cannot be mapped to an internal tenant-scoped pid, we return an
     empty card array (never leak existence).
  5. Immutable audit emit on every successful invocation.

The previous version returned full HCC/ICD-10 detail to unauthenticated
public callers — a HIPAA breach. This version refuses to serve any card
unless the shared secret is configured AND the caller supplies it.

Spec: https://cds-hooks.hl7.org/2.0/
"""
from __future__ import annotations

import ipaddress
import logging
import os
import time
from collections import defaultdict
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from app.config import settings
from app.db import raf_cursor

logger = logging.getLogger(__name__)

# No prefix — CDS Hooks requires the literal path /cds-services.
# Mounted at the app root in router_registry.register_routers().
router = APIRouter(tags=["cds_hooks"])


# ---------------------------------------------------------------------------
# Security configuration (env-driven; refuses to serve when unset)
# ---------------------------------------------------------------------------


def _shared_secret() -> str | None:
    secret = os.environ.get("CDS_HOOKS_SHARED_SECRET", "").strip()
    return secret or None


def _allowed_ip_networks() -> list[ipaddress._BaseNetwork]:
    raw = os.environ.get("CDS_HOOKS_ALLOWED_IPS", "").strip()
    if not raw:
        return []
    out: list[ipaddress._BaseNetwork] = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            out.append(ipaddress.ip_network(chunk, strict=False))
        except ValueError:
            logger.warning("CDS_HOOKS_ALLOWED_IPS skipping invalid entry %r", chunk)
    return out


# ---------------------------------------------------------------------------
# Per-IP rate limit — in-memory token bucket. 60 req / 60s window.
# ---------------------------------------------------------------------------

_RATE_WINDOW_SEC = 60
_RATE_LIMIT_PER_WINDOW = 60
_rate_state: dict[str, list[float]] = defaultdict(list)


def _rate_check(client_ip: str) -> tuple[bool, int]:
    now = time.time()
    cutoff = now - _RATE_WINDOW_SEC
    history = [t for t in _rate_state[client_ip] if t > cutoff]
    if len(history) >= _RATE_LIMIT_PER_WINDOW:
        retry_after = max(1, int(_RATE_WINDOW_SEC - (now - history[0])))
        _rate_state[client_ip] = history
        return False, retry_after
    history.append(now)
    _rate_state[client_ip] = history
    return True, 0


# ---------------------------------------------------------------------------
# Pydantic models — CDS Hooks 2.0
# ---------------------------------------------------------------------------


class CDSHookRequest(BaseModel):
    hook: str = Field(..., description="Hook name, e.g. 'patient-view'")
    hookInstance: str = Field(..., description="UUID for this invocation")
    fhirServer: str | None = Field(default=None)
    fhirAuthorization: dict[str, Any] | None = Field(default=None)
    context: dict[str, Any] = Field(default_factory=dict)
    prefetch: dict[str, Any] | None = Field(default=None)


# ---------------------------------------------------------------------------
# Auth + audit helpers
# ---------------------------------------------------------------------------


def _extract_bearer(req: CDSHookRequest, authorization: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization.split(None, 1)[1].strip()
    if req.fhirAuthorization:
        token = req.fhirAuthorization.get("access_token")
        if token:
            return str(token).strip()
    return None


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return (request.client.host if request.client else "0.0.0.0") or "0.0.0.0"


def _ip_allowed(ip_str: str) -> bool:
    nets = _allowed_ip_networks()
    if not nets:
        return True  # allow-list not configured → no IP filtering
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return any(ip in n for n in nets)


def _emit_audit(*, patient_id: int, service_id: str, source_ip: str) -> None:
    try:
        from app.services.immutable_audit import emit_audit_event

        emit_audit_event(
            "CDS_HOOKS_INVOKED",
            tenant_id="system",
            actor_user_id=None,
            subject_type="patient",
            subject_id=str(patient_id),
            payload={
                "service_id": service_id,
                "source_ip": source_ip,
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("cds_hooks audit emit failed: %s", exc)


# ---------------------------------------------------------------------------
# Internal helpers (patient resolution, suspect fetch)
# ---------------------------------------------------------------------------


def _resolve_internal_pid(fhir_patient_id: str) -> int | None:
    if not fhir_patient_id:
        return None
    try:
        from app.services import openemr_connector as conn

        helper = getattr(conn, "get_patient_by_fhir_id", None)
        if callable(helper):
            patient = helper(fhir_patient_id)
            if patient and patient.get("id"):
                return int(patient["id"])
    except Exception as exc:  # noqa: BLE001
        logger.warning("get_patient_by_fhir_id lookup failed: %s", exc)
    try:
        return int(fhir_patient_id)
    except (TypeError, ValueError):
        return None


def _patient_exists(pid: int) -> bool:
    try:
        with raf_cursor() as cur:
            cur.execute(
                "SELECT 1 FROM patients WHERE id=%s AND COALESCE(is_active,1)=1 LIMIT 1",
                (pid,),
            )
            return cur.fetchone() is not None
    except Exception as exc:  # noqa: BLE001
        logger.warning("CDS Hooks patient existence check failed: %s", exc)
        return False


def _fetch_open_suspects(pid: int) -> list[dict[str, Any]]:
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT id,
                       suspect_hcc,
                       suspect_icd10,
                       evidence_type,
                       confidence_score
                FROM   raf_suspect_conditions
                WHERE  patient_id = %s
                  AND  status = 'open'
                ORDER  BY confidence_score DESC
                LIMIT  50
                """,
                (pid,),
            )
            return [dict(r) for r in cur.fetchall()]
    except Exception as exc:  # noqa: BLE001
        logger.warning("CDS Hooks suspects lookup for pid=%s failed: %s", pid, exc)
        return []


def _app_base_url() -> str:
    base = getattr(settings, "public_app_url", None) or getattr(
        settings, "frontend_url", None
    )
    if base:
        return str(base).rstrip("/")
    return "https://app.raf.health"


# ---------------------------------------------------------------------------
# GET /cds-services — discovery document (public per spec)
# ---------------------------------------------------------------------------


@router.get("/cds-services", summary="CDS Hooks discovery document")
def discovery() -> dict[str, Any]:
    """Return the list of CDS services this server exposes. Public by spec."""
    return {
        "services": [
            {
                "hook": "patient-view",
                "id": "raf-suspects",
                "title": "RAF Suspects",
                "description": "Open HCC capture opportunities",
                "prefetch": {
                    "patient": "Patient/{{context.patientId}}",
                },
            }
        ]
    }


# ---------------------------------------------------------------------------
# POST /cds-services/raf-suspects — authenticated invocation
# ---------------------------------------------------------------------------


@router.post(
    "/cds-services/raf-suspects",
    summary="Return open HCC suspects as CDS Hooks cards (authenticated)",
)
def raf_suspects(
    req: CDSHookRequest,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    # 1. Refuse to serve when shared secret is not configured.
    secret = _shared_secret()
    if not secret:
        logger.warning(
            "CDS_HOOKS_SHARED_SECRET not configured — refusing CDS Hooks invocation"
        )
        raise HTTPException(status_code=503, detail="CDS Hooks not configured")

    # 2. IP allow-list (when configured).
    source_ip = _client_ip(request)
    if not _ip_allowed(source_ip):
        raise HTTPException(status_code=403, detail="Source IP not allowed")

    # 3. Rate limit by source IP.
    ok, retry_after = _rate_check(source_ip)
    if not ok:
        raise HTTPException(
            status_code=429,
            detail="rate limit exceeded",
            headers={"Retry-After": str(retry_after)},
        )

    # 4. Bearer-secret check (header OR fhirAuthorization.access_token).
    presented = _extract_bearer(req, authorization)
    if not presented or presented != secret:
        raise HTTPException(status_code=401, detail="Unauthorized")

    # 5. Resolve patient and confirm it exists. Never leak existence
    # ("not found" and "no cards" return the same empty card array).
    fhir_patient_id = str(req.context.get("patientId") or "")
    pid = _resolve_internal_pid(fhir_patient_id)
    if pid is None or not _patient_exists(pid):
        logger.info(
            "CDS Hooks raf-suspects: patient not resolvable patientId=%r",
            fhir_patient_id,
        )
        return {"cards": []}

    suspects = _fetch_open_suspects(pid)
    _emit_audit(patient_id=pid, service_id="raf-suspects", source_ip=source_ip)
    if not suspects:
        return {"cards": []}

    base = _app_base_url()
    deep_link = f"{base}/patients/{pid}"
    top = suspects[:3]
    preview_lines = [
        f"- HCC {row['suspect_hcc']} ({row['suspect_icd10']}) — "
        f"{row['evidence_type']} evidence, "
        f"confidence {float(row['confidence_score']):.2f}"
        for row in top
    ]
    extra = len(suspects) - len(top)
    if extra > 0:
        preview_lines.append(f"- …and {extra} more")
    detail_md = "Top suspects:\n" + "\n".join(preview_lines)

    card = {
        "summary": f"{len(suspects)} open HCC suspects",
        "detail": detail_md,
        "source": {"label": "RAF Intelligence", "url": deep_link},
        "indicator": "info",
        "links": [
            {"label": "Review in RAF", "url": deep_link, "type": "absolute"}
        ],
    }
    return {"cards": [card]}
