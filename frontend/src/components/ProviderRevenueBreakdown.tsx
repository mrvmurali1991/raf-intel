"use client";

/**
 * Provider Revenue Opportunity Breakdown.
 *
 * Decomposes a provider's total $ revenue opportunity into three buckets:
 *   1. Recapture        – chronic HCCs from prior year not yet recaptured
 *   2. MEAT improvement – coded HCCs with MEAT < 0.75 (audit-vulnerable)
 *   3. New suspects     – open suspects not yet coded
 *
 * Backed by GET /api/providers/{id}/revenue-breakdown?year=YYYY.
 * Renders a Recharts donut PieChart with center total, legend rows showing
 * $ + %, and a "top contributors" list of the top HCC per bucket.
 */
import React from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
  Tooltip,
} from "recharts";
import {
  getProviderRevenueBreakdown,
  type ProviderRevenueBreakdown,
  type RevenueBreakdownBucket,
} from "@/lib/api";

// ---------------------------------------------------------------------------
// Design tokens (mirror RAFForecastCard for visual consistency)
// ---------------------------------------------------------------------------
const T = {
  white: "#FFFFFF",
  slate900: "#0F172A",
  slate700: "#334155",
  slate500: "#64748B",
  slate400: "#64748B",
  slate300: "#CBD5E1",
  slate200: "#E2E8F0",
  slate100: "#F1F5F9",
  emerald600: "#059669",
  emerald500: "#10B981",
  amber600: "#D97706",
  amber500: "#F59E0B",
  red500: "#EF4444",
  blue600: "#2563EB",
  blue500: "#3B82F6",
  violet500: "#8B5CF6",
};

// One color per bucket — order MUST match buckets returned by the backend
const BUCKET_COLORS: Record<string, string> = {
  Recapture: T.amber500,
  "MEAT improvement": T.violet500,
  "New suspects": T.emerald500,
};

function formatUSD(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "$0";
  const abs = Math.abs(n);
  if (abs >= 1_000_000) return `$${(n / 1_000_000).toFixed(2)}M`;
  if (abs >= 10_000) return `$${(n / 1_000).toFixed(0)}k`;
  if (abs >= 1_000) return `$${(n / 1_000).toFixed(1)}k`;
  return `$${Math.round(n).toLocaleString()}`;
}

function formatUSDFull(n: number): string {
  return `$${Math.round(n).toLocaleString()}`;
}

interface Props {
  providerId: number | string;
  year?: number;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------
export default function ProviderRevenueBreakdownCard({ providerId, year }: Props) {
  const q = useQuery<ProviderRevenueBreakdown>({
    queryKey: ["provider-revenue-breakdown", providerId, year],
    queryFn: () => getProviderRevenueBreakdown(providerId, year),
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  });

  if (q.isLoading) {
    return (
      <Card>
        <div style={{ color: T.slate500, fontSize: 13 }}>
          Loading revenue breakdown…
        </div>
      </Card>
    );
  }

  if (q.isError || !q.data) {
    return (
      <Card>
        <div style={{ color: T.red500, fontSize: 13 }}>
          Revenue breakdown unavailable. {(q.error as Error)?.message ?? ""}
        </div>
      </Card>
    );
  }

  const data = q.data;
  const buckets = data.buckets;
  const total = data.total;

  // Build chart data, dropping zero-value slices so the donut doesn't render
  // a flat ring of 0% wedges.
  const chartData = buckets
    .filter((b) => b.amount > 0)
    .map((b) => ({
      name: b.name,
      value: b.amount,
      count: b.count,
      pct: b.pct_of_total,
    }));

  const baseRate = data.assumptions?.base_rate ?? 12000;
  const persistencePct = Math.round((data.assumptions?.persistence ?? 0.85) * 100);

  return (
    <Card>
      {/* Header --------------------------------------------------------- */}
      <div
        style={{
          display: "flex",
          alignItems: "flex-start",
          justifyContent: "space-between",
          marginBottom: 12,
        }}
      >
        <div>
          <div
            style={{
              fontSize: 10,
              fontWeight: 600,
              textTransform: "uppercase",
              letterSpacing: "0.06em",
              color: T.slate400,
              marginBottom: 4,
            }}
          >
            Revenue Opportunity Breakdown
          </div>
          <div style={{ fontSize: 13, color: T.slate500 }}>
            Year {data.year} · panel {data.panel_size}
          </div>
        </div>
      </div>

      {/* Donut chart + legend ------------------------------------------ */}
      {total > 0 ? (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "200px 1fr",
            gap: 16,
            alignItems: "center",
          }}
        >
          <div style={{ position: "relative", width: 200, height: 200 }}>
            <ResponsiveContainer>
              <PieChart>
                <Pie
                  data={chartData}
                  dataKey="value"
                  nameKey="name"
                  cx="50%"
                  cy="50%"
                  innerRadius={56}
                  outerRadius={86}
                  paddingAngle={2}
                  isAnimationActive={false}
                >
                  {chartData.map((d) => (
                    <Cell
                      key={d.name}
                      fill={BUCKET_COLORS[d.name] ?? T.slate300}
                    />
                  ))}
                </Pie>
                <Tooltip
                  formatter={(val: any, _name: any, item: any) => {
                    const count = item?.payload?.count ?? 0;
                    return [
                      `${formatUSDFull(Number(val))} · ${count} HCC${count === 1 ? "" : "s"}`,
                      item?.payload?.name,
                    ];
                  }}
                  contentStyle={{
                    border: `1px solid ${T.slate200}`,
                    borderRadius: 6,
                    fontSize: 12,
                  }}
                />
              </PieChart>
            </ResponsiveContainer>
            {/* Center total label */}
            <div
              style={{
                position: "absolute",
                inset: 0,
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                justifyContent: "center",
                pointerEvents: "none",
              }}
            >
              <div
                style={{
                  fontSize: 10,
                  fontWeight: 600,
                  textTransform: "uppercase",
                  letterSpacing: "0.05em",
                  color: T.slate400,
                }}
              >
                Total
              </div>
              <div
                style={{
                  fontSize: 20,
                  fontWeight: 700,
                  color: T.slate900,
                  lineHeight: 1.1,
                }}
              >
                {formatUSD(total)}
              </div>
            </div>
          </div>

          {/* Legend ----------------------------------------------------- */}
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {buckets.map((b) => (
              <LegendRow
                key={b.name}
                bucket={b}
                color={BUCKET_COLORS[b.name] ?? T.slate300}
              />
            ))}
          </div>
        </div>
      ) : (
        <div
          style={{
            padding: "20px 0",
            fontSize: 13,
            color: T.slate500,
            fontStyle: "italic",
          }}
        >
          No revenue opportunity detected. Panel either has no open suspects,
          fully recaptured prior-year HCCs, or complete MEAT documentation.
        </div>
      )}

