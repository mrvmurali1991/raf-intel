"use client";

import React, { useState, useMemo } from "react";
import { usePaymentYear, useIsHistoricalPY } from "@/contexts/payment-year-context";
import { HistoricalPYBanner } from "@/components/HistoricalPYBanner";
import PageAlerts from "@/components/PageAlerts";
import dynamic from "next/dynamic";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import {
  RefreshCw,
  Download,
  Calendar,
  Search,
  ChevronLeft,
  ChevronRight,
  ArrowUpDown,
  AlertTriangle,
  CalendarClock,
} from "lucide-react";
import { getRecaptureGapsReport, getRevenueOpportunity, useMetricFormula } from "@/lib/api";
import { downloadCSV } from "@/lib/csv-export";
import { PageHeader } from "@/components/ui/page-header";
import { EmptyState } from "@/components/ui/empty-state";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { HelpButton } from "@/components/HelpPanel";
import { MetricCard } from "@/components/ui/metric-card";
import FeatureFlag from "@/components/FeatureFlag";
import DataQualityBanner from "@/components/DataQualityBanner";
import { tokens } from "@/styles/tokens";
import { KgGapBadge } from "@/components/kg/KgGapBadge";
import { HccChipWithPopover } from "@/components/kg/HccExplainCard";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

// Feature-flagged secondary sections are lazy-loaded to defer ~60 kB
// (CfoExecutiveSummary, BonusLeaderboard, OutreachSummaryCards, AuditReadinessCard,
// RecaptureVelocityKpis, RecaptureDecayChart) that are hidden behind feature flags.
const RecaptureFeatureSections = dynamic(
  () => import("./RecaptureFeatureSections"),
  {
    ssr: false,
    loading: () => <div className="h-10" />,
  }
);

// ─── Types ──────────────────────────────────────────────────────────────────

interface Gap {
  pid: string;
  first_name: string;
  last_name: string;
  condition: string;
  icd_code: string;
  onset_date: string;
  /** Optional KG fields surfaced for the evidence-chain badge. */
  id?: number;
  hcc_code?: string;
  evidence_type?: string;
}

interface TopCondition {
  icd_code: string;
  condition: string;
  gap_count: number;
}

interface RecaptureReport {
  measurement_year: number;
  total_gaps: number;
  patients_affected: number;
  gaps: Gap[];
  top_conditions: TopCondition[];
}

// ─── Constants ──────────────────────────────────────────────────────────────

const REVENUE_PER_GAP = 3000;
const PAGE_SIZE = 25;

// ─── Helpers ────────────────────────────────────────────────────────────────

function daysSince(dateStr: string): number {
  const diff = Date.now() - new Date(dateStr).getTime();
  return Math.floor(diff / (1000 * 60 * 60 * 24));
}

interface Priority {
  label: string;
  rank: number;
  badgeClass: string;
  borderClass: string;
  borderStyle: string;
}

function priorityFromDays(days: number): Priority {
  if (days > 365) {
    return {
      label: "High",
      rank: 3,
      badgeClass: "inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400",
      borderClass: "border-l-4 border-l-red-500",
      borderStyle: tokens.dangerStrong,
    };
  }
  if (days >= 180) {
    return {
      label: "Medium",
      rank: 2,
      badgeClass: "inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400",
      borderClass: "border-l-4 border-l-amber-500",
      borderStyle: tokens.warningStrong,
    };
  }
  return {
    label: "Low",
    rank: 1,
    badgeClass: "inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400",
    borderClass: "border-l-4 border-l-emerald-500",
    borderStyle: tokens.successStrong,
  };
}

function formatCurrency(n: number): string {
  return "$" + n.toLocaleString("en-US");
}

function revenueColor(amount: number): string {
  if (amount >= 50000) return "text-red-600 dark:text-red-400";
  if (amount >= 15000) return "text-amber-600 dark:text-amber-400";
  return "text-emerald-600 dark:text-emerald-400";
}

type SortKey = "priority" | "name" | "condition";

// ─── Component ──────────────────────────────────────────────────────────────

