export interface Patient {
  id: string;
  pid: string;
  first_name: string;
  last_name: string;
  fname?: string;
  lname?: string;
  dob: string;
  age: number;
  sex: string;
  raf_score: number;
  raf_score_history?: RAFScoreEntry[];
  hcc_codes: HCCCode[];
  suspects: SuspectCondition[];
  encounters: Encounter[];
  meat_status: MEATStatus;
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
  status: "open" | "accepted" | "dismissed";
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

export interface AnalysisResult {
  encounter_id?: number;
  pid?: number;
  patient_id?: number;
  encounter_date?: string;
  diagnoses: GeminiDiagnosis[];
  suspect_conditions: GeminiSuspect[];
  negated_conditions: (string | { description: string; icd10?: string; reason?: string })[];
  coding_notes: string;
  error?: string;
  pipeline?: {
    tool_calls?: { function: string; args: Record<string, unknown>; result: Record<string, unknown> }[];
    medcat_entities?: Record<string, unknown>[];
    after_negation_filter?: Record<string, unknown>[];
    candidate_codes?: Record<string, unknown>[];
    timings?: Record<string, number>;
  };
  overall_confidence?: number;
  confidence_routing?: Record<string, unknown>;
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
}

export interface GeminiDiagnosis {
  /** Legacy field name (old pipeline) */
  condition?: string;
  /** Skill pipeline field name */
  description?: string;
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
  negated: boolean;
  historical: boolean;
  family_history?: boolean;
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

export interface GeminiSuspect {
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
  evidence_detail?: Record<string, unknown>;
  confidence_score: number;
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
  average_raf_score: number;
  total_suspects_open: number;
  meat_compliance_pct: number;
  raf_distribution: RAFDistributionBucket[];
  top_undercoded: PatientSummary[];
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
