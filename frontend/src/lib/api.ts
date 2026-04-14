/**
 * lib/api.ts
 *
 * Central axios instance used by every page and component.
 *
 * Auth wiring
 * -----------
 * This file owns the axios instance but does NOT import auth-context (that
 * would create a circular dependency). Instead, auth-context calls
 * `registerAuthInterceptors` once on mount, supplying:
 *   - a synchronous token getter   → attached to every outgoing request
 *   - a refresh callback           → called on 401 before retrying
 *   - a logout callback            → called when refresh itself fails
 *
 * The registration function returns an eject handle so auth-context can
 * clean up when the provider unmounts (important for React Strict Mode and
 * hot-reload).
 *
 * Usage
 * -----
 *   import api from "@/lib/api";                          // raw axios instance
 *   import { getPatients, calculateRaf } from "@/lib/api"; // typed helpers
 */

import axios, { AxiosInstance, InternalAxiosRequestConfig } from "axios";
import logger from "@/lib/logger";
import type {
  Patient,
  DashboardStats,
  SuspectCondition,
  AuditPackage,
  AnalysisResult,
  DBSuspect,
  JobStatusResponse,
  PopulationSummary,
  DataCompleteness,
  RevenueOpportunityReport,
  TrendMetric,
  DashboardTrends,
} from "@/types";

// Re-export consolidated types so existing consumers importing from "@/lib/api" continue to work.
export type {
  PopulationSummary,
  DataCompleteness,
  RevenueOpportunityReport,
  TrendMetric,
  DashboardTrends,
};

// ---------------------------------------------------------------------------
// Axios instance
// ---------------------------------------------------------------------------

export const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8500";

const api: AxiosInstance = axios.create({
  baseURL: API_BASE,
  headers: { "Content-Type": "application/json" },
  timeout: 180_000, // 3 minutes — complex clinical notes can take 60-90 s
  withCredentials: true,
});

export default api;

// ---------------------------------------------------------------------------
// Logging interceptors (always active)
// ---------------------------------------------------------------------------

api.interceptors.request.use(
  (config) => {
    (
      config as InternalAxiosRequestConfig & { _startTime?: number }
    )._startTime = Date.now();

    logger.api(config.method ?? "GET", config.url ?? "");
    return config;
  },
  (error) => {
    logger.error("API", "Request setup error", error?.message);
    return Promise.reject(error);
  }
);

api.interceptors.response.use(
  (response) => {
    const duration =
      Date.now() -
      (
        (
          response.config as InternalAxiosRequestConfig & {
            _startTime?: number;
          }
        )._startTime ?? Date.now()
      );
    logger.api(
      response.config.method ?? "GET",
      response.config.url ?? "",
      response.status,
      duration
    );
    return response;
  },
  (error) => {
    const config = error?.config as
      | (InternalAxiosRequestConfig & { _startTime?: number })
      | undefined;
    const duration = config?._startTime ? Date.now() - config._startTime : 0;
    const status = error?.response?.status ?? 0;
    const url = config?.url ?? "unknown";
    const method = config?.method ?? "GET";
    const code = (error?.response?.data as { code?: string } | undefined)?.code;

    // EMR deactivated (HTTP 423, code=EMR_DEACTIVATED) is an *expected* state,
    // not a bug. Swallow the noisy console.error, tag the error so React Query
    // can skip retries, and fire a global event so the EmrDeactivatedBanner
    // can surface it. CORS headers are sent by the backend on 423 responses.
    if (status === 423 && (code === "EMR_DEACTIVATED" || code === "NO_DATA_SOURCE")) {
      logger.api(method, url, status, duration);
      (error as { isEmrDeactivated?: boolean; gateCode?: string }).isEmrDeactivated = true;
      (error as { gateCode?: string }).gateCode = code;
      if (typeof window !== "undefined") {
        try {
          window.dispatchEvent(new CustomEvent("emr-deactivated", { detail: { code } }));
        } catch {}
      }
      return Promise.reject(error);
    }

    logger.api(method, url, status, duration);
    logger.error("API", `Request failed: ${method.toUpperCase()} ${url}`, {
      status,
      data: error?.response?.data,
      message: error?.message,
    });
    return Promise.reject(error);
  }
);

/**
 * Helper: returns true if an error was emitted because the tenant has no
 * active EMR connection (HTTP 423 + code=EMR_DEACTIVATED). Use this in page
 * components to render an empty state instead of a "Network Error" toast.
 */
export function isEmrDeactivatedError(err: unknown): boolean {
  if (!err || typeof err !== "object") return false;
  const e = err as {
    isEmrDeactivated?: boolean;
    response?: { status?: number; data?: { code?: string } };
  };
  if (e.isEmrDeactivated) return true;
  const c = e.response?.data?.code;
  return (
    e.response?.status === 423 && (c === "EMR_DEACTIVATED" || c === "NO_DATA_SOURCE")
  );
}

/** Return true if the error is specifically a "no data source at all" gate (no EMR and no upload). */
export function isNoDataSourceError(err: unknown): boolean {
  if (!err || typeof err !== "object") return false;
  const e = err as {
    gateCode?: string;
    response?: { status?: number; data?: { code?: string } };
  };
  if (e.gateCode === "NO_DATA_SOURCE") return true;
  return e.response?.status === 423 && e.response?.data?.code === "NO_DATA_SOURCE";
}

// ---------------------------------------------------------------------------
// Auth interceptor registration
//
// Called ONCE by AuthProvider on mount. Returns cleanup handles so the
// provider can eject on unmount (React Strict Mode mounts twice).
// ---------------------------------------------------------------------------

export interface AuthInterceptorHandles {
  ejectRequest: () => void;
  ejectResponse: () => void;
}

