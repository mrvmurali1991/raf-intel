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

from pydantic import BaseModel, Field
from typing import Optional


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
    current_step: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    error_message: Optional[str] = None


class PipelineBlock(BaseModel):
    mode: str  # auto_ai | auto_basic | manual
    ai_analysis_enabled: bool = False
    last_run: Optional[PipelineLastRun] = None
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
    pipeline: Optional[dict] = None


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
    patients_analyzed: Optional[TrendMetric] = None
    average_raf_score: Optional[TrendMetric] = None


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
    blend_weights: Optional[dict] = None
    score_type_breakdown: Optional[dict] = None


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
    age: Optional[int] = None
    race: Optional[str] = None
    ethnicity: Optional[str] = None
    language: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None
    phone_cell: Optional[str] = None
    email: Optional[str] = None
    mrn: Optional[str] = None
    insurance_type: Optional[str] = None
    raf_score: Optional[float] = None
    hcc_count: int = 0
    demographic_score: Optional[float] = None
    disease_score: Optional[float] = None
    interaction_score: Optional[float] = None
    provider_name: Optional[str] = None
    data_source: Optional[str] = None


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
    vendor: Optional[str] = None
    is_demo: bool = False
    connection_count: int = 0
    display_name: Optional[str] = None


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
    suspect_id: Optional[int] = None
    patient_id: int
    patient_name: Optional[str] = None
    icd10_code: str = ""
    hcc_code: Optional[str] = None
    description: Optional[str] = None
    confidence: float = 0.0
    evidence: Optional[str] = None
    evidence_type: Optional[str] = None
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
    last_sync_at: Optional[str] = None
    last_analysis_at: Optional[str] = None
