"use client";

/**
 * QProgressCard
 *
 * Displays the most-progressed active quarterly goal on the dashboard.
 * Shows metric label, % complete, actual vs target, days remaining,
 * and an on-track/behind-pace badge.
 *
 * Usage:
 *   <QProgressCard />
 */

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import {
  Target,
  TrendingUp,
  DollarSign,
  CheckCircle,
  Calendar,
  AlertTriangle,
  ChevronRight,
} from "lucide-react";
import { listGoals, type RafGoal, type GoalMetric } from "@/lib/api";

const METRIC_LABELS: Record<GoalMetric, string> = {
  raf_capture_count: "RAF Captures",
  revenue: "Revenue",
  gaps_closed: "Gaps Closed",
};

const METRIC_ICONS: Record<GoalMetric, React.ReactNode> = {
  raf_capture_count: <TrendingUp className="h-4 w-4" />,
  revenue: <DollarSign className="h-4 w-4" />,
  gaps_closed: <CheckCircle className="h-4 w-4" />,
};

function currentQuarter(): string {
  const d = new Date();
  const q = Math.floor(d.getMonth() / 3) + 1;
  return `${d.getFullYear()}-Q${q}`;
}

function formatValue(metric: GoalMetric, value: number): string {
  if (metric === "revenue")
    return `$${value.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
  return value.toLocaleString("en-US", { maximumFractionDigits: 0 });
}

export function QProgressCard() {
  const period = currentQuarter();

  const { data: goals = [], isLoading } = useQuery({
    queryKey: ["goals"],
    queryFn: () => listGoals(period),
    staleTime: 120_000,
  });

  // Pick the goal with highest percent_complete as the "most tracked"
  const featured: RafGoal | undefined = [...goals].sort(
    (a, b) => b.percent_complete - a.percent_complete,
  )[0];

  if (isLoading) {
    return (
      <div className="rounded-xl border border-slate-200 bg-white p-5 space-y-3 shadow-sm animate-pulse">
        <div className="h-4 bg-slate-100 rounded w-1/2" />
        <div className="h-2.5 bg-slate-100 rounded-full w-full" />
        <div className="h-3 bg-slate-100 rounded w-3/4" />
      </div>
    );
  }

  if (!featured) {
    return (
      <div className="rounded-xl border-2 border-dashed border-slate-200 bg-white p-5 text-sm text-slate-400 flex items-center justify-between">
        <span>No goals set for {period}.</span>
        <Link
          href="/goals"
          className="text-blue-600 hover:underline font-medium text-xs"
        >
          Set one
        </Link>
      </div>
    );
  }

  const pct = Math.min(featured.percent_complete, 100);
  const isComplete = pct >= 100;
  const barColor = isComplete
    ? "bg-green-500"
    : featured.on_track === false
    ? "bg-amber-400"
    : "bg-blue-500";

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 space-y-4 shadow-sm">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-slate-700 font-medium text-sm">
          <span className="p-1.5 bg-blue-50 rounded-lg text-blue-600">
            <Target className="h-4 w-4" />
          </span>
          Q-Progress: {period}
        </div>
        <Link
          href="/goals"
          className="flex items-center gap-0.5 text-xs text-blue-600 hover:underline font-medium"
          aria-label="View all goals"
        >
          All goals <ChevronRight className="h-3.5 w-3.5" />
        </Link>
      </div>

      {/* Metric label */}
      <div className="flex items-center gap-1.5 text-sm text-slate-600">
        <span className="text-slate-400">{METRIC_ICONS[featured.metric]}</span>
        {METRIC_LABELS[featured.metric]}
      </div>

      {/* Progress bar */}
      <div className="space-y-1.5">
        <div className="flex justify-between text-xs text-slate-500">
          <span>{formatValue(featured.metric, featured.actual_value)} actual</span>
          <span className="font-semibold text-slate-700">{pct}%</span>
          <span>{formatValue(featured.metric, featured.target_value)} target</span>
        </div>
        <div
          className="w-full bg-slate-100 rounded-full h-3 overflow-hidden"
          role="progressbar"
          aria-valuenow={pct}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label={`${METRIC_LABELS[featured.metric]} goal ${pct}% complete`}
        >
          <div
            className={`h-3 rounded-full transition-all duration-700 ${barColor}`}
            style={{ width: `${pct}%` }}
          />
        </div>
      </div>

      {/* Footer */}
      <div className="flex items-center justify-between text-xs text-slate-400 pt-0.5">
        <span className="flex items-center gap-1">
          <Calendar className="h-3.5 w-3.5" />
          {featured.days_remaining > 0
            ? `${featured.days_remaining}d left`
            : "Quarter ended"}
        </span>
        {isComplete ? (
          <span className="flex items-center gap-1 text-green-600 font-semibold">
            <CheckCircle className="h-3.5 w-3.5" />
            Goal met
          </span>
        ) : featured.on_track === false ? (
          <span className="flex items-center gap-1 text-amber-600 font-semibold">
            <AlertTriangle className="h-3.5 w-3.5" />
            Behind pace
          </span>
        ) : (
          <span className="text-green-600 font-semibold">On track</span>
        )}
      </div>
    </div>
  );
}
