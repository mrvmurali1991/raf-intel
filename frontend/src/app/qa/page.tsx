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
import { PageHeader, StatCard } from "@/components/healthcare-ui";
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
// Style tokens (mirrors /suspects + /disputes palette)
// ---------------------------------------------------------------------------

const T = {
  white: "#FFFFFF",
  slate50: "#F8FAFC",
  slate100: "#F1F5F9",
  slate200: "#E2E8F0",
  slate400: "#94A3B8",
  slate500: "#64748B",
  slate600: "#475569",
  slate700: "#334155",
  slate800: "#1E293B",
  blue50: "#EFF6FF",
  blue600: "#2563EB",
  amber50: "#FFFBEB",
  amber600: "#D97706",
  emerald50: "#ECFDF5",
  emerald600: "#059669",
  red50: "#FEF2F2",
  red600: "#DC2626",
} as const;

const COLUMNS: {
  key: "pending" | "escalated" | "closed";
  label: string;
  accent: string;
  bg: string;
  icon: React.ComponentType<{ size?: number }>;
}[] = [
  { key: "pending", label: "Awaiting secondary review", accent: T.amber600, bg: T.amber50, icon: ShieldCheck },
  { key: "escalated", label: "Escalated", accent: T.red600, bg: T.red50, icon: AlertTriangle },
  { key: "closed", label: "Closed (today)", accent: T.emerald600, bg: T.emerald50, icon: CheckCheck },
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
    <div
      style={{
        maxWidth: 1600,
        margin: "0 auto",
        padding: "24px 16px",
        fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
      }}
    >
      <PageHeader
        title="QA Review Queue"
        subtitle="Multi-rater quality assurance. Each accepted suspect gets a second pair of eyes; disagreements escalate to tier-2 adjudication."
        icon={<ShieldCheck size={22} />}
      />

      {/* Metrics strip */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
          gap: 16,
          marginBottom: 24,
        }}
      >
        <StatCard label="Awaiting secondary" value={counts.pending} icon={<ShieldCheck size={18} />} color={T.amber600} />
        <StatCard label="Escalated" value={counts.escalated} icon={<AlertTriangle size={18} />} color={T.red600} />
        <StatCard label="Closed today" value={counts.closed} icon={<CheckCheck size={18} />} color={T.emerald600} />
      </div>

      {/* Kanban */}
      <div
        style={{
          width: "100%",
          maxWidth: "100%",
          overflowX: "auto",
          WebkitOverflowScrolling: "touch",
        }}
      >
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(280px, 1fr))", gap: 12 }}>
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
                accent={col.accent}
                bg={col.bg}
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
  accent: string;
  bg: string;
  Icon: React.ComponentType<{ size?: number }>;
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
      style={{
        background: T.slate50,
        borderRadius: 10,
        padding: 10,
        minHeight: 400,
      }}
    >
      <header
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: 10,
          padding: "0 4px",
        }}
      >
        <span
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
            fontSize: 12,
            fontWeight: 700,
            color: props.accent,
            textTransform: "uppercase",
            letterSpacing: 0.5,
          }}
        >
          <Icon size={14} />
          {props.label}
        </span>
        <span
          style={{
            background: props.bg,
            color: props.accent,
            fontSize: 11,
            fontWeight: 700,
            padding: "2px 8px",
            borderRadius: 999,
          }}
        >
          {props.items.length}
        </span>
      </header>

      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {props.loading && Array.from({ length: 3 }).map((_, i) => (
          <div
            key={i}
            style={{
              height: 110,
              background: T.slate100,
              borderRadius: 8,
              animation: "pulse 1.5s infinite",
            }}
          />
        ))}

        {!props.loading && props.items.length === 0 && (
          <div style={{ fontSize: 12, color: T.slate400, textAlign: "center", padding: 24 }}>
            {props.emptyHint}
          </div>
        )}

        {!props.loading && props.items.map((r) => (
          <Card
            key={r.id}
            review={r}
            accent={props.accent}
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
  accent: string;
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
      style={{
        background: T.white,
        border: `1px solid ${T.slate200}`,
        borderLeft: `3px solid ${props.accent}`,
        borderRadius: 8,
        padding: 10,
        boxShadow: "0 1px 2px rgba(0,0,0,0.04)",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "start" }}>
        <span style={{ fontSize: 11, color: T.slate500, fontWeight: 600 }}>
          QA #{r.id}
          {r.patient_id != null ? ` · pid ${r.patient_id}` : ""}
        </span>
        <OutcomeBadge outcome={r.final_outcome} />
      </div>

      <div style={{ marginTop: 6, fontSize: 12, color: T.slate800, fontWeight: 600 }}>
        {r.patient_id != null ? (
          <a
            href={`/patients/${r.patient_id}`}
            style={{ color: T.blue600, textDecoration: "none" }}
            aria-label={`View patient ${r.patient_name ?? r.patient_id} — ${target}`}
          >
            {target}
          </a>
        ) : target}
      </div>
      {r.patient_name && (
        <div style={{ marginTop: 2, fontSize: 11, color: T.slate500 }}>{r.patient_name}</div>
      )}

      <div style={{ marginTop: 8, display: "flex", flexDirection: "column", gap: 4 }}>
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
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
      <span style={{ fontSize: 11, color: T.slate500 }}>
        {label} {userId != null ? `· user ${userId}` : ""}
      </span>
      <RatingPill rating={rating} />
    </div>
  );
}

function RatingPill({ rating }: { rating: Rating }) {
  const { bg, fg, label } =
    rating === "accept"
      ? { bg: T.emerald50, fg: T.emerald600, label: "ACCEPT" }
      : rating === "reject"
      ? { bg: T.red50, fg: T.red600, label: "REJECT" }
      : { bg: T.amber50, fg: T.amber600, label: "UNCLEAR" };
  return (
    <span
      style={{
        background: bg,
        color: fg,
        fontSize: 10,
        fontWeight: 700,
        padding: "2px 6px",
        borderRadius: 4,
      }}
    >
      {label}
    </span>
  );
}

function OutcomeBadge({ outcome }: { outcome: Outcome }) {
  const { bg, fg } =
    outcome === "accepted"
      ? { bg: T.emerald50, fg: T.emerald600 }
      : outcome === "rejected"
      ? { bg: T.red50, fg: T.red600 }
      : outcome === "escalated"
      ? { bg: T.red50, fg: T.red600 }
      : { bg: T.slate100, fg: T.slate600 };
  return (
    <span
      style={{
        background: bg,
        color: fg,
        fontSize: 10,
        fontWeight: 700,
        padding: "2px 6px",
        borderRadius: 4,
        textTransform: "uppercase",
      }}
    >
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
      style={{ display: "flex", gap: 6, marginTop: 10, flexWrap: "wrap" }}
    >
      <ActionButton
        onClick={props.onAccept}
        disabled={props.disabled}
        bg={T.emerald50}
        fg={T.emerald600}
        icon={<CheckCircle2 size={12} />}
        label={props.acceptLabel}
      />
      <ActionButton
        onClick={props.onReject}
        disabled={props.disabled}
        bg={T.red50}
        fg={T.red600}
        icon={<XCircle size={12} />}
        label={props.rejectLabel}
      />
      <ActionButton
        onClick={props.onUnclear}
        disabled={props.disabled}
        bg={T.amber50}
        fg={T.amber600}
        icon={<HelpCircle size={12} />}
        label={props.unclearLabel ?? "Unclear"}
      />
    </div>
  );
}

function ActionButton(props: {
  onClick: () => void;
  disabled: boolean;
  bg: string;
  fg: string;
  icon: React.ReactNode;
  label: string;
}) {
  return (
    <button
      type="button"
      onClick={props.onClick}
      disabled={props.disabled}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        background: props.bg,
        color: props.fg,
        border: "none",
        fontSize: 11,
        fontWeight: 700,
        padding: "4px 8px",
        borderRadius: 4,
        cursor: props.disabled ? "not-allowed" : "pointer",
        opacity: props.disabled ? 0.5 : 1,
      }}
    >
      {props.icon}
      {props.label}
    </button>
  );
}
