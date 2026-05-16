"use client";

/**
 * Quality Measures & STARS page
 *
 * Data sources (all real API calls via react-query):
 *   getQualitySummary()   → Summary tab KPIs
 *   getQualityMeasures()  → HEDIS Measures tab table
 *   getStarsEstimate()    → STARS Estimate tab gauge + breakdown
 *   getCareGaps()         → Care Gaps tab patient-level table
 *
 * Usage pattern mirrors /reports/page.tsx
 *
 * perf(rsc): MeasuresTab, StarsTab, CareGapsTab are lazy-loaded via dynamic()
 * so only the active tab's code is parsed on interaction.
 * SummaryTab stays inline (default/first-paint tab).
 */

import React, { useState } from "react";
import dynamic from "next/dynamic";
import { useQuery } from "@tanstack/react-query";
import {
  Star,
  TrendingUp,
  TrendingDown,
  AlertTriangle,
  CheckCircle,
  Activity,
  GitMerge,
  RefreshCw,
} from "lucide-react";
import { StatCard, PageHeader, SectionHeader } from "@/components/healthcare-ui";
import { DataQualityBanner } from "@/components/DataQualityBanner";
import { tokens } from "@/styles/tokens";
import {
  getQualityMeasures,
  getQualitySummary,
  getStarsEstimate,
  getCareGaps,
} from "@/lib/api";
import type {
  QualityMeasure,
  QualitySummary,
} from "@/lib/api";
import { C, T, starsColor, starsLabel, StarsGauge, Spinner, ErrorBox } from "./tabs/_shared";

// ── Lazy-loaded tab panels (only parsed when the tab is first activated) ───────
function TabFallback() {
  return <Spinner label="Loading tab..." />;
}

const MeasuresTabDynamic = dynamic(
  () => import("./tabs/MeasuresTab"),
  { ssr: false, loading: TabFallback },
);

const StarsTabDynamic = dynamic(
  () => import("./tabs/StarsTab"),
  { ssr: false, loading: TabFallback },
);

const CareGapsTabDynamic = dynamic(
  () => import("./tabs/CareGapsTab"),
  { ssr: false, loading: TabFallback },
);

// ── Tabs ──────────────────────────────────────────────────────────────────────
const TABS = ["Summary", "HEDIS Measures", "STARS Estimate", "Care Gaps"] as const;
type TabKey = (typeof TABS)[number];