export function registerAuthInterceptors(
  getToken: () => string | null,
  doRefresh: () => Promise<string>,
  onLogout: () => void
): AuthInterceptorHandles {
  // Local to this closure so eject fully resets state (handles React Strict Mode double-mount).
  let _isRefreshing = false;
  let _refreshQueue: Array<(token: string | null) => void> = [];

  const reqId = api.interceptors.request.use((config) => {
    const token = getToken();
    if (token) {
      config.headers["Authorization"] = `Bearer ${token}`;
    }
    return config;
  });

  const resId = api.interceptors.response.use(
    (response) => response,
    async (error) => {
      const originalRequest = error.config as InternalAxiosRequestConfig & {
        _retried?: boolean;
      };

      // Only attempt refresh if the original request HAD a token (authenticated request).
      // Unauthenticated 401s (no token in the request) should not trigger refresh/logout.
      const hadToken = !!originalRequest.headers?.["Authorization"];
      if (error.response?.status === 401 && !originalRequest._retried && hadToken) {
        originalRequest._retried = true;

        // If a refresh is already in flight, queue this request until it
        // resolves rather than firing a second refresh.
        if (_isRefreshing) {
          return new Promise((resolve, reject) => {
            _refreshQueue.push((newToken) => {
              if (newToken) {
                originalRequest.headers["Authorization"] = `Bearer ${newToken}`;
                resolve(api(originalRequest));
              } else {
                reject(error);
              }
            });
          });
        }

        _isRefreshing = true;
        try {
          const newToken = await doRefresh();
          _isRefreshing = false;
          _refreshQueue.forEach((cb) => cb(newToken));
          _refreshQueue = [];
          originalRequest.headers["Authorization"] = `Bearer ${newToken}`;
          return api(originalRequest);
        } catch {
          _isRefreshing = false;
          _refreshQueue.forEach((cb) => cb(null));
          _refreshQueue = [];
          onLogout();
          return Promise.reject(error);
        }
      }

      return Promise.reject(error);
    }
  );

  return {
    ejectRequest: () => api.interceptors.request.eject(reqId),
    ejectResponse: () => {
      api.interceptors.response.eject(resId);
      _refreshQueue = [];
      _isRefreshing = false;
    },
  };
}

// ---------------------------------------------------------------------------
// Shared response-shape types
// ---------------------------------------------------------------------------

export interface PaginatedPatients {
  total: number;
  patients: Patient[];
  limit: number;
  offset: number;
}

export interface PatientEncountersResponse {
  pid: number;
  count: number;
  encounters: Array<{
    encounter_id: number;
    date: string;
    reason?: string;
    provider_fname?: string;
    provider_lname?: string;
  }>;
}

export interface RafScore {
  pid: number;
  year: number;
  raf_score: number;
  model: string;
  hcc_codes: string[];
  calculated_at: string;
}

export interface RafBreakdown {
  pid: number;
  year: number;
  model: string;
  demographic_score: number;
  disease_score: number;
  interaction_score: number;
  total_score: number;
  hcc_details: Array<{
    hcc_code: string;
    description: string;
    score: number;
    icd10_codes: string[];
  }>;
}

// PopulationSummary and DataCompleteness are now canonical in @/types — re-exported above.

export interface SuspectsResponse {
  status_filter: string;
  count: number;
  suspects: DBSuspect[];
}

export interface BulkUpdateResponse {
  action: string;
  requested: number;
  succeeded: number;
  failed: number;
}

export interface ScanAllResponse {
  patients_scanned: number;
  total_new_suspects: number;
  per_patient: Array<{ pid: number; new_suspects: number }>;
  errors: Array<{ pid: number; error: string }>;
}

export interface DocumentItem {
  id: number;
  document_id?: number;
  filename: string;
  file_name?: string;
  file_type: string;
  document_type?: string;
  report_type?: string;
  status: "pending" | "processing" | "analyzed" | "failed";
  uploaded_at: string;
  upload_date?: string;
  created_at?: string;
  analyzed_at?: string;
  pid?: number;
  patient_name?: string;
  diagnosis_count?: number;
  new_hcc_count?: number;
}

export interface DocumentsResponse {
  total: number;
  documents: DocumentItem[];
}

export interface ClaimsBatch {
  id: number;
  filename: string;
  status: "pending" | "processing" | "completed" | "failed";
  record_count: number;
  uploaded_at: string;
  processed_at?: string;
  error_count?: number;
}

export interface ClaimsBatchesResponse {
  total: number;
  batches: ClaimsBatch[];
}

export interface FhirConnection {
  id: number;
  name: string;
  base_url: string;
  auth_type: "none" | "basic" | "oauth2" | "smart";
  status: "active" | "inactive" | "error";
  last_synced_at?: string;
  created_at: string;
}

export interface Provider {
  id: number;
  npi: string;
  first_name: string;
  last_name: string;
  specialty?: string;
  patient_count: number;
}

export interface ProviderScorecard {
  provider_id: number;
  npi: string;
  name: string;
  average_raf_score: number;
  capture_rate: number;
  patients_with_gaps: number;
  revenue_opportunity: number;
  rank?: number;
}

export interface SubmissionBatch {
  id: number;
  submission_year: number;
  record_count: number;
  status: "draft" | "validated" | "submitted" | "accepted" | "rejected";
  created_at: string;
  submitted_at?: string;
}

export interface SubmissionSchedule {
  upcoming: Array<{
    deadline: string;
    description: string;
    days_remaining: number;
  }>;
}

export interface ProspectiveWorklistItem {
  pid: number;
  name: string;
  dob: string;
  raf_score: number;
  open_gaps: number;
  awv_eligible: boolean;
  last_visit_date?: string;
  next_appointment?: string;
  priority: "high" | "medium" | "low";
}

export interface ProspectiveSummary {
  total_worklist: number;
  awv_eligible: number;
  high_priority: number;
  estimated_revenue: number;
}

export interface QualityMeasure {
  measure_id: string;
  name: string;
  numerator: number;
  denominator: number;
  rate: number;
  benchmark?: number;
  gap: number;
}

export interface QualitySummary {
  year: number;
  total_measures: number;
  measures_above_benchmark: number;
  composite_score: number;
  stars_estimate: number;
}

export interface StarsEstimate {
  year: number;
  current_estimate: number;
  projected_estimate: number;
  measure_breakdown: Array<{
    measure_id: string;
    stars: number;
    weight: number;
  }>;
}

export interface CareGap {
  gap_id: number;
  pid: number;
  patient_name: string;
  measure_id: string;
  measure_name: string;
  due_date?: string;
  status: "open" | "closed" | "excluded";
}

export interface WebhookEvent {
  id: number;
  webhook_id: number;
  event_type: string;
  payload: Record<string, unknown>;
  status: "delivered" | "failed" | "pending";
  delivered_at?: string;
  created_at: string;
}

export interface Webhook {
  id: number;
  url: string;
  event_types: string[];
  active: boolean;
  created_at: string;
  last_triggered_at?: string;
}

// RevenueOpportunityReport is now canonical in @/types — re-exported above.

export interface PatientScorecardRow {
  pid: number;
  name: string;
  age: number;
  sex: string;
  billing_raf: number | null;
  ai_raf: number | null;
  gap: number | null;
  revenue_opportunity: number | null;
  hcc_count_billing: number;
  hcc_count_ai: number;
  analyzed: boolean;
}

