"use client";

import { ErrorBoundary } from "@/components/error-boundary";
import React, { useState, useMemo, useCallback, useEffect } from "react";
import { HelpButton } from "@/components/HelpPanel";
import { usePaymentYear, useIsHistoricalPY, PAYMENT_YEARS } from "@/contexts/payment-year-context";
import { useTenantBranding } from "@/lib/useTenantBranding";
import dynamic from "next/dynamic";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { tokens } from "@/styles/tokens";
import { PageHeader } from "@/components/ui/page-header";
import { BarChart2 } from "lucide-react";

const ReportsHeavyTabs = dynamic(() => import("./ReportsHeavyTabs"), {
  ssr: false,
  loading: () => (
    <div className="flex flex-col items-center justify-center py-16 text-muted-foreground text-[13px]">
      <div
        className="w-8 h-8 rounded-full border-[3px] border-slate-200 mb-3"
        style={{ borderTopColor: tokens.primary, animation: "spin 0.8s linear infinite" }}
      />
      Loading...
    </div>
  ),
});
import {
  getRevenueOpportunity,
  getPatientScorecard,
  getHccDistribution,
  getRecaptureGapsReport,
  getDataCompleteness,
  useMetricFormula,
  type RevenueOpportunityReport,
  type PatientScorecardRow,
  type HccDistributionRow,
} from "@/lib/api";
import { MetricMetaTooltip } from "@/components/ui/metric-meta-tooltip";
import { Clock, FileDown, Printer, Lock } from "lucide-react";
import { downloadCSV } from "@/lib/csv-export";
import { HistoricalPYBanner } from "@/components/HistoricalPYBanner";
import { ChartExportMenu } from "@/components/ui/chart-export-menu";
import { DateRangePicker, presetToDates, type DateRange } from "@/components/charts/DateRangePicker";

// ── Shared types ──────────────────────────────────────────────────────────────
type QueryResult<T = unknown> = { data?: T; isLoading?: boolean; isError?: boolean; refetch?: () => void };
type PatientRow = PatientScorecardRow;
type GapRow = { patient_id?: number | string; pid?: number | string; patient_name?: string; name?: string; last_name?: string; first_name?: string; condition?: string; description?: string; icd10_code?: string; icd10?: string; icd_code?: string; hcc_code?: string; hcc?: string; onset_date?: string; last_coded?: string; date?: string };
type DataCountBlock = { count?: number; total?: number };
type DataQualityPayload = {
  completeness_score?: number;
  overall_score?: number;
  billing_count?: number;
  billing_total?: number;
  billing?: DataCountBlock;
  problems_count?: number;
  problems_total?: number;
  problems?: DataCountBlock;
  notes_count?: number;
  notes_total?: number;
  clinical_notes?: DataCountBlock;
  vitals_count?: number;
  vitals_total?: number;
  vitals?: DataCountBlock;
  labs_count?: number;
  labs_total?: number;
  labs?: DataCountBlock;
  immunizations_count?: number;
  immunizations_total?: number;
  immunizations?: DataCountBlock;
  insurance_count?: number;
  insurance_total?: number;
  insurance?: DataCountBlock;
};

// ── Constants ─────────────────────────────────────────────────────────────────
const REVENUE_PER_RAF = 11_015.04;
const YEARS = Array.from({ length: 3 }, (_, i) => new Date().getFullYear() - i);
const CURRENT_PAYMENT_YEAR = new Date().getFullYear();
type ReportGroup = "Clinical" | "Analytics";

const CLINICAL_TABS = [
  "Revenue",
  "Patient Scorecard",
  "HCC Distribution",
  "Provider Performance",
  "Quality",
] as const;

const ANALYTICS_TABS = [
  "Longitudinal Trends",
  "CMS Benchmarks",
  "Settlement Projection",
  "Scheduled Reports",
  "Recapture Gaps",
] as const;

type ClinicalTab = (typeof CLINICAL_TABS)[number];
type AnalyticsTab = (typeof ANALYTICS_TABS)[number];
type TabKey = ClinicalTab | AnalyticsTab;

const GROUP_TABS: Record<ReportGroup, readonly TabKey[]> = {
  Clinical: CLINICAL_TABS,
  Analytics: ANALYTICS_TABS,
};

// ── CMS National Average RAF by year (from official CMS publications) ─────────
const CMS_NATIONAL_AVG: { [year: number]: number } = { 2024: 1.08, 2025: 1.10, 2026: 1.12 };
const getCmsAvg = (yr: number) => CMS_NATIONAL_AVG[yr] ?? CMS_NATIONAL_AVG[Math.max(...Object.keys(CMS_NATIONAL_AVG).map(Number))];

// ── Colors — mapped to design tokens ─────────────────────────────────────────
const C = {
  bg: tokens.slate50,
  card: tokens.white,
  border: tokens.slate200,
  borderLight: tokens.slate100,
  text: tokens.slate900,
  textMuted: tokens.slate500,
  textSub: tokens.slate400,
  primary: tokens.primary,
  primaryLight: tokens.primarySoft,
  emerald: tokens.success,
  emeraldLight: tokens.emerald100,
  emeraldDark: tokens.emerald800,
  amber: tokens.warningStrong,
  amberLight: tokens.warningSoft,
  amberDark: tokens.warningText,
  red: tokens.riskHigh,
  redLight: tokens.riskHighSoft,
  redDark: tokens.danger,
  blue: tokens.infoBlue,
  blueLight: tokens.primarySoft,
  blueDark: tokens.primaryDark,
  violet: tokens.accentPurple,
  gray100: tokens.slate100,
  gray200: tokens.slate200,
  gray300: tokens.slate300,
  gray400: tokens.slate400,
  gray600: tokens.slate600,
  white: tokens.white,
};

// ── Helpers ───────────────────────────────────────────────────────────────────
function fmt$(v: number | null | undefined): string {
  if (v == null) return "—";
  return "$" + Math.round(v).toLocaleString("en-US");
}

function fmtN(v: number | null | undefined, d = 2): string {
  if (v == null) return "—";
  return (v ?? 0).toFixed(d);
}

function gapBadgeClass(gap: number | null): string {
  const base = "inline-block px-2.5 py-[2px] rounded-full text-xs font-semibold";
  if (gap == null || gap < 0.2) return `${base} bg-emerald-100 text-emerald-800`;
  if (gap < 0.5) return `${base} bg-amber-100 text-amber-800`;
  return `${base} bg-red-100 text-red-700`;
}

function initials(name: string): string {
  return name.split(/[\s,]+/).filter(Boolean).slice(0, 2).map((w) => w[0]?.toUpperCase() ?? "").join("");
}

const avatarColors = [tokens.primary, tokens.accentPurple, tokens.riskLow, tokens.riskHigh, tokens.riskMedium, tokens.infoBlue, tokens.riskMedium, tokens.primaryDark];

