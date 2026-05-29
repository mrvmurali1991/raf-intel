"use client";

/**
 * /worklist — "Today's priorities" page.
 *
 * Admin/manager/supervisor users additionally see:
 *  - Provider Workload heatmap (collapsible) above summary tiles
 *  - Provider filter pills to scope the card grid to one provider
 *
 * Bulk-select: always-visible 16px checkbox top-left each card.
 *   Shift+Click range · Cmd/Ctrl+A select all visible · Esc clear
 * Bulk actions bar (sticky top when any selection):
 *   Send to Attestation · Schedule AWV · Export CSV
 *
 * Tooltips: shadcn Tooltip (base-ui) with 200 ms delay on every interactive
 * element, pill, and filter — WCAG 2.1 AA focus-accessible.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  CalendarClock,
  CheckSquare,
  ChevronDown,
  ChevronRight,
  ChevronUp,
  Download,
  FileText,
  Activity,
  Loader2,
  Stethoscope,
  Users,
  X,
} from "lucide-react";
import { useAuth } from "@/contexts/auth-context";
import { PageHeader } from "@/components/ui/page-header";
import { EmptyState } from "@/components/ui/empty-state";
import { HelpButton } from "@/components/HelpPanel";
import { tokens } from "@/styles/tokens";
import DataQualityBanner from "@/components/DataQualityBanner";
import api from "@/lib/api";
import {
  Tooltip,
  TooltipTrigger,
  TooltipContent,
  TooltipProvider,
} from "@/components/ui/tooltip";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface WorklistGap {
  hcc_code: string;
  icd10_codes?: string[];
  prior_year?: number;
  revenue_impact?: number;
}

interface WorklistSuspect {
  hcc_code: string;
  source?: string;
  confidence?: number;
}

type AwvStatus = "overdue" | "due_soon" | "current" | "future" | "unknown";

interface WorklistItem {
  patient_id: number;
  patient_name: string;
  dob?: string | null;
  last_visit_date?: string | null;
  open_recapture_gaps: WorklistGap[];
  suspect_conditions: WorklistSuspect[];
  estimated_raf_impact: number;
  estimated_revenue_at_risk: number;
  priority_score: number;
  awv_status?: AwvStatus;
  awv_due_date?: string | null;
  awv_last_date?: string | null;
}

function awvPill(status?: AwvStatus): { bg: string; color: string; label: string } {
  switch (status) {
    case "overdue":
      return { bg: tokens.dangerSoft, color: tokens.danger, label: "Overdue" };
    case "due_soon":
      return { bg: tokens.warningSoft, color: tokens.warningStrong, label: "Due soon" };
    case "current":
      return { bg: tokens.slate100, color: tokens.slate700, label: "Current" };
    case "future":
      return { bg: tokens.slate100, color: tokens.slate500, label: "Future" };
    default:
      return { bg: tokens.slate100, color: tokens.slate500, label: "Unknown" };
  }
}

function awvDaysLabel(item: WorklistItem): string | null {
  if (!item.awv_due_date) return null;
  const due = new Date(item.awv_due_date);
  const now = new Date();
  const days = Math.round((due.getTime() - now.getTime()) / (1000 * 60 * 60 * 24));
  if (item.awv_status === "overdue") return `AWV overdue by ${Math.abs(days)}d`;
  if (item.awv_status === "due_soon") return `AWV due in ${days}d`;
  if (item.awv_status === "current") return "AWV current";
  return null;
}

function awvTooltip(item: WorklistItem): string {
  const dueLabel = item.awv_due_date
    ? ` (due ${new Date(item.awv_due_date).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })})`
    : "";
  switch (item.awv_status) {
    case "overdue":
      return `Annual Wellness Visit is past due${dueLabel}. Schedule immediately to avoid missing CMS G0439 reimbursement for this payment year.`;
    case "due_soon":
      return `Annual Wellness Visit is coming up${dueLabel}. Schedule before the payment year closes to capture the CMS G0439 reimbursement.`;
    case "current":
      return `Annual Wellness Visit has been completed this year${dueLabel}. No further action needed for this measure.`;
    case "future":
      return `Annual Wellness Visit is not yet due${dueLabel}. Plan ahead to ensure it is completed within the measurement year.`;
    default:
      return "AWV status is unknown. Review the patient chart to verify Annual Wellness Visit history.";
  }
}

interface WorklistResponse {
  provider_id: number;
  measurement_year: number;
  total: number;
  items: WorklistItem[];
}

interface ProviderWorkloadRow {
  provider_id: number;
  provider_name: string;
  open_gaps: number;
  awv_due: number;
  suspect_count: number;
  total_workload: number;
  capacity_pct: number;
}

interface ProviderWorkloadResponse {
  providers: ProviderWorkloadRow[];
  total_open_gaps: number;
  target_capacity: number;
  measurement_year: number;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fmtCurrency(n: number): string {
  if (Math.abs(n) >= 1000) return `$${(n / 1000).toFixed(1)}K`;
  return `$${Math.round(n).toLocaleString()}`;
}

function priorityBand(score: number): { label: string; color: string; bg: string } {
  if (score >= 70) return { label: "High", color: tokens.riskHigh, bg: tokens.riskHighSoft };
  if (score >= 40) return { label: "Medium", color: tokens.warningStrong, bg: tokens.warningSoft };
  return { label: "Low", color: tokens.success, bg: tokens.successSoft };
}

function capacityColor(pct: number): string {
  if (pct >= 90) return tokens.riskHigh;
  if (pct >= 70) return tokens.warningStrong;
  return tokens.success;
}

const ELEVATED_ROLES = new Set(["admin", "super_admin", "manager", "supervisor"]);

// ---------------------------------------------------------------------------
// WT — thin wrapper: TooltipProvider + Tooltip + Trigger + Content
// ---------------------------------------------------------------------------

function WT({
  text,
  children,
  side = "top",
  delay = 200,
  asChild = true,
}: {
  text: string;
  children: React.ReactElement;
  side?: "top" | "bottom" | "left" | "right";
  delay?: number;
  asChild?: boolean;
}) {
  return (
    <TooltipProvider delay={delay}>
      <Tooltip>
        <TooltipTrigger asChild={asChild}>{children}</TooltipTrigger>
        <TooltipContent side={side} sideOffset={6} className="max-w-[260px] text-center leading-snug">
          {text}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

// ---------------------------------------------------------------------------
// Toast
// ---------------------------------------------------------------------------

function Toast({
  message,
  linkHref,
  linkLabel,
  onDismiss,
}: {
  message: string;
  linkHref?: string;
  linkLabel?: string;
  onDismiss: () => void;
}) {
  useEffect(() => {
    const t = setTimeout(onDismiss, 6000);
    return () => clearTimeout(t);
  }, [onDismiss]);

  return (
    <div
      role="status"
      aria-live="polite"
      className="fixed bottom-6 left-1/2 -translate-x-1/2 z-[9999] flex items-center gap-3 rounded-[10px] bg-slate-900 text-white px-5 py-3 text-[13px] font-medium shadow-2xl max-w-[90vw] whitespace-nowrap"
    >
      <CheckSquare size={16} className="shrink-0 text-emerald-400" />
      <span>{message}</span>
      {linkHref && linkLabel && (
        <Link href={linkHref} className="text-cyan-300 font-bold underline">
          {linkLabel}
        </Link>
      )}
      <button
        type="button"
        onClick={onDismiss}
        aria-label="Dismiss notification"
        className="flex items-center text-slate-400 cursor-pointer bg-transparent border-none p-0 ml-1"
      >
        <X size={14} />
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// WorklistBulkActionsBar
// ---------------------------------------------------------------------------

const BRAND = "#0F766E";

function WorklistBulkActionsBar({
  selectedCount,
  totalCount,
  onClear,
  onSelectAll,
  onAttest,
  onScheduleAWV,
  onExportCSV,
  attesting,
  exporting,
}: {
  selectedCount: number;
  totalCount: number;
  onClear: () => void;
  onSelectAll: () => void;
  onAttest: () => void;
  onScheduleAWV: () => void;
  onExportCSV: () => void;
  attesting: boolean;
  exporting: boolean;
}) {
  if (selectedCount === 0) return null;
  return (
    <div
      role="region"
      aria-label="Bulk actions"
      className="sticky top-0 z-40 flex items-center flex-wrap gap-2.5 px-4 py-2.5 border-b-2 border-teal-600 bg-teal-600/[0.08] backdrop-blur-sm"
    >
      <span className="sr-only" aria-live="polite" aria-atomic="true">
        {selectedCount} patient{selectedCount === 1 ? "" : "s"} selected
      </span>

      {/* Selected count badge */}
      <span
        className="inline-flex items-center rounded-full px-3 py-0.5 text-xs font-bold text-white"
        style={{ background: BRAND }}
      >
        {selectedCount} selected
      </span>

      <button
        type="button"
        onClick={onClear}
        aria-label="Clear selection"
        className="px-2.5 py-1 rounded-md border border-border bg-card text-slate-700 text-xs cursor-pointer"
      >
        Clear
      </button>

      {selectedCount < totalCount && (
        <button
          type="button"
          onClick={onSelectAll}
          className="px-2.5 py-1 rounded-md border border-border bg-card text-slate-700 text-xs cursor-pointer"
        >
          Select all {totalCount}
        </button>
      )}

      <div className="w-px h-5 bg-border shrink-0" />

      {/* Send to Attestation */}
      <WT
        text="Submit selected patients for HCC gap attestation. Creates a structured attestation record for each patient and sends to your coding queue."
        side="bottom"
      >
        <button
          type="button"
          onClick={onAttest}
          disabled={attesting}
          aria-label={`Send ${selectedCount} patients to attestation`}
          data-testid="bulk-attest-btn"
          className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-md border-none text-white text-xs font-semibold disabled:opacity-60 disabled:cursor-not-allowed"
          style={{ background: attesting ? tokens.slate300 : BRAND, cursor: attesting ? "not-allowed" : "pointer" }}
        >
          {attesting ? <Loader2 size={13} className="animate-spin" /> : <FileText size={13} />}
          {attesting ? "Creating…" : "Send to Attestation"}
        </button>
      </WT>

      {/* Schedule AWV */}
      <WT
        text="Open the calendar to batch-schedule Annual Wellness Visits for all selected patients before the payment year closes."
        side="bottom"
      >
        <button
          type="button"
          onClick={onScheduleAWV}
          aria-label={`Schedule AWV for ${selectedCount} patients`}
          data-testid="bulk-schedule-awv-btn"
          className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-md bg-card text-xs font-semibold cursor-pointer"
          style={{ border: `1px solid ${BRAND}`, color: BRAND }}
        >
          <CalendarClock size={13} />
          Schedule AWV
        </button>
      </WT>

      {/* Export CSV */}
      <WT
        text="Download a CSV of selected patients with RAF scores, open gaps, revenue at risk, and AWV status for offline review or reporting."
        side="bottom"
      >
        <button
          type="button"
          onClick={onExportCSV}
          disabled={exporting}
          aria-label={`Export ${selectedCount} patients to CSV`}
          data-testid="export-csv-worklist"
          className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-md border border-border bg-card text-slate-700 text-xs font-semibold disabled:opacity-60 disabled:cursor-not-allowed"
          style={{ cursor: exporting ? "not-allowed" : "pointer" }}
        >
          {exporting ? <Loader2 size={13} className="animate-spin" /> : <Download size={13} />}
          {exporting ? "Exporting…" : "Export CSV"}
        </button>
      </WT>

      <span aria-hidden className="ml-auto text-[11px] text-slate-500 italic">
        Shift+Click range · Cmd/Ctrl+A all · Esc clear
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// AWV batch modal
// ---------------------------------------------------------------------------

