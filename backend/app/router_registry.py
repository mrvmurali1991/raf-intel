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
    adt,
    admin,
    analysis,
    attestations,
    audit,
    awv,
    benchmarks,
    care_gaps,
    ccda,
    chart_chase,
    claims,
    clearinghouse,
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
from app.routers import bi_export
from app.routers import coder_worklist
from app.routers import provider_worklist as provider_worklist_router
from app.routers import insights as insights_router
from app.routers import realtime as realtime_router
from app.routers import smart_fhir as smart_fhir_router
from app.routers import meat as meat_router
from app.routers import radv_audit as radv_audit_router
from app.routers import data_quality as data_quality_router
from app.routers import health as health_router
from app.routers import icd10 as icd10_router
from app.routers import bundles, cms_transmission
from app.routers import pipeline as pipeline_router
from app.routers import consent as consent_router
from app.routers import pipeline_settings as pipeline_settings_router
from app.routers import recapture_gaps as recapture_gaps_router
from app.routers import dashboard_analytics as dashboard_analytics_router


def register_routers(app: FastAPI) -> None:
    """Mount all application routers on *app*."""

    # Auth must come first (other routers depend on it for token issuance)
    app.include_router(auth_router.router)

    # Core clinical entities
    app.include_router(patients.router)
    app.include_router(raf.router)
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
    app.include_router(providers.router)
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
    app.include_router(reports.router)
    app.include_router(dashboard_analytics_router.router)
    app.include_router(audit.router)

    # Compliance — consent management
    app.include_router(consent_router.router)

    # BI Tools Export
    app.include_router(bi_export.router)

    # Coder worklist / review queue
    app.include_router(coder_worklist.router)

    # Provider worklist — prioritized patient lists and action items
    app.include_router(provider_worklist_router.router)

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
    app.include_router(data_quality_router.router)
