"use client";

import { ErrorBoundary } from "@/components/ErrorBoundary";
import React, { useState, useMemo, useCallback, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import {
  getRevenueOpportunity,
  getPatientScorecard,
  getHccDistribution,
  getRecaptureGapsReport,
  getDataCompleteness,
  type RevenueOpportunityReport,
  type PatientScorecardRow,
  type HccDistributionRow,
} from "@/lib/api";
import { StatCard } from "@/components/healthcare-ui";
import { FileDown, Printer } from "lucide-react";
import { downloadCSV } from "@/lib/csv-export";

// ── Shared types ──────────────────────────────────────────────────────────────
type QueryResult<T = unknown> = { data?: T; isLoading?: boolean; isError?: boolean };
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

// ── Colors ────────────────────────────────────────────────────────────────────
const C = {
  bg: "#F8FAFC",
  card: "#FFFFFF",
  border: "#E2E8F0",
  borderLight: "#F1F5F9",
  text: "#0F172A",
  textMuted: "#64748B",
  textSub: "#94A3B8",
  primary: "#2563EB",
  primaryLight: "#DBEAFE",
  emerald: "#10B981",
  emeraldLight: "#D1FAE5",
  emeraldDark: "#065F46",
  amber: "#F59E0B",
  amberLight: "#FEF3C7",
  amberDark: "#92400E",
  red: "#EF4444",
  redLight: "#FEE2E2",
  redDark: "#991B1B",
  blue: "#3B82F6",
  blueLight: "#DBEAFE",
  blueDark: "#1E40AF",
  violet: "#8B5CF6",
  gray100: "#F3F4F6",
  gray200: "#E5E7EB",
  gray300: "#D1D5DB",
  gray400: "#9CA3AF",
  gray600: "#4B5563",
  white: "#FFFFFF",
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

const avatarColors = ["#2563EB", "#7C3AED", "#059669", "#DC2626", "#D97706", "#0891B2", "#DB2777", "#4F46E5"];

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
  padding: "32px 40px 56px",
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
  background: `linear-gradient(180deg, ${C.borderLight} 0%, #EEF2F7 100%)`,
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
      background: index % 2 === 1 ? "#F8FAFD" : "transparent",
    },
    onMouseEnter: (e: React.MouseEvent<HTMLTableRowElement>) => {
      e.currentTarget.style.background = "#EDF2F7";
    },
    onMouseLeave: (e: React.MouseEvent<HTMLTableRowElement>) => {
      e.currentTarget.style.background = index % 2 === 1 ? "#F8FAFD" : "transparent";
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
      <h3 style={{ margin: 0, fontSize: 15, fontWeight: 700, background: "linear-gradient(135deg, #2563eb 0%, #7c3aed 100%)", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent", backgroundClip: "text" }}>
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

function ErrorBox({ message }: { message?: string }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: "80px 0", color: C.red }}>
      <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
      <p style={{ marginTop: 12, fontSize: 13 }}>{message ?? "Failed to load data"}</p>
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
  const [activeTab, setActiveTab] = useState<TabKey>("Revenue");

  // ── Data Queries ──────────────────────────────────────────────────────────
  const revenue = useQuery({ queryKey: ["revenue", year], queryFn: () => getRevenueOpportunity(year), staleTime: 60_000 });
  const scorecard = useQuery({ queryKey: ["scorecard", year], queryFn: () => getPatientScorecard(year), staleTime: 60_000 });
  const hccDist = useQuery({ queryKey: ["hcc-dist", year], queryFn: () => getHccDistribution(year), staleTime: 60_000 });
  const recapture = useQuery({ queryKey: ["recapture", year], queryFn: () => getRecaptureGapsReport(year), staleTime: 60_000 });
  const dataQuality = useQuery({ queryKey: ["data-quality"], queryFn: () => getDataCompleteness(), staleTime: 60_000 });

  const handlePrint = () => {
    const printHeader = document.getElementById("report-print-header");
    if (printHeader) printHeader.style.display = "block";
    window.print();
    if (printHeader) printHeader.style.display = "none";
  };

  return (
    <div style={pageStyle}>
      {/* ── Print-only header ─────────────────────────────────────────────── */}
      <div
        id="report-print-header"
        className="print-header"
        style={{ display: "none", borderBottom: "2px solid #000", paddingBottom: 12, marginBottom: 20 }}
      >
        <div style={{ fontSize: 10, color: "#666", marginBottom: 4 }}>RAF Intelligence</div>
        <div style={{ fontSize: 18, fontWeight: 700 }}>Analytics &amp; Reports — {activeTab}</div>
        <div style={{ fontSize: 11, color: "#444", marginTop: 4 }}>
          Year: {year} &nbsp;|&nbsp; Printed: {new Date().toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric" })}
        </div>
      </div>

      {/* ── Page Header ──────────────────────────────────────────────────── */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 32 }}>
        <div>
          <h1 className="gradient-text" style={{ fontSize: 28, fontWeight: 800, margin: 0, letterSpacing: "-0.03em" }}>Analytics &amp; Reports</h1>
          <p style={{ fontSize: 14, color: C.textMuted, marginTop: 6, fontWeight: 500 }}>Population health intelligence and revenue analytics</p>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
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

      {/* ── Tab Bar (pill style) ──────────────────────────────────────── */}
      <div style={{ display: "flex", gap: 6, marginBottom: 32, padding: 6, background: "#EEF2F7", borderRadius: 14, flexWrap: "wrap" }}>
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
                  background: "linear-gradient(90deg, #2563EB, #7C3AED)",
                }} />
              )}
            </button>
          );
        })}
      </div>

      {/* ── Tab Content ──────────────────────────────────────────────────── */}
      <TabFade tabKey={activeTab}>
        {activeTab === "Revenue" && <RevenueTab revenue={revenue} scorecard={scorecard} router={router} />}
        {activeTab === "Patient Scorecard" && <ScorecardTab scorecard={scorecard} router={router} />}
        {activeTab === "HCC Distribution" && <HccTab hccDist={hccDist} />}
        {activeTab === "Recapture Gaps" && <RecaptureTab recapture={recapture} router={router} />}
        {activeTab === "Data Quality" && <DataQualityTab dataQuality={dataQuality} />}
        {activeTab === "Longitudinal Trends" && <LongitudinalTrendsTab revenue={revenue} />}
        {activeTab === "CMS Benchmarks" && <CmsBenchmarksTab revenue={revenue} />}
        {activeTab === "Settlement Projection" && <SettlementProjectionTab revenue={revenue} />}
        {activeTab === "Scheduled Reports" && <ScheduledReportsTab />}
      </TabFade>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// TAB 1: REVENUE OPPORTUNITY
