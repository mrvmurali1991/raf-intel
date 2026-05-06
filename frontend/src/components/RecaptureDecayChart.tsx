"use client";

/**
 * RecaptureDecayChart
 * --------------------
 * Multi-cohort (cohort_year) line chart of cumulative recapture closure %
 * across the 12 months of the measurement year. Each line represents a
 * different cohort_year so CFOs can scan: "are we closing faster than last
 * year, or slipping?".
 *
 * A dashed horizontal reference line at 90% marks the "industry leader"
 * benchmark — top MA plans close ≥80% of gaps in Q1; we aim slightly
 * higher at 90% YE.
 */

import * as React from "react";
import { useQuery } from "@tanstack/react-query";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import {
  getRecaptureDecayCurve,
  type RecaptureDecayCurveResponse,
} from "@/lib/api";

const MONTH_LABELS = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];

// Distinct, accessible line colours per cohort year.
const COHORT_COLORS = ["#94A3B8", "#3B82F6", "#10B981", "#F59E0B", "#EC4899"];

interface ChartRow {
  month: string;
  month_of_year: number;
  [cohortKey: string]: string | number;
}

interface CohortMeta {
  year: number;
  key: string;          // e.g. "y2026"
  color: string;
  totalGaps: number;
  closedGaps: number;
  // dollars indexed by month_of_year (1..12)
  dollarsByMonth: Record<number, number>;
}

export interface RecaptureDecayChartProps {
  year?: number;
  lookback?: number;
  height?: number;
}

export default function RecaptureDecayChart({
  year,
  lookback = 3,
  height = 320,
}: RecaptureDecayChartProps) {
  const { data, isLoading, isError } = useQuery<RecaptureDecayCurveResponse>({
    queryKey: ["recapture-decay-curve", year, lookback],
    queryFn: () => getRecaptureDecayCurve(year, lookback),
  });

  const { rows, cohorts } = React.useMemo(() => {
    if (!data?.cohorts?.length) {
      return { rows: [] as ChartRow[], cohorts: [] as CohortMeta[] };
    }
    // Build per-cohort metadata
    const cohortMeta: CohortMeta[] = data.cohorts.map((c, idx) => ({
      year: c.cohort_year,
      key: `y${c.cohort_year}`,
      color: COHORT_COLORS[idx % COHORT_COLORS.length],
      totalGaps: c.total_gaps,
      closedGaps: c.closed_gaps,
      dollarsByMonth: Object.fromEntries(
        c.points.map((p) => [p.month_of_year, p["$_recaptured"]])
      ),
    }));

    // Build a 12-row table with one column per cohort
    const rows: ChartRow[] = MONTH_LABELS.map((label, i) => {
      const row: ChartRow = { month: label, month_of_year: i + 1 };
      data.cohorts.forEach((c) => {
        const point = c.points.find((p) => p.month_of_year === i + 1);
        // Express percentage as 0..100 for Recharts y-axis readability
        row[`y${c.cohort_year}`] = point
          ? Math.round(point.cumulative_closed_pct * 1000) / 10
          : 0;
      });
      return row;
    });

    return { rows, cohorts: cohortMeta };
  }, [data]);

  if (isLoading) {
    return (
      <div
        style={{
          height,
          borderRadius: 12,
          background: "linear-gradient(90deg, #F1F5F9 0%, #E2E8F0 50%, #F1F5F9 100%)",
          backgroundSize: "200% 100%",
          animation: "shimmer 1.5s infinite",
        }}
        aria-label="Loading decay curve"
      />
    );
  }
  if (isError || !data) {
    return (
      <div
        style={{
          padding: 16,
          borderRadius: 10,
          background: "#FEF2F2",
          border: "1px solid #FECACA",
          color: "#B91C1C",
          fontSize: 13,
        }}
      >
        Failed to load recapture decay curve.
      </div>
    );
  }

  return (
    <div
      className="premium-card"
      style={{ padding: 24, marginBottom: 24, background: "#fff", borderRadius: 12 }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
        <div>
          <h3 className="gradient-text" style={{ margin: 0, fontSize: 16, fontWeight: 700 }}>
            Recapture Decay Curve
          </h3>
          <p style={{ margin: "4px 0 0", fontSize: 12, color: "#64748B" }}>
            Cumulative % of cohort gaps closed by month (industry leader benchmark: 90%)
          </p>
        </div>
        <div style={{ display: "flex", gap: 12, fontSize: 11, color: "#475569" }}>
          {cohorts.map((c) => (
            <div key={c.key} style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <span
                style={{
                  display: "inline-block",
                  width: 10,
                  height: 10,
                  borderRadius: 2,
                  background: c.color,
                }}
              />
              <span className="tabular-nums">
                {c.year} · {c.closedGaps}/{c.totalGaps}
              </span>
            </div>
          ))}
        </div>
      </div>

      <div style={{ width: "100%", height }}>
        <ResponsiveContainer>
          <LineChart data={rows} margin={{ top: 16, right: 16, left: 4, bottom: 4 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#E2E8F0" vertical={false} />
            <XAxis dataKey="month" tick={{ fontSize: 12, fill: "#64748B" }} />
            <YAxis
              domain={[0, 100]}
              tickFormatter={(v) => `${v}%`}
              tick={{ fontSize: 12, fill: "#64748B" }}
            />
            <Tooltip
              content={({ active, payload, label }) => {
                if (!active || !payload?.length) return null;
                return (
                  <div
                    style={{
                      background: "#fff",
                      border: "1px solid #E2E8F0",
                      borderRadius: 8,
                      padding: 12,
                      boxShadow: "0 4px 12px rgba(15, 23, 42, 0.08)",
                      fontSize: 12,
                    }}
                  >
                    <div style={{ fontWeight: 600, color: "#0F172A", marginBottom: 6 }}>
                      {label}
                    </div>
                    {payload.map((entry) => {
                      const cohort = cohorts.find((c) => c.key === entry.dataKey);
                      if (!cohort) return null;
                      const monthIdx = MONTH_LABELS.indexOf(String(label)) + 1;
                      const dollars = cohort.dollarsByMonth[monthIdx] ?? 0;
                      return (
                        <div
                          key={entry.dataKey as string}
                          style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 2 }}
                        >
                          <span
                            style={{
                              width: 8,
                              height: 8,
                              borderRadius: 2,
                              background: cohort.color,
                              display: "inline-block",
                            }}
                          />
                          <span style={{ color: "#475569" }}>{cohort.year}:</span>
                          <span className="tabular-nums" style={{ fontWeight: 600, color: "#0F172A" }}>
                            {entry.value as number}%
                          </span>
                          <span className="tabular-nums" style={{ color: "#64748B" }}>
                            (${dollars.toLocaleString()})
                          </span>
                        </div>
                      );
                    })}
                  </div>
                );
              }}
            />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            <ReferenceLine
              y={90}
              stroke="#10B981"
              strokeDasharray="6 4"
              label={{
                value: "Industry leader 90%",
                position: "right",
                fill: "#10B981",
                fontSize: 11,
                fontWeight: 600,
              }}
            />
            {cohorts.map((c) => (
              <Line
                key={c.key}
                type="monotone"
                dataKey={c.key}
                name={String(c.year)}
                stroke={c.color}
                strokeWidth={2.5}
                dot={{ r: 3 }}
                activeDot={{ r: 5 }}
                isAnimationActive
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
