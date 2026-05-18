"use client";

/**
 * MetricTrend — inline sparkline + WoW delta arrow next to a KPI value.
 *
 * Usage:
 *   <MetricTrend series={[12, 14, 11, 16, 18, 20, 19, 21, 24, 22, 25, 27]} delta={8.3} format="number" />
 *   <MetricTrend series={[1.1, 1.12, 1.09, 1.13]} delta={-1.2} format="raf" />
 */

import React, { useId, useMemo } from "react";

export type MetricTrendFormat = "number" | "raf" | "currency" | "percent";

export interface MetricTrendProps {
  /** Array of numeric values ordered oldest → newest (up to 12 weeks). */
  series: number[];
  /** Week-over-week % change. Positive = up, negative = down. */
  delta?: number;
  /** Controls how the delta label is formatted. */
  format?: MetricTrendFormat;
  /** Height of the SVG sparkline in px. Default 32. */
  height?: number;
  /** Width of the SVG sparkline in px. Default 80. */
  width?: number;
  /** Override line color. Defaults to trend-aware green/red. */
  color?: string;
}

function formatDelta(delta: number, format: MetricTrendFormat): string {
  const abs = Math.abs(delta);
  const sign = delta >= 0 ? "+" : "-";
  if (format === "raf") return `${sign}${abs.toFixed(2)}`;
  if (format === "currency") return `${sign}${abs >= 1000 ? `$${(abs / 1000).toFixed(1)}K` : `$${abs.toFixed(0)}`}`;
  return `${sign}${abs.toFixed(1)}%`;
}

export function MetricTrend({
  series,
  delta,
  format = "number",
  height = 32,
  width = 80,
  color,
}: MetricTrendProps) {
  // Need at least 2 points for a line
  const points = useMemo(() => {
    if (!series || series.length < 2) return null;
    const min = Math.min(...series);
    const max = Math.max(...series);
    const range = max - min || 1;
    const pad = 2;
    const usableH = height - pad * 2;
    const step = (width - pad * 2) / (series.length - 1);
    return series.map((v, i) => ({
      x: pad + i * step,
      y: pad + usableH - ((v - min) / range) * usableH,
    }));
  }, [series, height, width]);

  const trendUp = delta === undefined ? null : delta >= 0;

  // Green for up (good), red for down unless this is "lower is better" —
  // for KPIs like open gaps, callers can pass inverted delta so the arrow
  // color stays intuitive. We just reflect the sign here.
  const lineColor = color ?? (trendUp === null ? "#94A3B8" : trendUp ? "#10B981" : "#EF4444");
  const arrowColor = trendUp === null ? "#94A3B8" : trendUp ? "#10B981" : "#EF4444";

  const polyline = points
    ? points.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ")
    : null;

  // Gradient fill under line — useId gives a stable, concurrent-safe ID
  const rawId = useId();
  const gradientId = "mtg-" + rawId.replace(/:/g, "");

  return (
    <span
      style={{ display: "inline-flex", alignItems: "center", gap: 6 }}
      aria-label={delta !== undefined ? `Trend: ${formatDelta(delta, format)} vs last week` : "Trend sparkline"}
    >
      {/* Sparkline SVG */}
      {polyline && (
        <svg
          width={width}
          height={height}
          viewBox={`0 0 ${width} ${height}`}
          aria-hidden="true"
          style={{ flexShrink: 0, overflow: "visible" }}
        >
          <defs>
            <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={lineColor} stopOpacity="0.18" />
              <stop offset="100%" stopColor={lineColor} stopOpacity="0" />
            </linearGradient>
          </defs>
          {/* Fill area */}
          <polygon
            points={`${points![0].x.toFixed(1)},${height} ${polyline} ${points![points!.length - 1].x.toFixed(1)},${height}`}
            fill={`url(#${gradientId})`}
          />
          {/* Line */}
          <polyline
            points={polyline}
            fill="none"
            stroke={lineColor}
            strokeWidth="1.5"
            strokeLinejoin="round"
            strokeLinecap="round"
          />
          {/* Endpoint dot */}
          <circle
            cx={points![points!.length - 1].x}
            cy={points![points!.length - 1].y}
            r="2.5"
            fill={lineColor}
          />
        </svg>
      )}

      {/* Delta badge */}
      {delta !== undefined && (
        <span
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 2,
            fontSize: 11,
            fontWeight: 700,
            color: arrowColor,
            letterSpacing: "0.01em",
            whiteSpace: "nowrap",
          }}
        >
          {/* Arrow */}
          <svg
            width="10"
            height="10"
            viewBox="0 0 10 10"
            aria-hidden="true"
            style={{ flexShrink: 0, transform: trendUp ? "rotate(0deg)" : "rotate(180deg)" }}
          >
            <path d="M5 1 L9 7 L1 7 Z" fill={arrowColor} />
          </svg>
          {formatDelta(delta, format)}
        </span>
      )}
    </span>
  );
}

export default MetricTrend;
