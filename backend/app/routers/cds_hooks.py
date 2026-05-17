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
  4. Per-(patient_id, hookInstance) rate limit — max 1 invocation per
     hookInstance per patient per 60 seconds (Epic/Cerner re-issue
     hookInstance on each new chart-open).
  5. A real patient resolution for the supplied context.patientId. If the
     id cannot be mapped to an internal tenant-scoped pid, we return an
     empty card array (never leak existence).
  6. Immutable audit emit on every successful invocation.
  7. Hard cap of 3 cards per patient-view invocation (ONC CDS safety).
  8. Dedup: suspects already shown/dismissed within last 24 h are suppressed;
     suppressed events emit CDS_CARD_SUPPRESSED_DUP.
  9. Suspects whose status in raf_suspect_conditions is 'dismissed' or
     'accepted' are excluded entirely.
 10. POST /cds-services/{service_id}/feedback implements CDS Hooks 2.0 §5.

Spec: https://cds-hooks.hl7.org/2.0/
"""
from __future__ import annotations

import ipaddress
import logging
import os
import time
import uuid as _uuid_mod
from collections import defaultdict
from datetime import datetime, timedelta, timezone
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

# Per-(patient_id, hookInstance) dedup: max 1 call per hookInstance per 60s.
_hook_instance_seen: dict[str, float] = {}
_HOOK_INSTANCE_TTL_SEC = 60


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


def _hook_instance_check(patient_id: int, hook_instance: str) -> bool:
    """Return True (allowed) if this (patient_id, hookInstance) has not been
    seen within the last 60 seconds.  Records the call time on success."""
    key = f"{patient_id}:{hook_instance}"
    now = time.time()
    last = _hook_instance_seen.get(key)
    if last is not None and (now - last) < _HOOK_INSTANCE_TTL_SEC:
        return False
    _hook_instance_seen[key] = now
    return True


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


class FeedbackReason(BaseModel):
    code: str | None = None
    system: str | None = None
    display: str | None = None


class FeedbackItem(BaseModel):
    card: str = Field(..., description="card UUID from the original response")
    outcome: str = Field(..., description="accepted | overridden | ignored")
    outcomeTimestamp: str | None = None
    reason: FeedbackReason | None = None


class CDSFeedbackRequest(BaseModel):
    feedback: list[FeedbackItem] = Field(default_factory=list)


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


def _emit_suppressed_dup_audit(
    *, patient_id: int, suspect_id: int | str, service_id: str
) -> None:
    try:
        from app.services.immutable_audit import emit_audit_event

        emit_audit_event(
            "CDS_CARD_SUPPRESSED_DUP",
            tenant_id="system",
            actor_user_id=None,
            subject_type="patient",
            subject_id=str(patient_id),
            payload={
                "service_id": service_id,
                "suspect_id": str(suspect_id),
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("cds_hooks suppressed_dup audit emit failed: %s", exc)


def _emit_feedback_audit(
    *, patient_id: int, card_uuid: str, outcome: str, service_id: str
) -> None:
    try:
        from app.services.immutable_audit import emit_audit_event

        emit_audit_event(
            "CDS_CARD_FEEDBACK_RECEIVED",
            tenant_id="system",
            actor_user_id=None,
            subject_type="patient",
            subject_id=str(patient_id),
            payload={
                "service_id": service_id,
                "card_uuid": card_uuid,
                "outcome": outcome,
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("cds_hooks feedback audit emit failed: %s", exc)


# ---------------------------------------------------------------------------
# Internal helpers (patient resolution, suspect fetch, dedup)
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
    """Return up to 3 open (not dismissed/accepted) suspects for this patient,
    ordered by confidence descending.  The hard cap of 3 is per ONC CDS safety
    guidance and PCP feedback — we never return more than 3 per invocation."""
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
                  AND  status NOT IN ('dismissed', 'accepted')
                ORDER  BY confidence_score DESC
                LIMIT  3
                """,
                (pid,),
            )
            return [dict(r) for r in cur.fetchall()]
    except Exception as exc:  # noqa: BLE001
        logger.warning("CDS Hooks suspects lookup for pid=%s failed: %s", pid, exc)
        return []


