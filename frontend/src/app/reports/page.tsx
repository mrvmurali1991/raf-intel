"use client";

import { ErrorBoundary } from "@/components/error-boundary";
import React, { useState, useMemo, useCallback, useEffect } from "react";
import { usePaymentYear, PAYMENT_YEARS } from "@/contexts/payment-year-context";
import dynamic from "next/dynamic";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";

const ReportsHeavyTabs = dynamic(() => import("./ReportsHeavyTabs"), {
  ssr: false,
  loading: () => (
    <div style={{ padding: "60px 24px", textAlign: "center", color: "#64748B", fontSize: 13 }}>
      <div style={{ width: 32, height: 32, border: "3px solid #E2E8F0", borderTopColor: "#2563EB", borderRadius: "50%", animation: "spin 0.8s linear infinite", margin: "0 auto 12px" }} />
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
import { tokens } from "@/styles/tokens";
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
const YEARS = Array.from({length: 3}, (_, i) => new Date().getFullYear() - i);
const CURRENT_PAYMENT_YEAR = new Date().getFullYear();
const TABS = [
  "Revenue",
  "Patient Scorecard",
  "HCC Distribution",
  "Recapture Gaps",
  "Data Quality",
  "Longitudinal Trends",
  "CMS Benchmarks",
  "Settlement Projection",
  "Scheduled Reports",
] as const;
type TabKey = (typeof TABS)[number];

// ── CMS National Average RAF by year (from official CMS publications) ─────────
const CMS_NATIONAL_AVG: { [year: number]: number } = { 2024: 1.08, 2025: 1.10, 2026: 1.12 };
const getCmsAvg = (yr: number) => CMS_NATIONAL_AVG[yr] ?? CMS_NATIONAL_AVG[Math.max(...Object.keys(CMS_NATIONAL_AVG).map(Number))];

// ── Longitudinal data — fetched from API (falls back to empty) ────────────────
// The YOUR_RAF_TREND, YOUR_HCC_CAPTURE_RATE, YOUR_MEAT_COMPLETENESS, and
// YOUR_SUSPECT_CLOSURE values are now computed from real API responses in the
// component below.  Hardcoded values have been removed.

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
  if (v == null) return "$0";
  return "$" + Math.round(v).toLocaleString("en-US");
}

function fmtN(v: number | null | undefined, d = 2): string {
  if (v == null) return "0";
  return (v ?? 0).toFixed(d);
}

function gapBadgeStyle(gap: number | null): React.CSSProperties {
  if (gap == null || gap < 0.2)
    return { background: C.emeraldLight, color: C.emeraldDark, padding: "2px 10px", borderRadius: 99, fontSize: 12, fontWeight: 600 };
  if (gap < 0.5)
    return { background: C.amberLight, color: C.amberDark, padding: "2px 10px", borderRadius: 99, fontSize: 12, fontWeight: 600 };
  return { background: C.redLight, color: C.redDark, padding: "2px 10px", borderRadius: 99, fontSize: 12, fontWeight: 600 };
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

// ── Shared Inline Styles ──────────────────────────────────────────────────────
const pageStyle: React.CSSProperties = {
  minHeight: "100vh",
  background: C.bg,
  padding: "20px 16px 56px",
  fontFamily: "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
  color: C.text,
};

const cardStyle: React.CSSProperties = {
  background: C.card,
  border: `1px solid ${C.border}`,
  borderRadius: 14,
  overflow: "hidden",
  boxShadow: "0 1px 3px rgba(0,0,0,0.06), 0 1px 2px rgba(0,0,0,0.04)",
  transition: "box-shadow 0.25s ease",
};

const thStyle: React.CSSProperties = {
  padding: "12px 16px",
  fontSize: 11,
  fontWeight: 700,
  textTransform: "uppercase" as const,
  letterSpacing: "0.06em",
  color: C.textMuted,
  borderBottom: `2px solid ${C.border}`,
  background: `linear-gradient(180deg, ${C.borderLight} 0%, ${tokens.slate100} 100%)`,
  whiteSpace: "nowrap" as const,
  cursor: "pointer",
  userSelect: "none" as const,
};

const tdStyle: React.CSSProperties = {
  padding: "12px 16px",
  fontSize: 13,
  borderBottom: `1px solid ${C.borderLight}`,
  whiteSpace: "nowrap" as const,
  transition: "background-color 0.15s ease",
};

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

// ── Tab content fade wrapper ────────────────────────────────────────────────
function TabFade({ children, tabKey }: { children: React.ReactNode; tabKey: string }) {
  const [visible, setVisible] = useState(false);
  const [prevKey, setPrevKey] = useState(tabKey);

  // When tabKey changes, reset animation
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

// ── Section header with gradient accent ─────────────────────────────────────
function GradientSectionHeader({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <div style={{ padding: "18px 22px", borderBottom: `1px solid ${C.border}`, background: "linear-gradient(135deg, rgba(37,99,235,0.03) 0%, rgba(139,92,246,0.03) 100%)" }}>
      <h3 style={{ margin: 0, fontSize: 15, fontWeight: 700, background: `linear-gradient(135deg, ${tokens.primary} 0%, ${tokens.accentPurple} 100%)`, WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent", backgroundClip: "text" }}>
        {title}
      </h3>
      {subtitle && <p style={{ margin: "4px 0 0", fontSize: 12, color: C.textMuted }}>{subtitle}</p>}
    </div>
  );
}

// ── Loading / Error ───────────────────────────────────────────────────────────
function Spinner({ label }: { label?: string }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: "80px 0", color: C.textMuted }}>
      <div style={{ width: 36, height: 36, border: `3px solid ${C.gray200}`, borderTopColor: C.primary, borderRadius: "50%", animation: "spin 0.8s linear infinite" }} />
      <style>{`@keyframes spin { to { transform: rotate(360deg) } }`}</style>
      <p style={{ marginTop: 14, fontSize: 13, fontWeight: 500 }}>{label ?? "Loading data..."}</p>
      <div className="shimmer" style={{ width: 200, height: 8, borderRadius: 4, marginTop: 12 }} />
    </div>
  );
}

function ErrorBox({ message, onRetry }: { message?: string; onRetry?: () => void }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: "80px 0", color: C.red }}>
      <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
      <p style={{ marginTop: 12, fontSize: 13 }}>{message ?? "Failed to load data"}</p>
      {onRetry && (
        <button onClick={onRetry} style={{ marginTop: 12, padding: "8px 20px", borderRadius: 8, border: `1px solid ${C.red}`, background: C.card, color: C.red, fontSize: 13, fontWeight: 600, cursor: "pointer" }}>
          Retry
        </button>
      )}
    </div>
  );
}

