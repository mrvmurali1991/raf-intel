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
  Search,
  ChevronLeft,
  ChevronRight,
  AlertTriangle,
  CalendarClock,
} from "lucide-react";
import {
  listRecaptureGaps,
  RecaptureGapRow,
} from "@/lib/api";
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
import DataQualityBanner from "@/components/DataQualityBanner";

// Feature-flagged secondary sections are lazy-loaded to defer ~60 kB
const RecaptureFeatureSections = dynamic(
  () => import("./RecaptureFeatureSections"),
  {
    ssr: false,
    loading: () => <div className="h-10" />,
  }
);

// ─── Constants ──────────────────────────────────────────────────────────────

const REVENUE_PER_GAP = 3000;
const PAGE_SIZE = 25;

// At-risk = gaps that are open AND have fewer than 90 days remaining in the year
const AT_RISK_DAYS_THRESHOLD = 90;

// ─── Types ──────────────────────────────────────────────────────────────────

type StatusFilter = "all" | "open" | "recaptured" | "dismissed";

// ─── Helpers ────────────────────────────────────────────────────────────────

/** Days remaining until Dec 31 of the given payment year. */
function daysRemainingInYear(paymentYear: number): number {
  const endOfYear = new Date(paymentYear, 11, 31); // Dec 31
  const today = new Date();
  const diff = endOfYear.getTime() - today.getTime();
  return Math.max(0, Math.ceil(diff / (1000 * 60 * 60 * 24)));
}

function formatCurrency(n: number): string {
  if (n >= 1_000_000) return "$" + (n / 1_000_000).toFixed(1) + "M";
  if (n >= 1_000) return "$" + Math.round(n / 1_000) + "K";
  return "$" + n.toLocaleString("en-US");
}

/** Urgency color classes based on days remaining in the payment year. */
function urgencyClasses(daysLeft: number): {
  pill: string;
  dot: string;
  label: string;
} {
  if (daysLeft <= 30) {
    return {
      pill: "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400",
      dot: "bg-red-500",
      label: `${daysLeft}d left`,
    };
  }
  if (daysLeft <= 90) {
    return {
      pill: "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400",
      dot: "bg-amber-500",
      label: `${daysLeft}d left`,
    };
  }
  return {
    pill: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400",
    dot: "bg-emerald-500",
    label: `${daysLeft}d left`,
  };
}

function statusBadgeClasses(status: RecaptureGapRow["status"]): string {
  if (status === "recaptured")
    return "inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400";
  if (status === "dismissed")
    return "inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold bg-muted text-muted-foreground";
  // open
  return "inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400";
}

function statusLabel(status: RecaptureGapRow["status"]): string {
  if (status === "recaptured") return "Recaptured";
  if (status === "dismissed") return "Dismissed";
  return "Open";
}

// ─── Summary Pill Bar ────────────────────────────────────────────────────────

interface SummaryPillBarProps {
  total: number;
  open: number;
  recaptured: number;
  atRisk: number;
  revenue: number;
}

function SummaryPillBar({ total, open, recaptured, atRisk, revenue }: SummaryPillBarProps) {
  const pills: { label: string; value: string; colorClass: string }[] = [
    {
      label: "Total",
      value: total.toLocaleString(),
      colorClass: "text-foreground",
    },
    {
      label: "Open",
      value: open.toLocaleString(),
      colorClass: "text-amber-700 dark:text-amber-400",
    },
    {
      label: "Recaptured",
      value: recaptured.toLocaleString(),
      colorClass: "text-emerald-700 dark:text-emerald-400",
    },
    {
      label: "At Risk",
      value: atRisk.toLocaleString(),
      colorClass: "text-red-700 dark:text-red-400",
    },
    {
      label: "Revenue",
      value: formatCurrency(revenue),
      colorClass: "text-foreground font-bold",
    },
  ];

  return (
    <div
      className="flex flex-wrap items-center gap-2 mb-6 px-4 py-3 rounded-lg border border-border bg-muted/40"
      role="status"
      aria-label="Recapture gap summary"
    >
      {pills.map((pill, idx) => (
        <React.Fragment key={pill.label}>
          <span className="inline-flex items-center gap-1.5 text-sm">
            <span className="text-muted-foreground">{pill.label}:</span>
            <span className={`font-semibold tabular-nums ${pill.colorClass}`}>
              {pill.value}
            </span>
          </span>
          {idx < pills.length - 1 && (
            <span className="text-muted-foreground/40 select-none" aria-hidden="true">
              |
            </span>
          )}
        </React.Fragment>
      ))}
    </div>
  );
}

