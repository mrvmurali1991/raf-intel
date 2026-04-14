/**
 * API response types for RAF Intelligence.
 *
 * Types shared with the rest of the frontend are re-exported from `@/types`
 * (the single source of truth). Only types that are specific to the API
 * contract layer (and not used elsewhere) are defined here.
 *
 * Naming conventions:
 *   - snake_case for all fields (matching backend JSON)
 *   - IDs are always number (never string for numeric IDs)
 *   - Scores use `_score` suffix: `average_raf_score`, `disease_score`
 *   - Counts use descriptive names: `total_patients`, `patients_analyzed`
 *   - Booleans use `is_` prefix: `is_active`, `is_demo`
 *   - Dates are ISO-8601 strings
 */

// Re-export shared types from the canonical source so consumers that import
// from "@/types/api-contracts" continue to work without changes.
export type {
  RAFDistributionBucket,
  PatientSummary,
  DashboardStats,
  TrendMetric,
  DashboardTrends,
  HCCSummary,
  PopulationSummary,
  DataCompleteness,
  RevenueOpportunityReport,
} from "@/types";

// ---------------------------------------------------------------------------
// Dashboard Stats pipeline block — only used in api-contracts context
// ---------------------------------------------------------------------------

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