// ── Summary Tab ───────────────────────────────────────────────────────────────
function SummaryTab({
  summary,
  measures,
}: {
  summary: QualitySummary;
  measures: QualityMeasure[];
}) {
  const aboveBenchmarkPct =
    summary.total_measures > 0
      ? Math.round((summary.measures_above_benchmark / summary.total_measures) * 100)
      : 0;

  const green = measures.filter((m) => m.rate * 100 >= 80).length;
  const amber = measures.filter((m) => m.rate * 100 >= 60 && m.rate * 100 < 80).length;
  const red = measures.filter((m) => m.rate * 100 < 60).length;
  const total = measures.length;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      {/* KPI strip */}
      <div
        className="qs-kpi-strip qs-fade-in"
        style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 18 }}
      >
        <StatCard
          label="Total Measures"
          value={summary.total_measures}
          subtitle={`Measurement year ${summary.year}`}
          icon={<Activity size={20} />}
          color={C.blue}
        />
        <StatCard
          label="Above Benchmark"
          value={`${summary.measures_above_benchmark} / ${summary.total_measures}`}
          subtitle={`${aboveBenchmarkPct}% of tracked measures`}
          icon={<CheckCircle size={20} />}
          color={aboveBenchmarkPct >= 50 ? C.emerald : C.amber}
        />
        <StatCard
          label="Composite Score"
          value={`${((summary.composite_score ?? 0) * 100).toFixed(1)}%`}
          subtitle="Population-weighted avg"
          icon={<GitMerge size={20} />}
          color={C.violet}
        />
        <StatCard
          label="STARS Estimate"
          value={(summary.stars_estimate ?? 0).toFixed(1)}
          subtitle={starsLabel(summary.stars_estimate ?? 0)}
          icon={<Star size={20} />}
          color={starsColor(summary.stars_estimate ?? 0)}
        />
      </div>

      {/* Compliance distribution bar */}
      {total > 0 && (
        <div className="premium-card premium-shadow hover-lift qs-fade-in qs-fade-in-1" style={{ ...T.card, borderRadius: 14 }}>
          <SectionHeader title="Compliance Rate Distribution" icon={<Activity size={18} />} />
          <div style={{ display: "flex", gap: 0, borderRadius: 10, overflow: "hidden", height: 32, marginBottom: 14, boxShadow: "inset 0 1px 3px rgba(0,0,0,0.08)" }}>
            {[
              { pct: (green / total) * 100, color: C.emerald },
              { pct: (amber / total) * 100, color: C.amber },
              { pct: (red / total) * 100, color: C.red },
            ].map((seg, i) => (
              <div
                key={i}
                style={{
                  width: `${seg.pct}%`,
                  background: seg.color,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontSize: 11,
                  fontWeight: 700,
                  color: tokens.white,
                  minWidth: seg.pct > 0 ? 30 : 0,
                }}
              >
                {seg.pct > 8 ? `${Math.round(seg.pct)}%` : ""}
              </div>
            ))}
          </div>
          <div style={{ display: "flex", gap: 20, flexWrap: "wrap" }}>
            {[
              { label: "Meeting target (≥80%)", color: C.emerald, count: green },
              { label: "Near target (60–80%)", color: C.amber, count: amber },
              { label: "Below target (<60%)", color: C.red, count: red },
            ].map((leg) => (
              <div key={leg.label} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: C.textMuted }}>
                <div style={{ width: 10, height: 10, borderRadius: 2, background: leg.color }} />
                <span>
                  <strong style={{ color: C.text }}>{leg.count}</strong> {leg.label}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// PAGE COMPONENT
// ══════════════════════════════════════════════════════════════════════════════
export default function QualityPage() {
  const [activeTab, setActiveTab] = useState<TabKey>("Summary");

  // ── Data queries ─────────────────────────────────────────────────────────
  const summaryQ = useQuery({
    queryKey: ["quality-summary"],
    queryFn: () => getQualitySummary(),
  });

  const measuresQ = useQuery({
    queryKey: ["quality-measures"],
    queryFn: () => getQualityMeasures(),
  });

  const starsQ = useQuery({
    queryKey: ["quality-stars"],
    queryFn: () => getStarsEstimate(),
  });

  const gapsQ = useQuery({
    queryKey: ["quality-gaps"],
    queryFn: () => getCareGaps({ limit: 500 }),
  });

  // ── Derived values for the top header gauge ───────────────────────────────
  const currentStars = starsQ.data?.current_estimate ?? summaryQ.data?.stars_estimate ?? 0;
  const projectedStars = starsQ.data?.projected_estimate ?? currentStars;
  const diff = projectedStars - currentStars;
  const diffUp = diff >= 0;

  function refetchAll() {
    summaryQ.refetch();
    measuresQ.refetch();
    starsQ.refetch();
    gapsQ.refetch();
  }

  // ── Render the active tab content ─────────────────────────────────────────
  function renderTabContent() {
    if (activeTab === "Summary") {
      if (summaryQ.isLoading || measuresQ.isLoading)
        return <Spinner label="Loading quality summary..." />;
      if (summaryQ.isError)
        return <ErrorBox message="Failed to load quality summary." onRetry={() => summaryQ.refetch()} />;
      if (!summaryQ.data) return <ErrorBox message="No summary data available." />;
      return (
        <SummaryTab summary={summaryQ.data} measures={measuresQ.data ?? []} />
      );
    }

    if (activeTab === "HEDIS Measures") {
      if (measuresQ.isLoading) return <Spinner label="Loading HEDIS measures..." />;
      if (measuresQ.isError)
        return <ErrorBox message="Failed to load measures." onRetry={() => measuresQ.refetch()} />;
      const measures = measuresQ.data ?? [];
      if (measures.length === 0)
        return (
          <div
            role="status"
            style={{
              margin: "0 0 16px",
              padding: "16px 20px",
              borderRadius: 10,
              background: tokens.warningSoft,
              border: `1px solid ${tokens.warningBorder}`,
              color: tokens.warningText,
              display: "flex",
              alignItems: "flex-start",
              gap: 12,
              fontSize: 13,
            }}
          >
            <AlertTriangle size={18} style={{ flexShrink: 0, marginTop: 1 }} />
            <div>
              <div style={{ fontWeight: 600, marginBottom: 2 }}>No HEDIS measures available — this is unusual</div>
              <div style={{ fontSize: 12 }}>
                STARS ratings depend on HEDIS measure data. Verify the quality pipeline is running
                and that measure data has been ingested for this plan year.
              </div>
            </div>
          </div>
        );
      return <MeasuresTabDynamic measures={measures} />;
    }

    if (activeTab === "STARS Estimate") {
      if (starsQ.isLoading) return <Spinner label="Loading STARS estimate..." />;
      if (starsQ.isError)
        return <ErrorBox message="Failed to load STARS estimate." onRetry={() => starsQ.refetch()} />;
      if (!starsQ.data)
        return (
          <div
            role="status"
            style={{
              margin: "0 0 16px",
              padding: "16px 20px",
              borderRadius: 10,
              background: tokens.warningSoft,
              border: `1px solid ${tokens.warningBorder}`,
              color: tokens.warningText,
              display: "flex",
              alignItems: "flex-start",
              gap: 12,
              fontSize: 13,
            }}
          >
            <AlertTriangle size={18} style={{ flexShrink: 0, marginTop: 1 }} />
            <div>
              <div style={{ fontWeight: 600, marginBottom: 2 }}>No STARS data available — this is unusual</div>
              <div style={{ fontSize: 12 }}>
                STARS estimates are required for CMS bonus payments and quality bonuses.
                Verify STARS calculation pipeline is configured.
              </div>
            </div>
          </div>
        );
      return <StarsTabDynamic stars={starsQ.data} />;
    }

    if (activeTab === "Care Gaps") {
      if (gapsQ.isLoading) return <Spinner label="Loading care gaps..." />;
      if (gapsQ.isError)
        return <ErrorBox message="Failed to load care gaps." onRetry={() => gapsQ.refetch()} />;
      return (
        <CareGapsTabDynamic
          gaps={gapsQ.data?.gaps ?? []}
          total={gapsQ.data?.total ?? 0}
        />
      );
    }

    return null;
  }

  return (
    <div style={{ background: C.bg, minHeight: "100vh", padding: "36px 44px", overflowX: "hidden" }} className="rci-page-pad-desktop">
      <style>{`
        @keyframes qs-spin { to { transform: rotate(360deg) } }
        @keyframes qs-fadeInUp {
          from { opacity: 0; transform: translateY(16px); }
          to { opacity: 1; transform: translateY(0); }
        }
        @keyframes qs-scaleIn {
          from { opacity: 0; transform: scale(0.95); }
          to { opacity: 1; transform: scale(1); }
        }
        @keyframes qs-starPulse {
          0%, 100% { transform: scale(1); }
          50% { transform: scale(1.15); }
        }
        @keyframes qs-progressGrow {
          from { width: 0%; }
        }
        @keyframes qs-shimmer {
          0% { background-position: -200% 0; }
          100% { background-position: 200% 0; }
        }
        @keyframes qs-gaugeStroke {
          from { stroke-dashoffset: 400; }
          to { stroke-dashoffset: 0; }
        }
        .qs-fade-in { animation: qs-fadeInUp 0.5s cubic-bezier(0.22, 1, 0.36, 1) both; }
        .qs-fade-in-1 { animation-delay: 0.05s; }
        .qs-fade-in-2 { animation-delay: 0.1s; }
        .qs-fade-in-3 { animation-delay: 0.15s; }
        .qs-fade-in-4 { animation-delay: 0.2s; }
        .qs-scale-in { animation: qs-scaleIn 0.4s cubic-bezier(0.22, 1, 0.36, 1) both; }
        @media (max-width: 1024px) {
          .qs-kpi-strip { grid-template-columns: repeat(2, 1fr) !important; }
          .qs-stars-top  { grid-template-columns: 1fr !important; }
        }
        @media (max-width: 640px) {
          .qs-kpi-strip { grid-template-columns: 1fr !important; }
          .rci-page-pad-desktop { padding: 20px 16px !important; }
        }
        .qs-measure-table tr:hover td { background: ${tokens.primarySoft} !important; }
        .qs-tab-btn { cursor: pointer; transition: all 0.2s ease; position: relative; }
        .qs-tab-btn:hover { color: ${tokens.primary} !important; }
        .qs-tab-btn::after {
          content: '';
          position: absolute;
          bottom: -2px;
          left: 50%;
          width: 0;
          height: 2px;
          background: ${tokens.primary};
          transition: all 0.25s cubic-bezier(0.22, 1, 0.36, 1);
          transform: translateX(-50%);
        }
        .qs-tab-btn:hover::after { width: 100%; }
        .qs-tab-active::after { width: 100% !important; }
        .qs-tab-btn:focus-visible { outline: 2px solid ${tokens.primary}; outline-offset: 2px; border-radius: 4px; }
        .qs-star-icon { transition: transform 0.2s ease; }
        .qs-star-icon:hover { animation: qs-starPulse 0.4s ease; }
        .qs-progress-bar { animation: qs-progressGrow 0.8s cubic-bezier(0.22, 1, 0.36, 1) both; }
        .qs-card-enter { animation: qs-fadeInUp 0.4s cubic-bezier(0.22, 1, 0.36, 1) both; }
        .qs-priority-card { transition: transform 0.2s ease, box-shadow 0.2s ease; }
        .qs-priority-card:hover { transform: translateY(-2px); box-shadow: 0 8px 24px rgba(0,0,0,0.08); }
        .qs-gauge-path { animation: qs-gaugeStroke 1.2s cubic-bezier(0.22, 1, 0.36, 1) both; }
      `}</style>

      {/* ── Data quality banner (degraded data is critical on compliance pages) ── */}
      <DataQualityBanner />

      {/* ── Page Header ── */}
      <PageHeader
        title="Quality Measures & STARS"
        subtitle="HEDIS performance tracking, care gap management, and STARS rating estimation"
        icon={<Star size={22} />}
        actions={
          <button
            onClick={refetchAll}
            disabled={summaryQ.isFetching || measuresQ.isFetching || starsQ.isFetching || gapsQ.isFetching}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              padding: "8px 16px",
              border: `1px solid ${C.border}`,
              borderRadius: 8,
              background: C.card,
              color: C.textMuted,
              fontSize: 13,
              fontWeight: 500,
              cursor: "pointer",
              opacity:
                summaryQ.isFetching || measuresQ.isFetching || starsQ.isFetching || gapsQ.isFetching
                  ? 0.6
                  : 1,
            }}
          >
            <RefreshCw size={14} />
            Refresh
          </button>
        }
      />

      {/* ── Top stripe: current STARS summary ── */}
      {currentStars > 0 && (
        <div
          className="premium-card premium-shadow mesh-pattern qs-fade-in"
          style={{
            ...T.card,
            display: "flex",
            alignItems: "center",
            gap: 28,
            background: `linear-gradient(135deg, ${tokens.slate900} 0%, ${tokens.slate800} 50%, ${tokens.slate900} 100%)`,
            border: "1px solid rgba(255,255,255,0.06)",
            marginBottom: 28,
            flexWrap: "wrap",
            borderRadius: 16,
          }}
        >
          <StarsGauge rating={currentStars} />
          <div style={{ flex: 1, minWidth: 200 }}>
            <div style={{ fontSize: 12, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.08em", color: tokens.slate400, marginBottom: 8 }}>
              Estimated STARS Rating
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
              {diffUp ? <TrendingUp size={16} color={tokens.success} /> : <TrendingDown size={16} color={tokens.riskHigh} />}
              <span style={{ color: diffUp ? tokens.success : tokens.riskHigh, fontWeight: 700, fontSize: 14 }}>
                {diffUp ? "+" : ""}{(diff ?? 0).toFixed(2)} projected change
              </span>
            </div>
            {summaryQ.data && (
              <div style={{ fontSize: 12, color: tokens.slate500 }}>
                {summaryQ.data.total_measures} measures tracked &middot; {summaryQ.data.measures_above_benchmark} above benchmark
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── Tab Bar ── */}
      {/* overflow-x: auto lets the strip scroll horizontally on narrow viewports */}
      <div className="qs-fade-in qs-fade-in-2" style={{ overflowX: "auto", WebkitOverflowScrolling: "touch", borderBottom: `2px solid ${C.borderLight}`, marginBottom: 24 } as React.CSSProperties}>
        <div style={{ display: "flex", gap: 0, minWidth: "max-content" }}>
        {TABS.map((tab) => (
          <button
            key={tab}
            className={`qs-tab-btn ${activeTab === tab ? "qs-tab-active" : ""}`}
            onClick={() => setActiveTab(tab)}
            style={{
              padding: "12px 22px",
              fontSize: 14,
              fontWeight: 600,
              color: activeTab === tab ? C.primary : C.textMuted,
              background: activeTab === tab ? `${C.primary}08` : "none",
              border: "none",
              borderBottom: activeTab === tab ? `2px solid ${C.primary}` : "2px solid transparent",
              borderRadius: "8px 8px 0 0",
              marginBottom: -2,
              cursor: "pointer",
              letterSpacing: "0.01em",
              whiteSpace: "nowrap",
            }}
          >
            {tab}
          </button>
        ))}
        </div>
      </div>

      {/* ── Active Tab Content ── */}
      <div key={activeTab} className="qs-fade-in qs-fade-in-3">
        {renderTabContent()}
      </div>
    </div>
  );
}
