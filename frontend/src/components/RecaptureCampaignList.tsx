"use client";

/**
 * RecaptureCampaignList — list view of bulk-recapture campaigns.
 *
 * Shows status pill, progress bar (closed / total), $-recaptured, and a
 * "Manage" CTA that opens the kanban view for that campaign.
 *
 * Wired to /api/recapture/campaigns via React Query.  Re-renders whenever
 * a campaign is created from CreateCampaignModal (we listen to the
 * `recapture-campaigns:changed` window event).
 */

import React, { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Plus,
  RefreshCw,
  ChevronRight,
  CalendarDays,
  TrendingUp,
} from "lucide-react";

import {
  listRecaptureCampaigns,
  type RecaptureCampaign,
  type RecaptureCampaignStatus,
} from "@/lib/api";

const STATUS_COLORS: Record<RecaptureCampaignStatus, { bg: string; fg: string }> = {
  draft:     { bg: "#F1F5F9", fg: "#475569" },
  active:    { bg: "#DBEAFE", fg: "#1D4ED8" },
  paused:    { bg: "#FEF3C7", fg: "#92400E" },
  completed: { bg: "#D1FAE5", fg: "#065F46" },
  archived:  { bg: "#E2E8F0", fg: "#64748B" },
};

function formatCurrency(n: number): string {
  return "$" + Math.round(n).toLocaleString("en-US");
}

interface Props {
  onSelect?: (campaign: RecaptureCampaign) => void;
  onCreateClick?: () => void;
}

export default function RecaptureCampaignList({ onSelect, onCreateClick }: Props) {
  const qc = useQueryClient();
  const [statusFilter, setStatusFilter] = useState<RecaptureCampaignStatus | "all">("all");

  const { data, isLoading, isError, refetch, isFetching } = useQuery({
    queryKey: ["recapture-campaigns", statusFilter],
    queryFn: () =>
      listRecaptureCampaigns(
        statusFilter === "all" ? undefined : statusFilter
      ),
    staleTime: 30_000,
  });

  // Re-fetch when other components signal a change (create / assign / mark).
  useEffect(() => {
    const handler = () => qc.invalidateQueries({ queryKey: ["recapture-campaigns"] });
    window.addEventListener("recapture-campaigns:changed", handler);
    return () => window.removeEventListener("recapture-campaigns:changed", handler);
  }, [qc]);

  const campaigns = data?.campaigns ?? [];

  return (
    <div className="rounded-xl border border-slate-200 bg-white shadow-sm">
      <header className="flex items-center justify-between border-b border-slate-100 p-4">
        <div>
          <h2 className="text-lg font-semibold text-slate-900">
            Recapture campaigns
          </h2>
          <p className="text-sm text-slate-500">
            Bulk-assign open recapture gaps to coder teams
          </p>
        </div>
        <div className="flex items-center gap-2">
          <select
            className="rounded-md border border-slate-200 bg-white px-2 py-1.5 text-sm text-slate-700"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as typeof statusFilter)}
          >
            <option value="all">All statuses</option>
            <option value="draft">Draft</option>
            <option value="active">Active</option>
            <option value="paused">Paused</option>
            <option value="completed">Completed</option>
            <option value="archived">Archived</option>
          </select>
          <button
            type="button"
            onClick={() => refetch()}
            className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-slate-200 text-slate-600 hover:bg-slate-50"
            aria-label="Refresh"
          >
            <RefreshCw size={14} className={isFetching ? "animate-spin" : ""} />
          </button>
          <button
            type="button"
            onClick={onCreateClick}
            className="inline-flex items-center gap-1.5 rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700"
          >
            <Plus size={14} /> New campaign
          </button>
        </div>
      </header>

      {isLoading ? (
        <div className="p-8 text-center text-sm text-slate-500">Loading campaigns…</div>
      ) : isError ? (
        <div className="p-8 text-center text-sm text-rose-600">
          Failed to load campaigns. Please retry.
        </div>
      ) : campaigns.length === 0 ? (
        <div className="p-10 text-center">
          <p className="text-sm text-slate-500">No campaigns yet.</p>
          <button
            type="button"
            onClick={onCreateClick}
            className="mt-3 inline-flex items-center gap-1.5 rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700"
          >
            <Plus size={14} /> Create your first campaign
          </button>
        </div>
      ) : (
        <ul className="divide-y divide-slate-100">
          {campaigns.map((c) => {
            const stats = c.stats ?? {
              total_gaps: 0,
              in_progress: 0,
              closed: 0,
              dismissed: 0,
              closure_rate: 0,
              recaptured_revenue: 0,
              at_risk_revenue: 0,
            };
            const pct = stats.total_gaps
              ? Math.min(100, (stats.closed / stats.total_gaps) * 100)
              : 0;
            const colors = STATUS_COLORS[c.status];
            return (
              <li
                key={c.id}
                className="cursor-pointer p-4 hover:bg-slate-50"
                onClick={() => onSelect?.(c)}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => {
                  if (e.key === "Enter") onSelect?.(c);
                }}
              >
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <h3 className="truncate text-base font-semibold text-slate-900">
                        {c.name}
                      </h3>
                      <span
                        className="rounded-full px-2 py-0.5 text-xs font-medium"
                        style={{ background: colors.bg, color: colors.fg }}
                      >
                        {c.status}
                      </span>
                    </div>
                    {c.description ? (
                      <p className="mt-1 line-clamp-1 text-sm text-slate-500">
                        {c.description}
                      </p>
                    ) : null}
                    <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500">
                      <span>
                        {stats.closed}/{stats.total_gaps} closed
                        {" · "}
                        {stats.closure_rate.toFixed(2)}% closure rate
                      </span>
                      <span className="inline-flex items-center gap-1">
                        <TrendingUp size={12} />
                        {formatCurrency(stats.recaptured_revenue)} recaptured
                      </span>
                      <span>
                        {formatCurrency(stats.at_risk_revenue)} at risk
                      </span>
                      {c.target_close_date ? (
                        <span className="inline-flex items-center gap-1">
                          <CalendarDays size={12} />
                          target {c.target_close_date}
                        </span>
                      ) : null}
                    </div>
                    <div className="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-slate-100">
                      <div
                        className="h-full bg-emerald-500 transition-all"
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                  </div>
                  <ChevronRight className="mt-1 shrink-0 text-slate-400" size={18} />
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
