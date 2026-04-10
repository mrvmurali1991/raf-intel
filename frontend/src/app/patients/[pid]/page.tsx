"use client";

import React, { use, useState, useRef, useEffect, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import {
  Printer,
  FileUp,
  FileText,
  Upload,
  CheckCircle2,
  XCircle,
  Eye,
  Brain,
  Paperclip,
  FlaskConical,
  Stethoscope,
  ClipboardList,
  TrendingUp,
} from "lucide-react";
import {
  getPatient,
  getPatientProfile,
  getRAFBreakdown,
  getRAFHistory,
  getPatientEncounters,
  getPatientSuspects,
  getPatientMedications,
  getPatientProblemList,
  getPatientRecaptureGaps,
  getPatientLabSuspects,
  getPatientVitalsSuspects,
  getPatientAllergies,
  getPatientImmunizations,
  getPatientFamilyHistory,
  getPatientSdoh,
  getPatientMedicationGaps,
  getAuditPackages,
  downloadAuditPackage,
  calculateRAF,
  generateAudit,
  acceptSuspect,
  dismissSuspect,
  analyzeEncounter,
  batchAnalysis,
  getJobStatus,
  getPatientDocuments,
  uploadPatientDocument,
  getDocumentAnalysis,
  getDocumentDiagnoses,
  confirmDocumentDiagnosis,
  rejectDocumentDiagnosis,
  getDocumentDraftRAF,
  analyzeDocument,
  lookupICD10Crosswalk,
} from "@/lib/api";
import { ModelComparison } from "@/components/model-comparison";
import { getAccessToken } from "@/contexts/auth-context";
import {
  RiskGauge,
  RiskBadge,
  MeatIndicator,
  ConfidencePill,
  DataRow,
  SectionHeader,
  EmptyState,
  ProgressBar,
} from "@/components/healthcare-ui";
import { useToast } from "@/components/Toast";
import { calculateAge } from "@/lib/utils";
import type { Patient, MEATEvidence, AnalysisResult, DBSuspect, AIDiagnosis } from "@/types";
import type {
  PatientProfile,
  RafBreakdown,
  RafHistoryResponse,
  PatientEncountersResponse,
  PatientSuspectsResponse,
  MedicationsResponse,
  ClinicalFindingsResponse,
  AllergiesResponse,
  ImmunizationsResponse,
  FamilyHistoryResponse,
  SdohResponse,
  MedicationGapsResponse,
  ProblemListResponse,
  RecaptureGapsResponse,
  AuditPackagesResponse,
  DocumentsResponse,
  DocumentAnalysisResult,
  CrosswalkResult,
} from "@/lib/api";

// ---------------------------------------------------------------------------
// Local Types
// ---------------------------------------------------------------------------

/** HCC detail from the RAF breakdown endpoint (runtime shape is wider than RafBreakdown type) */
interface HCCDetail {
  hcc_code?: string;
  code?: string;
  hcc_label?: string;
  label?: string;
  coefficient?: number;
  hcc_coefficient?: number;
  icd10_codes?: Array<string | { code?: string; icd10_code?: string }>;
  supporting_icd10s?: Array<string | { code?: string; icd10_code?: string }>;
  meat_status?: "complete" | "partial" | "missing";
  meat_evidence?: MEATEvidence;
  meat_status_detail?: { monitor?: boolean; evaluate?: boolean; assess?: boolean; treat?: boolean };
}

/** Extended RAF breakdown as returned at runtime (wider than the strict api type) */
interface ExtendedRafBreakdown extends Omit<RafBreakdown, "hcc_details"> {
  total_raf?: number;
  raf_score?: number;
  hcc_details?: HCCDetail[];
  hcc_count?: number;
  model_segment?: string;
  demographic_base?: number;
  measurement_year?: number;
  final_raf?: number;
}

/** Score history entry (from scores/history endpoint) */
interface ScoreHistoryEntry {
  id?: number;
  raf_score?: number;
  score?: number;
  total_score?: number;
  year?: number;
  measurement_year?: number;
  model?: string;
  calculated_at?: string;
  created_at?: string;
}

/** Encounter item from the encounters endpoint */
interface EncounterItem {
  encounter_id: number;
  date: string;
  encounter_date?: string;
  reason?: string;
  provider_fname?: string;
  provider_lname?: string;
  notes?: string;
  has_notes?: boolean;
  analyzed_at?: string;
  has_analysis?: boolean;
  analysis?: AnalysisResult;
  cached_analysis?: AnalysisResult;
}

/** Suspect item from the suspects endpoint (DB row) */
interface SuspectItem extends DBSuspect {
  condition?: string;
  suspect_condition?: string;
  hcc_description?: string;
  icd10_code?: string;
  icd10?: string;
  hcc_code?: string;
  rationale?: string;
  evidence?: string;
  confidence?: number;
  hcc_coefficient?: number;
  suspect_id?: number;
  meat_evidence?: MEATEvidence;
  source?: string;
  identified_at?: string;
}

/** Problem list item */
interface ProblemItem {
  title?: string;
  condition?: string;
  diagnosis?: string;
  icd10_code?: string;
  diagnosis_code?: string;
  begdate?: string;
  onset_date?: string;
  date?: string;
}

/** Recapture gap item */
interface RecaptureGapItem {
  hcc_code?: string;
  hcc?: string;
  description?: string;
  label?: string;
  hcc_label?: string;
  condition?: string;
  last_coded_year?: number;
  last_captured_year?: number;
  prior_year?: number;
  evidence?: string;
  icd10_code?: string;
  onset_date?: string;
  begdate?: string;
  status?: string;
  coefficient?: number;
}

/** Medication item */
interface MedicationItem {
  drug?: string;
  title?: string;
  medication?: string;
  dosage?: string;
  dose?: string;
  frequency?: string;
  route?: string;
  begdate?: string;
  start_date?: string;
  date?: string;
}

/** Clinical finding item (vitals/labs) */
interface ClinicalFindingItem {
  condition?: string;
  finding?: string;
  evidence?: string;
  rationale?: string;
  detail?: string;
  icd10_code?: string;
  hcc_code?: string;
}

/** Allergy item */
interface AllergyItem {
  title?: string;
  allergen?: string;
  substance?: string;
  reaction?: string;
  severity?: string;
  begdate?: string;
}

/** Immunization item */
interface ImmunizationItem {
  title?: string;
  vaccine?: string;
  immunization?: string;
  administered_date?: string;
  create_date?: string;
  date?: string;
}

/** Family history item */
interface FamilyHistoryItem {
  condition?: string;
  title?: string;
  diagnosis?: string;
  relation?: string;
  relative?: string;
  age_at_onset?: number;
}

/** SDOH factor */
interface SdohFactor {
  category?: string;
  factor?: string;
  description?: string;
  risk_level?: string;
  screening_date?: string;
}

/** Medication gap */
interface MedicationGapItem {
  medication?: string;
  condition?: string;
  gap?: string;
  gap_type?: string;
  drug?: string;
  evidence?: string;
  rationale?: string;
  recommendation?: string;
  severity?: string;
  icd10_code?: string;
}

/** Document analysis data with diagnoses merged in */
interface DocumentAnalysisData extends DocumentAnalysisResult {
  diagnoses?: Array<{
    id?: number;
    icd10_code?: string;
    icd_code?: string;
    description?: string;
    diagnosis?: string;
    hcc_code?: string;
    raf_weight?: number;
    confidence?: number;
    status?: string;
    meat_status?: string;
    meat_evidence?: MEATEvidence;
    meat?: { M?: string; E?: string; A?: string; T?: string };
  }>;
}

/** Draft RAF data from document */
interface DraftRAFData {
  current_raf_score?: number;
  draft_raf_score?: number;
  draft_score?: number;
  raf_delta?: number;
  draft_raf?: number;
  new_hccs?: Array<string | { code?: string; hcc_code?: string; label?: string; description?: string; coefficient?: number; raf_weight?: number }>;
  new_hcc_codes?: Array<string | { code?: string; hcc_code?: string; label?: string; description?: string; coefficient?: number; raf_weight?: number }>;
  existing_hcc_codes?: string[];
  estimated_revenue_impact?: number;
  revenue_impact?: number;
}

/** Audit package item */
interface AuditPackageItem {
  id: number;
  pid?: number;
  year?: number;
  filepath?: string;
  file_size_bytes?: number;
  created_at: string;
}

/** Axios-like error shape for mutation error handlers */
interface ApiError {
  response?: { data?: { detail?: string } };
  message?: string;
}

// ---------------------------------------------------------------------------
// Design Tokens
// ---------------------------------------------------------------------------
const C = {
  bg: "#F8FAFC",
  white: "#FFFFFF",
  slate900: "#0F172A",
  slate800: "#1E293B",
  slate700: "#334155",
  slate600: "#475569",
  slate500: "#64748B",
  slate400: "#94A3B8",
  slate300: "#CBD5E1",
  slate200: "#E2E8F0",
  slate100: "#F1F5F9",
  blue600: "#0f766e",
  blue500: "#0d9488",
  blue100: "#ccfbf1",
  blue50: "#f0fdfa",
  emerald600: "#059669",
  emerald500: "#10B981",
  emerald100: "#D1FAE5",
  emerald50: "#ECFDF5",
  amber600: "#D97706",
  amber500: "#F59E0B",
  amber100: "#FEF3C7",
  amber50: "#FFFBEB",
  red600: "#DC2626",
  red500: "#EF4444",
  red100: "#FEE2E2",
  red50: "#FEF2F2",
  purple600: "#9333EA",
  purple100: "#EDE9FE",
  purple50: "#F5F3FF",
  amber700: "#B45309",
  orange500: "#F97316",
  gray200: "#E5E7EB",
  gray400: "#9CA3AF",
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function formatDate(d: string | null | undefined): string {
  if (!d) return "\u2014";
  try {
    return new Date(d).toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
  } catch {
    return d;
  }
}

function rafScoreColor(score: number): string {
  if (score >= 3.0) return C.red600;
  if (score >= 1.5) return C.amber600;
  return C.emerald600;
}

function Spinner({ size = 16 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      style={{ animation: "spin 1s linear infinite" }}
    >
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
      <circle
        cx="12"
        cy="12"
        r="10"
        stroke={C.slate300}
        strokeWidth="3"
        fill="none"
      />
      <path
        d="M12 2a10 10 0 0 1 10 10"
        stroke={C.blue600}
        strokeWidth="3"
        strokeLinecap="round"
        fill="none"
      />
    </svg>
  );
}

function SectionLoader({ label }: { label?: string }) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        gap: 8,
        padding: "48px 0",
        color: C.slate400,
      }}
    >
      <Spinner size={18} />
      <span style={{ fontSize: 13 }}>{label || "Loading..."}</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Card wrapper (inline styles)
// ---------------------------------------------------------------------------
function Card({
  children,
  style,
  noPadding,
  className: extraClassName,
}: {
  children: React.ReactNode;
  style?: React.CSSProperties;
  noPadding?: boolean;
  className?: string;
}) {
  return (
    <div
      className={`premium-card ${extraClassName || ""}`}
      style={{
        background: C.white,
        border: `1px solid ${C.slate200}`,
        borderRadius: 12,
        padding: noPadding ? 0 : 20,
        ...style,
      }}
    >
      {children}
    </div>
  );
}

// ---------------------------------------------------------------------------
// MEAT Dots (local for encounters/raf detail)
// ---------------------------------------------------------------------------
function MeatDots({ evidence }: { evidence?: MEATEvidence | Record<string, any> | null }) {
  const letters = [
    { key: "monitor" as const, alt: ["M", "m"], label: "M", color: C.blue600 },
    { key: "evaluate" as const, alt: ["E", "e"], label: "E", color: C.purple600 },
    { key: "assess" as const, alt: ["A", "a"], label: "A", color: C.amber600 },
    { key: "treat" as const, alt: ["T", "t"], label: "T", color: C.emerald600 },
  ];
  return (
    <div style={{ display: "inline-flex", gap: 4 }}>
      {letters.map(({ key, alt, label, color }) => {
        const e = evidence as any;
        const filled = e && (e[key] || alt.some((a) => e[a]));
        return (
          <span
            key={key}
            style={{
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
              width: 26,
              height: 26,
              borderRadius: 6,
              fontSize: 11,
              fontWeight: 800,
              backgroundColor: filled ? `${color}20` : "transparent",
              color: filled ? color : C.gray400,
              border: `2px solid ${filled ? color : C.gray200}`,
              transition: "all 0.2s",
              boxShadow: filled ? `0 2px 6px ${color}25` : "none",
            }}
          >
            {label}
          </span>
        );
      })}
    </div>
  );
}

// ===========================================================================
// MAIN PAGE COMPONENT
// ===========================================================================

