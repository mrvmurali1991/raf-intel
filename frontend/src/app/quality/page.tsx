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
import { C, starsLabel, StarsGauge, Spinner, ErrorBox, renderStars } from "./tabs/_shared";

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

// ── HEDIS measure card used in the Summary tab ────────────────────────────────
function MeasureProgressCard({ measure }: { measure: QualityMeasure }) {
  const rate = Math.round(measure.rate * 100);
  const target = measure.benchmark != null ? Math.round(measure.benchmark * 100) : null;
  const aboveTarget = target !== null ? rate >= target : rate >= 80;
  const defaultTarget = 80;
  const targetPct = target ?? defaultTarget;

  // Color thresholds: green ≥ target, amber within 10 pts below, red otherwise
  let barColor: string;
  let statusClass: string;
  let statusText: string;
  if (aboveTarget) {
    barColor = C.emerald;
    statusClass = "text-emerald-700 bg-emerald-50 border border-emerald-200";
    statusText = "Above Target";
  } else if (rate >= targetPct - 10) {
    barColor = C.amber;
    statusClass = "text-amber-700 bg-amber-50 border border-amber-200";
    statusText = "Near Target";
  } else {
    barColor = C.red;
    statusClass = "text-red-700 bg-red-50 border border-red-200";
    statusText = "Below Target";
  }

  // Target marker position as percentage of 100
  const markerLeft = Math.min(targetPct, 100);

  return (
    <div className="rounded-xl border border-border bg-card p-4 flex flex-col gap-3 shadow-sm hover:shadow-md transition-shadow">
      {/* Measure name + status badge */}
      <div className="flex items-start justify-between gap-2">
        <div>
          <span className="text-[11px] font-bold text-primary font-mono tracking-wide">
            {measure.measure_id}
          </span>
          <p className="text-[13px] font-semibold text-foreground mt-0.5 leading-snug">
            {measure.name}
          </p>
        </div>
        <span className={`flex-shrink-0 text-[11px] font-bold px-2.5 py-1 rounded-full whitespace-nowrap ${statusClass}`}>
          {statusText}
        </span>
      </div>

      {/* Progress bar with target marker */}
      <div className="relative">
        <div className="relative h-2.5 rounded-full bg-slate-100 overflow-visible">
          {/* Filled bar */}
          <div
            className="qs-progress-bar absolute inset-y-0 left-0 rounded-full"
            style={{ width: `${Math.min(rate, 100)}%`, background: barColor, transition: "width 0.6s cubic-bezier(0.22,1,0.36,1)" }}
          />
          {/* Target marker — rendered outside overflow:hidden parent */}
          <div
            className="absolute top-1/2 -translate-y-1/2 w-0.5 h-4 rounded-full bg-slate-600 opacity-60 z-10"
            style={{ left: `${markerLeft}%` }}
          />
        </div>
      </div>

      {/* Rate / target text row */}
      <div className="flex items-center justify-between text-[12px]">
        <span className="font-bold" style={{ color: barColor }}>
          {rate}%
          {target !== null && (
            <span className="font-normal text-muted-foreground ml-1">/ {target}% target</span>
          )}
        </span>
        {measure.gap > 0 && (
          <span className="text-muted-foreground">
            <span className="font-semibold text-foreground">{measure.gap.toLocaleString()}</span> open gaps
          </span>
        )}
        {measure.gap === 0 && (
          <span className="flex items-center gap-1 text-emerald-700 font-medium">
            <CheckCircle size={12} />
            No gaps
          </span>
        )}
      </div>
    </div>
  );
}

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
        <div className="premium-card premium-shadow hover-lift qs-fade-in qs-fade-in-1 rounded-xl border border-border bg-card p-6">
          <SectionHeader title="Compliance Rate Distribution" icon={<Activity size={18} />} />
          <div className="flex overflow-hidden rounded-lg h-8 mb-3.5 shadow-inner">
            {[
              { pct: (green / total) * 100, color: C.emerald },
              { pct: (amber / total) * 100, color: C.amber },
              { pct: (red / total) * 100, color: C.red },
            ].map((seg, i) => (
              <div
                key={i}
                className="flex items-center justify-center text-[11px] font-bold text-white"
                style={{
                  width: `${seg.pct}%`,
                  background: seg.color,
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

      {/* HEDIS measure cards grid */}
      {measures.length > 0 && (
        <div className="qs-fade-in qs-fade-in-2">
          <SectionHeader title="HEDIS Measures Overview" icon={<Activity size={18} />} />
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 mt-3">
            {measures.map((m) => (
              <MeasureProgressCard key={m.measure_id} measure={m} />
            ))}
          </div>
        </div>
      )}

      {/* Empty state when no measures are loaded yet */}
      {total === 0 && (
        <div className="flex items-start gap-3 rounded-lg border border-amber-200 bg-amber-50 p-5 text-sm text-amber-800">
          <AlertTriangle size={18} className="flex-shrink-0 mt-0.5" />
          <div>
            <div className="font-semibold mb-0.5">No measure data to display</div>
            <div className="text-xs text-amber-700">
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
            className="flex items-start gap-3 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm mb-4 text-amber-800"
          >
            <AlertTriangle size={18} className="flex-shrink-0 mt-0.5" />
            <div>
              <div className="font-semibold mb-0.5">No HEDIS measures available — this is unusual</div>
              <div className="text-xs text-amber-700">
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
            className="flex items-start gap-3 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800"
          >
            <AlertTriangle size={18} className="flex-shrink-0 mt-0.5" />
            <div>
              <div className="font-semibold mb-0.5">No STARS data available — this is unusual</div>
              <div className="text-xs text-amber-700">
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
        .qs-measure-table tr:hover td { background: hsl(var(--primary) / 0.06) !important; }
        .qs-star-icon { transition: transform 0.2s ease; }
        .qs-star-icon:hover { animation: qs-starPulse 0.4s ease; }
        .qs-progress-bar { animation: qs-progressGrow 0.8s cubic-bezier(0.22, 1, 0.36, 1) both; }
        .qs-card-enter { animation: qs-fadeInUp 0.4s cubic-bezier(0.22, 1, 0.36, 1) both; }
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
        <div className="premium-card premium-shadow mesh-pattern qs-fade-in flex items-center gap-7 mb-7 flex-wrap rounded-xl bg-slate-900 border border-white/5 p-6">
          <StarsGauge rating={currentStars} />
          <div className="flex-1 min-w-[200px]">
            <div className="text-xs font-bold uppercase tracking-widest mb-3 text-slate-400">
              Estimated STARS Rating
            </div>
            {/* Star icons row */}
            <div className="mb-2">
              {renderStars(currentStars)}
            </div>
            <div className="flex items-center gap-2 mb-2">
              {diffUp
                ? <TrendingUp size={16} className="text-emerald-400" />
                : <TrendingDown size={16} className="text-red-400" />}
              <span className={`font-bold text-sm ${diffUp ? "text-emerald-400" : "text-red-400"}`}>
                {diffUp ? "+" : ""}{(diff ?? 0).toFixed(2)} projected change
              </span>
            </div>
            {summaryQ.data && (
              <div className="text-xs text-slate-500">
                {summaryQ.data.total_measures} measures tracked &middot;{" "}
                {summaryQ.data.measures_above_benchmark} above benchmark
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── Tab Bar ── */}
      <div className="qs-fade-in qs-fade-in-2 overflow-x-auto mb-6 border-b-2 border-slate-100">
        <div className="flex min-w-max">
          {TABS.map((tab) => {
            const isActive = activeTab === tab;
            return (
              <button
                key={tab}
                onClick={() => setActiveTab(tab)}
                className={[
                  "relative px-[22px] py-3 text-[14px] font-semibold tracking-[0.01em] whitespace-nowrap",
                  "rounded-tl-lg rounded-tr-lg -mb-0.5 border-none cursor-pointer transition-all duration-200",
                  "focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary focus-visible:outline-offset-2 focus-visible:rounded",
                  "after:content-[''] after:absolute after:bottom-[-2px] after:left-1/2 after:-translate-x-1/2 after:h-0.5 after:bg-primary after:transition-all after:duration-200",
                  isActive
                    ? "text-primary bg-primary/[0.03] after:w-full"
                    : "text-slate-500 bg-transparent hover:text-primary after:w-0 hover:after:w-full",
                ].join(" ")}
              >
                {tab}
              </button>
            );
          })}
        </div>
      </div>

      {/* ── Active Tab Content ── */}
      <div key={activeTab} className="qs-fade-in qs-fade-in-3">
        {renderTabContent()}
      </div>
    </div>
  );
}
