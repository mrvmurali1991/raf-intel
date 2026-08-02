"use client";

/**
 * QA Review Queue — multi-rater workflow (Reveleer pattern).
 *
 * Three-column Kanban over /api/qa-reviews:
 *   1. "Awaiting secondary review" — final_outcome = pending
 *      (primary rater has rated; we need a second human to confirm)
 *   2. "Escalated"                 — final_outcome = escalated
 *      (primary and secondary disagreed → a tier-2 reviewer must adjudicate)
 *   3. "Closed (today)"            — accepted/rejected, closed today (UTC)
 *
 * Each card surfaces:
 *   - suspect / HCC label (joined from form_suspects when present)
 *   - primary rater id + their rating
 *   - rating actions appropriate to the card's column
 *     · pending   → "Confirm accept" / "Dispute (reject)" / "Unclear"
 *     · escalated → "Tier-2 accept" / "Tier-2 reject"      / "Tier-2 unclear"
 *     · closed    → read-only
 */

import React, { useMemo, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ShieldCheck,
  AlertTriangle,
  CheckCheck,
  CheckCircle2,
  XCircle,
  HelpCircle,
} from "lucide-react";

import api from "@/lib/api";
import { PageHeader } from "@/components/healthcare-ui";
import { MetricCard } from "@/components/ui/metric-card";
import { useToast } from "@/components/Toast";

// ---------------------------------------------------------------------------
// Types — mirror backend pydantic models exactly
// ---------------------------------------------------------------------------

type Rating = "accept" | "reject" | "unclear";
type Outcome = "accepted" | "rejected" | "escalated" | "pending";

interface QAReview {
  id: number;
  tenant_id: string;
  suspect_id: number | null;
  raf_patient_hcc_id: number | null;
  primary_rater_user_id: number;
  primary_rating: Rating;
  primary_note: string | null;
  secondary_rater_user_id: number | null;
  secondary_rating: Rating | null;
  secondary_note: string | null;
  tier2_rater_user_id: number | null;
  tier2_rating: Rating | null;
  tier2_note: string | null;
  final_outcome: Outcome;
  created_at: string | null;
  updated_at: string | null;
  suspect_label: string | null;
  patient_id: number | null;
  patient_name: string | null;
}

interface ListResponse {
  items: QAReview[];
  total: number;
}

// ---------------------------------------------------------------------------
// API wrappers — kept local; not promoted to lib/api.ts yet because this
// is a first-cut workflow and the surface is small.
// ---------------------------------------------------------------------------

async function fetchReviews(params: {
  outcome?: Outcome;
  closedToday?: boolean;
}): Promise<ListResponse> {
  const q = new URLSearchParams();
  if (params.outcome) q.set("outcome", params.outcome);
  if (params.closedToday) q.set("closed_today", "true");
  const res = await api.get<ListResponse>(`/api/qa-reviews?${q.toString()}`);
  return res.data;
}

async function postSecondary(reviewId: number, rating: Rating, note?: string) {
  const res = await api.put<QAReview>(`/api/qa-reviews/${reviewId}/secondary`, {
    secondary_rating: rating,
    secondary_note: note ?? null,
  });
  return res.data;
}

async function postTier2(reviewId: number, rating: Rating, note?: string) {
  const res = await api.put<QAReview>(`/api/qa-reviews/${reviewId}/tier2`, {
    tier2_rating: rating,
    tier2_note: note ?? null,
  });
  return res.data;
}

// ---------------------------------------------------------------------------
// Column config — Tailwind class-based for dark mode
// ---------------------------------------------------------------------------

