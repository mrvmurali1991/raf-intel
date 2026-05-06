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

const T = {
  white: "#FFFFFF",
  slate900: "#0F172A",
  slate700: "#334155",
  slate500: "#64748B",
  slate400: "#94A3B8",
  slate200: "#E2E8F0",
  slate100: "#F1F5F9",
  slate50: "#F8FAFC",
  blue600: "#2563EB",
  emerald500: "#10B981",
  emerald600: "#059669",
  amber500: "#F59E0B",
  red500: "#EF4444",
  red600: "#DC2626",
  violet500: "#8B5CF6",
};

function formatUSD(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "$0";
  const abs = Math.abs(n);
  if (abs >= 1_000_000) return `${n < 0 ? "-" : ""}$${(Math.abs(n) / 1_000_000).toFixed(2)}M`;
  if (abs >= 10_000) return `${n < 0 ? "-" : ""}$${(Math.abs(n) / 1_000).toFixed(0)}k`;
  if (abs >= 1_000) return `${n < 0 ? "-" : ""}$${(Math.abs(n) / 1_000).toFixed(1)}k`;
  return `${n < 0 ? "-" : ""}$${Math.round(Math.abs(n)).toLocaleString()}`;
}

interface KpiProps {
  label: string;
  value: string;
  subtle?: string;
  color?: string;
  icon?: React.ReactNode;
  emphasis?: "good" | "bad" | "neutral";
}

function KpiCard({ label, value, subtle, color, icon, emphasis }: KpiProps) {
  const accent =
    emphasis === "bad" ? T.red600 : emphasis === "good" ? T.emerald600 : color || T.slate900;
  return (
    <div
      style={{
        background: T.white,
        border: `1px solid ${T.slate200}`,
        borderRadius: 12,
        padding: 16,
        display: "flex",
        flexDirection: "column",
        gap: 6,
        minHeight: 100,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8, color: T.slate500 }}>
        {icon}
        <span style={{ fontSize: 11, fontWeight: 600, textTransform: "uppercase", letterSpacing: 0.5 }}>
          {label}
        </span>
      </div>
      <div style={{ fontSize: 24, fontWeight: 700, color: accent, fontVariantNumeric: "tabular-nums" }}>
        {value}
      </div>
      {subtle && (
        <div style={{ fontSize: 12, color: T.slate500 }}>{subtle}</div>
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
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(6, 1fr)",
          gap: 12,
          marginBottom: 16,
        }}
      >
        {[1, 2, 3, 4, 5, 6].map((i) => (
          <div
            key={i}
            style={{
              height: 100,
              borderRadius: 12,
              background: T.slate100,
              border: `1px solid ${T.slate200}`,
            }}
          />
        ))}
      </div>
    );
  }

  if (isError || !data) {
    return (
      <div
        style={{
          padding: "12px 16px",
          border: `1px solid #FECACA`,
          background: "#FEF2F2",
          color: "#B91C1C",
          borderRadius: 10,
          display: "flex",
          alignItems: "center",
          gap: 8,
          fontSize: 13,
        }}
      >
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
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {/* KPI strip */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(6, minmax(0, 1fr))",
          gap: 12,
        }}
      >
        <KpiCard
          label="$ at risk"
          value={formatUSD(data.total_dollars_at_risk)}
          subtle={`${data.total_gaps_open.toLocaleString()} open gaps`}
          color={T.red600}
          icon={<AlertTriangle size={14} />}
          emphasis="bad"
        />
        <KpiCard
          label="$ recaptured YTD"
          value={formatUSD(data.ytd_dollars_recaptured)}
          subtle={`${data.ytd_closures} closures`}
          color={T.emerald600}
          icon={<DollarSign size={14} />}
          emphasis="good"
        />
        <KpiCard
          label="Forecast YE"
          value={formatUSD(data.forecast_ye_dollars)}
          subtle={`Budget ${formatUSD(data.budget_dollars)}`}
          color={T.blue600}
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
          color={T.violet500}
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
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "2fr 1fr",
          gap: 12,
        }}
      >
        <div
          style={{
            background: T.white,
            border: `1px solid ${T.slate200}`,
            borderRadius: 12,
            padding: 16,
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              marginBottom: 12,
              fontSize: 13,
              fontWeight: 600,
              color: T.slate700,
            }}
          >
            <Calendar size={14} /> Quarterly $ — recaptured vs remaining
          </div>
          <div style={{ width: "100%", height: 220 }}>
            <ResponsiveContainer>
              <BarChart data={quarterData} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                <CartesianGrid stroke={T.slate100} vertical={false} />
                <XAxis dataKey="name" tick={{ fontSize: 11, fill: T.slate500 }} />
                <YAxis tick={{ fontSize: 11, fill: T.slate500 }} tickFormatter={(v) => formatUSD(v)} />
                <Tooltip
                  formatter={(v) => formatUSD(Number(v))}
                  contentStyle={{ fontSize: 12, borderRadius: 8 }}
                />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Bar dataKey="Recaptured" stackId="a" fill={T.emerald500} radius={[0, 0, 0, 0]} />
                <Bar dataKey="Remaining" stackId="a" fill={T.amber500} radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div
          style={{
            background: T.white,
            border: `1px solid ${T.slate200}`,
            borderRadius: 12,
            padding: 16,
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              marginBottom: 12,
              fontSize: 13,
              fontWeight: 600,
              color: T.slate700,
            }}
          >
            <TrendingUp size={14} /> Year-over-year
          </div>
          <div style={{ width: "100%", height: 220 }}>
            <ResponsiveContainer>
              <LineChart data={yoyData} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                <CartesianGrid stroke={T.slate100} vertical={false} />
                <XAxis dataKey="year" tick={{ fontSize: 11, fill: T.slate500 }} />
                <YAxis tick={{ fontSize: 11, fill: T.slate500 }} tickFormatter={(v) => formatUSD(v)} />
                <Tooltip
                  formatter={(v) => formatUSD(Number(v))}
                  contentStyle={{ fontSize: 12, borderRadius: 8 }}
                />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Line type="monotone" dataKey="Recaptured" stroke={T.emerald600} strokeWidth={2} dot />
                <Line type="monotone" dataKey="AtRisk" stroke={T.red500} strokeWidth={2} dot />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>
    </div>
  );
}