export default function RecapturePage() {
  const router = useRouter();
  const { paymentYear: year, setPaymentYear: setYear } = usePaymentYear();
  const isHistoricalPY = useIsHistoricalPY();
  const [search, setSearch] = useState("");
  const [sortBy, setSortBy] = useState<SortKey>("priority");
  const [page, setPage] = useState(1);

  const { data, isLoading, isError, refetch } = useQuery<RecaptureReport>({
    queryKey: ["recapture-gaps", year],
    queryFn: () => getRecaptureGapsReport(year) as unknown as Promise<RecaptureReport>,
    // perf(demo): 60s staleTime keeps the recapture table cached so the
    // recapture -> dashboard -> recapture demo flow paints instantly.
    staleTime: 60_000,
  });

  // Revenue meta — stale-while-revalidate; provides formula tooltip for CFO.
  const { data: revData } = useQuery({
    queryKey: ["revenue-opportunity", year],
    queryFn: () => getRevenueOpportunity(year),
    staleTime: 5 * 60 * 1000,
  });
  const revenueAtRiskMeta =
    useMetricFormula(revData as Record<string, unknown> | null | undefined, "estimated_annual_revenue") ??
    revData?._meta ??
    null;

  // ── Derived data ────────────────────────────────────────────────────────

  const enrichedGaps = useMemo(() => {
    if (!data?.gaps?.length) return [];
    return data.gaps.map((g) => {
      const days = daysSince(g.onset_date);
      return { ...g, days, priority: priorityFromDays(days) };
    });
  }, [data]);

  const filtered = useMemo(() => {
    let list = enrichedGaps;
    if (search.trim()) {
      const q = search.toLowerCase();
      list = list.filter(
        (g) =>
          g.first_name.toLowerCase().includes(q) ||
          g.last_name.toLowerCase().includes(q)
      );
    }
    list = [...list].sort((a, b) => {
      if (sortBy === "priority") return b.priority.rank - a.priority.rank;
      if (sortBy === "name")
        return `${a.last_name} ${a.first_name}`.localeCompare(
          `${b.last_name} ${b.first_name}`
        );
      return a.condition.localeCompare(b.condition);
    });
    return list;
  }, [enrichedGaps, search, sortBy]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const paged = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  // Reset page on filter change
  React.useEffect(() => {
    setPage(1);
  }, [search, sortBy, year]);

  // ── CSV Export ──────────────────────────────────────────────────────────

  function exportCSV() {
    if (!filtered.length) return;
    downloadCSV(
      filtered.map((g) => ({
        Patient: `${g.last_name}, ${g.first_name}`,
        Condition: g.condition,
        "ICD-10": g.icd_code,
        "Last Coded": g.onset_date,
        "Days Since": g.days,
        Priority: g.priority.label,
      })),
      "recapture-gaps"
    );
  }

  // ── Loading state ────────────────────────────────────────────────────────

  if (isLoading) {
    return (
      <div className="p-6">
        <PageHeader
          title="Recapture Gaps"
          subtitle="Loading recapture opportunities…"
          icon={<RefreshCw size={22} />}
        />
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6">
          {[1, 2, 3].map((i) => (
            <div key={i} className="premium-card shimmer h-24 rounded-lg" />
          ))}
        </div>
        <div className="premium-card shimmer h-72 rounded-lg" />
      </div>
    );
  }

  // ── Error state ──────────────────────────────────────────────────────────

  if (isError || !data) {
    return (
      <div className="p-6">
        <PageHeader title="Recapture Gaps" icon={<RefreshCw size={22} />} />
        <div
          role="alert"
          className="flex items-center gap-3 p-4 rounded-lg border border-destructive/30 bg-destructive/10 text-destructive text-sm mt-4"
        >
          <AlertTriangle size={18} aria-hidden="true" className="flex-shrink-0" />
          <span className="flex-1">Failed to load recapture data. Please try again.</span>
          <button
            type="button"
            onClick={() => refetch()}
            aria-label="Retry loading recapture data"
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md border border-destructive/30 bg-card text-destructive text-xs font-semibold hover:bg-destructive/10 transition-colors cursor-pointer"
          >
            <RefreshCw size={13} aria-hidden="true" />
            Retry
          </button>
        </div>
      </div>
    );
  }

  // ── Derived view data ────────────────────────────────────────────────────

  const maxConditionCount =
    (data.top_conditions ?? []).length > 0
      ? Math.max(...(data.top_conditions ?? []).map((c) => c.gap_count))
      : 1;

  const sortOptions: { key: SortKey; label: string; tooltip: string }[] = [
    {
      key: "priority",
      label: "Priority",
      tooltip: "Sort by urgency: High (>365 days uncoded) first, then Medium, then Low",
    },
    {
      key: "name",
      label: "Patient Name",
      tooltip: "Sort alphabetically by patient last name, then first name",
    },
    {
      key: "condition",
      label: "Condition",
      tooltip: "Sort alphabetically by chronic condition diagnosis name",
    },
  ];

  const totalRevenue = (data.total_gaps ?? 0) * REVENUE_PER_GAP;

  return (
    <div className="p-6 max-w-[1200px] mx-auto overflow-x-hidden rci-page-pad-desktop">
      <PageAlerts defaultOpen>
        <DataQualityBanner />
        <HistoricalPYBanner />
      </PageAlerts>

      {/* Header */}
      <div className="animate-fade-in">
        <PageHeader
          title="Recapture Gaps"
          subtitle="Chronic conditions documented in prior years that must be re-coded annually to maintain RAF score accuracy and revenue"
          icon={<RefreshCw size={22} />}
          actions={
            <>
              <select
                value={year}
                onChange={(e) => setYear(Number(e.target.value))}
                aria-label="Measurement year"
                className="px-3 py-2 rounded-lg border border-border text-sm font-semibold text-foreground bg-card cursor-pointer focus:outline-none focus:ring-2 focus:ring-primary/30"
              >
                {Array.from({ length: 3 }, (_, i) => new Date().getFullYear() - i).map(
                  (yr) => (
                    <option key={yr} value={yr}>
                      {yr}
                    </option>
                  )
                )}
              </select>
              <HelpButton />
            </>
          }
        />
      </div>

      {/* Summary Strip — 3-column metric cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6">
        <div className="animate-fade-in stagger-1">
          <MetricCard
            label="Estimated Revenue at Risk"
            value={
              (data.total_gaps ?? 0) === 0
                ? "Awaiting data ingestion"
                : formatCurrency(totalRevenue)
            }
            subtitle={
              (data.total_gaps ?? 0) === 0
                ? "No open recapture gaps detected yet"
                : "Unrecaptured chronic conditions × prior-year RAF dollars"
            }
            intent="danger"
            icon={<ArrowUpDown size={18} />}
            meta={revenueAtRiskMeta ?? undefined}
            freshness={revData?.last_computed_at ?? undefined}
            labelTestId="revenue-at-risk-label"
            valueTestId="revenue-at-risk-value"
            labelTooltip="Projected revenue loss if uncaptured chronic conditions are not re-coded before year-end. Calculated as total gaps × $3,000 average RAF revenue per gap."
          />
        </div>
        <div className="animate-fade-in stagger-2">
          <MetricCard
            label="Total Recapture Gaps"
            value={
              (data.total_gaps ?? 0) === 0
                ? "0 — all clear"
                : (data.total_gaps ?? 0).toLocaleString()
            }
            subtitle={
              (data.total_gaps ?? 0) === 0
                ? "All chronic conditions recaptured this year"
                : undefined
            }
            intent="warning"
            icon={<RefreshCw size={18} />}
            labelTooltip="Number of chronic conditions documented in a prior year that have not yet been re-coded in the current measurement year. Each gap requires a qualifying encounter."
          />
        </div>
        <div className="animate-fade-in stagger-3">
          <MetricCard
            label="Patients Affected"
            value={
              (data.patients_affected ?? 0) === 0
                ? "0 — none yet"
                : (data.patients_affected ?? 0).toLocaleString()
            }
            subtitle={
              (data.patients_affected ?? 0) === 0
                ? "Begin by importing patient encounter data"
                : undefined
            }
            icon={<Calendar size={18} />}
            labelTooltip="Distinct patients who have at least one open recapture gap this measurement year. One patient may have multiple gaps across different HCC categories."
          />
        </div>
      </div>

      {/* Main row: Worklist (2fr) + Top Conditions (1fr) */}
      <div className="grid grid-cols-1 lg:grid-cols-[2fr_1fr] gap-4 mb-6 items-start">

        {/* Left: Patient Worklist */}
        <div className="premium-card animate-slide-up stagger-5 p-6 min-w-0">
          {/* Worklist header */}
          <div className="flex items-center justify-between mb-4 flex-wrap gap-3">
            <h3 className="gradient-text m-0 text-base font-bold">
              Patients Requiring Recapture
            </h3>
            <div className="flex items-center gap-3 flex-wrap">
              {/* Search */}
              <TooltipProvider delayDuration={200}>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <div className="relative">
                      <Search
                        size={14}
                        className="absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground pointer-events-none"
                      />
                      <input
                        type="text"
                        placeholder="Search patient..."
                        value={search}
                        onChange={(e) => setSearch(e.target.value)}
                        aria-label="Search patients by name or ICD code"
                        data-testid="recapture-search"
                        className="pl-8 pr-3 py-1.5 rounded-full border border-border text-sm text-foreground bg-card w-48 focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 transition-all"
                      />
                    </div>
                  </TooltipTrigger>
                  <TooltipContent side="bottom" sideOffset={6} data-testid="search-tooltip">
                    Filter by patient name or ICD code
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>

              {/* Sort Pills */}
              <div className="flex gap-1 bg-muted rounded-full p-0.5">
                {sortOptions.map((opt) => (
                  <TooltipProvider key={opt.key} delayDuration={200}>
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <button
                          onClick={() => setSortBy(opt.key)}
                          className="btn-press px-3 py-1 rounded-full border-none text-xs font-semibold cursor-pointer transition-all"
                          aria-pressed={sortBy === opt.key}
                          data-testid={`sort-${opt.key}`}
                          style={{
                            background: sortBy === opt.key ? tokens.primary : "transparent",
                            color: sortBy === opt.key ? tokens.white : tokens.slate600,
                            boxShadow:
                              sortBy === opt.key
                                ? "0 1px 3px rgba(37,99,235,0.3)"
                                : "none",
                          }}
                        >
                          {opt.label}
                        </button>
                      </TooltipTrigger>
                      <TooltipContent
                        side="bottom"
                        sideOffset={6}
                        data-testid={`sort-${opt.key}-tooltip`}
                      >
                        {opt.tooltip}
                      </TooltipContent>
                    </Tooltip>
                  </TooltipProvider>
                ))}
              </div>
            </div>
          </div>

          {/* Table or empty state */}
          {filtered.length === 0 ? (
            <EmptyState
              state="filtered-out"
              icon={<CalendarClock size={24} />}
              title="No recapture gaps found"
              description={
                search.trim()
                  ? "No patients match your search. Try a different name."
                  : "All chronic conditions have been recaptured for the selected year."
              }
              cta={
                search.trim()
                  ? { label: "Clear search", onClick: () => setSearch("") }
                  : undefined
              }
            />
          ) : (
            <>
              {/* Shared DataTable from @/components/ui/table */}
              <div className="rounded-lg border border-border overflow-hidden">
                <Table aria-label="Patients requiring recapture">
                  <TableHeader>
                    <TableRow className="bg-muted/40 hover:bg-muted/40">
                      <TableHead className="text-xs font-semibold uppercase tracking-wide text-muted-foreground pl-4">
                        Patient
                      </TableHead>
                      <TableHead className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                        Condition
                      </TableHead>
                      <TableHead className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                        <TooltipProvider delayDuration={200}>
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <span
                                className="cursor-help border-b border-dotted border-muted-foreground"
                                tabIndex={0}
                                data-testid="col-icd10"
                              >
                                ICD-10
                              </span>
                            </TooltipTrigger>
                            <TooltipContent
                              side="top"
                              sideOffset={6}
                              data-testid="col-icd10-tooltip"
                            >
                              ICD-10-CM diagnosis code. Hover any code in the table to see
                              its full description and RAF coefficient.
                            </TooltipContent>
                          </Tooltip>
                        </TooltipProvider>
                      </TableHead>
                      <TableHead className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                        Last Coded
                      </TableHead>
                      <TableHead className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                        <TooltipProvider delayDuration={200}>
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <span
                                className="cursor-help border-b border-dotted border-muted-foreground"
                                tabIndex={0}
                                data-testid="col-days-since"
                              >
                                Days Since
                              </span>
                            </TooltipTrigger>
                            <TooltipContent
                              side="top"
                              sideOffset={6}
                              data-testid="col-days-since-tooltip"
                            >
                              Days since last billing encounter for this HCC. Higher values
                              indicate more urgent recapture need.
                            </TooltipContent>
                          </Tooltip>
                        </TooltipProvider>
                      </TableHead>
                      <TableHead className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                        <TooltipProvider delayDuration={200}>
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <span
                                className="cursor-help border-b border-dotted border-muted-foreground"
                                tabIndex={0}
                                data-testid="col-priority"
                              >
                                Priority
                              </span>
                            </TooltipTrigger>
                            <TooltipContent
                              side="top"
                              sideOffset={6}
                              data-testid="col-priority-tooltip"
                            >
                              High: &gt;365 days uncoded · Medium: 180–365 days · Low:
                              &lt;180 days
                            </TooltipContent>
                          </Tooltip>
                        </TooltipProvider>
                      </TableHead>
                      <TableHead className="text-xs font-semibold uppercase tracking-wide text-muted-foreground text-right pr-4">
                        <TooltipProvider delayDuration={200}>
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <span
                                className="cursor-help border-b border-dotted border-muted-foreground"
                                tabIndex={0}
                              >
                                Revenue Impact
                              </span>
                            </TooltipTrigger>
                            <TooltipContent side="top" sideOffset={6}>
                              Estimated annual revenue at risk for this gap. Based on
                              $3,000 average RAF revenue per uncaptured condition.
                            </TooltipContent>
                          </Tooltip>
                        </TooltipProvider>
                      </TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {paged.map((g, i) => (
                      <TableRow
                        key={`${g.pid}-${g.icd_code}-${i}`}
                        tabIndex={0}
                        aria-label={`${g.last_name}, ${g.first_name} — ${g.condition}, ${g.priority.label} priority`}
                        onClick={() => router.push(`/patients/${g.pid}`)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" || e.key === " ") {
                            e.preventDefault();
                            router.push(`/patients/${g.pid}`);
                          }
                        }}
                        className="cursor-pointer transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary"
                        style={{
                          borderLeft: `3px solid ${g.priority.borderStyle}`,
                          background: i % 2 === 0 ? undefined : "hsl(var(--muted)/0.3)",
                        }}
                      >
                        {/* Patient name */}
                        <TableCell className="pl-4 font-semibold text-primary">
                          <TooltipProvider delayDuration={200}>
                            <Tooltip>
                              <TooltipTrigger asChild>
                                <span
                                  className="cursor-pointer"
                                  data-testid={`patient-name-${g.pid}`}
                                >
                                  {g.last_name}, {g.first_name}
                                </span>
                              </TooltipTrigger>
                              <TooltipContent
                                side="right"
                                sideOffset={6}
                                data-testid="patient-row-tooltip"
                              >
                                Open patient chart
                              </TooltipContent>
                            </Tooltip>
                          </TooltipProvider>
                        </TableCell>

                        {/* Condition */}
                        <TableCell>
                          <span className="inline-flex items-center gap-2 flex-wrap">
                            {g.hcc_code ? (
                              <FeatureFlag
                                flagKey="kg_evidence_panel"
                                fallback={<span>{g.condition}</span>}
                              >
                                <HccChipWithPopover hccCode={g.hcc_code}>
                                  <span>{g.condition}</span>
                                </HccChipWithPopover>
                              </FeatureFlag>
                            ) : (
                              <span>{g.condition}</span>
                            )}
                            <FeatureFlag flagKey="kg_evidence_panel">
                              <TooltipProvider delayDuration={200}>
                                <Tooltip>
                                  <TooltipTrigger asChild>
                                    <span>
                                      <KgGapBadge
                                        evidenceType={g.evidence_type ?? "kg_rule"}
                                        suspectId={g.id ?? undefined}
                                        hccCode={g.hcc_code}
                                        patientId={Number(g.pid) || undefined}
                                      />
                                    </span>
                                  </TooltipTrigger>
                                  <TooltipContent
                                    side="top"
                                    sideOffset={6}
                                    data-testid="kg-badge-tooltip"
                                  >
                                    Knowledge graph rule matched — see evidence panel for
                                    source citations and supporting clinical signals
                                  </TooltipContent>
                                </Tooltip>
                              </TooltipProvider>
                            </FeatureFlag>
                          </span>
                        </TableCell>

                        {/* ICD-10 */}
                        <TableCell className="font-mono text-xs tabular-nums">
                          <TooltipProvider delayDuration={200}>
                            <Tooltip>
                              <TooltipTrigger asChild>
                                <span
                                  className="cursor-help border-b border-dotted border-muted-foreground"
                                  data-testid={`icd-code-${g.icd_code}`}
                                >
                                  {g.icd_code}
                                </span>
                              </TooltipTrigger>
                              <TooltipContent
                                side="top"
                                sideOffset={6}
                                data-testid="icd-code-tooltip"
                              >
                                <span className="font-semibold">{g.icd_code}</span> —{" "}
                                {g.condition}
                                <br />
                                <span className="text-[10px] opacity-70">
                                  RAF coefficient determined by CMS HCC model for this
                                  diagnosis category.
                                </span>
                              </TooltipContent>
                            </Tooltip>
                          </TooltipProvider>
                        </TableCell>

                        {/* Last Coded */}
                        <TableCell className="tabular-nums text-muted-foreground text-sm">
                          {new Date(g.onset_date).toLocaleDateString()}
                        </TableCell>

                        {/* Days Since */}
                        <TableCell className="tabular-nums font-semibold text-sm">
                          {g.days}
                        </TableCell>

                        {/* Priority badge */}
                        <TableCell>
                          <TooltipProvider delayDuration={200}>
                            <Tooltip>
                              <TooltipTrigger asChild>
                                <span
                                  className={g.priority.badgeClass}
                                  data-testid={`priority-pill-${g.pid}`}
                                >
                                  {g.priority.label}
                                </span>
                              </TooltipTrigger>
                              <TooltipContent
                                side="left"
                                sideOffset={6}
                                data-testid="priority-tooltip"
                              >
                                {g.priority.label === "High"
                                  ? "High — condition uncoded for >365 days. Immediate outreach recommended."
                                  : g.priority.label === "Medium"
                                  ? "Medium — condition uncoded 180–365 days. Schedule within 30 days."
                                  : "Low — condition uncoded <180 days. Standard scheduling applies."}
                              </TooltipContent>
                            </Tooltip>
                          </TooltipProvider>
                        </TableCell>

                        {/* Revenue Impact — prominent, color-coded */}
                        <TableCell className="pr-4 text-right">
                          <span
                            className={`tabular-nums font-bold text-sm ${revenueColor(REVENUE_PER_GAP)}`}
                          >
                            {formatCurrency(REVENUE_PER_GAP)}
                          </span>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>

              {/* Pagination — consistent with other pages */}
              <div className="flex items-center justify-between mt-4 text-sm text-muted-foreground">
                <span className="tabular-nums">
                  Showing {(page - 1) * PAGE_SIZE + 1}–
                  {Math.min(page * PAGE_SIZE, filtered.length)} of {filtered.length}
                </span>
                <div className="flex items-center gap-1">
                  <button
                    onClick={() => setPage((p) => Math.max(1, p - 1))}
                    disabled={page === 1}
                    aria-label="Previous page"
                    className="btn-press p-1.5 rounded-md border border-border bg-card hover:bg-muted transition-colors disabled:opacity-40 disabled:cursor-not-allowed flex items-center"
                  >
                    <ChevronLeft size={14} />
                  </button>
                  <span className="tabular-nums px-2 font-semibold text-foreground">
                    {page} / {totalPages}
                  </span>
                  <button
                    onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                    disabled={page === totalPages}
                    aria-label="Next page"
                    className="btn-press p-1.5 rounded-md border border-border bg-card hover:bg-muted transition-colors disabled:opacity-40 disabled:cursor-not-allowed flex items-center"
                  >
                    <ChevronRight size={14} />
                  </button>
                </div>
              </div>
            </>
          )}
        </div>

        {/* Right: Top Conditions chart */}
        {(data.top_conditions ?? []).length > 0 && (
          <div className="premium-card animate-slide-up stagger-4 p-6 min-w-0">
            <h3 className="gradient-text m-0 mb-4 text-base font-bold">
              Most Common Uncaptured Conditions
            </h3>
            <div className="flex flex-col gap-2.5">
              {(data.top_conditions ?? []).slice(0, 10).map((c, idx) => (
                <div
                  key={c.icd_code}
                  className="hover-lift flex items-center gap-3 px-3 py-2 rounded-lg transition-all"
                  style={{
                    background: idx % 2 === 0 ? "hsl(var(--muted)/0.4)" : "transparent",
                  }}
                >
                  <span className="w-6 text-center text-xs font-bold text-muted-foreground flex-shrink-0">
                    {idx + 1}
                  </span>
                  <span className="flex-1 min-w-0 max-w-[220px] text-sm text-foreground font-medium truncate">
                    {c.condition}
                  </span>
                  <TooltipProvider delayDuration={200}>
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <span
                          className="flex-shrink-0 text-xs font-semibold text-primary font-mono cursor-help border-b border-dotted border-primary"
                          tabIndex={0}
                          data-testid={`top-condition-chip-${c.icd_code}`}
                        >
                          {c.icd_code}
                        </span>
                      </TooltipTrigger>
                      <TooltipContent
                        side="left"
                        sideOffset={6}
                        data-testid="top-condition-tooltip"
                      >
                        <span className="font-semibold">{c.icd_code}</span> — {c.condition}
                        <br />
                        <span className="text-[10px] opacity-70">
                          {c.gap_count} open gap{c.gap_count !== 1 ? "s" : ""} across your
                          patient panel
                        </span>
                      </TooltipContent>
                    </Tooltip>
                  </TooltipProvider>
                  {/* Progress bar */}
                  <div className="flex-1 h-2 rounded-full bg-muted overflow-hidden">
                    <div
                      className="h-full rounded-full bg-primary transition-[width] duration-500 ease-out"
                      style={{ width: `${(c.gap_count / maxConditionCount) * 100}%` }}
                    />
                  </div>
                  <span className="tabular-nums w-10 text-xs font-bold text-foreground text-right flex-shrink-0">
                    {c.gap_count}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Feature-flagged secondary sections — lazy-loaded (~60 kB deferred) */}
      <RecaptureFeatureSections year={year} />

      {/* Action Panel */}
      <div className="premium-card animate-slide-up stagger-6 bg-gradient-to-br from-muted to-card p-6 flex items-center justify-between flex-wrap gap-4">
        <div>
          <p className="m-0 text-sm font-semibold text-foreground">
            Schedule Wellness Visits
          </p>
          <p className="mt-1 mb-0 text-xs text-muted-foreground">
            Prioritize patients with high-priority recapture gaps for annual wellness visits
            to ensure chronic conditions are documented.
          </p>
        </div>
        <button
          onClick={isHistoricalPY ? undefined : exportCSV}
          disabled={isHistoricalPY}
          aria-label="Export recapture gaps to CSV"
          title={isHistoricalPY ? "Disabled in historical view" : undefined}
          data-testid="export-csv-recapture"
          className="btn-press inline-flex items-center gap-1.5 px-5 py-2.5 rounded-md border-none text-sm font-semibold text-white bg-primary hover:opacity-90 transition-opacity disabled:opacity-60 disabled:cursor-not-allowed shadow-sm flex-shrink-0"
        >
          <Download size={14} />
          Export to CSV
        </button>
      </div>
    </div>
  );
}
