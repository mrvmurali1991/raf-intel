"use client";

import React, { use, useState, useRef, useEffect, useMemo, startTransition } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { Printer, MoreHorizontal } from "lucide-react";
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
  markRafDirty,
  generateAudit,
  downloadRadvPacket,
  acceptSuspect,
  dismissSuspect,
  analyzeEncounter,
  batchAnalysis,
  getJobStatus,
  getPatientDocuments,
} from "@/lib/api";
import { ModelComparison } from "@/components/model-comparison";
import { AIHealthBanner } from "@/components/AIHealthBanner";
import { Breadcrumb } from "@/components/Breadcrumb";
// Tooltip + RiskGauge/ProgressBar used by sub-components; kept for legacy imports
// that may re-emerge if tabs re-introduce inline KPI widgets.
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
import { RAFCentralTab } from "./components/RAFCentralTab";
import { PatientV28ImpactPanel } from "./components/PatientV28ImpactPanel";
import { PatientHedisStrip } from "./components/PatientHedisStrip";
import { HeroStrip } from "./components/HeroStrip";
import { RiskSummaryCard } from "./components/RiskSummaryCard";
import { ActionItemsPanel } from "./components/ActionItemsPanel";

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
  const router = useRouter();
  const searchParams = useSearchParams();
  // Initialise from URL so refresh / shared links restore the correct tab.
  // Sub-pill state for the merged "RAF" tab (item B8)
  const [rafSubTab, setRafSubTab] = useState<"central" | "details" | "comparison" | "v28-impact">(() => {
    const t = searchParams.get("tab");
    if (t === "rafdetails" || t === "raf") return "details";
    if (t === "modelcomparison" || t === "models") return "comparison";
    if (t === "v28-impact" || t === "v28impact") return "v28-impact";
    return "central";
  });

  const [activeTab, setActiveTab] = useState(() => {
    const t = searchParams.get("tab");
    // Legacy aliases → new tab names
    if (
      t === "rafcentral" ||
      t === "rafdetails" ||
      t === "modelcomparison" ||
      t === "v28-impact" ||
      t === "v28impact"
    ) {
      return "raf";
    }
    // suspects / review queue → meat evidence tab
    if (t === "suspects" || t === "reviewqueue") return "meat";
    // clinical → overview (clinical data merged into overview context)
    if (t === "clinical") return "overview";
    return t ?? "overview";
  });

  // Overflow menu open state for More Actions button
  const [moreMenuOpen, setMoreMenuOpen] = useState(false);
  const moreMenuRef = React.useRef<HTMLDivElement>(null);
  const moreMenuTriggerRef = React.useRef<HTMLButtonElement>(null);
  const moreMenuItemsRef = React.useRef<Array<HTMLButtonElement | null>>([]);
  // Track whether the previous close was triggered by the keyboard so we
  // know to return focus to the trigger (mouse close should not steal focus).
  const moreMenuKeyboardCloseRef = React.useRef(false);

  // Close on outside click (mouse). Does not restore focus — pointer users
  // typically don't expect their focus to teleport back to the trigger.
  useEffect(() => {
    if (!moreMenuOpen) return;
    const handler = (e: MouseEvent) => {
      if (moreMenuRef.current && !moreMenuRef.current.contains(e.target as Node)) {
        setMoreMenuOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [moreMenuOpen]);

  // When the menu opens, focus the first item so keyboard users land inside.
  // When it closes via the keyboard (Escape / Tab-out), restore focus to the
  // trigger button. The keyboard-close flag is set by the keydown handler so
  // we don't fight click-outside (mouse) which intentionally leaves focus alone.
  useEffect(() => {
    if (moreMenuOpen) {
      const first = moreMenuItemsRef.current.find((b) => b && !b.disabled);
      first?.focus();
    } else if (moreMenuKeyboardCloseRef.current) {
      moreMenuKeyboardCloseRef.current = false;
      moreMenuTriggerRef.current?.focus();
    }
  }, [moreMenuOpen]);

  // Roving-style focus + standard menu keyboard semantics.
  // ArrowDown/ArrowUp cycle through items, Home/End jump to ends,
  // Escape closes & restores focus, Tab closes (focus falls through naturally).
  const handleMoreMenuKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    const items = moreMenuItemsRef.current.filter(
      (b): b is HTMLButtonElement => !!b && !b.disabled
    );
    if (items.length === 0) return;
    const activeIdx = items.findIndex((b) => b === document.activeElement);
    switch (e.key) {
      case "ArrowDown": {
        e.preventDefault();
        const next = activeIdx < 0 ? 0 : (activeIdx + 1) % items.length;
        items[next]?.focus();
        break;
      }
      case "ArrowUp": {
        e.preventDefault();
        const prev = activeIdx <= 0 ? items.length - 1 : activeIdx - 1;
        items[prev]?.focus();
        break;
      }
      case "Home": {
        e.preventDefault();
        items[0]?.focus();
        break;
      }
      case "End": {
        e.preventDefault();
        items[items.length - 1]?.focus();
        break;
      }
      case "Escape": {
        e.preventDefault();
        moreMenuKeyboardCloseRef.current = true;
        setMoreMenuOpen(false);
        break;
      }
      case "Tab": {
        // Tab out of the menu closes it but lets default focus movement proceed.
        // We do NOT restore focus to the trigger here — the user is leaving on
        // purpose and expects to land on the next/previous tabbable element.
        setMoreMenuOpen(false);
        break;
      }
      default:
        break;
    }
  };

  // Write-through: keep ?tab= in sync without adding browser history entries.
  // The tab-content swap is wrapped in startTransition so React can keep
  // the previous tab interactive while the new one mounts — smoother feel
  // than a hard re-render. URL update stays outside (urgent navigation).
  const handleTabChange = (tab: string) => {
    // Resolve legacy tab aliases to new IA
    let resolvedTab = tab;
    if (tab === "rafcentral") { resolvedTab = "raf"; setRafSubTab("central"); }
    else if (tab === "rafdetails") { resolvedTab = "raf"; setRafSubTab("details"); }
    else if (tab === "modelcomparison" || tab === "models") { resolvedTab = "raf"; setRafSubTab("comparison"); }
    else if (tab === "suspects" || tab === "reviewqueue") { resolvedTab = "meat"; }
    else if (tab === "clinical") { resolvedTab = "overview"; }
    startTransition(() => {
      setActiveTab(resolvedTab);
    });
    const params = new URLSearchParams(searchParams.toString());
    params.set("tab", resolvedTab);
    router.replace(`?${params.toString()}`);
  };
  const [selectedYear, setSelectedYear] = useState(new Date().getFullYear());
  const [lastAnalysisResult, setLastAnalysisResult] = useState<Record<number, AnalysisResult>>({});

  // Privacy mode masks patient name + MRN in the always-visible sticky
  // header for shoulder-surf-prone settings (open clinic monitors, shared
  // screens during demos). Toggled via Ctrl/Cmd+Shift+P or the eye icon
  // next to the patient name. Persisted to localStorage so a user's
  // preference survives navigation. UX-review #1 / round-3 carry-over.
  const [privacyMode, setPrivacyMode] = useState<boolean>(() => {
    if (typeof window === "undefined") return false;
    return window.localStorage.getItem("raf_privacy_mode") === "1";
  });
  useEffect(() => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem("raf_privacy_mode", privacyMode ? "1" : "0");
  }, [privacyMode]);
  useEffect(() => {
    if (typeof window === "undefined") return;
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.shiftKey && (e.key === "P" || e.key === "p")) {
        // Skip when focus is inside a typing surface — avoids clobbering
        // browser-native shortcuts (Print, Find) and user text input.
        const t = e.target as HTMLElement | null;
        const tag = (t?.tagName || "").toLowerCase();
        const isEditable =
          tag === "input" || tag === "textarea" || tag === "select" ||
          t?.isContentEditable === true;
        if (isEditable) return;
        e.preventDefault();
        setPrivacyMode((v) => !v);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

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

  // ---- Tab-specific queries ----
  const medsQ = useQuery({
    queryKey: ["patient-meds", pid, selectedYear],
    queryFn: () => getPatientMedications(pid, selectedYear),
    staleTime: 30_000,
    enabled: activeTab === "overview",
  });

  const recaptureQ = useQuery({
    queryKey: ["patient-recapture", pid, selectedYear],
    queryFn: () => getPatientRecaptureGaps(pid, selectedYear),
    staleTime: 30_000,
    enabled: activeTab === "raf" || activeTab === "overview",
  });

  const labSuspectsQ = useQuery({
    queryKey: ["patient-lab-suspects", pid, selectedYear],
    queryFn: () => getPatientLabSuspects(pid, selectedYear),
    staleTime: 30_000,
    // clinical data is now shown in overview tab
    enabled: activeTab === "overview",
  });

  const vitalsSuspectsQ = useQuery({
    queryKey: ["patient-vitals-suspects", pid, selectedYear],
    queryFn: () => getPatientVitalsSuspects(pid, selectedYear),
    staleTime: 30_000,
    enabled: activeTab === "overview",
  });

  const allergiesQ = useQuery({
    queryKey: ["patient-allergies", pid],
    queryFn: () => getPatientAllergies(pid),
    staleTime: 30_000,
    enabled: activeTab === "overview",
  });

  const immunizationsQ = useQuery({
    queryKey: ["patient-immunizations", pid],
    queryFn: () => getPatientImmunizations(pid),
    staleTime: 30_000,
    enabled: activeTab === "overview",
  });

  const familyHistoryQ = useQuery({
    queryKey: ["patient-family-history", pid],
    queryFn: () => getPatientFamilyHistory(pid),
    staleTime: 30_000,
    enabled: activeTab === "overview",
  });

  const sdohQ = useQuery({
    queryKey: ["patient-sdoh", pid],
    queryFn: () => getPatientSdoh(pid),
    staleTime: 30_000,
    enabled: activeTab === "overview",
  });

  const medGapsQ = useQuery({
    queryKey: ["patient-med-gaps", pid, selectedYear],
    queryFn: () => getPatientMedicationGaps(pid, selectedYear),
    staleTime: 30_000,
    enabled: activeTab === "overview",
  });

  const auditsQ = useQuery({
    queryKey: ["patient-audits", pid],
    queryFn: () => getAuditPackages(Number(pid)),
    enabled: activeTab === "audit",
  });

  const documentsQ = useQuery({
    queryKey: ["patient-documents", pid],
    queryFn: () => getPatientDocuments(pid),
    enabled: activeTab === "documents",
  });

  // ---- Mutations ----
  // RAF score is now async; breakdown query is the source of truth.
  // The old `lastCalcResult` (filled from sync /calculate response) is
  // retired — RAFTab falls back to `breakdown` when this is null.
  const lastCalcResult: { raf_score: number } | null = null;

  const auditMutation = useMutation({
    mutationFn: (year?: number) => generateAudit(Number(pid), { year: year ?? selectedYear }),
    onSuccess: () => {
      toast.success("Audit Generated", "Audit package is ready.");
      queryClient.invalidateQueries({ queryKey: ["patient-audits", pid] });
    },
    onError: () => toast.error("Error", "Failed to generate audit package."),
  });

  // RADV audit-packet PDF export — calls GET /api/radv/{pid}/packet
  // and downloads the response blob directly. Uses the currently-selected
  // year picker (same control used by every other tab on this page).
  const radvPacketMutation = useMutation({
    mutationFn: (year?: number) =>
      downloadRadvPacket(Number(pid), year ?? selectedYear),
    onSuccess: () => {
      toast.success("RADV Packet Ready", "Downloaded audit PDF.");
    },
    onError: (err: unknown) => {
      const e = err as { response?: { data?: { detail?: string } }; message?: string };
      toast.error(
        "RADV Packet Failed",
        e?.response?.data?.detail || e?.message || "Could not build RADV packet.",
      );
    },
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
        `Found ${dxCount} diagnoses, ${hccCnt} HCC codes. Recalculating RAF…`
      );
      // Async RAF recompute via inbox — SSE `raf_updated` will refresh the
      // RAF caches once the worker finishes.
      try {
        await markRafDirty(pid);
      } catch { /* non-fatal; analyze_encounter also marks dirty server-side */ }
      // Analysis-driven caches that SSE does not cover:
      queryClient.invalidateQueries({ queryKey: ["patient-encounters", pid] });
      queryClient.invalidateQueries({ queryKey: ["patient-suspects", pid, selectedYear] });
      queryClient.invalidateQueries({ queryKey: ["patient-problems", pid, selectedYear] });
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
              `Analyzed ${status.processed ?? (status as unknown as { progress?: number }).progress ?? 0} encounters. Recalculating RAF score…`
            );
            // Async RAF recompute via inbox — SSE updates the RAF caches.
            try {
              await markRafDirty(pid);
            } catch { /* non-fatal */ }
            // Analysis-driven caches that SSE does not cover:
            queryClient.invalidateQueries({ queryKey: ["patient-encounters", pid] });
            queryClient.invalidateQueries({ queryKey: ["patient-suspects", pid, selectedYear] });
            queryClient.invalidateQueries({ queryKey: ["patient-problems", pid, selectedYear] });
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
      !!(profile?.vitals?.latest) || !!(vitalsSuspectsQ.data?.suspects?.length),
      !!((profile as { labs?: { results?: unknown[] } } | undefined)?.labs?.results?.length) || !!(labSuspectsQ.data?.suspects?.length),
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

  // ---- Coder-first tab IA (reorganised) ------------------------------------
  // "Today's action items" (HCC suspects + HEDIS gaps) live above the tabs as
  // a persistent action queue. The "suspects" tab is renamed "MEAT Evidence"
  // to reflect its drill-down role; the review queue is always visible.
  // Legacy aliases: suspects → meat, rafcentral → raf, activity → activity
  const tabs: Array<{ id: string; label: string; badge?: number }> = [
    { id: "overview", label: "Overview" },
    { id: "raf", label: "RAF Detail" },
    { id: "meat", label: "MEAT Evidence" },
    { id: "encounters", label: "Encounters" },
    { id: "documents", label: "Documents" },
    { id: "audit", label: "Audit" },
    { id: "activity", label: "Activity" },
  ];

  // Last encounter date for the hero strip staleness indicator
  const lastVisitDate: string | null = (() => {
    const encs = encountersQ.data?.encounters ?? (Array.isArray(encountersQ.data) ? encountersQ.data : []);
    if (!encs.length) return null;
    const sorted = [...encs].sort((a, b) => {
      const da = new Date(a.encounter_date || a.date || "").getTime();
      const db = new Date(b.encounter_date || b.date || "").getTime();
      return db - da;
    });
    return sorted[0]?.encounter_date || sorted[0]?.date || null;
  })();

  // V28 delta — derive from v28-impact query (lazy: only needed for risk card)
  const v28ImpactQ = useQuery({
    queryKey: ["v28-impact", "patient", pid, selectedYear],
    queryFn: async () => {
      const { default: api } = await import("@/lib/api");
      const res = await api.get(`/api/v28-impact/patient/${pid}`, { params: { year: selectedYear } });
      return res.data as { v24_raf: number; v28_raf: number; raf_delta: number; revenue_delta_annual: number };
    },
    staleTime: 60_000,
    retry: 1,
  });

  // Prior-year RAF from history
  const priorYearRaf: number | null = (() => {
    const entries = history?.scores ?? history?.history ?? [];
    const priorEntry = (entries as Array<{ year?: number; measurement_year?: number; raf_score?: number; score?: number }>)
      .find((e) => (e.year ?? e.measurement_year) === selectedYear - 1);
    return priorEntry?.raf_score ?? priorEntry?.score ?? null;
  })();

  // V28 drawer open state (click on delta metric)
  const [v28DrawerOpen, setV28DrawerOpen] = useState(false);

  // =========================================================================
  // RENDER
  // =========================================================================
  return (
    <div className="dot-grid mesh-pattern" style={{ minHeight: "100vh", background: C.bg }}>
      {/* AI availability warning */}
      <div style={{ padding: "12px 16px 0" }}>
        <AIHealthBanner />
      </div>

      {/* Polite live region — privacy-mode toggle (symmetric for AT) */}
      <div role="status" aria-live="polite" className="sr-only">
        {privacyMode
          ? "Privacy mode enabled. Patient name and MRN are masked."
          : "Privacy mode disabled. Patient name and MRN are visible."}
      </div>

      {/* Breadcrumb */}
      <div style={{ padding: "0 16px" }}>
        <Breadcrumb
          items={[
            { label: "Patients", href: "/patients" },
            {
              label: (() => {
                if (!patientName || patientName === "Loading…") return `Patient ${pid}`;
                if (!privacyMode) return patientName;
                const parts = patientName.trim().split(/\s+/);
                const f = parts[0]?.charAt(0) || "?";
                const l = parts.length > 1 ? parts[parts.length - 1].charAt(0) : "";
                return `${f}${l ? ". " + l + "." : "."}`;
              })(),
            },
          ]}
        />
      </div>

      {/* ================================================================
          HERO STRIP — sticky, always-visible patient identity
          ================================================================ */}
      <HeroStrip
        patient={patient}
        profile={profile}
        pid={pid}
        privacyMode={privacyMode}
        onPrivacyToggle={() => setPrivacyMode((v) => !v)}
        lastVisitDate={lastVisitDate}
      />

      {/* Print-only patient header */}
      <div className="print-header" style={{ display: "none" }}>
        <div style={{ fontSize: 10, color: "#666", marginBottom: 4 }}>RAF Intelligence \u2014 Patient Record</div>
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

      {/* YEAR SELECTOR ROW */}
      <div
        style={{
          background: C.white,
          borderBottom: `1px solid ${C.slate100}`,
          display: "flex",
          alignItems: "center",
          justifyContent: "flex-end",
          padding: "0 24px",
          height: 32,
          gap: 4,
          flexWrap: "wrap",
        }}
      >
        <span style={{ fontSize: 10, fontWeight: 600, color: C.slate400, textTransform: "uppercase", letterSpacing: "0.05em", marginRight: 4 }}>Year</span>
        {Array.from({ length: 3 }, (_, i) => new Date().getFullYear() - i).map((yr) => (
          <button
            key={yr}
            onClick={() => setSelectedYear(yr)}
            style={{
              padding: "3px 10px", fontSize: 11,
              fontWeight: selectedYear === yr ? 700 : 500,
              color: selectedYear === yr ? C.white : C.slate500,
              background: selectedYear === yr ? C.blue600 : "transparent",
              border: selectedYear === yr ? "none" : `1px solid ${C.slate200}`,
              borderRadius: 6, cursor: "pointer", transition: "all 0.15s",
              flexShrink: 0,
            }}
          >
            {yr}
          </button>
        ))}
      </div>

      {/* ================================================================
          RISK SUMMARY CARD — animated count-up, V24\u2192V28 delta, dollar
          ================================================================ */}
      <RiskSummaryCard
        rafScore={rafScore}
        breakdown={breakdown}
        priorYearRaf={priorYearRaf}
        v28Delta={v28ImpactQ.data?.raf_delta ?? null}
        selectedYear={selectedYear}
        onOpenV28Drawer={() => setV28DrawerOpen(true)}
      />

      {/* V28 impact drawer (click on delta in risk card) */}
      {v28DrawerOpen && (
        <>
          <div
            style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.3)", zIndex: 200 }}
            aria-hidden="true"
            onClick={() => setV28DrawerOpen(false)}
          />
          <div
            role="dialog"
            aria-modal="true"
            aria-label="V24 to V28 impact breakdown"
            style={{
              position: "fixed", right: 0, top: 0, bottom: 0, width: 480,
              background: C.white, boxShadow: "-4px 0 24px rgba(0,0,0,0.12)",
              zIndex: 201, overflowY: "auto",
            }}
            onKeyDown={(e) => { if (e.key === "Escape") setV28DrawerOpen(false); }}
          >
            <div style={{ padding: 24 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
                <h2 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: C.slate800 }}>V24 \u2192 V28 Impact</h2>
                <button
                  type="button"
                  autoFocus
                  onClick={() => setV28DrawerOpen(false)}
                  aria-label="Close V28 impact drawer"
                  style={{
                    background: "transparent", border: `1px solid ${C.slate200}`,
                    borderRadius: 6, width: 32, height: 32, cursor: "pointer",
                    display: "flex", alignItems: "center", justifyContent: "center", color: C.slate600,
                  }}
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
                  </svg>
                </button>
              </div>
              <PatientV28ImpactPanel pid={pid} year={selectedYear} />
            </div>
          </div>
        </>
      )}

      {/* ================================================================
          TODAY'S ACTION ITEMS — persistent above tabs (action queue)
          HCC suspects (left 3/4) + HEDIS gaps (right 1/4)
          ================================================================ */}
      <div style={{ padding: "20px 24px 0" }}>
        <ActionItemsPanel
          pid={pid}
          year={selectedYear}
          suspects={suspectsQ.data}
          suspectsLoading={suspectsQ.isLoading}
          acceptMutation={acceptMutation}
          dismissMutation={dismissMutation}
        />
      </div>

      {/* TAB NAVIGATION */}
      <div style={{ background: C.white, borderBottom: `1px solid ${C.slate200}`, padding: "0 24px" }}>
        <div
          className="raf-tabbar-scroll"
          style={{
            display: "flex", gap: 0, alignItems: "center",
            overflowX: "auto", overflowY: "hidden",
            flexWrap: "nowrap", whiteSpace: "nowrap",
            scrollbarWidth: "thin",
          }}
        >
          <div role="tablist" style={{ display: "flex", flexWrap: "nowrap" }}>
            {tabs.map((tab) => (
              <button
                key={tab.id}
                role="tab"
                aria-selected={activeTab === tab.id}
                id={`tab-${tab.id}`}
                onClick={() => handleTabChange(tab.id)}
                style={{
                  padding: "14px 20px", fontSize: 13,
                  fontWeight: activeTab === tab.id ? 600 : 500,
                  color: activeTab === tab.id ? C.blue600 : C.slate500,
                  background: "transparent", border: "none",
                  borderBottom: activeTab === tab.id ? `2px solid ${C.blue600}` : "2px solid transparent",
                  cursor: "pointer", display: "inline-flex", alignItems: "center", gap: 6,
                  transition: "color 0.15s, border-color 0.15s",
                  flexShrink: 0,
                  outline: "none",
                }}
                onFocus={(e) => (e.currentTarget.style.outline = `2px solid ${C.blue600}`)}
                onBlur={(e) => (e.currentTarget.style.outline = "none")}
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

      {/* TAB CONTENT — lazy: each branch only mounts when tab is active */}
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
            setActiveTab={handleTabChange}
            aiAnalysis={aiAnalysis}
            selectedYear={selectedYear}
            meds={medsQ.data}
            labSuspects={labSuspectsQ.data}
            vitalsSuspects={vitalsSuspectsQ.data}
            onRetryProblems={() => queryClient.refetchQueries({ queryKey: ["patient-problems", pid, selectedYear] })}
            onRetryEncounters={() => queryClient.refetchQueries({ queryKey: ["patient-encounters", pid] })}
            onRetryRecapture={() => queryClient.refetchQueries({ queryKey: ["patient-recapture", pid, selectedYear] })}
            onRetryProfile={() => queryClient.refetchQueries({ queryKey: ["patient-profile", pid] })}
          />
        )}
        {activeTab === "raf" && (
          <div>
            {/* Sub-pill navigation for RAF Detail tab */}
            <div style={{ display: "flex", gap: 4, marginBottom: 20 }}>
              {([
                { id: "central" as const, label: "Central" },
                { id: "details" as const, label: "Details" },
                { id: "comparison" as const, label: "Comparison" },
                { id: "v28-impact" as const, label: "V28 Impact" },
              ]).map((pill) => (
                <button
                  key={pill.id}
                  onClick={() => setRafSubTab(pill.id)}
                  style={{
                    padding: "6px 16px", fontSize: 12, fontWeight: rafSubTab === pill.id ? 700 : 500,
                    color: rafSubTab === pill.id ? C.white : C.slate600,
                    background: rafSubTab === pill.id ? C.blue600 : C.white,
                    border: `1px solid ${rafSubTab === pill.id ? C.blue600 : C.slate200}`,
                    borderRadius: 20, cursor: "pointer", transition: "all 0.15s",
                  }}
                >
                  {pill.label}
                </button>
              ))}
            </div>
            {rafSubTab === "central" && <RAFCentralTab pid={pid} year={selectedYear} />}
            {rafSubTab === "details" && (
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
            {rafSubTab === "comparison" && (
              <div style={{ maxWidth: 1100 }}>
                <ModelComparison pid={pid} year={selectedYear} />
              </div>
            )}
            {rafSubTab === "v28-impact" && (
              <div style={{ maxWidth: 1100 }}>
                <PatientV28ImpactPanel pid={pid} year={selectedYear} />
              </div>
            )}
          </div>
        )}
        {/* "meat" tab = deep MEAT Evidence drill-down (replaces old "suspects" tab) */}
        {activeTab === "meat" && (
          <>
            <SuspectsTab
              suspects={suspectsQ.data}
              suspectsLoading={suspectsQ.isLoading}
              acceptMutation={acceptMutation}
              dismissMutation={dismissMutation}
            />
            {/* HEDIS strip — still co-located for PCP visit context */}
            <PatientHedisStrip pid={pid} year={selectedYear} />
          </>
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
        {activeTab === "activity" && <ActivityTab pid={pid} />}
      </div>
    </div>
  );
}
