import axios from "axios";
import logger from "@/lib/logger";
import type {
  Patient,
  DashboardStats,
  SuspectCondition,
  AuditPackage,
  AnalysisResult,
  DBSuspect,
} from "@/types";

const api = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_URL || "http://localhost:8500",
  headers: { "Content-Type": "application/json" },
  timeout: 180000, // 3 minutes — complex clinical notes can take 60-90s
});

// --- Logging interceptors ---

api.interceptors.request.use(
  (config) => {
    (config as any)._startTime = Date.now();
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
    const duration = Date.now() - ((response.config as any)._startTime ?? Date.now());
    logger.api(
      response.config.method ?? "GET",
      response.config.url ?? "",
      response.status,
      duration
    );
    return response;
  },
  (error) => {
    const config = error?.config;
    const duration = config?._startTime ? Date.now() - config._startTime : 0;
    const status = error?.response?.status ?? 0;
    const url = config?.url ?? "unknown";
    const method = config?.method ?? "GET";
    logger.api(method, url, status, duration);
    logger.error("API", `Request failed: ${method.toUpperCase()} ${url}`, {
      status,
      data: error?.response?.data,
      message: error?.message,
    });
    return Promise.reject(error);
  }
);

// Dashboard
export async function getDashboardStats(): Promise<DashboardStats> {
  const { data } = await api.get("/api/dashboard/stats");
  return data;
}

// Patients
export async function getPatients(): Promise<Patient[]> {
  const { data } = await api.get("/api/patients");
  return data.patients ?? data;
}

export async function searchPatients(params: {
  search?: string;
  limit?: number;
  offset?: number;
}): Promise<{ total: number; patients: any[]; limit: number; offset: number }> {
  const { data } = await api.get("/api/patients", { params });
  return data;
}

export async function getPatientsWithEncounters(): Promise<any[]> {
  const { data } = await api.get("/api/patients/with-encounters");
  return data.patients ?? data;
}

export async function getPatient(pid: string | number): Promise<Record<string, unknown>> {
  const { data } = await api.get(`/api/patients/${pid}`);
  return data;
}

export async function getPatientEncounters(pid: string | number): Promise<{
  pid: number;
  count: number;
  encounters: Array<{
    encounter_id: number;
    date: string;
    reason?: string;
    provider_fname?: string;
    provider_lname?: string;
  }>;
}> {
  const { data } = await api.get(`/api/patients/${pid}/encounters`);
  return data;
}

// RAF
export async function calculateRAF(pid: string): Promise<{ raf_score: number }> {
  const { data } = await api.post(`/api/raf/calculate/${pid}`);
  return data;
}

// Suspects
export async function getSuspects(
  status: string = "open",
  limit: number = 200
): Promise<{ status_filter: string; count: number; suspects: DBSuspect[] }> {
  const { data } = await api.get("/api/suspects", { params: { status, limit } });
  return data;
}

export async function acceptSuspect(
  suspectId: number,
  reviewedBy: string = "frontend_user"
): Promise<unknown> {
  const { data } = await api.put(`/api/suspects/${suspectId}/accept`, {
    reviewed_by: reviewedBy,
  });
  return data;
}

export async function dismissSuspect(
  suspectId: number,
  reviewedBy: string = "frontend_user",
  reason: string = "dismissed via UI"
): Promise<unknown> {
  const { data } = await api.put(`/api/suspects/${suspectId}/dismiss`, {
    reviewed_by: reviewedBy,
    reason,
  });
  return data;
}

export async function bulkUpdateSuspects(
  ids: number[],
  action: "accept" | "dismiss",
  reviewedBy: string = "frontend_user",
  reason: string = "bulk update via UI"
): Promise<{ action: string; requested: number; succeeded: number; failed: number }> {
  const { data } = await api.post("/api/suspects/bulk-update", {
    ids,
    action,
    reviewed_by: reviewedBy,
    reason,
  });
  return data;
}

export async function scanAllSuspects(): Promise<{
  patients_scanned: number;
  total_new_suspects: number;
  per_patient: Array<{ pid: number; new_suspects: number }>;
  errors: Array<{ pid: number; error: string }>;
}> {
  const { data } = await api.post("/api/suspects/scan-all");
  return data;
}

export async function scanPatientSuspects(pid: number): Promise<unknown> {
  const { data } = await api.post(`/api/suspects/scan/${pid}`);
  return data;
}

