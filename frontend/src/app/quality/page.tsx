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

import React, { useState, useEffect, useRef } from "react";
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
import { PageHeader } from "@/components/ui/page-header";
import { SectionHeader } from "@/components/ui/section-header";
import { MetricCard } from "@/components/ui/metric-card";
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
    <div className="flex flex-col gap-5">
      {/* KPI strip */}
      <div className="qs-kpi-strip qs-fade-in grid grid-cols-4 gap-[18px]">
        <MetricCard
          label="Total Measures"
          value={summary.total_measures}
          subtitle={`Measurement year ${summary.year}`}
          icon={<Activity size={20} />}
        />
        <MetricCard
          label="Above Benchmark"
          value={`${summary.measures_above_benchmark} / ${summary.total_measures}`}
          subtitle={`${aboveBenchmarkPct}% of tracked measures`}
          icon={<CheckCircle size={20} />}
          intent={aboveBenchmarkPct >= 50 ? "success" : "warning"}
        />
        <MetricCard
          label="Composite Score"
          value={`${((summary.composite_score ?? 0) * 100).toFixed(1)}%`}
          subtitle="Population-weighted avg"
          icon={<GitMerge size={20} />}
        />
        <MetricCard
          label="STARS Estimate"
          value={(summary.stars_estimate ?? 0).toFixed(1)}
          subtitle={starsLabel(summary.stars_estimate ?? 0)}
          icon={<Star size={20} />}
          intent={(summary.stars_estimate ?? 0) >= 4 ? "success" : (summary.stars_estimate ?? 0) >= 3 ? "warning" : "danger"}
        />
      </div>

      {/* Compliance distribution bar */}
      {total > 0 && (
        <div className="premium-card premium-shadow hover-lift qs-fade-in qs-fade-in-1 rounded-xl" style={T.card}>
          <SectionHeader title="Compliance Rate Distribution" icon={<Activity size={18} />} />
          <div className="flex overflow-hidden rounded-lg h-8 mb-3.5" style={{ boxShadow: "inset 0 1px 3px rgba(0,0,0,0.08)" }}>
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
          <div className="flex gap-5 flex-wrap">
            {[
              { label: "Meeting target (≥80%)", color: C.emerald, count: green },
              { label: "Near target (60–80%)", color: C.amber, count: amber },
              { label: "Below target (<60%)", color: C.red, count: red },
            ].map((leg) => (
              <div key={leg.label} className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <div className="w-2.5 h-2.5 rounded-sm" style={{ background: leg.color }} />
                <span>
                  <strong className="text-foreground">{leg.count}</strong> {leg.label}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Empty state when no measures are loaded yet */}
      {total === 0 && (
        <div className="flex items-start gap-3 rounded-lg border border-warning/30 bg-warning/5 p-5 text-sm text-warning-foreground">
          <AlertTriangle size={18} className="flex-shrink-0 mt-0.5" />
          <div>
            <div className="font-semibold mb-0.5">No measure data to display</div>
            <div className="text-xs text-muted-foreground">
              Compliance distribution will appear once HEDIS measures have been ingested for this plan year.
            </div>
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
  // ── 15-second load timeout guard ─────────────────────────────────────────
  const [loadTimedOut, setLoadTimedOut] = useState(false);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

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

  // Derived: true while any of the four queries are in-flight
  const anyFetching = summaryQ.isFetching || measuresQ.isFetching || starsQ.isFetching || gapsQ.isFetching;

  // Start/reset the 15-second timeout whenever fetching begins.
  // Clear it as soon as all loading finishes or an error is surfaced.
  useEffect(() => {
    if (anyFetching) {
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
      setLoadTimedOut(false);
      timeoutRef.current = setTimeout(() => {
        setLoadTimedOut(true);
      }, 15_000);
    } else {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
        timeoutRef.current = null;
      }
      setLoadTimedOut(false);
    }
    return () => {
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
    };
  }, [anyFetching]);

  // ── Derived values for the top header gauge ───────────────────────────────
  const currentStars = starsQ.data?.current_estimate ?? summaryQ.data?.stars_estimate ?? 0;
  const projectedStars = starsQ.data?.projected_estimate ?? currentStars;
  const diff = projectedStars - currentStars;
  const diffUp = diff >= 0;

  function refetchAll() {
    setLoadTimedOut(false);
    summaryQ.refetch();
    measuresQ.refetch();
    starsQ.refetch();
    gapsQ.refetch();
  }

  // ── Render the active tab content ─────────────────────────────────────────
  function renderTabContent() {
    if (activeTab === "Summary") {
      if (summaryQ.isLoading || measuresQ.isLoading) {
        if (loadTimedOut)
          return (
            <ErrorBox
              message="Loading is taking longer than expected. The server may be busy — please retry."
              onRetry={refetchAll}
            />
          );
        return <Spinner label="Loading quality summary..." />;
      }
      if (summaryQ.isError || measuresQ.isError)
        return <ErrorBox message={`Failed to load quality summary: ${
          (summaryQ.error as Error | null)?.message ??
          (measuresQ.error as Error | null)?.message ??
          "Unknown error"
        }`} onRetry={refetchAll} />;
      if (!summaryQ.data)
        return (
          <ErrorBox
            message="No quality summary data available for this tenant. Ensure the quality pipeline has run."
            onRetry={refetchAll}
          />
        );
      return (
        <SummaryTab summary={summaryQ.data} measures={measuresQ.data ?? []} />
      );
    }

    if (activeTab === "HEDIS Measures") {
      if (measuresQ.isLoading) {
        if (loadTimedOut)
          return <ErrorBox message="Measures did not load in time. Please retry." onRetry={refetchAll} />;
        return <Spinner label="Loading HEDIS measures..." />;
      }
      if (measuresQ.isError)
        return (
          <ErrorBox
            message={`Failed to load measures: ${(measuresQ.error as Error | null)?.message ?? "Unknown error"}`}
            onRetry={refetchAll}
          />
        );
      const measures = measuresQ.data ?? [];
      if (measures.length === 0)
        return (
          <div
            role="status"
            className="flex items-start gap-3 rounded-lg border border-warning/30 bg-warning/5 p-4 text-sm mb-4"
            style={{ color: tokens.warningText }}
          >
            <AlertTriangle size={18} className="flex-shrink-0 mt-0.5" />
            <div>
              <div className="font-semibold mb-0.5">No HEDIS measures available — this is unusual</div>
              <div className="text-xs text-muted-foreground">
                STARS ratings depend on HEDIS measure data. Verify the quality pipeline is running
                and that measure data has been ingested for this plan year.
              </div>
            </div>
          </div>
        );
      return <MeasuresTabDynamic measures={measures} />;
    }

    if (activeTab === "STARS Estimate") {
      if (starsQ.isLoading) {
        if (loadTimedOut)
          return <ErrorBox message="STARS estimate did not load in time. Please retry." onRetry={refetchAll} />;
        return <Spinner label="Loading STARS estimate..." />;
      }
      if (starsQ.isError)
        return (
          <ErrorBox
            message={`Failed to load STARS estimate: ${(starsQ.error as Error | null)?.message ?? "Unknown error"}`}
            onRetry={refetchAll}
          />
        );
      if (!starsQ.data)
        return (
          <div
            role="status"
            className="flex items-start gap-3 rounded-lg border border-warning/30 bg-warning/5 p-4 text-sm"
            style={{ color: tokens.warningText }}
          >
            <AlertTriangle size={18} className="flex-shrink-0 mt-0.5" />
            <div>
              <div className="font-semibold mb-0.5">No STARS data available — this is unusual</div>
              <div className="text-xs text-muted-foreground">
                STARS estimates are required for CMS bonus payments and quality bonuses.
                Verify STARS calculation pipeline is configured.
              </div>
            </div>
          </div>
        );
      return <StarsTabDynamic stars={starsQ.data} />;
    }

    if (activeTab === "Care Gaps") {
      if (gapsQ.isLoading) {
        if (loadTimedOut)
          return <ErrorBox message="Care gaps did not load in time. Please retry." onRetry={refetchAll} />;
        return <Spinner label="Loading care gaps..." />;
      }
      if (gapsQ.isError)
        return (
          <ErrorBox
            message={`Failed to load care gaps: ${(gapsQ.error as Error | null)?.message ?? "Unknown error"}`}
            onRetry={refetchAll}
          />
        );
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
    <div className="min-h-screen bg-slate-50 p-6 overflow-x-hidden">
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
            disabled={anyFetching}
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg border border-border bg-card text-muted-foreground text-[13px] font-medium cursor-pointer disabled:opacity-60 hover:text-foreground transition-colors"
          >
            <RefreshCw size={14} />
            Refresh
          </button>
        }
      />

      {/* ── Top stripe: current STARS summary ── */}
      {currentStars > 0 && (
        <div
          className="premium-card premium-shadow mesh-pattern qs-fade-in flex items-center gap-7 mb-7 flex-wrap rounded-xl"
          style={{
            ...T.card,
            background: `linear-gradient(135deg, ${tokens.slate900} 0%, ${tokens.slate800} 50%, ${tokens.slate900} 100%)`,
            border: "1px solid rgba(255,255,255,0.06)",
          }}
        >
          <StarsGauge rating={currentStars} />
          <div className="flex-1 min-w-[200px]">
            <div
              className="text-xs font-bold uppercase tracking-widest mb-2"
              style={{ color: tokens.slate400 }}
            >
              Estimated STARS Rating
            </div>
            <div className="flex items-center gap-2 mb-2">
              {diffUp
                ? <TrendingUp size={16} color={tokens.success} />
                : <TrendingDown size={16} color={tokens.riskHigh} />}
              <span
                className="font-bold text-sm"
                style={{ color: diffUp ? tokens.success : tokens.riskHigh }}
              >
                {diffUp ? "+" : ""}{(diff ?? 0).toFixed(2)} projected change
              </span>
            </div>
            {summaryQ.data && (
              <div className="text-xs" style={{ color: tokens.slate500 }}>
                {summaryQ.data.total_measures} measures tracked &middot;{" "}
                {summaryQ.data.measures_above_benchmark} above benchmark
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── Tab Bar ── */}
      <div
        className="qs-fade-in qs-fade-in-2 overflow-x-auto mb-6"
        style={{
          WebkitOverflowScrolling: "touch",
          borderBottom: `2px solid ${C.borderLight}`,
        } as React.CSSProperties}
      >
        <div className="flex min-w-max">
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
