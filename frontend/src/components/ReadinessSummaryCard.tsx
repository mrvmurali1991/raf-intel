"use client";

/**
 * ReadinessSummaryCard — aggregate dashboard card.
 *
 * Shows:
 *   - Average readiness score across all open gaps for the year
 *   - Defensibility distribution as a horizontal segmented donut
 *   - Total open gaps + actionable count
 *
 * Pulls data from /api/recapture/readiness/summary?year=YYYY.
 */

import React, { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Activity, Target, AlertTriangle } from "lucide-react";

import { getReadinessSummary, type ReadinessSummary } from "@/lib/api";

const colors = {
  white: "#FFFFFF",
  slate900: "#0F172A",
  slate600: "#475569",
  slate400: "#94A3B8",
  slate200: "#E2E8F0",
  slate100: "#F1F5F9",
  slate50: "#F8FAFC",
  emerald500: "#10B981",
  amber500: "#F59E0B",
  red500: "#EF4444",
  blue500: "#3B82F6",
};

const TIER_COLORS: Record<"strong" | "moderate" | "weak", string> = {
  strong:   colors.emerald500,
  moderate: colors.amber500,
  weak:     colors.red500,
};

interface DonutProps {
  distribution: ReadinessSummary["defensibility_distribution"];
  total: number;
}

