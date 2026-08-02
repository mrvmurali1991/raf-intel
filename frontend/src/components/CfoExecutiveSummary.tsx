"use client";

/**
 * CFO Executive Summary — top-of-page strip on /recapture.
 *
 * Renders six high-density KPI cards plus quarterly bar chart and YoY mini line.
 * Backed by `GET /api/recapture/cfo/summary` and `/api/recapture/cfo/yoy`.
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
  CartesianGrid,
  LineChart,
  Line,
  Legend,
} from "recharts";
import {
  AlertTriangle,
  Shield,
  TrendingUp,
  TrendingDown,
  DollarSign,
  Activity,
  Calendar,
} from "lucide-react";

import { getCfoSummary, getCfoYoy, type CfoExecutiveSummary } from "@/lib/api";

function formatUSD(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "$0";
  const abs = Math.abs(n);
  if (abs >= 1_000_000) return `${n < 0 ? "-" : ""}$${(Math.abs(n) / 1_000_000).toFixed(2)}M`;
  if (abs >= 10_000) return `${n < 0 ? "-" : ""}$${(Math.abs(n) / 1_000).toFixed(0)}k`;
  if (abs >= 1_000) return `${n < 0 ? "-" : ""}$${(Math.abs(n) / 1_000).toFixed(1)}k`;
  return `${n < 0 ? "-" : ""}$${Math.round(Math.abs(n)).toLocaleString()}`;
}

const EMPHASIS_CLASSES: Record<string, string> = {
  bad: "text-red-600 dark:text-red-400",
  good: "text-emerald-600 dark:text-emerald-400",
};

const COLOR_CLASSES: Record<string, string> = {
  "#DC2626": "text-red-600 dark:text-red-400",
  "#059669": "text-emerald-600 dark:text-emerald-400",
  "#2563EB": "text-blue-600 dark:text-blue-400",
  "#8B5CF6": "text-violet-500 dark:text-violet-400",
};

interface KpiProps {
  label: string;
  value: string;
  subtle?: string;
  color?: string;
  icon?: React.ReactNode;
  emphasis?: "good" | "bad" | "neutral";
}

function KpiCard({ label, value, subtle, color, icon, emphasis }: KpiProps) {
  const valueClass =
    emphasis && EMPHASIS_CLASSES[emphasis]
      ? EMPHASIS_CLASSES[emphasis]
      : color && COLOR_CLASSES[color]
        ? COLOR_CLASSES[color]
        : "text-slate-900 dark:text-slate-50";

  return (
    <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-[10px] p-4 flex flex-col gap-1.5 min-h-[100px]">
      <div className="flex items-center gap-2 text-slate-500 dark:text-slate-400">
        {icon}
        <span className="text-[11px] font-semibold uppercase tracking-wide">
          {label}
        </span>
      </div>
      <div className={`text-2xl font-bold tabular-nums ${valueClass}`}>
        {value}
      </div>
      {subtle && (
        <div className="text-xs text-slate-500 dark:text-slate-400">{subtle}</div>
      )}
    </div>
  );
}

interface Props {
  year?: number;
}

export default function CfoExecutiveSummary({ year }: Props) {
  const yr = year ?? new Date().getFullYear();

  const { data, isLoading, isError } = useQuery<CfoExecutiveSummary>({
    queryKey: ["cfo-summary", yr],
    queryFn: () => getCfoSummary(yr),
  });

  const { data: yoy } = useQuery({
    queryKey: ["cfo-yoy", 3],
    queryFn: () => getCfoYoy(3),
  });

  if (isLoading) {
    return (
      <div className="grid grid-cols-6 gap-3 mb-4">
        {[1, 2, 3, 4, 5, 6].map((i) => (
          <div
            key={i}
            className="h-[100px] rounded-[10px] bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-slate-700"
          />
        ))}
      </div>
    );
  }

  if (isError || !data) {
    return (
      <div className="px-4 py-3 border border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-950 text-red-700 dark:text-red-400 rounded-[10px] flex items-center gap-2 text-[13px]">
        <AlertTriangle size={16} />
        Unable to load CFO summary.
      </div>
    );
  }

  const varianceGood = data.variance_to_budget >= 0;

  const quarterData = data.quarter_breakdown.map((q) => ({
    name: q.quarter,
    Recaptured: q.recaptured_dollars,
    Remaining: q.remaining_dollars,
  }));

  const yoyData = (yoy?.series || []).map((r) => ({
    year: r.year,
    Recaptured: r.recaptured_dollars,
    AtRisk: r.at_risk_dollars,
  }));

  return (
    <div className="flex flex-col gap-4">
      {/* KPI strip */}
      <div className="grid grid-cols-6 gap-3">
        <KpiCard
          label="$ at risk"
          value={formatUSD(data.total_dollars_at_risk)}
          subtle={`${data.total_gaps_open.toLocaleString()} open gaps`}
          color="#DC2626"
          icon={<AlertTriangle size={14} />}
          emphasis="bad"
        />
        <KpiCard
          label="$ recaptured YTD"
          value={formatUSD(data.ytd_dollars_recaptured)}
          subtle={`${data.ytd_closures} closures`}
          color="#059669"
          icon={<DollarSign size={14} />}
          emphasis="good"
        />
        <KpiCard
          label="Forecast YE"
          value={formatUSD(data.forecast_ye_dollars)}
          subtle={`Budget ${formatUSD(data.budget_dollars)}`}
          color="#2563EB"
          icon={<TrendingUp size={14} />}
        />
        <KpiCard
          label="Variance vs. budget"
          value={formatUSD(data.variance_to_budget)}
          subtle={varianceGood ? "ahead of budget" : "below budget"}
          icon={varianceGood ? <TrendingUp size={14} /> : <TrendingDown size={14} />}
          emphasis={varianceGood ? "good" : "bad"}
        />
        <KpiCard
          label="Velocity"
          value={`${formatUSD(data.ytd_velocity_per_day)}/day`}
          subtle={`${data.days_elapsed}/${data.days_in_year} days`}
          icon={<Activity size={14} />}
          color="#8B5CF6"
        />
        <KpiCard
          label="Audit risk"
          value={data.audit_risk_flag ? "Flagged" : "Clear"}
          subtle={`${data.audit_dual_coded_pct.toFixed(1)}% dual-coded`}
          icon={<Shield size={14} />}
          emphasis={data.audit_risk_flag ? "bad" : "good"}
        />
      </div>

      {/* Quarterly + YoY charts */}
      <div className="grid grid-cols-[2fr_1fr] gap-3">
        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-[10px] p-4">
          <div className="flex items-center gap-2 mb-3 text-[13px] font-semibold text-slate-700 dark:text-slate-200">
            <Calendar size={14} /> Quarterly $ — recaptured vs remaining
          </div>
          <div style={{ width: "100%", height: 220 }}>
            <ResponsiveContainer>
              <BarChart data={quarterData} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                {/* Recharts: hex colors required for SVG rendering */}
                <CartesianGrid stroke="#F1F5F9" vertical={false} />
                <XAxis dataKey="name" tick={{ fontSize: 11, fill: "#64748B" }} />
                <YAxis tick={{ fontSize: 11, fill: "#64748B" }} tickFormatter={(v) => formatUSD(v)} />
                <Tooltip
                  formatter={(v) => formatUSD(Number(v))}
                  contentStyle={{ fontSize: 12, borderRadius: 8 }}
                />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Bar dataKey="Recaptured" stackId="a" fill="#10B981" radius={[0, 0, 0, 0]} />
                <Bar dataKey="Remaining" stackId="a" fill="#F59E0B" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-[10px] p-4">
          <div className="flex items-center gap-2 mb-3 text-[13px] font-semibold text-slate-700 dark:text-slate-200">
            <TrendingUp size={14} /> Year-over-year
          </div>
          <div style={{ width: "100%", height: 220 }}>
            <ResponsiveContainer>
              <LineChart data={yoyData} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                {/* Recharts: hex colors required for SVG rendering */}
                <CartesianGrid stroke="#F1F5F9" vertical={false} />
                <XAxis dataKey="year" tick={{ fontSize: 11, fill: "#64748B" }} />
                <YAxis tick={{ fontSize: 11, fill: "#64748B" }} tickFormatter={(v) => formatUSD(v)} />
                <Tooltip
                  formatter={(v) => formatUSD(Number(v))}
                  contentStyle={{ fontSize: 12, borderRadius: 8 }}
                />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Line type="monotone" dataKey="Recaptured" stroke="#059669" strokeWidth={2} dot />
                <Line type="monotone" dataKey="AtRisk" stroke="#EF4444" strokeWidth={2} dot />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>
    </div>
  );
}