export interface HccDistributionRow {
  hcc_code: string;
  description?: string;
  patient_count: number;
  revenue_impact?: number;
}

export interface Job {
  job_id: string;
  status: "queued" | "running" | "completed" | "failed";
  type: string;
  pid?: number;
  created_at: string;
  updated_at: string;
  result?: Record<string, unknown>;
  error?: string;
}

export interface BenchmarkResult {
  test_case_id: string;
  model: string;
  score: number;
  expected: string;
  actual: string;
  passed: boolean;
  duration_ms: number;
  run_at: string;
}

export interface AuditGenerateResponse {
  pid: number;
  year: number;
  package_id: number;
  filename: string;
  size_bytes: number;
  download_url: string;
}

export interface AuditPackagesResponse {
  count: number;
  packages: Array<{
    id: number;
    pid: number;
    year: number;
    filepath?: string;
    file_size_bytes?: number;
    created_at: string;
  }>;
}

// ---------------------------------------------------------------------------
// Dashboard
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// EMR Status & Demo Connect
// ---------------------------------------------------------------------------

export async function getEmrStatus(): Promise<{ connected: boolean; vendor?: string; is_demo?: boolean; connection_count?: number; display_name?: string }> {
  const { data } = await api.get("/api/emr/status");
  return data;
}

export async function connectDemoEmr(): Promise<{ success: boolean; message: string }> {
  const { data } = await api.post("/api/emr/demo-connect");
  return data;
}

export async function getDashboardStats(): Promise<DashboardStats> {
  const { data } = await api.get("/api/dashboard/stats");
  return data;
}

// TrendMetric and DashboardTrends are now canonical in @/types — re-exported above.

export async function getDashboardTrends(): Promise<DashboardTrends> {
  const { data } = await api.get("/api/dashboard/trends");
  return data;
}

// ---------------------------------------------------------------------------
// Patient APIs
// ---------------------------------------------------------------------------

/**
 * Returns a flat patient array. For pagination use `searchPatients`.
 */
export async function getPatients(): Promise<Patient[]> {
  const { data } = await api.get("/api/patients");
  return (data as { patients?: Patient[] }).patients ?? data;
}

export async function searchPatients(params?: {
  search?: string;
  limit?: number;
  offset?: number;
  year?: number;
}): Promise<PaginatedPatients> {
  const { data } = await api.get<PaginatedPatients>("/api/patients", {
    params,
  });
  return data;
}

export async function getPatientsWithEncounters(): Promise<Patient[]> {
  const { data } = await api.get("/api/patients/with-encounters");
  return (data as { patients?: Patient[] }).patients ?? data;
}

export async function getPatient(
  pid: string | number
): Promise<Patient> {
  const { data } = await api.get(`/api/patients/${pid}`);
  return data;
}

export async function getPatientEncounters(
  pid: string | number,
  year?: number
): Promise<PatientEncountersResponse> {
  const params: Record<string, string | number | boolean | undefined> = {};
  if (year) params.year = year;
  const { data } = await api.get(`/api/patients/${pid}/encounters`, { params });
  return data;
}

export interface PatientProfile {
  billing?: {
    raf_score?: number;
    hcc_codes?: string[];
    icd10_codes?: Array<string | { code?: string; icd10_code?: string }>;
    diagnoses?: Array<string | { code?: string; icd10_code?: string }>;
  };
  enrollment?: Record<string, string> & { source?: string };
  vitals?: {
    latest?: {
      weight?: number; height?: number; bps?: number; bpd?: number;
      temperature?: number; pulse?: number; respiration?: number;
      oxygen_saturation?: number; date?: string;
    };
  };
  data_completeness?: Record<string, boolean | number | null> & { completeness_pct?: number };
  demographics?: Record<string, unknown>;
  immunizations?: Array<{ title?: string; date?: string }>;
  problems?: Array<{ title?: string; icd10_code?: string; begdate?: string }>;
  medications?: Array<{ drug?: string; dosage?: string; frequency?: string; begdate?: string }>;
  [key: string]: unknown;
}

export async function getPatientProfile(
  pid: string | number
): Promise<PatientProfile> {
  const { data } = await api.get(
    `/api/patients/${pid}/comprehensive-profile`
  );
  return data;
}

export interface MedicationsResponse {
  medications?: Array<{
    drug?: string; title?: string; medication?: string;
    dosage?: string; dose?: string;
    frequency?: string; route?: string;
    begdate?: string; start_date?: string; date?: string;
  }>;
}

export async function getPatientMedications(
  pid: string | number,
  year?: number
): Promise<MedicationsResponse> {
  const params: Record<string, string | number | boolean | undefined> = {};
  if (year) params.year = year;
  const { data } = await api.get(`/api/patients/${pid}/medications`, { params });
  return data;
}

export interface DiagnosesResponse {
  diagnoses?: Array<{ icd10_code?: string; description?: string; date?: string }>;
}

export async function getPatientDiagnoses(
  pid: string | number
): Promise<DiagnosesResponse> {
  const { data } = await api.get(`/api/patients/${pid}/diagnoses`);
  return data;
}

export interface ProblemListResponse {
  problems?: Array<{
    title?: string; condition?: string; diagnosis?: string;
    icd10_code?: string; diagnosis_code?: string;
    begdate?: string; onset_date?: string; date?: string;
  }>;
}

export async function getPatientProblemList(
  pid: string | number,
  year?: number
): Promise<ProblemListResponse> {
  const params: Record<string, string | number | boolean | undefined> = {};
  if (year) params.year = year;
  const { data } = await api.get(`/api/patients/${pid}/problem-list`, { params });
  return data;
}

export interface VitalsLatest {
  date?: string;
  weight?: number | string | null;
  height?: number | string | null;
  bps?: number | string | null;
  bpd?: number | string | null;
  temperature?: number | string | null;
  pulse?: number | string | null;
  respiration?: number | string | null;
  oxygen_saturation?: number | string | null;
  BMI?: number | string | null;
  [key: string]: unknown;
}

export interface ClinicalFindingsResponse {
  suspects?: Array<{
    condition?: string; finding?: string;
    evidence?: string; rationale?: string; detail?: string;
    icd10_code?: string; hcc_code?: string;
  }>;
  /** Year-filtered latest vitals row returned by /vitals-suspects */
  latest_vitals?: VitalsLatest;
  /** Raw field name as returned by the backend (vitals_suspects) */
  vitals_suspects?: Array<{
    condition?: string; finding?: string;
    evidence?: string; rationale?: string; detail?: string;
    icd10_code?: string; hcc_code?: string;
    field?: string; measured_value?: number; confidence?: number;
    icd10?: string; hcc?: string; vitals_date?: string;
  }>;
}

