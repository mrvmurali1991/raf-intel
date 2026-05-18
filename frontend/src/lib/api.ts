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

import axios, { AxiosError, AxiosInstance, InternalAxiosRequestConfig } from "axios";
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
// Generated OpenAPI types — re-exported for downstream consumers
// ---------------------------------------------------------------------------
// Run `npm run gen:api` to regenerate after backend changes.
export type { paths, components, operations } from "./api.generated";
import type { paths, components } from "./api.generated";

/**
 * Extract the 200-response body type for a given path+method combination.
 *
 * Usage:
 *   type Payload = APIResponse<'/api/raf-central/{pid}', 'get'>;
 */
export type APIResponse<
  P extends keyof paths,
  M extends keyof paths[P],
> = paths[P][M] extends { responses: { 200: { content: { "application/json": infer T } } } }
  ? T
  : never;

/**
 * Extract the request body type for a given path+method combination.
 *
 * Usage:
 *   type Body = APIRequestBody<'/api/raf-central/{pid}/actions/accept-suspect', 'post'>;
 */
export type APIRequestBody<
  P extends keyof paths,
  M extends keyof paths[P],
> = paths[P][M] extends { requestBody: { content: { "application/json": infer T } } }
  ? T
  : never;

// Convenience aliases for the highest-traffic generated component schemas:
export type GeneratedRAFCentralPayload = components["schemas"]["RAFCentralPayload"];
export type GeneratedSuspectCard = components["schemas"]["SuspectCard"];
export type GeneratedMEATGap = components["schemas"]["MEATGap"];
export type GeneratedRecaptureCard = components["schemas"]["RecaptureCard"];
export type GeneratedLiveRAFBar = components["schemas"]["LiveRAFBar"];
export type GeneratedAuditReadiness = components["schemas"]["AuditReadiness"];
export type GeneratedFinancialImpact = components["schemas"]["FinancialImpact"];
export type GeneratedCodingOptCard = components["schemas"]["CodingOptCard"];

// ---------------------------------------------------------------------------
// Axios instance
// ---------------------------------------------------------------------------

export const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8500";

const api: AxiosInstance = axios.create({
  baseURL: API_BASE,
  headers: { "Content-Type": "application/json" },
  timeout: 30_000, // 30 seconds default; long-running endpoints override per-request
  withCredentials: true,
});

export default api;

// ---------------------------------------------------------------------------
// Per-endpoint timeout overrides for long-running operations
// ---------------------------------------------------------------------------

/** 2-minute timeout for operations that process many patients/encounters */
export const LONG_TIMEOUT = 120_000;
/** 3-minute timeout for full pipeline syncs and AI analysis */
export const PIPELINE_TIMEOUT = 180_000;

/**
 * URL patterns that need longer timeouts.  The request interceptor below
 * applies these automatically so callers don't need to remember.
 */
const LONG_TIMEOUT_PATTERNS: Array<[RegExp, number]> = [
  [/\/api\/emr\/sync/i,        PIPELINE_TIMEOUT],
  [/\/api\/analysis/i,         PIPELINE_TIMEOUT],
  [/\/api\/pipeline/i,         PIPELINE_TIMEOUT],
  [/\/api\/raf\/calculate/i,   LONG_TIMEOUT],
  [/\/api\/uploads/i,          LONG_TIMEOUT],
  [/\/api\/fhir\/sync/i,       PIPELINE_TIMEOUT],
];

api.interceptors.request.use((config) => {
  if (!config.timeout || config.timeout === 30_000) {
    const url = config.url || "";
    for (const [pattern, timeout] of LONG_TIMEOUT_PATTERNS) {
      if (pattern.test(url)) {
        config.timeout = timeout;
        break;
      }
    }
  }
  return config;
});

// ---------------------------------------------------------------------------
// Multi-tenant org switcher — X-Active-Tenant header
//
// The OrgSwitcher dropdown writes the selected tenant id to
// ``localStorage.active_tenant_id``. We forward it on every API request so
// the backend's ActiveTenantMiddleware can swap it into the user dict for
// the duration of the request. Storage access is wrapped in try/catch so
// the interceptor never throws (Safari private mode, blocked storage, SSR).
// ---------------------------------------------------------------------------

export const ACTIVE_TENANT_STORAGE_KEY = "active_tenant_id";

api.interceptors.request.use((config) => {
  if (typeof window === "undefined") return config;
  try {
    const activeTenant = window.localStorage.getItem(ACTIVE_TENANT_STORAGE_KEY);
    if (activeTenant) {
      config.headers["X-Active-Tenant"] = activeTenant;
    }
  } catch {
    /* storage unavailable — fall through without the header */
  }
  return config;
});

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

// ---------------------------------------------------------------------------
// Typed error envelope matching backend responses
// ---------------------------------------------------------------------------

export interface ApiErrorResponse {
  detail?: string;
  message?: string;
  error?: string;
  code?: string;
  status?: number;
}

/** Extract a user-friendly message from an API error */
export function getApiErrorMessage(err: unknown): string {
  if (axios.isAxiosError(err)) {
    const data = err.response?.data as ApiErrorResponse | undefined;
    const msg = data?.detail ?? data?.message ?? data?.error;
    if (msg) return String(msg);
    if (err.response?.status === 401) return "Authentication required. Please log in.";
    if (err.response?.status === 403) return "You do not have permission for this action.";
    if (err.response?.status === 429) return "Too many requests. Please wait and try again.";
    if (err.code === "ECONNABORTED") return "Request timed out. Please try again.";
    if (!err.response) return "Network error. Check your connection.";
  }
  if (err instanceof Error) return err.message;
  return "An unexpected error occurred.";
}

// ---------------------------------------------------------------------------
// Retry logic for 5xx errors (max 2 retries with exponential backoff)
// ---------------------------------------------------------------------------

interface RetryConfig {
  _retryCount?: number;
}

const MAX_RETRIES = 2;
const RETRY_DELAY_MS = 1000;

api.interceptors.response.use(undefined, async (error: AxiosError) => {
  const config = error.config as (InternalAxiosRequestConfig & RetryConfig) | undefined;
  if (!config) return Promise.reject(error);

  const status = error.response?.status ?? 0;
  const retryCount = config._retryCount ?? 0;

  // Only retry on 5xx server errors (not 401/403/423 etc.), and only idempotent-safe methods
  const isRetryable = status >= 500 && status < 600;
  const isSafeMethod = ["get", "head", "options", "put", "delete"].includes(
    (config.method ?? "").toLowerCase()
  );

  if (isRetryable && isSafeMethod && retryCount < MAX_RETRIES) {
    config._retryCount = retryCount + 1;
    const delay = RETRY_DELAY_MS * Math.pow(2, retryCount);
    logger.warn("API", `Retrying ${config.method?.toUpperCase()} ${config.url} (attempt ${config._retryCount}/${MAX_RETRIES}) after ${delay}ms`);
    await new Promise((r) => setTimeout(r, delay));
    return api(config);
  }

  return Promise.reject(error);
});

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

/**
 * Backend canonical shape for /api/raf/scores/{pid}.
 * Returns a SINGLE object (NOT an array — the prior hand-typed `RafScore[]`
 * was wrong cardinality; any caller doing `.map`/`.length` would crash).
 */
export interface RafScore {
  patient_id: number;
  patient_name?: string | null;
  measurement_year: number;
  model_segment: string;
  score_type?: string;
  raf_score: number;
  demographic_score?: number;
  disease_score?: number;
  interaction_score?: number;
  hcc_count?: number;
  blend_weights?: Record<string, unknown> | null;
  calculated_at?: string;
}

/**
 * Backend canonical shape for /api/raf/scores/{pid}/breakdown.
 * The prior hand-typed `total_score` field does NOT exist on the backend —
 * the wire fields are `raf_score` and `final_raf`. `hcc_details` is an
 * opaque list on the backend; keep it loose until the backend tightens.
 */
export interface RafBreakdown {
  patient_id: number;
  patient_name?: string | null;
  measurement_year: number;
  model_segment: string;
  score_type?: string;
  raf_score: number;
  final_raf?: number;
  blend_weights?: Record<string, unknown> | null;
  calculated_at?: string;
  engine_input?: Record<string, unknown> | null;
  engine_output?: Record<string, unknown> | null;
  dos_window?: Record<string, unknown> | null;
  hcc_details: Array<Record<string, unknown>>;
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
  /** numerator = met_count from API */
  numerator: number;
  /** denominator = eligible_count from API */
  denominator: number;
  /** rate as 0-100 (not 0-1) — compliance_rate from API */
  rate: number;
  benchmark?: number;
  gap: number;
}