function AWVBatchModal({ selectedCount, onClose }: { selectedCount: number; onClose: () => void }) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Schedule AWV for selected patients"
      tabIndex={-1}
      className="fixed inset-0 z-[9990] flex items-center justify-center p-4 bg-black/60"
      onClick={onClose}
    >
      <div
        className="bg-card rounded-xl shadow-2xl w-full max-w-[480px] p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-3">
          <h3 className="m-0 text-base font-bold text-foreground">
            Schedule AWV — {selectedCount} patient{selectedCount === 1 ? "" : "s"}
          </h3>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="flex items-center bg-transparent border-none cursor-pointer text-muted-foreground"
          >
            <X size={18} />
          </button>
        </div>
        <p className="text-[13px] text-muted-foreground mb-4">
          Batch AWV scheduling is managed in the Calendar module. Open the calendar to assign
          appointment slots for all {selectedCount} selected patient{selectedCount === 1 ? "" : "s"}.
        </p>
        <div className="flex gap-2 justify-end">
          <button
            type="button"
            onClick={onClose}
            className="px-3.5 py-1.5 rounded-md border border-border bg-card text-muted-foreground text-[13px] cursor-pointer"
          >
            Cancel
          </button>
          <Link
            href="/appointments"
            className="px-4 py-1.5 rounded-md text-[13px] font-semibold text-white no-underline"
            style={{ background: BRAND }}
          >
            Open Calendar
          </Link>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// WorklistPage
