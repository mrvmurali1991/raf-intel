"use client";

import React, { useState, useMemo, useCallback, useEffect, useRef, useId } from "react";
import dynamic from "next/dynamic";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  registerContextShortcut,
} from "@/lib/keyboard-shortcuts";
import DataQualityBanner from "@/components/DataQualityBanner";
import WorkflowProgressBar from "@/components/WorkflowProgressBar";
import WorkflowHandoffBanner from "@/components/WorkflowHandoffBanner";
import PageAlerts from "@/components/PageAlerts";
import ProblemListWriteBackModal from "@/components/ProblemListWriteBackModal";
import { tokens } from "@/styles/tokens";
import {
  getSuspects,
  acceptSuspect,
  dismissSuspect,
  unacceptSuspect,
  undismissSuspect,
  bulkUpdateSuspects,
} from "@/lib/api";
import type { DBSuspect } from "@/types";
import { useToast } from "@/components/Toast";
import { usePaymentYear, PAYMENT_YEARS } from "@/contexts/payment-year-context";
import { HistoricalPYBanner } from "@/components/HistoricalPYBanner";
import {
  ClipboardList,
  TrendingUp,
  DollarSign,
  Activity,
  Search,
  FileSearch,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  AlertCircle,
  FileDown,
  Check,
  X,
  CheckCircle2,
  XCircle,
  Pill,
  FlaskConical,
  ScanLine,
  Stethoscope,
  Clock,
  Sparkles,
} from "lucide-react";
import { downloadCSV } from "@/lib/csv-export";
import { C, FONT_SYS, FONT_MONO, initialsColor, deriveInitials } from "@/lib/ui-utils";
import { MA_PAYMENT_PER_RAF } from "@/lib/constants";
import FeatureFlag from "@/components/FeatureFlag";
import { KgGapBadge } from "@/components/kg/KgGapBadge";
import { HccChipWithPopover } from "@/components/kg/HccExplainCard";
// ── Dynamic import: defer SuspectDrawer expanded-row detail (~30 kB) ──
// Only loaded when the user clicks a row to expand it.
const SuspectDrawerDynamic = dynamic(
  () => import("./SuspectDrawer"),
  {
    ssr: false,
    loading: () => (
      <div style={{ padding: "20px 22px", background: "rgba(248,250,252,0.8)", borderTop: "1px solid rgba(0,0,0,0.06)" }}>
        <div style={{ height: 100, borderRadius: 10, background: "linear-gradient(90deg, #f1f5f9 25%, #e2e8f0 50%, #f1f5f9 75%)", backgroundSize: "200% 100%", animation: "shimmer 1.5s infinite" }} />
      </div>
    ),
  }
);

/* ================================================================== */
/*  Page-specific constants                                            */
/* ================================================================== */

/* Single-source-of-truth grid for header / filter / skeleton / rows */
/* Patient | Condition + rationale | Evidence | Confidence | RAF | Revenue | Status | Actions */
const SUSPECTS_GRID =
  "minmax(220px, 1.6fr) minmax(280px, 2.4fr) 130px 150px 92px 100px 108px 96px";
const SUSPECTS_GAP = 14;
const SUSPECTS_PAD_X = 22;
const ROW_MIN_HEIGHT = 84;

const REVENUE_PER_RAF = MA_PAYMENT_PER_RAF;
const PAGE_SIZE = 25;

type StatusTab = "all" | "open" | "accepted" | "dismissed" | "coded";
type EvidenceFilter = "all" | "medication" | "lab" | "imaging" | "referral" | "historical";
type ConfidenceBand = "all" | "high" | "medium" | "low";
type SortField = "confidence" | "patient" | "raf";

const STATUS_TABS: { value: StatusTab; label: string; dot: string | null }[] = [
  { value: "all", label: "All", dot: null },
  { value: "open", label: "Open", dot: C.blue },
  { value: "accepted", label: "Accepted", dot: C.low },
  { value: "dismissed", label: "Dismissed", dot: tokens.slate400 },
  { value: "coded", label: "Coded", dot: C.brand },
];

const EVIDENCE_FILTERS: { value: EvidenceFilter; label: string }[] = [
  { value: "all", label: "All Sources" },
  { value: "lab", label: "Lab" },
  { value: "medication", label: "Medication" },
  { value: "imaging", label: "Imaging" },
  { value: "referral", label: "Referral" },
  { value: "historical", label: "Historical" },
];

// Confidence band labels: "Strong / Moderate / Weak signal" instead of ">85% / 65-85% / <65%"
// Rationale: backend/app/services/nlp_suspect_extractor.py openly notes the scores are
// relative ranking signals only — NOT calibrated probabilities. Using % labels implies
// probabilistic meaning that the model does not support. Numeric score remains visible
// via tooltip on the confidence bar in each row.
const CONFIDENCE_OPTIONS: { value: ConfidenceBand; label: string; color: string }[] = [
  { value: "all", label: "Any", color: C.textSubtle },
  { value: "high", label: "Strong signal", color: C.low },
  { value: "medium", label: "Moderate signal", color: C.medium },
  { value: "low", label: "Weak signal", color: C.high },
];

/* ================================================================== */
/*  Helpers                                                            */
/* ================================================================== */

function confColor(score: number): string {
  if (score >= 0.85) return C.low;
  if (score >= 0.65) return C.medium;
  return C.textSubtle;
}

function confSoftBg(score: number): string {
  if (score >= 0.85) return C.lowSoft;
  if (score >= 0.65) return C.mediumSoft;
  return tokens.slate100;
}

function confAccent(score: number): string {
  if (score >= 0.85) return C.low;
  if (score >= 0.65) return C.medium;
  return tokens.slate300;
}

function matchesBand(score: number, band: ConfidenceBand): boolean {
  if (band === "all") return true;
  if (band === "high") return score >= 0.85;
  if (band === "medium") return score >= 0.65 && score < 0.85;
  return score < 0.65;
}

function evidenceIcon(type: string | undefined, size = 12) {
  switch (type) {
    case "medication": return <Pill size={size} />;
    case "lab": return <FlaskConical size={size} />;
    case "imaging": return <ScanLine size={size} />;
    case "referral": return <Stethoscope size={size} />;
    case "historical": return <Clock size={size} />;
    default: return <ClipboardList size={size} />;
  }
}

function evidenceLabelShort(type: string | undefined): string {
  switch (type) {
    case "medication": return "Medication";
    case "lab": return "Lab";
    case "imaging": return "Imaging";
    case "referral": return "Referral";
    case "historical": return "Historical";
    default: return "Clinical";
  }
}

function rationaleText(s: DBSuspect): string {
  if (s.trigger_value && s.trigger_value.trim()) return s.trigger_value;
  const evd = (s.evidence_detail && typeof s.evidence_detail === "object")
    ? s.evidence_detail as Record<string, unknown>
    : null;
  if (evd) {
    const rationale = (evd.rationale ?? evd.reason ?? evd.summary) as string | undefined;
    if (rationale) return rationale;
    const parts: string[] = [];
    if (evd.result_name) parts.push(String(evd.result_name));
    if (evd.result_value != null) parts.push(`${evd.result_value}`);
    if (evd.drug_name) parts.push(String(evd.drug_name));
    if (parts.length) return parts.join(" — ");
  }
  return "Clinical evidence detected — review chart";
}

function getCoefficient(s: DBSuspect): number {
  // Prefer explicit hcc_coefficient if backend returns it; fall back to a
  // conservative average estimate so the UI never shows zero.
  const coef = (s as unknown as { hcc_coefficient?: number }).hcc_coefficient;
  if (typeof coef === "number" && coef > 0) return coef;
  return 0.25;
}

function formatCurrency(n: number): string {
  if (!isFinite(n)) return "$0";
  return `$${Math.round(n).toLocaleString()}`;
}

function statusPill(status: string | undefined): { bg: string; fg: string; border: string; label: string } {
  switch (status) {
    case "accepted":
      return { bg: C.lowSoft, fg: C.low, border: "rgba(5, 150, 105, 0.25)", label: "Accepted" };
    case "dismissed":
      return { bg: tokens.slate100, fg: C.textSubtle, border: C.border, label: "Dismissed" };
    case "coded":
      return { bg: C.brandSoft, fg: C.brand, border: C.brandRing, label: "Coded" };
    default:
      return { bg: C.blueSoft, fg: tokens.skyText, border: "rgba(14, 165, 233, 0.25)", label: "Open" };
  }
}

/* ================================================================== */
/*  Skeleton row — matches SUSPECTS_GRID exactly                       */
/* ================================================================== */

function SkeletonRow({ index }: { index: number }) {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: SUSPECTS_GRID,
        gap: SUSPECTS_GAP,
        alignItems: "center",
        minHeight: ROW_MIN_HEIGHT,
        padding: `12px ${SUSPECTS_PAD_X}px`,
        backgroundColor: C.bgCard,
        borderBottom: `1px solid ${C.rowDivider}`,
        animation: `pulseSk 1.4s ease-in-out ${index * 80}ms infinite`,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <div style={{ width: 36, height: 36, borderRadius: 10, background: tokens.slate200 }} />
        <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 6 }}>
          <div style={{ width: "70%", height: 12, borderRadius: 4, background: tokens.slate200 }} />
          <div style={{ width: "50%", height: 9, borderRadius: 4, background: tokens.slate100 }} />
        </div>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <div style={{ width: "80%", height: 12, borderRadius: 4, background: tokens.slate200 }} />
        <div style={{ width: "55%", height: 9, borderRadius: 4, background: tokens.slate100 }} />
      </div>
      <div style={{ width: 92, height: 22, borderRadius: 999, background: tokens.slate200 }} />
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <div style={{ flex: 1, height: 6, borderRadius: 4, background: tokens.slate200 }} />
        <div style={{ width: 30, height: 12, borderRadius: 4, background: tokens.slate200 }} />
      </div>
      <div style={{ width: 50, height: 14, borderRadius: 4, background: tokens.slate200, justifySelf: "end" }} />
      <div style={{ width: 60, height: 14, borderRadius: 4, background: tokens.slate200, justifySelf: "end" }} />
      <div style={{ width: 78, height: 22, borderRadius: 999, background: tokens.slate200, justifySelf: "end" }} />
      <div style={{ width: 64, height: 28, borderRadius: 8, background: tokens.slate200, justifySelf: "end" }} />
    </div>
  );
}

/* ================================================================== */
/*  Page Component                                                     */
/* ================================================================== */

