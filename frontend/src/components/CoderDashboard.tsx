"use client";

/**
 * CoderDashboard — "My queue" view for an individual coder.
 *
 * Shows:
 *   - Open assignments across all campaigns (sorted by revenue impact)
 *   - Today's closure count
 *   - Last-7-day closure velocity sparkline (text-style for now)
 *   - Inline Close / Dismiss CTAs that mark the assignment in place
 */

import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, XCircle, RefreshCw } from "lucide-react";

import {
  getCoderDashboard,
  markRecaptureAssignment,
  type AssignmentStatus,
} from "@/lib/api";

function formatCurrency(n: number): string {
  return "$" + Math.round(n).toLocaleString("en-US");
}

interface Props {
  coderId: number;
}

export default function CoderDashboard({ coderId }: Props) {
  const qc = useQueryClient();

  const { data, isLoading, isError, refetch, isFetching } = useQuery({
    queryKey: ["coder-dashboard", coderId],
    queryFn: () => getCoderDashboard(coderId),
    staleTime: 15_000,
  });

  const markMut = useMutation({
    mutationFn: ({
      assignment_id,
      status,
    }: {
      assignment_id: number;
      status: AssignmentStatus;
    }) => markRecaptureAssignment(assignment_id, { status }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["coder-dashboard", coderId] });
      qc.invalidateQueries({ queryKey: ["recapture-kanban"] });
      qc.invalidateQueries({ queryKey: ["recapture-campaigns"] });
      window.dispatchEvent(new CustomEvent("recapture-campaigns:changed"));
    },
  });

  return (
    <section className="rounded-xl border border-slate-200 bg-white shadow-sm">
      <header className="flex items-center justify-between border-b border-slate-100 p-4">
        <div>
          <h2 className="text-lg font-semibold text-slate-900">My queue</h2>
          <p className="text-sm text-slate-500">
            Open recapture assignments across active campaigns
          </p>
        </div>
        <button
          type="button"
          onClick={() => refetch()}
          className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-slate-200 text-slate-600 hover:bg-slate-50"
          aria-label="Refresh"
        >
          <RefreshCw size={14} className={isFetching ? "animate-spin" : ""} />
        </button>
      </header>

      <div className="grid grid-cols-1 gap-4 border-b border-slate-100 p-4 sm:grid-cols-3">
        <Stat label="Today's closures" value={data?.today_closures ?? 0} />
        <Stat label="Last 7 days" value={data?.week_closures ?? 0} />
        <Stat label="Open assignments" value={data?.totals?.open ?? 0} />
      </div>

      {data?.weekly_velocity?.length ? (
        <div className="border-b border-slate-100 px-4 py-3">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            Velocity (last 7 days)
          </div>
          <div className="mt-2 flex items-end gap-1 h-12">
            {data.weekly_velocity.map((d) => {
              const max = Math.max(
                1,
                ...data.weekly_velocity.map((v) => v.closed)
              );
              const pct = (d.closed / max) * 100;
              return (
                <div
                  key={d.day}
                  className="flex flex-1 flex-col items-center justify-end"
                  title={`${d.day}: ${d.closed} closed`}
                >
                  <div
                    className="w-full rounded-t bg-emerald-500"
                    style={{ height: `${pct}%`, minHeight: 2 }}
                  />
                </div>
              );
            })}
          </div>
        </div>
      ) : null}

      {isLoading ? (
        <div className="p-8 text-center text-sm text-slate-500">Loading…</div>
      ) : isError ? (
        <div className="p-8 text-center text-sm text-rose-600">
          Failed to load coder dashboard.
        </div>
      ) : !data?.my_open_assignments?.length ? (
        <div className="p-10 text-center text-sm text-slate-500">
          No open assignments. Nice work!
        </div>
      ) : (
        <ul className="divide-y divide-slate-100">
          {data.my_open_assignments.map((a) => (
            <li
              key={a.assignment_id}
              className="flex flex-wrap items-center justify-between gap-3 p-4"
            >
              <div className="min-w-0 flex-1">
                <div className="text-sm font-semibold text-slate-900">
                  HCC {a.hcc_code} · ICD {a.icd10_code}
                </div>
                <div className="text-xs text-slate-500">
                  Patient {a.patient_id} · {a.campaign_name}
                </div>
              </div>
              <span className="text-sm font-medium text-emerald-700">
                {formatCurrency(a.revenue_impact ?? 0)}
              </span>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() =>
                    markMut.mutate({
                      assignment_id: a.assignment_id,
                      status: "closed",
                    })
                  }
                  disabled={markMut.isPending}
                  className="inline-flex items-center gap-1 rounded-md bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
                >
                  <CheckCircle2 size={14} /> Close
                </button>
                <button
                  type="button"
                  onClick={() =>
                    markMut.mutate({
                      assignment_id: a.assignment_id,
                      status: "dismissed",
                    })
                  }
                  disabled={markMut.isPending}
                  className="inline-flex items-center gap-1 rounded-md border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-50"
                >
                  <XCircle size={14} /> Dismiss
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50/60 p-3">
      <div className="text-xs font-medium uppercase tracking-wide text-slate-500">
        {label}
      </div>
      <div className="mt-1 text-2xl font-bold text-slate-900">{value}</div>
    </div>
  );
}