const COLUMNS: {
  key: "pending" | "escalated" | "closed";
  label: string;
  accentText: string;
  badgeCls: string;
  borderCls: string;
  icon: React.ComponentType<{ size?: number; className?: string }>;
}[] = [
  {
    key: "pending",
    label: "Awaiting secondary review",
    accentText: "text-amber-600 dark:text-amber-400",
    badgeCls: "bg-amber-50 dark:bg-amber-950 text-amber-600 dark:text-amber-400",
    borderCls: "border-l-amber-600 dark:border-l-amber-400",
    icon: ShieldCheck,
  },
  {
    key: "escalated",
    label: "Escalated",
    accentText: "text-red-600 dark:text-red-400",
    badgeCls: "bg-red-50 dark:bg-red-950 text-red-600 dark:text-red-400",
    borderCls: "border-l-red-600 dark:border-l-red-400",
    icon: AlertTriangle,
  },
  {
    key: "closed",
    label: "Closed (today)",
    accentText: "text-emerald-600 dark:text-emerald-400",
    badgeCls: "bg-emerald-50 dark:bg-emerald-950 text-emerald-600 dark:text-emerald-400",
    borderCls: "border-l-emerald-600 dark:border-l-emerald-400",
    icon: CheckCheck,
  },
];

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function QAReviewPage() {
  const qc = useQueryClient();
  const toast = useToast();

  const pendingQ = useQuery({
    queryKey: ["qa-reviews", "pending"],
    queryFn: () => fetchReviews({ outcome: "pending" }),
  });
  const escalatedQ = useQuery({
    queryKey: ["qa-reviews", "escalated"],
    queryFn: () => fetchReviews({ outcome: "escalated" }),
  });
  const closedTodayQ = useQuery({
    queryKey: ["qa-reviews", "closed-today"],
    queryFn: () => fetchReviews({ closedToday: true }),
  });

  const invalidateAll = () =>
    qc.invalidateQueries({ queryKey: ["qa-reviews"] });

  const secondaryMut = useMutation({
    mutationFn: (vars: { id: number; rating: Rating }) =>
      postSecondary(vars.id, vars.rating),
    onSuccess: (row) => {
      toast.success(
        "Secondary rating recorded",
        row.final_outcome === "escalated"
          ? "Disagreement — escalated to tier-2."
          : `Closed as ${row.final_outcome}.`,
      );
      invalidateAll();
    },
    onError: (err: unknown) => {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        "Could not save secondary rating.";
      toast.error("Error", detail);
    },
  });

  const tier2Mut = useMutation({
    mutationFn: (vars: { id: number; rating: Rating }) =>
      postTier2(vars.id, vars.rating),
    onSuccess: (row) => {
      toast.success("Tier-2 decision recorded", `Closed as ${row.final_outcome}.`);
      invalidateAll();
    },
    onError: (err: unknown) => {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        "Could not save tier-2 decision.";
      toast.error("Error", detail);
    },
  });

  const counts = useMemo(
    () => ({
      pending: pendingQ.data?.total ?? 0,
      escalated: escalatedQ.data?.total ?? 0,
      closed: closedTodayQ.data?.total ?? 0,
    }),
    [pendingQ.data, escalatedQ.data, closedTodayQ.data],
  );

  return (
    <div className="max-w-[1600px] mx-auto px-4 py-6">
      <PageHeader
        title="QA Audit"
        subtitle="Multi-rater quality assurance. Each accepted suspect gets a second pair of eyes; disagreements escalate to tier-2 adjudication."
        icon={<ShieldCheck size={22} />}
      />

      {/* Metrics strip */}
      <div className="grid grid-cols-[repeat(auto-fit,minmax(180px,1fr))] gap-4 mb-6">
        <MetricCard label="Awaiting secondary" value={counts.pending} icon={<ShieldCheck size={18} />} intent="warning" />
        <MetricCard label="Escalated" value={counts.escalated} icon={<AlertTriangle size={18} />} intent="danger" />
        <MetricCard label="Closed today" value={counts.closed} icon={<CheckCheck size={18} />} intent="success" />
      </div>

      {/* Kanban */}
      <div className="w-full max-w-full overflow-x-auto" style={{ WebkitOverflowScrolling: "touch" }}>
        <div className="grid grid-cols-3 gap-3" style={{ minWidth: 840 }}>
          {COLUMNS.map((col) => {
            const dataQ =
              col.key === "pending"
                ? pendingQ
                : col.key === "escalated"
                ? escalatedQ
                : closedTodayQ;
            return (
              <Column
                key={col.key}
                label={col.label}
                accentText={col.accentText}
                badgeCls={col.badgeCls}
                borderCls={col.borderCls}
                Icon={col.icon}
                loading={dataQ.isLoading}
                items={dataQ.data?.items ?? []}
                emptyHint={emptyHintFor(col.key)}
                onSecondary={(id, rating) => secondaryMut.mutate({ id, rating })}
                onTier2={(id, rating) => tier2Mut.mutate({ id, rating })}
                actionsKind={col.key}
                disabled={secondaryMut.isPending || tier2Mut.isPending}
              />
            );
          })}
        </div>
      </div>
    </div>
  );
}

