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
import copy

from fastapi import APIRouter, FastAPI

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
from app.routers import bulk_actions as bulk_actions_router
from app.routers import clinical_queries as clinical_queries_router
from app.routers import config as config_router
from app.routers import disputes as disputes_router
from app.routers import edps_feedback as edps_feedback_router
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
from app.routers import patient_activity as patient_activity_router
from app.routers import pipeline as pipeline_router
from app.routers import pipeline_settings as pipeline_settings_router
from app.routers import provider_suspect_hotlist as provider_suspect_hotlist_router
from app.routers import provider_worklist as provider_worklist_router
from app.routers import radv as radv_router
from app.routers import radv_audit as radv_audit_router
from app.routers import raf_central as raf_central_router
from app.routers import raf_inbox_admin as raf_inbox_admin_router
from app.routers import realtime as realtime_router
from app.routers import recapture_ai_recoding as recapture_ai_recoding_router
from app.routers import recapture_audit as recapture_audit_router
# Knowledge Graph routers
from app.routers import knowledge_graph as knowledge_graph_router
from app.routers import snomed_mapping as snomed_mapping_router
from app.routers import loinc_signals as loinc_signals_router
from app.routers import atc_classification as atc_classification_router
from app.routers import polypharmacy as polypharmacy_router
from app.routers import comorbidity_patterns as comorbidity_patterns_router
from app.routers import demographic_risk as demographic_risk_router
from app.routers import specialty_priors as specialty_priors_router
from app.routers import evidence_rules as evidence_rules_router
from app.routers import kg_query as kg_query_router
from app.routers import suspect_kg as suspect_kg_router
from app.routers import recapture_bonus as recapture_bonus_router
from app.routers import recapture_campaigns as recapture_campaigns_router
from app.routers import recapture_cfo_forecast as recapture_cfo_forecast_router
from app.routers import recapture_close as recapture_close_router
from app.routers import recapture_decay as recapture_decay_router
from app.routers import recapture_gaps as recapture_gaps_router
from app.routers import recapture_outreach as recapture_outreach_router
from app.routers import recapture_provider_benchmark as recapture_provider_benchmark_router
from app.routers import recapture_readiness as recapture_readiness_router
from app.routers import recapture_recurring as recapture_recurring_router
from app.routers import review as review_router
from app.routers import smart_fhir as smart_fhir_router
from app.routers import suspect_feedback as suspect_feedback_router


# ---------------------------------------------------------------------------
# /api/v1 dual-mount helper
# ---------------------------------------------------------------------------
#
# The codebase exposes endpoints under /api/<resource>/... (legacy prefix).
# API_CHANGELOG documents a /api/v1/<resource>/... namespace that was never
# wired up. To avoid breaking any existing client, we mount every router
# twice:
#
#   1. Under its native /api/<resource> prefix — kept for backward compat,
#      hidden from the OpenAPI schema to prevent duplicate entries.
#   2. Under /api/v1/<resource> — visible in the OpenAPI schema as the
#      canonical, versioned surface.
#
# A small helper handles both registrations so we don't copy-paste 100+
# include_router calls.


def _v1_router_of(router: APIRouter) -> APIRouter:
    """
    Return a shallow copy of *router* whose prefix is rewritten from
    ``/api/<name>`` to ``/api/v1/<name>``.

    The original router is left untouched (it remains mounted under its
    native prefix for backward compatibility).
    """
    v1 = copy.copy(router)
    # Rewrite /api/... -> /api/v1/...  (leave anything not starting with
    # /api alone so health/info etc. keep working).
    if router.prefix.startswith("/api/"):
        v1.prefix = "/api/v1/" + router.prefix[len("/api/"):]
    elif router.prefix == "/api":
        v1.prefix = "/api/v1"
    else:
        v1.prefix = router.prefix  # nothing to rewrite
    return v1


def _mount(app: FastAPI, router: APIRouter) -> None:
    """
    Mount *router* twice:

      - At its native prefix with ``include_in_schema=False`` so the legacy
        path is still served but does not double up the OpenAPI document.
      - At the rewritten ``/api/v1/...`` prefix, visible in the schema as
        the canonical versioned surface.
    """
    # Legacy mount — keep working for existing clients, hide from schema.
    app.include_router(router, include_in_schema=False)
    # Versioned mount — visible in OpenAPI as the canonical surface.
    if router.prefix.startswith("/api"):
        app.include_router(_v1_router_of(router))