// ── Sort hook ─────────────────────────────────────────────────────────────────
type SortDir = "asc" | "desc";
function useSortable<T>(data: T[], defaultKey: keyof T, defaultDir: SortDir = "desc") {
  const [sortKey, setSortKey] = useState<keyof T>(defaultKey);
  const [sortDir, setSortDir] = useState<SortDir>(defaultDir);
  const toggle = useCallback(
    (key: keyof T) => {
      if (sortKey === key) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
      else { setSortKey(key); setSortDir("desc"); }
    },
    [sortKey],
  );
  const sorted = useMemo(() => {
    return [...data].sort((a, b) => {
      const av = a[sortKey] ?? "";
      const bv = b[sortKey] ?? "";
      if (av < bv) return sortDir === "asc" ? -1 : 1;
      if (av > bv) return sortDir === "asc" ? 1 : -1;
      return 0;
    });
  }, [data, sortKey, sortDir]);
  return { sorted, toggle, sortKey, sortDir };
}

// ── Tab content fade wrapper ────────────────────────────────────────────────
function TabFade({ children, tabKey }: { children: React.ReactNode; tabKey: string }) {
  const [visible, setVisible] = useState(false);
  const [prevKey, setPrevKey] = useState(tabKey);

  if (prevKey !== tabKey) {
    setPrevKey(tabKey);
    setVisible(false);
  }

  useEffect(() => {
    if (!visible) {
      const raf = requestAnimationFrame(() => setVisible(true));
      return () => cancelAnimationFrame(raf);
    }
  }, [visible]);

  return (
    <div
      style={{
        opacity: visible ? 1 : 0,
        transform: visible ? "translateY(0)" : "translateY(8px)",
        transition: "opacity 0.3s ease, transform 0.3s ease",
      }}
    >
      {children}
    </div>
  );
}

// ── Section header ────────────────────────────────────────────────────────────
function SectionHeader({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <div className="px-5 py-4 border-b border-border">
      <h3 className="text-sm font-semibold text-foreground m-0">{title}</h3>
      {subtitle && <p className="mt-0.5 mb-0 text-xs text-muted-foreground">{subtitle}</p>}
    </div>
  );
}

// ── Loading / Error ───────────────────────────────────────────────────────────
function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-20 text-muted-foreground">
      <div
        className="w-9 h-9 rounded-full border-[3px] border-slate-200"
        style={{ borderTopColor: C.primary, animation: "spin 0.8s linear infinite" }}
      />
      <style>{`@keyframes spin { to { transform: rotate(360deg) } }`}</style>
      <p className="mt-3.5 text-[13px] font-medium">{label ?? "Loading data..."}</p>
      <div className="shimmer w-[200px] h-2 rounded mt-3" />
    </div>
  );
}

function ErrorBox({ message, onRetry }: { message?: string; onRetry?: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center py-20 text-red-600">
      <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <circle cx="12" cy="12" r="10" /><line x1="12" y1="8" x2="12" y2="12" /><line x1="12" y1="16" x2="12.01" y2="16" />
      </svg>
      <p className="mt-3 text-[13px]">{message ?? "Failed to load data"}</p>
      {onRetry && (
        <button
          onClick={onRetry}
          className="mt-3 px-5 py-2 rounded-lg text-[13px] font-semibold cursor-pointer bg-card border border-red-400 text-red-600"
        >
          Retry
        </button>
      )}
    </div>
  );
}

// ── Sort Arrow Icon ───────────────────────────────────────────────────────────
function SortArrow({ active, dir }: { active: boolean; dir: SortDir }) {
  if (!active) return <span className="ml-1 text-[10px] opacity-30">⇅</span>;
  return <span className="ml-1 text-[10px]">{dir === "asc" ? "↑" : "↓"}</span>;
}

// ── Select control shared style ───────────────────────────────────────────────
const selectCls = "px-3.5 pr-8 py-2 text-[14px] font-semibold border border-border rounded-lg bg-card text-foreground cursor-pointer appearance-none";

// ── Shared table class helpers ────────────────────────────────────────────────
const thCls = "px-4 py-3 text-[11px] font-bold uppercase tracking-[0.06em] text-muted-foreground border-b border-border bg-muted/50 whitespace-nowrap cursor-pointer select-none";
const tdCls = "px-4 py-3 text-[13px] border-b border-border/60 whitespace-nowrap";

// ── Row helper for alternating stripes + hover ──────────────────────────────
function rowProps(index: number) {
  return {
    style: {
      cursor: "pointer" as const,
      transition: "background-color 0.15s ease",
      background: index % 2 === 1 ? tokens.slate50 : "transparent",
    },
    onMouseEnter: (e: React.MouseEvent<HTMLTableRowElement>) => {
      e.currentTarget.style.background = tokens.slate50;
    },
    onMouseLeave: (e: React.MouseEvent<HTMLTableRowElement>) => {
      e.currentTarget.style.background = index % 2 === 1 ? tokens.slate50 : "transparent";
    },
  };
}