export default function PatientDetailPage({
  params,
}: {
  params: Promise<{ pid: string }>;
}) {
  const { pid } = use(params);
  const toast = useToast();
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState("overview");
  const [selectedYear, setSelectedYear] = useState(new Date().getFullYear());
  const [lastAnalysisResult, setLastAnalysisResult] = useState<Record<number, any>>({});

  // ---- Core queries (always fetched) ----
  const patientQ = useQuery({
    queryKey: ["patient", pid],
    queryFn: () => getPatient(pid),
  });

  const profileQ = useQuery({
    queryKey: ["patient-profile", pid],
    queryFn: () => getPatientProfile(pid),
  });

  const rafBreakdownQ = useQuery({
    queryKey: ["raf-breakdown", pid, selectedYear],
    queryFn: () => getRAFBreakdown(pid, selectedYear),
  });

  const rafHistoryQ = useQuery({
    queryKey: ["raf-history", pid],
    queryFn: () => getRAFHistory(pid),
  });

  const encountersQ = useQuery({
    queryKey: ["patient-encounters", pid, selectedYear],
    queryFn: () => getPatientEncounters(pid, selectedYear),
  });

  const problemsQ = useQuery({
    queryKey: ["patient-problems", pid, selectedYear],
    queryFn: () => getPatientProblemList(pid, selectedYear),
  });

  const suspectsQ = useQuery<any>({
    queryKey: ["patient-suspects", pid, selectedYear],
    queryFn: () => getPatientSuspects(pid, "open", selectedYear) as Promise<any>,
  });

  // ---- Tab-specific queries ----
  const medsQ = useQuery({
    queryKey: ["patient-meds", pid, selectedYear],
    queryFn: () => getPatientMedications(pid, selectedYear),
    enabled: activeTab === "clinical" || activeTab === "overview",
  });

  const recaptureQ = useQuery({
    queryKey: ["patient-recapture", pid, selectedYear],
    queryFn: () => getPatientRecaptureGaps(pid, selectedYear),
    enabled: activeTab === "raf" || activeTab === "overview",
  });

  const labSuspectsQ = useQuery({
    queryKey: ["patient-lab-suspects", pid, selectedYear],
    queryFn: () => getPatientLabSuspects(pid, selectedYear),
    enabled: activeTab === "clinical",
  });

  const vitalsSuspectsQ = useQuery({
    queryKey: ["patient-vitals-suspects", pid, selectedYear],
    queryFn: () => getPatientVitalsSuspects(pid, selectedYear),
    enabled: activeTab === "clinical",
  });

  const allergiesQ = useQuery({
    queryKey: ["patient-allergies", pid],
    queryFn: () => getPatientAllergies(pid),
    enabled: activeTab === "clinical",
  });

  const immunizationsQ = useQuery({
    queryKey: ["patient-immunizations", pid],
    queryFn: () => getPatientImmunizations(pid),
    enabled: activeTab === "clinical",
  });

  const familyHistoryQ = useQuery({
    queryKey: ["patient-family-history", pid],
    queryFn: () => getPatientFamilyHistory(pid),
    enabled: activeTab === "clinical",
  });

  const sdohQ = useQuery({
    queryKey: ["patient-sdoh", pid],
    queryFn: () => getPatientSdoh(pid),
    enabled: activeTab === "clinical",
  });

  const medGapsQ = useQuery({
    queryKey: ["patient-med-gaps", pid, selectedYear],
    queryFn: () => getPatientMedicationGaps(pid, selectedYear),
    enabled: activeTab === "clinical",
  });

  const auditsQ = useQuery({
    queryKey: ["patient-audits", pid],
    queryFn: () => getAuditPackages(Number(pid)),
    enabled: activeTab === "audit" || activeTab === "activity",
  });

  const documentsQ = useQuery({
    queryKey: ["patient-documents", pid],
    queryFn: () => getPatientDocuments(pid),
    enabled: activeTab === "documents",
  });

  // ---- Mutations ----
  const [lastCalcResult, setLastCalcResult] = useState<any>(null);

  const calcRAFMutation = useMutation({
    mutationFn: () => calculateRAF(pid, { year: selectedYear }),
    onSuccess: (data: any) => {
      setLastCalcResult(data);
      toast.success("RAF Calculated", `Score recalculated for ${selectedYear}.`);
      queryClient.invalidateQueries({ queryKey: ["raf-breakdown", pid, selectedYear] });
      queryClient.invalidateQueries({ queryKey: ["raf-history", pid] });
      queryClient.invalidateQueries({ queryKey: ["patient-profile", pid] });
    },
    onError: () => toast.error("Error", "Failed to calculate RAF score."),
  });

  const auditMutation = useMutation({
    mutationFn: (year?: number) => generateAudit(Number(pid), { year: year ?? selectedYear }),
    onSuccess: () => {
      toast.success("Audit Generated", "Audit package is ready.");
      queryClient.invalidateQueries({ queryKey: ["patient-audits", pid] });
    },
    onError: () => toast.error("Error", "Failed to generate audit package."),
  });

  const acceptMutation = useMutation({
    mutationFn: (id: number) => acceptSuspect(id),
    onSuccess: () => {
      toast.success("Accepted", "Suspect condition accepted.");
      queryClient.invalidateQueries({ queryKey: ["patient-suspects", pid, selectedYear] });
    },
  });

  const dismissMutation = useMutation({
    mutationFn: (id: number) => dismissSuspect(id),
    onSuccess: () => {
      toast.success("Dismissed", "Suspect condition dismissed.");
      queryClient.invalidateQueries({ queryKey: ["patient-suspects", pid, selectedYear] });
    },
  });

  const analyzeMutation = useMutation({
    mutationFn: (encId: number) => analyzeEncounter(encId),
    onSuccess: async (data, encId) => {
      const dxCount = data?.diagnoses?.length ?? 0;
      const hccCount =
        data?.diagnoses?.filter(
          (d: AIDiagnosis) => d.hcc_code || d.hcc || d.hcc_mapping?.hcc_code
        ).length ?? 0;
      setLastAnalysisResult((prev) => ({ ...prev, [encId]: data }));
      toast.success(
        "Analysis Complete",
        `Found ${dxCount} diagnoses, ${hccCount} HCC codes. Recalculating RAF...`
      );
      // Auto-recalculate RAF after encounter analysis
      try {
        await calculateRAF(pid, { year: selectedYear });
      } catch { /* ignore — user can click Calculate RAF manually */ }
      queryClient.invalidateQueries({ queryKey: ["patient-encounters", pid, selectedYear] });
      queryClient.invalidateQueries({ queryKey: ["patient-suspects", pid, selectedYear] });
      queryClient.invalidateQueries({ queryKey: ["patient-problems", pid, selectedYear] });
      queryClient.invalidateQueries({ queryKey: ["raf-breakdown", pid, selectedYear] });
      queryClient.invalidateQueries({ queryKey: ["raf-history", pid] });
      queryClient.invalidateQueries({ queryKey: ["patient-profile", pid] });
      queryClient.invalidateQueries({ queryKey: ["model-comparison", pid, selectedYear] });
    },
    onError: (e: ApiError) =>
      toast.error(
        "Analysis Failed",
        e?.response?.data?.detail || e?.message || "Encounter analysis failed."
      ),
  });

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Clean up any running poll on unmount
  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  const [batchStatus, setBatchStatus] = useState<string | null>(null);
  const batchMutation = useMutation({
    mutationFn: () => batchAnalysis(Number(pid)),
    onSuccess: async (data) => {
      const jobId = data.job_id;
      setBatchStatus("running");
      toast.success("Batch Started", "Analyzing all encounters...");
      pollRef.current = setInterval(async () => {
        try {
          const status = await getJobStatus(jobId);
          const done = status.status === "completed" || (status.status as string) === "SUCCESS";
          if (done) {
            clearInterval(pollRef.current!);
            pollRef.current = null;
            setBatchStatus(null);
            toast.success(
              "Batch Complete",
              `Analyzed ${status.processed ?? (status as any).progress ?? 0} encounters. Recalculating RAF score...`
            );
            // Auto-recalculate RAF score after analysis completes
            try {
              await calculateRAF(pid, { year: selectedYear });
              toast.success("RAF Updated", "RAF score has been recalculated with new analysis results.");
            } catch {
              toast.info("Note", "Analysis complete. Click 'Calculate RAF' to update the score.");
            }
            queryClient.invalidateQueries({
              queryKey: ["patient-encounters", pid, selectedYear],
            });
            queryClient.invalidateQueries({
              queryKey: ["patient-suspects", pid, selectedYear],
            });
            queryClient.invalidateQueries({
              queryKey: ["patient-problems", pid, selectedYear],
            });
            queryClient.invalidateQueries({
              queryKey: ["raf-breakdown", pid, selectedYear],
            });
            queryClient.invalidateQueries({
              queryKey: ["raf-history", pid],
            });
            queryClient.invalidateQueries({
              queryKey: ["patient-profile", pid],
            });
            queryClient.invalidateQueries({
              queryKey: ["model-comparison", pid, selectedYear],
            });
          } else if (status.status === "failed" || (status.status as string) === "FAILED") {
            clearInterval(pollRef.current!);
            pollRef.current = null;
            setBatchStatus(null);
            toast.error(
              "Batch Failed",
              (status.error as string) || "Analysis failed"
            );
          }
        } catch {
          clearInterval(pollRef.current!);
          pollRef.current = null;
          setBatchStatus(null);
        }
      }, 5000);
    },
    onError: (e: ApiError) => {
      setBatchStatus(null);
      toast.error(
        "Batch Failed",
        e?.response?.data?.detail ||
          e?.message ||
          "Failed to start batch analysis."
      );
    },
  });

  // ---- Derived data ----
  const patient = patientQ.data;
  const profile = profileQ.data as PatientProfile | undefined;
  const breakdown = rafBreakdownQ.data as ExtendedRafBreakdown | undefined;
  const history = rafHistoryQ.data as RafHistoryResponse | undefined;

  const patientName = patient
    ? `${patient.fname || patient.first_name || ""} ${patient.lname || patient.last_name || ""}`.trim()
    : "Loading...";
  const dob = patient?.DOB || patient?.dob || "";
  const sex = patient?.sex || patient?.gender || "";
  const age = dob ? calculateAge(dob) : null;

  const rafScore =
    breakdown?.final_raf ??
    breakdown?.total_raf ??
    breakdown?.raf_score ??
    null;
  const hccCount = breakdown?.hcc_details?.length ?? 0;
  const modelSegment = breakdown?.model_segment || "CNA";

  // MEAT compliance calc
  const meatTotal = hccCount * 4;
  const meatFilled = breakdown?.hcc_details
    ? breakdown.hcc_details.reduce((acc: number, hcc: HCCDetail) => {
        const e = hcc.meat_evidence || hcc.meat_status_detail || (hcc as any).meat_completeness;
        if (!e) return acc;
        return (
          acc +
          (e.monitor || e.m ? 1 : 0) +
          (e.evaluate || e.e ? 1 : 0) +
          (e.assess || e.a ? 1 : 0) +
          (e.treat || e.t ? 1 : 0)
        );
      }, 0)
    : 0;

  // Data quality — computed from year-filtered query data (mirrors DataCompletenessChecklist logic)
  const dataQuality = (() => {
    const encList = encountersQ.data?.encounters ?? (Array.isArray(encountersQ.data) ? encountersQ.data : []);
    const probList = Array.isArray(problemsQ.data) ? problemsQ.data : (problemsQ.data?.problems ?? []);
    const medList = Array.isArray(medsQ.data) ? medsQ.data : (medsQ.data?.medications ?? []);
    const dqSections = [
      encList.length > 0,
      encList.some((e: any) => e.notes || e.has_notes),
      probList.length > 0,
      medList.length > 0,
      !!(vitalsSuspectsQ.data?.suspects?.length),
      !!(labSuspectsQ.data?.suspects?.length),
      !!((profile?.billing as any)?.icd10_codes?.length),
      !!(profile?.enrollment) && (profile?.enrollment as any)?.source !== "default",
      Array.isArray(profile?.immunizations) && (profile?.immunizations?.length ?? 0) > 0,
      !!(profile?.demographics?.race) && !!(profile?.demographics?.language),
    ];
    return Math.round((dqSections.filter(Boolean).length / dqSections.length) * 100);
  })();

  const suspectCount = suspectsQ.data?.suspects?.length ?? 0;

  // AI Analysis summary — derived from encounters with cached_analysis
  const aiAnalysis = useMemo(() => {
    const encs: EncounterItem[] = encountersQ.data?.encounters || [];
    const analyzedEncs = encs.filter((e) => e.cached_analysis || e.analysis);
    if (analyzedEncs.length === 0) return null;
    const allDx: any[] = [];
    const allCodes = new Set<string>();
    for (const enc of analyzedEncs) {
      const a = enc.cached_analysis || enc.analysis;
      for (const dx of a?.diagnoses || []) {
        const code = dx.icd10_code || dx.code || "";
        if (code && !allCodes.has(code)) {
          allCodes.add(code);
          allDx.push(dx);
        }
      }
    }
    const hccDx = allDx.filter((d: any) => d.hcc_code || d.hcc || d.hcc_mapping?.hcc_code);
    // Get billing codes from year-filtered RAF breakdown (hcc_details has billed ICD codes for the selected year).
    // Fall back to all-time profile billing if breakdown data is not yet available.
    const yearBilledCodes = new Set<string>();
    const hccDetails: any[] = (rafBreakdownQ.data as any)?.hcc_details || [];
    for (const hcc of hccDetails) {
      for (const c of hcc.icd10_codes || []) {
        const code = (typeof c === "string" ? c : c.code || c.icd10_code || "").replace(".", "");
        if (code) yearBilledCodes.add(code);
      }
    }
    const billingCodes: Set<string> = yearBilledCodes.size > 0
      ? yearBilledCodes
      : new Set(
          ((profile?.billing as any)?.diagnoses || (profile?.billing as any)?.icd10_codes || [])
            .map((d: any) => (typeof d === "string" ? d : d.code || d.icd10_code || "").replace(".", ""))
        );
    const aiOnlyCodes = allDx.filter((d: any) => {
      const c = (d.icd10_code || d.code || "").replace(".", "");
      return c && !billingCodes.has(c);
    });
    return {
      totalDx: allDx.length,
      hccDx: hccDx.length,
      analyzedEncounters: analyzedEncs.length,
      totalEncounters: encs.length,
      diagnoses: allDx,
      aiOnlyCodes,
      aiOnlyCount: aiOnlyCodes.length,
    };
  }, [encountersQ.data, profile, rafBreakdownQ.data]);

  // Tab definitions
  const tabs = [
    { id: "overview", label: "Overview" },
    { id: "raf", label: "RAF Details" },
    { id: "models", label: "Model Comparison" },
    { id: "clinical", label: "Clinical Data" },
    { id: "encounters", label: "Encounters" },
    { id: "documents", label: "Documents & Reports", icon: FileText },
    {
      id: "suspects",
      label: "Review Queue",
      badge: suspectCount > 0 ? suspectCount : undefined,
    },
    { id: "audit", label: "Audit" },
    { id: "activity", label: "Activity" },
  ];

  // =========================================================================
  // RENDER
  // =========================================================================
  return (
    <div className="dot-grid mesh-pattern" style={{ minHeight: "100vh", background: C.bg }}>
      {/* ================================================================= */}
      {/* SECTION 1: PATIENT HEADER (sticky)                                */}
      {/* ================================================================= */}
      <header
        className="premium-card animate-fade-in"
        style={{
          position: "sticky",
          top: 0,
          zIndex: 30,
          background: C.white,
          borderBottom: `1px solid ${C.slate200}`,
          height: 80,
          borderRadius: 0,
        }}
      >
        <div
          style={{
            width: "100%",
            padding: "0 24px",
            height: 80,
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
          }}
        >
          {/* Left: back + avatar + patient name */}
          <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
            <Link
              href="/patients"
              className="hover-lift"
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                width: 36,
                height: 36,
                borderRadius: 8,
                border: `1px solid ${C.slate200}`,
                color: C.slate600,
                textDecoration: "none",
                flexShrink: 0,
                transition: "background 0.15s, transform 0.2s",
              }}
              onMouseEnter={(e) =>
                (e.currentTarget.style.background = C.slate100)
              }
              onMouseLeave={(e) =>
                (e.currentTarget.style.background = "transparent")
              }
            >
              <svg
                width="18"
                height="18"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M19 12H5M12 19l-7-7 7-7" />
              </svg>
            </Link>
            {/* Large avatar */}
            <div
              style={{
                width: 44,
                height: 44,
                borderRadius: 12,
                background: `linear-gradient(135deg, ${C.blue600}, ${C.emerald600})`,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                color: C.white,
                fontSize: 18,
                fontWeight: 800,
                letterSpacing: "-0.02em",
                flexShrink: 0,
                boxShadow: "0 2px 8px rgba(15, 118, 110, 0.25)",
              }}
            >
              {(patientName || "").trim().charAt(0).toUpperCase() || "\u2022"}
            </div>
            <div>
              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <h1
                  className="gradient-text"
                  style={{
                    margin: 0,
                    fontSize: 24,
                    fontWeight: 700,
                    color: C.slate800,
                    lineHeight: 1.2,
                  }}
                >
                  {patientName}
                </h1>
                <span
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    padding: "3px 10px",
                    borderRadius: 999,
                    fontSize: 11,
                    fontWeight: 600,
                    fontFamily: "monospace",
                    background: C.blue100,
                    color: C.blue600,
                  }}
                >
                  PID {pid}
                </span>
              </div>
            </div>
          </div>

          {/* Right: demographics + actions */}
          <div style={{ display: "flex", alignItems: "center", gap: 20 }}>
            {/* Demographics chips */}
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 16,
                fontSize: 13,
                color: C.slate500,
              }}
            >
              {age !== null && <span>{age} yrs</span>}
              {sex && (
                <span style={{ textTransform: "capitalize" }}>{sex}</span>
              )}
              {dob && <span>{formatDate(dob)}</span>}
            </div>

            {/* Divider */}
            <div
              style={{
                width: 1,
                height: 32,
                background: C.slate200,
              }}
            />

            {/* Action buttons */}
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <button
                onClick={() => batchMutation.mutate()}
                disabled={batchMutation.isPending || batchStatus === "running"}
                className="hover-lift"
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 8,
                  padding: "10px 18px",
                  borderRadius: 12,
                  border: "none",
                  background: C.blue600,
                  color: C.white,
                  fontSize: 13,
                  fontWeight: 600,
                  cursor:
                    batchMutation.isPending || batchStatus === "running"
                      ? "not-allowed"
                      : "pointer",
                  boxShadow: "0 4px 10px rgba(15, 118, 110, 0.2)",
                  opacity:
                    batchMutation.isPending || batchStatus === "running"
                      ? 0.6
                      : 1,
                  transition: "opacity 0.15s, transform 0.2s, box-shadow 0.2s",
                }}
              >
                {(batchMutation.isPending || batchStatus === "running") && (
                  <Spinner size={14} />
                )}
                {batchStatus === "running"
                  ? "Analyzing..."
                  : "Analyze All Encounters"}
              </button>
              <button
                onClick={() => calcRAFMutation.mutate()}
                disabled={calcRAFMutation.isPending}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 6,
                  padding: "8px 16px",
                  borderRadius: 8,
                  border: `1px solid ${C.slate200}`,
                  background: C.white,
                  color: C.slate700,
                  fontSize: 13,
                  fontWeight: 600,
                  cursor: calcRAFMutation.isPending ? "not-allowed" : "pointer",
                  opacity: calcRAFMutation.isPending ? 0.6 : 1,
                }}
              >
                {calcRAFMutation.isPending && <Spinner size={14} />}
                Calculate RAF
              </button>
              <button
                onClick={() => auditMutation.mutate(selectedYear)}
                disabled={auditMutation.isPending}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 6,
                  padding: "8px 16px",
                  borderRadius: 8,
                  border: `1px solid ${C.slate200}`,
                  background: C.white,
                  color: C.slate700,
                  fontSize: 13,
                  fontWeight: 600,
                  cursor: auditMutation.isPending ? "not-allowed" : "pointer",
                  opacity: auditMutation.isPending ? 0.6 : 1,
                }}
              >
                {auditMutation.isPending && <Spinner size={14} />}
                Generate Audit
              </button>
              <button
                onClick={() => window.print()}
                className="no-print"
                aria-label="Print patient record"
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 6,
                  padding: "8px 16px",
                  borderRadius: 8,
                  border: `1px solid ${C.slate200}`,
                  background: C.white,
                  color: C.slate700,
                  fontSize: 13,
                  fontWeight: 600,
                  cursor: "pointer",
                }}
              >
                <Printer size={14} /> Print
              </button>
            </div>
          </div>
        </div>
      </header>
      {/* Print-only patient header */}
      <div className="print-header" style={{ display: "none" }}>
        <div style={{ fontSize: 10, color: "#666", marginBottom: 4 }}>RAF Intelligence — Patient Record</div>
        <div style={{ fontSize: 18, fontWeight: 700 }}>{patientName}</div>
        <div style={{ fontSize: 12, marginTop: 4 }}>
          PID: {pid}
          {dob ? ` | DOB: ${formatDate(dob)}` : ""}
          {age !== null ? ` | Age: ${age}` : ""}
          {sex ? ` | Sex: ${sex}` : ""}
          {rafScore != null ? ` | RAF Score: ${Number(rafScore).toFixed(3)}` : ""}
          {hccCount > 0 ? ` | HCCs: ${hccCount}` : ""}
        </div>
        <div style={{ fontSize: 10, color: "#666", marginTop: 4 }}>
          Printed: {new Date().toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric" })}
        </div>
      </div>

      {/* ================================================================= */}
      {/* SECTION 2: RISK SUMMARY STRIP                                     */}
      {/* ================================================================= */}
      <div
        className="animate-slide-up stagger-1"
        style={{
          background: C.white,
          borderBottom: `1px solid ${C.slate200}`,
          height: 80,
          display: "flex",
          alignItems: "center",
          padding: "0 24px",
        }}
      >
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(5, 1fr)",
            width: "100%",
            gap: 0,
          }}
        >
          {/* 1. RAF Score — with AI comparison */}
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 12,
              padding: "0 16px",
            }}
          >
            <RiskGauge score={rafScore} size={56} label="" />
            <div>
              <div
                style={{
                  fontSize: 10,
                  fontWeight: 600,
                  textTransform: "uppercase",
                  letterSpacing: "0.05em",
                  color: C.slate400,
                  marginBottom: 2,
                }}
              >
                RAF Score ({selectedYear})
              </div>
              <div
                className="tabular-nums"
                style={{
                  fontSize: 24,
                  fontWeight: 800,
                  color: rafScore != null ? rafScoreColor(rafScore) : C.slate400,
                  fontFamily: "monospace",
                  lineHeight: 1,
                  textShadow: rafScore != null ? `0 0 20px ${rafScoreColor(rafScore)}33` : "none",
                }}
              >
                {rafScore != null ? Number(rafScore).toFixed(3) : "\u2014"}
              </div>
              {aiAnalysis && aiAnalysis.aiOnlyCount > 0 && (
                <div style={{ fontSize: 10, color: C.emerald600, fontWeight: 600, marginTop: 2 }}>
                  +{aiAnalysis.aiOnlyCount} AI-identified codes
                </div>
              )}
            </div>
          </div>

          {/* 2. Model Segment */}
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              justifyContent: "center",
              alignItems: "center",
              borderLeft: `1px solid ${C.slate100}`,
              padding: "0 16px",
            }}
          >
            <div
              style={{
                fontSize: 10,
                fontWeight: 600,
                textTransform: "uppercase",
                letterSpacing: "0.05em",
                color: C.slate400,
                marginBottom: 6,
              }}
            >
              Model Segment
            </div>
            <span
              style={{
                display: "inline-flex",
                alignItems: "center",
                padding: "4px 14px",
                borderRadius: 6,
                fontSize: 14,
                fontWeight: 700,
                background: C.slate100,
                color: C.slate700,
                fontFamily: "monospace",
              }}
            >
              {modelSegment}
            </span>
          </div>

          {/* 3. HCC Count */}
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              justifyContent: "center",
              alignItems: "center",
              borderLeft: `1px solid ${C.slate100}`,
              padding: "0 16px",
            }}
          >
            <div
              style={{
                fontSize: 10,
                fontWeight: 600,
                textTransform: "uppercase",
                letterSpacing: "0.05em",
                color: C.slate400,
                marginBottom: 6,
              }}
            >
              HCC Count
            </div>
            <div style={{ display: "flex", alignItems: "baseline", gap: 4 }}>
              <span
                style={{
                  fontSize: 24,
                  fontWeight: 700,
                  color: C.slate900,
                  lineHeight: 1,
                }}
              >
                {hccCount}
              </span>
              <span style={{ fontSize: 12, color: C.slate400, fontWeight: 500 }}>
                conditions
              </span>
            </div>
          </div>

          {/* 4. MEAT Compliance */}
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              justifyContent: "center",
              alignItems: "center",
              borderLeft: `1px solid ${C.slate100}`,
              padding: "0 16px",
            }}
          >
            <div
              style={{
                fontSize: 10,
                fontWeight: 600,
                textTransform: "uppercase",
                letterSpacing: "0.05em",
                color: C.slate400,
                marginBottom: 6,
              }}
            >
              MEAT Compliance
            </div>
            <div
              style={{
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                gap: 4,
              }}
            >
              <span
                style={{
                  fontSize: 16,
                  fontWeight: 700,
                  color: C.slate900,
                  lineHeight: 1,
                }}
              >
                {meatFilled}/{meatTotal || 0}
              </span>
              <div style={{ width: 80 }}>
                <ProgressBar
                  value={meatTotal > 0 ? (meatFilled / meatTotal) * 100 : 0}
                  showPercent={false}
                  height={4}
                  color={C.emerald500}
                />
              </div>
            </div>
          </div>

          {/* 5. Data Quality */}
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              justifyContent: "center",
              alignItems: "center",
              borderLeft: `1px solid ${C.slate100}`,
              padding: "0 16px",
            }}
          >
            <div
              style={{
                fontSize: 10,
                fontWeight: 600,
                textTransform: "uppercase",
                letterSpacing: "0.05em",
                color: C.slate400,
                marginBottom: 6,
              }}
            >
              Data Quality
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <span
                style={{
                  width: 8,
                  height: 8,
                  borderRadius: "50%",
                  background:
                    dataQuality === null
                      ? C.gray400
                      : dataQuality >= 80
                        ? C.emerald500
                        : dataQuality >= 50
                          ? C.amber500
                          : C.red500,
                }}
              />
              <span
                style={{
                  fontSize: 20,
                  fontWeight: 700,
                  color: C.slate900,
                  lineHeight: 1,
                }}
              >
                {dataQuality !== null ? `${dataQuality}%` : "\u2014"}
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* ================================================================= */}
      {/* SECTION 3: TAB NAVIGATION                                         */}
      {/* ================================================================= */}
      <div
        style={{
          background: C.white,
          borderBottom: `1px solid ${C.slate200}`,
          padding: "0 24px",
        }}
      >
        <div style={{ display: "flex", gap: 0, alignItems: "center" }}>
          {/* Year Selector */}
          <div style={{ display: "flex", alignItems: "center", gap: 4, marginRight: 16, paddingRight: 16, borderRight: `1px solid ${C.slate200}` }}>
            <span style={{ fontSize: 10, fontWeight: 600, color: C.slate400, textTransform: "uppercase", letterSpacing: "0.05em", marginRight: 4 }}>Year</span>
            {Array.from({length: 3}, (_, i) => new Date().getFullYear() - i).map((yr) => (
              <button
                key={yr}
                onClick={() => setSelectedYear(yr)}
                style={{
                  padding: "6px 12px",
                  fontSize: 12,
                  fontWeight: selectedYear === yr ? 700 : 500,
                  color: selectedYear === yr ? C.white : C.slate500,
                  background: selectedYear === yr ? C.blue600 : "transparent",
                  border: selectedYear === yr ? "none" : `1px solid ${C.slate200}`,
                  borderRadius: 6,
                  cursor: "pointer",
                  transition: "all 0.15s",
                }}
              >
                {yr}
              </button>
            ))}
          </div>
          {tabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              style={{
                padding: "14px 20px",
                fontSize: 13,
                fontWeight: activeTab === tab.id ? 600 : 500,
                color: activeTab === tab.id ? C.blue600 : C.slate500,
                background: "transparent",
                border: "none",
                borderBottom:
                  activeTab === tab.id
                    ? `2px solid ${C.blue600}`
                    : "2px solid transparent",
                cursor: "pointer",
                display: "flex",
                alignItems: "center",
                gap: 6,
                transition: "color 0.15s, border-color 0.15s",
              }}
            >
              {tab.label}
              {tab.badge !== undefined && (
                <span
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    justifyContent: "center",
                    minWidth: 20,
                    height: 20,
                    padding: "0 6px",
                    borderRadius: 999,
                    fontSize: 10,
                    fontWeight: 700,
                    background: C.amber500,
                    color: C.white,
                  }}
                >
                  {tab.badge}
                </span>
              )}
            </button>
          ))}
        </div>
      </div>

      {/* ================================================================= */}
      {/* TAB CONTENT                                                        */}
      {/* ================================================================= */}
      <div className="animate-slide-up stagger-2" style={{ padding: 24 }}>
        {activeTab === "overview" && (
          <OverviewTab
            pid={pid}
            patient={patient}
            profile={profile}
            profileLoading={profileQ.isLoading}
            breakdown={breakdown}
            breakdownLoading={rafBreakdownQ.isLoading}
            problems={problemsQ.data}
            problemsLoading={problemsQ.isLoading}
            encounters={encountersQ.data}
            encountersLoading={encountersQ.isLoading}
            recapture={recaptureQ.data}
            recaptureLoading={recaptureQ.isLoading}
            dob={dob}
            sex={sex}
            rafScore={rafScore}
            analyzeMutation={analyzeMutation}
            setActiveTab={setActiveTab}
            aiAnalysis={aiAnalysis}
            selectedYear={selectedYear}
            meds={medsQ.data}
            labSuspects={labSuspectsQ.data}
            vitalsSuspects={vitalsSuspectsQ.data}
          />
        )}
        {activeTab === "raf" && (
          <RAFTab
            breakdown={breakdown}
            breakdownLoading={rafBreakdownQ.isLoading}
            history={history}
            historyLoading={rafHistoryQ.isLoading}
            recapture={recaptureQ.data}
            recaptureLoading={recaptureQ.isLoading}
            rafScore={rafScore}
            suspects={suspectsQ.data}
            lastCalcResult={lastCalcResult}
            selectedYear={selectedYear}
          />
        )}
        {activeTab === "models" && (
          <div style={{ maxWidth: 1100 }}>
            <ModelComparison pid={pid} year={selectedYear} />
          </div>
        )}
        {activeTab === "clinical" && (
          <ClinicalTab
            meds={medsQ.data}
            medsLoading={medsQ.isLoading}
            vitalsSuspects={vitalsSuspectsQ.data}
            vitalsLoading={vitalsSuspectsQ.isLoading}
            labSuspects={labSuspectsQ.data}
            labsLoading={labSuspectsQ.isLoading}
            allergies={allergiesQ.data}
            allergiesLoading={allergiesQ.isLoading}
            immunizations={immunizationsQ.data}
            immunizationsLoading={immunizationsQ.isLoading}
            familyHistory={familyHistoryQ.data}
            familyHistoryLoading={familyHistoryQ.isLoading}
            sdoh={sdohQ.data}
            sdohLoading={sdohQ.isLoading}
            medGaps={medGapsQ.data}
            medGapsLoading={medGapsQ.isLoading}
            patient={patient}
            profile={profile}
            profileLoading={profileQ.isLoading}
            breakdown={breakdown}
            breakdownLoading={rafBreakdownQ.isLoading}
          />
        )}
        {activeTab === "encounters" && (
          <EncountersTab
            encounters={encountersQ.data}
            encountersLoading={encountersQ.isLoading}
            analyzeMutation={analyzeMutation}
            lastAnalysisResult={lastAnalysisResult}
            selectedYear={selectedYear}
          />
        )}
        {activeTab === "suspects" && (
          <SuspectsTab
            suspects={suspectsQ.data}
            suspectsLoading={suspectsQ.isLoading}
            acceptMutation={acceptMutation}
            dismissMutation={dismissMutation}
          />
        )}
        {activeTab === "documents" && (
          <DocumentsTab
            pid={pid}
            documents={documentsQ.data}
            documentsLoading={documentsQ.isLoading}
            rafScore={rafScore}
            selectedYear={selectedYear}
            patientName={patient ? `${patient.fname || patient.first_name || ""} ${patient.lname || patient.last_name || ""}`.trim() : ""}
          />
        )}
        {activeTab === "audit" && (
          <AuditTab
            audits={auditsQ.data}
            auditsLoading={auditsQ.isLoading}
            auditMutation={auditMutation}
            selectedYear={selectedYear}
          />
        )}
        {activeTab === "activity" && (
          <ActivityTab
            encounters={encountersQ.data}
            encountersLoading={encountersQ.isLoading}
            suspects={suspectsQ.data}
            suspectsLoading={suspectsQ.isLoading}
            rafHistory={rafHistoryQ.data}
            rafHistoryLoading={rafHistoryQ.isLoading}
            audits={auditsQ.data}
            auditsLoading={auditsQ.isLoading}
          />
        )}
      </div>
    </div>
  );
}

