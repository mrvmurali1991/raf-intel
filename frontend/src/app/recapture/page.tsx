"use client";

import React, { useState, useMemo } from "react";
import { usePaymentYear, useIsHistoricalPY } from "@/contexts/payment-year-context";
import { HistoricalPYBanner } from "@/components/HistoricalPYBanner";
import PageAlerts from "@/components/PageAlerts";
import dynamic from "next/dynamic";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { RefreshCw, Download, Calendar, Search, ChevronLeft, ChevronRight, ArrowUpDown, AlertTriangle } from "lucide-react";
import { getRecaptureGapsReport, getRevenueOpportunity, useMetricFormula } from "@/lib/api";
import { PageHeader, EmptyState } from "@/components/healthcare-ui";
import { MetricCard } from "@/components/ui/metric-card";
import FeatureFlag from "@/components/FeatureFlag";
import DataQualityBanner from "@/components/DataQualityBanner";
import { tokens } from "@/styles/tokens";
import { KgGapBadge } from "@/components/kg/KgGapBadge";
import { HccChipWithPopover } from "@/components/kg/HccExplainCard";
// Feature-flagged secondary sections are lazy-loaded to defer ~60 kB
// (CfoExecutiveSummary, BonusLeaderboard, OutreachSummaryCards, AuditReadinessCard,
// RecaptureVelocityKpis, RecaptureDecayChart) that are hidden behind feature flags.
const RecaptureFeatureSections = dynamic(
  () => import("./RecaptureFeatureSections"),
  {
    ssr: false,
    loading: () => <div style={{ height: 40 }} />,
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

// Alias tokens for concise inline usage — NO raw hex literals beyond this map.
const colors = {
  primary:    tokens.primary,
  slate900:   tokens.slate900,
  slate600:   tokens.slate600,
  slate400:   tokens.slate400,
  slate200:   tokens.slate200,
  slate100:   tokens.slate100,
  slate50:    tokens.slate50,
  white:      tokens.white,
  red600:     tokens.dangerStrong,
  amber500:   tokens.warningStrong,
  emerald500: tokens.successStrong,
  subtleText: tokens.slate500,
};

// ─── Helpers ────────────────────────────────────────────────────────────────

function daysSince(dateStr: string): number {
  const diff = Date.now() - new Date(dateStr).getTime();
  return Math.floor(diff / (1000 * 60 * 60 * 24));
}

function priorityFromDays(days: number): { label: string; color: string; rank: number; border: string } {
  if (days > 365) return { label: "High", color: colors.red600, rank: 3, border: tokens.dangerStrong };
  if (days >= 180) return { label: "Medium", color: colors.amber500, rank: 2, border: tokens.warningStrong };
  return { label: "Low", color: colors.emerald500, rank: 1, border: tokens.successStrong };
}

function formatCurrency(n: number): string {
  return "$" + n.toLocaleString("en-US");
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
  });

  // Revenue meta — stale-while-revalidate; provides formula tooltip for CFO.
  const { data: revData } = useQuery({
    queryKey: ["revenue-opportunity", year],
    queryFn: () => getRevenueOpportunity(year),
    staleTime: 5 * 60 * 1000,
  });
  const revenueAtRiskMeta = useMetricFormula(revData as Record<string, unknown> | null | undefined, "estimated_annual_revenue") ?? revData?._meta ?? null;

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
      if (sortBy === "name") return `${a.last_name} ${a.first_name}`.localeCompare(`${b.last_name} ${b.first_name}`);
      return a.condition.localeCompare(b.condition);
    });
    return list;
  }, [enrichedGaps, search, sortBy]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const paged = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  // Reset page on filter change
  React.useEffect(() => { setPage(1); }, [search, sortBy, year]);

  // ── CSV Export ──────────────────────────────────────────────────────────

  function exportCSV() {
    if (!filtered.length) return;
    const header = "Patient,Condition,ICD-10,Last Coded,Days Since,Priority\n";
    const rows = filtered.map((g) =>
      `"${g.last_name}, ${g.first_name}","${g.condition}","${g.icd_code}","${g.onset_date}",${g.days},${g.priority.label}`
    ).join("\n");
    const blob = new Blob([header + rows], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `recapture-gaps-${year}.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  // ── Render ──────────────────────────────────────────────────────────────

  const thStyle: React.CSSProperties = {
    padding: "12px 14px",
    fontSize: 11,
    fontWeight: 600,
    textTransform: "uppercase",
    letterSpacing: "0.06em",
    color: colors.slate400,
    textAlign: "left",
    borderBottom: `2px solid ${colors.slate200}`,
    whiteSpace: "nowrap",
    background: colors.slate50,
  };

  const tdStyle: React.CSSProperties = {
    padding: "12px 14px",
    fontSize: 13,
    color: colors.slate900,
    borderBottom: `1px solid ${colors.slate100}`,
  };

  if (isLoading) {
    return (
      <div style={{ padding: 32 }}>
        <PageHeader title="Recapture Gaps" subtitle="Loading recapture opportunities…" />
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 16, marginBottom: 24 }}>
          {[1, 2, 3].map((i) => (
            <div key={i} className="premium-card shimmer" style={{ height: 100, borderRadius: 12 }} />
          ))}
        </div>
        <div className="premium-card shimmer" style={{ height: 300, borderRadius: 12 }} />
      </div>
    );
  }

  if (isError || !data) {
    return (
      <div style={{ padding: 32 }}>
        <PageHeader title="Recapture Gaps" />
        <div role="alert" style={{ display: "flex", alignItems: "center", gap: 12, padding: "14px 18px", borderRadius: 10, background: tokens.dangerSoft, border: `1px solid ${tokens.dangerBorder}`, color: tokens.danger, fontSize: 14, marginTop: 16 }}>
          <AlertTriangle size={18} aria-hidden="true" />
          <span style={{ flex: 1 }}>Failed to load recapture data. Please try again.</span>
          <button
            type="button"
            onClick={() => refetch()}
            aria-label="Retry loading recapture data"
            style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "6px 12px", borderRadius: 8, border: `1px solid ${tokens.dangerBorder}`, background: tokens.white, color: tokens.danger, fontSize: 13, fontWeight: 600, cursor: "pointer" }}
          >
            <RefreshCw size={14} aria-hidden="true" /> Retry
          </button>
        </div>
      </div>
    );
  }

  const maxConditionCount = (data.top_conditions ?? []).length > 0
    ? Math.max(...(data.top_conditions ?? []).map((c) => c.gap_count))
    : 1;

  const sortOptions: { key: SortKey; label: string }[] = [
    { key: "priority", label: "Priority" },
    { key: "name", label: "Patient Name" },
    { key: "condition", label: "Condition" },
  ];

  return (
    <div style={{ padding: "20px 16px", maxWidth: 1200, margin: "0 auto", overflowX: "hidden" }} className="rci-page-pad-desktop">
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
            <select
              value={year}
              onChange={(e) => setYear(Number(e.target.value))}
              aria-label="Measurement year"
              style={{
                padding: "8px 12px",
                borderRadius: 8,
                border: `1px solid ${colors.slate200}`,
                fontSize: 13,
                fontWeight: 600,
                color: colors.slate900,
                background: colors.white,
                cursor: "pointer",
              }}
            >
              {Array.from({length: 3}, (_, i) => new Date().getFullYear() - i).map(yr => (
                <option key={yr} value={yr}>{yr}</option>
              ))}
            </select>
          }
        />
      </div>

      {/* Summary Strip — bento 12-col grid: hero "Revenue at Risk" spans 6 cols
          x 2 rows (a true hero tile) with "Gaps" + "Patients Affected" stacking
          to its right at 3 cols each over 2 rows. */}
      <style>{`
        .recapture-bento-summary > div { display: grid; }
        .recapture-bento-summary > div > div { height: 100%; }
        .recapture-bento-summary .recapture-hero-tile .tabular-nums { font-size: 40px !important; }

        /* Responsive overrides handled by Tailwind lg: breakpoint on .recapture-main-row */
      `}</style>
      <div
        className="recapture-bento-summary"
        style={{ display: "grid", gridTemplateColumns: "repeat(12, 1fr)", gridAutoRows: "min-content", gap: 16, marginBottom: 24 }}
      >
        <div className="animate-fade-in stagger-1 recapture-hero-tile" style={{ gridColumn: "span 6", gridRow: "span 2" }}>
          <MetricCard
            label="Estimated Revenue at Risk"
            value={formatCurrency((data.total_gaps ?? 0) * REVENUE_PER_GAP)}
            subtitle="Unrecaptured chronic conditions x prior-year RAF dollars"
            intent="danger"
            icon={<ArrowUpDown size={18} />}
            meta={revenueAtRiskMeta ?? undefined}
            freshness={revData?.last_computed_at ?? undefined}
            labelTestId="revenue-at-risk-label"
            valueTestId="revenue-at-risk-value"
          />
        </div>
        <div className="animate-fade-in stagger-2" style={{ gridColumn: "span 3" }}>
          <MetricCard
            label="Total Recapture Gaps"
            value={(data.total_gaps ?? 0).toLocaleString()}
            intent="warning"
            icon={<RefreshCw size={18} />}
          />
        </div>
        <div className="animate-fade-in stagger-3" style={{ gridColumn: "span 3" }}>
          <MetricCard
            label="Patients Affected"
            value={(data.patients_affected ?? 0).toLocaleString()}
            icon={<Calendar size={18} />}
          />
        </div>
      </div>

      {/* ════════════════════════════════════════════════════════════════════
          MAIN ROW (12-col, 8/4 split): priority patient worklist (left, 8 cols)
          + Top Conditions chart (right, 4 cols). This is the page's primary
          work surface — the bento hero below the summary tiles. Source order
          is Top Conditions -> Worklist, but explicit `gridColumn` placement
          renders them visually as Worklist (cols 1-8) + Top Conditions (9-12).
          Velocity / CFO / bonus / outreach / audit sections render below this
          row, each in its own 12-col grid row.
          ════════════════════════════════════════════════════════════════════ */}
      {/* grid-cols-1 below lg (tablet/mobile: stacked); lg:grid-cols-[2fr_1fr] at 1024px+ (worklist 2fr, top conditions 1fr) */}
      <div
        className="recapture-main-row grid grid-cols-1 lg:grid-cols-[2fr_1fr] gap-4 mb-6 items-start"
        style={{ marginBottom: 24 }}
      >
      {/* Left column: Patient Worklist — appears first in DOM so it stacks on top on mobile */}
      <div
        className="recapture-worklist premium-card animate-slide-up stagger-5"
        style={{ padding: 24, minWidth: 0 }}
      >
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16, flexWrap: "wrap", gap: 12 }}>
          <h3 className="gradient-text" style={{ margin: 0, fontSize: 16, fontWeight: 700 }}>
            Patients Requiring Recapture
          </h3>
          <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
            {/* Search */}
            <div style={{ position: "relative" }}>
              <Search size={14} style={{ position: "absolute", left: 10, top: "50%", transform: "translateY(-50%)", color: colors.slate400 }} />
              <input
                type="text"
                placeholder="Search patient..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                aria-label="Search patients by name"
                style={{
                  padding: "7px 10px 7px 30px",
                  borderRadius: 20,
                  border: `1px solid ${colors.slate200}`,
                  fontSize: 13,
                  color: colors.slate900,
                  width: "min(200px, calc(100vw - 180px))",
                  transition: "border-color 0.2s, box-shadow 0.2s",
                }}
                onFocus={(e) => {
                  e.currentTarget.style.borderColor = colors.primary;
                  e.currentTarget.style.boxShadow = `0 0 0 3px ${colors.primary}1A`;
                }}
                onBlur={(e) => {
                  e.currentTarget.style.borderColor = colors.slate200;
                  e.currentTarget.style.boxShadow = "none";
                }}
              />
            </div>
            {/* Sort Pills */}
            <div style={{ display: "flex", gap: 4, background: colors.slate100, borderRadius: 20, padding: 3 }}>
              {sortOptions.map((opt) => (
                <button
                  key={opt.key}
                  onClick={() => setSortBy(opt.key)}
                  className="btn-press"
                  style={{
                    padding: "5px 12px",
                    borderRadius: 16,
                    border: "none",
                    fontSize: 12,
                    fontWeight: 600,
                    cursor: "pointer",
                    transition: "all 0.2s ease",
                    background: sortBy === opt.key ? colors.primary : "transparent",
                    color: sortBy === opt.key ? colors.white : colors.slate600,
                    boxShadow: sortBy === opt.key ? "0 1px 3px rgba(37,99,235,0.3)" : "none",
                  }}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>
        </div>

        {filtered.length === 0 ? (
          <EmptyState title="No recapture gaps found" description="All chronic conditions have been recaptured for the selected year." />
        ) : (
          <>
            <div style={{ overflowX: "auto", borderRadius: 10, border: `1px solid ${colors.slate200}` }}>
              <table style={{ width: "100%", borderCollapse: "collapse" }} aria-label="Patients requiring recapture">
                <thead>
                  <tr>
                    <th scope="col" style={thStyle}>Patient</th>
                    <th scope="col" style={thStyle}>Condition</th>
                    <th scope="col" style={thStyle}>ICD-10</th>
                    <th scope="col" style={thStyle}>Last Coded</th>
                    <th scope="col" style={thStyle}>Days Since</th>
                    <th scope="col" style={thStyle}>Priority</th>
                  </tr>
                </thead>
                <tbody>
                  {paged.map((g, i) => (
                    <tr
                      key={`${g.pid}-${g.icd_code}-${i}`}
                      tabIndex={0}
                      role="row"
                      aria-label={`${g.last_name}, ${g.first_name} — ${g.condition}, ${g.priority.label} priority`}
                      onClick={() => router.push(`/patients/${g.pid}`)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); router.push(`/patients/${g.pid}`); }
                      }}
                      style={{
                        cursor: "pointer",
                        transition: "all 0.15s ease",
                        borderLeft: `3px solid ${g.priority.border}`,
                        background: i % 2 === 0 ? colors.white : colors.slate50,
                      }}
                      onMouseEnter={(e) => {
                        e.currentTarget.style.background = `${g.priority.border}08`;
                        e.currentTarget.style.transform = "scale(1.002)";
                        e.currentTarget.style.boxShadow = "0 1px 4px rgba(0,0,0,0.06)";
                      }}
                      onMouseLeave={(e) => {
                        e.currentTarget.style.background = i % 2 === 0 ? colors.white : colors.slate50;
                        e.currentTarget.style.transform = "none";
                        e.currentTarget.style.boxShadow = "none";
                      }}
                      onFocus={(e) => { e.currentTarget.style.boxShadow = `inset 0 0 0 2px ${tokens.primary}`; }}
                      onBlur={(e) => { e.currentTarget.style.boxShadow = "none"; }}
                    >
                      <td style={{ ...tdStyle, fontWeight: 600, color: colors.primary }}>
                        {g.last_name}, {g.first_name}
                      </td>
                      <td style={tdStyle}>
                        <span style={{ display: "inline-flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
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
                            <KgGapBadge
                              evidenceType={g.evidence_type ?? "kg_rule"}
                              suspectId={g.id ?? undefined}
                              hccCode={g.hcc_code}
                              patientId={Number(g.pid) || undefined}
                            />
                          </FeatureFlag>
                        </span>
                      </td>
                      <td className="tabular-nums" style={{ ...tdStyle, fontFamily: "monospace", fontSize: 12 }}>{g.icd_code}</td>
                      <td className="tabular-nums" style={{ ...tdStyle, color: colors.subtleText }}>{new Date(g.onset_date).toLocaleDateString()}</td>
                      <td className="tabular-nums" style={{ ...tdStyle, fontWeight: 600 }}>{g.days}</td>
                      <td style={tdStyle}>
                        <span
                          title={
                            g.priority.label === "High" ? "High priority: condition uncoded for >365 days" :
                            g.priority.label === "Medium" ? "Medium priority: condition uncoded 180–365 days" :
                            "Low priority: condition uncoded <180 days"
                          }
                          style={{
                            display: "inline-block",
                            padding: "3px 10px",
                            borderRadius: 999,
                            fontSize: 11,
                            fontWeight: 600,
                            color: g.priority.color,
                            backgroundColor: `${g.priority.color}1A`,
                            cursor: "help",
                          }}
                        >
                          {g.priority.label}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Pagination */}
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: 16, fontSize: 13, color: colors.subtleText }}>
              <span className="tabular-nums">
                Showing {(page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, filtered.length)} of {filtered.length}
              </span>
              <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                <button
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page === 1}
                  className="btn-press"
                  style={{
                    padding: "6px 10px",
                    borderRadius: 6,
                    border: `1px solid ${colors.slate200}`,
                    background: colors.white,
                    cursor: page === 1 ? "not-allowed" : "pointer",
                    opacity: page === 1 ? 0.4 : 1,
                    display: "flex",
                    alignItems: "center",
                    transition: "all 0.15s",
                  }}
                >
                  <ChevronLeft size={14} />
                </button>
                <span className="tabular-nums" style={{ padding: "0 8px", fontWeight: 600, color: colors.slate900 }}>
                  {page} / {totalPages}
                </span>
                <button
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  disabled={page === totalPages}
                  className="btn-press"
                  style={{
                    padding: "6px 10px",
                    borderRadius: 6,
                    border: `1px solid ${colors.slate200}`,
                    background: colors.white,
                    cursor: page === totalPages ? "not-allowed" : "pointer",
                    opacity: page === totalPages ? 0.4 : 1,
                    display: "flex",
                    alignItems: "center",
                    transition: "all 0.15s",
                  }}
                >
                  <ChevronRight size={14} />
                </button>
              </div>
            </div>
          </>
        )}
      </div>

      {/* Right column: Top Conditions chart */}
      {(data.top_conditions ?? []).length > 0 && (
        <div className="recapture-top-conditions premium-card animate-slide-up stagger-4" style={{ padding: 24, minWidth: 0 }}>
          <h3 className="gradient-text" style={{ margin: "0 0 16px", fontSize: 16, fontWeight: 700 }}>
            Most Common Uncaptured Conditions
          </h3>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {(data.top_conditions ?? []).slice(0, 10).map((c, idx) => (
              <div
                key={c.icd_code}
                className="hover-lift"
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 12,
                  padding: "8px 12px",
                  borderRadius: 8,
                  background: idx % 2 === 0 ? colors.slate50 : "transparent",
                  transition: "all 0.2s ease",
                }}
              >
                <span style={{ width: 24, fontSize: 11, fontWeight: 700, color: colors.slate400, flexShrink: 0, textAlign: "center" }}>
                  {idx + 1}
                </span>
                <span style={{ flex: "1 1 120px", minWidth: 0, maxWidth: 220, fontSize: 13, color: colors.slate900, fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {c.condition}
                </span>
                <span style={{ flexShrink: 0, fontSize: 11, fontWeight: 600, color: colors.primary, fontFamily: "monospace" }}>
                  {c.icd_code}
                </span>
                <div style={{ flex: 1, height: 8, borderRadius: 4, background: colors.slate200, overflow: "hidden" }}>
                  <div
                    style={{
                      height: "100%",
                      width: `${(c.gap_count / maxConditionCount) * 100}%`,
                      borderRadius: 4,
                      background: `linear-gradient(90deg, ${tokens.primary}, ${tokens.infoBlue})`,
                      transition: "width 0.6s cubic-bezier(0.4, 0, 0.2, 1)",
                    }}
                  />
                </div>
                <span className="tabular-nums" style={{ width: 40, fontSize: 12, fontWeight: 700, color: colors.slate900, textAlign: "right", flexShrink: 0 }}>
                  {c.gap_count}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      </div>
      {/* ════════════════════════════════════════════════════════════════════
          END MAIN ROW. Below: secondary feature-flag sections, each in its
          own 12-col grid row so they read as full-width bento bands stacked
          beneath the priority worklist.
          ════════════════════════════════════════════════════════════════════ */}

      {/* Feature-flagged secondary sections — lazy-loaded (~60 kB deferred) */}
      <RecaptureFeatureSections year={year} />

      {/* Action Panel — final bento row spans the full 12 columns. */}
      <div
        className="premium-card animate-slide-up stagger-6 bg-gradient-to-br from-muted to-card"
        style={{
          padding: 24,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          flexWrap: "wrap",
          gap: 16,
        }}
      >
        <div>
          <p style={{ margin: 0, fontSize: 13, fontWeight: 600, color: colors.slate900 }}>
            Schedule Wellness Visits
          </p>
          <p style={{ margin: "4px 0 0", fontSize: 12, color: colors.subtleText }}>
            Prioritize patients with high-priority recapture gaps for annual wellness visits to ensure chronic conditions are documented.
          </p>
        </div>
        <button
          onClick={isHistoricalPY ? undefined : exportCSV}
          disabled={isHistoricalPY}
          aria-label="Export recapture gaps to CSV"
          title={isHistoricalPY ? "Disabled in historical view" : undefined}
          className="btn-press"
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            padding: "10px 20px",
            borderRadius: 8,
            border: "none",
            background: isHistoricalPY ? "#D1D5DB" : `linear-gradient(135deg, ${tokens.primary}, ${tokens.primaryDark})`,
            color: colors.white,
            fontSize: 13,
            fontWeight: 600,
            cursor: isHistoricalPY ? "not-allowed" : "pointer",
            opacity: isHistoricalPY ? 0.6 : 1,
            flexShrink: 0,
            boxShadow: "0 2px 8px rgba(37,99,235,0.3)",
            transition: "all 0.2s ease",
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.boxShadow = "0 4px 14px rgba(37,99,235,0.4)";
            e.currentTarget.style.transform = "translateY(-1px)";
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.boxShadow = "0 2px 8px rgba(37,99,235,0.3)";
            e.currentTarget.style.transform = "none";
          }}
        >
          <Download size={14} />
          Export to CSV
        </button>
      </div>
    </div>
  );
}