// ─── Status Filter Tabs ──────────────────────────────────────────────────────

const STATUS_TABS: { key: StatusFilter; label: string }[] = [
  { key: "all", label: "All" },
  { key: "open", label: "Open" },
  { key: "recaptured", label: "Recaptured" },
  { key: "dismissed", label: "Dismissed" },
];

interface StatusTabsProps {
  active: StatusFilter;
  onChange: (v: StatusFilter) => void;
  counts: Record<StatusFilter, number>;
}

function StatusTabs({ active, onChange, counts }: StatusTabsProps) {
  return (
    <div
      role="tablist"
      aria-label="Filter by gap status"
      className="flex gap-1 bg-muted rounded-full p-0.5 w-fit"
    >
      {STATUS_TABS.map((tab) => {
        const isActive = active === tab.key;
        return (
          <button
            key={tab.key}
            role="tab"
            aria-selected={isActive}
            onClick={() => onChange(tab.key)}
            className={[
              "btn-press px-3 py-1 rounded-full text-xs font-semibold cursor-pointer transition-all border-none",
              isActive
                ? "bg-primary text-white shadow-sm"
                : "bg-transparent text-muted-foreground hover:text-foreground",
            ].join(" ")}
          >
            {tab.label}
            <span
              className={[
                "ml-1.5 tabular-nums",
                isActive ? "opacity-80" : "opacity-60",
              ].join(" ")}
            >
              {counts[tab.key]}
            </span>
          </button>
        );
      })}
    </div>
  );
}

// ─── Component ──────────────────────────────────────────────────────────────

