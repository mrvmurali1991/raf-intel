"use client";

import React, { useState, useMemo, useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import {
  getRevenueOpportunity,
  getPatientScorecard,
  getHccDistribution,
  getRecaptureGapsReport,
  getDataCompleteness,
} from "@/lib/api";
import { StatCard, ProgressBar, PageHeader, EmptyState, SectionHeader } from "@/components/healthcare-ui";

// ── Constants ─────────────────────────────────────────────────────────────────
const REVENUE_PER_RAF = 10_398.44;
const YEARS = [2024, 2025, 2026];
const TABS = ["Revenue", "Patient Scorecard", "HCC Distribution", "Recapture Gaps", "Data Quality"] as const;
type TabKey = (typeof TABS)[number];

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
  return v.toFixed(d);
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
      const av = a[sortKey] ?? ("" as any);
      const bv = b[sortKey] ?? ("" as any);
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
  padding: "24px 32px 48px",
  fontFamily: "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
  color: C.text,
};

const cardStyle: React.CSSProperties = {
  background: C.card,
  border: `1px solid ${C.border}`,
  borderRadius: 12,
  overflow: "hidden",
};

const thStyle: React.CSSProperties = {
  padding: "10px 14px",
  fontSize: 11,
  fontWeight: 600,
  textTransform: "uppercase" as const,
  letterSpacing: "0.05em",
  color: C.textMuted,
  borderBottom: `2px solid ${C.border}`,
  background: C.borderLight,
  whiteSpace: "nowrap" as const,
  cursor: "pointer",
  userSelect: "none" as const,
};

const tdStyle: React.CSSProperties = {
  padding: "10px 14px",
  fontSize: 13,
  borderBottom: `1px solid ${C.borderLight}`,
  whiteSpace: "nowrap" as const,
};