export async function getPatientVitalsSuspects(
  pid: string | number,
  year?: number
): Promise<ClinicalFindingsResponse> {
  const params: Record<string, string | number | boolean | undefined> = {};
  if (year) params.year = year;
  const { data } = await api.get(`/api/patients/${pid}/vitals-suspects`, { params });
  return data;
}

export async function getPatientLabSuspects(
  pid: string | number,
  year?: number
): Promise<ClinicalFindingsResponse> {
  const params: Record<string, string | number | boolean | undefined> = {};
  if (year) params.year = year;
  const { data } = await api.get(`/api/patients/${pid}/lab-suspects`, { params });
  return data;
}

export interface ProceduresResponse {
  procedures?: Array<{ code?: string; description?: string; date?: string }>;
}

export async function getPatientProcedures(
  pid: string | number
): Promise<ProceduresResponse> {
  const { data } = await api.get(`/api/patients/${pid}/procedures`);
  return data;
}

export interface RecaptureGapsResponse {
  gaps?: Array<{
    hcc_code?: string; description?: string; label?: string;
    last_coded_year?: number; evidence?: string;
    icd10_code?: string; status?: string;
  }>;
  recapture_gaps?: Array<{
    id?: number; title?: string; diagnosis?: string; begdate?: string;
  }>;
}

export async function getPatientRecaptureGaps(
  pid: string | number,
  year?: number
): Promise<RecaptureGapsResponse> {
  const y = year ?? new Date().getFullYear();
  const { data } = await api.get(`/api/patients/${pid}/recapture-gaps`, {
    params: { year: y },
  });
  return data;
}

export interface AllergiesResponse {
  allergies?: Array<{ title?: string; allergen?: string; reaction?: string; severity?: string; begdate?: string }>;
}

export async function getPatientAllergies(
  pid: string | number
): Promise<AllergiesResponse> {
  const { data } = await api.get(`/api/patients/${pid}/allergies`);
  return data;
}

export interface ImmunizationsResponse {
  immunizations?: Array<{ title?: string; vaccine?: string; administered_date?: string; date?: string }>;
}

export async function getPatientImmunizations(
  pid: string | number
): Promise<ImmunizationsResponse> {
  const { data } = await api.get(`/api/patients/${pid}/immunizations`);
  return data;
}

export interface EnrollmentResponse {
  enrollment?: Array<{ plan?: string; start_date?: string; end_date?: string; status?: string }>;
}

export async function getPatientEnrollment(
  pid: string | number
): Promise<EnrollmentResponse> {
  const { data } = await api.get(`/api/patients/${pid}/enrollment`);
  return data;
}

export interface MedicationGapsResponse {
  gaps?: Array<{
    medication?: string; drug?: string; condition?: string; gap_type?: string;
    recommendation?: string; severity?: string; description?: string; gap?: string;
    icd_code?: string; icd10_code?: string; evidence?: string; rationale?: string;
  }>;
}

export async function getPatientMedicationGaps(
  pid: string | number,
  year?: number
): Promise<MedicationGapsResponse> {
  const { data } = await api.get(`/api/patients/${pid}/medication-gaps`, {
    params: year ? { year } : undefined,
  });
  return data;
}

export interface HedisResponse {
  measures?: Array<{ measure_id?: string; name?: string; status?: string; due_date?: string }>;
}

export async function getPatientHedis(
  pid: string | number,
  year?: number
): Promise<HedisResponse> {
  const { data } = await api.get(`/api/patients/${pid}/hedis`, {
    params: year ? { year } : undefined,
  });
  return data;
}

export interface SdohResponse {
  factors?: Array<{ category?: string; description?: string; risk_level?: string; screening_date?: string }>;
}

export async function getPatientSdoh(pid: string | number): Promise<SdohResponse> {
  const { data } = await api.get(`/api/patients/${pid}/sdoh`);
  return data;
}

export interface FamilyHistoryResponse {
  history?: Array<{ condition?: string; relation?: string; relative?: string; age_at_onset?: number }>;
}

export async function getPatientFamilyHistory(
  pid: string | number
): Promise<FamilyHistoryResponse> {
  const { data } = await api.get(`/api/patients/${pid}/family-history`);
  return data;
}

export interface ReferralsResponse {
  referrals?: Array<{ specialty?: string; provider?: string; date?: string; reason?: string; status?: string }>;
}

export async function getPatientReferrals(
  pid: string | number
): Promise<ReferralsResponse> {
  const { data } = await api.get(`/api/patients/${pid}/referrals`);
  return data;
}

export interface PatientSuspectsResponse {
  suspects?: DBSuspect[];
  count?: number;
}

export async function getPatientSuspects(
  pid: string | number,
  status: string = "open",
  year?: number
): Promise<PatientSuspectsResponse> {
  const params: Record<string, string | number | boolean | undefined> = { status };
  if (year) params.year = year;
  const { data } = await api.get(`/api/suspects/${pid}`, { params });
  return data;
}

// ---------------------------------------------------------------------------
// RAF APIs
// ---------------------------------------------------------------------------

export async function calculateRaf(
  pid: string | number,
  body?: { year?: number; model?: string }
): Promise<{ raf_score: number }> {
  const { data } = await api.post(`/api/raf/calculate/${pid}`, body ?? {});
  return data;
}

/** @alias calculateRaf — kept for callers using the old name */
export const calculateRAF = calculateRaf;

export async function calculateAllRAF(): Promise<{ job_id?: string; status?: string; patients_calculated?: number }> {
  const { data } = await api.post("/api/raf/calculate-all");
  return data;
}

export async function getRafScores(
  pid: string | number,
  year?: number
): Promise<RafScore[]> {
  const { data } = await api.get(`/api/raf/scores/${pid}`, {
    params: year ? { year } : undefined,
  });
  return data;
}

/** @alias getRafScores */
export const getRAFScores = getRafScores;

export async function getRafBreakdown(
  pid: string | number,
  year?: number
): Promise<RafBreakdown> {
  const { data } = await api.get(`/api/raf/scores/${pid}/breakdown`, {
    params: year ? { year } : undefined,
  });
  return data;
}

/** @alias getRafBreakdown */
export const getRAFBreakdown = getRafBreakdown;

