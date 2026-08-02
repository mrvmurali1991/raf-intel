"use client";

/**
 * RAF Financial Forecast Card.
 *
 * Surfaces the projected $ revenue impact of accepting a patient's open
 * suspect conditions and re-capturing prior-year chronic HCCs.  Backed by
 * GET /api/forecast/patient/{pid}.
 */
import React from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  Cell,
} from "recharts";
import { getPatientForecast, type PatientForecast } from "@/lib/api";

// Chart-only hex constants (Recharts doesn't support className)
const CHART = {
  slate100: "#F1F5F9",
  slate200: "#E2E8F0",
  slate400: "#64748B",
  slate500: "#64748B",
  emerald500: "#10B981",
  amber500: "#F59E0B",
  blue600: "#2563EB",
};

function formatUSD(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  const abs = Math.abs(n);
  if (abs >= 1_000_000) return `$${(n / 1_000_000).toFixed(2)}M`;
  if (abs >= 1_000) return `$${(n / 1_000).toFixed(1)}k`;
  return `$${Math.round(n).toLocaleString()}`;
}

function formatRAF(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(3)}`;
}

interface Props {
  pid: number | string;
  year?: number;
}

export default function RAFForecastCard({ pid, year }: Props) {
  const q = useQuery<PatientForecast>({
    queryKey: ["patient-forecast", pid, year],
    queryFn: () => getPatientForecast(pid, year),
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  });

  if (q.isLoading) {
    return (
      <Card>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Calculating financial forecast…
        </p>
      </Card>
    );
  }

  if (q.isError || !q.data) {
    return (
      <Card>
        <p className="text-sm text-red-500 dark:text-red-400">
          Forecast unavailable. {(q.error as Error)?.message ?? ""}
        </p>
      </Card>
    );
  }

  const f = q.data;
  const netDelta = f.net_projected_revenue - f.current_revenue;
  const positive = netDelta >= 0;

  return (
    <Card>
      {/* Header */}
      <div className="flex items-center justify-between mb-3.5">
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400 mb-1">
            RAF Financial Forecast
          </div>
          <div className="text-lg font-bold text-slate-900 dark:text-slate-50">
            ${f.suspect_lift_revenue.toLocaleString(undefined, {
              maximumFractionDigits: 0,
            })}{" "}
            <span className="text-sm text-slate-500 dark:text-slate-400 font-medium">
              opportunity
            </span>
          </div>
        </div>

        <div
          className={`px-2.5 py-1 rounded-full text-[11px] font-bold ${
            positive
              ? "bg-emerald-50 dark:bg-emerald-950 text-emerald-600 dark:text-emerald-400"
              : "bg-red-50 dark:bg-red-950 text-red-500 dark:text-red-400"
          }`}
        >
          {positive ? "▲" : "▼"} {formatUSD(Math.abs(netDelta))}
        </div>
      </div>

      {/* Metrics row */}
      <div
        className="raf-forecast-metrics grid grid-cols-4 gap-3 py-3 border-t border-b border-slate-100 dark:border-slate-800"
      >
        <Metric
          label="Current"
          raf={f.current_raf}
          revenue={f.current_revenue}
          colorClass="text-slate-700 dark:text-slate-200"
        />
        <Metric
          label="Suspect Lift"
          raf={f.suspect_lift_raf}
          revenue={f.suspect_lift_revenue}
          colorClass="text-emerald-600 dark:text-emerald-400"
          positive
        />
        <Metric
          label="At Risk"
          raf={-f.removal_risk_raf}
          revenue={-f.removal_risk_revenue}
          colorClass="text-amber-600 dark:text-amber-400"
        />
        <Metric
          label="Projected"
          raf={f.net_projected_raf}
          revenue={f.net_projected_revenue}
          colorClass="text-blue-600 dark:text-blue-400"
        />
      </div>

      {/* By-suspect chart */}
      {f.by_suspect.length > 0 ? (
        <div className="mt-4">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400 mb-2">
            Top Suspects · $ Lift Per HCC
          </div>
          <div style={{ width: "100%", height: 140 }}>
            <ResponsiveContainer>
              <BarChart
                data={f.by_suspect.slice(0, 6).map((s) => ({
                  name: `HCC ${s.hcc}`,
                  lift: s.lift_revenue,
                  confidence: s.confidence,
                }))}
                layout="vertical"
                margin={{ top: 4, right: 16, bottom: 0, left: 16 }}
              >
                <XAxis
                  type="number"
                  tickFormatter={(v) => formatUSD(v)}
                  stroke={CHART.slate400}
                  fontSize={10}
                />
                <YAxis
                  type="category"
                  dataKey="name"
                  width={70}
                  stroke={CHART.slate500}
                  fontSize={11}
                  tickLine={false}
                  axisLine={false}
                />
                <Tooltip
                  formatter={(value: any) => formatUSD(Number(value))}
                  cursor={{ fill: CHART.slate100 }}
                  contentStyle={{
                    border: `1px solid ${CHART.slate200}`,
                    borderRadius: 6,
                    fontSize: 12,
                  }}
                />
                <Bar dataKey="lift" radius={[0, 4, 4, 0]}>
                  {f.by_suspect.slice(0, 6).map((s, idx) => (
                    <Cell
                      key={idx}
                      fill={
                        s.confidence >= 0.75
                          ? CHART.emerald500
                          : s.confidence >= 0.5
                            ? CHART.blue600
                            : CHART.amber500
                      }
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      ) : (
        <p className="mt-3.5 text-xs text-slate-500 dark:text-slate-400 italic">
          No open suspects.  Run a suspect scan to surface coding opportunities.
        </p>
      )}

      {/* Footer assumptions */}
      <div className="mt-3 pt-2.5 border-t border-slate-100 dark:border-slate-800 text-[10px] text-slate-500 dark:text-slate-400 leading-relaxed">
        Projection = Σ(coefficient × confidence) × ${f.base_rate.toLocaleString()} PMPY ·
        segment {f.model_segment} · persistence {Math.round(f.persistence_assumption * 100)}%
      </div>
      <style>{`
        @media (max-width: 640px) {
          .raf-forecast-metrics { grid-template-columns: repeat(2, 1fr) !important; }
        }
      `}</style>
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

function Metric({
  label,
  raf,
  revenue,
  colorClass,
  positive = false,
}: {
  label: string;
  raf: number;
  revenue: number;
  colorClass: string;
  positive?: boolean;
}) {
  return (
    <div>
      <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400 mb-1">
        {label}
      </div>
      <div className={`text-base font-bold leading-tight ${colorClass}`}>
        {revenue >= 0 || positive
          ? formatUSD(Math.abs(revenue))
          : `−${formatUSD(Math.abs(revenue))}`}
      </div>
      <div className="text-[11px] text-slate-500 dark:text-slate-400 font-mono mt-0.5">
        {formatRAF(raf)} RAF
      </div>
    </div>
  );
}