// ---------------------------------------------------------------------------

export default function WorklistPage() {
  const { user, isLoading: authLoading } = useAuth();
  const measurementYear = new Date().getFullYear();
  // Use the linked clinical provider_id (not the user table id) so the
  // ownership check on /api/worklist/provider/:id matches.
  const userAny = user as (typeof user & { provider_id?: number | null }) | null;
  const providerId = userAny?.provider_id
    ? Number(userAny.provider_id)
    : userAny?.id
      ? Number(userAny.id)
      : null;
  const isElevated = Boolean(user?.role && ELEVATED_ROLES.has(user.role));

  const [heatmapOpen, setHeatmapOpen] = useState(true);
  const [filterProviderId, setFilterProviderId] = useState<number | null>(null);

  // Bulk-select state
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const lastClickedIndexRef = useRef<number | null>(null);
  const [attesting, setAttesting] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [awvBatchOpen, setAwvBatchOpen] = useState(false);
  const [bulkToast, setBulkToast] = useState<{ message: string; linkHref?: string; linkLabel?: string } | null>(null);

  const queryProviderId = isElevated ? (filterProviderId ?? providerId) : providerId;

  const { data, isLoading, isError, error, refetch } = useQuery<WorklistResponse>({
    queryKey: ["provider-worklist", queryProviderId, measurementYear],
    queryFn: async () => {
      const { data } = await api.get<WorklistResponse>(
        `/api/worklist/provider/${queryProviderId}`,
        { params: { measurement_year: measurementYear } },
      );
      return data;
    },
    enabled: queryProviderId != null,
    staleTime: 60_000,
  });

  const { data: workloadData, isLoading: workloadLoading } =
    useQuery<ProviderWorkloadResponse>({
      queryKey: ["provider-workload", measurementYear],
      queryFn: async () => {
        const { data } = await api.get<ProviderWorkloadResponse>(
          "/api/worklist/provider-workload",
          { params: { measurement_year: measurementYear } },
        );
        return data;
      },
      enabled: isElevated,
      staleTime: 120_000,
    });

  const visibleItems = useMemo(() => data?.items ?? [], [data]);

  // Keyboard shortcuts: Cmd/Ctrl+A selects all visible, Esc clears
  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (visibleItems.length === 0) return;
      const tag = (document.activeElement as HTMLElement)?.tagName?.toLowerCase();
      if ((e.metaKey || e.ctrlKey) && e.key === "a") {
        if (tag === "input" || tag === "textarea") return;
        e.preventDefault();
        setSelectedIds(new Set(visibleItems.map((i) => i.patient_id)));
      }
      if (e.key === "Escape") {
        setSelectedIds(new Set());
        lastClickedIndexRef.current = null;
      }
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [visibleItems]);

  const handleCardSelect = useCallback(
    (patientId: number, index: number, shiftKey: boolean) => {
      setSelectedIds((prev) => {
        const next = new Set(prev);
        if (shiftKey && lastClickedIndexRef.current != null) {
          const lo = Math.min(index, lastClickedIndexRef.current);
          const hi = Math.max(index, lastClickedIndexRef.current);
          for (let i = lo; i <= hi; i++) next.add(visibleItems[i].patient_id);
        } else {
          if (next.has(patientId)) next.delete(patientId);
          else next.add(patientId);
        }
        lastClickedIndexRef.current = index;
        return next;
      });
    },
    [visibleItems],
  );

  const handleBulkAttest = useCallback(async () => {
    if (selectedIds.size === 0) return;
    setAttesting(true);
    try {
      const { data: result } = await api.post<{ created: number }>("/api/v1/worklist/bulk-attest", {
        patient_ids: Array.from(selectedIds),
      });
      setBulkToast({
        message: `${result.created} attestation${result.created === 1 ? "" : "s"} created`,
        linkHref: "/attestations",
        linkLabel: "View in Attestations",
      });
      setSelectedIds(new Set());
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setBulkToast({ message: `Error: ${detail ?? "Attestation creation failed"}` });
    } finally {
      setAttesting(false);
    }
  }, [selectedIds]);

  const handleBulkExportCSV = useCallback(async () => {
    if (selectedIds.size === 0) return;
    setExporting(true);
    try {
      const resp = await api.post(
        "/api/v1/worklist/bulk-export",
        { patient_ids: Array.from(selectedIds) },
        { responseType: "blob" },
      );
      const url = URL.createObjectURL(new Blob([resp.data], { type: "text/csv" }));
      const a = document.createElement("a");
      a.href = url;
      a.download = `raf-worklist-export-${new Date().toISOString().slice(0, 10)}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      setBulkToast({ message: "CSV export failed. Please try again." });
    } finally {
      setExporting(false);
    }
  }, [selectedIds]);

  const summary = useMemo(() => {
    if (!data?.items) return { patients: 0, gaps: 0, revenue: 0, awvDue: 0 };
    return {
      patients: data.items.length,
      gaps: data.items.reduce((s, p) => s + (p.open_recapture_gaps?.length ?? 0), 0),
      revenue: data.items.reduce((s, p) => s + (p.estimated_revenue_at_risk ?? 0), 0),
      awvDue: data.items.filter((i) => i.awv_status === "overdue" || i.awv_status === "due_soon").length,
    };
  }, [data]);

  const providerPills = useMemo(() => {
    if (!workloadData?.providers) return [];
    return workloadData.providers.map((p) => ({
      id: p.provider_id,
      name: p.provider_name,
      taskCount: p.total_workload,
    }));
  }, [workloadData]);

  // ---- Guards ----

  if (authLoading || (queryProviderId != null && isLoading)) {
    return (
      <div className="p-6">
        <PageHeader
          title="Today's worklist"
          subtitle="Loading prioritized patients…"
          icon={<Stethoscope size={20} />}
        />
        <div className="grid gap-4 mt-4" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))" }}>
          {[1, 2, 3].map((i) => (
            <div key={i} className="premium-card shimmer h-[140px] rounded-lg" />
          ))}
        </div>
      </div>
    );
  }

  if (queryProviderId == null) {
    return (
      <div className="p-6">
        <PageHeader title="Today's worklist" icon={<Stethoscope size={20} />} />
        <div className="mt-4 p-4 rounded-lg border text-sm" style={{ background: tokens.warningSoft, borderColor: tokens.warningBorder, color: tokens.warningText }}>
          Sign in to view your worklist.
        </div>
      </div>
    );
  }

  if (isError || !data) {
    return (
      <div className="p-6">
        <PageHeader title="Today's worklist" icon={<Stethoscope size={20} />} />
        <div
          role="alert"
          className="mt-4 p-4 rounded-lg border flex items-center gap-2.5 text-sm"
          style={{ background: tokens.dangerSoft, borderColor: tokens.dangerBorder, color: tokens.danger }}
        >
          <AlertTriangle size={18} className="shrink-0" />
          <span className="flex-1">
            Couldn't load your worklist{error instanceof Error ? `: ${error.message}` : ""}
          </span>
          <button
            type="button"
            onClick={() => refetch()}
            aria-label="Retry loading worklist"
            className="px-3 py-1.5 rounded-lg border text-[13px] font-semibold cursor-pointer bg-card"
            style={{ borderColor: tokens.dangerBorder, color: tokens.danger }}
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  // Empty state — no items and not elevated (elevated users may still use
  // provider filter, so they see the full layout with an inline empty notice)
  if (data.items.length === 0 && !isElevated) {
    return (
      <div className="p-6">
        <PageHeader
          title="Today's worklist"
          subtitle={`Measurement year ${measurementYear}`}
          icon={<Stethoscope size={20} />}
        />
        <div className="mt-6">
          <EmptyState
            state="complete"
            icon={<Stethoscope size={24} />}
            title="No items in your worklist today"
            description="All open gaps and AWV actions are up to date. Check back as new gaps are identified."
            cta={{ label: "View full panel", href: "/patients" }}
          />
          <div className="flex gap-3 justify-center mt-4">
            <Link
              href="/recapture"
              className="px-4 py-2 rounded-lg text-[13px] font-semibold text-white no-underline"
              style={{ background: tokens.successDark }}
            >
              Open recapture report
            </Link>
          </div>
        </div>
      </div>
    );
  }

  return (
    <>
      {/* Sticky bulk-actions bar — only appears when cards are selected */}
      <WorklistBulkActionsBar
        selectedCount={selectedIds.size}
        totalCount={visibleItems.length}
        onClear={() => { setSelectedIds(new Set()); lastClickedIndexRef.current = null; }}
        onSelectAll={() => setSelectedIds(new Set(visibleItems.map((i) => i.patient_id)))}
        onAttest={handleBulkAttest}
        onScheduleAWV={() => setAwvBatchOpen(true)}
        onExportCSV={handleBulkExportCSV}
        attesting={attesting}
        exporting={exporting}
      />

      <div className="p-6 max-w-[1280px] mx-auto">
        <DataQualityBanner />

        <PageHeader
          title="Today's worklist"
          subtitle={`${summary.patients} patient${summary.patients === 1 ? "" : "s"} prioritized for ${measurementYear}`}
          icon={<Stethoscope size={20} />}
          actions={<HelpButton />}
        />

        {/* Provider Workload Heatmap — elevated roles only */}
        {isElevated && (
          <section
            className="mt-5 rounded-lg border border-border bg-card overflow-hidden"
            aria-label="Provider workload heatmap"
          >
            <div className={`flex items-center justify-between px-4 py-3 bg-muted${heatmapOpen ? " border-b border-border" : ""}`}>
              <div className="flex items-center gap-2">
                <Users size={16} className="text-muted-foreground" />
                <span className="font-bold text-sm text-foreground">Provider Workload</span>
                {workloadData && (
                  <span className="text-xs text-muted-foreground font-normal">
                    — Total open: {workloadData.total_open_gaps} gaps
                  </span>
                )}
              </div>
              <button
                type="button"
                aria-expanded={heatmapOpen}
                aria-label={heatmapOpen ? "Collapse workload heatmap" : "Expand workload heatmap"}
                onClick={() => setHeatmapOpen((v) => !v)}
                className="flex items-center gap-1 px-2.5 py-1 rounded-md border border-border bg-card text-muted-foreground text-xs font-semibold cursor-pointer"
              >
                {heatmapOpen ? <><ChevronUp size={13} /> Collapse</> : <><ChevronDown size={13} /> Expand</>}
              </button>
            </div>

            {heatmapOpen && (
              <div className="px-4 pt-3 pb-4">
                {workloadLoading && (
                  <div className="flex flex-col gap-2">
                    {[1, 2, 3].map((i) => (
                      <div key={i} className="shimmer h-9 rounded-md" />
                    ))}
                  </div>
                )}
                {!workloadLoading && (!workloadData || workloadData.providers.length === 0) && (
                  <p className="m-0 text-[13px] text-muted-foreground">
                    No provider data available for {measurementYear}.
                  </p>
                )}
                {!workloadLoading && workloadData && workloadData.providers.length > 0 && (
                  <div className="flex flex-col gap-1.5">
                    {workloadData.providers.map((prov) => (
                      <HeatmapRow
                        key={prov.provider_id}
                        prov={prov}
                        isSelected={filterProviderId === prov.provider_id}
                        onClick={() => setFilterProviderId((c) => c === prov.provider_id ? null : prov.provider_id)}
                        targetCapacity={workloadData.target_capacity}
                      />
                    ))}
                  </div>
                )}
              </div>
            )}
          </section>
        )}

        {/* Summary tiles — 4 KPI cards */}
        <div
          className={`grid gap-3 mt-4 ${isElevated ? "mb-2" : "mb-6"}`}
          style={{ gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))" }}
        >
          <WT
            text={`${summary.patients} patient${summary.patients === 1 ? "" : "s"} in your panel have open HCC gaps or AWV actions due this measurement year.`}
            side="bottom"
          >
            <div data-testid="tile-patients-to-see">
              <SummaryTile label="Patients to see" value={summary.patients} icon={<Stethoscope size={18} />} color={tokens.primary} />
            </div>
          </WT>
          <WT
            text={`${summary.gaps} total open HCC recapture gap${summary.gaps === 1 ? "" : "s"} across all prioritized patients. Each gap represents a condition that was coded in a prior year but not yet confirmed this year.`}
            side="bottom"
          >
            <div data-testid="tile-open-gaps">
              <SummaryTile label="Open gaps" value={summary.gaps === 0 ? "0 — all clear" : summary.gaps} icon={<FileText size={18} />} color={tokens.riskHigh} />
            </div>
          </WT>
          <WT
            text="Estimated incremental revenue at risk if open HCC gaps are not recaptured this measurement year. Calculated at the MA rate of ~$9,000 per RAF point."
            side="bottom"
          >
            <div data-testid="tile-revenue-at-risk">
              <SummaryTile label="Revenue at risk" value={summary.revenue === 0 ? "—" : fmtCurrency(summary.revenue)} icon={<Activity size={18} />} color={tokens.warningStrong} />
            </div>
          </WT>
          <WT
            text={`${summary.awvDue} patient${summary.awvDue === 1 ? "" : "s"} have an Annual Wellness Visit that is overdue or due soon. Completing AWVs enables G0439 billing and supports comprehensive risk documentation.`}
            side="bottom"
          >
            <div data-testid="tile-awv-due">
              <SummaryTile
                label="AWV due/overdue"
                value={summary.awvDue === 0 ? "0 — all current" : summary.awvDue}
                icon={<CalendarClock size={18} />}
                color={tokens.danger}
              />
            </div>
          </WT>
        </div>

        {/* Provider filter pills — elevated only */}
        {isElevated && providerPills.length > 0 && (
          <div
            role="group"
            aria-label="Filter by provider"
            className="flex flex-wrap gap-1.5 mt-3 mb-5"
          >
            <WT text="Show worklist across all providers in your organization.">
              <span>
                <ProviderPill label="All providers" count={null} active={filterProviderId === null} onClick={() => setFilterProviderId(null)} />
              </span>
            </WT>
            {providerPills.map((p) => (
              <WT
                key={p.id}
                text={`Filter worklist to show only ${p.name}'s ${p.taskCount} open task${p.taskCount === 1 ? "" : "s"}.`}
              >
                <span>
                  <ProviderPill
                    label={p.name}
                    count={p.taskCount}
                    active={filterProviderId === p.id}
                    onClick={() => setFilterProviderId((c) => c === p.id ? null : p.id)}
                  />
                </span>
              </WT>
            ))}
          </div>
        )}

        {/* Patient cards list — or inline empty state for elevated users with no filtered results */}
        {visibleItems.length === 0 ? (
          <div className="mt-2">
            <EmptyState
              state="filtered-out"
              icon={<Stethoscope size={24} />}
              title="No items in your worklist today"
              description="No patients match the selected provider filter."
            />
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            {visibleItems.map((item, index) => (
              <PatientCard
                key={item.patient_id}
                item={item}
                isSelected={selectedIds.has(item.patient_id)}
                onSelect={(shiftKey) => handleCardSelect(item.patient_id, index, shiftKey)}
              />
            ))}
          </div>
        )}
      </div>

      {/* AWV batch modal */}
      {awvBatchOpen && (
        <AWVBatchModal selectedCount={selectedIds.size} onClose={() => setAwvBatchOpen(false)} />
      )}

      {/* Success/error toast */}
      {bulkToast && (
        <Toast
          message={bulkToast.message}
          linkHref={bulkToast.linkHref}
          linkLabel={bulkToast.linkLabel}
          onDismiss={() => setBulkToast(null)}
        />
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// HeatmapRow
// ---------------------------------------------------------------------------

function HeatmapRow({
  prov,
  isSelected,
  onClick,
  targetCapacity = 30,
}: {
  prov: ProviderWorkloadRow;
  isSelected: boolean;
  onClick: () => void;
  targetCapacity?: number;
}) {
  const barColor = capacityColor(prov.capacity_pct);
  const barPct = Math.max(prov.capacity_pct, 2);
  return (
    <WT
      text={`Capacity = ${prov.open_gaps} open gaps out of a target of ${targetCapacity}. Click to filter the worklist to ${prov.provider_name}'s patients only.`}
      side="right"
    >
      <button
        type="button"
        onClick={onClick}
        aria-pressed={isSelected}
        aria-label={`${prov.provider_name}: ${prov.capacity_pct}% capacity. Click to filter.`}
        data-testid={`heatmap-row-${prov.provider_id}`}
        className="grid items-center gap-3 px-2 py-1.5 rounded-lg cursor-pointer text-left w-full transition-colors"
        style={{
          gridTemplateColumns: "180px 1fr 120px",
          border: isSelected ? `1.5px solid ${barColor}` : `1px solid ${tokens.slate100}`,
          background: isSelected ? `${barColor}0D` : "transparent",
        }}
      >
        <span className="text-[13px] font-semibold text-foreground overflow-hidden text-ellipsis whitespace-nowrap">
          {prov.provider_name}
        </span>
        <div className="h-2.5 rounded-full bg-slate-100 overflow-hidden">
          <div
            className="h-full rounded-full transition-[width] duration-300"
            style={{ width: `${barPct}%`, background: barColor }}
          />
        </div>
        <span className="text-xs text-muted-foreground whitespace-nowrap text-right">
          <span className="font-bold" style={{ color: barColor }}>{prov.capacity_pct}%</span>
          {" · "}{prov.total_workload} tasks
        </span>
      </button>
    </WT>
  );
}

// ---------------------------------------------------------------------------
// ProviderPill
// ---------------------------------------------------------------------------

function ProviderPill({ label, count, active, onClick }: { label: string; count: number | null; active: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className="inline-flex items-center gap-1 px-3 py-1 rounded-full text-xs font-semibold cursor-pointer transition-all duration-100 whitespace-nowrap border"
      style={{
        borderColor: active ? tokens.primary : tokens.slate200,
        background: active ? tokens.primarySoft : "hsl(var(--card))",
        color: active ? tokens.primary : tokens.slate600,
      }}
    >
      {label}
      {count !== null && (
        <span
          className="px-1.5 py-px rounded-full text-[11px]"
          style={{
            background: active ? tokens.primary : tokens.slate200,
            color: active ? tokens.white : tokens.slate600,
          }}
        >
          {count}
        </span>
      )}
    </button>
  );
}

// ---------------------------------------------------------------------------
// SummaryTile
// ---------------------------------------------------------------------------

function SummaryTile({ label, value, icon, color }: { label: string; value: string | number; icon: React.ReactNode; color: string }) {
  return (
    <div className="flex items-center gap-3 px-4 py-3.5 rounded-lg bg-card border border-border cursor-default">
      <div
        className="w-9 h-9 rounded-lg flex items-center justify-center shrink-0"
        style={{ background: `${color}1A`, color }}
      >
        {icon}
      </div>
      <div className="min-w-0">
        <div className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wide">{label}</div>
        <div className="tabular-nums text-[22px] font-bold text-foreground leading-tight">{value}</div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// PatientCard — single compact row (desktop), always-visible 16px checkbox
// ---------------------------------------------------------------------------

/** Derive age in years from an ISO date string (YYYY-MM-DD or similar). */
function ageFromDob(dob: string | null | undefined): number | null {
  if (!dob) return null;
  const birth = new Date(dob);
  if (isNaN(birth.getTime())) return null;
  const today = new Date();
  let age = today.getFullYear() - birth.getFullYear();
  const m = today.getMonth() - birth.getMonth();
  if (m < 0 || (m === 0 && today.getDate() < birth.getDate())) age--;
  return age >= 0 ? age : null;
}

/** Return a colour for a RAF impact value (0–3+ typical range). */
function rafColor(raf: number): { color: string; bg: string } {
  if (raf >= 1.5) return { color: tokens.riskHigh, bg: tokens.riskHighSoft };
  if (raf >= 0.5) return { color: tokens.warningStrong, bg: tokens.warningSoft };
  return { color: tokens.slate600, bg: tokens.slate100 };
}

function PatientCard({
  item,
  isSelected,
  onSelect,
}: {
  item: WorklistItem;
  isSelected: boolean;
  onSelect: (shiftKey: boolean) => void;
}) {
  const age = ageFromDob(item.dob);
  const ageSex = age !== null ? `${age}y` : "Age N/A";

  const suspectCount = item.suspect_conditions?.length ?? 0;
  const topGap = item.open_recapture_gaps?.[0];
  const raf = item.estimated_raf_impact ?? 0;
  const rafStyle = rafColor(raf);

  // Initials — up to 2 letters
  const initials = item.patient_name
    .split(" ")
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0].toUpperCase())
    .join("");

  // Visit time: use awv_due_date only when status is today-relevant
  const visitLabel = (() => {
    if (!item.awv_due_date) return null;
    const due = new Date(item.awv_due_date);
    const today = new Date();
    const sameDay =
      due.getFullYear() === today.getFullYear() &&
      due.getMonth() === today.getMonth() &&
      due.getDate() === today.getDate();
    if (!sameDay) return null;
    return due.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
  })();

  const handleCheckboxClick = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    onSelect(e.shiftKey);
  };

  const handleCardClick = (e: React.MouseEvent) => {
    if (isSelected || e.shiftKey) {
      e.preventDefault();
      onSelect(e.shiftKey);
    }
  };

  return (
    <div className="relative">
      {/* 16px checkbox — always visible, positioned top-left, vertically centered */}
      <WT
        text="Select this patient for a bulk action (Send to Attestation, Schedule AWV, or Export CSV). Shift+Click to select a range."
        side="right"
        delay={200}
      >
        <button
          type="button"
          role="checkbox"
          aria-checked={isSelected}
          aria-label={`Select ${item.patient_name}`}
          onClick={handleCheckboxClick}
          data-testid={`card-checkbox-${item.patient_id}`}
          className="absolute top-1/2 -translate-y-1/2 left-3 z-10 w-4 h-4 rounded flex items-center justify-center p-0 transition-colors duration-100 cursor-pointer"
          style={{
            border: isSelected ? `2px solid ${BRAND}` : `2px solid ${tokens.slate300}`,
            background: isSelected ? BRAND : "hsl(var(--card))",
            boxShadow: isSelected ? `0 0 0 3px rgba(15,118,110,0.18)` : undefined,
          }}
        >
          {isSelected && (
            <svg width="9" height="7" viewBox="0 0 9 7" fill="none" aria-hidden>
              <path d="M1 3.5L3.5 6L8 1" stroke="white" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          )}
        </button>
      </WT>

      {/*
        Single-row card layout (desktop):
        [checkbox gap] [initials] [name+age] [RAF badge] [suspects] [top gap] [revenue] [visit] [arrow]
      */}
      <Link
        href={`/patients/${item.patient_id}`}
        onClick={handleCardClick}
        aria-label={`Open chart for ${item.patient_name}`}
        className="flex items-center gap-3 pl-10 pr-4 py-3 rounded-lg no-underline text-inherit transition-colors duration-[120ms] cursor-pointer group"
        style={{
          background: isSelected ? "rgba(15,118,110,0.06)" : "hsl(var(--card))",
          border: isSelected ? `1.5px solid ${BRAND}` : `1px solid ${tokens.slate200}`,
        }}
        onMouseEnter={(e) => {
          if (!isSelected) (e.currentTarget as HTMLAnchorElement).style.background = "hsl(var(--muted)/0.5)";
        }}
        onMouseLeave={(e) => {
          if (!isSelected) (e.currentTarget as HTMLAnchorElement).style.background = "hsl(var(--card))";
        }}
      >
        {/* Initials avatar — 32px circle */}
        <div
          aria-hidden
          className="shrink-0 w-8 h-8 rounded-full flex items-center justify-center text-[11px] font-bold select-none"
          style={{ background: tokens.primarySoft, color: tokens.primary }}
        >
          {initials}
        </div>

        {/* Name + age/sex — grows to fill available space */}
        <div className="min-w-0 flex-1">
          <div className="text-[13px] font-bold text-foreground overflow-hidden text-ellipsis whitespace-nowrap leading-tight">
            {item.patient_name}
          </div>
          <div className="text-[11px] text-muted-foreground leading-tight">{ageSex}</div>
        </div>

        {/* RAF score badge */}
        <WT
          text={`Estimated RAF impact: ${raf.toFixed(2)} points. Reflects the incremental risk-adjustment contribution of all open gaps for this patient.`}
          side="top"
        >
          <span
            data-testid={`raf-badge-${item.patient_id}`}
            className="shrink-0 inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-bold tabular-nums whitespace-nowrap cursor-default"
            style={{ background: rafStyle.bg, color: rafStyle.color }}
          >
            RAF {raf.toFixed(2)}
          </span>
        </WT>

        {/* Open suspects badge — amber, only shown if > 0 */}
        {suspectCount > 0 ? (
          <WT
            text={`${suspectCount} open suspect condition${suspectCount === 1 ? "" : "s"} — conditions flagged by analytics as likely present but not yet coded this year.`}
            side="top"
          >
            <span
              data-testid={`suspects-badge-${item.patient_id}`}
              className="shrink-0 inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-bold tabular-nums whitespace-nowrap cursor-default"
              style={{ background: tokens.warningSoft, color: tokens.warningStrong }}
            >
              {suspectCount} suspect{suspectCount === 1 ? "" : "s"}
            </span>
          </WT>
        ) : (
          /* Placeholder keeps column alignment on rows with no suspects */
          <span className="shrink-0 w-[60px]" aria-hidden />
        )}

        {/* Top HCC gap — truncated condition label */}
        <div className="shrink-0 w-[140px] min-w-0 hidden sm:block">
          {topGap ? (
            <WT
              text={`Top open recapture gap: HCC ${topGap.hcc_code}${topGap.icd10_codes?.length ? ` (${topGap.icd10_codes[0]})` : ""}. Was coded in a prior year but not yet confirmed this measurement year.`}
              side="top"
            >
              <span
                className="block text-[11px] font-semibold overflow-hidden text-ellipsis whitespace-nowrap cursor-default"
                style={{ color: tokens.danger }}
              >
                HCC {topGap.hcc_code}
                {item.open_recapture_gaps.length > 1 && (
                  <span className="ml-1 font-normal text-muted-foreground">
                    +{item.open_recapture_gaps.length - 1}
                  </span>
                )}
              </span>
            </WT>
          ) : (
            <span className="text-[11px] text-muted-foreground">No gaps</span>
          )}
        </div>

        {/* Revenue at risk */}
        <WT
          text="Estimated incremental revenue at risk if open HCC gaps are not recaptured this measurement year. Calculated at the MA rate of ~$9,000 per RAF point."
          side="top"
        >
          <span
            data-testid={`revenue-${item.patient_id}`}
            className="shrink-0 text-[12px] font-bold tabular-nums whitespace-nowrap cursor-default hidden md:block"
            style={{ color: tokens.slate700 }}
          >
            {fmtCurrency(item.estimated_revenue_at_risk ?? 0)}
          </span>
        </WT>

        {/* Visit time — only shown when AWV is scheduled today */}
        {visitLabel ? (
          <WT text={`AWV scheduled today at ${visitLabel}.`} side="top">
            <span
              className="shrink-0 inline-flex items-center gap-1 text-[11px] font-semibold whitespace-nowrap cursor-default hidden lg:inline-flex"
              style={{ color: tokens.primary }}
            >
              <CalendarClock size={12} aria-hidden />
              {visitLabel}
            </span>
          </WT>
        ) : (
          <span className="shrink-0 w-[72px] hidden lg:block" aria-hidden />
        )}

        {/* Navigate arrow */}
        <ChevronRight
          size={15}
          className="shrink-0 text-muted-foreground transition-transform duration-100 group-hover:translate-x-0.5"
          aria-hidden
        />
      </Link>
    </div>
  );
}
