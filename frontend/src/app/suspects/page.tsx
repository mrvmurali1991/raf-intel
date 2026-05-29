"use client";

import React, { useState, useMemo, useCallback, useEffect, useRef, useId } from "react";
import dynamic from "next/dynamic";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { registerContextShortcut } from "@/lib/keyboard-shortcuts";
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
  SearchCheck,
} from "lucide-react";
import { downloadCSV } from "@/lib/csv-export";
import { C, FONT_MONO, initialsColor, deriveInitials } from "@/lib/ui-utils";
import { MA_PAYMENT_PER_RAF } from "@/lib/constants";
import FeatureFlag from "@/components/FeatureFlag";
import { HelpButton } from "@/components/HelpPanel";
import { KgGapBadge } from "@/components/kg/KgGapBadge";
import { HccChipWithPopover } from "@/components/kg/HccExplainCard";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { EmptyState } from "@/components/ui/empty-state";
import { PageHeader } from "@/components/ui/page-header";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { humanizeEvidence } from "@/lib/evidence-labels";

// ── Dynamic import: defer SuspectDrawer expanded-row detail (~30 kB) ──
const SuspectDrawerDynamic = dynamic(
  () => import("./SuspectDrawer"),
  {
    ssr: false,
    loading: () => (
      <div className="px-6 py-5 bg-muted/30 border-t border-border">
        <div className="h-24 rounded-xl bg-muted animate-pulse" />
      </div>
    ),
  }
);

/* ================================================================== */
/*  Page-specific constants                                            */
/* ================================================================== */

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

// Confidence band labels use signal-strength words — NOT calibrated percentages.
// The raw scores are relative ranking signals only (see nlp_suspect_extractor.py).
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
  if (!type) return "Clinical";
  // Known values get fixed short labels; everything else goes through humanizeEvidence
  // which maps backend field names (evidence_v1, etc.) to readable strings.
  switch (type) {
    case "medication": return "Medication";
    case "lab": return "Lab";
    case "imaging": return "Imaging";
    case "referral": return "Referral";
    case "historical": return "Historical";
    default: return humanizeEvidence(type);
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
  const coef = (s as unknown as { hcc_coefficient?: number }).hcc_coefficient;
  if (typeof coef === "number" && coef > 0) return coef;
  return 0.25;
}