// ── Sort Arrow Icon ───────────────────────────────────────────────────────────
function SortArrow({ active, dir }: { active: boolean; dir: SortDir }) {
  if (!active) return <span style={{ opacity: 0.3, marginLeft: 4, fontSize: 10 }}>⇅</span>;
  return <span style={{ marginLeft: 4, fontSize: 10 }}>{dir === "asc" ? "↑" : "↓"}</span>;
}

// ══════════════════════════════════════════════════════════════════════════════
// PAGE COMPONENT
// ══════════════════════════════════════════════════════════════════════════════
export default function ReportsPage() {
  const router = useRouter();
  const [year, setYear] = useState(new Date().getFullYear());
  const { paymentYear, setPaymentYear } = usePaymentYear();
  const [activeTab, setActiveTab] = useState<TabKey>("Revenue");
  const [dateRange, setDateRange] = useState<DateRange>(() => {
    const { from, to } = presetToDates("30d");
    return { preset: "30d", from, to };
  });

  const isHistoricalPY = paymentYear !== CURRENT_PAYMENT_YEAR;

  // ── Data Queries ──────────────────────────────────────────────────────────
  const revenue = useQuery({ queryKey: ["revenue", year, paymentYear], queryFn: () => getRevenueOpportunity(year, paymentYear), staleTime: 60_000, retry: 1, gcTime: 0 });
  const scorecard = useQuery({ queryKey: ["scorecard", year, paymentYear], queryFn: () => getPatientScorecard(year, paymentYear), staleTime: 60_000, retry: 1, gcTime: 0 });
  const hccDist = useQuery({ queryKey: ["hcc-dist", year, paymentYear], queryFn: () => getHccDistribution(year, paymentYear), staleTime: 60_000, retry: 1 });
  const recapture = useQuery({ queryKey: ["recapture", year, paymentYear], queryFn: () => getRecaptureGapsReport(year, paymentYear), staleTime: 60_000, retry: 1 });
  const dataQuality = useQuery({ queryKey: ["data-quality"], queryFn: () => getDataCompleteness(), staleTime: 60_000, retry: 1 });

  const handlePrint = () => {
    const printHeader = document.getElementById("report-print-header");
    if (printHeader) printHeader.style.display = "block";
    window.print();
    if (printHeader) printHeader.style.display = "none";
  };

  return (
    <div className="rci-page-pad-desktop" style={pageStyle} {...(isHistoricalPY ? { "data-read-only": "true" } : {})}>
      {/* ── Print-only header ─────────────────────────────────────────────── */}
      <div
        id="report-print-header"
        className="print-header hidden border-b-2 border-foreground pb-3 mb-5"
      >
        <div className="text-[10px] text-muted-foreground mb-1">RAF Intelligence</div>
        <div className="text-lg font-bold">Analytics &amp; Reports — {activeTab}</div>
        <div className="text-[11px] text-muted-foreground mt-1">
          Year: {year} &nbsp;|&nbsp; Printed: {new Date().toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric" })}
        </div>
      </div>

      {/* ── Page Header ──────────────────────────────────────────────────── */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 32, flexWrap: "wrap", gap: 12 }}>
        <div>
          <h1 className="gradient-text" style={{ fontSize: 28, fontWeight: 800, margin: 0, letterSpacing: "-0.03em" }}>Analytics &amp; Reports</h1>
          <p style={{ fontSize: 14, color: C.textMuted, marginTop: 6, fontWeight: 500 }}>Population health intelligence and revenue analytics</p>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <label style={{ fontSize: 12, fontWeight: 600, color: C.textMuted, textTransform: "uppercase", letterSpacing: "0.05em" }}>Year</label>
          <select
            value={year}
            onChange={(e) => setYear(Number(e.target.value))}
            style={{
              padding: "8px 32px 8px 14px",
              fontSize: 14,
              fontWeight: 600,
              border: `1px solid ${C.border}`,
              borderRadius: 8,
              background: C.white,
              color: C.text,
              cursor: "pointer",
              appearance: "none" as const,
              backgroundImage: `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%2394A3B8' stroke-width='2'%3E%3Cpath d='M6 9l6 6 6-6'/%3E%3C/svg%3E")`,
              backgroundRepeat: "no-repeat",
              backgroundPosition: "right 10px center",
            }}
          >
            {YEARS.map((y) => (
              <option key={y} value={y}>{y}</option>
            ))}
          </select>
          <label style={{ fontSize: 12, fontWeight: 600, color: C.textMuted, textTransform: "uppercase", letterSpacing: "0.05em" }}>Payment Year</label>
          <select
            value={paymentYear}
            onChange={(e) => setPaymentYear(Number(e.target.value))}
            aria-label="As-of payment year"
            style={{
              padding: "8px 32px 8px 14px",
              fontSize: 14,
              fontWeight: 600,
              border: `1px solid ${isHistoricalPY ? C.amber : C.border}`,
              borderRadius: 8,
              background: isHistoricalPY ? C.amberLight : C.white,
              color: isHistoricalPY ? C.amberDark : C.text,
              cursor: "pointer",
              appearance: "none" as const,
              backgroundImage: `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%2394A3B8' stroke-width='2'%3E%3Cpath d='M6 9l6 6 6-6'/%3E%3C/svg%3E")`,
              backgroundRepeat: "no-repeat",
              backgroundPosition: "right 10px center",
            }}
          >
            {PAYMENT_YEARS.map((py) => (
              <option key={py} value={py}>PY{py}{py === CURRENT_PAYMENT_YEAR ? " (current)" : ""}</option>
            ))}
          </select>
          <DateRangePicker
            value={dateRange}
            onChange={setDateRange}
            className="no-print"
          />
          <button
            onClick={handlePrint}
            className="no-print"
            aria-label="Print report"
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              padding: "8px 16px",
              fontSize: 13,
              fontWeight: 600,
              border: `1px solid ${C.border}`,
              borderRadius: 8,
              background: C.white,
              color: C.textMuted,
              cursor: "pointer",
            }}
          >
            <Printer size={15} /> Print Report
          </button>
        </div>
      </div>

      {/* ── Historical view banner ────────────────────────────────────── */}
      {isHistoricalPY && (
        <div
          data-testid="historical-view-badge"
          role="status"
          aria-live="polite"
          style={{
            display: "flex",
            alignItems: "center",
            gap: 10,
            padding: "12px 18px",
            marginBottom: 24,
            borderRadius: 10,
            background: "#FFFBEB",
            border: "1px solid #F59E0B",
            color: "#92400E",
            fontSize: 14,
            fontWeight: 600,
          }}
        >
          <Lock size={16} style={{ flexShrink: 0, color: "#D97706" }} />
          Historical view — PY{paymentYear}. Data is read-only.
        </div>
      )}

      {/* ── Tab Bar (pill style) ──────────────────────────────────────── */}
      <div style={{ display: "flex", gap: 6, marginBottom: 32, padding: 6, background: tokens.slate100, borderRadius: 14, flexWrap: "wrap" }}>
        {TABS.map((tab) => {
          const isActive = activeTab === tab;
          return (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              style={{
                padding: "9px 18px",
                fontSize: 13,
                fontWeight: isActive ? 650 : 500,
                color: isActive ? C.primary : C.textMuted,
                background: isActive ? C.white : "transparent",
                border: "none",
                borderRadius: 10,
                cursor: "pointer",
                transition: "all 0.25s cubic-bezier(0.4, 0, 0.2, 1)",
                letterSpacing: "-0.01em",
                boxShadow: isActive ? "0 1px 3px rgba(0,0,0,0.08), 0 2px 8px rgba(37,99,235,0.08)" : "none",
                position: "relative" as const,
              }}
            >
              {tab}
              {isActive && (
                <span style={{
                  position: "absolute",
                  bottom: 6,
                  left: "50%",
                  transform: "translateX(-50%)",
                  width: 16,
                  height: 3,
                  borderRadius: 2,
                  background: `linear-gradient(90deg, ${tokens.primary}, ${tokens.accentPurple})`,
                }} />
              )}
            </button>
          );
        })}
      </div>

      {/* ── Tab Content ──────────────────────────────────────────────────── */}
      <TabFade tabKey={activeTab}>
        {activeTab === "Revenue" && <RevenueTab revenue={revenue} scorecard={scorecard} router={router} paymentYear={paymentYear} isHistoricalPY={isHistoricalPY} />}
        {activeTab === "Patient Scorecard" && <ScorecardTab scorecard={scorecard} router={router} isHistoricalPY={isHistoricalPY} />}
        {activeTab === "HCC Distribution" && <HccTab hccDist={hccDist} isHistoricalPY={isHistoricalPY} />}
        {activeTab === "Recapture Gaps" && <RecaptureTab recapture={recapture} router={router} isHistoricalPY={isHistoricalPY} />}
        {activeTab === "Data Quality" && <DataQualityTab dataQuality={dataQuality} />}
        {(activeTab === "Longitudinal Trends" || activeTab === "CMS Benchmarks" || activeTab === "Settlement Projection" || activeTab === "Scheduled Reports") && (
          <ReportsHeavyTabs activeTab={activeTab as "Longitudinal Trends" | "CMS Benchmarks" | "Settlement Projection" | "Scheduled Reports"} revenue={revenue} />
        )}
      </TabFade>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// TAB 1: REVENUE OPPORTUNITY
