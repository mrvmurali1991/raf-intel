"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useMemo } from "react";
import {
  Users,
  CheckCircle,
  TrendingUp,
  DollarSign,
  AlertCircle,
  RefreshCw,
  Calculator,
  Search,
  FileBarChart,
  ChevronRight,
  Heart,
  FileText,
  Stethoscope,
  Syringe,
  Shield,
  BarChart3,
} from "lucide-react";
import {
  getDashboardStats,
  getPopulationSummary,
  getRevenueOpportunity,
  getDataCompleteness,
  getPatientScorecard,
} from "@/lib/api";
import {
  StatCard,
  RiskBadge,
  ProgressBar,
  SectionHeader,
  PageHeader,
} from "@/components/healthcare-ui";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fmt$(v: number): string {
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(1)}M`;
  if (v >= 1_000) return `$${Math.round(v / 1_000)}K`;
  return `$${Math.round(v)}`;
}

function fmtN(v: number): string {
  return v.toLocaleString("en-US");
}

function rafColor(s: number): string {
  if (s >= 2.0) return "#EF4444";
  if (s >= 1.0) return "#F59E0B";
  return "#10B981";
}

function completenessColor(pct: number): string {
  if (pct >= 80) return "#10B981";
  if (pct >= 50) return "#F59E0B";
  return "#EF4444";
}

// ---------------------------------------------------------------------------
// Shared Styles
// ---------------------------------------------------------------------------

const card: React.CSSProperties = {
  background: "#FFFFFF",
  border: "1px solid #E5E7EB",
  borderRadius: 12,
  boxShadow: "0 1px 3px rgba(0,0,0,0.04), 0 1px 2px rgba(0,0,0,0.02)",
  padding: 24,
};

// ---------------------------------------------------------------------------
// Skeleton Primitives
// ---------------------------------------------------------------------------

function Pulse({ w, h, r = 6 }: { w: string | number; h: number; r?: number }) {
  return (
    <div
      style={{
        width: w,
        height: h,
        borderRadius: r,
        background: "#E2E8F0",
        animation: "pulse 1.5s ease-in-out infinite",
      }}
    />
  );
}

function KPISkeleton() {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 20 }}>
      {[1, 2, 3, 4].map((i) => (
        <div key={i} style={card}>
          <Pulse w={100} h={14} />
          <div style={{ height: 12 }} />
          <Pulse w={80} h={32} />
          <div style={{ height: 8 }} />
          <Pulse w={120} h={12} />
        </div>
      ))}
    </div>
  );
}

function CardSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <div style={card}>
      <Pulse w={180} h={18} />
      <div style={{ marginTop: 20, display: "flex", flexDirection: "column", gap: 16 }}>
        {Array.from({ length: rows }).map((_, i) => (
          <div key={i} style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <Pulse w={60} h={14} />
            <Pulse w="100%" h={18} />
            <Pulse w={40} h={14} />
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Dashboard
// ---------------------------------------------------------------------------

export default function DashboardPage() {
  const qc = useQueryClient();

  const { data: stats, isLoading: statsL, error: statsErr } = useQuery({
    queryKey: ["dashboard-stats"],
    queryFn: getDashboardStats,
    retry: 1,
  });

  const { data: pop, isLoading: popL } = useQuery({
    queryKey: ["population-summary"],
    queryFn: getPopulationSummary,
    retry: 1,
  });

  const { data: rev, isLoading: revL } = useQuery({
    queryKey: ["revenue-opportunity"],
    queryFn: () => getRevenueOpportunity(),
    retry: 1,
  });

  const { data: dc, isLoading: dcL } = useQuery({
    queryKey: ["data-completeness"],
    queryFn: getDataCompleteness,
    retry: 1,
  });

  const { data: scorecard, isLoading: scL } = useQuery({
    queryKey: ["patient-scorecard"],
    queryFn: () => getPatientScorecard(),
    retry: 1,
  });

  // Derived values
  const totalPop = stats?.total_patients ?? pop?.total_patients ?? 0;
  const analyzed = rev?.total_patients_analyzed ?? 0;
  const avgRaf = rev?.average_raf_score ?? (stats as any)?.avg_raf_score ?? 0;
  const revenueOpp = rev?.estimated_annual_revenue ?? 0;

  // Risk tiers from distribution
  const distribution = useMemo(() => {
    if (stats?.raf_distribution?.length) return stats.raf_distribution;
    if (pop?.raf_distribution) return pop.raf_distribution;
    return [];
  }, [stats, pop]);

  const tiers = useMemo(() => {
    let high = 0, med = 0, low = 0;
    for (const b of distribution) {
      const r = b.range ?? "";
      const c = b.count ?? 0;
      if (r.includes("2.0") || r.includes("≥ 2") || r.includes(">= 2") || r.includes("> 2") || r.includes("2.5") || r.includes("3")) {
        high += c;
      } else if (r.includes("1.0") || r.includes("1.5") || r.includes("≥ 1") || r.includes(">= 1")) {
        med += c;
      } else {
        low += c;
      }
    }
    const total = high + med + low || 1;
    return { high, med, low, total };
  }, [distribution]);

  // Top opportunities by gap
  const topOpps = useMemo(() => {
    if (!scorecard?.length) return [];
    return [...scorecard]
      .filter((p) => p.gap != null && p.gap > 0)
      .sort((a, b) => (b.gap ?? 0) - (a.gap ?? 0))
      .slice(0, 8);
  }, [scorecard]);

  // Top HCCs
  const topHccs = useMemo(() => {
    if (pop?.top_hccs && Array.isArray(pop.top_hccs)) return pop.top_hccs.slice(0, 10);
    return [];
  }, [pop]);

  const maxHcc = useMemo(() => {
    if (!topHccs.length) return 1;
    return Math.max(...topHccs.map((h: any) => h.patient_count ?? h.count ?? 0), 1);
  }, [topHccs]);

  const handleRefresh = () => qc.invalidateQueries();

  // Error state
  if (statsErr && !stats && !pop) {
    return (
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          minHeight: "60vh",
          gap: 20,
          textAlign: "center",
          padding: 40,
        }}
      >
        <div style={{ background: "#FEF2F2", borderRadius: 16, padding: 24 }}>
          <AlertCircle size={48} color="#EF4444" />
        </div>
        <h2 style={{ fontSize: 20, fontWeight: 700, color: "#1E293B" }}>
          Unable to Load Dashboard
        </h2>
        <p style={{ fontSize: 14, color: "#64748B", maxWidth: 400 }}>
          The analytics service is not responding. Please verify the backend is running and try again.
        </p>
        <button
          onClick={handleRefresh}
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 8,
            padding: "10px 20px",
            border: "1px solid #E5E7EB",
            borderRadius: 8,
            background: "#FFFFFF",
            color: "#1E293B",
            fontSize: 14,
            fontWeight: 500,
            cursor: "pointer",
          }}
        >
          <RefreshCw size={16} />
          Retry
        </button>
      </div>
    );
  }

  return (
    <div style={{ background: "#F8FAFC", minHeight: "100vh", padding: "32px 40px" }}>
      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.4; }
        }
        @media (max-width: 1024px) {
          .kpi-strip { grid-template-columns: repeat(2, 1fr) !important; }
          .row-60-40 { grid-template-columns: 1fr !important; }
          .row-50-50 { grid-template-columns: 1fr !important; }
          .actions-grid { grid-template-columns: 1fr !important; }
        }
        @media (max-width: 640px) {
          .kpi-strip { grid-template-columns: 1fr !important; }
        }
      `}</style>

      {/* ── Page Header ── */}
      <PageHeader
        title="Population Overview"
        subtitle={`Clinical analysis summary as of ${new Date().toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric" })}`}
        actions={
          <button
            onClick={handleRefresh}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              padding: "8px 16px",
              border: "1px solid #E5E7EB",
              borderRadius: 8,
              background: "#FFFFFF",
              color: "#64748B",
              fontSize: 13,
              fontWeight: 500,
              cursor: "pointer",
            }}
          >
            <RefreshCw size={14} />
            Refresh
          </button>
        }
      />

      {/* ── Row 1: KPI Strip ── */}
      {(statsL && revL) ? (
        <KPISkeleton />
      ) : (
        <div
          className="kpi-strip"
          style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 20, marginBottom: 24 }}
        >
          <StatCard
            label="Total Population"
            value={fmtN(totalPop)}
            subtitle="Patients in system"
            icon={<Users size={20} />}
            color="#3B82F6"
          />
          <StatCard
            label="Patients Analyzed"
            value={fmtN(analyzed)}
            subtitle={totalPop > 0 ? `${Math.round((analyzed / totalPop) * 100)}% coverage` : "No data"}
            icon={<CheckCircle size={20} />}
            color="#10B981"
          />
          <StatCard
            label="Average RAF Score"
            value={avgRaf > 0 ? avgRaf.toFixed(3) : "--"}
            subtitle={avgRaf < 1.0 ? "Below average risk" : avgRaf < 1.5 ? "Moderate risk" : "High risk"}
            icon={<TrendingUp size={20} />}
            color={rafColor(avgRaf)}
          />
          <StatCard
            label="Revenue Opportunity"
            value={revenueOpp > 0 ? fmt$(revenueOpp) : "--"}
            subtitle="Estimated annual gap"
            icon={<DollarSign size={20} />}
            color="#10B981"
          />
        </div>
      )}

      {/* ── Row 2: Risk Distribution (60%) + Top Opportunities (40%) ── */}
      <div
        className="row-60-40"
        style={{ display: "grid", gridTemplateColumns: "3fr 2fr", gap: 20, marginBottom: 24 }}
      >
        {/* Left: Risk Distribution */}
        {(statsL && popL) ? (
          <CardSkeleton rows={4} />
        ) : (
          <div style={card}>
            <SectionHeader
              title="Population Risk Stratification"
              icon={<BarChart3 size={18} />}
            />

            {/* Stacked horizontal bar */}
            {tiers.total > 1 && (
              <div style={{ marginBottom: 24 }}>
                <div
                  style={{
                    display: "flex",
                    height: 32,
                    borderRadius: 8,
                    overflow: "hidden",
                    background: "#F1F5F9",
                  }}
                >
                  {tiers.high > 0 && (
                    <div
                      style={{
                        width: `${(tiers.high / tiers.total) * 100}%`,
                        background: "#EF4444",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        color: "#FFF",
                        fontSize: 11,
                        fontWeight: 700,
                        minWidth: 24,
                      }}
                    >
                      {Math.round((tiers.high / tiers.total) * 100)}%
                    </div>
                  )}
                  {tiers.med > 0 && (
                    <div
                      style={{
                        width: `${(tiers.med / tiers.total) * 100}%`,
                        background: "#F59E0B",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        color: "#FFF",
                        fontSize: 11,
                        fontWeight: 700,
                        minWidth: 24,
                      }}
                    >
                      {Math.round((tiers.med / tiers.total) * 100)}%
                    </div>
                  )}
                  {tiers.low > 0 && (
                    <div
                      style={{
                        width: `${(tiers.low / tiers.total) * 100}%`,
                        background: "#10B981",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        color: "#FFF",
                        fontSize: 11,
                        fontWeight: 700,
                        minWidth: 24,
                      }}
                    >
                      {Math.round((tiers.low / tiers.total) * 100)}%
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* Tier cards */}
            <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12 }}>
              {[
                { label: "High Risk", desc: "RAF >= 2.0", count: tiers.high, color: "#EF4444", bg: "#FEF2F2" },
                { label: "Medium Risk", desc: "RAF 1.0 - 2.0", count: tiers.med, color: "#F59E0B", bg: "#FFFBEB" },
                { label: "Low Risk", desc: "RAF < 1.0", count: tiers.low, color: "#10B981", bg: "#F0FDF4" },
              ].map((t) => (
                <div
                  key={t.label}
                  style={{
                    background: t.bg,
                    border: `1px solid ${t.color}25`,
                    borderRadius: 10,
                    padding: 16,
                    textAlign: "center",
                  }}
                >
                  <div
                    style={{
                      width: 10,
                      height: 10,
                      borderRadius: 5,
                      background: t.color,
                      margin: "0 auto 8px",
                    }}
                  />
                  <div style={{ fontSize: 13, fontWeight: 600, color: t.color }}>{t.label}</div>
                  <div style={{ fontSize: 24, fontWeight: 700, color: "#1E293B", margin: "4px 0" }}>
                    {fmtN(t.count)}
                  </div>
                  <div style={{ fontSize: 11, color: "#64748B" }}>
                    {tiers.total > 0 ? `${Math.round((t.count / tiers.total) * 100)}%` : "0%"} of population
                  </div>
                  <div style={{ fontSize: 10, color: "#94A3B8", marginTop: 2 }}>{t.desc}</div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Right: Top Revenue Opportunities */}
        {scL ? (
          <CardSkeleton rows={8} />
        ) : (
          <div style={card}>
            <SectionHeader
              title="Top Revenue Opportunities"
              icon={<DollarSign size={18} />}
            />
            {topOpps.length === 0 ? (
              <div style={{ color: "#94A3B8", fontSize: 14, padding: "24px 0", textAlign: "center" }}>
                No gap data available. Run clinical analysis first.
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
                {topOpps.map((p, i) => (
                  <Link
                    key={p.pid}
                    href={`/patients/${p.pid}`}
                    style={{ textDecoration: "none", color: "inherit" }}
                  >
                    <div
                      style={{
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "space-between",
                        padding: "10px 8px",
                        borderRadius: 6,
                        cursor: "pointer",
                        borderBottom: i < topOpps.length - 1 ? "1px solid #F1F5F9" : "none",
                        transition: "background 0.15s",
                      }}
                      onMouseEnter={(e) => (e.currentTarget.style.background = "#F8FAFC")}
                      onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
                    >
                      <div style={{ display: "flex", alignItems: "center", gap: 10, flex: 1, minWidth: 0 }}>
                        <span
                          style={{
                            width: 22,
                            height: 22,
                            borderRadius: 6,
                            background: "#F1F5F9",
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "center",
                            fontSize: 11,
                            fontWeight: 600,
                            color: "#94A3B8",
                            flexShrink: 0,
                          }}
                        >
                          {i + 1}
                        </span>
                        <span
                          style={{
                            fontSize: 13,
                            fontWeight: 500,
                            color: "#1E293B",
                            overflow: "hidden",
                            textOverflow: "ellipsis",
                            whiteSpace: "nowrap",
                          }}
                        >
                          {p.name}
                        </span>
                        <span
                          style={{
                            fontSize: 11,
                            fontWeight: 600,
                            padding: "2px 6px",
                            borderRadius: 4,
                            background: "#F1F5F9",
                            color: "#64748B",
                            flexShrink: 0,
                          }}
                        >
                          {p.billing_raf != null ? p.billing_raf.toFixed(2) : "--"}
                        </span>
                      </div>
                      <div style={{ display: "flex", alignItems: "center", gap: 12, flexShrink: 0 }}>
                        <span
                          style={{
                            fontSize: 12,
                            fontWeight: 700,
                            color: "#EF4444",
                          }}
                        >
                          +{(p.gap ?? 0).toFixed(2)}
                        </span>
                        <span
                          style={{
                            fontSize: 13,
                            fontWeight: 700,
                            color: "#10B981",
                          }}
                        >
                          {fmt$(p.revenue_opportunity ?? 0)}
                        </span>
                        <ChevronRight size={14} color="#CBD5E1" />
                      </div>
                    </div>
                  </Link>
                ))}
                <Link
                  href="/reports"
                  style={{
                    display: "block",
                    textAlign: "center",
                    fontSize: 13,
                    fontWeight: 600,
                    color: "#2563EB",
                    textDecoration: "none",
                    padding: "12px 0 0",
                    marginTop: 4,
                  }}
                >
                  View All Opportunities &rarr;
                </Link>
              </div>
            )}
          </div>
        )}
      </div>

      {/* ── Row 3: HCC Distribution (50%) + Data Completeness (50%) ── */}
      <div
        className="row-50-50"
        style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20, marginBottom: 24 }}
      >
        {/* Left: HCC Distribution */}
        {popL ? (
          <CardSkeleton rows={10} />
        ) : (
          <div style={card}>
            <SectionHeader title="Most Common HCC Codes" icon={<Heart size={18} />} count={topHccs.length} />
            {topHccs.length === 0 ? (
              <div style={{ color: "#94A3B8", fontSize: 14, padding: "24px 0", textAlign: "center" }}>
                No HCC data available. Run clinical analysis first.
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                {topHccs.map((hcc: any, idx: number) => {
                  const count = hcc.patient_count ?? hcc.count ?? 0;
                  const pct = Math.round((count / maxHcc) * 100);
                  return (
                    <div key={idx} style={{ display: "flex", alignItems: "center", gap: 10 }}>
                      <span
                        style={{
                          width: 64,
                          fontSize: 12,
                          fontWeight: 700,
                          color: "#2563EB",
                          flexShrink: 0,
                        }}
                      >
                        {hcc.hcc_code ?? hcc.code ?? `HCC ${idx + 1}`}
                      </span>
                      <div
                        style={{
                          flex: 1,
                          height: 22,
                          borderRadius: 4,
                          background: "#F1F5F9",
                          overflow: "hidden",
                          position: "relative",
                        }}
                      >
                        <div
                          style={{
                            height: "100%",
                            width: `${pct}%`,
                            borderRadius: 4,
                            background: "linear-gradient(90deg, #3B82F6, #2563EB)",
                            transition: "width 0.4s ease",
                            minWidth: count > 0 ? 4 : 0,
                          }}
                        />
                        {hcc.description && (
                          <span
                            style={{
                              position: "absolute",
                              left: 8,
                              top: 0,
                              height: "100%",
                              display: "flex",
                              alignItems: "center",
                              fontSize: 10,
                              color: pct > 40 ? "#FFFFFF" : "#64748B",
                              overflow: "hidden",
                              textOverflow: "ellipsis",
                              whiteSpace: "nowrap",
                              maxWidth: "80%",
                            }}
                          >
                            {hcc.description}
                          </span>
                        )}
                      </div>
                      <span
                        style={{
                          width: 32,
                          fontSize: 12,
                          fontWeight: 600,
                          color: "#1E293B",
                          textAlign: "right",
                          flexShrink: 0,
                        }}
                      >
                        {count}
                      </span>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        )}

        {/* Right: Data Completeness */}
        {dcL ? (
          <CardSkeleton rows={6} />
        ) : (
          <div style={card}>
            <SectionHeader title="EMR Data Coverage" icon={<FileText size={18} />} />
            {!dc ? (
              <div style={{ color: "#94A3B8", fontSize: 14, padding: "24px 0", textAlign: "center" }}>
                No completeness data available.
              </div>
            ) : (() => {
              const total = dc.total_patients || 1;
              const overall = dc.completeness_score ?? 0;
              const items = [
                { label: "Billing Data", value: dc.patients_with_billing ?? 0, icon: DollarSign, color: "#3B82F6" },
                { label: "Problem Lists", value: dc.patients_with_problems ?? 0, icon: Heart, color: "#EF4444" },
                { label: "Clinical Notes", value: dc.patients_with_clinical_notes ?? 0, icon: FileText, color: "#8B5CF6" },
                { label: "Vitals", value: dc.patients_with_vitals ?? 0, icon: Stethoscope, color: "#10B981" },
                { label: "Immunizations", value: dc.patients_with_immunizations ?? 0, icon: Syringe, color: "#F59E0B" },
                { label: "Insurance", value: dc.patients_with_insurance ?? 0, icon: Shield, color: "#06B6D4" },
              ];
              return (
                <div>
                  {/* Overall score */}
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      gap: 12,
                      padding: "16px 0 24px",
                      borderBottom: "1px solid #F1F5F9",
                      marginBottom: 20,
                    }}
                  >
                    <span
                      style={{
                        fontSize: 48,
                        fontWeight: 800,
                        color: completenessColor(overall),
                        lineHeight: 1,
                      }}
                    >
                      {Math.round(overall)}
                    </span>
                    <div>
                      <div style={{ fontSize: 16, fontWeight: 600, color: completenessColor(overall) }}>%</div>
                      <div style={{ fontSize: 11, color: "#94A3B8", fontWeight: 500 }}>Overall</div>
                    </div>
                  </div>

                  {/* Per-type bars */}
                  <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                    {items.map((item) => {
                      const pct = Math.round((item.value / total) * 100);
                      const Icon = item.icon;
                      return (
                        <div key={item.label}>
                          <div
                            style={{
                              display: "flex",
                              alignItems: "center",
                              justifyContent: "space-between",
                              marginBottom: 6,
                            }}
                          >
                            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                              <Icon size={14} color={item.color} />
                              <span style={{ fontSize: 13, color: "#475569", fontWeight: 500 }}>{item.label}</span>
                            </div>
                            <span style={{ fontSize: 12, color: "#94A3B8", fontWeight: 500 }}>
                              {item.value}/{total} ({pct}%)
                            </span>
                          </div>
                          <ProgressBar
                            value={pct}
                            color={completenessColor(pct)}
                            showPercent={false}
                            height={6}
                          />
                        </div>
                      );
                    })}
                  </div>
                </div>
              );
            })()}
          </div>
        )}
      </div>

      {/* ── Row 4: Quick Actions ── */}
      <div
        className="actions-grid"
        style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 16 }}
      >
        {[
          {
            href: "/analysis",
            label: "Analyze Patients",
            desc: "Run clinical analysis for all patients",
            icon: Calculator,
            color: "#3B82F6",
            bg: "#EFF6FF",
          },
          {
            href: "/suspects",
            label: "Review Suspects",
            desc: "Identify and review suspect conditions",
            icon: Search,
            color: "#F59E0B",
            bg: "#FFFBEB",
          },
          {
            href: "/reports",
            label: "View Reports",
            desc: "Revenue opportunity and audit reports",
            icon: FileBarChart,
            color: "#10B981",
            bg: "#F0FDF4",
          },
        ].map((action) => {
          const Icon = action.icon;
          return (
            <Link key={action.href} href={action.href} style={{ textDecoration: "none" }}>
              <div
                style={{
                  ...card,
                  borderLeft: `3px solid ${action.color}`,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  cursor: "pointer",
                  transition: "box-shadow 0.15s, transform 0.15s",
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.boxShadow = "0 4px 12px rgba(0,0,0,0.08)";
                  e.currentTarget.style.transform = "translateY(-1px)";
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.boxShadow = "0 1px 3px rgba(0,0,0,0.04), 0 1px 2px rgba(0,0,0,0.02)";
                  e.currentTarget.style.transform = "translateY(0)";
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
                  <div
                    style={{
                      background: action.bg,
                      borderRadius: 10,
                      padding: 10,
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                    }}
                  >
                    <Icon size={20} color={action.color} />
                  </div>
                  <div>
                    <div style={{ fontSize: 14, fontWeight: 600, color: "#1E293B" }}>{action.label}</div>
                    <div style={{ fontSize: 12, color: "#94A3B8", marginTop: 2 }}>{action.desc}</div>
                  </div>
                </div>
                <ChevronRight size={18} color="#CBD5E1" />
              </div>
            </Link>
          );
        })}
      </div>
    </div>
  );
}