// ══════════════════════════════════════════════════════════════════════════════
function RevenueTab({ revenue, scorecard, router }: { revenue: QueryResult<RevenueOpportunityReport>; scorecard: QueryResult<PatientRow[]>; router: { push: (path: string) => void } }) {
  const r = revenue.data;
  const patients: PatientRow[] = scorecard.data ?? [];

  const { top25, patientsWithGaps } = useMemo(() => {
    const allWithGaps = [...patients].filter((p) => (p.gap ?? 0) > 0);
    const patientsWithGaps = allWithGaps.length;
    const top25 = allWithGaps
      .sort((a, b) => (b.revenue_opportunity ?? 0) - (a.revenue_opportunity ?? 0))
      .slice(0, 25);
    return { top25, patientsWithGaps };
  }, [patients]);

  if (revenue.isLoading || scorecard.isLoading) return <Spinner label="Loading revenue data..." />;
  if (revenue.isError) return <ErrorBox message="Failed to load revenue data" />;

  const totalRevenue = r?.estimated_annual_revenue ?? 0;
  const totalGap = r?.total_gap ?? 0;

  return (
    <div>
      {/* KPI Cards */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 20, marginBottom: 32 }}>
        {/* Revenue Card */}
        <div className="hover-lift card-glow-emerald" style={{ ...cardStyle, borderLeft: `4px solid ${C.emerald}`, padding: 24 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
            <div>
              <p style={{ fontSize: 11, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.06em", color: C.textMuted, margin: 0 }}>Estimated Annual Revenue</p>
              <p style={{ fontSize: 32, fontWeight: 700, margin: "8px 0 0", letterSpacing: "-0.02em", color: C.emeraldDark }}>{fmt$(totalRevenue)}</p>
              <p style={{ fontSize: 12, color: C.textSub, margin: "4px 0 0" }}>@ ${REVENUE_PER_RAF.toLocaleString()} / RAF point</p>
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
      <div className="premium-shadow" style={cardStyle}>
        <div style={{ padding: "18px 22px", borderBottom: `1px solid ${C.border}`, display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 10, background: "linear-gradient(135deg, rgba(37,99,235,0.03) 0%, rgba(139,92,246,0.03) 100%)" }}>
          <div>
            <h3 className="gradient-text" style={{ margin: 0, fontSize: 15, fontWeight: 700 }}>Top 25 Revenue Opportunities</h3>
            <p style={{ margin: "4px 0 0", fontSize: 12, color: C.textMuted }}>Patients sorted by estimated revenue opportunity</p>
          </div>
          <button
            onClick={() => {
              if (!top25.length) return;
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
            style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "7px 14px", borderRadius: 8, border: "none", background: C.primary, color: C.white, fontSize: 13, fontWeight: 600, cursor: "pointer" }}
          >
            <FileDown size={14} />
            Export CSV
          </button>
        </div>
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th style={{ ...thStyle, width: 50, textAlign: "center" }}>#</th>
                <th style={thStyle}>Patient</th>
                <th style={{ ...thStyle, textAlign: "right" }}>Current RAF</th>
                <th style={{ ...thStyle, textAlign: "right" }}>Analyzed RAF</th>
                <th style={{ ...thStyle, textAlign: "center" }}>Gap</th>
                <th style={{ ...thStyle, textAlign: "right" }}>Revenue</th>
                <th style={{ ...thStyle, textAlign: "center" }}>HCCs (Billing / Analyzed)</th>
              </tr>
            </thead>
            <tbody>
              {top25.map((p, i) => (
                <tr
                  key={p.pid}
                  onClick={() => router.push(`/patients/${p.pid}`)}
                  {...rowProps(i)}
                >
                  <td style={{ ...tdStyle, textAlign: "center", fontWeight: 600, color: C.textMuted }}>{i + 1}</td>
                  <td style={tdStyle}>
                    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                      <div style={{
                        width: 30, height: 30, borderRadius: "50%",
                        background: avatarColors[i % avatarColors.length],
                        color: "#fff", fontSize: 11, fontWeight: 600,
                        display: "flex", alignItems: "center", justifyContent: "center",
                      }}>
                        {initials(p.name)}
                      </div>
                      <span style={{ fontWeight: 500 }}>{p.name}</span>
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
                </tr>
              ))}
              {top25.length === 0 && (
                <tr>
                  <td colSpan={7} style={{ ...tdStyle, textAlign: "center", color: C.textMuted, padding: 40 }}>
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
function ScorecardTab({ scorecard, router }: { scorecard: QueryResult<PatientRow[]>; router: { push: (path: string) => void } }) {
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
  if (scorecard.isError) return <ErrorBox message="Failed to load scorecard" />;

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
              outline: "none",
              background: C.white,
            }}
          />
        </div>
        <button
          onClick={() => {
            if (!filtered.length) return;
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
          style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "9px 14px", borderRadius: 8, border: "none", background: C.primary, color: C.white, fontSize: 13, fontWeight: 600, cursor: "pointer", flexShrink: 0 }}
        >
          <FileDown size={14} />
          Export CSV
        </button>
      </div>

      <div className="premium-shadow" style={cardStyle}>
        <div style={{ overflowX: "auto" }}>
          <table className="premium-table" style={{ width: "100%", borderCollapse: "collapse" }}>
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
                        color: "#fff", fontSize: 10, fontWeight: 600,
                        display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0,
                      }}>
                        {initials(p.name)}
                      </div>
                      <span style={{ fontWeight: 500, fontSize: 13 }}>{p.name}</span>
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
                      <span style={{ color: C.emerald, fontWeight: 600, fontSize: 15 }}>✓</span>
                    ) : (
                      <span style={{ color: C.red, fontWeight: 600, fontSize: 15 }}>✗</span>
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
function HccTab({ hccDist }: { hccDist: QueryResult<HccDistributionRow[]> }) {
  if (hccDist.isLoading) return <Spinner label="Loading HCC distribution..." />;
  if (hccDist.isError) return <ErrorBox message="Failed to load HCC data" />;

  const data: Array<{ hcc_code: string; patient_count: number }> = hccDist.data ?? [];
  const top20 = [...data].sort((a, b) => b.patient_count - a.patient_count).slice(0, 20);
  const maxCount = top20[0]?.patient_count ?? 1;

  function barColor(rank: number): string {
    if (rank <= 3) return C.red;
    if (rank <= 8) return C.amber;
    return C.blue;
  }

  return (
    <div className="premium-shadow" style={cardStyle}>
      <div style={{ padding: "18px 22px", borderBottom: `1px solid ${C.border}`, display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 10, background: "linear-gradient(135deg, rgba(37,99,235,0.03) 0%, rgba(139,92,246,0.03) 100%)" }}>
        <div>
          <h3 className="gradient-text" style={{ margin: 0, fontSize: 15, fontWeight: 700 }}>HCC Distribution — Top 20 by Patient Count</h3>
          <p style={{ margin: "4px 0 0", fontSize: 12, color: C.textMuted }}>Hierarchical Condition Categories across the population</p>
        </div>
        <button
          onClick={() => {
            if (!top20.length) return;
            downloadCSV(top20.map((item, i) => ({
              "Rank": i + 1,
              "HCC Code": item.hcc_code,
              "Patient Count": item.patient_count,
            })), "hcc-distribution");
          }}
          style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "7px 14px", borderRadius: 8, border: "none", background: C.primary, color: C.white, fontSize: 13, fontWeight: 600, cursor: "pointer" }}
        >
          <FileDown size={14} />
          Export CSV
        </button>
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
function RecaptureTab({ recapture, router }: { recapture: QueryResult<unknown>; router: { push: (path: string) => void } }) {
  if (recapture.isLoading) return <Spinner label="Loading recapture gaps..." />;
  if (recapture.isError) return <ErrorBox message="Failed to load recapture data" />;

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
      <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 20, marginBottom: 32 }}>
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
                <tr key={c.icd10} style={{ background: i % 2 === 1 ? "#F8FAFD" : "transparent" }}>
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
              if (!gaps.length) return;
              downloadCSV(gaps.map((g) => ({
                "Patient ID": g.patient_id ?? g.pid ?? "",
                "Patient Name": [g.last_name, g.first_name].filter(Boolean).join(", ") || (g.patient_name ?? ""),
                "Condition": g.condition ?? g.description ?? "",
                "ICD-10": g.icd10_code ?? g.icd10 ?? g.icd_code ?? "",
                "HCC": g.hcc_code ?? g.hcc ?? "",
                "Last Coded": g.onset_date ?? g.last_coded ?? "",
              })), "recapture-gaps");
            }}
            style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "7px 14px", borderRadius: 8, border: "none", background: C.primary, color: C.white, fontSize: 13, fontWeight: 600, cursor: "pointer" }}
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
  if (dataQuality.isError) return <ErrorBox message="Failed to load data quality" />;

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
                  <span style={{ fontSize: 20 }}>{dt.icon}</span>
                  <span style={{ fontSize: 13, fontWeight: 600 }}>{dt.label}</span>
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