def _get_recently_shown_suspect_ids(
    tenant_id: str, patient_id: int, suspect_ids: list[int]
) -> set[int]:
    """Return the subset of suspect_ids that were shown or dismissed for this
    (tenant_id, patient_id) within the last 24 hours."""
    if not suspect_ids:
        return set()
    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=24)
    placeholders = ",".join(["%s"] * len(suspect_ids))
    try:
        with raf_cursor() as cur:
            cur.execute(
                f"""
                SELECT DISTINCT suspect_id
                FROM   cds_hooks_shown
                WHERE  tenant_id  = %s
                  AND  patient_id = %s
                  AND  suspect_id IN ({placeholders})
                  AND  shown_at   >= %s
                  AND  status IN ('shown', 'dismissed')
                """,
                (tenant_id, patient_id, *suspect_ids, cutoff),
            )
            return {int(r["suspect_id"]) for r in cur.fetchall()}
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "CDS Hooks dedup query failed for pid=%s: %s", patient_id, exc
        )
        return set()


def _record_shown(
    *,
    tenant_id: str,
    patient_id: int,
    suspect_id: int,
    hook_instance: str,
    hook_name: str,
    card_uuid: str,
) -> None:
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                INSERT INTO cds_hooks_shown
                    (tenant_id, patient_id, suspect_id, hook_instance, hook_name,
                     card_uuid, status)
                VALUES (%s, %s, %s, %s, %s, %s, 'shown')
                """,
                (
                    tenant_id,
                    patient_id,
                    suspect_id,
                    hook_instance,
                    hook_name,
                    card_uuid,
                ),
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("CDS Hooks record_shown failed: %s", exc)


def _update_feedback_status(card_uuid: str, outcome: str) -> dict[str, Any] | None:
    """Find the cds_hooks_shown row by card_uuid and update its status.
    Returns the row dict if found, None otherwise."""
    status = "accepted" if outcome == "accepted" else "dismissed"
    try:
        with raf_cursor() as cur:
            cur.execute(
                "SELECT id, patient_id, suspect_id FROM cds_hooks_shown WHERE card_uuid = %s LIMIT 1",
                (card_uuid,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            cur.execute(
                "UPDATE cds_hooks_shown SET status = %s WHERE id = %s",
                (status, row["id"]),
            )
            return dict(row)
    except Exception as exc:  # noqa: BLE001
        logger.warning("CDS Hooks update_feedback_status failed: %s", exc)
        return None


def _app_base_url() -> str:
    base = getattr(settings, "public_app_url", None) or getattr(
        settings, "frontend_url", None
    )
    if base:
        return str(base).rstrip("/")
    return "https://app.raf.health"


# ---------------------------------------------------------------------------
# Shared auth pre-check (DRY helper for both invocation endpoints)
# ---------------------------------------------------------------------------


def _auth_prechecks(
    req: CDSHookRequest,
    request: Request,
    authorization: str | None,
    patient_id_for_hook_dedup: int | None = None,
) -> str:
    """Run all security checks; return source_ip on success or raise HTTPException."""
    secret = _shared_secret()
    if not secret:
        logger.warning(
            "CDS_HOOKS_SHARED_SECRET not configured — refusing CDS Hooks invocation"
        )
        raise HTTPException(status_code=503, detail="CDS Hooks not configured")

    source_ip = _client_ip(request)
    if not _ip_allowed(source_ip):
        raise HTTPException(status_code=403, detail="Source IP not allowed")

    ok, retry_after = _rate_check(source_ip)
    if not ok:
        raise HTTPException(
            status_code=429,
            detail="rate limit exceeded",
            headers={"Retry-After": str(retry_after)},
        )

    presented = _extract_bearer(req, authorization)
    if not presented or presented != secret:
        raise HTTPException(status_code=401, detail="Unauthorized")

    if patient_id_for_hook_dedup is not None:
        if not _hook_instance_check(patient_id_for_hook_dedup, req.hookInstance):
            raise HTTPException(
                status_code=429,
                detail="hookInstance already processed for this patient within 60s",
                headers={"Retry-After": "60"},
            )

    return source_ip


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
                "description": "Open HCC capture opportunities (read-only summary cards).",
                "prefetch": {
                    "patient": "Patient/{{context.patientId}}",
                },
            },
            {
                "hook": "patient-view",
                "id": "hcc-suggestions-realtime",
                "title": "RAF HCC Suggestions (write-back)",
                "description": (
                    "Real-time HCC suspect cards with one-click FHIR Condition "
                    "resources ready to apply to the Problem List."
                ),
                "prefetch": {
                    "patient": "Patient/{{context.patientId}}",
                    "conditions": "Condition?patient={{context.patientId}}",
                },
            },
        ]
    }


# ---------------------------------------------------------------------------
# ICD-10 display helper (best-effort, with static fallback for demo HCCs)
# ---------------------------------------------------------------------------


def _icd10_display(icd10: str) -> str:
    """Return a short ICD-10 display label. Falls back to the code itself."""
    if not icd10:
        return ""
    try:
        from app.services import icd10_lookup as lk  # type: ignore

        helper = getattr(lk, "get_description", None)
        if callable(helper):
            desc = helper(icd10)
            if desc:
                return str(desc)
    except Exception:
        pass
    fallback = {
        "J44.9": "Chronic obstructive pulmonary disease, unspecified",
        "E11.9": "Type 2 diabetes mellitus without complications",
        "E11.65": "Type 2 diabetes mellitus with hyperglycemia",
        "I50.9": "Heart failure, unspecified",
        "N18.3": "Chronic kidney disease, stage 3 (moderate)",
        "F32.9": "Major depressive disorder, single episode, unspecified",
        "I25.10": ("Atherosclerotic heart disease of native coronary artery "
                   "without angina pectoris"),
    }
    return fallback.get(icd10, icd10)


def _condition_resource(
    *,
    patient_fhir_id: str,
    icd10: str,
    hcc: str | int,
    confidence: float,
) -> dict[str, Any]:
    """Build a FHIR R4 ``Condition`` resource the EHR can write directly to
    the Problem List.  Encodes ICD-10-CM as the primary coding and tags the
    confidence score in an extension for traceability."""
    return {
        "resourceType": "Condition",
        "clinicalStatus": {
            "coding": [
                {
                    "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                    "code": "active",
                    "display": "Active",
                }
            ]
        },
        "verificationStatus": {
            "coding": [
                {
                    "system": "http://terminology.hl7.org/CodeSystem/condition-ver-status",
                    "code": "provisional",
                    "display": "Provisional",
                }
            ]
        },
        "category": [
            {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/condition-category",
                        "code": "problem-list-item",
                        "display": "Problem List Item",
                    }
                ]
            }
        ],
        "code": {
            "coding": [
                {
                    "system": "http://hl7.org/fhir/sid/icd-10-cm",
                    "code": icd10,
                    "display": _icd10_display(icd10),
                }
            ],
            "text": _icd10_display(icd10),
        },
        "subject": {"reference": f"Patient/{patient_fhir_id}"},
        "extension": [
            {
                "url": "https://raf.health/fhir/StructureDefinition/hcc-category",
                "valueString": str(hcc),
            },
            {
                "url": "https://raf.health/fhir/StructureDefinition/raf-confidence",
                "valueDecimal": round(float(confidence), 4),
            },
        ],
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
    # 1-4. Auth, IP, rate-limit checks.
    fhir_patient_id = str(req.context.get("patientId") or "")
    pid_for_dedup = _resolve_internal_pid(fhir_patient_id)

    source_ip = _auth_prechecks(
        req, request, authorization,
        patient_id_for_hook_dedup=pid_for_dedup,
    )

    # 5. Resolve patient and confirm it exists.
    pid = pid_for_dedup
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
    # suspects already limited to 3 in _fetch_open_suspects
    top = suspects[:3]
    preview_lines = [
        f"- HCC {row['suspect_hcc']} ({row['suspect_icd10']}) — "
        f"{row['evidence_type']} evidence, "
        f"confidence {float(row['confidence_score']):.2f}"
        for row in top
    ]
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


# ---------------------------------------------------------------------------
# POST /cds-services/hcc-suggestions-realtime — write-back-ready suggestions
# ---------------------------------------------------------------------------


@router.post(
    "/cds-services/hcc-suggestions-realtime",
    summary="Real-time HCC suggestion cards with FHIR write-back actions",
)
def hcc_suggestions_realtime(
    req: CDSHookRequest,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Return one CDS Hooks card per top-3 open suspect; each card carries a
    ``suggestions`` block whose ``actions[0]`` is a ready-to-apply FHIR
    Condition resource for the Problem List.

    Deduplication: suspects shown/dismissed within the last 24 h are
    suppressed (CDS_CARD_SUPPRESSED_DUP audit event emitted per suppressed
    card).  Hard cap: max 3 cards per invocation per ONC CDS safety guidance.

    Response shape conforms to CDS Hooks 2.0 §4.2.1
    (https://cds-hooks.hl7.org/2.0/#card-attributes).
    """
    # 1-4. Auth, IP, rate-limit, per-hookInstance dedup checks.
    fhir_patient_id = str(req.context.get("patientId") or "")
    pid_for_dedup = _resolve_internal_pid(fhir_patient_id)

    source_ip = _auth_prechecks(
        req, request, authorization,
        patient_id_for_hook_dedup=pid_for_dedup,
    )

    # 5. Resolve patient.
    pid = pid_for_dedup
    if pid is None or not _patient_exists(pid):
        logger.info(
            "CDS Hooks hcc-suggestions-realtime: patient not resolvable patientId=%r",
            fhir_patient_id,
        )
        return {"cards": []}

    # _fetch_open_suspects already excludes dismissed/accepted and caps at 3.
    suspects = _fetch_open_suspects(pid)
    _emit_audit(
        patient_id=pid, service_id="hcc-suggestions-realtime", source_ip=source_ip
    )
    if not suspects:
        return {"cards": []}

    # 6. Dedup: remove suspects shown/dismissed within last 24 h.
    tenant_id = "system"
    suspect_ids = [int(s["id"]) for s in suspects]
    recently_shown = _get_recently_shown_suspect_ids(tenant_id, pid, suspect_ids)

    filtered: list[dict[str, Any]] = []
    for s in suspects:
        if int(s["id"]) in recently_shown:
            _emit_suppressed_dup_audit(
                patient_id=pid,
                suspect_id=s["id"],
                service_id="hcc-suggestions-realtime",
            )
        else:
            filtered.append(s)

    if not filtered:
        return {"cards": []}

    # 7. Hard cap: max 3 cards (already guaranteed by _fetch_open_suspects,
    #    but enforced again here after dedup for belt-and-suspenders).
    top = filtered[:3]

    base = _app_base_url()
    deep_link = f"{base}/patients/{pid}"
    cards: list[dict[str, Any]] = []

    for row in top:
        icd10 = str(row["suspect_icd10"])
        hcc = row["suspect_hcc"]
        confidence = float(row["confidence_score"])
        display = _icd10_display(icd10)
        suggestion_label = f"Add HCC {hcc} ({icd10} {display})"
        card_uuid = str(_uuid_mod.uuid4())

        cards.append(
            {
                "uuid": card_uuid,
                "summary": f"Suspected HCC {hcc}: {icd10} {display}",
                "detail": (
                    f"RAF Intelligence flagged ICD-10 **{icd10} — {display}** "
                    f"(HCC {hcc}) for this patient with confidence "
                    f"**{confidence:.2f}** based on "
                    f"{row.get('evidence_type', 'rule-based')} evidence.  "
                    "Click the suggestion below to write a provisional "
                    "Condition into the Problem List for provider review."
                ),
                "indicator": "info",
                "source": {
                    "label": "RAF Intelligence",
                    "url": deep_link,
                    "icon": f"{base}/favicon.ico",
                },
                "suggestions": [
                    {
                        "label": suggestion_label,
                        "uuid": str(_uuid_mod.uuid4()),
                        "actions": [
                            {
                                "type": "create",
                                "description": (
                                    f"Add provisional problem '{display}' "
                                    f"({icd10}) to the patient's Problem List."
                                ),
                                "resource": _condition_resource(
                                    patient_fhir_id=fhir_patient_id or str(pid),
                                    icd10=icd10,
                                    hcc=hcc,
                                    confidence=confidence,
                                ),
                            }
                        ],
                    }
                ],
                "links": [
                    {
                        "label": "Review in RAF",
                        "url": f"{deep_link}?focus_hcc={hcc}",
                        "type": "absolute",
                    }
                ],
            }
        )

        # 8. Record each shown card for future dedup.
        _record_shown(
            tenant_id=tenant_id,
            patient_id=pid,
            suspect_id=int(row["id"]),
            hook_instance=req.hookInstance,
            hook_name=req.hook,
            card_uuid=card_uuid,
        )

    return {"cards": cards}