// ===========================================================================
// OVERVIEW TAB
// ===========================================================================
function OverviewTab({
  pid,
  patient,
  profile,
  profileLoading,
  breakdown,
  breakdownLoading,
  problems,
  problemsLoading,
  encounters,
  encountersLoading,
  recapture,
  recaptureLoading,
  dob,
  sex,
  rafScore,
  analyzeMutation,
  setActiveTab,
  aiAnalysis,
  selectedYear,
  meds,
  labSuspects,
  vitalsSuspects,
}: {
  pid: string;
  patient: Patient | undefined;
  profile: PatientProfile | undefined;
  profileLoading: boolean;
  breakdown: ExtendedRafBreakdown | undefined;
  breakdownLoading: boolean;
  problems: ProblemListResponse | ProblemItem[] | undefined;
  problemsLoading: boolean;
  encounters: PatientEncountersResponse | undefined;
  encountersLoading: boolean;
  recapture: RecaptureGapsResponse | RecaptureGapItem[] | undefined;
  recaptureLoading: boolean;
  dob: string;
  sex: string;
  rafScore: number | null;
  analyzeMutation: { mutate: (encId: number) => void; isPending: boolean; variables?: number };
  setActiveTab: (tab: string) => void;
  aiAnalysis: { totalDx: number; hccDx: number; analyzedEncounters: number; totalEncounters: number; diagnoses: any[]; aiOnlyCodes: any[]; aiOnlyCount: number } | null;
  selectedYear: number;
  meds?: any;
  labSuspects?: any;
  vitalsSuspects?: any;
}) {
  const encountersWithNotes = (encounters?.encounters || []).filter(
    (e: EncounterItem) => !!e.notes || !!e.has_notes
  );
  const hasEncountersWithNotes = encountersWithNotes.length > 0;
  const hccCount = breakdown?.hcc_count ?? breakdown?.hcc_details?.length ?? 0;
  const isDemoOnly = hccCount === 0;
  const patientAge = dob ? calculateAge(dob) : null;
  const patientSex = sex === "Female" ? "Female" : sex === "Male" ? "Male" : sex;
  const problemItems: ProblemItem[] = Array.isArray(problems) ? problems : (problems as ProblemListResponse | undefined)?.problems ?? [];
  const recaptureItems: RecaptureGapItem[] = (() => {
    if (Array.isArray(recapture)) return recapture;
    const r = recapture as any;
    const raw = r?.gaps ?? r?.recapture_gaps ?? [];
    return raw.map((g: any) => ({
      ...g,
      description: g.description || g.title || "",
      icd10_code: g.icd10_code || (g.diagnosis?.includes(":") ? g.diagnosis.split(":").pop()?.trim() : g.diagnosis) || "",
    }));
  })();

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
      {/* Analysis Status Banner */}
      {isDemoOnly && (
        <div className="animate-slide-up stagger-1" style={{
          background: "#FFFBEB",
          border: "1px solid #FDE68A",
          borderRadius: 12,
          padding: "16px 20px",
          display: "flex",
          alignItems: "center",
          gap: 16,
        }}>
          <div style={{
            width: 44, height: 44, borderRadius: 10,
            background: "#FEF3C7", display: "flex", alignItems: "center", justifyContent: "center",
            flexShrink: 0,
          }}>
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#D97706" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
              <line x1="12" y1="9" x2="12" y2="13" /><line x1="12" y1="17" x2="12.01" y2="17" />
            </svg>
          </div>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 14, fontWeight: 700, color: "#92400E", marginBottom: 2 }}>
              Demographics-Only Score
            </div>
            <div style={{ fontSize: 13, color: "#A16207", lineHeight: 1.5 }}>
              This RAF score ({rafScore != null ? Number(rafScore).toFixed(3) : "—"}) is calculated from demographics only
              ({patientAge ? `${patientAge}-year-old` : ""} {patientSex || ""}).
              {hasEncountersWithNotes
                ? " Run analysis on clinical encounters to identify HCC conditions and calculate the full risk-adjusted score."
                : " No encounters with clinical notes found — the pipeline needs clinical notes to extract diagnoses."}
            </div>
          </div>
          {hasEncountersWithNotes && (
            <button
              onClick={() => setActiveTab("encounters")}
              style={{
                padding: "10px 18px", borderRadius: 8, border: "none",
                background: "#D97706", color: "#fff", fontSize: 13, fontWeight: 700,
                cursor: "pointer", whiteSpace: "nowrap", flexShrink: 0,
              }}
            >
              Go to Encounters →
            </button>
          )}
        </div>
      )}

      {!isDemoOnly && (
        <div className="animate-slide-up stagger-1" style={{
          background: "#ECFDF5",
          border: "1px solid #A7F3D0",
          borderRadius: 12,
          padding: "14px 20px",
          display: "flex",
          alignItems: "center",
          gap: 12,
        }}>
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#059669" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" /><polyline points="22 4 12 14.01 9 11.01" />
          </svg>
          <div style={{ fontSize: 13, color: "#065F46", fontWeight: 500 }}>
            <strong>{hccCount} HCC condition{hccCount !== 1 ? "s" : ""}</strong> identified from clinical analysis.
            RAF score includes demographic ({Number(breakdown?.demographic_score || 0).toFixed(3)}) + disease ({Number(breakdown?.disease_score || 0).toFixed(3)})
            {(breakdown?.interaction_score ?? 0) > 0 ? ` + interactions (${Number(breakdown?.interaction_score).toFixed(3)})` : ""}.
          </div>
        </div>
      )}

      {/* AI Analysis Summary — shows when encounters have been analyzed */}
      {aiAnalysis && aiAnalysis.totalDx > 0 && (
        <div className="animate-fade-in" style={{
          background: "linear-gradient(135deg, #EFF6FF, #F0FDF4)",
          borderRadius: 12,
          border: `1px solid ${C.blue100}`,
          padding: "16px 20px",
          marginBottom: 16,
        }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ fontSize: 18 }}>🤖</span>
              <span style={{ fontSize: 14, fontWeight: 700, color: C.slate800 }}>
                AI Analysis Summary
              </span>
              <span style={{
                padding: "2px 8px", borderRadius: 999, fontSize: 10, fontWeight: 700,
                background: C.emerald50, color: C.emerald600, border: `1px solid ${C.emerald100}`,
              }}>
                {aiAnalysis.analyzedEncounters}/{aiAnalysis.totalEncounters} encounters analyzed
              </span>
            </div>
            <span style={{ fontSize: 11, color: C.slate400 }}>
              Powered by AI Engine
            </span>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12 }}>
            {/* Total AI Diagnoses */}
            <div style={{
              background: C.white, borderRadius: 8, padding: "12px 16px",
              border: `1px solid ${C.slate200}`,
            }}>
              <div style={{ fontSize: 10, fontWeight: 600, color: C.slate400, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 4 }}>
                AI-Extracted Diagnoses
              </div>
              <div style={{ fontSize: 22, fontWeight: 800, color: C.blue600, fontFamily: "monospace" }}>
                {aiAnalysis.totalDx}
              </div>
              <div style={{ fontSize: 11, color: C.slate500, marginTop: 2 }}>
                {aiAnalysis.hccDx} with HCC mapping
              </div>
            </div>

            {/* New codes not in billing */}
            <div style={{
              background: C.white, borderRadius: 8, padding: "12px 16px",
              border: `1px solid ${aiAnalysis.aiOnlyCount > 0 ? C.emerald100 : C.slate200}`,
            }}>
              <div style={{ fontSize: 10, fontWeight: 600, color: C.slate400, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 4 }}>
                New Codes (Not in Billing)
              </div>
              <div style={{ fontSize: 22, fontWeight: 800, color: aiAnalysis.aiOnlyCount > 0 ? C.emerald600 : C.slate400, fontFamily: "monospace" }}>
                {aiAnalysis.aiOnlyCount}
              </div>
              <div style={{ fontSize: 11, color: C.slate500, marginTop: 2 }}>
                {aiAnalysis.aiOnlyCount > 0 ? "Potential revenue opportunity" : "All codes already billed"}
              </div>
            </div>

            {/* Code source breakdown */}
            <div style={{
              background: C.white, borderRadius: 8, padding: "12px 16px",
              border: `1px solid ${C.slate200}`,
            }}>
              <div style={{ fontSize: 10, fontWeight: 600, color: C.slate400, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 4 }}>
                Data Sources
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 4, marginTop: 4 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11 }}>
                  <span style={{ width: 8, height: 8, borderRadius: 999, background: C.slate500, flexShrink: 0 }} />
                  <span style={{ color: C.slate600, fontWeight: 500 }}>Billing (OpenEMR)</span>
                  <span style={{ marginLeft: "auto", fontWeight: 700, color: C.slate700, fontFamily: "monospace" }}>
                    {hccCount}
                  </span>
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11 }}>
                  <span style={{ width: 8, height: 8, borderRadius: 999, background: C.emerald500, flexShrink: 0 }} />
                  <span style={{ color: C.slate600, fontWeight: 500 }}>AI Analysis</span>
                  <span style={{ marginLeft: "auto", fontWeight: 700, color: C.emerald600, fontFamily: "monospace" }}>
                    +{aiAnalysis.aiOnlyCount}
                  </span>
                </div>
              </div>
            </div>
          </div>

          {/* List new AI-only codes */}
          {aiAnalysis.aiOnlyCount > 0 && (
            <div style={{ marginTop: 12 }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: C.slate500, marginBottom: 6, textTransform: "uppercase", letterSpacing: "0.05em" }}>
                AI-Identified Codes Not Yet in Billing
              </div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                {aiAnalysis.aiOnlyCodes.map((dx: any, i: number) => (
                  <span key={dx.code || dx.icd10_code || i} style={{
                    display: "inline-flex", alignItems: "center", gap: 6,
                    padding: "4px 10px", borderRadius: 6, fontSize: 11, fontWeight: 500,
                    background: C.white, border: `1px solid ${C.emerald100}`,
                    color: C.slate700,
                  }}>
                    <span style={{ fontFamily: "monospace", fontWeight: 700, color: C.emerald600 }}>
                      {dx.icd10_code || dx.code}
                    </span>
                    {dx.description || dx.condition || dx.diagnosis || ""}
                    {(dx.hcc_code || dx.hcc || dx.hcc_mapping?.hcc_code) && (
                      <span style={{
                        padding: "1px 6px", borderRadius: 4, fontSize: 9, fontWeight: 700,
                        background: C.blue50, color: C.blue600, border: `1px solid ${C.blue100}`,
                      }}>
                        {dx.hcc_code || dx.hcc || dx.hcc_mapping?.hcc_code}
                      </span>
                    )}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Main Grid */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 0.66fr",
          gap: 24,
        }}
      >
      {/* ============ LEFT COLUMN (60%) ============ */}
      <div className="animate-slide-up stagger-2" style={{ display: "flex", flexDirection: "column", gap: 24 }}>
        {/* Active Problems */}
        <Card noPadding className="hover-lift">
          <SectionHeader
            title="Active Problems"
            icon={
              <svg
                width="18"
                height="18"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2" />
                <rect x="8" y="2" width="8" height="4" rx="1" ry="1" />
              </svg>
            }
            count={
              problemItems.length || undefined
            }
          />
          <div style={{ padding: "0 0 0 0" }}>
            {problemsLoading ? (
              <SectionLoader />
            ) : !problemItems.length ? (
              <div style={{ padding: "32px 20px", textAlign: "center" }}>
                <svg
                  width="24"
                  height="24"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke={C.slate400}
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  style={{ marginBottom: 8 }}
                >
                  <path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2" />
                  <rect x="8" y="2" width="8" height="4" rx="1" ry="1" />
                </svg>
                <div style={{ fontSize: 14, fontWeight: 600, color: C.slate700, marginBottom: 4 }}>
                  No active problems
                </div>
                {hasEncountersWithNotes ? (
                  <>
                    <div style={{ fontSize: 13, color: C.slate500, marginBottom: 12 }}>
                      Run analysis on encounters to identify conditions
                    </div>
                    <button
                      onClick={() => setActiveTab("encounters")}
                      style={{
                        display: "inline-flex",
                        alignItems: "center",
                        gap: 6,
                        padding: "8px 16px",
                        borderRadius: 8,
                        border: `1px solid ${C.blue600}`,
                        background: C.blue50,
                        color: C.blue600,
                        fontSize: 13,
                        fontWeight: 600,
                        cursor: "pointer",
                      }}
                    >
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M22 12h-4l-3 9L9 3l-3 9H2" />
                      </svg>
                      Go to Encounters
                    </button>
                  </>
                ) : (
                  <div style={{ fontSize: 13, color: C.slate500 }}>
                    No encounters with clinical notes found
                  </div>
                )}
              </div>
            ) : (
              <div>
                {/* Table header */}
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "1fr 140px 120px",
                    padding: "8px 20px",
                    background: C.slate100,
                    borderTop: `1px solid ${C.slate200}`,
                    borderBottom: `1px solid ${C.slate200}`,
                  }}
                >
                  <span
                    style={{
                      fontSize: 11,
                      fontWeight: 600,
                      textTransform: "uppercase",
                      letterSpacing: "0.05em",
                      color: C.slate400,
                    }}
                  >
                    Condition
                  </span>
                  <span
                    style={{
                      fontSize: 11,
                      fontWeight: 600,
                      textTransform: "uppercase",
                      letterSpacing: "0.05em",
                      color: C.slate400,
                    }}
                  >
                    ICD-10
                  </span>
                  <span
                    style={{
                      fontSize: 11,
                      fontWeight: 600,
                      textTransform: "uppercase",
                      letterSpacing: "0.05em",
                      color: C.slate400,
                    }}
                  >
                    Onset
                  </span>
                </div>
                {/* Rows */}
                {problemItems
                  .slice(0, 15)
                  .map((p: ProblemItem, i: number) => (
                    <div
                      key={p.icd10_code || p.diagnosis_code || p.title || i}
                      style={{
                        display: "grid",
                        gridTemplateColumns: "1fr 140px 120px",
                        padding: "10px 20px",
                        borderBottom: `1px solid ${C.slate100}`,
                        background: i % 2 === 1 ? C.slate100 + "60" : "transparent",
                        transition: "background 0.15s",
                      }}
                      onMouseEnter={(e) =>
                        (e.currentTarget.style.background = C.slate100)
                      }
                      onMouseLeave={(e) =>
                        (e.currentTarget.style.background = i % 2 === 1 ? C.slate100 + "60" : "transparent")
                      }
                    >
                      <span
                        style={{
                          fontSize: 13,
                          fontWeight: 500,
                          color: C.slate800,
                        }}
                      >
                        {p.title || p.condition || p.diagnosis || "\u2014"}
                      </span>
                      <span>
                        <span
                          style={{
                            display: "inline-block",
                            padding: "2px 8px",
                            borderRadius: 4,
                            fontSize: 11,
                            fontWeight: 600,
                            fontFamily: "monospace",
                            background: C.slate100,
                            color: C.slate700,
                            border: `1px solid ${C.slate200}`,
                          }}
                        >
                          {p.icd10_code || p.diagnosis_code || "\u2014"}
                        </span>
                      </span>
                      <span style={{ fontSize: 12, color: C.slate500 }}>
                        {formatDate(p.begdate || p.onset_date || p.date)}
                      </span>
                    </div>
                  ))}
              </div>
            )}
          </div>
        </Card>

        {/* Recent Encounters */}
        <Card noPadding className="hover-lift">
          <SectionHeader
            title="Recent Encounters"
            icon={
              <svg
                width="18"
                height="18"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M22 12h-4l-3 9L9 3l-3 9H2" />
              </svg>
            }
            count={encounters?.encounters?.length || undefined}
          />
          <div>
            {encountersLoading ? (
              <SectionLoader />
            ) : !encounters?.encounters?.length ? (
              <EmptyState
                title="No encounters found"
                icon={
                  <svg
                    width="24"
                    height="24"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                  >
                    <path d="M22 12h-4l-3 9L9 3l-3 9H2" />
                  </svg>
                }
              />
            ) : (
              <div>
                {encounters.encounters.slice(0, 5).map((enc: EncounterItem) => {
                  const hasNotes = !!enc.notes || !!enc.has_notes;
                  return (
                    <div
                      key={enc.encounter_id}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "space-between",
                        padding: "12px 20px",
                        borderTop: `1px solid ${C.slate100}`,
                        transition: "background 0.1s",
                      }}
                      onMouseEnter={(e) =>
                        (e.currentTarget.style.background = C.slate100)
                      }
                      onMouseLeave={(e) =>
                        (e.currentTarget.style.background = "transparent")
                      }
                    >
                      <div>
                        <div
                          style={{
                            fontSize: 13,
                            fontWeight: 500,
                            color: C.slate800,
                          }}
                        >
                          {enc.reason || "Office Visit"}
                        </div>
                        <div
                          style={{
                            fontSize: 12,
                            color: C.slate400,
                            marginTop: 2,
                          }}
                        >
                          {enc.provider_fname || enc.provider_lname
                            ? `${enc.provider_fname || ""} ${enc.provider_lname || ""}`.trim()
                            : "Provider not listed"}
                          {" \u00B7 "}
                          {formatDate(enc.date)}
                        </div>
                      </div>
                      <div
                        style={{
                          display: "flex",
                          alignItems: "center",
                          gap: 8,
                        }}
                      >
                        {!hasNotes && (
                          <span
                            style={{
                              fontSize: 11,
                              color: C.slate400,
                              fontStyle: "italic",
                            }}
                          >
                            No notes
                          </span>
                        )}
                        <button
                          onClick={() =>
                            analyzeMutation.mutate(enc.encounter_id)
                          }
                          disabled={analyzeMutation.isPending || !hasNotes}
                          style={{
                            display: "inline-flex",
                            alignItems: "center",
                            gap: 4,
                            padding: "5px 12px",
                            borderRadius: 6,
                            border: `1px solid ${C.slate200}`,
                            background: C.white,
                            color:
                              !hasNotes ? C.slate400 : C.slate600,
                            fontSize: 12,
                            fontWeight: 500,
                            cursor:
                              analyzeMutation.isPending || !hasNotes
                                ? "not-allowed"
                                : "pointer",
                            opacity:
                              analyzeMutation.isPending || !hasNotes
                                ? 0.5
                                : 1,
                          }}
                        >
                          {analyzeMutation.isPending &&
                          analyzeMutation.variables === enc.encounter_id ? (
                            <Spinner size={12} />
                          ) : null}
                          Analyze
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </Card>

        {/* Care Gaps (Recapture) */}
        <Card noPadding className="hover-lift">
          <SectionHeader
            title="Care Gaps"
            icon={
              <svg
                width="18"
                height="18"
                viewBox="0 0 24 24"
                fill="none"
                stroke={C.amber600}
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0zM12 9v4M12 17h.01" />
              </svg>
            }
          />
          <div>
            {recaptureLoading ? (
              <SectionLoader />
            ) : !recaptureItems.length ? (
              <EmptyState
                title="No recapture gaps"
                description={`All conditions appear to be documented for ${selectedYear}`}
              />
            ) : (
              <div>
                {recaptureItems.map(
                  (gap: RecaptureGapItem, i: number) => (
                    <div
                      key={gap.hcc_code || gap.icd10_code || gap.hcc || `gap-${i}`}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        padding: "12px 20px",
                        borderTop: `1px solid ${C.slate100}`,
                        borderLeft: `3px solid ${C.amber500}`,
                      }}
                    >
                      <div style={{ flex: 1 }}>
                        <div
                          style={{
                            fontSize: 13,
                            fontWeight: 500,
                            color: C.slate800,
                          }}
                        >
                          {gap.condition ||
                            gap.hcc_label ||
                            gap.description ||
                            "\u2014"}
                        </div>
                        <div
                          style={{
                            display: "flex",
                            alignItems: "center",
                            gap: 8,
                            marginTop: 4,
                          }}
                        >
                          <span
                            style={{
                              display: "inline-block",
                              padding: "2px 8px",
                              borderRadius: 4,
                              fontSize: 11,
                              fontWeight: 600,
                              fontFamily: "monospace",
                              background: C.slate100,
                              color: C.slate700,
                              border: `1px solid ${C.slate200}`,
                            }}
                          >
                            {gap.icd10_code ||
                              gap.hcc_code ||
                              gap.hcc ||
                              "\u2014"}
                          </span>
                          <span style={{ fontSize: 11, color: C.slate400 }}>
                            {formatDate(gap.onset_date || gap.begdate)}
                          </span>
                        </div>
                      </div>
                    </div>
                  )
                )}
              </div>
            )}
          </div>
        </Card>
      </div>

      {/* ============ RIGHT COLUMN (40%) ============ */}
      <div className="animate-slide-up stagger-3" style={{ display: "flex", flexDirection: "column", gap: 24 }}>
        {/* Demographics */}
        <Card className="hover-lift">
          <SectionHeader
            title="Demographics"
            icon={
              <svg
                width="18"
                height="18"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
                <circle cx="12" cy="7" r="4" />
              </svg>
            }
          />
          {profileLoading ? (
            <SectionLoader />
          ) : (
            <div>
              <DataRow label="Date of Birth" value={formatDate(dob)} />
              <DataRow
                label="Sex"
                value={
                  sex
                    ? sex.charAt(0).toUpperCase() + sex.slice(1)
                    : "\u2014"
                }
              />
              <DataRow
                label="Race"
                value={
                  (profile?.demographics?.race as string) || patient?.race || "\u2014"
                }
              />
              <DataRow
                label="Ethnicity"
                value={
                  (profile?.demographics?.ethnicity as string) ||
                  patient?.ethnicity ||
                  "\u2014"
                }
              />
              <DataRow
                label="Language"
                value={
                  (profile?.demographics?.language as string) ||
                  patient?.language ||
                  "\u2014"
                }
              />
              <DataRow
                label="Address"
                value={
                  [
                    patient?.street,
                    patient?.city,
                    patient?.state,
                    patient?.postal_code,
                  ]
                    .filter(Boolean)
                    .join(", ") ||
                  (profile?.demographics?.address as string) ||
                  "\u2014"
                }
              />
              <DataRow
                label="Phone"
                value={
                  patient?.phone_home ||
                  patient?.phone_cell ||
                  (profile?.demographics?.phone as string) ||
                  "\u2014"
                }
              />
            </div>
          )}
        </Card>

        {/* Insurance */}
        <Card className="hover-lift">
          <SectionHeader
            title="Insurance"
            icon={
              <svg
                width="18"
                height="18"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
              </svg>
            }
          />
          {profileLoading ? (
            <SectionLoader />
          ) : (
            <div>
              <DataRow
                label="Plan Type"
                value={(profile?.enrollment as Record<string, string> | undefined)?.plan_type || "\u2014"}
              />
              <DataRow
                label="Dual Status"
                value={(profile?.enrollment as Record<string, string> | undefined)?.dual_status ?? "\u2014"}
              />
              <DataRow
                label="OREC"
                value={(profile?.enrollment as Record<string, string> | undefined)?.orec ?? "\u2014"}
              />
              <DataRow
                label="Enrolled Since"
                value={formatDate((profile?.enrollment as Record<string, string> | undefined)?.start_date)}
              />
            </div>
          )}
        </Card>

        {/* Data Completeness */}
        <Card className="hover-lift">
          <SectionHeader
            title="Data Completeness"
            icon={
              <svg
                width="18"
                height="18"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
              </svg>
            }
          />
          {profileLoading ? (
            <SectionLoader />
          ) : (
            <DataCompletenessChecklist
              profile={profile}
              encounters={encounters}
              problems={problems}
              meds={meds}
              labSuspects={labSuspects}
              vitalsSuspects={vitalsSuspects}
              selectedYear={selectedYear}
            />
          )}
        </Card>
      </div>
    </div>
    </div>
  );
}

function DataCompletenessChecklist({ profile, encounters, problems, meds, labSuspects, vitalsSuspects, selectedYear }: {
  profile: PatientProfile | undefined;
  encounters?: any;
  problems?: any;
  meds?: any;
  labSuspects?: any;
  vitalsSuspects?: any;
  selectedYear: number;
}) {
  // Build completeness from year-filtered query data instead of all-time profile
  const encList = encounters?.encounters ?? (Array.isArray(encounters) ? encounters : []);
  const probList = Array.isArray(problems) ? problems : (problems?.problems ?? []);
  const medList = Array.isArray(meds) ? meds : (meds?.medications ?? []);
  const hasEncounters = encList.length > 0;
  const hasNotes = encList.some((e: any) => e.notes || e.has_notes);
  const hasProblems = probList.length > 0;
  const hasMeds = medList.length > 0;
  const hasVitals = Array.isArray(vitalsSuspects) ? vitalsSuspects.length > 0 : !!(vitalsSuspects?.suspects?.length);
  const hasLabs = Array.isArray(labSuspects) ? labSuspects.length > 0 : !!(labSuspects?.suspects?.length);
  // These are not year-specific — use profile
  const hasInsurance = !!(profile?.enrollment) && (profile?.enrollment as any)?.source !== "default";
  const hasImmunizations = Array.isArray(profile?.immunizations) && profile.immunizations.length > 0;
  const hasBilling = !!((profile?.billing as any)?.icd10_codes?.length);
  const hasDemographics = !!(profile?.demographics?.race) && !!(profile?.demographics?.language);

  const sections = [
    { label: "Encounters", present: hasEncounters },
    { label: "Clinical Notes", present: hasNotes },
    { label: "Problems", present: hasProblems },
    { label: "Medications", present: hasMeds },
    { label: "Vitals", present: hasVitals },
    { label: "Labs", present: hasLabs },
    { label: "Billing", present: hasBilling },
    { label: "Insurance", present: hasInsurance },
    { label: "Immunizations", present: hasImmunizations },
    { label: "Demographics", present: hasDemographics },
  ];

  const pct = sections.length > 0
    ? Math.round((sections.filter((s) => s.present).length / sections.length) * 100)
    : 0;

  return (
    <div>
      <div style={{ marginBottom: 16 }}>
        <ProgressBar
          value={pct}
          label="Overall"
          color={pct >= 80 ? C.emerald500 : pct >= 50 ? C.amber500 : C.red500}
          height={6}
        />
      </div>
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 8,
        }}
      >
        {sections.map((s) => (
          <div
            key={s.label}
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              fontSize: 13,
            }}
          >
            <span
              style={{
                color: C.slate600,
                textTransform: "capitalize",
              }}
            >
              {s.label}
            </span>
            {s.present ? (
              <span
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 4,
                  color: C.emerald600,
                  fontSize: 12,
                  fontWeight: 600,
                }}
              >
                <svg
                  width="14"
                  height="14"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="3"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <polyline points="20 6 9 17 4 12" />
                </svg>
                Available
              </span>
            ) : (
              <span
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 4,
                  color: C.red500,
                  fontSize: 12,
                  fontWeight: 500,
                }}
              >
                <svg
                  width="14"
                  height="14"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="3"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <line x1="18" y1="6" x2="6" y2="18" />
                  <line x1="6" y1="6" x2="18" y2="18" />
                </svg>
                Missing
              </span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

// ===========================================================================
// RAF DETAILS TAB
// ===========================================================================
function RAFTab({
  breakdown,
  breakdownLoading,
  history,
  historyLoading,
  recapture,
  recaptureLoading,
  rafScore,
  suspects,
  lastCalcResult,
  selectedYear,
}: {
  breakdown: ExtendedRafBreakdown | undefined;
  breakdownLoading: boolean;
  history: RafHistoryResponse | undefined;
  historyLoading: boolean;
  recapture: RecaptureGapsResponse | RecaptureGapItem[] | undefined;
  recaptureLoading: boolean;
  rafScore: number | null;
  suspects: PatientSuspectsResponse | undefined;
  lastCalcResult?: any;
  selectedYear: number;
}) {
  const recaptureItems: RecaptureGapItem[] = (() => {
    if (Array.isArray(recapture)) return recapture;
    const r = recapture as any;
    const raw = r?.gaps ?? r?.recapture_gaps ?? [];
    return raw.map((g: any) => ({
      ...g,
      description: g.description || g.title || "",
      icd10_code: g.icd10_code || (g.diagnosis?.includes(":") ? g.diagnosis.split(":").pop()?.trim() : g.diagnosis) || "",
    }));
  })();
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
      {/* RAF Score Calculator Table */}
      <RAFScoreCalculatorTable breakdown={breakdown} breakdownLoading={breakdownLoading} lastCalcResult={lastCalcResult} selectedYear={selectedYear} />

      {/* Patient HCC Crosswalk */}
      <PatientCrosswalk breakdown={breakdown} rafScore={rafScore} suspects={suspects} />

      {/* Score History (CSS bars) */}
      <Card className="animate-slide-up stagger-3 hover-lift">
        <SectionHeader title="Score History" />
        {historyLoading ? (
          <SectionLoader />
        ) : (
          <RAFHistoryBars history={history} />
        )}
      </Card>
      {/* Recapture Gaps */}
      <Card noPadding className="animate-slide-up stagger-4 hover-lift">
        <SectionHeader title="Recapture Gaps" />
        {recaptureLoading ? (
          <SectionLoader />
        ) : !recaptureItems.length ? (
          <EmptyState title="No recapture gaps identified" />
        ) : (
          <div>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "1fr 100px 100px 100px",
                padding: "8px 20px",
                background: C.slate100,
                borderTop: `1px solid ${C.slate200}`,
                borderBottom: `1px solid ${C.slate200}`,
              }}
            >
              {["Condition", "HCC", "Last Year", "Coefficient"].map((h) => (
                <span
                  key={h}
                  style={{
                    fontSize: 11,
                    fontWeight: 600,
                    textTransform: "uppercase",
                    letterSpacing: "0.05em",
                    color: C.slate400,
                  }}
                >
                  {h}
                </span>
              ))}
            </div>
            {recaptureItems.map(
              (gap: RecaptureGapItem, i: number) => (
                <div
                  key={gap.hcc_code || gap.icd10_code || gap.hcc || `gap-${i}`}
                  style={{
                    display: "grid",
                    gridTemplateColumns: "1fr 100px 100px 100px",
                    padding: "10px 20px",
                    borderBottom: `1px solid ${C.slate100}`,
                    background: i % 2 === 1 ? C.slate100 + "60" : "transparent",
                    transition: "background 0.15s",
                  }}
                  onMouseEnter={(e) =>
                    (e.currentTarget.style.background = C.slate100)
                  }
                  onMouseLeave={(e) =>
                    (e.currentTarget.style.background = i % 2 === 1 ? C.slate100 + "60" : "transparent")
                  }
                >
                  <span
                    style={{
                      fontSize: 13,
                      fontWeight: 500,
                      color: C.slate800,
                    }}
                  >
                    {gap.condition ||
                      gap.hcc_label ||
                      gap.description ||
                      "\u2014"}
                  </span>
                  <span>
                    <span
                      style={{
                        display: "inline-block",
                        padding: "2px 8px",
                        borderRadius: 4,
                        fontSize: 11,
                        fontWeight: 600,
                        fontFamily: "monospace",
                        background: C.slate100,
                        color: C.slate700,
                        border: `1px solid ${C.slate200}`,
                      }}
                    >
                      {gap.hcc_code || gap.hcc || "\u2014"}
                    </span>
                  </span>
                  <span style={{ fontSize: 13, color: C.slate500 }}>
                    {gap.prior_year || gap.last_captured_year || "\u2014"}
                  </span>
                  <span
                    style={{
                      fontSize: 13,
                      fontFamily: "monospace",
                      fontWeight: 600,
                      color: C.blue600,
                    }}
                  >
                    {gap.coefficient != null
                      ? `+${Number(gap.coefficient).toFixed(3)}`
                      : "\u2014"}
                  </span>
                </div>
              )
            )}
          </div>
        )}
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------------------
// ICD-10 Description Lookup
// ---------------------------------------------------------------------------
const ICD10_DESCRIPTIONS: Record<string, string> = {
  "I50.9": "Heart failure, unspecified",
  "I50.20": "Unspecified systolic heart failure",
  "I48.91": "Unspecified atrial fibrillation",
  "E11.9": "Type 2 diabetes mellitus without complications",
  "E11.65": "Type 2 DM with hyperglycemia",
  "N18.3": "Chronic kidney disease, stage 3",
  "N18.4": "Chronic kidney disease, stage 4",
  "J44.1": "COPD with acute exacerbation",
  "J44.9": "COPD, unspecified",
  "F33.0": "Major depressive disorder, recurrent, mild",
  "F33.1": "Major depressive disorder, recurrent, moderate",
  "M06.9": "Rheumatoid arthritis, unspecified",
  "E66.01": "Morbid obesity due to excess calories",
  "G20": "Parkinson's disease",
  "F03.90": "Unspecified dementia",
  "I73.9": "Peripheral vascular disease",
  "K74.60": "Unspecified cirrhosis of liver",
  "I63.9": "Cerebral infarction, unspecified",
  "G40.909": "Epilepsy, unspecified",
  "B20": "HIV disease",
  "I48.0": "Paroxysmal atrial fibrillation",
};

// ---------------------------------------------------------------------------
// Disease Interaction Rules (CMS-HCC V28)
// ---------------------------------------------------------------------------
const DISEASE_INTERACTIONS: Array<{ name: string; groups: number[][]; coefficient: number }> = [
  { name: "DIABETES_HF", groups: [[37, 38], [85, 86]], coefficient: 0.112 },
  { name: "HF_CHR_LUNG", groups: [[85, 86], [112, 113]], coefficient: 0.078 },
  { name: "CHF_RENAL", groups: [[85, 86], [136, 137, 138, 141]], coefficient: 0.065 },
  { name: "DIABETES_CHR_LUNG", groups: [[37, 38], [112, 113]], coefficient: 0.022 },
  { name: "HF_RENAL_DIABETES", groups: [[85, 86], [136, 137, 138, 141], [37, 38]], coefficient: 0.034 },
];

const MA_PAYMENT_PER_RAF = 11015.04;