// ══════════════════════════════════════════════════════════════════════════════
function RevenueTab({ revenue, scorecard, router, paymentYear, isHistoricalPY }: { revenue: QueryResult<RevenueOpportunityReport>; scorecard: QueryResult<PatientRow[]>; router: { push: (path: string) => void }; paymentYear?: number; isHistoricalPY?: boolean }) {
  const r = revenue.data;
  const patients: PatientRow[] = scorecard.data ?? [];
  const revenueTableRef = React.useRef<HTMLDivElement | null>(null);
  // Formula provenance for CFO tooltip
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
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: "80px 24px", textAlign: "center" }}>
        <div style={{ width: 56, height: 56, borderRadius: 14, background: C.primaryLight, display: "flex", alignItems: "center", justifyContent: "center", marginBottom: 20 }}>
          <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke={C.primary} strokeWidth="1.8"><line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>
        </div>
        <h3 style={{ fontSize: 18, fontWeight: 700, margin: "0 0 8px", color: C.text }}>No revenue data available</h3>
        <p style={{ fontSize: 14, color: C.textMuted, maxWidth: 400, margin: "0 0 28px", lineHeight: 1.6 }}>
          No patients have been analyzed for payment year {paymentYear}. Connect your EMR to start analyzing RAF gaps, or load demo data to preview the reports.
        </p>
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap", justifyContent: "center" }}>
          <button
            onClick={() => router.push("/connect")}
            style={{ padding: "10px 22px", borderRadius: 10, border: "none", background: C.primary, color: C.white, fontSize: 14, fontWeight: 600, cursor: "pointer" }}
          >
            Connect EMR
          </button>
          <button
            onClick={() => router.push("/demo")}
            style={{ padding: "10px 22px", borderRadius: 10, border: `1px solid ${C.border}`, background: C.white, color: C.text, fontSize: 14, fontWeight: 600, cursor: "pointer" }}
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
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 20, marginBottom: 32 }}>
        {/* Revenue Card */}
        <div className="hover-lift card-glow-emerald" style={{ ...cardStyle, borderLeft: `4px solid ${C.emerald}`, padding: 24 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
            <div>
              <p data-testid="revenue-at-risk-label" style={{ fontSize: 11, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.06em", color: C.textMuted, margin: 0, display: "flex", alignItems: "center", gap: 4 }}>
                Estimated Annual Revenue
                {revMeta && <MetricMetaTooltip meta={revMeta} side="bottom" />}
              </p>
              <p data-testid="revenue-at-risk-value" style={{ fontSize: 32, fontWeight: 700, margin: "8px 0 0", letterSpacing: "-0.02em", color: C.emeraldDark }}>{fmt$(totalRevenue)}</p>
              <p style={{ fontSize: 12, color: C.textSub, margin: "4px 0 0" }}>@ ${REVENUE_PER_RAF.toLocaleString()} / RAF point</p>
              {r?.last_computed_at && (() => {
                const d = new Date(r.last_computed_at);
                if (isNaN(d.getTime())) return null;
                const mins = Math.floor((Date.now() - d.getTime()) / 60_000);
                if (mins < 0) return null;
                const rel = mins < 1 ? "<1m" : mins < 60 ? `${mins}m` : mins < 1440 ? `${Math.floor(mins / 60)}h` : `${Math.floor(mins / 1440)}d`;
                return (
                  <span data-testid="last-refreshed" style={{ display: "inline-flex", alignItems: "center", gap: 4, fontSize: 10, color: C.textMuted, marginTop: 4 }}>
                    <Clock size={11} aria-hidden />
                    Last refreshed {rel} ago
                  </span>
                );
              })()}
            </div>
            <div style={{ width: 44, height: 44, borderRadius: 10, background: C.emeraldLight, display: "flex", alignItems: "center", justifyContent: "center" }}>
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke={C.emerald} strokeWidth="2"><line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>
            </div>
          </div>
        </div>

        {/* RAF Gap Card */}
        <div className="hover-lift card-glow-amber" style={{ ...cardStyle, borderLeft: `4px solid ${C.amber}`, padding: 24 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
            <div>
              <p style={{ fontSize: 11, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.06em", color: C.textMuted, margin: 0 }}>Total RAF Gap</p>
              <p style={{ fontSize: 32, fontWeight: 700, margin: "8px 0 0", letterSpacing: "-0.02em", color: C.amberDark }}>{fmtN(totalGap)}</p>
              <p style={{ fontSize: 12, color: C.textSub, margin: "4px 0 0" }}>Cumulative gap across population</p>
            </div>
            <div style={{ width: 44, height: 44, borderRadius: 10, background: C.amberLight, display: "flex", alignItems: "center", justifyContent: "center" }}>
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke={C.amber} strokeWidth="2"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg>
            </div>
          </div>
        </div>

        {/* Patients with Gaps Card */}
        <div className="hover-lift card-glow-blue" style={{ ...cardStyle, borderLeft: `4px solid ${C.blue}`, padding: 24 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
            <div>
              <p style={{ fontSize: 11, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.06em", color: C.textMuted, margin: 0 }}>Patients with Gaps</p>
              <p style={{ fontSize: 32, fontWeight: 700, margin: "8px 0 0", letterSpacing: "-0.02em", color: C.blueDark }}>{patientsWithGaps}</p>
              <p style={{ fontSize: 12, color: C.textSub, margin: "4px 0 0" }}>Of {r?.total_patients_analyzed ?? 0} analyzed</p>
            </div>
            <div style={{ width: 44, height: 44, borderRadius: 10, background: C.blueLight, display: "flex", alignItems: "center", justifyContent: "center" }}>
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke={C.blue} strokeWidth="2"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>
            </div>
          </div>
        </div>
      </div>

      {/* Revenue Table */}
      <div ref={revenueTableRef} className="premium-shadow" style={cardStyle}>
        <div style={{ padding: "18px 22px", borderBottom: `1px solid ${C.border}`, display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 10, background: "linear-gradient(135deg, rgba(37,99,235,0.03) 0%, rgba(139,92,246,0.03) 100%)" }}>
          <div>
            <h3 className="gradient-text" style={{ margin: 0, fontSize: 15, fontWeight: 700 }}>Top 25 Revenue Opportunities</h3>
            <p style={{ margin: "4px 0 0", fontSize: 12, color: C.textMuted }}>Patients sorted by estimated revenue opportunity</p>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <button
              onClick={() => {
                if (isHistoricalPY || !top25.length) return;
                downloadCSV(top25.map((p) => ({
                  "Patient": p.name,
                  "Current RAF": p.billing_raf != null ? Number(p.billing_raf).toFixed(2) : "",
                  "Analyzed RAF": p.ai_raf != null ? Number(p.ai_raf).toFixed(2) : "",
                  "Gap": p.gap != null ? Number(p.gap).toFixed(2) : "",
                  "Revenue Opportunity": p.revenue_opportunity != null ? Math.round(p.revenue_opportunity) : "",
                  "HCCs Billing": p.hcc_count_billing,
                  "HCCs Analyzed": p.hcc_count_ai,
                })), "revenue-opportunities");
              }}
              disabled={isHistoricalPY}
              title={isHistoricalPY ? "Disabled in historical view" : undefined}
              style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "7px 14px", borderRadius: 8, border: "none", background: isHistoricalPY ? C.gray300 : C.primary, color: C.white, fontSize: 13, fontWeight: 600, cursor: isHistoricalPY ? "not-allowed" : "pointer", opacity: isHistoricalPY ? 0.6 : 1 }}
            >
              <FileDown size={14} />
              Export CSV
            </button>
            <ChartExportMenu
              filename="revenue-opportunities"
              csvData={top25.map((p) => ({
                patient: p.name,
                billing_raf: p.billing_raf,
                ai_raf: p.ai_raf,
                gap: p.gap,
                revenue_opportunity: p.revenue_opportunity,
                hcc_count_billing: p.hcc_count_billing,
                hcc_count_ai: p.hcc_count_ai,
              }) as Record<string, unknown>)}
              chartRef={revenueTableRef as React.RefObject<HTMLElement>}
              rawData={top25.map((p) => ({ patient: p.name, billing_raf: p.billing_raf, ai_raf: p.ai_raf, gap: p.gap, revenue: p.revenue_opportunity }) as Record<string, unknown>)}
            />
          </div>
        </div>
        <div style={{ overflowX: "auto", WebkitOverflowScrolling: "touch" }}>
          <table aria-label="Revenue opportunities" style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th style={{ ...thStyle, width: 50, textAlign: "center" }}>#</th>
                <th style={thStyle}>Patient</th>
                <th style={{ ...thStyle, textAlign: "right" }}>Current RAF</th>
                <th style={{ ...thStyle, textAlign: "right" }}>Analyzed RAF</th>
                <th style={{ ...thStyle, textAlign: "center" }}>Gap</th>
                <th style={{ ...thStyle, textAlign: "right" }}>Revenue</th>
                <th style={{ ...thStyle, textAlign: "center" }}>HCCs (Billing / Analyzed)</th>
                <th style={{ ...thStyle, textAlign: "center" }}>Evidence</th>
              </tr>
            </thead>
            <tbody>
              {top25.map((p, i) => (
                <tr
                  key={p.pid}
                  // TODO: backend /api/reports/patient-scorecard does not return hcc_code or
                  // encounter_id per row; currently falls back to /patients/{id}?tab=raf.
                  // When the backend adds those fields, replace the navigation below with:
                  //   p.encounter_id
                  //     ? `/patients/${p.pid}?tab=raf&focus=hcc:${p.hcc_code}&encounter=${p.encounter_id}`
                  //     : `/patients/${p.pid}?tab=raf&focus=hcc:${p.hcc_code}`
                  onClick={() => router.push(`/patients/${p.pid}?tab=raf`)}
                  title="Click to view supporting evidence in patient chart"
                  {...rowProps(i)}
                >
                  <td style={{ ...tdStyle, textAlign: "center", fontWeight: 600, color: C.textMuted }}>{i + 1}</td>
                  <td style={tdStyle}>
                    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                      <div style={{
                        width: 30, height: 30, borderRadius: "50%",
                        background: avatarColors[i % avatarColors.length],
                        color: tokens.white, fontSize: 11, fontWeight: 600,
                        display: "flex", alignItems: "center", justifyContent: "center",
                      }}>
                        {initials(p.name)}
                      </div>
                      <span className="font-medium">{p.name}</span>
                    </div>
                  </td>
                  <td style={{ ...tdStyle, textAlign: "right", fontFamily: "monospace", fontSize: 13 }}>{fmtN(p.billing_raf)}</td>
                  <td style={{ ...tdStyle, textAlign: "right", fontFamily: "monospace", fontSize: 13 }}>{fmtN(p.ai_raf)}</td>
                  <td style={{ ...tdStyle, textAlign: "center" }}>
                    <span style={gapBadgeStyle(p.gap)}>{fmtN(p.gap)}</span>
                  </td>
                  <td style={{ ...tdStyle, textAlign: "right", fontWeight: 600, color: C.emeraldDark }}>{fmt$(p.revenue_opportunity)}</td>
                  <td style={{ ...tdStyle, textAlign: "center", fontFamily: "monospace", fontSize: 12 }}>
                    {p.hcc_count_billing} / {p.hcc_count_ai}
                  </td>
                  <td style={{ ...tdStyle, textAlign: "center" }}>
                    <span style={{
                      display: "inline-flex", alignItems: "center", gap: 4,
                      padding: "3px 8px", borderRadius: 6,
                      background: tokens.primarySoft, color: tokens.primary,
                      fontSize: 11, fontWeight: 600, letterSpacing: "0.02em",
                      whiteSpace: "nowrap",
                    }}>
                      Evidence →
                    </span>
                  </td>
                </tr>
              ))}
              {top25.length === 0 && (
                <tr>
                  <td colSpan={8} style={{ ...tdStyle, textAlign: "center", color: C.textMuted, padding: 40 }}>
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
function ScorecardTab({ scorecard, router, isHistoricalPY }: { scorecard: QueryResult<PatientRow[]>; router: { push: (path: string) => void }; isHistoricalPY?: boolean }) {
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
      <div style={{ marginBottom: 16, display: "flex", alignItems: "center", gap: 10 }}>
        <div style={{ position: "relative", maxWidth: 340, flex: 1 }}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke={C.textSub} strokeWidth="2" style={{ position: "absolute", left: 12, top: 11 }}>
            <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
          </svg>
          <input
            type="text"
            placeholder="Search patients..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            style={{
              width: "100%",
              padding: "9px 14px 9px 36px",
              fontSize: 13,
              border: `1px solid ${C.border}`,
              borderRadius: 8,
              background: C.white,
            }}
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
          style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "9px 14px", borderRadius: 8, border: "none", background: isHistoricalPY ? C.gray300 : C.primary, color: C.white, fontSize: 13, fontWeight: 600, cursor: isHistoricalPY ? "not-allowed" : "pointer", flexShrink: 0, opacity: isHistoricalPY ? 0.6 : 1 }}
        >
          <FileDown size={14} />
          Export CSV
        </button>
      </div>

      <div className="premium-shadow" style={cardStyle}>
        <div style={{ overflowX: "auto" }}>
          <table aria-label="Patient scorecard" className="premium-table" style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                {colDefs.map((col) => (
                  <th
                    key={col.key}
                    style={{ ...thStyle, textAlign: (col.align as React.CSSProperties["textAlign"]) ?? "left" }}
                    onClick={() => toggle(col.key as keyof PatientRow)}
                  >
                    <span style={{ display: "inline-flex", alignItems: "center" }}>
                      {col.label}
                      <SortArrow active={sortKey === col.key} dir={sortDir} />
                    </span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {visible.map((p, i) => (
                <tr
                  key={p.pid}
                  onClick={() => router.push(`/patients/${p.pid}`)}
                  {...rowProps(i)}
                >
                  <td style={tdStyle}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <div style={{
                        width: 28, height: 28, borderRadius: "50%",
                        background: avatarColors[i % avatarColors.length],
                        color: tokens.white, fontSize: 10, fontWeight: 600,
                        display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0,
                      }}>
                        {initials(p.name)}
                      </div>
                      <span className="font-medium text-[13px]">{p.name}</span>
                    </div>
                  </td>
                  <td style={{ ...tdStyle, textAlign: "center" }}>{p.age ?? "—"}</td>
                  <td style={{ ...tdStyle, textAlign: "center" }}>{p.sex ?? "—"}</td>
                  <td style={{ ...tdStyle, textAlign: "right", fontFamily: "monospace" }}>{fmtN(p.billing_raf)}</td>
                  <td style={{ ...tdStyle, textAlign: "right", fontFamily: "monospace" }}>{fmtN(p.ai_raf)}</td>
                  <td style={{ ...tdStyle, textAlign: "right" }}>
                    <span style={gapBadgeStyle(p.gap)}>{fmtN(p.gap)}</span>
                  </td>
                  <td style={{ ...tdStyle, textAlign: "right", fontWeight: 600, color: C.emeraldDark }}>{fmt$(p.revenue_opportunity)}</td>
                  <td style={{ ...tdStyle, textAlign: "center", fontFamily: "monospace" }}>{p.hcc_count_billing}</td>
                  <td style={{ ...tdStyle, textAlign: "center", fontFamily: "monospace" }}>{p.hcc_count_ai}</td>
                  <td style={{ ...tdStyle, textAlign: "center" }}>
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
          <div style={{ padding: 16, textAlign: "center", borderTop: `1px solid ${C.border}` }}>
            <button
              onClick={() => setLimit((l) => l + 100)}
              style={{
                padding: "8px 24px",
                fontSize: 13,
                fontWeight: 600,
                color: C.primary,
                background: C.primaryLight,
                border: "none",
                borderRadius: 8,
                cursor: "pointer",
              }}
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
function HccTab({ hccDist, isHistoricalPY }: { hccDist: QueryResult<HccDistributionRow[]>; isHistoricalPY?: boolean }) {
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
    <div ref={chartRef} className="premium-shadow" style={cardStyle}>
      <div style={{ padding: "18px 22px", borderBottom: `1px solid ${C.border}`, display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 10, background: "linear-gradient(135deg, rgba(37,99,235,0.03) 0%, rgba(139,92,246,0.03) 100%)" }}>
        <div>
          <h3 className="gradient-text" style={{ margin: 0, fontSize: 15, fontWeight: 700 }}>HCC Distribution — Top 20 by Patient Count</h3>
          <p style={{ margin: "4px 0 0", fontSize: 12, color: C.textMuted }}>Hierarchical Condition Categories across the population</p>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <button
            onClick={() => { if (!isHistoricalPY && top20.length) downloadCSV(csvData, "hcc-distribution"); }}
            disabled={isHistoricalPY}
            title={isHistoricalPY ? "Disabled in historical view" : undefined}
            style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "7px 14px", borderRadius: 8, border: "none", background: isHistoricalPY ? C.gray300 : C.primary, color: C.white, fontSize: 13, fontWeight: 600, cursor: isHistoricalPY ? "not-allowed" : "pointer", opacity: isHistoricalPY ? 0.6 : 1 }}
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
      <div style={{ padding: 20 }}>
        {top20.map((item, i) => {
          const rank = i + 1;
          const pct = (item.patient_count / maxCount) * 100;
          return (
            <div key={item.hcc_code} style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 10 }}>
              <span style={{ width: 28, textAlign: "right", fontSize: 12, fontWeight: 600, color: C.textMuted, flexShrink: 0 }}>{rank}</span>
              <span style={{ width: 70, fontSize: 12, fontWeight: 700, color: barColor(rank), fontFamily: "monospace", flexShrink: 0 }}>{item.hcc_code}</span>
              <div style={{ flex: 1, position: "relative", height: 28, background: C.gray100, borderRadius: 6, overflow: "hidden" }}>
                <div
                  style={{
                    width: `${Math.max(pct, 2)}%`,
                    height: "100%",
                    background: barColor(rank),
                    borderRadius: 6,
                    opacity: 0.8,
                    transition: "width 0.4s ease",
                  }}
                />
              </div>
              <span style={{ width: 50, textAlign: "right", fontSize: 13, fontWeight: 600, color: C.text, flexShrink: 0 }}>{item.patient_count}</span>
            </div>
          );
        })}
        {top20.length === 0 && (
          <p style={{ textAlign: "center", color: C.textMuted, padding: 40 }}>No HCC data available</p>
        )}
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// TAB 4: RECAPTURE GAPS
// ══════════════════════════════════════════════════════════════════════════════
function RecaptureTab({ recapture, router, isHistoricalPY }: { recapture: QueryResult<unknown>; router: { push: (path: string) => void }; isHistoricalPY?: boolean }) {
  if (recapture.isLoading) return <Spinner label="Loading recapture gaps..." />;
  if (recapture.isError) return <ErrorBox message="Failed to load recapture data" onRetry={recapture.refetch} />;

  const raw = recapture.data ?? {};
  const gaps: GapRow[] = (raw as { gaps?: GapRow[]; data?: GapRow[] }).gaps ?? (raw as { data?: GapRow[] }).data ?? (Array.isArray(raw) ? raw as GapRow[] : []);
  const totalGaps = gaps.length;
  const uniquePatients = new Set(gaps.map((g) => g.patient_id ?? g.pid)).size;

  // Top conditions summary
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
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 20, marginBottom: 32 }}>
        <div className="hover-lift card-glow-rose" style={{ ...cardStyle, borderLeft: `4px solid ${C.red}`, padding: 24 }}>
          <p style={{ fontSize: 11, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.06em", color: C.textMuted, margin: 0 }}>Total Gaps</p>
          <p style={{ fontSize: 32, fontWeight: 700, margin: "8px 0 0", color: C.redDark }}>{totalGaps}</p>
        </div>
        <div className="hover-lift card-glow-amber" style={{ ...cardStyle, borderLeft: `4px solid ${C.amber}`, padding: 24 }}>
          <p style={{ fontSize: 11, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.06em", color: C.textMuted, margin: 0 }}>Patients Affected</p>
          <p style={{ fontSize: 32, fontWeight: 700, margin: "8px 0 0", color: C.amberDark }}>{uniquePatients}</p>
        </div>
      </div>

      {/* Top Conditions Table */}
      <div className="premium-shadow" style={{ ...cardStyle, marginBottom: 24 }}>
        <GradientSectionHeader title="Top Conditions for Recapture" />
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th style={thStyle}>Condition</th>
                <th style={thStyle}>ICD-10</th>
                <th style={{ ...thStyle, textAlign: "right" }}>Gap Count</th>
              </tr>
            </thead>
            <tbody>
              {topConditions.map((c, i) => (
                <tr key={c.icd10} style={{ background: i % 2 === 1 ? tokens.slate50 : "transparent" }}>
                  <td style={tdStyle}>{c.condition}</td>
                  <td style={{ ...tdStyle, fontFamily: "monospace", fontWeight: 600, color: C.primary }}>{c.icd10}</td>
                  <td style={{ ...tdStyle, textAlign: "right", fontWeight: 600 }}>{c.count}</td>
                </tr>
              ))}
              {topConditions.length === 0 && (
                <tr><td colSpan={3} style={{ ...tdStyle, textAlign: "center", color: C.textMuted, padding: 40 }}>No recapture gaps found</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Full Gaps Table */}
      <div className="premium-shadow" style={cardStyle}>
        <div style={{ padding: "18px 22px", borderBottom: `1px solid ${C.border}`, display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 10, background: "linear-gradient(135deg, rgba(37,99,235,0.03) 0%, rgba(139,92,246,0.03) 100%)" }}>
          <h3 className="gradient-text" style={{ margin: 0, fontSize: 15, fontWeight: 700 }}>All Recapture Gaps</h3>
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
            style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "7px 14px", borderRadius: 8, border: "none", background: isHistoricalPY ? C.gray300 : C.primary, color: C.white, fontSize: 13, fontWeight: 600, cursor: isHistoricalPY ? "not-allowed" : "pointer", opacity: isHistoricalPY ? 0.6 : 1 }}
          >
            <FileDown size={14} />
            Export CSV
          </button>
        </div>
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th style={thStyle}>Patient</th>
                <th style={thStyle}>Condition</th>
                <th style={thStyle}>ICD-10</th>
                <th style={thStyle}>Onset Date</th>
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
                  <td style={{ ...tdStyle, fontWeight: 500, color: C.primary }}>{g.patient_name ?? g.name ?? `Patient #${g.patient_id ?? g.pid}`}</td>
                  <td style={tdStyle}>{g.condition ?? g.description ?? "—"}</td>
                  <td style={{ ...tdStyle, fontFamily: "monospace", fontWeight: 600 }}>{g.icd10_code ?? g.icd10 ?? "—"}</td>
                  <td style={{ ...tdStyle, color: C.textMuted }}>{g.onset_date ?? g.date ?? "—"}</td>
                </tr>
              ))}
              {gaps.length === 0 && (
                <tr><td colSpan={4} style={{ ...tdStyle, textAlign: "center", color: C.textMuted, padding: 40 }}>No recapture gaps found</td></tr>
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

  function pctBg(pct: number): string {
    if (pct >= 80) return C.emeraldLight;
    if (pct >= 50) return C.amberLight;
    return C.redLight;
  }

  // SVG donut
  const donutSize = 180;
  const strokeWidth = 16;
  const radius = (donutSize - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const dashOffset = circumference * (1 - overallScore / 100);

  return (
    <div>
      {/* Donut + Score */}
      <div style={{ display: "flex", justifyContent: "center", marginBottom: 36 }}>
        <div className="premium-shadow hover-lift" style={{ ...cardStyle, padding: 32, display: "flex", flexDirection: "column", alignItems: "center", width: 280 }}>
          <svg width={donutSize} height={donutSize} viewBox={`0 0 ${donutSize} ${donutSize}`}>
            {/* Background ring */}
            <circle
              cx={donutSize / 2}
              cy={donutSize / 2}
              r={radius}
              fill="none"
              stroke={C.gray200}
              strokeWidth={strokeWidth}
            />
            {/* Progress ring */}
            <circle
              cx={donutSize / 2}
              cy={donutSize / 2}
              r={radius}
              fill="none"
              stroke={pctColor(overallScore)}
              strokeWidth={strokeWidth}
              strokeDasharray={circumference}
              strokeDashoffset={dashOffset}
              strokeLinecap="round"
              transform={`rotate(-90 ${donutSize / 2} ${donutSize / 2})`}
              style={{ transition: "stroke-dashoffset 0.6s ease" }}
            />
            {/* Center text */}
            <text
              x={donutSize / 2}
              y={donutSize / 2 - 6}
              textAnchor="middle"
              style={{ fontSize: 36, fontWeight: 700, fill: C.text }}
            >
              {Math.round(overallScore)}%
            </text>
            <text
              x={donutSize / 2}
              y={donutSize / 2 + 18}
              textAnchor="middle"
              style={{ fontSize: 12, fill: C.textMuted }}
            >
              Completeness
            </text>
          </svg>
          <p style={{ marginTop: 16, fontSize: 14, fontWeight: 600, color: C.text }}>Overall Data Completeness</p>
        </div>
      </div>

      {/* Data Type Cards Grid */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))", gap: 16 }}>
        {dataTypes.map((dt) => {
          const pct = dt.total > 0 ? Math.round((dt.count / dt.total) * 100) : 0;
          return (
            <div key={dt.key} className="hover-lift" style={{ ...cardStyle, padding: 20 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 12 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span className="text-xl">{dt.icon}</span>
                  <span className="text-[13px] font-semibold">{dt.label}</span>
                </div>
                <span style={{
                  fontSize: 12,
                  fontWeight: 700,
                  color: pctColor(pct),
                  background: pctBg(pct),
                  padding: "2px 8px",
                  borderRadius: 99,
                }}>{pct}%</span>
              </div>
              <p style={{ fontSize: 12, color: C.textMuted, margin: "0 0 8px" }}>
                {dt.count.toLocaleString()} / {dt.total.toLocaleString()} records
              </p>
              {/* Progress bar */}
              <div style={{ height: 6, background: C.gray200, borderRadius: 3, overflow: "hidden" }}>
                <div
                  style={{
                    width: `${pct}%`,
                    height: "100%",
                    background: pctColor(pct),
                    borderRadius: 3,
                    transition: "width 0.4s ease",
                  }}
                />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