# ---------------------------------------------------------------------------
# POST /cds-services/{service_id}/feedback — CDS Hooks 2.0 §5
# ---------------------------------------------------------------------------


@router.post(
    "/cds-services/{service_id}/feedback",
    summary="CDS Hooks 2.0 §5 feedback endpoint",
)
def cds_feedback(
    service_id: str,
    body: CDSFeedbackRequest,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Accept feedback from the EHR about card outcomes (accepted /
    overridden / ignored).  Updates the corresponding cds_hooks_shown row
    and emits a CDS_CARD_FEEDBACK_RECEIVED audit event per item.

    Auth: same pre-shared bearer secret as invocation endpoints.
    """
    secret = _shared_secret()
    if not secret:
        raise HTTPException(status_code=503, detail="CDS Hooks not configured")

    source_ip = _client_ip(request)
    if not _ip_allowed(source_ip):
        raise HTTPException(status_code=403, detail="Source IP not allowed")

    # Rate-limit by IP (shared bucket with invocation endpoints).
    ok, retry_after = _rate_check(source_ip)
    if not ok:
        raise HTTPException(
            status_code=429,
            detail="rate limit exceeded",
            headers={"Retry-After": str(retry_after)},
        )

    # Bearer auth — must present same shared secret.
    presented: str | None = None
    auth_hdr = authorization or ""
    if auth_hdr.lower().startswith("bearer "):
        presented = auth_hdr.split(None, 1)[1].strip()
    if not presented or presented != secret:
        raise HTTPException(status_code=401, detail="Unauthorized")

    results: list[dict[str, Any]] = []
    for item in body.feedback:
        row = _update_feedback_status(item.card, item.outcome)
        if row is None:
            results.append({"card": item.card, "status": "not_found"})
            continue

        patient_id = row.get("patient_id", 0)
        _emit_feedback_audit(
            patient_id=int(patient_id),
            card_uuid=item.card,
            outcome=item.outcome,
            service_id=service_id,
        )
        results.append({"card": item.card, "status": "ok", "outcome": item.outcome})

    return {"processed": len(results), "results": results}
