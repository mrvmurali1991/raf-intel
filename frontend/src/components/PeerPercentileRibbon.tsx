"use client";

/**
 * PeerPercentileRibbon
 *
 * A compact horizontal strip showing how a provider ranks against their
 * specialty cohort across six KPIs.  Each KPI gets a mini-bar whose height
 * is proportional to the percentile (0-100); colour encodes performance:
 *
 *   ≥75 emerald, ≥50 blue, ≥25 amber, <25 red.
 *
 * If the cohort has fewer than 3 peers, the API returns
 * `insufficient_peers: true` and we render nothing — peer comparison is
 * meaningless at that scale.
 */
import React from "react";
import { useQuery } from "@tanstack/react-query";
import {
  getPeerPercentile,
  type PeerKpiKey,
  type PeerPercentile,
} from "@/lib/api";

// ---------------------------------------------------------------------------
// KPI metadata — display order, label, cohort-context noun
// ---------------------------------------------------------------------------
type KpiMeta = {
  key: PeerKpiKey;
  short: string;
  label: string;
};

const KPI_ORDER: KpiMeta[] = [
  { key: "average_raf",                 short: "RAF", label: "Average RAF" },
  { key: "hcc_capture_rate",            short: "CAP", label: "HCC capture" },
  { key: "recapture_rate",              short: "RCP", label: "Recapture" },
  { key: "meat_completeness_avg",       short: "MET", label: "MEAT compliance" },
  { key: "revenue_opportunity",         short: "REV", label: "Revenue opportunity" },
  { key: "documentation_quality_score", short: "DOC", label: "Doc quality" },
];

function colorFor(percentile: number | null): { bgClass: string; fgClass: string } {
  if (percentile === null || percentile === undefined) {
    return { fgClass: "bg-slate-500 dark:bg-slate-400", bgClass: "bg-slate-100 dark:bg-slate-800" };
  }
  if (percentile >= 75) return { fgClass: "bg-emerald-500 dark:bg-emerald-400", bgClass: "bg-emerald-50 dark:bg-emerald-950" };
  if (percentile >= 50) return { fgClass: "bg-blue-600 dark:bg-blue-400", bgClass: "bg-blue-50 dark:bg-blue-950" };
  if (percentile >= 25) return { fgClass: "bg-amber-500 dark:bg-amber-400", bgClass: "bg-amber-50 dark:bg-amber-950" };
  return { fgClass: "bg-red-500 dark:bg-red-400", bgClass: "bg-red-50 dark:bg-red-950" };
}

function ordinal(p: number): string {
  const r = Math.round(p);
  const v = r % 100;
  if (v >= 11 && v <= 13) return `${r}th`;
  switch (r % 10) {
    case 1: return `${r}st`;
    case 2: return `${r}nd`;
    case 3: return `${r}rd`;
    default: return `${r}th`;
  }
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------
export interface PeerPercentileRibbonProps {
  providerId: number | string;
  year?: number;
  cohortNoun?: string;
  compact?: boolean;
}

export default function PeerPercentileRibbon({
  providerId,
  year,
  cohortNoun = "peers",
  compact = false,
}: PeerPercentileRibbonProps) {
  const q = useQuery<PeerPercentile>({
    queryKey: ["peer-percentile", providerId, year],
    queryFn: () => getPeerPercentile(providerId, year),
    staleTime: 60_000,
    refetchOnWindowFocus: false,
    retry: 1,
  });

  if (q.isLoading) {
    return <Skeleton compact={compact} />;
  }

  if (q.isError || !q.data) {
    return null;
  }

  if (q.data.insufficient_peers || q.data.cohort_size < 3) {
    return null;
  }

  const peerCount = Math.max(0, q.data.cohort_size - 1);
  const data = q.data;

  const barH = compact ? 22 : 28;
  const barW = compact ? 14 : 18;
  const gap = compact ? 4 : 6;

  return (
    <div
      role="group"
      aria-label="Peer percentile ribbon"
      className="inline-flex items-end bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg shadow-[0_1px_1px_rgba(15,23,42,0.03)]"
      style={{ gap, padding: "4px 8px" }}
    >
      {KPI_ORDER.map((kpi) => {
        const pct = data.percentiles[kpi.key] ?? null;
        const { fgClass, bgClass } = colorFor(pct);
        const fillH = pct === null ? 4 : Math.max(4, Math.round((pct / 100) * barH));
        const tooltip =
          pct === null
            ? `${kpi.label}: no data`
            : `${kpi.label}: ${ordinal(pct)} percentile vs ${peerCount} ${cohortNoun} in ${data.specialty ?? "your cohort"}`;

        return (
          <div
            key={kpi.key}
            title={tooltip}
            aria-label={tooltip}
            className="flex flex-col items-center"
            style={{ gap: 3 }}
          >
            <div
              className={`${bgClass} rounded overflow-hidden relative`}
              style={{ width: barW, height: barH }}
            >
              <div
                className={`${fgClass} rounded absolute bottom-0 left-0 right-0 transition-[height] duration-[250ms] ease-out`}
                style={{ height: fillH }}
              />
            </div>
            <div className="text-[8px] font-bold text-slate-500 dark:text-slate-400 tracking-wide leading-none">
              {kpi.short}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Loading skeleton — same footprint, gray bars
// ---------------------------------------------------------------------------
function Skeleton({ compact }: { compact: boolean }) {
  const barH = compact ? 22 : 28;
  const barW = compact ? 14 : 18;
  const gap = compact ? 4 : 6;
  return (
    <div
      aria-hidden
      className="inline-flex items-end bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg opacity-60"
      style={{ gap, padding: "4px 8px" }}
    >
      {KPI_ORDER.map((k) => (
        <div
          key={k.key}
          className="bg-slate-100 dark:bg-slate-800 rounded"
          style={{ width: barW, height: barH }}
        />
      ))}
    </div>
  );
}
