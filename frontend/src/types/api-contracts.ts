/**
 * Canonical API response types for RAF Intelligence.
 *
 * This is the SINGLE SOURCE OF TRUTH for all API field names on the frontend.
 * Backend Pydantic models in backend/app/schemas/api_contracts.py must mirror
 * these exactly.
 *
 * Naming conventions:
 *   - snake_case for all fields (matching backend JSON)
 *   - IDs are always number (never string for numeric IDs)
 *   - Scores use `_score` suffix: `average_raf_score`, `disease_score`
 *   - Counts use descriptive names: `total_patients`, `patients_analyzed`
 *   - Booleans use `is_` prefix: `is_active`, `is_demo`
 *   - Dates are ISO-8601 strings
 */

// ---------------------------------------------------------------------------
// Dashboard Stats  —  GET /api/dashboard/stats
// ---------------------------------------------------------------------------

export interface RAFDistributionBucket {
  range: string;
  count: number;
}

export interface PatientSummary {
  id: number;
  pid: number;
  name: string;
  raf_score: number;
  suspect_count: number;
}

export interface DashboardStats {
  total_patients: number;
  patients_analyzed: number;
  average_raf_score: number;
  coverage_pct: number;
  total_suspects_open: number;
  meat_compliance_pct: number;
  raf_distribution: RAFDistributionBucket[];
  top_undercoded: PatientSummary[];
  pipeline?: PipelineBlock;
}

export interface PipelinePhase {
  name: string;
  status: string;
}

export interface PipelineBlock {
  mode: string;
  ai_analysis_enabled: boolean;
  last_run?: Record<string, unknown>;
  phases: PipelinePhase[];
}

// ---------------------------------------------------------------------------
// Dashboard Trends  —  GET /api/dashboard/trends
// ---------------------------------------------------------------------------

export interface TrendMetric {
  current: number;
  previous: number;
  change_pct: number | null;
}

export interface DashboardTrends {
  period: string;
  patients_analyzed?: TrendMetric;
  average_raf_score?: TrendMetric;
}

// ---------------------------------------------------------------------------
// Population Summary  —  GET /api/raf/population-summary
// ---------------------------------------------------------------------------

export interface HCCSummary {
  hcc: string;
  label: string;
  count: number;
}

export interface PopulationSummary {
  year: number;
  total_patients: number;
  patients_with_scores: number;
  average_raf_score: number;
  median_raf_score: number;
  patients_with_gaps: number;
  hcc_capture_rate: number;
  total_revenue_opportunity: number;
  raf_distribution: RAFDistributionBucket[];
  top_hccs: HCCSummary[];
  blend_weights?: Record<string, number>;
  score_type_breakdown?: Record<string, number>;
}

// ---------------------------------------------------------------------------
// Revenue Opportunity  —  GET /api/reports/revenue-opportunity
// ---------------------------------------------------------------------------

export interface RevenueOpportunityReport {
  measurement_year: number;
  total_patients_analyzed: number;
  total_billing_raf: number;
  total_ai_raf: number;
  total_gap: number;
  estimated_annual_revenue: number;
  average_raf_score: number;
}

// ---------------------------------------------------------------------------
// EMR Status  —  GET /api/emr/status
// ---------------------------------------------------------------------------

export interface EmrStatus {
  connected: boolean;
  vendor?: string;
  is_demo?: boolean;
  connection_count?: number;
  display_name?: string;
}

// ---------------------------------------------------------------------------
// Data Completeness  —  GET /api/reports/data-completeness
// ---------------------------------------------------------------------------

export interface DataCompleteness {
  completeness_score: number;
  total_patients: number;
  patients_with_billing: number;
  patients_with_problems: number;
  patients_with_clinical_notes: number;
  patients_with_vitals: number;
  patients_with_immunizations: number;
  patients_with_insurance: number;
}

// ---------------------------------------------------------------------------
// Workflow Summary  —  GET /api/reports/workflow-summary
// ---------------------------------------------------------------------------

export interface WorkflowSummary {
  open_suspects: number;
  high_confidence_suspects: number;
  patients_unanalyzed: number;
  patients_total: number;
  recent_analyses_7d: number;
  providers_active: number;
  avg_confidence: number;
  last_sync_at?: string;
  last_analysis_at?: string;
}

// ---------------------------------------------------------------------------
// Provider Summary  —  GET /api/providers/summary
// ---------------------------------------------------------------------------

export interface ProviderSummary {
  measurement_year: number;
  total_providers: number;
  total_active_providers: number;
  total_attributed_patients: number;
  average_raf_score: number;
  avg_capture_rate: number;
  total_revenue_opportunity: number;
  avg_meat_completeness: number;
}
