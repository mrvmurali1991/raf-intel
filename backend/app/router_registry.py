"""
Router registry for RAF Intelligence.

All router imports and ``app.include_router()`` calls live here.
Call ``register_routers(app)`` from main.py to mount every router.

Routers are registered in logical / dependency order:
  - auth first (token issuance required by all other routers)
  - core clinical entities
  - payer / claims workflows
  - integrations
  - provider and quality management
  - population health
  - operations and compliance
  - BI and worklists
  - real-time dashboards
  - health, info, admin
"""
from fastapi import FastAPI

from app.routers import (
    admin,
    adt,
    analysis,
    attestations,
    audit,
    awv,
    benchmarks,
    bi_export,
    bundles,
    care_gaps,
    ccda,
    chart_chase,
    claims,
    clearinghouse,
    cms_transmission,
    coder_worklist,
    cohorts,
    direct_messaging,
    documents,
    emr,
    fhir,
    jobs,
    notifications,
    patients,
    prospective,
    providers,
    quality,
    raf,
    reports,
    retention,
    submissions,
    suspects,
    uploads,
    webhooks,
)
from app.routers import auth as auth_router
from app.routers import config as config_router
from app.routers import disputes as disputes_router
from app.routers import feature_flags as feature_flags_router
from app.routers import forecast as forecast_router
from app.routers import hcc_gap_drilldown as hcc_gap_drilldown_router
from app.routers import hcc_removal as hcc_removal_router
from app.routers import meat_audit_risk as meat_audit_risk_router
from app.routers import peer_benchmarking as peer_benchmarking_router
from app.routers import previsit_briefing as previsit_briefing_router
from app.routers import provider_pdf_report as provider_pdf_report_router
from app.routers import provider_revenue_breakdown as provider_revenue_breakdown_router
from app.routers import provider_trends as provider_trends_router
from app.routers import top_hcc_opportunities as top_hcc_opportunities_router
from app.routers import consent as consent_router
from app.routers import dashboard_analytics as dashboard_analytics_router
from app.routers import data_quality as data_quality_router
from app.routers import health as health_router
from app.routers import icd10 as icd10_router
from app.routers import insights as insights_router
from app.routers import meat as meat_router
from app.routers import pipeline as pipeline_router
from app.routers import pipeline_settings as pipeline_settings_router
from app.routers import provider_suspect_hotlist as provider_suspect_hotlist_router
from app.routers import provider_worklist as provider_worklist_router
from app.routers import radv as radv_router
from app.routers import radv_audit as radv_audit_router
from app.routers import raf_central as raf_central_router
from app.routers import raf_inbox_admin as raf_inbox_admin_router
from app.routers import realtime as realtime_router
from app.routers import recapture_gaps as recapture_gaps_router
from app.routers import review as review_router
from app.routers import smart_fhir as smart_fhir_router
from app.routers import snomed_mapping as snomed_mapping_router


def register_routers(app: FastAPI) -> None:
    """Mount all application routers on *app*."""

    # Auth must come first (other routers depend on it for token issuance)
    app.include_router(auth_router.router)

    # Core clinical entities
    app.include_router(patients.router)
    app.include_router(raf.router)
    app.include_router(raf_central_router.router)
    app.include_router(forecast_router.router)
    app.include_router(hcc_removal_router.router)
    app.include_router(disputes_router.router)
    app.include_router(analysis.router)
    app.include_router(suspects.router)
    app.include_router(attestations.router)
    app.include_router(chart_chase.router)
    app.include_router(documents.router)
    app.include_router(ccda.router)
    app.include_router(uploads.router)

    # Payer / claims workflows
    app.include_router(claims.router)
    app.include_router(submissions.router)
    app.include_router(bundles.router)
    app.include_router(cms_transmission.router)

    # Integrations
    app.include_router(fhir.router)
    app.include_router(smart_fhir_router.router)
    app.include_router(emr.router)
    app.include_router(adt.router)
    app.include_router(webhooks.router)
    app.include_router(notifications.router)
    app.include_router(direct_messaging.router)
    app.include_router(clearinghouse.router)

    # Provider and quality management
    # NOTE: peer_benchmarking is registered BEFORE providers.router so that
    # the literal /api/providers/specialty-benchmarks path matches before the
    # /api/providers/{id} catch-all.
    app.include_router(peer_benchmarking_router.router)
    app.include_router(provider_trends_router.router)  # /api/providers/trend-aggregate before /{id}/trend
    app.include_router(providers.router)
    app.include_router(top_hcc_opportunities_router.router)
    app.include_router(provider_revenue_breakdown_router.router)
    app.include_router(meat_audit_risk_router.router)
    app.include_router(hcc_gap_drilldown_router.router)
    app.include_router(previsit_briefing_router.router)
    app.include_router(provider_pdf_report_router.router)
    app.include_router(feature_flags_router.router)
    app.include_router(quality.router)
    app.include_router(prospective.router)
    app.include_router(benchmarks.router)
    app.include_router(care_gaps.router)
    app.include_router(recapture_gaps_router.router)
    app.include_router(awv.router)

    # Population health cohort analysis
    app.include_router(cohorts.router)

    # Operations and compliance
    app.include_router(jobs.router)
    app.include_router(pipeline_router.router)
    app.include_router(pipeline_settings_router.router)
    app.include_router(config_router.router)
    app.include_router(reports.router)
    app.include_router(dashboard_analytics_router.router)
    app.include_router(audit.router)

    # Compliance — consent management
    app.include_router(consent_router.router)

    # BI Tools Export
    app.include_router(bi_export.router)

    # Coder worklist / review queue
    app.include_router(coder_worklist.router)
    app.include_router(review_router.router)

    # Provider worklist — prioritized patient lists and action items
    app.include_router(provider_worklist_router.router)

    # Real-time suspect hot-list (provider drawer "action this week")
    app.include_router(provider_suspect_hotlist_router.router)

    # Real-time clinical intelligence insights
    app.include_router(insights_router.router)

    # Real-time dashboards
    app.include_router(realtime_router.router)

    # Health and info
    app.include_router(health_router.router)
    app.include_router(icd10_router.router)

    # Admin
    app.include_router(retention.router)
    app.include_router(admin.router)
    app.include_router(meat_router.router)
    app.include_router(radv_audit_router.router)
    # RADV packet PDF export (per-patient, per-payment-year audit bundle).
    # Shares the /api/radv prefix with radv_audit but owns distinct paths.
    app.include_router(radv_router.router)
    app.include_router(data_quality_router.router)
    app.include_router(raf_inbox_admin_router.router)

    # Knowledge-graph services (SNOMED CT mapping, free-text → HCC pipeline)
    app.include_router(snomed_mapping_router.router)