export default function RecapturePage() {
  const router = useRouter();
  const { paymentYear: year, setPaymentYear: setYear } = usePaymentYear();
  const isHistoricalPY = useIsHistoricalPY();
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [page, setPage] = useState(1);

  const { data: gaps = [], isLoading, isError, refetch } = useQuery<RecaptureGapRow[]>({
    queryKey: ["recapture-gaps-list", year],
    queryFn: () => listRecaptureGaps({ limit: 500 }),
    staleTime: 60_000,
  });

  // ── Derived statistics ────────────────────────────────────────────────────

  const stats = useMemo(() => {
    const daysLeft = daysRemainingInYear(year);
    const open = gaps.filter((g) => g.status === "open");
    const recaptured = gaps.filter((g) => g.status === "recaptured");
    const atRisk = open.filter(() => daysLeft <= AT_RISK_DAYS_THRESHOLD);
    const revenue = open.reduce(
      (sum, g) => sum + (g.revenue_impact ?? REVENUE_PER_GAP),
      0
    );
    return {
      total: gaps.length,
      open: open.length,
      recaptured: recaptured.length,
      dismissed: gaps.filter((g) => g.status === "dismissed").length,
      atRisk: atRisk.length,
      revenue,
    };
  }, [gaps, year]);

  const tabCounts: Record<StatusFilter, number> = useMemo(
    () => ({
      all: stats.total,
      open: stats.open,
      recaptured: stats.recaptured,
      dismissed: stats.dismissed,
    }),
    [stats]
  );

  // ── Filtered + searched list ──────────────────────────────────────────────

  const filtered = useMemo(() => {
    let list = gaps;
    if (statusFilter !== "all") {
      list = list.filter((g) => g.status === statusFilter);
    }
    if (search.trim()) {
      const q = search.toLowerCase();
      list = list.filter(
        (g) =>
          (g.patient_name ?? "").toLowerCase().includes(q) ||
          (g.hcc_code ?? "").toLowerCase().includes(q) ||
          (g.hcc_description ?? "").toLowerCase().includes(q) ||
          (g.icd10_code ?? "").toLowerCase().includes(q)
      );
    }
    // Open gaps first, then sort by revenue impact descending
    return [...list].sort((a, b) => {
      if (a.status === "open" && b.status !== "open") return -1;
      if (b.status === "open" && a.status !== "open") return 1;
      return (b.revenue_impact ?? REVENUE_PER_GAP) - (a.revenue_impact ?? REVENUE_PER_GAP);
    });
  }, [gaps, statusFilter, search]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const paged = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  // Reset page on filter/search/year change
  React.useEffect(() => {
    setPage(1);
  }, [search, statusFilter, year]);

  // ── CSV export ────────────────────────────────────────────────────────────

  function exportCSV() {
    if (!filtered.length) return;
    downloadCSV(
      filtered.map((g) => ({
        Patient: g.patient_name ?? g.patient_id,
        "HCC Code": g.hcc_code,
        Condition: g.hcc_description ?? "",
        "ICD-10": g.icd10_code ?? "",
        Status: statusLabel(g.status),
        "Prior Year": g.current_year ?? "",
        "Revenue Impact": g.revenue_impact ?? REVENUE_PER_GAP,
      })),
      "recapture-gaps"
    );
  }

  // ── Loading state ─────────────────────────────────────────────────────────

  if (isLoading) {
    return (
      <div className="p-6">
        <PageHeader
          title="Recapture Gaps"
          subtitle="Loading recapture opportunities..."
          icon={<RefreshCw size={22} />}
        />
        <div className="premium-card shimmer h-12 rounded-lg mb-6" />
        <div className="premium-card shimmer h-72 rounded-lg" />
      </div>
    );
  }

  // ── Error state ───────────────────────────────────────────────────────────

  if (isError) {
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

  const daysLeft = daysRemainingInYear(year);

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
                aria-label="Payment year"
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

      {/* Summary pill bar */}
      <div className="animate-fade-in stagger-1">
        <SummaryPillBar
          total={stats.total}
          open={stats.open}
          recaptured={stats.recaptured}
          atRisk={stats.atRisk}
          revenue={stats.revenue}
        />
      </div>

      {/* Main gap table */}
      <div className="premium-card animate-slide-up stagger-2 p-6 mb-6">
        {/* Table toolbar */}
        <div className="flex items-center justify-between flex-wrap gap-3 mb-4">
          <StatusTabs
            active={statusFilter}
            onChange={setStatusFilter}
            counts={tabCounts}
          />

          {/* Search */}
          <div className="relative">
            <Search
              size={14}
              aria-hidden="true"
              className="absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground pointer-events-none"
            />
            <input
              type="text"
              placeholder="Search by patient, HCC, or condition..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              aria-label="Search gaps by patient name, HCC code, or condition"
              data-testid="recapture-search"
              className="pl-8 pr-3 py-1.5 rounded-full border border-border text-sm text-foreground bg-card w-64 focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 transition-all"
            />
          </div>
        </div>

        {/* Table or empty */}
        {filtered.length === 0 ? (
          <EmptyState
            state="filtered-out"
            icon={<CalendarClock size={24} />}
            title="No recapture gaps found"
            description={
              search.trim()
                ? "No gaps match your search. Try a different term."
                : statusFilter !== "all"
                ? `No ${statusFilter} gaps for the selected year.`
                : "All chronic conditions have been recaptured for the selected year."
            }
            cta={
              search.trim()
                ? { label: "Clear search", onClick: () => setSearch("") }
                : statusFilter !== "all"
                ? { label: "Show all", onClick: () => setStatusFilter("all") }
                : undefined
            }
          />
        ) : (
          <>
            <div className="rounded-lg border border-border overflow-x-auto">
              <Table aria-label="Recapture gaps worklist">
                <TableHeader>
                  <TableRow className="bg-muted/40 hover:bg-muted/40">
                    <TableHead className="text-xs font-semibold uppercase tracking-wide text-muted-foreground pl-4">
                      HCC / Condition
                    </TableHead>
                    <TableHead className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                      Patient
                    </TableHead>
                    <TableHead className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                      Prior Year
                    </TableHead>
                    <TableHead className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                      Days Remaining
                    </TableHead>
                    <TableHead className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                      Status
                    </TableHead>
                    <TableHead className="text-xs font-semibold uppercase tracking-wide text-muted-foreground text-right pr-4">
                      Revenue Impact
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {paged.map((g, i) => {
                    const urgency = urgencyClasses(daysLeft);
                    return (
                      <TableRow
                        key={`${g.id}-${i}`}
                        tabIndex={0}
                        aria-label={`${g.patient_name ?? "Patient"} — ${g.hcc_description ?? g.hcc_code}, ${statusLabel(g.status)}`}
                        onClick={() => router.push(`/patients/${g.patient_id}`)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" || e.key === " ") {
                            e.preventDefault();
                            router.push(`/patients/${g.patient_id}`);
                          }
                        }}
                        className="cursor-pointer transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary"
                        style={{
                          background: i % 2 !== 0 ? "hsl(var(--muted)/0.3)" : undefined,
                        }}
                      >
                        {/* HCC + Condition */}
                        <TableCell className="pl-4">
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className="font-mono text-xs font-bold px-1.5 py-0.5 rounded bg-primary/10 text-primary tabular-nums">
                              {g.hcc_code}
                            </span>
                            <span className="text-sm font-medium text-foreground">
                              {g.hcc_description ?? g.icd10_code ?? "—"}
                            </span>
                          </div>
                          {g.icd10_code && (
                            <span className="mt-0.5 text-xs text-muted-foreground font-mono">
                              {g.icd10_code}
                            </span>
                          )}
                        </TableCell>

                        {/* Patient */}
                        <TableCell>
                          <span
                            className="text-sm font-semibold text-primary cursor-pointer"
                            data-testid={`patient-name-${g.patient_id}`}
                          >
                            {g.patient_name ?? `Patient #${g.patient_id}`}
                          </span>
                        </TableCell>

                        {/* Prior Year badge */}
                        <TableCell>
                          {g.current_year ? (
                            <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold bg-muted text-muted-foreground tabular-nums">
                              {g.current_year}
                            </span>
                          ) : (
                            <span className="text-muted-foreground text-xs">—</span>
                          )}
                        </TableCell>

                        {/* Days Remaining — only meaningful for open gaps */}
                        <TableCell>
                          {g.status === "open" ? (
                            <span
                              className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-semibold ${urgency.pill}`}
                              aria-label={`${daysLeft} days remaining in payment year`}
                            >
                              <span
                                className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${urgency.dot}`}
                                aria-hidden="true"
                              />
                              {urgency.label}
                            </span>
                          ) : (
                            <span className="text-muted-foreground text-xs">—</span>
                          )}
                        </TableCell>

                        {/* Status badge */}
                        <TableCell>
                          <span
                            className={statusBadgeClasses(g.status)}
                            data-testid={`status-badge-${g.id}`}
                          >
                            {statusLabel(g.status)}
                          </span>
                        </TableCell>

                        {/* Revenue Impact */}
                        <TableCell className="pr-4 text-right">
                          <span className="tabular-nums font-bold text-sm text-foreground">
                            {formatCurrency(g.revenue_impact ?? REVENUE_PER_GAP)}
                          </span>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>

            {/* Pagination */}
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

      {/* Feature-flagged secondary sections — lazy-loaded (~60 kB deferred) */}
      <RecaptureFeatureSections year={year} />

      {/* Action Panel */}
      <div className="premium-card animate-slide-up stagger-6 bg-gradient-to-br from-muted to-card p-6 flex items-center justify-between flex-wrap gap-4">
        <div>
          <p className="m-0 text-sm font-semibold text-foreground">
            Schedule Wellness Visits
          </p>
          <p className="mt-1 mb-0 text-xs text-muted-foreground">
            Prioritize patients with open recapture gaps for annual wellness visits to
            ensure chronic conditions are documented before year-end.
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