// Analysis
export async function analyzeEncounter(
  encounterId: number,
  includeContext: boolean = true,
  saveResults: boolean = true
): Promise<AnalysisResult> {
  const { data } = await api.post(`/api/analysis/encounter/${encounterId}`, {
    include_context: includeContext,
    save_results: saveResults,
  });
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

// Batch analysis
export async function batchAnalysis(
  pid: number,
  saveResults: boolean = true
): Promise<{ job_id: string; status: string; message: string }> {
  const { data } = await api.post(`/api/analysis/batch/${pid}?save_results=${saveResults}`);
  return data;
}

export async function getJobStatus(jobId: string): Promise<Record<string, unknown>> {
  const { data } = await api.get(`/api/analysis/jobs/${jobId}`);
  return data;
}

// Audit
export async function getAuditPackages(pid?: number): Promise<{
  count: number;
  packages: Array<{
    id: number;
    pid: number;
    year: number;
    filepath?: string;
    file_size_bytes?: number;
    created_at: string;
  }>;
}> {
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
): Promise<{
  pid: number;
  year: number;
  package_id: number;
  filename: string;
  size_bytes: number;
  download_url: string;
}> {
  const { data } = await api.post(`/api/audit/generate/${pid}`, options ?? {});
  return data;
}

export function getAuditDownloadUrl(packageId: number): string {
  const base = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8500";
  return `${base}/api/audit/packages/${packageId}/download`;
}

// Population Summary
export async function getPopulationSummary() {
  const { data } = await api.get("/api/raf/population-summary");
  return data;
}

export async function calculateAllRAF() {
  const { data } = await api.post("/api/raf/calculate-all");
  return data;
}

// Reports
export async function getRevenueOpportunity(year?: number) {
  const { data } = await api.get("/api/reports/revenue-opportunity", {
    params: year ? { year } : undefined,
  });
  return data as {
    measurement_year: number;
    total_patients_analyzed: number;
    total_billing_raf: number;
    total_ai_raf: number;
    total_gap: number;
    estimated_annual_revenue: number;
    average_raf_score: number;
  };
}

export async function getPatientScorecard(year?: number) {
  const { data } = await api.get("/api/reports/patient-scorecard", {
    params: year ? { year } : undefined,
  });
  return data as Array<{
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
  }>;
}

export async function getHccDistribution(year?: number) {
  const { data } = await api.get("/api/reports/hcc-distribution", {
    params: year ? { year } : undefined,
  });
  return data as Array<{
    hcc_code: string;
    patient_count: number;
  }>;
}

export async function getSuspectsSummary(status: string = "open") {
  const { data } = await api.get("/api/reports/suspects-summary", {
    params: { status },
  });
  return data as Array<{
    patient_id: number;
    condition: string;
    icd10_code: string;
    hcc_code: string | null;
    confidence_score: number | null;
    status: string;
    rationale: string;
  }>;
}

// Patient comprehensive profile
export async function getPatientProfile(pid: string | number): Promise<any> {
  const { data } = await api.get(`/api/patients/${pid}/comprehensive-profile`);
  return data;
}

// RAF endpoints
export async function getRAFScores(pid: string | number, year?: number): Promise<any> {
  const { data } = await api.get(`/api/raf/scores/${pid}`, { params: year ? { year } : undefined });
  return data;
}

export async function getRAFBreakdown(pid: string | number, year?: number): Promise<any> {
  const { data } = await api.get(`/api/raf/scores/${pid}/breakdown`, { params: year ? { year } : undefined });
  return data;
}

export async function getRAFHistory(pid: string | number): Promise<any> {
  const { data } = await api.get(`/api/raf/scores/${pid}/history`);
  return data;
}

// Patient clinical data
export async function getPatientMedications(pid: string | number): Promise<any> {
  const { data } = await api.get(`/api/patients/${pid}/medications`);
  return data;
}

export async function getPatientDiagnoses(pid: string | number): Promise<any> {
  const { data } = await api.get(`/api/patients/${pid}/diagnoses`);
  return data;
}

export async function getPatientProblemList(pid: string | number): Promise<any> {
  const { data } = await api.get(`/api/patients/${pid}/problem-list`);
  return data;
}

export async function getPatientVitalsSuspects(pid: string | number): Promise<any> {
  const { data } = await api.get(`/api/patients/${pid}/vitals-suspects`);
  return data;
}

export async function getPatientLabSuspects(pid: string | number): Promise<any> {
  const { data } = await api.get(`/api/patients/${pid}/lab-suspects`);
  return data;
}

export async function getPatientProcedures(pid: string | number): Promise<any> {
  const { data } = await api.get(`/api/patients/${pid}/procedures`);
  return data;
}

export async function getPatientRecaptureGaps(pid: string | number, year?: number): Promise<any> {
  const y = year || new Date().getFullYear();
  const { data } = await api.get(`/api/patients/${pid}/recapture-gaps`, { params: { year: y } });
  return data;
}

export async function getPatientAllergies(pid: string | number): Promise<any> {
  const { data } = await api.get(`/api/patients/${pid}/allergies`);
  return data;
}

export async function getPatientImmunizations(pid: string | number): Promise<any> {
  const { data } = await api.get(`/api/patients/${pid}/immunizations`);
  return data;
}

export async function getPatientEnrollment(pid: string | number): Promise<any> {
  const { data } = await api.get(`/api/patients/${pid}/enrollment`);
  return data;
}

export async function getPatientMedicationGaps(pid: string | number, year?: number): Promise<any> {
  const { data } = await api.get(`/api/patients/${pid}/medication-gaps`, { params: year ? { year } : undefined });
  return data;
}

export async function getPatientHedis(pid: string | number, year?: number): Promise<any> {
  const { data } = await api.get(`/api/patients/${pid}/hedis`, { params: year ? { year } : undefined });
  return data;
}

export async function getPatientSdoh(pid: string | number): Promise<any> {
  const { data } = await api.get(`/api/patients/${pid}/sdoh`);
  return data;
}

export async function getPatientFamilyHistory(pid: string | number): Promise<any> {
  const { data } = await api.get(`/api/patients/${pid}/family-history`);
  return data;
}

export async function getPatientReferrals(pid: string | number): Promise<any> {
  const { data } = await api.get(`/api/patients/${pid}/referrals`);
  return data;
}

// Reports
export async function getRecaptureGapsReport(year?: number) {
  const { data } = await api.get("/api/reports/recapture-gaps", { params: year ? { year } : undefined });
  return data;
}

export async function getDataCompleteness() {
  const { data } = await api.get("/api/reports/data-completeness");
  return data;
}

// Patient suspects
export async function getPatientSuspects(pid: string | number, status: string = "open"): Promise<any> {
  const { data } = await api.get(`/api/suspects/${pid}`, { params: { status } });
  return data;
}

// Legacy aliases for backward compatibility
export { acceptSuspect as updateSuspect };

export default api;
