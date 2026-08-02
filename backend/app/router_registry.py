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
from app.routers import bulk_ingest as bulk_ingest_router
from app.routers import cds_hooks as cds_hooks_router
from app.routers import clinical_queries as clinical_queries_router
from app.routers import cohorts_v2 as cohorts_v2_router
from app.routers import config as config_router
from app.routers import disputes as disputes_router
from app.routers import edi_generation as edi_generation_router
from app.routers import edps_feedback as edps_feedback_router
from app.routers import feature_flags as feature_flags_router
from app.routers import forecast as forecast_router
from app.routers import hcc_gap_drilldown as hcc_gap_drilldown_router
from app.routers import hcc_removal as hcc_removal_router
from app.routers import hedis as hedis_router
from app.routers import meat_audit_risk as meat_audit_risk_router
from app.routers import peer_benchmarking as peer_benchmarking_router
from app.routers import previsit_briefing as previsit_briefing_router
from app.routers import md_today as md_today_router
from app.routers import outreach_v2 as outreach_v2_router
from app.routers import chart_chase_v2 as chart_chase_v2_router
from app.routers import fhir_circuit_health as fhir_circuit_health_router
from app.routers import fhir_writeback_async as fhir_writeback_async_router
from app.routers import soc2_evidence as soc2_evidence_router
from app.routers import hcc_evidence as hcc_evidence_router
from app.routers import openemr_doc_ingest as openemr_doc_ingest_router
from app.routers import provider_pdf_report as provider_pdf_report_router
from app.routers import provider_revenue_breakdown as provider_revenue_breakdown_router
from app.routers import provider_scorecards as provider_scorecards_router
from app.routers import provider_trends as provider_trends_router
from app.routers import top_hcc_opportunities as top_hcc_opportunities_router
from app.routers import coder_analytics as coder_analytics_router
from app.routers import v28_impact as v28_impact_router
from app.routers import consent as consent_router
from app.routers import dashboard as dashboard_router
from app.routers import dashboard_analytics as dashboard_analytics_router
from app.routers import data_quality as data_quality_router
from app.routers import population_heatmap as population_heatmap_router
from app.routers import health as health_router
from app.routers import icd10 as icd10_router
from app.routers import insights as insights_router
from app.routers import meat as meat_router
from app.routers import meat_evidence as meat_evidence_router
from app.routers import nlp_extract as nlp_extract_router
from app.routers import patient_activity as patient_activity_router
from app.routers import pipeline as pipeline_router
from app.routers import pipeline_settings as pipeline_settings_router
from app.routers import provider_suspect_hotlist as provider_suspect_hotlist_router
from app.routers import provider_worklist as provider_worklist_router
from app.routers import worklist as worklist_bulk_router
from app.routers import radv as radv_router
from app.routers import radv_audit as radv_audit_router
from app.routers import radv_audit_runs as radv_audit_runs_router
from app.routers import radv_chart_requests as radv_chart_requests_router
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
from app.routers import qa_reviews as qa_reviews_router
from app.routers import review as review_router
from app.routers import smart_fhir as smart_fhir_router
from app.routers import suspect_feedback as suspect_feedback_router
from app.routers import pre_submission as pre_submission_router
from app.routers import tenant_branding as tenant_branding_router
from app.routers import encryption_admin as encryption_admin_router
from app.routers import hie_sync as hie_sync_router
from app.routers import hl7v2_mdm_receiver as hl7v2_mdm_receiver_router
from app.routers import tenant_doc_policy as tenant_doc_policy_router
from app.routers import inovalon_admin as inovalon_admin_router
from app.routers import fhir_bulk_export as fhir_bulk_export_router
from app.routers import datavant_admin as datavant_admin_router
from app.routers import datavant_webhook as datavant_webhook_router
from app.routers import reveleer_admin as reveleer_admin_router
from app.routers import direct_inbound as direct_inbound_router
from app.routers import document_ingestion_dashboard as document_ingestion_dashboard_router
from app.routers import demo_info as demo_info_router
from app.routers import demo_reset as demo_reset_router
from app.routers import goals as goals_router
from app.routers import ehr_writeback as ehr_writeback_router
from app.routers import hcc_rejections as hcc_rejections_router


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
    _mount(app, pre_submission_router.router)
    _mount(app, bundles.router)
    _mount(app, cms_transmission.router)
    _mount(app, edi_generation_router.router)

    # Integrations
    _mount(app, fhir.router)
    _mount(app, smart_fhir_router.router)
    # Public SMART 2.0 launch sequence (issuer-side) — mounted at /smart, no /api prefix.
    _mount(app, smart_fhir_router.public_router)
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
    _mount(app, v28_impact_router.router)
    _mount(app, provider_revenue_breakdown_router.router)
    _mount(app, meat_audit_risk_router.router)
    _mount(app, hcc_gap_drilldown_router.router)
    _mount(app, previsit_briefing_router.router)
    _mount(app, md_today_router.router)
    _mount(app, outreach_v2_router.router)
    _mount(app, outreach_v2_router.webhook_router)
    _mount(app, chart_chase_v2_router.router)
    _mount(app, fhir_circuit_health_router.router)
    _mount(app, fhir_writeback_async_router.router)
    _mount(app, soc2_evidence_router.router)
    _mount(app, hcc_evidence_router.router)
    _mount(app, openemr_doc_ingest_router.router)
    _mount(app, provider_pdf_report_router.router)
    _mount(app, provider_scorecards_router.router)
    _mount(app, feature_flags_router.router)
    _mount(app, quality.router)
    _mount(app, hedis_router.router)
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
    # NLP-based HCC suspect extractor (Gemini, single-note synchronous API)
    _mount(app, nlp_extract_router.router)
    _mount(app, awv.router)

    # Visual cohort builder v2 (drag-and-drop UI) — independent table & API.
    # Must mount BEFORE legacy cohorts router because /api/cohorts/{cohort_id}
    # in the legacy router would otherwise shadow /api/cohorts/v2 (FastAPI
    # matches in registration order — first match wins).
    _mount(app, cohorts_v2_router.router)
    # Population health cohort analysis (legacy)
    _mount(app, cohorts.router)

    # Population geographic heat-map (per-ZIP risk + gap clusters)
    _mount(app, population_heatmap_router.router)

    # Operations and compliance
    _mount(app, jobs.router)
    _mount(app, pipeline_router.router)
    _mount(app, pipeline_settings_router.router)
    _mount(app, config_router.router)
    _mount(app, reports.router)
    _mount(app, dashboard_router.router)
    _mount(app, dashboard_analytics_router.router)
    _mount(app, coder_analytics_router.router)
    _mount(app, audit.router)

    # Compliance — consent management
    _mount(app, consent_router.router)

    # BI Tools Export
    _mount(app, bi_export.router)

    # Provider worklist — prioritized patient lists and action items.
    # NOTE: must be mounted BEFORE coder_worklist because both use the
    # /api/worklist prefix and coder_worklist has a /{item_id} catch-all
    # that would shadow /summary, /provider, and /provider-workload otherwise.
    _mount(app, provider_worklist_router.router)

    # Coder worklist / review queue
    _mount(app, coder_worklist.router)
    _mount(app, review_router.router)

    # Worklist bulk-select chip bar actions
    _mount(app, bulk_actions_router.router)

    # Bulk FHIR ingest (panel onboarding from $export or NDJSON upload)
    _mount(app, bulk_ingest_router.router)

    # Multi-rater QA review workflow (Reveleer-style dual review)
    _mount(app, qa_reviews_router.router)

    # Worklist bulk actions — bulk-attest, bulk-export
    _mount(app, worklist_bulk_router.router)

    # Real-time suspect hot-list (provider drawer "action this week")
    _mount(app, provider_suspect_hotlist_router.router)

    # Real-time clinical intelligence insights
    _mount(app, insights_router.router)

    # Real-time dashboards
    _mount(app, realtime_router.router)

    # Health and info
    _mount(app, health_router.router)
    _mount(app, icd10_router.router)

    # CDS Hooks integration (Apixio Apicare / ForeSee Vim pattern).
    # Mounted at the app root — the CDS Hooks 2.0 spec mandates the literal
    # /cds-services discovery path, so this router intentionally bypasses the
    # /api/... prefix used by every other surface. Registered directly via
    # app.include_router so the routes appear in the OpenAPI schema.
    app.include_router(cds_hooks_router.router)

    # Admin
    _mount(app, retention.router)
    _mount(app, admin.router)
    # HIE (CommonWell + Carequality) admin sync
    _mount(app, hie_sync_router.router)
    # HL7 v2 MDM HTTP receiver
    _mount(app, hl7v2_mdm_receiver_router.router)
    # Per-tenant OCR / LLM document policy (42 CFR Part 2)
    _mount(app, tenant_doc_policy_router.router)
    # Inovalon Electronic Record On Demand
    _mount(app, inovalon_admin_router.router)
    # FHIR Bulk Data $export client
    _mount(app, fhir_bulk_export_router.router)
    # Datavant Switchboard
    _mount(app, datavant_admin_router.router)
    _mount(app, datavant_webhook_router.router)
    # Reveleer bi-directional
    _mount(app, reveleer_admin_router.router)
    # Direct Trust + C-CDA inbound
    _mount(app, direct_inbound_router.router)
    # Document Ingestion Dashboard
    _mount(app, document_ingestion_dashboard_router.router)
    _mount(app, meat_router.router)
    _mount(app, meat_evidence_router.router)
    _mount(app, radv_audit_router.router)
    # RADV mock-audit defense workflow (Gap #3) — sampler, decisions,
    # exposure simulator, MAO-004 re-submission batch, evidence export.
    # Shares /api/radv prefix with radv_audit but owns /audit-runs/* paths.
    _mount(app, radv_audit_runs_router.router)
    # RADV chart-request tracking — CMS-mandated workflow (Gap: chart pull docs).
    _mount(app, radv_chart_requests_router.router)
    # RADV packet PDF export (per-patient, per-payment-year audit bundle).
    # Shares the /api/radv prefix with radv_audit but owns distinct paths.
    _mount(app, radv_router.router)
    _mount(app, data_quality_router.router)
    _mount(app, raf_inbox_admin_router.router)

    # Tenant co-branding (per-tenant color + logo text)
    _mount(app, tenant_branding_router.router)

    # Encryption key management (KMS BYOK)
    _mount(app, encryption_admin_router.router)

    # Public demo info + ROI calculator (no auth required)
    _mount(app, demo_info_router.router)

    # Executive demo mode (reset + live stats + NLP suspects for /admin/demo)
    _mount(app, demo_reset_router.router)

    # Quarterly RAF capture goals (goal-vs-actual tracking)
    _mount(app, goals_router.router)

    # EHR Problem List write-back queue (SMART-on-FHIR Condition stub)
    _mount(app, ehr_writeback_router.router)

    # HCC Rejections — two-way coding audit (DOJ-compliant, Reveleer 2026)
    _mount(app, hcc_rejections_router.router)