export default function SuspectsPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();
  const toast = useToast();

  // Initialize filters from URL params (restores state on back-navigation)
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [statusFilter, setStatusFilter] = useState<StatusTab>((searchParams.get("status") as StatusTab) || "open");
  const [evidenceFilter, setEvidenceFilter] = useState<EvidenceFilter>((searchParams.get("evidence") as EvidenceFilter) || "all");
  const [searchTerm, setSearchTerm] = useState(searchParams.get("q") || "");
  const [confidenceBand, setConfidenceBand] = useState<ConfidenceBand>((searchParams.get("confidence") as ConfidenceBand) || "all");
  const [sortField, setSortField] = useState<SortField>((searchParams.get("sort") as SortField) || "confidence");
  const [page, setPage] = useState(0);

  // EHR Problem List write-back modal state
  const [writeBackSuspect, setWriteBackSuspect] = useState<DBSuspect | null>(null);

  // "More filters" popover
  const [moreOpen, setMoreOpen] = useState(false);
  const morePopoverRef = useRef<HTMLDivElement | null>(null);
  const moreTriggerRef = useRef<HTMLButtonElement | null>(null);
  const moreMenuId = useId();

  // Keyboard navigation — track focused row for A/D/R shortcut dispatch
  const [focusedRowIdx, setFocusedRowIdx] = useState(0);
  const rowRefs = useRef<Array<HTMLDivElement | null>>([]);

  // Sync filter state to URL (no history pollution)
  useEffect(() => {
    const params = new URLSearchParams();
    if (statusFilter !== "open") params.set("status", statusFilter);
    if (evidenceFilter !== "all") params.set("evidence", evidenceFilter);
    if (searchTerm) params.set("q", searchTerm);
    if (confidenceBand !== "all") params.set("confidence", confidenceBand);
    if (sortField !== "confidence") params.set("sort", sortField);
    const qs = params.toString();
    router.replace(qs ? `?${qs}` : "/suspects", { scroll: false });
  }, [statusFilter, evidenceFilter, searchTerm, confidenceBand, sortField, router]);
  const [bulkAction, setBulkAction] = useState<"accept" | "dismiss" | null>(null);
  const [hoveredId, setHoveredId] = useState<number | null>(null);
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [expandedRationale, setExpandedRationale] = useState<Set<number>>(new Set());
  const { paymentYear: measurementYear, setPaymentYear: setMeasurementYear } = usePaymentYear();

  // Close "More" popover on outside click
  useEffect(() => {
    if (!moreOpen) return;
    function handleOutside(e: MouseEvent) {
      const target = e.target as Node;
      if (
        morePopoverRef.current && !morePopoverRef.current.contains(target) &&
        moreTriggerRef.current && !moreTriggerRef.current.contains(target)
      ) setMoreOpen(false);
    }
    document.addEventListener("mousedown", handleOutside);
    return () => document.removeEventListener("mousedown", handleOutside);
  }, [moreOpen]);

  /* --- Data -------------------------------------------------------- */

  const { data: suspectsData, isLoading, isError } = useQuery({
    queryKey: ["suspects", statusFilter, measurementYear],
    queryFn: () => getSuspects(statusFilter === "coded" ? "all" : statusFilter, 500, measurementYear),
  });

  const allSuspects: DBSuspect[] = useMemo(
    () => suspectsData?.suspects ?? [],
    [suspectsData?.suspects]
  );

  // Status counts (always computed across the broadest result set we have)
  const statusCounts = useMemo(() => {
    const counts: Record<StatusTab, number> = {
      all: allSuspects.length,
      open: 0, accepted: 0, dismissed: 0, coded: 0,
    };
    for (const s of allSuspects) {
      const st = (s.status || "open") as StatusTab;
      if (st in counts) counts[st]++;
    }
    return counts;
  }, [allSuspects]);

  const filteredSorted = useMemo(() => {
    let list = allSuspects;

    // Status (client side; the query already narrows except for "coded")
    if (statusFilter !== "all") {
      list = list.filter((s) => (s.status || "open") === statusFilter);
    }

    if (evidenceFilter !== "all") {
      list = list.filter((s) => (s.evidence_type || "") === evidenceFilter);
    }

    if (searchTerm.trim()) {
      const t = searchTerm.toLowerCase();
      list = list.filter((s) => {
        return (
          (s.patient_name ?? "").toLowerCase().includes(t) ||
          String(s.patient_id).includes(t) ||
          (s.suspect_icd10 ?? "").toLowerCase().includes(t) ||
          (s.suspected_condition ?? "").toLowerCase().includes(t) ||
          String(s.suspect_hcc ?? "").includes(t) ||
          rationaleText(s).toLowerCase().includes(t)
        );
      });
    }

    if (confidenceBand !== "all") {
      list = list.filter((s) => matchesBand(s.confidence_score ?? 0, confidenceBand));
    }

    list = [...list].sort((a, b) => {
      if (sortField === "confidence") return (b.confidence_score ?? 0) - (a.confidence_score ?? 0);
      if (sortField === "raf") return getCoefficient(b) - getCoefficient(a);
      return (a.patient_name ?? "").localeCompare(b.patient_name ?? "");
    });

    return list;
  }, [allSuspects, statusFilter, evidenceFilter, searchTerm, confidenceBand, sortField]);

  const totalPages = Math.max(1, Math.ceil(filteredSorted.length / PAGE_SIZE));
  const pagedSuspects = filteredSorted.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  const hasActiveFilters =
    statusFilter !== "open" ||
    evidenceFilter !== "all" ||
    confidenceBand !== "all" ||
    searchTerm.trim() !== "";

  const clearAllFilters = () => {
    setStatusFilter("open");
    setEvidenceFilter("all");
    setConfidenceBand("all");
    setSearchTerm("");
    setPage(0);
  };

  /* --- Hero stats -------------------------------------------------- */

  const heroStats = useMemo(() => {
    const openSet = allSuspects.filter((s) => (s.status || "open") === "open");
    const totalUplift = openSet.reduce((sum, s) => sum + getCoefficient(s), 0);
    const totalRevenue = totalUplift * REVENUE_PER_RAF;
    const avgConf =
      openSet.length > 0
        ? openSet.reduce((sum, s) => sum + (s.confidence_score ?? 0), 0) / openSet.length
        : 0;
    return {
      openCount: openSet.length,
      totalUplift,
      totalRevenue,
      avgConf,
    };
  }, [allSuspects]);

  /* --- Mutations --------------------------------------------------- */

  // Undo refs — keyed by suspect id, value is the timeout handle.
  // When Undo is clicked the timeout is cleared and the reverse API is called.
  const undoTimers = useRef<Map<number, ReturnType<typeof setTimeout>>>(new Map());

  const undoMut = useMutation({
    mutationFn: ({ id, kind }: { id: number; kind: "accept" | "dismiss" }) =>
      kind === "accept" ? unacceptSuspect(id) : undismissSuspect(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["suspects"] });
      toast.success("Undone", "Action reversed — suspect is open again.");
    },
    onError: () => toast.error("Undo Failed", "The undo window may have passed."),
  });

  const handleAccept = useCallback(
    (id: number) => {
      acceptSuspect(id)
        .then(() => {
          queryClient.invalidateQueries({ queryKey: ["suspects"] });
          const timer = setTimeout(() => {
            undoTimers.current.delete(id);
          }, 5500);
          undoTimers.current.set(id, timer);
          toast.success(
            "Accepted",
            "Suspect accepted & written to OpenEMR.",
            {
              duration: 5500,
              action: {
                label: "Undo",
                onClick: () => {
                  const t = undoTimers.current.get(id);
                  if (t) { clearTimeout(t); undoTimers.current.delete(id); }
                  undoMut.mutate({ id, kind: "accept" });
                },
              },
            }
          );
          // Prompt provider to push to EHR Problem List
          const accepted = allSuspects.find((s) => s.id === id) ?? null;
          setWriteBackSuspect(accepted);
        })
        .catch(() => toast.error("Error", "Failed to accept suspect."));
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [queryClient, toast]
  );

  const handleDismiss = useCallback(
    (id: number) => {
      dismissSuspect(id)
        .then(() => {
          queryClient.invalidateQueries({ queryKey: ["suspects"] });
          const timer = setTimeout(() => {
            undoTimers.current.delete(id);
          }, 5500);
          undoTimers.current.set(id, timer);
          toast.success(
            "Dismissed",
            "Suspect condition dismissed.",
            {
              duration: 5500,
              action: {
                label: "Undo",
                onClick: () => {
                  const t = undoTimers.current.get(id);
                  if (t) { clearTimeout(t); undoTimers.current.delete(id); }
                  undoMut.mutate({ id, kind: "dismiss" });
                },
              },
            }
          );
        })
        .catch(() => toast.error("Error", "Failed to dismiss suspect."));
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [queryClient, toast]
  );

  // Shim mutation objects so existing JSX that reads .isPending still compiles
  const acceptMut = { isPending: false, mutate: handleAccept } as const;
  const dismissMut = { isPending: false, mutate: handleDismiss } as const;

  const bulkMut = useMutation({
    mutationFn: ({ action }: { action: "accept" | "dismiss" }) =>
      bulkUpdateSuspects(Array.from(selected), action),
    onSuccess: (data, vars) => {
      queryClient.invalidateQueries({ queryKey: ["suspects"] });
      setSelected(new Set());
      setBulkAction(null);
      toast.success(
        "Bulk Update",
        `${data.succeeded} suspects ${vars.action === "accept" ? "accepted & written to OpenEMR" : "dismissed"}.`
      );
    },
    onError: () => {
      setBulkAction(null);
      toast.error("Error", "Bulk update failed.");
    },
  });

  /* --- Keyboard shortcuts: A/D/R on focused row -------------------- */

  // Reset focus index when filtered data changes so it doesn't point past end
  useEffect(() => {
    setFocusedRowIdx(0);
  }, [filteredSorted.length, page]);

  // Register A/D/R context shortcuts that operate on the focused row.
  // Guards: skip when focus is inside a typing surface (search box etc.)
  useEffect(() => {
    function isTyping(): boolean {
      const el = document.activeElement as HTMLElement | null;
      if (!el) return false;
      const tag = el.tagName.toLowerCase();
      return tag === "input" || tag === "textarea" || tag === "select" || el.isContentEditable === true;
    }

    const unregAccept = registerContextShortcut("accept-focused-suspect", () => {
      if (isTyping()) return;
      const row = pagedSuspects[focusedRowIdx];
      if (row && (row.status || "open") === "open") {
        acceptMut.mutate(row.id);
      }
    });

    const unregDismiss = registerContextShortcut("dismiss-focused-suspect", () => {
      if (isTyping()) return;
      const row = pagedSuspects[focusedRowIdx];
      if (row && (row.status || "open") === "open") {
        dismissMut.mutate(row.id);
      }
    });

    const unregReview = registerContextShortcut("mark-meat-reviewed", () => {
      if (isTyping()) return;
      const row = pagedSuspects[focusedRowIdx];
      if (row) {
        router.push(`/patients/${row.patient_id}?tab=suspects`);
      }
    });

    return () => {
      unregAccept();
      unregDismiss();
      unregReview();
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusedRowIdx, pagedSuspects]);

  // Arrow / J / K key navigation across rows — only when not typing
  const handleListKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLDivElement>) => {
      const el = e.target as HTMLElement;
      const tag = el.tagName.toLowerCase();
      if (tag === "input" || tag === "textarea" || tag === "select" || el.isContentEditable) return;

      if (e.key === "ArrowDown" || e.key === "j") {
        e.preventDefault();
        setFocusedRowIdx((i) => {
          const next = Math.min(i + 1, pagedSuspects.length - 1);
          rowRefs.current[next]?.focus();
          return next;
        });
      } else if (e.key === "ArrowUp" || e.key === "k") {
        e.preventDefault();
        setFocusedRowIdx((i) => {
          const prev = Math.max(i - 1, 0);
          rowRefs.current[prev]?.focus();
          return prev;
        });
      }
    },
    [pagedSuspects.length],
  );

  /* --- Selection --------------------------------------------------- */

  const selectableIds = useMemo(
    () => pagedSuspects.filter((s) => (s.status || "open") === "open").map((s) => s.id),
    [pagedSuspects]
  );

  const allSelected = selectableIds.length > 0 && selectableIds.every((id) => selected.has(id));

  const toggleSelect = useCallback((id: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }, []);

  const toggleAll = useCallback(() => {
    if (allSelected) {
      setSelected((prev) => {
        const next = new Set(prev);
        selectableIds.forEach((id) => next.delete(id));
        return next;
      });
    } else {
      setSelected((prev) => new Set([...prev, ...selectableIds]));
    }
  }, [allSelected, selectableIds]);

  const handleStatusChange = useCallback((tab: StatusTab) => {
    setStatusFilter(tab);
    setSelected(new Set());
    setPage(0);
  }, []);

  /* --- CSV Export -------------------------------------------------- */

  function exportSuspectsCSV() {
    if (!filteredSorted.length) return;
    const data = filteredSorted.map((s) => ({
      "Patient ID": s.patient_id,
      "Patient Name": s.patient_name ?? `Patient ${s.patient_id}`,
      "Measurement Year": s.measurement_year ?? measurementYear,
      "Condition": s.suspected_condition ?? "",
      "ICD-10": s.suspect_icd10 ?? "",
      "HCC": s.suspect_hcc ?? "",
      "RAF Coefficient": getCoefficient(s).toFixed(3),
      "Est. Revenue": Math.round(getCoefficient(s) * REVENUE_PER_RAF),
      "Confidence": `${((s.confidence_score ?? 0) * 100).toFixed(0)}%`,
      "Status": s.status ?? "",
      "Evidence Type": s.evidence_type ?? "",
      "Rationale": rationaleText(s),
    }));
    downloadCSV(data, "suspects");
  }

  /* ============================================================== */
  /*  Render                                                         */
  /* ============================================================== */

  return (
    <div
      className="suspects-page-wrap"
      style={{
        background: C.bgPage,
        minHeight: "100vh",
        padding: "20px 16px 48px",
        fontFamily: FONT_SYS,
        color: C.text,
        overflowX: "hidden",
      }}
    >
      <PageAlerts defaultOpen>
        <HistoricalPYBanner paymentYear={measurementYear} />
        <DataQualityBanner />
        <WorkflowProgressBar currentStage="suspects" />
        <WorkflowHandoffBanner
          count={statusCounts.accepted}
          message="{count} suspects ready for attestation"
          ctaLabel="Send to Attestations"
          ctaHref="/attestations"
          showWhenZero
          zeroMessage="No suspects accepted yet — review AI suspects below and accept to proceed."
          zeroCtaLabel="View Suspects"
          zeroCtaHref="/suspects"
        />
      </PageAlerts>
      <style>{`
        @media (prefers-reduced-motion: no-preference) {
          @keyframes pulseSk { 0%, 100% { opacity: 1; } 50% { opacity: 0.55; } }
          @keyframes rowEnter { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }
          @keyframes shimmer { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }
        }
        .suspect-row {
          animation: rowEnter 0.32s cubic-bezier(0.16, 1, 0.3, 1) both;
          transition: background-color 0.15s ease;
        }
        @media (prefers-reduced-motion: reduce) {
          .suspect-row { animation: none; }
        }
        .suspect-row:hover { background-color: ${C.bgBand} !important; }
        .suspect-row:focus-visible {
          outline: 2px solid ${C.brand};
          outline-offset: -2px;
        }
        .row-action-btn {
          opacity: 0;
          transform: translateY(2px);
          transition: opacity 0.15s ease, transform 0.15s ease, background-color 0.15s ease, color 0.15s ease;
        }
        .suspect-row:hover .row-action-btn,
        .suspect-row:focus-within .row-action-btn { opacity: 1; transform: translateY(0); }
        @media (max-width: 900px) {
          .row-action-btn { opacity: 1; transform: none; }
        }
        @media (min-width: 640px) {
          .suspects-page-wrap { padding: 32px 40px 48px !important; }
        }
        /* WCAG 2.5.5 — touch targets ≥44px on mobile */
        @media (max-width: 768px) {
          .row-action-btn {
            width: 44px !important;
            height: 44px !important;
            border-radius: 10px !important;
          }
          .suspects-filter-chip-group {
            min-height: 44px !important;
          }
          .suspects-filter-chip-group button {
            min-height: 38px !important;
            padding-top: 5px !important;
            padding-bottom: 5px !important;
          }
        }
      `}</style>

      {/* ── Error Banner ─────────────────────────────────────────── */}
      {isError && (
        <div
          role="alert"
          style={{
            display: "flex",
            alignItems: "center",
            gap: 12,
            background: C.highSoft,
            border: `1px solid ${tokens.dangerBorder}`,
            borderRadius: 12,
            padding: "12px 16px",
            marginBottom: 20,
            fontSize: 13,
            color: C.high,
            fontWeight: 600,
          }}
        >
          <AlertCircle size={18} />
          Failed to load suspects. Please check the server connection and refresh.
        </div>
      )}

      {/* ============================================================ */}
      {/* Page header                                                  */}
      {/* ============================================================ */}
      <div
        style={{
          display: "flex",
          alignItems: "flex-start",
          gap: 16,
          marginBottom: 24,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 16, minWidth: 0 }}>
          <div
            style={{
              width: 48,
              height: 48,
              borderRadius: 14,
              background: `linear-gradient(135deg, ${C.brand} 0%, ${C.brandDark} 100%)`,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              boxShadow:
                "0 6px 16px rgba(15, 118, 110, 0.25), inset 0 1px 0 rgba(255,255,255,0.18)",
              flexShrink: 0,
            }}
          >
            <Sparkles size={22} color={tokens.white} strokeWidth={2.25} aria-hidden="true" />
          </div>
          <div style={{ minWidth: 0 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <h1
                style={{
                  margin: 0,
                  fontSize: 24,
                  fontWeight: 700,
                  color: C.text,
                  letterSpacing: "-0.02em",
                  lineHeight: 1.15,
                }}
              >
                Suspect Conditions
              </h1>
              <div
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 6,
                  height: 26,
                  padding: "0 4px 0 10px",
                  borderRadius: 8,
                  backgroundColor: C.brandSoft,
                  border: `1px solid ${C.brandRing}`,
                  color: C.brand,
                  fontSize: 11,
                  fontWeight: 600,
                  letterSpacing: "0.02em",
                  fontVariantNumeric: "tabular-nums",
                }}
              >
                <span>MY</span>
                <select
                  value={measurementYear}
                  onChange={(e) => setMeasurementYear(Number(e.target.value))}
                  aria-label="Measurement year"
                  style={{
                    appearance: "none",
                    WebkitAppearance: "none",
                    MozAppearance: "none",
                    background: "transparent",
                    border: "none",
                    color: C.brand,
                    fontSize: 12,
                    fontWeight: 700,
                    fontFamily: FONT_SYS,
                    fontVariantNumeric: "tabular-nums",
                    letterSpacing: "0.01em",
                    cursor: "pointer",
                    padding: "0 18px 0 2px",
                    backgroundImage:
                      "url(\"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='10' height='10' viewBox='0 0 20 20' fill='%230F766E'><path d='M5 8l5 5 5-5H5z'/></svg>\")",
                    backgroundRepeat: "no-repeat",
                    backgroundPosition: "right 2px center",
                  }}
                >
                  {PAYMENT_YEARS.map((y) => (
                    <option key={y} value={y}>{y}</option>
                  ))}
                </select>
              </div>
            </div>
            <p
              style={{
                margin: "4px 0 0",
                fontSize: 13,
                color: C.textSubtle,
                fontVariantNumeric: "tabular-nums",
              }}
            >
              {isLoading
                ? "Loading review queue\u2026"
                : `${heroStats.openCount.toLocaleString()} open suspects · ${formatCurrency(heroStats.totalRevenue)} estimated RAF opportunity · CMS-HCC V28`}
            </p>
          </div>
        </div>

      </div>

      {/* ============================================================ */}
      {/* Hero summary strip — 4 cards                                 */}
      {/* ============================================================ */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
          gap: 12,
          marginBottom: 16,
        }}
      >
        {[
          {
            label: "Open Suspects",
            value: isLoading ? "\u2014" : heroStats.openCount.toLocaleString(),
            sub: `In MY ${measurementYear}`,
            icon: ClipboardList,
            tone: C.blue,
          },
          {
            label: "Est. RAF Uplift",
            value: isLoading ? "\u2014" : `+${heroStats.totalUplift.toFixed(2)}`,
            sub: "Sum of coefficients",
            icon: TrendingUp,
            tone: C.brand,
          },
          {
            label: "Est. Annual Revenue",
            value: isLoading ? "\u2014" : formatCurrency(heroStats.totalRevenue),
            sub: `at $${REVENUE_PER_RAF.toLocaleString()}/RAF point`,
            icon: DollarSign,
            tone: C.low,
          },
          {
            label: "Avg Confidence",
            value: isLoading ? "\u2014" : `${(heroStats.avgConf * 100).toFixed(0)}%`,
            sub: "Across open suspects",
            icon: Activity,
            tone: C.medium,
          },
        ].map(({ label, value, sub, icon: Icon, tone }) => (
          <div
            key={label}
            style={{
              backgroundColor: C.bgCard,
              border: `1px solid ${C.borderSoft}`,
              borderRadius: 12,
              padding: "14px 16px",
              display: "flex",
              alignItems: "center",
              gap: 14,
              boxShadow: "0 1px 2px rgba(15, 23, 42, 0.03)",
            }}
          >
            <div
              style={{
                width: 36,
                height: 36,
                borderRadius: 10,
                backgroundColor: `${tone}14`,
                color: tone,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                flexShrink: 0,
              }}
            >
              <Icon size={17} strokeWidth={2.25} />
            </div>
            <div style={{ minWidth: 0, display: "flex", flexDirection: "column", gap: 2 }}>
              <span
                style={{
                  fontSize: 11,
                  fontWeight: 600,
                  textTransform: "uppercase",
                  letterSpacing: "0.06em",
                  color: C.label,
                }}
              >
                {label}
              </span>
              <span
                style={{
                  fontSize: 22,
                  fontWeight: 700,
                  color: C.text,
                  lineHeight: 1.1,
                  letterSpacing: "-0.02em",
                  fontVariantNumeric: "tabular-nums",
                }}
              >
                {value}
              </span>
              <span
                style={{
                  fontSize: 11,
                  color: C.textSubtle,
                  fontVariantNumeric: "tabular-nums",
                }}
              >
                {sub}
              </span>
            </div>
          </div>
        ))}
      </div>

      {/* ============================================================ */}
      {/* Filter strip                                                 */}
      {/* ============================================================ */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          flexWrap: "wrap",
          gap: 12,
          marginBottom: 14,
        }}
      >
        {/* ── Progressive-disclosure filter strip ──────────────────── */}
        {/* Primary (always visible): All / Open / Accepted + "More"   */}
        {/* Collapsed into "More": Dismissed, Coded, Evidence, Signal  */}
        {/* Always visible: Sort button                                */}
        {(() => {
          const PRIMARY_STATUS: StatusTab[] = ["all", "open", "accepted"];
          const MORE_STATUS: StatusTab[] = ["dismissed", "coded"];

          const moreActiveCount =
            (MORE_STATUS.includes(statusFilter) ? 1 : 0) +
            (evidenceFilter !== "all" ? 1 : 0) +
            (confidenceBand !== "all" ? 1 : 0);

          const groupStyle: React.CSSProperties = {
            display: "inline-flex",
            alignItems: "center",
            backgroundColor: tokens.white,
            border: `1px solid ${C.border}`,
            borderRadius: 10,
            padding: 3,
            gap: 2,
            height: 36,
          };

          const primaryChipStyle = (active: boolean): React.CSSProperties => ({
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
            height: 28,
            padding: "0 12px",
            borderRadius: 7,
            border: "none",
            backgroundColor: active ? C.text : "transparent",
            color: active ? tokens.white : C.textMuted,
            fontSize: 12,
            fontWeight: 600,
            fontFamily: FONT_SYS,
            cursor: "pointer",
            transition: "all 0.15s ease",
            whiteSpace: "nowrap" as const,
          });

          const activeTagStyle = (borderColor: string, bgColor: string, color: string): React.CSSProperties => ({
            display: "inline-flex",
            alignItems: "center",
            gap: 5,
            height: 28,
            padding: "0 10px",
            borderRadius: 999,
            border: `1px solid ${borderColor}`,
            backgroundColor: bgColor,
            color,
            fontSize: 12,
            fontWeight: 600,
            fontFamily: FONT_SYS,
            cursor: "pointer",
          });

          const handleMenuKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
            const items = Array.from(
              morePopoverRef.current?.querySelectorAll<HTMLElement>("[data-menu-item]") ?? []
            );
            const idx = items.indexOf(e.target as HTMLElement);
            if (e.key === "ArrowDown") { e.preventDefault(); items[(idx + 1) % items.length]?.focus(); }
            else if (e.key === "ArrowUp") { e.preventDefault(); items[(idx - 1 + items.length) % items.length]?.focus(); }
            else if (e.key === "Escape") { setMoreOpen(false); moreTriggerRef.current?.focus(); }
          };

          return (
            <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>

              {/* Primary status chips */}
              <div className="suspects-filter-chip-group" style={groupStyle} role="group" aria-label="Status filter">
                {STATUS_TABS.filter((t) => PRIMARY_STATUS.includes(t.value)).map(({ value, label, dot }) => {
                  const active = statusFilter === value;
                  return (
                    <button
                      key={value}
                      onClick={(e) => { e.stopPropagation(); handleStatusChange(value); }}
                      onKeyDown={(e) => e.stopPropagation()}
                      aria-pressed={active}
                      style={primaryChipStyle(active)}
                    >
                      {dot && <span style={{ width: 6, height: 6, borderRadius: 3, backgroundColor: dot, boxShadow: active ? "0 0 0 1.5px rgba(255,255,255,0.25)" : "none" }} />}
                      {label}
                      <span style={{ fontSize: 11, fontWeight: 600, color: active ? "rgba(255,255,255,0.7)" : C.label, fontVariantNumeric: "tabular-nums" }}>{statusCounts[value]}</span>
                    </button>
                  );
                })}
              </div>

              {/* "More filters" trigger + popover */}
              <div style={{ position: "relative" }}>
                <button
                  ref={moreTriggerRef}
                  id={`${moreMenuId}-btn`}
                  aria-haspopup="true"
                  aria-expanded={moreOpen}
                  aria-controls={`${moreMenuId}-menu`}
                  onClick={() => setMoreOpen((o) => !o)}
                  style={{
                    display: "inline-flex", alignItems: "center", gap: 6,
                    height: 36, padding: "0 14px", borderRadius: 10,
                    border: `1px solid ${moreActiveCount > 0 ? C.brand : C.border}`,
                    backgroundColor: moreActiveCount > 0 ? C.brandSoft : tokens.white,
                    color: moreActiveCount > 0 ? C.brand : C.textMuted,
                    fontSize: 12, fontWeight: 600, fontFamily: FONT_SYS,
                    cursor: "pointer", transition: "all 0.15s ease",
                  }}
                >
                  More filters
                  {moreActiveCount > 0 && (
                    <span
                      aria-label={`${moreActiveCount} active`}
                      style={{
                        display: "inline-flex", alignItems: "center", justifyContent: "center",
                        minWidth: 18, height: 18, borderRadius: 999,
                        backgroundColor: C.brand, color: tokens.white,
                        fontSize: 10, fontWeight: 700, padding: "0 4px",
                      }}
                    >
                      {moreActiveCount}
                    </span>
                  )}
                  <ChevronDown size={13} style={{ transition: "transform 0.15s", transform: moreOpen ? "rotate(180deg)" : "none" }} />
                </button>

                {moreOpen && (
                  <div
                    ref={morePopoverRef}
                    id={`${moreMenuId}-menu`}
                    role="dialog"
                    aria-label="More filters"
                    onKeyDown={handleMenuKeyDown}
                    style={{
                      position: "absolute", top: "calc(100% + 6px)", left: 0, zIndex: 120,
                      backgroundColor: tokens.white, border: `1px solid ${C.border}`,
                      borderRadius: 12, boxShadow: "0 8px 24px rgba(15,23,42,0.12), 0 2px 6px rgba(15,23,42,0.06)",
                      padding: "14px 16px", minWidth: 280, display: "flex", flexDirection: "column", gap: 14,
                    }}
                  >
                    {/* Status: Dismissed / Coded */}
                    <div>
                      <div style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.08em", color: C.label, marginBottom: 6 }}>Status</div>
                      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                        {STATUS_TABS.filter((t) => MORE_STATUS.includes(t.value)).map(({ value, label, dot }) => {
                          const active = statusFilter === value;
                          return (
                            <button
                              key={value}
                              data-menu-item
                              onClick={() => { handleStatusChange(value); setMoreOpen(false); }}
                              aria-pressed={active}
                              style={{
                                display: "inline-flex", alignItems: "center", gap: 6,
                                height: 30, padding: "0 12px", borderRadius: 8,
                                border: `1px solid ${active ? C.brand : C.border}`,
                                backgroundColor: active ? C.brandSoft : C.bgSubtle,
                                color: active ? C.brand : C.textMuted,
                                fontSize: 12, fontWeight: 600, fontFamily: FONT_SYS, cursor: "pointer", transition: "all 0.15s ease",
                              }}
                            >
                              {dot && <span style={{ width: 6, height: 6, borderRadius: 3, backgroundColor: dot }} />}
                              {label}
                              <span style={{ fontSize: 10, color: active ? C.brand : C.label, fontVariantNumeric: "tabular-nums" }}>{statusCounts[value]}</span>
                              {active && <X size={10} onClick={(e) => { e.stopPropagation(); handleStatusChange("open"); }} aria-label={`Remove ${label} filter`} />}
                            </button>
                          );
                        })}
                      </div>
                    </div>
                    <div style={{ height: 1, backgroundColor: C.borderSoft }} />

                    {/* Evidence source */}
                    <div>
                      <div style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.08em", color: C.label, marginBottom: 6 }}>Evidence source</div>
                      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                        {EVIDENCE_FILTERS.filter((f) => f.value !== "all").map(({ value, label }) => {
                          const active = evidenceFilter === value;
                          return (
                            <button
                              key={value}
                              data-menu-item
                              onClick={() => { setEvidenceFilter(active ? "all" : value); setPage(0); }}
                              aria-pressed={active}
                              style={{
                                display: "inline-flex", alignItems: "center", gap: 5,
                                height: 30, padding: "0 10px", borderRadius: 8,
                                border: `1px solid ${active ? C.brand : C.border}`,
                                backgroundColor: active ? C.brandSoft : C.bgSubtle,
                                color: active ? C.brand : C.textMuted,
                                fontSize: 12, fontWeight: 600, fontFamily: FONT_SYS, cursor: "pointer", transition: "all 0.15s ease",
                              }}
                            >
                              {evidenceIcon(value, 11)}{label}
                              {active && <X size={10} aria-label={`Remove ${label} filter`} />}
                            </button>
                          );
                        })}
                      </div>
                    </div>
                    <div style={{ height: 1, backgroundColor: C.borderSoft }} />

                    {/* Confidence signal */}
                    <div>
                      <div style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.08em", color: C.label, marginBottom: 6 }}>Confidence signal</div>
                      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                        {CONFIDENCE_OPTIONS.filter((o) => o.value !== "all").map(({ value, label, color }) => {
                          const active = confidenceBand === value;
                          return (
                            <button
                              key={value}
                              data-menu-item
                              onClick={() => { setConfidenceBand(active ? "all" : value); setPage(0); }}
                              aria-pressed={active}
                              style={{
                                display: "inline-flex", alignItems: "center", gap: 6,
                                height: 30, padding: "0 10px", borderRadius: 8,
                                border: `1px solid ${active ? color : C.border}`,
                                backgroundColor: active ? `${color}14` : C.bgSubtle,
                                color: active ? color : C.textMuted,
                                fontSize: 12, fontWeight: 600, fontFamily: FONT_SYS, cursor: "pointer", transition: "all 0.15s ease",
                              }}
                            >
                              <span style={{ width: 6, height: 6, borderRadius: 3, backgroundColor: color }} />
                              {label}
                              {active && <X size={10} aria-label={`Remove ${label} filter`} />}
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  </div>
                )}
              </div>

              {/* Surfaced active "More" chips — removable inline */}
              {MORE_STATUS.includes(statusFilter) && (() => {
                const t = STATUS_TABS.find((x) => x.value === statusFilter)!;
                return (
                  <button key={`active-${statusFilter}`} onClick={() => handleStatusChange("open")} aria-label={`Remove ${t.label} filter`} style={activeTagStyle(C.brand, C.brandSoft, C.brand)}>
                    {t.dot && <span style={{ width: 6, height: 6, borderRadius: 3, backgroundColor: t.dot }} />}
                    {t.label} <X size={11} />
                  </button>
                );
              })()}

              {evidenceFilter !== "all" && (
                <button onClick={() => { setEvidenceFilter("all"); setPage(0); }} aria-label={`Remove evidence filter: ${evidenceFilter}`} style={activeTagStyle(C.brand, C.brandSoft, C.brand)}>
                  {evidenceIcon(evidenceFilter, 11)}
                  {EVIDENCE_FILTERS.find((f) => f.value === evidenceFilter)?.label}
                  <X size={11} />
                </button>
              )}

              {confidenceBand !== "all" && (() => {
                const opt = CONFIDENCE_OPTIONS.find((o) => o.value === confidenceBand)!;
                return (
                  <button onClick={() => { setConfidenceBand("all"); setPage(0); }} aria-label={`Remove confidence filter: ${opt.label}`} style={activeTagStyle(opt.color, `${opt.color}14`, opt.color)}>
                    <span style={{ width: 6, height: 6, borderRadius: 3, backgroundColor: opt.color }} />
                    {opt.label} <X size={11} />
                  </button>
                );
              })()}

              {/* Sort — always visible */}
              <button
                onClick={() => setSortField((f) => f === "confidence" ? "raf" : f === "raf" ? "patient" : "confidence")}
                style={{
                  display: "inline-flex", alignItems: "center", gap: 6,
                  height: 36, padding: "0 14px", borderRadius: 10,
                  border: `1px solid ${C.border}`, backgroundColor: tokens.white,
                  color: C.textMuted, fontSize: 12, fontWeight: 600,
                  fontFamily: FONT_SYS, cursor: "pointer", transition: "all 0.15s ease",
                }}
              >
                Sort: {sortField === "confidence" ? "Confidence" : sortField === "raf" ? "RAF lift" : "Patient"}
              </button>

              {hasActiveFilters && (
                <button
                  onClick={clearAllFilters}
                  style={{
                    display: "inline-flex", alignItems: "center", gap: 6,
                    height: 36, padding: "0 14px", borderRadius: 999,
                    border: `1px dashed ${C.border}`, backgroundColor: "transparent",
                    color: C.textSubtle, fontSize: 12, fontWeight: 600,
                    fontFamily: FONT_SYS, cursor: "pointer",
                  }}
                >
                  <X size={12} /> Clear filters
                </button>
              )}

              {/* Divider between filter-side and action-side */}
              <div style={{ width: 1, height: 24, backgroundColor: C.border, flexShrink: 0, marginLeft: 4, marginRight: 4 }} aria-hidden="true" />

              {/* Search input */}
              <div style={{ position: "relative", flexShrink: 0 }}>
                <Search
                  size={14}
                  style={{
                    position: "absolute",
                    left: 10,
                    top: "50%",
                    transform: "translateY(-50%)",
                    color: C.label,
                    pointerEvents: "none",
                  }}
                />
                <input
                  type="text"
                  title="Search by patient, ICD, HCC, or rationale"
                  placeholder="Search suspects…"
                  value={searchTerm}
                  onChange={(e) => { setSearchTerm(e.target.value); setPage(0); }}
                  onKeyDown={(e) => e.stopPropagation()}
                  aria-label="Search suspects"
                  style={{
                    height: 36,
                    width: 220,
                    borderRadius: 10,
                    border: `1px solid ${C.border}`,
                    backgroundColor: tokens.white,
                    paddingLeft: 30,
                    paddingRight: 12,
                    fontSize: 12,
                    color: C.text,
                    fontFamily: FONT_SYS,
                    transition: "border-color 0.15s, box-shadow 0.15s",
                  }}
                  onFocus={(e) => {
                    e.currentTarget.style.borderColor = C.brand;
                    e.currentTarget.style.boxShadow = `0 0 0 3px ${C.brandSoft}`;
                  }}
                  onBlur={(e) => {
                    e.currentTarget.style.borderColor = C.border;
                    e.currentTarget.style.boxShadow = "none";
                  }}
                />
              </div>

              {/* Export button */}
              <button
                onClick={exportSuspectsCSV}
                aria-label="Export suspects as CSV"
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 6,
                  height: 36,
                  padding: "0 14px",
                  borderRadius: 10,
                  border: "none",
                  backgroundColor: C.brand,
                  color: tokens.white,
                  fontSize: 12,
                  fontWeight: 600,
                  fontFamily: FONT_SYS,
                  cursor: "pointer",
                  flexShrink: 0,
                  boxShadow: "0 1px 2px rgba(15, 118, 110, 0.25), 0 4px 12px rgba(15, 118, 110, 0.18)",
                  transition: "background-color 0.15s ease",
                }}
                onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = tokens.teal900; }}
                onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = C.brand; }}
              >
                <FileDown size={13} />
                Export
              </button>
            </div>
          );
        })()}

        <div style={{ fontSize: 12, fontWeight: 600, color: C.textSubtle, fontVariantNumeric: "tabular-nums" }}>
          Showing {filteredSorted.length.toLocaleString()} of {allSuspects.length.toLocaleString()}
        </div>
      </div>

      {/* ============================================================ */}
      {/* Worklist                                                     */}
      {/* ============================================================ */}
      {/* Keyboard hint footer — surface A/D/R affordance */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 16,
          marginBottom: 8,
          fontSize: 11,
          color: "#64748B",
          flexWrap: "wrap",
        }}
        aria-label="Keyboard shortcuts: use Up/Down or J/K to navigate rows, then A to accept, D to dismiss, R to open chart"
      >
        <span style={{ fontWeight: 600, color: "#475569" }}>Keyboard shortcuts:</span>
        {(
          [
            ["Up/Down", "Navigate rows"],
            ["A", "Accept focused"],
            ["D", "Dismiss focused"],
            ["R", "Open chart"],
          ] as [string, string][]
        ).map(([key, desc]) => (
          <span key={key} style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
            <kbd
              style={{
                display: "inline-flex",
                alignItems: "center",
                justifyContent: "center",
                minWidth: 22,
                height: 20,
                padding: "0 5px",
                borderRadius: 4,
                border: "1px solid #CBD5E1",
                background: "#F8FAFC",
                fontFamily: "monospace",
                fontSize: 11,
                fontWeight: 700,
                color: C.label,
                boxShadow: "0 1px 1px rgba(0,0,0,0.06)",
              }}
            >
              {key}
            </kbd>
            <span>{desc}</span>
          </span>
        ))}
      </div>

      <div
        role="grid"
        aria-label="Suspected conditions"
        onKeyDown={handleListKeyDown}
        style={{
          backgroundColor: C.bgCard,
          border: `1px solid ${C.border}`,
          borderRadius: 14,
          overflowX: "auto",
          overflowY: "visible",
          boxShadow: "0 1px 2px rgba(15, 23, 42, 0.04)",
        }}
      >
        {/* Header row */}
        <div
          role="rowgroup"
        >
        <div
          role="row"
          style={{
            display: "grid",
            gridTemplateColumns: SUSPECTS_GRID,
            gap: SUSPECTS_GAP,
            alignItems: "center",
            padding: `12px ${SUSPECTS_PAD_X}px`,
            backgroundColor: C.bgBand,
            borderBottom: `1px solid ${C.border}`,
            fontSize: 11,
            fontWeight: 600,
            textTransform: "uppercase",
            letterSpacing: "0.06em",
            color: C.label,
          }}
        >
          <div role="columnheader" aria-sort={sortField === "patient" ? "ascending" : "none"} style={{ display: "flex", alignItems: "center", gap: 10 }}>
            {selectableIds.length > 0 && (
              <input
                type="checkbox"
                checked={allSelected}
                onChange={toggleAll}
                aria-label="Select all on page"
                style={{ width: 14, height: 14, accentColor: C.brand, cursor: "pointer" }}
              />
            )}
            Patient
          </div>
          <div role="columnheader">Suspected Condition</div>
          <div role="columnheader">Evidence</div>
          <div role="columnheader" aria-sort={sortField === "confidence" ? "descending" : "none"}>Confidence</div>
          <div role="columnheader" aria-sort={sortField === "raf" ? "descending" : "none"} style={{ justifySelf: "end" }}>RAF Lift</div>
          <div role="columnheader" style={{ justifySelf: "end" }}>Revenue</div>
          <div role="columnheader" style={{ justifySelf: "end" }}>Status</div>
          <div role="columnheader" style={{ justifySelf: "end" }}>Actions</div>
        </div>
        </div>

        {/* Body */}
        {isLoading && (
          <div role="rowgroup">
            {Array.from({ length: 8 }).map((_, i) => <SkeletonRow key={i} index={i} />)}
          </div>
        )}

        <div role="rowgroup">
        {!isLoading && filteredSorted.length === 0 && (
          <div
            style={{
              padding: "56px 24px",
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              justifyContent: "center",
              gap: 12,
              textAlign: "center",
            }}
          >
            <div
              style={{
                width: 56,
                height: 56,
                borderRadius: 16,
                backgroundColor: C.brandSoft,
                color: C.brand,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              <FileSearch size={26} />
            </div>
            <div className="text-foreground" style={{ fontSize: 15, fontWeight: 700 }}>
              No suspects match your filters
            </div>
            <div className="text-muted-foreground" style={{ fontSize: 13, maxWidth: 360 }}>
              Try widening your status, evidence, or confidence filters to see more results.
            </div>
            {hasActiveFilters && (
              <button
                onClick={clearAllFilters}
                style={{
                  marginTop: 4,
                  height: 36,
                  padding: "0 18px",
                  borderRadius: 10,
                  border: `1px solid ${C.brand}`,
                  backgroundColor: C.brandSoft,
                  color: C.brand,
                  fontSize: 13,
                  fontWeight: 600,
                  cursor: "pointer",
                }}
              >
                Clear filters
              </button>
            )}
          </div>
        )}

        {!isLoading && pagedSuspects.map((s, idx) => {
          // Prefer calibrated_confidence (Platt-scaled) over the raw score.
          // Falls back to confidence_score so legacy rows without the
          // calibrated field still render correctly.
          const conf = s.calibrated_confidence ?? s.confidence_score ?? 0;
          const isCalibrated = s.calibrated_confidence != null && s.calibrated_confidence !== s.confidence_score;
          const cConf = confColor(conf);
          const accent = confAccent(conf);
          const isOpen = (s.status || "open") === "open";
          const isSelected = selected.has(s.id);
          const pill = statusPill(s.status);
          const coef = getCoefficient(s);
          const revenue = coef * REVENUE_PER_RAF;
          const initials = deriveInitials(s.patient_name, undefined, s.patient_id);
          const seed = (s.patient_name || String(s.patient_id) || "x").trim();
          const aColor = initialsColor(seed);
          const conditionLabel =
            s.suspected_condition ||
            (s.suspect_hcc ? `HCC ${s.suspect_hcc}` : "Suspected Condition");
          const rationale = rationaleText(s);

          const isExpanded = expandedId === s.id;
          const isFocused = focusedRowIdx === idx;

          return (
            <div
              key={s.id}
              style={{
                borderBottom: idx < pagedSuspects.length - 1 ? `1px solid ${C.rowDivider}` : "none",
                backgroundColor: isExpanded ? C.bgBand : isSelected ? C.brandSoft : C.bgCard,
                outline: isFocused ? `2px solid ${C.brand}` : "none",
                outlineOffset: -2,
                borderRadius: isFocused ? 4 : 0,
              }}
            >
            <div
              role="row"
              tabIndex={0}
              ref={(el) => { rowRefs.current[idx] = el; }}
              className="suspect-row"
              onClick={() => {
                setFocusedRowIdx(idx);
                setExpandedId((cur) => (cur === s.id ? null : s.id));
              }}
              onFocus={() => setFocusedRowIdx(idx)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  setExpandedId((cur) => (cur === s.id ? null : s.id));
                }
              }}
              onMouseEnter={() => setHoveredId(s.id)}
              onMouseLeave={() => setHoveredId(null)}
              style={{
                display: "grid",
                gridTemplateColumns: SUSPECTS_GRID,
                gap: SUSPECTS_GAP,
                alignItems: "center",
                minHeight: ROW_MIN_HEIGHT,
                padding: `14px ${SUSPECTS_PAD_X}px`,
                borderLeft: `3px solid ${accent}`,
                cursor: "pointer",
                animationDelay: `${idx * 25}ms`,
                position: "relative",
              }}
            >
              {/* Patient cell */}
              <div style={{ display: "flex", alignItems: "center", gap: 12, minWidth: 0 }}>
                {isOpen && (
                  <input
                    type="checkbox"
                    checked={isSelected}
                    onChange={() => toggleSelect(s.id)}
                    onClick={(e) => e.stopPropagation()}
                    aria-label={`Select suspect ${s.id}`}
                    style={{
                      width: 14,
                      height: 14,
                      accentColor: C.brand,
                      cursor: "pointer",
                      flexShrink: 0,
                    }}
                  />
                )}
                {!isOpen && <div style={{ width: 14, flexShrink: 0 }} />}
                <div
                  aria-hidden
                  style={{
                    width: 36,
                    height: 36,
                    borderRadius: 10,
                    background: `linear-gradient(135deg, ${aColor}, ${aColor}CC)`,
                    color: tokens.white,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontSize: 12,
                    fontWeight: 700,
                    letterSpacing: "0.02em",
                    flexShrink: 0,
                    boxShadow: "inset 0 1px 0 rgba(255,255,255,0.18)",
                  }}
                >
                  {initials}
                </div>
                <div style={{ minWidth: 0, display: "flex", flexDirection: "column", gap: 2 }}>
                  <div
                    style={{
                      fontSize: 14,
                      fontWeight: 600,
                      color: C.text,
                      whiteSpace: "nowrap",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      letterSpacing: "-0.005em",
                    }}
                  >
                    {s.patient_name ?? `Patient ${s.patient_id}`}
                  </div>
                  <div
                    style={{
                      fontSize: 11,
                      color: C.label,
                      fontVariantNumeric: "tabular-nums",
                      whiteSpace: "nowrap",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                    }}
                  >
                    PID {s.patient_id} · MY {s.measurement_year ?? measurementYear}
                  </div>
                </div>
              </div>

              {/* Condition + rationale */}
              <div style={{ minWidth: 0, display: "flex", flexDirection: "column", gap: 4 }}>
                <div
                  style={{
                    fontSize: 14,
                    fontWeight: 600,
                    color: C.text,
                    whiteSpace: "nowrap",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    letterSpacing: "-0.005em",
                  }}
                  title={conditionLabel}
                >
                  {conditionLabel}
                </div>
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                    fontSize: 11,
                    color: C.textSubtle,
                    fontFamily: FONT_MONO,
                    letterSpacing: "0.01em",
                  }}
                >
                  {s.suspect_hcc != null && (
                    <FeatureFlag flagKey="kg_evidence_panel" fallback={<span>HCC {s.suspect_hcc}</span>}>
                      <HccChipWithPopover hccCode={String(s.suspect_hcc)}>
                        <span>HCC {s.suspect_hcc}</span>
                      </HccChipWithPopover>
                    </FeatureFlag>
                  )}
                  {s.suspect_hcc != null && s.suspect_icd10 && <span className="text-muted-foreground">·</span>}
                  {s.suspect_icd10 && <span>ICD {s.suspect_icd10}</span>}
                  <FeatureFlag flagKey="kg_evidence_panel">
                    <KgGapBadge
                      evidenceType={s.evidence_type}
                      suspectId={s.id}
                      hccCode={s.suspect_hcc != null ? String(s.suspect_hcc) : undefined}
                      patientId={s.patient_id}
                    />
                  </FeatureFlag>
                </div>
                <div
                  onClick={() => setExpandedRationale(prev => {
                    const next = new Set(prev);
                    next.has(s.id) ? next.delete(s.id) : next.add(s.id);
                    return next;
                  })}
                  style={{
                    fontSize: 12,
                    color: C.textSubtle,
                    fontStyle: "italic",
                    fontFamily: FONT_SYS,
                    cursor: "pointer",
                    ...(expandedRationale.has(s.id) ? {} : {
                      overflow: "hidden",
                      display: "-webkit-box",
                      WebkitLineClamp: 1,
                      WebkitBoxOrient: "vertical",
                      textOverflow: "ellipsis",
                    }),
                  }}
                  title={expandedRationale.has(s.id) ? "Click to collapse" : "Click to expand"}
                >
                  &ldquo;{rationale}&rdquo;
                </div>
              </div>

              {/* Evidence pill */}
              <div>
                <span
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 6,
                    height: 22,
                    padding: "0 10px",
                    borderRadius: 999,
                    backgroundColor: C.bgBand,
                    border: `1px solid ${C.border}`,
                    color: C.textMuted,
                    fontSize: 11,
                    fontWeight: 600,
                    textTransform: "capitalize",
                  }}
                >
                  {evidenceIcon(s.evidence_type, 11)}
                  {evidenceLabelShort(s.evidence_type)}
                </span>
              </div>

              {/* Confidence bar — numeric score shown as tooltip; label uses signal-strength words */}
              <div
                title={`Internal signal score: ${(conf * 100).toFixed(0)}% (not a calibrated probability — relative ranking only)`}
                style={{ display: "flex", flexDirection: "column", gap: 3, minWidth: 0 }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <div
                    style={{
                      flex: 1,
                      height: 6,
                      borderRadius: 4,
                      backgroundColor: confSoftBg(conf),
                      overflow: "hidden",
                      minWidth: 40,
                    }}
                  >
                    <div
                      style={{
                        height: "100%",
                        width: `${Math.max(4, conf * 100)}%`,
                        borderRadius: 4,
                        backgroundColor: cConf,
                        transition: "width 0.3s ease",
                      }}
                    />
                  </div>
                  <span
                    title={`Internal signal score: ${(conf * 100).toFixed(0)}% (not a calibrated probability)`}
                    style={{
                      fontSize: 11,
                      fontWeight: 700,
                      color: cConf,
                      fontVariantNumeric: "tabular-nums",
                      minWidth: 56,
                      textAlign: "right",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {conf >= 0.85 ? "Strong" : conf >= 0.65 ? "Moderate" : "Weak"}
                  </span>
                </div>
                {/* Calibrated chip — shown when Platt scaling has been applied */}
                {isCalibrated && (
                  <span
                    title={`Raw: ${((s.confidence_score ?? 0) * 100).toFixed(0)}% → Calibrated: ${(conf * 100).toFixed(0)}%`}
                    style={{
                      fontSize: 9,
                      fontWeight: 600,
                      letterSpacing: "0.04em",
                      color: tokens.indigoText,
                      backgroundColor: tokens.indigoBg,
                      borderRadius: 3,
                      padding: "1px 4px",
                      width: "fit-content",
                      textTransform: "uppercase" as const,
                    }}
                  >
                    calibrated
                  </span>
                )}
              </div>

              {/* RAF lift */}
              <div
                style={{
                  justifySelf: "end",
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "flex-end",
                  gap: 1,
                }}
              >
                <span
                  style={{
                    fontSize: 14,
                    fontWeight: 700,
                    color: C.brand,
                    fontVariantNumeric: "tabular-nums",
                    letterSpacing: "-0.01em",
                  }}
                >
                  +{coef.toFixed(3)}
                </span>
                <span
                  style={{
                    fontSize: 10,
                    fontWeight: 600,
                    color: C.label,
                    textTransform: "uppercase",
                    letterSpacing: "0.06em",
                  }}
                >
                  RAF
                </span>
              </div>

              {/* Revenue */}
              <div
                style={{
                  justifySelf: "end",
                  fontSize: 13,
                  fontWeight: 600,
                  color: C.text,
                  fontVariantNumeric: "tabular-nums",
                }}
              >
                {formatCurrency(revenue)}
              </div>

              {/* Status pill */}
              <div style={{ justifySelf: "end" }}>
                <span
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 6,
                    height: 22,
                    padding: "0 10px",
                    borderRadius: 999,
                    backgroundColor: pill.bg,
                    color: pill.fg,
                    border: `1px solid ${pill.border}`,
                    fontSize: 11,
                    fontWeight: 700,
                    letterSpacing: "0.02em",
                    textDecoration: s.status === "dismissed" ? "line-through" : "none",
                  }}
                >
                  <span
                    style={{
                      width: 6,
                      height: 6,
                      borderRadius: 3,
                      backgroundColor: pill.fg,
                    }}
                  />
                  {pill.label}
                </span>
              </div>

              {/* Actions */}
              <div
                style={{
                  justifySelf: "end",
                  display: "flex",
                  alignItems: "center",
                  gap: 6,
                }}
                onClick={(e) => e.stopPropagation()}
              >
                {isOpen ? (
                  <>
                    <button
                      className="row-action-btn"
                      disabled={acceptMut.isPending}
                      onClick={() => acceptMut.mutate(s.id)}
                      aria-label="Push to EMR"
                      title="Push to EMR"
                      style={{
                        width: 32,
                        height: 32,
                        borderRadius: 8,
                        border: `1px solid ${C.low}`,
                        backgroundColor: "transparent",
                        color: C.low,
                        cursor: "pointer",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                      }}
                      onMouseEnter={(e) => {
                        e.currentTarget.style.backgroundColor = C.lowSoft;
                      }}
                      onMouseLeave={(e) => {
                        e.currentTarget.style.backgroundColor = "transparent";
                      }}
                    >
                      <Check size={15} strokeWidth={2.5} />
                    </button>
                    <button
                      className="row-action-btn"
                      disabled={dismissMut.isPending}
                      onClick={() => dismissMut.mutate(s.id)}
                      aria-label="Dismiss suspect"
                      title="Dismiss"
                      style={{
                        width: 32,
                        height: 32,
                        borderRadius: 8,
                        border: `1px solid ${C.high}`,
                        backgroundColor: "transparent",
                        color: C.high,
                        cursor: "pointer",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                      }}
                      onMouseEnter={(e) => {
                        e.currentTarget.style.backgroundColor = C.highSoft;
                      }}
                      onMouseLeave={(e) => {
                        e.currentTarget.style.backgroundColor = "transparent";
                      }}
                    >
                      <X size={15} strokeWidth={2.5} />
                    </button>
                  </>
                ) : (
                  <span
                    style={{
                      fontSize: 11,
                      color: C.label,
                      display: "inline-flex",
                      alignItems: "center",
                      gap: 4,
                    }}
                  >
                    {s.status === "accepted" && <CheckCircle2 size={13} color={C.low} />}
                    {s.status === "dismissed" && <XCircle size={13} color={C.textSubtle} />}
                    {s.status === "coded" && <CheckCircle2 size={13} color={C.brand} />}
                  </span>
                )}
                <ChevronRight
                  size={14}
                  color={isExpanded || hoveredId === s.id ? C.brand : tokens.slate300}
                  style={{
                    transform: isExpanded ? "rotate(90deg)" : "rotate(0deg)",
                    transition: "transform 0.18s ease",
                  }}
                />
              </div>
            </div>
            {isExpanded && (
              <SuspectDrawerDynamic
                suspect={s}
                conf={conf}
                coef={coef}
                revenue={revenue}
                rationale={rationale}
                conditionLabel={conditionLabel}
                onOpenChart={() => router.push(`/patients/${s.patient_id}`)}
                onAccept={() => acceptMut.mutate(s.id)}
                onDismiss={() => dismissMut.mutate(s.id)}
                acceptPending={acceptMut.isPending}
                dismissPending={dismissMut.isPending}
              />
            )}
            </div>
          );
        })}
        </div>{/* /rowgroup */}
      </div>

      {/* ============================================================ */}
      {/* Pagination                                                   */}
      {/* ============================================================ */}
      {!isLoading && filteredSorted.length > PAGE_SIZE && (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            gap: 16,
            marginTop: 20,
          }}
        >
          <button
            disabled={page === 0}
            onClick={() => setPage((p) => p - 1)}
            aria-label="Previous page"
            style={{
              width: 36,
              height: 36,
              borderRadius: 10,
              border: `1px solid ${C.border}`,
              backgroundColor: tokens.white,
              cursor: page === 0 ? "default" : "pointer",
              opacity: page === 0 ? 0.4 : 1,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              color: C.textMuted,
            }}
          >
            <ChevronLeft size={16} />
          </button>
          <span
            style={{
              fontSize: 13,
              fontWeight: 600,
              color: C.textMuted,
              fontVariantNumeric: "tabular-nums",
            }}
          >
            Page {page + 1} of {totalPages}
          </span>
          <button
            disabled={page >= totalPages - 1}
            onClick={() => setPage((p) => p + 1)}
            aria-label="Next page"
            style={{
              width: 36,
              height: 36,
              borderRadius: 10,
              border: `1px solid ${C.border}`,
              backgroundColor: tokens.white,
              cursor: page >= totalPages - 1 ? "default" : "pointer",
              opacity: page >= totalPages - 1 ? 0.4 : 1,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              color: C.textMuted,
            }}
          >
            <ChevronRight size={16} />
          </button>
        </div>
      )}

      {/* ============================================================ */}
      {/* Bulk action bar                                              */}
      {/* ============================================================ */}
      {selected.size > 0 && (
        <div
          style={{
            position: "fixed",
            bottom: 20,
            left: "50%",
            transform: "translateX(-50%)",
            width: "min(720px, calc(100% - 32px))",
            backgroundColor: "rgba(15, 23, 42, 0.96)",
            backdropFilter: "blur(12px)",
            WebkitBackdropFilter: "blur(12px)",
            borderRadius: 14,
            boxShadow:
              "0 -4px 32px rgba(0, 0, 0, 0.2), 0 0 0 1px rgba(255, 255, 255, 0.06)",
            padding: "14px 20px",
            display: "flex",
            alignItems: "center",
            gap: 14,
            zIndex: 50,
          }}
        >
          <span
            style={{
              fontSize: 13,
              fontWeight: 600,
              color: tokens.white,
              display: "flex",
              alignItems: "center",
              gap: 8,
            }}
          >
            <span
              style={{
                backgroundColor: C.brand,
                color: tokens.white,
                fontSize: 12,
                fontWeight: 700,
                borderRadius: 999,
                padding: "2px 10px",
                minWidth: 24,
                textAlign: "center",
                fontVariantNumeric: "tabular-nums",
              }}
            >
              {selected.size}
            </span>
            selected
          </span>

          <div
            style={{
              width: 1,
              height: 24,
              backgroundColor: "rgba(255,255,255,0.15)",
            }}
          />

          <button
            disabled={bulkMut.isPending}
            onClick={() => { setBulkAction("accept"); bulkMut.mutate({ action: "accept" }); }}
            style={{
              height: 36,
              padding: "0 18px",
              borderRadius: 10,
              border: "none",
              backgroundColor: C.low,
              color: tokens.white,
              fontSize: 13,
              fontWeight: 700,
              cursor: bulkMut.isPending ? "not-allowed" : "pointer",
              opacity: bulkMut.isPending ? 0.6 : 1,
              display: "flex",
              alignItems: "center",
              gap: 6,
              boxShadow: "0 2px 8px rgba(5, 150, 105, 0.3)",
            }}
          >
            <Check size={14} strokeWidth={2.5} />
            {bulkMut.isPending && bulkAction === "accept" ? "Accepting\u2026" : "Accept all"}
          </button>

          <button
            disabled={bulkMut.isPending}
            onClick={() => { setBulkAction("dismiss"); bulkMut.mutate({ action: "dismiss" }); }}
            style={{
              height: 36,
              padding: "0 18px",
              borderRadius: 10,
              border: `1px solid rgba(255,255,255,0.2)`,
              backgroundColor: "transparent",
              color: tokens.white,
              fontSize: 13,
              fontWeight: 600,
              cursor: bulkMut.isPending ? "not-allowed" : "pointer",
              opacity: bulkMut.isPending ? 0.6 : 1,
              display: "flex",
              alignItems: "center",
              gap: 6,
            }}
          >
            <X size={14} strokeWidth={2.5} />
            {bulkMut.isPending && bulkAction === "dismiss" ? "Dismissing\u2026" : "Dismiss all"}
          </button>

          <button
            onClick={() => setSelected(new Set())}
            style={{
              marginLeft: "auto",
              height: 36,
              padding: "0 14px",
              borderRadius: 10,
              border: "none",
              backgroundColor: "transparent",
              color: "rgba(255,255,255,0.7)",
              fontSize: 13,
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            Clear
          </button>
        </div>
      )}

      {selected.size > 0 && <div style={{ height: 80 }} />}

      {/* EHR Problem List write-back modal */}
      <ProblemListWriteBackModal
        open={writeBackSuspect !== null}
        patientId={writeBackSuspect?.patient_id ?? 0}
        patientName={writeBackSuspect?.patient_name}
        icd10={writeBackSuspect?.suspect_icd10 ?? ""}
        hccCode={writeBackSuspect ? String(writeBackSuspect.suspect_hcc) : null}
        evidenceText={
          typeof writeBackSuspect?.evidence_detail === "string"
            ? writeBackSuspect.evidence_detail
            : writeBackSuspect?.evidence_detail?.rationale ?? null
        }
        onClose={() => setWriteBackSuspect(null)}
      />
    </div>
  );
}