// ---------------------------------------------------------------------------
// RAF Score Calculator Table Component
// ---------------------------------------------------------------------------
function RAFScoreCalculatorTable({ breakdown, breakdownLoading, lastCalcResult, selectedYear }: { breakdown: ExtendedRafBreakdown | undefined; breakdownLoading: boolean; lastCalcResult?: any; selectedYear: number }) {
  if (breakdownLoading) {
    return (
      <div className="animate-slide-up stagger-1">
        <SectionLoader label="Loading RAF Score Analysis..." />
      </div>
    );
  }

  if (!breakdown) {
    return (
      <div className="animate-slide-up stagger-1">
        <Card><EmptyState title="No RAF breakdown available" /></Card>
      </div>
    );
  }

  const hccDetails: HCCDetail[] = breakdown.hcc_details || [];
  const patientHccCodes = hccDetails.map((h) => Number(h.hcc_code || h.code));

  // Compute triggered interactions
  const triggeredInteractions = DISEASE_INTERACTIONS.filter((inter) =>
    inter.groups.every((group) => group.some((hcc) => patientHccCodes.includes(hcc)))
  );

  const demographicScore = breakdown.demographic_score ?? breakdown.demographic_base ?? 0;
  const diseaseScore = hccDetails.reduce((sum: number, h: HCCDetail) => sum + Number(h.coefficient || h.hcc_coefficient || 0), 0);
  const interactionScore = triggeredInteractions.reduce((sum, i) => sum + i.coefficient, 0);
  const componentSum = demographicScore + diseaseScore + interactionScore;
  // Use the authoritative score from the backend (final_raf) so it matches
  // the header and patient list. Fall back to component sum if unavailable.
  const grandTotal = breakdown.final_raf ?? breakdown.raf_score ?? breakdown.total_raf ?? componentSum;
  // grandTotal already IS the payment-adjusted score (raw × (1-MACI) / norm)

  const fmtScore = (v: number) => v.toFixed(3);
  const fmtPay = (v: number) => `$${Math.round(v).toLocaleString("en-US")}`;

  return (
    <div className="animate-slide-up stagger-1" style={{ display: "flex", flexDirection: "column", gap: 16 }}>

      {/* ── RAF Score + Payment ── */}
      <div style={{
        background: `linear-gradient(135deg, ${C.blue50} 0%, ${C.white} 100%)`,
        borderRadius: 16, border: `1px solid ${C.blue100}`,
        padding: "20px 24px", display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 16,
      }}>
        <div>
          <div style={{ fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.08em", color: C.slate400, marginBottom: 4 }}>Total RAF Score</div>
          <div style={{ fontSize: 36, fontWeight: 800, fontFamily: "monospace", color: C.blue600, lineHeight: 1 }}>{fmtScore(grandTotal)}</div>
        </div>
        <div style={{ textAlign: "right" }}>
          <div style={{ fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.08em", color: C.slate400, marginBottom: 4 }}>Est. MA Payment</div>
          <div style={{ fontSize: 28, fontWeight: 800, fontFamily: "monospace", color: C.emerald600, lineHeight: 1 }}>{fmtPay(grandTotal * MA_PAYMENT_PER_RAF)}</div>
          <div style={{ fontSize: 12, color: C.slate400, marginTop: 6 }}>
            {["V28", breakdown.model_segment || "CNA", breakdown.measurement_year || selectedYear].map(t => (
              <span key={t} style={{ display: "inline-block", padding: "2px 8px", borderRadius: 4, fontSize: 10, fontWeight: 600, background: C.blue50, color: C.blue600, border: `1px solid ${C.blue100}`, marginLeft: 4 }}>{t}</span>
            ))}
          </div>
        </div>
      </div>

      {/* ── Breakdown Card ── */}
      <Card noPadding>
        {/* Demographic base */}
        <div style={{ padding: "14px 20px", display: "flex", justifyContent: "space-between", alignItems: "center", borderBottom: `1px solid ${C.slate100}` }}>
          <div>
            <div style={{ fontSize: 13, fontWeight: 600, color: C.slate700 }}>Demographic Base</div>
            <div style={{ fontSize: 11, color: C.slate400, marginTop: 1 }}>Age/sex coefficient</div>
          </div>
          <div style={{ textAlign: "right" }}>
            <span style={{ fontSize: 16, fontFamily: "monospace", fontWeight: 700, color: C.slate800 }}>{fmtScore(demographicScore)}</span>
            <span style={{ fontSize: 12, fontFamily: "monospace", color: C.emerald600, marginLeft: 12 }}>{fmtPay(demographicScore * MA_PAYMENT_PER_RAF)}</span>
          </div>
        </div>

        {/* Diagnosis section */}
        {hccDetails.length > 0 && (
          <div style={{ padding: "8px 20px 4px", fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.08em", color: C.slate400 }}>
            Diagnosis ({hccDetails.length})
          </div>
        )}
        {hccDetails.map((hcc: HCCDetail, i: number) => {
          const code = hcc.hcc_code;
          const icdCodes: string[] = (hcc.icd10_codes || []).map((c: any) => typeof c === "string" ? c : c.code || "");
          const primaryIcd = icdCodes[0] || "";
          const icdDesc = primaryIcd ? (ICD10_DESCRIPTIONS[primaryIcd] || hcc.hcc_label || "") : (hcc.hcc_label || "");
          const coeff = Number(hcc.coefficient || 0);
          const meatColor = hcc.meat_status === "complete" ? C.emerald500 : hcc.meat_status === "partial" ? C.amber500 : C.slate300;
          return (
            <div key={hcc.hcc_code || hcc.code || i} style={{
              display: "flex", alignItems: "center", gap: 12, padding: "10px 20px",
              borderBottom: `1px solid ${C.slate100}`, borderLeft: `3px solid ${meatColor}`,
              marginLeft: 0, transition: "background 0.15s",
            }}
            onMouseEnter={e => (e.currentTarget.style.background = C.slate100 + "60")}
            onMouseLeave={e => (e.currentTarget.style.background = "transparent")}
            >
              {/* ICD code pill */}
              <span style={{ minWidth: 64, padding: "3px 8px", borderRadius: 6, fontSize: 12, fontWeight: 700, fontFamily: "monospace", background: C.blue50, color: C.blue600, textAlign: "center", border: `1px solid ${C.blue100}` }}>
                {primaryIcd || `HCC${code}`}
              </span>
              {/* Description */}
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 13, fontWeight: 500, color: C.slate700, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{icdDesc}</div>
                <div style={{ fontSize: 11, color: C.slate400, marginTop: 1 }}>
                  HCC {code}
                  {icdCodes.length > 1 && <span style={{ marginLeft: 6, opacity: 0.7 }}>+{icdCodes.length - 1} codes</span>}
                </div>
              </div>
              {/* Score + Payment */}
              <span style={{ fontSize: 15, fontFamily: "monospace", fontWeight: 700, color: C.slate800, whiteSpace: "nowrap" }}>{fmtScore(coeff)}</span>
              <span style={{ fontSize: 13, fontFamily: "monospace", fontWeight: 600, color: C.emerald600, minWidth: 70, textAlign: "right", whiteSpace: "nowrap" }}>{fmtPay(coeff * MA_PAYMENT_PER_RAF)}</span>
            </div>
          );
        })}

        {/* Interactions — always show so users know it was calculated */}
        <div style={{ padding: "8px 20px 4px", fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.08em", color: C.slate400 }}>
          Disease Interactions ({triggeredInteractions.length})
        </div>
        {triggeredInteractions.length > 0 ? (
          triggeredInteractions.map(inter => (
            <div key={inter.name} style={{
              display: "flex", alignItems: "center", gap: 12, padding: "10px 20px",
              borderBottom: `1px solid ${C.slate100}`,
            }}>
              <span style={{ minWidth: 64, padding: "3px 8px", borderRadius: 6, fontSize: 10, fontWeight: 700, fontFamily: "monospace", background: C.amber50, color: C.amber600, textAlign: "center", border: `1px solid ${C.amber100}` }}>
                {inter.name.replace(/_/g, " ")}
              </span>
              <div style={{ flex: 1 }} />
              <span style={{ fontSize: 15, fontFamily: "monospace", fontWeight: 700, color: C.slate800 }}>{fmtScore(inter.coefficient)}</span>
              <span style={{ fontSize: 13, fontFamily: "monospace", fontWeight: 600, color: C.emerald600, minWidth: 70, textAlign: "right" }}>{fmtPay(inter.coefficient * MA_PAYMENT_PER_RAF)}</span>
            </div>
          ))
        ) : (
          <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "10px 20px", borderBottom: `1px solid ${C.slate100}` }}>
            <span style={{ fontSize: 13, color: C.slate400 }}>No qualifying HCC combinations — interaction score is 0</span>
            <div style={{ flex: 1 }} />
            <span style={{ fontSize: 15, fontFamily: "monospace", fontWeight: 700, color: C.slate400 }}>0.000</span>
            <span style={{ fontSize: 13, fontFamily: "monospace", fontWeight: 600, color: C.slate400, minWidth: 70, textAlign: "right" }}>$0</span>
          </div>
        )}

        {/* Footer note */}
        <div style={{ padding: "8px 20px", fontSize: 10, color: C.slate400 }}>
          * Based on CMS {new Date().getFullYear()} rate of ${MA_PAYMENT_PER_RAF.toLocaleString("en-US")}/RAF point
        </div>
      </Card>

      {/* ── Calculation Details (collapsible) ── */}
      <CalcDetails breakdown={breakdown} componentSum={componentSum} grandTotal={grandTotal} lastCalcResult={lastCalcResult} />
    </div>
  );
}

function LLMInputPanel({ llmInput }: { llmInput: any }) {
  const [open, setOpen] = useState(false);
  const pill = (text: string, bg: string, fg: string, border: string) => (
    <span style={{ padding: "3px 8px", borderRadius: 5, fontSize: 11, fontFamily: "monospace", fontWeight: 600, background: bg, color: fg, border: `1px solid ${border}` }}>{text}</span>
  );
  return (
    <div style={{ borderRadius: 8, border: `1px solid ${C.purple100}`, overflow: "hidden", marginBottom: 12 }}>
      <button
        onClick={() => setOpen(!open)}
        style={{
          width: "100%", padding: "10px 14px", background: `linear-gradient(135deg, ${C.purple50}, ${C.blue50})`,
          border: "none", cursor: "pointer", display: "flex",
          justifyContent: "space-between", alignItems: "center",
          fontSize: 12, fontWeight: 600, color: C.purple600,
        }}
      >
        <span>📋 Data Sent to AI Model</span>
        <span style={{ fontSize: 14, transform: open ? "rotate(180deg)" : "rotate(0deg)", transition: "transform 0.2s" }}>▼</span>
      </button>
      {open && (
        <div style={{ padding: "14px 16px", fontSize: 12, background: C.white }}>
          {/* Model & Config */}
          <div style={{ display: "grid", gridTemplateColumns: "130px 1fr", gap: "5px 12px", marginBottom: 12 }}>
            <span style={{ color: C.slate400, fontWeight: 600 }}>Patient Age</span>
            <span style={{ color: C.slate700 }}>{llmInput.patient_age ?? "N/A"}</span>
            <span style={{ color: C.slate400, fontWeight: 600 }}>Patient Sex</span>
            <span style={{ color: C.slate700 }}>{llmInput.patient_sex ?? "N/A"}</span>
            <span style={{ color: C.slate400, fontWeight: 600 }}>Note Length</span>
            <span style={{ color: C.slate700 }}>{llmInput.clinical_note_chars?.toLocaleString()} characters</span>
            <span style={{ color: C.slate400, fontWeight: 600 }}>Temperature</span>
            <span style={{ fontFamily: "monospace", color: C.slate700 }}>{llmInput.temperature}</span>
          </div>

          {/* Medications */}
          {llmInput.medications?.length > 0 && (
            <div style={{ marginBottom: 10 }}>
              <div style={{ color: C.slate500, fontWeight: 600, fontSize: 11, marginBottom: 4, textTransform: "uppercase", letterSpacing: "0.04em" }}>Medications ({llmInput.medications.length})</div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                {llmInput.medications.map((m: string, i: number) => <React.Fragment key={m || i}>{pill(m, C.amber50, C.amber700, C.amber100)}</React.Fragment>)}
              </div>
            </div>
          )}

          {/* Existing HCCs */}
          {llmInput.existing_hccs?.length > 0 && (
            <div style={{ marginBottom: 10 }}>
              <div style={{ color: C.slate500, fontWeight: 600, fontSize: 11, marginBottom: 4, textTransform: "uppercase", letterSpacing: "0.04em" }}>Existing HCCs ({llmInput.existing_hccs.length})</div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                {llmInput.existing_hccs.map((h: string, i: number) => <React.Fragment key={h || i}>{pill(h, C.emerald50, C.emerald600, C.emerald100)}</React.Fragment>)}
              </div>
            </div>
          )}

          {/* Problem List */}
          {llmInput.problem_list?.length > 0 && (
            <div style={{ marginBottom: 10 }}>
              <div style={{ color: C.slate500, fontWeight: 600, fontSize: 11, marginBottom: 4, textTransform: "uppercase", letterSpacing: "0.04em" }}>Problem List ({llmInput.problem_list.length})</div>
              <div style={{ fontSize: 11, color: C.slate600, lineHeight: 1.6 }}>
                {llmInput.problem_list.map((p: any, i: number) => (
                  <div key={p.diagnosis || p.title || i}>• {p.title} <span style={{ fontFamily: "monospace", color: C.blue600 }}>({p.diagnosis || "no code"})</span></div>
                ))}
              </div>
            </div>
          )}

          {/* Recapture Gaps */}
          {llmInput.recapture_gaps?.length > 0 && (
            <div style={{ marginBottom: 10 }}>
              <div style={{ color: C.slate500, fontWeight: 600, fontSize: 11, marginBottom: 4, textTransform: "uppercase", letterSpacing: "0.04em" }}>Recapture Gaps ({llmInput.recapture_gaps.length})</div>
              <div style={{ fontSize: 11, color: C.slate600, lineHeight: 1.6 }}>
                {llmInput.recapture_gaps.map((g: any, i: number) => (
                  <div key={g.diagnosis || g.title || i}>• {g.title} <span style={{ fontFamily: "monospace", color: C.orange500 }}>({g.diagnosis})</span></div>
                ))}
              </div>
            </div>
          )}

          {/* Vitals */}
          {llmInput.latest_vitals && Object.keys(llmInput.latest_vitals).length > 0 && (
            <div style={{ marginBottom: 10 }}>
              <div style={{ color: C.slate500, fontWeight: 600, fontSize: 11, marginBottom: 4, textTransform: "uppercase", letterSpacing: "0.04em" }}>Vitals Sent</div>
              <div style={{ display: "grid", gridTemplateColumns: "100px 1fr", gap: "2px 8px", fontSize: 11, fontFamily: "monospace", color: C.slate600 }}>
                {Object.entries(llmInput.latest_vitals).map(([k, v]: [string, any]) => (
                  <React.Fragment key={k}>
                    <span style={{ color: C.slate400 }}>{k}</span>
                    <span>{String(v)}</span>
                  </React.Fragment>
                ))}
              </div>
            </div>
          )}

          {/* Med Diagnoses */}
          {llmInput.med_diagnoses?.length > 0 && (
            <div style={{ marginBottom: 10 }}>
              <div style={{ color: C.slate500, fontWeight: 600, fontSize: 11, marginBottom: 4, textTransform: "uppercase", letterSpacing: "0.04em" }}>Medication Indications ({llmInput.med_diagnoses.length})</div>
              <div style={{ fontSize: 11, color: C.slate600, lineHeight: 1.6 }}>
                {llmInput.med_diagnoses.map((m: any, i: number) => (
                  <div key={m.drug || i}>• <strong>{m.drug}</strong>: {m.note}</div>
                ))}
              </div>
            </div>
          )}

          {/* Clinical Note Preview */}
          {llmInput.clinical_note_preview && (
            <div style={{ marginBottom: 10 }}>
              <div style={{ color: C.slate500, fontWeight: 600, fontSize: 11, marginBottom: 4, textTransform: "uppercase", letterSpacing: "0.04em" }}>Clinical Note Preview</div>
              <pre style={{ fontSize: 11, color: C.slate600, background: C.slate100, padding: 10, borderRadius: 6, border: `1px solid ${C.slate200}`, whiteSpace: "pre-wrap", wordBreak: "break-word", maxHeight: 200, overflow: "auto", margin: 0 }}>{llmInput.clinical_note_preview}</pre>
            </div>
          )}

          {/* Extracted ICD codes (reconstructed view) */}
          {llmInput.extracted_icd_codes?.length > 0 && (
            <div style={{ marginBottom: 10 }}>
              <div style={{ color: C.slate500, fontWeight: 600, fontSize: 11, marginBottom: 4, textTransform: "uppercase", letterSpacing: "0.04em" }}>ICD-10 Codes Extracted ({llmInput.extracted_icd_codes.length})</div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                {llmInput.extracted_icd_codes.map((c: string, i: number) => <React.Fragment key={c || i}>{pill(c, C.blue50, C.blue600, C.blue100)}</React.Fragment>)}
              </div>
            </div>
          )}

          {/* Tool Calls Summary */}
          {llmInput.tool_calls_summary && (
            <div style={{ marginBottom: 10 }}>
              <div style={{ color: C.slate500, fontWeight: 600, fontSize: 11, marginBottom: 4, textTransform: "uppercase", letterSpacing: "0.04em" }}>AI Processing Summary</div>
              <div style={{ display: "grid", gridTemplateColumns: "160px 1fr", gap: "4px 12px", fontSize: 11, color: C.slate600 }}>
                <span style={{ color: C.slate400 }}>Total Tool Calls</span>
                <span style={{ fontWeight: 600 }}>{llmInput.tool_calls_summary.total}</span>
                <span style={{ color: C.slate400 }}>Conversation Turns</span>
                <span style={{ fontWeight: 600 }}>{llmInput.tool_calls_summary.turns}</span>
                <span style={{ color: C.slate400 }}>Processing Time</span>
                <span style={{ fontWeight: 600 }}>{llmInput.tool_calls_summary.total_time?.toFixed(1)}s</span>
                <span style={{ color: C.slate400 }}>ICD-10 Validations</span>
                <span style={{ fontWeight: 600 }}>{llmInput.tool_calls_summary.icd_validated}</span>
                <span style={{ color: C.slate400 }}>HCC Lookups</span>
                <span style={{ fontWeight: 600 }}>{llmInput.tool_calls_summary.hcc_lookups}</span>
                <span style={{ color: C.slate400 }}>Medication Checks</span>
                <span style={{ fontWeight: 600 }}>{llmInput.tool_calls_summary.med_checks}</span>
              </div>
            </div>
          )}

          {/* Reconstructed notice */}
          {llmInput._reconstructed && (
            <div style={{ fontSize: 10, color: C.slate400, fontStyle: "italic", marginTop: 6 }}>
              Partial data — click Analyze again to capture full input details (demographics, vitals, problem list, note preview).
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function CalcDetails({ breakdown, componentSum, grandTotal, lastCalcResult }: { breakdown: ExtendedRafBreakdown; componentSum: number; grandTotal: number; lastCalcResult?: any }) {
  const [open, setOpen] = useState(false);
  // Prefer lastCalcResult (from Calculate RAF click), fall back to breakdown (which now also has engine_input/output)
  const data = lastCalcResult || breakdown as any;
  const engineInput = data.engine_input || (breakdown as any)?.engine_input;
  const engineOutput = data.engine_output || (breakdown as any)?.engine_output;
  const hasEngineData = !!engineInput;

  const hccContribs: any[] = data.hcc_contributions || data.hcc_details || [];

  const stepHeader = (num: number, label: string, color: string) => (
    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
      <span style={{ display: "inline-block", width: 22, height: 22, borderRadius: "50%", background: color, color: C.white, textAlign: "center", lineHeight: "22px", fontSize: 11, fontWeight: 700, flexShrink: 0 }}>{num}</span>
      <span style={{ fontSize: 12, fontWeight: 700, color, textTransform: "uppercase", letterSpacing: "0.05em" }}>{label}</span>
    </div>
  );

  const pill = (text: string, bg: string, fg: string, border: string) => (
    <span style={{ padding: "3px 8px", borderRadius: 5, fontSize: 11, fontFamily: "monospace", fontWeight: 600, background: bg, color: fg, border: `1px solid ${border}` }}>{text}</span>
  );

  return (
    <div style={{ borderRadius: 12, border: `1px solid ${C.slate200}`, overflow: "hidden" }}>
      <button
        onClick={() => setOpen(!open)}
        style={{
          width: "100%", padding: "12px 20px", background: C.slate100,
          border: "none", cursor: "pointer", display: "flex",
          justifyContent: "space-between", alignItems: "center",
          fontSize: 12, fontWeight: 600, color: C.slate600,
        }}
      >
        <span>Calculation Pipeline {hasEngineData ? "(last run)" : ""}</span>
        <span style={{ fontSize: 16, transform: open ? "rotate(180deg)" : "rotate(0deg)", transition: "transform 0.2s" }}>{"\u25BC"}</span>
      </button>
      {open && (
        <div style={{ padding: "20px", fontSize: 12, background: C.white }}>

          {!hasEngineData && (
            <div style={{ padding: "10px 14px", borderRadius: 8, background: C.amber50, border: `1px solid ${C.amber100}`, fontSize: 11, color: C.amber600, marginBottom: 16 }}>
              Click <strong>Calculate RAF</strong> to see the exact data sent to and received from the calculation engine.
            </div>
          )}

          {hasEngineData && (
            <>
              {/* STEP 1: Exact Engine Input */}
              {stepHeader(1, "Exact Data Sent to Calculation Engine", C.blue600)}
              <div style={{ marginLeft: 30, marginBottom: 20, padding: "14px 16px", borderRadius: 8, background: C.slate100, border: `1px solid ${C.slate200}` }}>
                <div style={{ display: "grid", gridTemplateColumns: "130px 1fr", gap: "6px 12px", fontSize: 12 }}>
                  <span style={{ color: C.slate400, fontWeight: 600 }}>Age</span>
                  <span style={{ color: C.slate700, fontWeight: 600 }}>{engineInput.age}</span>
                  <span style={{ color: C.slate400, fontWeight: 600 }}>Sex</span>
                  <span style={{ color: C.slate700, fontWeight: 600 }}>{engineInput.sex}</span>
                  <span style={{ color: C.slate400, fontWeight: 600 }}>Model Segment</span>
                  <span style={{ color: C.slate700, fontWeight: 600 }}>{engineInput.model_segment} ({engineInput.prefix_override})</span>
                  <span style={{ color: C.slate400, fontWeight: 600 }}>MACI Factor</span>
                  <span style={{ fontFamily: "monospace", color: C.slate700 }}>{engineInput.maci}</span>
                  <span style={{ color: C.slate400, fontWeight: 600 }}>Norm Factor</span>
                  <span style={{ fontFamily: "monospace", color: C.slate700 }}>{engineInput.norm_factor}</span>
                </div>
                <div style={{ marginTop: 10, borderTop: `1px solid ${C.slate200}`, paddingTop: 10 }}>
                  <div style={{ color: C.slate400, fontWeight: 600, marginBottom: 6 }}>ICD-10 Codes Sent ({engineInput.icd_codes?.length || 0})</div>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                    {(engineInput.icd_codes || []).map((c: string, i: number) => <React.Fragment key={c || i}>{pill(c, C.blue50, C.blue600, C.blue100)}</React.Fragment>)}
                  </div>
                  <div style={{ fontSize: 10, color: C.slate400, marginTop: 6 }}>
                    Collected from: OpenEMR billing codes + AI encounter analysis + document analysis + manual entries
                  </div>
                </div>
              </div>

              {/* STEP 2: Exact Engine Output */}
              {stepHeader(2, "Exact Data Received from Engine", C.emerald600)}
              <div style={{ marginLeft: 30, marginBottom: 20, padding: "14px 16px", borderRadius: 8, background: C.emerald50, border: `1px solid ${C.emerald100}` }}>
                <div style={{ display: "grid", gridTemplateColumns: "130px 1fr", gap: "6px 12px", fontSize: 12 }}>
                  <span style={{ color: C.slate400, fontWeight: 600 }}>Raw Score</span>
                  <span style={{ fontFamily: "monospace", fontWeight: 700, color: C.slate700 }}>{engineOutput.risk_score_raw}</span>
                  <span style={{ color: C.slate400, fontWeight: 600 }}>Payment Score</span>
                  <span style={{ fontFamily: "monospace", fontWeight: 700, color: C.blue600 }}>{engineOutput.risk_score_payment?.toFixed(3)}</span>
                  <span style={{ color: C.slate400, fontWeight: 600 }}>Demographics</span>
                  <span style={{ fontFamily: "monospace", color: C.slate700 }}>{engineOutput.risk_score_demographics}</span>
                </div>
                <div style={{ marginTop: 10, borderTop: `1px solid ${C.emerald100}`, paddingTop: 10 }}>
                  <div style={{ color: C.slate400, fontWeight: 600, marginBottom: 6 }}>HCCs Mapped ({engineOutput.hcc_list?.length || 0})</div>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginBottom: 8 }}>
                    {(engineOutput.hcc_list || []).map((h: string, i: number) => <React.Fragment key={h || i}>{pill(`HCC ${h}`, C.emerald50, C.emerald600, C.emerald100)}</React.Fragment>)}
                  </div>
                  {(engineOutput.hcc_details || []).map((h: any, i: number) => (
                    <div key={h.hcc || `hcc-detail-${i}`} style={{ display: "flex", alignItems: "center", gap: 8, padding: "4px 0", fontSize: 11, borderBottom: `1px solid ${C.emerald100}` }}>
                      <span style={{ fontFamily: "monospace", fontWeight: 700, color: C.emerald600, minWidth: 55 }}>HCC {h.hcc}</span>
                      <span style={{ flex: 1, color: C.slate600 }}>{h.label}</span>
                      <span style={{ fontFamily: "monospace", fontWeight: 600, color: C.slate700 }}>{h.coefficient?.toFixed(3)}</span>
                    </div>
                  ))}
                </div>
                {engineOutput.all_coefficients && Object.keys(engineOutput.all_coefficients).length > 0 && (
                  <div style={{ marginTop: 10, borderTop: `1px solid ${C.emerald100}`, paddingTop: 10 }}>
                    <div style={{ color: C.slate400, fontWeight: 600, marginBottom: 6 }}>All Coefficients</div>
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 80px", gap: "2px 8px", fontSize: 11, fontFamily: "monospace" }}>
                      {Object.entries(engineOutput?.all_coefficients || {}).sort((a: any, b: any) => b[1] - a[1]).map(([k, v]: [string, any]) => (
                        <React.Fragment key={k}>
                          <span style={{ color: C.slate600 }}>{k}</span>
                          <span style={{ textAlign: "right", fontWeight: 600, color: C.slate700 }}>{v.toFixed(3)}</span>
                        </React.Fragment>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </>
          )}

          {/* Always show ICD → HCC mapping from breakdown */}
          {!hasEngineData && (
            <>
              {stepHeader(1, `ICD-10 to HCC Mapping (${hccContribs.length} HCCs)`, C.emerald600)}
              <div style={{ marginLeft: 30, marginBottom: 16, borderRadius: 8, border: `1px solid ${C.slate200}`, overflow: "hidden" }}>
                {hccContribs.map((h: any, i: number) => {
                  const hccCode = h.hcc_code || h.code;
                  const icds: string[] = (h.icd10_codes || []).map((c: any) => typeof c === "string" ? c : c.code || "");
                  return (
                    <div key={h.hcc_code || h.code || i} style={{ display: "flex", alignItems: "center", gap: 10, padding: "6px 12px", borderBottom: i < hccContribs.length - 1 ? `1px solid ${C.slate100}` : "none", fontSize: 11 }}>
                      <span style={{ fontFamily: "monospace", color: C.emerald600, fontWeight: 700, minWidth: 55 }}>HCC {hccCode}</span>
                      <span style={{ color: C.slate400 }}>{"\u2190"}</span>
                      <div style={{ display: "flex", gap: 3, flexWrap: "wrap" }}>
                        {icds.length > 0 ? icds.map(c => (
                          <span key={c} style={{ padding: "1px 5px", borderRadius: 3, fontFamily: "monospace", fontSize: 10, background: C.blue50, color: C.blue600 }}>{c}</span>
                        )) : <span style={{ color: C.slate400 }}>-</span>}
                      </div>
                      <span style={{ marginLeft: "auto", fontFamily: "monospace", fontWeight: 600, color: C.slate700 }}>{(h.coefficient || 0).toFixed(3)}</span>
                    </div>
                  );
                })}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}

function PatientCrosswalk({ breakdown, rafScore, suspects }: { breakdown: ExtendedRafBreakdown | undefined; rafScore: number | null; suspects: PatientSuspectsResponse | undefined }) {
  const [extraCodes, setExtraCodes] = useState("");
  const [results, setResults] = useState<CrosswalkResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [hasSearched, setHasSearched] = useState(false);

  const currentRaf = rafScore ?? (breakdown?.demographic_score ?? 0) + (breakdown?.disease_score ?? 0) + (breakdown?.interaction_score ?? 0);

  // Patient's existing ICD-10 codes
  const patientCodes = useMemo(() => {
    if (!breakdown?.hcc_details) return [];
    const codes: string[] = [];
    for (const hcc of breakdown.hcc_details) {
      for (const c of (hcc.icd10_codes || [])) {
        const code = typeof c === "string" ? c : c.code || "";
        if (code && !codes.includes(code)) codes.push(code);
      }
    }
    return codes;
  }, [breakdown]);

  // Suspect suggestions — ICD codes AI found but not yet coded
  const suspectSuggestions = useMemo(() => {
    const list = suspects?.suspects || suspects || [];
    if (!Array.isArray(list)) return [];
    const seen = new Set(patientCodes.map(c => c.replace(/\./g, "").toUpperCase()));
    return list
      .filter((s: SuspectItem) => {
        const code = (s.suspect_icd10 || s.icd10_code || s.icd10 || "").replace(/\./g, "").toUpperCase();
        return code && !seen.has(code) && (s.status === "open" || !s.status);
      })
      .map((s: SuspectItem) => ({
        code: s.suspect_icd10 || s.icd10_code || s.icd10 || "",
        hcc: s.suspect_hcc || s.hcc_code || "",
        confidence: s.confidence_score || s.confidence || 0,
        coefficient: s.hcc_coefficient || 0,
        rationale: s.rationale || s.evidence_detail || "",
      }));
  }, [suspects, patientCodes]);

  // Full code list
  const allCodes = useMemo(() => {
    const extra = extraCodes.split(/[,\s]+/).map(c => c.trim().toUpperCase()).filter(Boolean);
    const combined = [...patientCodes];
    for (const c of extra) if (!combined.includes(c)) combined.push(c);
    return combined;
  }, [patientCodes, extraCodes]);

  const handleLookup = async () => {
    if (allCodes.length === 0) return;
    setLoading(true);
    setHasSearched(true);
    try {
      const data = await lookupICD10Crosswalk(allCodes);
      setResults(data.results || []);
    } catch { setResults([]); }
    finally { setLoading(false); }
  };

  useEffect(() => {
    if (patientCodes.length > 0 && !hasSearched) handleLookup();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [patientCodes]);

  const isExtra = (code: string) => {
    const n = code.replace(/\./g, "").toUpperCase();
    return !patientCodes.some(pc => pc.replace(/\./g, "").toUpperCase() === n);
  };

  const addSuggestion = (code: string) => {
    const current = extraCodes.split(/[,\s]+/).map(c => c.trim()).filter(Boolean);
    if (!current.some(c => c.toUpperCase() === code.toUpperCase())) {
      setExtraCodes([...current, code].join(", "));
    }
  };

  // RAF impact: estimate additional RAF from what-if codes
  const extraCoeffSum = useMemo(() => {
    if (!results.length) return 0;
    return results
      .filter(r => isExtra(r.icd10_code) && r.cms_hcc_v28)
      .reduce((sum, r) => {
        // Try to find coefficient from suspects
        const match = suspectSuggestions.find((s) =>
          s.code.replace(/\./g, "").toUpperCase() === r.icd10_code.replace(/\./g, "").toUpperCase()
        );
        return sum + (match?.coefficient || 0.15); // default estimate if no coefficient
      }, 0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [results, suspectSuggestions]);

  const projectedRaf = currentRaf + extraCoeffSum;
  const hasExtras = results.some(r => isExtra(r.icd10_code));

  return (
    <div className="animate-slide-up stagger-2" style={{ display: "flex", flexDirection: "column", gap: 16 }}>

      {/* ── RAF Impact Preview ── */}
      {hasExtras && extraCoeffSum > 0 && (
        <div style={{
          display: "grid", gridTemplateColumns: "1fr auto 1fr", alignItems: "center", gap: 16,
          padding: "16px 24px", borderRadius: 12,
          background: `linear-gradient(135deg, ${C.blue50} 0%, ${C.emerald50} 100%)`,
          border: `1px solid ${C.blue100}`,
        }}>
          <div>
            <div style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.08em", color: C.slate400 }}>Current RAF</div>
            <div style={{ fontSize: 24, fontWeight: 800, fontFamily: "monospace", color: C.slate700 }}>{currentRaf.toFixed(3)}</div>
            <div style={{ fontSize: 12, color: C.slate400 }}>${Math.round(currentRaf * MA_PAYMENT_PER_RAF).toLocaleString()}/yr</div>
          </div>
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 2 }}>
            <span style={{ fontSize: 20, color: C.blue600 }}>{"\u2192"}</span>
            <span style={{ fontSize: 12, fontWeight: 700, fontFamily: "monospace", color: C.emerald600, background: C.emerald50, padding: "2px 8px", borderRadius: 6, border: `1px solid ${C.emerald100}` }}>
              +{extraCoeffSum.toFixed(3)}
            </span>
          </div>
          <div style={{ textAlign: "right" }}>
            <div style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.08em", color: C.emerald600 }}>Projected RAF</div>
            <div style={{ fontSize: 24, fontWeight: 800, fontFamily: "monospace", color: C.emerald600 }}>{projectedRaf.toFixed(3)}</div>
            <div style={{ fontSize: 12, color: C.emerald600 }}>
              ${Math.round(projectedRaf * MA_PAYMENT_PER_RAF).toLocaleString()}/yr
              <span style={{ fontWeight: 700, marginLeft: 4 }}>(+${Math.round(extraCoeffSum * MA_PAYMENT_PER_RAF).toLocaleString()})</span>
            </div>
          </div>
        </div>
      )}

      {/* ── Main Crosswalk Card ── */}
      <Card noPadding>
        <div style={{ padding: "16px 20px", borderBottom: `1px solid ${C.slate100}` }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
            <div>
              <div style={{ fontSize: 15, fontWeight: 700, color: C.slate800 }}>ICD-10 to HCC Crosswalk</div>
              <div style={{ fontSize: 12, color: C.slate400, marginTop: 2 }}>{patientCodes.length} active codes {hasExtras && `+ ${results.filter(r => isExtra(r.icd10_code)).length} what-if`}</div>
            </div>
          </div>
          {/* Input */}
          <div style={{ display: "flex", gap: 8, marginTop: 12, alignItems: "center" }}>
            <input
              value={extraCodes}
              onChange={e => setExtraCodes(e.target.value)}
              placeholder="Add codes to test... e.g. N18.4, J44.1"
              style={{
                flex: 1, padding: "8px 12px", borderRadius: 8, border: `1px solid ${C.slate200}`,
                fontSize: 13, fontFamily: "monospace", color: C.slate800, outline: "none",
                transition: "border-color 0.15s",
              }}
              onFocus={e => (e.target.style.borderColor = C.blue600)}
              onBlur={e => (e.target.style.borderColor = C.slate200)}
              onKeyDown={e => e.key === "Enter" && handleLookup()}
            />
            <button
              onClick={handleLookup}
              disabled={loading || allCodes.length === 0}
              style={{
                padding: "8px 16px", borderRadius: 8, border: "none",
                background: C.blue600, color: C.white, fontSize: 13, fontWeight: 600,
                cursor: loading ? "wait" : "pointer", opacity: loading ? 0.7 : 1,
                whiteSpace: "nowrap",
              }}
            >
              {loading ? "Looking up..." : "Look Up"}
            </button>
          </div>
        </div>

        {/* Results table */}
        {hasSearched && results.length > 0 && (
          <>
            <div style={{
              display: "grid", gridTemplateColumns: "36px minmax(70px,1fr) 70px 70px 70px 2.5fr",
              padding: "8px 20px", gap: 4, borderBottom: `1px solid ${C.slate200}`, background: "#f0fdfa",
            }}>
              {["#", "ICD-10", "V24", "V28", "RxHCC", "Description"].map((h, i) => (
                <span key={h} style={{
                  fontSize: 10, fontWeight: 700, textTransform: "uppercase" as const,
                  letterSpacing: "0.06em", color: C.blue600,
                  textAlign: i === 0 ? "center" as const : "left" as const,
                }}>{h}</span>
              ))}
            </div>
            {results.map((r: CrosswalkResult, i: number) => {
              const extra = isExtra(r.icd10_code);
              return (
                <div key={r.icd10_code || i} style={{
                  display: "grid", gridTemplateColumns: "36px minmax(70px,1fr) 70px 70px 70px 2.5fr",
                  padding: "9px 20px", gap: 4, alignItems: "center",
                  borderBottom: `1px solid ${C.slate100}`,
                  borderLeft: extra ? `3px solid ${C.amber500}` : `3px solid transparent`,
                  background: extra ? C.amber50 + "40" : "transparent",
                  transition: "background 0.15s",
                }}
                onMouseEnter={e => (e.currentTarget.style.background = C.slate100 + "60")}
                onMouseLeave={e => (e.currentTarget.style.background = extra ? C.amber50 + "40" : "transparent")}
                >
                  <span style={{ fontSize: 12, color: C.slate400, textAlign: "center", fontWeight: 600 }}>{r.sno}</span>
                  <span style={{ fontSize: 13, fontFamily: "monospace", fontWeight: 700, color: extra ? C.amber600 : C.blue600 }}>{r.icd10_code}</span>
                  <span style={{ fontSize: 12, fontFamily: "monospace", fontWeight: 600, color: r.cms_hcc_v24 ? C.slate700 : C.slate300 }}>{r.cms_hcc_v24 ?? "--"}</span>
                  <span style={{ fontSize: 12, fontFamily: "monospace", fontWeight: 600, color: r.cms_hcc_v28 ? C.slate700 : C.slate300 }}>{r.cms_hcc_v28 ?? "--"}</span>
                  <span style={{ fontSize: 12, fontFamily: "monospace", fontWeight: 600, color: r.rxhcc ? C.slate700 : C.slate300 }}>{r.rxhcc ?? "--"}</span>
                  <span style={{ fontSize: 12, color: C.slate600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {r.description || ""}
                    {extra && <span style={{ marginLeft: 6, fontSize: 10, padding: "1px 5px", borderRadius: 4, background: C.amber100, color: C.amber600, fontWeight: 600 }}>What-if</span>}
                  </span>
                </div>
              );
            })}
          </>
        )}
        {hasSearched && !results.length && !loading && <EmptyState title="No crosswalk results found" />}
      </Card>

      {/* ── Smart Suggestions ── */}
      {suspectSuggestions.length > 0 && (
        <Card noPadding>
          <div style={{ padding: "14px 20px", borderBottom: `1px solid ${C.slate100}` }}>
            <div style={{ fontSize: 14, fontWeight: 700, color: C.slate800 }}>Codes to Consider</div>
            <div style={{ fontSize: 12, color: C.slate400, marginTop: 1 }}>AI-detected conditions not yet coded — click to add to what-if analysis</div>
          </div>
          {suspectSuggestions.map((s, i: number) => {
            const alreadyAdded = extraCodes.toUpperCase().includes(s.code.replace(/\./g, "").toUpperCase()) ||
                                 extraCodes.includes(s.code);
            return (
              <div key={s.code || i} style={{
                display: "flex", alignItems: "center", gap: 12, padding: "10px 20px",
                borderBottom: `1px solid ${C.slate100}`, transition: "background 0.15s",
              }}
              onMouseEnter={e => (e.currentTarget.style.background = C.slate100 + "60")}
              onMouseLeave={e => (e.currentTarget.style.background = "transparent")}
              >
                {/* ICD code */}
                <span style={{ minWidth: 64, padding: "3px 8px", borderRadius: 6, fontSize: 12, fontWeight: 700, fontFamily: "monospace", background: C.amber50, color: C.amber600, textAlign: "center", border: `1px solid ${C.amber100}` }}>
                  {s.code}
                </span>
                {/* HCC */}
                <span style={{ fontSize: 11, fontFamily: "monospace", fontWeight: 600, color: C.slate400, minWidth: 50 }}>
                  HCC {s.hcc}
                </span>
                {/* Rationale */}
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 12, color: C.slate600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.rationale}</div>
                </div>
                {/* Confidence */}
                <span style={{
                  fontSize: 11, fontWeight: 700, fontFamily: "monospace", padding: "2px 6px", borderRadius: 4,
                  background: s.confidence >= 0.8 ? C.emerald50 : C.amber50,
                  color: s.confidence >= 0.8 ? C.emerald600 : C.amber600,
                  border: `1px solid ${s.confidence >= 0.8 ? C.emerald100 : C.amber100}`,
                }}>
                  {Math.round(s.confidence * 100)}%
                </span>
                {/* Coefficient */}
                {s.coefficient > 0 && (
                  <span style={{ fontSize: 12, fontFamily: "monospace", fontWeight: 600, color: C.emerald600, minWidth: 50, textAlign: "right" }}>
                    +{s.coefficient.toFixed(3)}
                  </span>
                )}
                {/* Add button */}
                <button
                  onClick={() => addSuggestion(s.code)}
                  disabled={alreadyAdded}
                  style={{
                    padding: "4px 10px", borderRadius: 6, border: `1px solid ${alreadyAdded ? C.slate200 : C.blue100}`,
                    background: alreadyAdded ? C.slate100 : C.blue50, color: alreadyAdded ? C.slate400 : C.blue600,
                    fontSize: 11, fontWeight: 600, cursor: alreadyAdded ? "default" : "pointer",
                    whiteSpace: "nowrap",
                  }}
                >
                  {alreadyAdded ? "Added" : "Add"}
                </button>
              </div>
            );
          })}
        </Card>
      )}
    </div>
  );
}

function RAFHistoryBars({ history }: { history: RafHistoryResponse | ScoreHistoryEntry[] | undefined }) {
  const scores: ScoreHistoryEntry[] | undefined = Array.isArray(history) ? history : (history as RafHistoryResponse | undefined)?.scores ?? (history as RafHistoryResponse | undefined)?.history;
  if (!scores || !Array.isArray(scores) || scores.length === 0) {
    return <EmptyState title="No historical scores available" />;
  }

  const maxScore = Math.max(
    ...scores.map((s: ScoreHistoryEntry) => s.raf_score || s.score || 0),
    1
  );

  return (
    <div
      style={{
        display: "flex",
        alignItems: "flex-end",
        gap: 16,
        height: 160,
        padding: "0 8px",
      }}
    >
      {scores.map((entry: ScoreHistoryEntry, i: number) => {
        const score = entry.raf_score || entry.score || 0;
        const year = entry.year || entry.measurement_year;
        const heightPct = Math.max((score / maxScore) * 100, 8);
        const color = rafScoreColor(score);

        return (
          <div
            key={entry.measurement_year || entry.year || i}
            style={{
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              gap: 6,
              flex: 1,
            }}
          >
            <span
              className="tabular-nums"
              style={{
                fontSize: 12,
                fontWeight: 700,
                fontFamily: "monospace",
                color,
              }}
            >
              {(score ?? 0).toFixed(3)}
            </span>
            <div
              style={{
                width: "100%",
                maxWidth: 48,
                height: `${heightPct}%`,
                minHeight: 8,
                borderRadius: "6px 6px 0 0",
                background: `${color}22`,
                border: `2px solid ${color}`,
                borderBottom: "none",
                transition: "height 0.4s ease",
              }}
            />
            <span
              style={{
                fontSize: 12,
                fontWeight: 600,
                color: C.slate500,
              }}
            >
              {year}
            </span>
          </div>
        );
      })}
    </div>
  );
}

// ===========================================================================
// CLINICAL DATA TAB
// ===========================================================================
function ClinicalTab({
  meds,
  medsLoading,
  vitalsSuspects,
  vitalsLoading,
  labSuspects,
  labsLoading,
  allergies,
  allergiesLoading,
  immunizations,
  immunizationsLoading,
  familyHistory,
  familyHistoryLoading,
  sdoh,
  sdohLoading,
  medGaps,
  medGapsLoading,
  patient,
  profile,
  profileLoading,
  breakdown,
  breakdownLoading,
}: {
  meds: MedicationsResponse | MedicationItem[] | undefined;
  medsLoading: boolean;
  vitalsSuspects: ClinicalFindingsResponse | ClinicalFindingItem[] | undefined;
  vitalsLoading: boolean;
  labSuspects: ClinicalFindingsResponse | ClinicalFindingItem[] | undefined;
  labsLoading: boolean;
  allergies: AllergiesResponse | AllergyItem[] | undefined;
  allergiesLoading: boolean;
  immunizations: ImmunizationsResponse | ImmunizationItem[] | undefined;
  immunizationsLoading: boolean;
  familyHistory: FamilyHistoryResponse | FamilyHistoryItem[] | undefined;
  familyHistoryLoading: boolean;
  sdoh: SdohResponse | SdohFactor[] | undefined;
  sdohLoading: boolean;
  medGaps: MedicationGapsResponse | MedicationGapItem[] | undefined;
  medGapsLoading: boolean;
  patient: Patient | undefined;
  profile: PatientProfile | undefined;
  profileLoading: boolean;
  breakdown: ExtendedRafBreakdown | undefined;
  breakdownLoading: boolean;
}) {
  const [activeSection, setActiveSection] = useState("demographics");

  // Extract arrays from possibly-wrapped responses
  const medItems: MedicationItem[] = Array.isArray(meds) ? meds : (meds as MedicationsResponse | undefined)?.medications ?? [];
  const vitalsItems: ClinicalFindingItem[] = Array.isArray(vitalsSuspects) ? vitalsSuspects : (vitalsSuspects as ClinicalFindingsResponse | undefined)?.suspects ?? [];
  const labItems: ClinicalFindingItem[] = Array.isArray(labSuspects) ? labSuspects : (labSuspects as ClinicalFindingsResponse | undefined)?.suspects ?? [];
  const allergyItems: AllergyItem[] = Array.isArray(allergies) ? allergies : (allergies as AllergiesResponse | undefined)?.allergies ?? [];
  const immunizationItems: ImmunizationItem[] = Array.isArray(immunizations) ? immunizations : (immunizations as ImmunizationsResponse | undefined)?.immunizations ?? [];
  // Family history: API returns { family_history: { relatives_cancer: "Yes", ... , history_father: "...", ... } }
  const familyItems: FamilyHistoryItem[] = (() => {
    if (Array.isArray(familyHistory)) return familyHistory;
    const fhResp = familyHistory as any;
    if (fhResp?.history && Array.isArray(fhResp.history)) return fhResp.history;
    // Convert dict format to array
    const fh = fhResp?.family_history;
    if (!fh || typeof fh !== "object") return [];
    const items: FamilyHistoryItem[] = [];
    // Parse history_father/mother/siblings first
    if (fh.history_father) items.push({ condition: fh.history_father, relation: "Father", title: fh.history_father });
    if (fh.history_mother) items.push({ condition: fh.history_mother, relation: "Mother", title: fh.history_mother });
    if (fh.history_siblings) items.push({ condition: fh.history_siblings, relation: "Sibling", title: fh.history_siblings });
    if (fh.history_offspring) items.push({ condition: fh.history_offspring, relation: "Offspring", title: fh.history_offspring });
    if (fh.history_spouse) items.push({ condition: fh.history_spouse, relation: "Spouse", title: fh.history_spouse });
    // Parse relatives_* fields
    const relMap: Record<string, string> = {
      relatives_cancer: "Cancer", relatives_diabetes: "Diabetes",
      relatives_heart_disease: "Heart Disease", relatives_hypertension: "Hypertension",
      relatives_stroke: "Stroke", relatives_epilepsy: "Epilepsy",
      relatives_mental_illness: "Mental Illness", relatives_suicide: "Suicide",
      relatives_arthritis: "Arthritis", relatives_asthma: "Asthma",
    };
    for (const [key, label] of Object.entries(relMap)) {
      const val = fh[key];
      if (val && val !== "" && val !== "N/A") {
        // Only add if not already covered by history_father/mother/siblings
        if (!items.length) items.push({ condition: `${label}: ${val}`, relation: "Family", title: label });
      }
    }
    return items;
  })();

  // SDOH: API returns { billed_z_codes: [...], sdoh_form: {...}, billable_highlights: {...} }
  const sdohItems: SdohFactor[] = (() => {
    if (Array.isArray(sdoh)) return sdoh;
    const sr = sdoh as any;
    if (sr?.factors && Array.isArray(sr.factors)) return sr.factors;
    const items: SdohFactor[] = [];
    // billed_z_codes
    if (sr?.billed_z_codes?.length) {
      for (const z of sr.billed_z_codes) {
        items.push({ factor: z.code_text || z.code || "Z-code", category: z.code, description: z.code_text || "" });
      }
    }
    // sdoh_form entries
    if (sr?.sdoh_form && typeof sr.sdoh_form === "object") {
      for (const [k, v] of Object.entries(sr.sdoh_form)) {
        if (v && v !== "" && v !== "N/A") items.push({ factor: k.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase()), description: String(v) });
      }
    }
    // If nothing, show billable highlights as potential factors
    if (!items.length && sr?.billable_highlights) {
      for (const [code, desc] of Object.entries(sr.billable_highlights)) {
        items.push({ factor: String(desc), category: code, description: `Billable Z-code: ${code}` });
      }
    }
    return items;
  })();

  // Medication gaps: API returns { gaps: [{ icd_code, drug, description, ... }] }
  const medGapItems: MedicationGapItem[] = (() => {
    if (Array.isArray(medGaps)) return medGaps;
    const mg = medGaps as any;
    if (mg?.gaps && Array.isArray(mg.gaps)) {
      return mg.gaps.map((g: any) => ({
        condition: g.description || g.condition || g.gap || "",
        medication: g.drug || g.medication || "",
        drug: g.drug || "",
        icd10_code: g.icd_code || g.icd10_code || "",
        evidence: g.evidence || g.rationale || `Medication ${g.drug || ""} suggests unrecorded diagnosis`,
        gap: g.description || g.gap || "",
      }));
    }
    return [];
  })();

  const sections = [
    { id: "demographics", label: "Demographics" },
    { id: "insurance", label: "Insurance" },
    { id: "medications", label: "Medications" },
    { id: "vitals", label: "Vitals" },
    { id: "labs", label: "Labs" },
    { id: "allergies", label: "Allergies" },
    { id: "immunizations", label: "Immunizations" },
    { id: "family", label: "Family History" },
    { id: "sdoh", label: "SDOH" },
    { id: "medgaps", label: "Medication Gaps" },
  ];

  return (
    <div style={{ display: "flex", gap: 24 }}>
      {/* Left nav */}
      <nav
        style={{
          width: 200,
          flexShrink: 0,
          position: "sticky",
          top: 180,
          alignSelf: "flex-start",
        }}
      >
        {sections.map((s) => (
          <button
            key={s.id}
            onClick={() => setActiveSection(s.id)}
            style={{
              display: "block",
              width: "100%",
              padding: "10px 14px",
              borderRadius: 8,
              border: "none",
              textAlign: "left",
              fontSize: 13,
              fontWeight: activeSection === s.id ? 600 : 500,
              color: activeSection === s.id ? C.white : C.slate600,
              background:
                activeSection === s.id ? C.slate800 : "transparent",
              cursor: "pointer",
              marginBottom: 2,
              transition: "all 0.15s",
            }}
            onMouseEnter={(e) => {
              if (activeSection !== s.id) {
                e.currentTarget.style.background = C.slate100;
              }
            }}
            onMouseLeave={(e) => {
              if (activeSection !== s.id) {
                e.currentTarget.style.background = "transparent";
              }
            }}
          >
            {s.label}
          </button>
        ))}
      </nav>

      {/* Content */}
      <div style={{ flex: 1, minWidth: 0 }}>
        {activeSection === "demographics" && (
          <ClinicalSection title="Patient Demographics" loading={profileLoading}>
            <div style={{ padding: "16px 20px" }}>
              {(() => {
                const dob = (patient?.DOB || patient?.dob || profile?.demographics?.dob) as string | undefined;
                const sex = (patient?.sex || profile?.demographics?.sex) as string | undefined;
                const rawRace = (profile?.demographics?.race as string) || patient?.race || "";
                const rawEth = (profile?.demographics?.ethnicity as string) || patient?.ethnicity || "";
                const language = (profile?.demographics?.language as string) || patient?.language || "\u2014";
                const address = [patient?.street, patient?.city, patient?.state, patient?.postal_code].filter(Boolean).join(", ") || (profile?.demographics?.address as string) || "\u2014";
                const phone = patient?.phone_home || patient?.phone_cell || (profile?.demographics?.phone as string) || "\u2014";
                const email = (patient as any)?.email || "\u2014";
                const enrollment = profile?.enrollment as Record<string, string> | undefined;
                // Format race/ethnicity labels
                const fmtLabel = (s: string) => s ? s.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase()) : "\u2014";
                const race = fmtLabel(rawRace);
                const ethnicity = fmtLabel(rawEth);
                const fmtDual = (s?: string) => {
                  if (!s) return "\u2014";
                  if (s === "non_dual") return "Non-Dual";
                  if (s === "full_dual") return "Full Dual Eligible";
                  if (s === "partial_dual") return "Partial Dual";
                  return s.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
                };
                const fmtOrec = (o?: string) => {
                  if (o === "0") return "0 — Aged (≥65)";
                  if (o === "1") return "1 — Disabled (<65)";
                  if (o === "2") return "2 — ESRD";
                  return o || "\u2014";
                };
                return (
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0 32px" }}>
                    <div>
                      <DataRow label="Date of Birth" value={dob ? formatDate(dob) : "\u2014"} />
                      <DataRow label="Sex" value={sex ? sex.charAt(0).toUpperCase() + sex.slice(1) : "\u2014"} />
                      <DataRow label="Race" value={race} />
                      <DataRow label="Ethnicity" value={ethnicity} />
                      <DataRow label="Language" value={language} />
                      <DataRow label="Email" value={email} />
                    </div>
                    <div>
                      <DataRow label="Address" value={address} />
                      <DataRow label="Phone" value={phone} />
                      <DataRow label="Plan Type" value={enrollment?.plan_type || "\u2014"} />
                      <DataRow label="Enrolled Since" value={enrollment?.enrolled_since ? formatDate(enrollment.enrolled_since) : "\u2014"} />
                      <DataRow label="Dual Status" value={fmtDual(enrollment?.dual_status)} />
                      <DataRow label="OREC" value={fmtOrec(enrollment?.orec)} />
                    </div>
                  </div>
                );
              })()}
            </div>
          </ClinicalSection>
        )}

        {activeSection === "insurance" && (
          <ClinicalSection title="Insurance & Enrollment" loading={profileLoading}>
            <div style={{ padding: "16px 20px" }}>
              {(() => {
                const enrollment = profile?.enrollment as Record<string, string> | undefined;
                const fmtDual = (s?: string) => {
                  if (!s) return "\u2014";
                  if (s === "non_dual") return "Non-Dual";
                  if (s === "full_dual") return "Full Dual Eligible";
                  if (s === "partial_dual") return "Partial Dual";
                  return s.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
                };
                const fmtOrec = (o?: string) => {
                  if (o === "0") return "0 — Aged (≥65)";
                  if (o === "1") return "1 — Disabled (<65)";
                  if (o === "2") return "2 — ESRD";
                  return o || "\u2014";
                };
                return (
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0 32px" }}>
                    <div>
                      <DataRow label="Primary Insurance" value={enrollment?.primary_insurance || "\u2014"} />
                      <DataRow label="Secondary Insurance" value={enrollment?.secondary_insurance || "\u2014"} />
                      <DataRow label="Plan Type" value={enrollment?.plan_type || "\u2014"} />
                    </div>
                    <div>
                      <DataRow label="Enrolled Since" value={enrollment?.enrolled_since ? formatDate(enrollment.enrolled_since) : "\u2014"} />
                      <DataRow label="Dual Status" value={fmtDual(enrollment?.dual_status)} />
                      <DataRow label="OREC" value={fmtOrec(enrollment?.orec)} />
                    </div>
                  </div>
                );
              })()}
            </div>
          </ClinicalSection>
        )}

        {activeSection === "medications" && (
          <ClinicalSection title="Active Medications" loading={medsLoading}>
            {!medItems.length ? (
              <EmptyState title="No active medications" />
            ) : (
              <SimpleTable
                headers={["Drug", "Dose", "Frequency", "Date"]}
                rows={medItems.map((m: MedicationItem) => [
                  m.drug || m.title || m.medication || "\u2014",
                  m.dosage || m.dose || "\u2014",
                  m.frequency || m.route || "\u2014",
                  formatDate(m.begdate || m.start_date || m.date),
                ])}
              />
            )}
          </ClinicalSection>
        )}

        {activeSection === "vitals" && (
          <ClinicalSection
            title="Vitals"
            loading={vitalsLoading}
          >
            {(() => {
              const v = (vitalsSuspects as any)?.latest_vitals || (profile as any)?.vitals?.latest;
              if (!v) return <EmptyState title="No vitals recorded" />;
              const bmi = v.weight && v.height ? (v.weight / ((v.height / 100) ** 2)).toFixed(1) : null;
              return (
                <div>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "0 32px", padding: "16px 20px" }}>
                    <div>
                      <DataRow label="Weight" value={v.weight ? `${v.weight} kg (${(v.weight * 2.205).toFixed(1)} lbs)` : "\u2014"} />
                      <DataRow label="Height" value={v.height ? `${v.height} cm (${(v.height / 2.54).toFixed(0)}″)` : "\u2014"} />
                      <DataRow label="BMI" value={bmi ? `${bmi} kg/m²` : "\u2014"} />
                    </div>
                    <div>
                      <DataRow label="Blood Pressure" value={v.bps && v.bpd ? `${v.bps}/${v.bpd} mmHg` : "\u2014"} />
                      <DataRow label="Temperature" value={v.temperature ? `${v.temperature} °F` : "\u2014"} />
                      <DataRow label="Pulse" value={v.pulse ? `${v.pulse} bpm` : "\u2014"} />
                    </div>
                    <div>
                      <DataRow label="Respiration" value={v.respiration ? `${v.respiration} /min` : "\u2014"} />
                      <DataRow label="O₂ Saturation" value={v.oxygen_saturation ? `${v.oxygen_saturation}%` : "\u2014"} />
                      <DataRow label="Recorded" value={formatDate(v.date)} />
                    </div>
                  </div>
                  {vitalsItems.length > 0 && (
                    <div style={{ borderTop: `1px solid #e2e8f0`, padding: "12px 20px 0" }}>
                      <div style={{ fontSize: 13, fontWeight: 600, color: "#475569", marginBottom: 8 }}>Vitals-Derived Findings</div>
                      <FindingsList
                        items={vitalsItems.map((s: ClinicalFindingItem) => ({
                          name: s.condition || s.finding || "\u2014",
                          detail: s.evidence || s.rationale || s.detail || "",
                          icd10: s.icd10_code,
                        }))}
                      />
                    </div>
                  )}
                </div>
              );
            })()}
          </ClinicalSection>
        )}

        {activeSection === "labs" && (
          <ClinicalSection
            title="Lab Results"
            loading={labsLoading}
          >
            {(() => {
              const labResults = ((labSuspects as any)?.labs?.results || []) as Array<{ id?: number; result_text?: string; date?: string; encounter?: number }>;
              if (!labResults.length && !labItems.length) return <EmptyState title="No lab results" />;
              // Parse result_text like "HbA1c: 7.8 % (Ref: 4.0-5.6) [ABNORMAL]"
              const parsed = labResults.map((l) => {
                const rt = l.result_text || "";
                const nameMatch = rt.match(/^([^:]+):/);
                const valMatch = rt.match(/:\s*([^\(]+)/);
                const refMatch = rt.match(/\(Ref:\s*([^)]+)\)/);
                const flagMatch = rt.match(/\[([A-Z]+)\]/);
                return {
                  name: nameMatch ? nameMatch[1].trim() : rt,
                  value: valMatch ? valMatch[1].trim() : "\u2014",
                  reference: refMatch ? refMatch[1].trim() : "\u2014",
                  flag: flagMatch ? flagMatch[1] : "NORMAL",
                  date: l.date,
                };
              });
              return (
                <div>
                  {parsed.length > 0 && (
                    <SimpleTable
                      headers={["Test", "Result", "Reference Range", "Flag", "Date"]}
                      rows={parsed.map((l) => [
                        l.name,
                        l.value,
                        l.reference,
                        l.flag === "ABNORMAL" || l.flag === "HIGH" || l.flag === "LOW"
                          ? `⚠ ${l.flag}`
                          : l.flag === "NORMAL" ? "✓ Normal" : l.flag,
                        formatDate(l.date),
                      ])}
                    />
                  )}
                  {labItems.length > 0 && (
                    <div style={{ borderTop: `1px solid #e2e8f0`, padding: "12px 20px 0" }}>
                      <div style={{ fontSize: 13, fontWeight: 600, color: "#475569", marginBottom: 8 }}>Lab-Derived Suspect Conditions</div>
                      <FindingsList
                        items={labItems.map((s: ClinicalFindingItem) => ({
                          name: s.condition || s.finding || "\u2014",
                          detail: s.evidence || s.rationale || "",
                          icd10: s.icd10_code,
                          hcc: s.hcc_code,
                        }))}
                      />
                    </div>
                  )}
                </div>
              );
            })()}
          </ClinicalSection>
        )}

        {activeSection === "allergies" && (
          <ClinicalSection title="Allergies" loading={allergiesLoading}>
            {!allergyItems.length ? (
              <EmptyState title="No allergies documented" />
            ) : (
              <FindingsList
                items={allergyItems.map(
                  (a: AllergyItem) => ({
                    name:
                      a.title || a.allergen || a.substance || "\u2014",
                    detail: [a.reaction, a.severity]
                      .filter(Boolean)
                      .join(" \u00B7 "),
                  })
                )}
              />
            )}
          </ClinicalSection>
        )}

        {activeSection === "immunizations" && (
          <ClinicalSection
            title="Immunizations"
            loading={immunizationsLoading}
          >
            {!immunizationItems.length ? (
              <EmptyState title="No immunizations documented" />
            ) : (
              <SimpleTable
                headers={["Vaccine", "Date"]}
                rows={immunizationItems.map((imm: ImmunizationItem) => [
                  imm.title ||
                    imm.vaccine ||
                    imm.immunization ||
                    "\u2014",
                  formatDate(
                    imm.administered_date || imm.date || imm.create_date
                  ),
                ])}
              />
            )}
          </ClinicalSection>
        )}

        {activeSection === "family" && (
          <ClinicalSection
            title="Family History"
            loading={familyHistoryLoading}
          >
            {!familyItems.length ? (
              <EmptyState title="No family history documented" />
            ) : (
              <FindingsList
                items={familyItems.map((fh: FamilyHistoryItem) => ({
                  name:
                    fh.condition ||
                    fh.title ||
                    fh.diagnosis ||
                    "\u2014",
                  detail: fh.relation || "",
                }))}
              />
            )}
          </ClinicalSection>
        )}

        {activeSection === "sdoh" && (
          <ClinicalSection
            title="Social Determinants of Health"
            loading={sdohLoading}
          >
            {!sdohItems.length ? (
              <EmptyState title="No SDOH data available" />
            ) : (
              <FindingsList
                items={sdohItems.map(
                  (s: SdohFactor) => ({
                    name:
                      s.factor || s.category || "\u2014",
                    detail: s.description || "",
                  })
                )}
              />
            )}
          </ClinicalSection>
        )}

        {activeSection === "medgaps" && (
          <ClinicalSection
            title="Medication-Derived Gaps"
            loading={medGapsLoading}
          >
            {!medGapItems.length ? (
              <EmptyState title="No medication gaps identified" />
            ) : (
              <FindingsList
                items={medGapItems.map((g: MedicationGapItem) => ({
                  name: g.condition || g.gap || "\u2014",
                  detail: `${g.medication || g.drug || ""} ${g.evidence || g.rationale || ""}`.trim(),
                  icd10: g.icd10_code,
                }))}
              />
            )}
          </ClinicalSection>
        )}
      </div>
    </div>
  );
}

function ClinicalSection({
  title,
  loading,
  children,
}: {
  title: string;
  loading: boolean;
  children: React.ReactNode;
}) {
  return (
    <Card noPadding className="animate-fade-in">
      <SectionHeader title={title} />
      {loading ? <SectionLoader /> : children}
    </Card>
  );
}

function SimpleTable({
  headers,
  rows,
}: {
  headers: string[];
  rows: string[][];
}) {
  return (
    <div>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: headers
            .map((_, i) => (i === 0 ? "1fr" : "auto"))
            .join(" "),
          padding: "10px 20px",
          background: `linear-gradient(135deg, ${C.slate100}, ${C.slate200}40)`,
          borderTop: `1px solid ${C.slate200}`,
          borderBottom: `2px solid ${C.slate200}`,
          gap: 16,
        }}
      >
        {headers.map((h) => (
          <span
            key={h}
            style={{
              fontSize: 11,
              fontWeight: 700,
              textTransform: "uppercase",
              letterSpacing: "0.06em",
              color: C.slate500,
            }}
          >
            {h}
          </span>
        ))}
      </div>
      {rows.map((row, i) => (
        <div
          key={`${row[0]}-${i}`}
          style={{
            display: "grid",
            gridTemplateColumns: headers
              .map((_, idx) => (idx === 0 ? "1fr" : "auto"))
              .join(" "),
            padding: "10px 20px",
            borderBottom: `1px solid ${C.slate100}`,
            background: i % 2 === 1 ? C.slate100 + "60" : "transparent",
            gap: 16,
            transition: "background 0.15s",
          }}
          onMouseEnter={(e) =>
            (e.currentTarget.style.background = C.slate100)
          }
          onMouseLeave={(e) =>
            (e.currentTarget.style.background = i % 2 === 1 ? C.slate100 + "60" : "transparent")
          }
        >
          {row.map((cell, j) => (
            <span
              key={j}
              style={{
                fontSize: 13,
                fontWeight: j === 0 ? 500 : 400,
                color: j === 0 ? C.slate800 : C.slate500,
                whiteSpace: "nowrap",
                overflow: "hidden",
                textOverflow: "ellipsis",
              }}
            >
              {cell}
            </span>
          ))}
        </div>
      ))}
    </div>
  );
}

function FindingsList({
  items,
}: {
  items: {
    name: string;
    detail?: string;
    icd10?: string;
    hcc?: string;
  }[];
}) {
  return (
    <div>
      {items.map((item, i) => (
        <div
          key={item.icd10 || item.hcc || `${item.name}-${i}`}
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "12px 20px",
            borderTop: i === 0 ? `1px solid ${C.slate200}` : "none",
            borderBottom: `1px solid ${C.slate100}`,
          }}
        >
          <div>
            <div
              style={{
                fontSize: 13,
                fontWeight: 500,
                color: C.slate800,
              }}
            >
              {item.name}
            </div>
            {item.detail && (
              <div
                style={{
                  fontSize: 12,
                  color: C.slate400,
                  marginTop: 2,
                }}
              >
                {item.detail}
              </div>
            )}
          </div>
          <div style={{ display: "flex", gap: 6 }}>
            {item.icd10 && (
              <span
                style={{
                  display: "inline-block",
                  padding: "2px 8px",
                  borderRadius: 4,
                  fontSize: 11,
                  fontWeight: 600,
                  fontFamily: "monospace",
                  background: C.slate100,
                  color: C.slate700,
                  border: `1px solid ${C.slate200}`,
                }}
              >
                {item.icd10}
              </span>
            )}
            {item.hcc && (
              <span
                style={{
                  display: "inline-block",
                  padding: "2px 8px",
                  borderRadius: 4,
                  fontSize: 11,
                  fontWeight: 600,
                  fontFamily: "monospace",
                  background: C.blue50,
                  color: C.blue600,
                  border: `1px solid ${C.blue100}`,
                }}
              >
                {item.hcc}
              </span>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

// ===========================================================================
// ENCOUNTERS TAB
// ===========================================================================
function EncountersTab({ encounters, encountersLoading, analyzeMutation, lastAnalysisResult, selectedYear }: {
  encounters: PatientEncountersResponse | undefined;
  encountersLoading: boolean;
  analyzeMutation: { mutate: (encId: number) => void; isPending: boolean; variables?: number };
  lastAnalysisResult: Record<number, AnalysisResult>;
  selectedYear: number;
}) {
  const [expandedEnc, setExpandedEnc] = useState<number | null>(null);

  // Filter encounters by selected year
  const filteredEncounters = useMemo(() => {
    if (!encounters?.encounters) return [];
    return encounters.encounters.filter((enc: EncounterItem) => {
      const encDate = enc.date || enc.encounter_date;
      if (!encDate) return true; // show if no date
      const encYear = new Date(encDate).getFullYear();
      return encYear === selectedYear;
    });
  }, [encounters, selectedYear]);

  if (encountersLoading) return <SectionLoader label="Loading encounters..." />;
  if (!filteredEncounters.length) {
    return (
      <Card>
        <EmptyState
          title={`No encounters found for ${selectedYear}`}
          icon={
            <svg
              width="24"
              height="24"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
            >
              <path d="M22 12h-4l-3 9L9 3l-3 9H2" />
            </svg>
          }
        />
      </Card>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      {filteredEncounters.map((enc: EncounterItem) => {
        const isExpanded = expandedEnc === enc.encounter_id;
        const hasNotes = !!enc.notes || !!enc.has_notes;
        const analysis = enc.analysis || enc.cached_analysis || lastAnalysisResult?.[enc.encounter_id];
        const diagnoses = analysis?.diagnoses || [];
        const hccFromAnalysis = diagnoses.filter(
          (d: AIDiagnosis) => d.hcc_code || d.hcc || d.hcc_mapping?.hcc_code
        ).length;

        return (
          <Card key={enc.encounter_id} noPadding className="hover-lift animate-fade-in" style={{ overflow: "hidden" }}>
            {/* Header row */}
            <div
              role="button"
              tabIndex={0}
              onClick={() =>
                setExpandedEnc(isExpanded ? null : enc.encounter_id)
              }
              onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setExpandedEnc(isExpanded ? null : enc.encounter_id); } }}
              style={{
                width: "100%",
                padding: "16px 20px",
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                background: "transparent",
                border: "none",
                cursor: "pointer",
                textAlign: "left",
                transition: "background 0.1s",
              }}
              onMouseEnter={(e) =>
                (e.currentTarget.style.background = C.slate100)
              }
              onMouseLeave={(e) =>
                (e.currentTarget.style.background = "transparent")
              }
            >
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 14,
                }}
              >
                <div
                  style={{
                    width: 40,
                    height: 40,
                    borderRadius: 10,
                    background: C.blue50,
                    color: C.blue600,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    flexShrink: 0,
                  }}
                >
                  <svg
                    width="20"
                    height="20"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  >
                    <path d="M22 12h-4l-3 9L9 3l-3 9H2" />
                  </svg>
                </div>
                <div>
                  <div
                    style={{
                      fontSize: 14,
                      fontWeight: 600,
                      color: C.slate800,
                    }}
                  >
                    {enc.reason || "Office Visit"}
                  </div>
                  <div
                    style={{
                      fontSize: 12,
                      color: C.slate400,
                      marginTop: 2,
                    }}
                  >
                    {enc.provider_fname || enc.provider_lname
                      ? `${enc.provider_fname || ""} ${enc.provider_lname || ""}`.trim()
                      : "Provider not listed"}
                    {" \u00B7 "}Encounter #{enc.encounter_id}
                  </div>
                </div>
              </div>

              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 12,
                }}
              >
                <span style={{ fontSize: 13, color: C.slate500 }}>
                  {formatDate(enc.date)}
                </span>
                {!hasNotes && (
                  <span
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      gap: 4,
                      padding: "3px 10px",
                      borderRadius: 6,
                      fontSize: 11,
                      fontWeight: 600,
                      background: C.amber50,
                      color: C.amber600,
                      border: `1px solid ${C.amber100}`,
                    }}
                  >
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0zM12 9v4M12 17h.01" />
                    </svg>
                    No notes
                  </span>
                )}
                {diagnoses.length > 0 && (
                  <span
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      gap: 4,
                      padding: "3px 10px",
                      borderRadius: 6,
                      fontSize: 11,
                      fontWeight: 600,
                      background: C.emerald50,
                      color: C.emerald600,
                      border: `1px solid ${C.emerald100}`,
                    }}
                  >
                    {diagnoses.length} dx{hccFromAnalysis > 0 ? ` / ${hccFromAnalysis} HCC` : ""}
                  </span>
                )}
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    analyzeMutation.mutate(enc.encounter_id);
                  }}
                  disabled={analyzeMutation.isPending || !hasNotes}
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 4,
                    padding: "6px 14px",
                    borderRadius: 6,
                    border: `1px solid ${C.slate200}`,
                    background: C.white,
                    color: !hasNotes ? C.slate400 : C.blue600,
                    fontSize: 12,
                    fontWeight: 600,
                    cursor:
                      analyzeMutation.isPending || !hasNotes
                        ? "not-allowed"
                        : "pointer",
                    opacity:
                      analyzeMutation.isPending || !hasNotes ? 0.5 : 1,
                  }}
                >
                  {analyzeMutation.isPending &&
                  analyzeMutation.variables === enc.encounter_id ? (
                    <Spinner size={12} />
                  ) : null}
                  Analyze
                </button>
                <svg
                  width="16"
                  height="16"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke={C.slate400}
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  style={{
                    transform: isExpanded
                      ? "rotate(180deg)"
                      : "rotate(0)",
                    transition: "transform 0.2s",
                  }}
                >
                  <polyline points="6 9 12 15 18 9" />
                </svg>
              </div>
            </div>

            {/* Expanded content */}
            {isExpanded && (
              <div
                style={{
                  padding: "16px 20px",
                  borderTop: `1px solid ${C.slate200}`,
                  background: C.slate100 + "80",
                }}
              >
                {!hasNotes ? (
                  <div
                    style={{
                      textAlign: "center",
                      padding: "24px 0",
                      color: C.slate400,
                      fontSize: 13,
                    }}
                  >
                    No clinical notes available for this encounter
                  </div>
                ) : diagnoses.length > 0 ? (
                  <div>
                    {/* AI Analysis info banner */}
                    <div style={{
                      display: "flex", alignItems: "center", gap: 10,
                      padding: "10px 14px", marginBottom: 12,
                      background: "linear-gradient(135deg, rgba(59,130,246,0.06), rgba(16,185,129,0.06))",
                      border: `1px solid ${C.blue100}`, borderRadius: 8,
                      fontSize: 12, color: C.slate600, lineHeight: 1.5,
                    }}>
                      <span style={{ fontSize: 16 }}>🤖</span>
                      <div>
                        <strong style={{ color: C.slate800 }}>AI Analysis</strong> extracted <strong>{diagnoses.length}</strong> diagnoses
                        {hccFromAnalysis > 0 && <> including <strong style={{ color: C.blue600 }}>{hccFromAnalysis} HCC-carrying codes</strong></>} from
                        this encounter&apos;s SOAP notes. These codes are <strong>not yet in billing</strong> — review and accept to update claims.
                      </div>
                    </div>
                    {/* LLM Input Data — collapsible */}
                    {(() => {
                      const llmInput = analysis?.pipeline?.llm_input || (() => {
                        // Reconstruct from available analysis data for older analyses
                        const meta = analysis?._meta || {};
                        const pipeline = analysis?.pipeline || {};
                        const toolCalls = pipeline?.tool_calls || [];
                        const icdCodes = diagnoses.map((d: any) => d.icd10).filter(Boolean);
                        const hccLookups = toolCalls.filter((t: any) => t.function === "lookup_hcc");
                        const medChecks = toolCalls.filter((t: any) => t.function === "check_medication_gaps");
                        return {
                          model: meta.pipeline_version === "skill_v1" ? "ai-engine-v1" : "unknown",
                          patient_age: null,
                          patient_sex: null,
                          clinical_note_chars: pipeline.note_chars_submitted || pipeline.note_chars_original || 0,
                          temperature: 0.0,
                          medications: medChecks.map((t: any) => t.args?.medication).filter(Boolean),
                          existing_hccs: [],
                          problem_list: [],
                          recapture_gaps: [],
                          latest_vitals: {},
                          med_diagnoses: [],
                          clinical_note_preview: null,
                          _reconstructed: true,
                          tool_calls_summary: {
                            total: toolCalls.length,
                            turns: meta.turns || 0,
                            total_time: meta.total_time_seconds || 0,
                            icd_validated: toolCalls.filter((t: any) => t.function === "validate_icd10").length,
                            hcc_lookups: hccLookups.length,
                            med_checks: medChecks.length,
                            raf_calculated: toolCalls.filter((t: any) => t.function === "calculate_raf_score").length,
                          },
                          extracted_icd_codes: icdCodes,
                        };
                      })();
                      return <LLMInputPanel llmInput={llmInput} />;
                    })()}
                    <div
                      style={{
                        display: "flex", alignItems: "center", justifyContent: "space-between",
                        marginBottom: 10,
                      }}
                    >
                      <div style={{
                        fontSize: 12, fontWeight: 600, color: C.slate500,
                        textTransform: "uppercase", letterSpacing: "0.05em",
                      }}>
                        AI-Extracted Diagnoses
                      </div>
                      <span style={{
                        display: "inline-flex", alignItems: "center", gap: 4,
                        padding: "3px 10px", borderRadius: 999, fontSize: 10, fontWeight: 700,
                        background: C.emerald50, color: C.emerald600, border: `1px solid ${C.emerald100}`,
                        textTransform: "uppercase", letterSpacing: "0.03em",
                      }}>
                        Source: AI Analysis
                      </span>
                    </div>
                    <div
                      style={{
                        display: "grid",
                        gridTemplateColumns:
                          "1fr 100px 80px 100px 80px",
                        padding: "8px 16px",
                        background: C.white,
                        borderRadius: "8px 8px 0 0",
                        border: `1px solid ${C.slate200}`,
                        borderBottom: "none",
                        gap: 8,
                      }}
                    >
                      {[
                        "Diagnosis",
                        "ICD-10",
                        "HCC",
                        "Confidence",
                        "MEAT",
                      ].map((h) => (
                        <span
                          key={h}
                          style={{
                            fontSize: 10,
                            fontWeight: 600,
                            textTransform: "uppercase",
                            letterSpacing: "0.05em",
                            color: C.slate400,
                          }}
                        >
                          {h}
                        </span>
                      ))}
                    </div>
                    {diagnoses.map((dx: AIDiagnosis, i: number) => {
                      const hcc =
                        dx.hcc_code ||
                        dx.hcc ||
                        dx.hcc_mapping?.hcc_code;
                      const confidence =
                        dx.confidence_score ?? dx.confidence ?? 0;
                      return (
                        <div
                          key={dx.icd10 || dx.icd10_code || `dx-${i}`}
                          style={{
                            display: "grid",
                            gridTemplateColumns:
                              "1fr 100px 80px 100px 80px",
                            padding: "10px 16px",
                            background: C.white,
                            border: `1px solid ${C.slate200}`,
                            borderTop: "none",
                            borderRadius:
                              i === diagnoses.length - 1
                                ? "0 0 8px 8px"
                                : 0,
                            gap: 8,
                          }}
                        >
                          <span
                            style={{
                              fontSize: 13,
                              fontWeight: 500,
                              color: C.slate800,
                            }}
                          >
                            {dx.condition ||
                              dx.diagnosis ||
                              dx.description ||
                              "\u2014"}
                          </span>
                          <span>
                            <span
                              style={{
                                display: "inline-block",
                                padding: "2px 6px",
                                borderRadius: 4,
                                fontSize: 11,
                                fontWeight: 600,
                                fontFamily: "monospace",
                                background: C.slate100,
                                color: C.slate700,
                                border: `1px solid ${C.slate200}`,
                              }}
                            >
                              {dx.icd10_code ||
                                dx.code ||
                                "\u2014"}
                            </span>
                          </span>
                          <span>
                            {hcc && (
                              <span
                                style={{
                                  display: "inline-block",
                                  padding: "2px 6px",
                                  borderRadius: 4,
                                  fontSize: 11,
                                  fontWeight: 600,
                                  fontFamily: "monospace",
                                  background: C.blue50,
                                  color: C.blue600,
                                  border: `1px solid ${C.blue100}`,
                                }}
                              >
                                {hcc}
                              </span>
                            )}
                          </span>
                          <span>
                            <ConfidencePill value={confidence} />
                          </span>
                          <span>
                            <MeatDots evidence={dx.meat_evidence || dx.meat} />
                          </span>
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <div
                    style={{
                      textAlign: "center",
                      padding: "24px 0",
                      color: C.slate500,
                      fontSize: 13,
                    }}
                  >
                    <strong>Not analyzed yet.</strong> Click &ldquo;Analyze&rdquo; or &ldquo;Analyze All Encounters&rdquo; to run AI extraction on this encounter&apos;s SOAP notes. The AI will identify ICD-10 codes and HCC opportunities from the clinical documentation.
                  </div>
                )}

                {/* Show notes if present */}
                {enc.notes && (
                  <div
                    style={{
                      marginTop: 12,
                      padding: 16,
                      background: C.white,
                      borderRadius: 8,
                      border: `1px solid ${C.slate200}`,
                    }}
                  >
                    <div
                      style={{
                        fontSize: 11,
                        fontWeight: 600,
                        color: C.slate400,
                        marginBottom: 6,
                        textTransform: "uppercase",
                        letterSpacing: "0.05em",
                      }}
                    >
                      Clinical Notes
                    </div>
                    <div
                      style={{
                        fontSize: 13,
                        color: C.slate700,
                        whiteSpace: "pre-wrap",
                        lineHeight: 1.6,
                      }}
                    >
                      {enc.notes}
                    </div>
                  </div>
                )}
              </div>
            )}
          </Card>
        );
      })}
    </div>
  );
}

// ===========================================================================
// REVIEW QUEUE (SUSPECTS) TAB
// ===========================================================================
function SuspectsTab({
  suspects,
  suspectsLoading,
  acceptMutation,
  dismissMutation,
}: {
  suspects: PatientSuspectsResponse | undefined;
  suspectsLoading: boolean;
  acceptMutation: { mutate: (id: number) => void; isPending: boolean };
  dismissMutation: { mutate: (id: number) => void; isPending: boolean };
}) {
  if (suspectsLoading) {
    return <SectionLoader label="Loading suspect conditions..." />;
  }

  const suspectList: SuspectItem[] = (suspects?.suspects ?? []) as SuspectItem[];
  if (!suspectList.length) {
    return (
      <Card>
        <EmptyState
          title="No open suspects"
          description="Analyze encounters to identify potential conditions"
          icon={
            <svg
              width="24"
              height="24"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <circle cx="11" cy="11" r="8" />
              <line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
          }
        />
      </Card>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      {suspectList.map((s: SuspectItem, idx: number) => {
        const confidence = s.confidence_score ?? s.confidence ?? 0;
        const confidenceColor = confidence >= 0.8 ? C.emerald600 : confidence >= 0.5 ? C.amber600 : C.red600;
        return (
          <Card key={s.id} className={`hover-lift animate-slide-up stagger-${Math.min(idx + 1, 6)}`} style={{ padding: 20, borderLeft: `4px solid ${confidenceColor}` }}>
            <div
              style={{
                display: "flex",
                alignItems: "flex-start",
                justifyContent: "space-between",
                gap: 16,
              }}
            >
              <div style={{ flex: 1, minWidth: 0 }}>
                {/* Title + badges */}
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                    flexWrap: "wrap",
                  }}
                >
                  <span
                    style={{
                      fontSize: 14,
                      fontWeight: 600,
                      color: C.slate800,
                    }}
                  >
                    {s.condition || s.suspect_condition || "\u2014"}
                  </span>
                  {s.icd10_code && (
                    <span
                      style={{
                        display: "inline-block",
                        padding: "2px 8px",
                        borderRadius: 4,
                        fontSize: 11,
                        fontWeight: 600,
                        fontFamily: "monospace",
                        background: C.slate100,
                        color: C.slate700,
                        border: `1px solid ${C.slate200}`,
                      }}
                    >
                      {s.icd10_code}
                    </span>
                  )}
                  {s.hcc_code && (
                    <span
                      style={{
                        display: "inline-block",
                        padding: "2px 8px",
                        borderRadius: 4,
                        fontSize: 11,
                        fontWeight: 600,
                        fontFamily: "monospace",
                        background: C.blue50,
                        color: C.blue600,
                        border: `1px solid ${C.blue100}`,
                      }}
                    >
                      {s.hcc_code}
                    </span>
                  )}
                </div>

                {/* Confidence */}
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                    marginTop: 10,
                  }}
                >
                  <ConfidencePill value={confidence} />
                </div>

                {/* Evidence */}
                {(s.evidence || s.rationale) && (
                  <div
                    style={{
                      fontSize: 13,
                      color: C.slate500,
                      marginTop: 8,
                      lineHeight: 1.5,
                      display: "-webkit-box",
                      WebkitLineClamp: 2,
                      WebkitBoxOrient: "vertical",
                      overflow: "hidden",
                    }}
                  >
                    {s.evidence || s.rationale}
                  </div>
                )}

                {/* MEAT */}
                {s.meat_evidence && (
                  <div style={{ marginTop: 8 }}>
                    <MeatDots evidence={s.meat_evidence || (s as any).meat} />
                  </div>
                )}

                {s.source && (
                  <div
                    style={{
                      fontSize: 11,
                      color: C.slate400,
                      marginTop: 6,
                    }}
                  >
                    Source: {s.source}
                  </div>
                )}
              </div>

              {/* Accept / Dismiss */}
              <div
                style={{
                  display: "flex",
                  flexDirection: "column",
                  gap: 6,
                  flexShrink: 0,
                }}
              >
                <button
                  onClick={() => acceptMutation.mutate(s.id)}
                  disabled={acceptMutation.isPending}
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 6,
                    padding: "8px 16px",
                    borderRadius: 8,
                    border: `1px solid ${C.emerald500}`,
                    background: C.emerald50,
                    color: C.emerald600,
                    fontSize: 12,
                    fontWeight: 600,
                    cursor: acceptMutation.isPending
                      ? "not-allowed"
                      : "pointer",
                    opacity: acceptMutation.isPending ? 0.6 : 1,
                  }}
                >
                  <svg
                    width="14"
                    height="14"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="3"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  >
                    <polyline points="20 6 9 17 4 12" />
                  </svg>
                  Accept
                </button>
                <button
                  onClick={() => dismissMutation.mutate(s.id)}
                  disabled={dismissMutation.isPending}
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 6,
                    padding: "8px 16px",
                    borderRadius: 8,
                    border: `1px solid ${C.red500}`,
                    background: C.red50,
                    color: C.red600,
                    fontSize: 12,
                    fontWeight: 600,
                    cursor: dismissMutation.isPending
                      ? "not-allowed"
                      : "pointer",
                    opacity: dismissMutation.isPending ? 0.6 : 1,
                  }}
                >
                  <svg
                    width="14"
                    height="14"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="3"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  >
                    <line x1="18" y1="6" x2="6" y2="18" />
                    <line x1="6" y1="6" x2="18" y2="18" />
                  </svg>
                  Dismiss
                </button>
              </div>
            </div>
          </Card>
        );
      })}
    </div>
  );
}

// ===========================================================================
// AUDIT TAB
// ===========================================================================
function AuditTab({ audits, auditsLoading, auditMutation, selectedYear }: {
  audits: AuditPackagesResponse | undefined;
  auditsLoading: boolean;
  auditMutation: { mutate: (year?: number) => void; isPending: boolean };
  selectedYear: number;
}) {
  const [auditYear, setAuditYear] = useState(selectedYear);

  useEffect(() => { setAuditYear(selectedYear); }, [selectedYear]);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
      {/* Generate section */}
      <Card className="animate-slide-up stagger-1">
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
          }}
        >
          <div>
            <h3
              style={{
                margin: 0,
                fontSize: 16,
                fontWeight: 700,
                color: C.slate900,
              }}
            >
              Audit Packages
            </h3>
            <p
              style={{
                margin: "4px 0 0",
                fontSize: 13,
                color: C.slate500,
              }}
            >
              Generate and download comprehensive audit documentation.
            </p>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <select
              value={auditYear}
              onChange={(e) => setAuditYear(Number(e.target.value))}
              style={{
                padding: "8px 12px",
                borderRadius: 8,
                border: `1px solid ${C.slate200}`,
                background: C.white,
                fontSize: 13,
                color: C.slate700,
                cursor: "pointer",
              }}
            >
              {[0, 1, 2, 3].map((offset) => {
                const y = new Date().getFullYear() - offset;
                return (
                  <option key={y} value={y}>
                    {y}
                  </option>
                );
              })}
            </select>
            <button
              onClick={() => auditMutation.mutate(auditYear)}
              disabled={auditMutation.isPending}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 6,
                padding: "8px 16px",
                borderRadius: 8,
                border: "none",
                background: C.blue600,
                color: C.white,
                fontSize: 13,
                fontWeight: 600,
                cursor: auditMutation.isPending ? "not-allowed" : "pointer",
                opacity: auditMutation.isPending ? 0.6 : 1,
              }}
            >
              {auditMutation.isPending && <Spinner size={14} />}
              Generate New Audit
            </button>
          </div>
        </div>
      </Card>

      {/* Audit list */}
      <Card noPadding className="animate-slide-up stagger-2">
        {auditsLoading ? (
          <SectionLoader label="Loading audit packages..." />
        ) : !audits?.packages?.length ? (
          <EmptyState
            title="No audit packages generated yet"
            description="Click Generate New Audit to create your first package"
            icon={
              <svg
                width="24"
                height="24"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                <polyline points="14 2 14 8 20 8" />
              </svg>
            }
          />
        ) : (
          <div>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "80px 80px 1fr 100px 100px",
                padding: "8px 20px",
                background: C.slate100,
                borderBottom: `1px solid ${C.slate200}`,
                gap: 16,
              }}
            >
              {["Package", "Year", "Created", "Size", "Actions"].map(
                (h) => (
                  <span
                    key={h}
                    style={{
                      fontSize: 11,
                      fontWeight: 600,
                      textTransform: "uppercase",
                      letterSpacing: "0.05em",
                      color: C.slate400,
                      textAlign: h === "Actions" ? "right" : "left",
                    }}
                  >
                    {h}
                  </span>
                )
              )}
            </div>
            {audits.packages.map((pkg: AuditPackageItem) => (
              <div
                key={pkg.id}
                style={{
                  display: "grid",
                  gridTemplateColumns: "80px 80px 1fr 100px 100px",
                  padding: "12px 20px",
                  borderBottom: `1px solid ${C.slate100}`,
                  gap: 16,
                  transition: "background 0.1s",
                }}
                onMouseEnter={(e) =>
                  (e.currentTarget.style.background = C.slate100)
                }
                onMouseLeave={(e) =>
                  (e.currentTarget.style.background = "transparent")
                }
              >
                <span
                  style={{
                    fontSize: 13,
                    fontFamily: "monospace",
                    fontWeight: 600,
                    color: C.slate800,
                  }}
                >
                  #{pkg.id}
                </span>
                <span style={{ fontSize: 13, color: C.slate600 }}>
                  {pkg.year}
                </span>
                <span style={{ fontSize: 12, color: C.slate500 }}>
                  {formatDate(pkg.created_at)}
                </span>
                <span style={{ fontSize: 12, color: C.slate500 }}>
                  {pkg.file_size_bytes
                    ? `${(pkg.file_size_bytes / 1024).toFixed(1)} KB`
                    : "\u2014"}
                </span>
                <span style={{ textAlign: "right" }}>
                  <button
                    type="button"
                    onClick={() =>
                      downloadAuditPackage(pkg.id).catch((err: any) =>
                        alert(err?.response?.data?.detail || err?.message || "Download failed"),
                      )
                    }
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      gap: 4,
                      fontSize: 12,
                      fontWeight: 600,
                      color: C.blue600,
                      background: "none",
                      border: "none",
                      padding: 0,
                      cursor: "pointer",
                    }}
                  >
                    <svg
                      width="14"
                      height="14"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    >
                      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                      <polyline points="7 10 12 15 17 10" />
                      <line x1="12" y1="15" x2="12" y2="3" />
                    </svg>
                    Download
                  </button>
                </span>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}

// ===========================================================================
// ACTIVITY TAB
// ===========================================================================

type TimelineEventType = "encounter" | "analysis" | "suspect" | "raf" | "audit";

interface TimelineEvent {
  id: string;
  date: string;
  type: TimelineEventType;
  title: string;
  detail?: string;
}

const ACTIVITY_TYPE_META: Record<
  TimelineEventType,
  { color: string; bgColor: string; label: string }
> = {
  encounter: { color: "#2563EB", bgColor: "#DBEAFE", label: "Encounter" },
  analysis:  { color: "#9333EA", bgColor: "#F3E8FF", label: "Analysis" },
  suspect:   { color: "#D97706", bgColor: "#FEF3C7", label: "Suspect" },
  raf:       { color: "#059669", bgColor: "#D1FAE5", label: "RAF" },
  audit:     { color: "#0D9488", bgColor: "#CCFBF1", label: "Audit" },
};

function ActivityDot({ type }: { type: TimelineEventType }) {
  const meta = ACTIVITY_TYPE_META[type];
  return (
    <div
      style={{
        width: 32,
        height: 32,
        borderRadius: "50%",
        background: meta.bgColor,
        border: `2px solid ${meta.color}`,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        flexShrink: 0,
        zIndex: 1,
      }}
    >
      <div
        style={{
          width: 10,
          height: 10,
          borderRadius: "50%",
          background: meta.color,
        }}
      />
    </div>
  );
}

function ActivityTab({
  encounters,
  encountersLoading,
  suspects,
  suspectsLoading,
  rafHistory,
  rafHistoryLoading,
  audits,
  auditsLoading,
}: {
  encounters: PatientEncountersResponse | undefined;
  encountersLoading: boolean;
  suspects: PatientSuspectsResponse | undefined;
  suspectsLoading: boolean;
  rafHistory: RafHistoryResponse | undefined;
  rafHistoryLoading: boolean;
  audits: AuditPackagesResponse | undefined;
  auditsLoading: boolean;
}) {
  const isLoading =
    encountersLoading || suspectsLoading || rafHistoryLoading || auditsLoading;

  // Build unified timeline events
  const events: TimelineEvent[] = [];

  // Encounters
  const encounterList: EncounterItem[] = (encounters?.encounters ?? []) as EncounterItem[];
  for (const enc of encounterList) {
    const reason = enc.reason || "Office Visit";
    const provider =
      enc.provider_fname || enc.provider_lname
        ? `${enc.provider_fname ?? ""} ${enc.provider_lname ?? ""}`.trim()
        : null;
    events.push({
      id: `enc-${enc.encounter_id}`,
      date: enc.date,
      type: "encounter",
      title: reason,
      detail: provider ? `Provider: ${provider}` : undefined,
    });

    // If this encounter has been analyzed
    if (enc.analyzed_at || enc.has_analysis) {
      events.push({
        id: `analysis-${enc.encounter_id}`,
        date: enc.analyzed_at ?? enc.date,
        type: "analysis",
        title: "AI Analysis completed",
        detail: `Encounter #${enc.encounter_id}`,
      });
    }
  }

  // Suspect conditions
  const suspectList: SuspectItem[] = (suspects?.suspects ?? []) as SuspectItem[];
  for (const s of suspectList) {
    const dateField =
      s.created_at ?? s.identified_at ?? s.updated_at ?? null;
    if (dateField) {
      events.push({
        id: `suspect-${s.id ?? s.suspect_id}`,
        date: dateField,
        type: "suspect",
        title: `Suspect condition identified: ${s.condition ?? s.hcc_description ?? "Unknown"}`,
        detail: s.icd10_code ? `ICD-10: ${s.icd10_code}` : undefined,
      });
    }
  }

  // RAF history scores
  const rafScores: ScoreHistoryEntry[] = (Array.isArray(rafHistory)
    ? rafHistory
    : rafHistory?.scores ?? rafHistory?.history ?? []) as ScoreHistoryEntry[];
  for (const r of rafScores) {
    const dateField = r.calculated_at ?? r.created_at ?? null;
    const score = r.raf_score ?? r.total_score ?? r.score ?? null;
    if (dateField && score !== null) {
      events.push({
        id: `raf-${r.id ?? dateField}-${rafScores.indexOf(r)}`,
        date: dateField,
        type: "raf",
        title: `RAF score calculated: ${Number(score).toFixed(3)}`,
        detail: r.model ? `Model: ${r.model}` : undefined,
      });
    }
  }

  // Audit packages
  const auditList: AuditPackageItem[] = audits?.packages ?? [];
  for (const a of auditList) {
    events.push({
      id: `audit-${a.id}`,
      date: a.created_at,
      type: "audit",
      title: "Audit package generated",
      detail: a.year ? `Year: ${a.year}` : undefined,
    });
  }

  // Sort descending by date (most recent first)
  events.sort((a, b) => {
    const da = new Date(a.date).getTime();
    const db = new Date(b.date).getTime();
    return db - da;
  });

  return (
    <div style={{ maxWidth: 800 }}>
      <Card className="animate-slide-up stagger-1">
        <div style={{ marginBottom: 20 }}>
          <h3
            style={{
              margin: 0,
              fontSize: 16,
              fontWeight: 700,
              color: C.slate900,
            }}
          >
            Patient Activity Timeline
          </h3>
          <p
            style={{
              margin: "4px 0 0",
              fontSize: 13,
              color: C.slate500,
            }}
          >
            Chronological history of all patient events
          </p>
        </div>

        {/* Legend */}
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            gap: 12,
            marginBottom: 24,
            padding: "12px 16px",
            background: C.slate100,
            borderRadius: 8,
          }}
        >
          {(
            Object.entries(ACTIVITY_TYPE_META) as [
              TimelineEventType,
              (typeof ACTIVITY_TYPE_META)[TimelineEventType],
            ][]
          ).map(([type, meta]) => (
            <div
              key={type}
              style={{ display: "flex", alignItems: "center", gap: 6 }}
            >
              <div
                style={{
                  width: 10,
                  height: 10,
                  borderRadius: "50%",
                  background: meta.color,
                }}
              />
              <span
                style={{ fontSize: 12, color: C.slate600, fontWeight: 500 }}
              >
                {meta.label}
              </span>
            </div>
          ))}
        </div>

        {/* Timeline body */}
        {isLoading ? (
          <SectionLoader label="Loading activity..." />
        ) : events.length === 0 ? (
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              justifyContent: "center",
              padding: "48px 0",
              color: C.slate400,
              gap: 12,
            }}
          >
            <svg
              width="40"
              height="40"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <circle cx="12" cy="12" r="10" />
              <line x1="12" y1="8" x2="12" y2="12" />
              <line x1="12" y1="16" x2="12.01" y2="16" />
            </svg>
            <span style={{ fontSize: 14, fontWeight: 500 }}>
              No activity found
            </span>
            <span style={{ fontSize: 13, color: C.slate400 }}>
              Events will appear here as encounters, analyses, and RAF
              calculations are recorded.
            </span>
          </div>
        ) : (
          <div style={{ position: "relative" }}>
            {/* Vertical connector line */}
            <div
              style={{
                position: "absolute",
                left: 15,
                top: 0,
                bottom: 0,
                width: 2,
                background: C.slate200,
                zIndex: 0,
              }}
            />

            <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
              {events.map((event, idx) => {
                const meta = ACTIVITY_TYPE_META[event.type];
                const isLast = idx === events.length - 1;
                return (
                  <div
                    key={event.id}
                    style={{
                      display: "flex",
                      gap: 16,
                      alignItems: "flex-start",
                      paddingBottom: isLast ? 0 : 20,
                    }}
                  >
                    <ActivityDot type={event.type} />

                    <div style={{ flex: 1, paddingTop: 4, minWidth: 0 }}>
                      <div
                        style={{
                          display: "flex",
                          alignItems: "center",
                          gap: 8,
                          marginBottom: 2,
                          flexWrap: "wrap",
                        }}
                      >
                        <span
                          style={{
                            fontSize: 13,
                            fontWeight: 600,
                            color: C.slate900,
                          }}
                        >
                          {event.title}
                        </span>
                        <span
                          style={{
                            display: "inline-flex",
                            alignItems: "center",
                            padding: "1px 8px",
                            borderRadius: 12,
                            fontSize: 11,
                            fontWeight: 600,
                            background: meta.bgColor,
                            color: meta.color,
                          }}
                        >
                          {meta.label}
                        </span>
                      </div>

                      <div
                        style={{
                          display: "flex",
                          gap: 12,
                          alignItems: "center",
                          flexWrap: "wrap",
                        }}
                      >
                        <span style={{ fontSize: 12, color: C.slate400 }}>
                          {formatDate(event.date)}
                        </span>
                        {event.detail && (
                          <span style={{ fontSize: 12, color: C.slate500 }}>
                            {event.detail}
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </Card>
    </div>
  );
}

// ===========================================================================
// DOCUMENTS & REPORTS TAB
// ===========================================================================

const REPORT_TYPES = [
  "Lab Report",
  "Medical Report",
  "Wellness Report",
  "Care Report",
  "Discharge Summary",
  "Radiology",
  "Custom Report",
];

const DOC_STATUS_STYLES: Record<string, { bg: string; color: string; label: string }> = {
  analyzed: { bg: C.emerald100, color: C.emerald600, label: "Analyzed" },
  processing: { bg: C.blue100, color: C.blue600, label: "Processing" },
  pending: { bg: C.amber100, color: C.amber600, label: "Pending" },
  failed: { bg: C.red100, color: C.red600, label: "Failed" },
};

function DocumentsTab({
  pid,
  documents,
  documentsLoading,
  rafScore,
  patientName,
  selectedYear,
}: {
  pid: string;
  documents: DocumentsResponse | undefined;
  documentsLoading: boolean;
  rafScore: number | null;
  patientName: string;
  selectedYear: number;
}) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [reportType, setReportType] = useState("Medical Report");
  const [encounterDate, setEncounterDate] = useState("");
  const [dragOver, setDragOver] = useState(false);
  const [expandedAnalysis, setExpandedAnalysis] = useState<number | null>(null);
  const [expandedDraft, setExpandedDraft] = useState<number | null>(null);
  const [analysisData, setAnalysisData] = useState<Record<number, DocumentAnalysisData>>({});
  const [draftData, setDraftData] = useState<Record<number, DraftRAFData>>({});

  const uploadMutation = useMutation({
    mutationFn: async () => {
      if (!selectedFile) throw new Error("No file selected");
      return uploadPatientDocument(pid, selectedFile, reportType, encounterDate || undefined);
    },
    onSuccess: () => {
      toast.success("Upload Complete", "Document has been uploaded and queued for analysis.");
      queryClient.invalidateQueries({ queryKey: ["patient-documents", pid] });
      setSelectedFile(null);
      setEncounterDate("");
      if (fileInputRef.current) fileInputRef.current.value = "";
    },
    onError: () => toast.error("Upload Failed", "Could not upload the document. Please try again."),
  });

  const analyzeMut = useMutation({
    mutationFn: (docId: number) => analyzeDocument(docId),
    onSuccess: () => {
      toast.success("Analysis Started", "Document is being analyzed.");
      queryClient.invalidateQueries({ queryKey: ["patient-documents", pid] });
    },
    onError: () => toast.error("Error", "Failed to start analysis."),
  });

  const confirmDxMut = useMutation({
    mutationFn: ({ docId, dxId }: { docId: number; dxId: number }) =>
      confirmDocumentDiagnosis(docId, dxId),
    onSuccess: (_data, vars) => {
      toast.success("Confirmed", "Diagnosis has been confirmed.");
      fetchAnalysis(vars.docId);
    },
    onError: () => toast.error("Error", "Failed to confirm diagnosis."),
  });

  const rejectDxMut = useMutation({
    mutationFn: ({ docId, dxId }: { docId: number; dxId: number }) =>
      rejectDocumentDiagnosis(docId, dxId),
    onSuccess: (_data, vars) => {
      toast.success("Rejected", "Diagnosis has been rejected.");
      fetchAnalysis(vars.docId);
    },
    onError: () => toast.error("Error", "Failed to reject diagnosis."),
  });

  async function fetchAnalysis(docId: number) {
    try {
      const [analysis, diagnoses] = await Promise.all([
        getDocumentAnalysis(docId),
        getDocumentDiagnoses(docId),
      ]);
      setAnalysisData((prev) => ({ ...prev, [docId]: { ...analysis, diagnoses } }));
    } catch {
      toast.error("Error", "Failed to load analysis.");
    }
  }

  async function fetchDraftRAF(docId: number) {
    try {
      const draft = await getDocumentDraftRAF(docId);
      setDraftData((prev) => ({ ...prev, [docId]: draft }));
    } catch {
      toast.error("Error", "Failed to calculate draft RAF score.");
    }
  }

  function handleViewAnalysis(docId: number) {
    if (expandedAnalysis === docId) {
      setExpandedAnalysis(null);
      return;
    }
    setExpandedAnalysis(docId);
    setExpandedDraft(null);
    if (!analysisData[docId]) fetchAnalysis(docId);
  }

  function handleDraftRAF(docId: number) {
    if (expandedDraft === docId) {
      setExpandedDraft(null);
      return;
    }
    setExpandedDraft(docId);
    setExpandedAnalysis(null);
    if (!draftData[docId]) fetchDraftRAF(docId);
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files?.[0];
    if (file) setSelectedFile(file);
  }

  const docList = useMemo(() => {
    const all = documents?.documents ?? [];
    return all.filter((d: any) => {
      const dateStr = d.upload_date || d.created_at || d.encounter_date;
      if (!dateStr) return true;
      return new Date(dateStr).getFullYear() === selectedYear;
    });
  }, [documents, selectedYear]);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
      {/* =============== UPLOAD SECTION =============== */}
      <Card className="hover-lift">
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 20 }}>
          <div
            style={{
              width: 36,
              height: 36,
              borderRadius: 10,
              background: `linear-gradient(135deg, ${C.blue600}, ${C.emerald600})`,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            <FileUp size={18} color="#fff" />
          </div>
          <div>
            <h3 style={{ fontSize: 16, fontWeight: 700, color: C.slate900, margin: 0 }}>
              Upload Document
            </h3>
            <p style={{ fontSize: 12, color: C.slate500, margin: 0 }}>
              Upload lab reports, medical records, or clinical documents for AI analysis
            </p>
          </div>
        </div>

        {/* Drop zone */}
        <div
          onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
          onDragLeave={() => setDragOver(false)}
          onDrop={handleDrop}
          onClick={() => fileInputRef.current?.click()}
          style={{
            border: `2px dashed ${dragOver ? C.blue600 : C.slate300}`,
            borderRadius: 12,
            padding: selectedFile ? "16px 24px" : "40px 24px",
            textAlign: "center",
            cursor: "pointer",
            background: dragOver ? C.blue50 : C.slate100,
            transition: "all 0.2s ease",
            marginBottom: 16,
          }}
        >
          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf,.png,.jpg,.jpeg,.doc,.docx"
            style={{ display: "none" }}
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) setSelectedFile(f);
            }}
          />
          {selectedFile ? (
            <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 12 }}>
              <Paperclip size={18} color={C.blue600} />
              <span style={{ fontSize: 14, fontWeight: 600, color: C.slate800 }}>
                {selectedFile.name}
              </span>
              <span style={{ fontSize: 12, color: C.slate500 }}>
                ({(selectedFile.size / 1024).toFixed(1)} KB)
              </span>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  setSelectedFile(null);
                  if (fileInputRef.current) fileInputRef.current.value = "";
                }}
                style={{
                  background: "none",
                  border: "none",
                  cursor: "pointer",
                  color: C.red500,
                  padding: 4,
                }}
              >
                <XCircle size={16} />
              </button>
            </div>
          ) : (
            <>
              <Upload size={32} color={C.slate400} style={{ marginBottom: 8 }} />
              <p style={{ fontSize: 14, fontWeight: 600, color: C.slate700, margin: "4px 0" }}>
                Drop a file here or click to browse
              </p>
              <p style={{ fontSize: 12, color: C.slate400, margin: 0 }}>
                PDF, PNG, JPG, DOC up to 25 MB
              </p>
            </>
          )}
        </div>

        {/* Report type pills */}
        <div style={{ marginBottom: 16 }}>
          <label style={{ fontSize: 12, fontWeight: 600, color: C.slate600, marginBottom: 8, display: "block" }}>
            Report Type
          </label>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
            {REPORT_TYPES.map((rt) => (
              <button
                key={rt}
                onClick={() => setReportType(rt)}
                className="btn-press"
                style={{
                  padding: "6px 14px",
                  borderRadius: 20,
                  border: `1.5px solid ${reportType === rt ? C.blue600 : C.slate300}`,
                  background: reportType === rt ? C.blue50 : C.white,
                  color: reportType === rt ? C.blue600 : C.slate600,
                  fontSize: 12,
                  fontWeight: 600,
                  cursor: "pointer",
                  transition: "all 0.15s ease",
                }}
              >
                {rt}
              </button>
            ))}
          </div>
        </div>

        {/* Encounter date + Upload button */}
        <div style={{ display: "flex", alignItems: "flex-end", gap: 12, flexWrap: "wrap" }}>
          <div>
            <label style={{ fontSize: 12, fontWeight: 600, color: C.slate600, marginBottom: 4, display: "block" }}>
              Encounter Date (optional)
            </label>
            <input
              type="date"
              value={encounterDate}
              onChange={(e) => setEncounterDate(e.target.value)}
              style={{
                padding: "8px 12px",
                borderRadius: 8,
                border: `1px solid ${C.slate300}`,
                fontSize: 13,
                color: C.slate800,
                background: C.white,
                outline: "none",
              }}
            />
          </div>
          <button
            onClick={() => uploadMutation.mutate()}
            disabled={!selectedFile || uploadMutation.isPending}
            className="btn-press"
            style={{
              padding: "9px 24px",
              borderRadius: 10,
              border: "none",
              background: !selectedFile
                ? C.slate300
                : `linear-gradient(135deg, ${C.blue600}, ${C.emerald600})`,
              color: C.white,
              fontSize: 13,
              fontWeight: 700,
              cursor: selectedFile ? "pointer" : "not-allowed",
              display: "flex",
              alignItems: "center",
              gap: 8,
              transition: "all 0.2s ease",
              opacity: uploadMutation.isPending ? 0.7 : 1,
            }}
          >
            {uploadMutation.isPending ? (
              <>
                <Spinner size={14} /> Uploading...
              </>
            ) : (
              <>
                <FileUp size={14} /> Upload & Analyze
              </>
            )}
          </button>
        </div>
      </Card>

      {/* =============== DOCUMENTS LIST =============== */}
      <div>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 16 }}>
          <ClipboardList size={18} color={C.blue600} />
          <h3 style={{ fontSize: 16, fontWeight: 700, color: C.slate900, margin: 0 }}>
            Uploaded Documents
          </h3>
          <span
            className="tabular-nums"
            style={{
              fontSize: 11,
              fontWeight: 700,
              background: C.blue100,
              color: C.blue600,
              padding: "2px 8px",
              borderRadius: 10,
            }}
          >
            {docList.length}
          </span>
        </div>

        {documentsLoading ? (
          <SectionLoader label="Loading documents..." />
        ) : docList.length === 0 ? (
          <Card>
            <div style={{ textAlign: "center", padding: "48px 24px" }}>
              <FileText size={40} color={C.slate300} style={{ marginBottom: 12 }} />
              <p style={{ fontSize: 15, fontWeight: 600, color: C.slate500, margin: "0 0 4px" }}>
                No documents yet
              </p>
              <p style={{ fontSize: 13, color: C.slate400, margin: 0 }}>
                Upload a document above to get started with AI-powered analysis
              </p>
            </div>
          </Card>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            {docList.map((doc, idx: number) => {
              const status = DOC_STATUS_STYLES[doc.status] ?? DOC_STATUS_STYLES.pending;
              const docId = doc.id ?? doc.document_id;
              const isAnalysisOpen = expandedAnalysis === docId;
              const isDraftOpen = expandedDraft === docId;
              const aData = analysisData[docId];
              const dData = draftData[docId];

              return (
                <div
                  key={docId}
                  className={`animate-fade-in stagger-${Math.min(idx + 1, 5)}`}
                  style={{ display: "flex", flexDirection: "column", gap: 0 }}
                >
                  <Card className="hover-lift" style={{ transition: "all 0.2s ease" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
                      <div
                        style={{
                          width: 40,
                          height: 40,
                          borderRadius: 10,
                          background: `${C.blue600}15`,
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "center",
                          flexShrink: 0,
                        }}
                      >
                        <FileText size={18} color={C.blue600} />
                      </div>

                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                          <span style={{ fontSize: 14, fontWeight: 700, color: C.slate900 }}>
                            {doc.filename || doc.file_name || "Document"}
                          </span>
                          <span
                            style={{
                              padding: "2px 8px",
                              borderRadius: 10,
                              fontSize: 10,
                              fontWeight: 700,
                              background: status.bg,
                              color: status.color,
                            }}
                          >
                            {status.label}
                          </span>
                        </div>
                        <div style={{ display: "flex", gap: 16, marginTop: 4, flexWrap: "wrap" }}>
                          <span style={{ fontSize: 12, color: C.slate400 }}>
                            {doc.report_type || reportType}
                          </span>
                          <span style={{ fontSize: 12, color: C.slate400 }}>
                            {formatDate(doc.created_at || doc.upload_date)}
                          </span>
                          {doc.diagnosis_count != null && doc.diagnosis_count > 0 && (
                            <span style={{ fontSize: 12, color: C.emerald600, fontWeight: 600 }}>
                              {doc.diagnosis_count} diagnoses
                            </span>
                          )}
                        </div>
                      </div>

                      <div style={{ display: "flex", gap: 6, flexShrink: 0 }}>
                        {/* View original file */}
                        <button
                          onClick={() => {
                            const apiBase = process.env.NEXT_PUBLIC_API_URL || "";
                            const token = getAccessToken() || "";
                            window.open(`${apiBase}/api/documents/${docId}/view?token=${encodeURIComponent(token)}`, "_blank");
                          }}
                          className="btn-press"
                          style={{
                            padding: "6px 12px",
                            borderRadius: 8,
                            border: `1px solid ${C.slate300}`,
                            background: C.white,
                            color: C.slate600,
                            fontSize: 12,
                            fontWeight: 600,
                            cursor: "pointer",
                            display: "flex",
                            alignItems: "center",
                            gap: 4,
                            transition: "all 0.15s",
                          }}
                        >
                          <FileText size={13} /> View
                        </button>
                        {doc.status === "analyzed" && (
                          <>
                            <button
                              onClick={() => handleViewAnalysis(docId)}
                              className="btn-press"
                              style={{
                                padding: "6px 12px",
                                borderRadius: 8,
                                border: `1px solid ${isAnalysisOpen ? C.blue600 : C.slate300}`,
                                background: isAnalysisOpen ? C.blue50 : C.white,
                                color: isAnalysisOpen ? C.blue600 : C.slate600,
                                fontSize: 12,
                                fontWeight: 600,
                                cursor: "pointer",
                                display: "flex",
                                alignItems: "center",
                                gap: 4,
                                transition: "all 0.15s",
                              }}
                            >
                              <Eye size={13} /> Analysis
                            </button>
                            <button
                              onClick={() => handleDraftRAF(docId)}
                              className="btn-press"
                              style={{
                                padding: "6px 12px",
                                borderRadius: 8,
                                border: `1px solid ${isDraftOpen ? C.emerald600 : C.slate300}`,
                                background: isDraftOpen ? C.emerald50 : C.white,
                                color: isDraftOpen ? C.emerald600 : C.slate600,
                                fontSize: 12,
                                fontWeight: 600,
                                cursor: "pointer",
                                display: "flex",
                                alignItems: "center",
                                gap: 4,
                                transition: "all 0.15s",
                              }}
                            >
                              <TrendingUp size={13} /> Draft Score
                            </button>
                          </>
                        )}
                        {(doc.status === "pending" || doc.status === "failed") && (
                          <button
                            onClick={() => analyzeMut.mutate(docId)}
                            disabled={analyzeMut.isPending}
                            className="btn-press"
                            style={{
                              padding: "6px 12px",
                              borderRadius: 8,
                              border: "none",
                              background: `linear-gradient(135deg, ${C.blue600}, ${C.emerald600})`,
                              color: C.white,
                              fontSize: 12,
                              fontWeight: 600,
                              cursor: "pointer",
                              display: "flex",
                              alignItems: "center",
                              gap: 4,
                            }}
                          >
                            <Brain size={13} /> Analyze
                          </button>
                        )}
                      </div>
                    </div>
                  </Card>

                  {/* ===== ANALYSIS PANEL ===== */}
                  {isAnalysisOpen && (
                    <div className="animate-slide-up" style={{ marginTop: -1 }}>
                      <Card
                        className="card-glow-blue"
                        style={{
                          borderTopLeftRadius: 0,
                          borderTopRightRadius: 0,
                          borderTop: `2px solid ${C.blue600}`,
                        }}
                      >
                        {!aData ? (
                          <SectionLoader label="Loading analysis..." />
                        ) : (
                          <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
                            {aData.summary && (
                              <div>
                                <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 8 }}>
                                  <Stethoscope size={14} color={C.blue600} />
                                  <span style={{ fontSize: 13, fontWeight: 700, color: C.slate800 }}>
                                    Clinical Summary
                                  </span>
                                </div>
                                <p style={{ fontSize: 13, color: C.slate600, lineHeight: 1.6, margin: 0, background: C.slate100, padding: 12, borderRadius: 8 }}>
                                  {aData.summary}
                                </p>
                              </div>
                            )}

                            <div>
                              <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 10 }}>
                                <ClipboardList size={14} color={C.emerald600} />
                                <span style={{ fontSize: 13, fontWeight: 700, color: C.slate800 }}>
                                  Extracted Diagnoses
                                </span>
                                <span className="tabular-nums" style={{ fontSize: 11, fontWeight: 700, background: C.emerald100, color: C.emerald600, padding: "1px 6px", borderRadius: 8 }}>
                                  {aData.diagnoses?.length ?? 0}
                                </span>
                              </div>

                              {(!aData.diagnoses || aData.diagnoses.length === 0) ? (
                                <p style={{ fontSize: 13, color: C.slate400, fontStyle: "italic" }}>No diagnoses extracted.</p>
                              ) : (
                                <div style={{ overflowX: "auto" }}>
                                  <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
                                    <thead>
                                      <tr style={{ borderBottom: `2px solid ${C.slate200}` }}>
                                        {["ICD-10", "Description", "HCC", "RAF Weight", "Confidence", "MEAT", "Actions"].map((h) => (
                                          <th
                                            key={h}
                                            style={{
                                              textAlign: "left",
                                              padding: "8px 10px",
                                              fontSize: 11,
                                              fontWeight: 700,
                                              color: C.slate500,
                                              textTransform: "uppercase",
                                              letterSpacing: "0.5px",
                                            }}
                                          >
                                            {h}
                                          </th>
                                        ))}
                                      </tr>
                                    </thead>
                                    <tbody>
                                      {aData.diagnoses.map((dx, i: number) => (
                                        <tr
                                          key={dx.id ?? i}
                                          style={{
                                            borderBottom: `1px solid ${C.slate100}`,
                                            background: dx.status === "confirmed" ? `${C.emerald600}08` : dx.status === "rejected" ? `${C.red600}08` : "transparent",
                                          }}
                                        >
                                          <td style={{ padding: "10px", fontWeight: 700, color: C.blue600, fontFamily: "monospace" }}>
                                            {dx.icd10_code || dx.icd_code || "--"}
                                          </td>
                                          <td style={{ padding: "10px", color: C.slate700, maxWidth: 240 }}>
                                            {dx.description || dx.diagnosis || "--"}
                                          </td>
                                          <td style={{ padding: "10px" }}>
                                            {dx.hcc_code ? (
                                              <span style={{ padding: "2px 6px", borderRadius: 6, background: C.amber100, color: C.amber600, fontSize: 11, fontWeight: 700 }}>
                                                {dx.hcc_code}
                                              </span>
                                            ) : (
                                              <span style={{ color: C.slate400 }}>--</span>
                                            )}
                                          </td>
                                          <td className="tabular-nums" style={{ padding: "10px", fontWeight: 700, color: C.slate800 }}>
                                            {dx.raf_weight != null ? (dx.raf_weight ?? 0).toFixed(3) : "--"}
                                          </td>
                                          <td style={{ padding: "10px" }}>
                                            {dx.confidence != null ? (
                                              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                                                <div style={{ width: 40, height: 5, borderRadius: 3, background: C.slate200, overflow: "hidden" }}>
                                                  <div
                                                    style={{
                                                      width: `${Math.round((dx.confidence ?? 0) * 100)}%`,
                                                      height: "100%",
                                                      borderRadius: 3,
                                                      background: (dx.confidence ?? 0) >= 0.8 ? C.emerald500 : (dx.confidence ?? 0) >= 0.5 ? C.amber500 : C.red500,
                                                    }}
                                                  />
                                                </div>
                                                <span className="tabular-nums" style={{ fontSize: 11, color: C.slate500, fontWeight: 600 }}>
                                                  {Math.round((dx.confidence ?? 0) * 100)}%
                                                </span>
                                              </div>
                                            ) : (
                                              <span style={{ color: C.slate400 }}>--</span>
                                            )}
                                          </td>
                                          <td style={{ padding: "10px" }}>
                                            <MeatDots evidence={dx.meat_evidence ?? (dx.meat as MEATEvidence | undefined)} />
                                          </td>
                                          <td style={{ padding: "10px" }}>
                                            {dx.status === "confirmed" ? (
                                              <span style={{ fontSize: 11, fontWeight: 700, color: C.emerald600 }}>Confirmed</span>
                                            ) : dx.status === "rejected" ? (
                                              <span style={{ fontSize: 11, fontWeight: 700, color: C.red600 }}>Rejected</span>
                                            ) : (
                                              <div style={{ display: "flex", gap: 4 }}>
                                                <button
                                                  onClick={() => confirmDxMut.mutate({ docId, dxId: dx.id! })}
                                                  className="btn-press"
                                                  style={{
                                                    padding: "4px 8px",
                                                    borderRadius: 6,
                                                    border: `1px solid ${C.emerald600}`,
                                                    background: C.emerald50,
                                                    color: C.emerald600,
                                                    fontSize: 11,
                                                    fontWeight: 700,
                                                    cursor: "pointer",
                                                    display: "flex",
                                                    alignItems: "center",
                                                    gap: 3,
                                                  }}
                                                >
                                                  <CheckCircle2 size={11} /> Confirm
                                                </button>
                                                <button
                                                  onClick={() => rejectDxMut.mutate({ docId, dxId: dx.id! })}
                                                  className="btn-press"
                                                  style={{
                                                    padding: "4px 8px",
                                                    borderRadius: 6,
                                                    border: `1px solid ${C.red500}`,
                                                    background: C.red50,
                                                    color: C.red600,
                                                    fontSize: 11,
                                                    fontWeight: 700,
                                                    cursor: "pointer",
                                                    display: "flex",
                                                    alignItems: "center",
                                                    gap: 3,
                                                  }}
                                                >
                                                  <XCircle size={11} /> Reject
                                                </button>
                                              </div>
                                            )}
                                          </td>
                                        </tr>
                                      ))}
                                    </tbody>
                                  </table>
                                </div>
                              )}
                            </div>

                            {/* Medications / Labs / Vitals */}
                            <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
                              {aData.medications && aData.medications.length > 0 && (
                                <div style={{ flex: "1 1 200px" }}>
                                  <div style={{ display: "flex", alignItems: "center", gap: 4, marginBottom: 6 }}>
                                    <FlaskConical size={13} color={C.purple600} />
                                    <span style={{ fontSize: 12, fontWeight: 700, color: C.slate700 }}>Medications</span>
                                  </div>
                                  <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                                    {aData.medications.map((med: string, i: number) => (
                                      <span key={med || i} style={{ padding: "2px 8px", borderRadius: 6, background: C.slate100, fontSize: 11, color: C.slate600 }}>
                                        {med}
                                      </span>
                                    ))}
                                  </div>
                                </div>
                              )}
                              {aData.labs && aData.labs.length > 0 && (
                                <div style={{ flex: "1 1 200px" }}>
                                  <div style={{ display: "flex", alignItems: "center", gap: 4, marginBottom: 6 }}>
                                    <FlaskConical size={13} color={C.amber600} />
                                    <span style={{ fontSize: 12, fontWeight: 700, color: C.slate700 }}>Labs</span>
                                  </div>
                                  <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                                    {aData.labs.map((lab: string | { name: string; value: string }, i: number) => (
                                      <span key={typeof lab === "string" ? lab : `${lab.name}-${i}`} style={{ padding: "2px 8px", borderRadius: 6, background: C.amber50, fontSize: 11, color: C.amber600 }}>
                                        {typeof lab === "string" ? lab : `${lab.name}: ${lab.value}`}
                                      </span>
                                    ))}
                                  </div>
                                </div>
                              )}
                              {aData.vitals && aData.vitals.length > 0 && (
                                <div style={{ flex: "1 1 200px" }}>
                                  <div style={{ display: "flex", alignItems: "center", gap: 4, marginBottom: 6 }}>
                                    <Stethoscope size={13} color={C.red500} />
                                    <span style={{ fontSize: 12, fontWeight: 700, color: C.slate700 }}>Vitals</span>
                                  </div>
                                  <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                                    {aData.vitals.map((v: string | { name: string; value: string }, i: number) => (
                                      <span key={typeof v === "string" ? v : `${v.name}-${i}`} style={{ padding: "2px 8px", borderRadius: 6, background: C.red50, fontSize: 11, color: C.red600 }}>
                                        {typeof v === "string" ? v : `${v.name}: ${v.value}`}
                                      </span>
                                    ))}
                                  </div>
                                </div>
                              )}
                            </div>
                          </div>
                        )}
                      </Card>
                    </div>
                  )}

                  {/* ===== DRAFT RAF PANEL ===== */}
                  {isDraftOpen && (
                    <div className="animate-slide-up" style={{ marginTop: -1 }}>
                      <Card
                        className="card-glow-emerald"
                        style={{
                          borderTopLeftRadius: 0,
                          borderTopRightRadius: 0,
                          borderTop: `2px solid ${C.emerald600}`,
                        }}
                      >
                        {!dData ? (
                          <SectionLoader label="Calculating draft RAF score..." />
                        ) : (
                          <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
                            {/* Score comparison */}
                            <div style={{ display: "flex", gap: 24, flexWrap: "wrap", justifyContent: "center" }}>
                              <div style={{ textAlign: "center", minWidth: 140 }}>
                                <p style={{ fontSize: 11, fontWeight: 700, color: C.slate500, textTransform: "uppercase", letterSpacing: 1, margin: "0 0 6px" }}>
                                  Current RAF
                                </p>
                                <span
                                  className="tabular-nums"
                                  style={{ fontSize: 36, fontWeight: 800, color: rafScoreColor(rafScore ?? 0), lineHeight: 1 }}
                                >
                                  {(rafScore ?? 0).toFixed(3)}
                                </span>
                              </div>

                              <div style={{ display: "flex", alignItems: "center", color: C.slate400, fontSize: 28, fontWeight: 300 }}>
                                &rarr;
                              </div>

                              <div style={{ textAlign: "center", minWidth: 140 }}>
                                <p style={{ fontSize: 11, fontWeight: 700, color: C.slate500, textTransform: "uppercase", letterSpacing: 1, margin: "0 0 6px" }}>
                                  Draft RAF
                                </p>
                                <span
                                  className="tabular-nums"
                                  style={{
                                    fontSize: 36,
                                    fontWeight: 800,
                                    lineHeight: 1,
                                    background: `linear-gradient(135deg, ${C.blue600}, ${C.emerald600})`,
                                    WebkitBackgroundClip: "text",
                                    WebkitTextFillColor: "transparent",
                                  }}
                                >
                                  {(dData.draft_raf ?? dData.draft_score ?? 0).toFixed(3)}
                                </span>
                              </div>

                              <div style={{ textAlign: "center", minWidth: 120 }}>
                                <p style={{ fontSize: 11, fontWeight: 700, color: C.slate500, textTransform: "uppercase", letterSpacing: 1, margin: "0 0 6px" }}>
                                  Delta
                                </p>
                                <span
                                  className="tabular-nums"
                                  style={{ fontSize: 36, fontWeight: 800, color: C.emerald600, lineHeight: 1 }}
                                >
                                  +{((dData.draft_raf ?? dData.draft_score ?? 0) - (rafScore ?? 0)).toFixed(3)}
                                </span>
                              </div>
                            </div>

                            {/* New HCC codes */}
                            {(dData.new_hccs ?? dData.new_hcc_codes ?? []).length > 0 && (
                              <div>
                                <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 8 }}>
                                  <Brain size={14} color={C.blue600} />
                                  <span style={{ fontSize: 13, fontWeight: 700, color: C.slate800 }}>
                                    New HCC Codes
                                  </span>
                                </div>
                                <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                                  {(dData.new_hccs ?? dData.new_hcc_codes ?? []).map((hcc: string | { code?: string; hcc_code?: string; label?: string; description?: string; coefficient?: number; raf_weight?: number }, i: number) => (
                                    <div
                                      key={typeof hcc === "string" ? hcc : (hcc.hcc_code || hcc.code || `hcc-${i}`)}
                                      style={{
                                        padding: "6px 12px",
                                        borderRadius: 8,
                                        background: C.emerald50,
                                        border: `1px solid ${C.emerald100}`,
                                        display: "flex",
                                        alignItems: "center",
                                        gap: 6,
                                      }}
                                    >
                                      <span style={{ fontSize: 12, fontWeight: 800, color: C.emerald600, fontFamily: "monospace" }}>
                                        {typeof hcc === "string" ? hcc : hcc.code ?? hcc.hcc_code}
                                      </span>
                                      {typeof hcc === "object" && hcc.description && (
                                        <span style={{ fontSize: 11, color: C.slate500 }}>
                                          {hcc.description}
                                        </span>
                                      )}
                                      {typeof hcc === "object" && hcc.raf_weight != null && (
                                        <span className="tabular-nums" style={{ fontSize: 11, fontWeight: 700, color: C.blue600 }}>
                                          +{(hcc.raf_weight ?? 0).toFixed(3)}
                                        </span>
                                      )}
                                    </div>
                                  ))}
                                </div>
                              </div>
                            )}

                            {/* Revenue impact */}
                            {(dData.estimated_revenue_impact ?? dData.revenue_impact) != null && (
                              <div
                                style={{
                                  background: `linear-gradient(135deg, ${C.emerald50}, ${C.blue50})`,
                                  padding: "14px 18px",
                                  borderRadius: 10,
                                  display: "flex",
                                  alignItems: "center",
                                  gap: 10,
                                }}
                              >
                                <TrendingUp size={18} color={C.emerald600} />
                                <div>
                                  <span style={{ fontSize: 12, color: C.slate500, fontWeight: 600 }}>
                                    Estimated Revenue Impact
                                  </span>
                                  <span
                                    className="tabular-nums"
                                    style={{ display: "block", fontSize: 22, fontWeight: 800, color: C.emerald600 }}
                                  >
                                    ${((dData.estimated_revenue_impact ?? dData.revenue_impact ?? 0)).toLocaleString()}
                                  </span>
                                </div>
                              </div>
                            )}

                            {/* Disclaimer */}
                            <p style={{ fontSize: 11, color: C.slate400, fontStyle: "italic", margin: 0, padding: "8px 12px", background: C.slate100, borderRadius: 8 }}>
                              This is a preliminary score based on document-extracted diagnoses. Final RAF scores are subject to CMS adjudication and may differ from this estimate.
                            </p>
                          </div>
                        )}
                      </Card>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
