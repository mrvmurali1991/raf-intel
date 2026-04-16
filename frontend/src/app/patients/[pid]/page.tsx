"use client";

import React, { use, useState, useRef, useEffect, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { Printer } from "lucide-react";
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
  calculateRAF,
  generateAudit,
  acceptSuspect,
  dismissSuspect,
  analyzeEncounter,
  batchAnalysis,
  getJobStatus,
  getPatientDocuments,
} from "@/lib/api";
import { ModelComparison } from "@/components/model-comparison";
import { AIHealthBanner } from "@/components/AIHealthBanner";
import {
  RiskGauge,
  ProgressBar,
} from "@/components/healthcare-ui";
import { useToast } from "@/components/Toast";
import { calculateAge } from "@/lib/utils";
import type { Patient, AnalysisResult, AIDiagnosis } from "@/types";
import type {
  PatientProfile,
  RafBreakdown,
  RafHistoryResponse,
  PatientEncountersResponse,
  ProblemListResponse,
  RecaptureGapsResponse,
  AuditPackagesResponse,
  PatientSuspectsResponse,
} from "@/lib/api";

// Component imports
import {
  C,
  formatDate,
  rafScoreColor,
  Spinner,
  segmentLabel,
  segmentCodeUpper,
} from "./components/shared";
import type {
  ExtendedRafBreakdown,
  HCCDetail,
  EncounterItem,
  ApiError,
  ProblemItem,
  RecaptureGapItem,
} from "./components/shared";
import { OverviewTab } from "./components/OverviewTab";
import { RAFTab } from "./components/RAFTab";
import { ClinicalTab } from "./components/ClinicalTab";
import { EncountersTab } from "./components/EncountersTab";
import { SuspectsTab } from "./components/SuspectsTab";
import { AuditTab } from "./components/AuditTab";
import { ActivityTab } from "./components/ActivityTab";
import { DocumentsTab } from "./components/DocumentsTab";

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
  const [lastAnalysisResult, setLastAnalysisResult] = useState<Record<number, AnalysisResult>>({});

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
    queryKey: ["patient-encounters", pid],
    queryFn: () => getPatientEncounters(pid),
  });

  const problemsQ = useQuery({
    queryKey: ["patient-problems", pid, selectedYear],
    queryFn: () => getPatientProblemList(pid, selectedYear),
  });

  const suspectsQ = useQuery<PatientSuspectsResponse>({
    queryKey: ["patient-suspects", pid, selectedYear],
    queryFn: () => getPatientSuspects(pid, "open", selectedYear),
  });

  // All suspects (including accepted/dismissed) for timeline
  const allSuspectsQ = useQuery<PatientSuspectsResponse>({
    queryKey: ["patient-suspects-all", pid, selectedYear],
    queryFn: () => getPatientSuspects(pid, "all", selectedYear),
    enabled: activeTab === "activity",
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
  const [lastCalcResult, setLastCalcResult] = useState<{ raf_score: number } | null>(null);

  const calcRAFMutation = useMutation({
    mutationFn: () => calculateRAF(pid, { year: selectedYear }),
    onSuccess: (data) => {
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
    onError: () => toast.error("Error", "Failed to accept suspect condition."),
  });

  const dismissMutation = useMutation({
    mutationFn: (id: number) => dismissSuspect(id),
    onSuccess: () => {
      toast.success("Dismissed", "Suspect condition dismissed.");
      queryClient.invalidateQueries({ queryKey: ["patient-suspects", pid, selectedYear] });
    },
    onError: () => toast.error("Error", "Failed to dismiss suspect condition."),
  });

  const analyzeMutation = useMutation({
    mutationFn: (encId: number) => analyzeEncounter(encId),
    onSuccess: async (data, encId) => {
      const dxCount = data?.diagnoses?.length ?? 0;
      const hccCnt =
        data?.diagnoses?.filter(
          (d: AIDiagnosis) => d.hcc_code || d.hcc || d.hcc_mapping?.hcc_code
        ).length ?? 0;
      setLastAnalysisResult((prev) => ({ ...prev, [encId]: data }));
      toast.success(
        "Analysis Complete",
        `Found ${dxCount} diagnoses, ${hccCnt} HCC codes. Recalculating RAF...`
      );
      try {
        await calculateRAF(pid, { year: selectedYear });
      } catch { /* ignore */ }
      queryClient.invalidateQueries({ queryKey: ["patient-encounters", pid] });
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
  const pollCountRef = useRef<number>(0);
  const MAX_POLL_COUNT = 60; // 60 × 5 s = 5 minutes maximum

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
      pollCountRef.current = 0;
      setBatchStatus("running");
      toast.success("Batch Started", "Analyzing all encounters...");
      pollRef.current = setInterval(async () => {
        pollCountRef.current += 1;
        if (pollCountRef.current >= MAX_POLL_COUNT) {
          clearInterval(pollRef.current!);
          pollRef.current = null;
          setBatchStatus(null);
          toast.error("Timeout", "Batch analysis is taking too long. Please check back later.");
          return;
        }
        try {
          const status = await getJobStatus(jobId);
          const done = status.status === "completed" || (status.status as string) === "SUCCESS";
          if (done) {
            clearInterval(pollRef.current!);
            pollRef.current = null;
            setBatchStatus(null);
            toast.success(
              "Batch Complete",
              `Analyzed ${status.processed ?? (status as unknown as { progress?: number }).progress ?? 0} encounters. Recalculating RAF score...`
            );
            try {
              await calculateRAF(pid, { year: selectedYear });
              toast.success("RAF Updated", "RAF score has been recalculated with new analysis results.");
            } catch {
              toast.info("Note", "Analysis complete. Click 'Calculate RAF' to update the score.");
            }
            queryClient.invalidateQueries({ queryKey: ["patient-encounters", pid] });
            queryClient.invalidateQueries({ queryKey: ["patient-suspects", pid, selectedYear] });
            queryClient.invalidateQueries({ queryKey: ["patient-problems", pid, selectedYear] });
            queryClient.invalidateQueries({ queryKey: ["raf-breakdown", pid, selectedYear] });
            queryClient.invalidateQueries({ queryKey: ["raf-history", pid] });
            queryClient.invalidateQueries({ queryKey: ["patient-profile", pid] });
            queryClient.invalidateQueries({ queryKey: ["model-comparison", pid, selectedYear] });
          } else if (status.status === "failed" || (status.status as string) === "FAILED") {
            clearInterval(pollRef.current!);
            pollRef.current = null;
            setBatchStatus(null);
            toast.error("Batch Failed", (status.error as string) || "Analysis failed");
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
        e?.response?.data?.detail || e?.message || "Failed to start batch analysis."
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
    : "Loading\u2026";
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
        const e = (hcc.meat_evidence || hcc.meat_status_detail || hcc.meat_completeness) as Record<string, unknown> | null | undefined;
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

  // Data quality
  const dataQuality = (() => {
    const encList = encountersQ.data?.encounters ?? (Array.isArray(encountersQ.data) ? encountersQ.data : []);
    const probList = Array.isArray(problemsQ.data) ? problemsQ.data : (problemsQ.data?.problems ?? []);
    const medList = Array.isArray(medsQ.data) ? medsQ.data : (medsQ.data?.medications ?? []);
    const dqSections = [
      encList.length > 0,
      encList.some((e: EncounterItem) => e.notes || e.has_notes),
      probList.length > 0,
      medList.length > 0,
      !!(profile as any)?.vitals?.latest || !!(vitalsSuspectsQ.data?.suspects?.length),
      !!((profile as any)?.labs?.results?.length) || !!(labSuspectsQ.data?.suspects?.length),
      !!(profile?.billing?.icd10_codes?.length),
      !!(profile?.enrollment) && profile?.enrollment?.source !== "default",
      Array.isArray(profile?.immunizations) && (profile?.immunizations?.length ?? 0) > 0,
      !!(profile?.demographics?.race) && !!(profile?.demographics?.language),
    ];
    return Math.round((dqSections.filter(Boolean).length / dqSections.length) * 100);
  })();

  const suspectCount = suspectsQ.data?.suspects?.length ?? 0;

  // AI Analysis summary
  const aiAnalysis = useMemo(() => {
    const encs: EncounterItem[] = encountersQ.data?.encounters || [];
    const analyzedEncs = encs.filter((e) => e.cached_analysis || e.analysis);
    if (analyzedEncs.length === 0) return null;
    const allDx: AIDiagnosis[] = [];
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
    const hccDx = allDx.filter((d: AIDiagnosis) => d.hcc_code || d.hcc || d.hcc_mapping?.hcc_code);
    const yearBilledCodes = new Set<string>();
    const hccDetails: HCCDetail[] = (rafBreakdownQ.data as ExtendedRafBreakdown | undefined)?.hcc_details || [];
    for (const hcc of hccDetails) {
      for (const c of hcc.icd10_codes || []) {
        const code = (typeof c === "string" ? c : c.code || c.icd10_code || "").replace(".", "");
        if (code) yearBilledCodes.add(code);
      }
    }
    const billingCodes: Set<string> = yearBilledCodes.size > 0
      ? yearBilledCodes
      : new Set(
          (profile?.billing?.diagnoses || profile?.billing?.icd10_codes || [])
            .map((d: string | { code?: string; icd10_code?: string }) => (typeof d === "string" ? d : d.code || d.icd10_code || "").replace(".", ""))
        );
    const aiOnlyCodes = allDx.filter((d: AIDiagnosis) => {
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
    { id: "documents", label: "Documents & Reports" },
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
      {/* AI availability warning — surfaces when Gemini is unreachable */}
      <div style={{ padding: "12px 16px 0" }}>
        <AIHealthBanner />
      </div>
      {/* PATIENT HEADER (sticky) */}
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
              onMouseEnter={(e) => (e.currentTarget.style.background = C.slate100)}
              onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M19 12H5M12 19l-7-7 7-7" />
              </svg>
            </Link>
            <div
              style={{
                width: 44, height: 44, borderRadius: 12,
                background: `linear-gradient(135deg, ${C.blue600}, ${C.emerald600})`,
                display: "flex", alignItems: "center", justifyContent: "center",
                color: C.white, fontSize: 18, fontWeight: 800, letterSpacing: "-0.02em",
                flexShrink: 0, boxShadow: "0 2px 8px rgba(15, 118, 110, 0.25)",
              }}
            >
              {(patientName || "").trim().charAt(0).toUpperCase() || "\u2022"}
            </div>
            <div>
              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <h1 className="gradient-text" style={{ margin: 0, fontSize: 24, fontWeight: 700, color: C.slate800, lineHeight: 1.2 }}>
                  {patientName}
                </h1>
                <span style={{
                  display: "inline-flex", alignItems: "center", padding: "3px 10px",
                  borderRadius: 999, fontSize: 11, fontWeight: 600, fontFamily: "monospace",
                  background: C.blue100, color: C.blue600,
                }}>
                  PID {pid}
                </span>
              </div>
            </div>
          </div>

          {/* Right: demographics + actions */}
          <div style={{ display: "flex", alignItems: "center", gap: 20 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 16, fontSize: 13, color: C.slate500 }}>
              {age !== null && <span>{age} yrs</span>}
              {sex && <span style={{ textTransform: "capitalize" }}>{sex}</span>}
              {dob && <span>{formatDate(dob)}</span>}
            </div>
            <div style={{ width: 1, height: 32, background: C.slate200 }} />
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <button
                onClick={() => batchMutation.mutate()}
                disabled={batchMutation.isPending || batchStatus === "running"}
                className="hover-lift"
                style={{
                  display: "inline-flex", alignItems: "center", gap: 8,
                  padding: "10px 18px", borderRadius: 12, border: "none",
                  background: C.blue600, color: C.white, fontSize: 13, fontWeight: 600,
                  cursor: batchMutation.isPending || batchStatus === "running" ? "not-allowed" : "pointer",
                  boxShadow: "0 4px 10px rgba(15, 118, 110, 0.2)",
                  opacity: batchMutation.isPending || batchStatus === "running" ? 0.6 : 1,
                  transition: "opacity 0.15s, transform 0.2s, box-shadow 0.2s",
                }}
              >
                {(batchMutation.isPending || batchStatus === "running") && <Spinner size={14} />}
                {batchStatus === "running" ? "Analyzing..." : "Analyze All Encounters"}
              </button>
              <button
                onClick={() => calcRAFMutation.mutate()}
                disabled={calcRAFMutation.isPending}
                style={{
                  display: "inline-flex", alignItems: "center", gap: 6,
                  padding: "8px 16px", borderRadius: 8,
                  border: `1px solid ${C.slate200}`, background: C.white,
                  color: C.slate700, fontSize: 13, fontWeight: 600,
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
                  display: "inline-flex", alignItems: "center", gap: 6,
                  padding: "8px 16px", borderRadius: 8,
                  border: `1px solid ${C.slate200}`, background: C.white,
                  color: C.slate700, fontSize: 13, fontWeight: 600,
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
                  display: "inline-flex", alignItems: "center", gap: 6,
                  padding: "8px 16px", borderRadius: 8,
                  border: `1px solid ${C.slate200}`, background: C.white,
                  color: C.slate700, fontSize: 13, fontWeight: 600, cursor: "pointer",
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

      {/* RISK SUMMARY STRIP */}
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
        <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", width: "100%", gap: 0 }}>
          {/* 1. RAF Score */}
          <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "0 16px" }}>
            <RiskGauge score={rafScore} size={56} label="" />
            <div>
              <div style={{ fontSize: 10, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em", color: C.slate400, marginBottom: 2 }}>
                RAF Score ({selectedYear})
              </div>
              <div
                className="tabular-nums"
                style={{
                  fontSize: 24, fontWeight: 800,
                  color: rafScore != null ? rafScoreColor(rafScore) : C.slate400,
                  fontFamily: "monospace", lineHeight: 1,
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
          <div style={{ display: "flex", flexDirection: "column", justifyContent: "center", alignItems: "center", borderLeft: `1px solid ${C.slate100}`, padding: "0 16px" }}>
            <div style={{ fontSize: 10, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em", color: C.slate400, marginBottom: 6 }}>
              Model Segment
            </div>
            <span
              title={`Segment code: ${segmentCodeUpper(modelSegment)}`}
              style={{ display: "inline-flex", alignItems: "center", padding: "4px 14px", borderRadius: 6, fontSize: 13, fontWeight: 700, background: C.slate100, color: C.slate700, textAlign: "center" }}
            >
              {segmentLabel(modelSegment)}
            </span>
          </div>

          {/* 3. HCC Count */}
          <div style={{ display: "flex", flexDirection: "column", justifyContent: "center", alignItems: "center", borderLeft: `1px solid ${C.slate100}`, padding: "0 16px" }}>
            <div style={{ fontSize: 10, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em", color: C.slate400, marginBottom: 6 }}>
              HCC Count
            </div>
            <div style={{ display: "flex", alignItems: "baseline", gap: 4 }}>
              <span style={{ fontSize: 24, fontWeight: 700, color: C.slate900, lineHeight: 1 }}>{hccCount}</span>
              <span style={{ fontSize: 12, color: C.slate400, fontWeight: 500 }}>conditions</span>
            </div>
          </div>

          {/* 4. MEAT Compliance */}
          <div style={{ display: "flex", flexDirection: "column", justifyContent: "center", alignItems: "center", borderLeft: `1px solid ${C.slate100}`, padding: "0 16px" }}>
            <div style={{ fontSize: 10, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em", color: C.slate400, marginBottom: 6 }}>
              MEAT Compliance
            </div>
            <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 4 }}>
              <span style={{ fontSize: 16, fontWeight: 700, color: meatTotal === 0 ? C.slate400 : meatFilled === 0 ? C.amber600 : C.slate900, lineHeight: 1 }}>
                {meatTotal === 0 ? "—" : meatFilled === 0 ? "Pending" : `${meatFilled}/${meatTotal}`}
              </span>
              <div style={{ width: 80 }}>
                <ProgressBar value={meatTotal > 0 ? (meatFilled / meatTotal) * 100 : 0} showPercent={false} height={4} color={meatFilled > 0 ? C.emerald500 : C.amber600} />
              </div>
            </div>
          </div>

          {/* 5. Data Quality */}
          <div style={{ display: "flex", flexDirection: "column", justifyContent: "center", alignItems: "center", borderLeft: `1px solid ${C.slate100}`, padding: "0 16px" }}>
            <div style={{ fontSize: 10, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em", color: C.slate400, marginBottom: 6 }}>
              Data Quality
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <span style={{
                width: 8, height: 8, borderRadius: "50%",
                background: dataQuality === null ? C.gray400 : dataQuality >= 80 ? C.emerald500 : dataQuality >= 50 ? C.amber500 : C.red500,
              }} />
              <span style={{ fontSize: 20, fontWeight: 700, color: C.slate900, lineHeight: 1 }}>
                {dataQuality !== null ? `${dataQuality}%` : "\u2014"}
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* TAB NAVIGATION */}
      <div style={{ background: C.white, borderBottom: `1px solid ${C.slate200}`, padding: "0 24px" }}>
        <div style={{ display: "flex", gap: 0, alignItems: "center" }}>
          {/* Year Selector */}
          <div style={{ display: "flex", alignItems: "center", gap: 4, marginRight: 16, paddingRight: 16, borderRight: `1px solid ${C.slate200}` }}>
            <span style={{ fontSize: 10, fontWeight: 600, color: C.slate400, textTransform: "uppercase", letterSpacing: "0.05em", marginRight: 4 }}>Year</span>
            {Array.from({length: 3}, (_, i) => new Date().getFullYear() - i).map((yr) => (
              <button
                key={yr}
                onClick={() => setSelectedYear(yr)}
                style={{
                  padding: "6px 12px", fontSize: 12,
                  fontWeight: selectedYear === yr ? 700 : 500,
                  color: selectedYear === yr ? C.white : C.slate500,
                  background: selectedYear === yr ? C.blue600 : "transparent",
                  border: selectedYear === yr ? "none" : `1px solid ${C.slate200}`,
                  borderRadius: 6, cursor: "pointer", transition: "all 0.15s",
                }}
              >
                {yr}
              </button>
            ))}
          </div>
          <div role="tablist">
            {tabs.map((tab) => (
              <button
                key={tab.id}
                role="tab"
                aria-selected={activeTab === tab.id}
                id={`tab-${tab.id}`}
                onClick={() => setActiveTab(tab.id)}
                style={{
                  padding: "14px 20px", fontSize: 13,
                  fontWeight: activeTab === tab.id ? 600 : 500,
                  color: activeTab === tab.id ? C.blue600 : C.slate500,
                  background: "transparent", border: "none",
                  borderBottom: activeTab === tab.id ? `2px solid ${C.blue600}` : "2px solid transparent",
                  cursor: "pointer", display: "inline-flex", alignItems: "center", gap: 6,
                  transition: "color 0.15s, border-color 0.15s",
                }}
              >
                {tab.label}
                {tab.badge !== undefined && (
                  <span style={{
                    display: "inline-flex", alignItems: "center", justifyContent: "center",
                    minWidth: 20, height: 20, padding: "0 6px", borderRadius: 999,
                    fontSize: 10, fontWeight: 700, background: C.amber500, color: C.white,
                  }}>
                    {tab.badge}
                  </span>
                )}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* TAB CONTENT */}
      <div role="tabpanel" aria-labelledby={`tab-${activeTab}`} className="animate-slide-up stagger-2" style={{ padding: 24 }}>
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
            suspects={allSuspectsQ.data ?? suspectsQ.data}
            suspectsLoading={allSuspectsQ.isLoading}
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
