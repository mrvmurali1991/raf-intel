"use client";

/**
 * CampaignKanban — 4-column kanban view for a single recapture campaign.
 *
 * Columns: assigned → in_progress → closed / dismissed.  We use a simple
 * dropdown per card to move it between columns (no DnD library required;
 * keeps the bundle slim and stays accessible by default).  After every
 * move we invalidate the kanban query so closure-rate / $-recaptured
 * always match the database.
 */

import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";

import {
  getRecaptureKanban,
  markRecaptureAssignment,
  type AssignmentCard,
  type AssignmentStatus,
} from "@/lib/api";

const COLUMN_LABELS: Record<
  "assigned" | "in_progress" | "closed" | "dismissed",
  { label: string; color: string }
> = {
  assigned:    { label: "Assigned",    color: "#1D4ED8" },
  in_progress: { label: "In progress", color: "#92400E" },
  closed:      { label: "Closed",      color: "#065F46" },
  dismissed:   { label: "Dismissed",   color: "#64748B" },
};

const NEXT_OPTIONS: AssignmentStatus[] = [
  "assigned",
  "in_progress",
  "closed",
  "dismissed",
];

function formatCurrency(n: number): string {
  return "$" + Math.round(n).toLocaleString("en-US");
}

interface Props {
  campaignId: number;
  campaignName?: string;
  onBack?: () => void;
}

export default function CampaignKanban({ campaignId, campaignName, onBack }: Props) {
  const qc = useQueryClient();

  const { data, isLoading, isError, refetch, isFetching } = useQuery({
    queryKey: ["recapture-kanban", campaignId],
    queryFn: () => getRecaptureKanban(campaignId),
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
      qc.invalidateQueries({ queryKey: ["recapture-kanban", campaignId] });
      qc.invalidateQueries({ queryKey: ["recapture-campaigns"] });
      window.dispatchEvent(new CustomEvent("recapture-campaigns:changed"));
    },
  });

  const stats = data?.stats;

  return (
    <section className="rounded-xl border border-slate-200 bg-white shadow-sm">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 p-4">
        <div>
          <div className="flex items-center gap-2">
            {onBack ? (
              <button
                type="button"
                onClick={onBack}
                className="text-sm text-blue-600 hover:underline"
              >
                ← Back to campaigns
              </button>
            ) : null}
          </div>
          <h2 className="mt-0.5 text-lg font-semibold text-slate-900">
            {campaignName ?? `Campaign #${campaignId}`}
          </h2>
          {stats ? (
            <p className="mt-1 text-sm text-slate-500">
              {stats.closed}/{stats.total_gaps} closed · {stats.closure_rate.toFixed(2)}% closure rate ·{" "}
              <span className="text-emerald-700">
                {formatCurrency(stats.recaptured_revenue)} recaptured
              </span>{" "}
              ·{" "}
              <span className="text-rose-700">
                {formatCurrency(stats.at_risk_revenue)} at risk
              </span>
            </p>
          ) : null}
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

      {isLoading ? (
        <div className="p-8 text-center text-sm text-slate-500">Loading kanban…</div>
      ) : isError ? (
        <div className="p-8 text-center text-sm text-rose-600">
          Failed to load kanban.
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 p-4 lg:grid-cols-4">
          {(Object.keys(COLUMN_LABELS) as Array<keyof typeof COLUMN_LABELS>).map((col) => {
            const cards = data?.buckets[col] ?? [];
            return (
              <div
                key={col}
                className="rounded-lg border border-slate-200 bg-slate-50/60"
              >
                <div className="flex items-center justify-between border-b border-slate-200 p-3">
                  <span
                    className="text-sm font-semibold"
                    style={{ color: COLUMN_LABELS[col].color }}
                  >
                    {COLUMN_LABELS[col].label}
                  </span>
                  <span className="rounded-full bg-white px-2 py-0.5 text-xs font-medium text-slate-600 ring-1 ring-slate-200">
                    {cards.length}
                  </span>
                </div>
                <ul className="space-y-2 p-3">
                  {cards.length === 0 ? (
                    <li className="rounded-md border border-dashed border-slate-200 bg-white p-4 text-center text-xs text-slate-400">
                      No assignments
                    </li>
                  ) : (
                    cards.map((card) => (
                      <KanbanCard
                        key={card.assignment_id}
                        card={card}
                        onMove={(status) =>
                          markMut.mutate({
                            assignment_id: card.assignment_id,
                            status,
                          })
                        }
                        disabled={markMut.isPending}
                      />
                    ))
                  )}
                </ul>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}

function KanbanCard({
  card,
  onMove,
  disabled,
}: {
  card: AssignmentCard;
  onMove: (status: AssignmentStatus) => void;
  disabled?: boolean;
}) {
  return (
    <li className="rounded-md border border-slate-200 bg-white p-3 shadow-sm">
      <div className="flex items-start justify-between">
        <div className="min-w-0">
          <div className="text-sm font-semibold text-slate-900">
            HCC {card.hcc_code}
          </div>
          <div className="text-xs text-slate-500">
            ICD {card.icd10_code} · Patient {card.patient_id}
          </div>
        </div>
        <span className="text-xs font-medium text-emerald-700">
          {formatCurrency(card.revenue_impact ?? 0)}
        </span>
      </div>
      <div className="mt-2 text-xs text-slate-500">
        {card.coder_name ?? `Coder #${card.coder_id}`}
      </div>
      <select
        className="mt-2 w-full rounded-md border border-slate-200 bg-white px-2 py-1 text-xs"
        value={card.assignment_status}
        disabled={disabled}
        onChange={(e) => onMove(e.target.value as AssignmentStatus)}
        aria-label={`Move assignment ${card.assignment_id}`}
      >
        {NEXT_OPTIONS.map((opt) => (
          <option key={opt} value={opt}>
            {opt.replace("_", " ")}
          </option>
        ))}
      </select>
    </li>
  );
}