// ── Loading / Error ───────────────────────────────────────────────────────────
function Spinner({ label }: { label?: string }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: "80px 0", color: C.textMuted }}>
      <div style={{ width: 32, height: 32, border: `3px solid ${C.gray200}`, borderTopColor: C.primary, borderRadius: "50%", animation: "spin 0.8s linear infinite" }} />
      <style>{`@keyframes spin { to { transform: rotate(360deg) } }`}</style>
      <p style={{ marginTop: 12, fontSize: 13 }}>{label ?? "Loading data..."}</p>
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
  const [year, setYear] = useState(2025);
  const [activeTab, setActiveTab] = useState<TabKey>("Revenue");

  // ── Data Queries ──────────────────────────────────────────────────────────
  const revenue = useQuery({ queryKey: ["revenue", year], queryFn: () => getRevenueOpportunity(year) });
  const scorecard = useQuery({ queryKey: ["scorecard", year], queryFn: () => getPatientScorecard(year) });
  const hccDist = useQuery({ queryKey: ["hcc-dist", year], queryFn: () => getHccDistribution(year) });
  const recapture = useQuery({ queryKey: ["recapture", year], queryFn: () => getRecaptureGapsReport(year) });
  const dataQuality = useQuery({ queryKey: ["data-quality"], queryFn: () => getDataCompleteness() });

  return (
    <div style={pageStyle}>
      {/* ── Page Header ──────────────────────────────────────────────────── */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 24 }}>
        <div>
          <h1 style={{ fontSize: 26, fontWeight: 700, margin: 0, letterSpacing: "-0.02em" }}>Analytics &amp; Reports</h1>
          <p style={{ fontSize: 13, color: C.textMuted, marginTop: 4 }}>Population health intelligence and revenue analytics</p>
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
        </div>
      </div>

      {/* ── Tab Bar (underline style) ────────────────────────────────────── */}
      <div style={{ display: "flex", gap: 0, borderBottom: `2px solid ${C.border}`, marginBottom: 28 }}>
        {TABS.map((tab) => {
          const isActive = activeTab === tab;
          return (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              style={{
                padding: "10px 20px",
                fontSize: 13,
                fontWeight: isActive ? 600 : 500,
                color: isActive ? C.primary : C.textMuted,
                background: "transparent",
                border: "none",
                borderBottom: isActive ? `2px solid ${C.primary}` : "2px solid transparent",
                marginBottom: -2,
                cursor: "pointer",
                transition: "all 0.15s ease",
                letterSpacing: "-0.01em",
              }}
            >
              {tab}
            </button>
          );
        })}
      </div>

      {/* ── Tab Content ──────────────────────────────────────────────────── */}
      {activeTab === "Revenue" && <RevenueTab revenue={revenue} scorecard={scorecard} router={router} />}
      {activeTab === "Patient Scorecard" && <ScorecardTab scorecard={scorecard} router={router} />}
      {activeTab === "HCC Distribution" && <HccTab hccDist={hccDist} />}
      {activeTab === "Recapture Gaps" && <RecaptureTab recapture={recapture} router={router} />}
      {activeTab === "Data Quality" && <DataQualityTab dataQuality={dataQuality} />}
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// TAB 1: REVENUE OPPORTUNITY
// ══════════════════════════════════════════════════════════════════════════════
function RevenueTab({ revenue, scorecard, router }: { revenue: any; scorecard: any; router: any }) {
  const r = revenue.data;
  const patients = scorecard.data ?? [];

  const top25 = useMemo(() => {
    return [...patients]
      .filter((p: any) => (p.gap ?? 0) > 0)
      .sort((a: any, b: any) => (b.revenue_opportunity ?? 0) - (a.revenue_opportunity ?? 0))
      .slice(0, 25);
  }, [patients]);

  if (revenue.isLoading || scorecard.isLoading) return <Spinner label="Loading revenue data..." />;
  if (revenue.isError) return <ErrorBox message="Failed to load revenue data" />;

  const totalRevenue = r?.estimated_annual_revenue ?? 0;
  const totalGap = r?.total_gap ?? 0;
  const patientsWithGaps = top25.length;

  return (
    <div>
      {/* KPI Cards */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 20, marginBottom: 28 }}>
        {/* Revenue Card */}
        <div style={{ ...cardStyle, borderLeft: `4px solid ${C.emerald}`, padding: 24 }}>
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
        <div style={{ ...cardStyle, borderLeft: `4px solid ${C.amber}`, padding: 24 }}>
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
        <div style={{ ...cardStyle, borderLeft: `4px solid ${C.blue}`, padding: 24 }}>
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
      <div style={cardStyle}>
        <div style={{ padding: "16px 20px", borderBottom: `1px solid ${C.border}` }}>
          <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600 }}>Top 25 Revenue Opportunities</h3>
          <p style={{ margin: "4px 0 0", fontSize: 12, color: C.textMuted }}>Patients sorted by estimated revenue opportunity</p>
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
              {top25.map((p: any, i: number) => (
                <tr
                  key={p.pid}
                  onClick={() => router.push(`/patients/${p.pid}`)}
                  style={{ cursor: "pointer", transition: "background 0.1s" }}
                  onMouseEnter={(e) => (e.currentTarget.style.background = C.borderLight)}
                  onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
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
function ScorecardTab({ scorecard, router }: { scorecard: any; router: any }) {
  const [search, setSearch] = useState("");
  const [limit, setLimit] = useState(100);
  const patients = scorecard.data ?? [];

  const { sorted, toggle, sortKey, sortDir } = useSortable<Record<string, any>>(patients, "gap", "desc");

  const filtered = useMemo(() => {
    if (!search.trim()) return sorted;
    const q = search.toLowerCase();
    return sorted.filter((p: any) => p.name?.toLowerCase().includes(q));
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
      {/* Search */}
      <div style={{ marginBottom: 16, position: "relative", maxWidth: 340 }}>
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

      <div style={cardStyle}>
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                {colDefs.map((col) => (
                  <th
                    key={col.key}
                    style={{ ...thStyle, textAlign: (col.align as any) ?? "left" }}
                    onClick={() => toggle(col.key as any)}
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
              {visible.map((p: any, i: number) => (
                <tr
                  key={p.pid}
                  onClick={() => router.push(`/patients/${p.pid}`)}
                  style={{ cursor: "pointer", transition: "background 0.1s" }}
                  onMouseEnter={(e) => (e.currentTarget.style.background = C.borderLight)}
                  onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
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
function HccTab({ hccDist }: { hccDist: any }) {
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

  function barBg(rank: number): string {
    if (rank <= 3) return C.redLight;
    if (rank <= 8) return C.amberLight;
    return C.blueLight;
  }

  return (
    <div style={cardStyle}>
      <div style={{ padding: "16px 20px", borderBottom: `1px solid ${C.border}` }}>
        <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600 }}>HCC Distribution — Top 20 by Patient Count</h3>
        <p style={{ margin: "4px 0 0", fontSize: 12, color: C.textMuted }}>Hierarchical Condition Categories across the population</p>
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
function RecaptureTab({ recapture, router }: { recapture: any; router: any }) {
  if (recapture.isLoading) return <Spinner label="Loading recapture gaps..." />;
  if (recapture.isError) return <ErrorBox message="Failed to load recapture data" />;

  const raw = recapture.data ?? {};
  const gaps: any[] = raw.gaps ?? raw.data ?? (Array.isArray(raw) ? raw : []);
  const totalGaps = gaps.length;
  const uniquePatients = new Set(gaps.map((g: any) => g.patient_id ?? g.pid)).size;

  // Top conditions summary
  const conditionMap = new Map<string, { condition: string; icd10: string; count: number }>();
  gaps.forEach((g: any) => {
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
      <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 20, marginBottom: 28 }}>
        <div style={{ ...cardStyle, borderLeft: `4px solid ${C.red}`, padding: 24 }}>
          <p style={{ fontSize: 11, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.06em", color: C.textMuted, margin: 0 }}>Total Gaps</p>
          <p style={{ fontSize: 32, fontWeight: 700, margin: "8px 0 0", color: C.redDark }}>{totalGaps}</p>
        </div>
        <div style={{ ...cardStyle, borderLeft: `4px solid ${C.amber}`, padding: 24 }}>
          <p style={{ fontSize: 11, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.06em", color: C.textMuted, margin: 0 }}>Patients Affected</p>
          <p style={{ fontSize: 32, fontWeight: 700, margin: "8px 0 0", color: C.amberDark }}>{uniquePatients}</p>
        </div>
      </div>

      {/* Top Conditions Table */}
      <div style={{ ...cardStyle, marginBottom: 24 }}>
        <div style={{ padding: "16px 20px", borderBottom: `1px solid ${C.border}` }}>
          <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600 }}>Top Conditions for Recapture</h3>
        </div>
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
              {topConditions.map((c) => (
                <tr key={c.icd10}>
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
      <div style={cardStyle}>
        <div style={{ padding: "16px 20px", borderBottom: `1px solid ${C.border}` }}>
          <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600 }}>All Recapture Gaps</h3>
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
              {gaps.slice(0, 100).map((g: any, i: number) => (
                <tr
                  key={i}
                  style={{ cursor: "pointer", transition: "background 0.1s" }}
                  onMouseEnter={(e) => (e.currentTarget.style.background = C.borderLight)}
                  onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
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
function DataQualityTab({ dataQuality }: { dataQuality: any }) {
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
        <div style={{ ...cardStyle, padding: 32, display: "flex", flexDirection: "column", alignItems: "center", width: 280 }}>
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
            <div key={dt.key} style={{ ...cardStyle, padding: 20 }}>
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