export interface RafHistoryResponse {
  scores?: Array<{
    id?: number;
    raf_score?: number; score?: number; total_score?: number;
    year?: number; measurement_year?: number;
    model?: string;
    calculated_at?: string; created_at?: string;
  }>;
  history?: Array<{
    id?: number;
    raf_score?: number; score?: number; total_score?: number;
    year?: number; measurement_year?: number;
    model?: string;
    calculated_at?: string; created_at?: string;
  }>;
}

export async function getRafHistory(pid: string | number): Promise<RafHistoryResponse> {
  const { data } = await api.get(`/api/raf/scores/${pid}/history`);
  return data;
}

/** @alias getRafHistory */
export const getRAFHistory = getRafHistory;

export interface ModelComparisonResponse {
  models?: Array<{ model: string; raf_score: number; hcc_count: number }>;
}

export interface HCCRow {
  hcc_code: string;
  description: string;
  v24_coefficient: number | null;
  v28_coefficient: number | null;
  in_v24: boolean;
  in_v28: boolean;
}

export interface ModelComparisonResult {
  v24_score: number | null;
  v28_score: number | null;
  blended_score: number | null;
  hcc_comparison: HCCRow[];
}

export async function getModelComparison(
  pid: string | number,
  year?: number
): Promise<ModelComparisonResult> {
  const params: Record<string, string | number | boolean | undefined> = {};
  if (year) params.year = year;
  const { data } = await api.get(`/api/raf/scores/${pid}/model-comparison`, { params });

  // Transform API response into the shape the ModelComparison component expects:
  // { v24_score, v28_score, blended_score, hcc_comparison: HCCRow[] }
  const v24 = data?.v24 || {};
  const v28 = data?.v28 || {};
  const blended = data?.blended || {};
  const cmp = data?.hcc_comparison || {};

  // Build coefficient maps
  const v24Coeffs: Record<string, number> = {};
  const v24Labels: Record<string, string> = {};
  for (const h of v24.hcc_contributions || []) {
    v24Coeffs[h.hcc_code] = h.coefficient;
    v24Labels[h.hcc_code] = h.label || "";
  }
  const v28Coeffs: Record<string, number> = {};
  const v28Labels: Record<string, string> = {};
  for (const h of v28.hcc_contributions || []) {
    v28Coeffs[h.hcc_code] = h.coefficient;
    v28Labels[h.hcc_code] = h.label || "";
  }

  // Flatten hcc_comparison into HCCRow[]
  const hccRows: HCCRow[] = [];
  for (const h of cmp.in_both_annotated || []) {
    hccRows.push({
      hcc_code: h.hcc_code,
      description: h.label || `HCC ${h.hcc_code}`,
      v24_coefficient: v24Coeffs[h.hcc_code] ?? null,
      v28_coefficient: v28Coeffs[h.hcc_code] ?? null,
      in_v24: true,
      in_v28: true,
    });
  }
  for (const h of cmp.v24_only_annotated || []) {
    hccRows.push({
      hcc_code: h.hcc_code,
      description: h.label || `HCC ${h.hcc_code}`,
      v24_coefficient: v24Coeffs[h.hcc_code] ?? null,
      v28_coefficient: null,
      in_v24: true,
      in_v28: false,
    });
  }
  for (const h of cmp.v28_only_annotated || []) {
    hccRows.push({
      hcc_code: h.hcc_code,
      description: h.label || `HCC ${h.hcc_code}`,
      v24_coefficient: null,
      v28_coefficient: v28Coeffs[h.hcc_code] ?? null,
      in_v24: false,
      in_v28: true,
    });
  }

  return {
    v24_score: v24.payment_raf ?? v24.raw_raf ?? null,
    v28_score: v28.payment_raf ?? v28.raw_raf ?? null,
    blended_score: blended.payment_raf ?? null,
    hcc_comparison: hccRows,
  };
}

export async function getPopulationSummary(
  year?: number
): Promise<PopulationSummary> {
  const { data } = await api.get("/api/raf/population-summary", {
    params: year ? { year } : undefined,
  });
  return data;
}

export async function getRafModels(): Promise<string[]> {
  const { data } = await api.get("/api/raf/models");
  return data;
}

// ---------------------------------------------------------------------------
// Analysis APIs
// ---------------------------------------------------------------------------

export async function analyzeEncounter(
  encounterId: number,
  includeContext: boolean = true,
  saveResults: boolean = true
): Promise<AnalysisResult> {
  const { data } = await api.post(
    `/api/analysis/encounter/${encounterId}`,
    {
      include_context: includeContext,
      save_results: saveResults,
    }
  );
  return data;
}

export async function analyzeNote(
  patientId: string | number,
  noteText: string
): Promise<AnalysisResult> {
  const { data } = await api.post("/api/analysis/note", {
    patient_id: patientId,
    note_text: noteText,
  });
  return data;
}

export async function batchAnalysis(
  pid: number,
  saveResults: boolean = true
): Promise<{ job_id: string; status: string; message: string }> {
  const { data } = await api.post(`/api/analysis/batch/${pid}`, null, {
    params: { save_results: saveResults },
  });
  return data;
}

export async function getJobStatus(
  jobId: string
): Promise<JobStatusResponse> {
  const { data } = await api.get(`/api/analysis/jobs/${jobId}`);
  return data;
}

// ---------------------------------------------------------------------------
// Suspects APIs
// ---------------------------------------------------------------------------

export async function getSuspects(
  status: string = "open",
  limit: number = 200
): Promise<SuspectsResponse> {
  const { data } = await api.get("/api/suspects", {
    params: { status, limit },
  });
  return data;
}

export async function acceptSuspect(
  suspectId: number,
): Promise<{ status: string; id: number }> {
  const { data } = await api.put(`/api/suspects/${suspectId}/accept`, {});
  return data;
}

export async function dismissSuspect(
  suspectId: number,
  reason: string = "dismissed via UI"
): Promise<{ status: string; id: number }> {
  const { data } = await api.put(`/api/suspects/${suspectId}/dismiss`, {
    reason,
  });
  return data;
}

export async function bulkUpdateSuspects(
  ids: number[],
  action: "accept" | "dismiss",
  reason: string = "bulk update via UI"
): Promise<BulkUpdateResponse> {
  const { data } = await api.post("/api/suspects/bulk-update", {
    ids,
    action,
    reason,
  });
  return data;
}

export async function scanAllSuspects(): Promise<ScanAllResponse> {
  const { data } = await api.post("/api/suspects/scan-all");
  return data;
}

export async function scanPatientSuspects(pid: number): Promise<{ new_suspects: number; pid: number }> {
  const { data } = await api.post(`/api/suspects/scan/${pid}`);
  return data;
}

