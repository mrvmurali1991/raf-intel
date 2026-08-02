"use client";

/**
 * Peer Comparison tab for the Quality page.
 *
 * Shows the current provider's KPI performance vs their specialty cohort:
 *   - Percentile rank badge ("You are in the Xth percentile")
 *   - Per-KPI bar chart comparing provider value to cohort median
 *   - Cohort summary stats (min / median / max)
 *
 * Data source: GET /api/providers/{id}/peer-percentile  (via getPeerPercentile)
 */

import React from "react";
import { TrendingUp, TrendingDown, Users, Award, Minus } from "lucide-react";
import type { PeerPercentile, PeerKpiKey } from "@/lib/api";
import { C } from "./_shared";

// ── Human-friendly KPI labels ────────────────────────────────────────────────
const KPI_META: Record<PeerKpiKey, { label: string; fmt: (v: number) => string }> = {
  average_raf:                { label: "Average RAF Score",       fmt: (v) => v.toFixed(2) },
  hcc_capture_rate:           { label: "HCC Capture Rate",       fmt: (v) => `${(v * 100).toFixed(1)}%` },
  recapture_rate:             { label: "Recapture Rate",         fmt: (v) => `${(v * 100).toFixed(1)}%` },
  meat_completeness_avg:      { label: "MEAT Completeness",      fmt: (v) => `${(v * 100).toFixed(1)}%` },
  revenue_opportunity:        { label: "Revenue Opportunity",    fmt: (v) => `$${Math.round(v).toLocaleString()}` },
  documentation_quality_score:{ label: "Documentation Quality",  fmt: (v) => `${(v * 100).toFixed(1)}%` },
};

// Order to display KPIs
const KPI_ORDER: PeerKpiKey[] = [
  "hcc_capture_rate",
  "recapture_rate",
  "meat_completeness_avg",
  "documentation_quality_score",
  "average_raf",
  "revenue_opportunity",
];

function ordinalSuffix(n: number): string {
  const s = ["th", "st", "nd", "rd"];
  const v = n % 100;
  return n + (s[(v - 20) % 10] || s[v] || s[0]);
}

function percentileColor(pct: number): string {
  if (pct >= 75) return C.emerald;
  if (pct >= 50) return C.amber;
  return C.red;
}

function percentileIntent(pct: number): string {
  if (pct >= 75) return "text-emerald-700 bg-emerald-50 border-emerald-200 dark:text-emerald-400 dark:bg-emerald-900/30 dark:border-emerald-800";
  if (pct >= 50) return "text-amber-700 bg-amber-50 border-amber-200 dark:text-amber-400 dark:bg-amber-900/30 dark:border-amber-800";
  return "text-red-700 bg-red-50 border-red-200 dark:text-red-400 dark:bg-red-900/30 dark:border-red-800";
}

// ── KPI comparison row ───────────────────────────────────────────────────────
function KpiRow({
  kpi,
  myValue,
  percentile,
  cohort,
}: {
  kpi: PeerKpiKey;
  myValue: number | null | undefined;
  percentile: number | null | undefined;
  cohort: { min: number | null; median: number | null; max: number | null } | undefined;
}) {
  const meta = KPI_META[kpi];
  const median = cohort?.median;
  const hasData = myValue != null && median != null;

  // For bar width calculation, normalize to percentage of max in cohort
  // But for revenue_opportunity and average_raf, use the max as 100%
  const maxVal = cohort?.max ?? 1;
  const myBarPct = hasData ? Math.min((myValue / (maxVal || 1)) * 100, 100) : 0;
  const medBarPct = hasData && median != null ? Math.min((median / (maxVal || 1)) * 100, 100) : 0;

  const aboveMedian = hasData && median != null && myValue >= median;

  return (
    <div className="rounded-lg border border-border bg-card p-4 hover:shadow-sm transition-shadow">
      <div className="flex items-center justify-between mb-3">
        <span className="text-sm font-semibold text-foreground">{meta.label}</span>
        {percentile != null && (
          <span className={`text-xs font-bold px-2 py-0.5 rounded-full border ${percentileIntent(percentile)}`}>
            {ordinalSuffix(Math.round(percentile))} percentile
          </span>
        )}
      </div>

      {hasData ? (
        <>
          {/* My value bar */}
          <div className="flex items-center gap-3 mb-2">
            <span className="text-xs font-medium text-foreground w-10 shrink-0">You</span>
            <div className="flex-1 h-3 bg-slate-100 dark:bg-slate-700 rounded-full overflow-hidden">
              <div
                className="h-full rounded-full transition-all duration-700"
                style={{
                  width: `${myBarPct}%`,
                  background: aboveMedian ? C.emerald : C.amber,
                }}
              />
            </div>
            <span className="text-sm font-bold text-foreground w-20 text-right tabular-nums">
              {meta.fmt(myValue)}
            </span>
          </div>

          {/* Cohort median bar */}
          <div className="flex items-center gap-3 mb-2">
            <span className="text-xs font-medium text-muted-foreground w-10 shrink-0">Avg</span>
            <div className="flex-1 h-3 bg-slate-100 dark:bg-slate-700 rounded-full overflow-hidden">
              <div
                className="h-full rounded-full transition-all duration-700 opacity-50"
                style={{
                  width: `${medBarPct}%`,
                  background: C.textMuted,
                }}
              />
            </div>
            <span className="text-sm font-medium text-muted-foreground w-20 text-right tabular-nums">
              {median != null ? meta.fmt(median) : "--"}
            </span>
          </div>

          {/* Delta indicator */}
          <div className="flex items-center justify-between mt-1">
            <div className="flex items-center gap-1.5">
              {aboveMedian ? (
                <TrendingUp size={14} className="text-emerald-600 dark:text-emerald-400" />
              ) : (
                <TrendingDown size={14} className="text-amber-600 dark:text-amber-400" />
              )}
              <span className={`text-xs font-semibold ${aboveMedian ? "text-emerald-600 dark:text-emerald-400" : "text-amber-600 dark:text-amber-400"}`}>
                {aboveMedian ? "Above" : "Below"} cohort median
              </span>
            </div>
            <span className="text-[11px] text-muted-foreground">
              Range: {cohort?.min != null ? meta.fmt(cohort.min) : "--"} &ndash; {cohort?.max != null ? meta.fmt(cohort.max) : "--"}
            </span>
          </div>
        </>
      ) : (
        <div className="flex items-center gap-2 py-3 text-muted-foreground text-sm">
          <Minus size={14} />
          <span>Insufficient data</span>
        </div>
      )}
    </div>
  );
}