// ══════════════════════════════════════════════════════════════════════════════
// PAGE COMPONENT
// ══════════════════════════════════════════════════════════════════════════════
export default function ReportsPage() {
  const router = useRouter();
  const { branding } = useTenantBranding();
  const [year, setYear] = useState(new Date().getFullYear());
  const { paymentYear, setPaymentYear } = usePaymentYear();
  const isHistoricalPY = useIsHistoricalPY();
  const [activeGroup, setActiveGroup] = useState<ReportGroup>("Clinical");
  const [activeTab, setActiveTab] = useState<TabKey>("Revenue");

  const handleGroupChange = (g: ReportGroup) => {
    setActiveGroup(g);
    setActiveTab(GROUP_TABS[g][0]);
  };

  const [dateRange, setDateRange] = useState<DateRange>(() => {
    const { from, to } = presetToDates("30d");
    return { preset: "30d", from, to };
  });

  // ── Data Queries ──────────────────────────────────────────────────────────
  const revenue = useQuery({ queryKey: ["revenue", year, paymentYear], queryFn: () => getRevenueOpportunity(year, paymentYear), staleTime: 60_000, retry: 1, gcTime: 0 });
  const scorecard = useQuery({ queryKey: ["scorecard", year, paymentYear], queryFn: () => getPatientScorecard(year, paymentYear), staleTime: 60_000, retry: 1, gcTime: 0 });
  const hccDist = useQuery({ queryKey: ["hcc-dist", year, paymentYear], queryFn: () => getHccDistribution(year, paymentYear), staleTime: 60_000, retry: 1 });
  const recapture = useQuery({ queryKey: ["recapture", year, paymentYear], queryFn: () => getRecaptureGapsReport(year, paymentYear), staleTime: 60_000, retry: 1 });
  const dataQuality = useQuery({ queryKey: ["data-quality"], queryFn: () => getDataCompleteness(), staleTime: 60_000, retry: 1 });

  // Page-level loading state: true while any primary query is loading
  const isPageLoading = revenue.isLoading || scorecard.isLoading;

  const handlePrint = () => {
    const printHeader = document.getElementById("report-print-header");
    if (printHeader) printHeader.style.display = "block";
    window.print();
    if (printHeader) printHeader.style.display = "none";
  };

  return (
    <div
      className="rci-page-pad-desktop min-h-screen bg-background p-4 sm:p-6 pb-14 font-sans text-foreground"
      {...(isHistoricalPY ? { "data-read-only": "true" } : {})}
    >
      {/* ── Print-only header ─────────────────────────────────────────────── */}
      <div
        id="report-print-header"
        className="print-header hidden border-b-2 border-foreground pb-3 mb-5"
      >
        <div className="text-[10px] text-muted-foreground mb-1">{branding.display_name}</div>
        <div className="text-lg font-bold">Analytics &amp; Reports — {activeTab}</div>
        <div className="text-[11px] text-muted-foreground mt-1">
          Year: {year} &nbsp;|&nbsp; Printed:{" "}
          {new Date().toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric" })}
        </div>
      </div>

      {/* ── Page Header ──────────────────────────────────────────────────── */}
      <PageHeader
        title={<span className="gradient-text">Analytics &amp; Reports</span>}
        subtitle="Population health intelligence and revenue analytics"
        icon={<BarChart2 size={20} />}
        actions={
          <div className="flex items-center gap-2.5 flex-wrap">
            <label className="text-[12px] font-semibold text-muted-foreground uppercase tracking-[0.05em]">
              Year
            </label>
            <select
              value={year}
              onChange={(e) => setYear(Number(e.target.value))}
              aria-label="Select reporting year"
              className={selectCls}
              style={{
                backgroundImage: `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%2394A3B8' stroke-width='2'%3E%3Cpath d='M6 9l6 6 6-6'/%3E%3C/svg%3E")`,
                backgroundRepeat: "no-repeat",
                backgroundPosition: "right 10px center",
              }}
            >
              {YEARS.map((y) => (
                <option key={y} value={y}>{y}</option>
              ))}
            </select>

            <label className="text-[12px] font-semibold text-muted-foreground uppercase tracking-[0.05em]">
              Payment Year
            </label>
            <select
              value={paymentYear}
              onChange={(e) => setPaymentYear(Number(e.target.value))}
              aria-label="As-of payment year"
              className="px-3.5 pr-8 py-2 text-[14px] font-semibold border rounded-lg cursor-pointer appearance-none"
              style={{
                borderColor: isHistoricalPY ? C.amber : C.border,
                background: isHistoricalPY ? C.amberLight : C.white,
                color: isHistoricalPY ? C.amberDark : C.text,
                backgroundImage: `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%2394A3B8' stroke-width='2'%3E%3Cpath d='M6 9l6 6 6-6'/%3E%3C/svg%3E")`,
                backgroundRepeat: "no-repeat",
                backgroundPosition: "right 10px center",
              }}
            >
              {PAYMENT_YEARS.map((py) => (
                <option key={py} value={py}>
                  PY{py}{py === CURRENT_PAYMENT_YEAR ? " (current)" : ""}
                </option>
              ))}
            </select>

            <DateRangePicker value={dateRange} onChange={setDateRange} className="no-print" />

            <button
              onClick={handlePrint}
              className="no-print inline-flex items-center gap-1.5 px-4 py-2 text-[13px] font-semibold border border-border rounded-lg bg-card text-muted-foreground cursor-pointer hover:bg-muted/50 transition-colors"
              aria-label="Print report"
            >
              <Printer size={15} /> Print Report
            </button>

            <HelpButton />
          </div>
        }
      />

      {/* ── Loading skeleton (page-level) ─────────────────────────────── */}
      {isPageLoading && (
        <div className="grid grid-cols-3 gap-5 mb-8" aria-busy="true" aria-label="Loading report data">
          {[0, 1, 2].map((i) => (
            <div key={i} className="shimmer h-28 rounded-xl" />
          ))}
        </div>
      )}

      {/* ── Historical view banner ────────────────────────────────────── */}
      <HistoricalPYBanner paymentYear={paymentYear} />

      {/* ── Group switcher: Clinical / Analytics ────────────────────── */}
      <div
        role="group"
        aria-label="Report group"
        className="inline-flex gap-1 mb-4 p-1 bg-muted rounded-[10px]"
      >
        {(["Clinical", "Analytics"] as ReportGroup[]).map((g) => {
          const isActive = activeGroup === g;
          return (
            <button
              key={g}
              type="button"
              aria-pressed={isActive}
              onClick={() => handleGroupChange(g)}
              className={[
                "px-[22px] py-[7px] text-[13px] rounded-[7px] border-none cursor-pointer transition-all duration-200 tracking-[-0.01em]",
                isActive
                  ? "font-bold text-white bg-primary shadow-sm"
                  : "font-medium text-muted-foreground bg-transparent",
              ].join(" ")}
            >
              {g}
            </button>
          );
        })}
      </div>

      {/* ── Tab Bar — underline style ─────────────────────────────────── */}
      <div
        role="tablist"
        aria-label={`${activeGroup} report tabs`}
        className="flex gap-0 mb-8 border-b border-border flex-wrap"
      >
        {GROUP_TABS[activeGroup].map((tab) => {
          const isActive = activeTab === tab;
          return (
            <button
              key={tab}
              role="tab"
              aria-selected={isActive}
              onClick={() => setActiveTab(tab)}
              className={[
                "relative px-4 py-2.5 text-[13px] border-none bg-transparent cursor-pointer transition-colors duration-150 tracking-[-0.01em] whitespace-nowrap",
                isActive
                  ? "font-semibold text-teal-600 border-b-2 border-teal-600 -mb-px"
                  : "font-medium text-muted-foreground hover:text-foreground",
              ].join(" ")}
            >
              {tab}
            </button>
          );
        })}
      </div>

      {/* ── Tab Content ──────────────────────────────────────────────────── */}
      <TabFade tabKey={activeTab}>
        {activeTab === "Revenue" && (
          <RevenueTab revenue={revenue} scorecard={scorecard} router={router} paymentYear={paymentYear} isHistoricalPY={isHistoricalPY} />
        )}
        {activeTab === "Patient Scorecard" && (
          <ScorecardTab scorecard={scorecard} router={router} isHistoricalPY={isHistoricalPY} />
        )}
        {activeTab === "HCC Distribution" && (
          <HccTab hccDist={hccDist} isHistoricalPY={isHistoricalPY} />
        )}
        {activeTab === "Recapture Gaps" && (
          <RecaptureTab recapture={recapture} router={router} isHistoricalPY={isHistoricalPY} />
        )}
        {activeTab === "Quality" && (
          <DataQualityTab dataQuality={dataQuality} />
        )}
        {activeTab === "Provider Performance" && (
          <div className="flex flex-col items-center justify-center py-12 px-6 text-[14px] text-muted-foreground rounded-xl border border-dashed border-border">
            <Lock size={20} className="mb-2.5 opacity-40" />
            <div className="font-semibold mb-1.5">Provider Performance</div>
            <div className="text-[13px]">Provider-level performance benchmarks are coming soon.</div>
          </div>
        )}
        {(
          activeTab === "Longitudinal Trends" ||
          activeTab === "CMS Benchmarks" ||
          activeTab === "Settlement Projection" ||
          activeTab === "Scheduled Reports"
        ) && (
          <ReportsHeavyTabs
            activeTab={activeTab as "Longitudinal Trends" | "CMS Benchmarks" | "Settlement Projection" | "Scheduled Reports"}
            revenue={revenue}
          />
        )}
      </TabFade>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// TAB 1: REVENUE OPPORTUNITY
// ══════════════════════════════════════════════════════════════════════════════
function RevenueTab({ revenue, scorecard, router, paymentYear, isHistoricalPY }: {
  revenue: QueryResult<RevenueOpportunityReport>;
  scorecard: QueryResult<PatientRow[]>;
  router: { push: (path: string) => void };
  paymentYear?: number;
  isHistoricalPY?: boolean;
}) {
  const r = revenue.data;
  const patients: PatientRow[] = scorecard.data ?? [];
  const revenueTableRef = React.useRef<HTMLDivElement | null>(null);
  const revMeta = useMetricFormula(r as Record<string, unknown> | null | undefined, "estimated_annual_revenue") ?? r?._meta ?? null;

  const { top25, patientsWithGaps } = useMemo(() => {
    const allWithGaps = [...patients].filter((p) => (p.gap ?? 0) > 0);
    const patientsWithGaps = allWithGaps.length;
    const top25 = allWithGaps
      .sort((a, b) => (b.revenue_opportunity ?? 0) - (a.revenue_opportunity ?? 0))
      .slice(0, 25);
    return { top25, patientsWithGaps };
  }, [patients]);

  if (revenue.isLoading || scorecard.isLoading) return <Spinner label="Loading revenue data..." />;
  if (revenue.isError || scorecard.isError) return (
    <ErrorBox
      message={revenue.isError ? "Failed to load revenue data. The server may be slow or unavailable." : "Failed to load patient scorecard."}
      onRetry={() => { revenue.refetch?.(); scorecard.refetch?.(); }}
    />
  );

  const totalRevenue = r?.estimated_annual_revenue ?? 0;
  const totalGap = r?.total_gap ?? 0;
  const isEmpty = !r || (r.total_patients_analyzed === 0 && totalRevenue === 0 && totalGap === 0 && top25.length === 0);

  if (isEmpty) {
    return (
      <div className="flex flex-col items-center justify-center py-20 px-6 text-center">
        <div className="w-14 h-14 rounded-[14px] flex items-center justify-center mb-5 bg-blue-50">
          <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke={C.primary} strokeWidth="1.8">
            <line x1="12" y1="1" x2="12" y2="23" /><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6" />
          </svg>
        </div>
        <h3 className="text-[18px] font-bold mb-2 text-foreground">No revenue data available</h3>
        <p className="text-[14px] text-muted-foreground max-w-[400px] mb-7 leading-relaxed">
          No patients have been analyzed for payment year {paymentYear}. Connect your EMR to start analyzing RAF gaps, or load demo data to preview the reports.
        </p>
        <div className="flex gap-3 flex-wrap justify-center">
          <button
            onClick={() => router.push("/connect")}
            className="px-[22px] py-2.5 rounded-[10px] border-none text-[14px] font-semibold cursor-pointer text-white bg-primary"
          >
            Connect EMR
          </button>
          <button
            onClick={() => router.push("/demo")}
            className="px-[22px] py-2.5 rounded-[10px] text-[14px] font-semibold cursor-pointer border border-border bg-card text-foreground"
          >
            Try Demo Data
          </button>
        </div>
      </div>
    );
  }

  return (
    <div>
      {/* KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5 mb-8">
        {/* Revenue Card */}
        <div className="border border-border rounded-xl p-6 bg-card border-l-4 border-l-emerald-500">
          <div className="flex justify-between items-start">
            <div>
              <p
                data-testid="revenue-at-risk-label"
                className="text-[11px] font-semibold uppercase tracking-[0.06em] text-muted-foreground m-0 flex items-center gap-1"
              >
                Estimated Annual Revenue
                {revMeta && <MetricMetaTooltip meta={revMeta} side="bottom" />}
              </p>
              <p
                data-testid="revenue-at-risk-value"
                className="text-[32px] font-bold mt-2 mb-0 tracking-[-0.02em] text-emerald-800"
              >
                {fmt$(totalRevenue)}
              </p>
              <p className="text-[12px] mt-1 mb-0 text-slate-400">
                @ ${REVENUE_PER_RAF.toLocaleString()} / RAF point
              </p>
              {r?.last_computed_at && (() => {
                const d = new Date(r.last_computed_at);
                if (isNaN(d.getTime())) return null;
                const mins = Math.floor((Date.now() - d.getTime()) / 60_000);
                if (mins < 0) return null;
                const rel = mins < 1 ? "<1m" : mins < 60 ? `${mins}m` : mins < 1440 ? `${Math.floor(mins / 60)}h` : `${Math.floor(mins / 1440)}d`;
                return (
                  <span
                    data-testid="last-refreshed"
                    className="inline-flex items-center gap-1 text-[10px] text-muted-foreground mt-1"
                  >
                    <Clock size={11} aria-hidden />
                    Last refreshed {rel} ago
                  </span>
                );
              })()}
            </div>
            <div className="w-11 h-11 rounded-[10px] flex items-center justify-center flex-shrink-0 bg-emerald-100">
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke={C.emerald} strokeWidth="2">
                <line x1="12" y1="1" x2="12" y2="23" /><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6" />
              </svg>
            </div>
          </div>
        </div>

        {/* RAF Gap Card */}
        <div className="border border-border rounded-xl p-6 bg-card border-l-4 border-l-amber-400">
          <div className="flex justify-between items-start">
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-[0.06em] text-muted-foreground m-0">Total RAF Gap</p>
              <p className="text-[32px] font-bold mt-2 mb-0 tracking-[-0.02em] text-amber-800">
                {fmtN(totalGap)}
              </p>
              <p className="text-[12px] mt-1 mb-0 text-slate-400">Cumulative gap across population</p>
            </div>
            <div className="w-11 h-11 rounded-[10px] flex items-center justify-center flex-shrink-0 bg-amber-100">
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke={C.amber} strokeWidth="2">
                <path d="M22 12h-4l-3 9L9 3l-3 9H2" />
              </svg>
            </div>
          </div>
        </div>

        {/* Patients with Gaps Card */}
        <div className="border border-border rounded-xl p-6 bg-card border-l-4 border-l-blue-400">
          <div className="flex justify-between items-start">
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-[0.06em] text-muted-foreground m-0">Patients with Gaps</p>
              <p className="text-[32px] font-bold mt-2 mb-0 tracking-[-0.02em] text-blue-800">
                {patientsWithGaps}
              </p>
              <p className="text-[12px] mt-1 mb-0 text-slate-400">Of {r?.total_patients_analyzed ?? 0} analyzed</p>
            </div>
            <div className="w-11 h-11 rounded-[10px] flex items-center justify-center flex-shrink-0 bg-blue-50">
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke={C.blue} strokeWidth="2">
                <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" /><circle cx="9" cy="7" r="4" />
                <path d="M23 21v-2a4 4 0 0 0-3-3.87" /><path d="M16 3.13a4 4 0 0 1 0 7.75" />
              </svg>
            </div>
          </div>
        </div>
      </div>

      {/* Revenue Table */}
      <div ref={revenueTableRef} className="border border-border rounded-xl bg-card overflow-hidden">
        <div className="px-5 py-4 border-b border-border flex items-center justify-between flex-wrap gap-2.5">
          <div>
            <h3 className="text-sm font-semibold text-foreground m-0">Top 25 Revenue Opportunities</h3>
            <p className="mt-0.5 mb-0 text-xs text-muted-foreground">Patients sorted by estimated revenue opportunity</p>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => {
                if (isHistoricalPY || !top25.length) return;
                downloadCSV(top25.map((p) => ({
                  "Patient": p.name,
                  "Current RAF": p.billing_raf != null ? Number(p.billing_raf).toFixed(3) : "",
                  "Analyzed RAF": p.ai_raf != null ? Number(p.ai_raf).toFixed(3) : "",
                  "Gap": p.gap != null ? Number(p.gap).toFixed(3) : "",
                  "Revenue Opportunity": p.revenue_opportunity != null ? Math.round(p.revenue_opportunity) : "",
                  "HCCs Billing": p.hcc_count_billing,
                  "HCCs Analyzed": p.hcc_count_ai,
                })), "revenue-opportunities");
              }}
              disabled={isHistoricalPY}
              title={isHistoricalPY ? "Disabled in historical view" : undefined}
              data-testid="export-csv-revenue"
              className="inline-flex items-center gap-1.5 px-3.5 py-[7px] rounded-lg border-none text-[13px] font-semibold text-white cursor-pointer bg-primary disabled:opacity-60 disabled:cursor-not-allowed"
            >
              <FileDown size={14} />
              Export CSV
            </button>
            <ChartExportMenu
              filename="revenue-opportunities"
              csvData={top25.map((p) => ({
                "Patient": p.name,
                "Current RAF": p.billing_raf != null ? Number(p.billing_raf).toFixed(3) : "",
                "Analyzed RAF": p.ai_raf != null ? Number(p.ai_raf).toFixed(3) : "",
                "Gap": p.gap != null ? Number(p.gap).toFixed(3) : "",
                "Revenue Opportunity": p.revenue_opportunity != null ? Math.round(p.revenue_opportunity) : "",
                "HCCs Billing": p.hcc_count_billing,
                "HCCs Analyzed": p.hcc_count_ai,
              }) as Record<string, unknown>)}
              chartRef={revenueTableRef as React.RefObject<HTMLElement>}
              rawData={top25.map((p) => ({ patient: p.name, billing_raf: p.billing_raf, ai_raf: p.ai_raf, gap: p.gap, revenue: p.revenue_opportunity }) as Record<string, unknown>)}
            />
          </div>
        </div>
        <div className="overflow-x-auto">
          <table aria-label="Revenue opportunities" className="w-full border-collapse">
            <thead>
              <tr>
                <th className={`${thCls} w-12 text-center`}>#</th>
                <th className={thCls}>Patient</th>
                <th className={`${thCls} text-right`}>Current RAF</th>
                <th className={`${thCls} text-right`}>Analyzed RAF</th>
                <th className={`${thCls} text-center`}>Gap</th>
                <th className={`${thCls} text-right`}>Revenue</th>
                <th className={`${thCls} text-center`}>HCCs (Billing / Analyzed)</th>
                <th className={`${thCls} text-center`}>Evidence</th>
              </tr>
            </thead>
            <tbody>
              {top25.map((p, i) => (
                <tr
                  key={p.pid}
                  onClick={() => router.push(`/patients/${p.pid}?tab=raf`)}
                  title="Click to view supporting evidence in patient chart"
                  {...rowProps(i)}
                >
                  <td className={`${tdCls} text-center font-semibold text-muted-foreground`}>{i + 1}</td>
                  <td className={tdCls}>
                    <div className="flex items-center gap-2.5">
                      <div
                        className="w-[30px] h-[30px] rounded-full flex items-center justify-center text-[11px] font-semibold flex-shrink-0 text-white"
                        style={{ background: avatarColors[i % avatarColors.length] }}
                      >
                        {initials(p.name)}
                      </div>
                      <span className="font-medium">{p.name}</span>
                    </div>
                  </td>
                  <td className={`${tdCls} text-right font-mono`}>{fmtN(p.billing_raf)}</td>
                  <td className={`${tdCls} text-right font-mono`}>{fmtN(p.ai_raf)}</td>
                  <td className={`${tdCls} text-center`}>
                    <span className={gapBadgeClass(p.gap)}>{fmtN(p.gap)}</span>
                  </td>
                  <td className={`${tdCls} text-right font-semibold text-emerald-800`}>{fmt$(p.revenue_opportunity)}</td>
                  <td className={`${tdCls} text-center font-mono text-xs`}>
                    {p.hcc_count_billing} / {p.hcc_count_ai}
                  </td>
                  <td className={`${tdCls} text-center`}>
                    <span className="inline-flex items-center gap-1 px-2 py-[3px] rounded-[6px] text-[11px] font-semibold tracking-[0.02em] whitespace-nowrap bg-blue-50 text-primary">
                      Evidence →
                    </span>
                  </td>
                </tr>
              ))}
              {top25.length === 0 && (
                <tr>
                  <td colSpan={8} className={`${tdCls} text-center text-muted-foreground py-10`}>
                    No revenue gaps found for this year
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// TAB 2: PATIENT SCORECARD
// ══════════════════════════════════════════════════════════════════════════════
function ScorecardTab({ scorecard, router, isHistoricalPY }: {
  scorecard: QueryResult<PatientRow[]>;
  router: { push: (path: string) => void };
  isHistoricalPY?: boolean;
}) {
  const [search, setSearch] = useState("");
  const [limit, setLimit] = useState(100);
  const patients: PatientRow[] = scorecard.data ?? [];

  const { sorted, toggle, sortKey, sortDir } = useSortable<PatientRow>(patients, "gap", "desc");

  const filtered = useMemo(() => {
    if (!search.trim()) return sorted;
    const q = search.toLowerCase();
    return sorted.filter((p) => p.name?.toLowerCase().includes(q));
  }, [sorted, search]);

  const visible = filtered.slice(0, limit);

  if (scorecard.isLoading) return <Spinner label="Loading scorecard..." />;
  if (scorecard.isError) return <ErrorBox message="Failed to load scorecard" onRetry={scorecard.refetch} />;

  const colDefs: { key: string; label: string; align?: string }[] = [
    { key: "name", label: "Patient" },
    { key: "age", label: "Age", align: "center" },
    { key: "sex", label: "Sex", align: "center" },
    { key: "billing_raf", label: "Billing RAF", align: "right" },
    { key: "ai_raf", label: "Analyzed RAF", align: "right" },
    { key: "gap", label: "Gap", align: "right" },
    { key: "revenue_opportunity", label: "Revenue", align: "right" },
    { key: "hcc_count_billing", label: "HCCs (B)", align: "center" },
    { key: "hcc_count_ai", label: "HCCs (A)", align: "center" },
    { key: "analyzed", label: "Status", align: "center" },
  ];

  return (
    <div>
      {/* Search + Export */}
      <div className="mb-4 flex items-center gap-2.5">
        <div className="relative max-w-[340px] flex-1">
          <svg
            width="16" height="16" viewBox="0 0 24 24" fill="none"
            stroke={C.textSub} strokeWidth="2"
            className="absolute left-3 top-[11px]"
          >
            <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
          </svg>
          <input
            type="text"
            placeholder="Search patients..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full py-[9px] px-3.5 pl-9 text-[13px] border border-border rounded-lg bg-card"
          />
        </div>
        <button
          onClick={() => {
            if (isHistoricalPY || !filtered.length) return;
            downloadCSV(filtered.map((p) => ({
              "Patient": p.name,
              "Age": p.age,
              "Sex": p.sex,
              "Billing RAF": p.billing_raf != null ? Number(p.billing_raf).toFixed(2) : "",
              "Analyzed RAF": p.ai_raf != null ? Number(p.ai_raf).toFixed(2) : "",
              "Gap": p.gap != null ? Number(p.gap).toFixed(2) : "",
              "Revenue Opportunity": p.revenue_opportunity != null ? Math.round(p.revenue_opportunity) : "",
              "HCCs Billing": p.hcc_count_billing,
              "HCCs Analyzed": p.hcc_count_ai,
              "Status": p.analyzed ? "Analyzed" : "Pending",
            })), "patient-scorecard");
          }}
          disabled={isHistoricalPY}
          title={isHistoricalPY ? "Disabled in historical view" : undefined}
          data-testid="export-csv-patient-scorecard"
          className="inline-flex items-center gap-1.5 px-3.5 py-[9px] rounded-lg border-none text-[13px] font-semibold text-white flex-shrink-0 bg-primary disabled:opacity-60 disabled:cursor-not-allowed cursor-pointer"
        >
          <FileDown size={14} />
          Export CSV
        </button>
      </div>

      <div className="border border-border rounded-xl bg-card overflow-hidden">
        <div className="overflow-x-auto">
          <table aria-label="Patient scorecard" className="w-full border-collapse">
            <thead>
              <tr>
                {colDefs.map((col) => (
                  <th
                    key={col.key}
                    className={[thCls, col.align === "right" ? "text-right" : col.align === "center" ? "text-center" : "text-left"].join(" ")}
                    onClick={() => toggle(col.key as keyof PatientRow)}
                  >
                    <span className="inline-flex items-center">
                      {col.label}
                      <SortArrow active={sortKey === col.key} dir={sortDir} />
                    </span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {visible.map((p, i) => (
                <tr key={p.pid} onClick={() => router.push(`/patients/${p.pid}`)} {...rowProps(i)}>
                  <td className={tdCls}>
                    <div className="flex items-center gap-2">
                      <div
                        className="w-7 h-7 rounded-full flex items-center justify-center text-[10px] font-semibold flex-shrink-0 text-white"
                        style={{ background: avatarColors[i % avatarColors.length] }}
                      >
                        {initials(p.name)}
                      </div>
                      <span className="font-medium text-[13px]">{p.name}</span>
                    </div>
                  </td>
                  <td className={`${tdCls} text-center`}>{p.age ?? "—"}</td>
                  <td className={`${tdCls} text-center`}>{p.sex ?? "—"}</td>
                  <td className={`${tdCls} text-right font-mono`}>{fmtN(p.billing_raf)}</td>
                  <td className={`${tdCls} text-right font-mono`}>{fmtN(p.ai_raf)}</td>
                  <td className={`${tdCls} text-right`}>
                    <span className={gapBadgeClass(p.gap)}>{fmtN(p.gap)}</span>
                  </td>
                  <td className={`${tdCls} text-right font-semibold text-emerald-800`}>{fmt$(p.revenue_opportunity)}</td>
                  <td className={`${tdCls} text-center font-mono`}>{p.hcc_count_billing}</td>
                  <td className={`${tdCls} text-center font-mono`}>{p.hcc_count_ai}</td>
                  <td className={`${tdCls} text-center`}>
                    {p.analyzed ? (
                      <span className="text-emerald-600 font-semibold text-[15px]">✓</span>
                    ) : (
                      <span className="text-destructive font-semibold text-[15px]">✗</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {filtered.length > limit && (
          <div className="p-4 text-center border-t border-border">
            <button
              onClick={() => setLimit((l) => l + 100)}
              className="px-6 py-2 text-[13px] font-semibold rounded-lg border-none cursor-pointer text-primary bg-blue-50"
            >
              Load more ({filtered.length - limit} remaining)
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// TAB 3: HCC DISTRIBUTION
// ══════════════════════════════════════════════════════════════════════════════
function HccTab({ hccDist, isHistoricalPY }: {
  hccDist: QueryResult<HccDistributionRow[]>;
  isHistoricalPY?: boolean;
}) {
  const chartRef = React.useRef<HTMLDivElement | null>(null);
  if (hccDist.isLoading) return <Spinner label="Loading HCC distribution..." />;
  if (hccDist.isError) return <ErrorBox message="Failed to load HCC data" onRetry={hccDist.refetch} />;

  const data: Array<{ hcc_code: string; patient_count: number }> = hccDist.data ?? [];
  const top20 = [...data].sort((a, b) => b.patient_count - a.patient_count).slice(0, 20);
  const maxCount = top20[0]?.patient_count ?? 1;

  function barColor(rank: number): string {
    if (rank <= 3) return C.red;
    if (rank <= 8) return C.amber;
    return C.blue;
  }

  const csvData = top20.map((item, i) => ({
    "Rank": i + 1,
    "HCC Code": item.hcc_code,
    "Patient Count": item.patient_count,
  }));

  return (
    <div ref={chartRef} className="border border-border rounded-xl bg-card overflow-hidden">
      <div className="px-5 py-4 border-b border-border flex items-center justify-between flex-wrap gap-2.5">
        <div>
          <h3 className="text-sm font-semibold text-foreground m-0">HCC Distribution — Top 20 by Patient Count</h3>
          <p className="mt-0.5 mb-0 text-xs text-muted-foreground">Hierarchical Condition Categories across the population</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => { if (!isHistoricalPY && top20.length) downloadCSV(csvData, "hcc-distribution"); }}
            disabled={isHistoricalPY}
            title={isHistoricalPY ? "Disabled in historical view" : undefined}
            data-testid="export-csv-hcc-distribution"
            className="inline-flex items-center gap-1.5 px-3.5 py-[7px] rounded-lg border-none text-[13px] font-semibold text-white bg-primary disabled:opacity-60 disabled:cursor-not-allowed cursor-pointer"
          >
            <FileDown size={14} />
            Export CSV
          </button>
          <ChartExportMenu
            filename="hcc-distribution"
            csvData={csvData as Record<string, unknown>[]}
            chartRef={chartRef as React.RefObject<HTMLElement>}
            rawData={top20.map((item, i) => ({ rank: i + 1, hcc_code: item.hcc_code, patient_count: item.patient_count }) as Record<string, unknown>)}
          />
        </div>
      </div>
      <div className="p-5">
        {top20.map((item, i) => {
          const rank = i + 1;
          const pct = (item.patient_count / maxCount) * 100;
          return (
            <div key={item.hcc_code} className="flex items-center gap-3 mb-2.5">
              <span className="w-7 text-right text-[12px] font-semibold text-muted-foreground flex-shrink-0">{rank}</span>
              <span
                className="w-[70px] text-[12px] font-bold font-mono flex-shrink-0"
                style={{ color: barColor(rank) }}
              >
                {item.hcc_code}
              </span>
              <div className="flex-1 relative h-7 rounded-md overflow-hidden bg-muted">
                <div
                  className="h-full rounded-md opacity-80 transition-[width] duration-300 ease-in-out"
                  style={{ width: `${Math.max(pct, 2)}%`, background: barColor(rank) }}
                />
              </div>
              <span className="w-[50px] text-right text-[13px] font-semibold flex-shrink-0 text-foreground">
                {item.patient_count}
              </span>
            </div>
          );
        })}
        {top20.length === 0 && (
          <div className="flex flex-col items-center gap-2 py-7 px-4 text-center">
            <p className="text-[13px] font-semibold m-0 text-foreground">
              No HCC data — run analysis to populate this chart
            </p>
            <a
              href="/patients"
              className="inline-block px-4 py-[7px] rounded-lg text-[13px] font-semibold no-underline text-white bg-primary"
            >
              Go to Patients
            </a>
          </div>
        )}
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// TAB 4: RECAPTURE GAPS
// ══════════════════════════════════════════════════════════════════════════════
function RecaptureTab({ recapture, router, isHistoricalPY }: {
  recapture: QueryResult<unknown>;
  router: { push: (path: string) => void };
  isHistoricalPY?: boolean;
}) {
  if (recapture.isLoading) return <Spinner label="Loading recapture gaps..." />;
  if (recapture.isError) return <ErrorBox message="Failed to load recapture data" onRetry={recapture.refetch} />;

  const raw = recapture.data ?? {};
  const gaps: GapRow[] = (raw as { gaps?: GapRow[]; data?: GapRow[] }).gaps ?? (raw as { data?: GapRow[] }).data ?? (Array.isArray(raw) ? raw as GapRow[] : []);
  const totalGaps = gaps.length;
  const uniquePatients = new Set(gaps.map((g) => g.patient_id ?? g.pid)).size;

  const conditionMap = new Map<string, { condition: string; icd10: string; count: number }>();
  gaps.forEach((g) => {
    const key = g.icd10_code ?? g.icd10 ?? "Unknown";
    const existing = conditionMap.get(key);
    if (existing) {
      existing.count++;
    } else {
      conditionMap.set(key, { condition: g.condition ?? g.description ?? "Unknown", icd10: key, count: 1 });
    }
  });
  const topConditions = [...conditionMap.values()].sort((a, b) => b.count - a.count).slice(0, 15);

  return (
    <div>
      {/* KPI Row */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-5 mb-8">
        <div className="border border-border rounded-xl p-6 bg-card border-l-4 border-l-red-400">
          <p className="text-[11px] font-semibold uppercase tracking-[0.06em] text-muted-foreground m-0">Total Gaps</p>
          <p className="text-[32px] font-bold mt-2 mb-0 text-red-700">{totalGaps}</p>
        </div>
        <div className="border border-border rounded-xl p-6 bg-card border-l-4 border-l-amber-400">
          <p className="text-[11px] font-semibold uppercase tracking-[0.06em] text-muted-foreground m-0">Patients Affected</p>
          <p className="text-[32px] font-bold mt-2 mb-0 text-amber-800">{uniquePatients}</p>
        </div>
      </div>

      {/* Top Conditions Table */}
      <div className="border border-border rounded-xl bg-card overflow-hidden mb-6">
        <SectionHeader title="Top Conditions for Recapture" />
        <div className="overflow-x-auto">
          <table className="w-full border-collapse">
            <thead>
              <tr>
                <th className={thCls}>Condition</th>
                <th className={thCls}>ICD-10</th>
                <th className={`${thCls} text-right`}>Gap Count</th>
              </tr>
            </thead>
            <tbody>
              {topConditions.map((c, i) => (
                <tr key={c.icd10} style={{ background: i % 2 === 1 ? tokens.slate50 : "transparent" }}>
                  <td className={tdCls}>{c.condition}</td>
                  <td className={`${tdCls} font-mono font-semibold text-primary`}>{c.icd10}</td>
                  <td className={`${tdCls} text-right font-semibold`}>{c.count}</td>
                </tr>
              ))}
              {topConditions.length === 0 && (
                <tr>
                  <td colSpan={3} className={`${tdCls} text-center text-muted-foreground py-10`}>
                    No recapture gaps found
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Full Gaps Table */}
      <div className="border border-border rounded-xl bg-card overflow-hidden">
        <div className="px-5 py-4 border-b border-border flex items-center justify-between flex-wrap gap-2.5">
          <h3 className="text-sm font-semibold text-foreground m-0">All Recapture Gaps</h3>
          <button
            onClick={() => {
              if (isHistoricalPY || !gaps.length) return;
              downloadCSV(gaps.map((g) => ({
                "Patient ID": g.patient_id ?? g.pid ?? "",
                "Patient Name": [g.last_name, g.first_name].filter(Boolean).join(", ") || (g.patient_name ?? ""),
                "Condition": g.condition ?? g.description ?? "",
                "ICD-10": g.icd10_code ?? g.icd10 ?? g.icd_code ?? "",
                "HCC": g.hcc_code ?? g.hcc ?? "",
                "Last Coded": g.onset_date ?? g.last_coded ?? "",
              })), "recapture-gaps");
            }}
            disabled={isHistoricalPY}
            title={isHistoricalPY ? "Disabled in historical view" : undefined}
            data-testid="export-csv-recapture-gaps"
            className="inline-flex items-center gap-1.5 px-3.5 py-[7px] rounded-lg border-none text-[13px] font-semibold text-white bg-primary disabled:opacity-60 disabled:cursor-not-allowed cursor-pointer"
          >
            <FileDown size={14} />
            Export CSV
          </button>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full border-collapse">
            <thead>
              <tr>
                <th className={thCls}>Patient</th>
                <th className={thCls}>Condition</th>
                <th className={thCls}>ICD-10</th>
                <th className={thCls}>Onset Date</th>
              </tr>
            </thead>
            <tbody>
              {gaps.slice(0, 100).map((g, i) => (
                <tr
                  key={i}
                  {...rowProps(i)}
                  onClick={() => {
                    const pid = g.patient_id ?? g.pid;
                    if (pid) router.push(`/patients/${pid}`);
                  }}
                >
                  <td className={`${tdCls} font-medium text-primary`}>
                    {g.patient_name ?? g.name ?? `Patient #${g.patient_id ?? g.pid}`}
                  </td>
                  <td className={tdCls}>{g.condition ?? g.description ?? "—"}</td>
                  <td className={`${tdCls} font-mono font-semibold`}>{g.icd10_code ?? g.icd10 ?? "—"}</td>
                  <td className={`${tdCls} text-muted-foreground`}>{g.onset_date ?? g.date ?? "—"}</td>
                </tr>
              ))}
              {gaps.length === 0 && (
                <tr>
                  <td colSpan={4} className={`${tdCls} text-center text-muted-foreground py-10`}>
                    No recapture gaps found
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// TAB 5: DATA QUALITY
// ══════════════════════════════════════════════════════════════════════════════
function DataQualityTab({ dataQuality }: { dataQuality: QueryResult<DataQualityPayload> }) {
  if (dataQuality.isLoading) return <Spinner label="Loading data quality metrics..." />;
  if (dataQuality.isError) return <ErrorBox message="Failed to load data quality" onRetry={dataQuality.refetch} />;

  const raw = dataQuality.data ?? {};
  const overallScore: number = raw.completeness_score ?? raw.overall_score ?? 0;

  const dataTypes: Array<{ key: string; label: string; icon: string; count: number; total: number }> = [
    { key: "billing", label: "Billing", icon: "💳", count: raw.billing_count ?? raw.billing?.count ?? 0, total: raw.billing_total ?? raw.billing?.total ?? 0 },
    { key: "problems", label: "Problems", icon: "📋", count: raw.problems_count ?? raw.problems?.count ?? 0, total: raw.problems_total ?? raw.problems?.total ?? 0 },
    { key: "notes", label: "Clinical Notes", icon: "📝", count: raw.notes_count ?? raw.clinical_notes?.count ?? 0, total: raw.notes_total ?? raw.clinical_notes?.total ?? 0 },
    { key: "vitals", label: "Vitals", icon: "❤️", count: raw.vitals_count ?? raw.vitals?.count ?? 0, total: raw.vitals_total ?? raw.vitals?.total ?? 0 },
    { key: "labs", label: "Labs", icon: "🔬", count: raw.labs_count ?? raw.labs?.count ?? 0, total: raw.labs_total ?? raw.labs?.total ?? 0 },
    { key: "immunizations", label: "Immunizations", icon: "💉", count: raw.immunizations_count ?? raw.immunizations?.count ?? 0, total: raw.immunizations_total ?? raw.immunizations?.total ?? 0 },
    { key: "insurance", label: "Insurance", icon: "🛡️", count: raw.insurance_count ?? raw.insurance?.count ?? 0, total: raw.insurance_total ?? raw.insurance?.total ?? 0 },
  ];

  function pctColor(pct: number): string {
    if (pct >= 80) return C.emerald;
    if (pct >= 50) return C.amber;
    return C.red;
  }

  function pctBadgeClass(pct: number): string {
    if (pct >= 80) return "text-emerald-800 bg-emerald-100";
    if (pct >= 50) return "text-amber-800 bg-amber-100";
    return "text-red-700 bg-red-100";
  }

  const donutSize = 180;
  const strokeWidth = 16;
  const radius = (donutSize - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const dashOffset = circumference * (1 - overallScore / 100);

  return (
    <div>
      {/* Donut + Score */}
      <div className="flex justify-center mb-9">
        <div className="border border-border rounded-xl p-8 bg-card flex flex-col items-center w-[280px]">
          <svg width={donutSize} height={donutSize} viewBox={`0 0 ${donutSize} ${donutSize}`}>
            <circle cx={donutSize / 2} cy={donutSize / 2} r={radius} fill="none" stroke={C.gray200} strokeWidth={strokeWidth} />
            <circle
              cx={donutSize / 2} cy={donutSize / 2} r={radius}
              fill="none"
              stroke={pctColor(overallScore)}
              strokeWidth={strokeWidth}
              strokeDasharray={circumference}
              strokeDashoffset={dashOffset}
              strokeLinecap="round"
              transform={`rotate(-90 ${donutSize / 2} ${donutSize / 2})`}
              style={{ transition: "stroke-dashoffset 0.6s ease" }}
            />
            <text x={donutSize / 2} y={donutSize / 2 - 6} textAnchor="middle" style={{ fontSize: 36, fontWeight: 700, fill: C.text }}>
              {Math.round(overallScore)}%
            </text>
            <text x={donutSize / 2} y={donutSize / 2 + 18} textAnchor="middle" style={{ fontSize: 12, fill: C.textMuted }}>
              Completeness
            </text>
          </svg>
          <p className="mt-4 text-[14px] font-semibold text-foreground">Overall Data Completeness</p>
        </div>
      </div>

      {/* Data Type Cards Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {dataTypes.map((dt) => {
          const pct = dt.total > 0 ? Math.round((dt.count / dt.total) * 100) : 0;
          return (
            <div key={dt.key} className="border border-border rounded-xl p-5 bg-card">
              <div className="flex justify-between items-start mb-3">
                <div className="flex items-center gap-2">
                  <span className="text-xl">{dt.icon}</span>
                  <span className="text-[13px] font-semibold">{dt.label}</span>
                </div>
                <span className={`text-[12px] font-bold px-2 py-[2px] rounded-full ${pctBadgeClass(pct)}`}>
                  {pct}%
                </span>
              </div>
              <p className="text-[12px] text-muted-foreground mb-2">
                {dt.count.toLocaleString()} / {dt.total.toLocaleString()} records
              </p>
              <div className="h-1.5 rounded-sm overflow-hidden bg-muted">
                <div
                  className="h-full rounded-sm transition-[width] duration-300 ease-in-out"
                  style={{ width: `${pct}%`, background: pctColor(pct) }}
                />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