// ---------------------------------------------------------------------------
// Documents APIs
// ---------------------------------------------------------------------------

export async function getDocuments(params?: {
  status?: string;
  pid?: number;
  limit?: number;
  offset?: number;
}): Promise<DocumentsResponse> {
  const { data } = await api.get("/api/documents", { params });
  return data;
}

export async function uploadDocument(
  formData: FormData
): Promise<DocumentItem> {
  const { data } = await api.post("/api/documents/upload", formData, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data;
}

export interface DocumentAnalysisResult {
  id?: number;
  status?: string;
  diagnoses?: Array<{
    id?: number; icd10_code?: string; icd_code?: string;
    description?: string; diagnosis?: string;
    hcc_code?: string; raf_weight?: number; confidence?: number;
    status?: string; meat_status?: string;
  }>;
  medications?: string[];
  labs?: Array<string | { name: string; value: string }>;
  vitals?: Array<string | { name: string; value: string }>;
  summary?: string;
}

export async function analyzeDocument(id: number): Promise<DocumentAnalysisResult> {
  const { data } = await api.post(`/api/documents/${id}/analyze`);
  return data;
}

export async function getDocumentAnalysis(id: number): Promise<DocumentAnalysisResult> {
  const { data } = await api.get(`/api/documents/${id}/analysis`);
  return data;
}

// Get documents for a specific patient
export async function getPatientDocuments(pid: string | number): Promise<DocumentsResponse> {
  const { data } = await api.get("/api/documents", { params: { patient_id: pid, limit: 100 } });
  return data;
}

// Upload document linked to a specific patient with report type
export async function uploadPatientDocument(
  pid: string | number,
  file: File,
  reportType: string,
  encounterDate?: string
): Promise<DocumentItem> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("patient_id", String(pid));
  formData.append("document_type", reportType);
  formData.append("auto_analyze", "true");
  if (encounterDate) formData.append("encounter_date", encounterDate);
  const { data } = await api.post("/api/documents/upload", formData, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data;
}

// Get document diagnoses (extracted by AI)
export async function getDocumentDiagnoses(docId: number): Promise<DocumentAnalysisResult["diagnoses"]> {
  const { data } = await api.get(`/api/documents/${docId}/diagnoses`);
  return data;
}

// Confirm a document diagnosis
export async function confirmDocumentDiagnosis(docId: number, diagId: number): Promise<{ status: string }> {
  const { data } = await api.put(`/api/documents/${docId}/diagnoses/${diagId}/confirm`);
  return data;
}

// Reject a document diagnosis
export async function rejectDocumentDiagnosis(docId: number, diagId: number): Promise<{ status: string }> {
  const { data } = await api.put(`/api/documents/${docId}/diagnoses/${diagId}/reject`);
  return data;
}

// Get draft RAF score from document
export async function getDocumentDraftRAF(docId: number): Promise<{
  current_raf_score: number;
  draft_raf_score: number;
  raf_delta: number;
  new_hcc_codes: Array<{ hcc: string; label: string; coefficient: number }>;
  existing_hcc_codes: string[];
  document_diagnoses: Array<{ icd10: string; description: string; hcc: string; confidence: number }>;
  estimated_revenue_impact: number;
}> {
  const { data } = await api.post(`/api/documents/${docId}/draft-raf`);
  return data;
}

// ---------------------------------------------------------------------------
// Patient file uploads (CSV / XLSX)
// ---------------------------------------------------------------------------

export interface UploadResult {
  upload_id: number;
  filename: string;
  file_type: "csv" | "xlsx";
  row_count_total: number;
  row_count_imported: number;
  row_count_failed: number;
  status: "processing" | "completed" | "failed" | "partial";
  errors: string[];
}

export interface UploadRecord {
  id: number;
  tenant_id: string;
  uploaded_by: number;
  filename: string;
  file_size_bytes: number | null;
  file_type: "csv" | "xlsx";
  row_count_total: number;
  row_count_imported: number;
  row_count_failed: number;
  status: "processing" | "completed" | "failed" | "partial";
  created_at: string;
  completed_at: string | null;
  error_summary?: string | null;
  active_patient_count?: number;
}

export async function uploadPatientFile(file: File): Promise<UploadResult> {
  const formData = new FormData();
  formData.append("file", file);
  const { data } = await api.post("/api/uploads/patients", formData, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data;
}

export async function listUploads(): Promise<{ uploads: UploadRecord[]; total: number }> {
  const { data } = await api.get("/api/uploads");
  return data;
}

export async function getUpload(id: number): Promise<UploadRecord> {
  const { data } = await api.get(`/api/uploads/${id}`);
  return data;
}

export async function deleteUpload(id: number): Promise<{ upload_id: number; deleted: number }> {
  const { data } = await api.delete(`/api/uploads/${id}`, { params: { confirm: true } });
  return data;
}

export async function downloadUploadTemplate(format: "csv" | "xlsx"): Promise<void> {
  const res = await api.get(`/api/uploads/template`, {
    params: { format },
    responseType: "blob",
  });
  const blob = res.data as Blob;
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = format === "xlsx" ? "raf_patient_template.xlsx" : "raf_patient_template.csv";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// ---------------------------------------------------------------------------
// Claims APIs
// ---------------------------------------------------------------------------

export async function uploadClaims(formData: FormData): Promise<ClaimsBatch> {
  const { data } = await api.post("/api/claims/upload", formData, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data;
}

export async function getClaimsBatches(params?: {
  status?: string;
  limit?: number;
  offset?: number;
}): Promise<ClaimsBatchesResponse> {
  const { data } = await api.get("/api/claims/batches", { params });
  return data;
}

export async function processClaimsBatch(id: number): Promise<{ status: string; processed?: number }> {
  const { data } = await api.post(`/api/claims/batches/${id}/process`);
  return data;
}

// ---------------------------------------------------------------------------
// FHIR APIs
// ---------------------------------------------------------------------------

export async function getFhirConnections(): Promise<FhirConnection[]> {
  const { data } = await api.get("/api/fhir/connections");
  return data;
}

export async function createFhirConnection(
  body: Omit<FhirConnection, "id" | "status" | "created_at">
): Promise<FhirConnection> {
  const { data } = await api.post("/api/fhir/connections", body);
  return data;
}

export async function testFhirConnection(
  id: number
): Promise<{ success: boolean; message: string }> {
  const { data } = await api.post(`/api/fhir/connections/${id}/test`);
  return data;
}

export async function syncFhir(
  connId: number,
  body?: { resource_types?: string[]; since?: string }
): Promise<{ job_id: string; status: string }> {
  const { data } = await api.post(`/api/fhir/sync/${connId}`, body ?? {});
  return data;
}

// ---------------------------------------------------------------------------
// Provider APIs
// ---------------------------------------------------------------------------

export async function getProviders(params?: {
  search?: string;
  specialty?: string;
  limit?: number;
  offset?: number;
}): Promise<{ total: number; providers: Provider[] }> {
  const { data } = await api.get("/api/providers", { params });
  return data;
}

export async function getProviderScorecard(
  id: number
): Promise<ProviderScorecard> {
  const { data } = await api.get(`/api/providers/${id}/scorecard`);
  return data;
}

export async function getProviderLeaderboard(): Promise<ProviderScorecard[]> {
  const { data } = await api.get("/api/providers/leaderboard");
  return data;
}

// ---------------------------------------------------------------------------
// Submissions APIs
// ---------------------------------------------------------------------------

export async function generateSubmission(body: {
  year: number;
  model?: string;
  patient_ids?: number[];
}): Promise<{ job_id: string; status: string; batch_id?: number }> {
  const { data } = await api.post("/api/submissions/generate", body);
  return data;
}

export async function getSubmissionBatches(params?: {
  year?: number;
  status?: string;
  limit?: number;
  offset?: number;
}): Promise<{ total: number; batches: SubmissionBatch[] }> {
  const { data } = await api.get("/api/submissions/batches", { params });
  return data;
}

export async function validateSubmission(
  id: number
): Promise<{ valid: boolean; errors: string[]; warnings: string[] }> {
  const { data } = await api.post(
    `/api/submissions/batches/${id}/validate`
  );
  return data;
}

export async function getSubmissionSchedule(): Promise<SubmissionSchedule> {
  const { data } = await api.get("/api/submissions/schedule");
  return data;
}

// ---------------------------------------------------------------------------
// Prospective APIs
// ---------------------------------------------------------------------------

export async function getProspectiveWorklist(params?: {
  priority?: "high" | "medium" | "low";
  awv_eligible?: boolean;
  limit?: number;
  offset?: number;
}): Promise<{ total: number; items: ProspectiveWorklistItem[] }> {
  const { data } = await api.get("/api/prospective/worklist", { params });
  return data;
}

export interface PreVisitSummary {
  pid: number;
  open_gaps?: Array<{ hcc_code?: string; description?: string }>;
  recent_diagnoses?: Array<{ icd10?: string; description?: string }>;
  recommended_actions?: string[];
}

export async function getPreVisitSummary(pid: number): Promise<PreVisitSummary> {
  const { data } = await api.get(
    `/api/prospective/worklist/${pid}/pre-visit-summary`
  );
  return data;
}

export async function getAwvEligible(): Promise<{
  count: number;
  patients: Patient[];
}> {
  const { data } = await api.get("/api/prospective/awv-eligible");
  return data;
}

export async function getProspectiveSummary(): Promise<ProspectiveSummary> {
  const { data } = await api.get("/api/prospective/summary");
  return data;
}

// ---------------------------------------------------------------------------
// Quality APIs
// ---------------------------------------------------------------------------

export async function getQualityMeasures(): Promise<QualityMeasure[]> {
  const { data } = await api.get("/api/quality/measures");
  return data;
}

export async function getQualitySummary(
  year?: number
): Promise<QualitySummary> {
  const { data } = await api.get("/api/quality/summary", {
    params: year ? { year } : undefined,
  });
  return data;
}

export async function getStarsEstimate(
  year?: number
): Promise<StarsEstimate> {
  const { data } = await api.get("/api/quality/stars-estimate", {
    params: year ? { year } : undefined,
  });
  return data;
}

export async function getCareGaps(params?: {
  measure_id?: string;
  status?: "open" | "closed" | "excluded";
  pid?: number;
  limit?: number;
  offset?: number;
}): Promise<{ total: number; gaps: CareGap[] }> {
  const { data } = await api.get("/api/quality/gaps", { params });
  return data;
}

// ---------------------------------------------------------------------------
// Webhook APIs
// ---------------------------------------------------------------------------

export async function getWebhookEvents(): Promise<{
  total: number;
  events: WebhookEvent[];
}> {
  const { data } = await api.get("/api/webhooks/events");
  return data;
}

export async function getWebhooks(): Promise<Webhook[]> {
  const { data } = await api.get("/api/webhooks");
  return data;
}

export async function createWebhook(
  body: Omit<Webhook, "id" | "created_at" | "last_triggered_at">
): Promise<Webhook> {
  const { data } = await api.post("/api/webhooks", body);
  return data;
}

export async function testWebhook(
  id: number
): Promise<{ success: boolean; response_code?: number; message: string }> {
  const { data } = await api.post(`/api/webhooks/${id}/test`);
  return data;
}

// ---------------------------------------------------------------------------
// Reports APIs
// ---------------------------------------------------------------------------

export async function getRevenueOpportunity(
  year?: number
): Promise<RevenueOpportunityReport> {
  const { data } = await api.get("/api/reports/revenue-opportunity", {
    params: year ? { year } : undefined,
  });
  return data;
}

export async function getPatientScorecard(
  year?: number
): Promise<PatientScorecardRow[]> {
  const { data } = await api.get("/api/reports/patient-scorecard", {
    params: year ? { year } : undefined,
  });
  return data;
}

export async function getHccDistribution(
  year?: number
): Promise<HccDistributionRow[]> {
  const { data } = await api.get("/api/reports/hcc-distribution", {
    params: year ? { year } : undefined,
  });
  return data;
}

export async function getSuspectsSummary(status: string = "open"): Promise<
  Array<{
    patient_id: number;
    condition: string;
    icd10_code: string;
    hcc_code: string | null;
    confidence_score: number | null;
    status: string;
    rationale: string;
  }>
> {
  const { data } = await api.get("/api/reports/suspects-summary", {
    params: { status },
  });
  return data;
}

export interface DashboardInsight {
  id: string;
  category: string;
  priority: string;
  title: string;
  description: string;
  metric_value: string;
  action_label: string;
  action_href: string;
  icon: string;
  generated_at: string;
}

export async function getDashboardInsights(): Promise<{ insights: DashboardInsight[]; generated_at: string; count: number }> {
  const { data } = await api.get("/api/dashboard/insights");
  return data;
}

export async function getWorkflowSummary(): Promise<{
  open_suspects: number;
  high_confidence_suspects: number;
  patients_unanalyzed: number;
  patients_total: number;
  recent_analyses_7d: number;
  providers_active: number;
  avg_confidence: number;
  last_sync_at: string | null;
  last_analysis_at: string | null;
}> {
  const { data } = await api.get("/api/reports/workflow-summary");
  return data;
}

export async function getRecaptureGapsReport(year?: number): Promise<{ total_gaps?: number; gaps?: Array<{ pid: number; hcc_code: string; description?: string }> }> {
  const { data } = await api.get("/api/reports/recapture-gaps", {
    params: year ? { year } : undefined,
  });
  return data;
}

export async function getDataCompleteness(): Promise<DataCompleteness> {
  const { data } = await api.get("/api/reports/data-completeness");
  return data;
}

// ---------------------------------------------------------------------------
// Jobs APIs
// ---------------------------------------------------------------------------

export async function getJobs(params?: {
  status?: string;
  type?: string;
  limit?: number;
  offset?: number;
}): Promise<{ total: number; jobs: Job[] }> {
  const { data } = await api.get("/api/jobs", { params });
  return data;
}

export async function getJobDetail(id: string): Promise<Job> {
  const { data } = await api.get(`/api/jobs/${id}`);
  return data;
}

// ---------------------------------------------------------------------------
// Benchmarks APIs
// ---------------------------------------------------------------------------

export async function getBenchmarkResults(): Promise<{
  total: number;
  pass_rate: number;
  results: BenchmarkResult[];
}> {
  const { data } = await api.get("/api/benchmarks/results");
  return data;
}

export async function getTestCases(): Promise<unknown[]> {
  const { data } = await api.get("/api/benchmarks/test-cases");
  return data;
}

// ---------------------------------------------------------------------------
// Audit APIs
// ---------------------------------------------------------------------------

export async function getAuditPackages(
  pid?: number
): Promise<AuditPackagesResponse> {
  const { data } = await api.get("/api/audit/packages", {
    params: pid ? { pid } : undefined,
  });
  return data;
}

export async function generateAudit(
  pid: number,
  options?: {
    year?: number;
    recalculate?: boolean;
    include_suspects?: boolean;
  }
): Promise<AuditGenerateResponse> {
  const { data } = await api.post(
    `/api/audit/generate/${pid}`,
    options ?? {}
  );
  return data;
}

/** @alias generateAudit — kept for callers using the old name */
export const generateAuditPackage = generateAudit;

/**
 * Fetch an audit package PDF as a blob and trigger a browser download.
 *
 * Uses the authenticated axios instance so the Bearer token is sent —
 * a plain `<a href>` cannot do this because the access token lives in
 * memory, not in a cookie.
 *
 * Throws on HTTP error (e.g., 404 missing package, 410 file pruned,
 * 409 not ready). Callers should surface the error message to the user.
 */
export async function downloadAuditPackage(
  packageId: number,
  suggestedFilename?: string,
): Promise<void> {
  let res;
  try {
    res = await api.get(`/api/audit/packages/${packageId}/download`, {
      responseType: "blob",
    });
  } catch (err: unknown) {
    const axiosErr = err as { response?: { data?: unknown }; message?: string };
    const responseData = axiosErr.response?.data;
    if (responseData instanceof Blob) {
      try {
        const text = await responseData.text();
        try {
          const parsed = JSON.parse(text);
          if (parsed?.detail) axiosErr.message = parsed.detail;
        } catch {
          if (text) axiosErr.message = text;
        }
      } catch {
        /* ignore */
      }
    }
    throw err;
  }
  const blob = res.data as Blob;
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = suggestedFilename || `audit_package_${packageId}.pdf`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  // Defer revoke so Safari/Firefox have time to start the download.
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// ---------------------------------------------------------------------------
// ICD-10 to HCC Crosswalk
// ---------------------------------------------------------------------------

export interface CrosswalkResult {
  sno?: number;
  icd10_code: string;
  description?: string;
  cms_hcc_v24?: string | null;
  cms_hcc_v24_label?: string;
  cms_hcc_v24_coefficient?: number | null;
  cms_hcc_v28?: string | null;
  cms_hcc_v28_label?: string;
  cms_hcc_v28_coefficient?: number | null;
  rxhcc?: string | null;
  rxhcc_label?: string;
  rxhcc_coefficient?: number | null;
  is_chronic?: boolean;
  delta_v28_v24?: number;
  risk_adjusting?: boolean;
}

export interface CrosswalkSummary {
  total_codes: number;
  risk_adjusting_count: number;
  not_risk_adjusting_count: number;
  total_v24_coefficient: number;
  total_v28_coefficient: number;
  total_rxhcc_coefficient: number;
  delta_v28_v24: number;
}

export interface CrosswalkResponse {
  results?: CrosswalkResult[];
  summary?: CrosswalkSummary;
}

export async function lookupICD10Crosswalk(codes: string[]): Promise<CrosswalkResponse> {
  const { data } = await api.post("/api/raf/crosswalk", { codes });
  return data;
}

// ---------------------------------------------------------------------------
// Full RAF calculation (demographic + HCC + interactions + normalization)
// ---------------------------------------------------------------------------

export interface RAFCalcHccDetail {
  hcc: string;
  label: string;
  coefficient: number;
  is_chronic: boolean;
  diagnosis_codes: string[];
}

export interface RAFCalcInteraction {
  name: string;
  coefficient: number;
}

export interface RAFCalcResponse {
  model: string;
  risk_factor: string;
  prefix: string | null;
  age: number;
  gender: string;
  norm_factor: number;
  maci: number;
  base_rate: number;
  demographic: { category: string; coefficient: number };
  hcc_details: RAFCalcHccDetail[];
  interactions: RAFCalcInteraction[];
  unmapped_codes: string[];
  totals: {
    hcc_sum: number;
    grand_total: number;
    normalized: number;
    ma_cp_adjusted: number;
    risk_score_payment: number;
  };
}

export interface RAFCalcRequest {
  codes: string[];
  age: number;
  gender: "Male" | "Female";
  risk_factor: string;
  model: string;
  norm_factor?: number;
  maci?: number;
}

export async function calculateRAFFull(req: RAFCalcRequest): Promise<RAFCalcResponse> {
  const { data } = await api.post("/api/raf/calculate", req);
  return data;
}

// ---------------------------------------------------------------------------
// Legacy aliases — maintained for backward compatibility
// ---------------------------------------------------------------------------

/** @deprecated Use acceptSuspect */
export { acceptSuspect as updateSuspect };