      {/* Top contributors list ----------------------------------------- */}
      {total > 0 && (
        <div
          style={{
            marginTop: 18,
            paddingTop: 14,
            borderTop: `1px solid ${T.slate100}`,
          }}
        >
          <div
            style={{
              fontSize: 10,
              fontWeight: 600,
              textTransform: "uppercase",
              letterSpacing: "0.05em",
              color: T.slate500,
              marginBottom: 8,
            }}
          >
            Top contributor per bucket
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {buckets.map((b) => (
              <TopContributorRow
                key={b.name}
                bucket={b}
                color={BUCKET_COLORS[b.name] ?? T.slate300}
              />
            ))}
          </div>
        </div>
      )}

      {/* Assumptions footnote ------------------------------------------ */}
      <div
        style={{
          marginTop: 12,
          paddingTop: 10,
          borderTop: `1px solid ${T.slate100}`,
          fontSize: 10,
          color: T.slate400,
          lineHeight: 1.5,
        }}
      >
        Assumes ${baseRate.toLocaleString()} PMPY × {persistencePct}% chronic
        persistence · MEAT threshold{" "}
        {Math.round((data.assumptions?.meat_threshold ?? 0.75) * 100)}%
      </div>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------
function Card({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        background: T.white,
        border: `1px solid ${T.slate200}`,
        borderRadius: 12,
        padding: 16,
        boxShadow: "0 1px 2px rgba(15, 23, 42, 0.04)",
      }}
    >
      {children}
    </div>
  );
}

function LegendRow({
  bucket,
  color,
}: {
  bucket: RevenueBreakdownBucket;
  color: string;
}) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: 10,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span
          style={{
            display: "inline-block",
            width: 10,
            height: 10,
            borderRadius: 2,
            background: color,
            flexShrink: 0,
          }}
        />
        <span
          style={{
            fontSize: 12,
            fontWeight: 600,
            color: T.slate700,
          }}
        >
          {bucket.name}
        </span>
        <span style={{ fontSize: 11, color: T.slate400 }}>
          ({bucket.count} HCC{bucket.count === 1 ? "" : "s"})
        </span>
      </div>
      <div style={{ textAlign: "right" }}>
        <div
          style={{
            fontSize: 13,
            fontWeight: 700,
            color: T.slate900,
            lineHeight: 1.1,
          }}
        >
          {formatUSD(bucket.amount)}
        </div>
        <div style={{ fontSize: 10, color: T.slate500, marginTop: 1 }}>
          {bucket.pct_of_total.toFixed(1)}%
        </div>
      </div>
    </div>
  );
}

function TopContributorRow({
  bucket,
  color,
}: {
  bucket: RevenueBreakdownBucket;
  color: string;
}) {
  const top = bucket.top_3_hccs?.[0];
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: 10,
        padding: "6px 10px",
        background: T.slate100,
        borderRadius: 6,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
        <span
          style={{
            display: "inline-block",
            width: 6,
            height: 6,
            borderRadius: "50%",
            background: color,
            flexShrink: 0,
          }}
        />
        <span
          style={{
            fontSize: 11,
            fontWeight: 600,
            color: T.slate500,
            textTransform: "uppercase",
            letterSpacing: "0.04em",
          }}
        >
          {bucket.name}
        </span>
      </div>
      <div
        style={{
          fontSize: 12,
          color: T.slate700,
          textAlign: "right",
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}
      >
        {top ? (
          <>
            <span style={{ fontWeight: 700 }}>HCC {top.hcc_code}</span>
            {top.hcc_label ? (
              <span style={{ color: T.slate500 }}> · {top.hcc_label}</span>
            ) : null}
            <span
              style={{
                marginLeft: 8,
                fontWeight: 700,
                color: T.slate900,
              }}
            >
              {formatUSD(top.dollars)}
            </span>
          </>
        ) : (
          <span style={{ color: T.slate400, fontStyle: "italic" }}>—</span>
        )}
      </div>
    </div>
  );
}