/* ================================================================== */
/*  SuspectDrawer — inline expanded row                                */
/* ================================================================== */

function SuspectDrawer({
  suspect,
  conf,
  coef,
  revenue,
  rationale,
  conditionLabel,
  onOpenChart,
  onAccept,
  onDismiss,
  acceptPending,
  dismissPending,
}: {
  suspect: DBSuspect;
  conf: number;
  coef: number;
  revenue: number;
  rationale: string;
  conditionLabel: string;
  onOpenChart: () => void;
  onAccept: () => void;
  onDismiss: () => void;
  acceptPending: boolean;
  dismissPending: boolean;
}) {
  const s = suspect;
  const isOpen = (s.status || "open") === "open";
  const cConf = confColor(conf);

  // Parse evidence_detail if it's a JSON string
  const evidenceLines: { label: string; value: string }[] = [];
  const detail = s.evidence_detail;
  try {
    const obj =
      typeof detail === "string" && detail.trim().startsWith("{")
        ? JSON.parse(detail)
        : detail && typeof detail === "object"
          ? detail
          : null;
    if (obj && typeof obj === "object") {
      for (const [k, v] of Object.entries(obj)) {
        if (v == null || v === "") continue;
        const label = k.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
        const value =
          typeof v === "object" ? JSON.stringify(v) : String(v);
        evidenceLines.push({ label, value });
      }
    }
  } catch {
    // ignore
  }

  const fmtDate = (d?: string) => {
    if (!d) return "—";
    try {
      return new Date(d).toLocaleDateString(undefined, {
        year: "numeric",
        month: "short",
        day: "numeric",
      });
    } catch {
      return d;
    }
  };

  return (
    <div
      onClick={(e) => e.stopPropagation()}
      style={{
        padding: "18px 22px 22px 22px",
        backgroundColor: tokens.bgFaintCard,
        borderTop: `1px solid ${C.borderSoft}`,
        borderLeft: `3px solid ${confAccent(conf)}`,
        display: "grid",
        gridTemplateColumns: "minmax(0, 1.4fr) minmax(0, 1fr)",
        gap: 24,
        animation: "drawerFadeIn 0.22s ease",
      }}
    >
      <style>{`
        @media (prefers-reduced-motion: no-preference) {
          @keyframes drawerFadeIn {
            from { opacity: 0; transform: translateY(-4px); }
            to { opacity: 1; transform: translateY(0); }
          }
        }
      `}</style>

      {/* LEFT — Clinical evidence */}
      <div style={{ minWidth: 0, display: "flex", flexDirection: "column", gap: 16 }}>
        <div>
          <div
            style={{
              fontSize: 10,
              fontWeight: 700,
              color: C.label,
              textTransform: "uppercase",
              letterSpacing: "0.08em",
              marginBottom: 6,
            }}
          >
            Why we flagged this
          </div>
          <div
            style={{
              fontSize: 14,
              lineHeight: 1.55,
              color: C.text,
              fontStyle: "italic",
              padding: "12px 14px",
              borderRadius: 10,
              backgroundColor: C.white,
              border: `1px solid ${C.borderSoft}`,
            }}
          >
            &ldquo;{rationale}&rdquo;
          </div>
        </div>

        {evidenceLines.length > 0 && (
          <div>
            <div
              style={{
                fontSize: 10,
                fontWeight: 700,
                color: C.label,
                textTransform: "uppercase",
                letterSpacing: "0.08em",
                marginBottom: 6,
              }}
            >
              Supporting evidence
            </div>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
                gap: 8,
                padding: 12,
                borderRadius: 10,
                backgroundColor: C.white,
                border: `1px solid ${C.borderSoft}`,
              }}
            >
              {evidenceLines.map((ln, i) => (
                <div key={i} style={{ minWidth: 0 }}>
                  <div
                    style={{
                      fontSize: 10,
                      color: C.label,
                      textTransform: "uppercase",
                      letterSpacing: "0.06em",
                      fontWeight: 600,
                      marginBottom: 2,
                    }}
                  >
                    {ln.label}
                  </div>
                  <div
                    style={{
                      fontSize: 12,
                      color: C.text,
                      fontFamily: FONT_MONO,
                      wordBreak: "break-word",
                    }}
                  >
                    {ln.value}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        <div
          style={{
            display: "flex",
            gap: 16,
            fontSize: 11,
            color: C.textSubtle,
          }}
        >
          <span>
            <span className="text-muted-foreground">Detected </span>
            {fmtDate(s.created_at)}
          </span>
          {s.reviewed_at && (
            <span>
              <span className="text-muted-foreground">Reviewed </span>
              {fmtDate(s.reviewed_at)}
              {s.reviewed_by && <span className="text-muted-foreground"> · {s.reviewed_by}</span>}
            </span>
          )}
        </div>
      </div>

      {/* RIGHT — Code card + actions */}
      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <div
          style={{
            padding: 16,
            borderRadius: 12,
            backgroundColor: C.white,
            border: `1px solid ${C.border}`,
          }}
        >
          <div
            style={{
              fontSize: 10,
              fontWeight: 700,
              color: C.label,
              textTransform: "uppercase",
              letterSpacing: "0.08em",
              marginBottom: 8,
            }}
          >
            Suspected Code
          </div>
          <div
            style={{
              fontSize: 15,
              fontWeight: 700,
              color: C.text,
              marginBottom: 6,
              letterSpacing: "-0.01em",
            }}
          >
            {conditionLabel}
          </div>
          <div
            style={{
              display: "flex",
              gap: 8,
              fontFamily: FONT_MONO,
              fontSize: 11,
              color: C.textMuted,
              marginBottom: 12,
            }}
          >
            {s.suspect_hcc != null && (
              <FeatureFlag
                flagKey="kg_evidence_panel"
                fallback={
                  <span
                    style={{
                      padding: "2px 8px",
                      borderRadius: 6,
                      backgroundColor: C.brandSoft,
                      color: C.brand,
                      fontWeight: 700,
                    }}
                  >
                    HCC {s.suspect_hcc}
                  </span>
                }
              >
                <HccChipWithPopover hccCode={String(s.suspect_hcc)}>
                  <span
                    style={{
                      padding: "2px 8px",
                      borderRadius: 6,
                      backgroundColor: C.brandSoft,
                      color: C.brand,
                      fontWeight: 700,
                    }}
                  >
                    HCC {s.suspect_hcc}
                  </span>
                </HccChipWithPopover>
              </FeatureFlag>
            )}
            {s.suspect_icd10 && (
              <span
                style={{
                  padding: "2px 8px",
                  borderRadius: 6,
                  backgroundColor: C.bgSubtle,
                  border: `1px solid ${C.borderSoft}`,
                  fontWeight: 700,
                }}
              >
                ICD {s.suspect_icd10}
              </span>
            )}
          </div>

          <div
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 1fr 1fr",
              gap: 10,
              paddingTop: 12,
              borderTop: `1px solid ${C.borderSoft}`,
            }}
          >
            <div>
              <div className="text-muted-foreground" style={{ fontSize: 9, textTransform: "uppercase", letterSpacing: "0.06em", fontWeight: 700 }}>
                Signal
              </div>
              <div
                style={{ fontSize: 16, fontWeight: 700, color: cConf }}
                title={`Internal signal score: ${(conf * 100).toFixed(0)}% (not a calibrated probability)`}
              >
                {conf >= 0.85 ? "Strong" : conf >= 0.65 ? "Moderate" : "Weak"}
              </div>
            </div>
            <div>
              <div className="text-muted-foreground" style={{ fontSize: 9, textTransform: "uppercase", letterSpacing: "0.06em", fontWeight: 700 }}>
                RAF Lift
              </div>
              <div style={{ fontSize: 16, fontWeight: 700, color: C.brand, fontVariantNumeric: "tabular-nums" }}>
                +{coef.toFixed(3)}
              </div>
            </div>
            <div>
              <div className="text-muted-foreground" style={{ fontSize: 9, textTransform: "uppercase", letterSpacing: "0.06em", fontWeight: 700 }}>
                Revenue
              </div>
              <div className="text-foreground" style={{ fontSize: 16, fontWeight: 700, fontVariantNumeric: "tabular-nums" }}>
                {formatCurrency(revenue)}
              </div>
            </div>
          </div>
        </div>

        {isOpen && (
          <div style={{ display: "flex", gap: 8 }}>
            <button
              onClick={onAccept}
              disabled={acceptPending}
              style={{
                flex: 1,
                height: 40,
                borderRadius: 10,
                border: "none",
                backgroundColor: C.low,
                color: tokens.white,
                fontSize: 13,
                fontWeight: 700,
                cursor: acceptPending ? "default" : "pointer",
                opacity: acceptPending ? 0.6 : 1,
                display: "inline-flex",
                alignItems: "center",
                justifyContent: "center",
                gap: 6,
                letterSpacing: "0.01em",
              }}
            >
              <Check size={15} strokeWidth={2.5} />
              Push to EMR
            </button>
            <button
              onClick={onDismiss}
              disabled={dismissPending}
              style={{
                flex: 1,
                height: 40,
                borderRadius: 10,
                border: `1px solid ${C.high}`,
                backgroundColor: tokens.white,
                color: C.high,
                fontSize: 13,
                fontWeight: 700,
                cursor: dismissPending ? "default" : "pointer",
                opacity: dismissPending ? 0.6 : 1,
                display: "inline-flex",
                alignItems: "center",
                justifyContent: "center",
                gap: 6,
                letterSpacing: "0.01em",
              }}
            >
              <X size={15} strokeWidth={2.5} />
              Dismiss
            </button>
          </div>
        )}

        <button
          onClick={onOpenChart}
          style={{
            height: 40,
            borderRadius: 10,
            border: `1px solid ${C.brand}`,
            backgroundColor: C.brandSoft,
            color: C.brand,
            fontSize: 13,
            fontWeight: 700,
            cursor: "pointer",
            display: "inline-flex",
            alignItems: "center",
            justifyContent: "center",
            gap: 8,
            letterSpacing: "0.01em",
          }}
        >
          <FileSearch size={15} strokeWidth={2.2} />
          Open Patient Chart
          <ChevronRight size={14} />
        </button>
      </div>
    </div>
  );
}
