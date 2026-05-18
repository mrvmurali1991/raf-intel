export interface Patient {
  /** Numeric primary key — the backend aliases `id` as `pid`. May be number or string. */
  id?: string | number;
  pid: string | number;
  /** Backend returns fname/lname; first_name/last_name provided for legacy compat */
  first_name?: string;
  last_name?: string;
  fname?: string;
  lname?: string;
  /** Backend returns DOB (capitalised); dob is the lowercased variant */
  dob?: string;
  DOB?: string;
  age?: number;
  sex?: string;
  city?: string;
  state?: string;
  postal_code?: string;
  phone_cell?: string;
  phone_home?: string;
  gender?: string;
  race?: string;
  ethnicity?: string;
  language?: string;
  street?: string;
  insurance_type?: string;
  hcc_count?: number;
  provider_name?: string;
  /** May be null when patient has not yet been scored */
  raf_score?: number | null;
  demographic_score?: number | null;
  disease_score?: number | null;
  interaction_score?: number | null;
  data_source?: string;
  /** Medical Record Number — present when the patient was imported from an EMR. */
  mrn?: string;
  raf_score_history?: RAFScoreEntry[];
  hcc_codes?: HCCCode[];
  suspects?: SuspectCondition[];
  encounters?: Encounter[];
  meat_status?: MEATStatus;
}

export interface RAFScoreEntry {
  year: number;
  score: number;
}

export interface HCCCode {
  id: string;
  code: string;
  label: string;
  coefficient: number;
  icd10_sources: string[];
  meat_status: "complete" | "partial" | "missing";
  meat_evidence?: MEATEvidence;
}

export interface MEATEvidence {
  monitor: string | null;
  evaluate: string | null;
  assess: string | null;
  treat: string | null;
  raw_note_excerpt?: string | null;
}

export interface MEATStatus {
  complete: number;
  partial: number;
  missing: number;
  total: number;
  compliance_pct: number;
}

export interface SuspectCondition {
  id: string;
  patient_id: string;
  patient_name?: string;
  condition: string;
  icd10_code: string;
  hcc_code: string;
  confidence: number;
  evidence: string;
  status: "open" | "accepted" | "dismissed" | "coded";
  source?: string;
  created_at?: string;
}

export interface Encounter {
  id: string;
  patient_id: string;
  date: string;
  provider: string;
  type: string;
  diagnoses: string[];
  notes?: string;
  analyzed: boolean;
}

/** One fired interaction term returned by the RAF calculation service. */
export interface InteractionDetail {
  /** Interaction term identifier, e.g. "HCC18_HCC85". */
  term: string;
  /** Rounded coefficient contribution. */
  coefficient: number;
  /** Human-readable label for display. */
  description: string;
}

/** Shape returned by the review_queue service (review_queue.py → route_for_review). */
export interface ReviewQueueResult {
  auto_accept: ReviewQueueEntry[];
  needs_review: ReviewQueueEntry[];
  reject: ReviewQueueEntry[];
  review_summary: {
    total: number;
    auto_accept_count: number;
    needs_review_count: number;
    reject_count: number;
    estimated_review_time_minutes: number;
    encounter_quality_score: number | null;
  };
}

export interface ReviewQueueEntry {
  icd10: string;
  description: string;
  hcc: string | null;
  hcc_weight?: number;
  confidence: number;
  confidence_label: string;
  stage1_found: boolean;
  stage2_found: boolean;
  stage3_restored: boolean;
  meat_score: number;
  routing: "auto_accept" | "needs_review" | "reject";
  review_flags: string[];
  review_notes: string[];
}

export interface AnalysisResult {
  encounter_id?: number;
  pid?: number;
  patient_id?: number;
  encounter_date?: string;
  diagnoses: AIDiagnosis[];
  suspect_conditions: AISuspect[];
  negated_conditions: (string | { description: string; icd10?: string; reason?: string })[];
  coding_notes: string;
  error?: string;
  pipeline?: {
    tool_calls?: { function: string; args: any; result: any }[];
    medcat_entities?: any[];
    after_negation_filter?: any[];
    candidate_codes?: any[];
    timings?: Record<string, number>;
    llm_input?: any;
    note_chars_submitted?: number;
    note_chars_original?: number;
  };
  overall_confidence?: number;
  confidence_routing?: unknown;
  /** Populated by review_queue service on the backend; present in fresh pipeline responses. */
  review_queue?: ReviewQueueResult | null;
  /** Structured per-interaction breakdown; returned by skill_pipeline RAF calculation. */
  interaction_details?: InteractionDetail[];
  _meta?: {
    model?: string;
    pipeline_version?: string;
    patient_age?: number;
    patient_sex?: string;
    total_time_seconds?: number;
    tool_calls_count?: number;
    turns?: number;
    timings?: Record<string, number>;
    stages?: string[];
  };
  /** Whether this result was served from the server-side cache. */
  _cached?: boolean;
  verification?: unknown;
}

