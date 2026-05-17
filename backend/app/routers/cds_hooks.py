"""
CDS Hooks integration (first-cut).

Implements the CDS Hooks 2.0 discovery + invocation pattern used by Apixio
Apicare and ForeSee Vim. External EHRs call:

  GET  /cds-services                 -> discovery document
  POST /cds-services/{service-id}    -> returns Card[] for the given hook

This first-cut exposes a single service, ``raf-suspects``, bound to the
``patient-view`` hook. When an EHR loads a patient chart, it fires the hook;
we return a card summarising open HCC suspect conditions for that patient
with a deep link back into the RAF Intelligence app.

NOTE: These endpoints intentionally live OUTSIDE the ``/api/`` namespace,
because the CDS Hooks spec mandates the literal ``/cds-services`` discovery
path at the service root. No authentication is enforced here for the stub
— a production implementation must validate the JWT supplied in
``fhirAuthorization.access_token`` per the CDS Hooks security spec.

Spec: https://cds-hooks.hl7.org/2.0/
"""

import logging
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.config import settings
from app.db import raf_cursor

logger = logging.getLogger(__name__)

# No prefix — CDS Hooks requires the literal path /cds-services.
# Mounted at the app root in router_registry.register_routers().
router = APIRouter(tags=["cds_hooks"])


# ---------------------------------------------------------------------------
# Pydantic models — CDS Hooks 2.0 request/response shapes
# ---------------------------------------------------------------------------


class CDSHookRequest(BaseModel):
    """Incoming POST body per CDS Hooks 2.0 spec."""

    hook: str = Field(..., description="Hook name, e.g. 'patient-view'")
    hookInstance: str = Field(..., description="UUID for this invocation")
    fhirServer: str | None = Field(
        default=None, description="Base URL of the calling EHR's FHIR server"
    )
    fhirAuthorization: dict[str, Any] | None = Field(
        default=None,
        description="OAuth2 bearer token used to call back into fhirServer",
    )
    context: dict[str, Any] = Field(
        default_factory=dict,
        description="Hook-specific context, e.g. {patientId, userId, encounterId}",
    )
    prefetch: dict[str, Any] | None = Field(
        default=None, description="EHR-resolved prefetch templates"
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_internal_pid(fhir_patient_id: str) -> int | None:
    """Map a CDS Hooks ``context.patientId`` to an internal patient pid.

    Prefers ``app.services.openemr_connector.get_patient_by_fhir_id`` if it
    exists; otherwise falls back to a direct integer match against the
    internal patient id (suitable for OpenEMR-style numeric pids).

    Returns ``None`` if no mapping can be made.
    """
    if not fhir_patient_id:
        return None

    # Try the dedicated helper first if it's been added to the connector.
    try:
        from app.services import openemr_connector as conn

        helper = getattr(conn, "get_patient_by_fhir_id", None)
        if callable(helper):
            patient = helper(fhir_patient_id)
            if patient and patient.get("id"):
                return int(patient["id"])
    except Exception as exc:  # noqa: BLE001 — best-effort lookup
        logger.warning("get_patient_by_fhir_id lookup failed: %s", exc)

    # Fallback: treat the FHIR id as the internal numeric pid.
    try:
        return int(fhir_patient_id)
    except (TypeError, ValueError):
        return None


def _fetch_open_suspects(pid: int) -> list[dict[str, Any]]:
    """Return a list of open suspect-condition rows for the given pid.

    Returns an empty list on any database error so the CDS Hooks card
    rendering still degrades gracefully (the EHR will simply see no card
    rather than a hard error in the chart).
    """
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
    """Best-effort public base URL for deep links back into the app."""
    base = getattr(settings, "public_app_url", None) or getattr(
        settings, "frontend_url", None
    )
    if base:
        return str(base).rstrip("/")
    return "https://app.raf.health"


# ---------------------------------------------------------------------------
# GET /cds-services — discovery document
# ---------------------------------------------------------------------------


@router.get("/cds-services", summary="CDS Hooks discovery document")
def discovery() -> dict[str, Any]:
    """Return the list of CDS services this server exposes.

    External EHRs poll this once at registration time to learn which hooks
    and services are supported. The shape is fixed by the CDS Hooks 2.0
    spec.
    """
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
# POST /cds-services/raf-suspects — invocation
# ---------------------------------------------------------------------------


@router.post(
    "/cds-services/raf-suspects",
    summary="Return open HCC suspects as CDS Hooks cards",
)
def raf_suspects(req: CDSHookRequest) -> dict[str, Any]:
    """Return a CDS Hooks Card array describing open HCC suspects.

    The EHR posts the standard CDS Hooks request body. We resolve the
    ``context.patientId`` to an internal pid, query open suspects, and
    return one summary card with a deep link back into RAF Intelligence.

    Returns ``{"cards": []}`` (a valid empty response) when the patient
    cannot be resolved or has no open suspects, so the EHR simply renders
    nothing in the chart.
    """
    fhir_patient_id = str(req.context.get("patientId") or "")
    pid = _resolve_internal_pid(fhir_patient_id)
    if pid is None:
        logger.info(
            "CDS Hooks raf-suspects: could not resolve patientId=%r (hook=%s)",
            fhir_patient_id,
            req.hook,
        )
        return {"cards": []}

    suspects = _fetch_open_suspects(pid)
    if not suspects:
        return {"cards": []}

    base = _app_base_url()
    deep_link = f"{base}/patients/{pid}"

    # Build a short bullet-point preview of the top 3 suspects for the
    # card's detail markdown so the provider sees specifics without
    # navigating away.
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
        "source": {
            "label": "RAF Intelligence",
            "url": deep_link,
        },
        "indicator": "info",
        "links": [
            {
                "label": "Review in RAF",
                "url": deep_link,
                "type": "absolute",
            }
        ],
    }
    return {"cards": [card]}
