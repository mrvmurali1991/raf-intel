"use client";

/**
 * ProviderTrendSparkline
 * ----------------------
 * Compact (120 × 32 by default) inline sparkline for a single provider
 * metric — designed to slot into the leaderboard table next to the
 * current-period number.
 *
 * Colour rule (CFO scan-ability):
 *   ▲ positive YoY delta → emerald
 *   ▼ negative YoY delta → red
 *   ▬ flat / single point → slate
 *
 * For revenue we treat "up" as positive; for every other metric a higher
 * value is also positive, so the rule is uniform.
 *
 * Renders an explicit `Need more history` badge when only one datapoint is
 * available (DB has only the current measurement year).
 */

import * as React from "react";
import { Line, LineChart, ResponsiveContainer, Tooltip, YAxis } from "recharts";

import type {
  ProviderTrendMetricKey,
  ProviderTrendPoint,
} from "@/lib/api";

export interface ProviderTrendSparklineProps {
  data: Array<Pick<ProviderTrendPoint, "year" | "value">>;
  metric: ProviderTrendMetricKey;
  width?: number;
  height?: number;
  /** Visible YoY delta (current - prior year). Used to colour the line. */
  deltaVsPriorYear?: number | null;
  /** When true, hide the tooltip (e.g. inside dense table cells). */
  disableTooltip?: boolean;
  className?: string;
}

const COLOR = {
  emerald: "#10b981",
  red: "#ef4444",
  slate: "#64748b",
} as const;

const METRIC_LABEL: Record<ProviderTrendMetricKey, string> = {
  raf: "RAF",
  recapture: "Recapture",
  capture: "Capture",
  revenue: "Revenue",
};

function pickColor(delta: number | null | undefined): string {
  if (delta === null || delta === undefined || Number.isNaN(delta)) return COLOR.slate;
  if (delta > 0.0001) return COLOR.emerald;
  if (delta < -0.0001) return COLOR.red;
  return COLOR.slate;
}

function formatValue(metric: ProviderTrendMetricKey, value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  if (metric === "revenue") {
    if (value >= 1_000_000) return `$${(value / 1_000_000).toFixed(2)}M`;
    if (value >= 1_000) return `$${(value / 1_000).toFixed(1)}k`;
    return `$${value.toFixed(0)}`;
  }
  if (metric === "raf") return value.toFixed(2);
  // recapture + capture are stored as 0..1 ratios.
  return `${(value * 100).toFixed(1)}%`;
}

export default function ProviderTrendSparkline({
  data,
  metric,
  width = 120,
  height = 32,
  deltaVsPriorYear,
  disableTooltip = false,
  className,
}: ProviderTrendSparklineProps) {
  // Filter out null values for the line — recharts will render them as gaps
  // otherwise but we'd rather just collapse the series.
  const numeric = React.useMemo(
    () => data.filter((d) => d.value !== null && d.value !== undefined && !Number.isNaN(d.value)),
    [data],
  );

  if (numeric.length === 0) {
    return (
      <span
        className={className}
        style={{
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
          width,
          height,
          fontSize: 10,
          color: COLOR.slate,
          fontStyle: "italic",
        }}
        title={`No ${METRIC_LABEL[metric]} history yet`}
      >
        no data
      </span>
    );
  }

  if (numeric.length === 1) {
    const only = numeric[0];
    return (
      <span
        className={className}
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 6,
          width,
          height,
          fontSize: 10,
          color: COLOR.slate,
          background: "#f1f5f9",
          border: "1px dashed #cbd5e1",
          borderRadius: 4,
          padding: "0 6px",
        }}
        title={`${METRIC_LABEL[metric]} ${only.year}: ${formatValue(metric, only.value)} — needs at least 2 years for trend`}
      >
        <span
          aria-hidden
          style={{ width: 6, height: 6, borderRadius: "50%", background: COLOR.slate }}
        />
        Need more history
      </span>
    );
  }

  const stroke = pickColor(deltaVsPriorYear ?? null);

  // Convert null → undefined so recharts treats them as gaps cleanly when we
  // do pass mixed series in future.  Here we already filtered, but keep the
  // shape stable for downstream consumers.
  const series = numeric.map((d) => ({ year: d.year, value: d.value as number }));

  return (
    <div
      className={className}
      style={{ width, height, display: "inline-block", verticalAlign: "middle" }}
      aria-label={`${METRIC_LABEL[metric]} trend, ${series.length} years`}
    >
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={series} margin={{ top: 2, right: 2, bottom: 2, left: 2 }}>
          {/* Hidden Y-axis sized to the data bounds keeps the line centred
              while suppressing the axis labels to stay compact. */}
          <YAxis hide domain={["dataMin", "dataMax"]} />
          {!disableTooltip && (
            <Tooltip
              cursor={false}
              contentStyle={{
                background: "#0f172a",
                border: "none",
                borderRadius: 6,
                fontSize: 11,
                padding: "4px 8px",
                color: "#f8fafc",
              }}
              labelStyle={{ color: "#cbd5e1", fontSize: 10 }}
              formatter={(v) =>
                [formatValue(metric, typeof v === "number" ? v : Number(v)), METRIC_LABEL[metric]] as [string, string]
              }
              labelFormatter={(label) => `Year ${label}`}
            />
          )}
          <Line
            type="monotone"
            dataKey="value"
            stroke={stroke}
            strokeWidth={1.6}
            dot={{ r: 1.6, fill: stroke, stroke }}
            activeDot={{ r: 3, fill: stroke, stroke: "#fff", strokeWidth: 1 }}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

ProviderTrendSparkline.formatValue = formatValue;
ProviderTrendSparkline.pickColor = pickColor;
