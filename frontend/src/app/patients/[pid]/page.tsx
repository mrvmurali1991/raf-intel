"use client";

import React, { Component, use, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
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
  getAuditDownloadUrl,
  calculateRAF,
  generateAudit,
  acceptSuspect,
  dismissSuspect,
  analyzeEncounter,
  batchAnalysis,
  getJobStatus,
} from "@/lib/api";
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
import type { MEATEvidence } from "@/types";

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
  blue600: "#2563EB",
  blue500: "#3B82F6",
  blue100: "#DBEAFE",
  blue50: "#EFF6FF",
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

// ---------------------------------------------------------------------------
// Tab Error Boundary
// ---------------------------------------------------------------------------
class TabErrorBoundary extends Component<
  { tabName: string; children: React.ReactNode },
  { hasError: boolean; error: Error | null }
> {
  constructor(props: { tabName: string; children: React.ReactNode }) {
    super(props);
    this.state = { hasError: false, error: null };
  }
  static getDerivedStateFromError(error: Error) {
    return { hasError: true, error };
  }
  render() {
    if (this.state.hasError) {
      return (
        <div style={{
          background: C.red50,
          border: `1px solid ${C.red100}`,
          borderRadius: 12,
          padding: "32px 24px",
          textAlign: "center",
        }}>
          <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke={C.red500} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ marginBottom: 12 }}>
            <circle cx="12" cy="12" r="10" /><line x1="12" y1="8" x2="12" y2="12" /><line x1="12" y1="16" x2="12.01" y2="16" />
          </svg>
          <div style={{ fontSize: 15, fontWeight: 700, color: C.red600, marginBottom: 4 }}>
            {this.props.tabName} failed to load
          </div>
          <div style={{ fontSize: 13, color: C.slate500, marginBottom: 16 }}>
            {this.state.error?.message || "An unexpected error occurred"}
          </div>
          <button
            onClick={() => this.setState({ hasError: false, error: null })}
            style={{
              display: "inline-flex", alignItems: "center", gap: 6,
              padding: "8px 20px", borderRadius: 8, border: `1px solid ${C.red500}`,
              background: C.white, color: C.red600, fontSize: 13, fontWeight: 600,
              cursor: "pointer",
            }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="23 4 23 10 17 10" /><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" />
            </svg>
            Retry
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

// ---------------------------------------------------------------------------
// CSS Keyframes (injected once)
// ---------------------------------------------------------------------------
function AnimatedStyles() {
  return (
    <style>{`
      @keyframes raf-count-up {
        from { opacity: 0; transform: translateY(12px) scale(0.9); }
        to { opacity: 1; transform: translateY(0) scale(1); }
      }
      @keyframes raf-pulse {
        0%, 100% { box-shadow: 0 0 0 0 rgba(37, 99, 235, 0.3); }
        50% { box-shadow: 0 0 0 8px rgba(37, 99, 235, 0); }
      }
    `}</style>
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
}: {
  children: React.ReactNode;
  style?: React.CSSProperties;
  noPadding?: boolean;
}) {
  return (
    <div
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
function MeatDots({ evidence }: { evidence?: MEATEvidence | null }) {
  const letters = [
    { key: "monitor" as const, label: "M", color: C.blue600 },
    { key: "evaluate" as const, label: "E", color: C.purple600 },
    { key: "assess" as const, label: "A", color: C.amber600 },
    { key: "treat" as const, label: "T", color: C.emerald600 },
  ];
  return (
    <div style={{ display: "inline-flex", gap: 3 }}>
      {letters.map(({ key, label, color }) => {
        const filled = evidence && evidence[key];
        return (
          <span
            key={key}
            style={{
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
              width: 22,
              height: 22,
              borderRadius: 4,
              fontSize: 10,
              fontWeight: 700,
              backgroundColor: filled ? `${color}1A` : "transparent",
              color: filled ? color : C.gray400,
              border: `1.5px solid ${filled ? color : C.gray200}`,
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
    queryKey: ["raf-breakdown", pid],
    queryFn: () => getRAFBreakdown(pid),
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
    queryKey: ["patient-problems", pid],
    queryFn: () => getPatientProblemList(pid),
  });

  const suspectsQ = useQuery({
    queryKey: ["patient-suspects", pid],
    queryFn: () => getPatientSuspects(pid),
  });

  // ---- Tab-specific queries ----
  const medsQ = useQuery({
    queryKey: ["patient-meds", pid],
    queryFn: () => getPatientMedications(pid),
    enabled: activeTab === "clinical" || activeTab === "overview",
  });

  const recaptureQ = useQuery({
    queryKey: ["patient-recapture", pid],
    queryFn: () => getPatientRecaptureGaps(pid),
    enabled: activeTab === "raf" || activeTab === "overview",
  });

  const labSuspectsQ = useQuery({
    queryKey: ["patient-lab-suspects", pid],
    queryFn: () => getPatientLabSuspects(pid),
    enabled: activeTab === "clinical",
  });

  const vitalsSuspectsQ = useQuery({
    queryKey: ["patient-vitals-suspects", pid],
    queryFn: () => getPatientVitalsSuspects(pid),
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
    queryKey: ["patient-med-gaps", pid],
    queryFn: () => getPatientMedicationGaps(pid),
    enabled: activeTab === "clinical",
  });

  const auditsQ = useQuery({
    queryKey: ["patient-audits", pid],
    queryFn: () => getAuditPackages(Number(pid)),
    enabled: activeTab === "audit",
  });

  // ---- Mutations ----
  const calcRAFMutation = useMutation({
    mutationFn: () => calculateRAF(pid),
    onSuccess: () => {
      toast.success("RAF Calculated", "Score has been recalculated.");
      queryClient.invalidateQueries({ queryKey: ["raf-breakdown", pid] });
      queryClient.invalidateQueries({ queryKey: ["raf-history", pid] });
      queryClient.invalidateQueries({ queryKey: ["patient-profile", pid] });
    },
    onError: () => toast.error("Error", "Failed to calculate RAF score."),
  });

  const auditMutation = useMutation({
    mutationFn: () => generateAudit(Number(pid)),
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
      queryClient.invalidateQueries({ queryKey: ["patient-suspects", pid] });
    },
  });

  const dismissMutation = useMutation({
    mutationFn: (id: number) => dismissSuspect(id),
    onSuccess: () => {
      toast.success("Dismissed", "Suspect condition dismissed.");
      queryClient.invalidateQueries({ queryKey: ["patient-suspects", pid] });
    },
  });

  const analyzeMutation = useMutation({
    mutationFn: (encId: number) => analyzeEncounter(encId),
    onSuccess: (data, encId) => {
      const dxCount = data?.diagnoses?.length ?? 0;
      const hccCount =
        data?.diagnoses?.filter(
          (d: any) => d.hcc_code || d.hcc || d.hcc_mapping?.hcc_code
        ).length ?? 0;
      setLastAnalysisResult((prev) => ({ ...prev, [encId]: data }));
      toast.success(
        "Analysis Complete",
        `Found ${dxCount} diagnoses, ${hccCount} HCC codes. Recalculate RAF to update score.`
      );
      queryClient.invalidateQueries({ queryKey: ["patient-encounters", pid] });
      queryClient.invalidateQueries({ queryKey: ["patient-suspects", pid] });
      queryClient.invalidateQueries({ queryKey: ["patient-problems", pid] });
      queryClient.invalidateQueries({ queryKey: ["raf-breakdown", pid] });
      queryClient.invalidateQueries({ queryKey: ["raf-history", pid] });
      queryClient.invalidateQueries({ queryKey: ["patient-profile", pid] });
    },
    onError: (e: any) =>
      toast.error(
        "Analysis Failed",
        e?.response?.data?.detail || e?.message || "Encounter analysis failed."
      ),
  });

  const [batchStatus, setBatchStatus] = useState<string | null>(null);
  const batchMutation = useMutation({
    mutationFn: () => batchAnalysis(Number(pid)),
    onSuccess: async (data) => {
      const jobId = data.job_id;
      setBatchStatus("running");
      toast.success("Batch Started", "Analyzing all encounters...");
      const poll = setInterval(async () => {
        try {
          const status = await getJobStatus(jobId);
          if (status.status === "complete") {
            clearInterval(poll);
            setBatchStatus(null);
            toast.success(
              "Batch Complete",
              `Analyzed ${status.processed} encounters.`
            );
            queryClient.invalidateQueries({
              queryKey: ["patient-encounters", pid],
            });
            queryClient.invalidateQueries({
              queryKey: ["patient-suspects", pid],
            });
            queryClient.invalidateQueries({
              queryKey: ["patient-problems", pid],
            });
            queryClient.invalidateQueries({
              queryKey: ["raf-breakdown", pid],
            });
            queryClient.invalidateQueries({
              queryKey: ["raf-history", pid],
            });
            queryClient.invalidateQueries({
              queryKey: ["patient-profile", pid],
            });
          } else if (status.status === "failed") {
            clearInterval(poll);
            setBatchStatus(null);
            toast.error(
              "Batch Failed",
              (status.error as string) || "Analysis failed"
            );
          }
        } catch {
          clearInterval(poll);
          setBatchStatus(null);
        }
      }, 5000);
    },
    onError: (e: any) => {
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
  const patient = patientQ.data as any;
  const profile = profileQ.data as any;
  const breakdown = rafBreakdownQ.data as any;
  const history = rafHistoryQ.data as any;

  const patientName = patient
    ? `${patient.fname || patient.first_name || ""} ${patient.lname || patient.last_name || ""}`.trim()
    : "Loading...";
  const dob = patient?.DOB || patient?.dob || "";
  const sex = patient?.sex || patient?.gender || "";
  const age = dob ? calculateAge(dob) : null;

  const rafScore =
    breakdown?.total_raf ??
    breakdown?.raf_score ??
    profile?.billing?.raf_score ??
    null;
  const hccCount = breakdown?.hcc_details?.length ?? 0;
  const modelSegment = breakdown?.model_segment || "CNA";

  // MEAT compliance calc
  const meatTotal = hccCount * 4;
  const meatFilled = breakdown?.hcc_details
    ? breakdown.hcc_details.reduce((acc: number, hcc: any) => {
        const e = hcc.meat_evidence || hcc.meat_status_detail;
        if (!e) return acc;
        return (
          acc +
          (e.monitor ? 1 : 0) +
          (e.evaluate ? 1 : 0) +
          (e.assess ? 1 : 0) +
          (e.treat ? 1 : 0)
        );
      }, 0)
    : 0;

  // Data quality
  const dataQuality = profile?.data_completeness?.completeness_pct != null
    ? Math.round(profile.data_completeness.completeness_pct)
    : (() => {
        const completenessItems = profile?.data_completeness
          ? Object.entries(profile.data_completeness)
              .filter(([k]) => k !== "completeness_pct")
              .map(([, v]) => v)
          : [];
        return completenessItems.length > 0
          ? Math.round(
              (completenessItems.filter(
                (v: any) => v === true || v > 0 || (typeof v === "object" && v !== null)
              ).length /
                completenessItems.length) *
                100
            )
          : null;
      })();

  const suspectCount = suspectsQ.data?.suspects?.length ?? 0;

  // Tab definitions
  const tabs = [
    { id: "overview", label: "Overview" },
    { id: "raf", label: "RAF Details" },
    { id: "clinical", label: "Clinical Data" },
    { id: "encounters", label: "Encounters" },
    {
      id: "suspects",
      label: "Review Queue",
      badge: suspectCount > 0 ? suspectCount : undefined,
    },
    { id: "audit", label: "Audit" },
  ];

  // =========================================================================
  // RENDER
  // =========================================================================
  return (
    <div style={{ minHeight: "100vh", background: C.bg }}>
      {/* ================================================================= */}
      {/* SECTION 1: PATIENT HEADER (sticky)                                */}
      {/* ================================================================= */}
      <header
        style={{
          position: "sticky",
          top: 0,
          zIndex: 30,
          background: C.white,
          borderBottom: `1px solid ${C.slate200}`,
          height: 80,
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
          {/* Left: back + patient name */}
          <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
            <Link
              href="/patients"
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
                transition: "background 0.15s",
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
            <div>
              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <h1
                  style={{
                    margin: 0,
                    fontSize: 20,
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
                {age !== null && (
                  <span style={{
                    display: "inline-flex", alignItems: "center", padding: "3px 10px",
                    borderRadius: 999, fontSize: 11, fontWeight: 600,
                    background: C.emerald100, color: C.emerald600,
                  }}>
                    {age} yrs
                  </span>
                )}
                {sex && (
                  <span style={{
                    display: "inline-flex", alignItems: "center", padding: "3px 10px",
                    borderRadius: 999, fontSize: 11, fontWeight: 600,
                    background: sex.toLowerCase() === "male" ? "#DBEAFE" : sex.toLowerCase() === "female" ? "#FCE7F3" : C.slate100,
                    color: sex.toLowerCase() === "male" ? "#2563EB" : sex.toLowerCase() === "female" ? "#DB2777" : C.slate700,
                    textTransform: "capitalize",
                  }}>
                    {sex}
                  </span>
                )}
                {profile?.enrollment?.plan_type && (
                  <span style={{
                    display: "inline-flex", alignItems: "center", padding: "3px 10px",
                    borderRadius: 999, fontSize: 11, fontWeight: 600,
                    background: C.amber100, color: C.amber600,
                  }}>
                    {profile.enrollment.plan_type}
                  </span>
                )}
              </div>
            </div>
          </div>

          {/* Right: actions */}
          <div style={{ display: "flex", alignItems: "center", gap: 20 }}>
            {dob && (
              <span style={{ fontSize: 12, color: C.slate400 }}>{formatDate(dob)}</span>
            )}

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
                  cursor:
                    batchMutation.isPending || batchStatus === "running"
                      ? "not-allowed"
                      : "pointer",
                  opacity:
                    batchMutation.isPending || batchStatus === "running"
                      ? 0.6
                      : 1,
                  transition: "opacity 0.15s",
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
                onClick={() => auditMutation.mutate()}
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
            </div>
          </div>
        </div>
      </header>

      {/* ================================================================= */}
      {/* SECTION 2: RISK SUMMARY STRIP                                     */}
      {/* ================================================================= */}
      <div
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
          {/* 1. RAF Score */}
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
                RAF Score
              </div>
              <div
                style={{
                  fontSize: 22,
                  fontWeight: 700,
                  color: rafScore !== null ? rafScoreColor(rafScore) : C.slate400,
                  fontFamily: "monospace",
                  lineHeight: 1,
                }}
              >
                {rafScore !== null ? Number(rafScore).toFixed(3) : "\u2014"}
              </div>
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
        <div style={{ display: "flex", gap: 0 }}>
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
      {/* BREADCRUMB                                                         */}
      {/* ================================================================= */}
      <div style={{
        padding: "10px 24px",
        background: C.bg,
        borderBottom: `1px solid ${C.slate200}`,
        fontSize: 13,
        color: C.slate400,
        display: "flex",
        alignItems: "center",
        gap: 6,
        position: "sticky",
        top: 80,
        zIndex: 25,
      }}>
        <Link href="/patients" style={{ color: C.blue600, textDecoration: "none", fontWeight: 500 }}>
          Patients
        </Link>
        <span style={{ color: C.slate300 }}>/</span>
        <span style={{ color: C.slate600, fontWeight: 500 }}>{patientName}</span>
        <span style={{ color: C.slate300 }}>/</span>
        <span style={{ color: C.slate800, fontWeight: 600 }}>
          {tabs.find((t) => t.id === activeTab)?.label || activeTab}
        </span>
      </div>

      {/* ================================================================= */}
      {/* TAB CONTENT                                                        */}
      {/* ================================================================= */}
      <div style={{ padding: 24 }}>
        <AnimatedStyles />
        {activeTab === "overview" && (
          <TabErrorBoundary tabName="Overview">
            <OverviewTab
              pid={pid}
              patient={patient}
              profile={profile}
              profileLoading={profileQ.isLoading}
              breakdown={breakdown}
              breakdownLoading={rafBreakdownQ.isLoading}
              history={history}
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
            />
          </TabErrorBoundary>
        )}
        {activeTab === "raf" && (
          <TabErrorBoundary tabName="RAF Details">
            <RAFTab
              breakdown={breakdown}
              breakdownLoading={rafBreakdownQ.isLoading}
              history={history}
              historyLoading={rafHistoryQ.isLoading}
              recapture={recaptureQ.data}
              recaptureLoading={recaptureQ.isLoading}
              rafScore={rafScore}
            />
          </TabErrorBoundary>
        )}
        {activeTab === "clinical" && (
          <TabErrorBoundary tabName="Clinical Data">
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
            />
          </TabErrorBoundary>
        )}
        {activeTab === "encounters" && (
          <TabErrorBoundary tabName="Encounters">
            <EncountersTab
              encounters={encountersQ.data}
              encountersLoading={encountersQ.isLoading}
              analyzeMutation={analyzeMutation}
              lastAnalysisResult={lastAnalysisResult}
            />
          </TabErrorBoundary>
        )}
        {activeTab === "suspects" && (
          <TabErrorBoundary tabName="Review Queue">
            <SuspectsTab
              suspects={suspectsQ.data}
              suspectsLoading={suspectsQ.isLoading}
              acceptMutation={acceptMutation}
              dismissMutation={dismissMutation}
              patientAge={age}
              patientSex={sex}
            />
          </TabErrorBoundary>
        )}
        {activeTab === "audit" && (
          <TabErrorBoundary tabName="Audit">
            <AuditTab
              audits={auditsQ.data}
              auditsLoading={auditsQ.isLoading}
              auditMutation={auditMutation}
            />
          </TabErrorBoundary>
        )}
        {activeTab === "models" && (
          <TabErrorBoundary tabName="Model Comparison">
            <Card>
              <EmptyState
                title="Model Comparison"
                description="Compare RAF scores across CMS-HCC V24, V28, and RxHCC models. Run analysis on encounters first to generate comparison data."
                icon={<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="7" height="7" /><rect x="14" y="3" width="7" height="7" /><rect x="14" y="14" width="7" height="7" /><rect x="3" y="14" width="7" height="7" /></svg>}
              />
            </Card>
          </TabErrorBoundary>
        )}
        {activeTab === "documents" && (
          <TabErrorBoundary tabName="Documents & Reports">
            <Card>
              <EmptyState
                title="No documents uploaded yet"
                description="Upload a C-CDA, PDF, or clinical document to extract diagnoses and enrich the patient's RAF profile."
                icon={<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><polyline points="14 2 14 8 20 8" /><line x1="12" y1="18" x2="12" y2="12" /><line x1="9" y1="15" x2="15" y2="15" /></svg>}
              />
            </Card>
          </TabErrorBoundary>
        )}
        {activeTab === "activity" && (
          <TabErrorBoundary tabName="Activity">
            <Card>
              <EmptyState
                title="No activity recorded"
                description="Activity timeline will appear here once encounters are analyzed, suspects are reviewed, or audits are generated."
                icon={<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" /></svg>}
              />
            </Card>
          </TabErrorBoundary>
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
  history,
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
}: any) {
  const encountersWithNotes = (encounters?.encounters || []).filter(
    (e: any) => !!e.notes || !!e.has_notes
  );
  const hasEncountersWithNotes = encountersWithNotes.length > 0;
  const hccCount = breakdown?.hcc_count ?? breakdown?.hcc_details?.length ?? 0;
  const isDemoOnly = hccCount === 0;
  const patientAge = dob ? Math.floor((Date.now() - new Date(dob).getTime()) / 31557600000) : null;
  const patientSex = sex === "Female" ? "Female" : sex === "Male" ? "Male" : sex;

  // Year-over-year RAF comparison
  const historyYears = history?.history || history?.scores || [];
  const currentYear = new Date().getFullYear();
  const currentYearScore = historyYears.find?.((h: any) => h.year === currentYear);
  const prevYearScore = historyYears.find?.((h: any) => h.year === currentYear - 1);
  const yoyChange = (rafScore != null && prevYearScore?.raf_score != null)
    ? rafScore - prevYearScore.raf_score : null;

  // Revenue impact estimate (average MA payment ~$1,000/month per 1.0 RAF)
  const annualRevenueImpact = rafScore != null ? rafScore * 12000 : null;

  // Risk level
  const riskLevel = rafScore == null ? "Unknown"
    : rafScore >= 3.0 ? "High" : rafScore >= 1.5 ? "Medium" : "Low";
  const riskColor = riskLevel === "High" ? C.red600
    : riskLevel === "Medium" ? C.amber600 : C.emerald600;
  const riskBg = riskLevel === "High" ? C.red50
    : riskLevel === "Medium" ? C.amber50 : C.emerald50;
  const riskBorder = riskLevel === "High" ? C.red100
    : riskLevel === "Medium" ? C.amber100 : C.emerald100;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
      {/* ---- RAF Score Highlight Card ---- */}
      <Card style={{ overflow: "hidden" }}>
        <div style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr 1fr 1fr",
          gap: 0,
        }}>
          {/* Large RAF Score */}
          <div style={{
            display: "flex", flexDirection: "column", alignItems: "center",
            justifyContent: "center", padding: "24px 16px",
            borderRight: `1px solid ${C.slate100}`,
          }}>
            <div style={{
              fontSize: 10, fontWeight: 600, textTransform: "uppercase",
              letterSpacing: "0.08em", color: C.slate400, marginBottom: 8,
            }}>
              RAF Score
            </div>
            <div style={{
              fontSize: 42, fontWeight: 800, fontFamily: "monospace", lineHeight: 1,
              color: rafScore != null ? rafScoreColor(rafScore) : C.slate300,
              animation: "raf-count-up 0.6s ease-out",
            }}>
              {rafScore != null ? Number(rafScore).toFixed(3) : "--"}
            </div>
            {yoyChange !== null && (
              <div style={{
                display: "flex", alignItems: "center", gap: 4, marginTop: 8,
                fontSize: 12, fontWeight: 600,
                color: yoyChange > 0 ? C.emerald600 : yoyChange < 0 ? C.red600 : C.slate400,
              }}>
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                  {yoyChange >= 0
                    ? <polyline points="18 15 12 9 6 15" />
                    : <polyline points="6 9 12 15 18 9" />}
                </svg>
                {yoyChange > 0 ? "+" : ""}{yoyChange.toFixed(3)} vs {currentYear - 1}
              </div>
            )}
          </div>

          {/* Risk Level Badge */}
          <div style={{
            display: "flex", flexDirection: "column", alignItems: "center",
            justifyContent: "center", padding: "24px 16px",
            borderRight: `1px solid ${C.slate100}`,
          }}>
            <div style={{
              fontSize: 10, fontWeight: 600, textTransform: "uppercase",
              letterSpacing: "0.08em", color: C.slate400, marginBottom: 8,
            }}>
              Risk Level
            </div>
            <span style={{
              display: "inline-flex", alignItems: "center", gap: 6,
              padding: "8px 20px", borderRadius: 999,
              background: riskBg, border: `1px solid ${riskBorder}`,
              color: riskColor, fontSize: 16, fontWeight: 700,
              animation: "raf-pulse 2s ease-in-out 1",
            }}>
              <span style={{
                width: 10, height: 10, borderRadius: "50%", background: riskColor,
              }} />
              {riskLevel}
            </span>
          </div>

          {/* Revenue Impact */}
          <div style={{
            display: "flex", flexDirection: "column", alignItems: "center",
            justifyContent: "center", padding: "24px 16px",
            borderRight: `1px solid ${C.slate100}`,
          }}>
            <div style={{
              fontSize: 10, fontWeight: 600, textTransform: "uppercase",
              letterSpacing: "0.08em", color: C.slate400, marginBottom: 8,
            }}>
              Est. Annual Revenue
            </div>
            <div style={{
              fontSize: 28, fontWeight: 700, color: C.slate900, lineHeight: 1,
              animation: "raf-count-up 0.6s ease-out 0.2s both",
            }}>
              {annualRevenueImpact != null
                ? `$${Math.round(annualRevenueImpact).toLocaleString()}`
                : "--"}
            </div>
            <div style={{ fontSize: 11, color: C.slate400, marginTop: 4 }}>
              Based on RAF x $12K/yr
            </div>
          </div>

          {/* HCC Conditions */}
          <div style={{
            display: "flex", flexDirection: "column", alignItems: "center",
            justifyContent: "center", padding: "24px 16px",
          }}>
            <div style={{
              fontSize: 10, fontWeight: 600, textTransform: "uppercase",
              letterSpacing: "0.08em", color: C.slate400, marginBottom: 8,
            }}>
              HCC Conditions
            </div>
            <div style={{
              fontSize: 28, fontWeight: 700, color: C.slate900, lineHeight: 1,
              animation: "raf-count-up 0.6s ease-out 0.1s both",
            }}>
              {hccCount}
            </div>
            <div style={{ fontSize: 11, color: C.slate400, marginTop: 4 }}>
              {isDemoOnly ? "Demographics only" : "Mapped conditions"}
            </div>
          </div>
        </div>
      </Card>
      {/* Analysis Status Banner */}
      {isDemoOnly && (
        <div style={{
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
              This RAF score ({rafScore !== null ? Number(rafScore).toFixed(3) : "—"}) is calculated from demographics only
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
        <div style={{
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
            {(breakdown?.interaction_score ?? 0) > 0 ? ` + interactions (${Number(breakdown.interaction_score).toFixed(3)})` : ""}.
          </div>
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
      <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
        {/* Active Problems */}
        <Card noPadding>
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
              (problems?.problems || problems || []).length || undefined
            }
          />
          <div style={{ padding: "0 0 0 0" }}>
            {problemsLoading ? (
              <SectionLoader />
            ) : !problems?.problems?.length && !problems?.length ? (
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
                {(problems?.problems || problems || [])
                  .slice(0, 15)
                  .map((p: any, i: number) => (
                    <div
                      key={i}
                      style={{
                        display: "grid",
                        gridTemplateColumns: "1fr 140px 120px",
                        padding: "10px 20px",
                        borderBottom: `1px solid ${C.slate100}`,
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
        <Card noPadding>
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
                {encounters.encounters.slice(0, 5).map((enc: any) => {
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
        <Card noPadding>
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
            ) : !recapture?.gaps?.length && !recapture?.length ? (
              <EmptyState
                title="No recapture gaps"
                description="All conditions appear to be documented for the current year"
              />
            ) : (
              <div>
                {(recapture?.gaps || recapture || []).map(
                  (gap: any, i: number) => (
                    <div
                      key={i}
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
      <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
        {/* Demographics */}
        <Card>
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
                  profile?.demographics?.race || patient?.race || "\u2014"
                }
              />
              <DataRow
                label="Ethnicity"
                value={
                  profile?.demographics?.ethnicity ||
                  patient?.ethnicity ||
                  "\u2014"
                }
              />
              <DataRow
                label="Language"
                value={
                  profile?.demographics?.language ||
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
                  profile?.demographics?.address ||
                  "\u2014"
                }
              />
              <DataRow
                label="Phone"
                value={
                  patient?.phone_home ||
                  patient?.phone_cell ||
                  profile?.demographics?.phone ||
                  "\u2014"
                }
              />
            </div>
          )}
        </Card>

        {/* Insurance */}
        <Card>
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
                value={profile?.enrollment?.plan_type || "\u2014"}
              />
              <DataRow
                label="Dual Status"
                value={profile?.enrollment?.dual_status ?? "\u2014"}
              />
              <DataRow
                label="OREC"
                value={profile?.enrollment?.orec ?? "\u2014"}
              />
              <DataRow
                label="Enrolled Since"
                value={formatDate(profile?.enrollment?.start_date)}
              />
            </div>
          )}
        </Card>

        {/* Data Completeness */}
        <Card>
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
            <DataCompletenessChecklist profile={profile} />
          )}
        </Card>
      </div>
    </div>
    </div>
  );
}

function DataCompletenessChecklist({ profile }: { profile: any }) {
  const completeness = profile?.data_completeness;

  const fieldLabelMap: Record<string, string> = {
    has_billing: "Billing",
    has_problems: "Problems",
    has_clinical_notes: "Clinical Notes",
    has_vitals: "Vitals",
    has_labs: "Labs",
    has_immunizations: "Immunizations",
    has_insurance: "Insurance",
  };

  const sections = completeness
    ? Object.entries(completeness)
        .filter(([key]) => key !== "completeness_pct")
        .map(([key, val]: [string, any]) => ({
          label: fieldLabelMap[key] || key.replace(/^has_/, "").replace(/_/g, " "),
          present:
            val === true || val > 0 || (typeof val === "object" && val !== null),
        }))
    : [
        { label: "Billing", present: !!profile?.billing },
        {
          label: "Problems",
          present: (profile?.problems?.length ?? 0) > 0,
        },
        { label: "Clinical Notes", present: (profile?.encounters?.length ?? 0) > 0 },
        { label: "Vitals", present: (profile?.vitals?.length ?? 0) > 0 },
        { label: "Labs", present: (profile?.labs?.length ?? 0) > 0 },
        {
          label: "Immunizations",
          present: (profile?.immunizations?.length ?? 0) > 0,
        },
        {
          label: "Insurance",
          present: !!profile?.enrollment || !!profile?.insurance,
        },
      ];

  const pct = completeness?.completeness_pct != null
    ? Math.round(completeness.completeness_pct)
    : sections.length > 0
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
}: any) {
  const [expandedHcc, setExpandedHcc] = useState<string | null>(null);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
      {/* Score Breakdown: 4 metric boxes */}
      <div>
        <SectionHeader title="Score Breakdown" />
        {breakdownLoading ? (
          <SectionLoader label="Loading breakdown..." />
        ) : !breakdown ? (
          <Card>
            <EmptyState title="No RAF breakdown available" />
          </Card>
        ) : (
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(4, 1fr)",
              gap: 16,
            }}
          >
            {[
              {
                label: "Demographic",
                value:
                  breakdown.demographic_score ??
                  breakdown.demographic_base ??
                  "\u2014",
                color: C.slate700,
              },
              {
                label: "Disease",
                value:
                  breakdown.disease_score ??
                  breakdown.disease_coefficients ??
                  "\u2014",
                color: C.blue600,
              },
              {
                label: "Interaction",
                value:
                  breakdown.interaction_score ??
                  breakdown.interaction_terms ??
                  0,
                color: C.purple600,
              },
              {
                label: "Total",
                value: rafScore ?? breakdown.total_raf ?? "\u2014",
                color:
                  rafScore !== null ? rafScoreColor(rafScore) : C.slate900,
                highlight: true,
              },
            ].map((m) => (
              <div
                key={m.label}
                style={{
                  background: m.highlight ? C.slate100 : C.white,
                  border: `1px solid ${m.highlight ? C.slate300 : C.slate200}`,
                  borderRadius: 12,
                  padding: 20,
                  textAlign: "center",
                }}
              >
                <div
                  style={{
                    fontSize: 11,
                    fontWeight: 600,
                    textTransform: "uppercase",
                    letterSpacing: "0.05em",
                    color: C.slate400,
                    marginBottom: 8,
                  }}
                >
                  {m.label}
                </div>
                <div
                  style={{
                    fontSize: 28,
                    fontWeight: 700,
                    fontFamily: "monospace",
                    color: m.color,
                    lineHeight: 1,
                  }}
                >
                  {typeof m.value === "number" ? m.value.toFixed(3) : m.value}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* HCC List */}
      <Card noPadding>
        <SectionHeader
          title="HCC Conditions"
          count={breakdown?.hcc_details?.length}
        />
        {breakdownLoading ? (
          <SectionLoader />
        ) : !breakdown?.hcc_details?.length ? (
          <EmptyState title="No HCC conditions found" />
        ) : (
          <div>
            {breakdown.hcc_details.map((hcc: any, i: number) => {
              const code = hcc.hcc_code || hcc.code;
              const icdCodes = hcc.icd10_codes || hcc.supporting_icd10s || [];
              const meatComp = hcc.meat_completeness || {};
              const meatEvidence = meatComp.m || meatComp.e || meatComp.a || meatComp.t ? {
                monitor: meatComp.m ? "Yes" : "",
                evaluate: meatComp.e ? "Yes" : "",
                assess: meatComp.a ? "Yes" : "",
                treat: meatComp.t ? "Yes" : "",
              } : (hcc.meat_evidence || null);
              return (
                <div
                  key={i}
                  style={{
                    borderTop: i === 0 ? `1px solid ${C.slate200}` : "none",
                    borderBottom: `1px solid ${C.slate100}`,
                    padding: "16px 20px",
                  }}
                >
                  {/* HCC Header Row */}
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                      <span style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", minWidth: 44, padding: "4px 12px", borderRadius: 8, fontSize: 14, fontWeight: 800, fontFamily: "monospace", background: C.blue50, color: C.blue600, border: `1.5px solid ${C.blue100}` }}>
                        {code}
                      </span>
                      <span style={{ fontSize: 15, fontWeight: 600, color: C.slate800 }}>
                        {hcc.hcc_label || hcc.label || "\u2014"}
                      </span>
                    </div>
                    <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
                      <MeatDots evidence={meatEvidence} />
                      <span style={{ fontSize: 16, fontFamily: "monospace", fontWeight: 800, color: C.blue600 }}>
                        +{Number(hcc.coefficient || hcc.hcc_coefficient || breakdown.disease_score || 0).toFixed(3)}
                      </span>
                    </div>
                  </div>

                  {/* ICD-10 Codes — always visible */}
                  {icdCodes.length > 0 && (
                    <div style={{ marginBottom: 10 }}>
                      <div style={{ fontSize: 11, fontWeight: 600, color: C.slate400, marginBottom: 6, textTransform: "uppercase", letterSpacing: "0.05em" }}>
                        Supporting ICD-10 Codes
                      </div>
                      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                        {icdCodes.map((icd: any, j: number) => {
                          const icdCode = typeof icd === "string" ? icd : icd.code || icd.icd10_code;
                          return (
                            <span key={j} style={{ display: "inline-block", padding: "4px 10px", borderRadius: 6, fontSize: 12, fontWeight: 700, fontFamily: "monospace", background: "#F0FDF4", color: "#166534", border: "1px solid #BBF7D0" }}>
                              {icdCode}
                            </span>
                          );
                        })}
                      </div>
                    </div>
                  )}

                  {/* MEAT Compliance Detail */}
                  <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
                    <div style={{ fontSize: 12, color: C.slate500 }}>
                      <span style={{ fontWeight: 600 }}>Status:</span>{" "}
                      <span style={{ color: hcc.meat_status === "complete" ? "#10B981" : hcc.meat_status === "partial" ? "#F59E0B" : "#EF4444", fontWeight: 600 }}>
                        {hcc.meat_status === "complete" ? "Complete (4/4)" : hcc.meat_status === "partial" ? `Partial (${meatComp.meat_score || 0}/4)` : "Missing — run analysis"}
                      </span>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </Card>

      {/* Score History (CSS bars) */}
      <Card>
        <SectionHeader title="Score History" />
        {historyLoading ? (
          <SectionLoader />
        ) : (
          <RAFHistoryBars history={history} />
        )}
      </Card>
      {/* Recapture Gaps */}
      <Card noPadding>
        <SectionHeader title="Recapture Gaps" />
        {recaptureLoading ? (
          <SectionLoader />
        ) : !recapture?.gaps?.length && !recapture?.length ? (
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
            {(recapture?.gaps || recapture || []).map(
              (gap: any, i: number) => (
                <div
                  key={i}
                  style={{
                    display: "grid",
                    gridTemplateColumns: "1fr 100px 100px 100px",
                    padding: "10px 20px",
                    borderBottom: `1px solid ${C.slate100}`,
                  }}
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

function RAFHistoryBars({ history }: { history: any }) {
  const scores = history?.scores || history?.history || history;
  if (!scores || !Array.isArray(scores) || scores.length === 0) {
    return <EmptyState title="No historical scores available" />;
  }

  const maxScore = Math.max(
    ...scores.map((s: any) => s.raf_score || s.score || 0),
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
      {scores.map((entry: any, i: number) => {
        const score = entry.raf_score || entry.score || 0;
        const year = entry.year || entry.measurement_year;
        const heightPct = Math.max((score / maxScore) * 100, 8);
        const color = rafScoreColor(score);

        return (
          <div
            key={i}
            style={{
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              gap: 6,
              flex: 1,
            }}
          >
            <span
              style={{
                fontSize: 12,
                fontWeight: 700,
                fontFamily: "monospace",
                color,
              }}
            >
              {score.toFixed(3)}
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
}: any) {
  const [activeSection, setActiveSection] = useState("medications");

  const sections = [
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
        {activeSection === "medications" && (
          <ClinicalSection title="Active Medications" loading={medsLoading}>
            {!meds?.medications?.length && !meds?.length ? (
              <EmptyState title="No active medications" />
            ) : (
              <SimpleTable
                headers={["Drug", "Dose", "Frequency", "Date"]}
                rows={(meds?.medications || meds || []).map((m: any) => [
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
            title="Vitals-Derived Findings"
            loading={vitalsLoading}
          >
            {!vitalsSuspects?.suspects?.length && !vitalsSuspects?.length ? (
              <EmptyState title="No vitals-derived findings" />
            ) : (
              <FindingsList
                items={(
                  vitalsSuspects?.suspects ||
                  vitalsSuspects ||
                  []
                ).map((s: any) => ({
                  name: s.condition || s.finding || "\u2014",
                  detail: s.evidence || s.rationale || s.detail || "",
                  icd10: s.icd10_code,
                }))}
              />
            )}
          </ClinicalSection>
        )}

        {activeSection === "labs" && (
          <ClinicalSection
            title="Lab-Derived Suspect Conditions"
            loading={labsLoading}
          >
            {!labSuspects?.suspects?.length && !labSuspects?.length ? (
              <EmptyState title="No lab-derived suspects" />
            ) : (
              <FindingsList
                items={(labSuspects?.suspects || labSuspects || []).map(
                  (s: any) => ({
                    name: s.condition || s.finding || "\u2014",
                    detail: s.evidence || s.rationale || "",
                    icd10: s.icd10_code,
                    hcc: s.hcc_code,
                  })
                )}
              />
            )}
          </ClinicalSection>
        )}

        {activeSection === "allergies" && (
          <ClinicalSection title="Allergies" loading={allergiesLoading}>
            {!allergies?.allergies?.length && !allergies?.length ? (
              <EmptyState title="No allergies documented" />
            ) : (
              <FindingsList
                items={(allergies?.allergies || allergies || []).map(
                  (a: any) => ({
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
            {!immunizations?.immunizations?.length &&
            !immunizations?.length ? (
              <EmptyState title="No immunizations documented" />
            ) : (
              <SimpleTable
                headers={["Vaccine", "Date"]}
                rows={(
                  immunizations?.immunizations ||
                  immunizations ||
                  []
                ).map((imm: any) => [
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
            {!familyHistory?.history?.length && !familyHistory?.length ? (
              <EmptyState title="No family history documented" />
            ) : (
              <FindingsList
                items={(
                  familyHistory?.history ||
                  familyHistory ||
                  []
                ).map((fh: any) => ({
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
            {!sdoh?.factors?.length &&
            !sdoh?.length &&
            !sdoh?.sdoh ? (
              <EmptyState title="No SDOH data available" />
            ) : (
              <FindingsList
                items={(sdoh?.factors || sdoh?.sdoh || sdoh || []).map(
                  (s: any) => ({
                    name:
                      s.factor || s.category || s.title || "\u2014",
                    detail: s.detail || "",
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
            {!medGaps?.gaps?.length && !medGaps?.length ? (
              <EmptyState title="No medication gaps identified" />
            ) : (
              <FindingsList
                items={(medGaps?.gaps || medGaps || []).map((g: any) => ({
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
    <Card noPadding>
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
          padding: "8px 20px",
          background: C.slate100,
          borderTop: `1px solid ${C.slate200}`,
          borderBottom: `1px solid ${C.slate200}`,
          gap: 16,
        }}
      >
        {headers.map((h) => (
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
      {rows.map((row, i) => (
        <div
          key={i}
          style={{
            display: "grid",
            gridTemplateColumns: headers
              .map((_, idx) => (idx === 0 ? "1fr" : "auto"))
              .join(" "),
            padding: "10px 20px",
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
          key={i}
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
function EncountersTab({ encounters, encountersLoading, analyzeMutation, lastAnalysisResult }: any) {
  const [expandedEnc, setExpandedEnc] = useState<number | null>(null);

  if (encountersLoading) return <SectionLoader label="Loading encounters..." />;
  if (!encounters?.encounters?.length) {
    return (
      <Card>
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
      </Card>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      {encounters.encounters.map((enc: any) => {
        const isExpanded = expandedEnc === enc.encounter_id;
        const hasNotes = !!enc.notes || !!enc.has_notes;
        const analysis = enc.analysis || enc.cached_analysis || lastAnalysisResult?.[enc.encounter_id];
        const diagnoses = analysis?.diagnoses || [];
        const hccFromAnalysis = diagnoses.filter(
          (d: any) => d.hcc_code || d.hcc || d.hcc_mapping?.hcc_code
        ).length;

        return (
          <Card key={enc.encounter_id} noPadding style={{ overflow: "hidden" }}>
            {/* Header row */}
            <button
              onClick={() =>
                setExpandedEnc(isExpanded ? null : enc.encounter_id)
              }
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
            </button>

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
                    <div
                      style={{
                        fontSize: 12,
                        fontWeight: 600,
                        color: C.slate500,
                        marginBottom: 10,
                        textTransform: "uppercase",
                        letterSpacing: "0.05em",
                      }}
                    >
                      Analysis Results
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
                    {diagnoses.map((dx: any, i: number) => {
                      const hcc =
                        dx.hcc_code ||
                        dx.hcc ||
                        dx.hcc_mapping?.hcc_code;
                      const confidence =
                        dx.confidence_score ?? dx.confidence ?? 0;
                      return (
                        <div
                          key={i}
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
                            <MeatDots evidence={dx.meat_evidence} />
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
                    Run analysis to extract diagnoses from this
                    encounter&apos;s notes
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
  patientAge,
  patientSex,
}: any) {
  // Age-specific HCC context
  const ageContext = (() => {
    if (patientAge == null) return null;
    const notes: string[] = [];
    if (patientAge >= 65) notes.push("Medicare age-in: eligible for CMS-HCC V24/V28 risk adjustment");
    if (patientAge >= 75) notes.push("Age 75+ increases demographic RAF factor significantly");
    if (patientAge >= 85) notes.push("Age 85+ has highest demographic weight in CMS-HCC models");
    if (patientAge < 65) notes.push("Under 65: likely ESRD or disabled enrollment model");
    return notes;
  })();

  if (suspectsLoading) {
    return <SectionLoader label="Loading suspect conditions..." />;
  }

  const suspectList = suspects?.suspects || suspects || [];
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
      {/* Patient Clinical Context Banner */}
      {(patientAge != null || patientSex) && (
        <div style={{
          background: C.blue50, border: `1px solid ${C.blue100}`, borderRadius: 10,
          padding: "12px 16px", display: "flex", alignItems: "flex-start", gap: 12,
        }}>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke={C.blue600} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ marginTop: 2, flexShrink: 0 }}>
            <circle cx="12" cy="12" r="10" /><line x1="12" y1="16" x2="12" y2="12" /><line x1="12" y1="8" x2="12.01" y2="8" />
          </svg>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: C.blue600, marginBottom: 4 }}>
              Patient Context: {patientAge != null ? `${patientAge} yrs` : ""}{patientAge != null && patientSex ? ", " : ""}{patientSex || ""}
            </div>
            {ageContext && ageContext.length > 0 && (
              <ul style={{ margin: 0, paddingLeft: 16, fontSize: 12, color: C.slate600, lineHeight: 1.6 }}>
                {ageContext.map((note, i) => <li key={i}>{note}</li>)}
              </ul>
            )}
          </div>
        </div>
      )}
      {suspectList.map((s: any) => {
        const confidence = s.confidence_score ?? s.confidence ?? 0;
        return (
          <Card key={s.id} style={{ padding: 20 }}>
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
                    <MeatDots evidence={s.meat_evidence} />
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
function AuditTab({ audits, auditsLoading, auditMutation }: any) {
  const [auditYear, setAuditYear] = useState(new Date().getFullYear());

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
      {/* Generate section */}
      <Card>
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
              onClick={() => auditMutation.mutate()}
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
      <Card noPadding>
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
            {audits.packages.map((pkg: any) => (
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
                  <a
                    href={getAuditDownloadUrl(pkg.id)}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      gap: 4,
                      fontSize: 12,
                      fontWeight: 600,
                      color: C.blue600,
                      textDecoration: "none",
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
                  </a>
                </span>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
