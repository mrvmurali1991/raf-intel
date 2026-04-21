"""
Canonical API response schemas for RAF Intelligence.

This is the SINGLE SOURCE OF TRUTH for all API field names.
Frontend TypeScript types in frontend/src/types/api-contracts.ts
must mirror these exactly.

Naming conventions:
  - snake_case for all fields
  - IDs are always int (never float, never string for numeric IDs)
  - Scores use `_score` suffix: `average_raf_score`, `disease_score`
  - Counts use descriptive names: `total_patients`, `patients_analyzed`
  - Booleans use `is_` prefix: `is_active`, `is_demo`
  - Dates are ISO-8601 strings
"""

from __future__ import annotations

from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Dashboard Stats  —  GET /api/dashboard/stats
# ---------------------------------------------------------------------------

class RAFDistributionBucket(BaseModel):
    range: str
    count: int


class PatientSummary(BaseModel):
    id: int
    pid: int
    name: str
    raf_score: float = 0.0
    suspect_count: int = 0


class PipelinePhase(BaseModel):
    name: str
    status: str  # completed | running | pending | failed


class PipelineLastRun(BaseModel):
    id: int
    status: str
    current_step: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    error_message: str | None = None


class PipelineBlock(BaseModel):
    mode: str  # auto_ai | auto_basic | manual
    ai_analysis_enabled: bool = False
    last_run: PipelineLastRun | None = None
    phases: list[PipelinePhase] = []


class DashboardStatsResponse(BaseModel):
    """GET /api/dashboard/stats"""
    total_patients: int = 0
    patients_analyzed: int = 0
    average_raf_score: float = 0.0
    coverage_pct: float = 0.0
    total_suspects_open: int = 0
    meat_compliance_pct: float = 0.0
    raf_distribution: list[RAFDistributionBucket] = []
    top_undercoded: list[PatientSummary] = []
    pipeline: dict | None = None


# ---------------------------------------------------------------------------
# Dashboard Trends  —  GET /api/dashboard/trends
# ---------------------------------------------------------------------------

class TrendMetric(BaseModel):
    current: float = 0.0
    previous: float = 0.0
    change_pct: float = 0.0


class DashboardTrendsResponse(BaseModel):
    """GET /api/dashboard/trends"""
    period: str = "30d"
    patients_analyzed: TrendMetric | None = None
    average_raf_score: TrendMetric | None = None


# ---------------------------------------------------------------------------
# Population Summary  —  GET /api/raf/population-summary
# ---------------------------------------------------------------------------

class HCCSummary(BaseModel):
    hcc: str
    label: str
    count: int


class PopulationSummaryResponse(BaseModel):
    """GET /api/raf/population-summary"""
    year: int
    total_patients: int = 0
    patients_with_scores: int = 0
    average_raf_score: float = 0.0
    median_raf_score: float = 0.0
    patients_with_gaps: int = 0
    hcc_capture_rate: float = 0.0
    total_revenue_opportunity: float = 0.0
    raf_distribution: list[RAFDistributionBucket] = []
    top_hccs: list[HCCSummary] = []
    blend_weights: dict | None = None
    score_type_breakdown: dict | None = None


# ---------------------------------------------------------------------------
# Revenue Opportunity  —  GET /api/reports/revenue-opportunity
# ---------------------------------------------------------------------------

class RevenueOpportunityResponse(BaseModel):
    """GET /api/reports/revenue-opportunity"""
    measurement_year: int
    total_patients_analyzed: int = 0
    total_billing_raf: float = 0.0
    total_ai_raf: float = 0.0
    total_gap: float = 0.0
    estimated_annual_revenue: float = 0.0
    average_raf_score: float = 0.0


# ---------------------------------------------------------------------------
# Patient  —  GET /api/patients, GET /api/patients/{pid}
# ---------------------------------------------------------------------------

class PatientResponse(BaseModel):
    """Single patient record."""
    pid: int
    first_name: str = ""
    last_name: str = ""
    dob: str = ""
    sex: str = ""
    age: int | None = None
    race: str | None = None
    ethnicity: str | None = None
    language: str | None = None
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None
    phone_cell: str | None = None
    email: str | None = None
    mrn: str | None = None
    insurance_type: str | None = None
    raf_score: float | None = None
    hcc_count: int = 0
    demographic_score: float | None = None
    disease_score: float | None = None
    interaction_score: float | None = None
    provider_name: str | None = None
    data_source: str | None = None


class PaginatedPatientsResponse(BaseModel):
    """GET /api/patients"""
    total: int = 0
    limit: int = 20
    offset: int = 0
    search: str = ""
    patients: list[dict] = []  # PatientResponse dicts


# ---------------------------------------------------------------------------
# EMR Status  —  GET /api/emr/status
# ---------------------------------------------------------------------------

class EmrStatusResponse(BaseModel):
    """GET /api/emr/status"""
    connected: bool = False
    vendor: str | None = None
    is_demo: bool = False
    connection_count: int = 0
    display_name: str | None = None


# ---------------------------------------------------------------------------
# Provider Summary  —  GET /api/providers/summary
# ---------------------------------------------------------------------------

class ProviderSummaryResponse(BaseModel):
    """GET /api/providers/summary"""
    measurement_year: int
    total_providers: int = 0
    total_active_providers: int = 0
    total_attributed_patients: int = 0
    average_raf_score: float = 0.0
    avg_capture_rate: float = 0.0
    total_revenue_opportunity: float = 0.0
    avg_meat_completeness: float = 0.0


# ---------------------------------------------------------------------------
# Suspects  —  GET /api/suspects
# ---------------------------------------------------------------------------

class SuspectResponse(BaseModel):
    """Single suspect condition."""
    suspect_id: int | None = None
    patient_id: int
    patient_name: str | None = None
    icd10_code: str = ""
    hcc_code: str | None = None
    description: str | None = None
    confidence: float = 0.0
    evidence: str | None = None
    evidence_type: str | None = None
    status: str = "open"


class SuspectsListResponse(BaseModel):
    """GET /api/suspects"""
    status_filter: str = "open"
    count: int = 0
    limit: int = 200
    offset: int = 0
    suspects: list[dict] = []


# ---------------------------------------------------------------------------
# Care Gaps  —  GET /api/care-gaps
# ---------------------------------------------------------------------------

class CareGapsListResponse(BaseModel):
    """GET /api/care-gaps"""
    count: int = 0
    limit: int = 200
    offset: int = 0
    tasks: list[dict] = []


# ---------------------------------------------------------------------------
# Data Completeness  —  GET /api/reports/data-completeness
# ---------------------------------------------------------------------------

class DataCompletenessResponse(BaseModel):
    """GET /api/reports/data-completeness"""
    completeness_score: float = 0.0
    total_patients: int = 0
    patients_with_billing: int = 0
    patients_with_problems: int = 0
    patients_with_clinical_notes: int = 0
    patients_with_vitals: int = 0
    patients_with_immunizations: int = 0
    patients_with_insurance: int = 0


# ---------------------------------------------------------------------------
# Workflow Summary  —  GET /api/reports/workflow-summary
# ---------------------------------------------------------------------------

class WorkflowSummaryResponse(BaseModel):
    """GET /api/reports/workflow-summary"""
    open_suspects: int = 0
    high_confidence_suspects: int = 0
    patients_unanalyzed: int = 0
    patients_total: int = 0
    recent_analyses_7d: int = 0
    providers_active: int = 0
    avg_confidence: float = 0.0
    last_sync_at: str | None = None
    last_analysis_at: str | None = None
