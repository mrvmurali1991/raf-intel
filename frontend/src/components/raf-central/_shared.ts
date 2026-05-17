/**
 * _shared.ts
 * Shared type definitions and constants used across raf-central subcomponents.
 * Mirrors backend response shape (see app/routers/raf_central.py).
 */

export interface LiveRAFBar {
  current: number;
  prior_year: number | null;
  delta: number | null;
  hcc_count: number;
  model_segment: string;
  model_version: string;
  year: number;
}

// gaps is intentionally Record<string, boolean> to mirror the backend
// GeneratedMEATGap shape — the API may emit additional keys (e.g. future
// MEAT-letter expansions). The four canonical keys monitor/evaluate/assess/
// treat are always present today; derive booleans defensively in render
// code with `gaps.monitor ?? false`.
export interface MEATGap {
  patient_hcc_id: number | null;
  hcc: string;
  icd10_codes: string[];
  label: string;
  coefficient: number;
  status: "COMPLETE" | "PARTIAL" | "MISSING" | "NOT_COMPLIANT";
  gaps: Record<string, boolean>;
}

export interface SuspectMeat {
  monitor: boolean;
  evaluate: boolean;
  assess: boolean;
  treat: boolean;
}

export interface SuspectCard {
  id: number;
  hcc: number;
  icd10: string;
  label: string;
  confidence: number;
  evidence_type: string;
  trigger: string;
  status: string;
  /** Per-letter MEAT coverage. Absent until backend adds it to SuspectCard. */
  meat?: SuspectMeat | null;
  /** MEAT completeness status string — added by Agent-G. */
  meat_status?: string | null;
  /** Number of present MEAT elements (0-4) — added by Agent-G. */
  meat_count?: number | null;
  /** Truthy when a clinical sanity rule is violated — added by Agent-N. */
  clinical_rule_violation?: boolean | string | null;
  /** Expected revenue impact of accepting this suspect — added by Agent-N. */
  expected_dollar_impact?: number | null;
  /** When set, V28 will trump this HCC at scoring time — accepting it is
   *  wasted effort. Surfaced by raf_central.py:_fetch_trumped_map. */
  trumped_by_hcc?: number | null;
  /** Fractional MEAT completeness (0..1) when the engine wrote one — used
   *  by the UI to combine with confidence in prioritization. */
  meat_completeness?: number | null;
  /** Suspect taxonomy — drives the Net-new / Audit / Confirmed badge.
   *   - "new":       net-new suspect — never coded before, evidence-supported
   *   - "audit":     previously coded but lacks current MEAT documentation
   *   - "confirmed": already valid and submitted (informational)
   *   - undefined:   derive heuristically on the frontend
   *  Frontend derives this when the backend doesn't supply it: evidence_type
   *  == "historical" → audit; meat_completeness >= 0.75 → confirmed;
   *  otherwise → new.
   */
  taxonomy?: "new" | "audit" | "confirmed" | null;
  /** Canonical specialty bucket derived from the HCC code on the backend
   *  (see app/services/specialty_routing.py). One of: "cardiology",
   *  "nephrology", "endocrinology", "pulmonology", "oncology",
   *  "behavioral", "general". Drives the specialty filter-chip row above
   *  the confidence buckets so a nephrologist sees CKD suspects first,
   *  a cardiologist sees CHF first, etc. ("ForeSee" pattern.) */
  specialty?: string;
}

export interface RecaptureCard {
  id: number;
  hcc: string;
  icd10: string;
  label: string;
  prior_year: number;
  current_year: number;
  revenue_at_risk: number;
  last_encounter_date: string | null;
}

export interface AuditReadiness {
  meat_compliance_pct: number;
  hccs_compliant: number;
  hccs_total: number;
  risk_level: "LOW" | "MEDIUM" | "HIGH";
}

export interface FinancialImpact {
  current_raf: number;
  projected_raf: number;
  current_annual: number;
  projected_annual: number;
  pmpm_delta: number;
  annual_delta: number;
  revenue_per_raf_point: number;
}

/** Mirrors backend CodingOptCard Pydantic model (app/routers/raf_central.py). */
export interface CodingOptCard {
  current_icd10: string;
  current_label: string;
  suggested_icd10: string;
  suggested_label: string;
  raf_impact: number;
  source: string;
}

export interface RAFCentralPayload {
  patient_id: number;
  measurement_year: number;
  generated_at: string;
  raf_score: LiveRAFBar;
  meat_gaps: MEATGap[];
  suspects: SuspectCard[];
  recapture: RecaptureCard[];
  coding_opt: CodingOptCard[];
  audit_readiness: AuditReadiness;
  financial_impact: FinancialImpact;
}

// ---------------------------------------------------------------------------
// Dismiss reason codes — single source of truth for UI labels <-> API values
// ---------------------------------------------------------------------------

export const DISMISS_REASONS = {
  not_clinically_supported: "Not clinically supported",
  already_documented: "Already documented under different code",
  patient_transferred: "Patient transferred",
  clinical_override: "Clinical judgment override",
  other: "Other",
} as const;

export type DismissReasonCode = keyof typeof DISMISS_REASONS;

export type MeatFilter = "all" | "incomplete" | "high-impact";