def register_routers(app: FastAPI) -> None:
    """Mount all application routers on *app*."""

    # Auth must come first (other routers depend on it for token issuance)
    _mount(app, auth_router.router)

    # Core clinical entities
    _mount(app, patients.router)
    # Per-patient activity feed (PCP review #8 carry-over). Mounted under
    # the same /api/patients prefix as patients.router but owns the distinct
    # ``/{pid}/activity`` sub-path so there is no route collision.
    _mount(app, patient_activity_router.router)
    _mount(app, raf.router)
    _mount(app, raf_central_router.router)
    _mount(app, forecast_router.router)
    _mount(app, hcc_removal_router.router)
    _mount(app, disputes_router.router)
    # CMS MAO-004 / EDPS response ingest — feeds accepted_raf into the
    # RAF Central financial_impact block consumed by RAFReconciliationCard.
    _mount(app, edps_feedback_router.router)
    _mount(app, clinical_queries_router.router)
    _mount(app, analysis.router)
    _mount(app, suspects.router)
    _mount(app, suspect_feedback_router.router)
    _mount(app, attestations.router)
    _mount(app, chart_chase.router)
    _mount(app, documents.router)
    _mount(app, ccda.router)
    _mount(app, uploads.router)

    # Payer / claims workflows
    _mount(app, claims.router)
    _mount(app, submissions.router)
    _mount(app, bundles.router)
    _mount(app, cms_transmission.router)

    # Integrations
    _mount(app, fhir.router)
    _mount(app, smart_fhir_router.router)
    _mount(app, emr.router)
    _mount(app, adt.router)
    _mount(app, webhooks.router)
    _mount(app, notifications.router)
    _mount(app, direct_messaging.router)
    _mount(app, clearinghouse.router)

    # Provider and quality management
    # NOTE: peer_benchmarking is registered BEFORE providers.router so that
    # the literal /api/providers/specialty-benchmarks path matches before the
    # /api/providers/{id} catch-all.
    _mount(app, peer_benchmarking_router.router)
    _mount(app, provider_trends_router.router)  # /api/providers/trend-aggregate before /{id}/trend
    _mount(app, providers.router)
    _mount(app, top_hcc_opportunities_router.router)
    _mount(app, provider_revenue_breakdown_router.router)
    _mount(app, meat_audit_risk_router.router)
    _mount(app, hcc_gap_drilldown_router.router)
    _mount(app, previsit_briefing_router.router)
    _mount(app, provider_pdf_report_router.router)
    _mount(app, feature_flags_router.router)
    _mount(app, quality.router)
    _mount(app, prospective.router)
    _mount(app, benchmarks.router)
    _mount(app, care_gaps.router)
    _mount(app, recapture_gaps_router.router)
    _mount(app, recapture_decay_router.router)
    _mount(app, recapture_provider_benchmark_router.router)
    _mount(app, recapture_audit_router.router)
    _mount(app, recapture_campaigns_router.router)
    _mount(app, recapture_outreach_router.router)
    _mount(app, recapture_bonus_router.router)
    _mount(app, recapture_cfo_forecast_router.router)
    _mount(app, recapture_readiness_router.router)
    _mount(app, recapture_recurring_router.router)
    _mount(app, recapture_close_router.router)

    # Knowledge Graph (closes the Navina-style "we use a knowledge graph" gap)
    _mount(app, knowledge_graph_router.router)
    _mount(app, snomed_mapping_router.router)
    _mount(app, loinc_signals_router.router)
    _mount(app, atc_classification_router.router)
    _mount(app, polypharmacy_router.router)
    _mount(app, comorbidity_patterns_router.router)
    _mount(app, demographic_risk_router.router)
    _mount(app, specialty_priors_router.router)
    _mount(app, evidence_rules_router.router)
    _mount(app, kg_query_router.router)
    _mount(app, suspect_kg_router.router)
    _mount(app, recapture_ai_recoding_router.router)
    _mount(app, awv.router)

    # Population health cohort analysis
    _mount(app, cohorts.router)

    # Operations and compliance
    _mount(app, jobs.router)
    _mount(app, pipeline_router.router)
    _mount(app, pipeline_settings_router.router)
    _mount(app, config_router.router)
    _mount(app, reports.router)
    _mount(app, dashboard_analytics_router.router)
    _mount(app, audit.router)

    # Compliance — consent management
    _mount(app, consent_router.router)

    # BI Tools Export
    _mount(app, bi_export.router)

    # Coder worklist / review queue
    _mount(app, coder_worklist.router)
    _mount(app, review_router.router)

    # Worklist bulk-select chip bar actions
    _mount(app, bulk_actions_router.router)

    # Provider worklist — prioritized patient lists and action items
    _mount(app, provider_worklist_router.router)

    # Real-time suspect hot-list (provider drawer "action this week")
    _mount(app, provider_suspect_hotlist_router.router)

    # Real-time clinical intelligence insights
    _mount(app, insights_router.router)

    # Real-time dashboards
    _mount(app, realtime_router.router)

    # Health and info
    _mount(app, health_router.router)
    _mount(app, icd10_router.router)

    # Admin
    _mount(app, retention.router)
    _mount(app, admin.router)
    _mount(app, meat_router.router)
    _mount(app, radv_audit_router.router)
    # RADV packet PDF export (per-patient, per-payment-year audit bundle).
    # Shares the /api/radv prefix with radv_audit but owns distinct paths.
    _mount(app, radv_router.router)
    _mount(app, data_quality_router.router)
    _mount(app, raf_inbox_admin_router.router)
