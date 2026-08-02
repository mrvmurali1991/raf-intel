"""
Public demo information endpoints — no authentication required.

Routes
------
GET /api/demo/info
    Describes the RAF Intelligence platform, features, compliance
    posture, suspect-detection rules, and integration catalogue.
    Used by marketing sites to show prospects what they get.

GET /api/demo/roi-calculator
    Estimates the revenue impact of closing RAF gaps given member
    count and gap-rate assumptions.  Returns a conservative capture
    projection and supporting assumptions.
"""
# Note: do NOT use 'from __future__ import annotations' —
# it breaks FastAPI/Pydantic schema generation.

from fastapi import APIRouter, Query

router = APIRouter(
    prefix="/api/demo",
    tags=["demo"],
    # No auth dependency — these endpoints are intentionally public.
)


# ---------------------------------------------------------------------------
# GET /api/demo/info
# ---------------------------------------------------------------------------

@router.get("/info", summary="Demo environment information")
def demo_info() -> dict:
    """
    Public endpoint (no auth required) that describes the demo environment.
    Used by the marketing site to show prospects what they'll get.
    """
    return {
        "product": "RAF Intelligence",
        "version": "1.0",
        "demo_available": True,
        "demo_credentials": {
            "url": "https://raf.comercioit.com",
            "note": "Contact sales for demo access",
        },
        "features": [
            "CMS-HCC V24/V28 blended RAF scoring",
            "1,587+ clinical suspect detection rules",
            "AI-powered MEAT evidence extraction (Google Gemini)",
            "RADV audit defense with cryptographic evidence chain",
            "17 EMR integration protocols (FHIR, SMART, CDS Hooks, HL7v2, C-CDA)",
            "OpenEMR embedded plugin",
            "Multi-tenant SaaS with HIPAA-compliant audit trail",
            "Provider scorecards and peer benchmarking",
            "Recapture campaign management",
            "Real-time population health analytics",
        ],
        "compliance": [
            "HIPAA Technical Safeguards (§164.312) — Compliant",
            "CMS-HCC Model V24/V28 — Compliant",
            "FHIR R4 / SMART on FHIR 2.0 / CDS Hooks 2.0",
            "HL7 C-CDA R2.1 / HL7v2 ADT",
            "SOC 2 Type II — Evidence collection automated",
        ],
        "suspect_detection": {
            "total_rules": 1587,
            "medication_signals": 614,
            "lab_signals": 377,
            "procedure_signals": 358,
            "comorbidity_patterns": 93,
            "specificity_upgrades": 82,
            "vital_signals": 63,
        },
        "integrations": [
            "OpenEMR (Direct DB + FHIR R4)",
            "Epic (SMART on FHIR + CDS Hooks)",
            "Cerner/Oracle Health (FHIR R4)",
            "Athenahealth (REST API)",
            "Allscripts/Veradigm (REST API + Unity)",
            "DrChrono (OAuth2 REST)",
            "CommonWell Health Alliance (HIE)",
            "Carequality (HIE)",
            "Inovalon EROND (Unified Pull)",
            "Datavant Switchboard (Chart Retrieval)",
            "Direct Trust (S/MIME C-CDA)",
        ],
    }


# ---------------------------------------------------------------------------
# GET /api/demo/roi-calculator
# ---------------------------------------------------------------------------

@router.get("/roi-calculator", summary="Estimate RAF revenue impact")
def roi_calculator(
    total_patients: int = Query(1000, ge=100, le=100000),
    avg_raf: float = Query(1.05, ge=0.5, le=5.0),
    suspected_gap_rate: float = Query(0.15, ge=0.01, le=0.50),
    cms_rate: float = Query(11800, ge=5000, le=20000),
) -> dict:
    """
    Public ROI calculator -- no auth required.
    Estimates the revenue impact of closing RAF gaps.
    """
    gaps = int(total_patients * suspected_gap_rate)
    avg_gap_value = cms_rate * 0.05  # ~5% of CMS rate per gap
    total_opportunity = gaps * avg_gap_value
    conservative_capture = total_opportunity * 0.60  # 60% capture rate

    return {
        "inputs": {
            "total_patients": total_patients,
            "avg_raf_score": avg_raf,
            "suspected_gap_rate": suspected_gap_rate,
            "cms_per_member_rate": cms_rate,
        },
        "estimated_results": {
            "suspected_gaps": gaps,
            "avg_revenue_per_gap": round(avg_gap_value, 2),
            "total_opportunity": round(total_opportunity, 2),
            "conservative_capture_60pct": round(conservative_capture, 2),
            "per_member_impact": round(conservative_capture / total_patients, 2),
        },
        "assumptions": [
            "Gap rate based on industry average (10-20% of members have undocumented HCCs)",
            "Average gap value is ~5% of CMS per-capita rate",
            "Conservative 60% capture rate (industry range: 40-80%)",
            "Does not include RADV audit savings or coding efficiency gains",
        ],
    }
