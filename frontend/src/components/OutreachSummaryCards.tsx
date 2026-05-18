"use client";

/**
 * OutreachSummaryCards — 4-card strip summarising member-outreach performance.
 *
 * Cards:
 *   1. Total Sent           — events that left "queued"
 *   2. Conversion Rate      — closed / sent
 *   3. Avg Days to Response — sent_at -> responded_at (days)
 *   4. $ Recaptured         — total_closed × $3,000
 */

import React from "react";
import { useQuery } from "@tanstack/react-query";
import { Send, Target, Clock, DollarSign } from "lucide-react";

import { MetricCard } from "@/components/ui/metric-card";
import { getOutreachSummary, type OutreachSummary } from "@/lib/api";

const REVENUE_PER_CLOSURE = 3000;

const colors = {
  primary: "#2563EB",
  emerald: "#10B981",
  amber: "#F59E0B",
  violet: "#8B5CF6",
};

interface Props {
  year?: number;
}

function formatCurrency(n: number): string {
  return "$" + Math.round(n).toLocaleString("en-US");
}

function formatPercent(n: number): string {
  return (n * 100).toFixed(1) + "%";
}

function formatDays(n: number | null): string {
  if (n == null) return "—";
  if (n < 1) return `${(n * 24).toFixed(1)}h`;
  return `${n.toFixed(1)}d`;
}

export function OutreachSummaryCards({ year }: Props) {
  const { data, isLoading, isError } = useQuery<OutreachSummary>({
    queryKey: ["outreach-summary", year ?? "all"],
    queryFn: () => getOutreachSummary(year),
  });

  // Derived $ recaptured: closures × $3,000.  Backed by `estimated_revenue`
  // from the API but we recompute defensively for the unit-cost transparency
  // promised in the spec.
  const recaptured = React.useMemo(() => {
    if (!data) return 0;
    return data.total_closed * REVENUE_PER_CLOSURE;
  }, [data]);

  if (isError) {
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
        Failed to load outreach summary.
      </div>
    );
  }

  const cards = [
    {
      label: "Total Sent",
      value: isLoading ? "—" : (data?.total_sent ?? 0).toLocaleString(),
      subtitle: data ? `${data.total_responded} responses` : undefined,
      color: colors.primary,
      icon: <Send size={18} />,
    },
    {
      label: "Conversion Rate",
      value: isLoading ? "—" : formatPercent(data?.conversion_rate ?? 0),
      subtitle: data ? `${data.total_closed} gaps closed` : undefined,
      color: colors.emerald,
      icon: <Target size={18} />,
    },
    {
      label: "Avg Days to Response",
      value: isLoading ? "—" : formatDays(data?.avg_days_to_response ?? null),
      subtitle: "sent → responded",
      color: colors.amber,
      icon: <Clock size={18} />,
    },
    {
      label: "$ Recaptured via Outreach",
      value: isLoading ? "—" : formatCurrency(recaptured),
      subtitle: `${data?.total_closed ?? 0} × $${REVENUE_PER_CLOSURE.toLocaleString()}`,
      color: colors.violet,
      icon: <DollarSign size={18} />,
    },
  ];

  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(4, minmax(0, 1fr))",
        gap: 16,
      }}
    >
      {cards.map((c) => (
        <MetricCard
          key={c.label}
          label={c.label}
          value={c.value}
          subtitle={c.subtitle}
          icon={c.icon}
          loading={isLoading}
        />
      ))}
    </div>
  );
}

export default OutreachSummaryCards;