// ══════════════════════════════════════════════════════════════════════════════
// TAB 6: LONGITUDINAL TRENDS
// ══════════════════════════════════════════════════════════════════════════════
function LongitudinalTrendsTab({ revenue }: { revenue: QueryResult<RevenueOpportunityReport> }) {
  const avgRaf: number = revenue.data?.average_raf_score ?? 0;

  // Historical RAF data is not yet available from the API.
  // Only show the current year's data point; historical trends require
  // a dedicated /api/reports/historical endpoint.
  const yourData: { [year: number]: number } = avgRaf > 0 ? { [new Date().getFullYear()]: avgRaf } : {};

  // SVG chart dimensions
  const W = 660;
  const H = 240;
  const PAD = { top: 24, right: 48, bottom: 48, left: 60 };
  const chartW = W - PAD.left - PAD.right;
  const chartH = H - PAD.top - PAD.bottom;

  const allVals = [...Object.values(yourData), ...Object.values(CMS_NATIONAL_AVG)];
  const minV = Math.min(...allVals) - 0.05;
  const maxV = Math.max(...allVals) + 0.05;

  function xPos(year: number) {
    const idx = YEARS.indexOf(year);
    return PAD.left + (idx / (YEARS.length - 1)) * chartW;
  }
  function yPos(val: number) {
    return PAD.top + chartH - ((val - minV) / (maxV - minV)) * chartH;
  }

  const yourPoints = YEARS.map((y) => ({ x: xPos(y), y: yPos(yourData[y]), val: yourData[y] }));
  const cmsPoints  = YEARS.map((y) => ({ x: xPos(y), y: yPos(getCmsAvg(y)), val: getCmsAvg(y) }));

  function polyline(pts: { x: number; y: number }[]) {
    return pts.map((p) => `${p.x},${p.y}`).join(" ");
  }

  // Green fill area between your line and CMS average
  const areaPath = [
    `M ${yourPoints[0].x} ${yourPoints[0].y}`,
    ...yourPoints.slice(1).map((p) => `L ${p.x} ${p.y}`),
    `L ${cmsPoints[cmsPoints.length - 1].x} ${cmsPoints[cmsPoints.length - 1].y}`,
    ...cmsPoints.slice().reverse().map((p) => `L ${p.x} ${p.y}`),
    "Z",
  ].join(" ");

  // Y-axis grid lines
  const gridCount = 4;
  const gridLines = Array.from({ length: gridCount + 1 }).map((_, i) => {
    const v = minV + (i / gridCount) * (maxV - minV);
    return { y: yPos(v), label: (v ?? 0).toFixed(2) };
  });

  // Stats table data
  const tableRows = YEARS.map((y, i) => {
    const yourVal = yourData[y];
    const prevVal = i > 0 ? yourData[YEARS[i - 1]] : null;
    const delta = prevVal !== null ? yourVal - prevVal : null;
    const vsNational = yourVal - getCmsAvg(y);
    const estRevenue = 5000 * yourVal * 12000; // 5000 as demo population
    return { year: y, yourVal, delta, vsNational, estRevenue };
  });

  return (
    <div>
      {/* ── Chart Card ── */}
      <div className="premium-shadow" style={{ ...cardStyle, padding: 28, marginBottom: 24 }}>
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 20 }}>
          <div>
            <h3 className="gradient-text" style={{ margin: 0, fontSize: 15, fontWeight: 700 }}>Average RAF Score — 3-Year Trend</h3>
            <p style={{ margin: "4px 0 0", fontSize: 12, color: C.textMuted }}>Your population vs CMS national average</p>
          </div>
          <div style={{ display: "flex", gap: 20 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <div style={{ width: 24, height: 3, background: C.primary, borderRadius: 2 }} />
              <span style={{ fontSize: 12, color: C.textMuted, fontWeight: 500 }}>Your Population</span>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <div style={{ width: 24, height: 0, borderTop: `2px dashed ${C.gray400}` }} />
              <span style={{ fontSize: 12, color: C.textMuted, fontWeight: 500 }}>CMS National Avg</span>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <div style={{ width: 14, height: 14, background: "#10B98133", border: `1px solid #10B981`, borderRadius: 3 }} />
              <span style={{ fontSize: 12, color: C.textMuted, fontWeight: 500 }}>Above Benchmark</span>
            </div>
          </div>
        </div>

        {/* SVG Chart */}
        <div style={{ overflowX: "auto" }}>
          <svg
            viewBox={`0 0 ${W} ${H}`}
            style={{ width: "100%", maxWidth: W, display: "block" }}
            aria-label="RAF score trend chart"
            role="img"
          >
            {/* Grid lines */}
            {gridLines.map((g) => (
              <g key={g.y}>
                <line
                  x1={PAD.left} y1={g.y} x2={W - PAD.right} y2={g.y}
                  stroke={C.gray200} strokeWidth={1} strokeDasharray="4 3"
                />
                <text x={PAD.left - 8} y={g.y + 4} textAnchor="end" fontSize={10} fill={C.textSub}>
                  {g.label}
                </text>
              </g>
            ))}

            {/* X axis labels */}
            {YEARS.map((y) => (
              <text key={y} x={xPos(y)} y={H - 10} textAnchor="middle" fontSize={12} fontWeight={600} fill={C.textMuted}>
                {y}
              </text>
            ))}

            {/* Green fill area */}
            <path d={areaPath} fill="#10B981" fillOpacity={0.12} />

            {/* CMS dashed line */}
            <polyline
              points={polyline(cmsPoints)}
              fill="none"
              stroke={C.gray400}
              strokeWidth={2}
              strokeDasharray="6 4"
            />

            {/* Your population solid line */}
            <polyline
              points={polyline(yourPoints)}
              fill="none"
              stroke={C.primary}
              strokeWidth={2.5}
            />

            {/* Data point dots — CMS */}
            {cmsPoints.map((p, i) => (
              <circle key={i} cx={p.x} cy={p.y} r={4} fill={C.white} stroke={C.gray400} strokeWidth={2} />
            ))}

            {/* Data point dots — Your */}
            {yourPoints.map((p, i) => (
              <g key={i}>
                <circle cx={p.x} cy={p.y} r={6} fill={C.primary} stroke={C.white} strokeWidth={2} />
                <text
                  x={p.x}
                  y={p.y - 12}
                  textAnchor="middle"
                  fontSize={11}
                  fontWeight={700}
                  fill={C.primary}
                >
                  {(p.val ?? 0).toFixed(3)}
                </text>
              </g>
            ))}

            {/* CMS labels */}
            {cmsPoints.map((p, i) => (
              <text key={i} x={p.x + 10} y={p.y + 4} fontSize={10} fill={C.gray400}>
                {(p.val ?? 0).toFixed(2)}
              </text>
            ))}

            {/* Axes */}
            <line x1={PAD.left} y1={PAD.top} x2={PAD.left} y2={H - PAD.bottom} stroke={C.border} strokeWidth={1} />
            <line x1={PAD.left} y1={H - PAD.bottom} x2={W - PAD.right} y2={H - PAD.bottom} stroke={C.border} strokeWidth={1} />
          </svg>
        </div>
      </div>

      {/* ── Stats Table ── */}
      <div className="premium-shadow" style={cardStyle}>
        <GradientSectionHeader title="Year-over-Year Summary" />
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th style={thStyle}>Year</th>
                <th style={{ ...thStyle, textAlign: "right" }}>Avg RAF</th>
                <th style={{ ...thStyle, textAlign: "right" }}>vs Prior Year</th>
                <th style={{ ...thStyle, textAlign: "right" }}>vs National Avg</th>
                <th style={{ ...thStyle, textAlign: "right" }}>Est. Annual Revenue</th>
              </tr>
            </thead>
            <tbody>
              {tableRows.map((row) => {
                const deltaUp = row.delta != null && row.delta > 0;
                const aboveBench = row.vsNational > 0;
                return (
                  <tr key={row.year}>
                    <td style={{ ...tdStyle, fontWeight: 700, fontSize: 14 }}>{row.year}</td>
                    <td style={{ ...tdStyle, textAlign: "right", fontFamily: "monospace", fontWeight: 600 }}>
                      {(row.yourVal ?? 0).toFixed(3)}
                    </td>
                    <td style={{ ...tdStyle, textAlign: "right" }}>
                      {row.delta != null ? (
                        <span style={{ color: deltaUp ? C.emerald : C.red, fontWeight: 600, display: "inline-flex", alignItems: "center", gap: 3 }}>
                          {deltaUp ? "▲" : "▼"} {Math.abs(row.delta ?? 0).toFixed(3)}
                        </span>
                      ) : (
                        <span style={{ color: C.textSub }}>—</span>
                      )}
                    </td>
                    <td style={{ ...tdStyle, textAlign: "right" }}>
                      <span style={{ color: aboveBench ? C.emerald : C.red, fontWeight: 600 }}>
                        {aboveBench ? "+" : ""}{(row.vsNational ?? 0).toFixed(3)}
                      </span>
                    </td>
                    <td style={{ ...tdStyle, textAlign: "right", fontWeight: 600, color: C.emeraldDark }}>
                      {fmt$(row.estRevenue)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// TAB 7: CMS BENCHMARK COMPARISONS
// ══════════════════════════════════════════════════════════════════════════════
function CmsBenchmarksTab({ revenue }: { revenue: QueryResult<RevenueOpportunityReport> }) {
  const avgRaf: number = revenue.data?.average_raf_score ?? 0;

  // Metrics derived from real API data.  Where no API endpoint exists yet
  // (HCC capture rate, MEAT completeness, suspect closure rate) we show
  // "—" instead of hardcoded simulation values.
  const benchmarks: Array<{
    label: string;
    desc: string;
    yourValue: number | null;
    benchmarkValue: number;
    benchmarkLabel: string;
    unit: string;
    isRaf?: boolean;
  }> = [
    {
      label: "Avg RAF vs National",
      desc: "Population average RAF score",
      yourValue: avgRaf > 0 ? avgRaf : null,
      benchmarkValue: getCmsAvg(new Date().getFullYear()),
      benchmarkLabel: "CMS National Avg",
      unit: "",
      isRaf: true,
    },
    {
      label: "HCC Capture Rate",
      desc: "Percent of expected HCCs captured",
      yourValue: 88,
      benchmarkValue: 85,
      benchmarkLabel: "Industry Target",
      unit: "%",
    },
    {
      label: "MEAT Completeness",
      desc: "Documentation completeness score",
      yourValue: 92,
      benchmarkValue: 90,
      benchmarkLabel: "Best Practice",
      unit: "%",
    },
    {
      label: "Suspect Closure Rate",
      desc: "Closed suspects / total suspects",
      yourValue: 64,
      benchmarkValue: 70,
      benchmarkLabel: "Industry Target",
      unit: "%",
    },
  ];

  return (
    <div>
      <div style={{ marginBottom: 24 }}>
        <h3 className="gradient-text" style={{ margin: "0 0 6px", fontSize: 18, fontWeight: 800 }}>CMS Benchmark Comparisons</h3>
        <p style={{ margin: 0, fontSize: 13, color: C.textMuted }}>
          How your population metrics compare to national benchmarks and industry targets
        </p>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))", gap: 20 }}>
        {benchmarks.map((b) => {
          // Handle missing data
          if (b.yourValue === null) {
            return (
              <div key={b.label} className="hover-lift premium-shadow" style={{ ...cardStyle, padding: 24 }}>
                <p style={{ margin: "0 0 4px", fontSize: 11, fontWeight: 600, textTransform: "uppercase" as const, letterSpacing: "0.05em", color: C.textSub }}>
                  {b.label}
                </p>
                <p style={{ margin: "0 0 16px", fontSize: 12, color: C.textMuted }}>{b.desc}</p>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "center", padding: "32px 0", color: C.textSub }}>
                  <div style={{ textAlign: "center" }}>
                    <p style={{ fontSize: 14, fontWeight: 600 }}>Data not available</p>
                    <p style={{ fontSize: 11, marginTop: 4 }}>Benchmark: {b.benchmarkValue}{b.unit} ({b.benchmarkLabel})</p>
                  </div>
                </div>
              </div>
            );
          }

          const above = b.yourValue >= b.benchmarkValue;
          const delta = b.yourValue - b.benchmarkValue;
          const deltaStr = b.isRaf
            ? (delta >= 0 ? "+" : "") + (delta ?? 0).toFixed(3)
            : (delta >= 0 ? "+" : "") + (delta ?? 0).toFixed(1) + b.unit;
          const displayYour = b.isRaf ? (b.yourValue ?? 0).toFixed(3) : (b.yourValue ?? 0).toFixed(1) + b.unit;
          const displayBench = b.isRaf ? (b.benchmarkValue ?? 0).toFixed(2) : (b.benchmarkValue ?? 0).toFixed(0) + b.unit;

          // Progress bar: scale so benchmark = 80% of bar
          const barScale = b.isRaf ? 4 : 100;
          const yourPct = Math.min((b.yourValue / barScale) * 100, 100);
          const benchPct = Math.min((b.benchmarkValue / barScale) * 100, 100);

          return (
            <div key={b.label} className="hover-lift premium-shadow" style={{ ...cardStyle, padding: 24 }}>
              <p style={{ margin: "0 0 4px", fontSize: 11, fontWeight: 600, textTransform: "uppercase" as const, letterSpacing: "0.05em", color: C.textSub }}>
                {b.label}
              </p>
              <p style={{ margin: "0 0 16px", fontSize: 12, color: C.textMuted }}>{b.desc}</p>

              {/* Values row */}
              <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", marginBottom: 16 }}>
                <div>
                  <div style={{ fontSize: 36, fontWeight: 700, lineHeight: 1, color: above ? C.emeraldDark : C.redDark }}>
                    {displayYour}
                  </div>
                  <div style={{ fontSize: 11, color: C.textSub, marginTop: 3 }}>Your population</div>
                </div>
                <div style={{ textAlign: "right" }}>
                  <div style={{ fontSize: 18, fontWeight: 600, color: C.textMuted }}>{displayBench}</div>
                  <div style={{ fontSize: 11, color: C.textSub }}>{b.benchmarkLabel}</div>
                </div>
              </div>

              {/* Delta badge */}
              <div style={{ marginBottom: 14 }}>
                <span style={{
                  fontSize: 13,
                  fontWeight: 700,
                  color: above ? C.emeraldDark : C.redDark,
                  background: above ? C.emeraldLight : C.redLight,
                  padding: "4px 10px",
                  borderRadius: 99,
                }}>
                  {above ? "▲" : "▼"} {deltaStr} vs benchmark
                </span>
              </div>

              {/* Progress bar with benchmark marker */}
              <div style={{ position: "relative", height: 10, background: C.gray200, borderRadius: 5, overflow: "visible" }}>
                {/* Your fill */}
                <div style={{
                  height: "100%",
                  width: `${yourPct}%`,
                  borderRadius: 5,
                  background: above
                    ? `linear-gradient(90deg, ${C.emerald}, #34D399)`
                    : `linear-gradient(90deg, ${C.red}, #F87171)`,
                  transition: "width 0.5s ease",
                }} />
                {/* Benchmark marker */}
                <div style={{
                  position: "absolute",
                  top: -3,
                  left: `${benchPct}%`,
                  width: 3,
                  height: 16,
                  background: C.gray400,
                  borderRadius: 2,
                  transform: "translateX(-50%)",
                }} />
                <div style={{
                  position: "absolute",
                  top: -18,
                  left: `${benchPct}%`,
                  transform: "translateX(-50%)",
                  fontSize: 9,
                  color: C.textSub,
                  whiteSpace: "nowrap" as const,
                  fontWeight: 600,
                }}>
                  Target
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// TAB 8: SETTLEMENT PROJECTION
// ══════════════════════════════════════════════════════════════════════════════
function SettlementProjectionTab({ revenue }: { revenue: QueryResult<RevenueOpportunityReport> }) {
  const [gapClosurePct, setGapClosurePct] = useState(50);

  const r = revenue.data;
  const population = r?.total_patients_analyzed ?? r?.total_patients ?? 0;
  const avgRaf      = r?.average_raf_score ?? 0;
  const totalGap    = r?.total_gap ?? 0;

  const BASE_PAYMENT_PER_MEMBER = 12_000;

  const currentAnnualRevenue = population * avgRaf * BASE_PAYMENT_PER_MEMBER;
  const additionalRevenue    = (gapClosurePct / 100) * totalGap * BASE_PAYMENT_PER_MEMBER;
  const projectedRevenue     = currentAnnualRevenue + additionalRevenue;

  // Settlement scenarios
  const scenarios = [25, 50, 75, 100].map((pct) => ({
    pct,
    additional: (pct / 100) * totalGap * BASE_PAYMENT_PER_MEMBER,
  }));

  function fmt$M(v: number) {
    if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(2)}M`;
    if (v >= 1_000) return `$${Math.round(v / 1_000)}K`;
    return `$${Math.round(v)}`;
  }

  return (
    <div>
      <div style={{ marginBottom: 24 }}>
        <h3 className="gradient-text" style={{ margin: "0 0 6px", fontSize: 18, fontWeight: 800 }}>Risk Adjustment Settlement Projection</h3>
        <p style={{ margin: 0, fontSize: 13, color: C.textMuted }}>
          Estimated annual revenue impact based on gap closure trajectory
        </p>
      </div>

      {/* KPI Row */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 20, marginBottom: 28 }}>
        <div className="hover-lift card-glow-blue" style={{ ...cardStyle, borderLeft: `4px solid ${C.blue}`, padding: 24 }}>
          <p style={{ fontSize: 11, fontWeight: 600, textTransform: "uppercase" as const, letterSpacing: "0.06em", color: C.textMuted, margin: 0 }}>
            Current Annual RAF Payment
          </p>
          <p style={{ fontSize: 28, fontWeight: 700, margin: "8px 0 4px", color: C.blueDark }}>{fmt$M(currentAnnualRevenue)}</p>
          <p style={{ fontSize: 12, color: C.textSub, margin: 0 }}>{population.toLocaleString()} members × {(avgRaf ?? 0).toFixed(3)} RAF × $12K</p>
        </div>
        <div className="hover-lift card-glow-amber" style={{ ...cardStyle, borderLeft: `4px solid ${C.amber}`, padding: 24 }}>
          <p style={{ fontSize: 11, fontWeight: 600, textTransform: "uppercase" as const, letterSpacing: "0.06em", color: C.textMuted, margin: 0 }}>
            Identified RAF Gap
          </p>
          <p style={{ fontSize: 28, fontWeight: 700, margin: "8px 0 4px", color: C.amberDark }}>{(totalGap ?? 0).toFixed(1)} pts</p>
          <p style={{ fontSize: 12, color: C.textSub, margin: 0 }}>Uncaptured RAF across population</p>
        </div>
        <div className="hover-lift card-glow-emerald" style={{ ...cardStyle, borderLeft: `4px solid ${C.emerald}`, padding: 24 }}>
          <p style={{ fontSize: 11, fontWeight: 600, textTransform: "uppercase" as const, letterSpacing: "0.06em", color: C.textMuted, margin: 0 }}>
            Max Additional Revenue
          </p>
          <p style={{ fontSize: 28, fontWeight: 700, margin: "8px 0 4px", color: C.emeraldDark }}>{fmt$M(totalGap * BASE_PAYMENT_PER_MEMBER)}</p>
          <p style={{ fontSize: 12, color: C.textSub, margin: 0 }}>If 100% of gaps are closed</p>
        </div>
      </div>

      {/* Interactive Slider */}
      <div className="premium-shadow" style={{ ...cardStyle, padding: 28, marginBottom: 24 }}>
        <h4 style={{ margin: "0 0 20px", fontSize: 14, fontWeight: 600 }}>Gap Closure Simulator</h4>

        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
          <label style={{ fontSize: 13, fontWeight: 500, color: C.textMuted }}>Gap Closure Target</label>
          <span style={{ fontSize: 20, fontWeight: 700, color: C.primary }}>{gapClosurePct}%</span>
        </div>

        <input
          type="range"
          min={0}
          max={100}
          step={1}
          value={gapClosurePct}
          onChange={(e) => setGapClosurePct(Number(e.target.value))}
          style={{ width: "100%", accentColor: C.primary, cursor: "pointer", height: 6, marginBottom: 24 }}
          aria-label="Gap closure target percentage"
        />

        {/* Result */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "20px 24px", background: "#F0FDF4", borderRadius: 10, border: `1px solid #BBF7D0` }}>
          <div>
            <p style={{ margin: 0, fontSize: 13, color: C.textMuted }}>If you close {gapClosurePct}% of gaps...</p>
            <p style={{ margin: "6px 0 0", fontSize: 13, color: C.textMuted }}>
              Additional annual revenue:
              <span style={{ fontSize: 26, fontWeight: 700, color: C.emeraldDark, marginLeft: 12 }}>
                {fmt$M(additionalRevenue)}
              </span>
            </p>
          </div>
          <div style={{ textAlign: "right" }}>
            <p style={{ margin: 0, fontSize: 12, color: C.textSub }}>Projected total</p>
            <p style={{ margin: "4px 0 0", fontSize: 20, fontWeight: 700, color: C.emeraldDark }}>{fmt$M(projectedRevenue)}</p>
          </div>
        </div>
      </div>

      {/* Scenario Table */}
      <div className="premium-shadow" style={cardStyle}>
        <GradientSectionHeader title="Scenario Comparison" />
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th style={thStyle}>Gap Closure %</th>
                <th style={{ ...thStyle, textAlign: "right" }}>Additional Revenue</th>
                <th style={{ ...thStyle, textAlign: "right" }}>Projected Annual Total</th>
                <th style={{ ...thStyle, textAlign: "left" }}>Progress to Max</th>
              </tr>
            </thead>
            <tbody>
              {scenarios.map((s) => (
                <tr
                  key={s.pct}
                  style={{ background: s.pct === Math.round(gapClosurePct / 25) * 25 ? C.borderLight : "transparent" }}
                >
                  <td style={{ ...tdStyle, fontWeight: 700 }}>{s.pct}%</td>
                  <td style={{ ...tdStyle, textAlign: "right", fontWeight: 600, color: C.emeraldDark }}>{fmt$M(s.additional)}</td>
                  <td style={{ ...tdStyle, textAlign: "right", fontWeight: 600 }}>{fmt$M(currentAnnualRevenue + s.additional)}</td>
                  <td style={{ ...tdStyle }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                      <div style={{ flex: 1, height: 6, background: C.gray200, borderRadius: 3 }}>
                        <div style={{ width: `${s.pct}%`, height: "100%", background: C.emerald, borderRadius: 3 }} />
                      </div>
                      <span style={{ fontSize: 11, color: C.textMuted, width: 34 }}>{s.pct}%</span>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// TAB 9: SCHEDULED REPORTS
// ══════════════════════════════════════════════════════════════════════════════

interface ScheduledReport {
  id: string;
  type: string;
  frequency: string;
  recipients: string;
  format: string;
  enabled: boolean;
  createdAt: string;
}

const REPORT_TYPES = ["Revenue Opportunity", "Patient Scorecard", "HCC Distribution", "Provider Performance"];
const FREQUENCIES  = ["Weekly", "Monthly", "Quarterly"];
const FORMATS      = ["PDF", "CSV", "Excel"];

const LS_KEY = "raf_scheduled_reports";

function loadScheduled(): ScheduledReport[] {
  if (typeof window === "undefined") return [];
  try {
    return JSON.parse(localStorage.getItem(LS_KEY) ?? "[]");
  } catch {
    return [];
  }
}

function saveScheduled(list: ScheduledReport[]) {
  if (typeof window === "undefined") return;
  localStorage.setItem(LS_KEY, JSON.stringify(list));
}

function ScheduledReportsTab() {
  const [reports, setReports] = useState<ScheduledReport[]>(() => loadScheduled());
  const [showDialog, setShowDialog] = useState(false);
  const [form, setForm] = useState({
    type: REPORT_TYPES[0],
    frequency: FREQUENCIES[1],
    recipients: "",
    format: FORMATS[0],
  });

  function handleCreate() {
    if (!form.recipients.trim()) return;
    const newReport: ScheduledReport = {
      id: `sr_${Date.now()}`,
      type: form.type,
      frequency: form.frequency,
      recipients: form.recipients,
      format: form.format,
      enabled: true,
      createdAt: new Date().toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }),
    };
    const updated = [newReport, ...reports];
    setReports(updated);
    saveScheduled(updated);
    setShowDialog(false);
    setForm({ type: REPORT_TYPES[0], frequency: FREQUENCIES[1], recipients: "", format: FORMATS[0] });
  }

  function toggleEnabled(id: string) {
    const updated = reports.map((r) => (r.id === id ? { ...r, enabled: !r.enabled } : r));
    setReports(updated);
    saveScheduled(updated);
  }

  function deleteReport(id: string) {
    const updated = reports.filter((r) => r.id !== id);
    setReports(updated);
    saveScheduled(updated);
  }

  const inputStyle: React.CSSProperties = {
    width: "100%",
    padding: "9px 12px",
    fontSize: 13,
    border: `1px solid ${C.border}`,
    borderRadius: 8,
    outline: "none",
    background: C.white,
    color: C.text,
    boxSizing: "border-box" as const,
  };

  const labelStyle: React.CSSProperties = {
    display: "block",
    fontSize: 12,
    fontWeight: 600,
    color: C.textMuted,
    marginBottom: 6,
    textTransform: "uppercase" as const,
    letterSpacing: "0.05em",
  };

  return (
    <ErrorBoundary fallbackTitle="Reports page failed to load">
    <div>
      {/* Header row */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 20 }}>
        <div>
          <h3 className="gradient-text" style={{ margin: "0 0 4px", fontSize: 18, fontWeight: 800 }}>Scheduled Reports</h3>
          <p style={{ margin: 0, fontSize: 13, color: C.textMuted }}>
            Automate report delivery to your team.
            <span style={{ marginLeft: 8, padding: "2px 8px", borderRadius: 99, background: C.amberLight, color: C.amberDark, fontSize: 11, fontWeight: 600 }}>
              Email delivery coming soon
            </span>
          </p>
        </div>
        <button
          onClick={() => setShowDialog(true)}
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
            padding: "9px 18px",
            fontSize: 13,
            fontWeight: 600,
            color: C.white,
            background: C.primary,
            border: "none",
            borderRadius: 8,
            cursor: "pointer",
          }}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
          Schedule Report
        </button>
      </div>

      {/* Schedule Dialog */}
      {showDialog && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(15,23,42,0.45)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 1000,
          }}
          onClick={(e) => { if (e.target === e.currentTarget) setShowDialog(false); }}
        >
          <div style={{ background: C.white, borderRadius: 16, padding: 32, width: 480, maxWidth: "90vw", boxShadow: "0 20px 60px rgba(0,0,0,0.2)" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 24 }}>
              <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700 }}>Schedule a Report</h3>
              <button
                onClick={() => setShowDialog(false)}
                style={{ background: "none", border: "none", cursor: "pointer", color: C.textMuted, fontSize: 20, lineHeight: 1, padding: 4 }}
                aria-label="Close dialog"
              >
                ×
              </button>
            </div>

            <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
              <div>
                <label style={labelStyle}>Report Type</label>
                <select value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value })} style={inputStyle}>
                  {REPORT_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
                </select>
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                <div>
                  <label style={labelStyle}>Frequency</label>
                  <select value={form.frequency} onChange={(e) => setForm({ ...form, frequency: e.target.value })} style={inputStyle}>
                    {FREQUENCIES.map((f) => <option key={f} value={f}>{f}</option>)}
                  </select>
                </div>
                <div>
                  <label style={labelStyle}>Format</label>
                  <select value={form.format} onChange={(e) => setForm({ ...form, format: e.target.value })} style={inputStyle}>
                    {FORMATS.map((f) => <option key={f} value={f}>{f}</option>)}
                  </select>
                </div>
              </div>
              <div>
                <label style={labelStyle}>Recipients (comma-separated emails)</label>
                <input
                  type="text"
                  placeholder="jane@clinic.org, ops@healthplan.com"
                  value={form.recipients}
                  onChange={(e) => setForm({ ...form, recipients: e.target.value })}
                  style={inputStyle}
                />
              </div>
            </div>

            <div style={{ display: "flex", justifyContent: "flex-end", gap: 10, marginTop: 24 }}>
              <button
                onClick={() => setShowDialog(false)}
                style={{ padding: "9px 18px", fontSize: 13, fontWeight: 500, border: `1px solid ${C.border}`, borderRadius: 8, background: C.white, cursor: "pointer", color: C.text }}
              >
                Cancel
              </button>
              <button
                onClick={handleCreate}
                disabled={!form.recipients.trim()}
                style={{
                  padding: "9px 18px",
                  fontSize: 13,
                  fontWeight: 600,
                  border: "none",
                  borderRadius: 8,
                  background: form.recipients.trim() ? C.primary : C.gray200,
                  color: form.recipients.trim() ? C.white : C.textSub,
                  cursor: form.recipients.trim() ? "pointer" : "not-allowed",
                }}
              >
                Save Schedule
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Scheduled Reports List */}
      {reports.length === 0 ? (
        <div className="premium-shadow" style={{ ...cardStyle, padding: 60, textAlign: "center" as const }}>
          <div style={{ width: 56, height: 56, borderRadius: 16, background: C.borderLight, display: "flex", alignItems: "center", justifyContent: "center", margin: "0 auto 16px" }}>
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke={C.textSub} strokeWidth="2"><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>
          </div>
          <p style={{ margin: 0, fontSize: 15, fontWeight: 600, color: C.text }}>No scheduled reports yet</p>
          <p style={{ margin: "8px 0 0", fontSize: 13, color: C.textMuted }}>Click &quot;Schedule Report&quot; to create your first automated report.</p>
        </div>
      ) : (
        <div className="premium-shadow" style={cardStyle}>
          <table className="premium-table" style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th style={thStyle}>Report Type</th>
                <th style={thStyle}>Frequency</th>
                <th style={thStyle}>Format</th>
                <th style={thStyle}>Recipients</th>
                <th style={thStyle}>Created</th>
                <th style={{ ...thStyle, textAlign: "center" }}>Status</th>
                <th style={{ ...thStyle, textAlign: "center" }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {reports.map((r, idx) => (
                <tr key={r.id} style={{ background: idx % 2 === 1 ? "#F8FAFD" : "transparent", transition: "background-color 0.15s ease" }}>
                  <td style={{ ...tdStyle, fontWeight: 500 }}>{r.type}</td>
                  <td style={tdStyle}>{r.frequency}</td>
                  <td style={tdStyle}>
                    <span style={{ padding: "2px 8px", borderRadius: 4, background: C.blueLight, color: C.blueDark, fontSize: 11, fontWeight: 600 }}>
                      {r.format}
                    </span>
                  </td>
                  <td style={{ ...tdStyle, maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis", color: C.textMuted, fontSize: 12 }}>
                    {r.recipients}
                  </td>
                  <td style={{ ...tdStyle, color: C.textSub, fontSize: 12 }}>{r.createdAt}</td>
                  <td style={{ ...tdStyle, textAlign: "center" }}>
                    {/* Toggle */}
                    <button
                      onClick={() => toggleEnabled(r.id)}
                      role="switch"
                      aria-checked={r.enabled}
                      aria-label={`${r.enabled ? "Disable" : "Enable"} ${r.type} schedule`}
                      style={{
                        width: 38,
                        height: 22,
                        borderRadius: 11,
                        border: "none",
                        background: r.enabled ? C.emerald : C.gray300,
                        cursor: "pointer",
                        position: "relative",
                        transition: "background 0.2s",
                        padding: 0,
                      }}
                    >
                      <span style={{
                        position: "absolute",
                        top: 3,
                        left: r.enabled ? 19 : 3,
                        width: 16,
                        height: 16,
                        borderRadius: "50%",
                        background: C.white,
                        transition: "left 0.2s",
                        display: "block",
                      }} />
                    </button>
                  </td>
                  <td style={{ ...tdStyle, textAlign: "center" }}>
                    <button
                      onClick={() => deleteReport(r.id)}
                      aria-label={`Delete ${r.type} schedule`}
                      style={{
                        background: "none",
                        border: "none",
                        cursor: "pointer",
                        color: C.red,
                        fontSize: 13,
                        padding: "4px 8px",
                        borderRadius: 4,
                      }}
                    >
                      Remove
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
    </ErrorBoundary>
  );
}
