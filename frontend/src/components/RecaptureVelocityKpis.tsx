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

import {
  getRecaptureDecayCurve,
  getRecaptureVelocity,
  type RecaptureDecayCurveResponse,
  type RecaptureVelocityResponse,
} from "@/lib/api";
import { tokens } from "@/styles/tokens";
import { MetricCard } from "@/components/ui/metric-card";

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
  if (rate >= 0.7) return tokens.success;
  if (rate >= 0.5) return tokens.warningStrong;
  return tokens.riskHigh;
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
              borderRadius: 10,
              background: `linear-gradient(90deg, ${tokens.slate100} 0%, ${tokens.slate200} 50%, ${tokens.slate100} 100%)`,
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
          background: tokens.dangerSoft,
          border: `1px solid ${tokens.dangerBorder}`,
          color: tokens.danger,
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

  const earlyIntent =
    earlyRate >= 0.7 ? "success" : earlyRate >= 0.5 ? "warning" : "danger";

  return (
    <div
      className="rci-velocity-strip"
      style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 16, marginBottom: 24 }}
    >
      <MetricCard
        label="Avg Days to Close"
        value={`${v.avg_days_to_close.toFixed(1)} days`}
        subtitle={`Median ${v.median_days_to_close.toFixed(1)} · ${pct(v.days_to_close_target_30)} closed ≤30d`}
        trend={sparkData.map((d) => d.v)}
        intent="default"
      />
      <MetricCard
        label="YTD $ Recaptured"
        value={fmtCurrency(v.ytd_$_recaptured)}
        subtitle={`${v.closed_cohort_gaps} of ${v.total_cohort_gaps} gaps closed`}
        intent="success"
      />
      <MetricCard
        label="YE Projected $"
        value={fmtCurrency(v.ye_projected_$)}
        delta={budgetBaseline > 0 ? (projectedDelta / budgetBaseline) * 100 : undefined}
        subtitle={`vs budget ${fmtCurrency(budgetBaseline)}`}
        intent={projectedDelta >= 0 ? "success" : "danger"}
      />
      <MetricCard
        label="Early-Recapture Rate"
        value={pct(earlyRate)}
        subtitle={`Q1 closures · Q4 lag ${pct(v.late_recapture_rate)}`}
        intent={earlyIntent}
      />
    </div>
  );
}