export interface AIDiagnosis {
  /** Legacy field name (old pipeline) */
  condition?: string;
  /** Skill pipeline field name */
  description?: string;
  /** Alternative field name */
  diagnosis?: string;
  /** Alternative code field */
  code?: string;
  /** Skill pipeline: icd10; legacy: icd10_code */
  icd10?: string;
  icd10_code?: string;
  icd10_description?: string;
  icd10_valid?: boolean;
  /** Skill pipeline: hcc; legacy: hcc_code */
  hcc?: string | null;
  hcc_code?: string | null;
  hcc_weight?: number;
  hcc_mapping?: { hcc_code?: string; coefficient?: number } | null;
  confidence: number;
  confidence_score?: number;
  negated: boolean;
  historical: boolean;
  family_history?: boolean;
  meat_evidence?: MEATEvidence;
  meat: {
    M?: string;
    E?: string;
    A?: string;
    T?: string;
    monitoring?: string;
    evaluation?: string;
    assessment?: string;
    treatment?: string;
  };
  meat_score: number;
  supporting_text: string;
  source?: string;
}

export interface AISuspect {
  condition?: string;
  /** Skill pipeline: rationale; legacy: evidence */
  rationale?: string;
  evidence?: string;
  evidence_type?: string;
  /** Skill pipeline: icd10_code; legacy: suspect_icd10 */
  icd10_code?: string;
  icd10?: string;
  suspect_icd10?: string;
  /** Skill pipeline: hcc_code; legacy: suspect_hcc */
  hcc_code?: string | null;
  suspect_hcc?: string | null;
  /** Skill pipeline: confidence_score; legacy: confidence */
  confidence_score?: number;
  confidence?: number;
  code_valid?: boolean;
  code_description?: string | null;
  hcc_mapping?: { hcc_code?: string; coefficient?: number } | null;
}

/** Legacy type kept for backward compat */
export interface ExtractedDiagnosis {
  icd10_code: string;
  description: string;
  confidence: number;
  hcc_code?: string;
  supporting_text: string;
}

/** Backend suspect from raf_suspect_conditions table */
export interface DBSuspect {
  id: number;
  patient_id: number;
  patient_name?: string;
  measurement_year?: number;
  suspect_hcc: number;
  suspect_icd10: string;
  evidence_type: string;
  evidence_detail?: any;
  confidence_score: number;
  /** Raw (uncalibrated) confidence — same as confidence_score. Populated by backend serializer. */
  raw_confidence?: number;
  /** Platt-calibrated probability in [0,1]. Falls back to raw_confidence when
   *  the calibration feature flag is off or no model artifact exists. */
  calibrated_confidence?: number;
  status: "open" | "accepted" | "dismissed" | "coded";
  reviewed_by?: string;
  reviewed_at?: string;
  created_at?: string;
  updated_at?: string;
  // Enriched fields from connector
  suspected_condition?: string;
  trigger_type?: string;
  trigger_value?: string;
}

export interface AuditPackage {
  id: number;
  pid: number;
  patient_name?: string;
  year: number;
  filepath?: string;
  file_size_bytes?: number;
  created_at: string;
  download_url?: string;
  // Legacy fields for backward compat
  status?: "ready" | "generating" | "error";
  hcc_count?: number;
  raf_score?: number;
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
  pipeline?: Record<string, unknown>;
}

export interface RAFDistributionBucket {
  range: string;
  count: number;
}

export interface PatientSummary {
  id: string;
  pid: string;
  name: string;
  raf_score: number;
  suspect_count: number;
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
  error?: boolean;
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
// Revenue Opportunity  —  GET /api/reports/revenue-opportunity
// ---------------------------------------------------------------------------

export interface RevenueOpportunityReport {
  measurement_year: number;
  total_patients_analyzed: number;
  total_patients?: number;
  total_billing_raf: number;
  total_ai_raf: number;
  total_gap: number;
  estimated_annual_revenue: number;
  average_raf_score: number;
  /** Backend _meta block — formula provenance for CFO tooltip */
  _meta?: import("@/lib/api").MetricMeta;
}

export interface JobStatusResponse {
  job_id: string;
  status: "queued" | "running" | "completed" | "failed";
  processed?: number;
  total?: number;
  error?: string;
  result?: any;
}