// ── Main component ───────────────────────────────────────────────────────────
export default function PeerComparisonTab({ data }: { data: PeerPercentile }) {
  // Calculate overall percentile as the average of available KPI percentiles
  const pctValues = KPI_ORDER
    .map((k) => data.percentiles[k])
    .filter((v): v is number => v != null);
  const overallPercentile = pctValues.length > 0
    ? Math.round(pctValues.reduce((a, b) => a + b, 0) / pctValues.length)
    : null;

  // Count KPIs above median
  const aboveMedianCount = KPI_ORDER.filter((k) => {
    const my = data.provider_kpis[k];
    const med = data.cohort_summary[k]?.median;
    return my != null && med != null && my >= med;
  }).length;

  return (
    <div className="flex flex-col gap-5">
      {/* Percentile hero card */}
      <div className="rounded-xl border border-border bg-card p-6 shadow-sm">
        <div className="flex flex-col sm:flex-row items-start sm:items-center gap-5">
          {/* Percentile ring */}
          {overallPercentile != null && !data.insufficient_peers ? (
            <>
              <div className="relative w-28 h-28 shrink-0">
                <svg viewBox="0 0 120 120" className="w-full h-full -rotate-90">
                  <circle
                    cx="60" cy="60" r="50"
                    fill="none"
                    stroke="currentColor"
                    className="text-slate-100 dark:text-slate-700"
                    strokeWidth="10"
                  />
                  <circle
                    cx="60" cy="60" r="50"
                    fill="none"
                    stroke={percentileColor(overallPercentile)}
                    strokeWidth="10"
                    strokeLinecap="round"
                    strokeDasharray={`${(overallPercentile / 100) * 314} 314`}
                    className="transition-all duration-1000"
                  />
                </svg>
                <div className="absolute inset-0 flex flex-col items-center justify-center">
                  <span className="text-2xl font-extrabold text-foreground">{ordinalSuffix(overallPercentile)}</span>
                  <span className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">percentile</span>
                </div>
              </div>

              <div className="flex-1 min-w-0">
                <h3 className="text-lg font-bold text-foreground mb-1">
                  My Performance vs Peers
                </h3>
                <p className="text-sm text-muted-foreground mb-3">
                  You are in the <strong className="text-foreground">{ordinalSuffix(overallPercentile)} percentile</strong> for
                  RAF capture across your {data.specialty ?? "specialty"} cohort of{" "}
                  <strong className="text-foreground">{data.cohort_size}</strong> providers.
                </p>
                <div className="flex flex-wrap gap-3">
                  <div className="flex items-center gap-1.5 text-xs">
                    <Users size={14} className="text-muted-foreground" />
                    <span className="text-muted-foreground">
                      Cohort: <strong className="text-foreground">{data.cohort_size}</strong> {data.specialty ?? ""} providers
                    </span>
                  </div>
                  <div className="flex items-center gap-1.5 text-xs">
                    <Award size={14} className="text-muted-foreground" />
                    <span className="text-muted-foreground">
                      Above median in <strong className="text-foreground">{aboveMedianCount}</strong> of {KPI_ORDER.length} KPIs
                    </span>
                  </div>
                </div>
              </div>
            </>
          ) : (
            <div className="flex-1">
              <h3 className="text-lg font-bold text-foreground mb-1">
                My Performance vs Peers
              </h3>
              {data.insufficient_peers ? (
                <p className="text-sm text-muted-foreground">
                  Your {data.specialty ?? "specialty"} cohort has only{" "}
                  <strong className="text-foreground">{data.cohort_size}</strong> provider{data.cohort_size !== 1 ? "s" : ""}.
                  Percentile rankings require at least 3 providers in the cohort for meaningful comparison.
                  Cohort summary statistics are still shown below.
                </p>
              ) : (
                <p className="text-sm text-muted-foreground">
                  No peer comparison data is available. This may happen if your user account is not
                  linked to a clinical provider or if scorecard snapshots have not been generated yet.
                </p>
              )}
            </div>
          )}
        </div>
      </div>

      {/* KPI comparison grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {KPI_ORDER.map((kpi) => (
          <KpiRow
            key={kpi}
            kpi={kpi}
            myValue={data.provider_kpis[kpi]}
            percentile={data.insufficient_peers ? null : data.percentiles[kpi]}
            cohort={data.cohort_summary[kpi]}
          />
        ))}
      </div>

      {/* Measurement year footer */}
      <div className="text-xs text-muted-foreground text-center pt-2">
        Measurement year {data.measurement_year} &middot; Percentiles based on {data.specialty ?? "all"} specialty cohort
      </div>
    </div>
  );
}
