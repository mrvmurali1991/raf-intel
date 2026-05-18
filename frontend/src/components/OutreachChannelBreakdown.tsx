"use client";

/**
 * OutreachChannelBreakdown — grouped bar chart (Recharts) showing
 * sent / responded / closed counts per outreach channel.
 */

import React from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { EmptyState } from "@/components/healthcare-ui";
import { getOutreachSummary, type OutreachSummary } from "@/lib/api";

const colors = {
  sent: "#3B82F6",
  responded: "#F59E0B",
  closed: "#10B981",
  slate200: "#E2E8F0",
  slate900: "#0F172A",
  slate600: "#475569",
};

const CHANNEL_LABELS: Record<string, string> = {
  sms: "SMS",
  portal: "Portal",
  phone: "Phone",
  email: "Email",
  letter: "Letter",
};

interface Props {
  year?: number;
  height?: number;
}

interface ChartRow {
  channel: string;
  sent: number;
  responded: number;
  closed: number;
}

export function OutreachChannelBreakdown({ year, height = 280 }: Props) {
  const { data, isLoading, isError } = useQuery<OutreachSummary>({
    queryKey: ["outreach-summary-chart", year ?? "all"],
    queryFn: () => getOutreachSummary(year),
  });

  const rows: ChartRow[] = React.useMemo(() => {
    if (!data?.by_channel) return [];
    return Object.entries(data.by_channel)
      .map(([channel, m]) => ({
        channel: CHANNEL_LABELS[channel] ?? channel,
        sent: m.sent ?? 0,
        responded: m.responded ?? 0,
        closed: m.closed ?? 0,
      }))
      .sort((a, b) => b.sent - a.sent);
  }, [data]);

  return (
    <div
      className="premium-card"
      style={{
        padding: 24,
        borderRadius: 10,
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          marginBottom: 16,
        }}
      >
        <h3
          className="gradient-text"
          style={{ margin: 0, fontSize: 16, fontWeight: 700 }}
        >
          Outreach Channel Performance
        </h3>
        <span style={{ fontSize: 12, color: colors.slate600 }}>
          {year ? `${year}` : "All time"}
        </span>
      </div>

      {isError ? (
        <EmptyState
          title="Could not load chart"
          description="Try refreshing the page."
        />
      ) : isLoading ? (
        <div
          className="shimmer"
          style={{ height, borderRadius: 8 }}
          aria-label="Loading chart"
        />
      ) : rows.length === 0 ? (
        <EmptyState
          title="No outreach data yet"
          description="Queue an outreach event for a gap to populate this chart."
        />
      ) : (
        <ResponsiveContainer width="100%" height={height}>
          <BarChart
            data={rows}
            margin={{ top: 8, right: 16, left: 0, bottom: 8 }}
          >
            <CartesianGrid stroke={colors.slate200} strokeDasharray="3 3" vertical={false} />
            <XAxis
              dataKey="channel"
              tick={{ fontSize: 12, fill: colors.slate600 }}
              axisLine={{ stroke: colors.slate200 }}
              tickLine={false}
            />
            <YAxis
              allowDecimals={false}
              tick={{ fontSize: 12, fill: colors.slate600 }}
              axisLine={{ stroke: colors.slate200 }}
              tickLine={false}
            />
            <Tooltip
              cursor={{ fill: "rgba(37, 99, 235, 0.06)" }}
              contentStyle={{
                borderRadius: 8,
                border: `1px solid ${colors.slate200}`,
                fontSize: 12,
              }}
            />
            <Legend
              wrapperStyle={{ fontSize: 12, paddingTop: 8 }}
              iconType="circle"
            />
            <Bar dataKey="sent" name="Sent" fill={colors.sent} radius={[4, 4, 0, 0]} />
            <Bar dataKey="responded" name="Responded" fill={colors.responded} radius={[4, 4, 0, 0]} />
            <Bar dataKey="closed" name="Closed" fill={colors.closed} radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}

export default OutreachChannelBreakdown;
