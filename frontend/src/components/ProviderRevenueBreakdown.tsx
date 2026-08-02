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

// Chart-only hex constants (Recharts doesn't support className)
const CHART = {
  slate200: "#E2E8F0",
  slate300: "#CBD5E1",
  amber500: "#F59E0B",
  violet500: "#8B5CF6",
  emerald500: "#10B981",
};

const BUCKET_COLORS: Record<string, string> = {
  Recapture: CHART.amber500,
  "MEAT improvement": CHART.violet500,
  "New suspects": CHART.emerald500,
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
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Loading revenue breakdown…
        </p>
      </Card>
    );
  }

  if (q.isError || !q.data) {
    return (
      <Card>
        <p className="text-sm text-red-500 dark:text-red-400">
          Revenue breakdown unavailable. {(q.error as Error)?.message ?? ""}
        </p>
      </Card>
    );
  }

  const data = q.data;
  const buckets = data.buckets;
  const total = data.total;

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
      {/* Header */}
      <div className="flex items-start justify-between mb-3">
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400 mb-1">
            Revenue Opportunity Breakdown
          </div>
          <div className="text-sm text-slate-500 dark:text-slate-400">
            Year {data.year} · panel {data.panel_size}
          </div>
        </div>
      </div>

      {/* Donut chart + legend */}
      {total > 0 ? (
        <div className="grid gap-4 items-center" style={{ gridTemplateColumns: "200px 1fr" }}>
          <div className="relative" style={{ width: 200, height: 200 }}>
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
                      fill={BUCKET_COLORS[d.name] ?? CHART.slate300}
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
                    border: `1px solid ${CHART.slate200}`,
                    borderRadius: 6,
                    fontSize: 12,
                  }}
                />
              </PieChart>
            </ResponsiveContainer>
            {/* Center total label */}
            <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
              <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
                Total
              </div>
              <div className="text-xl font-bold text-slate-900 dark:text-slate-50 leading-tight">
                {formatUSD(total)}
              </div>
            </div>
          </div>

          {/* Legend */}
          <div className="flex flex-col gap-2">
            {buckets.map((b) => (
              <LegendRow
                key={b.name}
                bucket={b}
                color={BUCKET_COLORS[b.name] ?? CHART.slate300}
              />
            ))}
          </div>
        </div>
      ) : (
        <p className="py-5 text-sm text-slate-500 dark:text-slate-400 italic">
          No revenue opportunity detected. Panel either has no open suspects,
          fully recaptured prior-year HCCs, or complete MEAT documentation.
        </p>
      )}

      {/* Top contributors list */}
      {total > 0 && (
        <div className="mt-[18px] pt-3.5 border-t border-slate-100 dark:border-slate-800">
          <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400 mb-2">
            Top contributor per bucket
          </div>
          <div className="flex flex-col gap-1.5">
            {buckets.map((b) => (
              <TopContributorRow
                key={b.name}
                bucket={b}
                color={BUCKET_COLORS[b.name] ?? CHART.slate300}
              />
            ))}
          </div>
        </div>
      )}

      {/* Assumptions footnote */}
      <div className="mt-3 pt-2.5 border-t border-slate-100 dark:border-slate-800 text-[10px] text-slate-500 dark:text-slate-400 leading-relaxed">
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
    <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-[10px] p-4 shadow-sm">
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
    <div className="flex items-center justify-between gap-2.5">
      <div className="flex items-center gap-2">
        <span
          className="inline-block w-2.5 h-2.5 rounded-sm shrink-0"
          style={{ background: color }}
        />
        <span className="text-xs font-semibold text-slate-700 dark:text-slate-200">
          {bucket.name}
        </span>
        <span className="text-[11px] text-slate-500 dark:text-slate-400">
          ({bucket.count} HCC{bucket.count === 1 ? "" : "s"})
        </span>
      </div>
      <div className="text-right">
        <div className="text-[13px] font-bold text-slate-900 dark:text-slate-50 leading-tight">
          {formatUSD(bucket.amount)}
        </div>
        <div className="text-[10px] text-slate-500 dark:text-slate-400 mt-px">
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
    <div className="flex items-center justify-between gap-2.5 px-2.5 py-1.5 bg-slate-100 dark:bg-slate-800 rounded-md">
      <div className="flex items-center gap-2 min-w-0">
        <span
          className="inline-block w-1.5 h-1.5 rounded-full shrink-0"
          style={{ background: color }}
        />
        <span className="text-[11px] font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wide">
          {bucket.name}
        </span>
      </div>
      <div className="text-xs text-slate-700 dark:text-slate-200 text-right overflow-hidden text-ellipsis whitespace-nowrap">
        {top ? (
          <>
            <span className="font-bold">HCC {top.hcc_code}</span>
            {top.hcc_label ? (
              <span className="text-slate-500 dark:text-slate-400"> · {top.hcc_label}</span>
            ) : null}
            <span className="ml-2 font-bold text-slate-900 dark:text-slate-50">
              {formatUSD(top.dollars)}
            </span>
          </>
        ) : (
          <span className="text-slate-500 dark:text-slate-400 italic">—</span>
        )}
      </div>
    </div>
  );
}