export interface QualitySummary {
  year: number;
  /** Derived: Object.keys(measures).length */
  total_measures: number;
  /** Derived: count of measures where compliance_rate > 0 and above some threshold */
  measures_above_benchmark: number;
  /** overall_compliance_rate from API (0-100 scale) */
  composite_score: number;
  /** estimated_stars from /api/quality/stars-estimate */
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
  /** patient_id from API */
  pid: number;
  patient_name: string;
  /** measure_code from API */
  measure_id: string;
  measure_name: string;
  due_date?: string;
  /** API doesn't return status; we synthesise as "open" for all gaps returned */
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
    patient_id: number;
    measurement_year: number;
    file_path?: string;
    file_size_bytes?: number;
    created_at: string;
    status?: string;
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

/**
 * Shared row shape for entries returned by /vitals-suspects and /lab-suspects.
 * Both endpoints emit the same dict structure under the `suspects` key.
 */
export interface ClinicalFindingRow {
  condition?: string;
  finding?: string;
  evidence?: string;
  rationale?: string;
  detail?: string;
  icd10_code?: string;
  hcc_code?: string;
  field?: string;
  measured_value?: number;
  confidence?: number;
  icd10?: string;
  hcc?: string;
  vitals_date?: string;
}

/**
 * Response shape for /api/patients/{pid}/vitals-suspects and /lab-suspects.
 * Backend canonical fields (verified live): pid, count, suspects. The optional
 * vitals_suspects and latest_vitals aliases are kept as a transitional
 * compatibility layer for callers still reading the old field names; they
 * are NOT emitted by the current backend.
 */
export interface ClinicalFindingsResponse {
  pid: number;
  count: number;
  suspects: ClinicalFindingRow[];
  note?: string | null;
  /** Lab-suspects only — present when the FHIR lab fallback returned rows. */
  labs?: { results?: unknown[]; source?: string } | null;
  /**
   * @deprecated never emitted by the live backend — kept only so existing
   * callers reading `r.vitals_suspects` continue to compile while migrating
   * to `r.suspects`.
   */
  vitals_suspects?: ClinicalFindingRow[];
  /**
   * @deprecated never emitted by the live backend — kept transitionally for
   * callers reading `r.latest_vitals`.
   */
  latest_vitals?: VitalsLatest;
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

/**
 * Backend canonical shape for /api/patients/{pid}/enrollment.
 * Verified live: { pid, enrollment: dict }. `enrollment` is a single record,
 * NOT an array — previously the frontend hand-typed it as an array of plans,
 * which would have thrown on .map/.length if anyone actually consumed it.
 */
export interface EnrollmentResponse {
  pid: number;
  enrollment: Record<string, unknown>;
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

/**
 * Backend canonical shape for /api/patients/{pid}/hedis.
 * Verified live: { pid, year, summary: dict, measures: dict, source? }.
 * `measures` is a dict keyed by measure_id, NOT an array.
 */
export interface HedisResponse {
  pid: number;
  year: number;
  summary: Record<string, unknown>;
  measures: Record<string, unknown>;
  source?: string | null;
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

/**
 * Backend canonical shape for /api/patients/{pid}/sdoh.
 * Verified live: { pid, sdoh_form, billed_z_codes, billable_highlights }.
 * The legacy `factors[]` field is NOT emitted; kept as deprecated to ease
 * migration of any caller still reading it.
 */
export interface SdohResponse {
  pid: number;
  sdoh_form: Record<string, unknown>;
  billed_z_codes: Array<unknown>;
  billable_highlights: Record<string, unknown>;
  /** @deprecated never emitted by the backend — use sdoh_form. */
  factors?: Array<{ category?: string; description?: string; risk_level?: string; screening_date?: string }>;
}

export async function getPatientSdoh(pid: string | number): Promise<SdohResponse> {
  const { data } = await api.get(`/api/patients/${pid}/sdoh`);
  return data;
}

/**
 * Backend canonical shape for /api/patients/{pid}/family-history.
 * Verified live: { pid, family_history: {...nested object...}, source?, note? }.
 * The previous `history[]` array shape was hand-typed against a backend that
 * never existed — every consumer reading `.history` always got undefined.
 */
export interface FamilyHistoryResponse {
  pid: number;
  family_history: Record<string, unknown>;
  source?: string | null;
  note?: string | null;
  /** @deprecated never emitted by the backend — use family_history. */
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

/**
 * Enqueue an async RAF recompute via the inbox pipeline.
 *
 * Returns immediately after the patient is marked dirty; the actual
 * recompute runs on the Celery worker within ~15 s and pushes a
 * ``raf_updated`` SSE event. Listeners (NotificationCenter) invalidate
 * React Query caches on receipt, so callers typically do not need to
 * manually refetch after this call — just show a lightweight
 * "Recalculating…" toast and let SSE drive the UI.
 */
export async function markRafDirty(
  pid: string | number
): Promise<{ enqueued: boolean }> {
  const { data } = await api.post(`/api/raf/recompute/${pid}`);
  return data;
}

export async function calculateAllRAF(): Promise<{ job_id?: string; status?: string; patients_calculated?: number }> {
  const { data } = await api.post("/api/raf/calculate-all");
  return data;
}

export async function getRafScores(
  pid: string | number,
  year?: number
): Promise<RafScore> {
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

export async function unacceptSuspect(
  suspectId: number,
): Promise<{ suspect_id: number; action: string; reverted_to: string }> {
  const { data } = await api.post(`/api/suspects/${suspectId}/unaccept`);
  return data;
}

export async function undismissSuspect(
  suspectId: number,
): Promise<{ suspect_id: number; action: string; reverted_to: string }> {
  const { data } = await api.post(`/api/suspects/${suspectId}/undismiss`);
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

/**
 * /api/quality/measures — returns an array of measure definitions (no rates).
 * /api/quality/summary  — returns compliance_rate per measure in `measures` obj.
 * We merge both to produce QualityMeasure[] with rate/numerator/denominator/gap.
 */
export async function getQualityMeasures(): Promise<QualityMeasure[]> {
  const [defsRes, summaryRes] = await Promise.all([
    api.get("/api/quality/measures"),
    api.get("/api/quality/summary"),
  ]);
  const defs: Array<{ code: string; name: string; stars_weight: number }> = defsRes.data;
  const summaryMeasures: Record<string, {
    measure_name: string;
    eligible_count: number;
    met_count: number;
    gap_count: number;
    compliance_rate: number | null;
  }> = summaryRes.data.measures ?? {};

  return defs.map((def) => {
    const s = summaryMeasures[def.code];
    const rate = s?.compliance_rate ?? 0;
    return {
      measure_id: def.code,
      name: def.name,
      numerator: s?.met_count ?? 0,
      denominator: s?.eligible_count ?? 0,
      // API compliance_rate is already 0-100; MeasureRow multiplies by 100 expecting 0-1,
      // so we store as 0-1 fraction here.
      rate: rate / 100,
      gap: s?.gap_count ?? 0,
    } satisfies QualityMeasure;
  });
}

export async function getQualitySummary(
  year?: number
): Promise<QualitySummary> {
  const [summaryRes, starsRes] = await Promise.all([
    api.get("/api/quality/summary", { params: year ? { year } : undefined }),
    api.get("/api/quality/stars-estimate", { params: year ? { year } : undefined }),
  ]);
  const raw = summaryRes.data as {
    year: number;
    total_patients_evaluated: number;
    overall_compliance_rate: number;
    measures: Record<string, { compliance_rate: number | null }>;
  };
  const measuresArr = Object.values(raw.measures ?? {});
  const total = measuresArr.length;
  // "above benchmark" = compliance_rate >= 60 (reasonable mid-tier threshold)
  const aboveBenchmark = measuresArr.filter(
    (m) => (m.compliance_rate ?? 0) >= 60
  ).length;

  return {
    year: raw.year,
    total_measures: total,
    measures_above_benchmark: aboveBenchmark,
    composite_score: raw.overall_compliance_rate / 100,
    stars_estimate: starsRes.data.estimated_stars ?? 0,
  };
}

export async function getStarsEstimate(
  year?: number
): Promise<StarsEstimate> {
  const { data } = await api.get("/api/quality/stars-estimate", {
    params: year ? { year } : undefined,
  });
  // Raw shape: { year, estimated_stars, star_breakdown: { CODE: { stars, weight, ... } } }
  const raw = data as {
    year: number;
    estimated_stars: number;
    star_breakdown: Record<string, { stars: number; weight: number }>;
  };
  const breakdown = Object.entries(raw.star_breakdown ?? {}).map(
    ([code, v]) => ({ measure_id: code, stars: v.stars, weight: v.weight })
  );
  return {
    year: raw.year,
    current_estimate: raw.estimated_stars,
    projected_estimate: raw.estimated_stars, // no projection in API yet; same value
    measure_breakdown: breakdown,
  };
}

export async function getCareGaps(params?: {
  measure_id?: string;
  status?: "open" | "closed" | "excluded";
  pid?: number;
  limit?: number;
  offset?: number;
}): Promise<{ total: number; gaps: CareGap[] }> {
  const { data } = await api.get("/api/quality/gaps", { params });
  // Raw shape: { total_gaps, gaps: [{ patient_id, patient_name, measure_code, measure_name, gap, ... }] }
  const raw = data as {
    total_gaps: number;
    gaps: Array<{
      patient_id: number;
      patient_name: string;
      measure_code: string;
      measure_name: string;
    }>;
  };
  return {
    total: raw.total_gaps ?? 0,
    gaps: (raw.gaps ?? []).map((g, i) => ({
      gap_id: i,
      pid: g.patient_id,
      patient_name: g.patient_name,
      measure_id: g.measure_code,
      measure_name: g.measure_name,
      due_date: undefined,
      status: "open" as const,
    })),
  };
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

// ---------------------------------------------------------------------------
// Per-patient activity feed (PCP review #8 carry-over)
// ---------------------------------------------------------------------------

/** One row in the per-patient activity feed. */
export interface PatientActivityEntry {
  id: string;
  action: string;
  actor_email: string | null;
  actor_display_name: string | null;
  created_at: string;
  metadata: Record<string, unknown>;
  resource_type: string | null;
  resource_id: string | null;
}

export interface PatientActivityResponse {
  patient_id: number;
  total: number;
  items: PatientActivityEntry[];
}

/**
 * Fetch the audit-log timeline for a single patient.
 *
 * Backed by ``GET /api/patients/{pid}/activity`` which UNIONs ``audit_log``
 * and ``immutable_audit_log`` so PHI accesses, clinical-query creation,
 * suspect accept/dismiss, and audit-package generation all appear in one
 * chronological list.  The endpoint is tenant-scoped server-side.
 */
export async function getPatientActivity(
  pid: string | number,
  options?: { limit?: number; since?: string }
): Promise<PatientActivityResponse> {
  const params: Record<string, string | number> = {};
  if (options?.limit !== undefined) params.limit = options.limit;
  if (options?.since) params.since = options.since;
  const { data } = await api.get(`/api/patients/${pid}/activity`, {
    params: Object.keys(params).length ? params : undefined,
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

export function getAuditDownloadUrl(packageId: string | number): string {
  return `${API_BASE}/api/audit/download/${packageId}`;
}

/**
 * Download a RADV (Risk Adjustment Data Validation) audit packet PDF.
 *
 * Hits GET /api/radv/{pid}/packet?payment_year=YYYY and streams the blob
 * back to the browser as a file download. Uses the authenticated axios
 * instance so the Bearer token is attached.
 *
 * Throws on HTTP error — callers should surface `err.response?.data?.detail`
 * (when present) or `err.message` to the user via toast.
 */
export async function downloadRadvPacket(
  pid: number,
  paymentYear: number,
): Promise<void> {
  let res;
  try {
    res = await api.get(`/api/radv/${pid}/packet`, {
      params: { payment_year: paymentYear },
      responseType: "blob",
    });
  } catch (err: unknown) {
    // The server returns JSON error bodies; when responseType is 'blob' the
    // error body is also a Blob, so extract the detail before rethrowing.
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
  a.download = `radv_packet_patient_${pid}_py${paymentYear}.pdf`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

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
// RAF Financial Forecast
// ---------------------------------------------------------------------------

export interface ForecastBySuspect {
  suspect_id: number;
  hcc: string;
  icd10: string;
  evidence_type: string;
  coefficient: number;
  confidence: number;
  lift_raf: number;
  lift_revenue: number;
}

export interface PatientForecast {
  patient_id: number;
  patient_name?: string;
  measurement_year: number;
  model_segment: string;
  base_rate: number;
  persistence_assumption: number;
  current_raf: number;
  current_revenue: number;
  suspect_lift_raf: number;
  suspect_lift_revenue: number;
  removal_risk_raf: number;
  removal_risk_revenue: number;
  net_projected_raf: number;
  net_projected_revenue: number;
  by_suspect: ForecastBySuspect[];
  open_suspect_count: number;
  removal_risk_hcc_count: number;
}

export async function getPatientForecast(
  pid: string | number,
  year?: number
): Promise<PatientForecast> {
  const { data } = await api.get(`/api/forecast/patient/${pid}`, {
    params: year ? { year } : undefined,
  });
  return data;
}

export async function getProviderForecast(
  providerId: string | number,
  year?: number
): Promise<unknown> {
  const { data } = await api.get(`/api/forecast/provider/${providerId}`, {
    params: year ? { year } : undefined,
  });
  return data;
}


// ---------------------------------------------------------------------------
// Document Ingestion Dashboard
// ---------------------------------------------------------------------------

export interface DocIngestionSource {
  id: string;
  name: string;
  status: "active" | "idle" | "not_configured";
  docs_24h: number;
  suspects_24h: number;
  last_activity: string | null;
  config_path: string;
}

export interface DocIngestionRow {
  source: string;
  timestamp: string | null;
  document_id: string | null;
  patient_id: string | null;
  filename: string | null;
  mimetype: string | null;
  suspects: number;
  status: string;
}

export interface DocIngestionKpis {
  total_docs_24h: number;
  total_suspects_24h: number;
  success_rate_pct: number | null;
  active_sources: number;
  window_hours: number;
}

export interface DocIngestionDashboard {
  sources: DocIngestionSource[];
  recent_documents: DocIngestionRow[];
  kpis: DocIngestionKpis;
  generated_at: string;
}

export async function getDocumentIngestionDashboard(
  hours = 24
): Promise<DocIngestionDashboard> {
  const { data } = await api.get("/api/admin/document-ingestion/dashboard", {
    params: { hours },
  });
  return data;
}

export interface DocIngestionDetail {
  source: string;
  document_id: string;
  record: Record<string, unknown>;
  suspects: Array<{
    hcc_code: string;
    icd10_code: string;
    confidence_score: number;
    evidence_sentence: string;
  }>;
}

export async function getDocumentDetail(
  sourceId: string,
  documentId: string
): Promise<DocIngestionDetail> {
  const { data } = await api.get(
    `/api/admin/document-ingestion/document/${encodeURIComponent(sourceId)}/${encodeURIComponent(documentId)}`
  );
  return data;
}

export async function reprocessDocument(
  sourceId: string,
  documentId: string,
  engine: string
): Promise<{ queued: boolean; job_id?: string }> {
  const { data } = await api.post(
    `/api/admin/document-ingestion/document/${encodeURIComponent(sourceId)}/${encodeURIComponent(documentId)}/reprocess`,
    { engine }
  );
  return data;
}

export async function getTenantForecast(
  year?: number,
  tenantId?: string
): Promise<unknown> {
  const { data } = await api.get("/api/forecast/tenant", {
    params: { ...(year ? { year } : {}), ...(tenantId ? { tenant_id: tenantId } : {}) },
  });
  return data;
}

// ---------------------------------------------------------------------------
// Real-Time Suspect Hot-List
// ---------------------------------------------------------------------------

export interface SuspectHotlistItem {
  patient_id: number;
  patient_name: string;
  suspect_id: number;
  hcc_code: string;
  hcc_label: string;
  icd10: string;
  confidence: number;
  evidence_type: string;
  raf_coefficient: number;
  expected_dollars: number;
  days_open: number;
  urgency_score: number;
}

export interface SuspectHotlistSummary {
  total_open: number;
  high_confidence_count: number;
  total_expected_dollars: number;
  avg_dollars_per_suspect: number;
  max_panel_dollars: number;
  high_confidence_threshold: number;
}

export interface ProviderSuspectHotlist {
  provider_id: number;
  measurement_year: number;
  min_confidence: number;
  limit: number;
  items: SuspectHotlistItem[];
  summary: SuspectHotlistSummary;
}

export async function getProviderSuspectHotlist(
  providerId: number | string,
  opts?: { year?: number; limit?: number; minConfidence?: number }
): Promise<ProviderSuspectHotlist> {
  const params: Record<string, number> = {};
  if (opts?.year !== undefined) params.year = opts.year;
  if (opts?.limit !== undefined) params.limit = opts.limit;
  if (opts?.minConfidence !== undefined) params.min_confidence = opts.minConfidence;
  const { data } = await api.get(
    `/api/providers/${providerId}/suspect-hotlist`,
    { params },
  );
  return data;
}

// ---------------------------------------------------------------------------
// Legacy aliases — maintained for backward compatibility
// ---------------------------------------------------------------------------

/** @deprecated Use acceptSuspect */
export { acceptSuspect as updateSuspect };

// ---------------------------------------------------------------------------
// Disputes & Appeals
// ---------------------------------------------------------------------------

export type DisputeStatus =
  | "open"
  | "in_review"
  | "appealing"
  | "won"
  | "lost"
  | "abandoned";

export interface Dispute {
  id: number;
  tenant_id?: number | null;
  patient_id: number;
  hcc_code: number;
  icd10: string;
  disputed_by: "cms" | "payer" | "internal_audit";
  payer_name?: string | null;
  denial_reason_code?: string | null;
  denial_reason_text?: string | null;
  denial_received_at: string;
  financial_impact: number;
  status: DisputeStatus;
  assigned_to?: string | null;
  notes?: string | null;
  created_at: string;
  updated_at: string;
  closed_at?: string | null;
  evidence?: DisputeEvidence[];
  appeals?: Appeal[];
}

export interface DisputeEvidence {
  id: number;
  dispute_id: number;
  evidence_type: string;
  source_doc_id?: string | null;
  encounter_date?: string | null;
  snippet_text?: string | null;
  meat_components?: string | null;
  uploaded_at: string;
}

export interface Appeal {
  id: number;
  dispute_id: number;
  appeal_round: number;
  appeal_letter_text?: string | null;
  evidence_attached_json?: unknown;
  submitted_by?: string | null;
  submitted_at?: string | null;
  response_received_at?: string | null;
  outcome: "pending" | "overturned" | "upheld" | "partial" | "withdrawn";
  monetary_recovered: number;
  outcome_notes?: string | null;
}

export interface DisputeMetrics {
  tenant_id: number | null;
  totals: Record<DisputeStatus | "total", number>;
  win_rate: number;
  money_at_risk: number;
  money_recovered: number;
  avg_cycle_time_days: number;
}

export async function listDisputes(params?: {
  status?: DisputeStatus;
  assigned_to?: string;
  tenant_id?: number;
  patient_id?: number;
  limit?: number;
}): Promise<{ count: number; disputes: Dispute[] }> {
  const { data } = await api.get("/api/disputes", { params });
  return data;
}

export async function getDispute(id: number): Promise<Dispute> {
  const { data } = await api.get(`/api/disputes/${id}`);
  return data;
}

export async function createDispute(
  payload: Partial<Dispute> & {
    patient_id: number;
    hcc_code: number;
    icd10: string;
    disputed_by: Dispute["disputed_by"];
    denial_received_at: string;
  }
): Promise<Dispute> {
  const { data } = await api.post("/api/disputes", payload);
  return data;
}

export async function assignDispute(id: number, userId: string): Promise<Dispute> {
  const { data } = await api.put(`/api/disputes/${id}/assign`, { user_id: userId });
  return data;
}

export async function gatherDisputeEvidence(
  id: number
): Promise<{ dispute_id: number; count: number; evidence: DisputeEvidence[] }> {
  const { data } = await api.post(`/api/disputes/${id}/gather-evidence`);
  return data;
}

export async function draftAppeal(
  id: number,
  appealRound: number = 1
): Promise<{
  dispute_id: number;
  appeal_round: number;
  draft_text: string;
  evidence_cited: Array<{ tag: string; evidence_id: number }>;
  model_used: string;
}> {
  const { data } = await api.post(`/api/disputes/${id}/draft-appeal`, {
    appeal_round: appealRound,
  });
  return data;
}

export async function submitAppeal(
  id: number,
  payload: {
    appeal_round: number;
    appeal_letter_text: string;
    appeal_letter_model?: string;
    evidence_attached_json?: unknown;
    submitted_by?: string;
  }
): Promise<Appeal> {
  const { data } = await api.post(`/api/disputes/${id}/submit-appeal`, payload);
  return data;
}

export async function recordAppealOutcome(
  appealId: number,
  payload: {
    outcome: Appeal["outcome"];
    recovered_amount?: number;
    response_received_at?: string;
    outcome_notes?: string;
  }
): Promise<Appeal> {
  const { data } = await api.post(`/api/appeals/${appealId}/record-outcome`, payload);
  return data;
}

export async function getDisputeMetrics(tenantId?: number): Promise<DisputeMetrics> {
  const { data } = await api.get("/api/disputes/metrics", {
    params: tenantId !== undefined ? { tenant_id: tenantId } : undefined,
  });
  return data;
}

// ===========================================================================
// Provider /providers page features (10-feature integration)
// ===========================================================================

// --- Feature flags ---------------------------------------------------------
export interface FeatureFlagItem {
  key: string;
  name: string;
  description: string;
  category: string;
  default_enabled: boolean;
  enabled: boolean;
  scope: string;
}
export async function getFeatureFlags(): Promise<{ user_id: number; count: number; flags: FeatureFlagItem[] }> {
  const { data } = await api.get("/api/feature-flags");
  return data;
}
export async function setFeatureFlag(key: string, enabled: boolean): Promise<unknown> {
  const { data } = await api.put(`/api/feature-flags/${encodeURIComponent(key)}`, { enabled });
  return data;
}
export async function resetFeatureFlags(): Promise<unknown> {
  const { data } = await api.post("/api/feature-flags/reset");
  return data;
}

// --- Top 5 HCC opportunities ----------------------------------------------
export interface ProviderTopHccOpportunity {
  hcc_code: string; hcc_label: string;
  patient_count_missing: number; avg_confidence: number;
  raf_coefficient: number; expected_lift: number;
  peer_capture_rate: number | null;
  model_segment: string; model_year: number;
}
export async function getProviderTopHccOpportunities(
  pid: string | number, year?: number, limit: number = 5,
): Promise<{ opportunities: ProviderTopHccOpportunity[]; count: number }> {
  const { data } = await api.get(`/api/providers/${pid}/top-opportunities`, {
    params: { ...(year ? { year } : {}), limit },
  });
  return data;
}

// --- Revenue breakdown -----------------------------------------------------
export interface RevenueBreakdownBucket {
  name: string; amount: number; pct_of_total: number; count: number;
  top_3_hccs: { hcc_code: string; hcc_label: string; dollars: number }[];
}
export interface ProviderRevenueBreakdown {
  provider_id: number; year: number; total: number;
  buckets: RevenueBreakdownBucket[];
  assumptions: { persistence: number; base_rate: number; meat_threshold: number; model_segment: string; coefficient_year: number };
  panel_size?: number;
}
export async function getProviderRevenueBreakdown(
  pid: string | number, year?: number,
): Promise<ProviderRevenueBreakdown> {
  const { data } = await api.get(`/api/providers/${pid}/revenue-breakdown`, {
    params: year ? { year } : undefined,
  });
  return data;
}

// --- Provider trend (YoY) --------------------------------------------------
export type ProviderTrendMetricKey = "raf" | "recapture" | "capture" | "revenue";
export interface ProviderTrendResponse {
  provider_id: number;
  metrics: Record<ProviderTrendMetricKey, {
    values: { year: number; value: number | null; calculated_at: string }[];
    current: number | null;
    delta_vs_prior_year: number | null;
    delta_vs_4y: number | null;
  }>;
  years_available: number[];
  single_year_only: boolean;
  years_requested: number;
}
export async function getProviderTrend(
  pid: string | number, years: number = 4,
): Promise<ProviderTrendResponse> {
  const { data } = await api.get(`/api/providers/${pid}/trend`, { params: { years } });
  return data;
}
export async function getProviderTrendAggregate(
  metric: ProviderTrendMetricKey = "raf", years: number = 4,
): Promise<unknown> {
  const { data } = await api.get(`/api/providers/trend-aggregate`, { params: { metric, years } });
  return data;
}

// --- Peer percentile -------------------------------------------------------
export type PeerKpiKey =
  | "average_raf" | "hcc_capture_rate" | "recapture_rate"
  | "meat_completeness_avg" | "revenue_opportunity" | "documentation_quality_score";
export interface PeerPercentile {
  provider_id: number; specialty: string | null;
  measurement_year: number; cohort_size: number; insufficient_peers: boolean;
  provider_kpis: Partial<Record<PeerKpiKey, number | null>>;
  percentiles: Partial<Record<PeerKpiKey, number | null>>;
  cohort_summary: Partial<Record<PeerKpiKey, { min: number; median: number; max: number; n: number }>>;
}
export async function getPeerPercentile(
  pid: string | number, year?: number,
): Promise<PeerPercentile> {
  const { data } = await api.get(`/api/providers/${pid}/peer-percentile`, {
    params: year ? { year } : undefined,
  });
  return data;
}
export async function getSpecialtyBenchmarks(year?: number, specialty?: string): Promise<unknown> {
  const { data } = await api.get("/api/providers/specialty-benchmarks", {
    params: { ...(year ? { year } : {}), ...(specialty ? { specialty } : {}) },
  });
  return data;
}

// --- MEAT audit risk ------------------------------------------------------
export type MeatAuditRiskTier = "ready" | "at_risk" | "audit_risk" | "insufficient";
export interface MeatAuditWeakHcc {
  hcc_code: string; label: string; meat_score: number;
  patient_hcc_ids: number[]; missing_components: string[];
}
export interface MeatAuditRisk {
  provider_id: number; year: number;
  meat_completeness: number; hcc_count: number;
  risk_tier: MeatAuditRiskTier; risk_label: string;
  top_weak_hccs: MeatAuditWeakHcc[];
}
export interface MeatEvidenceRow {
  patient_id: number; encounter_date: string | null;
  components_present: string[]; components_missing: string[]; evidence_snippet: string | null;
}
export interface MeatEvidenceResponse {
  provider_id: number; hcc_code: string; year: number;
  evidence: MeatEvidenceRow[]; count: number;
}
export async function getProviderMeatAuditRisk(
  pid: string | number, year?: number,
): Promise<MeatAuditRisk> {
  const { data } = await api.get(`/api/providers/${pid}/meat-audit-risk`, {
    params: year ? { year } : undefined,
  });
  return data;
}
export async function getProviderMeatEvidence(
  pid: string | number, hccCode: string | number, year?: number,
): Promise<MeatEvidenceResponse> {
  const { data } = await api.get(`/api/providers/${pid}/meat-evidence/${hccCode}`, {
    params: year ? { year } : undefined,
  });
  return data;
}

// --- HCC gap drilldown ----------------------------------------------------
export interface HccGapPatient {
  patient_id: number; patient_name: string;
  first_name: string; last_name: string;
  mrn: string | null; dob: string | null; age: number | null; sex: string | null;
  last_encounter_date: string | null;
  suspect_status: "open" | "none" | string;
  confidence: number | null;
  evidence_type: string | null; evidence_detail: unknown;
  evidence_snippet: string | null; top_evidence_snippet: string | null;
  prior_year_coded: boolean;
}
export interface HccGapPatientsResponse {
  provider_id: number; provider_name: string;
  hcc_code: string; year: number;
  panel_size: number; missing_count: number;
  patients: HccGapPatient[];
}
export async function getProviderHccGapPatients(
  pid: string | number, hccCode: string | number, year?: number, limit: number = 50,
): Promise<HccGapPatientsResponse> {
  const { data } = await api.get(`/api/providers/${pid}/hcc/${hccCode}/gap-patients`, {
    params: { ...(year ? { year } : {}), limit },
  });
  return data;
}

// --- Pre-visit HCC briefing -----------------------------------------------
export interface PreVisitBriefingTopHcc {
  hcc_code: string; hcc_label: string;
  status: "suspect" | "recapture" | "meat_weak";
  evidence_type: string | null; evidence_snippet: string | null;
  confidence: number; expected_dollars: number;
}
export interface PreVisitBriefing {
  encounter_id: number;
  patient_id: number; patient_name: string;
  dob: string | null; age: number | null; sex: string | null; mrn: string | null;
  visit_date: string; visit_time: string | null;
  encounter_reason: string | null;
  model_segment: string;
  top_hccs: PreVisitBriefingTopHcc[];
  total_potential_dollars: number;
}
export interface PreVisitBriefingsResponse {
  provider_id: number; days_ahead: number;
  briefings: PreVisitBriefing[]; message?: string;
}
export async function getProviderPreVisitBriefings(
  pid: string | number, days: number = 7, limit_per_patient: number = 3,
): Promise<PreVisitBriefingsResponse> {
  const { data } = await api.get(`/api/providers/${pid}/pre-visit-briefings`, {
    params: { days, limit_per_patient },
  });
  return data;
}

// ---------------------------------------------------------------------------
// Recapture MEAT Audit (dual-coder) APIs
// ---------------------------------------------------------------------------

export type MeatElement = "M" | "E" | "A" | "T" | "MULTI";

export type AuditStatus =
  | "draft" | "primary_coded" | "review_pending" | "approved" | "rejected";

export interface RecaptureGapAudit {
  id: number;
  patient_id: string | number;
  tenant_id: string | number;
  hcc_code: string;
  icd10_code: string;
  prior_year: number;
  current_year: number;
  status: string;
  revenue_impact: number;
  evidence_phrase: string | null;
  evidence_source_url: string | null;
  meat_element: MeatElement | null;
  primary_coder_id: number | null;
  primary_coded_at: string | null;
  primary_coder_name?: string | null;
  primary_coder_email?: string | null;
  secondary_coder_id: number | null;
  secondary_approved_at: string | null;
  secondary_coder_name?: string | null;
  secondary_coder_email?: string | null;
  audit_status: AuditStatus;
  audit_notes: string | null;
  patient_name?: string | null;
  review_required?: boolean;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface AuditReadinessResponse {
  total_gaps: number;
  with_evidence: number;
  dual_signed: number;
  audit_ready_pct: number;
  missing_meat: Array<{
    gap_id: number;
    hcc: string;
    patient_id: string | number;
    revenue_impact: number;
    reason: string;
  }>;
  inter_rater_reliability?: {
    secondary_approved: number;
    secondary_rejected: number;
    pending_review: number;
    agreement_pct: number | null;
    band: "excellent" | "acceptable" | "moderate" | "needs_review" | null;
    method: string;
    /** Cohen's kappa coefficient — present when method === "cohens_kappa" */
    kappa?: number | null;
    /** Number of dual-coded gaps used to compute kappa */
    kappa_n?: number | null;
    note: string;
  } | null;
}

export interface ReviewQueueResponse {
  status: AuditStatus;
  total: number;
  items: RecaptureGapAudit[];
}

/** POST /api/recapture/gaps/{gap_id}/evidence */
export async function recordGapEvidence(
  gapId: number,
  body: {
    phrase: string;
    meat_element: MeatElement;
    source_url?: string | null;
    notes?: string | null;
  },
): Promise<RecaptureGapAudit> {
  const { data } = await api.post(`/api/recapture/gaps/${gapId}/evidence`, body);
  return (data as { gap: RecaptureGapAudit }).gap;
}

/** POST /api/recapture/gaps/{gap_id}/submit-review */
export async function submitGapForReview(gapId: number): Promise<RecaptureGapAudit> {
  const { data } = await api.post(`/api/recapture/gaps/${gapId}/submit-review`);
  return (data as { gap: RecaptureGapAudit }).gap;
}

/** POST /api/recapture/gaps/{gap_id}/approve */
export async function approveGapReview(
  gapId: number,
  notes?: string,
): Promise<RecaptureGapAudit> {
  const { data } = await api.post(`/api/recapture/gaps/${gapId}/approve`, { notes });
  return (data as { gap: RecaptureGapAudit }).gap;
}

/** POST /api/recapture/gaps/{gap_id}/reject */
export async function rejectGapReview(
  gapId: number,
  reason: string,
): Promise<RecaptureGapAudit> {
  const { data } = await api.post(`/api/recapture/gaps/${gapId}/reject`, { reason });
  return (data as { gap: RecaptureGapAudit }).gap;
}

/** GET /api/recapture/review-queue?status=review_pending */
export async function getRecaptureReviewQueue(
  status: AuditStatus = "review_pending",
  limit: number = 100,
): Promise<ReviewQueueResponse> {
  const { data } = await api.get("/api/recapture/review-queue", {
    params: { status, limit },
  });
  return data;
}

/** GET /api/recapture/audit-readiness */
export async function getRecaptureAuditReadiness(): Promise<AuditReadinessResponse> {
  const { data } = await api.get("/api/recapture/audit-readiness");
  return data;
}

/** GET /api/recapture/audit-report.pdf?year=YYYY — triggers a download. */
export async function downloadRecaptureAuditPdf(year?: number): Promise<void> {
  let res;
  try {
    res = await api.get("/api/recapture/audit-report.pdf", {
      params: year ? { year } : undefined,
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
  const suffix = year ? `-${year}` : "";
  a.download = `radv-audit${suffix}.pdf`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// ---------------------------------------------------------------------------
// Knowledge Graph (KG) — "Why this HCC?" explainability endpoints
// ---------------------------------------------------------------------------

/** A single piece of evidence that contributed to an HCC suggestion. */
export interface KgEvidenceItem {
  kind: string;
  source: string;
  citation?: string;
  value?: unknown;
  verbatim?: string;
}

/** The full reasoning chain for one HCC, traced through the KG. */
export interface KgEvidenceChain {
  hcc_code: string;
  suggested_icd10?: string;
  evidence_chain: KgEvidenceItem[];
  total_score: number;
  decision_tree: string[];
}

/** A ranked HCC candidate from a patient-wide KG inference. */
export interface KgHccCandidate {
  hcc: string;
  /** Confidence the UI should display.  When the backend has applied
   *  Platt-scaling calibration this matches calibrated_confidence; when
   *  no calibration artefact is loaded it equals raw_confidence. */
  confidence: number;
  /** Original (uncalibrated) confidence emitted by the KG sub-services. */
  raw_confidence?: number;
  /** Platt-scaled probability in [0,1].  Equals raw_confidence when the
   *  calibration artefact is missing (identity fit). */
  calibrated_confidence?: number;
  sources: string[];
  reasoning: string[];
  final_evidence: KgEvidenceChain;
}

/** Full HCC explanation card data — used on hover popovers. */
export async function getHccExplanation(hcc: string): Promise<unknown> {
  const { data } = await api.get(`/api/kg/query/explain/${hcc}`);
  return data;
}

/** Per-patient evidence chain for a single HCC. */
export async function getEvidenceChain(
  hcc: string,
  pid: number,
  year = 2026,
): Promise<KgEvidenceChain> {
  const { data } = await api.get(
    `/api/kg/query/evidence-chain/${hcc}/patient/${pid}`,
    { params: { year } },
  );
  return data;
}

/** Whole-patient KG inference — ranked candidate HCCs with evidence. */
export async function getPatientFullInference(
  pid: number,
  year = 2026,
): Promise<{ patient_id: number; candidates: KgHccCandidate[] }> {
  const { data } = await api.post(`/api/kg/query/patient-full-inference/${pid}`, { year });
  return data;
}

/** Evidence chain attached to an existing suspect row. */
export async function getSuspectEvidenceChain(suspectId: number): Promise<KgEvidenceChain> {
  const { data } = await api.get(`/api/suspects/${suspectId}/evidence-chain`);
  return data;
}

/** Traverse the KG between two concepts; useful for the graph view. */
export async function traverseKgPath(
  from: string,
  to: string,
  max_depth = 5,
): Promise<unknown> {
  const { data } = await api.get('/api/kg/query/traverse', {
    params: { from, to, max_depth },
  });
  return data;
}

// =============================================================================
// RECAPTURE — NEW EXPORTS (batch 1)
// Added to resolve 122 tsc errors across 31 untracked components.
// Every type is derived directly from the corresponding Pydantic schema or
// service-layer docstring in backend/app/routers/recapture_*.py and
// backend/app/services/recapture_*.py.
// =============================================================================

// ---------------------------------------------------------------------------
// Shared gap row — used by CloseHistoryTimeline and SmartCloseDialog
// ---------------------------------------------------------------------------

/**
 * A single recapture_gaps DB row as serialised by the close-history and
 * list-gaps endpoints. Fields mirror `get_close_history()` and `list_gaps()`
 * return values (recapture_close_service / recapture_gap_service).
 */
export interface RecaptureGapRow {
  id: number;
  patient_id: number;
  patient_name?: string | null;
  hcc_code: string;
  /** Human-readable HCC description added by list_gaps() service. */
  hcc_description?: string | null;
  icd10_code?: string | null;
  status: "open" | "recaptured" | "dismissed";
  evidence_phrase?: string | null;
  meat_element?: string | null;
  resolved_at?: string | null;
  resolved_by?: string | null;
  revenue_impact?: number | null;
  provider_npi?: string | null;
  current_year?: number;
  created_at?: string | null;
}

// ---------------------------------------------------------------------------
// AI suggestion — AISuggestionPanel
// ---------------------------------------------------------------------------

/** One row from `recapture_ai_suggestions`, returned by the AI-recoding endpoints. */
export interface AISuggestion {
  id: number;
  gap_id: number;
  evidence_phrase: string;
  confidence: number;
  meat_element?: string | null;
  encounter_date?: string | null;
  source_note_id?: string | null;
  status?: "pending" | "accepted" | "rejected";
}

/** Response shape for POST /api/recapture/gaps/{gap_id}/ai-suggest */
export interface AISuggestResponse {
  gap_id: number;
  suggestions: AISuggestion[];
  scanned_note_count: number;
  llm_model_used: string;
  error?: string | null;
}

/** Scan recent clinical notes for AI evidence supporting this gap. */
export async function aiSuggestRecapture(
  gapId: number,
  months = 12,
): Promise<AISuggestResponse> {
  const { data } = await api.post<AISuggestResponse>(
    `/api/recapture/gaps/${gapId}/ai-suggest`,
    null,
    { params: { months } },
  );
  return data;
}

/** List pending AI suggestions for a gap. */
export async function listAiSuggestions(gapId: number): Promise<AISuggestion[]> {
  const { data } = await api.get<{ suggestions: AISuggestion[] }>(
    `/api/recapture/gaps/${gapId}/ai-suggestions`,
  );
  return data.suggestions;
}

/** Accept an AI suggestion (promotes evidence to the gap). */
export async function acceptAiSuggestion(
  suggestionId: number,
): Promise<{ ok: boolean; suggestion_id: number; status: string }> {
  const { data } = await api.post(`/api/recapture/ai-suggestions/${suggestionId}/accept`);
  return data;
}

/** Reject an AI suggestion. */
export async function rejectAiSuggestion(
  suggestionId: number,
): Promise<{ ok: boolean; suggestion_id: number; status: string }> {
  const { data } = await api.post(`/api/recapture/ai-suggestions/${suggestionId}/reject`);
  return data;
}

// ---------------------------------------------------------------------------
// Orphan-gap attribution — AttributeOrphansBanner
// ---------------------------------------------------------------------------

/** Response shape for POST /api/recapture/orphan-gaps/attribute */
export interface AttributeOrphansResult {
  checked: number;
  updated: number;
  still_orphan: number;
}

/** Attribute orphan recapture gaps to a provider via the patient panel. */
export async function attributeOrphanGaps(): Promise<AttributeOrphansResult> {
  const { data } = await api.post<AttributeOrphansResult>('/api/recapture/orphan-gaps/attribute');
  return data;
}

// ---------------------------------------------------------------------------
// List recapture gaps — AttributeOrphansBanner, etc.
// ---------------------------------------------------------------------------

export interface ListRecaptureGapsParams {
  patient_id?: number;
  status?: string;
  hcc_code?: string;
  limit?: number;
  offset?: number;
}

/** List recapture gaps with optional filters.
 *  Returns the items array directly (convenience wrapper). */
export async function listRecaptureGaps(
  params?: ListRecaptureGapsParams,
): Promise<RecaptureGapRow[]> {
  const { data } = await api.get<{ gaps: RecaptureGapRow[] }>(
    '/api/recapture/gaps',
    { params },
  );
  return data.gaps;
}

// ---------------------------------------------------------------------------
// AWV suggestion — AWVSuggestionDialog
// ---------------------------------------------------------------------------

/**
 * Response from POST /api/recapture/gaps/{gap_id}/suggest-awv
 * (SuggestAWVResponse Pydantic model in recapture_recurring.py)
 */
export interface AWVSuggestion {
  gap_id: number;
  patient_id: number;
  eligible: boolean;
  suggested_visit_date: string;
  last_awv_date?: string | null;
  days_since?: number | null;
  recommended_provider_id?: number | null;
  hcc_code?: string | null;
  reason?: string | null;
}

/** Read-only AWV recommendation for a recurring gap. */
export async function suggestAwvForGap(gapId: number): Promise<AWVSuggestion> {
  const { data } = await api.post<AWVSuggestion>(
    `/api/recapture/gaps/${gapId}/suggest-awv`,
  );
  return data;
}

/** Record that an AWV has been booked (metadata only — no EHR call). */
export async function markGapAwvScheduled(
  gapId: number,
  body: { visit_date: string; encounter_id?: string },
): Promise<{ gap_id: number; awv_suggested: boolean; awv_visit_date: string; awv_encounter_id?: string | null }> {
  const { data } = await api.post(
    `/api/recapture/gaps/${gapId}/mark-awv-scheduled`,
    body,
  );
  return data;
}

// ---------------------------------------------------------------------------
// Bonus — BonusBadgeForGap, BonusLeaderboard, BonusMultiplierBanner, CoderEarningsCard
// ---------------------------------------------------------------------------

/** Current-month multiplier sub-object inside BonusConfigResponse / LeaderboardResponse. */
export interface BonusMonthMultiplier {
  month: number;
  multiplier: number;
  next_month: number;
  next_multiplier: number;
  delta: number;
  days_until_next_month: number;
}

/**
 * Response from GET /api/recapture/bonus/config
 * (BonusConfigResponse Pydantic model)
 */
export interface RecaptureBonusConfig {
  id: number;
  tenant_id: string;
  bonus_per_closure_default: number;
  month_multipliers: Record<string, number>;
  active: boolean;
  current_month_multiplier: BonusMonthMultiplier;
  created_at?: string | null;
  updated_at?: string | null;
}

/** Per-tenant bonus configuration. */
export async function getRecaptureBonusConfig(): Promise<RecaptureBonusConfig> {
  const { data } = await api.get<RecaptureBonusConfig>('/api/recapture/bonus/config');
  return data;
}

/**
 * One coder row in the leaderboard
 * (LeaderboardEntry Pydantic model in recapture_bonus.py)
 */
export interface LeaderboardEntry {
  rank: number;
  coder_id?: number | null;
  resolved_by: string;
  name: string;
  email: string;
  ytd_closures: number;
  ytd_dollars_recaptured: number;
  bonus_earned: number;
  open_gaps: number;
  win_rate: number;
}

/**
 * Response from GET /api/recapture/bonus/leaderboard
 * (LeaderboardResponse Pydantic model)
 */
export interface BonusLeaderboardResponse {
  tenant_id: string;
  year: number;
  current_month_multiplier: BonusMonthMultiplier;
  leaderboard: LeaderboardEntry[];
}

/** Ranked coder leaderboard for a given year. */
export async function getRecaptureBonusLeaderboard(
  year?: number,
  limit = 20,
): Promise<BonusLeaderboardResponse> {
  const { data } = await api.get<BonusLeaderboardResponse>(
    '/api/recapture/bonus/leaderboard',
    { params: { year, limit } },
  );
  return data;
}

/** One month's bonus breakdown in CoderEarningsResponse. */
export interface CoderEarningsMonth {
  month: number;
  closures: number;
  bonus: number;
  dollars_recaptured: number;
}

/**
 * Response from GET /api/recapture/bonus/coder/{coder_id}/earnings
 * (CoderEarningsResponse Pydantic model)
 */
export interface CoderEarnings {
  coder_id: number;
  name: string;
  email: string;
  role: string;
  year: number;
  ytd_closures: number;
  ytd_dollars_recaptured: number;
  bonus_earned: number;
  bonus_at_risk: number;
  open_gaps: number;
  current_month: number;
  current_multiplier: number;
  next_month: number;
  next_multiplier: number;
  monthly_breakdown: CoderEarningsMonth[];
}

/** Per-coder year-to-date bonus earnings. */
export async function getCoderEarnings(
  coderId: number,
  year?: number,
): Promise<CoderEarnings> {
  const { data } = await api.get<CoderEarnings>(
    `/api/recapture/bonus/coder/${coderId}/earnings`,
    { params: { year } },
  );
  return data;
}

/**
 * Response from GET /api/recapture/gaps/{gap_id}/bonus-preview
 * (BonusPreviewResponse Pydantic model)
 */
export interface BonusPreview {
  gap_id: number;
  bonus: number;
  base_bonus: number;
  month: number;
  multiplier: number;
  eligible: boolean;
  reason?: string | null;
}

/** Preview the bonus a coder would earn closing a gap right now. */
export async function getGapBonusPreview(gapId: number): Promise<BonusPreview> {
  const { data } = await api.get<BonusPreview>(
    `/api/recapture/gaps/${gapId}/bonus-preview`,
  );
  return data;
}

// ---------------------------------------------------------------------------
// Bulk close — BulkCloseToolbar
// ---------------------------------------------------------------------------

export interface BulkCloseRequest {
  gap_ids: number[];
  evidence_phrase: string;
  meat_element?: string | null;
  write_to_raf_hcc?: boolean;
  measurement_year?: number | null;
}

/**
 * Response from POST /api/recapture/gaps/bulk-close
 * (BulkCloseResponse Pydantic model)
 */
export interface BulkCloseResult {
  closed: number;
  raf_hcc_inserted: number;
  errors: Array<Record<string, unknown>>;
  results: Array<Record<string, unknown>>;
}

/** Bulk-close recapture gaps with shared evidence. */
export async function bulkCloseGaps(body: BulkCloseRequest): Promise<BulkCloseResult> {
  const { data } = await api.post<BulkCloseResult>('/api/recapture/gaps/bulk-close', body);
  return data;
}

// ---------------------------------------------------------------------------
// Smart close — SmartCloseDialog
// ---------------------------------------------------------------------------

/**
 * Response from POST /api/recapture/gaps/{gap_id}/smart-close
 * (SmartCloseResponse Pydantic model)
 */
export interface SmartCloseResult {
  gap_id: number;
  status: string;
  raf_hcc_inserted: boolean;
  raf_hcc_already_present: boolean;
  measurement_year: number;
}

/** Close a recapture gap with documentation evidence + MEAT element. */
export async function smartCloseGap(
  gapId: number,
  body: {
    evidence_phrase: string;
    meat_element?: string | null;
    write_to_raf_hcc?: boolean;
    measurement_year?: number | null;
  },
): Promise<SmartCloseResult> {
  const { data } = await api.post<SmartCloseResult>(
    `/api/recapture/gaps/${gapId}/smart-close`,
    body,
  );
  return data;
}

// ---------------------------------------------------------------------------
// Close history — CloseHistoryTimeline
// ---------------------------------------------------------------------------

/** Response from GET /api/recapture/close-history */
export interface CloseHistoryResponse {
  items: RecaptureGapRow[];
  count: number;
}

/** Recent recapture-gap closures with evidence. */
export async function getRecaptureCloseHistory(
  year?: number,
  limit = 50,
): Promise<CloseHistoryResponse> {
  const { data } = await api.get<CloseHistoryResponse>(
    '/api/recapture/close-history',
    { params: { year, limit } },
  );
  return data;
}

// ---------------------------------------------------------------------------
// Campaign management — CampaignKanban, RecaptureCampaignList, CreateCampaignModal, CoderDashboard
// ---------------------------------------------------------------------------

export type AssignmentStatus = "assigned" | "in_progress" | "closed" | "dismissed";

export type RecaptureCampaignStatus = "draft" | "active" | "paused" | "completed" | "archived";

/** A single assignment card as returned by the kanban endpoint. */
export interface AssignmentCard {
  assignment_id: number;
  gap_id: number;
  patient_id: number;
  hcc_code: string;
  icd10_code?: string | null;
  coder_id?: number | null;
  coder_name?: string | null;
  campaign_id: number;
  campaign_name?: string | null;
  assignment_status: AssignmentStatus;
  revenue_impact?: number | null;
  created_at?: string | null;
  updated_at?: string | null;
}

/** Rolled-up campaign stats sub-object. */
export interface CampaignStats {
  total_gaps: number;
  assigned: number;
  in_progress: number;
  closed: number;
  dismissed: number;
  closure_rate: number;
  recaptured_revenue: number;
  at_risk_revenue: number;
}

/** A single recapture campaign record. */
export interface RecaptureCampaign {
  id: number;
  tenant_id: string;
  name: string;
  description?: string | null;
  status: RecaptureCampaignStatus;
  filter_criteria?: Record<string, unknown> | null;
  target_close_date?: string | null;
  created_by?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  stats?: CampaignStats | null;
}

/** Response from GET /api/recapture/campaigns/{id}/kanban */
export interface KanbanResponse {
  campaign_id: number;
  buckets: {
    assigned: AssignmentCard[];
    in_progress: AssignmentCard[];
    closed: AssignmentCard[];
    dismissed: AssignmentCard[];
  };
  stats: CampaignStats;
}

/** Kanban-bucketed assignments for a campaign. */
export async function getRecaptureKanban(campaignId: number): Promise<KanbanResponse> {
  const { data } = await api.get<KanbanResponse>(
    `/api/recapture/campaigns/${campaignId}/kanban`,
  );
  return data;
}

/** Update an assignment's kanban state. */
export async function markRecaptureAssignment(
  assignmentId: number,
  body: { status: AssignmentStatus; notes?: string | null },
): Promise<Record<string, unknown>> {
  const { data } = await api.post(
    `/api/recapture/assignments/${assignmentId}/mark`,
    body,
  );
  return data;
}

/** List recapture campaigns, optionally filtered by status. */
export async function listRecaptureCampaigns(
  status?: RecaptureCampaignStatus,
  limit = 100,
  offset = 0,
): Promise<{ campaigns: RecaptureCampaign[]; total: number; limit: number; offset: number }> {
  const { data } = await api.get('/api/recapture/campaigns', {
    params: { status, limit, offset },
  });
  return data;
}

/** Create a new recapture campaign. Returns the persisted campaign row. */
export async function createRecaptureCampaign(body: {
  name: string;
  description?: string | null;
  filter_criteria?: Record<string, unknown> | null;
  target_close_date?: string | null;
  status?: string;
}): Promise<RecaptureCampaign> {
  const { data } = await api.post<RecaptureCampaign>('/api/recapture/campaigns', body);
  return data;
}

/** Bulk-assign matching gaps to coders. */
export async function assignRecaptureCampaign(
  campaignId: number,
  body: { coder_ids: number[]; distribution: "round_robin" | "by_specialty" },
): Promise<{ assigned: number; campaign_id: number }> {
  const { data } = await api.post(
    `/api/recapture/campaigns/${campaignId}/assign`,
    body,
  );
  return data;
}

/** An eligible coder returned by GET /api/recapture/coders */
export interface EligibleCoder {
  id: number;
  full_name: string;
  email: string;
  role: string;
}

/** List active users eligible for campaign assignment. */
export async function listEligibleCoders(): Promise<EligibleCoder[]> {
  const { data } = await api.get<{ coders: EligibleCoder[] }>('/api/recapture/coders');
  return data.coders;
}

/** Filter criteria for previewing / creating campaigns. */
export interface RecaptureFilterCriteria {
  hcc_codes?: string[];
  min_revenue?: number;
  max_age_days?: number;
  [key: string]: unknown;
}

/** By-HCC breakdown row in the filter preview. */
export interface PreviewByHcc {
  hcc_code: string;
  count: number;
  revenue: number;
}

/** Response from POST /api/recapture/campaigns/preview-filter */
export interface RecaptureFilterPreview {
  matched_gaps: number;
  total_revenue_at_risk: number;
  by_hcc: PreviewByHcc[];
}

/** Preview how many gaps match a filter before creating a campaign. */
export async function previewRecaptureFilter(
  filter_criteria: RecaptureFilterCriteria,
): Promise<RecaptureFilterPreview> {
  const { data } = await api.post<RecaptureFilterPreview>(
    '/api/recapture/campaigns/preview-filter',
    { filter_criteria },
  );
  return data;
}

// ---------------------------------------------------------------------------
// Coder dashboard — CoderDashboard
// ---------------------------------------------------------------------------

/** Weekly closure velocity data point. */
export interface VelocityDay {
  day: string;
  closed: number;
}

/** Response from GET /api/recapture/coder/{coder_id}/dashboard */
export interface CoderDashboardResponse {
  coder_id: number;
  today_closures: number;
  week_closures: number;
  totals: { open: number; closed: number; dismissed: number };
  weekly_velocity: VelocityDay[];
  my_open_assignments: AssignmentCard[];
}

/** Coder queue + closure velocity. */
export async function getCoderDashboard(coderId: number): Promise<CoderDashboardResponse> {
  const { data } = await api.get<CoderDashboardResponse>(
    `/api/recapture/coder/${coderId}/dashboard`,
  );
  return data;
}

// ---------------------------------------------------------------------------
// CFO summary — CfoExecutiveSummary, RecapturedByCondition
// ---------------------------------------------------------------------------

/** Quarter breakdown row in the CFO executive summary. */
export interface CfoQuarterBreakdown {
  quarter: string;
  opened: number;
  closed: number;
  recaptured_dollars: number;
  remaining_dollars: number;
}

/** Top-3 condition row in the CFO executive summary. */
export interface CfoTopCondition {
  hcc_code: string;
  description: string;
  count: number;
  dollars: number;
}

/** Top provider contributor row in the CFO executive summary. */
export interface CfoTopProvider {
  provider_npi: string;
  recaptured_count: number;
  recaptured_dollars: number;
}

/**
 * Response from GET /api/recapture/cfo/summary
 * (ExecutiveSummary Pydantic model)
 */
export interface CfoExecutiveSummary {
  year: number;
  generated_at: string;
  total_gaps_open: number;
  total_dollars_at_risk: number;
  ytd_dollars_recaptured: number;
  ytd_closures: number;
  ytd_velocity_per_day: number;
  budget_dollars: number;
  forecast_ye_dollars: number;
  variance_to_budget: number;
  month_breakdown: Array<{
    month: number;
    opened: number;
    closed: number;
    recaptured_dollars: number;
    remaining_dollars: number;
  }>;
  quarter_breakdown: CfoQuarterBreakdown[];
  top_3_recaptured_conditions: CfoTopCondition[];
  top_3_at_risk_conditions: CfoTopCondition[];
  top_3_provider_contributors: CfoTopProvider[];
  audit_risk_flag: boolean;
  audit_dual_coded_pct: number;
  totals: Record<string, number>;
  days_elapsed: number;
  days_in_year: number;
}

/** CFO executive summary for a measurement year. */
export async function getCfoSummary(year: number): Promise<CfoExecutiveSummary> {
  const { data } = await api.get<CfoExecutiveSummary>('/api/recapture/cfo/summary', {
    params: { year },
  });
  return data;
}

/** One YoY series row (YoyRow Pydantic model). */
export interface CfoYoyRow {
  year: number;
  opened: number;
  closed: number;
  recaptured_dollars: number;
  at_risk_dollars: number;
  closure_rate_pct: number;
}

/** Response from GET /api/recapture/cfo/yoy */
export interface CfoYoyResponse {
  tenant_id: string;
  years_back: number;
  series: CfoYoyRow[];
}

/** Year-over-year recapture trend. */
export async function getCfoYoy(years = 3): Promise<CfoYoyResponse> {
  const { data } = await api.get<CfoYoyResponse>('/api/recapture/cfo/yoy', {
    params: { years },
  });
  return data;
}

/** Download CFO export as a Blob (CSV or JSON). */
export async function downloadCfoExport(year: number, format: "csv" | "json"): Promise<Blob> {
  const response = await api.get('/api/recapture/cfo/export', {
    params: { year, format },
    responseType: 'blob',
  });
  return response.data as Blob;
}

// ---------------------------------------------------------------------------
// Outreach — GapOutreachHistoryDrawer, OutreachChannelBreakdown,
//             OutreachSummaryCards, OutreachTemplateManager
// ---------------------------------------------------------------------------

export type OutreachChannel = "sms" | "portal" | "phone" | "email" | "letter";

export type OutreachStatus =
  | "queued"
  | "sent"
  | "delivered"
  | "responded"
  | "failed"
  | "opted_out";

/**
 * One outreach event record (OutreachEventResponse Pydantic model).
 */
export interface OutreachEvent {
  id: number;
  tenant_id: string;
  gap_id: number;
  patient_id: string;
  template_id?: number | null;
  template_name?: string | null;
  channel: OutreachChannel;
  status: OutreachStatus;
  scheduled_for?: string | null;
  sent_at?: string | null;
  delivered_at?: string | null;
  responded_at?: string | null;
  response_text?: string | null;
  resulted_in_visit: boolean;
  resulted_in_closure: boolean;
  metadata?: unknown;
  created_at?: string | null;
  updated_at?: string | null;
}

/**
 * An outreach template record (TemplateResponse Pydantic model).
 */
export interface OutreachTemplate {
  id: number;
  tenant_id: string;
  channel: OutreachChannel;
  name: string;
  subject?: string | null;
  message_text: string;
  trigger_rules?: unknown;
  is_active: boolean;
  created_at?: string | null;
  updated_at?: string | null;
}

/** Per-channel metrics sub-object (ChannelMetrics Pydantic model). */
export interface OutreachChannelMetrics {
  queued: number;
  sent: number;
  delivered: number;
  responded: number;
  visits: number;
  closed: number;
  response_rate: number;
  visit_rate: number;
  closure_rate: number;
}

/**
 * Response from GET /api/recapture/outreach/summary
 * (OutreachSummaryResponse Pydantic model)
 */
export interface OutreachSummary {
  year?: number | null;
  total_sent: number;
  total_responded: number;
  total_closed: number;
  conversion_rate: number;
  avg_days_to_response?: number | null;
  estimated_revenue: number;
  by_channel: Record<string, OutreachChannelMetrics>;
}

/** Aggregate outreach metrics for a year. */
export async function getOutreachSummary(year?: number): Promise<OutreachSummary> {
  const { data } = await api.get<OutreachSummary>('/api/recapture/outreach/summary', {
    params: { year },
  });
  return data;
}

/** List outreach templates. Returns the templates array directly. */
export async function getOutreachTemplates(): Promise<OutreachTemplate[]> {
  const { data } = await api.get<{ templates: OutreachTemplate[]; total: number }>(
    '/api/recapture/outreach/templates',
  );
  return data.templates;
}

/** Create an outreach template. */
export async function createOutreachTemplate(body: {
  channel: OutreachChannel;
  name: string;
  message_text: string;
  subject?: string | null;
  trigger_rules?: unknown;
  is_active?: boolean;
}): Promise<OutreachTemplate> {
  const { data } = await api.post<OutreachTemplate>(
    '/api/recapture/outreach/templates',
    body,
  );
  return data;
}

/** Seed default SMS/portal/phone templates if missing. */
export async function seedOutreachDefaults(): Promise<{
  created: OutreachTemplate[];
  total_created: number;
}> {
  const { data } = await api.post('/api/recapture/outreach/templates/seed-defaults');
  return data;
}

/** Chronological outreach events for a gap. */
export async function getGapOutreachHistory(gapId: number): Promise<OutreachEvent[]> {
  const { data } = await api.get<{ events: OutreachEvent[]; total: number; gap_id: number }>(
    `/api/recapture/gaps/${gapId}/outreach-history`,
  );
  return data.events;
}

// ---------------------------------------------------------------------------
// Provider benchmark — ProviderRecaptureCard, ProviderRecaptureLeaderboard
// ---------------------------------------------------------------------------

/**
 * One provider row in the leaderboard.
 * Field names mirror the dict returned by compute_provider_rates().
 */
export interface ProviderRecaptureRow {
  provider_id: number;
  provider_name?: string | null;
  npi?: string | null;
  specialty?: string | null;
  panel_size: number;
  total_gaps: number;
  gaps_open: number;
  gaps_closed: number;
  recapture_rate: number;
  /** Dollar field names include $ to match the backend dict keys. */
  "$_recaptured": number;
  "$_at_risk": number;
}

/** Specialty cohort statistics sub-object. */
export interface SpecialtyCohort {
  n: number;
  median_rate: number;
  q1_rate: number;
  q3_rate: number;
  top_provider?: string | null;
}

/** Network-wide quartile summary sub-object. */
export interface NetworkSummary {
  n: number;
  median_rate: number;
  q1_rate: number;
  q3_rate: number;
}

/** Response from GET /api/recapture/provider-leaderboard */
export interface ProviderRecaptureLeaderboardResponse {
  year: number;
  providers: ProviderRecaptureRow[];
  specialty_cohorts: Record<string, SpecialtyCohort>;
  network: NetworkSummary;
}

/** Per-provider recapture rate leaderboard with cohort context. */
export async function getProviderRecaptureLeaderboard(
  year: number,
): Promise<ProviderRecaptureLeaderboardResponse> {
  const { data } = await api.get<ProviderRecaptureLeaderboardResponse>(
    '/api/recapture/provider-leaderboard',
    { params: { year } },
  );
  return data;
}

/**
 * Response from GET /api/recapture/provider/{id}/percentile
 * Derived from provider_percentile() in recapture_provider_benchmark.py.
 * The router appends top_unrecaptured_hccs and year to this response.
 */
export interface ProviderPercentileResponse {
  provider_id: number;
  provider_name?: string | null;
  specialty?: string | null;
  recapture_rate: number;
  percentile_in_specialty?: number | null;
  percentile_in_network?: number | null;
  specialty_median?: number | null;
  network_median: number;
  ranks_among_n: number;
  insufficient_peers: boolean;
  year: number;
  top_unrecaptured_hccs: Array<{
    hcc_code: string;
    /** Patient count (field name from provider_unrecaptured_top_hccs service). */
    count: number;
    "$_at_risk": number;
  }>;
}

/** Provider percentile rank vs specialty + network.
 *  Response includes provider's own rates plus top unrecaptured HCCs. */
export async function getProviderRecapturePercentile(
  providerId: number,
  year: number,
): Promise<ProviderPercentileResponse> {
  const { data } = await api.get<ProviderPercentileResponse>(
    `/api/recapture/provider/${providerId}/percentile`,
    { params: { year } },
  );
  return data;
}

/**
 * Response from GET /api/recapture/provider/{id}/trend
 * Derived from provider_decay() in recapture_provider_benchmark.py.
 */
export interface ProviderTrendResponse {
  provider_id: number;
  years: number[];
  rates: number[];
  deltas: Array<number | null>;
}

/** Per-year recapture rate for a single provider (sparkline data). */
export async function getProviderRecaptureTrend(
  providerId: number,
  years = 3,
): Promise<ProviderTrendResponse> {
  const { data } = await api.get<ProviderTrendResponse>(
    `/api/recapture/provider/${providerId}/trend`,
    { params: { years } },
  );
  return data;
}

// ---------------------------------------------------------------------------
// Readiness — ReadinessDetailModal, ReadinessSummaryCard
// ---------------------------------------------------------------------------

/** Score components sub-object (ReadinessComponents Pydantic model). */
export interface ReadinessComponents {
  problem_list: boolean;
  problem_list_recent: boolean;
  recent_encounter: boolean;
  meat: Record<string, number>;
}

/**
 * Single-gap readiness payload (ReadinessPayload Pydantic model).
 */
export interface GapReadiness {
  gap_id: number;
  patient_id: number | string;
  hcc_code: string;
  icd10_code?: string | null;
  current_year: number;
  score: number;
  components: ReadinessComponents;
  score_breakdown: Record<string, number>;
  defensibility_tier: "strong" | "moderate" | "weak";
  recommended_actions: string[];
  problem_list_matches: Array<Record<string, unknown>>;
  last_encounter_in_window?: string | null;
  computed_at: string;
}

/** Recapture readiness score for one gap. */
export async function getGapReadiness(gapId: number): Promise<GapReadiness> {
  const { data } = await api.get<GapReadiness>(
    `/api/recapture/gaps/${gapId}/readiness`,
  );
  return data;
}

/**
 * Aggregate readiness summary (ReadinessSummaryResponse Pydantic model).
 */
export interface ReadinessSummary {
  year: number;
  total_open_gaps: number;
  average_score: number;
  defensibility_distribution: {
    strong: number;
    moderate: number;
    weak: number;
  };
  actionable_gaps: number;
}

/** Aggregate recapture readiness summary for all open gaps in a year. */
export async function getReadinessSummary(year: number): Promise<ReadinessSummary> {
  const { data } = await api.get<ReadinessSummary>(
    '/api/recapture/readiness/summary',
    { params: { year } },
  );
  return data;
}

// ---------------------------------------------------------------------------
// Recurring gaps — RecurringGapsList, RecurringGapAlert (type only)
// ---------------------------------------------------------------------------

/**
 * A recurring-gap record as returned by GET /api/recapture/recurring.
 * The actual row is a dict from get_recurring_gaps() so we type all fields
 * that the RecurringGapsList component accesses.
 */
export interface RecurringGap {
  id: number;
  patient_id: number;
  patient_name?: string | null;
  hcc_code: string;
  icd10_code?: string | null;
  years_recurring?: number | null;
  is_recurring?: boolean | null;
  current_year?: number;
  status?: string;
  revenue_impact?: number | null;
  /** Set after markGapAwvScheduled is called. */
  awv_suggested?: boolean | null;
  /** ISO date string set by the AWV scheduled endpoint. */
  awv_visit_date?: string | null;
  /** Patient date of birth (joined from patients table). */
  dob?: string | null;
  /** Provider NPI attributed to this gap. */
  provider_npi?: string | null;
}

/** Response wrapper from GET /api/recapture/recurring */
export interface RecurringListResponse {
  year: number;
  total: number;
  items: RecurringGap[];
}

/** Detect recurring (multi-year) recapture gaps and flag them. */
export async function detectRecurringGaps(
  currentYear: number,
  lookbackYears = 3,
): Promise<{ current_year: number; lookback_years: number; matches: number; items: RecurringGap[] }> {
  const { data } = await api.post('/api/recapture/recurring/detect', {
    current_year: currentYear,
    lookback_years: lookbackYears,
  });
  return data;
}

/** List recurring recapture gaps for a year. */
export async function listRecurringGaps(year: number): Promise<RecurringListResponse> {
  const { data } = await api.get<RecurringListResponse>('/api/recapture/recurring', {
    params: { year },
  });
  return data;
}

// ---------------------------------------------------------------------------
// Decay curve + velocity + slow movers — RecaptureDecayChart, RecaptureVelocityKpis, RecaptureSlowMovers
// ---------------------------------------------------------------------------

/** One data point in a decay-curve cohort. */
export interface DecayCurvePoint {
  month_of_year: number;
  closed_count: number;
  closure_rate: number;
  cumulative_closed_pct: number;
  "$_recaptured": number;
  "cumulative_$_recaptured": number;
}

/** One cohort in the decay-curve response. */
export interface DecayCurveCohort {
  cohort_year: number;
  total_gaps: number;
  closed_gaps: number;
  points: DecayCurvePoint[];
}

/**
 * Response from GET /api/recapture/decay-curve
 * Derived from get_decay_curve() return dict in recapture_decay.py.
 */
export interface RecaptureDecayCurveResponse {
  current_year: number;
  lookback_years: number;
  cohorts: DecayCurveCohort[];
}

/** Multi-year recapture decay curve (cohort × month-of-year). */
export async function getRecaptureDecayCurve(
  year?: number,
  lookback = 3,
): Promise<RecaptureDecayCurveResponse> {
  const { data } = await api.get<RecaptureDecayCurveResponse>(
    '/api/recapture/decay-curve',
    { params: { year, lookback } },
  );
  return data;
}

/**
 * Response from GET /api/recapture/velocity
 * Derived from get_velocity_kpis() return dict in recapture_decay.py.
 * Note: backend keys include $ characters (e.g. "ytd_$_recaptured").
 */
export interface RecaptureVelocityResponse {
  year: number;
  avg_days_to_close: number;
  median_days_to_close: number;
  "ytd_$_recaptured": number;
  "ye_projected_$": number;
  days_remaining_in_year: number;
  days_to_close_target_30: number;
  early_recapture_rate: number;
  late_recapture_rate: number;
  total_cohort_gaps: number;
  closed_cohort_gaps: number;
  open_cohort_gaps: number;
}

/** Recapture velocity KPIs for the given measurement year. */
export async function getRecaptureVelocity(year?: number): Promise<RecaptureVelocityResponse> {
  const { data } = await api.get<RecaptureVelocityResponse>('/api/recapture/velocity', {
    params: { year },
  });
  return data;
}

/** One slow-mover HCC row. */
export interface SlowMoverRow {
  hcc_code: string;
  description: string;
  avg_days_to_close: number | null;
  open_count: number;
  "$_at_risk": number;
  total_gaps: number;
  closed_count: number;
}

/**
 * Response from GET /api/recapture/slow-movers
 * Derived from the router return dict in recapture_decay.py.
 */
export interface RecaptureSlowMoversResponse {
  year: number;
  limit: number;
  slow_movers: SlowMoverRow[];
}

/** HCC codes with the slowest closure velocity. */
export async function getRecaptureSlowMovers(
  year?: number,
  limit = 10,
): Promise<RecaptureSlowMoversResponse> {
  const { data } = await api.get<RecaptureSlowMoversResponse>(
    '/api/recapture/slow-movers',
    { params: { year, limit } },
  );
  return data;
}


// ---------------------------------------------------------------------------
// HEDIS / Star Ratings + Health Equity Index (HEI)
// ---------------------------------------------------------------------------

export interface HedisMeasureMeta {
  measure_id: string;
  name: string;
  description: string;
  age_min: number | null;
  age_max: number | null;
  sex_restriction: string | null;
  higher_is_better: boolean;
  star_cutoffs_pct: number[];
  ncqa_spec: string;
}

export interface HedisMeasureScore {
  measure_id: string;
  name: string;
  denominator: number;
  numerator: number;
  rate_pct: number;
  stars: number;
  star_cutoffs_pct: number[];
  sub_rates?: Record<
    string,
    { numerator: number; rate_pct: number; stars: number }
  >;
}

export interface HedisScoresResponse {
  measurement_year: number;
  tenant_id: number;
  patient_population: number;
  measures: HedisMeasureScore[];
}

export interface HedisSegmentRate {
  segment: "dual" | "lis" | "disability" | "other";
  denominator: number;
  numerator: number;
  rate_pct: number;
  stars: number;
}

export interface HedisMeasureBySegment {
  measure_id: string;
  name: string;
  by_segment: HedisSegmentRate[];
  disparity_gap_pct: number;
}

export interface HedisSegmentResponse {
  measurement_year: number;
  tenant_id: number;
  segment_population: Record<string, number>;
  measures: HedisMeasureBySegment[];
  segments: string[];
}

export interface HedisFailingPatient {
  patient_id: number;
  first_name: string | null;
  last_name: string | null;
  dob: string | null;
  sex: string | null;
  hei_segment: "dual" | "lis" | "disability" | "other";
  evidence: string[];
  exclusions: string[];
}

export interface HedisFailingResponse {
  measure_id: string;
  measurement_year: number;
  tenant_id: number;
  total: number;
  limit: number;
  offset: number;
  patients: HedisFailingPatient[];
}

export async function getHedisMeasures(year?: number) {
  const { data } = await api.get<{
    measurement_year: number;
    measures: HedisMeasureMeta[];
    star_cutoffs: Record<string, number[]>;
    licensing_notice: string;
  }>("/api/hedis/measures", { params: year ? { year } : undefined });
  return data;
}

export async function getHedisScores(year?: number) {
  const { data } = await api.get<HedisScoresResponse>("/api/hedis/scores", {
    params: year ? { year } : undefined,
  });
  return data;
}

export async function getHedisScoresBySegment(year?: number) {
  const { data } = await api.get<HedisSegmentResponse>(
    "/api/hedis/scores/by-segment",
    { params: year ? { year } : undefined },
  );
  return data;
}

export async function getHedisPatientsFailing(
  measureId: string,
  year?: number,
  limit = 200,
  offset = 0,
) {
  const { data } = await api.get<HedisFailingResponse>(
    `/api/hedis/patients-failing/${encodeURIComponent(measureId)}`,
    { params: { year, limit, offset } },
  );
  return data;
}

// ---------------------------------------------------------------------------
// Per-patient HEDIS gaps — co-located with HCC suspects on patient detail page
// ---------------------------------------------------------------------------

export interface PatientHedisGap {
  measure_id: string;
  name: string;
  status: "open" | "met";
  last_value: string | null;
  due_date: string | null;
  evidence: unknown[];
  exclusions: string[];
}

export interface PatientHedisGapsResponse {
  patient_id: number;
  measurement_year: number;
  open_gaps: PatientHedisGap[];
  all_gaps: PatientHedisGap[];
}

export async function getPatientHedisGaps(
  pid: string | number,
  year?: number,
): Promise<PatientHedisGapsResponse> {
  const { data } = await api.get<PatientHedisGapsResponse>(
    `/api/hedis/patient/${pid}/gaps`,
    { params: year ? { year } : undefined },
  );
  return data;
}