function emptyHintFor(k: "pending" | "escalated" | "closed"): string {
  if (k === "pending") return "No cases in Pending — all caught up.";
  if (k === "escalated") return "No cases in Escalated — no disagreements.";
  return "No cases in Closed (today) — nothing resolved yet today.";
}

// ---------------------------------------------------------------------------
// Column
// ---------------------------------------------------------------------------

function Column(props: {
  label: string;
  accentText: string;
  badgeCls: string;
  borderCls: string;
  Icon: React.ComponentType<{ size?: number; className?: string }>;
  loading: boolean;
  items: QAReview[];
  emptyHint: string;
  onSecondary: (id: number, rating: Rating) => void;
  onTier2: (id: number, rating: Rating) => void;
  actionsKind: "pending" | "escalated" | "closed";
  disabled: boolean;
}) {
  const { Icon } = props;
  return (
    <section
      role="region"
      aria-label={props.label}
      className="bg-slate-50 dark:bg-slate-800/50 rounded-[10px] p-2.5 min-h-[400px]"
    >
      <header className="flex items-center justify-between mb-2.5 px-1">
        <span
          className={`inline-flex items-center gap-1.5 text-xs font-bold uppercase tracking-wide ${props.accentText}`}
        >
          <Icon size={14} />
          {props.label}
        </span>
        <span
          className={`text-[11px] font-bold px-2 py-0.5 rounded-full ${props.badgeCls}`}
        >
          {props.items.length}
        </span>
      </header>

      <div className="flex flex-col gap-2">
        {props.loading && Array.from({ length: 3 }).map((_, i) => (
          <div
            key={i}
            className="h-[110px] bg-slate-100 dark:bg-slate-700 rounded-lg animate-pulse"
          />
        ))}

        {!props.loading && props.items.length === 0 && (
          <div className="text-xs text-slate-500 dark:text-slate-400 text-center p-6">
            {props.emptyHint}
          </div>
        )}

        {!props.loading && props.items.map((r) => (
          <Card
            key={r.id}
            review={r}
            borderCls={props.borderCls}
            onSecondary={(rating) => props.onSecondary(r.id, rating)}
            onTier2={(rating) => props.onTier2(r.id, rating)}
            actionsKind={props.actionsKind}
            disabled={props.disabled}
          />
        ))}
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Card
// ---------------------------------------------------------------------------

function Card(props: {
  review: QAReview;
  borderCls: string;
  onSecondary: (rating: Rating) => void;
  onTier2: (rating: Rating) => void;
  actionsKind: "pending" | "escalated" | "closed";
  disabled: boolean;
}) {
  const { review: r } = props;
  const target =
    r.suspect_label ||
    (r.suspect_id != null ? `Suspect #${r.suspect_id}` : null) ||
    (r.raf_patient_hcc_id != null ? `HCC row #${r.raf_patient_hcc_id}` : "Unknown target");

  return (
    <article
      aria-label={`QA review ${r.id}`}
      className={`bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 border-l-[3px] ${props.borderCls} rounded-lg p-2.5 shadow-[0_1px_2px_rgba(0,0,0,0.04)] dark:shadow-[0_1px_2px_rgba(0,0,0,0.2)]`}
    >
      <div className="flex justify-between items-start">
        <span className="text-[11px] text-slate-500 dark:text-slate-400 font-semibold">
          QA #{r.id}
          {r.patient_id != null ? ` · pid ${r.patient_id}` : ""}
        </span>
        <OutcomeBadge outcome={r.final_outcome} />
      </div>

      <div className="mt-1.5 text-xs text-slate-800 dark:text-slate-100 font-semibold">
        {r.patient_id != null ? (
          <a
            href={`/patients/${r.patient_id}`}
            className="text-blue-600 dark:text-blue-400 no-underline hover:underline"
            aria-label={`View patient ${r.patient_name ?? r.patient_id} — ${target}`}
          >
            {target}
          </a>
        ) : target}
      </div>
      {r.patient_name && (
        <div className="mt-0.5 text-[11px] text-slate-500 dark:text-slate-400">{r.patient_name}</div>
      )}

      <div className="mt-2 flex flex-col gap-1">
        <RaterLine label="Primary" userId={r.primary_rater_user_id} rating={r.primary_rating} />
        {r.secondary_rating && (
          <RaterLine label="Secondary" userId={r.secondary_rater_user_id} rating={r.secondary_rating} />
        )}
        {r.tier2_rating && (
          <RaterLine label="Tier-2" userId={r.tier2_rater_user_id} rating={r.tier2_rating} />
        )}
      </div>

      {props.actionsKind === "pending" && (
        <ActionRow
          disabled={props.disabled}
          ariaLabel="Record secondary rating"
          onAccept={() => props.onSecondary("accept")}
          onReject={() => props.onSecondary("reject")}
          onUnclear={() => props.onSecondary("unclear")}
          acceptLabel="Confirm accept"
          rejectLabel="Confirm reject"
          unclearLabel="Confirm escalate"
        />
      )}
      {props.actionsKind === "escalated" && (
        <ActionRow
          disabled={props.disabled}
          ariaLabel="Record tier-2 decision"
          onAccept={() => props.onTier2("accept")}
          onReject={() => props.onTier2("reject")}
          onUnclear={() => props.onTier2("unclear")}
          acceptLabel="Tier-2 accept"
          rejectLabel="Tier-2 reject"
        />
      )}
    </article>
  );
}

function RaterLine({
  label,
  userId,
  rating,
}: {
  label: string;
  userId: number | null | undefined;
  rating: Rating;
}) {
  return (
    <div className="flex justify-between items-center">
      <span className="text-[11px] text-slate-500 dark:text-slate-400">
        {label} {userId != null ? `· user ${userId}` : ""}
      </span>
      <RatingPill rating={rating} />
    </div>
  );
}

function RatingPill({ rating }: { rating: Rating }) {
  const styles: Record<Rating, string> = {
    accept: "bg-emerald-50 dark:bg-emerald-950 text-emerald-600 dark:text-emerald-400",
    reject: "bg-red-50 dark:bg-red-950 text-red-600 dark:text-red-400",
    unclear: "bg-amber-50 dark:bg-amber-950 text-amber-600 dark:text-amber-400",
  };
  const labels: Record<Rating, string> = {
    accept: "Accept",
    reject: "Reject",
    unclear: "Unclear",
  };
  return (
    <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${styles[rating]}`}>
      {labels[rating]}
    </span>
  );
}

function OutcomeBadge({ outcome }: { outcome: Outcome }) {
  const styles: Record<Outcome, string> = {
    accepted: "bg-emerald-50 dark:bg-emerald-950 text-emerald-600 dark:text-emerald-400",
    rejected: "bg-red-50 dark:bg-red-950 text-red-600 dark:text-red-400",
    escalated: "bg-red-50 dark:bg-red-950 text-red-600 dark:text-red-400",
    pending: "bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300",
  };
  return (
    <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded uppercase ${styles[outcome]}`}>
      {outcome}
    </span>
  );
}

function ActionRow(props: {
  disabled: boolean;
  ariaLabel: string;
  onAccept: () => void;
  onReject: () => void;
  onUnclear: () => void;
  acceptLabel: string;
  rejectLabel: string;
  unclearLabel?: string;
}) {
  return (
    <div
      role="group"
      aria-label={props.ariaLabel}
      className="flex gap-1.5 mt-2.5 flex-wrap"
    >
      <ActionButton
        onClick={props.onAccept}
        disabled={props.disabled}
        colorCls="bg-emerald-50 dark:bg-emerald-950 text-emerald-600 dark:text-emerald-400"
        icon={<CheckCircle2 size={12} />}
        label={props.acceptLabel}
      />
      <ActionButton
        onClick={props.onReject}
        disabled={props.disabled}
        colorCls="bg-red-50 dark:bg-red-950 text-red-600 dark:text-red-400"
        icon={<XCircle size={12} />}
        label={props.rejectLabel}
      />
      <ActionButton
        onClick={props.onUnclear}
        disabled={props.disabled}
        colorCls="bg-amber-50 dark:bg-amber-950 text-amber-600 dark:text-amber-400"
        icon={<HelpCircle size={12} />}
        label={props.unclearLabel ?? "Unclear"}
      />
    </div>
  );
}

function ActionButton(props: {
  onClick: () => void;
  disabled: boolean;
  colorCls: string;
  icon: React.ReactNode;
  label: string;
}) {
  return (
    <button
      type="button"
      onClick={props.onClick}
      disabled={props.disabled}
      className={`inline-flex items-center gap-1 border-none text-[11px] font-bold px-2 py-1 rounded cursor-pointer disabled:cursor-not-allowed disabled:opacity-50 ${props.colorCls}`}
    >
      {props.icon}
      {props.label}
    </button>
  );
}