function DefensibilityDonut({ distribution, total }: DonutProps) {
  const radius = 52;
  const stroke = 16;
  const c = 2 * Math.PI * radius;

  const segments = useMemo(() => {
    const order: ("strong" | "moderate" | "weak")[] = ["strong", "moderate", "weak"];
    const safeTotal = total > 0 ? total : 1;
    let offset = 0;
    return order.map((k) => {
      const value = distribution[k] ?? 0;
      const len = (value / safeTotal) * c;
      const seg = { key: k, len, offset, value };
      offset += len;
      return seg;
    });
  }, [distribution, total, c]);

  const avgIsZero = total === 0;

  return (
    <div
      style={{
        position: "relative",
        width: 140,
        height: 140,
        flexShrink: 0,
      }}
      aria-label="Defensibility distribution"
    >
      <svg width={140} height={140} viewBox="0 0 140 140">
        {/* Track */}
        <circle
          cx={70}
          cy={70}
          r={radius}
          fill="none"
          stroke={colors.slate100}
          strokeWidth={stroke}
        />
        {/* Segments */}
        {!avgIsZero &&
          segments.map((seg) => (
            <circle
              key={seg.key}
              cx={70}
              cy={70}
              r={radius}
              fill="none"
              stroke={TIER_COLORS[seg.key]}
              strokeWidth={stroke}
              strokeDasharray={`${seg.len} ${c - seg.len}`}
              strokeDashoffset={-seg.offset}
              strokeLinecap="butt"
              transform="rotate(-90 70 70)"
              style={{ transition: "stroke-dasharray 0.6s ease" }}
            />
          ))}
      </svg>
      <div
        style={{
          position: "absolute",
          inset: 0,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <span
          className="tabular-nums"
          style={{ fontSize: 11, color: colors.slate400, fontWeight: 600, letterSpacing: "0.05em", textTransform: "uppercase" }}
        >
          Gaps
        </span>
        <span
          className="tabular-nums"
          style={{ fontSize: 26, color: colors.slate900, fontWeight: 700, lineHeight: 1 }}
        >
          {total}
        </span>
      </div>
    </div>
  );
}

export interface ReadinessSummaryCardProps {
  year: number;
}

export function ReadinessSummaryCard({ year }: ReadinessSummaryCardProps) {
  const { data, isLoading, isError } = useQuery<ReadinessSummary>({
    queryKey: ["recapture-readiness-summary", year],
    queryFn: () => getReadinessSummary(year),
  });

  return (
    <div
      className="premium-card"
      style={{
        padding: 24,
        marginBottom: 24,
        background: `linear-gradient(135deg, ${colors.slate50}, ${colors.white})`,
      }}
    >
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 18 }}>
        <div>
          <p
            style={{
              margin: 0,
              fontSize: 11,
              fontWeight: 600,
              letterSpacing: "0.06em",
              textTransform: "uppercase",
              color: colors.slate400,
            }}
          >
            Recapture Readiness · {year}
          </p>
          <h3
            className="gradient-text"
            style={{ margin: "4px 0 0", fontSize: 18, fontWeight: 700 }}
          >
            Problem-list defensibility
          </h3>
        </div>
        <Activity size={18} color={colors.blue500} />
      </div>

      {isLoading && (
        <div style={{ display: "flex", gap: 24, alignItems: "center" }}>
          <div className="shimmer" style={{ width: 140, height: 140, borderRadius: 999 }} />
          <div style={{ flex: 1 }}>
            <div className="shimmer" style={{ height: 16, width: "60%", borderRadius: 6, marginBottom: 8 }} />
            <div className="shimmer" style={{ height: 12, width: "40%", borderRadius: 6 }} />
          </div>
        </div>
      )}

      {isError && !isLoading && (
        <div
          style={{
            padding: 12,
            borderRadius: 8,
            background: "#FEF2F2",
            border: "1px solid #FECACA",
            color: "#B91C1C",
            fontSize: 13,
            display: "flex",
            alignItems: "center",
            gap: 8,
          }}
        >
          <AlertTriangle size={14} />
          Could not load readiness summary.
        </div>
      )}

      {data && !isLoading && (
        <div style={{ display: "flex", gap: 24, alignItems: "center", flexWrap: "wrap" }}>
          <DefensibilityDonut
            distribution={data.defensibility_distribution}
            total={data.total_open_gaps}
          />

          <div style={{ flex: 1, minWidth: 240, display: "flex", flexDirection: "column", gap: 14 }}>
            {/* Average score */}
            <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
              <span
                className="tabular-nums"
                style={{ fontSize: 32, fontWeight: 700, color: colors.slate900, lineHeight: 1 }}
              >
                {data.average_score.toFixed(1)}
              </span>
              <span style={{ fontSize: 12, color: colors.slate600, fontWeight: 600 }}>
                / 100 average score
              </span>
            </div>

            {/* Distribution bars */}
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {(["strong", "moderate", "weak"] as const).map((tier) => {
                const value = data.defensibility_distribution[tier] ?? 0;
                const pct = data.total_open_gaps > 0
                  ? (value / data.total_open_gaps) * 100
                  : 0;
                return (
                  <div key={tier} style={{ display: "flex", alignItems: "center", gap: 10 }}>
                    <span
                      style={{
                        width: 70,
                        fontSize: 12,
                        fontWeight: 600,
                        color: colors.slate600,
                        textTransform: "capitalize",
                      }}
                    >
                      {tier}
                    </span>
                    <div
                      style={{
                        flex: 1,
                        height: 8,
                        borderRadius: 4,
                        background: colors.slate100,
                        overflow: "hidden",
                      }}
                    >
                      <div
                        style={{
                          height: "100%",
                          width: `${pct}%`,
                          borderRadius: 4,
                          background: TIER_COLORS[tier],
                          transition: "width 0.5s cubic-bezier(0.4,0,0.2,1)",
                        }}
                      />
                    </div>
                    <span
                      className="tabular-nums"
                      style={{ width: 32, fontSize: 12, fontWeight: 700, color: colors.slate900, textAlign: "right" }}
                    >
                      {value}
                    </span>
                  </div>
                );
              })}
            </div>

            {/* Actionable count */}
            <div
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 8,
                padding: "6px 12px",
                borderRadius: 999,
                background: data.actionable_gaps > 0 ? "#FEF3C7" : "#D1FAE5",
                color: data.actionable_gaps > 0 ? "#B45309" : "#047857",
                fontSize: 12,
                fontWeight: 600,
                alignSelf: "flex-start",
              }}
            >
              <Target size={12} />
              {data.actionable_gaps} actionable gap{data.actionable_gaps === 1 ? "" : "s"}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default ReadinessSummaryCard;
