"use client";

/**
 * ProviderTrendCard
 * -----------------
 * Larger detail-drawer card showing the four key metrics stacked vertically:
 *
 *   RAF        ▁▂▃▅  1.34   ▲ +0.13 vs prior year
 *   Recapture  ▁▂▄▆  82.0%  ▲ +0.03 vs prior year
 *   Capture    ▂▃▄▅  78.0%  ▲ +0.04 vs prior year
 *   Revenue    ▁▃▆▇  $180k  ▲ +$20k vs prior year
 *
 * Each row is label · sparkline · current value · delta arrow.  Designed to
 * sit inside the existing `ProviderDetailPanel` left column (240px wide).
 *
 * Self-fetches via `getProviderTrend` so the parent only has to pass the
 * provider id.  React-Query is reused so the response is cached alongside
 * existing provider-detail queries.
 */

import * as React from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowDown, ArrowRight, ArrowUp, TrendingUp } from "lucide-react";

import {
  getProviderTrend,
  type ProviderTrendMetricKey,
  type ProviderTrendResponse,
} from "@/lib/api";
import ProviderTrendSparkline from "./ProviderTrendSparkline";

type ProviderTrendMetric = ProviderTrendResponse["metrics"][ProviderTrendMetricKey];

export interface ProviderTrendCardProps {
  providerId: number;
  years?: number;
  /** Optional pre-fetched payload (skips the network call). */
  initialData?: ProviderTrendResponse;
  /** Width hint — defaults to 100% of the parent. */
  width?: number | string;
}

const METRIC_ORDER: ProviderTrendMetricKey[] = [
  "raf",
  "recapture",
  "capture",
  "revenue",
];

const METRIC_LABEL: Record<ProviderTrendMetricKey, string> = {
  raf: "RAF",
  recapture: "Recapture",
  capture: "Capture",
  revenue: "Revenue",
};

const COLOR = {
  text: "#0f172a",
  muted: "#64748b",
  border: "#e2e8f0",
  bg: "#ffffff",
  emerald: "#10b981",
  red: "#ef4444",
  slate: "#64748b",
} as const;

function formatCurrent(metric: ProviderTrendMetricKey, value: number | null): string {
  return ProviderTrendSparkline.formatValue(metric, value);
}

function formatDelta(metric: ProviderTrendMetricKey, delta: number | null): string {
  if (delta === null || delta === undefined || Number.isNaN(delta)) return "—";
  const sign = delta > 0 ? "+" : delta < 0 ? "−" : "";
  const abs = Math.abs(delta);
  if (metric === "revenue") {
    if (abs >= 1_000_000) return `${sign}$${(abs / 1_000_000).toFixed(2)}M`;
    if (abs >= 1_000) return `${sign}$${(abs / 1_000).toFixed(1)}k`;
    return `${sign}$${abs.toFixed(0)}`;
  }
  if (metric === "raf") return `${sign}${abs.toFixed(2)}`;
  // recapture + capture: ratio diff → percentage points.
  return `${sign}${(abs * 100).toFixed(1)}pp`;
}

function deltaIcon(delta: number | null) {
  if (delta === null || delta === undefined || Number.isNaN(delta)) {
    return { icon: ArrowRight, color: COLOR.slate };
  }
  if (delta > 0.0001) return { icon: ArrowUp, color: COLOR.emerald };
  if (delta < -0.0001) return { icon: ArrowDown, color: COLOR.red };
  return { icon: ArrowRight, color: COLOR.slate };
}

function MetricRow({
  metric,
  block,
}: {
  metric: ProviderTrendMetricKey;
  block: ProviderTrendMetric | undefined;
}) {
  const values = block?.values ?? [];
  const current = block?.current ?? null;
  const delta = block?.delta_vs_prior_year ?? null;
  const { icon: Icon, color: deltaColor } = deltaIcon(delta);

  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "72px 1fr auto",
        alignItems: "center",
        gap: 10,
        padding: "8px 4px",
        borderBottom: `1px solid ${COLOR.border}`,
        fontSize: 12,
      }}
    >
      <span style={{ color: COLOR.muted, fontWeight: 600 }}>
        {METRIC_LABEL[metric]}
      </span>

      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <ProviderTrendSparkline
          data={values}
          metric={metric}
          deltaVsPriorYear={delta}
          width={110}
          height={28}
        />
        <span style={{ fontSize: 13, fontWeight: 700, color: COLOR.text }}>
          {formatCurrent(metric, current)}
        </span>
      </div>

      <span
        title={
          delta === null
            ? "No prior-year data available"
            : `${formatDelta(metric, delta)} vs prior year`
        }
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 3,
          color: deltaColor,
          fontWeight: 600,
          fontSize: 11,
          minWidth: 56,
          justifyContent: "flex-end",
        }}
      >
        <Icon size={11} />
        {formatDelta(metric, delta)}
      </span>
    </div>
  );
}

export default function ProviderTrendCard({
  providerId,
  years = 4,
  initialData,
  width = "100%",
}: ProviderTrendCardProps) {
  const { data, isLoading, isError } = useQuery<ProviderTrendResponse>({
    queryKey: ["provider-trend", providerId, years],
    queryFn: () => getProviderTrend(providerId, years),
    initialData,
    // Trends move once a day at most — 5 minutes is a comfortable cache.
    staleTime: 5 * 60_000,
  });

  return (
    <section
      aria-labelledby={`provider-trend-card-${providerId}`}
      style={{
        width,
        background: COLOR.bg,
        border: `1px solid ${COLOR.border}`,
        borderRadius: 10,
        padding: 14,
        boxSizing: "border-box",
      }}
    >
      <header
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: 8,
        }}
      >
        <h4
          id={`provider-trend-card-${providerId}`}
          style={{
            margin: 0,
            fontSize: 13,
            fontWeight: 700,
            color: COLOR.text,
            display: "flex",
            alignItems: "center",
            gap: 6,
          }}
        >
          <TrendingUp size={14} />
          {years}-Year Trajectory
        </h4>
        {data?.single_year_only && (
          <span
            style={{
              fontSize: 10,
              color: COLOR.muted,
              background: "#f1f5f9",
              border: "1px dashed #cbd5e1",
              padding: "2px 6px",
              borderRadius: 4,
            }}
          >
            Need more history
          </span>
        )}
      </header>

      {isLoading ? (
        <div style={{ padding: "16px 0", color: COLOR.muted, fontSize: 12 }}>
          Loading trends...
        </div>
      ) : isError ? (
        <div style={{ padding: "16px 0", color: COLOR.red, fontSize: 12 }}>
          Failed to load trend data.
        </div>
      ) : (
        <div>
          {METRIC_ORDER.map((metric) => (
            <MetricRow
              key={metric}
              metric={metric}
              block={data?.metrics?.[metric]}
            />
          ))}
        </div>
      )}
    </section>
  );
}