function formatCurrency(n: number): string {
  if (!isFinite(n) || n === 0) return "Awaiting data ingestion";
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
/*  Skeleton rows for loading state                                    */
/* ================================================================== */

function SkeletonRows() {
  return (
    <>
      {Array.from({ length: 8 }).map((_, i) => (
        <TableRow
          key={i}
          className="animate-pulse"
          style={{ animationDelay: `${i * 80}ms` }}
        >
          {/* Patient */}
          <TableCell className="py-2.5 pl-6">
            <div className="flex items-center gap-3">
              <div className="w-8 h-8 rounded-lg bg-muted shrink-0" />
              <div className="flex flex-col gap-1.5 flex-1 min-w-0">
                <div className="h-3 w-2/3 rounded bg-muted" />
                <div className="h-2.5 w-1/2 rounded bg-muted/70" />
              </div>
            </div>
          </TableCell>
          {/* Condition */}
          <TableCell className="py-2.5">
            <div className="flex flex-col gap-1.5">
              <div className="h-3 w-4/5 rounded bg-muted" />
              <div className="h-2.5 w-3/5 rounded bg-muted/70" />
            </div>
          </TableCell>
          {/* Evidence */}
          <TableCell className="py-2.5">
            <div className="h-5 w-24 rounded-full bg-muted" />
          </TableCell>
          {/* Confidence */}
          <TableCell className="py-2.5">
            <div className="flex items-center gap-2">
              <div className="flex-1 h-1.5 rounded bg-muted" />
              <div className="w-14 h-3 rounded bg-muted" />
            </div>
          </TableCell>
          {/* RAF */}
          <TableCell className="py-2.5 text-right">
            <div className="h-3.5 w-14 rounded bg-muted ml-auto" />
          </TableCell>
          {/* Revenue */}
          <TableCell className="py-2.5 text-right">
            <div className="h-3.5 w-16 rounded bg-muted ml-auto" />
          </TableCell>
          {/* Status */}
          <TableCell className="py-2.5 text-right">
            <div className="h-5 w-20 rounded-full bg-muted ml-auto" />
          </TableCell>
          {/* Actions */}
          <TableCell className="py-2.5 pr-6 text-right">
            <div className="h-7 w-16 rounded-lg bg-muted ml-auto" />
          </TableCell>
        </TableRow>
      ))}
    </>
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
  const rowRefs = useRef<Array<HTMLTableRowElement | null>>([]);

  const [hoveredId, setHoveredId] = useState<number | null>(null);
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [expandedRationale, setExpandedRationale] = useState<Set<number>>(new Set());
  const [bulkAction, setBulkAction] = useState<"accept" | "dismiss" | null>(null);
  const { paymentYear: measurementYear, setPaymentYear: setMeasurementYear } = usePaymentYear();

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
    return { openCount: openSet.length, totalUplift, totalRevenue, avgConf };
  }, [allSuspects]);

  /* --- Mutations --------------------------------------------------- */

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
          const timer = setTimeout(() => { undoTimers.current.delete(id); }, 5500);
          undoTimers.current.set(id, timer);
          toast.success("Accepted", "Suspect accepted & written to OpenEMR.", {
            duration: 5500,
            action: {
              label: "Undo",
              onClick: () => {
                const t = undoTimers.current.get(id);
                if (t) { clearTimeout(t); undoTimers.current.delete(id); }
                undoMut.mutate({ id, kind: "accept" });
              },
            },
          });
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
          const timer = setTimeout(() => { undoTimers.current.delete(id); }, 5500);
          undoTimers.current.set(id, timer);
          toast.success("Dismissed", "Suspect condition dismissed.", {
            duration: 5500,
            action: {
              label: "Undo",
              onClick: () => {
                const t = undoTimers.current.get(id);
                if (t) { clearTimeout(t); undoTimers.current.delete(id); }
                undoMut.mutate({ id, kind: "dismiss" });
              },
            },
          });
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

  useEffect(() => {
    setFocusedRowIdx(0);
  }, [filteredSorted.length, page]);

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
      if (row && (row.status || "open") === "open") acceptMut.mutate(row.id);
    });

    const unregDismiss = registerContextShortcut("dismiss-focused-suspect", () => {
      if (isTyping()) return;
      const row = pagedSuspects[focusedRowIdx];
      if (row && (row.status || "open") === "open") dismissMut.mutate(row.id);
    });

    const unregReview = registerContextShortcut("mark-meat-reviewed", () => {
      if (isTyping()) return;
      const row = pagedSuspects[focusedRowIdx];
      if (row) router.push(`/patients/${row.patient_id}?tab=suspects`);
    });

    return () => {
      unregAccept();
      unregDismiss();
      unregReview();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusedRowIdx, pagedSuspects]);

  // Arrow / J / K key navigation across rows
  const handleListKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTableSectionElement>) => {
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
  /*  Filter bar helpers                                             */
  /* ============================================================== */

  const PRIMARY_STATUS: StatusTab[] = ["all", "open", "accepted"];
  const MORE_STATUS: StatusTab[] = ["dismissed", "coded"];

  const moreActiveCount =
    (MORE_STATUS.includes(statusFilter) ? 1 : 0) +
    (evidenceFilter !== "all" ? 1 : 0) +
    (confidenceBand !== "all" ? 1 : 0);

  const handleMenuKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    const items = Array.from(
      morePopoverRef.current?.querySelectorAll<HTMLElement>("[data-menu-item]") ?? []
    );
    const idx = items.indexOf(e.target as HTMLElement);
    if (e.key === "ArrowDown") { e.preventDefault(); items[(idx + 1) % items.length]?.focus(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); items[(idx - 1 + items.length) % items.length]?.focus(); }
    else if (e.key === "Escape") { setMoreOpen(false); moreTriggerRef.current?.focus(); }
  };

  /* ============================================================== */
  /*  Render                                                         */
  /* ============================================================== */

  return (
    <TooltipProvider delayDuration={200}>
      <div className="p-6 pb-12 min-h-screen bg-background">

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

        {/* ── Error Banner ───────────────────────────────────────── */}
        {isError && (
          <div
            role="alert"
            className="flex items-center gap-3 bg-destructive/10 border border-destructive/30 rounded-lg px-4 py-3 mb-5 text-sm font-semibold text-destructive"
          >
            <AlertCircle size={18} aria-hidden="true" />
            Failed to load suspects. Please check the server connection and refresh.
          </div>
        )}

        {/* ── Page Header ────────────────────────────────────────── */}
        <PageHeader
          icon={<Sparkles size={20} aria-hidden="true" />}
          title={
            <span className="flex items-center gap-2.5 flex-wrap">
              Suspect Conditions
              <Tooltip>
                <TooltipTrigger asChild>
                  <span className="inline-flex items-center gap-1 h-6 pl-2.5 pr-1 rounded-lg border text-[11px] font-bold tracking-wide cursor-default select-none"
                    style={{
                      backgroundColor: C.brandSoft,
                      borderColor: C.brandRing,
                      color: C.brand,
                    }}
                  >
                    MY
                    <select
                      value={measurementYear}
                      onChange={(e) => setMeasurementYear(Number(e.target.value))}
                      aria-label="Measurement year"
                      className="bg-transparent border-none text-[12px] font-bold cursor-pointer pr-5 pl-0.5 focus:outline-none appearance-none"
                      style={{
                        color: C.brand,
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
                  </span>
                </TooltipTrigger>
                <TooltipContent side="bottom">
                  Measurement year — affects HCC code set (V28 for 2026+)
                </TooltipContent>
              </Tooltip>
            </span>
          }
          subtitle={
            isLoading
              ? "Loading review queue…"
              : `${heroStats.openCount.toLocaleString()} open suspects · ${formatCurrency(heroStats.totalRevenue)} estimated RAF opportunity · CMS-HCC V28`
          }
          actions={<HelpButton />}
        />

        {/* ── Hero Stats Strip — compact KPI pill row ─────────────── */}
        <div
          className="flex items-center gap-1.5 flex-wrap mb-5 px-4 py-2.5 bg-card border border-border rounded-lg shadow-sm"
          aria-label="Key performance indicators"
        >
          {isLoading ? (
            <div className="h-4 w-64 rounded bg-muted animate-pulse" />
          ) : (
            <>
              <Tooltip>
                <TooltipTrigger asChild>
                  <span className="inline-flex items-center gap-1.5 text-[12px] font-semibold text-foreground cursor-default">
                    <ClipboardList size={13} style={{ color: C.blue }} aria-hidden="true" />
                    <span className="text-muted-foreground">Open:</span>
                    <span className="tabular-nums font-bold">{heroStats.openCount.toLocaleString()}</span>
                  </span>
                </TooltipTrigger>
                <TooltipContent side="bottom">Open suspects in MY {measurementYear}</TooltipContent>
              </Tooltip>

              <span className="text-muted-foreground/40 text-[12px] select-none" aria-hidden="true">|</span>

              <Tooltip>
                <TooltipTrigger asChild>
                  <span className="inline-flex items-center gap-1.5 text-[12px] font-semibold text-foreground cursor-default">
                    <Activity size={13} style={{ color: C.medium }} aria-hidden="true" />
                    <span className="text-muted-foreground">High Confidence:</span>
                    <span className="tabular-nums font-bold">
                      {allSuspects.filter((s) => (s.confidence_score ?? 0) >= 0.85 && (s.status || "open") === "open").length}
                    </span>
                  </span>
                </TooltipTrigger>
                <TooltipContent side="bottom">Open suspects with confidence score &ge;85%</TooltipContent>
              </Tooltip>

              <span className="text-muted-foreground/40 text-[12px] select-none" aria-hidden="true">|</span>

              <Tooltip>
                <TooltipTrigger asChild>
                  <span className="inline-flex items-center gap-1.5 text-[12px] font-semibold text-foreground cursor-default">
                    <DollarSign size={13} style={{ color: C.low }} aria-hidden="true" />
                    <span className="text-muted-foreground">Revenue at Risk:</span>
                    <span className="tabular-nums font-bold" style={{ color: C.low }}>
                      {heroStats.totalRevenue > 0
                        ? `$${Math.round(heroStats.totalRevenue / 1000)}K`
                        : "—"}
                    </span>
                  </span>
                </TooltipTrigger>
                <TooltipContent side="bottom">
                  Estimated annual revenue = RAF uplift &times; ${REVENUE_PER_RAF.toLocaleString()}/point (CMS V28, 2026)
                </TooltipContent>
              </Tooltip>

              <span className="text-muted-foreground/40 text-[12px] select-none" aria-hidden="true">|</span>

              <Tooltip>
                <TooltipTrigger asChild>
                  <span className="inline-flex items-center gap-1.5 text-[12px] font-semibold text-foreground cursor-default">
                    <TrendingUp size={13} style={{ color: C.brand }} aria-hidden="true" />
                    <span className="text-muted-foreground">Avg Confidence:</span>
                    <span className="tabular-nums font-bold">
                      {heroStats.avgConf > 0 ? `${(heroStats.avgConf * 100).toFixed(0)}%` : "—"}
                    </span>
                  </span>
                </TooltipTrigger>
                <TooltipContent side="bottom">Average AI confidence score across open suspects</TooltipContent>
              </Tooltip>
            </>
          )}
        </div>

        {/* ── Filter Strip ───────────────────────────────────────── */}
        <div className="flex items-center gap-2 flex-wrap mb-3.5">

          {/* Search — first in visual order */}
          <div className="relative shrink-0">
            <Search
              size={13}
              className="absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground pointer-events-none"
              aria-hidden="true"
            />
            <input
              type="text"
              placeholder="Search suspects…"
              value={searchTerm}
              onChange={(e) => { setSearchTerm(e.target.value); setPage(0); }}
              onKeyDown={(e) => e.stopPropagation()}
              aria-label="Search suspects"
              className="h-8 w-[200px] rounded-lg border border-border bg-card pl-7 pr-3 text-[12px] text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/25 focus:border-primary transition-all"
            />
          </div>

          {/* Divider */}
          <div className="w-px h-5 bg-border shrink-0" aria-hidden="true" />

          {/* Primary status chips */}
          <div
            className="inline-flex items-center bg-card border border-border rounded-lg p-0.5 gap-0.5 h-8"
            role="group"
            aria-label="Status filter"
          >
            {STATUS_TABS.filter((t) => PRIMARY_STATUS.includes(t.value)).map(({ value, label, dot }) => {
              const active = statusFilter === value;
              const chipTooltip: Record<string, string> = {
                all: "Show all suspects regardless of status",
                open: "Suspects not yet reviewed — requires coder action",
                accepted: "Suspects accepted and written to OpenEMR",
              };
              return (
                <Tooltip key={value}>
                  <TooltipTrigger asChild>
                    <button
                      onClick={(e) => { e.stopPropagation(); handleStatusChange(value); }}
                      onKeyDown={(e) => e.stopPropagation()}
                      aria-pressed={active}
                      className={cn(
                        "inline-flex items-center gap-1.5 h-6 px-3 rounded-md text-[12px] font-semibold transition-all duration-150 border-0 cursor-pointer whitespace-nowrap",
                        active
                          ? "bg-foreground text-background"
                          : "bg-transparent text-muted-foreground hover:bg-muted hover:text-foreground"
                      )}
                    >
                      {dot && (
                        <span
                          className="w-1.5 h-1.5 rounded-full shrink-0"
                          style={{ backgroundColor: dot }}
                          aria-hidden="true"
                        />
                      )}
                      {label}
                      <span className={cn(
                        "text-[11px] font-semibold tabular-nums",
                        active ? "text-background/70" : "text-muted-foreground"
                      )}>
                        {statusCounts[value]}
                      </span>
                    </button>
                  </TooltipTrigger>
                  <TooltipContent side="bottom">{chipTooltip[value]}</TooltipContent>
                </Tooltip>
              );
            })}
          </div>

          {/* "More filters" trigger + popover */}
          <div className="relative">
            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  ref={moreTriggerRef}
                  id={`${moreMenuId}-btn`}
                  aria-haspopup="true"
                  aria-expanded={moreOpen}
                  aria-controls={`${moreMenuId}-menu`}
                  onClick={() => setMoreOpen((o) => !o)}
                  className={cn(
                    "inline-flex items-center gap-1.5 h-8 px-3 rounded-lg border text-[12px] font-semibold transition-all duration-150 cursor-pointer",
                    moreActiveCount > 0
                      ? "border-primary/30 bg-primary/8 text-primary"
                      : "border-border bg-card text-muted-foreground hover:bg-muted"
                  )}
                >
                  More filters
                  {moreActiveCount > 0 && (
                    <span
                      aria-label={`${moreActiveCount} active`}
                      className="inline-flex items-center justify-center min-w-[18px] h-[18px] rounded-full text-[10px] font-bold px-1 text-white"
                      style={{ backgroundColor: C.brand }}
                    >
                      {moreActiveCount}
                    </span>
                  )}
                  <ChevronDown
                    size={13}
                    className="transition-transform duration-150"
                    style={{ transform: moreOpen ? "rotate(180deg)" : "none" }}
                    aria-hidden="true"
                  />
                </button>
              </TooltipTrigger>
              <TooltipContent side="bottom">
                Filter by status (Dismissed / Coded), evidence source, or confidence signal
              </TooltipContent>
            </Tooltip>

            {moreOpen && (
              <div
                ref={morePopoverRef}
                id={`${moreMenuId}-menu`}
                role="dialog"
                aria-label="More filters"
                onKeyDown={handleMenuKeyDown}
                className="absolute top-[calc(100%+6px)] left-0 z-[120] bg-card border border-border rounded-lg shadow-lg p-4 min-w-[280px] flex flex-col gap-3.5"
              >
                {/* Status: Dismissed / Coded */}
                <div>
                  <p className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground mb-1.5">
                    Status
                  </p>
                  <div className="flex flex-wrap gap-1.5">
                    {STATUS_TABS.filter((t) => MORE_STATUS.includes(t.value)).map(({ value, label, dot }) => {
                      const active = statusFilter === value;
                      return (
                        <button
                          key={value}
                          data-menu-item
                          onClick={() => { handleStatusChange(value); setMoreOpen(false); }}
                          aria-pressed={active}
                          className={cn(
                            "inline-flex items-center gap-1.5 h-[30px] px-3 rounded-lg border text-[12px] font-semibold transition-all cursor-pointer",
                            active
                              ? "border-primary/30 bg-primary/8 text-primary"
                              : "border-border bg-muted/50 text-muted-foreground hover:bg-muted"
                          )}
                        >
                          {dot && (
                            <span
                              className="w-1.5 h-1.5 rounded-full"
                              style={{ backgroundColor: dot }}
                              aria-hidden="true"
                            />
                          )}
                          {label}
                          <span className="text-[10px] tabular-nums">{statusCounts[value]}</span>
                          {active && (
                            <X
                              size={10}
                              onClick={(e) => { e.stopPropagation(); handleStatusChange("open"); }}
                              aria-label={`Remove ${label} filter`}
                            />
                          )}
                        </button>
                      );
                    })}
                  </div>
                </div>
                <div className="h-px bg-border" />

                {/* Evidence source */}
                <div>
                  <p className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground mb-1.5">
                    Evidence source
                  </p>
                  <div className="flex flex-wrap gap-1.5">
                    {EVIDENCE_FILTERS.filter((f) => f.value !== "all").map(({ value, label }) => {
                      const active = evidenceFilter === value;
                      return (
                        <button
                          key={value}
                          data-menu-item
                          onClick={() => { setEvidenceFilter(active ? "all" : value); setPage(0); }}
                          aria-pressed={active}
                          className={cn(
                            "inline-flex items-center gap-1.5 h-[30px] px-2.5 rounded-lg border text-[12px] font-semibold transition-all cursor-pointer",
                            active
                              ? "border-primary/30 bg-primary/8 text-primary"
                              : "border-border bg-muted/50 text-muted-foreground hover:bg-muted"
                          )}
                        >
                          {evidenceIcon(value, 11)}
                          {label}
                          {active && <X size={10} aria-label={`Remove ${label} filter`} />}
                        </button>
                      );
                    })}
                  </div>
                </div>
                <div className="h-px bg-border" />

                {/* Confidence signal */}
                <div>
                  <p className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground mb-1.5">
                    Confidence signal
                  </p>
                  <div className="flex flex-wrap gap-1.5">
                    {CONFIDENCE_OPTIONS.filter((o) => o.value !== "all").map(({ value, label, color }) => {
                      const active = confidenceBand === value;
                      return (
                        <button
                          key={value}
                          data-menu-item
                          onClick={() => { setConfidenceBand(active ? "all" : value); setPage(0); }}
                          aria-pressed={active}
                          className="inline-flex items-center gap-1.5 h-[30px] px-2.5 rounded-lg border text-[12px] font-semibold transition-all cursor-pointer"
                          style={{
                            borderColor: active ? color : undefined,
                            backgroundColor: active ? `${color}14` : undefined,
                            color: active ? color : undefined,
                          }}
                        >
                          <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: color }} aria-hidden="true" />
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
              <button
                key={`active-${statusFilter}`}
                onClick={() => handleStatusChange("open")}
                aria-label={`Remove ${t.label} filter`}
                className="inline-flex items-center gap-1.5 h-7 px-2.5 rounded-full border text-[12px] font-semibold transition-all cursor-pointer"
                style={{ borderColor: C.brand, backgroundColor: C.brandSoft, color: C.brand }}
              >
                {t.dot && <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: t.dot }} aria-hidden="true" />}
                {t.label} <X size={11} aria-hidden="true" />
              </button>
            );
          })()}

          {evidenceFilter !== "all" && (
            <button
              onClick={() => { setEvidenceFilter("all"); setPage(0); }}
              aria-label={`Remove evidence filter: ${evidenceFilter}`}
              className="inline-flex items-center gap-1.5 h-7 px-2.5 rounded-full border text-[12px] font-semibold cursor-pointer"
              style={{ borderColor: C.brand, backgroundColor: C.brandSoft, color: C.brand }}
            >
              {evidenceIcon(evidenceFilter, 11)}
              {EVIDENCE_FILTERS.find((f) => f.value === evidenceFilter)?.label}
              <X size={11} aria-hidden="true" />
            </button>
          )}

          {confidenceBand !== "all" && (() => {
            const opt = CONFIDENCE_OPTIONS.find((o) => o.value === confidenceBand)!;
            return (
              <button
                onClick={() => { setConfidenceBand("all"); setPage(0); }}
                aria-label={`Remove confidence filter: ${opt.label}`}
                className="inline-flex items-center gap-1.5 h-7 px-2.5 rounded-full border text-[12px] font-semibold cursor-pointer"
                style={{ borderColor: opt.color, backgroundColor: `${opt.color}14`, color: opt.color }}
              >
                <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: opt.color }} aria-hidden="true" />
                {opt.label} <X size={11} aria-hidden="true" />
              </button>
            );
          })()}

          {/* Sort */}
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                onClick={() => setSortField((f) => f === "confidence" ? "raf" : f === "raf" ? "patient" : "confidence")}
                className="inline-flex items-center gap-1.5 h-8 px-3 rounded-lg border border-border bg-card text-muted-foreground text-[12px] font-semibold cursor-pointer hover:bg-muted transition-colors"
              >
                Sort: {sortField === "confidence" ? "Confidence" : sortField === "raf" ? "RAF lift" : "Patient"}
              </button>
            </TooltipTrigger>
            <TooltipContent side="bottom">
              {sortField === "confidence"
                ? "Sorted by AI confidence score — highest signal first. Click to switch to RAF lift."
                : sortField === "raf"
                ? "Sorted by RAF coefficient — highest revenue impact first. Click to switch to patient name."
                : "Sorted alphabetically by patient name. Click to switch to confidence."}
            </TooltipContent>
          </Tooltip>

          {hasActiveFilters && (
            <button
              onClick={clearAllFilters}
              className="inline-flex items-center gap-1.5 h-8 px-3 rounded-full border border-dashed border-border bg-transparent text-muted-foreground text-[12px] font-semibold cursor-pointer hover:border-foreground/30 transition-colors"
            >
              <X size={12} aria-hidden="true" /> Clear filters
            </button>
          )}

          {/* Export */}
          <Button
            onClick={exportSuspectsCSV}
            aria-label="Export suspects as CSV"
            className="h-8 gap-1.5 text-[12px] font-semibold shrink-0"
            size="sm"
          >
            <FileDown size={13} aria-hidden="true" />
            Export
          </Button>
        </div>

        {/* ── Meta row: count + keyboard hints ──────────────────── */}
        <div
          className="flex items-center justify-between flex-wrap gap-2 mb-2"
          aria-label="Keyboard shortcuts: use Up/Down or J/K to navigate rows, then A to accept, D to dismiss, R to open chart"
        >
          <p className="text-[12px] font-semibold text-muted-foreground tabular-nums">
            Showing {Math.min(filteredSorted.length, (page + 1) * PAGE_SIZE).toLocaleString()} of {filteredSorted.length.toLocaleString()}
            {filteredSorted.length !== allSuspects.length && (
              <span className="font-normal"> (filtered from {allSuspects.length.toLocaleString()})</span>
            )}
          </p>
          <div className="flex items-center gap-3 text-[11px] text-muted-foreground">
            {(
              [
                ["↑↓", "Navigate"],
                ["A", "Accept"],
                ["D", "Dismiss"],
                ["R", "Chart"],
              ] as [string, string][]
            ).map(([key, desc]) => (
              <span key={key} className="inline-flex items-center gap-1">
                <kbd className="inline-flex items-center justify-center min-w-[20px] h-4.5 px-1 rounded border border-border bg-muted font-mono text-[10px] font-bold text-muted-foreground shadow-[0_1px_1px_rgba(0,0,0,0.06)]">
                  {key}
                </kbd>
                <span>{desc}</span>
              </span>
            ))}
          </div>
        </div>

        {/* ── Suspects Table ─────────────────────────────────────── */}
        <div
          role="grid"
          aria-label="Suspected conditions"
          className="bg-card border border-border rounded-xl overflow-x-auto shadow-sm"
        >
          <Table>
            <TableHeader>
              <TableRow className="bg-muted/40 hover:bg-muted/40">
                <TableHead
                  className="pl-6 py-3 text-[11px] font-semibold uppercase tracking-widest text-muted-foreground"
                  role="columnheader"
                  aria-sort={sortField === "patient" ? "ascending" : "none"}
                >
                  <div className="flex items-center gap-2.5">
                    {selectableIds.length > 0 && (
                      <input
                        type="checkbox"
                        checked={allSelected}
                        onChange={toggleAll}
                        aria-label="Select all on page"
                        className="w-3.5 h-3.5 cursor-pointer accent-primary"
                      />
                    )}
                    Patient
                  </div>
                </TableHead>
                <TableHead className="py-3 text-[11px] font-semibold uppercase tracking-widest text-muted-foreground" role="columnheader">
                  Suspected Condition
                </TableHead>
                <TableHead className="py-3 text-[11px] font-semibold uppercase tracking-widest text-muted-foreground" role="columnheader">
                  Evidence
                </TableHead>
                <TableHead
                  className="py-3 text-[11px] font-semibold uppercase tracking-widest text-muted-foreground"
                  role="columnheader"
                  aria-sort={sortField === "confidence" ? "descending" : "none"}
                >
                  Confidence
                </TableHead>
                <TableHead
                  className="py-3 text-[11px] font-semibold uppercase tracking-widest text-muted-foreground text-right"
                  role="columnheader"
                  aria-sort={sortField === "raf" ? "descending" : "none"}
                >
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <span className="cursor-help border-b border-dashed border-current">RAF Lift</span>
                    </TooltipTrigger>
                    <TooltipContent side="top">
                      Estimated RAF score increase if this HCC is documented this year
                    </TooltipContent>
                  </Tooltip>
                </TableHead>
                <TableHead className="py-3 text-[11px] font-semibold uppercase tracking-widest text-muted-foreground text-right" role="columnheader">
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <span className="cursor-help border-b border-dashed border-current">Revenue</span>
                    </TooltipTrigger>
                    <TooltipContent side="top">
                      Estimated $ = RAF lift × ${MA_PAYMENT_PER_RAF.toLocaleString()} (CMS V28 per-point rate, 2026)
                    </TooltipContent>
                  </Tooltip>
                </TableHead>
                <TableHead className="py-3 text-[11px] font-semibold uppercase tracking-widest text-muted-foreground text-right" role="columnheader">
                  Status
                </TableHead>
                <TableHead className="pr-6 py-3 text-[11px] font-semibold uppercase tracking-widest text-muted-foreground text-right" role="columnheader">
                  Actions
                </TableHead>
              </TableRow>
            </TableHeader>

            <TableBody onKeyDown={handleListKeyDown}>
              {/* Loading skeleton */}
              {isLoading && <SkeletonRows />}

              {/* Empty state */}
              {!isLoading && filteredSorted.length === 0 && (
                <TableRow className="hover:bg-transparent">
                  <TableCell colSpan={8} className="py-10 px-6">
                    <EmptyState
                      state={hasActiveFilters ? "filtered-out" : "no-data"}
                      icon={<SearchCheck size={22} aria-hidden="true" />}
                      title={hasActiveFilters ? undefined : "No open suspects"}
                      description={
                        hasActiveFilters
                          ? "Try adjusting your filters or clearing them to see all suspects."
                          : "No suspect conditions were found for the current measurement year."
                      }
                      cta={hasActiveFilters ? { label: "Clear filters", onClick: clearAllFilters } : undefined}
                    />
                  </TableCell>
                </TableRow>
              )}

              {/* Data rows */}
              {!isLoading && pagedSuspects.map((s, idx) => {
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
                  <React.Fragment key={s.id}>
                    <TableRow
                      ref={(el) => { rowRefs.current[idx] = el; }}
                      tabIndex={0}
                      role="row"
                      aria-selected={isSelected}
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
                      className={cn(
                        "cursor-pointer transition-colors duration-150 group motion-safe:animate-[rowEnter_0.32s_cubic-bezier(0.16,1,0.3,1)_both]",
                        isExpanded ? "bg-muted/30" : isSelected ? "bg-primary/5" : "bg-card hover:bg-muted/20",
                        isFocused && "outline outline-2 outline-primary outline-offset-[-2px]"
                      )}
                      style={{
                        borderLeft: `3px solid ${accent}`,
                        animationDelay: `${idx * 25}ms`,
                      }}
                    >
                      {/* Patient cell */}
                      <TableCell className="py-2.5 pl-6">
                        <div className="flex items-center gap-3 min-w-0">
                          {isOpen ? (
                            <input
                              type="checkbox"
                              checked={isSelected}
                              onChange={() => toggleSelect(s.id)}
                              onClick={(e) => e.stopPropagation()}
                              aria-label={`Select suspect ${s.id}`}
                              className="w-3.5 h-3.5 cursor-pointer accent-primary shrink-0"
                            />
                          ) : (
                            <div className="w-3.5 shrink-0" />
                          )}
                          <div
                            aria-hidden="true"
                            className="w-8 h-8 rounded-lg flex items-center justify-center text-[11px] font-bold text-white shrink-0 shadow-inner"
                            style={{
                              background: `linear-gradient(135deg, ${aColor}, ${aColor}CC)`,
                            }}
                          >
                            {initials}
                          </div>
                          <div className="min-w-0 flex flex-col gap-0.5">
                            <span className="text-[14px] font-semibold text-foreground truncate tracking-[-0.005em]">
                              {s.patient_name ?? `Patient ${s.patient_id}`}
                            </span>
                            <span className="text-[11px] text-muted-foreground tabular-nums truncate">
                              PID {s.patient_id} · MY {s.measurement_year ?? measurementYear}
                            </span>
                          </div>
                        </div>
                      </TableCell>

                      {/* Condition + rationale */}
                      <TableCell className="py-2.5 min-w-0 max-w-[320px]">
                        <div className="flex flex-col gap-1 min-w-0">
                          <span
                            className="text-[14px] font-semibold text-foreground truncate tracking-[-0.005em]"
                            title={conditionLabel}
                          >
                            {conditionLabel}
                          </span>
                          <div className="flex items-center gap-2 text-[11px] text-muted-foreground font-mono tracking-[0.01em] flex-wrap">
                            {s.suspect_hcc != null && (
                              <FeatureFlag flagKey="kg_evidence_panel" fallback={<span>HCC {s.suspect_hcc}</span>}>
                                <HccChipWithPopover hccCode={String(s.suspect_hcc)}>
                                  <span>HCC {s.suspect_hcc}</span>
                                </HccChipWithPopover>
                              </FeatureFlag>
                            )}
                            {s.suspect_hcc != null && s.suspect_icd10 && (
                              <span className="text-muted-foreground/50" aria-hidden="true">·</span>
                            )}
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
                            onClick={(e) => {
                              e.stopPropagation();
                              setExpandedRationale(prev => {
                                const next = new Set(prev);
                                next.has(s.id) ? next.delete(s.id) : next.add(s.id);
                                return next;
                              });
                            }}
                            className={cn(
                              "text-[12px] text-muted-foreground italic cursor-pointer",
                              !expandedRationale.has(s.id) && "line-clamp-1"
                            )}
                            title={expandedRationale.has(s.id) ? "Click to collapse" : "Click to expand"}
                          >
                            &ldquo;{rationale}&rdquo;
                          </div>
                        </div>
                      </TableCell>

                      {/* Evidence pill */}
                      <TableCell className="py-2.5">
                        {(() => {
                          const evidenceTooltips: Record<string, string> = {
                            medication: "Medication — a prescribed drug suggests this condition may be active",
                            lab: "Lab — a lab result or abnormal value flagged this condition",
                            imaging: "Imaging — a radiology report or scan referenced this diagnosis",
                            referral: "Referral — a specialist referral indicates this condition was suspected",
                            historical: "Historical — condition was documented in a prior measurement year",
                          };
                          const tipText = evidenceTooltips[s.evidence_type ?? ""] ?? "Clinical — evidence detected in chart notes";
                          return (
                            <Tooltip>
                              <TooltipTrigger asChild>
                                <span className="inline-flex items-center gap-1.5 h-[22px] px-2.5 rounded-full bg-muted border border-border text-muted-foreground text-[11px] font-semibold capitalize cursor-help whitespace-nowrap">
                                  {evidenceIcon(s.evidence_type, 11)}
                                  {evidenceLabelShort(s.evidence_type)}
                                </span>
                              </TooltipTrigger>
                              <TooltipContent side="top">{tipText}</TooltipContent>
                            </Tooltip>
                          );
                        })()}
                      </TableCell>

                      {/* Confidence bar */}
                      <TableCell className="py-2.5 min-w-[140px]">
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <div className="flex flex-col gap-1 min-w-0 cursor-help">
                              <div className="flex items-center gap-2">
                                <div
                                  className="flex-1 h-1.5 rounded overflow-hidden min-w-[40px]"
                                  style={{ backgroundColor: confSoftBg(conf) }}
                                >
                                  <div
                                    className="h-full rounded transition-[width_0.3s_ease]"
                                    style={{
                                      width: `${Math.max(4, conf * 100)}%`,
                                      backgroundColor: cConf,
                                    }}
                                  />
                                </div>
                                <span
                                  className="text-[11px] font-bold tabular-nums min-w-[56px] text-right whitespace-nowrap"
                                  style={{ color: cConf }}
                                >
                                  {conf >= 0.85 ? "Strong" : conf >= 0.65 ? "Moderate" : "Weak"}
                                </span>
                              </div>
                              {isCalibrated && (
                                <span
                                  className="text-[9px] font-semibold uppercase tracking-[0.04em] rounded-[3px] px-1 py-[1px] w-fit"
                                  style={{
                                    color: tokens.indigoText,
                                    backgroundColor: tokens.indigoBg,
                                  }}
                                >
                                  calibrated
                                </span>
                              )}
                            </div>
                          </TooltipTrigger>
                          <TooltipContent side="top" className="max-w-[260px]">
                            {conf >= 0.85
                              ? `Strong: ≥0.85 score · High confidence this HCC is undocumented (raw: ${(conf * 100).toFixed(0)}%)`
                              : conf >= 0.65
                              ? `Moderate: 0.65–0.85 score · Reasonable evidence, coder review recommended (raw: ${(conf * 100).toFixed(0)}%)`
                              : `Weak: <0.65 score · AI-uncertain — requires careful coder review (raw: ${(conf * 100).toFixed(0)}%)`}
                            {isCalibrated ? ` · Platt-calibrated from ${((s.confidence_score ?? 0) * 100).toFixed(0)}%` : ""}
                          </TooltipContent>
                        </Tooltip>
                      </TableCell>

                      {/* RAF lift */}
                      <TableCell className="py-2.5 text-right">
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <div className="inline-flex flex-col items-end gap-0.5 cursor-help">
                              <span
                                className="text-[14px] font-bold tabular-nums tracking-[-0.01em]"
                                style={{ color: C.brand }}
                              >
                                +{coef.toFixed(3)}
                              </span>
                              <span className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">
                                RAF
                              </span>
                            </div>
                          </TooltipTrigger>
                          <TooltipContent side="top">
                            Estimated RAF score increase of +{coef.toFixed(3)} if this HCC is documented this year
                          </TooltipContent>
                        </Tooltip>
                      </TableCell>

                      {/* Revenue — bold, teal for positive $ */}
                      <TableCell className="py-2.5 text-right">
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <span
                              className={cn(
                                "text-[13px] font-bold tabular-nums cursor-help",
                                revenue > 0 ? "text-teal-600 dark:text-teal-400" : "text-muted-foreground"
                              )}
                            >
                              {formatCurrency(revenue)}
                            </span>
                          </TooltipTrigger>
                          <TooltipContent side="top">
                            Estimated $ = RAF lift ({coef.toFixed(3)}) × ${MA_PAYMENT_PER_RAF.toLocaleString()} (CMS V28 per-point rate, 2026)
                          </TooltipContent>
                        </Tooltip>
                      </TableCell>

                      {/* Status pill */}
                      <TableCell className="py-2.5 text-right">
                        <span
                          className="inline-flex items-center gap-1.5 h-[22px] px-2.5 rounded-full border text-[11px] font-bold tracking-[0.02em]"
                          style={{
                            backgroundColor: pill.bg,
                            color: pill.fg,
                            borderColor: pill.border,
                            textDecoration: s.status === "dismissed" ? "line-through" : "none",
                          }}
                        >
                          <span
                            className="w-1.5 h-1.5 rounded-full"
                            style={{ backgroundColor: pill.fg }}
                            aria-hidden="true"
                          />
                          {pill.label}
                        </span>
                      </TableCell>

                      {/* Actions */}
                      <TableCell
                        className="py-2.5 pr-6 text-right"
                        onClick={(e) => e.stopPropagation()}
                      >
                        <div className="inline-flex items-center gap-1.5 justify-end">
                          {isOpen ? (
                            <>
                              <Tooltip>
                                <TooltipTrigger asChild>
                                  <button
                                    disabled={acceptMut.isPending}
                                    onClick={() => acceptMut.mutate(s.id)}
                                    aria-label="Accept suspect — push to OpenEMR (keyboard: A)"
                                    className={cn(
                                      "row-action-btn w-8 h-8 rounded-lg border flex items-center justify-center cursor-pointer transition-colors",
                                      "opacity-0 translate-y-0.5 group-hover:opacity-100 group-hover:translate-y-0 group-focus-within:opacity-100 group-focus-within:translate-y-0",
                                      "focus-visible:opacity-100 focus-visible:ring-2 focus-visible:ring-primary/50",
                                      "@media (max-width: 900px):opacity-100",
                                      "hover:bg-emerald-50 dark:hover:bg-emerald-950/30"
                                    )}
                                    style={{
                                      borderColor: C.low,
                                      color: C.low,
                                      transition: "opacity 0.15s ease, transform 0.15s ease, background-color 0.15s ease",
                                    }}
                                  >
                                    <Check size={15} strokeWidth={2.5} aria-hidden="true" />
                                  </button>
                                </TooltipTrigger>
                                <TooltipContent side="top">
                                  Accept &amp; write to OpenEMR · keyboard <kbd>A</kbd>
                                </TooltipContent>
                              </Tooltip>
                              <Tooltip>
                                <TooltipTrigger asChild>
                                  <button
                                    disabled={dismissMut.isPending}
                                    onClick={() => dismissMut.mutate(s.id)}
                                    aria-label="Dismiss suspect — mark not applicable (keyboard: D)"
                                    className={cn(
                                      "row-action-btn w-8 h-8 rounded-lg border flex items-center justify-center cursor-pointer transition-colors",
                                      "opacity-0 translate-y-0.5 group-hover:opacity-100 group-hover:translate-y-0 group-focus-within:opacity-100 group-focus-within:translate-y-0",
                                      "focus-visible:opacity-100 focus-visible:ring-2 focus-visible:ring-destructive/50",
                                      "hover:bg-red-50 dark:hover:bg-red-950/30"
                                    )}
                                    style={{
                                      borderColor: C.high,
                                      color: C.high,
                                      transition: "opacity 0.15s ease, transform 0.15s ease, background-color 0.15s ease",
                                    }}
                                  >
                                    <X size={15} strokeWidth={2.5} aria-hidden="true" />
                                  </button>
                                </TooltipTrigger>
                                <TooltipContent side="top">
                                  Dismiss — condition not applicable · keyboard <kbd>D</kbd>
                                </TooltipContent>
                              </Tooltip>
                            </>
                          ) : (
                            <span className="inline-flex items-center gap-1 text-[11px] text-muted-foreground" aria-label={`Status: ${s.status}`}>
                              {s.status === "accepted" && <CheckCircle2 size={13} color={C.low} aria-hidden="true" />}
                              {s.status === "dismissed" && <XCircle size={13} color={C.textSubtle} aria-hidden="true" />}
                              {s.status === "coded" && <CheckCircle2 size={13} color={C.brand} aria-hidden="true" />}
                            </span>
                          )}
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <span
                                aria-label={isExpanded ? "Collapse row" : "Expand row — open chart (keyboard: R)"}
                                className="inline-flex items-center"
                              >
                                <ChevronRight
                                  size={14}
                                  className="transition-transform duration-[180ms] ease"
                                  style={{
                                    color: isExpanded || hoveredId === s.id ? C.brand : tokens.slate300,
                                    transform: isExpanded ? "rotate(90deg)" : "rotate(0deg)",
                                  }}
                                />
                              </span>
                            </TooltipTrigger>
                            <TooltipContent side="top">
                              {isExpanded ? "Collapse detail" : "Expand — view evidence · keyboard R opens chart"}
                            </TooltipContent>
                          </Tooltip>
                        </div>
                      </TableCell>
                    </TableRow>

                    {/* Expanded detail drawer */}
                    {isExpanded && (
                      <TableRow className="hover:bg-transparent">
                        <TableCell colSpan={8} className="p-0">
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
                        </TableCell>
                      </TableRow>
                    )}
                  </React.Fragment>
                );
              })}
            </TableBody>
          </Table>
        </div>

        {/* ── Pagination ─────────────────────────────────────────── */}
        {!isLoading && filteredSorted.length > PAGE_SIZE && (
          <div className="flex items-center justify-between mt-4 px-1">
            <span className="text-[12px] text-muted-foreground tabular-nums">
              Showing{" "}
              <span className="font-semibold text-foreground">
                {(page * PAGE_SIZE + 1).toLocaleString()}–{Math.min((page + 1) * PAGE_SIZE, filteredSorted.length).toLocaleString()}
              </span>
              {" "}of{" "}
              <span className="font-semibold text-foreground">{filteredSorted.length.toLocaleString()}</span>
            </span>
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="icon"
                disabled={page === 0}
                onClick={() => setPage((p) => p - 1)}
                aria-label="Previous page"
                className="w-8 h-8"
              >
                <ChevronLeft size={15} aria-hidden="true" />
              </Button>
              <span className="text-[12px] font-semibold text-muted-foreground tabular-nums min-w-[72px] text-center">
                {page + 1} / {totalPages}
              </span>
              <Button
                variant="outline"
                size="icon"
                disabled={page >= totalPages - 1}
                onClick={() => setPage((p) => p + 1)}
                aria-label="Next page"
                className="w-8 h-8"
              >
                <ChevronRight size={15} aria-hidden="true" />
              </Button>
            </div>
          </div>
        )}

        {/* ── Bulk Action Bar ────────────────────────────────────── */}
        {selected.size > 0 && (
          <>
            <div className="h-20" aria-hidden="true" />
            <div
              className="fixed bottom-5 left-1/2 -translate-x-1/2 w-[min(720px,calc(100%-32px))] bg-foreground/95 backdrop-blur-md rounded-xl shadow-2xl px-5 py-3.5 flex items-center gap-3.5 z-50"
              role="toolbar"
              aria-label="Bulk actions"
            >
              <span className="text-[13px] font-semibold text-background flex items-center gap-2">
                <span
                  className="inline-flex items-center justify-center min-w-[24px] h-[22px] rounded-full text-[12px] font-bold px-2.5 tabular-nums text-white"
                  style={{ backgroundColor: C.brand }}
                >
                  {selected.size}
                </span>
                selected
              </span>

              <div className="w-px h-6 bg-background/15" aria-hidden="true" />

              <Tooltip>
                <TooltipTrigger asChild>
                  <button
                    disabled={bulkMut.isPending}
                    onClick={() => { setBulkAction("accept"); bulkMut.mutate({ action: "accept" }); }}
                    aria-label={`Accept all ${selected.size} selected suspects and write to OpenEMR`}
                    className="inline-flex items-center gap-1.5 h-9 px-4 rounded-lg text-[13px] font-bold text-white cursor-pointer disabled:cursor-not-allowed disabled:opacity-60 transition-opacity"
                    style={{ backgroundColor: C.low }}
                  >
                    <Check size={14} strokeWidth={2.5} aria-hidden="true" />
                    {bulkMut.isPending && bulkAction === "accept" ? "Accepting…" : "Accept all"}
                  </button>
                </TooltipTrigger>
                <TooltipContent side="top">
                  Accept all {selected.size} selected suspects — writes each to OpenEMR
                </TooltipContent>
              </Tooltip>

              <Tooltip>
                <TooltipTrigger asChild>
                  <button
                    disabled={bulkMut.isPending}
                    onClick={() => { setBulkAction("dismiss"); bulkMut.mutate({ action: "dismiss" }); }}
                    aria-label={`Dismiss all ${selected.size} selected suspects`}
                    className="inline-flex items-center gap-1.5 h-9 px-4 rounded-lg border border-background/20 bg-transparent text-background text-[13px] font-semibold cursor-pointer disabled:cursor-not-allowed disabled:opacity-60 transition-opacity"
                  >
                    <X size={14} strokeWidth={2.5} aria-hidden="true" />
                    {bulkMut.isPending && bulkAction === "dismiss" ? "Dismissing…" : "Dismiss all"}
                  </button>
                </TooltipTrigger>
                <TooltipContent side="top">
                  Mark all {selected.size} selected suspects as not applicable
                </TooltipContent>
              </Tooltip>

              <Tooltip>
                <TooltipTrigger asChild>
                  <button
                    onClick={() => setSelected(new Set())}
                    aria-label="Clear selection — no changes will be saved"
                    className="ml-auto h-9 px-3.5 rounded-lg bg-transparent text-background/70 text-[13px] font-semibold cursor-pointer hover:text-background transition-colors"
                  >
                    Clear
                  </button>
                </TooltipTrigger>
                <TooltipContent side="top">Deselect all — no changes will be saved</TooltipContent>
              </Tooltip>
            </div>
          </>
        )}

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

        {/* Row enter animation */}
        <style>{`
          @media (prefers-reduced-motion: no-preference) {
            @keyframes rowEnter {
              from { opacity: 0; transform: translateY(4px); }
              to   { opacity: 1; transform: translateY(0);   }
            }
          }
          @media (prefers-reduced-motion: reduce) {
            [class*='animate-[rowEnter'] { animation: none !important; }
          }
          /* Always-visible action buttons on touch/small screens */
          @media (max-width: 900px) {
            .row-action-btn { opacity: 1 !important; transform: none !important; }
          }
          /* WCAG 2.5.5 — minimum 44px touch targets on mobile */
          @media (max-width: 768px) {
            .row-action-btn { width: 44px !important; height: 44px !important; border-radius: 10px !important; }
          }
        `}</style>
      </div>
    </TooltipProvider>
  );
}
