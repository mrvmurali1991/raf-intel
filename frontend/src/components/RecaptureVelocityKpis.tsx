"use client";

/**
 * RecaptureVelocityKpis
 * ----------------------
 * 4-card strip used at the top of the /recapture page:
 *   1. Avg Days to Close (with sparkline of cumulative closures by month)
 *   2. YTD $ Recaptured
 *   3. YE Projected $ + delta vs budget (open × $3,000 baseline)
 *   4. Early-Recapture Rate (Q1 closures % — green/amber/red)
 *
 * Data is fetched from /api/recapture/velocity. Sparkline source uses the
 * monthly cumulative %s from /api/recapture/decay-curve so the avg-days
 * card has visual context of "how the year is shaping up".
 */

import * as React from "react";
import { useQuery } from "@tanstack/react-query";
import { Line, LineChart, ResponsiveContainer } from "recharts";

import {
  getRecaptureDecayCurve,
  getRecaptureVelocity,
  type RecaptureDecayCurveResponse,
  type RecaptureVelocityResponse,
} from "@/lib/api";

const REVENUE_PER_GAP = 3000;

function fmtCurrency(n: number): string {
  if (Math.abs(n) >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`;
  if (Math.abs(n) >= 1_000) return `$${(n / 1_000).toFixed(1)}K`;
  return `$${Math.round(n).toLocaleString()}`;
}

function pct(n: number): string {
  return `${(n * 100).toFixed(1)}%`;
}

function colourForEarlyRate(rate: number): string {
  if (rate >= 0.7) return "#10B981"; // green
  if (rate >= 0.5) return "#F59E0B"; // amber
  return "#DC2626";                  // red
}

export interface RecaptureVelocityKpisProps {
  year?: number;
}

export default function RecaptureVelocityKpis({ year }: RecaptureVelocityKpisProps) {
  const velocityQ = useQuery<RecaptureVelocityResponse>({
    queryKey: ["recapture-velocity", year],
    queryFn: () => getRecaptureVelocity(year),
  });
  const decayQ = useQuery<RecaptureDecayCurveResponse>({
    queryKey: ["recapture-velocity-spark", year],
    queryFn: () => getRecaptureDecayCurve(year, 1),
  });

  const sparkData = React.useMemo(() => {
    const cohort = decayQ.data?.cohorts?.[0];
    if (!cohort) return [] as Array<{ m: number; v: number }>;
    return cohort.points.map((p) => ({
      m: p.month_of_year,
      v: Math.round(p.cumulative_closed_pct * 1000) / 10,
    }));
  }, [decayQ.data]);

  if (velocityQ.isLoading || decayQ.isLoading) {
    return (
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 16, marginBottom: 24 }}>
        {[1, 2, 3, 4].map((i) => (
          <div
            key={i}
            style={{
              height: 120,
              borderRadius: 12,
              background: "linear-gradient(90deg, #F1F5F9 0%, #E2E8F0 50%, #F1F5F9 100%)",
              backgroundSize: "200% 100%",
              animation: "shimmer 1.5s infinite",
            }}
          />
        ))}
      </div>
    );
  }
  if (velocityQ.isError || !velocityQ.data) {
    return (
      <div
        style={{
          padding: 14,
          borderRadius: 10,
          background: "#FEF2F2",
          border: "1px solid #FECACA",
          color: "#B91C1C",
          fontSize: 13,
          marginBottom: 24,
        }}
      >
        Failed to load recapture velocity KPIs.
      </div>
    );
  }

  const v = velocityQ.data;
  const budgetBaseline = (v.open_cohort_gaps + v.closed_cohort_gaps) * REVENUE_PER_GAP;
  const projectedDelta = v.ye_projected_$ - budgetBaseline;
  const earlyRate = v.early_recapture_rate;
  const earlyColour = colourForEarlyRate(earlyRate);

  return (
    <div
      className="rci-velocity-strip"
      style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 16, marginBottom: 24 }}
    >
      {/* Card 1 — Avg Days to Close */}
      <KpiCard
        label="Avg Days to Close"
        primary={`${v.avg_days_to_close.toFixed(1)} days`}
        sub={`Median ${v.median_days_to_close.toFixed(1)} · ${pct(v.days_to_close_target_30)} closed ≤30d`}
        accent="#3B82F6"
      >
        {sparkData.length > 0 && (
          <div style={{ width: "100%", height: 36, marginTop: 8 }}>
            <ResponsiveContainer>
              <LineChart data={sparkData}>
                <Line
                  type="monotone"
                  dataKey="v"
                  stroke="#3B82F6"
                  strokeWidth={2}
                  dot={false}
                  isAnimationActive={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
      </KpiCard>

      {/* Card 2 — YTD $ Recaptured */}
      <KpiCard
        label="YTD $ Recaptured"
        primary={fmtCurrency(v.ytd_$_recaptured)}
        sub={`${v.closed_cohort_gaps} of ${v.total_cohort_gaps} gaps closed`}
        accent="#10B981"
      />

      {/* Card 3 — YE Projected $ */}
      <KpiCard
        label="YE Projected $"
        primary={fmtCurrency(v.ye_projected_$)}
        sub={
          <span style={{ color: projectedDelta >= 0 ? "#10B981" : "#DC2626", fontWeight: 600 }}>
            {projectedDelta >= 0 ? "+" : ""}
            {fmtCurrency(projectedDelta)} vs budget ({fmtCurrency(budgetBaseline)})
          </span>
        }
        accent="#8B5CF6"
      />

      {/* Card 4 — Early Recapture Rate */}
      <KpiCard
        label="Early-Recapture Rate"
        primary={
          <span style={{ color: earlyColour }}>
            {pct(earlyRate)}
          </span>
        }
        sub={`Q1 closures · Q4 lag ${pct(v.late_recapture_rate)}`}
        accent={earlyColour}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// KpiCard primitive
// ---------------------------------------------------------------------------

function KpiCard({
  label,
  primary,
  sub,
  accent,
  children,
}: {
  label: string;
  primary: React.ReactNode;
  sub: React.ReactNode;
  accent: string;
  children?: React.ReactNode;
}) {
  return (
    <div
      className="premium-card"
      style={{
        padding: 16,
        borderRadius: 12,
        background: "#fff",
        borderLeft: `3px solid ${accent}`,
        display: "flex",
        flexDirection: "column",
        gap: 4,
      }}
    >
      <div
        style={{
          fontSize: 11,
          fontWeight: 600,
          color: "#64748B",
          textTransform: "uppercase",
          letterSpacing: "0.06em",
        }}
      >
        {label}
      </div>
      <div className="tabular-nums" style={{ fontSize: 24, fontWeight: 700, color: "#0F172A" }}>
        {primary}
      </div>
      <div style={{ fontSize: 12, color: "#64748B" }}>{sub}</div>
      {children}
    </div>
  );
}
